# Stage 4-D — 반사광↔컬러 고속 교대 구현 명세 (브릿지 후보 D)

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3(`stages/stage3v2_linetrace_branch.py`) 실기 Done(2026-07-02), 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."
>
> **Stage 4 브릿지 후보 4개 중 D — 위험이 가장 크다. 구현 전 §7-0b 전환 벤치마크의
> go/no-go 를 먼저 통과해야 한다.** 나머지: [A — 반사광 단독](stage4a_reflect_only.md),
> [B — 000 의심+후진 컬러](stage4b_suspect_backup_color.md),
> [C — 반사광 게이트+컬러 확정](stage4c_reflect_gate_color.md).
> 컬러 모드 공통 부품은 [stage4_color.md](stage4_color.md) §2/§4/§5 인용.

## 0. 아이디어 요약 / 후보 비교

- **한 줄**: 중앙 컬러센서를 **반사광 모드 N루프 ↔ 컬러 모드 1슬롯**으로 빠르게
  번갈아 돌린다. 라인추종은 반사광 슬롯의 값으로(컬러 슬롯 동안은 직전 조향 유지 =
  잠깐 "눈 감고" 주행), 노드색 판정은 컬러 슬롯 샘플의 연속 확정으로 상시 수행한다.
- **장점**: 의심 트리거(A/B/C)가 아예 필요 없다 — 색 정보가 상시 들어오므로 마커
  배치/반사광 특성에 대한 가정이 최소다. 판정 즉시성이 가장 높다.
- **치명 리스크**: ev3dev 의 센서 모드 전환은 커널 드라이버 경유라 **한 번에 수십~수백
  ms 걸릴 수 있고**(stage4_color.md §8 "전환 직후 오판"과 동근원 — 정확한 시간은 실기
  bench 로만 확인, 추측 금지), 전환 직후 값이 튀어 매 슬롯 settle+더미읽기를 지불해야
  한다. 슬롯 비용(= 전환왕복 + settle×2 + 판독)이 크면 그 시간만큼 라인추종이 눈을
  감아 **곡선에서 선을 놓친다**. 그래서 이 후보만 **구현 전 벤치마크 관문**을 둔다.
- **go/no-go(§7-0b)**: 컬러 슬롯 1회 총 비용(blind 시간)이 `BLIND_BUDGET_MS`(기본 80ms
  — Stage 1~3 루프 15ms 의 ~5배, 직선 기준 허용 추정치로 시작해 실기로 조정) 를
  넘으면 **D 폐기, C 로 전환**하고 그 사실을 PROGRESS 에 기록한다.

### 후보 4개 비교(공통 표 — 4개 문서 동일 내용)

| 후보 | 트리거 | 컬러 모드 사용 | 성립 조건 | 주 위험 |
|---|---|---|---|---|
| A | 반사광 대역+유지시간 | 없음 | 5개 대역(흑/백/3색) 전부 분리 | 마커색 반사광이 흑/백과 겹침(특히 노랑≈흰) |
| B | `010`→`000` 의심지점 | 의심지점에서만(+후진) | 마커가 선 끝에 있고 반사광이 threshold 위 | 어두운 마커는 000 을 안 만듦 |
| C | 반사광 의심대역+유지 → 컬러 확정 | 의심 시에만 | "마커 vs 흑/백" 분리만 되면 됨(색끼리 분리 불필요) | 의심대역 오탐 시 잦은 정지 |
| **D(이 문서)** | 상시(반사광↔컬러 교대) | 매 슬롯 | 전환 왕복 비용이 예산 안(bench) | 전환 지연으로 라인추종 붕괴 |

> 권장 순서: **C 기본 트랙**, A 는 5대역 분리 시 최우선, B 는 막다른 길 전용 보완,
> **D 는 bench 통과 시에만**.

## 1. 목표 / 범위

- **하는 것(1단계, 관문)**: `do bench_toggle` — 정지 상태에서 반사광↔컬러 왕복 전환을
  K회 반복해 평균/최대 소요 ms 와 전환 직후 유효값까지의 더미 수를 실측, `BENCH_TOGGLE`
  이벤트로 기록. **여기서 no-go 면 이후 절은 구현하지 않는다.**
- **하는 것(2단계)**: 교대 루프 — 반사광 `interleave_every_n` 루프마다 컬러 1슬롯.
  컬러 슬롯의 색 샘플을 `ColorConfirmer`(연속 슬롯 기준)로 확정,
  `classify_node_color` 로 판정·기록. 흰(6)/없음(0)은 "마커 아님"으로 무시(상시
  판정이므로 오탐 개념이 아니라 기본 상태).
- **하는 것**: 컬러 슬롯 동안 모터는 직전 조향 유지 × `blind_speed_scale` 감속(눈 감은
  시간의 이동거리 최소화).
- **명시적으로 안 하는 것**: 색 판정에 따른 주행 결정(→ Stage 5/6), 의심 트리거(→ B/C).
- stage3v2 확정 코드는 수정하지 않고 import 재사용.

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4d_mode_interleave.py` (독립 실행 가능).
- 재사용(수정 금지): stage3v2 판단층 + `lib/turns.pivot`/`lib/decide_turn` + `lib/` 인프라.
- 컬러 전환 구동층: stage4_color.md §2 3함수(`lib/hardware.py`, B/C/D 공용).

### 판단층 (순수 함수, 하드웨어 없음)

```python
class SlotScheduler(object):
    # 루프 카운터 → 이번 루프가 컬러 슬롯인지(순수).
    def __init__(self, every_n): ...
    def tick(self) -> bool          # True = 이번 루프는 컬러 슬롯

class SlotColorConfirmer(object):
    # 연속 "컬러 슬롯" 기준 같은 색 N회 확정(마커색만; 0/6 은 리셋값).
    def __init__(self, confirm_samples): ...
    def push(self, color) -> color | None

blind_budget_ok(avg_ms, max_ms, budget_ms) -> bool   # go/no-go 판정(순수)
```

### 구동층 (ev3dev2 의존)

```python
bench_toggle(hw, k, settle_s, dummy_reads) -> {"avg_ms":…, "max_ms":…, "k":k}
#   반사광→컬러→반사광 왕복 k회, 각 왕복 소요 실측(전환+settle+dummy+판독 1회 포함).

read_color_slot(hw, settle_s, dummy_reads) -> (color, slot_ms)
#   컬러 전환 → settle/dummy → color 1샘플 → 반사광 복귀 → 소요 ms 반환.
#   slot_ms 는 매 슬롯 telemetry 로 흘려 런타임에도 예산 감시(MODE_SWITCH_SLOW).
```

## 3. 라이브 params (6개 이하)

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `interleave_every_n` | 반사광 몇 루프마다 컬러 1슬롯 | 8 | (2,50) | 5 | 추종이 흔들림(눈 감는 빈도 과다) → ↑. 마커 통과 중 슬롯이 모자라 확정 실패 → ↓ |
| `switch_settle_ms` | 전환 후 settle(ms, 슬롯당 왕복 2회 지불) | 미정(§7-0b bench) | (0,300) | 20 | 슬롯 색이 0/엉뚱 → ↑. 슬롯 비용 과다 → ↓ |
| `color_dummy_reads` | 전환 후 버리는 읽기 수 | 2 | (0,6) | 1 | settle 올려도 첫 값 튐 → ↑ |
| `color_confirm_samples` | 연속 슬롯 같은 색 확정 수 | 2 | (1,6) | 1 | 슬롯 색 튐 오판 → ↑. 마커 통과 중 확정 실패 → ↓ |
| `blind_speed_scale` | 컬러 슬롯 동안 속도 배율 | 0.7 | (0.0,1.0) | 0.1 | 슬롯 중 선 이탈 → ↓. 주행이 울컥거림 → ↑ |
| `base_speed` | 주행 속도(%) | 17(stage3v2 확정값 시드) | (5,45) | 5 | 마커 통과 시간 대비 슬롯 부족 → ↓ |

### config/ 에 묻는 값

| 이름 | 의미 | 기본값 |
|---|---|---|
| `BLIND_BUDGET_MS` | 슬롯 1회 허용 blind 시간(go/no-go·런타임 경고 기준) | 80 |
| `BENCH_K` | bench 왕복 횟수 | 20 |
| `start/checkpoint/goal_color` | 색코드(§7-0 실측, stage4_color.md §3) | 〃 |
| 라인추종·분기 값 | stage3v2 확정값 시드(수정 금지) | kp 0.22 등 |

## 4. telemetry 필드 / reason_code

telemetry 추가 키: `slot`("reflect"/"color"), `slot_ms`(직전 컬러 슬롯 비용),
`slot_color`(직전 슬롯 색), `color`(확정 색), `node_kind`.

| reason_code | 언제 | detail |
|---|---|---|
| `BENCH_TOGGLE` | `do bench_toggle` 완료 | `avg_ms`, `max_ms`, `k`, `settle_ms`, `dummy` |
| `MODE_SWITCH_SLOW` | 런타임 슬롯 비용이 예산 초과 | `slot_ms`, `budget_ms` (throttle) |
| `INTERLEAVE_COLOR` | 컬러 슬롯 샘플(디버그, throttle 0.5s) | `color`, `slot_ms` |
| `COLOR_READ` / `NODE_IS_*` | 색 확정/종류(카탈로그 공유) | stage4_color.md §4 + `method:"interleave"` |

구현 시 DECISIONS.md 카탈로그에 `BENCH_TOGGLE`/`MODE_SWITCH_SLOW`/`INTERLEAVE_COLOR` 추가.

## 5. 동작 로직 (의사코드)

브릭 코드는 Python 3.5 안전(f-string 금지). 네트워크 비차단/stop 은 인프라 공통.

```python
def stage4d_loop():
    sched = SlotScheduler(P["interleave_every_n"])
    confirmer = SlotColorConfirmer(P["color_confirm_samples"])
    while True:
        if stop_requested(): stop(); return
        if sched.tick():
            # --- 컬러 슬롯: 직전 조향 유지 + 감속, 눈 감은 시간 최소화 ---
            hw.drive(last_l * P["blind_speed_scale"], last_r * P["blind_speed_scale"])
            color, slot_ms = read_color_slot(hw, P["switch_settle_ms"]/1000.0,
                                             P["color_dummy_reads"])
            if slot_ms > BLIND_BUDGET_MS:
                log("MODE_SWITCH_SLOW", slot_ms=slot_ms, budget_ms=BLIND_BUDGET_MS)
            if color in (0, 6):
                confirmer.reset_if_needed(color)      # 마커 아님(기본 상태)
            else:
                done = confirmer.push(color)
                if done is not None:
                    log("COLOR_READ", color=done, method="interleave")
                    kind, reason, detail = classify_node_color(done, P)
                    log(reason, detail)
                    hw.stop(); wait_for_trigger_or_stop()   # Stage 4 는 판정까지
            continue
        # --- 반사광 슬롯: stage3v2 추종/분기 그대로 ---
        raw = hw.read_reflect(); ...
        last_l, last_r = pd_follow_step(...)
```

> 회전/advance(분기 처리) 중에는 컬러 슬롯을 쉬게 한다(스케줄러 일시 억제) —
> 회전 중 모드 전환이 겹치면 전환 지연이 회전 엔코더 폴링을 방해한다.

## 6. 대시보드 / CLI 연동

- `do bench_toggle` — **구현 1단계이자 관문.** 결과 `BENCH_TOGGLE` 이벤트 + 콘솔 출력.
- `do read_color` / `do read_reflect` — 정지 실측(§7-0 공통).
- 조정 키(라이브 set): §3 의 6개. `Space` pause/resume(슬롯 스케줄도 함께 멈춤),
  `s` stop — 인프라 공통.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0a. **[공통 선결 실측]** 각 마커/검은 선/흰 바닥에서 `do read_reflect`+`do read_color`
    5회씩 → PROGRESS 표(색코드 확정 포함).
0b. **[D 전용 관문 — bench]** `do bench_toggle` 실행, `avg_ms`/`max_ms` 기록.
    `switch_settle_ms` 를 0 부터 20 씩 올리며 "슬롯 색이 유효하게 나오는 최소 settle"
    을 찾고, 그때의 슬롯 총비용이 `BLIND_BUDGET_MS` 초과면 **여기서 중단, D 폐기
    기록 후 C 로.** (budget 초과 판정은 max 기준 — 최악 슬롯이 선을 놓치게 한다.)
1. 직선 코스에서 `interleave_every_n` 기본 8 로 주행 — 추종이 흔들리면 ↑(+5).
2. 곡선 코스에서 슬롯 중 이탈이 보이면 `blind_speed_scale` -0.1.
3. 마커 통과 시 확정이 안 되면(슬롯 표본 부족) `interleave_every_n` ↓ 또는
   `color_confirm_samples` -1 또는 `base_speed` -5 — 하나씩.
4. 슬롯 색이 가끔 0/엉뚱하면 `switch_settle_ms` +20, 그래도면 `color_dummy_reads` +1.
5. 세 마커 × 5회 재현 + 곡선 포함 코스에서 선 이탈 0 → Done, PROGRESS 기록.

## 8. 실패 모드 & 진단

- **전환 지연으로 추종 붕괴(주 위험)**: `MODE_SWITCH_SLOW` 가 찍히거나 telemetry
  `slot_ms` 분포가 budget 근처 → D 는 구조적으로 한계. `interleave_every_n` 을 올려
  연명하지 말고(색 감지 실효성이 죽는다) **C 전환을 판단**한다.
- **슬롯 표본 부족으로 마커 미확정**: 마커 체류 시간 = 마커 길이/속도. 그 안에 컬러
  슬롯이 `color_confirm_samples` 개 이상 들어와야 한다 —
  `(every_n × 루프주기 + slot_ms) × confirm_samples < 체류시간` 을 로그(`INTERLEAVE_COLOR`
  타임스탬프)로 검산. 부족하면 §7-3.
- **전환 직후 쓰레기값**: 슬롯 색이 0 빈발 → settle/dummy ↑ (= 슬롯 비용 ↑ 라는
  트레이드오프가 이 후보의 본질임을 기억).
- **울컥거리는 주행**: blind 감속/복귀가 체감되면 `blind_speed_scale` ↑ — 단 슬롯 중
  이탈과 맞바꾸는 값이다.
- **센서 모드 전환의 장기 안정성**: 수천 회 전환 시 드라이버가 가끔 실패/지연하는지
  — 장시간 주행 로그의 `MODE_SWITCH_SLOW` 빈도로 감시(§11).

## 9. PC 검증

- `python3 -m py_compile stages/stage4d_mode_interleave.py`.
- 단위 테스트(순수): `SlotScheduler`(every_n 주기 정확성), `SlotColorConfirmer`
  (연속 확정/0·6 리셋/1회 반환), `blind_budget_ok` 경계값.
- replay: 슬롯 색 시퀀스(기록 telemetry `slot_color`)를 confirmer 에 흘려
  `--set color_confirm_samples=3 interleave_every_n=12` 로 확정 시점 변화 재연.
- bench 는 PC 재연 불가(하드웨어 고유) — §7-0b 실기 전용임을 테스트 주석에 명시.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] §7-0a 공통 선결 실측(색코드 포함).
- [ ] `lib/hardware.py` 컬러 전환 3함수(B/C/D 공용 — 이미 있으면 재사용) +
      `bench_toggle`/`read_color_slot`.
- [ ] **`do bench_toggle` 만 먼저 구현·실기 실행 → go/no-go 판정, PROGRESS 기록.**
      no-go 면 여기서 종료(아래 항목 착수 금지, C 로).
- [ ] 판단층 `SlotScheduler`/`SlotColorConfirmer` + 단위 테스트.
- [ ] `stages/stage4d_mode_interleave.py` 교대 루프 + 회전 중 슬롯 억제.
- [ ] 라이브 params 6개 + LIMITS + MAX_STEP, DECISIONS.md 카탈로그 갱신.
- [ ] py_compile + 단위테스트 + replay → 실기 §7 보정 → PROGRESS 기록.

## 11. 미해결 / 실기 확인 필요

- **모드 전환 왕복의 실제 소요(ms) — 이 후보의 존폐(§7-0b).** ev3dev 드라이버 전환
  비용은 문서/추측으로 정하지 않고 bench 로만 확정한다.
- `BLIND_BUDGET_MS=80` 이 실제 곡선 추종에서 타당한지 — 직선/곡선 각각 실기로 검증
  (budget 자체를 실측으로 재조정).
- 잦은 모드 전환의 장기 안정성(드라이버 에러/지연 누적, 센서 발열 등) — 장시간 로그.
- 컬러 슬롯 동안 조향 유지 vs 정지(속도 0) 중 어느 쪽이 이탈에 강한지 —
  `blind_speed_scale=0` 이 사실상 "슬롯마다 미세 정지" 모드라 param 하나로 실험 가능.
- 마커 길이(mm) 실측 — 슬롯 표본 수 검산(§8)의 입력.
