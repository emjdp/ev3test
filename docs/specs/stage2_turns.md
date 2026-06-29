# Stage 2 — 원시 회전 (좌90 / 우90 / U턴) 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 1(라인트레이싱) 실기 Done + 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))의
> `robotctl do` / reason 로깅 / record 동작.
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 2 인용 —
> "바닥 표시 기준 각 회전을 3회 연속 ±몇 도 안에서 재현. (라인 재포착 방식은 Stage 5에서
> 라인트레이싱과 합칠 때 도입; 여기서는 순수 회전 각도만 본다.)"

상위 규칙: [../../AGENTS.md](../../AGENTS.md) · 라이브 튜닝/대시보드: [../LIVE_TUNING.md](../LIVE_TUNING.md) ·
판단기록/재연: [../DECISIONS.md](../DECISIONS.md) · 배선: [../HARDWARE.md](../HARDWARE.md).

---

## 1. 목표 / 범위

**하는 것**

- 제자리(탱크) 회전으로 좌90°·우90°·180° U턴을 각각 일관되게 수행한다.
- 회전량을 **시간(ms)이 아니라 엔코더 각도 + 보정계수**로 정한다
  ([LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 5).
- `robotctl do turn_left / turn_right / uturn` **단일 동작 트리거**로 노트북에서 회전을
  1회 실행 → 값 하나(`turn_90_factor` 또는 `turn_180_factor`) 고침 → 다시 실행.
  **재배포 0.** "좌회전 하나에 1시간" 문제를 없애는 것이 이 단계의 핵심.
- 좌/우/U **셋을 따로** 맞춘다. 회전마다 `TURN_LEFT/RIGHT/UTURN` reason 로그를 남긴다.
- **판단층 ↔ 구동층 분리**: "어느 회전을 왜 하는가"(판단)와 "엔코더 각도만큼 도는가"(구동)를 나눈다.

**안 하는 것 (다음 단계로 미룸)**

- **라인 재포착으로 회전 정지**(중앙센서가 다음 선을 다시 잡으면 멈춤)는 안 한다.
  이건 Stage 5에서 라인트레이싱과 합칠 때 도입. 여기서는 **순수 회전 각도만** 본다.
- 노드 감지/색 판정/분기 선택 로직 없음(Stage 3·4·6).
- 어느 회전을 할지 자동으로 정하는 탐색 알고리즘 없음. Stage 2의 판단층은
  `do <action>` 으로 들어온 "사람이 고른 한 동작"을 reason 과 함께 구동층에 넘기는 수준.

---

## 2. 파일 / 인터페이스

**새로 만들/수정할 파일**

| 경로 | 내용 |
|---|---|
| `stages/stage2_turns.py` | 이 단계 독립 실행 진입점. 초기 params dict + PARAM_LIMITS(파일 맨 위 상수), 제어/대기 루프, `do turn_*` 수신. |
| `lib/turns.py` (신규, 구동층) | 엔코더 각도 기반 제자리 회전 구동 함수. ev3dev2 모터 의존. |
| `lib/decide_turn.py` (신규, 판단층, **순수**) | 어느 회전을 왜 하는지 → (action, reason_code, detail). 하드웨어 없음. |
| `lib/hardware.py` (기존, Stage 1에서 생성) | 좌/우 모터 엔코더 읽기·리셋 메서드 추가만(직진/정지는 재사용). |
| `tools/robotctl.py` (기존) | `do turn_left/turn_right/uturn` 액션 등록(인프라 명세 참조). |

**판단층 (순수 함수, PC 에서 import·재연 가능)**

```python
# lib/decide_turn.py  — ev3dev2 import 금지. 시간·모터 없음.

def decide_turn(command, params, state):
    """'어느 회전을 왜' 결정. command 는 do 트리거가 넘긴 'turn_left'|'turn_right'|'uturn'.

    반환: (action, reason_code, detail)
      action      : 구동층이 실행할 회전. 'LEFT90' | 'RIGHT90' | 'UTURN180'
      reason_code : 'TURN_LEFT' | 'TURN_RIGHT' | 'UTURN'   (DECISIONS.md 카탈로그)
      detail      : {"command": command, "rule": "...", "target_deg": <보정 적용된 목표각>,
                     "factor": <적용 계수>, "turn_speed": <속도>}
    Stage 2 에서는 '왜'가 단순하다(사람이 do 로 고른 동작). 그래도 Stage 5~6 에서
    available_exits/selected 로 확장될 자리를 reason/detail 형태로 미리 비워 둔다.
    """
```

목표각 계산도 순수 함수로 분리해 PC 단위 테스트한다:

```python
def target_degrees(action, params):
    """회전 종류 + 보정계수 → '모터에 줄 바퀴 회전 각도(도)'.
    BASE_PIVOT_DEG_90 / BASE_PIVOT_DEG_180 (파일 상수, 기하학적 1차 추정)에
    live 보정계수를 곱한다.  반환은 양수(절댓값), 방향은 구동층이 정한다.
    """
    if action == "UTURN180":
        return params["BASE_PIVOT_DEG_180"] * params["turn_180_factor"]
    return params["BASE_PIVOT_DEG_90"] * params["turn_90_factor"]
```

**구동층 (ev3dev2, `lib/turns.py`)**

```python
def pivot(hw, action, target_deg, turn_speed):
    """엔코더 각도 기준 제자리 회전. action 으로 좌/우/방향 결정.
       하드웨어(hw)의 좌/우 모터를 반대 방향으로 같은 각도만큼 돌린다.
       BACK 버튼 즉시 정지 포함. 반환: 실제 회전한 평균 엔코더 각도(검증용)."""
```

> 분리 이유([DECISIONS.md](../DECISIONS.md) 0장): 판단 버그("엉뚱한 회전을 골랐다")와
> 구동 버그("각도가 안 맞는다")를 따로 잡기 위함. Stage 2는 구동 정확도가 주제이므로
> 판단층은 얇지만, **분리 형태는 지금부터 지켜** Stage 5~6에서 그대로 자란다.

---

## 3. 라이브 params (6개 이하)

이 단계에서 라이브로 노출하는 값은 **4개**. 나머지(기하 추정 기준각, settle 등)는
파일 상수/`config/` 에 묻는다.

| 이름 | 의미 | 기본값 | LIMITS (min,max) | MAX_STEP | 올림/내림 |
|---|---|---|---|---|---|
| `turn_speed` | 제자리 회전 속도(%). 낮을수록 관성 오버슛↓, 재현성↑ | 18 | (5, 40) | 5 | 너무 느려 안 도는 느낌 → ↑ / 멈출 때 밀려 과회전 → ↓ |
| `turn_90_factor` | 좌·우 90° 목표각 보정계수(기하 추정각 × 계수) | 1.0 | (0.5, 2.0) | 0.05 | 90°가 **부족**(덜 돌아 비스듬) → ↑ / **과다** → ↓ |
| `turn_180_factor` | U턴 180° 보정계수 | 1.0 | (0.5, 2.0) | 0.05 | U턴 부족 → ↑ / 과다 → ↓ |
| `post_turn_settle_ms` | 회전 정지 후 관성 멎을 때까지 대기(ms). 각도 측정 안정화 | 120 | (0, 400) | 40 | 정지 직후 밀려 측정 흔들림 → ↑ |

> **좌90과 우90 보정을 하나의 `turn_90_factor` 로 묶을지 따로 둘지** — 기본은 하나로
> 시작(파라미터 6개 이하 원칙, 제자리 회전이라 좌우 대칭 기대). 실기에서 좌/우 오차가
> 계속 다른 방향으로 남으면 `turn_90_left_factor` / `turn_90_right_factor` 로 분리한다.
> (그러면 라이브 4→5개, 여전히 6 이하.) → 11절 미해결.

**config/ 에 묻는 상수(라이브 노출 안 함)**

```python
# stage2_turns.py 파일 맨 위 상수 (검증되면 config/stage2.json 으로 save)
BASE_PIVOT_DEG_90  = 0   # 미정: 바퀴/트레드 기하로 1차 추정 후 실기 보정. 11절 참조.
BASE_PIVOT_DEG_180 = 0   # 미정: 위의 약 2배에서 시작.
TURN_RAMP = False        # 가감속 사용 여부(기본 off; 관성 영향 최소화 위해 일정속도)
```

**PARAM_LIMITS / MAX_STEP (서버가 강제, 범위 밖은 거부)**

```python
PARAM_LIMITS = {
    "turn_speed": (5, 40), "turn_90_factor": (0.5, 2.0),
    "turn_180_factor": (0.5, 2.0), "post_turn_settle_ms": (0, 400),
}
MAX_STEP = {
    "turn_speed": 5, "turn_90_factor": 0.05,
    "turn_180_factor": 0.05, "post_turn_settle_ms": 40,
}
```

---

## 4. telemetry 필드 / reason_code

**추가 telemetry 키** (제어 틱/회전 동작 동안 흘려보냄)

| 키 | 의미 |
|---|---|
| `enc_l` / `enc_r` | 좌/우 모터 누적 엔코더 각도(도) |
| `enc_avg` | `(abs(enc_l)+abs(enc_r))/2` — 회전량 추정 |
| `target_deg` | 이번 회전 목표각(보정 적용) |
| `turning` | 현재 회전 중 여부(bool) |

**reason_code** (events.jsonl, [DECISIONS.md](../DECISIONS.md) 카탈로그와 일치)

| reason_code | 언제 | detail |
|---|---|---|
| `TURN_LEFT` | 좌90 회전 시작 | `node_id`(미정 시 null), `available_exits`(Stage2 미사용), `selected:"LEFT"`, `rule:"DO_TRIGGER"`, `target_deg`, `factor`, `turn_speed` |
| `TURN_RIGHT` | 우90 회전 시작 | 위와 동일(`selected:"RIGHT"`) |
| `UTURN` | U턴 시작 | 위와 동일(`selected:"UTURN"`, `factor:turn_180_factor`) |
| `EMERGENCY_STOP` | BACK 또는 네트워크 stop | `source:"BACK"|"NET"` |

> 회전 **종료**는 별도 reason_code 를 새로 만들지 않는다. 대신 같은 이벤트에 회전 후
> `enc_avg`(실제 돈 각도)를 detail 로 덧붙이거나, 다음 telemetry 틱의 `enc_avg` 로 본다.
> (카탈로그를 불필요하게 늘리지 않기 위함. 필요해지면 그때 1줄 추가.)

---

## 5. 동작 로직 (의사코드)

EV3(브릭) 코드는 **Python 3.5 안전**(f-string 금지, `.format()`).

### 5.1 진입점 / 대기 루프 (stage2_turns.py)

```python
# 의사코드 (실제 import 는 __main__ 안에서, PC py_compile 통과 위해)
def main():
    hw = Ev3Hardware()                      # 구동층(ev3dev2)
    params = dict(INITIAL_PARAMS)           # 파일 맨 위 상수에서 복제
    server = start_tuning_server(params, PARAM_LIMITS, MAX_STEP)  # lib, 별도 thread
    log = ReasonLogger()                    # events 소켓 전송

    while True:
        if hw.abort_requested():            # BACK = 1차 정지(항상 최우선)
            hw.stop(); log.event("EMERGENCY_STOP", source="BACK"); break
        cmd = server.take_pending_do()      # 'turn_left'|'turn_right'|'uturn'|None
        if cmd is not None:
            run_turn(hw, cmd, params, log, server)
        push_idle_telemetry(server, hw)     # enc_l/enc_r/turning=False
        sleep(0.02)                         # 네트워크는 절대 제어를 블록하지 않음(snapshot)
```

> Stage 2는 라인트레이싱처럼 *연속 제어*가 아니라 **트리거 대기 → 회전 1회** 구조다.
> 그래도 telemetry/BACK/네트워크 비차단 규칙은 동일하게 지킨다.

### 5.2 회전 1회 (판단 → 구동)

```python
def run_turn(hw, cmd, params, log, server):
    snap = dict(params)                      # 회전 도중 params 변경에 흔들리지 않게 snapshot
    action, reason, detail = decide_turn(cmd, snap, state={})   # 판단층(순수)
    log.event(reason, **detail)              # TURN_LEFT/RIGHT/UTURN + 이유/목표각
    target = detail["target_deg"]
    actual = pivot(hw, action, target, snap["turn_speed"], hw_abort=hw.abort_requested)
    if snap["post_turn_settle_ms"]:
        sleep(snap["post_turn_settle_ms"] / 1000.0)
    push_telemetry(server, enc_avg=actual, target_deg=target, turning=False)
    hw.beep_ok()                             # 사람이 "끝났다" 인지(보정 루프 리듬)
```

### 5.3 엔코더 각도 회전 (구동층, lib/turns.py)

```python
def pivot(hw, action, target_deg, turn_speed, hw_abort):
    # 좌회전: 왼바퀴 후진 / 오른바퀴 전진.  우회전: 반대.  U턴: 우회전과 같은 방향(또는 약속).
    left_dir, right_dir = _dirs(action)      # {'LEFT90':(-1,+1), 'RIGHT90':(+1,-1), 'UTURN180':(+1,-1)}
    hw.reset_encoders()                      # enc_l=enc_r=0
    hw.drive(left_dir * turn_speed, right_dir * turn_speed, apply_trim=False)  # 회전엔 트림 X
    while True:
        if hw_abort():                       # BACK 즉시 정지
            break
        el, er = hw.read_encoders()          # 누적 각도(도)
        if (abs(el) + abs(er)) / 2.0 >= target_deg:
            break
        sleep(0.005)
    hw.stop()                                # brake=True
    el, er = hw.read_encoders()
    return (abs(el) + abs(er)) / 2.0         # 실제 평균 회전 각도(검증/telemetry)
```

> **왜 시간이 아니라 엔코더인가**: `on_for_degrees`/엔코더 목표각은 배터리·마찰이 바뀌어도
> "바퀴가 그 각도만큼 돈다"는 점이 일정하다. 시간기반은 같은 ms 라도 전압이 낮으면 덜 돈다
> ([LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 5). **남는 변수는 보정계수 하나**라
> 라이브로 그것만 만지면 된다.
>
> `on_for_degrees` 를 쓸지 직접 루프로 엔코더를 폴링할지: 직접 폴링이 **BACK 즉시 정지**와
> **실시간 telemetry** 에 유리(블로킹 호출 중엔 BACK 을 못 본다). 기본은 위처럼 폴링 루프.
> 11절 참조.

---

## 6. 대시보드 / CLI 연동

이 단계에서 누를 수 있는 동작(`do <action>`)과 만질 키:

```bash
python tools/robotctl.py do turn_left      # 좌90 1회 (TURN_LEFT 로그)
python tools/robotctl.py do turn_right     # 우90 1회 (TURN_RIGHT 로그)
python tools/robotctl.py do uturn          # U턴 1회 (UTURN 로그)
python tools/robotctl.py set turn_90_factor 1.05
python tools/robotctl.py set turn_180_factor 1.10
python tools/robotctl.py set turn_speed 16
python tools/robotctl.py stop              # 네트워크 정지(보조; BACK 이 1차)
python tools/robotctl.py save              # config/stage2.json 으로 검증값 저장
python tools/robotctl.py rollback          # 마지막 저장값 복귀
```

터미널 TUI(`tools/dashboard.py`, [00_infra_dashboard.md](00_infra_dashboard.md))에서는
키 매핑 권장: `l`=do turn_left, `r`=do turn_right, `u`=do uturn,
`[`/`]`=turn_90_factor ∓/± MAX_STEP, `{`/`}`=turn_180_factor, `-`/`+`=turn_speed, `s`=STOP.

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

> 바닥에 **0°/90°/180° 기준선(테이프)**을 그려 두고, 회전 후 로봇 정면이 기준과 얼마나
> 어긋나는지 눈/각도기로 본다. **한 번에 값 하나만** 바꾸고 [PROGRESS.md](../../PROGRESS.md) 에 기록.

1. **속도 고정 먼저.** `turn_speed` 를 낮게(예 16~18) 고정. 관성 오버슛을 줄여 재현성 확보.
2. **좌90 맞추기.**
   - `do turn_left` 1회 → 실제 각도 관찰.
   - 부족하면 `turn_90_factor` 를 MAX_STEP(0.05)씩 ↑, 과다면 ↓. → `do turn_left` 재실행.
   - **3회 연속 ±오차 안**에 들 때까지 반복. (이때 `turn_90_factor` **외 다른 값은 안 만진다.**)
3. **우90 확인.** 같은 `turn_90_factor` 로 `do turn_right` 3회. 좌와 같게 재현되면 OK.
   - 좌는 맞는데 우만 계속 한쪽으로 어긋나면 → 11절(좌/우 분리) 검토.
4. **U턴 맞추기.** `do uturn` → `turn_180_factor` 만 0.05씩 조정 → 3회 연속 재현.
5. **settle 점검.** 정지 직후 밀려 측정이 흔들리면 `post_turn_settle_ms` ↑.
6. 셋 다 3회 연속 통과하면 `robotctl save` → `config/stage2.json`. PROGRESS 갱신.

> **셋을 동시에 만지지 않는다.** 좌가 끝나야 우, 우가 끝나야 U턴. (STAGES.md "셋을 따로".)

---

## 8. 실패 모드 & 진단

| 증상 | 로그/필드로 보는 법 | 고칠 값 |
|---|---|---|
| 90°가 항상 **부족**(비스듬히 섬) | `enc_avg` < 기대각, target_deg 가 작음 | `turn_90_factor` ↑ (하나만) |
| 90°가 항상 **과다** | `enc_avg` 가 target 도달했는데 실제 더 돎(관성) | 먼저 `turn_speed` ↓, 그래도 남으면 `turn_90_factor` ↓ |
| 매 회전 각도가 **들쭉날쭉**(재현 안 됨) | `enc_avg` 분산 큼, 정지 직후 telemetry 흔들림 | `turn_speed` ↓ + `post_turn_settle_ms` ↑ |
| 좌는 맞는데 **우만** 일관되게 어긋남 | 좌/우 `enc_avg` 비대칭 | `turn_90_factor` 좌우 분리(11절) |
| **회전 시작 직후 멈춤** | `turning` 이 바로 false | (Stage 2는 라인 재포착 안 함) → 코드 버그 의심. 엔코더 리셋 누락 점검 |
| 회전이 **영영 안 멈춤** | `enc_avg` 가 안 오름 | 엔코더 읽기/방향 부호 버그. `read_encoders` 단위 점검 |

> **재연 한계**: 회전 각도는 *물리(관성·마찰)가 섞인 양*이라 `replay.py` 로 완전 재연되지
> 않는다([DECISIONS.md](../DECISIONS.md) 5장). 재연으로는 `decide_turn` 이 **올바른 action/target_deg
> 를 골랐는지**(판단)만 확인하고, **실제 각도는 실기 `do` 루프**로 잡는다.

---

## 9. PC 검증

- `python3 -m py_compile stages/stage2_turns.py lib/turns.py lib/decide_turn.py`
  (ev3dev2 import 는 `__main__`/메서드 안에 둬 PC 에서도 컴파일 통과.)
- **판단층 단위 테스트** (`lib/decide_turn.py`, 순수):
  - `decide_turn("turn_left", params, {})` → `("LEFT90","TURN_LEFT", detail)` 이고
    `detail["target_deg"] == BASE_PIVOT_DEG_90 * turn_90_factor`.
  - `decide_turn("uturn", ...)` → action `"UTURN180"`, factor 가 `turn_180_factor`.
  - `target_degrees` 가 계수 변경에 선형으로 반응(0.5/1.0/2.0).
- **replay 시나리오**: 기록한 run 의 events 에서 `TURN_*` 의 target_deg 가
  `--set turn_90_factor=1.1` 로 바꿨을 때 기대대로 재계산되는지(판단만). 실제 각도는 비대상.

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] `lib/hardware.py` 에 `reset_encoders()`, `read_encoders() -> (deg_l, deg_r)` 추가
      (Stage 1 의 `drive`/`stop` 은 수정 없이 재사용).
- [ ] `lib/decide_turn.py`: `decide_turn`, `target_degrees` 순수 함수 작성(ev3dev2 import 금지).
- [ ] `lib/turns.py`: `pivot()` 엔코더 폴링 회전 + BACK 즉시 정지.
- [ ] `stages/stage2_turns.py`: 초기 params/PARAM_LIMITS/MAX_STEP 상수, 대기 루프, `run_turn`.
- [ ] `tools/robotctl.py` 에 `do turn_left/turn_right/uturn` 액션 등록(인프라 명세).
- [ ] reason_code `TURN_LEFT/RIGHT/UTURN` 을 events 로 전송(detail 포함).
- [ ] telemetry 에 `enc_l/enc_r/enc_avg/target_deg/turning` 추가.
- [ ] `BASE_PIVOT_DEG_90/180` 1차 추정값 채우기(11절) → 실기 보정.
- [ ] PC: py_compile + decide_turn 단위 테스트.
- [ ] 실기: 좌→우→U 순서로 각 3회 연속 재현, `save`, PROGRESS 갱신("실기 검증 필요"→결과).

---

## 11. 미해결 / 실기 확인 필요

- **`BASE_PIVOT_DEG_90` / `BASE_PIVOT_DEG_180` 초기값**: 바퀴 지름·트레드(좌우 바퀴 간격)
  로 기하 추정(제자리 90° 시 각 바퀴가 도는 호 길이 → 바퀴 회전각)할 수 있으나, **실측 치수가
  없어 미정**. Stage 0/2 에서 줄자로 바퀴 지름·트레드 측정 후 1차값을 넣고 보정계수로 미세조정.
  (이전 로봇은 시간기반이라 이 값이 없다 — 참고 불가.)
- **좌/우 보정계수 통합 vs 분리**: 기본은 `turn_90_factor` 하나. 실기에서 좌/우 오차가 계속
  다른 방향이면 `turn_90_left_factor`/`turn_90_right_factor` 로 분리(라이브 5개, 6 이하 유지).
- **`on_for_degrees` vs 폴링 루프**: 본 명세는 BACK 즉시정지/telemetry 위해 폴링을 기본으로
  잡았다. `on_for_degrees(brake=True)` 가 정확도/관성에서 더 나은지는 실기 비교 필요.
- **회전 방향 부호 약속**: 좌회전=왼바퀴 후진/오른바퀴 전진으로 가정. 실기에서 모터 극성·
  배선과 맞는지 Stage 0 결과로 확정(반대면 `_dirs` 부호만 뒤집음).
- **U턴 방향**: 우회전과 같은 방향으로 180°로 가정. 코스/공간 제약에 따라 좌로 돌 수도 있음 —
  실기에서 정하고 reason detail 에 명시.
- **정지 후 관성 오버슛 보정**: settle 로 *측정*은 안정화하지만 *실제 과회전*은 못 줄인다.
  남으면 목표각에서 일정량을 빼는 "관성 여유각"을 둘지 검토(지금은 도입 안 함 — 변수 늘림 지양).
