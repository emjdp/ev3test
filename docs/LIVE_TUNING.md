# 라이브 튜닝 구조 — EV3는 주행, 노트북은 관제소

`scp → 실행 → 실패 → 수정`을 반복하는 대신, **EV3에서 주행 코드가 도는 동안
노트북에서 파라미터(kp/kd/속도/threshold 등)를 실시간으로 바꾸고 telemetry를 보며
튜닝**한다. 현실값(조명·배터리·바닥·속도)이 계속 변하므로 이 피드백 루프가 핵심이다.

> **이건 "스테이지"가 아니라 "공용 도구(infra)"다.** 단계와 함께 *최소한으로* 등장해서
> *단계마다 조금씩* 자란다. 라인트레이싱(Stage 1)이 실기에서 되기도 전에 대시보드·자동
> 튜닝까지 다 지으면, 이전 프로젝트가 망한 방식(다 만들어놓고 눈감고 튜닝)을 그대로
> 반복하는 것이다. **절대 금지.**

> **우선순위 주의:** 무거운 웹 대시보드(Streamlit·실시간 그래프 등)는 *나중*이다. 먼저
> 필요한 건 ① 단일 동작 원격 트리거(`do`)로 빠른 보정 루프, ② 판단 기록(reason logging),
> ③ 재연(replay). 이 셋은 [DECISIONS.md](DECISIONS.md) 에 정의했다.

> **사람이 쓰는 인터페이스 = 터미널 TUI 대시보드(`tools/dashboard.py`).** 매번 명령을
> 타이핑하지 않고 **키 한 번으로 동작 실행 + 키로 파라미터 즉석 조정**한다. stdlib `curses`
> 로 노트북에서 실행(추가 설치 없음). 같은 튜닝 서버에 붙는 `robotctl.py` 는 스크립트·
> 에이전트용 비대화형 CLI 로 병행 유지한다. 둘 다 SSH 터널 위에서 동작.

## 전체 그림

```
EV3 (브릭)                          노트북 (관제소)
  stages/stageN_*.py                  tools/robotctl.py     (get/set/stop CLI)
    제어 루프(주행)                    tools/telemetry_watcher.py
    + tuning_server thread   <──SSH──>   runs/current/
      (params 변경/telemetry)   터널        telemetry.jsonl
                                            latest_state.json
                                            params.json
                                          ↑ Claude/Codex/Antigravity 가 읽고 제안
```

SSH 포트포워딩으로 노트북 `localhost:8765` → EV3 `127.0.0.1:8765` 에 붙는다.
튜닝 포트를 외부에 노출하지 않아 안전하다.

```bash
ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local
```

## 절대 규칙: 제어 루프는 네트워크를 기다리지 않는다

```
제어 루프 (EV3 내부, 독립적으로 계속 돈다)
  센서 읽기 → params snapshot 읽기 → PID 계산 → 모터 출력 → telemetry 갱신 → sleep

네트워크 thread (별도)
  노트북 명령 수신 → params 업데이트 / 최신 telemetry 전송
```

네트워크가 끊겨도 로봇은 **마지막 안전값으로 계속 주행하거나 안전 정지**한다.
네트워크 I/O가 제어 루프를 단 한 순간도 블록해선 안 된다(snapshot 패턴으로 분리).

## 기술 결정 (검토에서 확정)

1. **EV3 Python 버전부터 확인.** `ev3dev-stretch`면 Python 3.5 → f-string(3.6+) 불가.
   브릭에서 도는 코드(`lib/`, `stages/`)는 **3.5 안전**하게(`.format()`). 노트북 `tools/`는
   최신 문법 OK. Stage 0에서 `python3 --version`으로 확정한다.
2. **서버 동시성: 연결당 thread.** 단일 `listen(1)`+blocking accept면 telemetry 스트림이
   연결을 잡은 동안 `set` 명령이 안 받힌다. 연결마다 핸들러 thread를 띄운다(threaded accept).
   (또는 telemetry를 push 말고 watcher가 polling 하는 pull 모델. 기본은 threaded accept.)
3. **PID `dt`는 측정값.** `sleep(0.01)`을 dt로 가정하지 말고 실제 경과시간을 재서 쓴다.
   EV3 루프는 0.01초를 못 지킨다(센서모드 전환·로깅에서 튐).
4. **telemetry 파일쓰기는 노트북에서.** EV3 SD카드에 매 루프 JSONL 쓰기 금지(느림·수명).
   EV3는 소켓으로 `latest`만 흘려보내고, 노트북 watcher가 `runs/current/telemetry.jsonl` 기록.
5. **회전은 시간보다 엔코더 각도.** `turn_90_ms` 같은 시간기반은 배터리/마찰에 가장 크게
   흔들린다. `on_for_degrees` + **보정계수 하나**를 live param으로 둔다(Stage 2).
6. **BACK 버튼 정지가 항상 최우선**, 네트워크와 독립. `emergency_stop`(네트워크)은 보조.
   옵션으로 "N초간 명령/연결 없으면 안전정지" watchdog을 *토글 가능*하게(모드별 선택).
7. **파라미터 의미를 섞지 않는다.** `target_reflect`(중앙 1센서 PID)와
   `black/white_threshold`(3센서 노드 bits)는 다른 단계 것. 단계별로 *필요한 것만* 노출한다.

## "거대 config 금지" 원칙과의 관계

이전 실패는 *config가 있던 것*이 아니라 **모든 기능을 다 만들고 한꺼번에 눈감고 튜닝**한
것이다. 라이브 튜닝에서는 각 스테이지 파일 맨 위 상수가 **그 스테이지의 "초기 params dict
+ PARAM_LIMITS"** 가 된다. 여전히 per-stage·소수다. 차이는 *"파일 고치고 재배포"가 아니라
"피드백 보며 한 값씩 라이브 변경"*. 그래도 **한 번에 변수 하나** 원칙은 그대로 지킨다.

## 안전장치 (반드시)

### 값 범위 제한 (PARAM_LIMITS) — 예시(Stage 1)
```python
PARAM_LIMITS = {
    "kp": (0.0, 3.0), "ki": (0.0, 0.5), "kd": (0.0, 1.0),
    "base_speed": (5, 45), "turn_limit": (5, 60),
    "target_reflect": (0, 100),
}
```
서버는 범위 밖 값을 거부한다(클램프 X, 거부 + 에러 응답).

### 한 번에 바꿀 변화폭 제한 (MAX_STEP)
```python
MAX_STEP = {"kp": 0.1, "ki": 0.02, "kd": 0.05, "base_speed": 5, "turn_limit": 10}
```

### emergency stop은 항상 가능
```bash
python tools/robotctl.py stop          # 네트워크 정지(보조)
# 브릭 BACK 버튼 = 1차 정지(항상 동작)
```

### live vs saved 분리
```bash
python tools/robotctl.py set kp 0.82   # 지금 주행에만 적용(메모리)
python tools/robotctl.py save          # config/ 에 저장(검증된 값)
python tools/robotctl.py rollback      # 마지막 저장값으로 복귀
```

### 단일 동작 트리거 + 재연 (빠른 보정 루프) — 상세는 [DECISIONS.md](DECISIONS.md)
```bash
python tools/robotctl.py do turn_left  # 동작 1회 실행(재배포 0), reason 로그 남김
python tools/robotctl.py do read_color # 현재 위치 색 + reflect
python tools/replay.py runs/<ts> --set node_advance=8   # 로봇 없이 판단 재연
```

## 실시간으로 여는 값 (단계별, 처음엔 작게)

> **한 단계에서 라이브로 노출하는 params 는 6개 이하.** 그 단계가 실제로 만지는 것만.
> 나머지는 검증된 기본값으로 `config/` 에 묻어 둔다. 그리고 **감으로 만지지 말고
> reason 로그가 짚는 값만** 만진다([DECISIONS.md](DECISIONS.md) 6장).

### Stage 1 (라인 PID) — 이것만
```json
{ "kp": 0.75, "ki": 0.0, "kd": 0.06, "base_speed": 22,
  "turn_limit": 35, "target_reflect": 35 }
```
### Stage 2~ 추가 후보 (회전/노드)
```json
{ "turn_90_factor": 1.0, "turn_180_factor": 1.0, "scan_turn_speed": 14,
  "node_black_threshold": 16, "node_confirm_ms": 120, "node_debounce_ms": 900,
  "node_centering_ms": 180, "intersection_advance_ms": 220, "line_lost_ms": 300 }
```

| 값 | 현실에서 달라지는 이유 |
|---|---|
| `target_reflect` | 조명, 라인 테이프 색, 바닥 반사 |
| `node_black_threshold` | 센서 높이, 바닥 재질 |
| `kp/kd` | 배터리 전압, 바퀴 마찰 |
| `base_speed` | 코스 곡률, 센서 위치 |
| `node_confirm_ms` | 교차로 폭, 속도 |
| `turn_90_factor` | 배터리, 바닥 마찰, 바퀴 지름 |
| `node_debounce_ms` | 노드 중복 감지 방지 |

## 권장 빌드 순서 (단계와 깍지 끼움)

```
0. Stage 0  : plain 연결확인 (네트워크 없음)
1. infra MVP + Stage 1 동시:
     lib(shared_params / telemetry / tuning_server / pid)
     + 판단층↔구동층 분리 + reason logging (events 기록)  ← DECISIONS.md
     + tools/robotctl.py (get / set / stop / do)
     + 라인트레이싱 제어 루프 (kp, kd, base_speed, target_reflect)
2. tools/dashboard.py : 터미널 TUI (키로 do 실행 + 파라미터 조정 + 상태/이벤트 표시 + STOP)
3. tools/telemetry_watcher.py : 노트북이 runs/<ts>/{samples,events}.jsonl 기록
4. tools/replay.py : 기록한 samples 를 판단층에 재연(로봇 없이)
5. → Stage 1 을 라이브로 튜닝해 실기 Done 까지
6. Stage 2 : 회전을 `do turn_*` 로 트리거 + turn 보정계수(엔코더) 추가
7. Stage 3~ : 단계마다 params/telemetry/reason_code 만 늘림
8. (한참 뒤) 무거운 웹 대시보드, (그다음) approve 방식 반자동
```

## 디렉토리 구조 (목표)

```
ev3test/
  lib/            # 브릭에서 import: shared_params, telemetry, tuning_server, pid, hardware
  stages/         # 단계별 독립 실행 진입점 (lib import)
  tools/          # 노트북: robotctl, telemetry_watcher, (나중) propose/apply
  config/         # save 된 검증값 (stage별, git 추적함)
  runs/current/   # telemetry.jsonl, latest_state.json, params.json (git 추적 안 함)
  dashboard/      # (나중)
  docs/  AGENTS.md  CLAUDE.md  GEMINI.md  README.md  PROGRESS.md
```

`runs/` 는 gitignore, `config/` 의 저장값은 추적(검증된 값은 변경 추적 대상).

## 에이전트 워크플로우 (안전선)

- **1단계(한동안 여기 고정): 에이전트는 제안만.** 어떤 에이전트도 `robotctl set`을 직접
  실행하지 않는다. telemetry/로그를 읽고 `runs/current/proposal.json` 또는 텍스트로 조정안을
  내면, **사람이** `robotctl set` 으로 적용한다.
- 2단계(나중): `propose → 사람 approve → apply`.
- 3단계(완전 자동): 안전 범위·변화폭 제한·실패시 rollback 갖춘 뒤에만. 당분간 안 함.

역할 분담(예):
- **Claude** — 코드 구조 + 튜닝 알고리즘. 예: "최근 20초 telemetry 에서 error 부호변화가
  잦은 구간을 찾아 kp/kd 조정안을 `robotctl` 명령 형태로 제안."
- **Codex** — 안전 리뷰. 예: "튜닝 서버의 파라미터 범위 누락, emergency_stop 실패,
  네트워크 오류 시 제어 루프 멈춤, JSON 파싱 실패로 서버 죽음 가능성 점검."
- **Antigravity** — 실험 관제. 예: "대시보드 보며 최근 telemetry 에서 라인 분실·노드 중복
  감지·motor saturation 구간 리포트 + 다음 실험 체크리스트."
