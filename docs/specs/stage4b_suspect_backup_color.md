# Stage 4-B — 000 의심지점 컬러 판독(+후진) 구현 명세 (브릿지 후보 B)

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3(`stages/stage3v2_linetrace_branch.py`) 실기 Done(2026-07-02), 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."
>
> **Stage 4 브릿지 후보 4개 중 B.** 나머지: [A — 반사광 단독](stage4a_reflect_only.md),
> [C — 반사광 게이트+컬러 확정](stage4c_reflect_gate_color.md),
> [D — 반사광↔컬러 고속 교대](stage4d_mode_interleave.md).
> 컬러 모드 공통 부품(전환 settle/더미읽기·`ColorConfirmer`·`classify_node_color`·
> `COLOR_READ`/`COLOR_FLOOR_WARN`/`NODE_IS_*` reason)은 [stage4_color.md](stage4_color.md)
> §2/§4/§5 를 그대로 인용한다(여기 중복 기술하지 않음). **채택 결정은 §7-0 공통 선결 실측 후.**

## 0. 아이디어 요약 / 후보 비교

- **한 줄**: 평소엔 반사광 모드로만 달린다(전환 비용 0). `010`(선 위 직진)으로 진행하다가
  **`000`(전부 흰)이 지속되는 "의심지점"에서만** 컬러 모드를 켠다. 000 은 ① 선이 끝났다
  (막다른 길 — 마커가 있을 자리) ② 밝은 마커 위를 지나는 중 ③ 선 이탈, 셋 중 하나다.
  이미 마커를 **지나쳤을 가능성이 크므로 후진**하면서 색을 읽어 마커를 되찾는다.
- **장점**: 컬러 모드 전환이 의심지점에서만 1회 — 라인추종 루프는 전혀 느려지지 않는다.
  막다른 길 끝 마커(선이 끊기는 지점)에 특히 자연스럽다. 후진 판독이라 "마커를 지나쳐
  빈 바닥을 읽는" 실패 #2 를 구조적으로 되돌린다.
- **성립 조건(§7-0 실측으로 확인)**: 마커가 **선 끝(또는 선 위)에 있고**, 마커 반사광이
  중앙 threshold(36) **위**여서 000 을 만들거나, 최소한 선이 끊겨 000 이 되는 코스여야
  한다. **어두운 마커(파랑/초록이 threshold 아래로 읽히면)** 는 000 을 안 만들어 B 단독
  으론 못 잡는다 — 그 경우 C 로.

### 후보 4개 비교(공통 표 — 4개 문서 동일 내용)

| 후보 | 트리거 | 컬러 모드 사용 | 성립 조건 | 주 위험 |
|---|---|---|---|---|
| A | 반사광 대역+유지시간 | 없음 | 5개 대역(흑/백/3색) 전부 분리 | 마커색 반사광이 흑/백과 겹침(특히 노랑≈흰) |
| **B(이 문서)** | `010`→`000` 의심지점 | 의심지점에서만(+후진) | 마커가 선 끝에 있고 반사광이 threshold 위 | 어두운 마커는 000 을 안 만듦 |
| C | 반사광 의심대역+유지 → 컬러 확정 | 의심 시에만 | "마커 vs 흑/백" 분리만 되면 됨(색끼리 분리 불필요) | 의심대역 오탐 시 잦은 정지 |
| D | 상시(반사광↔컬러 교대) | 매 슬롯 | 전환 왕복 비용이 예산 안(bench) | 전환 지연으로 라인추종 붕괴 |

> 권장 순서: **C 기본 트랙**, A 는 5대역 분리 확인 시 최우선, **B 는 막다른 길 전용
> 보완**(C 와 결합 가능 — C 가 선 위 마커, B 가 선 끝 마커), D 는 bench 통과 시에만.

## 1. 목표 / 범위

- **하는 것**: `010` 직진 이력이 있는 상태에서 `000` 이 연속 확정되면 → 정지 → 컬러
  모드 전환(1회) → **저속 후진**하며 색을 읽어, 흰/없음이 아닌 색이 확정되면 그 자리에
  멈추고 `NODE_IS_*` 판정. `backup_max_mm` 안에 색을 못 찾으면 `COLOR_NOT_FOUND` 로
  기록하고 정지(선 이탈로 간주 — 재탐색은 Stage 4 범위 밖).
- **하는 것**: "직진하다가"라는 전제조건을 순수 함수로 명시(최근 히스토리의 010 비율) —
  곡선에서 순간 000 이 뜨는 흔들림과 구분한다.
- **명시적으로 안 하는 것**: 선 위(끊기지 않은 선)의 마커 감지(→ A/C), 색 판정 후 주행
  결정(U턴/복귀 → Stage 5/6), 선 재탐색.
- stage3v2 확정 코드는 수정하지 않고 import 재사용. stage3v2 의 기존 000 대응(감속
  0.55 유지 직진)은 **의심 확정 전까지** 그대로 둔다(확정되면 이 후보의 시퀀스로 전환).

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4b_suspect_backup_color.py` (독립 실행 가능).
- 재사용(수정 금지): stage3v2 판단층 + `lib/turns.pivot`/`lib/decide_turn` + `lib/` 인프라.
- 컬러 전환 구동층은 stage4_color.md §2 의 `hw.read_center_color(settle, dummy)` /
  `hw.restore_reflect_mode(settle)` / `read_center_reflect` 를 그대로 구현·재사용
  (`lib/hardware.py` 에 추가 — 후보 B/C/D 공용).

### 판단층 (순수 함수, 하드웨어 없음)

```python
class SuspectDetector(object):
    # "직진(010) 이력 + 000 연속" 의심지점 판정.
    def __init__(self, confirm_count, straight_window, straight_min): ...
    def push(self, bits) -> bool
    #   bits==(0,0,0) 이면 counter+=1, 아니면 counter=0 하고 히스토리에 bits 적재.
    #   counter >= confirm_count 이고, 000 시작 직전 straight_window 샘플 중
    #   (0,1,0) 이 straight_min 개 이상일 때만 True(1회).

# 후진 판독 결과 분류(색 확정 후):
#   stage4_color.md 의 classify_node_color(color, params) 재사용.
#   color in (0=없음, 6=흰) 은 "아직 마커 못 찾음"으로 계속 후진.
is_marker_color(color) -> bool   # color not in (0, 6)
```

### 구동층 (ev3dev2 의존)

```python
backup_and_read(hw, params, should_stop, should_pause) -> (color|None, backed_mm)
#   ① 컬러 모드 전환 1회(settle+dummy — stage4_color.md §5 NOTE: 루프 중 재전환 금지)
#   ② drive(-backup_speed, -backup_speed) 폴링 후진. 매 폴마다 color 1샘플 →
#      ColorConfirmer(color_confirm_samples). is_marker_color 확정 → 정지, 반환.
#   ③ 엔코더 기준 backup_max_mm 도달 → 정지, (None, backed_mm) 반환.
#   ④ 반환 전 반사광 모드 복귀(restore settle).
#   advance_straight(stage3v2)와 동일한 폴링 패턴(stop/pause 즉시 반응) — 부호만 후진.
```

## 3. 라이브 params (6개 이하)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `suspect_confirm_count` | 000 연속 확정 횟수 | 4 | (1,30) | 3 | 곡선 흔들림에 오탐(불필요 정지) → ↑. 마커 반응이 늦어 backup 이 길어짐 → ↓ |
| `backup_speed` | 후진 속도(%) | 8 | (3,20) | 3 | 색 샘플이 흐려/못 잡고 지나침 → ↓. 판독이 너무 느림 → ↑ |
| `backup_max_mm` | 후진 한계 거리 | 60 | (10,150) | 10 | 마커 앞에서 후진이 끝남(`COLOR_NOT_FOUND` 인데 실제론 마커 있음) → ↑ |
| `color_confirm_samples` | 같은 색 연속 확정 수 | 3 | (1,10) | 1 | 색 튐 오판 → ↑. 확정 굼뜸(후진 오버슛) → ↓ |
| `color_mode_settle_s` | 반사광→컬러 전환 settle(초) | 0.12 | (0.0,0.5) | 0.02 | 전환 직후 0/엉뚱한 색 → ↑ |
| `straight_min` | 직진 전제: 최근 창에서 010 최소 개수 | 12 | (0,20) | 2 | 곡선 000 오탐 → ↑. 진짜 선 끝을 놓침 → ↓ |

### config/ 에 묻는 값

| 이름 | 의미 | 기본값 |
|---|---|---|
| `STRAIGHT_WINDOW` | 직진 전제 히스토리 창 크기(샘플) | 20 |
| `color_dummy_reads` / `color_mode_restore_settle_s` | stage4_color.md 와 동일 | 2 / 0.08 |
| 라인추종·분기 값 | stage3v2 확정값 시드(수정 금지) | kp 0.22 등 |

## 4. telemetry 필드 / reason_code

telemetry 추가 키: `suspect_count`(000 연속), `backup_mm`(후진 진행), `color`,
`node_kind`.

| reason_code | 언제 | detail |
|---|---|---|
| `SUSPECT_000` | 의심지점 확정(후진 시퀀스 진입) | `count`, `straight_hits`, `bits_before`(직전 창 요약) |
| `BACKUP_READ` | 후진 판독 종료 | `backed_mm`, `found`(bool), `color` |
| `COLOR_NOT_FOUND` | backup_max_mm 안에 마커색 없음 | `backed_mm` |
| `COLOR_READ` / `NODE_IS_*` | 색 확정/종류(카탈로그 공유) | stage4_color.md §4 와 동일 + `method:"backup"` |

구현 시 DECISIONS.md 카탈로그에 `SUSPECT_000`/`BACKUP_READ`/`COLOR_NOT_FOUND` 추가.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크 비차단/stop 은 인프라 공통.

```python
def stage4b_loop():
    det = SuspectDetector(P["suspect_confirm_count"], STRAIGHT_WINDOW, P["straight_min"])
    while True:
        if stop_requested(): stop(); return
        raw = hw.read_reflect(); bits = black_bits(raw, thresholds)
        # --- 분기 감지/회전은 stage3v2 그대로(생략). 회전/advance 후 det 리셋 ---
        if det.push(bits):
            hw.stop()
            log("SUSPECT_000", count=..., straight_hits=...)
            color, backed = backup_and_read(hw, P, should_stop, should_pause)
            if color is None:
                log("COLOR_NOT_FOUND", backed_mm=backed)
                hw.stop(); wait_for_trigger_or_stop()   # 선 이탈 취급, 사람 개입
            else:
                log("COLOR_READ", color=color, method="backup", backed_mm=backed)
                kind, reason, detail = classify_node_color(color, P)  # stage4_color 재사용
                log(reason, detail)
                hw.stop(); wait_for_trigger_or_stop()   # Stage 4 는 판정까지
            det.reset()
            continue
        # --- 000 미확정 구간: stage3v2 기존 동작(감속 유지 포함) 그대로 ---
        pd_follow_step(...)
```

## 6. 대시보드 / CLI 연동

- `do read_color` — 정지 상태 색 1회 판독(§7-0 실측 + 위치별 재현, stage4_color.md §6).
- `do backup_read` — 현재 위치에서 후진 판독 시퀀스만 단발 실행(의심 감지 없이) —
  후진 거리/속도/confirm 보정용 단일 트리거.
- `do nudge <ms>` — 마커를 살짝 지나친 위치를 만들어 `do backup_read` 재현.
- 조정 키(라이브 set): §3 의 6개. `Space` pause/resume, `s` stop — 인프라 공통.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0. **[공통 선결 실측]** 각 마커/검은 선/흰 바닥에서 `do read_reflect`+`do read_color`
   5회씩 → PROGRESS 에 표. **B 성립 확인**: 마커 반사광이 중앙 threshold(36) 위인가
   (000 을 만드는가), 마커가 선 끝에 배치되는 코스인가. 아니면 B 폐기 → C.
1. 색코드/전환 안정화 보정은 stage4_color.md §7-1~4 와 동일(같은 부품).
2. **후진 판독 단발 보정**: 마커를 ~30mm 지나친 위치에 로봇을 두고 `do backup_read`.
   못 찾으면 `backup_max_mm` +10. 색이 튀면 `color_confirm_samples` +1. 확정이 늦어
   마커를 되지나치면 `backup_speed` -3.
3. **의심 감지 보정**: 직선 끝 마커로 실주행. 곡선/흔들림에서 `SUSPECT_000` 오탐이면
   `suspect_confirm_count` +3 또는 `straight_min` +2(하나만). 진짜 선 끝에서 감지가
   늦으면(backed_mm 가 항상 큼) `suspect_confirm_count` -3.
4. 세 마커 × 5회 재현 + 곡선 코스 오탐 0 → Done, PROGRESS 기록.

## 8. 실패 모드 & 진단

- **어두운 마커(치명, B 단독 폐기 사유)**: 파랑/초록 반사광이 threshold 아래면 000 이
  아니라 010/111 로 보여 감지 자체가 안 된다. §7-0 에서 걸러 C 로 보완/전환.
- **곡선에서 000 오탐**: `SUSPECT_000` 의 `straight_hits` 가 낮게 찍히면 직진 전제가
  약한 것 → `straight_min` ↑. 사행(뱀주행) 중 000 은 짧으므로 `suspect_confirm_count` ↑.
- **후진 중 마커를 되지나침**: `BACKUP_READ` 의 `backed_mm` 이 마커 위치보다 큼 →
  `backup_speed` ↓ 또는 `color_confirm_samples` ↓ (확정 지연이 원인인지 로그로 구분).
- **후진이 선을 벗어남(비스듬한 진입)**: 000 진입이 사행 끝이었으면 후진 궤적이 선과
  어긋난다 — `straight_min` 을 올려 "곧게 들어온 경우"만 시퀀스에 태우는 게 1차 대응.
- **전환 직후 오판**: stage4_color.md §8 과 동일(`color_mode_settle_s`/`dummy_reads` ↑).

## 9. PC 검증

- `python3 -m py_compile stages/stage4b_suspect_backup_color.py`.
- 단위 테스트(순수): `SuspectDetector` — ① 010×N 후 000×confirm → True 1회,
  ② 곡선 히스토리(110/011 섞임, straight_min 미달) 후 000 → False, ③ 000 중단 시 리셋.
  `is_marker_color` — 0/6 False, 2/4/5 True. `classify_node_color` 는 stage4_color 테스트 공유.
- replay: 실주행 telemetry(bits 시퀀스)를 `SuspectDetector` 에 흘려
  `--set suspect_confirm_count=6 straight_min=14` 로 의심 확정 시점 변화를 재연.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] §7-0 공통 선결 실측 → **B 성립 여부 먼저 판정**(마커 위치·반사광).
- [ ] `lib/hardware.py` 컬러 전환 3함수(stage4_color.md §2 — B/C/D 공용) 추가.
- [ ] 판단층 `SuspectDetector`/`is_marker_color` + 단위 테스트.
- [ ] 구동층 `backup_and_read`(advance_straight 폴링 패턴, stop/pause 반응).
- [ ] `stages/stage4b_suspect_backup_color.py` + `do backup_read` 트리거.
- [ ] 라이브 params 6개 + LIMITS + MAX_STEP, DECISIONS.md 카탈로그 갱신.
- [ ] py_compile + 단위테스트 + replay → 실기 §7 보정 → PROGRESS 기록.

## 11. 미해결 / 실기 확인 필요

- **마커 배치(선 끝 vs 선 위)와 마커 반사광(§7-0)** — B 성립의 전제. 코스 확정 필요.
- 후진 중 이동하면서 읽는 컬러 값이 정지 판독 대비 얼마나 흔들리는지(backup_speed 상한).
- 000 의심지점이 "막다른 길"과 "선 이탈"을 실기에서 얼마나 잘 가르는지 —
  `COLOR_NOT_FOUND` 빈도로 판단.
- stage3v2 의 000 감속 직진(0.55)과 의심 카운트가 상호작용해 감지 거리(선 끝을 지나
  얼마나 가서 서는지)가 얼마나 되는지 — `backup_max_mm` 기본값의 근거가 된다.
