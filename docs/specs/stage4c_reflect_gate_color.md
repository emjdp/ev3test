# Stage 4-C — 반사광 게이트 + 컬러 확정 구현 명세 (브릿지 후보 C)

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3(`stages/stage3v2_linetrace_branch.py`) 실기 Done(2026-07-02), 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."
>
> **Stage 4 브릿지 후보 4개 중 C (= A 의 반사광 감지 + B 의 컬러 확정 결합).** 나머지:
> [A — 반사광 단독](stage4a_reflect_only.md), [B — 000 의심+후진 컬러](stage4b_suspect_backup_color.md),
> [D — 반사광↔컬러 고속 교대](stage4d_mode_interleave.md).
> 컬러 모드 공통 부품(전환 settle/더미읽기·`ColorConfirmer`·`classify_node_color`·
> `COLOR_READ`/`COLOR_FLOOR_WARN`/`NODE_IS_*` reason)은 [stage4_color.md](stage4_color.md)
> §2/§4/§5 인용. **채택 결정은 §7-0 공통 선결 실측 후 — C 가 기본 권장 트랙이다(아래 §0).**

## 0. 아이디어 요약 / 후보 비교

- **한 줄**: 평소엔 반사광 모드로 달리다가, 중앙 반사광이 **"마커 의심대역"**
  (`suspect_lo`~`suspect_hi` — 검은 선보다 밝고 흰 바닥보다 어두운 중간대)에
  **일정 시간 이상 유지**되면 → 정지 → 컬러 모드로 전환해 **색으로 확정**한다.
  반사광은 값싼 1차 스크리닝(스티커인가?), 컬러는 비싼 최종 판정(무슨 색인가?).
- **A 와의 차이**: 반사광에게 "3색 구분"을 요구하지 않는다. **"흑도 백도 아닌 무언가"**
  하나의 대역만 있으면 된다 → 성립 조건이 후보 중 가장 관대하다. 색끼리 반사광이
  겹쳐도(예: 파랑≈초록) 컬러 모드가 갈라준다.
- **B 와의 차이**: 트리거가 000(선 소실)이 아니라 반사광 대역이므로, **선 위/선 옆의
  마커도** 잡고, 유지시간 안에 정지하므로 **후진이 원칙적으로 불필요**하다(잔여
  오버슛은 config 소량 후진으로).
- **오탐 자기교정**: 의심이 틀렸으면(컬러 결과 흰/없음) `SUSPECT_FALSE` 로 기록하고
  주행을 재개한다 — 오탐의 비용이 "잠깐 멈춤"뿐이라 의심대역을 공격적으로 잡아도 된다.
  `SUSPECT_FALSE` 빈도 자체가 튜닝 지표가 된다.

### 후보 4개 비교(공통 표 — 4개 문서 동일 내용)

| 후보 | 트리거 | 컬러 모드 사용 | 성립 조건 | 주 위험 |
|---|---|---|---|---|
| A | 반사광 대역+유지시간 | 없음 | 5개 대역(흑/백/3색) 전부 분리 | 마커색 반사광이 흑/백과 겹침(특히 노랑≈흰) |
| B | `010`→`000` 의심지점 | 의심지점에서만(+후진) | 마커가 선 끝에 있고 반사광이 threshold 위 | 어두운 마커는 000 을 안 만듦 |
| **C(이 문서)** | 반사광 의심대역+유지 → 컬러 확정 | 의심 시에만 | "마커 vs 흑/백" 분리만 되면 됨(색끼리 분리 불필요) | 의심대역 오탐 시 잦은 정지 |
| D | 상시(반사광↔컬러 교대) | 매 슬롯 | 전환 왕복 비용이 예산 안(bench) | 전환 지연으로 라인추종 붕괴 |

> 권장 순서: **C 기본 트랙**(조건 최관대 + 오탐 자기교정), A 는 5대역 분리 시 최우선,
> B 는 막다른 길 전용 보완(C 와 결합 가능), D 는 bench 통과 시에만.

## 1. 목표 / 범위

- **하는 것**: 주행 중 중앙 반사광의 의심대역 진입+유지 감지(순수 판단) → 정지 →
  컬러 모드 1회 전환 → `ColorConfirmer` 로 색 확정 → `classify_node_color` 로
  출발/체크포인트/도착 판정·기록 → 반사광 복귀 → (오탐이면) 주행 재개.
- **하는 것**: 의심 진입 시점의 reflect 를 detail 로 남겨, 확정 색과 반사광의 대응표를
  로그에서 축적한다(→ 나중에 A 로 승격 가능한지 데이터로 판단).
- **명시적으로 안 하는 것**: 색 판정에 따른 주행 결정(→ Stage 5/6), 000/선 끝 대응
  (→ B 와 결합은 §11), 상시 컬러 감시(→ D).
- stage3v2 확정 코드는 수정하지 않고 import 재사용.

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4c_reflect_gate_color.py` (독립 실행 가능).
- 재사용(수정 금지): stage3v2 판단층 + `lib/turns.pivot`/`lib/decide_turn` + `lib/` 인프라.
- 컬러 전환 구동층: stage4_color.md §2 의 `hw.read_center_color`/`hw.restore_reflect_mode`/
  `read_center_reflect` (`lib/hardware.py`, 후보 B/C/D 공용).

### 판단층 (순수 함수, 하드웨어 없음)

```python
in_suspect_band(reflect, params) -> bool
#   params["suspect_lo"] <= reflect <= params["suspect_hi"]

class SuspectHold(object):
    # stage4a 의 BandHold 와 동일 구조(대역이 1개뿐). 공용화 가능하면 lib/ 로.
    def __init__(self, hold_ms): ...
    def push(self, in_band, t_ms) -> bool   # hold_ms 유지 시 True(1회)

validate_suspect_band(params, black_seed, white_seed) -> [error_str]
#   대역이 검은 선/흰 바닥 시드와 겹치면 시작 즉시 에러.

# 색 확정/분류: stage4_color.md 의 ColorConfirmer / classify_node_color 재사용.
# 컬러 결과가 흰(6)/없음(0)이면 "오탐(SUSPECT_FALSE)" — 마커 아님.
```

### 구동층 (ev3dev2 의존)

```python
confirm_color_at_rest(hw, params, should_stop) -> (color, pre_reflect)
#   정지 상태에서: 전환 1회(settle+dummy) → ColorConfirmer 확정 루프(모드 유지,
#   stage4_color.md §5 NOTE) → 반사광 복귀. pre_reflect = 전환 직전 반사광(기록용).
#   stage4_color.md 의 read_node_color_at_rest 와 동일 물건 — 구현을 공용으로 둔다.
```

## 3. 라이브 params (6개 이하)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `suspect_lo` | 의심대역 하한(반사광) | 미정(§7-0: 검은 선 최대 + 여유) | (0,100) | 5 | 검은 선/경계에서 오탐 → ↑. 어두운 마커 미탐 → ↓ |
| `suspect_hi` | 의심대역 상한 | 미정(§7-0: 흰 바닥 최소 − 여유) | (0,100) | 5 | 흰 바닥에서 오탐 → ↓. 밝은 마커 미탐 → ↑ |
| `suspect_hold_ms` | 대역 유지시간(의심 확정) | 80 | (15,600) | 30 | 선 경계 스파이크 오탐 → ↑. 마커를 지나쳐 미탐 → ↓ |
| `color_confirm_samples` | 같은 색 연속 확정 수 | 3 | (1,10) | 1 | 색 튐 오판 → ↑. 확정 굼뜸 → ↓ |
| `color_mode_settle_s` | 반사광→컬러 전환 settle(초) | 0.12 | (0.0,0.5) | 0.02 | 전환 직후 0/엉뚱한 색 → ↑ |
| `suspect_cooldown_ms` | 판정(오탐 포함) 후 의심 억제 | 1200 | (200,5000) | 300 | 같은 마커 이중 판정 → ↑. 연속 마커 코스에서 미탐 → ↓ |

### config/ 에 묻는 값

| 이름 | 의미 | 기본값 |
|---|---|---|
| `start/checkpoint/goal_color`, `color_dummy_reads`, restore settle 등 | stage4_color.md §3 과 동일(색코드는 §7-0 실측으로 확정) | 〃 |
| `OVERSHOOT_BACKUP_MM` | 정지 후 소량 후진(센서를 마커 중심으로) | 0 (실기에서 필요 시만) |
| 라인추종·분기 값 | stage3v2 확정값 시드(수정 금지) | kp 0.22 등 |

> 색코드 3개를 라이브에서 뺀 이유: 한 세션에서 자주 만지는 값은 의심대역/유지시간이고,
> 색코드는 §7-0 에서 한 번 실측하면 고정이다(6개 규칙 유지). 대시보드로 만질 일이
> 생기면 `suspect_cooldown_ms` 와 교체 개방(§11).

## 4. telemetry 필드 / reason_code

telemetry 추가 키: `suspect`(bool, 대역 안), `suspect_held_ms`, `color`, `node_kind`.

| reason_code | 언제 | detail |
|---|---|---|
| `SUSPECT_REFLECT` | 의심 확정(정지·컬러 확인 진입) | `reflect`, `held_ms` |
| `SUSPECT_FALSE` | 컬러 결과가 흰/없음(오탐, 주행 재개) | `reflect`, `color` |
| `COLOR_READ` / `COLOR_FLOOR_WARN` / `NODE_IS_*` | 색 확정/바닥 경고/종류 | stage4_color.md §4 와 동일 + `method:"gate"` |

구현 시 DECISIONS.md 카탈로그에 `SUSPECT_REFLECT`/`SUSPECT_FALSE` 추가.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크 비차단/stop 은 인프라 공통.

```python
def stage4c_loop():
    hold = SuspectHold(P["suspect_hold_ms"])
    last_done_ms = -999999
    while True:
        if stop_requested(): stop(); return
        raw = hw.read_reflect(); bits = black_bits(raw, thresholds)
        # --- 분기 감지/회전은 stage3v2 그대로(회전/advance 중 hold 리셋+쿨다운) ---
        gated = in_suspect_band(raw[1], P) and not in_cooldown(t_ms, last_done_ms)
        if hold.push(gated, t_ms):
            hw.stop()
            log("SUSPECT_REFLECT", reflect=raw[1], held_ms=...)
            color, pre_reflect = confirm_color_at_rest(hw, P, should_stop)
            if color in (0, 6):                      # 흰/없음 → 오탐
                log("SUSPECT_FALSE", reflect=pre_reflect, color=color)
                last_done_ms = t_ms; hold.reset()
                continue                              # 주행 재개
            log("COLOR_READ", color=color, reflect=pre_reflect, method="gate")
            kind, reason, detail = classify_node_color(color, P)
            log(reason, detail)
            last_done_ms = t_ms; hold.reset()
            hw.stop(); wait_for_trigger_or_stop()     # Stage 4 는 판정까지(기본 정지)
            continue
        # --- 라인추종 PD(stage3v2 재사용) ---
        pd_follow_step(...)
```

> 주의: 의심 확정~컬러 확정 사이 로봇은 정지 상태다. 관성으로 마커를 조금 지나쳐
> 섰다면 `pre_reflect` 가 흰 바닥 수준으로 찍히고 `COLOR_FLOOR_WARN`/`SUSPECT_FALSE`
> 가 뜬다 → 그때만 `OVERSHOOT_BACKUP_MM` 을 켠다(실패 #2 의 이 후보식 대응).

## 6. 대시보드 / CLI 연동

- `do read_reflect` / `do read_color` — 정지 실측(§7-0), 위치별 재현.
- `do gate_test` — 현재 위치에서 "의심 확정 → 컬러 확정 → 복귀" 시퀀스만 단발 실행
  (주행 없이) — 전환/확정 파이프라인 단독 보정용.
- 조정 키(라이브 set): §3 의 6개. `Space` pause/resume, `s` stop — 인프라 공통.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0. **[공통 선결 실측]** 각 마커/검은 선/흰 바닥에서 `do read_reflect`+`do read_color`
   5회씩 → PROGRESS 표. **C 성립 확인**: 마커 3색 반사광이 전부 (검은 선 최대, 흰 바닥
   최소) 사이 구간에 들어오는가. 색코드 3개도 이때 확정(config).
1. `suspect_lo` = 검은 선 최대 + 5, `suspect_hi` = 흰 바닥 최소 − 5 로 초기 설정.
2. 정지 상태 `do gate_test` 로 전환 파이프라인 보정(stage4_color.md §7-3~4 와 동일:
   `color_mode_settle_s` → `color_confirm_samples` 순).
3. 마커 위를 실주행 통과: `SUSPECT_REFLECT` 가 안 뜨면 `suspect_hold_ms` -15(또는
   대역 폭 확인). 선 경계/그림자에서 `SUSPECT_FALSE` 가 잦으면 `suspect_hold_ms` +30,
   그래도면 대역을 좁힌다(`lo` ↑ 또는 `hi` ↓, 오탐 쪽만).
4. 같은 마커 이중 판정이 나오면 `suspect_cooldown_ms` +300.
5. 세 마커 × 5회 재현 + 마커 없는 구간 오탐 0(SUSPECT_FALSE 포함 관찰) → Done, PROGRESS 기록.

## 8. 실패 모드 & 진단

- **잦은 오탐 정지(주 위험)**: `SUSPECT_FALSE` 가 자주 찍히면 코스 주행이 계속 끊긴다.
  detail 의 `reflect` 분포를 보고 — 경계값(대역 끝)에 몰려 있으면 대역을 좁히고,
  넓게 퍼져 있으면 `suspect_hold_ms` 를 올린다(원인이 다르면 손잡이도 다르다).
- **마커 미탐**: 통과 속도 대비 hold 가 길다(`suspect_held_ms` 텔레메트리가 hold 직전
  까지 갔다 리셋). `suspect_hold_ms` ↓ 가 1순위(속도는 stage3v2 확정값이라 유지).
- **정지 오버슛으로 빈 바닥 판독**: `COLOR_FLOOR_WARN` + `SUSPECT_FALSE` 조합 →
  `OVERSHOOT_BACKUP_MM` 을 10~20 으로 켠다(config, 실기 확인 후).
- **전환 직후 오판 / 색 흔들림**: stage4_color.md §8 과 동일 대응.
- **어두운 마커가 검은 선과 겹침**: `suspect_lo` 를 못 내리는 경우 — 마커색 교체 검토
  (§7-0 에서 드러남). 그 마커가 선 끝에만 있다면 B 와 결합(§11).

## 9. PC 검증

- `python3 -m py_compile stages/stage4c_reflect_gate_color.py`.
- 단위 테스트(순수): `in_suspect_band` 경계값, `SuspectHold`(유지/이탈 리셋/1회 확정),
  `validate_suspect_band`(흑/백 겹침 에러), 오탐 분기(color 0/6 → SUSPECT_FALSE 경로).
  `ColorConfirmer`/`classify_node_color` 는 stage4_color 테스트 공유.
- replay: 기록 telemetry(중앙 reflect)를 게이트 판단에 흘려 `--set suspect_hold_ms=120
  suspect_lo=18` 로 의심 확정 시점/오탐 수 변화를 로봇 없이 재연.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] §7-0 공통 선결 실측 → C 성립 확인 + 색코드/대역 초기값 확정.
- [ ] `lib/hardware.py` 컬러 전환 3함수(B/C/D 공용 — 이미 있으면 재사용).
- [ ] 판단층 `in_suspect_band`/`SuspectHold`/`validate_suspect_band` + 단위 테스트.
- [ ] 구동층 `confirm_color_at_rest`(stage4_color 의 read_node_color_at_rest 와 공용화).
- [ ] `stages/stage4c_reflect_gate_color.py` + `do gate_test` 트리거.
- [ ] 라이브 params 6개 + LIMITS + MAX_STEP, DECISIONS.md 카탈로그 갱신.
- [ ] py_compile + 단위테스트 + replay → 실기 §7 보정 → PROGRESS 기록.

## 11. 미해결 / 실기 확인 필요

- **마커 3색의 반사광이 실제로 흑/백 사이 중간대에 들어오는지(§7-0)** — C 성립 전제.
  특히 노랑(흰에 가까울 위험)과 파랑(검정에 가까울 위험)이 경계 사례.
- 의심 확정 시 정지 오버슛 거리(관성) — `OVERSHOOT_BACKUP_MM` 필요 여부.
- 오탐(SUSPECT_FALSE) 1회당 시간 비용(정지+전환 왕복+확정) 실측 — 코스 완주 시간에
  미치는 영향으로 대역 폭의 실질 상한이 정해진다.
- **B 와의 결합 여부**: 선 끝 마커(000 유발)는 B 시퀀스, 선 위 마커는 C 게이트 —
  두 트리거를 한 스크립트에 얹을지, C 단독으로 충분한지는 코스 확정 후 결정.
- 로그로 축적한 (확정 색 ↔ 진입 reflect) 대응이 안정되면 A(반사광 단독)로 승격해
  전환 비용마저 제거할 수 있는지 — 데이터가 모인 뒤 판단.
