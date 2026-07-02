# Stage 4-A — 반사광 단독 노드색 판정 구현 명세 (브릿지 후보 A)

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3(`stages/stage3v2_linetrace_branch.py`) 실기 Done(2026-07-02), 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."
>
> **Stage 4 브릿지 후보 4개 중 A.** 나머지: [B — 000 의심지점 컬러+후진](stage4b_suspect_backup_color.md),
> [C — 반사광 게이트+컬러 확정](stage4c_reflect_gate_color.md),
> [D — 반사광↔컬러 고속 교대](stage4d_mode_interleave.md).
> 컬러 모드 공통 부품(모드 전환·`ColorConfirmer`·`classify_node_color`·`COLOR_*` reason)의 기준
> 문서는 [stage4_color.md](stage4_color.md) — 단 **A 는 컬러 모드를 아예 쓰지 않으므로** 그중
> 재사용하는 것은 `NODE_IS_*` reason 체계뿐이다. **후보 채택 결정은 §7-0 공통 선결 실측 후.**

## 0. 아이디어 요약 / 후보 비교

- **한 줄**: 중앙 컬러센서를 **반사광 모드로만** 쓴다. 출발/노드(체크포인트)/도착 마커의
  반사광이 서로(그리고 검은 선/흰 바닥과) 다른 대역(band)에 있으면, 반사광이 그 대역에
  **일정 시간 이상 유지**될 때(즉시 인지 금지 — 순간 스파이크 배제) 그 노드색으로 판정한다.
- **최대 장점**: **컬러 모드 전환 0회.** stage4_color.md §8 의 "전환 직후 오판(0/엉뚱한 색)"
  문제와 settle/더미읽기 시간 비용이 원천 제거된다. 판정이 주행 중 실시간으로 돈다.
- **성립 조건(엄격)**: 검은 선(≈10) / 흰 바닥(중앙 ≈62~68, 2026-07-01 실측) / 마커 3색,
  합계 **5개 대역이 반사광 축 위에서 전부 분리**되어야 한다. §7-0 실측으로만 확인 가능.
- **노드별 반사광 파라미터는 전부 라이브** — 대시보드에서 `start_reflect` /
  `checkpoint_reflect` / `goal_reflect` 를 마커 실측값으로 바로 맞춘다(사용자 요구사항).

### 후보 4개 비교(공통 표 — 4개 문서 동일 내용)

| 후보 | 트리거 | 컬러 모드 사용 | 성립 조건 | 주 위험 |
|---|---|---|---|---|
| **A(이 문서)** | 반사광 대역+유지시간 | 없음 | 5개 대역(흑/백/3색) 전부 분리 | 마커색 반사광이 흑/백과 겹침(특히 노랑≈흰) |
| B | `010`→`000` 의심지점 | 의심지점에서만(+후진) | 마커가 선 끝에 있고 반사광이 threshold 위 | 어두운 마커는 000 을 안 만듦 |
| C | 반사광 의심대역+유지 → 컬러 확정 | 의심 시에만 | "마커 vs 흑/백" 분리만 되면 됨(색끼리 분리 불필요) | 의심대역 오탐 시 잦은 정지 |
| D | 상시(반사광↔컬러 교대) | 매 슬롯 | 전환 왕복 비용이 예산 안(bench) | 전환 지연으로 라인추종 붕괴 |

> 권장 순서: **C 기본 트랙**(조건 최관대), A 는 §7-0 에서 5대역 분리가 확인되면 최우선
> (가장 빠르고 단순), B 는 막다른 길 전용 보완, D 는 bench 통과 시에만.

## 1. 목표 / 범위

- **하는 것**: stage3v2 라인추종(+분기 탱크회전) 위에, 중앙센서 반사광 값으로 노드 마커
  (출발/체크포인트/도착)를 **주행 중 실시간** 판정해 `NODE_IS_*` 로 기록한다. 확정 시
  기본은 정지(`STOP_ON_NODE=True`, config)해 Done 검증을 쉽게 한다.
- **하는 것**: "같은 대역이 `reflect_hold_ms` 이상 유지"라는 시간 조건으로 순간 스파이크
  (선 경계 통과, 그림자)를 배제한다.
- **명시적으로 안 하는 것**: 컬러 모드 사용(전환 없음), 색 판정에 따른 주행 결정(U턴/종료
  → Stage 5/6), 빈 바닥 오독 대응의 컬러식 검출(`COLOR_FLOOR_WARN` — 여기선 흰 바닥
  대역 자체가 어떤 밴드에도 안 걸리는 것으로 갈음).
- stage3v2 확정 코드(`black_bits`/`branch_side`/`branch_confirm_step`/`PdController`/
  `advance_straight`/`lib/turns.pivot`)는 **수정하지 않고 import 재사용**한다.

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4a_reflect_only.py` (독립 실행 가능).
- 재사용(수정 금지): `stages/stage3v2_linetrace_branch.py` 의 판단층 함수 +
  `lib/turns.pivot`, `lib/decide_turn`, `lib/` 인프라(shared_params/telemetry/
  decision_log/tuning_server).

### 판단층 (순수 함수, 하드웨어 없음)

```python
# reflect: 중앙센서 raw 반사광(0~100)
match_band(reflect, params) -> "START" | "CHECKPOINT" | "GOAL" | None
#   |reflect - {start,checkpoint,goal}_reflect| <= reflect_tol 인 대역.
#   우선순위 GOAL→START→CHECKPOINT (stage4_color.classify_node_color 와 동일 순서;
#   시작 자기검증이 겹침을 걸러내므로 실전에선 우선순위가 작동할 일이 없어야 정상).

class BandHold(object):
    # "같은 대역이 hold_ms 이상 연속 유지"를 판정하는 순수 디바운서.
    def __init__(self, hold_ms): ...
    def push(self, band, t_ms) -> band | None
    #   band 가 바뀌거나 None 이면 리셋. 같은 band 가 hold_ms 이상 유지되면 그 band 반환(1회).

validate_reflect_bands(params, black_seed, white_seed) -> [error_str]
#   5개 대역(흑/백/3색) pairwise 간격 > 2*reflect_tol 검사. 위반 시 시작 즉시 에러.
```

### 구동층

- 추가 없음(중앙 반사광은 stage3v2 가 이미 읽는 `hw.read_reflect()[1]` 그대로).
  **모드 전환 함수가 필요 없다는 것이 이 후보의 정체성이다.**

## 3. 라이브 params (6개)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `start_reflect` | 출발 마커 반사광 중심값 | 미정(§7-0 실측) | (0,100) | 5 | 마커 위에서 대역 미매칭 → 실측값으로 재설정 |
| `checkpoint_reflect` | 노드(체크포인트) 마커 반사광 중심값 | 미정(§7-0) | (0,100) | 5 | 〃 |
| `goal_reflect` | 도착 마커 반사광 중심값 | 미정(§7-0) | (0,100) | 5 | 〃 |
| `reflect_tol` | 대역 반폭(±) | 5 | (1,20) | 2 | 마커 위인데 값이 흔들려 미매칭 → ↑. 흑/백/이웃색까지 물림 → ↓ |
| `reflect_hold_ms` | 같은 대역 유지시간(확정 조건) | 120 | (30,1000) | 30 | 스파이크 오탐 → ↑. 마커를 지나쳐 확정 실패 → ↓ (또는 `base_speed` ↓) |
| `base_speed` | 주행 속도(%) — 유지시간 조건과 트레이드오프 | 17(stage3v2 확정값 시드) | (5,45) | 5 | 마커 통과가 빨라 hold 미충족 → ↓ |

### config/ 에 묻는 값 (라이브 노출 안 함)

| 이름 | 의미 | 기본값 |
|---|---|---|
| `kp`/`KD`/`TURN_LIMIT`/threshold 등 | 라인추종·분기(stage3v2 확정값 시드, 수정 금지) | kp 0.22, thr 43/36/42 등 |
| `RNODE_COOLDOWN_MS` | 확정 후 같은 마커 중복 확정 방지 | 1500 |
| `STOP_ON_NODE` | 확정 시 정지 여부(Done 검증용) | True |
| `BLACK_SEED` / `WHITE_SEED` | 자기검증용 흑/백 반사광 시드(실측) | 10 / 64 |

## 4. telemetry 필드 / reason_code

telemetry 추가 키: `rband`(현재 매칭 대역 또는 null), `rband_held_ms`(유지 경과),
`node_kind`(마지막 확정 종류).

| reason_code | 언제 | detail |
|---|---|---|
| `RNODE_CANDIDATE` | 대역에 처음 진입 | `band`, `reflect` |
| `RNODE_CONFIRMED` | 유지시간 충족, 노드색 확정 | `band`, `reflect`, `held_ms` |
| `RNODE_LOST` | hold 중 대역 이탈(리셋) | `band`, `held_ms`, `reflect` (throttle) |
| `NODE_IS_START/CHECKPOINT/GOAL` | 확정 종류(카탈로그는 stage4_color.md 와 공유) | `method:"reflect"`, `reflect` |

구현 시 [../DECISIONS.md](../DECISIONS.md) 카탈로그에 `RNODE_*` 3줄 추가.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크 비차단/stop 은 인프라 공통.

```python
def stage4a_loop():
    # stage3v2 run() 뼈대 복제 + import 재사용(확정 코드 수정 금지).
    hold = BandHold(params["reflect_hold_ms"])
    last_confirm_ms = -999999
    while True:
        if stop_requested(): stop(); return
        raw = hw.read_reflect()               # (l, c, r)
        bits = black_bits(raw, thresholds)     # stage3v2 재사용
        # --- 분기 감지/회전은 stage3v2 그대로 (생략) ---
        # --- 노드색 판정(이 후보의 본체) ---
        band = match_band(raw[1], params)
        if in_cooldown(t_ms, last_confirm_ms): band = None   # 회전/확정 직후 억제
        confirmed = hold.push(band, t_ms)
        if confirmed is not None:
            log("RNODE_CONFIRMED", band=confirmed, reflect=raw[1], held_ms=...)
            log("NODE_IS_" + confirmed, method="reflect", reflect=raw[1])
            last_confirm_ms = t_ms
            if STOP_ON_NODE:
                hw.stop(); beep(); wait_for_trigger_or_stop()
        # --- 라인추종 PD(stage3v2 pd_step 재사용) ---
        ...
```

주의: 분기 확정(`advance`+회전) 동안은 센서가 선/바닥을 쓸고 지나가므로 `hold` 를
리셋하고 쿨다운을 건다(회전 중 대역 오탐 방지).

## 6. 대시보드 / CLI 연동

- `do read_reflect` — 정지 상태에서 중앙 반사광 1회 읽어 출력(§7-0 실측용, 재배포 0).
- `do follow` 자동 시작(stage3v2 관례 유지) + `do turn_left/right/uturn` 수동 트리거 유지.
- 조정 키(라이브 set): `start_reflect`/`checkpoint_reflect`/`goal_reflect`/`reflect_tol`/
  `reflect_hold_ms`/`base_speed` — **노드별 반사광 파라미터를 대시보드에서 직접 조정**
  (이 후보의 사용자 요구 핵심).
- `Space` pause/resume, `s` stop — 인프라 공통.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0. **[공통 선결 실측 — 후보 A/B/C/D 채택 결정의 입력]** 정지 상태에서 각 마커(출발/노드/
   도착) 위 + 검은 선 위 + 흰 바닥에서 `do read_reflect` 5회씩 기록해 PROGRESS 에 표로
   남긴다. (같은 자리에서 `do read_color` 도 함께 — B/C/D 판단용, stage4_color.md §7-1.)
   → **5개 대역이 전부 `2×tol+여유` 로 분리되면 A 성립.** 하나라도 겹치면(특히 노랑↔흰
   바닥) A 폐기 또는 마커색 교체 검토 후 C 로.
1. 실측 중심값을 `start/checkpoint/goal_reflect` 에 설정(대시보드 set).
2. 마커 위를 천천히 통과시키며 `RNODE_CANDIDATE`→`RNODE_CONFIRMED` 가 뜨는지 확인.
   미매칭이면 `reflect_tol` +2. 흑/백에서 오탐이면 `reflect_tol` -2.
3. 스파이크 오탐(선 경계·그림자에서 `RNODE_CONFIRMED`)이면 `reflect_hold_ms` +30.
4. 마커를 지나쳐 확정을 놓치면(로그에 `RNODE_LOST` 의 `held_ms` 가 hold 근처까지 갔다가
   리셋) `reflect_hold_ms` -30 **또는** `base_speed` -5 — 둘 중 하나만.
5. 세 마커 × 5회 재현 + 빈 바닥/검은 선 오탐 0 확인 → Done, PROGRESS 기록.

## 8. 실패 모드 & 진단

- **대역 겹침(치명, A 폐기 사유)**: 노랑 마커 반사광이 흰 바닥(≈62~68)과, 파랑/초록이
  검은 선(≈10)과 겹칠 수 있다. 시작 자기검증(`validate_reflect_bands`)이 즉시 에러를
  내고, 실기에선 §7-0 표로 먼저 걸러진다. 대응: 마커색 교체(반사광 중간대 색) 또는 C 로.
- **속도 의존(hold 미충족)**: `held_ms` 가 항상 hold 직전에 리셋되는 로그 패턴 →
  마커 길이/속도 대비 hold 가 김. §7-4.
- **조명/배터리 드리프트**: 대역 중심이 세션마다 이동 → 세션 시작마다 §7-0 을 짧게
  재실측(대시보드에서 중심값만 재설정, 재배포 0).
- **회전/advance 중 오탐**: 쿨다운+hold 리셋으로 억제(§5). 그래도 뜨면 `RNODE_*` detail
  의 `t_ms` 를 TURN 이벤트와 대조해 쿨다운을 늘린다(config).

## 9. PC 검증

- `python3 -m py_compile stages/stage4a_reflect_only.py`.
- 단위 테스트(순수): `match_band` 경계값(±tol 안/밖, 우선순위), `BandHold` — 유지 중
  1샘플 이탈 시 리셋, hold 충족 시 1회만 확정, None 리셋. `validate_reflect_bands` —
  겹침 조합에서 에러.
- replay: 기록된 telemetry(중앙 reflect 시퀀스)를 `match_band`+`BandHold` 에 흘려
  `--set reflect_tol=7 reflect_hold_ms=150` 식으로 확정 시점 변화를 로봇 없이 재연.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] §7-0 공통 선결 실측(마커 3색 반사광) — **이 결과로 A 채택/폐기 먼저 결정.**
- [ ] 판단층 `match_band`/`BandHold`/`validate_reflect_bands` + 단위 테스트.
- [ ] `stages/stage4a_reflect_only.py`: stage3v2 import 재사용 + 노드색 판정 루프 +
      `RNODE_*`/`NODE_IS_*` 로깅 + `do read_reflect`.
- [ ] 라이브 params 6개 + LIMITS + MAX_STEP, config 상수(쿨다운/STOP_ON_NODE/시드).
- [ ] DECISIONS.md 카탈로그에 `RNODE_*` 추가.
- [ ] py_compile + 단위테스트 + replay 통과 → 실기 §7 보정 → PROGRESS 기록.

## 11. 미해결 / 실기 확인 필요

- **마커 3색의 실제 반사광(§7-0) — 이 후보의 존폐를 결정.** 실측 전엔 기본값도 못 정한다.
- 반사광 모드에서 색 마커의 값이 **조명·입사각·마커 재질**에 얼마나 흔들리는지(tol 결정).
- `reflect_hold_ms` 와 주행 속도의 트레이드오프 — 마커 지름(실측)과 base_speed 17 기준
  통과 시간이 hold 보다 충분히 긴지.
- 분기 마커와 색 마커가 같은 지점에 겹치는 코스라면(분기 bits 와 대역 매칭이 동시 발생)
  어느 쪽을 우선할지 — 코스 확정 후 결정.
