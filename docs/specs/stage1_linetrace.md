# Stage 1 — 기초 라인트레이싱 + 인프라 MVP 최초 통합 구현 명세

> 상태: REVIEWED (설계 검토 완료, 실기 미검증) — 검토 반영: 라인유실 상태전이 순수화(#4),
> D항 EMA 필터(#8).
> 선행: **Stage 0 Done** (실기 확인·좌/우 방향 확인·Python 버전 확정).
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 1 인용 —
> "직선 + 곡선이 섞인 코스를 끝에서 끝까지 선을 벗어나지 않고 추종.
> `robotctl stop` 또는 키보드 인터럽트 등 BACK 이 아닌 정지 경로로 멈춘다."
> + 여기서 라이브 튜닝 최소 인프라를 처음 만든다.

## 1. 목표 / 범위

- **하는 것**
  - **중앙 컬러센서 1개(in2)** 반사광으로 검은 선을 PID(처음엔 P, 필요시 D/I)로 추종.
  - 직선 + 완만한 곡선이 섞인 코스를 선을 벗어나지 않고 끝까지 추종.
  - **라이브 튜닝 인프라 MVP 최초 통합**: 주행 중 노트북에서 params 실시간 변경 + telemetry
    관찰. 구조/서버/CLI 는 [00_infra_dashboard.md](00_infra_dashboard.md)(작성 예정)와
    [LIVE_TUNING.md](../LIVE_TUNING.md) 에 정의 — **여기서 중복 설명하지 않고 링크로 참조**한다.
  - **판단층↔구동층 분리**(순수 PID 계산 vs 실제 모터 출력). [DECISIONS.md](../DECISIONS.md) 0장.
  - **reason 로깅 최초 도입**: `LINE_FOLLOW`, `LINE_LOST`, `LINE_RECOVER`, `EMERGENCY_STOP`.
  - BACK 버튼은 프로그램 입력으로 할당하지 않고, 네트워크 stop + 비차단(snapshot 패턴)을 쓴다.
- **안 하는 것 (다음 단계로)**
  - 좌/우 센서(in1/in3) 사용 안 함 → 분기/노드 감지 없음(Stage 3). 중앙 1센서만.
  - 회전 없음(Stage 2). 색 판정 없음(Stage 4). 그리퍼 없음.
  - 무거운 웹 대시보드/자동튜닝 없음(LIVE_TUNING.md: 절대 금지). 터미널 TUI 는 인프라 스펙 소관.
  - 선이 끊기면(000) **그냥 멈추거나 천천히 직진**. 막다른 길 판정/U턴 안 함.

## 2. 파일 / 인터페이스

### 새/수정 파일
- **새**: `stages/stage1_linetrace.py` — 제어 루프 진입점(독립 실행).
- **새(인프라 MVP, lib/)**: 상세 시그니처/구현은 [00_infra_dashboard.md](00_infra_dashboard.md).
  Stage 1 은 이들을 **import 해서 쓴다**(여기선 사용 계약만 명시):
  - `lib/shared_params.py` — params dict + PARAM_LIMITS + MAX_STEP, thread-safe get/set snapshot.
  - `lib/telemetry.py` — 최신 telemetry/events 보관·소켓 송신(파일쓰기는 노트북, 결정 4).
  - `lib/tuning_server.py` — 연결당 thread, params set(범위검증)/telemetry 전송(결정 2).
  - `lib/pid.py` — 순수 PID 계산(아래 판단층).
  - `lib/hardware.py` — ev3dev2 구동층(아래). Stage 0 에서 본 포트/방향을 반영.
- **새(노트북, tools/)**: `tools/robotctl.py` get/set/stop(상세는 인프라 스펙).

### 판단층 (순수, 하드웨어 없음) — `lib/pid.py`
PC 에서 import·테스트·replay 가능. ev3dev2 비의존.

```text
# 순수 PID: 입력(reflect, params, state) → 출력(turn, new_state, reason)
def pid_step(reflect, params, state):
    # error = target_reflect - reflect   (선=어두움=작은 reflect → +error → 한쪽으로 보정)
    # dt 는 측정값(state 의 직전 시각 사용, 결정 3). 첫 틱은 d 항 0.
    # turn = kp*error + ki*integral + kd*derivative,  clamp 로 turn_limit 제한
    # return turn, new_state(integral,last_error,last_t), reason_detail(error,p,i,d)
    ...
```

> 판단층은 "조향량(turn)"까지만 낸다. **좌/우 바퀴 속도로 바꾸는 건 구동층**(분리 핵심).
> 라인 유실(000) 판단도 순수 함수로 둬 replay 가능하게 한다:
> `classify_line(reflect, params) -> "ON" | "LOST"` (reflect 가 흰바닥 수준이면 LOST 후보).

### 구동층 (ev3dev2) — `lib/hardware.py`
```text
def read_center_reflect() -> int          # in2 reflected_light_intensity (0~100)
def drive(left_speed, right_speed)        # 트림 적용, clamp(-100,100)
def stop()                                # off(brake=True)
def should_stop() -> bool                 # 네트워크 stop/watchdog 같은 정지 플래그
```
- 좌/우 트림(`LEFT/RIGHT_MOTOR_TRIM`)은 **상수**로 시작(STAGES.md: "트림은 상수로 시작").
  곱셈 트림 패턴은 이전 구현 `hardware.Ev3Hardware.drive` 참고(복붙 금지, 구조만).
- turn→바퀴속도 변환(구동층):
  `left = base_speed - turn`, `right = base_speed + turn` (부호는 실기에서 확정, 11절).

## 3. 라이브 params (6개 이하)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 (증상) |
|---|---|---|---|---|---|
| `kp` | 비례 게인(오차 비례 조향) | `0.75` | (0.0, 3.0) | 0.1 | 곡선에서 굼떠 선 벗어남→↑ / 직선에서 좌우 진동→↓ |
| `ki` | 적분 게인(누적 오차) | `0.0` | (0.0, 0.5) | 0.02 | 한쪽으로 꾸준히 치우침 잔류→소량↑ / 흔들·오버슈트→↓(기본 0 유지 권장) |
| `kd` | 미분 게인(오차 변화 감쇠) | `0.06` | (0.0, 1.0) | 0.05 | kp 올렸더니 진동→↑(감쇠) / 노이즈로 떨림 심함→↓ |
| `base_speed` | 직진 기준 속도(%) | `22` | (5, 45) | 5 | 안정적이라 더 빠르게→↑ / 곡선에서 못 따라가 벗어남→↓ |
| `turn_limit` | 조향량 상한(±, 포화 방지) | `35` | (5, 60) | 10 | 급코너 복귀 약함→↑ / 과조향으로 휙휙 꺾임→↓ |
| `target_reflect` | 흑/백 중간 반사광(오차 0점) | `35` | (0, 100) | (보정값) | 보정① 측정으로 정함. 선쪽으로 치우치면 흑값에, 바닥쪽이면 백값에 가깝게 |

- 기본값은 [LIVE_TUNING.md](../LIVE_TUNING.md) "Stage 1 (라인 PID) — 이것만" JSON 과 일치.
  PARAM_LIMITS/MAX_STEP 도 동 문서 안전장치 예시와 일치.
- 정확히 6개 → config/ 로 묻을 것 없음. 좌/우 트림은 live 아님(상수, §2).
- **한 번에 변수 하나**(README 황금률). reason 로그가 짚는 값만 만진다([DECISIONS.md](../DECISIONS.md) 6장).

## 4. telemetry 필드 / reason_code

### telemetry (제어 틱마다 최신값; 노트북 watcher 가 기록)
| 키 | 의미 |
|---|---|
| `reflect` | in2 반사광 raw(0~100) |
| `error` | `target_reflect - reflect` |
| `turn` | PID 출력 조향량(clamp 후) |
| `left_speed` | 좌 바퀴 명령 속도 |
| `right_speed` | 우 바퀴 명령 속도 |

- (인프라 공통 필드 `t_ms`, `param_rev` 등은 [00_infra_dashboard.md](00_infra_dashboard.md) 소관.)

### reason_code (events; [DECISIONS.md](../DECISIONS.md) 카탈로그와 일치)
| reason_code | 언제 | detail |
|---|---|---|
| `LINE_FOLLOW` | PID 추종 중(주기적/상태유지) | `reflect`, `error`, `turn` |
| `LINE_LOST` | reflect 가 흰바닥 수준 지속 → 선 유실 판단 | `lost_ms`, `reflect` |
| `LINE_RECOVER` | 유실 후 선 재포착 | `lost_ms` |
| `EMERGENCY_STOP` | 네트워크 stop 또는 watchdog 안전정지 | `source`("NET"/"WATCHDOG") |

- 매 틱 `LINE_FOLLOW` 를 다 남기면 events 가 폭주 → **상태 전이/주기 throttle** 로만 남긴다
  (예: 0.25s 간격 또는 turn 부호 변화 시). 카탈로그에 새 reason 추가 시 DECISIONS.md 표도 갱신.

## 5. 동작 로직 (의사코드)

> 브릭 코드는 **Python 3.5 안전**(f-string 금지, `.format()`). dt 는 측정값(결정 3).
> 네트워크는 **별도 thread**, 제어 루프는 params **snapshot** 만 읽어 절대 블록 안 함(결정 6 / LIVE_TUNING).

```text
# stages/stage1_linetrace.py (제어 루프)  — 파일 맨 위: INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, 트림 상수
def run():
    params_store = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP)  # lib/shared_params
    tel = Telemetry()                                                    # lib/telemetry
    server = start_tuning_server(params_store, tel)   # 별도 thread (결정 2), 비차단
    hw = Hardware()                                   # lib/hardware (ev3dev2)
    state = pid_init_state()
    lost_since = None

    try:
        while True:
            # (1) 정지 플래그 확인. BACK 버튼은 프로그램 입력으로 할당하지 않는다.
            if hw.should_stop():
                hw.stop()
                tel.event("EMERGENCY_STOP", source="NET")
                break

            # (2) 센서 읽기
            reflect = hw.read_center_reflect()

            # (3) params snapshot (네트워크 비차단: 복사본만 읽음)
            p = params_store.snapshot()

            # (4) 판단층 — 순수 함수 (replay 가능)
            line = classify_line(reflect, p)          # "ON" | "LOST"
            if line == "LOST":
                if lost_since is None:
                    lost_since = now_ms(); tel.event("LINE_LOST", lost_ms=0, reflect=reflect)
                # 선 끊김: 그냥 멈추거나 천천히 직진 (Stage1 범위, 회전/막다른길 판정 안 함)
                turn = 0
                left, right = recover_speeds(p)        # 0,0(멈춤) 또는 저속 직진 — 11절 결정
            else:
                if lost_since is not None:
                    tel.event("LINE_RECOVER", lost_ms=now_ms()-lost_since); lost_since = None
                turn, state, d = pid_step(reflect, p, state)  # 조향량 + detail
                left, right = to_wheel_speeds(p["base_speed"], turn)  # 구동층 변환

            # (5) 구동층 출력
            hw.drive(left, right)

            # (6) telemetry 갱신 + reason(throttle)
            tel.update(reflect=reflect, error=p["target_reflect"]-reflect,
                       turn=turn, left_speed=left, right_speed=right)
            tel.event_throttled("LINE_FOLLOW", 0.25, reflect=reflect,
                                error=p["target_reflect"]-reflect, turn=turn)

            sleep(LOOP_DELAY)   # 0.015 정도. dt 는 LOOP_DELAY 가정 말고 실측(결정 3)
    finally:
        hw.stop(); server.stop()
```

```text
# 판단층 (lib/pid.py) — 순수, ev3dev2 없음
def pid_step(reflect, p, state):
    t = now_s()
    dt = (t - state.last_t) if state.last_t else 0.0     # 측정 dt (결정 3)
    error = p["target_reflect"] - reflect
    integral = state.integral + error*dt
    deriv = (error - state.last_error)/dt if dt > 0 else 0.0
    turn = p["kp"]*error + p["ki"]*integral + p["kd"]*deriv
    turn = clamp(turn, -p["turn_limit"], p["turn_limit"])
    return turn, State(integral, error, t), {"error":error,"d":deriv}

def to_wheel_speeds(base, turn):
    return base - turn, base + turn      # 부호/좌우 대응은 실기 확정 (11절)

def classify_line(reflect, p):
    # 선=어두움(작은 reflect). 흰바닥 수준으로 밝으면 유실 후보.
    return "LOST" if reflect >= (p["target_reflect"] + LINE_LOST_MARGIN) else "ON"
```

- **네트워크 비차단**: server thread 만 소켓 I/O. 제어 루프는 `snapshot()`(락 짧게, 복사) 만.
  네트워크 끊겨도 마지막 안전 params 로 계속 주행/정지(LIVE_TUNING "절대 규칙").
- **PID 계산(순수) ↔ 모터 출력(구동) 분리**: `pid_step`/`classify_line`(pure) ≠ `hw.drive`(ev3dev2).

> **검토 반영 #4 — 라인유실 상태전이도 순수층으로.** 위 루프는 `lost_since`(유실 지속시간)
> 추적과 `LINE_LOST`/`LINE_RECOVER` 전이를 루프 글루에서 했다. 이 전이 자체를 순수 함수
> `decide_line(reflect, params, state) -> (action, reason_code, new_state)` 로 옮겨 **replay 가
> 타이밍까지 재연**하게 한다(`action` ∈ `FOLLOW`/`LOST`). 단, 모든 스테이지를 단일 `decide_*`
> 시그니처로 강제하지는 않는다 — 목표는 "상태전이의 replay 가능성"이지 형식 통일이 아니다.
>
> **검토 반영 #8 — D항 EMA 필터.** raw reflect 수치미분은 센서 노이즈를 증폭해 모터를 떨게
> 한다. `pid_step` 안에서 미분값에 고정 alpha 지수이동평균을 적용한다(`deriv` 평활).
> **라이브 param 으로 열지 않는다**(6개 규칙 유지) — 내부 상수로 두고 필요 시에만 노출.

- 이 단계에서 **조정 가능한 키/param**: §3 의 6개(`kp ki kd base_speed turn_limit target_reflect`).
  서버는 PARAM_LIMITS 범위 밖/ MAX_STEP 초과 변화를 **거부**(클램프 X). 상세 [LIVE_TUNING.md](../LIVE_TUNING.md).
- **누를 수 있는 동작(`do <action>`)**: Stage 1 은 회전/색 같은 단발 동작이 없어 **`do` 동작은
  최소**다. `stop`(정지)만 필수. (`do nudge` 등은 Stage 2+ 에서 등장.)
- CLI 예(상세·구현은 인프라 스펙):
  ```
  python tools/robotctl.py get                 # 현재 params + 최신 telemetry
  python tools/robotctl.py set kp 0.85         # live 변경(메모리, 범위/스텝 검증)
  python tools/robotctl.py stop                # 네트워크 정지
  ```
- **에이전트는 제안만**(LIVE_TUNING 워크플로우 1단계): `set` 은 사람이 실행.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

순서는 STAGES.md Stage 1 그대로. **한 번에 하나만** 바꾸고 PROGRESS.md 에 기록.

1. **반사광 측정 → `target_reflect`**
   - 중앙센서를 **흰 바닥** 위에 두고 `reflect` raw 읽기(예 ~80), **검은 선** 위에서 읽기(예 ~10).
   - `target_reflect = (흰 + 검)/2` 로 설정(예 ~45). 측정은 telemetry `reflect` 로 확인.
   - 측정 도구로 `robotctl get` 또는 (있으면) `do read_reflect` 사용.
2. **직진 쏠림 트림**(상수)
   - `kp=0` 에 가깝게(또는 직선에서) 저속 직진시켜 한쪽으로 흐르는지 본다.
   - 흐르면 좌/우 트림 상수 **하나만** 미세 조정(빠른 쪽↓ 또는 느린 쪽↑). 곱셈 트림.
   - 트림은 live param 아님 → 파일 상수 고치고 재배포(이 단계 1회성).
3. **kp 올리며 곡선 추종**
   - 노트북에서 `kp` 를 MAX_STEP(0.1)씩 올린다. 곡선을 더 잘 따라오면 유지.
   - **좌우로 진동(떨림)** 하면 한 단계 내린다. 그래도 진동 남으면 `kd` 를 0.05씩 올려 감쇠.
   - `ki` 는 기본 0 유지. 직선에서 일정한 한쪽 치우침이 남을 때만 소량.
4. 각 변경 후 telemetry(`error`,`turn`)와 events(`LINE_FOLLOW`,`LINE_LOST`) 로 결과 확인.

## 8. 실패 모드 & 진단

| 증상 | 로그/필드로 보는 법 | 고칠 값 |
|---|---|---|
| 곡선에서 선 벗어남(굼뜸) | `error` 큰데 `turn` 작음 | `kp`↑ (한 단계) |
| 직선에서 좌우 진동 | `turn` 부호가 빠르게 자주 바뀜 | `kp`↓ 또는 `kd`↑ |
| `turn` 이 ±`turn_limit` 에 붙어있음(포화) | telemetry `turn`==limit 지속 | `turn_limit`↑ 또는 `base_speed`↓ |
| 직진인데 한쪽으로 흐름 | `error`≈0 인데 한쪽 치우침 | 좌/우 트림(상수) |
| 선을 흰바닥으로 오판(자꾸 LOST) | `LINE_LOST` 잦음, `reflect` 가 target 근처 | `target_reflect` 재측정 / `LINE_LOST_MARGIN` |
| 빠른데 못 따라감 | 곡선마다 LOST/벗어남 | `base_speed`↓ |
| `robotctl stop` 이 안 먹힘 | `EMERGENCY_STOP` 이벤트 없음 | stop 플래그 전달/루프 앞 확인 위치 점검 |

- 진단 원칙([DECISIONS.md](../DECISIONS.md) 6장): **감으로 만지지 말고 로그가 짚는 값만**.

## 9. PC 검증

- `python3 -m py_compile stages/stage1_linetrace.py lib/*.py` (ev3dev2 import 는 함수/구동층 안).
- **판단층 단위 테스트**(ev3dev2 없이):
  - `pid_step`: error>0 이면 turn 부호 일정, `turn_limit` 클램프 동작, dt=0 첫 틱 d항 0.
  - `classify_line`: 흰바닥 reflect → "LOST", 선 reflect → "ON", 경계 margin 동작.
  - `to_wheel_speeds`: base±turn 대칭.
- **replay**([DECISIONS.md](../DECISIONS.md) 5장): 기록한 `samples.jsonl`(reflect)을 같은
  판단층에 흘려, `target_reflect`/`kp` 바꿨을 때 LINE_LOST/turn 이 어떻게 달라지는지 로봇 없이 확인.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] (인프라 MVP) `lib/shared_params.py`,`telemetry.py`,`tuning_server.py`,`pid.py`,`hardware.py`
      — 상세는 [00_infra_dashboard.md](00_infra_dashboard.md)(없으면 그 스펙 먼저 작성).
- [ ] `tools/robotctl.py` get/set/stop(범위·스텝 검증) — 인프라 스펙.
- [ ] `stages/stage1_linetrace.py`: §5 제어 루프(stop 플래그 확인, snapshot 비차단, dt 실측).
- [ ] 판단층 `pid_step`/`classify_line`/`to_wheel_speeds` 순수 함수로 분리(ev3dev2 비의존).
- [ ] 구동층 turn→바퀴속도 변환 + 좌/우 트림 상수(Stage 0 방향 반영).
- [ ] telemetry 5필드 + reason 4종(throttle) 연결.
- [ ] `python3 -m py_compile` 통과 + 판단층 단위 테스트.
- [ ] SSH 포트포워딩(`ssh -L 8765:127.0.0.1:8765 ...`) 확인 후 라이브 set 동작 확인.
- [ ] **실기**: 보정 ①→②→③(한 번에 하나) → 직선+곡선 코스 끝까지 추종 + `robotctl stop` 정지 확인.
- [ ] 결과·확정 params 를 PROGRESS.md 기록, `robotctl save` 로 config/ 저장.

## 11. 미해결 / 실기 확인 필요

- **조향 부호/좌우 대응**: `to_wheel_speeds` 가 `base-turn / base+turn` 인지 반대인지 실기 확정
  (Stage 0 모터 방향 결과에 의존). error 부호와 함께 한 번에 맞춘다.
- **선 유실(000) 처리**: 멈춤 vs 저속 직진 중 무엇을 기본으로 둘지 미확정(STAGES.md 는 둘 다 허용).
  `recover_speeds`/`LINE_LOST_MARGIN` 기본값은 실기로 정함.
- **target_reflect/흑·백 raw**: 조명·테이프·바닥에 따라 달라 실기 측정 전엔 추정값(35). 보정①에서 확정.
- **좌/우 트림 상수**: Stage 0 에서 방향만 봤으므로 쏠림 보정값은 Stage 1 보정②에서 실측.
- **LOOP_DELAY/dt**: 0.015 가정이나 센서 읽기·소켓 thread 부하로 흔들릴 수 있음 → dt 실측 사용.
- **reason throttle 주기**(0.25s)와 events 폭주 균형 — 실기에서 가독성 보고 조정.
- **인프라 스펙 의존**: lib/ 계약(서버 동시성·snapshot·검증 응답)은 [00_infra_dashboard.md]
  (00_infra_dashboard.md)(상태 REVIEWED)에서 확정. Stage 1 코드는 그 계약을 따른다.
