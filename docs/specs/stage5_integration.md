# Stage 5 — 통합: 라인트레이싱 + 노드 분기 회전 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 1(하드웨어/주행 부호 기반) · Stage 2(회전) · Stage 3(좌/중/우 3센서 추종
>       `decide_line3` + 노드 감지) 실기 Done. **라인추종층은 Stage 3 의 3센서 추종**이다
>       (Stage 1 중앙센서 단일 PID 재사용 아님 — 2026-06-30 Stage 3 변경 반영).
>       Stage 4(색 판정)는 노드 종류 기록용으로 함께 쓰되 회전 결정 자체에는 필수 아님.
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 5 인용 —
> "미리 정한 회전 시퀀스(예: 좌,직,우,U)대로 코스를 노드마다 정확히 돌아 통과."

관련 문서: 단계 통과기준 [../STAGES.md](../STAGES.md), 라이브 튜닝/안전 [../LIVE_TUNING.md](../LIVE_TUNING.md),
판단기록·재연·실패분석 [../DECISIONS.md](../DECISIONS.md), 배선 [../HARDWARE.md](../HARDWARE.md).
하위 스테이지 명세: [stage1_linetrace.md](stage1_linetrace.md) · [stage2_turns.md](stage2_turns.md) ·
[stage3_node_detect.md](stage3_node_detect.md) · [stage4_color.md](stage4_color.md).
참고 원본(검증값/구조만 인용, 복붙 금지): `/home/emjdp/dev/ev3maze/robot/run/solver.py`
(`follow_to_node` → `turn` → `_clear_junction` 흐름, `_pivot`/`PivotTracker` 라인 재포착,
`_turn_from_junction` + `pre_turn_nudge`), `config.py` 6절(nudge/clear 타이밍).

---

## 1. 목표 / 범위

- **하는 것**: 하위 스테이지를 **하나의 주행 루프로 연결**한다.
  선 추종(Stage 3 좌/중/우 `decide_line3`) → 노드 감지(Stage 3) → **미리 정한 시퀀스대로 회전**(Stage 2)
  → 회전 후 **다음 선 다시 올라타기** → 다시 선 추종 … 을 노드마다 반복.
- **하는 것**: 회전을 **라인 재포착 방식과 결합**한다. Stage 2 의 순수 회전(엔코더/보정
  계수)으로 돌되, 회전 후 중앙센서로 **선을 다시 잡았을 때** 회전을 끝낸다(원본
  `_pivot`+`PivotTracker` 흐름 인용).
- **하는 것**: 입력 시퀀스(예: `L S R U`)를 받아 노드 순서대로 소비하며 코스 통과.
  매 노드의 판단(감지·회전·색)을 reason_code 로 기록.
- **하는 것**: 통합 시 **실패 #1(분기 오버슛)·실패 #2(색 위치)** 가 다시 나오는 구간을
  명시하고 진단 경로를 둔다.
- **명시적으로 안 하는 것**:
  - 지도 없는 자율 탐색/출구 선택/U턴 분기 우선 → Stage 6(원본 `MazeSolver` 의 `explore`).
    여기서는 **외부에서 준 고정 시퀀스**만 따른다.
  - 형태 peek(1?1 십자 판별), 물체 집기 → Stage 6/7.
  - 색을 보고 **종료/U턴 같은 주행 결정** → Stage 6. 여기서는 색을 **기록만** 한다
    (노드가 막다른 길일 때 Stage 4 의 색 읽기를 호출해 `NODE_IS_*` 로깅).
  - 확정된 하위 스테이지 코드는 **수정하지 않고 재사용**(import/copy).

> 이 단계의 본질은 **연결**이다. 새 알고리즘을 만들지 않는다. 각 하위 동작은 이미
> 실기 Done 이므로, 여기서 새로 늘리는 라이브 params 는 **연결부(회전↔라인 사이) 타이밍**
> 최소한으로 제한한다(3절).

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage5_integration.py` (독립 실행, 시퀀스 인자 입력).
- 재사용(수정 금지):
  - Stage 3 `follow_to_node`(좌/중/우 `decide_line3` 추종 + 노드에서 멈춤, bits/dist_mm).
    라인추종은 Stage 3 의 3센서 판단이다(Stage 1 중앙 PID 아님 — Stage 1 은 부호/속도 기반만),
  - Stage 2 `turn(token)`/`_pivot`/`PivotTracker`(라인 재포착 회전),
  - Stage 4 `read_node_color_at_rest`/`classify_node_color`(색 기록),
  - `lib/` 인프라(params/telemetry/events/안전).

### 판단층(순수 함수)

```python
# 토큰 약속(원본 solver.py 인용): L=1 직진S=2 우R=3 U턴=4
# 시퀀스에서 이번 노드의 회전을 고른다(분기면 회전, 막다른 길이면 색 기록 후 보통 U).
decide_turn_from_sequence(arrival_kind, seq, idx, params)
    -> (token, reason_code, detail)
#   arrival_kind: "JCT" | "LEAF" (Stage 3 가 준 도착 종류)
#   seq: 미리 정한 토큰 리스트, idx: 현재 소비 위치
#   detail: {"node_index": idx, "selected": token, "rule": "FROM_SEQUENCE"}

# 회전 후 라인을 다시 잡았는지 판정 (Stage 2 PivotTracker 재사용 — 순수).
#   update(elapsed, center_bit) -> stop?  (ignore<min<timeout, require_clear)
```

### 구동층(ev3dev2)

```python
follow_to_node()            # Stage3 재사용(3센서 decide_line3 추종 + 노드 감지): 노드에서 정지, Arrival(kind,bits,dist_mm)
turn(token)                 # Stage2 재사용: 라인 재포착 회전(좌/우/U) 또는 직진 nudge(S)
clear_junction()            # 회전/통과 직후 분기 위 거짓 이벤트 방지 짧은 직진(원본 _clear_junction)
pre_turn_nudge(token)       # 회전반경 보정용 회전 직전 소량 전진(원본 pre_turn_nudge, 선택)
read_node_color_at_rest()   # Stage4 재사용: 막다른 길에서 색 기록(주행결정 X)
```

> **연결 흐름(원본 인용)**: `_clear_junction()` → `follow_to_node()` → (분기면)
> `pre_turn_nudge(token)` → `turn(token)` → 회전 안에서 라인 재포착으로 정지 →
> 다음 루프의 `_clear_junction()` 가 분기 잔상 벗어남 → 다시 `follow_to_node()`.
> 이 순서가 "다음 선에 올라타기"를 만든다([../DECISIONS.md](../DECISIONS.md) 0장 분리 구조 위에서).

## 3. 라이브 params (6개 이하)

원칙: **하위 스테이지에서 확정된 값은 그대로 재사용하고 여기서 다시 노출하지 않는다.**
(라인추종층 = Stage 3 좌/중/우 threshold + `decide_line3` follow 상수(`FOLLOW_*`, stage3 파일
상수), turn_*_factor/turn_speed=Stage2, `node_confirm_ms`/`node_debounce_ms`/`node_advance`=
Stage3, 색값=Stage4 — 전부 config/ 또는 stage3 상수로 묻음. Stage 1 kp/kd 중앙 PID 는 라인추종에
쓰지 않으므로 여기서 노출/재보정 대상이 아니다.)
새로 노출하는 건 **연결부 타이밍**뿐:

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `clear_junction_ms` | 회전/통과 후 분기 잔상 벗어나려 직진하는 시간 | 180 | (0,600) | 20 | 회전 후 같은 분기를 또 잡음 → ↑. 다음 분기를 지나침 → ↓ |
| `straight_nudge_ms` | 직진(S) 토큰: 분기 지나 다음 라인 올라타기 전진 시간 | 220 | (0,800) | 20 | 분기 다 못 지나 다음 선 못 탐 → ↑. 너무 멀리 감 → ↓ |
| `pre_turn_forward_ms` | 좌/우 회전 직전 회전반경 보정 전진 시간 | 75 | (0,400) | 10 | 너무 일찍 돌아 이전 선 다시 잡음 → ↑. 과전진 → ↓ |

> 셋 다 원본 `config.py` 6절의 `CLEAR_JUNCTION_SECONDS`/`STRAIGHT_NUDGE_SECONDS`/
> `PRE_*_TURN_FORWARD_SECONDS` 를 ms 단위 라이브 param 으로 인용한 것이다(값은 검증된
> 출발점, 실기 재보정 필요). **3개로 시작**하고 모자랄 때만 늘린다(6개 한도).

### config/ 에 묻는 값 (필요시 라이브 승격)

`pre_uturn_forward_ms`(보통 0), 회전별 `post_turn_settle_ms`/`post_turn_sensor_settle_ms`
(Stage 2 확정), `loop_delay`. 라인 재포착 회전의 `ignore/min/timeout/require_clear` 는
Stage 2 값을 그대로 쓴다.

## 4. telemetry 필드 / reason_code

### telemetry 추가 키

| 키 | 의미 |
|---|---|
| `node_index` | 시퀀스에서 지금까지 소비한 노드 수 |
| `last_token` | 직전 노드에서 실행한 회전 토큰(L/S/R/U) |
| `seq_remaining` | 남은 시퀀스 길이 |

(하위 telemetry: `reflect`/`error`/`turn`(Stage1), `bits`/`dist_mm`(Stage3),
`color`/`color_reflect`(Stage4)는 그대로 흘려보낸다.)

### reason_code (events) — [../DECISIONS.md](../DECISIONS.md) 카탈로그와 일치

새 reason_code 는 거의 없다(통합은 하위 것을 그대로 씀). 회전 이유에 시퀀스 규칙을 남긴다.

| reason_code | 언제 | detail |
|---|---|---|
| `NODE_CONFIRMED` | (Stage3) 노드 확정 | `bits`, `duration_ms`, `dist_mm` |
| `TURN_LEFT`/`TURN_RIGHT`/`UTURN` | 시퀀스대로 회전 시작 | `node_id`, `selected`, `rule:"FROM_SEQUENCE"` |
| `COLOR_READ` / `NODE_IS_*` | (Stage4) 막다른 길에서 색 기록 | `color`, `reflect`, `dist_since_node_mm` |
| `LINE_RECOVER` | 회전 후 라인 재포착해 회전 종료 | `lost_ms` |
| `SEQUENCE_DONE` | 시퀀스를 다 소비(코스 통과) | `node_index` |
| `SEQUENCE_EXHAUSTED` | 노드를 더 만났는데 시퀀스가 비어 멈춤 | `node_index` |

> 매 노드마다 "왜 그 회전?"이 `rule:"FROM_SEQUENCE"` + `selected` 로 남는다 →
> 실패 시 "감지가 틀렸나 / 회전이 틀렸나 / 시퀀스가 틀렸나"를 로그로 가른다.

## 5. 동작 로직 (의사코드)

> EV3(브릭) 코드는 **Python 3.5 안전**: f-string 금지, `.format()`. 네트워크 비차단
> (snapshot) · 네트워크 stop 처리는 인프라([00_infra_dashboard.md](00_infra_dashboard.md)).

### 판단층 (순수)

```python
LEFT, STRAIGHT, RIGHT, UTURN = 1, 2, 3, 4
TOKEN_REASON = {LEFT: "TURN_LEFT", RIGHT: "TURN_RIGHT",
                UTURN: "UTURN", STRAIGHT: "NODE_STRAIGHT"}

def decide_turn_from_sequence(arrival_kind, seq, idx, params):
    if idx >= len(seq):
        return (None, "SEQUENCE_EXHAUSTED", {"node_index": idx})
    token = seq[idx]
    reason = TOKEN_REASON[token]
    return (token, reason,
            {"node_id": idx, "selected": token, "rule": "FROM_SEQUENCE"})
```

### 진입점 — 통합 주행 루프

```python
def stage5_run(seq, params, hw, telem, events):
    idx = 0
    while True:
        if stop_requested(): stop(); return
        clear_junction(params["clear_junction_ms"])      # 직전 회전 잔상 벗어남
        arr = follow_to_node()    # Stage3: 3센서 decide_line3 추종 + 노드 감지로 노드에서 멈춤
                                  # arr: kind("JCT"/"LEAF"), bits, dist_mm
        # NODE_CONFIRMED 는 Stage3 가 이미 로깅(bits,duration_ms,dist_mm)

        # ---- 막다른 길이면 색 기록(주행 결정은 안 함; Stage6 가 결정) ----
        if arr.kind == "LEAF":
            color, reflect = read_node_color_at_rest(hw, params)   # Stage4
            # COLOR_READ + COLOR_FLOOR_WARN + NODE_IS_* 는 Stage4 가 로깅

        # ---- 시퀀스에서 이번 회전 결정(판단층) ----
        token, reason, detail = decide_turn_from_sequence(arr.kind, seq, idx, params)
        if token is None:
            events.log("SEQUENCE_EXHAUSTED", detail); stop(); return
        events.log(reason, detail)         # TURN_* with rule=FROM_SEQUENCE

        # ---- 회전(라인 재포착 결합) ----
        if token in (LEFT, RIGHT, UTURN):
            pre_turn_nudge(token, params["pre_turn_forward_ms"])  # 회전반경 보정(좌/우)
            turn(token)        # Stage2: 순수 회전 + 회전 안에서 중앙센서로 라인 재포착 정지
                               # 재포착 시 LINE_RECOVER 로깅
        else:  # STRAIGHT: 회전 아님 — 분기 지나 다음 라인 올라타기 nudge
            straight_nudge(params["straight_nudge_ms"])

        idx += 1
        telem.set(node_index=idx, last_token=token, seq_remaining=len(seq)-idx)
        if idx >= len(seq):
            events.log("SEQUENCE_DONE", {"node_index": idx})
            finish(); return
```

### 회전 후 "다음 선 올라타기" (라인 재포착, 원본 _pivot 인용)

```python
# turn(token) 내부(Stage2 재사용). 통합에서 새로 만들지 않고 그대로 호출.
#   (1) IGNORE 동안 센서 무시(출발 선 잔상)
#   (2) MIN 전엔 잡아도 정지 안 함(과소회전 방지 = 엔코더 각도 대용)
#   (3) require_clear: 선을 한 번 벗어났다 다시 잡을 때만 정지(센서 다닥 붙음 대비, U턴 필수)
#   (4) 중앙센서가 선 재포착 → 정지 + POST_TURN settle → LINE_RECOVER 로깅
# 그다음 루프 머리의 clear_junction() 이 분기 위 잔상에서 벗어나 다음 follow_to_node 로.
```

## 6. 대시보드 / CLI 연동

인프라 구조는 [00_infra_dashboard.md](00_infra_dashboard.md).

- 실행: `python3 stages/stage5_integration.py --seq "L S R U"` (시퀀스 인자).
- `do corner` — **노드감지 → (nudge) → 회전 → 라인 재포착** 1세트만 재현(실패 #1 보정 핵심).
- `do turn_left`/`turn_right`/`uturn` — Stage2 회전 1회(연결 전 회전만 점검).
- `do read_color` — 현재 위치 색+ reflect(막다른 길 색 기록 점검, Stage4).
- `do nudge <ms>` — 분기 후 전진량 감 잡기.
- 조정 키(라이브 set): `clear_junction_ms`, `straight_nudge_ms`, `pre_turn_forward_ms`.
  하위 값(kp/turn_factor/node_advance/색)은 **각 하위 스테이지에서 이미 확정** — 통합에선
  건드리지 않는다(필요하면 그 스테이지로 돌아가 보정).
- `Space` 일시정지/재개(pause) — 인프라 공통([00_infra_dashboard.md](00_infra_dashboard.md)).
  `follow_to_node`·`turn`·`nudge`(Stage 2~3 구동) 모두 pause 중 속도 0 유지 후 **같은 목표를
  이어간다**(중간에 시퀀스/회전 목표를 버리지 않음). 완전 정지는 `s`(stop).
- 에이전트는 제안만([../LIVE_TUNING.md](../LIVE_TUNING.md) 워크플로우).

## 7. 보정 절차 (실기, 한 번에 변수 하나)

> 전제: Stage 1~4 가 **각각** 실기 Done. 통합에서 새로 맞추는 건 연결부뿐.

1. **회전 단독 확인**: `do turn_left`/`right`/`uturn` 로 각 회전이 라인 재포착으로 잘
   끝나는지(과소/과다회전 없는지) 본다. 틀리면 Stage 2 로 돌아간다(여기서 안 고침).
2. **한 코너 재현**: `do corner` 로 감지→회전→재포착 1세트. 회전 후 **다음 선에 올라타는지**
   확인. 못 올라타면:
   - 너무 일찍 돌아 이전 선을 다시 잡음 → `pre_turn_forward_ms` ↑.
   - 회전 후 같은 분기를 또 잡음 → `clear_junction_ms` ↑.
3. **직진 노드(S) 통과**: 십자/T 를 직진으로 지날 때 다음 라인에 올라타는지.
   못 지나면 `straight_nudge_ms` ↑, 너무 멀리 가면 ↓.
4. **시퀀스 전체**: `--seq` 로 코스 한 바퀴. reason 로그로 매 노드 `selected` 가 코스와
   맞는지 본다. 한 노드만 틀리면 그 노드 구간의 연결 param 하나만 만진다.

> 한 번에 한 값. 바꾼 값·결과를 [../../PROGRESS.md](../../PROGRESS.md) 에 기록.

## 8. 실패 모드 & 진단

### 실패 #1 — 분기/코너 오버슛 → 다음 라인에 못 올라탐 (통합에서 재발 지점)

- **언제 재발**: 노드 감지 후 회전까지의 전진량(연결부)이 통합 속도/관성에서 누적될 때.
- **로그로 잡는 법**: `NODE_CONFIRMED.dist_mm`(노드 얼마나 들어가 확정했나) + 그 뒤
  회전 전 `pre_turn_forward_ms`/`straight_nudge_ms`. `dist_mm` 가 크면 advance 과다.
- **고치는 법(우선순위)**:
  1. 감지 자체가 늦으면 → Stage 3 `node_advance`(config 값) 로 돌아가 줄인다.
  2. 회전 직전 전진이 과하면 → `pre_turn_forward_ms` ↓.
  3. 회전 후 분기 재감지면 → `clear_junction_ms` ↑.
  - `do corner` + `replay.py`(감지 타이밍은 재연됨, 회전 물리는 실기)로 방향 잡고 확정
    ([../DECISIONS.md](../DECISIONS.md) 5장: 판단은 재연, 구동은 `do`).

### 실패 #2 — 노드 지나 빈 바닥 색 측정 (막다른 길 색 기록 시 재발)

- **언제 재발**: 통합 주행 관성으로 막다른 길을 지나 멈춘 뒤 색을 읽을 때.
- **로그로 잡는 법**: `COLOR_READ.reflect` 가 흰 바닥 수준 + `COLOR_FLOOR_WARN` 자동 경고
  + `dist_since_node_mm` 큼.
- **고치는 법**: Stage 4 와 동일 — 색은 **노드 확정 즉시(at_node)** 읽기 유지, 그래도
  크면 Stage 3 `node_advance` ↓. 색값은 안 만진다([stage4_color.md](stage4_color.md) 8절).

### 시퀀스/감지 불일치

- **증상**: 코스는 맞게 도는데 한 노드에서 엉뚱하게 돔.
- **로그로 잡는 법**: 그 노드의 `NODE_CONFIRMED.bits` 와 `TURN_*.selected` 를 비교 —
  bits 가 코스 모양과 다르면 **감지(Stage3)** 문제, bits 는 맞는데 selected 가 다르면
  **시퀀스 입력** 문제. 통합 param 을 만지기 전에 어느 층 문제인지부터 가른다.

### 라인 재포착 실패(회전 타임아웃)

- **증상**: 회전 후 선을 못 잡아 타임아웃.
- **고치는 법**: Stage 2 의 `min`/`require_clear`/`timeout` 문제 → Stage 2 로 복귀.
  통합에서 새로 만들지 않는다.

## 9. PC 검증

- `python3 -m py_compile stages/stage5_integration.py`.
- **판단 함수 단위 테스트**:
  - `decide_turn_from_sequence("JCT", [1,2,3,4], 0, p)` → `(1,"TURN_LEFT",...)`.
  - idx 가 len(seq) 이상 → `(None,"SEQUENCE_EXHAUSTED",...)`.
  - 시퀀스 소비가 idx 증가로만 진행되는지(노드당 1 소비).
- **replay**: 기록한 `samples.jsonl`(reflect/bits 시퀀스)을 통합 판단층에 흘려,
  노드 감지 타이밍 + 매 노드 `selected` 가 시퀀스와 맞물리는지 로봇 없이 확인.
  회전 각도/관성은 재연 불가 → 실기 `do corner` 로 확정(5장).
- (선택) 가짜 io(원본 `tests/sim_maze.py` 구조 인용)로 `stage5_run` 에 bits 시퀀스를
  먹여 시퀀스 소비/이벤트 순서만 검증.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] 하위 스테이지 함수 import/재사용 경로 확정(수정 금지): follow_to_node(Stage3 의
      3센서 `decide_line3` 추종 + 노드 감지), turn/_pivot/PivotTracker(2),
      read_node_color_at_rest/classify(4). 라인추종에 Stage 1 중앙 PID(`decide_line`) 안 씀.
- [ ] 판단층 `decide_turn_from_sequence`(순수) 작성 + 단위테스트.
- [ ] `stages/stage5_integration.py`: `--seq` 입력 파싱 + 통합 루프(5절).
- [ ] 연결부 동작: `clear_junction`/`straight_nudge`/`pre_turn_nudge` (원본 타이밍 인용).
- [ ] 라이브 params 3개(`clear_junction_ms`,`straight_nudge_ms`,`pre_turn_forward_ms`)
      + PARAM_LIMITS + MAX_STEP. 하위 값은 config/ 재사용(노출 금지).
- [ ] telemetry(`node_index`,`last_token`,`seq_remaining`) + reason_code
      (`SEQUENCE_DONE`/`SEQUENCE_EXHAUSTED`/`TURN_*` with rule).
- [ ] `do corner` 트리거(감지→nudge→회전→재포착 1세트) 연결.
- [ ] 네트워크 stop·네트워크 비차단 확인.
- [ ] `py_compile` + 단위테스트 + replay 시나리오 통과.
- [ ] 7절 보정으로 실기 Done(시퀀스대로 코스 통과), [../../PROGRESS.md](../../PROGRESS.md) 기록.

## 11. 미해결 / 실기 확인 필요

> **검토 반영 메모 (2026-07-02, Stage 3 v2 채택 전파 — 가장 크게 영향받음).** 공식 Stage 3
> 구현체가 `lib/nodes.py:decide_line3`(및 그 기반이던 아날로그 centroid 설계)에서
> **`stages/stage3v2_linetrace_branch.py`로 교체**됐고, 그 아날로그 설계는 폐기됐다
> ([PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그). 아래 2026-06-30 메모의 `decide_line3`
> 재사용 지시는 **stale** — 재사용 대상은 `black_bits`/`branch_side`/`pd_step`. **더 중요한
> 변화**: v2 Stage 3 는 이미 "분기 감지 → 정지 → 전진 → 탱크 회전(`lib/turns.pivot`) →
> 재포착"을 자체적으로 한다(감지된 쪽으로 자동 회전). 즉 이 Stage 5 문서의 핵심 범위였던
> "선 추종+노드감지+회전 통합"의 상당 부분을 Stage 3 가 이미 수행한다. Stage 5 착수 시 남는
> 차별점은 ① **미리 정한/입력받은 방향 시퀀스**대로 도는 것(v2 는 "보이는 분기 쪽" 고정)
> ② **노드 종류(T자/십자/막다른 길) 구분**(v2 는 좌/우 분기만 본다) — 이 문서를 처음부터 다시
> 설계할지, v2 위에 시퀀스/종류판별만 얹을지는 착수 시 결정([STAGES.md](../STAGES.md) Stage 5
> 메모 참조).

> **검토 반영 메모 (2026-06-30, Stage 3 변경 전파, ⚠️ 위 2026-07-02 메모로 대체됨 — 참고용 보존).**
> Stage 3 라인추종이 중앙센서 단일
> PID(`decide_line`)에서 **좌/중/우 3센서(`lib/nodes.py:decide_line3`)**로 확정되었다. Stage 5
> 의 `follow_to_node` 는 이 3센서 추종을 재사용한다 — 통합에서 라인추종 거동(`FOLLOW_GAIN`
> 등)을 다시 만지려면 **Stage 3 파일 상수**로 돌아가 보정한다(라이브 param 아님). 회전 후
> "다음 선 재포착"은 여전히 **중앙센서 비트**(3센서 read 의 `bits[1]`)로 판정하며 Stage 2
> `PivotTracker` 흐름 그대로다 — 3센서화로 인한 변경은 없다. 통합 시 3센서 추종 거동이 회전
> 직전/직후 연결부 타이밍(`pre_turn_forward_ms`/`clear_junction_ms`)과 맞물리는지는 실기 확인.

> **검토 반영 메모 (antigravity #6) — LEAF 도달 시 U턴 강제.** 아래 "막다른 길 시퀀스 토큰"
> 미정 항목의 권장 해법: 판단층(`decide_turn_from_sequence`)에서 `arrival_kind == "LEAF"` 면
> 시퀀스 토큰과 무관하게 강제로 `UTURN` 하고 `LEAF_FORCE_UTURN` 을 남긴다(시퀀스 작성
> 실수로 벽 충돌·미로 갇힘 방지). 싸고 안전 — Stage 5 구현 시 반영.

- **연결부 param 3개로 충분한지 미검증.** 통합 속도에서 `clear_junction`/`nudge`/
  `pre_turn` 만으로 다음 라인 올라타기가 안정적인지, 회전 후 별도 settle 가 더 필요한지
  실기 확인. 모자라면 6개 한도 안에서 신중히 추가.
- **막다른 길에서 색 읽기 → 그다음 동작.** Stage 5 는 색을 기록만 하고 시퀀스대로
  (보통 U) 회전한다. 막다른 길에서 시퀀스에 U 가 아닌 토큰이 오면 어떻게 할지(에러? 강제 U?)
  미정 — 시퀀스 작성 규약과 함께 실기 전 확정 필요.
- **속도 의존성.** Stage 1~4 를 낮은 속도로 따로 Done 했어도, 통합 연속 주행에서 관성이
  누적돼 실패 #1/#2 가 재발할 수 있음. `base_speed`(Stage1 값)를 통합에서 낮춰 시작할지
  실기 판단 필요(낮추면 그 자체로 한 변수 변경 — 기록).
- **`pre_uturn_forward_ms`.** 원본은 0. U턴 직전 전진이 필요한 코스가 있는지 미확인 →
  필요하면 config 에서 라이브로 승격.
- **시퀀스 길이 vs 실제 노드 수 불일치 처리.** `SEQUENCE_EXHAUSTED`(노드 더 만남)와
  `SEQUENCE_DONE`(시퀀스 끝) 중 어느 게 정상 종료인지는 코스/시퀀스 작성에 의존 — 실기 확인.
