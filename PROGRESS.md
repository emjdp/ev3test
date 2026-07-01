# PROGRESS — 진행 상황 + TODO

모든 에이전트가 공통으로 기록한다. **작업 후 반드시 갱신·커밋.**
규칙은 [AGENTS.md](AGENTS.md), 단계 정의는 [docs/STAGES.md](docs/STAGES.md).

## 현재 단계

**Stage 3 — 노드 감지 구현 + PC 검증 완료, 실기 검증 필요 (Stage 2 실기 Done)**
(Stage 1 은 2026-06-30 사용자 판단으로 실기 Done 처리 — 아래 상태판/로그 참조.)
**다음 단계는 Stage 3 가 실기 Done 된 뒤에야 Stage 4(색상코드 노드 판정)만 가능하다.**

## 단계 상태판

| 단계 | 상태 | 비고 |
|---|---|---|
| Stage 0 연결/포트 확인 | 🟢 실기 Done | Python 3.5.3, 좌/우 전진 정상. `in1` FAIL 출력은 실물 확인 후 무시하고 통과 처리 |
| Stage 1 기초 라인트레이싱 | 🟢 실기 Done | 2026-06-30 **사용자 판단으로 Done 처리**. 중앙센서 반사광 검정 0/흰색 10, target_reflect 6, base_speed 20 |
| Stage 2 원시 회전(좌/우/U) | 🟢 실기 Done | 2026-06-30 사용자 실기 보정 완료. 저장값: speed 18, 90 factor 0.9, 180 factor 0.8, settle 120ms |
| Stage 3 노드 감지 | 🟡 진행 중 | 2026-06-30 코드+PC검증(claude). 좌/중/우 bits, 3센서 추종(decide_line3), debounce, 노드 위 정지. **2026-07-01 실기 버그 수정**: 시작하자마자 오른쪽으로 꺾여 직진 불가 → 조향을 raw차(r-l)→**bits 위치 오차**로 재설계(아래 참조). **실기 재검증 필요** |
| Stage 4 색상코드 노드 판정 | ⬜ 시작 전 | |
| Stage 5 통합(트레이싱+회전) | ⬜ 시작 전 | |
| Stage 6 탐색/복귀 | ⬜ 시작 전 | |
| Stage 7 물체 집기 | ⬜ 시작 전 | |

상태 표기: ⬜ 시작 전 / 🟡 진행 중 / 🟢 실기 Done / 🔴 막힘

## 명세(docs/specs/) 검토 처리 현황

antigravity 검토 보고서(9개 지적)를 claude 가 재검토해 우선순위 재조정 후 반영. 상태 표기는
DRAFT/REVIEWED 2단계(실기 Done 은 명세가 아니라 이 PROGRESS 의 🟢 로 — [specs/README.md](docs/specs/README.md)).

- ✅ **near-term 반영 완료(REVIEWED 승격)**:
  - `00_infra_dashboard.md` — #2 브릭 통신 단일 채널(watcher만 상시접속·3~5Hz, 대시보드는 로컬 파일 읽기).
  - `stage1_linetrace.md` — #4 라인유실 상태전이 순수화(`decide_line`), #8 D항 EMA 필터(내부상수).
- ✅ **Stage 3 변경 전파(2026-06-30, claude)**: Stage 3 라인추종이 중앙센서 단일 PID 재사용 →
  좌/중/우 3센서(`lib/nodes.py:decide_line3`)로 확정됨에 따라, 이를 전제하던 하위 DRAFT 명세를 갱신.
  - `stage4_color.md`·`stage5_integration.md` — "Stage 1 라인추종 PID 재사용" → "Stage 3 3센서
    추종(`decide_line3`) 재사용, Stage 1 은 부호/속도 기반만"으로 본문+§11 검토 메모 반영.
  - `stage6_explore_return.md`·`stage7_gripper.md` — 재사용 컴포넌트 목록에 "라인추종층 = Stage 3
    3센서" 한 줄 주석 추가(나머지 DRAFT 유지). Stage 5 의 회전 후 재포착은 중앙비트(=3센서 bits[1])
    그대로라 변경 없음을 §11 에 명시.
- ✅ **해당 스테이지 11절에 검토 메모만 추가(DRAFT 유지, 그 단계 착수 시 반영)**:
  - `stage5` #6 LEAF U턴 강제 / `stage6` #3 복귀 노드패턴 검증·#5 재귀→명시스택 /
    `stage7` #1 초음파 백그라운드 폴링·#7 그리퍼 스톨 보호.
- ⏸ **보류**: #9(pre_uturn 등 미리 라이브 개방) — 6개 규칙상 실기 튜닝이 요구할 때 개방.
- 판정 근거: High 로 분류됐던 #1/#3/#5 는 Stage 6/7(먼 미래 DRAFT)이라 Stage 0/1 을 막지 않음.

## TODO (다음 할 일)

- [x] **Stage 0 스크립트 작성**: `stages/stage0_check.py` (py_compile 통과, f-string 없음). [claude]
- [x] **실기에서 Stage 0 실행** (`python3 stages/stage0_check.py`):
      Python 3.5.3 확정. outA/outB/outC OK, in2/in3/in4 OK. `in1` 은 두 번 모두
      `ColorSensor(in1) is not connected` 로 출력됐으나 사용자가 포트 이상 없음으로 판단해
      Stage 0 통과 처리. 좌/우 전진 방향 정상.
- [x] **인프라 MVP 빌드 — codex 담당.** 스테이지가 아닌 공용 도구라 지금 만들 수
      있다. 명세: [00_infra_dashboard.md](docs/specs/00_infra_dashboard.md) (REVIEWED).
      - 완료(하드웨어 무관, PC 검증): `lib/` shared_params·telemetry·decision_log·
        tuning_server·pid + `tools/` robotctl(get/set/stop/do/save/rollback/latest)·
        최소 dashboard·watcher·replay.
      - 확장 완료(하드웨어 무관, PC 검증): `describe` 계약(stage/params/actions), params
        UI 메타(step/unit), data-driven dashboard, 액션 반복/자동 재실행/coarse step.
      - `lib/hardware.py` 는 **Stage 0 실기 Done 후** (모터 극성·트림 결과 필요).
      - ⚠️ **MVP 한정**: 무거운 대시보드(그래프/자동튜닝)는 금지(LIVE_TUNING.md). py_compile + PC 테스트.
- [x] (Stage 1) **코드 작성 + PC 검증 완료** — `stages/stage1_linetrace.py`, `lib/hardware.py`,
      `tests/test_stage1_logic.py`. 판단층(순수)↔구동층(ev3dev2) 분리, params 6개, reason 4종. [claude]
- [x] **Stage 1 실기 Done — 사용자 판단으로 처리(2026-06-30).** ⚠️ 대화상에서 코스 추종/정지
      경로의 상세 실기 로그까지는 남기지 않았다. 추후 Stage 1 을 다시 만질 일이 생기면
      "Stage 1 실기 검증 필요" 표의 미확정 상수(조향 부호/트림/LINE_LOST_MARGIN/RECOVER_SPEED)를
      그때 확정한다. (Stage 0 도 같은 방식으로 사람이 Done 처리한 선례.)
- [x] (Stage 2) **코드 작성 + PC 검증 완료** — `stages/stage2_turns.py`, `lib/decide_turn.py`,
      `lib/turns.py`, `lib/hardware.py`(엔코더 메서드 추가), `tests/test_stage2_logic.py`. [claude]
- [x] **Stage 2 실기 Done — 사용자 판단으로 처리(2026-06-30).** 브릭 저장 파일 확인:
      `~/ev3test/config/stage2.json` = `turn_speed 18`, `turn_90_factor 0.9`,
      `turn_180_factor 0.8`, `post_turn_settle_ms 120`. 로컬 `config/stage2.json`에도 반영.
- [x] **Stage 3 착수 전 확인**: `docs/STAGES.md` / `docs/specs/stage3_node_detect.md` 읽고,
      Stage 2 확정 코드는 수정하지 않는다. [claude]
- [x] (Stage 3) **코드 작성 + PC 검증 완료** — `stages/stage3_node_detect.py`, `lib/nodes.py`,
      `lib/hardware.py`(좌/우 반사광 + enc_avg 추가만), `tests/test_stage3_logic.py`. [claude]
- [ ] SSH 포트포워딩 확인: `ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local`.

### Stage 3 실기 검증 필요 (다음에 브릭에서 할 일) — 한 번에 변수 하나

> 보정 루프: 노트북에서 `robotctl do follow` → 선 따라가다 노드에서 1정지 → 값 하나만
> 고치고 다시 `do follow`. 만질 값은 **로그가 짚는 것만**(DECISIONS.md 6장).

0. **3센서 추종 거동 먼저 확인(decide_line3).** 직선(`010`)에서 `turn≈0`(좌=우)으로 곧게 가는지,
   왼쪽이 더 검을 때(`110`/`100`) 왼쪽으로, 오른쪽이 더 검을 때(`011`/`001`) 오른쪽으로 도는지
   telemetry `bits`/`line_error3`/`turn`/`left_speed`/`right_speed` 로 본다. 흔들리거나 과조향이면
   **`FOLLOW_GAIN` 한 값만** 내리고(반대면 올리고) 재배포(라이브 아님 — 파일 상단 Stage 3 상수).
   곡선을 못 따라가면 `FOLLOW_BASE_SPEED`↓ 또는 `FOLLOW_GAIN`↑ 중 **하나만**. 노드 후보(`111`/`101`)
   에서 너무 빠르면 `FOLLOW_SLOW_SPEED`↓. 이 거동이 안정된 뒤 1번 threshold 보정으로 넘어간다.
1. **threshold 부터(센서별 1개씩).** 흰 바닥/검은 선에 각 센서를 두고 telemetry `reflect_l/c/r`
   raw 를 본다. **좌/우 센서(in1/in3)는 미실측** — Stage 1 중앙 실측(검정 0/흰색 10)을 따라
   `left/center/right_threshold` 기본 5로 시작했다. 흑·백 중간으로 한 센서씩 맞춘다.
   검증: 직선(`010`), 십자(`111`), 막다른길(`000`)에 올려두면 기대 bits 가 나와야 한다.
2. **`node_confirm_ms`.** 직선 구간에서 오감지(`NODE_*`) 없는 최소값. 일찍 확정되면 ↑,
   노드에서 못 멈추면 ↓. (replay 로 confirm 영향 먼저 확인 가능 — 아래.)
3. **`node_debounce_ms`.** 한 노드 두 번 잡으면 ↑, 가까운 두 노드 하나로 합치면 ↓.
4. **`node_advance`(핵심, 실패#1).** `NODE_CONFIRMED` 의 `dist_mm` 와 실제 멈춤 위치 비교 —
   오버슛이면 `node_advance` 만 내린다. 모자라면 올린다. confirm 과 동시에 만지지 않는다.
5. **`deg_to_mm` 환산계수**: `WHEEL_DIAM_MM=56` 은 가정(Stage2 와 동일). 줄자로 바퀴지름 실측
   후 stage3 상수 갱신(미확정이면 `dist_mm` 는 상대 비교용). [§11]
6. 모든 노드 종류(직선/좌·우 분기/T/십자/막다른길) 노드 위 정지 + 올바른 bits → `save`
   → `config/stage3.json`. **그 전에는 Stage 3 Done 으로 표시하지 않는다.**

| 미확정 상수/값 | 위치 | 현재값 | 확정 방법 |
|---|---|---|---|
| `left/right_threshold` 기본 | stage3 INITIAL_PARAMS | 5 | 좌/우 센서 미실측 — 실기 raw 보고 센서별 확정 |
| `WHEEL_DIAM_MM`(deg→mm) | stage3 상수 | 56.0(가정) | 줄자 실측 후 갱신 |
| `ADVANCE_SPEED` | stage3 상수 | 15 | advance 가 느리고 안정적인지 실기 확인 |
| `CONTINUE_AFTER_NODE` | stage3 상수 | False(1노드 1정지) | 코스 연속 통과 확인 시 True 검토 |
| `FOLLOW_GAIN` | stage3 상수 | 12.0 | bits 위치 오차(±1/±2)당 turn. 과조향/흔들림이면 ↓, 곡선 못 따라가면 ↑(한 값만) |
| `FOLLOW_BASE_SPEED` | stage3 상수 | 20 | Stage 1 기조. 곡선에서 빠르면 ↓ |
| `FOLLOW_TURN_LIMIT` | stage3 상수 | 35 | Stage 1 기조. turn 포화 잦으면 조정 |
| `FOLLOW_SLOW_SPEED` | stage3 상수 | 12 | 노드 후보(111/101) 저속 직진. 노드 지나치면 ↓ |

### Stage 2 실기 검증 결과 (2026-06-30 Done)

- 사용자 실기 보정 후 `robotctl save` 완료.
- 확인:
  - `python3 tools/robotctl.py get` 현재값이 아래 저장값과 일치.
  - 브릭 `~/ev3test/config/stage2.json` 내용이 아래 저장값과 일치.
- 저장값:
  - `turn_speed`: 18
  - `turn_90_factor`: 0.9
  - `turn_180_factor`: 0.8
  - `post_turn_settle_ms`: 120
- Done 판단: 사용자 요청에 따라 Stage 2 를 실기 Done 으로 표시. 이후 Stage 3 착수 가능.

| 확정/잔여 메모 | 위치 | 현재값 | 메모 |
|---|---|---|---|
| `BASE_PIVOT_DEG_90/180` | stage2 상수 | 193 / 386 (가정) | 실제 보정은 저장 factor 로 확정. 상수는 Stage 2 Done 후 수정하지 않음 |
| 회전 방향 부호(`_DIRS`) | lib/turns.py | 좌=(-,+)/우=(+,-)/U=(+,-) | 실기에서 사용 가능하다고 판단되어 유지 |
| 좌/우 계수 통합 vs 분리 | stage2 params | 통합(`turn_90_factor=0.9`) | 분리 없이 Done 처리 |
| U턴 방향 | lib/turns.py | 우회전과 동일 | `turn_180_factor=0.8` 로 Done 처리 |

### Stage 1 실기 검증 필요 (다음에 브릭에서 할 일)

1. **인프라 통합 동작**: 브릭에서 `python3 stages/stage1_linetrace.py` 실행 → 노트북에서
   `python3 tools/robotctl.py latest` 가 프레임 반환(서버/터널 OK), `set kp 0.85` 반영,
   범위·MAX_STEP 거부 응답, `stop` 으로 정지(EMERGENCY_STOP 이벤트) 확인.
2. **보정① target_reflect**: 중앙센서 raw 측정 완료. 검은색 `reflect=0`, 흰색 `reflect=10`.
   실기상 기준값은 `target_reflect=6` 정도가 적당해 보여 기본값에 반영.
3. **보정② 직진 트림**: 저속 직진 쏠림 보면 `lib/hardware.py` `LEFT/RIGHT_MOTOR_TRIM`
   상수 하나만 미세 조정(라이브 아님, 재배포 1회성).
4. **보정③ kp/kd**: 아직 미확정. `base_speed=20` 에서 `kp` 0.1씩 올리며 곡선 추종,
   진동하면 내리거나 `kd` 0.05씩. ki 는 0 유지.
5. **미확정값 실기 확정**: 아래 "Stage 1 실기 확정 필요 상수" 표.
6. **Done**: 직선+곡선 코스 끝까지 추종 + `robotctl stop`/Ctrl-C 정지. 확정 params `robotctl save`.

| 미확정 상수/부호 | 위치 | 현재값 | 확정 방법 |
|---|---|---|---|
| 조향 부호(`to_wheel_speeds` base∓turn) | stage1 §11 | `base-turn / base+turn` | 선 한쪽 치우칠 때 복귀 방향 보고 부호/좌우 확정 |
| `LINE_LOST_MARGIN` | stage1 상수 | 25 | 현재 흰색 reflect=10 / target=6 기준으로는 유실 판정이 거의 안 뜸. 필요 시 별도 한 변수로 검증 |
| `RECOVER_SPEED`(유실 시 거동) | stage1 상수 | 0(정지) | 정지 vs 저속 직진 중 실기 선택 |
| `LEFT/RIGHT_MOTOR_TRIM` | hardware 상수 | 1.0/1.0 | 보정②에서 쏠림 실측 |

## 작업 로그 (최신이 위로)

### 2026-07-01 — Stage 3 실기 버그 수정: 시작하자마자 우회전 (Agent: claude)
- **증상(실기)**: `do follow` 시작하자마자 직진 못 하고 바로 오른쪽으로 꺾여버림.
- **원인(로그 `runs/2026-07-01T09-11-12` 분석)**: `decide_line3` 의 조향이 `line_error3 =
  r - l`(좌/우 raw 반사광 차)였다. 그런데 **얇은 선 위에선 좌/우 센서가 둘 다 흰 바닥**이라
  이 차이는 선 위치가 아니라 두 센서의 '흰색 읽는 값' 불일치(캘리브레이션 편차)만 먹는다.
  현재 실기 대역에서 흰바닥 좌≈20 / 우≈14 → `line_error3 ≈ -6` 이 **상시** 걸려(선 위
  `010` 에서도) turn 음수 → 우측 바퀴 감속 → 시작부터 우회전. 값 튜닝이 아니라 설계 결함.
- **수정**: 3센서 구조는 유지(사용자 선택). 조향을 **bits 위치 오차**로 재설계 —
  `line_error3 = (l_bit - r_bit) × (중앙 놓쳤으면 2 else 1)`. `010`→0(직진, 중앙 폭 데드밴드),
  `110/100`→+1/+2(왼쪽 보정), `011/001`→-1/-2(오른쪽 보정). bits 는 이미 센서별 threshold 로
  잘려 흰바닥 편차가 없다. 부호/바퀴매핑(Stage 1 `left=base-turn`)은 유지. `FOLLOW_GAIN`
  2.0→12.0(±1→turn 12, ±2→24). `lib/nodes.py` + `stages/stage3_node_detect.py`.
- **검증(PC)**: `python3 lib/nodes.py`, `tests/test_stage3_logic.py` 통과. 회귀 가드 추가
  (좌/우 흰바닥 raw 20/14 불일치라도 `010`이면 turn 0). **실기 재검증 필요.**
- 노드 감지(bits/debounce/decide_node)·reason_code 카탈로그는 변경 없음 → 하위 스펙 전파 불필요.

### 2026-07-01 — Stage 6 복귀 경로 압축(삽질 제거)으로 명세 변경 (Agent: claude)
- **배경**: 사용자가 "복귀(RETURN) 때 갈 때 들어갔던 막다른 길을 또 되밟는다"는 비효율을 지적.
  코스는 **막다른 길이 전부 노드(잎)로 표시된 트리(사이클 없음)** 임을 확인. "분기 탐색 전 새
  분기를 만나 되돌아오는 것"은 루프가 아니라 트리의 정상 백트래킹 → 온라인 스택 압축으로 충분
  (그래프+BFS/Trémaux 불필요)으로 결론.
- **기존 알고리즘과 무엇이 다른가 (핵심)**:
  - **이전(인용 골격, `solver.py`)**: EXPLORE 의 모든 회전을 raw `path[]` 에 선형 기록하고,
    RETURN = `return_plan(path)` = **raw path 전체를 거꾸로+좌우반전**. → 막다른 길 진입 토큰까지
    그대로 역재생되어 **복귀 때도 똑같이 삽질**. (실패표의 그 증상이 설계상 예정된 결과였음.)
  - **변경 후**: raw `path[]`(폴백/검산용)와 **압축 `live[]`(살아있는 경로만)** 를 이중 기록.
    잎 체크포인트/보류(deferred)/완료서브트리에서 **분기로 U턴해 돌아오는 순간 그 가지를
    `live` 에서 통째 제거**(`prune`→`pop_dead_branch`, `del live[mark:]`). 도착에 닿으면 `live` =
    유일한 출발→도착 단순경로 = 최단. **`return_plan(live)`** = live 거꾸로+좌우반전 →
    RETURN 동선에 막다른 길이 끼지 않음.
  - **교차검증 추가**: 순수 함수 `simplify_path(raw)`(U턴 3-토큰 기하 환원: L U R=U, L U S=R,
    L U L=S, R U R=S, S U S=U …)를 따로 두고 **불변식 `live == simplify_path(path)`** 를 시뮬/replay
    에서 assert. 온라인 압축과 사후 압축이 다르면 분기 식별(`facing`)·기록 버그 알람.
  - **새 reason_code**: `PRUNE_DEAD_BRANCH`(mark, popped, reason=leaf/deferred/subtree_done).
- **수정 파일**: [docs/specs/stage6_explore_return.md](docs/specs/stage6_explore_return.md) 만
  (1·2·4·5·7·8·9·10·11절). 코드 미작성 — Stage 6 는 아직 시작 전(Stage 3 실기 Done 선행).
  `lib/explore.py` 구현 시 `pop_dead_branch`/`simplify_path`/`return_plan(live 입력)` 반영 + 불변식
  단위테스트가 체크리스트(10절)에 추가됨.
- **하위 명세 영향 없음**: `return_plan`/역순 참조는 stage6 한 곳뿐(grep 확인). DECISIONS.md
  reason_code 카탈로그 추가는 Stage 6 구현 시점에 4절과 함께 일괄(10절 기존 TODO 유지).
- **다음**: 실기 흐름은 여전히 Stage 3 실기 Done 이 먼저. Stage 6 착수 시 `tests/sim_explore.py`
  로 ⑥ "RETURN 에 막다른 잎 0" + ⑦ 불변식부터 PASS 시키고 브릭에 올린다.

### 2026-06-30 — pause/resume 검증 + Stage 4~7 명세 전파 (Agent: claude)
- **Codex 작업 검증(통과)**: `pause` 명령(tuning_server)·`Space` 토글(dashboard)·`pause/resume`
  (robotctl)·`should_pause` 위빙(lib/turns.pivot, stage3.advance)·Stage1/2/3 루프 pause 분기
  모두 확인. `python3 -m py_compile`(stages/lib/tools), `python3 lib/tuning_server.py`
  self-test, `pytest tests/`(35 passed) 전부 통과. Stage1 pause 분기는 `last` 갱신 뒤라 resume
  시 dt 튐 없음. stop 은 pause 분기보다 먼저 검사돼 pause 중에도 즉시 정지 가능. 구현 정상.
- **stage0 는 pause 불필요**: TuningServer/대시보드를 안 씀(연결확인 전용).
- **Stage 4~7 명세 전파(코드 없음, "4부터는 명세로만")**: 각 스펙 6절에 `Space` pause/resume
  의미를 인프라 공통으로 명시.
  - stage4: 라인추종/`advance` 중 속도 0 유지 후 같은 목표 이어감, `read_color` 등 단발은 멈춘 채.
  - stage5: `follow_to_node`/`turn`/`nudge` 가 pause 중 시퀀스·회전 목표를 버리지 않음.
  - stage6: `io` 인터페이스에 `io.paused()` 추가, watchdog 시간은 pause 동안 멈춰야 안전정지 오발 없음.
  - stage7: 주행은 pause 존중하되 `grip`/`release` 모터 1회 동작 중에는 끊지 않음(물체 떨굼 방지).
- **다음**: 브릭에서 Stage 1/2/3 각각 `Space` pause/resume 실기 확인(Codex 항목과 동일 TODO).

### 2026-06-30 — 대시보드 Space 일시정지/재개 semantics 정리 (Agent: codex)
- **검토 결과**: 기존 대시보드에서 `s` 는 `stop`(스테이지 루프 종료)이고, `Space`/`.` 는 마지막
  `do` 반복이었다. 사용자가 기대한 "잠깐 멈췄다가 다시 동작"과 달리 `stop` 은 EMERGENCY_STOP
  성격이라 재개가 안 되고, `Space` 는 follow/turn 반복이라 정지 키처럼 쓰기 애매했다.
- **수정**: `lib/tuning_server.py` 에 `pause` 명령 추가. `tools/dashboard.py` 는 `Space` 를
  pause/resume 토글로, `.` 를 마지막 `do` 반복으로 분리. `tools/robotctl.py` 에도
  `pause`/`resume` 추가.
- **구동 semantics**: `stop` 은 기존처럼 강한 종료 경로로 유지. `pause` 는 `hw.drive(0,0)` 또는
  `hw.drive_raw(0,0)` 으로 속도 0 을 유지하고 서버/제어 루프는 계속 산다. Stage 2 회전과 Stage 3
  `advance` 중 pause 는 엔코더 목표/거리 목표를 버리지 않고 resume 후 이어간다.
- **기록**: `PAUSE`/`RESUME` reason_code 를 DECISIONS.md 카탈로그에 추가. telemetry 에 `paused`
  필드를 실어 대시보드가 현재 상태를 표시하고 다음 Space 동작을 결정한다.
- **범위 주의**: Stage 1/2 는 실기 Done 이지만 튜닝값/판단값은 수정하지 않았고, 공용 안전/대시보드
  semantics 만 추가했다. 그래도 브릭에서 Stage 1/2/3 각각 `Space` pause/resume 실기 확인 필요.
- **PC 검증(통과)**: `python3 -m py_compile stages/*.py lib/*.py tools/*.py`,
  `python3 lib/tuning_server.py`, `tests/test_stage1_logic.py`, `tests/test_stage2_logic.py`,
  `tests/test_stage3_logic.py`.

### 2026-06-30 — Git 정책 변경: 원격 없음 → GitHub origin 팀 공유 (Agent: claude)
- **원인 분석**: `git status` 의 "ahead of origin/master by 10 commits" 는 손상이 아니라,
  AGENTS.md §3("원격 없음")과 달리 GitHub origin 이 연결돼 있고 `origin/master` 추적 ref 가
  `ab695e8`(Stage0)에 멈춰 있어 그 뒤 로컬 10커밋이 미push 상태였기 때문. 워킹트리는 clean.
  (부차: `refs/codex/turn-diffs/*` 체크포인트 ref 는 Codex 툴 내부용, 사용자 결정으로 그대로 둠.)
- **정책 변경(사용자 결정)**: 팀원과 공유하게 되어 "원격 없음" 규칙을 폐기. AGENTS.md §3 을
  "원격 공유: GitHub origin"으로 갱신(push/pull 규약, force-push 금지, 정책 변경 시점 메모 추가).
- **조치**: AGENTS.md+PROGRESS 커밋 후 `master` 를 origin/master 로 push(누락 10+커밋 동기화).

### 2026-06-30 — Stage 3 3센서 추종 변경을 하위 DRAFT 명세에 전파 (Agent: claude)
- **배경**: 직전 커밋에서 Stage 3 라인추종이 Stage 1 중앙센서 단일 PID 재사용 → 좌/중/우
  3센서(`lib/nodes.py:decide_line3`)로 바뀌었다. 이를 "Stage 1 라인추종을 가져온다"고 전제하던
  하위 DRAFT 명세가 stale 해져 갱신(코드 구현 아님 — 미래 단계 코드 금지 §1 준수).
- **stage4_color.md**: 재사용 대상 라인추종을 `decide_line3`(+Stage 3 노드 감지)로 수정. §11 에
  Stage 3 변경 전파 검토 메모 추가(색 읽기 위치/`node_advance` 손잡이는 Stage 3 그대로).
- **stage5_integration.md**(가장 영향 큼): 선행/§1 범위/§2 재사용 인터페이스/§3 params 재사용
  목록/§5 의사코드/§10 체크리스트의 "선 추종(Stage 1)" → "선 추종(Stage 3 3센서 `decide_line3`)"
  로 일괄 수정. §11 에 ① 라인추종 거동은 Stage 3 파일 상수(`FOLLOW_*`)로 보정 ② 회전 후 재포착은
  중앙비트(=3센서 `bits[1]`)로 Stage 2 PivotTracker 그대로(변경 없음) 명시.
- **stage6/stage7**: 재사용 컴포넌트 목록에 "라인추종층 = Stage 3 3센서 `decide_line3`" 주석 1줄.
- **검토 처리 현황** 절에 "Stage 3 변경 전파" 항목 기록.
- 문서만 변경 → 코드/테스트 영향 없음. `git grep` 으로 "Stage 1 라인추종 재사용" 잔존 표현 정리 확인.

### 2026-06-30 — Stage 3 주행 판단을 좌/중/우 3센서로 교체(중앙센서 PID 제거) (Agent: claude)
- **문제**: Stage 3 가 Stage 1 중앙센서 PID(`decide_line`)를 그대로 import 해 라인추종했다.
  중앙센서가 검정 위에 있으면 `target_reflect` 오차로 바로 크게 돌 수 있었다. Stage 3 는
  이미 좌/중/우 bits 를 만들고 있으므로 **그 bits/raw 로 3센서 추종**하도록 고쳤다.
- **범위 유지**: 노드 감지 확정 로직(NODE_CANDIDATE/CONFIRMED·node_confirm_ms·node_debounce_ms·
  node_advance)·debounce·노드 위 정지는 그대로. **회전·색 판정·분기 선택은 추가하지 않음**(Stage 4/5).
- **lib/nodes.py**: 순수 함수 `decide_line3(raw, bits, params, state)` 추가(+`make_follow_state`).
  - 출력 action: `left/right/turn/error/line_error3/line`.
  - 부호는 Stage 1 하드웨어 기준 유지: `turn>0 → left=base-turn, right=base+turn`(왼쪽으로 돈다).
  - `010`→turn 0 직진, `100/110`→왼쪽 보정(turn>0), `001/011`→오른쪽 보정(turn<0).
  - `line_error3 = r - l`(왼쪽이 더 검으면 l 작음 → 양수 → 왼쪽). gain·clamp 는 follow 상수.
  - `111/101`→노드 후보: 저속(slow_speed) 직진(turn 0, 노드에서 멈추기 유리). 멈춤은 debounce.
  - `000`→DEAD_END 후보: 확정 전 짧은 순간엔 **속도 0(정지) + 직전 조향(last_turn) 유지**(보수).
- **stages/stage3_node_detect.py**: `stage1_linetrace`(decide_line/make_state/STAGE1_PID) **import 완전 제거**.
  follow gain/base/turn limit/slow speed 를 **파일 상단 Stage 3 내부 상수**(`FOLLOW_*`/`FOLLOW_CONSTS`)로
  두고, 제어 루프가 params 스냅샷에 **병합해 decide_line3 으로 전달**(lib 가 stages 를 import 하지
  않게 — 순환 참조 방지). 새 live param 추가 없음(여전히 6개). `_line_follow`→`_follow3`.
- **tools/dashboard.py**: `_telemetry_summary` 우선순위를 Stage 3 친화로 개선(bits/mode/reflect_l·c·r/
  node_candidate/node_confirmed/error·line_error3/turn/left·right_speed 가 첫 줄에). **있는 키만 표시**
  구조 유지 → Stage 1(reflect/error/turn/속도)·Stage 2(generic fallback) 표시 안 깨짐.
- **docs**: STAGES.md Stage 3 메모 + `docs/specs/stage3_node_detect.md` 를 "Stage 1 중앙 PID 재사용"
  → "Stage 1 하드웨어/주행 기반은 유지, 주행 판단은 좌/중/우 3센서"로 수정. 회전/색 없음·노드 정지까지 명시.
- **tests**: `tests/test_stage3_logic.py` 에 decide_line3 케이스(010/100·110/001·011/111·101/000) +
  `_telemetry_summary` 단위 테스트(Stage 3 키 포함·Stage 1 비파괴) 추가. 기존 debounce 테스트 유지.
- **PC 검증(통과)**: `python3 -m py_compile stages/*.py lib/*.py tools/*.py`,
  `test_stage1_logic.py`/`test_stage2_logic.py`/`test_stage3_logic.py`(22개), `lib/nodes.py` self-test.
- **실기 검증 필요**(아래 블록): threshold→confirm→debounce→node_advance 순은 그대로. 3센서 추종
  거동(`FOLLOW_GAIN`/`FOLLOW_BASE_SPEED`/`FOLLOW_SLOW_SPEED`)은 내부 상수라 **재배포 1회로** 만진다
  (라이브 아님). **Stage 3 Done 아님.**

### 2026-06-30 — 대시보드 save 상태 메시지 명확화(혼동 원인 규명) (Agent: claude)
- **증상**: 노트북 대시보드에서 `S`→`y` 로 저장하니 "어디에 저장됨" 경로는 떴는데 노트북에서
  그 파일을 못 찾음.
- **규명(코드 버그 아님)**: 저장은 **브릭의 튜닝 서버**(`stage2_turns.py run()` 안)가 수행한다.
  `tools/dashboard.py` 는 SSH 터널 너머 `{"cmd":"save"}` 만 보내고, 서버가 `params.save()` 로
  `SAVE_PATH`(`os.path.join(_ROOT,"config","stage2.json")`, _ROOT=실행 위치=브릭 `~/ev3test`)에
  쓴다. 상태줄에 뜬 경로는 **브릭 파일시스템 경로**(`/home/robot/ev3test/config/stage2.json`)라
  노트북엔 없었다. 실제 데이터는 브릭에 잘 저장됐고 codex 가 그 값을 로컬 `config/stage2.json`
  에 옮겨 커밋(b7e8ec0)했다 — 유실 없음.
- **수정**: `tools/dashboard.py` `_compact_response` 의 save 응답 표시를
  `ok saved=<경로>` → `ok saved on robot: <경로>` 로 바꿔, 그 경로가 로봇(브릭) 쪽임을 명시.
  단순 표시 문구라 동작/계약 영향 없음(테스트 영향 없음). 대시보드는 노트북에서 실행 → scp 불필요.
- **PC 검증**: `python3 -m py_compile tools/dashboard.py` 통과.

### 2026-06-30 — Stage 3 노드 감지 구현 + PC 검증 (Agent: claude)
- **게이트**: Stage 2 가 🟢 실기 Done(상태판) 확인 → Stage 3 착수. Stage 4 색판정·Stage 5
  통합회전·Stage 6 탐색은 구현하지 않음(회전·색읽기 금지, 노드 위 정지까지만).
- **범위**: 좌·중·우 3센서 반사광 → threshold → bits(`LCR`) → debounce 로 노드 후보/확정.
  Stage 1 라인추종(중앙센서 PID)을 수정 없이 import 재사용해 "선 따라가다 노드에서 멈춤"까지.
- **새 파일**:
  - `lib/nodes.py` — 판단층(순수, ev3dev2/시간/모터 없음). `bits_from_raw`, `node_kind`,
    `classify_node`, `NodeDebouncer`(후보→확정, 010 리셋, node_debounce 중복방지),
    `decide_node`(replay 어댑터, `tools/replay.py --decider lib.nodes:decide_node`).
  - `stages/stage3_node_detect.py` — INITIAL_PARAMS(**6개**)+LIMITS/STEP/UI/UNITS/ORDER,
    IDLE↔FOLLOW 제어 루프. `do follow` 로 1세트(선추종→노드 확정 정지), `do nudge <mm>`.
    노드 확정 시 `hw.stop()`+로그+`advance(node_advance mm)`+beep. 네트워크 비차단(snapshot).
  - `tests/test_stage3_logic.py` — 15 테스트(bits 변환/노드종류 8/후보 debounce/중복방지/
    노이즈 무시/000 처리/확정 정지 action/advance 도달·정지·제자리/params 메타).
- **lib/hardware.py 최소 추가(Stage 1/2 메서드·`__init__` 동작 불변)**: `read_left_reflect`/
  `read_right_reflect`/`read_reflect`(좌/중/우 튜플)·`enc_avg`. 좌/우 센서(in1/in3)는 Stage1/2
  가 안 쓰므로 `__init__` 을 건드리지 않고 **첫 사용 시 지연 오픈**(`_ensure_side_sensors`).
- **라이브 params 6개**(요청·STAGES 한도): `left/center/right_threshold`, `node_confirm_ms`,
  `node_debounce_ms`, `node_advance`. threshold 기본 5(Stage1 중앙 실측 검정0/흰10 따름).
  명세는 `thr_*`/기본40 이었으나 **요청 네이밍(`*_threshold`)·실측 범위(0~10)**에 맞춰 조정.
- **reason_code**: `NODE_CANDIDATE`/`NODE_CONFIRMED`/`CORNER_LEFT`/`CORNER_RIGHT`/`LINE_FOLLOW`/
  `LINE_LOST`/`LINE_RECOVER`/`EMERGENCY_STOP` — 전부 DECISIONS.md 카탈로그에 **이미 존재 →
  추가 없음**. `000` 은 DEAD_END 노드 후보로 다뤄 Stage1 `LINE_LOST` 와 reason/kind 로 구분.
- **telemetry**: `reflect_l/c/r`(+`reflect` 리스트)·`bits`·`node_candidate`·`node_confirmed`·
  `dist_mm`·`enc_avg`·`confirm_count`·`mode` + 추종 `error/turn/left_speed/right_speed`.
- **dist_mm**: 엔코더 평균각 → `deg_to_mm`(바퀴지름 56mm 가정, §11 실측 필요). 실패#1 진단 핵심.
- **정지**: 네트워크 stop → 플래그만(제어/advance 폴링이 안전 시점 처리), Ctrl-C 처리.
  **BACK 버튼은 읽지도 할당하지도 않음.** 노드 확정 시 기본은 정지(`CONTINUE_AFTER_NODE=False`).
- **PC 검증(통과)**: `python3 -m py_compile stages/*.py lib/*.py tools/*.py`,
  `tests/test_stage3_logic.py`(15), `lib/nodes.py` self-test, Stage 1/2 회귀
  (`test_stage1_logic.py`/`test_stage2_logic.py`)·lib self-test 전부, replay 시나리오
  (`--decider lib.nodes:decide_node` — confirm_ms 100 은 CONFIRMED, 300 은 CANDIDATE 만 →
  확정 타이밍을 로봇 없이 재연), 서버 통합 smoke(describe stage3·do follow/nudge 큐·미지액션
  거부·set 1스텝 허용/과스텝·범위 거부·stop).
- **한 번에 변수 하나**: 보정 순서를 threshold(센서별)→confirm→debounce→advance 로 PROGRESS
  "Stage 3 실기 검증 필요" 블록에 명시. replay 로 confirm 영향 먼저, advance 는 실기 do 로.
- **실기 검증 필요**: 위 블록. **Stage 3 Done 아님**(모든 노드 종류 노드 위 정지/출력 + save 전).
  Stage 3 Done 후에만 Stage 4 착수.

### 2026-06-30 — Stage 2 실기 Done 확정 + 저장값 기록 (Agent: codex)
- 사용자가 Stage 2 회전 보정 완료 및 저장을 보고해 Stage 2 를 실기 Done 으로 표시했다.
- 확인:
  - `robotctl get` 현재값: `turn_speed=18`, `turn_90_factor=0.9`, `turn_180_factor=0.8`,
    `post_turn_settle_ms=120`.
  - 브릭 `~/ev3test/config/stage2.json` 내용도 같은 값으로 확인.
- 로컬 추적용 `config/stage2.json` 을 추가해 검증값을 git 에 남겼다.
- 다음 단계는 Stage 3 노드 감지. Stage 2 확정 코드/값은 수정하지 않는다.

### 2026-06-30 — 브릭 업로드/실행 안내 규칙 추가 (Agent: codex)
- `AGENTS.md` 에 스테이지 코드를 브릭에 올릴 때 기본 안내를 `scp` 로 하도록 명시했다.
- 스테이지 구현/수정 완료 답변에는 앞으로 **코드 업로드 명령어**와 **터미널별 실행 명령어**를
  함께 첨부하도록 종료 규칙에 추가했다.

### 2026-06-30 — Stage 2 원시 회전(좌90/우90/U턴) 구현 + PC 검증 (Agent: claude)
- **게이트**: 사용자가 Stage 1 을 실기 Done 으로 선언 → Stage 2 착수(Stage 0 도 사람이 Done
  처리한 선례). 대화상 코스 추종/정지의 상세 실기 로그는 남기지 않음 — 정직하게 기록만.
- **범위**: Stage 2 만. 노드 감지(Stage3)·색 판정(Stage4)·라인트레이싱 통합(Stage5) 미구현.
  라인 재포착 회전정지도 안 함(Stage 5). 여기서는 **순수 회전 각도만**.
- **새 파일**:
  - `stages/stage2_turns.py` — 트리거 대기 루프. 파일 맨 위 INITIAL_PARAMS(**4개**) +
    PARAM_LIMITS/MAX_STEP/UI_STEP/UNITS/PARAM_ORDER(Stage 1 패턴). do 명령은 네트워크
    thread 가 큐에 넣고 **대기 루프가 회전 실행**(제어/모터는 절대 네트워크가 블록 안 함).
  - `lib/decide_turn.py` — 판단층(순수, ev3dev2 없음). `decide_turn(command,params,state)` →
    `(action, reason_code, detail)`, `target_degrees(action,params)`. PC import/테스트 가능.
  - `lib/turns.py` — 구동층. `pivot()` 엔코더 **폴링 루프**(블로킹 호출 X → stop 즉시 반응).
    모터 접근은 전부 hw 경유라 ev3dev2 직접 import 없음(가짜 hw 로 PC 테스트됨).
  - `tests/test_stage2_logic.py` — 판단층 + pivot 단위 테스트.
- **lib/hardware.py 최소 추가(Stage 1 drive/stop/__init__ 동작 수정 없음)**: `reset_encoders()`,
  `read_encoders()`, `drive_raw()`(회전엔 트림 미적용), `beep_ok()`(best-effort, Sound 없어도 무해).
- **라이브 params 4개**: `turn_speed`, `turn_90_factor`, `turn_180_factor`, `post_turn_settle_ms`
  (6 이하). 좌·우 90° 는 하나의 계수로 시작(좌우 대칭 기대), 실기서 어긋나면 분리(§11).
- **회전=엔코더 각도 기반**(시간 X). `BASE_PIVOT_DEG_90/180`(파일 상수, 가정 193/386°) × 보정계수.
  배터리/마찰이 변해도 남는 변수는 보정계수 하나라 라이브로 그것만 만짐.
- **reason_code**: `TURN_LEFT/RIGHT/UTURN`(DECISIONS.md 카탈로그에 이미 존재 → 추가 없음) +
  `EMERGENCY_STOP`. detail 에 command/selected/rule/target_deg/factor/turn_speed/param_rev/
  enc_l/enc_r/enc_avg/error_deg/stopped_early 포함(시작 의도 + 실제 결과 한 이벤트).
- **telemetry**: `enc_l/enc_r/enc_avg/target_deg/turning`(+ 공통 t_ms/param_rev/running).
- **인프라 버그 1건 수정(별도 관심사, 아래 별도 항목)**: `SharedParams.set` 의 MAX_STEP 비교가
  부동소수로 정확히 한 스텝(예 `set turn_90_factor 1.05`)을 거부하던 것 → `+1e-9` 여유로 허용.
- **정지**: 네트워크 stop → 플래그만 세팅(폴링 루프/대기 루프가 안전 시점에 처리), Ctrl-C 처리.
  **BACK 버튼은 읽지도 할당하지도 않음.**
- **PC 검증(통과)**: `python3 -m py_compile stages/*.py lib/*.py tools/*.py`,
  `tests/test_stage2_logic.py`(decide/target_degrees 선형·미지명령·pivot 도달/방향/조기정지/
  zero-target/params 4개), `lib/decide_turn.py`·`lib/turns.py` self-test, Stage 1 회귀
  (`tests/test_stage1_logic.py`)·lib self-test 전부, 서버 통합 smoke(describe stage2·
  do 큐/미지액션 거부·set 1스텝 허용/과스텝·범위 거부·stop).
- **실기 검증 필요**: 위 "Stage 2 실기 검증 필요" 블록. **Stage 2 Done 아님**(좌·우·U 3회 연속
  재현 전). Stage 3 이후 착수 금지.

### 2026-06-30 — 인프라 SharedParams MAX_STEP 부동소수 경계 수정 (Agent: claude)
- **증상**: `set turn_90_factor 1.05`(기본 1.0, MAX_STEP 0.05)가 거부됨 — `1.05-1.0`이 부동소수로
  `0.05000000000000004`라 `> step` 에 걸림. 문서화된 보정 스텝(정확히 한 MAX_STEP)이 막히는 버그.
- **수정**: `lib/shared_params.py` `set()` 의 스텝 비교를 `> step` → `> step + 1e-9`. 1e-9 는 어떤
  param 단위에서도 무의미한 크기라 실제 과도 스텝은 그대로 거부. Stage 1/shared_params self-test 회귀 통과.
- **이유를 먼저 적고 별도 관심사로 기록**(AGENTS.md): 인프라(codex)의 공용 도구라 Stage 2 구현과
  분리해 둔다. 영향: 모든 스테이지의 set 경계가 더 견고해짐(특히 라이브 보정 스텝).


- **실기 측정**: 중앙 컬러센서(`in2`) 반사광이 검은색에서 `0`, 흰색에서 `10`으로 관측됨.
- **반영값**: `target_reflect=6` 정도가 적당해 보여 Stage 1 초기값에 반영. 기본 주행 속도는
  `base_speed=20`으로 반영.
- **미확정**: `kp`/`kd` 등 PID 보정값은 추후 실기에서 결정. 현재 `LINE_LOST_MARGIN=25`는
  반사광 범위(0~10)에 비해 커서 유실 판정에는 맞지 않을 수 있으나, 이번에는 값 하나씩
  검증 원칙에 따라 수정하지 않고 TODO 로 남김.
- **Stage 1 Done 아님**: 직선+곡선 코스 끝까지 추종 및 정지 경로 확인은 아직 남아 있음.

### 2026-06-30 — Stage 1 기초 라인트레이싱 구현 + 인프라 통합 (Agent: claude)
- **범위**: Stage 1 만. 회전(Stage2)·노드(Stage3)·색(Stage4)·그리퍼 미구현. 중앙센서 in2 1개.
- **새 파일**:
  - `stages/stage1_linetrace.py` — 판단층(순수)과 구동층 분리. 파일 맨 위에 INITIAL_PARAMS(6개)
    + PARAM_LIMITS + MAX_STEP + UI_STEP/UNITS. 제어 루프 `run()`: stop 플래그 확인 →
    dt 실측 → 센서 → params snapshot(비차단) → `decide_line`(순수) → 구동 → telemetry/reason.
  - `lib/hardware.py` — 구동층(ev3dev2). outA/outB 주행 + in2 반사광. ev3dev2 import 는
    `__init__` 안(PC py_compile 안전). 좌/우 곱셈 트림 상수(라이브 아님).
  - `tests/test_stage1_logic.py` — 판단층 단위 테스트(ev3dev2 없이).
- **판단층(순수, replay 가능)**: `classify_line`, `to_wheel_speeds`, `decide_line`. `decide_line`
  은 `state` 를 제자리 갱신 + `(action, reason_code, detail)` 반환(replay.py 계약). PID 는 기존
  `lib/pid.py` `Pid`(D항 EMA, 검토 #8) 재사용 — 중복 구현 안 함. dt 는 sample t_ms 차로 측정.
- **params 6개**: kp/ki/kd/base_speed/turn_limit/target_reflect (STAGES.md 한도 준수).
- **telemetry**: reflect/error/turn/left_speed/right_speed (+ 인프라 공통 t_ms/dt_ms/param_rev/running).
- **reason_code 4종**: LINE_FOLLOW(0.25s throttle)/LINE_LOST/LINE_RECOVER/EMERGENCY_STOP.
  모두 DECISIONS.md 기존 카탈로그에 있어 카탈로그 추가 없음.
- **정지**: 네트워크 `stop` → `on_stop` 가 플래그만 세팅(제어 루프 비차단), Ctrl-C 도 처리.
  **BACK 버튼은 읽지도 할당하지도 않음**(정책 준수).
- **PC 검증(통과)**: `python3 -m py_compile stages/*.py lib/*.py tools/*.py`,
  `tests/test_stage1_logic.py`(classify/wheel/PID 부호·클램프·첫틱 D=0/유실·복구 전이/state 제자리),
  `lib/*` self-test 전부, replay 왕복(`--decider stages.stage1_linetrace:decide_line`:
  기본 params 는 LINE_LOST→RECOVER, `--set target_reflect=70` 은 유실 없음 — 재연으로 값 영향 확인).
- **실기 검증 필요**: 위 TODO "Stage 1 실기 검증 필요" + "실기 확정 필요 상수"(조향 부호, LINE_LOST_MARGIN,
  RECOVER_SPEED, 트림). 실기 Done 전까지 Stage 2 착수 금지.

### 2026-06-30 — Stage0 실기 Done 확정 + BACK 버튼 정책 변경 (Agent: codex)
- 브릭에서 `python3 stages/stage0_check.py` 실행 결과 Python `3.5.3` 확인. 이후 브릭 실행
  코드는 Python 3.5 안전 문법(`.format()`, f-string 금지)을 유지한다.
- 모터: `outA` 좌 주행 라지 모터 OK, `outB` 우 주행 라지 모터 OK, `outC` 그리퍼 미디엄 모터 OK.
- 센서: `in2` 중앙 컬러센서 OK(value 6~7), `in3` 오른쪽 컬러센서 OK(value 7~8),
  `in4` 초음파 OK(약 6.3~9.9cm). `in1` 왼쪽 컬러센서는 실행 로그상 미연결 FAIL 이었지만,
  사용자가 실물 확인 후 "포트 이상 없음, 실패는 무시 가능"으로 판단해 Stage 0 Done 처리.
- 방향 확인: 좌/우 주행 모터 전진 방향 정상.
- 정책 변경: EV3 BACK 버튼은 어느 프로그램에서든 종료 버튼처럼 동작하므로 앞으로
  stop/skip/abort 입력으로 할당하지 않는다. 정지는 `robotctl stop`/키보드 인터럽트/필요 시
  별도 안전 입력으로 처리한다.

### 2026-06-30 — 실기 주행 준비 및 단계별 보정 가이드라인 보고서 작성 (Agent: antigravity)
- 내일 아침 9시부터 실기 테스트 및 구현을 즉시 시작할 수 있는 종합 가이드라인 [tomorrow_morning_guide.md](file:///home/emjdp/.gemini/antigravity/brain/8a7d13ee-e3fd-4744-bcfb-f1f7101d7367/tomorrow_morning_guide.md) 작성 완료.
- 블루투스 PAN 네트워크 설정 방법, SSH 8765 포트포워딩 가이드 포함.
- 터미널 3분할 연동 실행법(SSH 브릭 제어, telemetry_watcher.py, curses dashboard.py) 상세 정리.
- Stage 0(포트 검증), Stage 1(PID 추종), Stage 2(회전 보정)의 구체적인 보정 기준 및 절차 명시.
- Stage 3~7 구현을 위해 Codex/Claude/Gemini 에이전트에게 내릴 최적화된 프롬프트 템플릿 세트(Carousel 형식) 제공.

### 2026-06-30 — Stage0 출력 ASCII 잔여 문자열 마무리 (Agent: codex)
- antigravity 의 한글 출력 제거 후 남아 있던 `stage0_check.py` 의 position fallback 출력
  1줄을 ASCII(`position unavailable, opened OK`)로 교체했다.
- 확인: `describe.actions[*].label` 은 표시 전용이고 실행 의존성은 `name` 에 걸려 있어,
  데모 라벨 영어화는 `do turn_left`/`turn_right`/`uturn` 경로를 깨지 않는다.
- PC 검증: `python3 -m py_compile lib/*.py tools/*.py stages/*.py`, Stage0 출력 후보 문자열
  ASCII 확인. **실기 검증 필요**: 브릭에서 Stage 0 실행.

### 2026-06-30 — 브릭 실행 코드 내 UnicodeEncodeError 방지를 위한 한글 제거 (Agent: antigravity)
- 수정 내용: `stages/stage0_check.py` 내의 모터/센서 레이블 및 `print()` 한글 출력 문자열을 모두 영어(ASCII)로 전환. `lib/tuning_server.py` 내의 `_demo()` 데모 코드 한글 레이블을 영어로 전환.
- 배경: ev3dev OS의 기본 로케일(Locale)이 UTF-8이 아닌 환경(ASCII 등)에서 실행 시 `print` 속 한글로 인해 `UnicodeEncodeError` 크래시가 발생하는 것을 방지.
- **실기 검증 필요**: 브릭에서 `stage0_check.py` 실행 시 영어 출력 및 동작 정상 여부 확인 필요.

### 2026-06-30 — 인프라 describe + data-driven 대시보드 확장 (Agent: codex)
- `SharedParams` 에 `ui_step`/`units`/`param_order` 메타와 `describe()` 를 추가해
  value/min/max/step/max_step/unit 을 서버가 그대로 노출할 수 있게 했다(기존 생성자 호출은 유지).
- `TuningServer` 에 `{"cmd":"describe"}` 를 추가하고, `stage` + actions manifest 주입을
  지원했다. 데모 서버는 PC 단독 테스트용 params/actions 를 반환한다.
- `tools/dashboard.py` 를 describe 기반으로 변경: params 행과 action 키를 동적으로 구성하고,
  `1..` 액션 실행, `Space`/`.` 마지막 액션 반복, `a` 자동 재실행, `c` coarse step 을 지원한다.
  상태/이벤트는 계속 `runs/current/latest_state.json` 을 읽고, 키 입력 때만 서버 명령을 보낸다.
- `tools/robotctl.py describe` 를 추가했다. `docs/specs/00_infra_dashboard.md` 는 REVIEWED 상태를
  유지하며 describe 스키마·data-driven 대시보드·step/max_step 메타를 반영했다.
- PC 검증: `python3 -m py_compile lib/*.py tools/*.py`, `lib/` f-string 없음 확인, shared_params/
  tuning_server self-test, 데모 서버 `describe/set/do`, dashboard `--once`, 키 핸들러 smoke
  (액션 키/반복/자동 재실행/coarse 거부), watcher 1회 기록 후 렌더 확인. **실기 검증 필요**:
  Stage 1/2 통합 때 브릭 부하·SSH 터널·회전 보정 루프 체감을 확인한다.

### 2026-06-30 — 인프라 MVP 구현 + PC 통합 검증 (Agent: codex)
- `lib/` 코어 구현: `SharedParams`(범위/스텝 거부, rev, save/rollback), `Telemetry`,
  `DecisionLog`, dt 측정값 기반 `Pid`(D항 EMA), threaded newline-JSON `TuningServer`
  (`get/set/stop/do/save/rollback/get_latest`, 깨진 JSON 라인 복구, 데모 서버).
- `tools/` 구현: 비대화형 `robotctl.py`, watcher(`runs/<ts>/` 기록 +
  `runs/current/latest_state.json`), curses MVP `dashboard.py`(브릭 직접 polling 없이 로컬 상태 파일
  렌더, 키 입력 시에만 명령 전송), `replay.py` 스켈레톤(stub/plug-in decide).
- PC 검증: `python3 -m py_compile lib/*.py tools/*.py stages/*.py`, lib self-test,
  데모 서버로 `robotctl get/set/do/stop/latest`, watcher 기록/param diff, dashboard `--once`
  렌더 및 키→명령 경로, replay stub 실행 통과. `lib/` f-string 없음 확인.
- 범위 준수: `stages/`, `lib/hardware.py`, `docs/specs/*` 수정 없음. **실기 검증 필요**:
  인프라 자체 Done 은 없고, Stage 1 라인트레이싱 통합 때 SSH 터널/브릭 부하/stop/save/rollback 을 확인한다.
- 다음: Stage 0 실기 검증 → Stage 1 착수 시 인프라 통합.

### 2026-06-30 — 소유권/순서 정리: 인프라는 codex, 스테이지는 일괄 금지 (Agent: claude)
- 확인: Stage 1~7 코드를 미리 일괄 작성하는 것은 금지(AGENTS.md 1절). codex 가 "나머지"를
  맡되 **단계별로 하나씩, 이전 단계 실기 Done 후**. claude 의 이전 "codex가 1~7" 표현이
  batch 로 읽힐 소지가 있어 바로잡음.
- "미리 만들 수 있는 것"은 스테이지가 아니라 **인프라/대시보드 도구**(공용 도구라 규칙 대상 아님,
  PC 단위테스트 가능). → **인프라 MVP 빌드를 codex 에 배정**(다음 작업). MVP 한정.
- 이후 Stage 1~7 은 **codex·claude 협업/교대**로 진행하기로 결정.
- claude 는 현재 추가 빌드 없음(인프라/스테이지 모두 codex 시작). Stage 0 실기 검증 대기.

### 2026-06-29 — Stage 0 스크립트 구현 (Agent: claude)
- `stages/stage0_check.py` 작성(명세 docs/specs/stage0_connection.md 기반).
- 모터3(outA/outB/outC)·센서4(in1~in4) 포트 probe + 값 1회 읽기, 좌/우 forward nudge
  (15%/400ms, ENTER 로 시작), python 버전 출력, OK/FAIL 요약.
- Python 3.5 안전(f-string 없음, .format()), ev3dev2 는 main() 안 import → PC py_compile 통과.
- 한 포트 실패해도 나머지 계속 점검(try/except per device). position 읽기 예외도 감쌈.
- **실기 검증 필요**: 브릭에서 실행해 버전·7포트·방향 확인 후 PROGRESS 기록 → Done.
- 나머지 스테이지(1~7)는 codex 담당 예정.

### 2026-06-29 — antigravity 검토 보고서 재검토 + 반영 (Agent: claude)
- antigravity 보고서(9개 지적)를 명세 원문과 대조 검토(#2 통신·#4 Stage1 분리 직접 확인 — 보고서 정확).
- 우선순위 재조정: High 로 표시된 #1/#3/#5 는 Stage 6/7(먼 미래 DRAFT)이라 지금 막지 않음.
  지금 만들 것(인프라+Stage1)에 영향 주는 #2/#4/#8 만 즉시 반영.
- 반영: 00_infra(#2 단일 채널)·stage1(#4 순수전이·#8 EMA) → REVIEWED 승격.
  stage5(#6)·stage6(#3,#5)·stage7(#1,#7) 은 11절에 검토 메모 추가(DRAFT 유지).
- 상태 규약 정리: specs 는 DRAFT→REVIEWED 2단계, 실기 Done 은 PROGRESS 🟢 로 구분
  (보고서의 'APPROVED' 대신 — 실기검증과 의미 분리). specs/README.md 갱신.
- stage1 의 "00_infra 아직 없음" 스테일 문구 수정. 상세 현황은 위 "명세 검토 처리 현황".
- 참고: antigravity 가 남긴 analysis 링크는 `~/.gemini/...` 로컬 경로라 타 환경에선 안 열림.

### 2026-06-29 — 서브에이전트를 활용한 스테이지별 구현 명세 검토 (Agent: antigravity)
- 서브에이전트 3개를 띄워 `00_infra_dashboard.md` 및 `stage0~7` 스펙의 전반을 검증함.
- 핵심 검토 결과를 [analysis_results.md](file:///home/emjdp/.gemini/antigravity/brain/b9afc161-214b-499b-9d0a-29579839fa4b/analysis_results.md) 아티팩트로 작성 완료.
- 주요 지적 사항: 초음파 센서 동기식 읽기로 인한 제어 주기 붕괴 위험(High), 복귀 로직의 노이즈 취약성 및 재귀 구조 우려(High), Stage 1 판단-구동 분리 미흡(Medium) 등.
- **다음**: 지적 사항을 바탕으로 docs/specs/의 DRAFT 문서들을 보완 및 APPROVED 처리 후 Stage 0 실행.

### 2026-06-29 — 스테이지별 구현 명세 작성 (docs/specs/) (Agent: claude)
- 사람 인터페이스를 터미널 TUI 대시보드(`tools/dashboard.py`, curses)로 확정. 눌러서 실행
  + 키로 파라미터 즉석 조정. `robotctl` 은 스크립트/에이전트용 비대화형 CLI 로 병행.
- 서브 에이전트 5개 병렬로 [docs/specs/](docs/specs/) 에 구현 명세 9종 작성(이어받기용 11절 형식):
  00_infra_dashboard, stage0_connection, stage1_linetrace, stage2_turns, stage3_node_detect,
  stage4_color, stage5_integration, stage6_explore_return, stage7_gripper (총 ~3050줄, 모두 DRAFT).
- 검토: 11절 형식 준수, 브릭 코드 f-string 없음, 내부 링크 전부 유효 확인.
- **선행 의존성**: Stage 1 착수 전 `00_infra_dashboard.md` 의 lib/ 계약을 먼저 확정해야 함
  (stage1~3 명세가 이 인프라에 의존). EV3 Python 버전은 Stage 0 에서 확정.
- **다음**: Stage 0 코드 착수(또는 00_infra 명세 리뷰 후 Stage 1 인프라 MVP).

### 2026-06-29 — 판단 기록·재연·빠른 보정 루프 추가 (문서 반영) (Agent: claude)
- 실사용 페인포인트 반영: ① 좌회전 하나에 1시간(느린 반복) ② "왜 그렇게 움직였나" 안 보임
  ③ 오늘의 실패(분기/코너 오버슛, 노드 지나 빈 바닥 색 측정)를 실시간 수정·재연하고 싶음.
- 새 문서 [docs/DECISIONS.md](docs/DECISIONS.md): 판단층↔구동층 분리, reason_code 카탈로그,
  events.jsonl 스키마, 두 실패를 로그로 잡는 법, `robotctl do <action>` 단일 트리거,
  record/replay, "params 6개 이하 + 로그가 짚는 값만" 원칙.
- LIVE_TUNING: 대시보드는 *나중*, do/reason/replay 가 먼저. CLI 에 `do`·`replay.py` 추가.
  빌드순서에 reason logging·replay 끼워넣음.
- STAGES: Stage2(=`do turn_*` 보정 루프), Stage3(`node_advance`+실패#1), Stage4(색읽기 위치
  +실패#2) 반영. Stage1부터 reason_code 기록 명시.
- AGENTS: 판단층 분리·reason 로그·do 트리거·replay 를 코드 규약에 추가.
- README: 문서 목록/라이브튜닝 섹션에 DECISIONS 연결.
- 코드 미작성(문서 단계).

### 2026-06-29 — 라이브 튜닝 구조 채택 (문서 반영) (Agent: claude)
- "EV3=주행 / 노트북=관제소" 라이브 튜닝 구조를 검토·확정해 문서에 반영(코드는 아직).
- 새 문서 [docs/LIVE_TUNING.md](docs/LIVE_TUNING.md): 서버/CLI/telemetry/안전장치/빌드순서/
  에이전트 워크플로우. 핵심 결정: 제어루프↔네트워크 분리, threaded accept, dt 측정,
  telemetry 파일쓰기는 노트북, 회전은 엔코더+보정계수, 에이전트는 제안만.
  (2026-06-30 이후 BACK 버튼은 프로그램 입력으로 할당하지 않는 정책으로 변경.)
- README/STAGES/AGENTS 갱신: 라이브 튜닝을 "스테이지가 아닌 공용 도구"로 못박고
  단계와 함께 자라게. 목표 디렉토리(lib/tools/config/runs/dashboard) 반영. `runs/` gitignore.
- **다음**: Stage 0 스크립트(여전히 plain 연결확인, 네트워크 없음).

### 2026-06-29 — 프로젝트 초기 세팅 (Agent: claude)
- 단계별 재구축 구조로 새 프로젝트 디렉토리(`ev3test`) 세팅.
- 공용 문서 작성: README.md(공용 설명), AGENTS.md(에이전트 규칙),
  CLAUDE.md / GEMINI.md(전용 포인터), docs/HARDWARE.md, docs/STAGES.md, 이 PROGRESS.md.
- 이전 구현(`ev3maze/robot`)에서 검증된 포트 배선만 가져옴. 거대 config 는 버리고
  단계별 독립 스크립트 방식 채택.
- git 로컬 저장소 초기화, 초기 커밋.
- **다음**: Stage 0 스크립트.
