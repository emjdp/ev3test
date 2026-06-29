# Stage 3 — 노드(분기) 감지 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 1(라인트레이싱) 실기 Done — 이 단계는 Stage 1의 라인추종을 가져와 쓴다.
> 인프라([00_infra_dashboard.md](00_infra_dashboard.md))의 record/replay 가 동작해야 한다.
> 통과기준(Done): [STAGES.md](../STAGES.md) Stage 3 인용 —
> "코스 위 각 노드 종류(T자, 십자, 좌/우 분기, 막다른 길)를 **노드 위에서** 멈춰 올바른
> 패턴으로 출력. 주행 중 흔들림에 오감지하지 않는다."

상위 규칙: [../../AGENTS.md](../../AGENTS.md) · 라이브 튜닝/대시보드: [../LIVE_TUNING.md](../LIVE_TUNING.md) ·
판단기록/재연: [../DECISIONS.md](../DECISIONS.md) · 배선: [../HARDWARE.md](../HARDWARE.md).

---

## 1. 목표 / 범위

**하는 것**

- **좌·중·우 3센서**의 반사광을 threshold 로 잘라 흑/백 **bits(`LCR`)**로 만든다.
  - 약속: `1 = 검은 선(어두움)`, `0 = 흰 바닥(밝음)`. (반사광은 흰 바닥=큰 값, 검은 선=작은 값.)
  - 예: `010`=직선 / `111`=십자/교차 / `110`·`011`=좌/우 코너·분기 / `000`=선 없음(막다른 길 후보).
- bits 패턴으로 **분기·교차·막다른 길·코너**를 구분한다.
- Stage 1 라인추종으로 "**선 따라가다 노드에서 멈춤**"까지 한다.
- 노드 확정 시 패턴·진입거리를 reason 로그로 남긴다(`NODE_CANDIDATE` / `NODE_CONFIRMED`).
- **판단층(`classify_node`)을 순수 함수**로 둬, 기록한 센서로 **로봇 없이 재연**(`replay.py`)한다.

**안 하는 것 (다음 단계로 미룸)**

- **회전 안 함.** 노드에서 멈추고 패턴만 출력. 분기 선택·회전은 Stage 5.
- **색 판정 안 함.** 막다른 길/노드 색 읽기는 Stage 4(반사광↔컬러 모드 전환은 여기서 안 섞음).
- 탐색/복귀 알고리즘 없음(Stage 6).

---

## 2. 파일 / 인터페이스

| 경로 | 내용 |
|---|---|
| `stages/stage3_node_detect.py` | 독립 실행 진입점. 초기 params/PARAM_LIMITS/MAX_STEP 상수, 라인추종 루프 + 노드 감지로 정지. |
| `lib/nodes.py` (신규, 판단층, **순수**) | `bits_from_raw`, `classify_node`, `NodeDebouncer`. ev3dev2·시간·모터 없음. |
| `lib/linetrace.py` (기존, Stage 1) | 라인추종 PID. **수정 없이 import 재사용**(확정 코드 불변 원칙). |
| `lib/hardware.py` (기존) | `read_reflect()`(좌/중/우), `read_encoders()`(이동거리 추정). 재사용. |
| `tools/replay.py` (기존, 인프라) | 기록한 samples 를 `classify_node` 에 재연. |

**판단층 (순수, PC import·재연 가능) — `lib/nodes.py`**

```python
def bits_from_raw(raw, thresholds):
    """raw 반사광 3개(L,C,R)를 좌/중/우 threshold 로 잘라 0/1 비트로.
       어두울수록(작을수록) 1=검은 선.  반환: (l, c, r) 0/1 튜플."""
    return tuple(1 if v < t else 0 for v, t in zip(raw, thresholds))


def classify_node(bits, params, state):
    """3센서 bits → 노드 종류 분류 (순수 함수, replay 대상이므로 부작용 없음).

    반환: (kind, reason_code, detail)
      kind        : 'LINE' | 'CORNER_L' | 'CORNER_R' | 'BRANCH' | 'CROSS' | 'DEAD_END'
      reason_code : 'NODE_CANDIDATE' | 'CORNER_LEFT' | 'CORNER_RIGHT' | None(LINE)
                    (확정은 NodeDebouncer 가 'NODE_CONFIRMED' 로 승격)
      detail      : {"bits": "LCR 문자열", "reflect": (l,c,r)}

    분류 규칙(약속, l/c/r 은 0/1):
      010            -> LINE       (정상 라인, 노드 아님)
      000            -> DEAD_END   (선 없음 = 막다른 길 후보)
      110            -> CORNER_L / BRANCH (좌측 갈래)   ┐ 코너 vs 분기 구분은
      011            -> CORNER_R / BRANCH (우측 갈래)   ┘ Stage3 에선 같은 'BRANCH'로
      111 / 101      -> CROSS      (십자/교차, 직진 개통)
    NOTE: '코너냐 분기냐(직진이 살아있나)'의 정밀 구분(peek)은 Stage5 에서 회전과 함께.
          Stage3 은 'bits 패턴 종류'까지만 확정해 출력한다.
    """
```

```python
class NodeDebouncer(object):
    """노드 이벤트를 주행 흔들림 속에서 확정한다(순수, 시간은 ms/샘플로 받음).

    같은 패턴(또는 같은 '노드 종류')이 node_confirm_ms 만큼 연속될 때만 NODE_CONFIRMED.
    010(LINE) 이 끼면 카운트 리셋(통과 중 순간 흔들림 무시). 직전 확정 뒤
    node_debounce_ms 안에는 재확정 금지(같은 노드 중복 감지 방지).

    push(bits, t_ms) -> ('NODE_CONFIRMED', detail) | ('NODE_CANDIDATE', detail) | (None, ...)
      detail 에 bits, duration_ms, dist_mm(state 에서 받은 진입거리) 를 채워 준다.
    """
```

> 참고(이전 로봇 `run/solver.py`): `bits_from_raw`(threshold 로 자름), `event_kind`(JUNCTION/LEAF/None),
> `ArrivalDebouncer`(pattern/kind 모드, leaf 를 더 보수적으로 확정)의 **구조**가 검증돼 있다.
> 그 프로젝트는 시간기반이었고 단일 `config.py` 였다 — 여기서는 **구조만** 가져오고
> threshold·confirm 은 이 단계의 라이브 params 로, 거리는 ms 가 아니라 **엔코더 dist_mm** 로 남긴다.

**구동층 (ev3dev2)**: 라인추종(Stage 1 `lib/linetrace.py`)과 `hardware`(`read_reflect`,
`read_encoders`)만. Stage 3은 **새 모터 동작이 거의 없다**(노드에서 `stop` + `node_advance` 전진만).

---

## 3. 라이브 params (6개 이하)

이 단계 라이브 노출은 **6개**(딱 한도). 그 이상 필요해지면 검증된 값을 `config/` 로 내린다.

| 이름 | 의미 | 기본값 | LIMITS (min,max) | MAX_STEP | 올림/내림 |
|---|---|---|---|---|---|
| `thr_left` | 좌센서 흑/백 threshold(이 값보다 작으면 1=선) | 40 | (0, 100) | 3 | 좌센서가 흰 바닥을 선으로 오판 → ↓ / 선을 못 봄 → ↑ |
| `thr_center` | 중앙센서 threshold | 40 | (0, 100) | 3 | 위와 동일(중앙) |
| `thr_right` | 우센서 threshold | 40 | (0, 100) | 3 | 위와 동일(우) |
| `node_confirm_ms` | 같은 패턴이 이만큼 지속돼야 노드 확정 | 120 | (20, 400) | 20 | 흔들림에 너무 일찍 확정 → ↑ / 노드에서 못 멈춤 → ↓ |
| `node_debounce_ms` | 직전 확정 후 재확정 금지 시간(중복 방지) | 900 | (200, 2000) | 100 | 한 노드를 두 번 잡음 → ↑ / 가까운 두 노드를 하나로 → ↓ |
| `node_advance` | **노드 확정 후 회전/색읽기 전 전진량(mm)** | 0 | (0, 60) | 5 | 정지 위치가 노드 못 미침 → ↑ / **오버슛(실패#1)** → ↓ |

> **`node_advance` 가 이 단계의 핵심 보정 손잡이.** 실패 #1(분기/코너 오버슛으로 다음 라인 못 탐)을
> 잡는 값이라 라이브 6개에 반드시 포함한다. Stage 3 자체는 회전을 안 하지만, `node_advance` 만큼
> 전진한 뒤 멈춰 **그 자리에서의 bits/거리를 기록**해 두면 Stage 5 의 회전 위치 보정에 그대로 쓰인다.

**좌/중/우 threshold 를 셋 다 노출하면 4개를 이미 쓴다.** 단일 threshold 로 시작하고
필요할 때만 분리하는 선택지도 있으나, [LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 7 처럼
"센서별로 특성이 다르다"가 검증돼 있어 **3개 분리로 시작**한다(이전 로봇도 좌/중/우 따로 잡음).

**config/ 로 내리는 값(라이브 노출 안 함)**: `loop_delay`(Stage1 확정), `post_stop_settle_ms`,
`node_advance_speed`(advance 전진 속도, 느리게 고정), 라인추종 PID(전부 Stage1 확정값).

```python
PARAM_LIMITS = {
    "thr_left": (0,100), "thr_center": (0,100), "thr_right": (0,100),
    "node_confirm_ms": (20,400), "node_debounce_ms": (200,2000), "node_advance": (0,60),
}
MAX_STEP = {
    "thr_left": 3, "thr_center": 3, "thr_right": 3,
    "node_confirm_ms": 20, "node_debounce_ms": 100, "node_advance": 5,
}
```

---

## 4. telemetry 필드 / reason_code

**추가 telemetry 키** (제어 틱마다; record 의 `samples.jsonl` 핵심)

| 키 | 의미 |
|---|---|
| `reflect` | 좌/중/우 raw 반사광 `(l,c,r)` |
| `bits` | threshold 적용 후 "LCR" 문자열(예 `"110"`) |
| `enc_avg` | 누적 엔코더 평균(도) — dist_mm 환산용 |
| `dist_mm` | 직전 노드(또는 시작) 이후 진행 거리(mm) |
| `confirm_count` | 현재 패턴 연속 지속 카운트(디버그) |

**reason_code** (events.jsonl, [DECISIONS.md](../DECISIONS.md) 카탈로그와 일치)

| reason_code | 언제 | detail |
|---|---|---|
| `LINE_FOLLOW` | PID 추종 중(주기 제한 로깅) | `reflect`, `error`, `turn` (Stage1에서 옴) |
| `NODE_CANDIDATE` | 노드 후보(노드 패턴이 막 잡힘) | `bits`, `reflect`, `duration_ms` |
| `NODE_CONFIRMED` | 노드 확정(멈춤) | `bits`, `duration_ms`, `debounce_ms`, `dist_mm` |
| `CORNER_LEFT` / `CORNER_RIGHT` | 코너 패턴 확정(`110`/`011`) | `bits` |
| `LINE_LOST` / `LINE_RECOVER` | 선 유실/복구(000 이 DEAD_END 확정 전) | `lost_ms` |
| `EMERGENCY_STOP` | BACK/네트워크 stop | `source` |

> `dist_mm` 는 **엔코더에서 환산**한다(바퀴 지름 → 1도당 이동거리, Stage 0/2 측정값 사용).
> 실패 #1 진단의 핵심 필드이므로 `NODE_CONFIRMED` 에 반드시 채운다.

---

## 5. 동작 로직 (의사코드)

EV3 코드는 **Python 3.5 안전**(f-string 금지, `.format()`).

### 5.1 제어 루프 (stage3_node_detect.py)

```python
def main():
    hw = Ev3Hardware()
    pid = LineTracer(STAGE1_PID)            # 확정된 Stage1 라인추종(수정 없이)
    params = dict(INITIAL_PARAMS)
    server = start_tuning_server(params, PARAM_LIMITS, MAX_STEP)
    log = ReasonLogger()
    deb = NodeDebouncer()                    # 순수 판정기
    state = {"node_dist0_deg": 0}            # 직전 노드 이후 거리 기준점

    hw.reset_encoders()
    while True:
        if hw.abort_requested():             # BACK = 1차 정지(최우선)
            hw.stop(); log.event("EMERGENCY_STOP", source="BACK"); break
        snap = server.snapshot_params()      # 네트워크는 제어를 블록하지 않음
        t_ms = now_ms()

        raw = hw.read_reflect()              # (l,c,r)
        thr = (snap["thr_left"], snap["thr_center"], snap["thr_right"])
        bits = bits_from_raw(raw, thr)
        dist_mm = deg_to_mm(hw.enc_avg() - state["node_dist0_deg"])

        kind, reason, detail = classify_node(bits, snap, state)
        status, info = deb.push(bits, t_ms, snap, dist_mm)

        if status == "NODE_CANDIDATE":
            log.event("NODE_CANDIDATE", bits=info["bits"], reflect=raw,
                      duration_ms=info["duration_ms"])
        elif status == "NODE_CONFIRMED":
            # 노드 위에서 멈춤 (이 단계의 목표). 회전은 안 함.
            hw.stop()
            if kind in ("CORNER_L",):  log.event("CORNER_LEFT", bits=info["bits"])
            if kind in ("CORNER_R",):  log.event("CORNER_RIGHT", bits=info["bits"])
            log.event("NODE_CONFIRMED", bits=info["bits"], duration_ms=info["duration_ms"],
                      debounce_ms=snap["node_debounce_ms"], dist_mm=info["dist_mm"])
            advance(hw, snap["node_advance"])         # 확정 후 전진량(실패#1 손잡이)
            hw.beep_ok()                              # 사람 인지
            state["node_dist0_deg"] = hw.enc_avg()    # 거리 기준점 갱신(debounce 와 함께)
            wait_or_stop(hw)                          # 다음 노드 보러 계속 / 또는 정지(운용 선택)
        else:
            ls, rs = pid.step(raw, snap)              # 노드 아니면 라인추종 계속
            hw.drive(ls, rs)

        push_telemetry(server, reflect=raw, bits=bits_str(bits),
                       dist_mm=dist_mm, enc_avg=hw.enc_avg(), confirm_count=deb.count)
        sleep(snap_loop_delay)
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
        if hw.abort_requested():
            break
        sleep(0.005)
    hw.stop()
```

> `node_advance` 는 **엔코더 거리(mm) 기반**(시간 ms 아님). 이전 로봇은 `STRAIGHT_NUDGE_SECONDS`
> 같은 ms 였는데, 배터리/마찰에 흔들려 오버슛을 만들었다. 거리 기반이면 보정 손잡이가 하나로
> 줄고 replay 에서도 dist_mm 로 바로 검증된다.

---

## 6. 대시보드 / CLI 연동

```bash
python tools/robotctl.py do follow         # 선 따라가다 노드에서 멈추는 1세트 실행
python tools/robotctl.py do nudge 10        # 10mm 전진(노드 확정 위치 미세 확인)
python tools/robotctl.py set node_advance 8
python tools/robotctl.py set thr_left 38
python tools/robotctl.py set node_confirm_ms 100
python tools/robotctl.py stop               # 네트워크 정지(보조; BACK 이 1차)
python tools/robotctl.py save               # config/stage3.json 저장
python tools/replay.py runs/<ts> --set node_advance=8 node_confirm_ms=100
```

TUI 권장 키: `f`=do follow, `[`/`]`=node_advance ∓/±, `c`/`C`=node_confirm_ms,
`1`/`2`/`3`=좌/중/우 threshold 선택 후 `-`/`+`, `s`=STOP. 화면에 현재 `bits`·`dist_mm` 상시 표시.

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

1. **threshold 부터.** 흰 바닥 / 검은 선 위에 각 센서를 두고 `reflect` raw 를 telemetry 로 본다.
   좌/중/우 각각 흑·백 중간값으로 `thr_left/center/right` 설정. **한 센서씩** 맞춘다.
   - 검증: 직선(`010`), 십자(`111`), 막다른길(`000`)에 올려두면 기대 bits 가 나와야 한다.
2. **`node_confirm_ms`.** 천천히 주행시켜 직선 구간에서 **오감지(`NODE_*`)가 없는** 최소값을
   찾는다. 흔들림에 일찍 확정되면 ↑, 노드에서 못 멈추면 ↓. (한 번에 이 값만.)
3. **`node_debounce_ms`.** 한 노드를 두 번 잡으면 ↑, 가까운 두 노드를 하나로 합치면 ↓.
4. **`node_advance`(핵심).** 노드 확정 후 멈춘 위치를 본다. `NODE_CONFIRMED` 의 `dist_mm` 와
   실제 멈춤 위치를 비교 — **오버슛이면 `node_advance` 만 내린다**(실패 #1). 모자라면 올린다.
5. 모든 노드 종류(직선/좌·우 분기/T/십자/막다른길)에서 노드 위 정지 + 올바른 bits 출력 →
   `save` → `config/stage3.json`. PROGRESS 갱신.

> 만질 값은 **로그가 짚는 것만**([DECISIONS.md](../DECISIONS.md) 6장): `dist_mm` 크면 `node_advance`,
> 특정 센서만 bits 가 틀리면 그 센서 threshold. 감으로 여러 개 동시에 안 만진다.

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
| 직선인데 노드로 오감지 | `bits` 가 직선에서 `110`/`011` 로 튐 | 해당 센서 threshold(흰 바닥을 선으로 봄) / `node_confirm_ms` ↑ |
| 노드인데 못 멈춤 | `confirm_count` 가 confirm 도달 못 함 | `node_confirm_ms` ↓ / 주행 속도(Stage1) 점검 |
| 막다른길(000)을 라인 유실로 흘림(또는 반대) | `LINE_LOST` 빈발, `bits=000` 짧게 | 000 은 분기보다 보수적으로(leaf 확정 더 길게) — confirm/유실시간 조정 |
| 한 노드 두 번 감지 | `NODE_CONFIRMED` 가 짧은 간격 2회 | `node_debounce_ms` ↑ |
| 센서 하나만 항상 틀림 | 그 센서 `reflect` 분포가 다름 | 그 센서 threshold 만 조정(기술결정 7) |

---

## 9. PC 검증

- `python3 -m py_compile stages/stage3_node_detect.py lib/nodes.py`
  (ev3dev2/라인추종 구동 import 는 `__main__`/메서드 안.)
- **판단층 단위 테스트** (`lib/nodes.py`, 순수, 매우 중요 — replay 대상):
  - `bits_from_raw((80,80,80),(40,40,40)) == (0,0,0)`(밝음=0),
    `bits_from_raw((10,80,10),(40,40,40)) == (1,0,1)`.
  - `classify_node((0,1,0),..)→LINE` / `(1,1,1)→CROSS` / `(0,0,0)→DEAD_END` /
    `(1,1,0)→BRANCH`(또는 CORNER_L) / `(0,1,1)→BRANCH`(CORNER_R).
  - `NodeDebouncer`: `010` 만 들어오면 절대 확정 안 함;
    `110` 이 `node_confirm_ms` 미만이면 CANDIDATE, 도달하면 CONFIRMED;
    확정 후 `node_debounce_ms` 안의 재패턴은 무시; 중간에 `010` 끼면 카운트 리셋.
- **replay 시나리오**: 기록한 run 으로
  `replay.py runs/<ts> --set node_confirm_ms=80 node_advance=8` 가 events 를 다시 만들어
  확정 시점/개수가 바뀌는지 출력. (실패 #1 진단 8절과 동일 흐름을 로봇 없이.)

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] `lib/nodes.py`: `bits_from_raw`, `classify_node`, `NodeDebouncer` (순수, ev3dev2 import 금지).
- [ ] `lib/hardware.py`: `read_reflect()` 확인/추가(좌/중/우), `enc_avg()`·`deg_to_mm` 환산 헬퍼.
- [ ] `stages/stage3_node_detect.py`: 초기 params/LIMITS/STEP 상수, 라인추종(Stage1) import,
      제어 루프 + 노드 확정 정지 + `advance`.
- [ ] reason_code `NODE_CANDIDATE/NODE_CONFIRMED/CORNER_LEFT/CORNER_RIGHT` events 전송(detail 포함).
- [ ] telemetry `reflect/bits/dist_mm/enc_avg/confirm_count` 추가.
- [ ] `tools/replay.py` 가 `lib/nodes.py` 의 같은 함수로 재연하는지 확인.
- [ ] PC: py_compile + `lib/nodes.py` 단위 테스트 + replay 시나리오 1개.
- [ ] 실기: threshold→confirm→debounce→node_advance 순 보정, 모든 노드 종류 정지/출력 확인,
      `save`, PROGRESS 갱신("실기 검증 필요"→결과).

---

## 11. 미해결 / 실기 확인 필요

- **bits 극성 약속(1=선)**: 본 명세는 `1=검은 선`으로 통일(STAGES.md 예시와 일치). 코드 전반·
  단위테스트가 이 약속을 따르는지 일관 확인.
- **`deg_to_mm` 환산 계수**: 바퀴 지름이 있어야 1도당 mm 가 나온다. Stage 0/2 에서 실측 후 채움.
  미확정이면 `dist_mm` 대신 `enc_avg`(도)만 우선 기록하고, 계수 확정 후 환산(보정 손잡이는 동일).
- **코너 vs 분기 구분 시점**: Stage3 은 `110`/`011` 을 `BRANCH`(또는 CORNER_*)로 같이 출력.
  "직진이 살아있는 분기"인지 "꺾이는 코너"인지의 정밀 구분(peek 전진 확인)은 Stage5 로 미룸 —
  여기서 미리 하면 회전이 없어 검증이 안 된다.
- **`node_advance` 기본값 0**: 회전이 없는 Stage3 에서는 0(제자리 정지)이 안전하다. 단,
  Stage5 회전을 위한 멈춤 위치 데이터를 모으려면 작은 값으로 실험할 수 있다 — 실기에서 결정.
- **000(막다른 길) vs 라인 순간 유실**: 이전 로봇은 leaf 를 junction 보다 보수적으로(샘플 더 많이)
  확정했다. 여기선 `node_confirm_ms` 하나로 갈지, 000 전용 confirm 을 따로 둘지 실기로 결정
  (라이브 6개 한도 때문에 우선 단일 confirm + 라인유실 시간으로 시작).
- **`do follow` 정지/계속 정책**: 노드에서 멈춘 뒤 그대로 정지할지, beep 후 다음 노드까지
  계속 갈지(운용 편의). 보정 루프에선 "1노드 1정지"가 편하나 코스 통과 확인엔 연속이 편하다 —
  토글로 둘지 실기에서 판단.
