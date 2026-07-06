# Stage 5 하위 단계 분할 계획 (5-1 ~ 5-4)

상태: **REVIEWED** (2026-07-06, 사용자 결정 반영)

## 0. 왜 쪼개나

`stages/stage5_integration.py`(2026-07-06)는 시퀀스 토큰 소비 + 감지↔지시 분리 회전 +
S 직진 통과 + LEAF 색 마커 강제 U턴을 **한 번에** 얹었다. PC 검증은 통과했지만 실기에서
제대로 동작하지 않았고, 신규 변수가 여러 개라 어느 것이 범인인지 가릴 수 없었다
("한 번에 변수 하나" 원칙 위반이 스테이지 단위에서 재발한 것).

그래서 Stage 5 를 하위 단계 **5-1 ~ 5-4** 로 쪼갠다. 각 하위 단계는 **신규 기능 딱 하나**만
추가하고, 실기에서 그 하나가 Done 되기 전에 다음 하위 단계 코드를 쓰지 않는다
(STAGES.md 의 스테이지 원칙을 하위 단계에도 그대로 적용).

## 1. 공통 원칙

- **파일명**: `stages/stage5_<n>_<짧은이름>.py`, config 는 `config/stage5_<n>_<이름>.json`.
  각 파일은 독립 실행 가능해야 한다.
- **재사용(미수정 import)**: stage3v2 의 `black_bits`/`branch_side`/`branch_confirm_step`/
  `pd_step`/`advance_straight`/`_run_turn`, stage4 reflected 의 마커 게이트. 확정 코드는
  고치지 않는다.
- **공용 코드는 `lib/`**: 토큰 어휘(L/S/R/U — `lib/seq_tokens.py`), 확정값 병합 뷰
  (`lib/params_view.py`). 하위 단계끼리 복붙하지 않는다.
- **라이브 params — 속도·회전 factor 는 항상 대시보드에 남긴다(사용자 결정 2026-07-06)**:
  모든 하위 단계가 아래 공통 3개를 노출하고, 단계별 연결부 1~3개를 더해 **6개 이하**를
  유지한다. (stage5_integration 은 turn_speed/turn_90_factor 를 CONFIRMED 로 묻었는데,
  실기 튜닝에서 계속 만질 값이라 되살린다.)

  | 공통 라이브 | 시드값 | 근거 |
  |---|---:|---|
  | `base_speed` | 17 | Stage 3 v2 확정값 시드. 통합 관성 문제 시 ↓ |
  | `turn_speed` | 6 | Stage 3 v2 확정값 시드 |
  | `turn_90_factor` | 0.66 | Stage 3 v2 확정값 시드 |

  `kp`(0.22)·`branch_confirm_count`(2)·마커 판정값 등은 파일 상수(CONFIRMED)로 묻는다 —
  틀리면 해당 스테이지(3v2/4)로 돌아간다.
- **판단층 순수 유지 + reason 로그**: 새 판단마다 DECISIONS.md 카탈로그 1줄, replay 어댑터
  제공(재연 가능한 부분만).
- **각 하위 단계 Done 은 PROGRESS.md 상태판에 기록**하고, 확정 param 은 `robotctl save`
  + 로컬 config 미러.

## 2. Stage 5-1 — 분기에서 고정 지시 회전 (감지 ↔ 실행 분리)

- **구현**: `stages/stage5_1_fixed_turn.py`
- **새 기능(딱 하나)**: 분기 확정 시 감지된 방향이 아니라 **고정 지시 토큰 1개**(L/R/U/S)를
  실행한다. 모든 노드에서 같은 동작 → 시퀀스 상태(node_index 등)가 없어 디버깅이 단순하다.
  - `--turn R` CLI 로 시작, 재배포 없이 `robotctl do set_turn turn=L` 로 교체(`TURN_SET`).
  - `S` = 회전 없이 `straight_nudge_mm` 전진해 분기를 지나 계속 추종 — Stage 5-3 의 S 토큰
    연결부를 여기서 먼저 단독 검증한다.
  - 감지(BRANCH_*.bits)와 실행(TURN_*.selected, rule=FIXED_TURN)을 함께 로깅해 감지 문제와
    회전 문제를 로그로 가른다.
- **라이브 params(5)**: 공통 3 + `branch_advance_mm`(30) + `straight_nudge_mm`(60).
- **Done**: ① 좌 분기에서 R/U, 우 분기에서 L/U 각각 지시대로 회전해 다음 선 재포착
  ② 십자/T 를 `--turn S` 로 직진 통과(재감지 없이 다음 구간 추종) — 각각 반복 재현.
- **하지 않는 것**: 시퀀스 소비, 111 십자 구분(111 은 stage3v2 그대로 좌 분기 취급),
  색 마커(LEAF).

## 3. Stage 5-2 — 노드 종류 구분 (111 십자 vs 110/011 T자)

- **구현(예정)**: `stages/stage5_2_node_kind.py` — 5-1 위에 분류만 얹는다.
- **새 기능(딱 하나)**: 분기 확정 시점의 bits 로 노드 종류를 구분해 **로그로만** 남긴다
  (`NODE_KIND` reason, kind=`T_LEFT`(110)/`T_RIGHT`(011)/`CROSS`(111)). **행동은 5-1 과
  동일(고정 지시)** — 분류가 행동을 바꾸지 않으므로 분류 오류를 주행 문제와 분리해 본다.
- **예상 이슈(착수 시 명세화)**: 진입 각도에 따라 110→111 순서로 보일 수 있어, 확정 직전
  N틱 bits 이력에서 111 이 한 번이라도 잡히면 CROSS 로 볼지 등 판정 규칙이 필요.
  replay 로 실기 기록을 재연해 규칙을 정한 뒤 실기 확인.
- **라이브 params**: 공통 3 + `branch_advance_mm` + (분류용 1개 이내, 필요할 때만).
- **Done**: 좌T/우T/십자 각각 반복 통과시켜 events 의 kind 가 실제 코스와 매번 일치.

## 4. Stage 5-3 — 시퀀스 소비 (JCT 만, 색 마커 없음)

- **구현(예정)**: `stages/stage5_3_sequence.py` — 5-1 의 고정 지시를 시퀀스 소비로 교체.
- **새 기능(딱 하나)**: `--seq "L S R"` 토큰을 노드마다 1개 소비(`FROM_SEQUENCE`),
  `SEQUENCE_DONE`/`SEQUENCE_EXHAUSTED`/`do set_seq` + telemetry `node_index`/`seq_remaining`.
  회전/직진 연결부는 5-1 에서, 노드 분류는 5-2 에서 이미 검증된 상태이므로 여기서 새로
  검증하는 것은 **소비 순서·타이밍뿐**이다.
- **라이브 params**: 공통 3 + `branch_advance_mm` + `straight_nudge_mm`.
- **Done**: 분기만 있는 코스에서 미리 정한 시퀀스대로 통과 반복 재현.

## 5. Stage 5-4 — LEAF 색 마커 + 전체 코스 (= Stage 5 Done)

- **구현**: `stages/stage5_integration.py` **재활용** — 이미 이 형태로 작성돼 있다.
  5-1~5-3 에서 배운 수정(공통 라이브 params 복원 포함)을 반영해 최종 확정한다.
- **새 기능(딱 하나)**: stage4 색 마커 게이트를 LEAF 노드로 통합 — 색 기록(COLOR_READ) 후
  강제 U턴(`LEAF_FORCE_UTURN`), 토큰 1개 소비.
- **Done**: 색 마커 포함 전체 코스를 시퀀스대로 통과 반복 재현 = **STAGES.md Stage 5 Done**.

## 6. 기존 `stage5_integration.py` 의 위상

- 삭제하지 않는다. 5-4 의 참조 구현으로 보존하고, 하위 단계 진행 중 실기에서 확인된
  수정 사항(파라미터 노출, 타이밍, 111 규칙)을 5-4 착수 시점에 반영한다.
- 실기 검증 순서는 이 문서의 5-1 → 5-2 → 5-3 → 5-4 다. PROGRESS.md 의 기존
  "Stage 5 실기 검증 필요" 절차는 5-4 시점의 절차로 남는다.
