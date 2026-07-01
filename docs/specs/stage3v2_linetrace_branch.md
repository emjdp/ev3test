# Stage 3 v2 — 라인트레이싱 + 분기 탱크 회전 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 1 주행 기반(모터 부호 `left=base-turn`/`right=base+turn`·트림) 실기 Done,
>       Stage 2 탱크 회전([lib/turns.py](../../lib/turns.py)) 실기 Done, 인프라([00_infra_dashboard.md](00_infra_dashboard.md)) Done.
> 통과기준(Done): 선 추종 중 좌/우 분기를 만나면 **제자리(탱크) 90° 회전**으로 다음 선에
>       올라타 계속 추종. 각 회전을 여러 번 재현하고, 주행 흔들림에 오회전하지 않는다.
>       (STAGES.md Stage 3 "노드 감지" + Stage 5 "노드에서 분기 회전" 을 잇는 **실험 통합 트랙**.)

## 0. 배경 / 이 문서의 위치

- 실측 실험 스크립트 [stages/only_linetrace.py](../../stages/only_linetrace.py) 를 기반으로 한다.
  이 스크립트는 3센서 PD 라인추종 + **왼쪽 분기 감지 시 엔코더 회전**을 이미 하지만, 회전을
  파일 안에서 **인라인 `run_encoder_turn` 으로 중복 구현**한다.
- **v2 의 핵심 변경**: 회전을 Stage 2 에서 실기 Done 된 **`lib/turns.pivot`(엔코더 각도 +
  보정계수 탱크 회전)로 재사용**한다. 인라인 회전 코드는 제거한다(복붙 금지·AGENTS §1).
- 표준 [stage3_node_detect.md](stage3_node_detect.md)(아날로그 노드 감지, 문서만)와는 **다른
  트랙**이다. v2 는 bits 기반 only_linetrace 계열이고, 실기에서 어느 쪽으로 갈지는 §11 에서
  결정한다. **둘 중 하나가 실기 Done 되면 다른 문서의 상태를 정리한다.**

### 0.1 회전 방식 명확화 (탱크 vs 컴퍼스) — 반드시 읽는다

- **탱크(제자리) 회전** = 좌회전 시 좌바퀴 후진(−)/우바퀴 전진(+), 우회전은 반대. 회전축이
  **차체 중심**이라 위치 이동 없이 몸의 방향만 90° 꺾인다. ← **v2 가 쓰는 방식.**
- **컴퍼스 회전** = 한 바퀴 고정, 반대 바퀴만 전진. 회전축이 고정 바퀴라 몸이 그 바퀴를 중심으로
  호를 그린다(위치가 옮겨짐).
- **현재 코드는 이미 탱크 부호다**: [lib/turns.py:22](../../lib/turns.py) `_DIRS` 와
  [only_linetrace.py](../../stages/only_linetrace.py) `wheel_dirs` 모두
  좌=`(-1,+1)`·우=`(+1,-1)`. 실기에서 컴퍼스처럼 보였다면 **코드 설계가 아니라 실기 원인**
  (한 모터 미응답/부호 반대, 좌우 트림 불균형, 브레이크 비대칭, 배터리 저전압)일 수 있다 → §8·§11.
- **기하(base 값 근거)**: 제자리 90° → 각 바퀴가 도는 호 = 90°×(트랙/2), 바퀴 회전각 =
  90 × 트랙/지름 ≈ 90 × 120/56 ≈ **193°**. 이것이 `BASE_PIVOT_DEG_90`. (컴퍼스라면 움직이는
  한 바퀴가 ≈386° 필요.) 즉 **base 는 탱크값 193 로 두고, factor 로 실측 미세보정**한다.

## 1. 목표 / 범위

- **하는 것**:
  - 3센서(좌/중/우 반사광) bits + PD 라인추종(only_linetrace 유지).
  - 좌/우 분기 감지 → **제자리 탱크 회전으로 90° 꺾기**(`lib/turns.pivot` 재사용).
  - 회전량은 `turn_90_factor` 로 실기 보정(Stage 2 방식 그대로).
  - **회전 시점(트리거) 튜닝 가능**: 분기 확정 연속횟수 + 확정 후 전진거리 두 손잡이.
  - 회전 후 선 재포착(중앙비트 복귀)까지.
- **안 하는 것(다음 단계)**: 색 판정(Stage 4), 노드 종류 트리 판별(십자/T 구분)·탐색/복귀
  (Stage 6), 미리 입력한 회전 **시퀀스** 재생(Stage 5 완전판). U턴(막다른 길)은 옵션(§11).

## 2. 파일 / 인터페이스

- 신규: `stages/stage3v2_linetrace_branch.py` — only_linetrace.py 를 정리·개명. 인라인
  `run_encoder_turn`/`wheel_dirs`/`encoder_target` 제거하고 `lib/turns.pivot` 호출로 대체.
- 재사용(수정 없이 import):
  - [lib/turns.py](../../lib/turns.py) `pivot(hw, action, target_deg, turn_speed, should_stop, should_pause)`
    — 이미 탱크 부호·엔코더 폴링·stop/pause 대응. **여기서는 안 고친다.**
  - [lib/hardware.py](../../lib/hardware.py) `reset_encoders/read_encoders/drive_raw/drive/stop/read_reflect/beep_ok`.
  - `lib/shared_params`, `lib/telemetry`, `lib/tuning_server`(인프라 공통).
- 판단층(순수, ev3dev2/시간/모터 없음 — PC 테스트/replay 가능):
  - `black_bits(raw, params) -> (l, c, r)` — 센서별 threshold 로 흑/백.
  - `branch_side(bits) -> 'left' | 'right' | None` — `110`/`111`→left, `011`→right.
    단독 드리프트(`100`/`001`)는 분기가 아님(중앙이 살아 있어야 분기로 본다).
  - `pd_step(raw, params, state) -> (left_speed, right_speed, error, derivative, turn)` (기존 PdController).
  - `turn_target_deg(action, params) -> deg` — `BASE_PIVOT_DEG_90*turn_90_factor` 또는
    `BASE_PIVOT_DEG_180*turn_180_factor`.
- 구동층: `advance_straight(hw, mm, speed, should_stop, should_pause)` — 엔코더 직진 전진(회전 전
  차체 중심을 교차점에 올리기). `mm→deg` 는 `WHEEL_DIAM_MM`(config 상수) 사용.

## 3. 라이브 params (6개) — 나머지는 config

회전 거동에 초점. 6개 한도(AGENTS §1)에 맞춰 아래 6개만 라이브로, 나머지는 config 상수/파일.

| 이름 | 의미 | 기본 | LIMITS | MAX_STEP | 올림 / 내림 |
|---|---|---|---|---|---|
| `kp` | 조향 게인 | 0.22 | 0.0..3.0 | 0.1 | 곡선 못 따라감 ↑ / 흔들림 ↓ |
| `base_speed` | 직진 속도(%) | 12 | 5..45 | 5 | 빠르게 ↑ / 곡선·정확도 ↓ |
| `turn_speed` | **탱크 회전 속도(%)** | 6 | 5..40 | 5 | 빠르게 ↑ / 오버슛 나면 ↓ |
| `turn_90_factor` | **90° 보정계수** | 1.0 | 0.5..2.0 | 0.05 | 덜 돌면 ↑ / 더 돌면 ↓ |
| `branch_confirm_count` | **분기 확정 연속횟수(오탐 방지)** | 4 | 1..20 | 2 | 오탐 ↑(올림) / 놓침 ↑(내림) |
| `branch_advance_mm` | **확정 후 회전 전 전진거리 = 회전 시점** | 20 | 0..120 | 10 | 일찍 돌면 ↑ / 지나치면 ↓ |

- **config 로 내리는 값**(라이브 아님, 재배포 1회로 조정):
  - 센서 threshold `thr_left/center/right` — 실측 시드 43/36/42 를 `config/stage3v2_calib.json`
    또는 파일 상단 상수로. (센서 캘리브는 자주 안 바꾸므로 config.)
  - `kd`(0.05), `turn_180_factor`(0.8), `turn_limit`(16), `post_turn_settle_ms`(90),
    `branch_cooldown_ms`(1500), `loop_delay_ms`(15), `advance_speed`, `WHEEL_DIAM_MM`(56 가정).
- **대안 세트**(§11 결정): threshold 를 라이브로 두고 싶으면 `base_speed`/`turn_speed` 중 하나를
  config 로 내려 6개를 맞춘다. 회전 시점 두 손잡이(`branch_confirm_count`·`branch_advance_mm`)와
  `turn_90_factor` 는 사용자 요청의 핵심이라 **항상 라이브**로 남긴다.

## 4. telemetry 필드 / reason_code

- telemetry: `reflect`(l,c,r)·`bits`·`error`·`turn`·`left_speed`/`right_speed`·`branch_seen`·
  `mode`(`follow`/`branch_left`/`branch_right`/`advancing`/`turning`)·`target_deg`·`enc_l`/`enc_r`/
  `enc_avg`·`advance_mm` + 공통 `t_ms`/`param_rev`/`running`.
- reason_code(‑ DECISIONS.md 카탈로그와 일치, 없으면 1줄 추가):
  - `BRANCH_LEFT` / `BRANCH_RIGHT` — detail: `bits`·`branch_seen`·`advance_mm`·`reflect`.
  - `TURN_LEFT` / `TURN_RIGHT`(Stage 2 재사용) — detail: `target_deg`·`factor`·`turn_speed`·
    `enc_avg`·`error_deg`.
  - `LINE_FOLLOW`(throttle) · `EMERGENCY_STOP`.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크 비차단(snapshot). BACK 버튼 미할당.

```
loop while not stop:
    snap = params.snapshot()
    raw  = hw.read_reflect()            # (좌, 중, 우)
    bits = black_bits(raw, snap)
    side = branch_side(bits)            # 'left' | 'right' | None
    in_cooldown = (now - last_turn_ms) < CONFIG.branch_cooldown_ms

    if side and not in_cooldown: branch_seen += 1
    else:                       branch_seen  = 0

    if branch_seen >= int(snap.branch_confirm_count):
        hw.stop(); log BRANCH_LEFT/RIGHT (bits, branch_seen)
        # (1) 회전 시점: 확정 후 교차점 위로 전진
        advance_straight(hw, snap.branch_advance_mm, CONFIG.advance_speed, should_stop, should_pause)
        # (2) 제자리 탱크 회전 — Stage 2 검증 코드 재사용
        action     = 'LEFT90' if side=='left' else 'RIGHT90'
        target_deg = BASE_PIVOT_DEG_90 * snap.turn_90_factor
        actual = turns.pivot(hw, action, target_deg, snap.turn_speed, should_stop, should_pause)
        log TURN_LEFT/RIGHT (target_deg, actual, error_deg)
        pd.reset(); branch_seen = 0; last_turn_ms = now
        continue                         # 다음 루프에서 중앙비트로 선 재포착

    # 라인추종
    l, r, err, d, turn = pd.step(raw, snap)
    if bits == (0,0,0):  l *= 0.55; r *= 0.55     # 전부 흰색이면 감속(직전 조향 유지)
    hw.drive(l, r)
    telemetry.publish(...); sleep(CONFIG.loop_delay_ms)
```

- `advance_straight`: `reset_encoders` → 양 바퀴 전진(`advance_speed`) → `enc_avg >= mm_to_deg(mm)`
  까지 폴링(중간 stop/pause 대응). `mm=0` 이면 전진 없이 바로 회전.
- 정지: 네트워크 `stop` → 플래그만(폴링/대기 루프가 안전 시점 처리), Ctrl-C 처리.

## 6. 대시보드 / CLI 연동

- `do turn_left` / `do turn_right` / `do uturn` — **수동 회전 트리거**(Stage 2 처럼 factor 보정용,
  선 없이 제자리 회전만). 내부적으로 `turns.pivot` 호출.
- `do follow` — 라인추종+분기 자동(1세트) 시작. (자동 시작으로 둘지는 §11.)
- `Space` pause/resume, `stop` 정지(인프라 공통).
- 조정 키: §3 의 라이브 params 6개(UI_STEP: kp 0.01, factor 0.01, count 1, advance_mm 10 …).

## 7. 보정 절차 (실기, 한 번에 변수 하나)

1. **센서 threshold**(config, 재배포): 실측 43/36/42 로 시작. 중앙 선 위 `010`, 흰 바닥 `000`
   확인. (자주 안 바꿈.)
2. **`kp`**: 직선 곧게·곡선 부드럽게. 흔들리면 ↓, 못 따라가면 ↑.
3. **`base_speed`**: 추종 안정 확인 후 조금씩 ↑.
4. **회전량 `turn_90_factor`**: `do turn_left` **반복** → 바닥 90° 표시에 맞춤 → `do turn_right`
   로 우회전 확인(대칭 안 맞으면 §11 에서 좌/우 factor 분리). **재배포 없이** 이 값만 돈다.
5. **`turn_speed`**: 너무 빠르면 오버슛 → 정확도와 trade 로 조정.
6. **회전 시점**: 먼저 `branch_confirm_count` 로 **오탐 제거**(직선에서 회전 안 하게) →
   그다음 `branch_advance_mm` 로 **교차점 위에서 돌게**(일찍 돌면 ↑, 지나치면 ↓). 값 하나씩.
7. 모든 분기에서 제자리 90° 로 다음 선에 올라타면 `save`. → PROGRESS 에 값·결과 기록.

## 8. 실패 모드 & 진단

| 증상 | 로그로 확인 | 고칠 값 |
|---|---|---|
| 분기 보고 **너무 일찍** 회전 | `enc_avg`(회전 시작 시점)·`advance_mm` | `branch_advance_mm` ↑ (confirm_count 는 이미 상한 근처) |
| 직선에서 **오회전** | `bits`·`branch_seen` | `branch_confirm_count` ↑ / threshold |
| 90° **안 맞음**(덜/더 돎) | `target_deg`·`error_deg` | `turn_90_factor` |
| **컴퍼스처럼** 한 바퀴만 돎 | `enc_l`/`enc_r` 한쪽만 증가 | 실기 점검: 모터 응답/부호(`drive_raw` 좌우), 트림, 브레이크, 배터리 → §11 |
| 회전 후 **선 못 올라탐** | 회전 후 `bits` 오랫동안 `000` | `branch_advance_mm`/`turn_90_factor`, 또는 회전 후 재포착 로직(Stage 5) |

## 9. PC 검증

- `python3 -m py_compile stages/*.py lib/*.py`.
- 단위: `black_bits`, `branch_side`(`110`/`111`/`011`/`010`/`000`/`100`/`001`),
  `turn_target_deg` 선형(factor 배수), `pd_step` 부호/클램프. `lib/turns.pivot` 는 기존
  self-test 재사용(도달/방향/조기정지).
- `replay.py`: 분기 트리거 타이밍(confirm_count 별 회전 발생 시점) 재연.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용)

- [ ] `only_linetrace.py` → `stage3v2_linetrace_branch.py` 정리·개명.
- [ ] 인라인 `run_encoder_turn`/`wheel_dirs`/`encoder_target` 제거, `lib/turns.pivot` 호출로 대체.
- [ ] `branch_side` 좌/우 일반화(only_linetrace 는 좌만).
- [ ] `advance_straight`(엔코더 직진) + `branch_advance_mm` 반영.
- [ ] 라이브 params **6개**로 축소(§3), 나머지 config 상수/`config/stage3v2_calib.json`.
- [ ] telemetry/reason_code(`BRANCH_LEFT/RIGHT`) 반영, 필요 시 DECISIONS.md 1줄 추가.
- [ ] 판단층 단위 테스트 + replay 시나리오(§9).
- [ ] 실기 보정 §7 → 값 확정 후 `save` + PROGRESS 기록. **그 전엔 Done 아님.**

## 11. 미해결 / 실기 확인 필요

- **탱크 vs 컴퍼스 관측 불일치**: 코드는 이미 탱크 부호인데 실기서 컴퍼스처럼 보였다면 원인 규명
  필요(모터 응답/부호/트림/브레이크/배터리). 실기 로그 `enc_l`/`enc_r` 로 한쪽만 도는지 확인.
- **회전 시점 손잡이 2개면 충분한가**: `branch_confirm_count`(상한 20 근처) + `branch_advance_mm`.
  advance 없이 confirm 만으로 될지, 아니면 advance 가 주 손잡이가 될지 실기로 판단.
- **라이브 6개 셋 확정**: threshold 를 라이브로 둘지(그럼 `base_speed`/`turn_speed` 중 하나 내림).
- **좌/우 factor 분리**: 우회전이 좌회전과 대칭 아니면 `turn_90_factor` 를 좌/우로 나눔(Stage 2 §11 선례).
- **분기 방향 정책**: v2 는 "감지한 분기쪽으로 회전". 정해진 시퀀스(좌/직/우/U) 재생은 Stage 5.
- **`WHEEL_DIAM_MM`**: 56 가정 — 줄자 실측 후 갱신(`branch_advance_mm` 거리 정확도).
- **U턴(막다른 길) 포함 여부**: `UTURN180`+`turn_180_factor` 로 확장 가능(기본은 좌/우만).
- **`do follow` 자동 시작 vs 수동 트리거**: only_linetrace 는 시작 즉시 추종. 트리거식으로 바꿀지.
- **stage3_node_detect.md(아날로그)와의 관계**: v2(bits)와 공존/대체 — 실기에서 방향 확정 후 정리.
