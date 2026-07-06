# Stage 4 v2 — 중앙 상시 컬러 모드 라인추종 + 마커 색 판정 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3 실기 Done(`stage3v2_linetrace_branch.py`, 2026-07-02), 인프라 MVP
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."

관련 문서: 브릿지 후보 A~D([A](stage4a_reflect_only.md)/[B](stage4b_suspect_backup_color.md)/
[C](stage4c_reflect_gate_color.md)/[D](stage4d_mode_interleave.md)), 공통 부품 기준 문서
[stage4_color.md](stage4_color.md), 판단기록 [../DECISIONS.md](../DECISIONS.md),
라이브 튜닝 [../LIVE_TUNING.md](../LIVE_TUNING.md).

---

## 0. 배경 — 왜 v2 인가 (A~D 브릿지와의 관계)

기존 브릿지 후보 A~D 는 모두 **"라인추종은 반사광 3개"라는 전제**를 유지한 채, 컬러 모드
전환 비용(settle/더미읽기/blind 슬롯)을 언제·어떻게 치를지를 다뤘다. v2(사용자 방향 전환,
2026-07-03)는 전제 자체를 바꾼다:

> **중앙센서(in2)를 처음부터 끝까지 컬러 모드로 두고, 좌/우(in1/in3)만 반사광 모드로 쓴다.
> 그러면 반사광↔컬러 전환이 주행 중 0회가 된다** — A~D 가 브릿지하려던 문제가 사라진다.

성립 근거(코드 사실): stage3v2 의 PD 조향 `pd_step`(=`PdController.step`)은
`error = raw[2] - raw[0]` 로 **좌/우 반사광만 쓰고 중앙 raw 를 쓰지 않는다.** 중앙은
① bits 의 가운데 비트(분기/000 판정) ② 000 감속 판정에만 쓰인다. 이 흑백 정보는 컬러코드
(검정=1 → bit 1, 흰색=6 → bit 0)로 대체할 수 있다. 따라서 **Stage 3 확정 조향 수식·게인을
수정 없이 그대로 재사용**하면서 중앙만 컬러 모드로 바꿀 수 있다.

성립 조건(§7 실측으로 go/no-go):

1. 컬러 모드 판독이 15ms 제어 루프를 눈에 띄게 느리게 하지 않는다.
2. 검은 선 위에서 color 가 안정적으로 1(검정)이다(초록=3/갈색=7 오독이 드물다).
3. 마커색이 검정(1)/흰색(6)과 컬러코드 수준에서 구분된다.

이 중 하나라도 실기에서 깨지면 v2 를 폐기하고 기존 후보 C(반사광 게이트+컬러 확정)로
돌아간다. v2 가 성립하면 A~D 는 폐기 후보가 된다(§11).

부수 효과: **실패 #2(빈 바닥 색 측정)가 구조적으로 해소**된다 — 빈 바닥은 컬러 모드에서
흰색(6)으로 읽히고 6은 마커색이 될 수 없으므로, "바닥을 마커로 오독"이 판정 규칙상 불가능하다
(reflect 기반 `COLOR_FLOOR_WARN` 경고가 필요 없다).

## 1. 목표 / 범위

- **하는 것**: 좌/우 반사광 PD 라인추종(Stage 3 확정 수식 재사용)을 유지하면서, **주행 중**
  중앙 컬러코드를 매 루프 읽어 같은 마커색이 연속 N번이면 확정 →
  `COLOR_READ` + `NODE_IS_*`(시작/체크포인트/도착) 라벨을 남긴다. 주행은 계속한다.
- **하는 것**: `do read_color` 단일 트리거 — 정지 상태에서 색 N회 판독(다수결)+분류.
  §7 정지 실측(마커/선/바닥 색코드 수집)의 도구.
- **하는 것**: 중앙 컬러코드 기반 가운데 비트로 bits(`LCR`)를 유지해 000 감속(선 유실 시
  감속)을 Stage 3 과 동일하게 한다. bits 는 telemetry 로 흘려 2단계(분기판단) 실측 근거를
  쌓는다.
- **명시적으로 안 하는 것**:
  - **분기 판단/회전** — 사용자 지시로 "나중에"(이 트랙의 2단계). 이 코드에서는 110/011/111
    이 보여도 회전하지 않는다(§11).
  - 색을 보고 U턴/정지/종료 같은 **주행 결정** → Stage 5/6.
  - `stage3v2_linetrace_branch.py`·`lib/turns.py`·`lib/decide_turn.py` 등 확정 코드 수정.

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4v2_color_follow.py` (독립 실행 가능).
- 재사용(수정 금지): `stages.stage3v2_linetrace_branch` 의 `PdController`/`pd_step`/
  `bits_to_str`/`THR_LEFT`/`THR_RIGHT`(좌/우 threshold 43/42, 실기 1차 보정값),
  `lib/` 인프라(shared_params/telemetry/decision_log/tuning_server).
  `pd_step(pd, (l, 0, r), params)` 로 부른다 — **가운데 값은 수식에서 안 쓰이므로 0 을
  넣는다**(호출부 주석 필수).
- `lib/hardware.py` 에 **추가만**(기존 메서드/`__init__` 불변):

```python
hw.read_side_reflect() -> (l, r)
#   좌/우 반사광만. read_reflect() 는 중앙 반사광 속성을 읽어 중앙 모드를 COL-REFLECT 로
#   되돌리므로 이 트랙에서 쓰면 안 된다(핵심 함정, §8).
hw.read_center_color_now() -> int
#   in2 color 1회, 전환/settle 없음. 시작 시 read_center_color(기존 메서드)로 컬러 모드에
#   들어간 뒤 매 루프 호출한다(ev3dev2 는 모드가 같으면 재전환하지 않는다).
```

### 판단층(순수 함수, 하드웨어 없음)

```python
# color: ev3dev2 컬러코드 0=없음 1=검정 2=파랑 3=초록 4=노랑 5=빨강 6=흰색 7=갈색
center_bit_from_color(color) -> 0|1     # 흰색(6)/없음(0)만 0, 나머지(검정+마커색)는 1(선 위)
is_marker_color(color) -> bool          # 검정/흰색/없음 이 아닌 색(2,3,4,5,7)
classify_node_color(color, params) -> (kind, reason_code, detail)
#   kind: "START"|"CHECKPOINT"|"GOAL"|"UNKNOWN" (stage4_color.md §5 와 동일, 우선순위
#   GOAL→START→CHECKPOINT)
validate_node_colors(params, allow_duplicate) -> None | raise ValueError
side_bits(l_raw, r_raw, thr_l, thr_r) -> (l_bit, r_bit)
line_bits(l_raw, r_raw, color, thr_l, thr_r) -> (l, c, r)  # c = center_bit_from_color

marker_confirm_step(color, t_ms, state, confirm_count, cooldown_ms) -> color | None
#   state dict(marker_last/marker_count/last_marker_ms)를 갱신하는 순수 스텝.
#   같은 마커색 연속 confirm_count 회면 확정색 반환 + 쿨다운 시작. 마커색이 아니거나
#   (검정/흰색) 쿨다운 중이면 리셋. — 제어 루프와 replay 어댑터가 공유한다.

decide_marker(sensors, params, state) -> (kind, reason_code, detail)  # replay 어댑터
#   tools/replay.py --decider stages.stage4v2_color_follow:decide_marker
```

### 구동층(hw 경유)

```python
read_color_at_rest(hw, samples, delay_s, should_stop) -> (color, reads)
#   정지 상태에서 color 를 samples 회 읽어 다수결. do read_color 가 쓴다.
```

## 3. 라이브 params (정확히 6개)

| 이름 | 의미 | 기본값 | LIMITS | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `kp` | 조향 게인(좌/우 raw 차) | 0.22 (Stage 3 확정값 시드) | (0.0, 3.0) | 0.1 | 곡선 못 따라감 ↑ / 흔들림 ↓ |
| `base_speed` | 직진 속도(%) | 17 (Stage 3 확정값 시드) | (5, 45) | 5 | 마커 확정 미달(너무 빨리 통과) ↓ |
| `color_confirm_count` | 같은 마커색 연속 루프 수 | 3 | (1, 10) | 1 | 오탐(검정↔갈색 튐) ↑ / 마커 놓침 ↓ |
| `start_color` | 시작 마커 색코드 | 4(노랑) | (0, 7) | 7 | 실측 색코드로 설정 |
| `checkpoint_color` | 체크포인트 마커 색코드 | 2(파랑) | (0, 7) | 7 | 실측 색코드로 설정 |
| `goal_color` | 도착 마커 색코드 | 5(빨강) | (0, 7) | 7 | 실측 색코드로 설정 |

> 색코드 3개의 MAX_STEP 은 7 이다(기준 문서의 1 에서 의도적으로 변경): 색코드는 연속
> 물리량이 아니라 라벨이라 2→5 를 3번 나눠 갈 이유가 없고, 중간값(3,4)을 스치는 게 오히려
> 위험하다.

### config 상수(라이브 아님, 파일 맨 위)

| 이름 | 의미 | 기본값 |
|---|---|---|
| `THR_LEFT`/`THR_RIGHT` | 좌/우 흑백 threshold — stage3v2 에서 import(43/42) | import |
| `KD`/`TURN_LIMIT` | PD D항/조향 클램프 — stage3v2 `PdController` 내부값 그대로 | import(0.05/16) |
| `COLOR_ENTER_SETTLE_S` | 시작 시 컬러 모드 진입 settle(1회뿐) | 0.15 |
| `COLOR_ENTER_DUMMY_READS` | 진입 직후 버리는 읽기(1회뿐) | 2 |
| `MARKER_COOLDOWN_MS` | 마커 확정 후 재확정 금지 시간 | 1500 |
| `LOOP_DELAY_MS` | 제어 루프 주기 | 15 |
| `LOST_SLOWDOWN` | bits 000 감속 배율(stage3v2 와 동일) | 0.55 |
| `AT_REST_SAMPLES`/`AT_REST_DELAY_S` | `do read_color` 판독 횟수/간격 | 5 / 0.02 |
| `ALLOW_DUPLICATE_NODE_COLORS` | 색 3개 중복 허용(개발용) | False |
| `REASON_THROTTLE_S` | LINE_FOLLOW 로그 주기 | 0.25 |

## 4. telemetry 필드 / reason_code

### telemetry 추가/변경 키

| 키 | 의미 |
|---|---|
| `reflect_lr` | 좌/우 반사광 `[l, r]` (중앙 없음 — 컬러 모드) |
| `color` | 중앙 컬러코드(매 루프) |
| `bits` | `LCR` — 가운데는 color 기반 bit |
| `marker_count` | 진행 중인 마커 연속 카운트 |
| `last_marker` / `last_marker_color` | 마지막 확정 노드 종류/색코드 |

`error/turn/left_speed/right_speed/mode/paused/param_rev` 는 인프라·Stage 3 공통.

### reason_code — [../DECISIONS.md](../DECISIONS.md) 카탈로그와 일치

| reason_code | 언제 | detail |
|---|---|---|
| `COLOR_MODE_ENTER` | 시작 시 컬러 모드 진입(1회) | color, settle_ms, dummy |
| `COLOR_READ` | 마커색 확정(주행 중 method:"driving") / `do read_color`(method:"at_rest") | color, method, reflect_l, reflect_r, count |
| `NODE_IS_START`/`_CHECKPOINT`/`_GOAL`/`_UNKNOWN` | 확정색 → 노드 종류 | color |
| `LINE_FOLLOW` | 라인추종 중(throttle) | reflect_lr, color, bits, error, turn |

`COLOR_FLOOR_WARN` 은 이 트랙에 없다(§0 — 빈 바닥은 흰색(6)이라 마커 판정 자체가 안 됨).

## 5. 동작 로직 (의사코드)

> Python 3.5 안전(f-string 금지). 네트워크는 큐잉만, 제어 루프가 실행(stage3v2 pending 패턴).
> BACK 버튼 미사용, 정지는 네트워크 stop / Ctrl-C.

```python
run():
    validate_node_colors(초기 params, ALLOW_DUPLICATE_NODE_COLORS)   # 시작 자기검증
    hw = Ev3Hardware()
    c0 = hw.read_center_color(COLOR_ENTER_SETTLE_S, COLOR_ENTER_DUMMY_READS)  # 모드 진입(1회)
    log COLOR_MODE_ENTER(color=c0)
    state = {}   # marker_confirm_step 공유 상태

    loop:
        if stop_flag: hw.stop(); log EMERGENCY_STOP; break
        if paused:    hw.drive(0,0); telemetry; continue
        if pending "read_color":                       # do 트리거(정지 판독)
            hw.stop()
            color, reads = read_color_at_rest(hw, AT_REST_SAMPLES, AT_REST_DELAY_S, should_stop)
            l, r = hw.read_side_reflect()
            log COLOR_READ(method="at_rest", color, reflect_l=l, reflect_r=r, count=len(reads))
            kind, reason, detail = classify_node_color(color, snap); log reason(detail)
            continue                                    # 주행은 재개하지 않음(사람이 위치 이동)

        snap = params.snapshot()
        l, r = hw.read_side_reflect()                   # read_reflect() 금지(§8)
        color = hw.read_center_color_now()
        bits = line_bits(l, r, color, THR_LEFT, THR_RIGHT)

        # ---- 주행 중 마커 확정 (판단층 공유 스텝) ----
        confirmed = marker_confirm_step(color, now_ms(), state,
                                        snap["color_confirm_count"], MARKER_COOLDOWN_MS)
        if confirmed is not None:
            log COLOR_READ(method="driving", color=confirmed, reflect_l=l, reflect_r=r,
                           count=snap["color_confirm_count"])
            kind, reason, detail = classify_node_color(confirmed, snap); log reason(detail)
            telemetry(last_marker=kind, last_marker_color=confirmed)
            # 주행은 계속한다(정지/회전 없음 — Stage 4 범위)

        # ---- 라인추종 (Stage 3 확정 수식 재사용) ----
        left, right, error, deriv, turn = pd_step(pd, (l, 0, r), snap)  # 가운데 0 = 미사용
        if bits == (0,0,0): left *= LOST_SLOWDOWN; right *= LOST_SLOWDOWN
        hw.drive(left, right)
        LINE_FOLLOW throttle 로그 + telemetry
        sleep(LOOP_DELAY_MS)
```

## 6. 대시보드 / CLI 연동

- `do read_color` — 정지 상태 색 N회 다수결 판독 + 분류(§7 실측 도구, 재배포 0).
- 라이브 set: §3 의 6개.
- `Space` pause / `s` stop — 인프라 공통. 에이전트는 제안만(LIVE_TUNING.md).

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0. **정지 실측(선결)**: 로봇을 손으로 옮겨가며 각 위치에서 `do read_color` **5회씩** —
   검은 선 / 흰 바닥 / 각 마커. 색코드 표를 PROGRESS 에 기록. 확인할 것:
   - 검은 선 → 1(검정)이 5회 모두인가? (초록/갈색 오독 빈도가 여기서 보인다)
   - 흰 바닥 → 6(흰색)인가?
   - 각 마커 → 서로 다른, 검정/흰색이 아닌 코드가 안정적으로 나오는가?
   - **여기서 마커색이 튀거나 검정과 겹치면 v2 no-go 판단 재료다(§0). 마커를 EV3 가
     구분하는 색(파랑/초록/노랑/빨강/갈색)으로 바꾸는 것도 대안.**
1. **색코드 설정**: 실측값으로 `start/checkpoint/goal_color` set(각 1회, MAX_STEP 7).
2. **컬러 모드 주행 확인**: 마커 없는 직선+곡선에서 자동 추종. Stage 3 확정값 시드
   (kp 0.22 / base_speed 17)로 시작 — 추종이 Stage 3 과 다르게 흔들리면 **루프 주기 지연
   의심**(telemetry `t_ms` 간격 확인) → v2 성립 조건 ① 검증.
3. **주행 중 마커 판정**: 마커 하나를 통과시키며 `COLOR_READ(driving)`/`NODE_IS_*` 확인.
   - 마커를 놓침 → `color_confirm_count` ↓ (또는 `base_speed` ↓ — 단 한 번에 하나).
   - 검은 선 위에서 오탐(갈색 등) → `color_confirm_count` ↑.
4. **재현**: 세 마커 각각 왕복 여러 번 — 의도한 `NODE_IS_*` 만 나오면 Done 후보.

## 8. 실패 모드 & 진단

- **`read_reflect()` 호출로 컬러 모드가 풀림(구현 함정)**: 중앙 반사광 속성을 읽는 순간
  ev3dev2 가 모드를 COL-REFLECT 로 되돌린다 → 이 파일에서는 `read_side_reflect()` 만 쓴다.
  증상: color 가 갑자기 0/이상값 + 루프가 매번 모드 전환 비용을 냄(느려짐).
- **검은 선을 갈색(7)/초록(3)으로 오독**: `COLOR_READ(driving)` 오탐으로 보임 →
  `color_confirm_count` ↑. 그래도 잦으면 그 색은 마커색에서 제외(§7-0).
- **마커 통과가 빨라 confirm 미달**: `NODE_IS_*` 가 안 뜨고 telemetry `marker_count` 가
  N 미만에서 리셋 → `color_confirm_count` ↓ 또는 `base_speed` ↓.
- **컬러 판독이 루프를 느리게 함**: telemetry `t_ms` 간격이 LOOP_DELAY_MS+판독시간보다
  훨씬 큼 → v2 성립 조건 ① 위반, C 로 회귀 검토.
- **색 3개 충돌**: 시작 자기검증(`validate_node_colors`)에서 즉시 에러. 개발 중 의도적이면
  `ALLOW_DUPLICATE_NODE_COLORS=True`.

## 9. PC 검증

- `python3 -m py_compile stages/stage4v2_color_follow.py lib/*.py`.
- 단위 테스트 `tests/test_stage4v2_logic.py`:
  - `center_bit_from_color`: 1(검정)→1, 마커색(2,3,4,5,7)→1, 6/0→0.
  - `is_marker_color` / `classify_node_color`(우선순위 포함) / `validate_node_colors`(중복/범위).
  - `marker_confirm_step`: 연속 확정, 검정 끼어들면 리셋, 다른 마커색이면 1부터, 쿨다운 차단.
  - `decide_marker` replay: color 샘플 스트림 → confirm_count 별 확정 시점 재연.
  - `pd_step((l, X, r))` 가 가운데 값 X 에 불변임을 확인(§0 성립 근거의 회귀 테스트).
  - `read_color_at_rest`(가짜 hw): 다수결/조기 stop.
  - params 6개 안전 메타.
- replay: `tools/replay.py runs/<ts> --decider stages.stage4v2_color_follow:decide_marker
  --set color_confirm_count=5` 로 기록한 color 샘플에서 확정 시점 재연.

## 10. 구현 체크리스트

- [ ] `lib/hardware.py` 에 `read_side_reflect`/`read_center_color_now` **추가만**.
- [ ] 판단층 순수 함수 + `marker_confirm_step` + `decide_marker`(replay 어댑터).
- [ ] `stages/stage4v2_color_follow.py` 제어 루프(§5) + `do read_color` + pause/stop.
- [ ] 라이브 params 6개 + LIMITS/MAX_STEP/UI 메타, 시작 자기검증.
- [ ] DECISIONS.md 카탈로그에 `COLOR_MODE_ENTER` 추가, `COLOR_READ` 에 method:"driving" 주석.
- [ ] `py_compile` + `tests/test_stage4v2_logic.py` + 기존 테스트 회귀.
- [ ] §7 실기 보정 → 결과를 PROGRESS 에 기록(0번 표 필수), Done 판단.

## 11. 미해결 / 실기 확인 필요

- **성립 조건 3개(§0) 전부 실기로만 확정된다.** 특히 "컬러 모드 판독이 15ms 루프에서
  안정"과 "검은 선 위 color==1 안정"이 go/no-go. 깨지면 후보 C 로 회귀.
- **마커 실제 색 미정.** 2026-07-03 반사광 실측표(PROGRESS)에는 보라(26)/갈색(32)도
  있는데, **보라는 EV3 컬러코드에 없다**(0~7) — 보라 마커는 파랑/빨강으로 불안정하게 읽힐
  가능성이 높아 마커색으로 부적합할 수 있다. §7-0 실측으로 확정.
- **분기판단(2단계, 사용자 "나중에")**: bits 의 가운데 비트를 color 기반으로 바꾼 채
  `branch_side`+탱크 회전(stage3v2)을 얹는 구상. 단, **마커가 3센서 폭을 덮으면**(파랑
  reflect 15, 초록 7 — 좌/우 반사광에도 검정으로 잡힘) `111` 오탐으로 좌회전할 위험이
  있어, 마커 위 bits 실측(이 코드의 telemetry 로 수집됨)을 보고 설계한다.
- **A~D 후보의 지위**: v2 성립 시 A~D(및 D 의 `bench_toggle` 관문 TODO) 폐기. 실기
  확인 전에는 보류로만 표기(PROGRESS).
- **STAGES.md Stage 4 본문**("전환 settle/더미읽기" 라이브 params 언급)은 v2 채택 확정
  시점에 개정한다(Stage 3 v2 선례).
- **`do read_color` 후 주행 미재개**가 실측 워크플로우로 충분한지(재개 트리거가 필요한지)
  실기에서 확인.
