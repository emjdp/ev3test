# Stage 3 — 노드(분기) 감지 구현 명세

> **⚠️ 폐기 (2026-07-02).** 아래 아날로그 centroid(`pos`/`total`) 설계는 코드 착수 전에
> [stage3v2_linetrace_branch.md](stage3v2_linetrace_branch.md)(bits+PD 라인추종 + 탱크 회전,
> `stages/stage3v2_linetrace_branch.py`)가 **공식 Stage 3 로 채택**되면서 대체됐다(사용자 결정,
> [PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그). **이 문서로 새로 구현하지 않는다** —
> 히스토리 참고용으로만 남겨둔다.

> 상태: DRAFT (실기 미검증, **2026-07-01 아날로그 방식으로 개정 — §0 참조**)
> 선행: Stage 1(라인트레이싱) 실기 Done — 이 단계는 Stage 1에서 확정한 **하드웨어/주행
> 기반**(모터 부호 `left=base-turn`/`right=base+turn`, 속도 기조)은 유지하되, **주행 판단은
> 좌·중·우 3센서 기반**(`decide_line3`)으로 한다. Stage 1 중앙센서 단일 PID 를 그대로 쓰지 않는다.
> 인프라([00_infra_dashboard.md](00_infra_dashboard.md))의 record/replay 가 동작해야 한다.
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 3 인용 —
> "코스 위 각 노드 종류(T자, 십자, 좌/우 분기, 막다른 길)를 **노드 위에서** 멈춰 올바른
> 패턴으로 출력. 주행 중 흔들림에 오감지하지 않는다."

상위 규칙: [../../AGENTS.md](../../AGENTS.md) · 라이브 튜닝/대시보드: [../LIVE_TUNING.md](../LIVE_TUNING.md) ·
판단기록/재연: [../DECISIONS.md](../DECISIONS.md) · 배선: [../HARDWARE.md](../HARDWARE.md).

---

## 0. 설계 개정 (2026-07-01) — bits+시간 → 아날로그 centroid + 총 어둠

**배경(실기).** 센서 3개가 **딱 붙어 있고**(사진 확인) **선 폭 ≈ 센서 폭**이다. 이 배치에서:

- 초기 설계(bits 를 threshold 로 자르고 `r-l` raw 차로 조향)는 정상 추종 중 좌/우 센서가
  둘 다 흰 바닥이라 raw 차가 "흰색 읽는 값 불일치(상시 편향)"만 먹어 **시작하자마자 한쪽으로
  꺾였다**(로그 `runs/2026-07-01T09-11-12`).
- 조향을 bits 위치 오차로 1차 수정했으나, 근본 문제는 남는다: **`110`/`011`/`111` 이 주행 중에도
  상시 뜬다**(선이 인접 센서로 넘침). 그래서 "이게 코너/분기냐 vs 잠깐 삐끗이냐"를 **시간 지속
  (debounce)** 으로만 갈라야 했는데, 이는 속도 의존적이고 튜닝 트레이드오프가 크다.
- 센서 간격은 **넓히지 않기로 확정**(넓히면 드리프트 때 선이 센서 사이 틈에 빠져 `000` 오탐).

**개정 방향.** 붙어 있는 센서 어레이는 **아날로그(raw) centroid 라인트레이서의 정석 배치**다.
bits(0/1)로 자르지 말고 raw 를 정규화해 서로 **직교하는 두 물리량**을 쓴다.

1. **위치(무게중심) `pos`** = 세 센서의 "검은 정도" 가중 평균 위치 → **조향**.
   선이 두 센서에 걸쳐도 걸친 비율만큼 연속값이 나와 부드럽고 편향이 없다.
2. **총 어둠 `total`** = 세 센서 darkness 합(어레이 밑 검은 면적) → **노드 감지**.
   - 드리프트: 선이 옆으로 옮겨갈 뿐 → `total` **보존(거의 일정)**, `pos` 만 이동.
   - 노드(분기/교차/코너): 없던 검정이 추가됨 → `total` **급증**.
   - 즉 **`total > 임계` = 노드**. "얼마나 오래 봤나(시간)"에 의존하지 않고 갈라진다.

**bits 는 버리지 않는다.** telemetry/로그 가독용과 **노드 종류(어느 쪽 갈래)** 참고용으로만
유지하고(그 정밀 구분과 회전은 Stage 5), **조향과 노드 트리거의 판단은 pos/total(아날로그)** 이 한다.

**필수 선행: 센서별 흰/검 캘리브레이션.** 정규화하려면 센서마다 white/black 실측값이 있어야 한다.
실측(2026-07-01 antigravity): **검≈(10,10,10) / 흰≈(75,64,75)** — 센서마다 흰색값이 다르다(중앙 64
vs 옆 75). 이 값이 `sensor_darkness` 초기 시드가 되고, `do calibrate` 스윕으로 재확인·갱신(§5.3).

> 이하 본문은 이 개정을 반영한다. 초기 bits+시간 설계 흔적(§구 `NodeDebouncer` 시간 기반 등)은
> "구 방식"으로 표시하고 아날로그 방식으로 대체한다. 코드도 이 순서로 단계 이행(§10 체크리스트).

---

## 1. 목표 / 범위

**하는 것** (2026-07-01 아날로그 개정 반영 — §0)

- **좌·중·우 3센서**의 raw 반사광을 센서별 흰/검 캘리브레이션으로 **darkness(0~1)** 로 정규화한다.
  - 약속: `darkness=1 = 완전 검은 선`, `0 = 흰 바닥`. (반사광은 흰 바닥=큰 값, 검은 선=작은 값.)
- 세 darkness 로 두 직교량을 만든다:
  - **`pos`(무게중심, −1~+1)** = 선의 좌우 위치 → **조향**(`decide_line3`, 아날로그 P).
  - **`total`(darkness 합, 0~3)** = 어레이 밑 검은 면적 → **노드 감지**(`total>임계`).
- `total` 로 **분기·교차·막다른 길·코너(=검은 면적이 넓거나 없음)** 를 감지한다. 드리프트는
  `total` 이 보존돼 걸러진다(시간 지속 debounce 에 의존하지 않음).
- **아날로그 centroid 라인추종**(`decide_line3`)으로 "**선 따라가다 노드에서 멈춤**"까지 한다.
  Stage 1 중앙센서 단일 PID 를 재사용하지 않는다 — Stage 1 의 **부호/속도 기조만** 따른다.
- 노드 확정 시 `total`·`pos`·bits·진입거리를 reason 로그로 남긴다(`NODE_CANDIDATE`/`NODE_CONFIRMED`).
- **판단층(darkness/pos/total/`node_kind`)을 순수 함수**로 둬, 기록한 센서로 **로봇 없이 재연**(`replay.py`).
- **bits(`LCR`)는 telemetry/로그 가독 + 노드 종류 참고용으로만** 유지한다(자동 threshold=흰/검 중간값).
  - 예: `010`=직선 / `111`=십자 / `110`·`011`=좌/우 갈래 / `000`=선 없음. **조향/트리거 판단엔 안 씀.**

**안 하는 것 (다음 단계로 미룸)**

- **회전 안 함.** 노드에서 멈추고 패턴만 출력. 분기 선택·회전은 Stage 5.
- **색 판정 안 함.** 막다른 길/노드 색 읽기는 Stage 4(반사광↔컬러 모드 전환은 여기서 안 섞음).
- 탐색/복귀 알고리즘 없음(Stage 6).

---

## 2. 파일 / 인터페이스

| 경로 | 내용 |
|---|---|
| `stages/stage3_node_detect.py` | 독립 실행 진입점. 초기 params/LIMITS/STEP + follow/노드 상수, `do calibrate`/`follow` 루프. |
| `lib/nodes.py` (판단층, **순수**) | **`sensor_darkness`, `line_position`, `total_darkness`, `decide_line3`(아날로그 centroid), `NodeDetector`(total 기반)**. + 로그용 `bits_from_raw`/`node_kind`/`bits_str`. ev3dev2·모터 없음. |
| `lib/calib.py` (신규, 순수) | 센서별 흰/검 값 로드/저장·정규화 헬퍼. `do calibrate` 결과를 `config/stage3_calib.json` 에 묻는다. |
| `lib/hardware.py` (기존) | `read_reflect()`(좌/중/우), `enc_avg()`(이동거리 추정), 캘리브레이션 스윕용 저속 pivot. 재사용. |
| `tools/replay.py` (기존, 인프라) | 기록한 samples(reflect+calib)를 `decide_line3`/`NodeDetector` 에 재연. |

**판단층 (순수, PC import·재연 가능) — `lib/nodes.py`**

```python
def sensor_darkness(raw, calib):
    """raw 반사광 3개(L,C,R) → darkness 3개(0=흰,1=검). 센서별 흰/검으로 정규화.
       calib = {"white": (wl,wc,wr), "black": (bl,bc,br)}.
       d_i = clamp((white_i - raw_i) / (white_i - black_i), 0, 1).  분모≈0 방어."""


def line_position(dark):
    """darkness (dL,dC,dR) → 무게중심 pos ∈ [-1,+1].  (센서 위치 -1/0/+1 가중)
       pos = (dL*-1 + dR*+1) / (dL+dC+dR).  합≈0(선 없음)이면 None."""


def total_darkness(dark):
    """darkness 합 ∈ [0,3]. 어레이 밑 검은 '면적' 지표(노드 감지의 핵심)."""


def decide_line3(raw, calib, params, state):
    """아날로그 centroid 라인추종 1틱(순수). 노드 확정 전 FOLLOW 조향.

    pos = line_position(...). turn = clamp(follow_kp * pos, ±turn_limit).
      부호(Stage 1 동일): pos>0(선이 오른쪽) → 오른쪽 보정 → turn<0 → left=base-turn(빠름).
      pos is None(선 없음, total≈0) → 속도 0 + 직전 조향 유지(보수적, dead-end 는 NodeDetector 가).
    반환 action(dict): {line, pos, total, turn, left, right}."""


def node_kind(bits):
    """bits(LCR, 로그/종류 참고용) → 'LINE'|'CORNER_L'|'CORNER_R'|'CROSS'|'DEAD_END'.
       ⚠️ 조향/트리거 판단에는 쓰지 않는다(그건 pos/total). Stage5 종류 판정의 씨앗."""
```

```python
class NodeDetector(object):
    """총 어둠(total) 기반 노드 감지 (순수, 거리는 mm/샘플로 받음 — 속도 무관).

    - total > node_total_on 이 node_confirm_mm 만큼 '거리로' 지속되면 NODE_CONFIRMED.
      (구 NodeDebouncer 의 '같은 bits 가 node_confirm_ms 지속'을 대체 — 시간→거리, 패턴→면적.)
    - total 이 node_total_on 아래로 내려가면 후보 리셋(드리프트/노이즈 무시).
    - 직전 확정 뒤 node_debounce_mm 안에는 재확정 금지(같은 노드 중복 감지 방지).

    push(dark, dist_mm, params) -> (status, info)
      status : 'NODE_CONFIRMED' | 'NODE_CANDIDATE' | None
      info   : {total, pos, bits, kind, run_mm(지속 거리), dist_mm, debounce_mm}
    """
```

> 참고(이전 로봇 `run/solver.py`): `event_kind`(JUNCTION/LEAF/None), `ArrivalDebouncer`(leaf 를 더
> 보수적으로 확정)의 **구조**가 검증돼 있다. 그 프로젝트는 bits+시간·단일 `config.py` 였다 —
> 여기서는 **아이디어만** 취하고, 감지는 **아날로그 total + 거리(dist_mm)** 로 바꿔 속도/편향에
> 강하게 한다. (구 `NodeDebouncer`(bits+ms)는 이 개정으로 대체 — 코드는 §10 순서로 이행.)

**구동층 (ev3dev2)**: `decide_line3`(아날로그)로 구동 + `hardware`(`read_reflect`, `enc_avg`).
Stage 3은 **새 모터 동작이 거의 없다**(노드에서 `stop` + `node_advance` 전진, `do calibrate` 저속 스윕).

---

## 3. 라이브 params (6개 이하)

이 단계 라이브 노출은 **6개**(딱 한도). 그 이상 필요해지면 검증된 값을 `config/` 로 내린다.
**아날로그 개정(§0)으로 라이브 6개가 threshold 3개 → 조향/노드 손잡이로 교체된다.** 센서별 흰/검
값은 라이브가 아니라 **캘리브레이션 상수**(config, `do calibrate` 로 확보)라 6개 한도를 안 먹는다.

| 이름 | 의미 | 기본값 | LIMITS (min,max) | MAX_STEP | 올림/내림 |
|---|---|---|---|---|---|
| `follow_kp` | 조향 게인 (pos[-1..1] 당 turn) | 25 | (0, 80) | 5 | 흔들림/과조향 → ↓ / 곡선 못 따라감 → ↑ |
| `follow_base_speed` | 직진 기본 속도(%) — Stage1 기조 | 20 | (5, 45) | 5 | 곡선에서 빠르면 ↓ |
| `node_total_on` | **노드 트리거 임계**(darkness 합, 0~3) | 1.7 | (1.0, 3.0) | 0.2 | 직선에서 오탐 → ↑ / 노드 못 잡음 → ↓ |
| `node_confirm_mm` | total>on 이 이 거리만큼 지속돼야 확정 | 8 | (2, 40) | 3 | 단발 스파이크 오탐 → ↑ / 노드 지나침 → ↓ |
| `node_debounce_mm` | 직전 확정 후 재확정 금지 거리(중복 방지) | 60 | (10, 200) | 10 | 한 노드 두 번 → ↑ / 가까운 두 노드 하나로 → ↓ |
| `node_advance` | **노드 확정 후 회전/색읽기 전 전진량(mm)** | 0 | (0, 60) | 5 | 정지 위치가 노드 못 미침 → ↑ / **오버슛(실패#1)** → ↓ |

> **`node_total_on` 이 이 단계의 새 핵심 손잡이.** "검은 면적이 이만큼 넓으면 노드"라는 하나의
> 물리 임계로 분기/교차/코너를 잡는다. 드리프트는 total 이 보존돼 여기 안 걸린다.
> **`node_advance` 는 실패 #1(분기/코너 오버슛) 손잡이로 그대로 유지.** 확정 후 그 자리 bits/거리
> 기록은 Stage 5 회전 위치 보정에 쓰인다.

**config/ 로 내리는 값(라이브 노출 안 함)**: `loop_delay`(Stage1 확정), `follow_turn_limit`(35, Stage1
기조), `advance_speed`(느리게 고정), `post_stop_settle_ms`, 그리고 **센서 캘리브레이션**
(`config/stage3_calib.json`: 센서별 white/black — `do calibrate` 로 채움, §5.3).

```python
INITIAL_PARAMS = {
    "follow_kp": 25, "follow_base_speed": 20,
    "node_total_on": 1.7, "node_confirm_mm": 8, "node_debounce_mm": 60, "node_advance": 0,
}
PARAM_LIMITS = {
    "follow_kp": (0,80), "follow_base_speed": (5,45),
    "node_total_on": (1.0,3.0), "node_confirm_mm": (2,40),
    "node_debounce_mm": (10,200), "node_advance": (0,60),
}
MAX_STEP = {
    "follow_kp": 5, "follow_base_speed": 5,
    "node_total_on": 0.2, "node_confirm_mm": 3, "node_debounce_mm": 10, "node_advance": 5,
}
```

> **왜 threshold 3개를 라이브에서 뺐나:** 아날로그에선 흰/검 정규화가 캘리브레이션 상수로 흡수돼
> 라이브 튜닝이 필요 없다. bits 는 로그용이라 threshold=(white+black)/2 로 자동 유도(라이브 아님).

---

## 4. telemetry 필드 / reason_code

**추가 telemetry 키** (제어 틱마다; record 의 `samples.jsonl` 핵심)

| 키 | 의미 |
|---|---|
| `reflect` | 좌/중/우 raw 반사광 `(l,c,r)` |
| `darkness` | 정규화 darkness `(dL,dC,dR)` 0~1 (캘리브레이션 적용) |
| `pos` | 무게중심 위치 −1~+1 (조향 오차; 선 없음이면 `null`) |
| `total` | darkness 합 0~3 (**노드 감지 지표**) |
| `bits` | 로그 가독용 "LCR"(threshold=흰/검 중간, 판단엔 안 씀) |
| `turn` / `left_speed` / `right_speed` | 조향/구동 출력 |
| `enc_avg` | 누적 엔코더 평균(도) — dist_mm 환산용 |
| `dist_mm` | 직전 노드(또는 시작) 이후 진행 거리(mm) |
| `node_run_mm` | 현재 `total>on` 연속 지속 거리(디버그; 확정 판정) |

**reason_code** (events.jsonl, [DECISIONS.md](../DECISIONS.md) 카탈로그와 일치)

| reason_code | 언제 | detail |
|---|---|---|
| `LINE_FOLLOW` | 아날로그 추종 중(주기 제한 로깅) | `reflect`, `pos`, `total`, `turn` |
| `NODE_CANDIDATE` | 노드 후보(`total>node_total_on` 막 진입) | `total`, `pos`, `bits`, `reflect` |
| `NODE_CONFIRMED` | 노드 확정(멈춤; total 이 confirm_mm 지속) | `total`, `bits`, `kind`, `run_mm`, `debounce_mm`, `dist_mm` |
| `CORNER_LEFT` / `CORNER_RIGHT` | 확정 노드의 bits 가 `110`/`011`(종류 참고) | `bits` |
| `LINE_LOST` / `LINE_RECOVER` | 선 유실/복구(`total≈0` 이 DEAD_END 확정 전) | `total` |
| `EMERGENCY_STOP` | 네트워크 stop 또는 watchdog 안전정지 | `source` |
| `CALIBRATE` | `do calibrate` 스윕 완료(센서별 흰/검 저장) | `white`, `black` |

> `dist_mm`·`run_mm` 은 **엔코더에서 환산**한다(바퀴 지름 → 1도당 이동거리, Stage 0/2 측정값).
> 실패 #1 진단의 핵심 필드이므로 `NODE_CONFIRMED` 에 반드시 채운다.
> 노드 트리거는 `duration_ms`(시간)가 아니라 `run_mm`(거리)다 — 속도 무관(개정 §0).

---

## 5. 동작 로직 (의사코드)

EV3 코드는 **Python 3.5 안전**(f-string 금지, `.format()`).

### 5.1 제어 루프 (stage3_node_detect.py) — 아날로그 개정

```python
def main():
    hw = Ev3Hardware()
    params = dict(INITIAL_PARAMS)
    server = start_tuning_server(params, PARAM_LIMITS, MAX_STEP, actions=["follow","calibrate","nudge"])
    log = ReasonLogger()
    calib = load_calib("config/stage3_calib.json")   # 센서별 white/black (없으면 안전 기본)
    det = NodeDetector()                              # total 기반 순수 판정기
    follow_state = make_follow_state()                # 조향 상태(last_turn 보관)
    state = {"node_dist0_deg": 0}                     # 직전 노드 이후 거리 기준점

    hw.reset_encoders()
    while True:
        if server.stop_requested():
            hw.stop(); log.event("EMERGENCY_STOP", source="NET"); break
        if server.pending("calibrate"):
            calib = run_calibration(hw, log); save_calib("config/stage3_calib.json", calib)
            continue
        snap = server.snapshot_params()               # 네트워크는 제어를 블록하지 않음

        raw = hw.read_reflect()                       # (l,c,r)
        dark = sensor_darkness(raw, calib)            # (dL,dC,dR) 0~1
        pos = line_position(dark)                     # -1~+1 또는 None(선 없음)
        total = total_darkness(dark)                  # 0~3
        bits = bits_from_raw(raw, calib_mid(calib))   # 로그용만
        dist_mm = deg_to_mm(hw.enc_avg() - state["node_dist0_deg"])

        status, info = det.push(dark, dist_mm, snap)  # total>on 이 confirm_mm 지속?

        if status == "NODE_CANDIDATE":
            log.event("NODE_CANDIDATE", total=total, pos=pos, bits=bits_str(bits), reflect=raw)
            drive_follow(hw, raw, calib, snap, follow_state)   # 후보 단계도 노드 중심까지 추종
        elif status == "NODE_CONFIRMED":
            hw.stop()                                 # 노드 위에서 멈춤(회전은 Stage5)
            k = node_kind(bits)
            if k == "CORNER_L": log.event("CORNER_LEFT", bits=bits_str(bits))
            if k == "CORNER_R": log.event("CORNER_RIGHT", bits=bits_str(bits))
            log.event("NODE_CONFIRMED", total=total, bits=bits_str(bits), kind=k,
                      run_mm=info["run_mm"], debounce_mm=snap["node_debounce_mm"], dist_mm=dist_mm)
            advance(hw, snap["node_advance"])         # 확정 후 전진량(실패#1 손잡이)
            hw.beep_ok()
            state["node_dist0_deg"] = hw.enc_avg()    # 거리 기준점 갱신(debounce_mm 와 함께)
            wait_or_stop(hw)                          # 1노드1정지 / 연속(운용 선택)
        else:
            drive_follow(hw, raw, calib, snap, follow_state)   # 아날로그 centroid 추종

        push_telemetry(server, reflect=raw, darkness=dark, pos=pos, total=total,
                       bits=bits_str(bits), dist_mm=dist_mm, enc_avg=hw.enc_avg(),
                       node_run_mm=info.get("run_mm", 0))
        sleep(snap_loop_delay)


def drive_follow(hw, raw, calib, snap, follow_state):
    follow_p = merge(snap, FOLLOW_CONSTS)             # follow_turn_limit 등 config 상수 병합
    action = decide_line3(raw, calib, follow_p, follow_state)
    hw.drive(action["left"], action["right"])
    maybe_follow_log(action)                          # LINE_FOLLOW 주기 로깅(pos/total/turn)
```

### 5.2 노드 확정 후 전진 (구동, 짧고 느리게)

```python
def advance(hw, node_advance_mm):
    """노드 확정 후 회전/색읽기 위치까지 살짝 전진. 거리는 엔코더로.
       node_advance==0 이면 제자리. 느린 고정 속도(ADVANCE_SPEED, config)."""
    if node_advance_mm <= 0:
        return
    start = hw.enc_avg()
    hw.drive(ADVANCE_SPEED, ADVANCE_SPEED)
    while deg_to_mm(hw.enc_avg() - start) < node_advance_mm:
        if server.stop_requested():
            break
        sleep(0.005)
    hw.stop()
```

> `node_advance` 는 **엔코더 거리(mm) 기반**(시간 ms 아님). 이전 로봇은 `STRAIGHT_NUDGE_SECONDS`
> 같은 ms 였는데, 배터리/마찰에 흔들려 오버슛을 만들었다. 거리 기반이면 보정 손잡이가 하나로
> 줄고 replay 에서도 dist_mm 로 바로 검증된다.

### 5.3 센서 캘리브레이션 (`do calibrate`) — 아날로그의 필수 선행

정규화(`sensor_darkness`)에 센서별 흰/검 값이 있어야 한다. 로그상 센서마다 흰색 읽는 값이
제각각(중앙 10 vs 옆 5~6, 다른 때 20/14)이라 **고정값으로는 total/pos 가 틀어진다.** 버튼을
쓰지 않으므로(규칙) `do calibrate` 트리거로 로봇이 스스로 스윕해 센서별 min(검)/max(흰)을 잡는다.

```python
def run_calibration(hw, log):
    """제자리 저속 pivot 으로 좌우로 살짝 쓸며 각 센서가 흑·백을 모두 지나게 한다.
       스윕 동안 센서별 min(=검은 선)·max(=흰 바닥) raw 를 기록. 회전은 작게(±).
       ⚠️ 시작 시 어레이가 선 위(중앙이 선)에 있어야 세 센서가 흑·백을 다 본다."""
    lo = [999, 999, 999]; hi = [0, 0, 0]
    hw.pivot_slow(+1)                     # 오른쪽으로 살짝
    for _ in range(sweep_ticks):
        r = hw.read_reflect(); update_min_max(lo, hi, r); sleep(0.01)
    hw.pivot_slow(-1)                     # 왼쪽으로 되돌며(원위치 지나 반대까지)
    for _ in range(2 * sweep_ticks):
        r = hw.read_reflect(); update_min_max(lo, hi, r); sleep(0.01)
    hw.pivot_slow(+1)                     # 대략 원위치 복귀
    for _ in range(sweep_ticks):
        r = hw.read_reflect(); update_min_max(lo, hi, r); sleep(0.01)
    hw.stop()
    calib = {"white": tuple(hi), "black": tuple(lo)}
    log.event("CALIBRATE", white=calib["white"], black=calib["black"])
    return calib
```

> **검증 포인트**(스윕 후 telemetry 로): 중앙을 선 위에 두면 `dark≈(0,1,0)`, `pos≈0`, `total≈1`.
> 흰 바닥에선 `total≈0`. 교차/분기 위에선 `total≥2`. 이 값이 안 나오면 스윕 각/속도(config)나
> 센서 높이를 손본다. 캘리브레이션 값은 `config/stage3_calib.json` 에 저장돼 재시작에도 유지된다.
> 조명이 바뀌면 다시 `do calibrate`.

---

## 6. 대시보드 / CLI 연동

```bash
python tools/robotctl.py do calibrate       # 센서 흰/검 스윕 → config/stage3_calib.json (먼저!)
python tools/robotctl.py do follow          # 선 따라가다 노드에서 멈추는 1세트 실행
python tools/robotctl.py do nudge 10         # 10mm 전진(노드 확정 위치 미세 확인)
python tools/robotctl.py set node_total_on 1.9
python tools/robotctl.py set follow_kp 20
python tools/robotctl.py set node_advance 8
python tools/robotctl.py stop               # 네트워크 정지
python tools/robotctl.py save               # config/stage3.json 저장(라이브 6개)
python tools/replay.py runs/<ts> --set node_total_on=1.9 node_confirm_mm=6
```

TUI 권장 키: `k`=do calibrate, `f`=do follow, `[`/`]`=node_advance ∓/±,
`t`/`T`=node_total_on ∓/±, `p`/`P`=follow_kp ∓/±, `s`=STOP.
화면에 현재 `pos`·`total`·`bits`·`dist_mm` 상시 표시.

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

0. **캘리브레이션 먼저(`do calibrate`).** 어레이 중앙을 선 위에 두고 실행 → 센서별 흰/검 저장.
   검증(telemetry): 중앙만 선 위 `dark≈(0,1,0)`/`pos≈0`/`total≈1`, 흰 바닥 `total≈0`,
   교차 위 `total≥2`. 안 나오면 스윕 각/센서 높이 손봄. **이게 안 되면 아래 전부 무의미.**
1. **`follow_kp`(조향).** `do follow` 로 직선에서 곧게(`pos≈0`, `turn≈0`) 가는지, 걸침에도
   부드럽게 되돌아오는지 telemetry `pos`/`turn` 으로 본다. 과조향/흔들림이면 ↓, 곡선 못
   따라가면 ↑. **한 값만.** (곡선에서 빠르면 `follow_base_speed` ↓ — 이것도 하나만.)
2. **`node_total_on`(노드 트리거).** 직선 구간을 주행시켜 **오감지(`NODE_*`) 없는** 최소 위로
   올린다. 드리프트에서 total 이 얼마까지 튀는지(대개 <1.3) 보고 그 위, 노드 total(≥2) 아래로.
   직선 오탐 → ↑ / 노드 못 잡음 → ↓. (replay 로 먼저 확인 가능 — §9.)
3. **`node_confirm_mm` / `node_debounce_mm`.** 단발 스파이크 오탐이면 confirm ↑. 한 노드를 두 번
   잡으면 debounce ↑, 가까운 두 노드를 하나로 합치면 ↓. (한 번에 하나.)
4. **`node_advance`(핵심).** 노드 확정 후 멈춘 위치를 본다. `NODE_CONFIRMED` 의 `dist_mm` 와
   실제 멈춤 위치를 비교 — **오버슛이면 `node_advance` 만 내린다**(실패 #1). 모자라면 올린다.
5. 모든 노드 종류(직선/좌·우 분기/T/십자/막다른길)에서 노드 위 정지 + 올바른 종류 →
   `save` → `config/stage3.json`(라이브 6개). PROGRESS 갱신.

> 만질 값은 **로그가 짚는 것만**([DECISIONS.md](../DECISIONS.md) 6장): `dist_mm` 크면 `node_advance`,
> 직선에서 `total` 튀면 `node_total_on`, `pos`/`turn` 흔들리면 `follow_kp`. 여러 개 동시에 안 만진다.
> **센서 자체가 이상하면(특정 센서 darkness 편향) 값 튜닝 말고 `do calibrate` 다시.**

---

## 8. 실패 모드 & 진단 (실패 #1 흐름 포함)

### 실패 #1 — 분기/코너에서 너무 가서 정지(→ Stage5 에서 회전 시 다음 라인 못 탐)

진단 흐름(로봇 없이 가능한 데까지 → 실기 확정):

1. **로그를 본다.** `NODE_CONFIRMED` 의 `dist_mm`(노드에 얼마나 들어가 확정했나)이 큰지 확인.
   더불어 `node_confirm_ms` 가 너무 커서 확정이 늦어 `dist_mm` 가 커진 것은 아닌지 본다.
2. **replay 로 분리한다.** `python tools/replay.py runs/<ts> --set node_confirm_ms=80`
   - 같은 samples 로 `classify_node`/`NodeDebouncer` 를 다시 돌려, confirm 을 줄이면 **확정 시점이
     앞당겨져 dist_mm 가 작아지는지** 본다. 이건 *판단 타이밍* 부분이라 **로봇 없이** 검증된다.
   - confirm 을 줄여도 dist_mm 가 크면, 남은 건 **확정 후 전진량** = `node_advance`.
3. **node_advance 한 값만 내린다.** `robotctl set node_advance <작게>` → `do follow` 로 실기 확인.
   (confirm 과 advance 를 동시에 만지지 않는다 — 한 번에 변수 하나.)
4. 멈춤 위치가 노드 중심에 오면 `save`.

> 핵심: **"확정이 늦은 것(confirm_ms·판단)"과 "확정 후 너무 간 것(node_advance·구동)"을 분리**한다.
> 앞은 replay 로, 뒤는 실기 `do` 로. 둘을 섞어 만지면 다시 감으로 돌아간다.

### 그 밖의 실패

| 증상 | 로그/필드 | 고칠 값 |
|---|---|---|
| 직선인데 노드로 오감지 | 직선에서 `total` 이 자주 `node_total_on` 넘김 | `node_total_on` ↑ / `node_confirm_mm` ↑ / (편향이면 `do calibrate`) |
| 노드인데 못 멈춤 | 노드 위 `total` 이 `node_total_on` 못 넘음 | `node_total_on` ↓ / 캘리브레이션 재실행(정규화 이상) |
| 시작하자마자 한쪽 꺾임 | 직선인데 `pos≠0`(선 위인데 편향) | `do calibrate` 다시(센서 흰/검 불일치) / 그래도면 조향 부호 점검 |
| 막다른길(`total≈0`)을 순간유실로 흘림 | `LINE_LOST` 빈발, `total≈0` 짧게 | dead-end 는 보수적으로 — `node_confirm_mm`(0 지속) 조정 |
| 한 노드 두 번 감지 | `NODE_CONFIRMED` 가 짧은 거리 2회 | `node_debounce_mm` ↑ |
| 센서 하나만 darkness 편향 | 그 센서 `darkness` 가 흰/검에서 이상 | 값 튜닝 말고 `do calibrate` 재실행(높이/스윕 점검) |

---

## 9. PC 검증

- `python3 -m py_compile stages/stage3_node_detect.py lib/nodes.py lib/calib.py`
  (ev3dev2/구동 import 는 `__main__`/메서드 안.)
- **판단층 단위 테스트** (`lib/nodes.py`, 순수, 매우 중요 — replay 대상):
  - `sensor_darkness`: 흰(raw=white)→0, 검(raw=black)→1, 중간→0.5 부근. 분모≈0 방어(clamp).
  - `line_position`: `(0,1,0)→0`, `(1,0,0)→-1`, `(0,0,1)→+1`, `(1,1,0)→-0.5`; `(0,0,0)→None`.
  - `total_darkness`: `(0,1,0)→1`, `(1,1,1)→3`, `(0,0,0)→0`.
  - **드리프트 vs 노드(핵심 회귀)**: 선을 옆으로 옮긴 darkness 열은 `total` 보존·`pos`만 이동 →
    NodeDetector 가 확정 안 함. 옆에 검정 추가한 열은 `total` 급증 → 확정.
  - `NodeDetector`: `total<on` 만 오면 확정 없음; `total>on` 이 `node_confirm_mm` 미만이면
    CANDIDATE, 도달하면 CONFIRMED; 확정 후 `node_debounce_mm` 안은 무시; total 내려가면 리셋.
  - `bits_from_raw`/`node_kind`(로그용): `(0,1,0)→LINE`, `(1,1,1)→CROSS`, `(0,0,0)→DEAD_END`.
- **replay 시나리오**: 기록한 run(reflect+calib)으로
  `replay.py runs/<ts> --set node_total_on=1.9 node_confirm_mm=6` 가 events 를 다시 만들어
  확정 시점/개수가 바뀌는지 출력. (실패 #1 진단 8절과 동일 흐름을 로봇 없이.)

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

**아날로그 개정(§0) 이행 순서 — 한 단계씩 PC검증→실기확인.** 각 단계가 "한 번에 변수 하나".

- [ ] **1단계 캘리브레이션.** `lib/calib.py`(순수: 정규화·load/save), `lib/hardware.py` 에
      `pivot_slow`/스윕. `stages/`: `do calibrate` → `config/stage3_calib.json`. telemetry `darkness/pos/total`.
      실기: 중앙 선 위 `dark≈(0,1,0)`, 흰 `total≈0`, 교차 `total≥2` 확인.
- [ ] **2단계 아날로그 조향.** `lib/nodes.py`: `sensor_darkness`/`line_position`/`total_darkness` +
      `decide_line3`(pos 기반 P)로 교체. `bits_from_raw`/`node_kind`/`bits_str` 는 로그용 유지.
      PC: 위 §9 단위테스트. 실기: 직선 곧게·걸침 복귀(`do follow`, 노드 감지 임시 off/느슨).
- [ ] **3단계 노드 감지(total).** `NodeDetector`(total>on 이 confirm_mm 지속, debounce_mm) 신설,
      구 `NodeDebouncer`(bits+ms) 대체. `stages/` 제어 루프를 §5.1 형태로. reason_code
      `NODE_CANDIDATE/NODE_CONFIRMED/CORNER_LEFT/CORNER_RIGHT/CALIBRATE`(detail 포함).
- [ ] 라이브 params 6개 교체(§3): `follow_kp/follow_base_speed/node_total_on/node_confirm_mm/`
      `node_debounce_mm/node_advance`. telemetry `reflect/darkness/pos/total/bits/dist_mm/node_run_mm`.
- [ ] `tools/replay.py` 가 `lib/nodes.py` 의 `decide_line3`/`NodeDetector` 로 재연(reflect+calib) 확인.
- [ ] PC: py_compile + `lib/nodes.py` 단위테스트 + replay 시나리오 1개.
- [ ] 실기 보정(§7): calibrate→follow_kp→node_total_on→confirm/debounce→node_advance,
      모든 노드 종류 정지/출력 확인, `save`, PROGRESS 갱신("실기 검증 필요"→결과).

---

## 11. 미해결 / 실기 확인 필요

- **캘리브레이션 스윕 방식(§5.3)**: 제자리 pivot 으로 세 센서가 흑·백을 다 지나게 하는 게 실기에서
  깔끔한지(각도/속도/시작 위치), 아니면 짧은 전후진 등 다른 스윕이 나은지 실기 확인. 시작 시
  어레이가 선 위에 있어야 함(안내 필요). 조명 변하면 재실행.
- **`node_total_on` 기본값 1.7 / 임계 방식**: 드리프트 total 상한과 노드 total 하한 사이가 실제로
  벌어지는지(마진) 실기 확인. 너무 붙으면 `pos` 안정도(어레이가 검은 영역 안에 잘 머무나)나 센서
  높이로 마진을 벌린다. 히스테리시스(on/off 분리)가 필요할지도 실기로 결정.
- **`deg_to_mm` 환산 계수**: 바퀴 지름이 있어야 1도당 mm 가 나온다(`node_confirm_mm`/`node_advance`
  가 거리 기반이라 중요). Stage 0/2 실측 후 채움. 미확정이면 상대 비교로 쓰되 계수 확정 후 갱신.
- **코너 vs 분기 구분 시점**: Stage3 은 `total` 로 "노드 있음"까지만. bits(`110`/`011`)로 **어느 쪽**
  갈래인지 참고는 남기되, "직진이 살아있나(분기)" vs "꺾이나(코너)"의 정밀 구분(peek)은 Stage5.
- **`node_advance` 기본값 0**: 회전 없는 Stage3 에선 0(제자리)이 안전. Stage5 회전용 멈춤 위치
  데이터를 모으려면 작은 값 실험 가능 — 실기 결정.
- **dead-end(`total≈0`) vs 라인 순간 유실**: total 이 0 근처로 얼마나(거리) 지속되면 DEAD_END 로
  볼지 실기 확인. leaf 를 junction 보다 보수적으로 볼지도(라이브 6개 한도 안에서) 결정.
- **`do follow` 정지/계속 정책**: 1노드 1정지 vs 연속(토글). 보정엔 1정지가, 코스 통과엔 연속이 편함.
- **`bits_from_raw` 로그용 threshold**: (white+black)/2 자동 유도가 무난한지, 로그 가독이 충분한지 확인.
