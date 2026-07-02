# 판단 기록 + 재연 (Decision logging & Replay)

로봇이 **왜 그 행동을 했는지** 안 보이면 감으로 디버깅하게 되고, 좌회전 하나에 1시간이
날아간다. 이 문서는 그걸 없애는 3가지 — **판단 기록 / 빠른 보정 루프 / 재연** — 을 정의한다.

## 0. 핵심 구조: 판단층 ↔ 구동층 분리

```
판단층 (pure, 하드웨어 없음)        구동층 (ev3dev2)
  decide(sensors, params, state)      모터/센서 실제 동작
   → (action, reason_code, detail)    (회전/전진/색읽기)
```

- **판단층은 순수 함수**다: 입력(센서값·params·현재 상태) → 출력(행동 + reason). import 만으로
  PC에서 테스트·재연 가능. ev3dev2 를 건드리지 않는다.
- **구동층**만 ev3dev2 에 의존한다.
- 이렇게 나눠야 ① **판단 버그와 구동 버그를 분리**해 잡고, ② 기록한 센서로 **재연**이 된다.
  (오늘의 실패 분석: #1 분기 오버슛 = 구동/타이밍, #2 빈 바닥 색 측정 = 판단 위치. 둘 다
  "언제·어디서 행동했나"를 로그가 잡아줘야 고친다.)

## 1. 판단 기록 (reason logging) — PID 만큼 중요

모든 **상태 전이/행동 결정**에 `reason_code` 를 붙여 `events.jsonl` 에 남긴다.
대시보드/사람/에이전트가 "왜?"를 바로 읽는다.

### reason_code 가 붙는 판단들 (시작 카탈로그)

| reason_code | 언제 | 같이 남기는 detail |
|---|---|---|
| `LINE_FOLLOW` | 라인추종 중(throttle) | reflect, bits, error, turn |
| `BRANCH_STOP` | **Stage 3 v3(DRAFT)**: `110`/`011` 분기 후보를 보고 라인트레이싱을 끊고 즉시 정지 | bits, side, reflect, stop_settle_ms |
| `BRANCH_CANCEL` | **Stage 3 v3(DRAFT)**: 정지 후 재확인에서 같은 분기가 아니어서 자동 회전을 취소 | initial_bits, stationary_bits, reflect |
| `BRANCH_LEFT` / `BRANCH_RIGHT` | **Stage 3(공식, bits 트랙)**: 좌/우 분기 확정(탱크 회전 트리거 전) | bits, branch_seen 또는 stationary_seen, advance_mm, reflect |
| `TURN_LEFT` / `TURN_RIGHT` / `UTURN` | 회전 시작 + **이유**(Stage 2 재사용, Stage 3 분기 회전도 이 코드 경유) | target_deg, factor, turn_speed, enc_avg, error_deg (Stage 5 부터는 node_id/available_exits/selected/rule 도 추가) |
| `COLOR_READ` | 노드 색 읽음 | color, reflect(바닥/노드 구분), dist_since_node_mm |
| `NODE_IS_GOAL` / `_CHECKPOINT` / `_START` | 색으로 노드 종류 확정 | color |
| `LINE_LOST` / `LINE_RECOVER` | 선 유실/복구 | reflect |
| `PAUSE` / `RESUME` | 대시보드/robotctl 일시정지 토글 | source |
| `EMERGENCY_STOP` | 네트워크 stop 또는 watchdog 안전정지 | source |

> **(2026-07-02) 공식 Stage 3 는 bits 트랙(`stages/stage3v2_linetrace_branch.py`)이다.** 좌/중/우
> 3센서 raw 차 기반 PD 로 추종하고, 분기 확정은 `total`/시간 지속이 아니라 **연속 확정 횟수
> (`branch_confirm_count`) + 확정 후 전진거리(`branch_advance_mm`)** 로 갈린다. 이전에 검토했던
> 아날로그 centroid(`pos`/`total`) 설계와 그 전용 reason_code `NODE_CANDIDATE`/`NODE_CONFIRMED`/
> `CORNER_LEFT`/`CORNER_RIGHT`/`CALIBRATE` 는 **그 설계와 함께 폐기**됐다(코드 미착수 상태였음,
> [specs/stage3_node_detect.md](specs/stage3_node_detect.md) 참조 — 과거 실측 로그에 남아있을
> 수 있어 해석용으로만 이름을 남긴다). 새 로그에는 등장하지 않는다.

> 새 판단을 추가할 때마다 이 표에 reason_code 를 1줄 추가한다. 카탈로그가 곧 "로봇이 할 수
> 있는 판단의 전체 목록"이다.

### events.jsonl 예시 (사람이 읽기 쉽게 풀면 아래 주석처럼)
```jsonl
{"t_ms":13120,"event":"NODE_CANDIDATE","reason":"BITS_110_FOR_80MS","bits":"110","reflect":12,"duration_ms":80}
{"t_ms":13260,"event":"NODE_CONFIRMED","reason":"BITS_STABLE_AND_DEBOUNCE_OK","bits":"110","duration_ms":140,"dist_mm":18}
{"t_ms":13430,"event":"TURN_LEFT","reason":"CORNER_110_LEFT_ONLY_EXIT","node_id":3,"available":["LEFT"]}
{"t_ms":14980,"event":"COLOR_READ","reason":"READ_AT_NODE_BEFORE_ADVANCE","color":5,"reflect":11,"dist_since_node_mm":4}
{"t_ms":15010,"event":"NODE_IS_GOAL","reason":"COLOR_5_RED","color":5}
```
```
# 13.26s NODE_CONFIRMED  bits=110 stable 140ms, 노드 진입 18mm
# 13.43s TURN_LEFT       110 코너, 출구 LEFT 뿐 → 좌회전
# 14.98s COLOR_READ      색=5(빨강) reflect=11(노드 위, 바닥 아님) 노드후 4mm
# 15.01s NODE_IS_GOAL    빨강 → 도착 노드
```

## 2. 오늘의 두 실패를 로그로 잡는 법

### 실패 #1 — 분기/코너에서 너무 가서 회전 → 다음 라인에 못 올라탐
- 로그가 보여줄 것: `NODE_CONFIRMED` 의 `dist_mm`(노드 얼마나 들어가 확정했나) + 그 뒤
  `TURN_*` 시작 전 advance 량.
- 진단: advance(노드 확정 후 회전 전 전진)가 너무 큼 → **`node_advance` 한 값만** 내린다.
  `robotctl set node_advance ...` 후 `robotctl do replay` 또는 실기 `do corner` 로 검증.

### 실패 #2 — 노드 도착 후 더 가서 빈 바닥 색을 측정
- 로그가 보여줄 것: `COLOR_READ` 의 `reflect`(흰 바닥이면 높음) + `dist_since_node_mm`.
- 진단: 색을 **노드 확정 즉시(이동 전)** 읽거나 advance 를 줄인다. 그리고 색 읽을 때
  `reflect` 가 흰 바닥 수준이면 **"바닥 읽음" 경고**를 reason 에 남겨 자동으로 잡아낸다.

> 둘 다 본질은 "행동한 위치"가 틀린 것. 로그에 `dist_mm`/`reflect` 를 함께 남기면 *어느 값이
> 범인인지* 즉시 보인다 — 더 이상 감으로 안 만진다.

## 3. 빠른 보정 루프 (1시간 → 1분): 단일 동작 원격 트리거

회전 하나 맞추려고 매번 코드 고쳐 재배포하지 않는다. 노트북에서 **동작 하나를 즉시 트리거**
하고, 결과 보고 **값 하나** 고치고, 다시 트리거한다.

```bash
python tools/robotctl.py do turn_left      # 좌90 1회 실행
python tools/robotctl.py set turn_90_factor 1.05
python tools/robotctl.py do turn_left      # 다시 실행해 확인
python tools/robotctl.py do read_color     # 현재 위치 색 + reflect 출력
python tools/robotctl.py do corner         # 노드감지→advance→회전 1세트 재현
python tools/robotctl.py do nudge 120      # 120ms 전진(분기 후 전진량 감)
```

- `do <action>` 는 **그 동작 1회만** 실행하고 reason 로그를 남긴다(재배포 0).
- 보정 대상이 명확한 단계(Stage 2 회전, Stage 4 색)는 이 루프가 주 작업 방식이 된다.

## 4. 기록 (record)

주행/보정 중 EV3 는 소켓으로 흘려보내고 **노트북이** `runs/<timestamp>/` 에 저장:

- `samples.jsonl` — 제어 틱마다: `t_ms`, reflect(L/C/R raw), encoder(L/R), `param_rev`.
- `events.jsonl` — 위 판단 로그.
- `params.json` — 값 변경 타임라인(언제 무엇을 바꿨나).

(EV3 SD 에 매 틱 쓰지 않는다 — LIVE_TUNING.md 기술결정 4.)

## 5. 재연 (replay) — 노트북, 로봇 없이

```bash
python tools/replay.py runs/2026-06-29T14-03 --set node_confirm_ms=100 node_advance=8
```

- 기록한 `samples.jsonl` 을 **같은 판단층 함수**에 다시 흘려, 새 params 로 어떤 `events`(판단)가
  나오는지 출력한다. 로봇·코스 없이 즉시.
- **잘 재연되는 것**: 노드 감지 타이밍, 코너/분기 패턴 확정, 색 판정, 라인 유실 판단 — 즉
  *센서→판단* 부분 전부.
- **부분만 재연**: 물리가 섞인 것(회전 각도, 관성으로 밀린 거리). 이건 실기 `do` 루프로 잡는다.
- 그래서 판단 버그(#2 색, 노드 타이밍)는 **재연으로**, 구동 버그(#1 오버슛 일부)는 **재연으로
  방향 잡고 실기 `do` 로 확정**.

## 6. 값이 너무 많다 — 줄이는 원칙

- **한 화면(한 단계) 라이브 params 6개 이하.** 그 단계가 실제로 만지는 것만 노출한다.
- 나머지는 검증된 기본값으로 `config/` 에 묻어 둔다(보이지 않게).
- **감으로 만지지 말고 reason 로그가 짚는 값만** 만진다. 로그에 `dist_mm` 가 크면 advance,
  `reflect` 가 높은데 색을 읽었으면 색읽기 위치 — 범인이 로그에 있다.
