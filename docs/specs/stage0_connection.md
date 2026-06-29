# Stage 0 — 연결/포트 확인 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: 없음 (첫 단계). 네트워크/튜닝 인프라 없음(plain).
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 0 인용 —
> "7개 장치가 모두 기대한 포트에서 에러 없이 열리고 값이 읽힌다.
> 좌/우 모터 방향이 코드 기대와 일치한다."

## 1. 목표 / 범위

- **하는 것**
  - ev3dev 브릭에서 모터 3개·센서 4개가 [HARDWARE.md](../HARDWARE.md) 배선대로
    인식되는지 각 포트를 열어 확인한다.
  - 각 센서의 현재 값을 한 번씩 읽어 화면/콘솔에 출력한다(살아있는지 확인).
  - **EV3 Python 버전을 확정**한다(`python3 --version`). 이후 모든 브릭 코드 규약의 전제다.
  - 좌/우 주행 모터를 **아주 짧게 저속**으로 돌려 방향이 코드 기대와 맞는지 눈으로 확인.
  - BACK 버튼으로 언제든 즉시 중단.
- **안 하는 것 (다음 단계로)**
  - 라인추종/PID 없음(Stage 1).
  - 라이브 튜닝 서버·telemetry·reason 로깅 없음(Stage 1에서 인프라 최초 도입).
  - 회전 보정·노드 감지·색 판정·그리퍼 없음.
  - 센서 모드 전환(반사광↔컬러) 안 함. 컬러센서는 기본/반사광 모드로만 한 번 읽는다.

## 2. 파일 / 인터페이스

- **새 파일**: `stages/stage0_check.py` (독립 실행: `python3 stages/stage0_check.py`).
  - lib import 없음(인프라 도입 전). 이 파일 하나로 완결.
- 판단층↔구동층 분리는 이 단계에선 **불필요**(순수 판단 로직이 없음 — 열기/읽기/짧은 구동뿐).
  단, ev3dev2 import 는 함수/`__main__` 안에서 하거나 try/except 로 감싸 **PC에서
  `python3 -m py_compile` 가 되게** 한다(AGENTS.md 2절).
- 제시 함수 시그니처(의사):
  - `probe_motor(cls, port) -> (ok, detail)` — 모터 1개 열기 시도, 성공/예외 메시지.
  - `probe_sensor(cls, port, read) -> (ok, value_or_detail)` — 센서 1개 열기 + 값 1회 읽기.
  - `nudge_drive(left_motor, right_motor, speed, ms)` — 좌/우 모터 짧게 저속 구동(방향 확인).
  - `back_pressed(button) -> bool` — BACK 즉시 정지 체크.

## 3. 라이브 params (6개 이하)

- **없음.** Stage 0 은 라이브 튜닝 인프라가 들어오기 전이라 조정 가능한 live param 이 없다.
- 파일 맨 위 상수(고정값, live 아님):

| 상수 | 의미 | 기본값 | 비고 |
|---|---|---|---|
| `NUDGE_SPEED` | 방향 확인용 구동 속도(%) | `15` | HARDWARE.md "첫 실행 15~20%" |
| `NUDGE_MS` | 방향 확인 구동 시간(ms) | `400` | 아주 짧게. 책상 위 띄워서 확인 권장 |

> live param 표가 비는 것은 정상이다(이 단계는 인프라 없음). Stage 1부터 params dict 가 생긴다.

## 4. telemetry 필드 / reason_code

- **telemetry 없음, reason_code 없음**(인프라/이벤트 로깅이 Stage 1부터 등장).
- 출력은 사람이 읽는 **콘솔/LCD 텍스트**로만 한다. 예: `outA LargeMotor OK`,
  `in2 reflect=83`, `python 3.5.3`.
- (참고) reason_code 카탈로그는 [DECISIONS.md](../DECISIONS.md). Stage 0 은 거기에 기여하지 않는다.

## 5. 동작 로직 (의사코드)

> EV3(브릭)에서 도는 코드는 **Python 3.5 안전**: f-string 금지, `.format()` 사용.
> 버전 미확정 단계이므로 더더욱 3.5 문법으로만 쓴다.

```text
NUDGE_SPEED = 15
NUDGE_MS = 400

def main():
    # ev3dev2 는 함수 안에서 import (PC py_compile 안전)
    from ev3dev2.motor import LargeMotor, MediumMotor, SpeedPercent
    from ev3dev2.sensor.lego import ColorSensor, UltrasonicSensor
    from ev3dev2.button import Button
    import platform, time

    print("python " + platform.python_version())   # 3.5.x 면 f-string 불가 확정

    button = Button()

    # --- 1) 모터 3개 열기 ---
    motors = [
        ("outA", "LargeMotor(주행 좌)", LargeMotor),
        ("outB", "LargeMotor(주행 우)", LargeMotor),
        ("outC", "MediumMotor(그립)", MediumMotor),
    ]
    opened = {}
    for port, label, cls in motors:
        try:
            m = cls(port)
            opened[port] = m
            print("{} {} OK (pos={})".format(port, label, m.position))
        except Exception as exc:
            print("{} {} FAIL: {}".format(port, label, exc))

    # --- 2) 센서 4개 열기 + 값 1회 읽기 ---
    #   컬러센서는 반사광(reflected_light_intensity)만 1회 (모드전환 안 함)
    sensors = [
        ("in1", "ColorSensor 좌",  ColorSensor,     lambda s: s.reflected_light_intensity),
        ("in2", "ColorSensor 중",  ColorSensor,     lambda s: s.reflected_light_intensity),
        ("in3", "ColorSensor 우",  ColorSensor,     lambda s: s.reflected_light_intensity),
        ("in4", "Ultrasonic",      UltrasonicSensor, lambda s: s.distance_centimeters),
    ]
    for port, label, cls, read in sensors:
        try:
            s = cls(port)
            val = read(s)
            print("{} {} OK value={}".format(port, label, val))
        except Exception as exc:
            print("{} {} FAIL: {}".format(port, label, exc))

    # --- 3) 좌/우 모터 방향 확인 (짧게 저속, BACK 으로 중단 가능) ---
    if "outA" in opened and "outB" in opened:
        print("forward nudge: 두 바퀴가 같은 '전진' 방향인지 보세요")
        if not back_pressed(button):
            opened["outA"].on(SpeedPercent(NUDGE_SPEED))   # 좌=전진(+)
            opened["outB"].on(SpeedPercent(NUDGE_SPEED))   # 우=전진(+)
            wait_ms_or_back(button, NUDGE_MS)
        opened["outA"].off(brake=True)
        opened["outB"].off(brake=True)
        time.sleep(0.1)   # settle (관성)

    print("DONE. 위 결과를 PROGRESS.md 에 적으세요.")

def back_pressed(button):
    return bool(button.backspace)   # BACK = 즉시 정지/중단 (최우선)

def wait_ms_or_back(button, ms):
    # ms 동안 대기하되 BACK 누르면 즉시 빠져나온다
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if back_pressed(button):
            break
        time.sleep(0.01)
```

- **BACK 즉시 정지**: 구동 구간 진입 전 1회 + 대기 루프 안에서 매 10ms 체크. 누르면 즉시 off.
- 네트워크 비차단: 해당 없음(네트워크 자체가 없음).
- 모터/센서 열기는 각각 try/except 로 감싸 **하나가 실패해도 나머지를 계속 점검**한다
  (한 포트 빠졌다고 전체가 죽지 않게).

## 6. 대시보드 / CLI 연동

- **없음.** Stage 0 은 plain 실행이라 `robotctl`/대시보드와 연동하지 않는다.
- 유일한 입력은 브릭 버튼(ENTER 로 시작 대기 — 선택, BACK 으로 중단).
- 인프라/대시보드는 Stage 1에서 처음 등장한다 → [00_infra_dashboard.md](00_infra_dashboard.md)
  (작성 예정), [LIVE_TUNING.md](../LIVE_TUNING.md).

## 7. 보정 절차 (실기, 한 번에 변수 하나)

Stage 0 은 "튜닝"이 아니라 "확인"이다. 순서:

1. **버전 확인**: 출력 첫 줄 `python 3.x.x` 를 PROGRESS.md 에 적는다.
   - `3.5.x` → 이후 모든 브릭 코드 f-string 금지(`.format()` 만). **이게 가장 중요한 산출물.**
   - `3.6+` → f-string 가능하나, AGENTS.md 규약대로 안전하게 `.format()` 유지 권장.
2. **포트 확인**: 7개 장치가 모두 `OK` 인지 본다. `FAIL` 이면 배선/포트만 고치고 재실행
   (코드 값은 안 만진다 — 바꿀 게 없다).
3. **센서 값 sanity**: in1~in3 반사광이 0~100 범위의 그럴듯한 값인지, in4 거리(cm)가
   실제 전방 거리와 대략 맞는지 본다.
4. **모터 방향**: forward nudge 에서 좌/우 바퀴가 **둘 다 전진**으로 도는지 본다.
   - 한쪽이 반대로 돌면 → 배선/장착을 먼저 의심. 코드 극성 반전은 **Stage 1에서** 다룬다
     (여기선 "기대와 다름"만 기록). 한 번에 하나 원칙: Stage 0 에선 관찰만.

## 8. 실패 모드 & 진단

| 증상 | 원인 후보 | 어떻게 짚나 / 대응 |
|---|---|---|
| 특정 포트 `FAIL` | 배선 안 됨/다른 포트 꽂힘/케이블 불량 | 출력의 포트명 확인 → 물리 배선 교정 후 재실행 |
| 모든 센서 `FAIL` | ev3dev2 미설치/펌웨어 문제 | `python3 -c "import ev3dev2"` 별도 확인 |
| in1~3 값이 항상 0/100 고정 | 센서 너무 멀거나 가림/조명 | 높이·바닥 바꿔 재실행(값이 변하는지) |
| in4 거리 비현실적(0/255) | 초음파 정면에 물체 없음/너무 가까움 | 30cm 앞 벽 두고 재확인 |
| 좌/우 한쪽만 돔 | 모터 한쪽 `FAIL` 또는 정지 | 모터 OK 출력과 대조 |
| 좌/우 반대로 돔 | 모터 장착 방향/배선 | 기록만 → Stage 1 극성에서 처리 |

- Stage 0 은 로그(events)가 없으므로 진단은 **콘솔 출력 텍스트**로 한다.

## 9. PC 검증

- `python3 -m py_compile stages/stage0_check.py` 로 문법 점검(ev3dev2 import 가 함수 안에
  있어야 PC 에서 통과).
- 판단층이 없으므로 단위 테스트/replay 대상 없음. (replay 는 Stage 1+ 의 판단층용.)
- PC 에서 실제 동작 확인 불가 → **실기에서만** Done 판정.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] `stages/stage0_check.py` 작성(위 의사코드 기반, Python 3.5 안전).
- [ ] ev3dev2 import 를 함수 안/try-except 로 감싸 PC py_compile 통과 확인.
- [ ] 모터 3개·센서 4개 probe + 값 출력 구현.
- [ ] forward nudge(15%, 400ms) + BACK 즉시 정지 구현.
- [ ] `python3 -m py_compile stages/stage0_check.py` 통과.
- [ ] **실기 실행** → `python3 --version` 결과를 PROGRESS.md 에 기록(3.5 여부 확정).
- [ ] 7개 포트 OK + 센서값 sanity + 좌/우 방향을 PROGRESS.md 에 기록.
- [ ] 방향이 기대와 다르면 "다름"으로만 기록(수정은 Stage 1).

## 11. 미해결 / 실기 확인 필요

- **EV3 Python 버전 미확정**: stretch=3.5(f-string 불가) 가정이나 실기 출력으로 확정 필요.
  이 명세는 3.5 가정으로 작성(가장 안전한 하위호환).
- 모터 `position` 속성 접근이 모든 펌웨어에서 예외 없이 되는지 미확인 → 실패 시 출력에서 빼고
  "열림 OK"만 표기.
- 초음파 측정 불가 시 반환값(큰 값/예외)이 ev3dev2 버전마다 다를 수 있음 — 실기 확인.
- forward nudge 시 책상에서 바퀴를 띄울지(공회전) 바닥에 둘지(실제 전진)는 운용 선택 —
  안전상 **띄워서 방향만** 보는 것을 기본 권장(미확정, 사람이 판단).
- ENTER 시작 대기를 넣을지 여부(Stage 0 은 짧으므로 생략 가능) — 운용 결정 필요.
