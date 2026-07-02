# Stage 6 — 노드 탐색/복귀 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: Stage 5(통합: 라인트레이싱 + 노드에서 분기 회전) 실기 Done.
>   그 위에 더해 Stage 3(노드 bits 감지) · Stage 4(노드 색 판정) · Stage 2(좌/우/U턴)가
>   각각 실기 Done 이어야 한다. 인프라(판단층↔구동층 분리, reason 로그, replay)는
>   [00_infra_dashboard.md](00_infra_dashboard.md).
> 통과기준(Done) — [../STAGES.md](../STAGES.md) Stage 6 인용:
>   "지도 없이 모든 노드를 방문하고 도착까지 간 뒤 회전 기록을 역재생해 복귀.
>    정해진 코스에서 전체 탐색 + 복귀 성공."

이전 구현(`/home/emjdp/dev/ev3maze/robot/run/solver.py`, `ALGORITHM.md`)에 **지도 없는
자율 탐색(EXPLORE) + 회전기록 역재생 복귀(RETURN)** 의 검증된 알고리즘 골격이 있다.
이 명세는 그 **알고리즘 골격(판단 규칙·자료구조)만** 골라 인용하고, ev3dev 구동·타이밍은
Stage 2~5 에서 이미 확정한 코드를 그대로 가져다 쓰는 것을 전제로 한다. 값은 대부분
"미정/실기 확인 필요"이며 11절로 모은다.

---

## 1. 목표 / 범위

- **하는 것**
  - 지도·좌표·자이로 없이, 출발 노드(색=시작)에서 출발해 코스의 **모든 노드를 방문**하고
    **도착 노드(색=빨강)** 까지 자율 주행한다(EXPLORE).
  - EXPLORE 중 분기/잎에서 한 **회전 토큰(L/S/R/U)** 을 순서대로 raw `path[]` 에 기록하되,
    막다른 길/보류/완료서브트리에서 분기로 **U턴해 되돌아오는 순간 그 가지를 `live[]` 스택에서
    떼어낸다**(삽질 제거). 도착에 닿은 순간 `live[]` = **출발→도착 단순경로(트리에서 최단)**.
  - 도착에서 그 **압축된 경로(`live[]`)를 거꾸로 + 좌우반전** 해 재생, **출발 노드(색=노랑)** 로
    정확히 복귀한다(RETURN). raw `path[]` 전체를 역재생하지 않으므로 **갈 때의 막다른 길을
    복귀 때 되밟지 않는다.**
  - 모든 "다음 출구 선택" 결정을 **순수 함수**로 분리해 reason_code 로 남기고
    `replay.py` 로 로봇 없이 재연 가능하게 한다.

- **명시적으로 안 하는 것 (다음 단계/다른 명세)**
  - 물체 집기/내려놓기: **Stage 7**([stage7_gripper.md](stage7_gripper.md)). 본 단계는
    초음파·그리퍼를 건드리지 않는다.
  - 라인추종·노드 감지·색 판정·회전 동작 자체의 튜닝: 각각 Stage 1~5 에서 **이미 확정**.
    여기서 그 값을 수정하지 않는다(거대 config 금지 원칙, [../../AGENTS.md](../../AGENTS.md)).
    (라인추종층 = Stage 3 좌/중/우 3센서 `decide_line3`. 중앙센서 단일 PID 아님 — 2026-06-30 Stage 3 변경.)
  - 형태 peek(좌·우 동시 분기에서 직진 개통 확인)의 구동: Stage 3/5 의 노드 감지가
    좌/직/우 출구를 알려주는 것을 **전제**한다. 본 명세는 peek 의 *결과*(출구 집합 + cross
    여부)만 입력으로 받는다. peek 구동이 아직 없다면 Stage 3 명세로 되돌아가 확정한다.

---

## 2. 파일 / 인터페이스

### 새로 만들/수정할 파일
- `stages/stage6_explore_return.py` — 진입점. EXPLORE → RETURN 을 실행. 튜닝 상수는
  파일 맨 위(이 단계가 실제로 만지는 것만; 3절).
- `lib/explore.py` (신규, **순수 판단층**) — 하드웨어·시간·모터 없이 import 만으로
  PC 에서 테스트/재연 가능한 탐색 두뇌. ev3dev2 를 절대 import 하지 않는다.
- 구동층은 **Stage 5 에서 만든 io 인터페이스 재사용**. 새 구동 동작을 만들지 않는다.

### 판단층 ↔ 구동층 분리 (핵심)
[../DECISIONS.md](../DECISIONS.md) 0장 원칙을 그대로 따른다. 이전 구현
(`solver.py`)에서 `MazeSolver`(순수) / `Ev3Motion`(구동)으로 나뉜 골격을 인용한다.

**구동층 io 인터페이스** (Stage 5 까지 구현된 것을 그대로 호출. 시그니처 예시):
```
io.follow_to_node(label) -> Arrival(kind)   # 다음 노드까지 주행. kind = JUNCTION | LEAF
io.sense_exits()        -> ({"L":bool,"S":bool,"R":bool}, cross_bool)  # 출구 + 십자여부
io.turn(token)          -> None             # token = LEFT/STRAIGHT/RIGHT/UTURN, 라인 재포착
io.read_node_color()    -> int              # 노드 색 코드(0~7), 막다른 길에서만
io.finish(label)        -> None
io.stop_requested()     -> bool             # 네트워크 stop/watchdog 정지 플래그
io.paused()             -> bool             # 일시정지(Space) 플래그. True 면 속도 0 유지·같은 목표 이어감
```
> 이 시그니처는 이전 `Ev3Motion` 에서 인용한 것이다. Stage 5 의 실제 메서드명/반환형이
> 다르면 **Stage 5 쪽 이름에 맞추고**, 어긋난 부분은 11절에 적는다(추측 금지).

**순수 판단층 주요 함수 (이번 단계가 새로 정의)** — 모두 `lib/explore.py`:
```
# 도착 종류·회전 토큰 상수
LEAF, JUNCTION                      # 도착 종류
LEFT=1, STRAIGHT=2, RIGHT=3, UTURN=4  # 회전 토큰(path 에 저장되는 숫자)

# 출구 선택 (순수, replay 가능) — 이 단계의 심장
pick_exit(state, facing, cross) -> (angle | None, reason_code)
    # state: {각도: 'open'|'leaf'|'deferred'|'done'|'parent'}, facing: 현재 바라보는 각도
    # 미탐색('open') 출구를 우선순위로 고른다. 없으면 보류('deferred')에서 고른다.
    # cross(십자)=True 면 '직진 우선', 아니면 '좌선우선(좌>직>우)'.
    # 반환 reason_code 예: DFS_SELECTED_UNVISITED_LEFT / _STRAIGHT / _RIGHT,
    #                      DFS_SELECTED_DEFERRED_*, ALL_EXITS_DONE

token_for(angle, facing) -> token   # facing 에서 angle 출구로 가려면 무슨 회전인가
has_open_other(state, angle) -> bool # angle 외에 아직 'open' 인 출구가 남았는지(한 분기 우선)
invert_token(token) -> token        # 복귀용 좌우반전(L<->R, S/U 그대로)

# ── 경로 압축(삽질 제거) — 이번 변경의 핵심. 둘은 같은 결과를 내는 서로 다른 시점의 구현 ──
pop_dead_branch(live, mark) -> None  # 온라인(안 A): 분기로 되돌아온 순간 live[mark:] 통째 제거.
    # mark = 그 출구로 떠나기 직전의 len(live). 잎 체크포인트/보류(deferred)/완료서브트리에서
    # 분기로 제어가 돌아오면 호출 → 그 가지가 통째로 live 에서 사라진다(파괴적, list 슬라이스 del).
    # 도착(EXPLORE_COMPLETE)을 찾으면 호출되지 않으므로 live = 출발→도착 단순경로.
simplify_path(tokens) -> [token,...] # 사후(안 B, 순수): U턴(=180)을 가운데 둔 3-토큰을
    # 세 회전의 각도 합(mod 360)으로 한 토큰으로 환원, U턴이 사라질 때까지 반복.
    # 트리 DFS walk 를 출발→도착 단순경로로 접는다. live 와 동일해야 한다(아래 불변식).
    # 예: L U R=(90+180-90)=U,  L U S=(90+180+0)=R,  L U L=S,  R U R=S,  S U S=U.
return_plan(live)   -> [token,...]  # ★변경: raw path 가 아니라 압축된 live 를 거꾸로 + 좌우반전.
    # 불변식(replay/시뮬에서 assert): live == simplify_path(raw_path).
classify_leaf_color(color, params) -> reason_code
    # GOAL → NODE_IS_GOAL, START → NODE_IS_START, 그 외 → NODE_IS_CHECKPOINT
```

> **이번 변경(2026-07-01): `return_plan` 의 입력을 raw `path` → 압축 `live` 로 교체.**
> 이전 인용 골격(`solver.py`)은 raw path 전체를 역순+반전해 재생했고, 그러면 EXPLORE 때 들어간
> 막다른 길을 RETURN 때도 똑같이 되밟는 "복귀 삽질"이 생긴다(8절 표의 그 증상). 막다른 길이
> 전부 노드(잎)로 표시된 **트리 코스**이므로, 분기로 U턴해 돌아오는 순간 그 가지를 떼면
> (`pop_dead_branch`) 남는 `live` 가 곧 유일한 출발→도착 단순경로 = 최단이다. `simplify_path`
> 는 같은 결과를 raw 에서 사후 계산해 **교차검증**한다(둘이 다르면 분기 식별/기록 버그 알람).

> **왜 `pick_exit` 가 순수 함수여야 하나**: "다음 출구 선택"이 입력(state·facing·cross)만으로
> 결정되면, EXPLORE 중 기록한 입력 시퀀스를 같은 함수에 다시 흘려 **로봇 없이 동일한 결정과
> reason_code 를 재생**할 수 있다(9절 replay). 분기 식별 버그를 코스 없이 잡는다.

### 분기 식별: "분기 로컬 프레임" (자이로 불필요) — 인용
지도/좌표 없이 "이 분기에서 어느 출구를 이미 가봤나"를 아는 방법. 이전 `ALGORITHM.md`
4-1 에서 인용:

- 어떤 분기에 **처음 도착한 순간** 바라보는 방향을 `0°`(직진), 들어온 길(부모)을 `180°`,
  오른쪽 `90°`, 왼쪽 `270°` 로 고정한다(미로가 90° 격자라는 전제).
- 잎에서 U턴해 되돌아오면 "**방금 들어온 출구가 곧 내 뒤(180°)**"라는 사실로 현재
  `facing` 을 다시 계산한다. 그러면 남은 출구를 좌/직/우로 정확히 재식별한다.
- **전역 방위를 누적하지 않는다.** 분기에서의 출구 방향만 쓰므로 미로 엣지가 중간에
  꺾여도 안전하다. 이것이 자이로 없이 탐색이 되는 이유다.

자료구조(인용): `state = {각도: 상태}` (`A_BACK=180` 은 'parent'), `facing`(현재 방향).

---

## 3. 라이브 params (6개 이하)

> Stage 6 는 **탐색 규칙**이 본질이라 라이브로 만질 "주행 숫자"가 거의 없다(그건 Stage
> 1~5 에서 끝났다). 이 단계가 새로 노출하는 params 는 **노드 색 3개 + 안전 watchdog**
> 정도로 최소다. 나머지(노드/회전/추종 값)는 검증된 값으로 `config/` 에 묻는다.

| 이름 | 의미 | 기본값 | LIMITS(min,max) | MAX_STEP | 올림/내림 |
|---|---|---|---|---|---|
| `start_color` | 출발 노드 색 코드 — RETURN 종료 판정 | 미정(노랑 후보 4) | (0,7) | 1 | 실제 마커 색에 맞춤 |
| `goal_color` | 도착 노드 색 코드 — EXPLORE 종료 판정 | 미정(빨강 후보 5) | (0,7) | 1 | 실제 마커 색에 맞춤 |
| `checkpoint_color` | 그 외 노드 색 — U턴 대상(체크포인트) | 미정(파랑 후보 2) | (0,7) | 1 | 실제 마커 색에 맞춤 |
| `cross_prefers_straight` | 십자(D형)에서 직진 우선 여부(끄면 항상 좌선우선) | True | (bool) | - | 십자 동작 검증 시 토글 |
| `explore_watchdog_s` | EXPLORE 중 N초간 새 노드 도착이 없으면 안전정지(무한루프 방지) | 미정 | (0, 600) | 큼 | 코스 크기에 맞춤. 0=끔 |
| `max_path_len` | path 토큰 수 상한(폭주 시 안전정지) | 미정 | (0, 999) | 큼 | 코스 노드 수×여유. 0=끔 |

> 색 3개는 `start/goal/checkpoint` 가 **서로 달라야** 위상 구분이 된다(이전 config 의
> `validate_config` 가 강제하던 규칙 인용). 셋이 같으면 거부/경고.
> `cross_prefers_straight` 는 노출하되, 십자 분기가 코스에 없으면 안 만진다.

---

## 4. telemetry 필드 / reason_code

### 추가 telemetry 키
| 키 | 의미 |
|---|---|
| `phase` | `EXPLORE` / `RETURN` (현재 단계) |
| `path_len` | 지금까지 기록된 회전 토큰 수 |
| `facing` | 현재 분기 로컬 프레임의 바라보는 각도(0/90/180/270) |
| `open_exits` | 현재 분기에서 아직 'open' 인 출구 각도 목록 |
| `return_idx` | RETURN 재생 중 몇 번째 토큰인지 |

### 새 reason_code (events.jsonl) — [../DECISIONS.md](../DECISIONS.md) 카탈로그에 추가
| reason_code | 언제 | 같이 남기는 detail |
|---|---|---|
| `EXPLORE_START` | EXPLORE 시작 | start_color, goal_color |
| `JCT_ENTER` | 분기 도착, 로컬 프레임 구성 | open_exits, cross |
| `DFS_SELECTED_UNVISITED_LEFT` | 미탐색 좌출구 선택 | angle, facing, available |
| `DFS_SELECTED_UNVISITED_STRAIGHT` | 미탐색 직진출구 선택 | angle, facing, available |
| `DFS_SELECTED_UNVISITED_RIGHT` | 미탐색 우출구 선택 | angle, facing, available |
| `DFS_SELECTED_DEFERRED` | 보류해 둔 분기 출구 선택(내려감) | angle, facing |
| `DFS_DEFER_BRANCH` | 분기인데 미탐색 출구 남음 → U턴 보류 | angle |
| `DFS_DESCEND_BRANCH` | 미탐색 출구 없음 → 곧장 내려감 | angle |
| `PRUNE_DEAD_BRANCH` | 분기로 U턴 복귀 → 그 가지를 `live` 에서 제거(삽질 제거) | mark, popped(제거 토큰 수), reason(leaf/deferred/subtree_done) |
| `JCT_ALL_DONE` | 분기의 모든 출구 완료 → 부모로 나감 | (루트면 EXPLORE 종료) |
| `LEAF_REACHED` | 막다른 길 도착, 색 읽기 직전 | dist_mm |
| `NODE_IS_GOAL` / `_CHECKPOINT` / `_START` | 색으로 노드 종류 확정 | color, reflect |
| `EXPLORE_COMPLETE` | 도착 색 확인, EXPLORE 종료 | path_len |
| `RETURN_START` | RETURN 시작(첫 U턴 + plan 재생 개시) | plan_len |
| `RETURN_REPLAY_TOKEN` | RETURN 중 토큰 하나 재생 | idx, token, arrival_kind |
| `RETURN_COMPLETE` | 출발 색 확인, RETURN 종료 | - |
| `EXPLORE_WATCHDOG_STOP` / `PATH_OVERFLOW_STOP` | 안전정지 발동 | elapsed_s / path_len |

> 기존 카탈로그의 `TURN_*` / `COLOR_READ` / `NODE_CONFIRMED` 등은 Stage 2~5 가 이미
> 남긴다. 본 단계는 **출구 선택 이유**(DFS_*)와 **단계 경계**(EXPLORE/RETURN start·end)를
> 새로 더한다. 표에 한 줄씩 추가하는 것은 [DECISIONS.md](../DECISIONS.md) 1장 규칙.

---

## 5. 동작 로직 (의사코드)

> EV3 브릭 코드는 **Python 3.5 안전**(f-string 금지, `.format()`). 아래는 의사코드.
> 정지 플래그 확인은 구동층 `io` 가 매 루프 책임진다(Stage 1~5 에서 이미 보장).
> 네트워크 비차단(snapshot)은 인프라([00_infra_dashboard.md](00_infra_dashboard.md))가 담당.

### 5-1. 순수 판단층 — 출구 선택 (replay 의 대상)
```
# 우선순위: 십자면 (직진,좌,우), 아니면 (좌,직,우)
def order_for(cross):
    if cross and params.cross_prefers_straight:
        return [A_STRAIGHT, A_LEFT, A_RIGHT]
    return [A_LEFT, A_STRAIGHT, A_RIGHT]

def pick_exit(state, facing, cross):
    # 1) 미탐색('open') 우선
    for rel in order_for(cross):
        for a in opens(state):
            if (a - facing) % 360 == rel:
                return a, reason_for_open(rel)   # DFS_SELECTED_UNVISITED_*
    # 2) 보류('deferred') — 좌선우선
    for rel in [A_LEFT, A_STRAIGHT, A_RIGHT]:
        for a in deferred(state):
            if (a - facing) % 360 == rel:
                return a, "DFS_SELECTED_DEFERRED"
    # 3) 다 끝남
    return None, "JCT_ALL_DONE"
```

### 5-2. EXPLORE (재귀: 분기 중첩 깊이만큼만, 매우 얕음) — 인용 골격 + 온라인 압축
```
# 두 기록을 함께 유지한다:
#   path[] = raw — 실제로 한 모든 회전(삽질 포함). 폴백 + simplify_path 교차검증용.
#   live[] = 압축 — '지금 살아있는 경로'만. 분기로 U턴 복귀 시 그 가지를 떼어낸다.
def record(token):
    path.append(token); live.append(token)      # 두 곳 모두에 push

def explore():
    path, live = [], []
    emit(EXPLORE_START)
    first = io.follow_to_node("EXPLORE")        # 출발을 떠나 첫 노드까지
    if first.kind == LEAF:                       # (작은 코스) 바로 막다른 길
        if classify_leaf_color(io.read_node_color()) == NODE_IS_GOAL:
            emit(EXPLORE_COMPLETE); return live   # (raw path 도 보관: 검산/폴백)
    explore_junction(is_root=True)              # 본체 (도착 찾으면 ExploreComplete 로 탈출)
    io.finish("EXPLORE")
    return live                                  # ★ RETURN 은 압축된 live 를 받는다

def explore_junction(is_root):
    exits, cross = io.sense_exits()
    state = build_local_frame(exits)            # {180:'parent', 열린 각도:'open'}
    facing = 0
    emit(JCT_ENTER, open_exits=opens(state), cross=cross)
    while True:
        check_watchdog_and_overflow()           # explore_watchdog_s / max_path_len
        angle, why = pick_exit(state, facing, cross)
        if angle is not None and state[angle] in ('open',):
            emit(why, angle=angle, facing=facing)
            mark = len(live)                     # 이 출구로 떠나기 직전의 live 길이
            kind = take_exit(angle, facing)     # record(token) → io.turn → follow_to_node
            if kind == LEAF:
                handle_leaf()                   # 색 읽기(+도착이면 EXPLORE_COMPLETE 예외)
                return_to_junction()            # U턴 직후 라인 따라 분기 복귀
                state[angle] = 'leaf'
                prune(mark, "leaf")             # ★ 막다른 가지 제거 (도착이면 위에서 이미 탈출)
            else:                                # 가 보니 분기
                if has_open_other(state, angle):
                    emit(DFS_DEFER_BRANCH, angle=angle)
                    record(UTURN); io.turn(UTURN); return_to_junction()
                    state[angle] = 'deferred'
                    prune(mark, "deferred")     # ★ 보류한 가지 제거(나중에 deferred 로 다시 옴)
                else:
                    emit(DFS_DESCEND_BRANCH, angle=angle)
                    explore_junction(is_root=False)   # 곧장 내려가 재귀
                    state[angle] = 'done'
                    prune(mark, "subtree_done") # ★ 도착 없던 서브트리 통째 제거
            facing = (angle + 180) % 360         # 그 출구에서 되돌아온 방향
            continue
        if why == "DFS_SELECTED_DEFERRED":
            emit(why, angle=angle, facing=facing)
            mark = len(live)
            descend_deferred(angle, facing); state[angle] = 'done'
            prune(mark, "subtree_done")          # ★ 보류분기 내려갔다 도착 못 찾고 옴 → 제거
            facing = (angle + 180) % 360; continue
        # 모든 출구 완료
        if is_root:
            emit(JCT_ALL_DONE); return           # 루트면 EXPLORE 종료
        token = token_for(180, facing)           # 부모로 나감
        record(token); io.turn(token); io.follow_to_node("EXPLORE")
        return

def prune(mark, why):
    # 분기로 U턴해 돌아온 가지를 live 에서 통째 제거(raw path 는 그대로 둔다).
    popped = len(live) - mark
    if popped > 0:
        pop_dead_branch(live, mark)              # del live[mark:]
        emit(PRUNE_DEAD_BRANCH, mark=mark, popped=popped, reason=why)

def handle_leaf():
    emit(LEAF_REACHED)
    color = io.read_node_color()
    why = classify_leaf_color(color, params)     # NODE_IS_GOAL / _START / _CHECKPOINT
    emit(why, color=color)
    if why == NODE_IS_GOAL:
        emit(EXPLORE_COMPLETE); raise ExploreComplete()  # live 는 그대로 = 출발→도착 단순경로
    record(UTURN); io.turn(UTURN)                # 체크포인트 → U턴해 부모로 (prune 이 위에서 떼냄)
```

> **핵심 불변식**: EXPLORE 가 끝나면 `live == simplify_path(path)` 이어야 한다. 같지 않으면
> 분기 식별(`facing`/`pick_exit`) 또는 기록 버그다 — 시뮬/replay(9절)에서 assert 로 잡는다.
> `pop_dead_branch` 는 파괴적 슬라이스 삭제라 O(가지 길이)이고 EV3 에서 무시할 만하다.

### 5-3. RETURN (기록 역재생) — 인용 골격
```
def return_run(live):
    plan = return_plan(live)                       # 압축된 live 를 거꾸로 + 좌우반전(raw path 아님)
    emit(RETURN_START, plan_len=len(plan))
    io.turn(UTURN)                                # 도착(막다른 길)에서 먼저 돌아 출발 쪽으로
    arr = io.follow_to_node("RETURN")
    for idx, token in enumerate(plan):
        if arr.kind == LEAF and \
           classify_leaf_color(io.read_node_color(), params) == NODE_IS_START:
            break                                 # 출발 색 보면 끝
        emit(RETURN_REPLAY_TOKEN, idx=idx, token=token, arrival_kind=arr.kind)
        io.turn(token)                            # 분기/잎 구분 없이 기록대로만 회전
        arr = io.follow_to_node("RETURN")
    emit(RETURN_COMPLETE)
    io.finish("RETURN")
```

> RETURN 은 **다시 판단·peek·스캔하지 않는다.** 압축된 `live` 의 토큰대로만 돌아 헤매지
> 않는다(이전 ALGORITHM.md 5장 인용). plan 토큰 수 = 출발→도착 분기 수이고, 그 사이 잎(막다른
> 길)은 들르지 않는다 — RETURN 동선에 막다른 길이 끼지 않는 게 이번 변경의 결과다.
> 단, 도착 정렬 가정에 주의 — 8절.

### 5-4. 안전
- **정지 플래그**: 구동층 `io.stop_requested()` 가 매 루프 확인 → 즉시 정지(인용 골격은
  `Aborted` 예외로 위로 전달). 본 단계 코드는 이를 잡아 `io.finish` 후 종료.
  BACK 버튼은 프로그램 입력으로 할당하지 않는다.
- **watchdog / overflow**: `explore_watchdog_s` 초간 새 노드 없거나 `max_path_len`
  초과면 안전정지 + reason 로그. 무한 재귀/제자리 맴돔 방지(이전 구현엔 없던 보강).

---

## 6. 대시보드 / CLI 연동

이 단계에서 `do <action>` 으로 실행 가능한 동작(빠른 보정 루프, [DECISIONS.md](../DECISIONS.md) 3장):
- `do explore` — EXPLORE 1회 실행(도착까지). reason 로그로 출구 선택 추적.
- `do return` — 마지막 `path` 로 RETURN 1회 실행.
- `do read_color` — 현재 위치 노드 색 + reflect(바닥/노드 구분). Stage 4 의 것 재사용.

조정 가능한 키/파라미터(대시보드 TUI): `start/goal/checkpoint_color`,
`cross_prefers_straight`, `explore_watchdog_s`. (주행 숫자는 Stage 1~5 화면에서 만진다.)

`Space` 일시정지/재개(pause) — 인프라 공통([00_infra_dashboard.md](00_infra_dashboard.md)).
구동층 `io.paused()` 를 매 루프 확인해 `io.stop_requested()` 와 같은 위치에서 처리한다(노드 간
주행·회전 중 속도 0 유지 후 **같은 목표를 이어감**). pause 동안 `explore_watchdog_s` 시간은
멈춰야 한다(정지 중을 무응답으로 오판해 안전정지하지 않게). 완전 정지는 `s`(stop).

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

> 이 단계는 "값 튜닝"보다 **알고리즘이 코스에서 의도대로 도느냐**를 본다. 그래서 먼저
> PC 시뮬(9절)로 규칙을 못 박고, 실기는 색·정렬만 잡는다.

1. **PC 시뮬 먼저**: 코스 그래프를 시뮬에 넣어 EXPLORE raw 토큰·노드 방문 순서·압축 live·
   RETURN(압축 live 역순)이 기대와 일치하고 **RETURN 에 막다른 길이 안 끼는지** 확인(로봇 0).
   `live == simplify_path(path)` 불변식도 본다. 여기서 통과 못 하면 브릭에 올리지 않는다.
2. **색 3개 확정**: `do read_color` 로 출발/도착/체크포인트 마커에서 색 코드를 읽어
   `start/goal/checkpoint_color` 를 실제 값으로. 셋이 서로 다른지 확인.
3. **EXPLORE 한 번**: `do explore`. 막히면 reason 로그에서 **어느 출구 선택(DFS_*)이
   틀렸는지** 본다. 분기 식별이 틀리면 보통 Stage 3(노드 출구 감지)·Stage 2(회전 각도)로
   되돌아간다(본 단계 값이 아님). 한 번에 한 곳만.
4. **RETURN 정렬**: 도착에서 첫 U턴 후 라인을 못 잡으면 도착 정렬 문제(8절) — Stage 2 의
   `UTURN_*`, Stage 3 의 leaf 확정값으로 잡는다(본 단계가 아님).

---

## 8. 실패 모드 & 진단

| 증상 | 로그가 보여줄 것 | 진단 / 어디를 고치나 |
|---|---|---|
| 미방문 노드를 남기고 도착함 | `JCT_ENTER` 의 open_exits vs 이후 DFS_* 선택 | 출구 감지 누락(좌·우 감지) → Stage 3. 또는 `has_open_other` 판단 → 9절 시뮬로 재연 |
| 같은 분기를 무한히 맴돔 | DFS_* 가 반복, `path_len` 폭증 → `PATH_OVERFLOW_STOP` | facing 재계산/분기 식별 버그 → 시뮬 재연으로 `pick_exit` 입력 확인 |
| 십자에서 엉뚱한 출구 우선 | `JCT_ENTER` cross 값 + DFS_* | cross 오판이면 Stage 3 peek. 규칙이면 `cross_prefers_straight` 토글 |
| 체크포인트를 도착으로(또는 반대) 오판 | `NODE_IS_*` 의 color/reflect | 색 코드 오설정 → `start/goal/checkpoint_color`. reflect 가 흰 바닥이면 색읽기 위치 → Stage 4 |
| RETURN 이 출발에 못 닿음/엉뚱한 길 | `RETURN_REPLAY_TOKEN` idx·token·arrival_kind | `return_plan`(압축 live 역순+반전) 버그면 시뮬로 잡힌다. 도착 정렬이면 아래 |
| **RETURN 때 막다른 길을 또 들어감(복귀 삽질)** | `PRUNE_DEAD_BRANCH` 누락/`popped`=0, `live != simplify_path(path)` | 가지 제거(`prune`/`pop_dead_branch`) 미동작 또는 facing 재계산 버그 → 9절 불변식 assert 로 재연 |
| 도착에서 첫 U턴 후 라인 분실 | RETURN 직후 LINE_LOST | 도착 정렬 가정 위반(이전 ALGORITHM.md 5장 ⚠️). Stage 2 `UTURN_*`, Stage 3 leaf 확정으로 |

> 본 단계 실패는 대개 **(a) 순수 판단 버그**(시뮬·replay 로 잡음) 또는 **(b) 하위 단계
> 구동 부정확**(해당 Stage 로 되돌아감) 둘 중 하나다. 로그의 DFS_* 와 NODE_IS_* 가 어느
> 쪽인지 바로 가른다. **본 단계 값(색·watchdog)만으로 고쳐지는 건 색 오판뿐**이다.

---

## 9. PC 검증

- **문법**: `python3 -m py_compile stages/stage6_explore_return.py lib/explore.py`.
- **순수 함수 단위 테스트** (`lib/explore.py`, ev3dev 불필요):
  - `pick_exit`: 좌선우선 vs 십자 직진우선 순서, open→deferred→done 전이.
  - `token_for`/`facing` 재계산: 잎 U턴 복귀 후 남은 출구를 정확히 재식별하는가.
  - `simplify_path`: U턴 3-토큰 환원표(L U R=U, L U S=R, L U L=S, R U R=S, S U S=U …)
    + 트리 DFS walk → 출발→도착 단순경로. 막다른 가지가 전부 사라지는가.
  - `pop_dead_branch`: `del live[mark:]` 가 가지만 떼고 그 앞은 보존하는가.
  - `return_plan`: 압축 live 의 거꾸로+좌우반전(L↔R, S/U 불변). raw path 가 아님에 주의.
  - **불변식**: 여러 코스에서 `live == simplify_path(path)` 단언(온라인 압축 vs 사후 압축 일치).
  - `classify_leaf_color`: GOAL/START/CHECKPOINT 분기.
- **알고리즘 통합 시뮬** — 이전 `tests/sim_maze.py` 의 **가짜 미로 + SimMotion** 아이디어를
  인용해 새로 만든다(`tests/sim_explore.py` 제안):
  - 코스 그래프(노드·엣지·각도)를 넣고, `io` 인터페이스를 흉내 내는 `SimMotion` 으로
    **실제 판단층**(`lib/explore.py`)을 돌린다.
  - 검사 항목(인용): ① EXPLORE raw 토큰 시퀀스가 기대값과 동일, ② 노드 방문 순서가 기대
    경로와 동일, ③ **모든 노드 방문(N/N)**, ④ 도착 노드에서 종료, ⑤ RETURN 이 출발로
    복귀하고 경로가 **압축 live 의 역순**(raw 역순 아님), ⑥ **RETURN 동선에 막다른 잎이
    하나도 끼지 않음**(복귀 삽질 0), ⑦ `live == simplify_path(path)` 불변식 성립.
  - 알고리즘을 고치면 **이 시뮬을 먼저 통과**시키고 브릭에 올린다(이전 워크플로 인용).
- **replay**: EXPLORE 중 기록한 `pick_exit` 입력 시퀀스(state·facing·cross)를 `replay.py`
  로 같은 함수에 흘려 동일 결정·reason 이 나오는지 확인([DECISIONS.md](../DECISIONS.md) 5장).
  단, 회전 각도/관성 같은 물리는 replay 대상이 아니다(실기 `do` 로).

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

- [ ] Stage 5 의 io 인터페이스 실제 시그니처 확인 → 2절 시그니처와 맞춤(다르면 11절 기록).
- [ ] `lib/explore.py` 순수 판단층 작성: 상수, `pick_exit`, `token_for`,
      `has_open_other`, `invert_token`, `pop_dead_branch`, `simplify_path`,
      `return_plan`(압축 live 입력), `classify_leaf_color`, 분기 로컬 프레임 자료구조.
- [ ] EXPLORE 에 raw `path` + 압축 `live` 이중 기록 + `prune`(분기 복귀 시 가지 제거) 구현.
      시뮬에서 `live == simplify_path(path)` 불변식 PASS.
- [ ] reason_code 카탈로그([DECISIONS.md](../DECISIONS.md))에 4절 항목 추가.
- [ ] `tests/sim_explore.py` 작성(가짜 미로 + SimMotion), 단위+통합 검사 PASS.
- [ ] `stages/stage6_explore_return.py` 진입점: params/telemetry 노출, EXPLORE→RETURN,
      watchdog/overflow 안전정지, 네트워크 stop.
- [ ] `do explore` / `do return` / `do read_color` 트리거 연동.
- [ ] `python3 -m py_compile` 통과 확인.
- [ ] (실기) 색 3개 확정 → EXPLORE 전노드 방문 → RETURN 출발 복귀. PROGRESS.md 기록.

---

## 11. 미해결 / 실기 확인 필요

> **검토 반영 메모 (2026-07-02, Stage 3 v2 채택 전파).** 공식 Stage 3 구현체가
> `lib/nodes.py:decide_line3`(중앙 PID→3센서, 아날로그 centroid 설계)에서
> `stages/stage3v2_linetrace_branch.py`(bits+PD 라인추종, `lib/turns.pivot` 분기 탱크회전)로
> 교체됐다(아날로그 설계 폐기 — [PROGRESS.md](../../PROGRESS.md) 2026-07-02 로그). 위/아래 본문의
> "라인추종층 = Stage 3 3센서 `decide_line3`" 주석은 **stale** — Stage 6 착수 시 재사용 대상을
> `stage3v2_linetrace_branch.py` 함수로 다시 잡는다. v2 Stage 3 가 좌/우 분기에서 이미 자동
> 회전을 하므로, 탐색 알고리즘이 "분기에서 멈춘 뒤 스스로 방향을 고른다"는 이 문서의 전제가
> "Stage 3 의 자동 회전을 어떻게 탐색 로직이 override/관찰하는가"로 바뀌어야 하는지 결정 필요.

> **복귀 경로 압축 메모 (2026-07-01) — 이번 변경의 배경.**
> - 이전 인용 골격은 raw `path` 전체를 역순+반전해 복귀했다 → EXPLORE 때 들어간 막다른 길을
>   RETURN 때도 되밟는 "복귀 삽질"이 발생. 사용자 요구는 "복귀는 지름길만".
> - 코스는 **막다른 길이 전부 노드(잎)로 표시된 트리**(사이클 없음)임을 확인 → 분기로 U턴해
>   돌아오는 순간 그 가지를 `live` 에서 떼면(`pop_dead_branch`) 남는 게 곧 유일·최단 경로.
>   루프가 있는 미로였다면 이 방식만으로 최단 보장이 안 되어 그래프+BFS 또는 Trémaux 가
>   필요했겠지만, **트리이므로 온라인 스택 압축으로 충분**하다.
> - 온라인 압축(`live`)과 사후 압축(`simplify_path(raw)`)을 둘 다 두고 `live == simplify_path(path)`
>   불변식으로 교차검증한다(둘이 다르면 분기 식별/기록 버그).
>
> **검토 반영 메모 (antigravity #3, #5) — Stage 6 구현 시 반영.**
> - **#3 복귀 견고성**: 회전 토큰만 역재생하면 바퀴 슬립으로 노드를 하나 놓치거나(False Neg)
>   노이즈로 더 세면(False Pos) 전체가 어긋나 폭주한다. 노드 기록 시 **그 노드의 bits 패턴
>   (코너/T/십자/잎)도 함께 구조체로 저장**하고, 복귀 주행에서 만나는 노드 패턴이 계획과
>   일치하는지 **검증**한다. 어긋나면 즉시 `EMERGENCY_STOP`. (이전 프로젝트가 여기서 고생.)
>   (압축은 *확정된* 토큰열에만 적용되므로, 이 패턴 검증이 압축 입력의 품질도 함께 지킨다.)
> - **#5 재귀 대신 명시 스택**: `explore_junction` 재귀 호출 대신 `stack=[]` + `while` 상태
>   머신으로. 임베디드에서 stop/watchdog 탈출 시 자원(모터·소켓) 해제가 단순해진다.
>   (명시 스택으로 가면 `mark`/`prune` 가 스택 프레임과 자연히 맞아떨어져 `live` 관리가 더 단순.)

- **Stage 5 io 인터페이스 정확한 이름/반환형**: 본 명세는 이전 `Ev3Motion` 에서 인용했다.
  실제 Stage 5 구현의 메서드명·`Arrival` 형태·`sense_exits` 반환을 확인해 맞춰야 한다.
- **노드 색 코드(start/goal/checkpoint)**: 실제 코스 마커 색을 `do read_color` 로
  읽어야 확정. 문구상 출발=노랑, 도착=빨강으로 추정되나 **실기 확인 전까지 추정값**.
- **코스 그래프**: 시뮬에 넣을 노드/엣지/각도와 기대 EXPLORE 경로는 실제 코스 도면이
  나와야 확정. 이전 코스(`sim_maze.py`)는 *다른 미로*이므로 그대로 못 쓴다(아이디어만).
- **`explore_watchdog_s` / `max_path_len` 기본값**: 코스 크기·평균 노드 간 주행시간을
  실기에서 재야 정한다.
- **`cross_prefers_straight` 가 실제로 필요한가**: 코스에 십자(D형) 분기가 있는지 도면
  확인 필요. 없으면 항상 좌선우선이면 충분.
- **도착 정렬 가정**: RETURN 첫 U턴이 라인 위로 떨어진다는 가정(이전 ⚠️)이 이 코스/이
  로봇에서 성립하는지 실기 확인. 안 되면 Stage 2/3 로 되돌아가 보정.
- **잎이 아닌 분기에 색 마커가 있을 가능성**: 인용 골격은 색을 **막다른 길에서만** 읽는다
  (분기에서 컬러 모드 전환은 불필요·느림). 코스 도착/출발이 분기형이면 규칙 보강 필요.
