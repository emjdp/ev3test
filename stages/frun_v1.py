#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frun_v1.py — 무상태 좌수법(L>S>R) 탐색 + 111 OR-latch 보강 + trail 표시.

배경(v4/v5 의 work_id/pending/BACKTRACK DFS 상태머신에서 관찰된 문제, 2026-07-07):
  1) 상태(work_id 등)가 실제 위치와 어긋나면 같은 구간에 갇힌다 — 지도가 틀리면
     주행 자체가 막힌다.
  2) 111 분기(좌우 동시 개방)에 로봇이 비스듬히 진입하면, confirm 창(node_confirm_ms)
     동안 사이드 센서 반사값이 흔들려 bits 가 110→011→110 처럼 깜빡인다. v4/v5 는
     `cand != nbits` 면 후보를 통째로 리셋하므로 111 을 한 번도 확정 못 하고
     110/011 로 오판 → 존재하지 않는 코너로 착각해 길을 잃는다.

frun_v1 은 두 문제를 다른 각도로 푼다:
  - **판단층을 무상태 좌수법으로 교체.** 분기에서 열린 출구 중 L>S>R 우선순위로
    고르고(D형 111 최초 방문만 예외로 직진 먼저), 상태(work_id/pending/BACKTRACK)를
    아예 없앤다 — 상태가 틀릴 일 자체가 없다. 지도(FrunMap)는 D형 최초방문 판정
    "참고용"으로만 쓰고, 지도가 틀려도(mismatch) 주행은 막히지 않는다(trusted=False
    로 D형 예외만 꺼지고 순수 좌수법으로 강등).
  - **노드 후보를 OR-latch 로 보강.** confirm 창 동안 bits 가 110→111→011 로
    깜빡여도, CANDIDATES 안에서 바뀌는 한 후보를 리셋하지 않고 비트별 OR 로
    계속 합산한다(110|011=111) — 한 번이라도 111 이 스쳐 지나가면 그 정보를
    잃지 않는다. confirm 타이머는 후보가 처음 활성화된 시각을 그대로 유지한다.
    (0,0,0) 은 latch 하지 않고 기존 방식 그대로(진짜 선 유실 판정과 섞이면 안 됨).

편도 완주 전용(v4/v5 의 전 노드 방문 + 최단경로 복귀는 없음): 초록(도착) 도달 시
그 자리에서 그리퍼 오픈 후 정지한다. U턴/복귀 주행이 없다.

trail(튜닝용): 분기/커브/유턴/도착마다 "이동(컨텍스트)" 문자열을 누적해 telemetry
"trail" 필드(최근 20개)와 이벤트 로그(trail_add)에 남긴다. 도착/세션 종료 시
RUN_TRAIL 이벤트로 전체 리스트를 한 번에 남겨, 실기 로그만 보고도 로봇이 지나온
경로를 사람이 눈으로 복기할 수 있게 한다.

v1/v2/v4 에서 그대로 가져오는 것(import — 확정 코드 미수정):
  v1(run_maze): bits_node/bits_to_str, advance_straight/backup_until_line,
    _tick_stop/_publish, 색상 상수, CANDIDATES/SLOW_ON, 타이밍/기하 상수.
  v2(run_maze_v2): 000 가드(lost_candidate_blocked/LOST_GUARD_TURN), 라이브
    turn_speed 회전(_run_turn), 마커 색(COL_VISIT=빨강/COL_GOAL=초록).
  v4(run_maze_v4): heading 순수 헬퍼 4개(DIRS/turn_heading/abs_to_rel/opposite)만
    — Explorer/MazeMap 등 상태머신은 가져오지 않는다(이 파일이 없애려는 대상).
  Stage 3(stage3v2_linetrace_branch): PdController(PD 조향, 미수정).

라이브 params: v4 의 12개 값을 복사(참고용, import 아님 — AGENTS.md "이전 단계 확정
코드/값은 재사용하되 수정하지 않는다"에 따라 v4 를 건드리지 않고 이 파일에 독립
정의) + 신설 3개:
  left_th_node/right_th_node — 기존 run_maze 의 고정 상수 LEFT_TH_NODE/RIGHT_TH_NODE
    를 라이브로 개방(bits_node 판정 감도를 실기에서 바로 조정).
  peek_backup_mm — B형(T자, 좌우만 개방) 분기에서 advance 로 교차점을 지나친 뒤
    직진 없음을 확인했을 때, 회전 전 후진 복귀 거리.

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C,
      재시작은 네트워크 reset(robotctl do reset / 대시보드 액션).

독립 실행(브릭):  python3 stages/frun_v1.py
문법 점검(PC):    python3 -m py_compile stages/frun_v1.py lib/*.py
판단층 테스트(PC): python3 tests/test_frun_v1_logic.py
"""

import os
import sys
import threading
import time

# stages/ 에서 단독 실행해도 lib/ 를 import 하도록 저장소 루트를 경로에 넣는다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams                         # noqa: E402
from lib.telemetry import Telemetry                                 # noqa: E402
from lib.decision_log import DecisionLog                            # noqa: E402
from lib.tuning_server import TuningServer                          # noqa: E402
# v1(run_maze) 확정 코드 재사용(미수정).
from stages.run_maze import (                                        # noqa: E402
    bits_node, bits_to_str,
    advance_straight, backup_until_line, _tick_stop, _publish,
    COL_BLACK, COL_YELLOW,
    CANDIDATES, SLOW_ON,
    NODE_DEBOUNCE_MS,
    LOST_BACKUP_MM, BACKUP_SPEED, LOST_RETRY_WINDOW_MS,
    COLOR_DEBOUNCE_MS, START_EXIT_MM, GRIP_SEC, LOOP_DELAY_MS,
    REASON_THROTTLE_S, STRAIGHT_SPEED, SLOW_SPEED, MM_PER_DEG,
)
# v2(run_maze_v2) 확정 코드 재사용(미수정): 000 가드 + 라이브 turn_speed 회전 + 마커 색.
from stages.run_maze_v2 import (                                     # noqa: E402
    lost_candidate_blocked, LOST_GUARD_TURN, _run_turn,
    COL_VISIT, COL_GOAL,
)
# v4(run_maze_v4) 에서 heading 순수 헬퍼 4개만 재사용(미수정) — Explorer/MazeMap 은
# 가져오지 않는다(이 파일이 상태머신을 없애려는 것이 핵심).
from stages.run_maze_v4 import DIRS, turn_heading, abs_to_rel, opposite  # noqa: E402,F401
# Stage 3 확정 조향 재사용(미수정).
from stages.stage3v2_linetrace_branch import PdController            # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 라이브 params — v4(run_maze_v4) 의 12개 값을 그대로 복사(참고용 시드, import 아님)
# + 이 스테이지 신설 3개(left_th_node/right_th_node/peek_backup_mm) = 15개.
# =====================================================================

INITIAL_PARAMS = {
    "base_speed": 16,         # 주행 속도(%). v4 시드 그대로.
    "kp": 0.2,                # PD 조향 게인(좌/우 raw 차). v4 시드 그대로.
    "turn_speed": 6,          # 회전 속도(%). v4 시드 그대로.
    "node_confirm_ms": 90,    # 노드 후보 확정 시간(ms). v4 시드 그대로.
    "left_th_steer": 64,      # 후진 복구 line_found 감도. v4 시드 그대로.
    "right_th_steer": 65,
    "left_th_node": 20,       # ★ 신설: 기존 run_maze 고정상수 LEFT_TH_NODE 라이브화.
    "right_th_node": 18,      # ★ 신설: RIGHT_TH_NODE 라이브화.
    "node_advance_mm": 20,    # ★ 확정 후 재판정/회전 전 전진량. v4 시드 그대로.
    "goal_advance_mm": 20,    # ★ 도착 시퀀스 전진 거리. v4 시드 그대로.
    "peek_backup_mm": 20,     # ★ 신설: B형(T자) 직진 막힘 확인 후 후진 복귀 거리.
    "turn_90_factor": 0.66,   # ★ 과/부족 시 0.05 단위 미세조정. v4 시드 그대로.
    "turn_180_factor": 0.71,  # ★ 유턴도 같은 비율. v4 시드 그대로.
    "grab_dist_cm": 6.0,      # ★ 조립에 따라 실기값 다름. v4 시드 그대로.
    "grip_speed": 30,         # ★ 조립에 따라 부호 반전. v4 시드 그대로.
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "kp": (0.0, 3.0),
    "turn_speed": (5, 40),
    "node_confirm_ms": (0, 1000),
    "left_th_steer": (0, 100),
    "right_th_steer": (0, 100),
    "left_th_node": (5, 60),
    "right_th_node": (5, 60),
    "node_advance_mm": (0, 120),
    "goal_advance_mm": (0, 200),
    "peek_backup_mm": (0, 60),
    "turn_90_factor": (0.3, 2.0),
    "turn_180_factor": (0.3, 2.0),
    "grab_dist_cm": (1.0, 20.0),
    "grip_speed": (5, 80),
}

MAX_STEP = {
    "base_speed": 5,
    "kp": 0.1,
    "turn_speed": 5,
    "node_confirm_ms": 60,
    "left_th_steer": 3,
    "right_th_steer": 3,
    "left_th_node": 5,
    "right_th_node": 5,
    "node_advance_mm": 10,
    "goal_advance_mm": 10,
    "peek_backup_mm": 10,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "grab_dist_cm": 1.0,
    "grip_speed": 5,
}

UI_STEP = {
    "base_speed": 1,
    "kp": 0.01,
    "turn_speed": 1,
    "node_confirm_ms": 10,
    "left_th_steer": 1,
    "right_th_steer": 1,
    "left_th_node": 1,
    "right_th_node": 1,
    "node_advance_mm": 10,
    "goal_advance_mm": 10,
    "peek_backup_mm": 5,
    "turn_90_factor": 0.01,
    "turn_180_factor": 0.01,
    "grab_dist_cm": 0.5,
    "grip_speed": 1,
}
UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "node_confirm_ms": "ms",
    "left_th_steer": "%",
    "right_th_steer": "%",
    "left_th_node": "%",
    "right_th_node": "%",
    "node_advance_mm": "mm",
    "goal_advance_mm": "mm",
    "peek_backup_mm": "mm",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "grab_dist_cm": "cm",
    "grip_speed": "%",
}
PARAM_ORDER = [
    "base_speed", "kp", "turn_speed", "node_confirm_ms",
    "left_th_steer", "right_th_steer", "left_th_node", "right_th_node",
    "node_advance_mm", "goal_advance_mm", "peek_backup_mm",
    "turn_90_factor", "turn_180_factor",
    "grab_dist_cm", "grip_speed",
]

SAVE_PATH = os.path.join(_ROOT, "config", "frun_v1.json")
STAGE_NAME = "frun_v1"

ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
    {"name": "reset", "label": "Reset to Start (wait YELLOW)"},
]


# =====================================================================
# 판단층 1: 무상태 좌수법 분기 선택 (순수 — PC 테스트 가능)
# =====================================================================

def pick_move(has_left, has_right, has_straight, is_new_cross):
    """분기에서 다음 이동을 고른다. 반환 (move, reason_code).

    우선순위 L>S>R 의 무상태 좌수법. 예외 둘:
      - 좌우 둘 다 열려 있고 직진도 열려 있는 최초 방문(is_new_cross)이면 "이왕
        전진했으니" 직진부터 본다(D형/사거리 완전 탐색 보조, PEEK_STRAIGHT_OPEN_
        FIRST_VISIT 로그와 짝).
      - 좌우만 열려 있고 직진이 막혀 있으면(B형/T자) 항상 좌측부터
        (TEE_LEFT_FIRST) — 호출부가 이 판단 전에 peek_backup 후진을 실행한다.
    지도(FrunMap)가 신뢰를 잃으면(trusted=False) 호출부가 is_new_cross 를 항상
    False 로 넘겨 D형 예외를 끄고 순수 좌수법으로 강등시킨다.
    """
    n_options = int(has_left) + int(has_right) + int(has_straight)
    if n_options == 0:
        return "U", "DEAD_END"

    if has_left and has_right:
        if has_straight:
            if is_new_cross:
                return "S", "CROSS_STRAIGHT_FIRST"
            # 재방문 십자(is_new_cross=False) → 아래로 흘러 좌수법(L 우선)으로 처리.
        else:
            return "L", "TEE_LEFT_FIRST"

    if has_left:
        return "L", "LEFT_HAND_PICK"
    if has_straight:
        return "S", "LEFT_HAND_PICK"
    if has_right:
        return "R", "LEFT_HAND_PICK"
    return "U", "DEAD_END"   # 방어적 폴백(n_options>=1 이면 이론상 도달 안 함)


# =====================================================================
# 판단층 2: OR-latch 노드 후보 (순수 — confirm 창 중 bits 깜빡임 보강)
# =====================================================================

def latch_bits(latched, nbits):
    """비트별 OR 합산. 110 다음에 011 이 스쳐도 111 을 잃지 않는다."""
    return (latched[0] | nbits[0], latched[1] | nbits[1], latched[2] | nbits[2])


# =====================================================================
# 판단층 3: FrunMap — D형(사거리) 최초 방문 판정 전용 슬림 지도 (순수)
#
# 실제 주행 방향은 전부 pick_move (좌수법)가 정한다. 이 지도는 딱 하나만 본다:
# "이 십자(111)에 처음 왔는가?" 지도가 틀려도(mismatch) trusted=False 로 D형
# 예외만 꺼질 뿐 주행 자체는 항상 계속된다 — 지도 오류가 완주를 막지 않는다.
# =====================================================================

class FrunMap(object):

    def __init__(self):
        self.nodes = {}            # node_id -> {"arms": frozenset(절대방향), "edges": {}}
        self._next_id = 0
        self.heading = "N"          # apply_move 로만 갱신(회전 실행 지점 한 곳, do_turn).
        self.trusted = True
        self.cur = None
        self._pending_from = None
        self._pending_dir = None

    def arrive(self, heading, has_left, has_right, has_straight):
        """분기 도착. 직전 depart() 가 남긴 (출발 노드, 출구 절대방향)으로 현재
        노드를 특정한다(간선 있으면 기존 노드, 없으면 새 노드 생성+양방향 간선).

        반환 (node_id, is_new, mismatch). mismatch 판정은 "이번에 확인 가능한
        방향(현재 heading 기준 L/R/직진) 중, 저장된 arm 집합에 이미 있던(=예전에
        확인된) 방향이 이번엔 안 보인다"일 때만 발동한다 — 매번 다른 방향에서
        재도착하면 "뒤(진입 방향)"는 원래 못 보므로, 단순 집합 전체 비교(==)는
        진입각이 바뀔 때마다 오탐(false positive)이 난다. 이번에 처음 보이는
        방향(예전엔 뒤쪽이라 못 봤던 팔)은 mismatch 가 아니라 학습(합집합)한다.
        mismatch 는 {"expected": [...], "actual": [...]}, 그 외에는 None(mismatch
        가 나면 self.trusted 가 False 로 강등된다).
        """
        arms_open = self._arms(heading, has_left, has_right, has_straight)

        if self._pending_from is None:
            nid = self._new_node(arms_open)
            self.cur = nid
            return nid, True, None

        from_id = self._pending_from
        from_dir = self._pending_dir
        self._pending_from = None
        self._pending_dir = None

        edges = self.nodes[from_id]["edges"]
        if from_dir in edges:
            nid = edges[from_dir]
            node = self.nodes[nid]
            stored = node["arms"]
            checkable = set([turn_heading(heading, "L"), turn_heading(heading, "R"), heading])
            expected_true = stored & checkable
            missing = expected_true - arms_open
            node["arms"] = stored | arms_open   # 새로 보인 방향 학습(합집합)
            self.cur = nid
            if missing:
                self.trusted = False
                return nid, False, {"expected": sorted(stored), "actual": sorted(arms_open)}
            return nid, False, None

        nid = self._new_node(arms_open)
        edges[from_dir] = nid
        self.nodes[nid]["edges"][opposite(heading)] = from_id
        self.cur = nid
        return nid, True, None

    def depart(self, move):
        """현재 노드에서 나가는 절대방향을 기록(다음 arrive() 매칭용). heading 은
        여기서 바꾸지 않는다 — 실제 회전 실행 지점(apply_move)에서만 바뀐다."""
        self._pending_from = self.cur
        self._pending_dir = turn_heading(self.heading, move)

    def apply_move(self, move):
        """회전 실행 지점(do_turn)에서만 호출 — heading 갱신. 커브/유턴 포함
        모든 회전이 이 한 곳을 거친다(depart() 는 heading 을 바꾸지 않는다)."""
        self.heading = turn_heading(self.heading, move)

    def _arms(self, heading, has_left, has_right, has_straight):
        arms = set()
        if has_left:
            arms.add(turn_heading(heading, "L"))
        if has_right:
            arms.add(turn_heading(heading, "R"))
        if has_straight:
            arms.add(heading)
        return frozenset(arms)

    def _new_node(self, arms_open):
        nid = self._next_id
        self._next_id += 1
        self.nodes[nid] = {"arms": arms_open, "edges": {}}
        return nid


# =====================================================================
# 판단층 4: trail (순수 문자열 헬퍼) — 튜닝용 경로 표시
# =====================================================================

TRAIL_DISPLAY_MAX = 20     # 대시보드 telemetry 에 보여줄 최근 항목 수
TRAIL_KEEP_MAX = 400       # 메모리 상한(전체 이력은 RUN_TRAIL 이벤트로 별도 기록)


def trail_entry(move, bits):
    """분기/커브 trail 한 항목: "L(110)" 형식."""
    return move + "(" + bits_to_str(bits) + ")"


def trail_tail(trail, limit=TRAIL_DISPLAY_MAX):
    """telemetry 프레임용 — 최근 limit 개를 공백으로 join(오래된 것부터, 최신이
    오른쪽 끝)."""
    if not trail:
        return ""
    return " ".join(trail[-limit:])


def trail_append(trail, item):
    """전체 이력에 추가(메모리 상한만 적용). 표시는 trail_tail 이 최근분만 자른다."""
    trail.append(item)
    if len(trail) > TRAIL_KEEP_MAX:
        del trail[0]


# =====================================================================
# 판단층(세션 초기화값)
# =====================================================================

def fresh_session_state():
    """한 세션(출발→탐색→도착)의 가변 상태 초기값. trail 도 세션마다 비운다."""
    return {"visits": 0, "goal_seen": False, "done": False, "grabbed": False, "trail": []}


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run(). v5 뼈대(세션 루프/reset/pause) 재사용,
# 탐색 판단층만 좌수법+FrunMap 으로 교체.
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()
    fmap = FrunMap()                      # 세션마다 new_session 에서 새로 만든다

    stop_flag = {"on": False, "source": None}
    reset_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending_do = {"action": None}
    plock = threading.Lock()

    state = fresh_session_state()
    lost = {"last_recover_t": -1e9}
    steer = {"last_turn": 0.0}

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "run"}

    def on_do(action, args):
        if action not in ("read_color", "read_reflect", "reset"):
            return {"error": "unknown action: {}".format(action)}
        if action == "reset":
            reset_flag["on"] = True
            reset_flag["source"] = args.get("source", "dashboard") if args else "dashboard"
            return {"queued": "reset"}
        with plock:
            pending_do["action"] = action
        return {"queued": action}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    started = time.monotonic()

    def reset_steer():
        pd.reset()
        steer["last_turn"] = 0.0

    def log_run_trail(reason):
        if state["trail"]:
            log.log("RUN_TRAIL", reason, trail=" ".join(state["trail"]),
                    count=len(state["trail"]))

    def take_pending():
        with plock:
            action = pending_do["action"]
            pending_do["action"] = None
        return action

    def handle_pending(action):
        if action == "read_color":
            color = hw.read_center_color_value()
            log.log("COLOR_READ", "DO_TRIGGER", color=color, method="in_place")
            _publish(tele, params, started, mode="read_color", color=color)
        elif action == "read_reflect":
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            log.log("REFLECT_READ", "DO_TRIGGER", reflect_l=rl, reflect_r=rr)
            _publish(tele, params, started, mode="read_reflect", reflect_l=rl, reflect_r=rr)

    def do_turn(cmd):
        """회전 실행(라이브 turn_speed) + heading 갱신 — 한 곳에서만."""
        _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)
        fmap.apply_move({"turn_left": "L", "turn_right": "R", "uturn": "U"}[cmd])

    def exec_move(move):
        if move == "L":
            do_turn("turn_left")
        elif move == "R":
            do_turn("turn_right")
        elif move == "U":
            do_turn("uturn")
        # "S" 는 회전 없음(heading 불변)

    def leaf_uturn():
        """잎(빨강 마커/막다른길/선 유실)에서의 U턴을 지도에 반영한다.

        잎을 노드로 등록하고 U턴 후 출발(depart)을 기록하지 않으면, 분기로
        되돌아왔을 때 직전 depart 간선이 미등록이라 같은 분기가 새 노드로 중복
        등록(phantom)되고, 십자 재방문이 매번 is_new=True 가 되어 D형 "최초
        1회만" 판정이 깨진다. 잎→U턴→역방향 depart 를 기록하면 다음 arrive 가
        기존 분기 노드로 매칭된다.
        """
        fmap.arrive(fmap.heading, False, False, False)
        do_turn("uturn")
        fmap.depart("S")

    def advance(distance_mm, speed):
        def on_adv_tick():
            _publish(tele, params, started, mode="advancing",
                     enc_avg=hw.enc_avg() * MM_PER_DEG, trail=trail_tail(state["trail"]))
        advance_straight(hw, distance_mm, speed,
                         _tick_stop(should_stop, on_adv_tick), should_pause)

    def goal_sequence():
        """도착 시퀀스(편도 종료) — U턴/복귀 없음. 전진→그리퍼 오픈→비프 2회→종료."""
        hw.stop()
        snap = params.snapshot()
        state["goal_seen"] = True
        item = "G(goal)"
        log.log("NODE_IS_GOAL", "COLOR_GREEN", color=COL_GOAL, trail_add=item)
        trail_append(state["trail"], item)
        advance(snap["goal_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return
        hw.grip_open(snap["grip_speed"], GRIP_SEC)
        hw.beep_ok()
        hw.beep_ok()
        state["done"] = True
        log_run_trail("GOAL_REACHED")

    def handle_lost(bits):
        """000(선 유실) — v1/v4/v5 와 동일한 후진 복구. 유턴까지 가면 trail 에
        "U(lost)" 를 남긴다(커브 판정 중 진짜 막다른길의 "U(dead)" 와 구분)."""
        snap = params.snapshot()
        retry_ok = ((time.monotonic() - lost["last_recover_t"]) * 1000
                    >= LOST_RETRY_WINDOW_MS)
        if retry_ok:
            log.log("LINE_LOST", "ALL_WHITE_BACKUP", bits=bits_to_str(bits),
                    backup_mm=LOST_BACKUP_MM)

            def on_backup_tick():
                _publish(tele, params, started, mode="lost_backup",
                         enc_avg=hw.enc_avg() * MM_PER_DEG)

            found, dist = backup_until_line(
                hw, LOST_BACKUP_MM, BACKUP_SPEED,
                snap["left_th_steer"], snap["right_th_steer"],
                _tick_stop(should_stop, on_backup_tick), should_pause)
            if should_stop():
                return
            if found:
                log.log("LINE_RECOVER", "BACKUP_FOUND_LINE", dist_mm=round(dist, 1))
                lost["last_recover_t"] = time.monotonic()
                return
            item = "U(lost)"
            log.log("DEAD_END", "BACKUP_NO_LINE", bits=bits_to_str(bits),
                    dist_mm=round(dist, 1), trail_add=item)
        else:
            item = "U(lost)"
            log.log("DEAD_END", "LOST_AGAIN_AFTER_RECOVER", bits=bits_to_str(bits),
                    trail_add=item)
        trail_append(state["trail"], item)
        leaf_uturn()

    def handle_node(bits):
        """분기/커브 처리: 정지 → 전진 → 색 재판정 → 커브는 강제 이동, 분기(≥2)는
        FrunMap.arrive() 로 D형 최초방문만 참고하고 실제 이동은 pick_move(좌수법)."""
        hw.stop()

        if bits == (0, 0, 0):
            handle_lost(bits)
            return

        snap = params.snapshot()
        advance(snap["node_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if c == COL_GOAL:
            goal_sequence()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)
        n_options = int(has_left) + int(has_right) + int(has_straight)

        if n_options <= 1:
            # 커브 등 강제 이동: 선택이 아니므로 노드로 취급하지 않는다(heading 만 갱신).
            if has_left:
                item = trail_entry("L", bits)
                log.log("NODE_CURVE", "FORCED_LEFT", bits=bits_to_str(bits), color=c,
                        trail_add=item)
                trail_append(state["trail"], item)
                exec_move("L")
            elif has_right:
                item = trail_entry("R", bits)
                log.log("NODE_CURVE", "FORCED_RIGHT", bits=bits_to_str(bits), color=c,
                        trail_add=item)
                trail_append(state["trail"], item)
                exec_move("R")
            elif has_straight:
                item = trail_entry("S", bits)
                log.log("NODE_CURVE", "FORCED_STRAIGHT", bits=bits_to_str(bits), color=c,
                        trail_add=item)
                trail_append(state["trail"], item)
            else:
                item = "U(dead)"
                log.log("DEAD_END", "NO_EXIT_AFTER_ADVANCE", bits=bits_to_str(bits),
                        color=c, trail_add=item)
                trail_append(state["trail"], item)
                leaf_uturn()
            return

        # 분기(≥2 개방) — FrunMap 은 D형 최초방문 참고용, 실제 이동은 항상 좌수법.
        nid, is_new, mismatch = fmap.arrive(fmap.heading, has_left, has_right, has_straight)
        if mismatch is not None:
            log.log("MAP_MISMATCH", "ARMS_DISAGREE", node_id=nid, bits=bits_to_str(bits),
                    expected=mismatch["expected"], actual=mismatch["actual"])
        is_new_cross = is_new and fmap.trusted

        if has_left and has_right and not has_straight:
            # B형(T자): 직진이 막혀 있다는 걸 advance 로 지나친 뒤에야 알았으므로,
            # 회전 전에 교차점 중심으로 후진 복귀한다.
            snap2 = params.snapshot()
            advance(snap2["peek_backup_mm"], -STRAIGHT_SPEED)
            if should_stop():
                return
            log.log("NODE_TEE", "PEEK_STRAIGHT_BLOCKED", node_id=nid, bits=bits_to_str(bits))
        elif has_left and has_right and has_straight and is_new_cross:
            log.log("NODE_CROSS", "PEEK_STRAIGHT_OPEN_FIRST_VISIT", node_id=nid,
                    bits=bits_to_str(bits))

        move, reason = pick_move(has_left, has_right, has_straight, is_new_cross)
        item = trail_entry(move, bits)
        log.log("NODE_CHOICE", reason, node_id=nid, is_new=is_new, bits=bits_to_str(bits),
                has_left=has_left, has_right=has_right, has_straight=has_straight,
                choice=move, trail_add=item)
        trail_append(state["trail"], item)

        fmap.depart(move)
        exec_move(move)

    # ---- 세션 초기화 (시작/reset 공용) ----
    session_no = {"n": 0}

    def new_session():
        """탐색 상태를 전부 버리고 새 세션을 준비한다(시작/reset 공용)."""
        nonlocal fmap
        if state.get("trail"):
            log_run_trail("SESSION_END")
        fmap = FrunMap()
        state.clear()
        state.update(fresh_session_state())
        lost["last_recover_t"] = -1e9
        reset_steer()
        reset_flag["on"] = False
        session_no["n"] += 1
        if session_no["n"] > 1:
            log.log("SESSION_RESET", "DASHBOARD", source=reset_flag["source"],
                    session=session_no["n"])
        else:
            log.log("SESSION_READY", "STARTUP", session=session_no["n"])

    def take_reset():
        """reset 플래그를 소비했는가. True 면 호출부가 세션을 접어야 한다."""
        if reset_flag["on"]:
            hw.stop()
            return True
        return False

    # ---- 출발 대기(노랑) — reset/stop 을 함께 감시. 반환 status ----
    def wait_for_start():
        snap0 = params.snapshot()
        hw.grip_open(snap0["grip_speed"], GRIP_SEC)
        while hw.read_center_color_value() != COL_YELLOW:
            if stop_flag["on"]:
                log_run_trail("EMERGENCY_STOP")
                return "stop"
            if take_reset():
                return "reset"
            action = take_pending()
            if action is not None:
                handle_pending(action)
            _publish(tele, params, started, mode="waiting_start",
                     session=session_no["n"], trail=trail_tail(state["trail"]))
            time.sleep(0.05)
        hw.beep_ok()
        log.log("NODE_IS_START", "COLOR_YELLOW", color=COL_YELLOW)
        advance_straight(hw, START_EXIT_MM, STRAIGHT_SPEED, should_stop, should_pause)
        reset_steer()
        return "go"

    # ---- 탐색 루프(편도) — 반환 status(stop/reset/done) ----
    def explore():
        node_track = {"kind": None, "t0": 0.0, "latched": (0, 0, 0), "raw": (0, 0, 0)}
        last_node_t = time.monotonic()
        last_visit_t = 0.0
        last_follow_log = time.monotonic() - REASON_THROTTLE_S

        def reset_node_track():
            node_track["kind"] = None
            node_track["t0"] = 0.0
            node_track["latched"] = (0, 0, 0)
            node_track["raw"] = (0, 0, 0)

        while not state["done"]:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                log_run_trail("EMERGENCY_STOP")
                return "stop"
            if take_reset():
                return "reset"

            if pause_state["paused"]:
                hw.stop()
                reset_steer()
                _publish(tele, params, started, mode="paused", paused=True,
                         visits=state["visits"], grabbed=state["grabbed"],
                         nodes=len(fmap.nodes), heading=fmap.heading,
                         session=session_no["n"], trail=trail_tail(state["trail"]))
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            action = take_pending()
            if action is not None:
                handle_pending(action)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            snap = params.snapshot()
            now = time.monotonic()

            # (1) 중앙 색상(상시 컬러모드) — 노드/마커 판정 전용
            c_color = hw.read_center_color_value()

            if c_color == COL_GOAL:
                goal_sequence()
                continue

            # 방문 마커(빨강): 잎 취급 — 유턴하고 계속(복귀/on_probe_end 같은 건 없음).
            if (c_color == COL_VISIT and
                    (now - last_visit_t) * 1000 >= COLOR_DEBOUNCE_MS):
                hw.stop()
                state["visits"] += 1
                item = "U(red)"
                log.log("VISIT_NODE", "RED_REVISIT", color=c_color,
                        visits=state["visits"], trail_add=item)
                trail_append(state["trail"], item)
                leaf_uturn()
                last_visit_t = time.monotonic()
                reset_node_track()
                reset_steer()
                continue

            # (2) 소스통: 초음파 근접 → 파지 (1회)
            if ((not state["grabbed"]) and
                    hw.read_distance_cm() < snap["grab_dist_cm"]):
                hw.stop()
                hw.grip_close(snap["grip_speed"], GRIP_SEC)
                state["grabbed"] = True
                log.log("GRAB", "ULTRASONIC_NEAR", grab_dist_cm=snap["grab_dist_cm"],
                        grip_speed=snap["grip_speed"])
                hw.beep_ok()
                reset_steer()

            # (3) 좌/우 반사광 1회 판독 → 노드 bits 생성(라이브 left_th_node/right_th_node)
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            nbits = bits_node(rl, c_color, rr, snap["left_th_node"], snap["right_th_node"])

            # (4) 노드 후보 추적: 000 은 기존 방식, 나머지는 OR-latch 로 깜빡임 보강.
            if nbits in CANDIDATES and not lost_candidate_blocked(
                    nbits, steer["last_turn"], LOST_GUARD_TURN):
                if nbits == (0, 0, 0):
                    if node_track["kind"] != "empty":
                        node_track["kind"] = "empty"
                        node_track["t0"] = now
                    node_track["raw"] = nbits
                    confirmed_bits = nbits
                else:
                    if node_track["kind"] != "latch":
                        node_track["kind"] = "latch"
                        node_track["t0"] = now
                        node_track["latched"] = nbits
                    else:
                        node_track["latched"] = latch_bits(node_track["latched"], nbits)
                    node_track["raw"] = nbits
                    confirmed_bits = node_track["latched"]

                if ((now - node_track["t0"]) * 1000 >= snap["node_confirm_ms"] and
                        (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS):
                    log.log("NODE_CANDIDATE_LATCH", "OR_LATCH_CONFIRMED",
                            bits_raw=bits_to_str(node_track["raw"]),
                            bits_latched=bits_to_str(confirmed_bits))
                    handle_node(confirmed_bits)
                    last_node_t = time.monotonic()
                    reset_node_track()
                    reset_steer()
                    continue
            else:
                reset_node_track()

            # (5) PD 조향 — 좌/우 반사광 raw 차이만(중앙은 안 쓴다).
            snap_eff = snap if nbits not in SLOW_ON else dict(snap, base_speed=SLOW_SPEED)
            left_speed, right_speed, err, _deriv, turn = pd.step((rl, 0, rr), snap_eff)
            hw.drive(left_speed, right_speed)
            steer["last_turn"] = turn

            if (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "PID", reflect_l=rl, reflect_r=rr,
                        bits=bits_to_str(nbits), error=err, turn=turn)
                last_follow_log = now

            _publish(tele, params, started, mode="follow",
                     reflect_l=rl, reflect_r=rr,
                     color=c_color, bits=bits_to_str(nbits), error=err, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     visits=state["visits"], arrived=state["goal_seen"],
                     nodes=len(fmap.nodes), heading=fmap.heading,
                     grabbed=state["grabbed"], session=session_no["n"],
                     trail=trail_tail(state["trail"]))

            time.sleep(LOOP_DELAY_MS / 1000.0)
        return "done"

    # ---- 완주 후 대기 — reset 을 눌러야 다음 세션. ----
    def idle_after_done():
        hw.stop()
        while True:
            if stop_flag["on"]:
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                log_run_trail("EMERGENCY_STOP")
                return "stop"
            if take_reset():
                return "reset"
            action = take_pending()
            if action is not None:
                handle_pending(action)
            _publish(tele, params, started, mode="finished",
                     visits=state["visits"], nodes=len(fmap.nodes),
                     session=session_no["n"], trail=trail_tail(state["trail"]))
            time.sleep(0.05)

    print("frun_v1 ready. dashboard 'reset' returns to YELLOW start any time. "
          "(Ctrl-C or robotctl stop to quit)")

    # ================= 세션 루프 =================
    try:
        while not stop_flag["on"]:
            new_session()

            status = wait_for_start()
            if status == "stop":
                break
            if status == "reset":
                continue

            status = explore()
            if status == "stop":
                break
            if status == "reset":
                continue

            # status == "done" → 완주. reset 전까지 idle.
            status = idle_after_done()
            if status == "stop":
                break
            # "reset" → 세션 루프 상단으로(new_session).
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
        log_run_trail("KEYBOARD_STOP")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()

    print("frun_v1 stopped. sessions={}".format(session_no["n"]))


if __name__ == "__main__":
    run()
