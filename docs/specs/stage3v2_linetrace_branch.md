# Stage 3 v2 — 라인트레이싱 + 분기 탱크 회전 구현 명세 (공식 Stage 3 구현체)

> 상태: REVIEWED — **2026-07-02 공식 Stage 3 로 채택**(사용자 결정, [PROGRESS.md](../../PROGRESS.md)
>       2026-07-02 로그). **같은 날 실기 Done 확정**(좌/우 분기 각각 여러 번 재현 성공, 흔들림
>       오회전 없음 — 사용자 확인). 실기 Done 표기는 명세가 아니라
>       [PROGRESS.md](../../PROGRESS.md) 의 🟢 로 한다(이 문서는 그 사실을 참고 표기만 한다).
> 선행: Stage 1 주행 기반(모터 부호 `left=base-turn`/`right=base+turn`·트림) 실기 Done,
>       Stage 2 탱크 회전([lib/turns.py](../../lib/turns.py)) 실기 Done, 인프라([00_infra_dashboard.md](00_infra_dashboard.md)) Done.
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 3 인용 — 코스 위 좌/우 분기 각각에서
>       **제자리(탱크) 90° 회전**으로 다음 선에 올라타 계속 추종하는 것을 여러 번 재현하고,
>       주행 흔들림에 오회전하지 않는다.

## 0. 배경 / 이 문서의 위치

- 실측 실험 스크립트 [stages/only_linetrace.py](../../stages/only_linetrace.py) 를 기반으로 한다.
  이 스크립트는 3센서 PD 라인추종 + **왼쪽 분기 감지 시 엔코더 회전**을 이미 하지만, 회전을
  파일 안에서 **인라인 `run_encoder_turn` 으로 중복 구현**한다.
- **v2 의 핵심 변경**: 회전을 Stage 2 에서 실기 Done 된 **`lib/turns.pivot`(엔코더 각도 +
  보정계수 탱크 회전)로 재사용**한다. 인라인 회전 코드는 제거한다(복붙 금지·AGENTS §1).
- **(2026-07-02 확정) 이 문서가 공식 Stage 3 명세다.** [stage3_node_detect.md](stage3_node_detect.md)
  (아날로그 centroid 노드 감지, 코드 미착수)는 이 트랙과 설계가 충돌해 **폐기**됐다 — 사용자
  결정, 경위는 [PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그. 더 이상 "둘 중 하나 선택"
  대기 상태가 아니다.

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

- [x] `only_linetrace.py` → `stage3v2_linetrace_branch.py` 정리·개명(2026-07-02, claude).
- [x] 인라인 `run_encoder_turn`/`wheel_dirs`/`encoder_target` 제거, `lib/turns.pivot` +
      `lib/decide_turn.decide_turn`(Stage 2 재사용) 호출로 대체.
- [x] `branch_side` 좌/우 일반화(110/111→left, 011→right).
- [x] `advance_straight`(엔코더 직진) + `branch_advance_mm` 반영.
- [x] 라이브 params **6개**로 축소(§3): kp/base_speed/turn_speed/turn_90_factor/
      branch_confirm_count/branch_advance_mm. threshold(43/36/42)·kd·turn_limit·
      turn_180_factor·post_turn_settle_ms·branch_cooldown_ms·loop_delay_ms·advance_speed·
      WHEEL_DIAM_MM 은 파일 상단 config 상수(`config/stage3v2_calib.json` 은 아직 미도입 —
      값이 적어 파일 상수로 충분하다고 판단, 필요해지면 분리).
- [x] telemetry/reason_code(`BRANCH_LEFT/RIGHT`) 반영 + DECISIONS.md 카탈로그 1줄 추가.
- [x] 판단층 단위 테스트(`tests/test_stage3v2_logic.py`, 14개) + replay 어댑터
      `decide_branch`(confirm_count/cooldown/좌우 흔들림 재연, `tools/replay.py` 스모크 확인).
- [x] Codex 교차검증(2026-07-02, `codex exec --model gpt-5.5`) 및 지적 반영(아래 §11.1).
- [x] 실기 보정 §7 완료 + `save` — 2026-07-02, 값: `kp=0.22`/`base_speed=17`/
      `turn_speed=6`/`turn_90_factor=0.66`/`branch_confirm_count=2`/`branch_advance_mm=30`
      ([PROGRESS.md](../../PROGRESS.md) "Stage 3 v2 실기 확정값" 참조).
- [x] 위 값으로 **좌/우 분기 각각 여러 번 재현** 확인(사용자, 2026-07-02) — 오회전 없음.
      **Stage 3 실기 Done.** [PROGRESS.md](../../PROGRESS.md) 상태판/로그에 반영됨.

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
- ~~**stage3_node_detect.md(아날로그)와의 관계**: v2(bits)와 공존/대체~~ — **확정(2026-07-02):
  v2 채택, 아날로그 폐기.** [PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그 참조.

### 구현 시 내린 판단(2026-07-02, claude) — Codex 교차검증에서 재확인 요청

- **자동 시작 유지**: `do follow` 트리거 게이팅 대신 only_linetrace 와 동일하게 **프로그램
  시작 즉시 추종**을 기본으로 뒀다(이미 실기 1차 보정된 동작을 그대로 유지해 위험을 줄이는
  선택). 수동 `do turn_left/turn_right/uturn` 은 그 위에 별도 큐(`pending["turn"]`)로
  얹어 회전 중엔 그 틱만 실행하고 넘어간다.
- **회전 판단층에 `lib/decide_turn.decide_turn` 추가 재사용**: 명세 §2 는 새 함수
  `turn_target_deg` 만 언급했지만, 그 목표각 계산은 Stage 2 `lib/decide_turn.py:
  target_degrees` 와 완전히 같은 공식이라 **직접 재사용**(얇은 래퍼로 위임)했다. 수동/자동
  회전 모두 `decide_turn(cmd, ...)` 한 곳을 거쳐 `TURN_LEFT`/`TURN_RIGHT`/`UTURN` reason 을
  만든다(중복 구현 없음). `lib/decide_turn.py` 자체는 수정하지 않았다.
- **텔레메트리 훅**: `lib/turns.pivot`/`advance_straight` 는 텔레메트리 파라미터가 없어,
  호출부에서 `should_stop` 콜백에 부수효과(`_tick_stop`)를 얹어 회전/전진 중 프레임을
  흘렸다(`pivot` 자체 미수정).
- **kd 는 라이브→config 상수로 전환, 공식은 그대로**: only_linetrace 는 `kd` 를 **라이브
  param** 으로 뒀고(`turn = kp*error + kd*derivative`), v2 §3 "config 로 내리는 값" 표는
  `kd(0.05)` 를 config 로 내리도록 지정한다. v2 는 같은 공식(D항 유지)에서 `kd` 만 파일
  상수 `KD=0.05` 로 고정했다(재배포 1회로만 조정, 라이브 6개엔 포함 안 함). 계산 자체가
  달라진 건 아니다.

### 11.1 Codex 교차검증(2026-07-02) 지적 + 반영

`codex exec --model gpt-5.5` 로 구현체+lib 코드를 명세/AGENTS 기준 검증받았다. 지적 5건과
처리 결과:

1. **[High, 코드 수정함] 분기 확정 카운터가 "같은 방향 연속"을 보장하지 않음.** 원래
   `branch_confirm_step` 은 `side is not None` 이면 직전이 좌였는지 우였는지 안 보고
   카운트를 올렸다 → `110/011/110/011` 처럼 좌우가 번갈아 흔들려도 `confirm_count` 에
   도달하면 **마지막으로 본 방향**으로 오회전할 수 있었다(실기 최우선 위험). **수정**:
   `branch_confirm_step`/`decide_branch`/`run()` 모두 `last_side` 를 들고 다니다 방향이
   바뀌면 카운트를 1로 재시작하도록 고쳤다. 회귀 테스트
   `test_branch_confirm_step_ignores_oscillation`/`test_decide_branch_ignores_oscillating_sides`
   추가(좌우 8회 교대 입력에서 confirm 이 전혀 안 뜨는지 확인).
2. **[Medium, 이미 반영됨] AGENTS/STAGES 기준 표준 Stage 3 구현이 아니라 실험 트랙.**
   명세 §0/§8 이 이미 "실험 통합 트랙"으로 명시하고 있고, PROGRESS 단계 상태판도 이 파일을
   Stage 3 공식 구현으로 취급하지 않는다(별도 작업 로그로만 기록) — 추가 조치 없음, 문서
   표현 유지.
3. **[Medium, 코드 수정함] `LINE_FOLLOW` reason 로그 누락.** follow 경로가 telemetry 만
   publish 하고 판단 기록을 안 남겼다(§4/DECISIONS.md 요구사항 미반영). **수정**:
   `stage3_node_detect.py` 의 `_maybe_follow_log` 패턴을 그대로 가져와(`REASON_THROTTLE_S
   =0.25`) follow 틱마다 주기적으로 `LINE_FOLLOW` 를 기록하게 했다. 단위테스트
   `test_maybe_follow_log_throttles` 추가.
4. **[Low/Medium, 코드 수정함] advance 중 stop 이 걸려도 `_run_turn()` 까지 진행.**
   `pivot()` 자체는 stop 이면 안 돌지만, `_run_turn()` 은 settle sleep·`TURN_LEFT/RIGHT`
   로그·beep 까지 그대로 실행돼 "실제로 안 돈 회전"이 기록에 남을 수 있었다. **수정**:
   `advance_straight` 직후 `should_stop()` 을 확인해 True 면 회전 단계 전체를 건너뛰고
   다음 루프(맨 위 EMERGENCY_STOP 처리)로 넘어가게 했다.
5. **[Low, 조치 불필요] `do follow` 가 명세 본문과 다름.** §11 "구현 시 내린 판단"에 이미
   자동 시작 유지가 의도적 차이로 기록돼 있어 추가 조치 없음(Codex 도 "문서화된 의도적
   차이"로 확인).

수정 후 재검증: `python3 -m py_compile stages/*.py lib/*.py tools/*.py tests/*.py`,
`tests/test_stage1_logic.py`~`test_stage3v2_logic.py`(14개, 신규 3개 포함) 전부 통과,
`tools/replay.py --decider stages.stage3v2_linetrace_branch:decide_branch` 스모크 재확인.
