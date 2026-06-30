# Stage 7 — 물체 집기 (그리퍼 + 초음파) 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 6(노드 탐색/복귀) 실기 Done. 그 위에 **초음파(in4) + 미디엄 모터(outC)**
>   를 더한다. 라인추종·노드·회전은 Stage 1~5, 탐색/복귀 골격은
>   [stage6_explore_return.md](stage6_explore_return.md).
> 통과기준(Done) — [../STAGES.md](../STAGES.md) Stage 7 인용:
>   "초음파로 전방 물체 감지 → 그리퍼로 집고 → 목표에 내려놓기.
>    물체를 안정적으로 집어 운반·하차. 주행/센싱 방해 없음."

이전 구현(`/home/emjdp/dev/ev3maze/robot/run/solver.py` 의 `_maybe_pick_object` /
`deliver`, `config.py` 9절)에 **초음파 감지 → 그립 → 도착에서 release** 의 검증된 구조가
있다. 이 명세는 그 **구조·안전조건만** 인용하고, 그립 각도·거리 등 물리값은 대부분
"미정/실기 확인 필요"(11절)다.

---

## 1. 목표 / 범위

- **하는 것**
  - 탐색(EXPLORE) 주행 중 **초음파(in4)** 로 전방 물체를 감지한다.
  - 감지하면 멈춰 **그리퍼(outC 미디엄 모터)** 로 집고(필요 시 살짝 들어 올림), 들고 주행을 잇는다.
  - **목표(도착 노드)** 에 닿으면 내려놓는다(release).
  - 감지·집기·내려놓기의 모든 결정에 reason_code 를 남긴다.

- **명시적으로 안 하는 것**
  - 탐색/복귀 알고리즘 자체: **Stage 6**. 본 단계는 그 주행 루프에 **감지/집기 훅만** 끼운다.
  - 라인추종·노드·회전·색: Stage 1~5 에서 확정. 수정하지 않는다.
    (라인추종층 = Stage 3 좌/중/우 3센서 `decide_line3`. 중앙센서 단일 PID 아님 — 2026-06-30 Stage 3 변경.)
  - 물체 2개 이상, 특정 위치에 정밀 적재, 물체 종류 구분: 범위 밖(가정: **물체 1개**,
    첫 감지 때 집고 도착에서 내려놓음 — 이전 구현 가정 인용).

---

## 2. 파일 / 인터페이스

### 새로 만들/수정할 파일
- `stages/stage7_gripper.py` — 진입점. Stage 6 의 EXPLORE→RETURN 에 물체 임무를 합친 실행.
  튜닝 상수는 파일 맨 위(3절).
- `lib/gripper.py` (신규, **순수 판단층**) — 거리 샘플 → "집어야 하나" 판정. 하드웨어 없음.
- 구동층: Stage 6 의 `io` 에 **그립/감지 메서드 추가**(아래). ev3dev2 의존은 구동층만.

### 판단층 ↔ 구동층 분리
[../DECISIONS.md](../DECISIONS.md) 0장. 감지 **판정**(순수)과 **모터 동작**(구동)을 나눈다.

**순수 판단층** (`lib/gripper.py`, replay/단위테스트 가능):
```
should_pick(distance_samples, params, holding, phase) -> (bool, reason_code)
    # distance_samples: 최근 거리(cm) 표본들
    # 조건(모두 만족해야 True):
    #   - not holding (이미 들고 있으면 안 집음)
    #   - phase == EXPLORE (탐색 중에만, 안전조건 5절)
    #   - 유효 표본이 detect_cm 미만이고 min_valid_cm 이상 (벽/부품 반사 노이즈 제외)
    #   - 그 표본이 confirm_samples 회 연속(한 번 튄 값에 안 속음)
    # 반환 reason_code: OBJECT_DETECTED / NO_OBJECT / ALREADY_HOLDING /
    #                   NOT_EXPLORE_PHASE / OUT_OF_RANGE / NOISE_TOO_CLOSE
in_range(d, params) -> bool   # min_valid_cm <= d < detect_cm
```

**구동층 io 에 추가** (ev3dev2; 시그니처 예시 — 이전 `Ev3Motion` 인용):
```
io.distance_cm()  -> float    # 초음파 전방 거리(cm)
io.grip()         -> None     # 미디엄 모터로 집게 닫기(+lift_degrees 만큼 들어 올림)
io.release()      -> None     # 집게 열어 내려놓기
io.holding        -> bool     # 현재 물체를 들고 있는지(상태 플래그)
```

### 주행 루프 훅 (인용 골격)
이전 `Ev3Motion.follow_to_node` 가 매 스텝 `_maybe_pick_object(label)` 를 부르는 구조를
인용한다. Stage 6 의 `io.follow_to_node` 에 **감지 훅 한 줄**을 끼운다(주행 비차단):
```
follow_to_node(label):
    while 라인추종 중:
        maybe_pick_object(label)     # ← 본 단계가 추가하는 훅
        ... (기존 추종/노드 감지) ...
```
> Stage 6 의 `follow_to_node` 가 본 단계에서 한 줄 늘어난다. 이는 "확정 코드 수정"이 아니라
> **합의된 확장점**이다 — PROGRESS 에 이유를 적고 별도 커밋([../../AGENTS.md](../../AGENTS.md) 5).

---

## 3. 라이브 params (6개 이하)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 |
|---|---|---|---|---|---|
| `detect_cm` | 이 거리(cm)보다 가까우면 물체로 봄 | 미정(8 후보) | (1, 50) | 1 | 너무 일찍 집으면 ↓, 늦으면 ↑ |
| `min_valid_cm` | 이 값 미만은 노이즈(벽/부품 반사)로 무시 | 미정(1 후보) | (0, 10) | 0.5 | 헛집음 잦으면 ↑ |
| `confirm_samples` | 연속 N회 감지돼야 확정(한 번 튐 방지) | 미정(3 후보) | (1, 10) | 1 | 오탐 잦으면 ↑, 반응 굼뜨면 ↓ |
| `grip_close_deg` | 집게 닫는 각도(도) | 미정 | (0, 360) | 10 | 물체 크기에 맞춤(덜 잡으면 ↑) |
| `grip_speed` | 그립 모터 속도(%) | 미정(40 후보) | (5, 100) | 5 | 물체 으스러지면 ↓ |
| `post_grip_settle_s` | 집/놓기 후 자세 흔들림 안정화(초) | 미정(0.2 후보) | (0, 2.0) | 0.05 | 집은 직후 라인 놓치면 ↑ |

> 6개 한도. `lift_deg`(들어 올림 각도, 0=안 함), `post_release_settle_s`,
> `detect_on_explore_only`(안전조건) 는 **검증된 기본값으로 `config/` 에 묻는다**.
> `lift_deg` 는 물체가 주행/센서를 가릴 때만 꺼내 만진다.

---

## 4. telemetry 필드 / reason_code

### 추가 telemetry 키
| 키 | 의미 |
|---|---|
| `distance_cm` | 초음파 전방 거리(주기 제한 로깅) |
| `holding` | 물체를 들고 있는지 |
| `grip_state` | `OPEN` / `CLOSED` |

### 새 reason_code — [../DECISIONS.md](../DECISIONS.md) 카탈로그에 추가
| reason_code | 언제 | 같이 남기는 detail |
|---|---|---|
| `OBJECT_DETECTED` | 거리 확정(집기 직전) | distance_cm, samples |
| `GRIP_CLOSE` | 집게 닫음 | grip_close_deg, grip_speed |
| `OBJECT_PICKED` | 집기 완료(holding=True) | - |
| `RELEASE` | 도착에서 내려놓음 | - |
| `PICK_SKIPPED_HOLDING` | 이미 들고 있어 감지 무시 | - |
| `PICK_SKIPPED_NOT_EXPLORE` | RETURN 등 비탐색이라 감지 안 함(안전조건) | phase |
| `DIST_NOISE_IGNORED` | min_valid_cm 미만(반사 노이즈) 무시 | distance_cm |

> 주행 중 매 스텝 거리는 `distance_cm` telemetry 로만 흘리고, **이벤트는 위 확정 시점에만**
> 남긴다(로그 폭주·주행 타이밍 방해 방지, [DECISIONS.md](../DECISIONS.md) 4·6장 정신).

---

## 5. 동작 로직 (의사코드)

> EV3 브릭 코드는 **Python 3.5 안전**(f-string 금지, `.format()`). 정지 플래그 확인은
> 구동층이 매 루프 책임(Stage 1~6 보장). 네트워크 비차단(snapshot)은 인프라 담당.

### 5-1. 순수 판단 (replay 대상)
```
def should_pick(samples, params, holding, phase):
    if holding:                      return False, "ALREADY_HOLDING"
    if phase != "EXPLORE" and params.detect_on_explore_only:
                                     return False, "NOT_EXPLORE_PHASE"
    valid = [d for d in samples if d >= params.min_valid_cm]
    if len(samples) and not valid:   return False, "NOISE_TOO_CLOSE"
    recent = samples[-params.confirm_samples:]
    if len(recent) < params.confirm_samples:
                                     return False, "NO_OBJECT"
    if all(in_range(d, params) for d in recent):
                                     return True,  "OBJECT_DETECTED"
    return False, "NO_OBJECT"
```

### 5-2. 구동 훅 (인용 골격: `_maybe_pick_object`)
```
def maybe_pick_object(label):
    if io.holding:
        return                                   # PICK_SKIPPED_HOLDING (조용히)
    if detect_on_explore_only and label != "EXPLORE":
        return                                   # PICK_SKIPPED_NOT_EXPLORE
    d = io.distance_cm()
    push_sample(d)                               # 최근 표본 버퍼
    ok, why = should_pick(samples, params, io.holding, label)
    if not ok:
        if why == "NOISE_TOO_CLOSE": emit(DIST_NOISE_IGNORED, distance_cm=d)
        return
    io.stop()
    emit(OBJECT_DETECTED, distance_cm=d)
    emit(GRIP_CLOSE, grip_close_deg=..., grip_speed=...)
    io.grip()                                    # 집게 닫기(+lift_deg)
    emit(OBJECT_PICKED)
    sleep(post_grip_settle_s)                    # 집은 뒤 자세 안정화

def deliver():                                   # 도착 노드에서 호출(Stage 6 종료 시점)
    if io.holding:
        emit(RELEASE)
        io.release()
        sleep(post_release_settle_s)
```

> `should_pick` 의 "연속 확인"은 순수 함수가 버퍼로 판정하지만, 구동에서 한 번 멈춘 뒤
> 재확인하는 방식(이전 구현)도 가능하다. 어느 쪽이든 **확정 전엔 집지 않는다**는 규칙은 동일.

### 5-3. 안전 조건 (반드시)
- **탐색 중에만 감지**: `detect_on_explore_only=True`. RETURN 때는 이미 내려놓았으므로
  벽/구조물 오탐을 막는다(인용). RETURN 에서 감지가 켜져 헛집으면 이 플래그부터 확인.
- **노이즈 하한**: `min_valid_cm` 미만은 무시. 분기 구조물·로봇 부품 반사 제외.
- **한 번만 집음**: `holding` 플래그로 중복 집기 차단.
- **주행 방해 금지**: 감지 훅은 매 스텝 거리 1회 읽기 + 순수 판정뿐. 그립 모터는 **멈춘 뒤**
  돈다(주행과 동시 구동 금지). settle 로 집은 뒤 라인 재포착을 보장.
- **네트워크 stop/watchdog 정지**가 그립 동작 중에도 우선(구동층 보장).
- **일시정지(Space/pause)**: 주행 루프는 인프라 공통대로 속도 0 유지 후 같은 목표를 이어간다.
  단 `grip()`/`release()` 1회 모터 동작은 짧고 원자적이므로 **동작 중간에는 끊지 않고**, 완료 후
  다음 루프에서 pause 를 반영한다(집는 중 멈춰 물체를 떨구지 않게).

---

## 6. 대시보드 / CLI 연동

`do <action>` (빠른 보정 루프, [DECISIONS.md](../DECISIONS.md) 3장):
- `do grip` — 그립 1회 닫기(물체 없이 각도/속도 보정).
- `do release` — 집게 열기.
- `do distance` — 현재 전방 거리(cm) 1회 출력(감지 거리 보정).
- `do pick_test` — 전방에 물체 둔 상태로 "감지→집기" 1세트 재현.

조정 가능한 키/파라미터: `detect_cm`, `min_valid_cm`, `confirm_samples`,
`grip_close_deg`, `grip_speed`, `post_grip_settle_s`.

`Space` 일시정지/재개(pause) — 인프라 공통([00_infra_dashboard.md](00_infra_dashboard.md)).
주행은 속도 0 유지 후 같은 목표를 이어가되, `grip`/`release` 모터 1회 동작 중에는 끊지 않는다
(5-3 안전 조건). 완전 정지는 `s`(stop).

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

1. **거리 읽기**: `do distance` 로 빈 전방/물체 있는 전방의 cm 를 기록 → `detect_cm`(둘
   사이값), `min_valid_cm`(헛값 하한)을 정한다.
2. **그립 각도/속도**: 물체 없이 `do grip`/`do release` 로 집게 여닫음 확인 → 물체를 두고
   `grip_close_deg` 하나만 조정(덜 잡으면 ↑, 으스러지면 `grip_speed` ↓).
3. **감지 안정**: `do pick_test` 반복. 헛집음이 잦으면 `confirm_samples`↑ 또는
   `min_valid_cm`↑. 한 번에 한 값.
4. **운반 안정**: 집은 직후 라인을 놓치면 `post_grip_settle_s`↑(필요 시 `lift_deg` 를
   config 에서 꺼내 살짝 들어 올림).
5. **통합**: Stage 6 EXPLORE 안에서 실제로 집고, 도착에서 release 되는지 1회 통과 확인.

---

## 8. 실패 모드 & 진단

| 증상 | 로그가 보여줄 것 | 진단 / 어떤 값 |
|---|---|---|
| 너무 일찍/늦게 집음 | `OBJECT_DETECTED` 의 distance_cm | `detect_cm` 조정 |
| 벽/분기 구조물을 물체로 헛집음 | `DIST_NOISE_IGNORED` 없이 OBJECT_DETECTED | `min_valid_cm`↑, `confirm_samples`↑ |
| 물체를 놓침(덜 잡음) | `GRIP_CLOSE` 후에도 운반 중 떨어짐 | `grip_close_deg`↑ |
| 물체가 으스러짐 | - | `grip_speed`↓, `grip_close_deg`↓ |
| 집은 직후 라인 놓침/휘청 | GRIP 직후 LINE_LOST | `post_grip_settle_s`↑, (config) `lift_deg` |
| RETURN 중 헛집음 | `PICK_SKIPPED_NOT_EXPLORE` 가 안 찍힘 | `detect_on_explore_only=True` 확인 |
| 도착에서 안 내려놓음 | RELEASE 이벤트 없음 | `deliver()` 가 도착 종료 시점에 호출되는지(Stage 6 연동) |
| 집기 때문에 노드/색 오판 | 그립 직후 NODE/COLOR 오확정 | 그립을 **멈춘 뒤** 실행하는지, settle 충분한지 |

---

## 9. PC 검증

- **문법**: `python3 -m py_compile stages/stage7_gripper.py lib/gripper.py`.
- **순수 함수 단위 테스트** (`lib/gripper.py`, ev3dev 불필요):
  - `should_pick`: holding/phase/range/noise/연속확인 각 분기가 기대 reason 을 내는가.
  - `in_range`: 경계값(min_valid_cm, detect_cm) 포함/제외.
  - 노이즈 내성: `[0.5, 0.5, 7]` 처럼 하한 미만이 섞인 표본을 헛집지 않는가.
- **replay**: 주행 중 기록한 `distance_cm` 표본 시퀀스를 `should_pick` 에 다시 흘려
  새 `detect_cm`/`confirm_samples` 로 감지 시점이 어떻게 달라지는지 확인(로봇 없이,
  [DECISIONS.md](../DECISIONS.md) 5장). 단, 그립 각도/물체 파지력 같은 물리는 실기 `do`.
- **Stage 6 시뮬 확장**(선택): `tests/sim_explore.py` 에 "특정 노드 도착 시 물체 발견"
  훅을 더해(이전 `sim_maze.py` 의 `obstacle_node` 인용) **집기→도착 내려놓기**가
  알고리즘 흐름에 끼어도 EXPLORE/RETURN 이 깨지지 않는지 확인.

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] 구동층 io 에 `distance_cm`/`grip`/`release`/`holding` 추가(ev3dev2, outC·in4).
- [ ] `lib/gripper.py` 순수 판단층: `should_pick`, `in_range`.
- [ ] Stage 6 `follow_to_node` 에 `maybe_pick_object` 훅 추가(합의된 확장, PROGRESS 기록).
- [ ] 도착 종료 시점에 `deliver()` 연동(Stage 6).
- [ ] reason_code 카탈로그([DECISIONS.md](../DECISIONS.md))에 4절 항목 추가.
- [ ] params/telemetry 노출(3·4절), 안전조건(5-3) 구현.
- [ ] `do grip/release/distance/pick_test` 트리거 연동.
- [ ] 단위테스트 + (선택) 시뮬 확장 PASS, `py_compile` 통과.
- [ ] (실기) 거리·그립 보정 → EXPLORE 중 집기 → 도착 내려놓기 1회 통과. PROGRESS 기록.

---

## 11. 미해결 / 실기 확인 필요

> **검토 반영 메모 (antigravity #1, #7) — Stage 7 구현 시 반영.**
> - **#1 초음파 비차단 읽기**: 아래 "감지 동시성" 의 권장 해법 — 구동층(`hardware.py`)에서
>   초음파를 **백그라운드 스레드로 주기 폴링**하고, 제어 루프는 그 최신 snapshot 만 읽는다
>   (블로킹 0). 초음파는 continuous 모드면 읽기 자체는 빠르나(수십 ms 는 과장), 모드/타이밍
>   변동을 스레드로 흡수해 PID 주기를 지킨다.
> - **#7 그리퍼 스톨 보호**: `io.grip()` 에 timeout 을 두거나 ev3dev2 스톨 감지로 닫힘 완료를
>   판정하고, 쥔 뒤 유지 토크를 낮춰(또는 off) 과전류·전압강하·브릭 리셋을 막는다.

- **그립 물리값 전부**: `grip_close_deg`, `grip_speed`, `lift_deg` 는 그리퍼 기구·물체
  크기에 전적으로 의존. 실기 `do grip` 으로만 정한다(현재 모두 추정/미정).
- **`detect_cm` / `min_valid_cm`**: 초음파 특성·물체 재질·코스 구조물 반사에 따라 다름.
  `do distance` 로 빈 전방/물체 전방을 재야 확정.
- **물체 위치·개수**: 가정은 물체 1개, 첫 감지 때 집고 도착에서 내려놓음(이전 구현 인용).
  코스가 다물체/지정 위치 적재면 규칙 보강 필요.
- **감지 동시성**: 매 스텝 `distance_cm()` 읽기가 라인추종 루프 타이밍을 흔드는지 실기
  확인(센서 모드/읽기 지연). 흔들면 N스텝마다 1회 읽기로 완화 검토.
- **그립 중 자세 변화**: 집게가 닫히며 무게중심이 바뀌어 직진/회전이 달라질 수 있음. 집은
  뒤 라인추종·회전 재보정이 필요한지 실기 확인(필요하면 그건 Stage 1/2 쪽 영향).
- **`deliver()` 호출 위치**: Stage 6 의 EXPLORE 종료(도착 색 확인) 시점에 정확히 한 번
  호출되도록 두 단계의 경계를 맞춰야 함. 도착이 분기형이면 색 읽기 위치와 함께 재검토.
- **lift 가 센서 시야를 가리나**: 들어 올린 물체가 중앙 컬러센서/초음파 시야를 가리면
  노드·색 오판. `lift_deg` 와 센서 배치 실기 확인.
