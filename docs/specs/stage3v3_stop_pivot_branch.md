# Stage 3 v3 — 정지 후 제자리 분기 회전 구현 명세

> 상태: DRAFT (실기 미검증, 구현 미착수)
> 선행: Stage 1 주행 기반(모터 부호 `left=base-turn`/`right=base+turn`·트림) 실기 Done,
>       Stage 2 탱크 회전([lib/turns.py](../../lib/turns.py)) 실기 Done,
>       Stage 3 v2([stage3v2_linetrace_branch.md](stage3v2_linetrace_branch.md)) 실기 Done.
> 통과기준(Done): Stage 3 v2 와 같은 코스에서 좌/우 분기(`110`/`011`)를 보면
>       **먼저 정지한 뒤 그 자리에서 제자리 탱크 90도 회전**으로 다음 선에 올라타 계속 추종한다.
>       v2 처럼 라인트레이싱 중 생긴 사전 회전량을 `turn_90_factor` 로 보상하지 않는다.

## 0. 배경 / 이 문서의 위치

- Stage 3 v2 는 실기에서 잘 동작했고 공식 Stage 3 Done 으로 유지한다. 다만 사용자가 확인한
  실제 튜닝 방식은 약간의 편법이었다:
  - `110`/`011` 같은 회전 지점에서 분기 확정 전 라인트레이싱이 이미 조금 회전을 만들었다.
  - 그 뒤 Stage 2 탱크 회전이 이어지면 총 회전량이 커져서, `turn_90_factor` 를 **0.66**까지
    낮춰 "라인추종 중 사전 회전 + 작은 90도 회전"으로 맞췄다.
- v3 는 이 보정을 제거하는 실험 트랙이다. **분기 bits 를 보는 즉시 먼저 정지**하고, 정지
  상태에서 같은 분기임을 확인한 뒤 Stage 2 의 `lib/turns.pivot` 으로 제자리 회전한다.
- v2 공식 Done 값과 문서는 그대로 둔다. v3 는 "더 정석적인 회전 시점"을 검증하기 위한
  별도 명세이며, 구현/실기 Done 전까지 Stage 3 공식 구현체를 대체하지 않는다.

## 1. 목표 / 범위

- **하는 것**:
  - Stage 3 v2 의 3센서 raw 기반 PD 라인추종, threshold, telemetry, `do turn_*`, pause/stop
    구조를 최대한 유지한다.
  - 분기 bits 는 우선 사용자가 지정한 **`110` = 좌회전, `011` = 우회전**을 본다.
  - 분기 bits 를 보자마자 `hw.stop()` 으로 정지한다. 그 뒤에는 라인트레이싱을 더 진행하지 않는다.
  - 짧은 settle 후 정지 상태에서 센서를 다시 읽어 같은 방향이 확인되면 제자리 탱크 회전을 실행한다.
  - 자동 분기 회전에서는 `branch_advance_mm` 전진을 쓰지 않는다. `advance_mm=0` 을 로그에 남긴다.
- **안 하는 것**:
  - 색 판정(Stage 4), 미리 정한 회전 시퀀스(Stage 5), 탐색/복귀(Stage 6)는 하지 않는다.
  - 사전 회전량 보상을 위해 `turn_90_factor` 를 과도하게 낮추는 튜닝을 목표로 삼지 않는다.
  - 회전 전 소량 전진/후진(`pre_pivot_nudge_mm`)은 v3 기본 범위 밖이다. 정지 후 제자리 회전
    자체가 실패할 때만 별도 v3.1 손잡이로 검토한다.

## 2. 파일 / 인터페이스

- 신규 구현 예정: `stages/stage3v3_stop_pivot_branch.py`
  - [stages/stage3v2_linetrace_branch.py](../../stages/stage3v2_linetrace_branch.py) 를 기반으로
    하되 자동 분기 처리에서 `advance_straight()` 호출을 제거한다.
  - Stage 2 확정 코드 [lib/turns.py](../../lib/turns.py) `pivot` 과
    [lib/decide_turn.py](../../lib/decide_turn.py) `decide_turn` 은 수정 없이 재사용한다.
- 판단층(순수, PC 테스트/replay 가능):
  - `black_bits(raw, thresholds) -> (l, c, r)` — v2 와 동일.
  - `branch_side_v3(bits, include_111=False) -> 'left' | 'right' | None`
    - 기본: `110` -> left, `011` -> right.
    - `111` 을 v2 처럼 left 로 볼지는 실기 미해결. 기본은 사용자가 지정한 두 패턴만 본다.
  - `stationary_confirm_step(side, initial_side, seen, required) -> (seen, confirmed, cancelled)`
    - 정지 후 같은 방향이 연속으로 읽힐 때만 확정한다.
    - 다른 방향이 읽히면 cancel, `None` 이면 seen 을 0으로 리셋한다.
  - `decide_branch_stop(sensors, params, state) -> (action, reason_code, detail)`
    - replay 용 어댑터. "분기 발견 즉시 정지해야 하는가"와 "정지 후 확정됐는가"를 재연한다.
- 구동층:
  - `stop_and_confirm_branch(hw, initial_side, params, should_stop, should_pause) -> confirmed_side | None`
    - `hw.stop()` -> `stop_settle_ms` 대기 -> 정지 상태 센서 재확인.
  - `_run_turn(...)` — v2 의 수동/자동 공용 회전 함수 그대로 재사용.

## 3. 라이브 params (6개 이하)

v2 의 주행 손잡이는 유지하되, 자동 분기 회전에서는 `branch_advance_mm` 을 제거한다. 그 자리는
정지 후 확인 손잡이로 바꾼다.

| 이름 | 의미 | 기본 | LIMITS | MAX_STEP | 올림 / 내림 |
|---|---|---|---|---|---|
| `kp` | 조향 게인(v2 확정값 유지) | 0.22 | 0.0..3.0 | 0.1 | 곡선 못 따라감 ↑ / 흔들림 ↓ |
| `base_speed` | 직진 속도(v2 확정값 유지) | 17 | 5..45 | 5 | 빠르게 ↑ / 분기에서 멈춤 늦으면 ↓ |
| `turn_speed` | 탱크 회전 속도 | 6 | 5..40 | 5 | 빠르게 ↑ / 오버슛 나면 ↓ |
| `turn_90_factor` | 정지 후 순수 90도 보정계수 | 0.9 | 0.5..2.0 | 0.05 | 덜 돌면 ↑ / 더 돌면 ↓ |
| `stop_settle_ms` | 분기 발견 후 정지 안정화 대기 | 80 | 0..400 | 20 | 멈춘 뒤 센서값 흔들림 ↑ / 반응 느림 ↓ |
| `stationary_confirm_count` | 정지 상태 같은 방향 확인 횟수 | 2 | 1..8 | 1 | 오탐 정지/회전 ↑ / 확정 못함 ↓ |

- `turn_90_factor` 기본은 v2 확정값 0.66 이 아니라 **Stage 2 확정 순수 회전값 0.9**에서 시작한다.
  v3 의 목적은 사전 회전량을 factor 로 보상하지 않는 것이다.
- config 상수로 유지:
  - 센서 threshold `THR_LEFT=43`, `THR_CENTER=36`, `THR_RIGHT=42`(v2 실기값).
  - `KD=0.05`, `TURN_LIMIT=16`, `TURN_180_FACTOR=0.8`, `POST_TURN_SETTLE_MS=90`,
    `BRANCH_COOLDOWN_MS=1500`, `LOOP_DELAY_MS=15`.
  - `INCLUDE_111_AS_LEFT=False`(실기에서 111 이 반드시 필요하면 한 변수로 바꿔 검증).

## 4. telemetry 필드 / reason_code

### telemetry

- v2 필드(`reflect`, `bits`, `error`, `turn`, `left_speed`, `right_speed`, `branch_seen`,
  `mode`, `target_deg`, `enc_l`, `enc_r`, `enc_avg`)는 유지한다.
- v3 추가/변경:
  - `mode`: `follow` / `branch_stop` / `stationary_confirm` / `turning` / `paused`.
  - `initial_bits`: 처음 정지를 만든 bits.
  - `stationary_bits`: 정지 후 재확인 중 읽은 bits.
  - `stationary_seen`: 정지 상태 같은 방향 확인 횟수.
  - `advance_mm`: 자동 분기 회전에서는 항상 `0`.

### reason_code

| reason_code | 언제 | detail |
|---|---|---|
| `BRANCH_STOP` | `110`/`011` 을 보고 라인트레이싱을 끊고 즉시 정지 | `bits`, `side`, `reflect`, `stop_settle_ms` |
| `BRANCH_CANCEL` | 정지 후 재확인에서 같은 분기가 아니어서 자동 회전을 취소 | `initial_bits`, `stationary_bits`, `reflect` |
| `BRANCH_LEFT` / `BRANCH_RIGHT` | 정지 상태 확인까지 통과해 회전 트리거 확정 | `bits`, `stationary_seen`, `advance_mm:0`, `stop_before_turn:true`, `reflect` |
| `TURN_LEFT` / `TURN_RIGHT` | Stage 2 `decide_turn`/`pivot` 재사용 회전 결과 | `target_deg`, `factor`, `turn_speed`, `enc_avg`, `error_deg` |
| `LINE_FOLLOW` | 라인추종 중(throttle) | `reflect`, `bits`, `error`, `turn` |

`BRANCH_STOP`/`BRANCH_CANCEL` 은 v3 신규 판단이다. [../DECISIONS.md](../DECISIONS.md)
카탈로그에는 이 명세 작성 시점에 추가해 두었다. 구현할 때 events 로그 detail 을 위 표와 맞춘다.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크는 v2 처럼 snapshot 으로 읽고, stop/pause 는
플래그만 세운 뒤 제어 루프가 처리한다. BACK 버튼은 프로그램 입력으로 쓰지 않는다.

```
loop while not stop:
    snap = params.snapshot()
    raw  = hw.read_reflect()
    bits = black_bits(raw, thresholds)
    side = branch_side_v3(bits)

    if side and not in_cooldown:
        # v3 핵심: 라인트레이싱으로 더 꺾기 전에 먼저 정지한다.
        hw.stop()
        log BRANCH_STOP(bits, side, reflect, stop_settle_ms)
        publish(mode="branch_stop", initial_bits=bits)

        sleep(stop_settle_ms)
        stationary_seen = 0
        confirmed_side = None

        while not stop and not pause:
            raw2  = hw.read_reflect()
            bits2 = black_bits(raw2, thresholds)
            side2 = branch_side_v3(bits2)
            publish(mode="stationary_confirm",
                    initial_bits=bits, stationary_bits=bits2,
                    stationary_seen=stationary_seen)

            if side2 == side:
                stationary_seen += 1
                if stationary_seen >= stationary_confirm_count:
                    confirmed_side = side
                    break
            elif side2 is None:
                stationary_seen = 0
            else:
                log BRANCH_CANCEL(initial_bits=bits, stationary_bits=bits2)
                confirmed_side = None
                break

            sleep(LOOP_DELAY_MS)

        if confirmed_side is None:
            pd.reset()
            last_turn_ms = now_ms()   # 짧은 쿨다운으로 같은 노이즈 재진입 방지
            continue                  # 라인트레이싱 재개

        log BRANCH_LEFT/RIGHT(bits=bits2, stationary_seen, advance_mm=0, stop_before_turn=True)
        cmd = "turn_left" if confirmed_side == "left" else "turn_right"
        _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)
        pd.reset()
        last_turn_ms = now_ms()
        continue

    # 평소 라인추종은 v2 와 동일
    left, right, error, derivative, turn = pd_step(pd, raw, snap)
    if bits == (0,0,0):
        left *= 0.55
        right *= 0.55
    hw.drive(left, right)
    log LINE_FOLLOW(throttle)
    publish(mode="follow", ...)
```

## 6. 대시보드 / CLI 연동

- 자동 시작은 v2 와 같이 유지한다(`python3 stages/stage3v3_stop_pivot_branch.py` 실행 즉시 추종).
- `do turn_left` / `do turn_right` / `do uturn` 은 v2 와 동일하게 수동 회전 보정용으로 유지한다.
- 라이브 조정:
  - `kp`, `base_speed`, `turn_speed`, `turn_90_factor`, `stop_settle_ms`,
    `stationary_confirm_count`.
- 자동 분기 회전에는 `branch_advance_mm` 이 없다. dashboard/robotctl 에도 노출하지 않는다.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

1. v2 확정 주행값으로 시작한다: `kp=0.22`, `base_speed=17`, `turn_speed=6`.
2. `do turn_left`/`do turn_right` 로 **정지 상태 순수 회전**부터 맞춘다.
   `turn_90_factor` 는 Stage 2 확정값 `0.9`에서 시작하고, 덜 돌면 ↑ / 더 돌면 ↓.
3. 자동 추종을 켜고 `110`/`011` 에서 **BRANCH_STOP 이 먼저 찍히는지** 확인한다.
   `BRANCH_STOP` 이후 `LINE_FOLLOW` 가 더 진행되면 v3 실패다.
4. 멈춘 뒤 센서값이 흔들려 `BRANCH_CANCEL` 이 자주 나면 `stop_settle_ms` 를 하나만 올린다.
5. 직선에서 오탐 회전하면 먼저 threshold/패턴 로그를 보고, 그다음 `stationary_confirm_count` 를
   하나만 올린다. 움직이는 중 confirm_count 를 늘리는 방식으로 해결하지 않는다.
6. 좌/우 분기 각각에서 정지 후 제자리 회전으로 다음 선에 올라타면 `save` 하고 PROGRESS 에
   v3 실기값과 "실기 검증 필요/완료"를 기록한다.

## 8. 실패 모드 & 진단

| 증상 | 로그로 확인 | 고칠 값 / 판단 |
|---|---|---|
| 분기에서 멈추기 전에 차체가 이미 돌아감 | `BRANCH_STOP` 전 `LINE_FOLLOW` tick 과 `bits` | `base_speed` ↓ 또는 분기 판정 위치 확인. v3 는 `side` 즉시 stop 이어야 함 |
| 멈췄지만 회전이 덜/더 됨 | `TURN_LEFT/RIGHT target_deg`, `enc_avg`, `error_deg` | `turn_90_factor` 하나만 조정 |
| 멈춘 뒤 회전하지 않고 취소됨 | `BRANCH_CANCEL`, `stationary_bits` | `stop_settle_ms` ↑ 또는 threshold/패턴 확인 |
| 직선에서 오탐 정지/회전 | `BRANCH_STOP bits`, `stationary_seen` | threshold 확인 후 `stationary_confirm_count` ↑ |
| 회전 후 다음 선 못 탐 | 회전 후 `bits=000` 지속 | 먼저 `turn_90_factor`; 그래도 반복되면 v3 기본 가정(정지 위치)이 맞는지 검토 |
| 111 에서 돌아야 하는데 무시함 | `bits=111`, `side=None` | `INCLUDE_111_AS_LEFT=True` 를 별도 한 변수로 실기 검증 |

## 9. PC 검증

- `python3 -m py_compile stages/*.py lib/*.py tools/*.py tests/*.py`
- 단위 테스트:
  - `branch_side_v3`: `110` left, `011` right, 기본 `111` None, `010/000/100/001` None.
  - `stationary_confirm_step`: 같은 방향 N회만 confirm, 다른 방향 cancel, None 은 리셋.
  - 자동 분기 경로 fake hw: branch 감지 즉시 `stop` 이 `drive` 보다 먼저 호출되는지.
  - 자동 분기 경로에서 `advance_straight` 또는 전진 모터 호출 없이 `_run_turn` 으로 넘어가는지.
  - `turn_90_factor` 기본값이 0.9 인지(v2 저장값 0.66 재사용 금지).
- replay:
  - v2 실기 로그가 있으면 `110`/`011` 첫 tick 에 `BRANCH_STOP` 이 발생하는지 비교한다.
  - 흔들리는 `110,010,110,011` 샘플에서 정지 후 확정/취소가 의도대로 갈리는지 확인한다.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용)

- [ ] `stages/stage3v3_stop_pivot_branch.py` 신규 작성(v2 기반, Stage 2 회전 재사용 유지).
- [ ] 자동 분기 처리에서 `branch_advance_mm`/`advance_straight()` 제거.
- [ ] `branch_side_v3` 기본 패턴을 `110`/`011` 로 제한하고, `111` 은 config 옵션으로 둔다.
- [ ] `BRANCH_STOP` -> 정지 후 stationary confirm -> `BRANCH_LEFT/RIGHT` -> `_run_turn` 순서 구현.
- [ ] 라이브 params 6개를 §3 표와 맞춘다(`turn_90_factor` 기본 0.9).
- [ ] telemetry mode/detail 을 §4 와 맞춘다.
- [x] `BRANCH_STOP`/`BRANCH_CANCEL` 을 [../DECISIONS.md](../DECISIONS.md) 카탈로그에 추가한다.
- [ ] PC 테스트 추가 후 py_compile/tests 통과.
- [ ] 실기에서 좌/우 분기 각각 "정지 후 제자리 회전" 재현, PROGRESS 에 값과 결과 기록.

## 11. 미해결 / 실기 확인 필요

- `111` 을 v2 처럼 좌분기로 볼지, v3 기본처럼 무시할지. 사용자가 지정한 핵심 패턴은 `110`/`011`
  이므로 기본은 두 패턴만 본다.
- 정지 위치가 실제 회전 중심으로 충분한지. 만약 항상 너무 일찍 멈춰 다음 선을 못 잡는다면
  factor 를 낮추기 전에 "정지 후 제자리 회전" 가정 자체를 먼저 기록한다.
- `stop_settle_ms=80`, `stationary_confirm_count=2` 는 출발점일 뿐이다. 정지 후 센서 흔들림과
  관성은 실기로만 확정한다.
- v3 가 성공하면 Stage 3 공식 구현체를 v2 에서 v3 로 바꿀지, 아니면 Stage 5 통합에서만 v3
  정책을 가져갈지 별도 결정한다.
