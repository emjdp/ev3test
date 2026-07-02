# Stage 4 — 색상코드 노드 판정 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 3(노드 감지) 실기 Done, 인프라 MVP([00_infra_dashboard.md](00_infra_dashboard.md))
> 통과기준(Done): [../STAGES.md](../STAGES.md) Stage 4 인용 —
> "각 색 마커에서 의도한 색을 안정적으로 판정. 빈 바닥 오독 없음. 전환 직후 오판(0/엉뚱한 색) 없음."

관련 문서: 단계 통과기준 [../STAGES.md](../STAGES.md), 라이브 튜닝/안전 [../LIVE_TUNING.md](../LIVE_TUNING.md),
판단기록·재연·실패분석 [../DECISIONS.md](../DECISIONS.md), 배선/센서모드 [../HARDWARE.md](../HARDWARE.md).
참고 원본(검증값/구조만 인용, 복붙 금지): `/home/emjdp/dev/ev3maze/robot/run/config.py` 8절,
`/home/emjdp/dev/ev3maze/robot/run/solver.py` `read_node_color` / `Ev3Hardware.read_center_color`.

---

## 1. 목표 / 범위

- **하는 것**: Stage 3 가 노드(분기/막다른 길)를 확정해 **멈춘 그 자리에서**, 중앙
  컬러센서(`in2`)를 **컬러 모드**로 읽어 노드 색을 판정하고, 그 색을 노드 종류
  (시작 / 체크포인트 / 도착)로 매핑한다.
- **하는 것**: 반사광 모드 ↔ 컬러 모드 **전환**(settle + 더미 읽기)과, 같은 색이
  연속으로 N번 보여야 인정하는 **색 확정**.
- **하는 것**: 색을 읽는 **위치 문제**를 직접 다룬다(노드 확정 즉시 vs `node_advance` 후).
  빈 바닥을 잘못 읽으면 `reflect` 가 흰 바닥 수준이라는 사실로 **"바닥 읽음" 경고**를
  reason 에 남겨 자동 검출한다(실패 #2 대응).
- **명시적으로 안 하는 것**:
  - 회전·분기 선택·다음 라인 올라타기 → Stage 5.
  - 색을 보고 U턴/종료 같은 **주행 결정** → Stage 5/6. 여기서는 "색 → 노드 종류"
    라벨까지만 낸다(`NODE_IS_*` 이벤트는 남기되 그에 따른 동작은 하지 않는다).
  - 라인추종(**Stage 3 좌/중/우 3센서 `decide_line3`**), 노드 bits 감지(Stage 3) 코드는
    **수정하지 않고 재사용**한다. (Stage 1 은 하드웨어/주행 부호 기반만 제공 — 중앙센서 단일
    PID 를 라인추종으로 쓰지 않는다. 2026-06-30 Stage 3 변경 반영.)

> 이 단계의 본질은 **"색 읽기"라는 한 동작을 위치/타이밍까지 포함해 신뢰 가능하게**
> 만드는 것이다. `do read_color` 단일 트리거로 위치별 재현하며 보정한다.

## 2. 파일 / 인터페이스

- 새 파일: `stages/stage4_color.py` (독립 실행 가능, Stage 3 위에 색 읽기를 얹음).
- 재사용(수정 금지): **Stage 3 의 3센서 라인추종(`lib/nodes.py:decide_line3`)** + 노드 감지
  (`bits`, debounce, `node_advance`), `lib/` 인프라(shared_params / telemetry / tuning_server /
  events 로깅). (Stage 1 은 부호/속도 기반만 — 중앙센서 PID 재사용 아님.)
- 하드웨어 모드 전환은 구동층 `lib/hardware.py` 에 둔다(없으면 Stage 4 에서 추가).

### 판단층(순수 함수, 하드웨어 없음)

```python
# color: ev3dev2 ColorSensor.color 정수코드(0=없음 1=검정 2=파랑 3=초록 4=노랑 5=빨강 6=흰색 7=갈색)
# reflect: 색 읽기 직전/직후의 반사광(0~100). 빈 바닥 판별용.
classify_node_color(color, params) -> (node_kind, reason_code, detail)
#   node_kind: "START" | "CHECKPOINT" | "GOAL" | "UNKNOWN"
#   params: start_color / checkpoint_color / goal_color
#   detail: {"color": color}

is_floor_read(reflect, params) -> bool
#   reflect 가 floor_reflect_min 이상이면 "흰 바닥 위에서 읽었다"(노드 마커가 아님)로 본다.

# 같은 색이 연속 N번이어야 확정하는 디바운서(순수, 시간/하드웨어 없음).
class ColorConfirmer:
    def __init__(self, confirm_samples): ...
    def push(self, color) -> color | None   # 확정되면 color, 아니면 None
```

### 구동층(ev3dev2 의존)

```python
# 반사광 모드 → 컬러 모드 전환 + settle + 더미읽기 후, 안정된 color 한 번 반환.
hw.read_center_color(settle_s, dummy_reads) -> int
# 컬러 모드 → 반사광 모드 복귀 + 짧은 settle (라인추종 재개 전).
hw.restore_reflect_mode(restore_settle_s) -> None
# 색 읽기 직전 반사광(빈 바닥 판별용). 모드 전환 전에 읽어둔다.
hw.read_center_reflect() -> int

# 노드에서 멈춘 상태에서 색을 안정적으로 읽어 (color, reflect) 반환.
#   Confirmer + 모드 전환을 묶는다. 판단(분류)은 하지 않고 raw 만 돌려준다.
read_node_color_at_rest(params) -> (color, reflect)
```

> **판단층↔구동층 분리 핵심**: "반사광→컬러 전환·더미읽기·색 N번 확정"은 *구동/타이밍*,
> "color→노드종류" 와 "reflect→바닥인가"는 *순수 판단*. 전자는 실기 `do read_color` 로,
> 후자는 `replay.py` 로 검증한다([../DECISIONS.md](../DECISIONS.md) 0·5장).

## 3. 라이브 params (6개 이하)

이 단계에서 라이브로 노출하는 색 관련 값. `node_advance` 등 노드 감지 값은 Stage 3
것을 그대로 쓰고 여기서 새로 노출하지 않는다(겹치면 6개 초과).

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 증상 |
|---|---|---|---|---|---|
| `start_color` | 시작 마커 색코드(0~7) | 4(노랑) | (0,7) | 1 | 코스 마커색에 맞춰 설정. RETURN 종료 판정용 |
| `checkpoint_color` | 체크포인트 마커 색코드 | 2(파랑) | (0,7) | 1 | 코스 마커색에 맞춰 설정 |
| `goal_color` | 도착 마커 색코드 | 5(빨강) | (0,7) | 1 | 코스 마커색에 맞춰 설정. EXPLORE 종료 판정용 |
| `color_confirm_samples` | 같은 색 연속 몇 번이면 확정 | 3 | (1,10) | 1 | 색이 0/엉뚱하게 튀어 오판 → ↑. 색 확정이 너무 굼뜸 → ↓ |
| `color_mode_settle_s` | 반사광→컬러 전환 후 안정화 대기(초) | 0.12 | (0.0,0.5) | 0.02 | 전환 직후 0/엉뚱한 색 → ↑ |
| `color_dummy_reads` | 전환 후 버리는 더미 읽기 횟수 | 2 | (0,6) | 1 | settle 올려도 첫 읽기가 튐 → ↑ |

> `start/checkpoint/goal_color` 는 **서로 달라야** 위상 구분이 된다(아래 8절 자기검증).
> 개발 중 임시로 같게 두고 돌리려면 config 의 `allow_duplicate_node_colors=True` 로
> 풀 수 있게 한다(원본 config.py `ALLOW_DUPLICATE_NODE_COLORS` 구조 인용).

### config/ 에 묻는 값 (라이브 노출 안 함)

| 이름 | 의미 | 기본값 |
|---|---|---|
| `color_mode_restore_settle_s` | 컬러→반사광 복귀 후 라인추종 재개 전 안정화(초) | 0.08 |
| `floor_reflect_min` | 이 반사광 이상이면 "흰 바닥에서 읽음" 경고(실패 #2) | 미정 (Stage 1 흑/백 raw 측정 후 흰 바닥값의 70~80%로 잡음) |
| `read_color_position` | 색 읽는 위치: `"at_node"`(확정 즉시) / `"after_advance"` | `"at_node"` (실패 #2 기본 안전값) |
| `allow_duplicate_node_colors` | 색 3개가 같아도 허용(개발용) | False |

> **`read_color_position` 는 "실패 #2"의 핵심 스위치다.** 기본은 `"at_node"`(노드 확정
> 즉시, 이동 전). 빈 바닥 오독이 잡히면 이걸 바꾸지 말고 `node_advance`(Stage 3 값) 만
> 만진다. 여기 라이브 6개에 넣지 않은 이유: 한 번에 변수 하나, 그리고 이 위치는 거의
> 항상 `"at_node"` 가 정답이라 자주 만질 값이 아니다(8절 참조).

## 4. telemetry 필드 / reason_code

### telemetry 추가 키

| 키 | 의미 |
|---|---|
| `color` | 마지막으로 확정된 노드 색코드(0~7), 없으면 null |
| `color_reflect` | 색 읽기 직전 반사광(빈 바닥 판별; 높으면 바닥 의심) |
| `dist_since_node_mm` | 노드 확정 후 색 읽기까지 진행한 거리(엔코더 추정) |

### reason_code (events) — [../DECISIONS.md](../DECISIONS.md) 카탈로그와 일치

| reason_code | 언제 | detail |
|---|---|---|
| `COLOR_READ` | 노드 색을 읽어 확정 | `color`, `reflect`, `dist_since_node_mm` |
| `COLOR_FLOOR_WARN` | 색 읽을 때 `reflect >= floor_reflect_min` (빈 바닥 의심) | `reflect`, `floor_reflect_min`, `color` |
| `NODE_IS_START` | 색이 `start_color` | `color` |
| `NODE_IS_CHECKPOINT` | 색이 `checkpoint_color` | `color` |
| `NODE_IS_GOAL` | 색이 `goal_color` | `color` |
| `NODE_IS_UNKNOWN` | 셋 중 무엇도 아님(오독/미설정) | `color` |

> `COLOR_FLOOR_WARN` 은 **실패 #2 자동 검출**이다. 색을 읽되, 그 직전 reflect 가
> 흰 바닥 수준이면 함께 경고를 남긴다 → 로그만 보고 "위치가 틀렸다"를 즉시 안다.

## 5. 동작 로직 (의사코드)

> EV3(브릭) 코드는 **Python 3.5 안전**: f-string 금지, `.format()` 사용. 네트워크
> 비차단(snapshot) · 네트워크 stop 처리는 인프라([00_infra_dashboard.md](00_infra_dashboard.md))를 따른다.

### 판단층 (순수)

```python
def classify_node_color(color, params):
    if color == params["goal_color"]:
        return ("GOAL", "NODE_IS_GOAL", {"color": color})
    if color == params["start_color"]:
        return ("START", "NODE_IS_START", {"color": color})
    if color == params["checkpoint_color"]:
        return ("CHECKPOINT", "NODE_IS_CHECKPOINT", {"color": color})
    return ("UNKNOWN", "NODE_IS_UNKNOWN", {"color": color})

def is_floor_read(reflect, params):
    # reflect 가 흰 바닥 수준이면 노드 마커가 아니라 빈 바닥을 읽은 것.
    return reflect >= params["floor_reflect_min"]

class ColorConfirmer(object):
    def __init__(self, confirm_samples):
        self.confirm_samples = confirm_samples
        self.last = None
        self.count = 0
    def push(self, color):
        if color == self.last:
            self.count += 1
        else:
            self.last = color
            self.count = 1
        if self.count >= self.confirm_samples:
            return color
        return None
```

### 구동층 — 색 읽기 (모드 전환 + 확정)

```python
def read_node_color_at_rest(hw, params, telem):
    # (0) 색 읽기 직전 반사광 측정(빈 바닥 판별용) — 반사광 모드일 때.
    reflect = hw.read_center_reflect()
    # (1) 컬러 모드로 전환 + settle + 더미읽기(전환 직후 값 튐 방지).
    #     read_center_color 안에서 settle/dummy 처리.
    confirmer = ColorConfirmer(params["color_confirm_samples"])
    color = None
    while color is None:
        if stop_requested(): raise Aborted
        c = hw.read_center_color(params["color_mode_settle_s"],
                                 params["color_dummy_reads"])
        color = confirmer.push(c)
        sleep(LOOP_DELAY)   # 측정 dt 기반(LIVE_TUNING 기술결정 3)
    # (2) 반사광 모드로 복귀 (라인추종 재개 전 — Stage 5 가 이어받음).
    hw.restore_reflect_mode(params["color_mode_restore_settle_s"])
    return color, reflect

# NOTE: 첫 settle/더미는 read_center_color 호출마다 반복하면 느리다.
#       구현에서는 "한 번 컬러 모드로 들어가 settle/dummy 후, 확정 루프 동안은
#       모드 유지"하고, 확정되면 복귀하는 형태가 낫다. confirm 루프는 모드 전환을
#       다시 하지 않는다(아래 8절 '전환 직후 오판' 참고).
```

### 진입점 — Stage 3 위에 색 읽기 (do read_color / 자동)

```python
def stage4_loop(params, hw, telem, events):
    # Stage 3 의 3센서 라인추종(decide_line3) + 노드 감지를 그대로 돌린다(코드 재사용).
    while True:
        if stop_requested(): stop(); return
        arr = follow_to_node()        # Stage3: 3센서 추종+감지로 노드에서 멈추고 bits/dist_mm 확정
        # ---- 색 읽기 위치 결정 (실패 #2) ----
        if params["read_color_position"] == "after_advance":
            node_advance_move()       # Stage 3 의 node_advance 만큼 전진 후 읽기
        # 기본은 at_node: 이동하지 않고 즉시 읽는다.
        color, reflect = read_node_color_at_rest(hw, params, telem)
        dist = dist_since_node_mm()   # 노드 확정 후 지금까지 진행 거리(엔코더)
        # ---- 빈 바닥 자동 검출 ----
        if is_floor_read(reflect, params):
            events.log("COLOR_FLOOR_WARN",
                       {"reflect": reflect,
                        "floor_reflect_min": params["floor_reflect_min"],
                        "color": color})
        events.log("COLOR_READ",
                   {"color": color, "reflect": reflect,
                    "dist_since_node_mm": dist})
        # ---- 색 → 노드 종류 (판단층) ----
        kind, reason, detail = classify_node_color(color, params)
        events.log(reason, detail)
        telem.set(color=color, color_reflect=reflect, dist_since_node_mm=dist)
        # Stage 4 는 여기서 끝(주행 결정 없음). 멈춰서 다음 read_color 트리거 대기,
        # 또는 사람이 로봇을 다음 노드로 옮겨 다시 측정.
        stop_and_wait_for_trigger()
```

> Stage 4 자동 루프는 "노드에서 멈춰 색만 읽고 보고"까지다. **회전/다음 노드로 진행은
> 하지 않는다**(Stage 5). 따라서 보통은 `do read_color` 단일 트리거로 위치를 바꿔가며
> 측정하는 게 주 작업 방식이다(아래 6·7절).

## 6. 대시보드 / CLI 연동

이 단계에서 누를 수 있는 동작·조정값. 인프라 구조는 [00_infra_dashboard.md](00_infra_dashboard.md).

- `do read_color` — **현재 위치에서** 색 1회 읽기 → `color` + `reflect` +
  `COLOR_READ`/`NODE_IS_*` reason 출력. (재배포 0, 위치별 재현의 핵심)
- `do nudge <ms>` — 짧게 전진(Stage 3 인프라). 노드 위/지나친 위치로 옮겨 `read_color`
  를 다시 눌러 **위치에 따른 reflect 변화**를 직접 본다(실패 #2 진단).
- 조정 키(라이브 set): `color_confirm_samples`, `color_mode_settle_s`,
  `color_dummy_reads`, `start_color`/`checkpoint_color`/`goal_color`.
- `Space` 일시정지/재개(pause) — 인프라 공통([00_infra_dashboard.md](00_infra_dashboard.md)).
  라인추종·`advance`(Stage 3 재사용) 중에는 속도 0 으로 멈췄다가 **같은 목표를 이어간다**
  (`should_pause` 콜백). `do read_color` 같은 단발 동작은 멈춘 상태에서 누른다. 완전 정지는
  `s`(stop, 재개하려면 재실행).
- 에이전트는 **제안만**(`robotctl set` 직접 실행 금지) — [../LIVE_TUNING.md](../LIVE_TUNING.md) 워크플로우.

## 7. 보정 절차 (실기, 한 번에 변수 하나)

1. **색코드 확정**: 각 마커(시작/체크포인트/도착) 위에 센서를 두고 `do read_color`
   를 눌러 나오는 `color` 정수를 기록. 그 값으로 `start/checkpoint/goal_color` 설정.
   셋이 **서로 다른지** 확인(같으면 마커색을 바꾸거나 임시로 `allow_duplicate` 해제).
2. **흰 바닥 reflect 측정**: 마커 밖 빈 바닥에서 `do read_color` → `reflect` 기록.
   `floor_reflect_min` 을 그 값의 70~80%(또는 마커 위 reflect 와 바닥 reflect 의
   중간)로 설정. → 빈 바닥에서 읽으면 `COLOR_FLOOR_WARN` 이 뜨도록.
3. **전환 안정화**: 마커 위에서 `do read_color` 를 연달아 눌렀을 때 첫 읽기가
   0/엉뚱하게 나오면 `color_mode_settle_s` 한 값만 +0.02 씩 올린다. 그래도 첫 값이
   튀면 `color_dummy_reads` 를 +1.
4. **확정 강건성**: 색이 가끔 흔들리면 `color_confirm_samples` 를 +1. 너무 굼뜨면 -1.
5. **위치 검증(실패 #2)**: 노드 확정 직후(at_node)와, `do nudge` 로 살짝 지난 위치에서
   각각 `do read_color`. 지난 위치에서 `COLOR_FLOOR_WARN` 이 뜨고 색이 바뀌면 → 위치가
   범인. 위치는 `at_node` 로 두고 **Stage 3 의 `node_advance` 를 줄인다**(여기 색값 X).

> 황금률: 한 번에 한 값. 바꾼 값·`do read_color` 결과를 [../../PROGRESS.md](../../PROGRESS.md) 에 기록.

## 8. 실패 모드 & 진단

### 실패 #2 — 노드를 지나 빈 바닥 색을 측정 (이 단계의 핵심 대응)

- **증상**: 체크포인트인데 흰 바닥(6) 또는 0 으로 읽혀 노드 종류 오판.
- **로그로 잡는 법**: `COLOR_READ` 의 `reflect` 가 흰 바닥 수준 + `dist_since_node_mm`
  이 큼 → 자동으로 `COLOR_FLOOR_WARN` 이 함께 찍힌다. "어느 값이 범인인지" 로그에 보임.
- **고치는 법(우선순위)**:
  1. `read_color_position` 가 `after_advance` 면 `at_node` 로(노드 확정 즉시 읽기). 기본은 이미 `at_node`.
  2. 그래도 `dist_since_node_mm` 가 크면 **Stage 3 `node_advance` 를 줄인다**(색값 아님).
  3. `do nudge` 로 위치 바꿔 `do read_color` 재현해 확인.
- **자동 검출의 의미**: 사람이 색만 보고 "왜 틀리지" 헤매지 않는다 — reflect 가 높은데
  색을 읽었으면 위치가 범인이라고 로그가 먼저 말한다([../DECISIONS.md](../DECISIONS.md) 6장).

### 전환 직후 오판 (0 / 엉뚱한 색)

- **증상**: 마커 위인데 첫 읽기가 0 이나 다른 색.
- **원인**: 반사광→컬러 모드 전환 직후 센서값이 튄다([../HARDWARE.md](../HARDWARE.md) 센서모드 메모).
- **고치는 법**: `color_mode_settle_s` ↑, 그래도면 `color_dummy_reads` ↑. confirm
  루프 안에서 **매번 모드 전환을 반복하지 말 것**(5절 NOTE) — 전환은 1회, 확정 루프는 유지.

### 색 흔들림(가끔 다른 색)

- **증상**: 같은 마커가 2↔5 처럼 가끔 다르게 읽힘.
- **고치는 법**: `color_confirm_samples` ↑. 그래도 흔들리면 조명/마커 상태 점검.

### 색 3개 충돌(START==CHECKPOINT 등)

- **증상**: 분류가 항상 한쪽으로 쏠림.
- **고치는 법**: `classify_node_color` 의 우선순위(GOAL→START→CHECKPOINT)상 같은 값이면
  먼저 매칭되는 종류로 고정됨. 시작 시 **세 색이 서로 다른지 자기검증**(아래 9절)에서
  걸러야 한다. 개발 중 의도적이면 `allow_duplicate_node_colors=True`.

## 9. PC 검증

- `python3 -m py_compile stages/stage4_color.py` (브릭 코드 3.5 문법 점검).
- **판단 함수 단위 테스트**(하드웨어 없이):
  - `classify_node_color(5, p)` → GOAL(기본 goal=5), `(4,...)`→START, `(2,...)`→CHECKPOINT,
    `(6,...)`/`(0,...)`→UNKNOWN.
  - `is_floor_read(85, p)`→True, `is_floor_read(11, p)`→False (floor_reflect_min 기준).
  - `ColorConfirmer(3)` 에 `[2,2,5,2,2,2]` 를 넣으면 마지막에 2 확정(중간 5 에서 리셋).
- **자기검증(시작 시)**: `start/checkpoint/goal_color` 가 모두 다른지, 0~7 범위인지
  검사해 위반이면 즉시 에러(원본 `validate_config` 색 검사 인용). `allow_duplicate` 면 통과.
- **replay**: `replay.py runs/<ts> --set color_confirm_samples=4 floor_reflect_min=60`
  로 기록한 색/ reflect 샘플을 판단층에 다시 흘려 `NODE_IS_*` / `COLOR_FLOOR_WARN`
  결과가 어떻게 바뀌는지 로봇 없이 확인(센서→판단 부분은 재연됨).

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] `lib/hardware.py` 에 `read_center_reflect` / `read_center_color(settle,dummy)` /
      `restore_reflect_mode` (반사광↔컬러 전환·settle·더미읽기) 추가.
- [ ] 판단층: `classify_node_color`, `is_floor_read`, `ColorConfirmer` 작성(순수).
- [ ] 시작 시 색코드 자기검증(서로 다름 + 0~7) + `allow_duplicate` 우회.
- [ ] `read_node_color_at_rest` (모드전환 1회 + 확정 루프 + 복귀) 작성.
- [ ] `stages/stage4_color.py`: Stage 3 재사용(3센서 `decide_line3` 추종 + 노드 감지) + 색 읽기 위치(`at_node` 기본) +
      `COLOR_READ`/`COLOR_FLOOR_WARN`/`NODE_IS_*` 이벤트 로깅.
- [ ] 라이브 params 6개 + PARAM_LIMITS + MAX_STEP 등록, config/ 에 나머지 값.
- [ ] `do read_color` 트리거 연결, telemetry 키(`color`,`color_reflect`,`dist_since_node_mm`).
- [ ] 네트워크 stop·네트워크 비차단 확인.
- [ ] `python3 -m py_compile` + 판단함수 단위테스트 + replay 시나리오 통과.
- [ ] 7절 보정으로 실기 Done, [../../PROGRESS.md](../../PROGRESS.md) 기록.

## 11. 미해결 / 실기 확인 필요

> **검토 반영 메모 (2026-07-02, Stage 3 v2 채택 전파).** 공식 Stage 3 구현체가
> `lib/nodes.py:decide_line3`(중앙 PID→3센서, 아날로그 centroid 설계 포함)에서
> **`stages/stage3v2_linetrace_branch.py`(3센서 raw 차 PD `pd_step` + bits `black_bits`)로
> 교체**됐다(아날로그 설계는 폐기 — [PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그). 위
> 2026-06-30 메모의 `decide_line3` 재사용 지시는 **stale** — Stage 4 착수 시 라인추종/노드
> 감지 재사용 대상을 `stage3v2_linetrace_branch.py` 의 함수로 다시 잡는다. 또한 v2 Stage 3 는
> 분기에서 **이미 자동으로 회전**하므로(감지된 쪽으로), "노드에서 멈춘 자리에서 색을 읽는다"는
> 이 문서의 전제(§1)가 "회전 전에 멈춘 순간 읽는다"로 바뀌어야 하는지 착수 시 결정 필요.

> **검토 반영 메모 (2026-06-30, Stage 3 변경 전파, ⚠️ 위 2026-07-02 메모로 대체됨— 참고용 보존).**
> Stage 3 가 중앙센서 단일 PID 재사용을
> 버리고 **좌/중/우 3센서 추종(`lib/nodes.py:decide_line3`)**으로 확정되었다. Stage 4 는 색
> 읽기를 **Stage 3 위에** 얹으므로, 라인추종 재사용 대상은 `decide_line3` + Stage 3 노드 감지다
> (Stage 1 은 부호/속도 기반만). 색 읽기 전 정지 위치/`node_advance` 손잡이는 Stage 3 그대로다.

- **`floor_reflect_min` 절대값 미정.** Stage 1 의 흑/백 raw 측정값과 실제 마커 위
  reflect 가 있어야 정한다(빈 바닥 reflect 와 마커 위 reflect 의 중간). 실기 측정 필요.
- **컬러 모드 전환 비용(시간).** `color_mode_settle_s`+`color_dummy_reads` 가 실기에서
  얼마나 걸리는지, 라인추종 정지~색 읽기~복귀 총 시간이 코스 타이밍에 영향 주는지 미검증.
- **마커 위 reflect vs 색 안정성.** 색 마커(파랑/빨강/노랑)에서 `color` 가 안정적으로
  나오는 최소 settle/샘플 수는 조명·마커 재질에 의존 → 실기로만 확정.
- **`read_color_position` 의 `after_advance` 가 실제로 쓸모 있는지.** 거의 항상
  `at_node` 가 정답일 것으로 보지만, 센서가 노드 중심보다 앞/뒤에 달린 기구 배치에선
  소량 advance 가 필요할 수 있음 — 실기 확인 후 필요 없으면 옵션 제거 고려.
- **색코드 매핑(노랑=4 등)** 은 원본 config 값 인용이다. 실제 코스 마커색이 다르면
  `do read_color` 로 재측정해 바꾼다(추측 금지).
