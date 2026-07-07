#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v4.py — 전 노드 방문(분기 정리형, 좌>우>직) 탐색 + 최단경로 복귀.

v3(run_maze_v3.py, 유지)와의 차이 — 사용자 사양(2026-07-07):
  - 가는 길: 우>좌>직 편도 탐색 대신 **모든 분기의 모든 팔을 정리**하는 완전 탐색.
    우선순위는 좌>우>직(PRIORITY 상수 — 테스트에서 우>좌>직으로 교체 가능).
  - 초록(도착): v3 도착 시퀀스(goal_advance_mm 전진→그리퍼 오픈→후진→유턴) 그대로
    실행하되 **종료하지 않고** 남은 팔/pending 을 계속 정리한다.
  - 탐색 중 지도(트리)를 구축하고, 전부 정리되면 **트리 최단경로(부모 체인)**를
    계산해 노드 안 찍고 집(노랑)으로 직행 복귀한다.

탐색 규칙(분기 정리형):
  항상 "작업 분기(work junction)" 하나를 정리 중이다.
  1. 작업 분기의 안 가본 팔을 우선순위(좌>우>직, 그 시점 heading 기준 상대방향)로
     하나 골라 진입(PROBE).
  2. 팔 끝이 빨강 마커/막다른길/초록이면: (초록은 도착 시퀀스 후) 유턴 → 작업
     분기로 복귀(RETURN_TO_WORK) → 다음 팔.
  3. 진입 도중 새 분기를 만나면 들어가지 않는다:
     - 작업 분기에 안 가본 팔이 남았으면 → 새 분기를 작업 분기의 pending 에 기록,
       즉시 유턴해 복귀. 남은 팔을 전부 정리한 뒤 pending 으로 이동(GOTO_PENDING),
       그것이 새 작업 분기가 된다.
     - 남은 팔이 없으면 → 새 분기가 그 자리에서 바로 작업 분기(복귀 없음).
  4. 한 분기가 팔+pending 까지 전부 끝나면 부모 분기로 복귀(BACKTRACK)해 부모의
     남은 pending 을 잇는다. 루트까지 다 끝나면 EXPLORE_DONE → 복귀 단계.
  5. 커브(출구 1개 강제 이동)는 분기가 아니다 — v2/v3 과 동일한 강제 이동 처리.

핵심 불변식 (노드 식별이 전역 위치인식 없이 성립하는 이유):
  pending 은 전역 스택이 아니라 **분기별 목록**이고, 분기 완료 시 **부모로 복귀**
  (BACKTRACK)하므로, 로봇의 모든 전이 주행(RETURN_TO_WORK/GOTO_PENDING/BACKTRACK)은
  **인접 분기 간 이동**이다 — 그 사이 경로에는 커브만 있다(발견 당시 PROBE 가 커브만
  지나 처음 만난 분기에서 멈췄기 때문). 따라서:
    "전이 주행 중 처음 만나는 분기 = 전이의 목표 분기"
  가 모든 전이에서 보장된다. tests/test_run_maze_v4_logic.py 의 코스 시뮬레이션이
  이 불변식 위에서 전 마커 방문/복귀를 검증한다.

heading dead-reckoning: 논리 방향 N/E/S/W 를 순수 판단층(Explorer)이 유지한다.
  실행된 모든 회전(커브 강제 이동, 유턴, 도착 시퀀스 유턴 포함)마다 apply_move 로
  갱신 — 구동층 do_turn() 래퍼가 한 곳에서 처리한다. 직각 그리드 코스 가정.

복귀(home): EXPLORE_DONE 시점 노드에서 부모 체인이 곧 트리 최단경로. 경로를
  "노드별 절대 출구 방향" 리스트로 만들어(RETURN_PLAN 1회 로그) 분기 검출마다
  하나씩 소비 — heading 대비 상대 회전(L/R/S/U)으로 변환해 실행(RETURN_STEP).
  커브는 평소처럼 강제 이동(소비 없음). 복귀 중 빨강/초록 무시, 초음파 파지 비활성.
  노랑 감지 = 집 도착 → 정지 + 비프 2회 종료. 예상과 불일치/경로 소진 시
  RETURN_FALLBACK 후 즉석 탐색(좌>우>직)으로 계속 — 절대 멈춰 기다리지 않는다.

v1/v2/v3 재사용(import — 확정 코드 미수정):
  v1: bits/구동 헬퍼/타이밍/임계값. v2: 000 가드, 라이브 turn_speed 회전(_run_turn),
  마커 색(방문=빨강/도착=초록). v3: 구조만 따름(도착 시퀀스 순서, 라이브 params
  12개 동일 구성 — config/run_maze_v3.json 을 run_maze_v4.json 으로 복사해 이식 가능).

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C.

독립 실행(브릭):  python3 stages/run_maze_v4.py
문법 점검(PC):    python3 -m py_compile stages/run_maze_v4.py lib/*.py
판단층 테스트(PC): python3 tests/test_run_maze_v4_logic.py
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
    LEFT_TH_NODE, RIGHT_TH_NODE,
    NODE_DEBOUNCE_MS,
    LOST_BACKUP_MM, BACKUP_SPEED, LOST_RETRY_WINDOW_MS,
    COLOR_DEBOUNCE_MS, START_EXIT_MM, GRIP_SEC, LOOP_DELAY_MS,
    REASON_THROTTLE_S, STRAIGHT_SPEED, SLOW_SPEED, MM_PER_DEG,
)
# v2 확정 코드 재사용(미수정): 000 가드 + 라이브 turn_speed 회전 + 마커 색 재배치.
from stages.run_maze_v2 import (                                     # noqa: E402
    lost_candidate_blocked, LOST_GUARD_TURN, _run_turn,
    COL_VISIT, COL_GOAL,
)
# Stage 3 확정 조향 재사용(미수정).
from stages.stage3v2_linetrace_branch import PdController            # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 라이브 params — v3 와 완전 동일 12개(키/시드). v4 전용 추가 없음
# (탐색 우선순위는 PRIORITY 상수). config/run_maze_v3.json 이식 가능.
# =====================================================================

INITIAL_PARAMS = {
    "base_speed": 16,         # 주행 속도(%). PD 확정 조합(stage3v2/stage4v2) 시드
    "kp": 0.2,                # PD 조향 게인(좌/우 raw 차) — stage3v2 실기 확정값 시드
    "turn_speed": 6,          # 회전 속도(%) — 팀 스테이지 확정값 시드
    "node_confirm_ms": 90,    # 노드 후보 확정 시간(ms)
    "left_th_steer": 64,      # 후진 복구 line_found 감도
    "right_th_steer": 65,
    "node_advance_mm": 20,    # ★ 확정 후 재판정/회전 전 전진량
    "goal_advance_mm": 20,    # ★ 도착 시퀀스: 초록 후 추가 전진(=후진) 거리
    "turn_90_factor": 0.66,   # ★ 과/부족 시 0.05 단위 미세조정
    "turn_180_factor": 0.71,  # ★ 유턴도 같은 비율로 과회전 가감
    "grab_dist_cm": 6.0,      # ★ 조립에 따라 실기값 다름
    "grip_speed": 30,         # ★ 조립에 따라 부호 반전
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "kp": (0.0, 3.0),
    "turn_speed": (5, 40),
    "node_confirm_ms": (0, 1000),
    "left_th_steer": (0, 100),
    "right_th_steer": (0, 100),
    "node_advance_mm": (0, 120),
    "goal_advance_mm": (0, 200),
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
    "node_advance_mm": 10,
    "goal_advance_mm": 10,
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
    "node_advance_mm": 10,
    "goal_advance_mm": 10,
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
    "node_advance_mm": "mm",
    "goal_advance_mm": "mm",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "grab_dist_cm": "cm",
    "grip_speed": "%",
}
PARAM_ORDER = [
    "base_speed", "kp", "turn_speed", "node_confirm_ms",
    "left_th_steer", "right_th_steer",
    "node_advance_mm", "goal_advance_mm",
    "turn_90_factor", "turn_180_factor",
    "grab_dist_cm", "grip_speed",
]

SAVE_PATH = os.path.join(_ROOT, "config", "run_maze_v4.json")
STAGE_NAME = "run_maze_v4"

ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
]

# 탐색 우선순위(상대방향). 좌>우>직 — 테스트에서 ("R","L","S") 로도 검증한다.
PRIORITY = ("L", "R", "S")


# =====================================================================
# 판단층 1: 논리 heading (순수 — PC 테스트 가능)
# =====================================================================

DIRS = ("N", "E", "S", "W")   # 시계방향 순서

# 상대 이동 → heading 인덱스 변화 (시계방향 +)
_MOVE_STEP = {"S": 0, "R": 1, "U": 2, "L": 3}
_STEP_MOVE = {0: "S", 1: "R", 2: "U", 3: "L"}


def turn_heading(heading, move):
    """상대 이동(L/R/S/U) 후의 heading. rel→abs 변환으로도 쓴다."""
    return DIRS[(DIRS.index(heading) + _MOVE_STEP[move]) % 4]


def abs_to_rel(heading, target_dir):
    """현재 heading 에서 절대 방향 target_dir 로 나가려면 필요한 상대 이동."""
    return _STEP_MOVE[(DIRS.index(target_dir) - DIRS.index(heading)) % 4]


def opposite(direction):
    return DIRS[(DIRS.index(direction) + 2) % 4]


def arms_from_bits(heading, has_left, has_right, has_straight):
    """분기 도착 시점 감지 출구(진입 팔 제외) → 절대 방향 집합."""
    arms = []
    if has_left:
        arms.append(turn_heading(heading, "L"))
    if has_right:
        arms.append(turn_heading(heading, "R"))
    if has_straight:
        arms.append(heading)
    return arms


# =====================================================================
# 판단층 2: 지도(트리) — MazeMap (순수)
# =====================================================================

# 팔 상태
ARM_UNEXPLORED = "UNEXPLORED"
ARM_CLEARED = "CLEARED"       # 빨강/막다른길/초록 끝 — 더 볼 것 없음
ARM_LINKED = "LINKED"         # 자식 분기로 이어짐


class MazeMap(object):
    """분기 트리. 노드 = 분기(junction), 팔(arm) = 절대 방향별 출구."""

    def __init__(self):
        self.nodes = {}
        self._next_id = 0

    def add_junction(self, heading, has_left, has_right, has_straight, parent_id):
        """도착 heading 과 감지 출구로 새 분기 생성. parent_dir = 진입 팔(뒤쪽)."""
        nid = self._next_id
        self._next_id += 1
        arms = {}
        for d in arms_from_bits(heading, has_left, has_right, has_straight):
            arms[d] = {"state": ARM_UNEXPLORED, "child_id": None}
        self.nodes[nid] = {
            "id": nid,
            "parent_id": parent_id,
            "parent_dir": opposite(heading),
            "arms": arms,
            "pending": [],            # 미룬 자식 분기의 팔 방향(LIFO)
        }
        return nid

    def node(self, nid):
        return self.nodes[nid]

    def unexplored_dirs(self, nid):
        node = self.nodes[nid]
        return [d for d in node["arms"] if node["arms"][d]["state"] == ARM_UNEXPLORED]

    def pick_arm(self, nid, heading, priority):
        """우선순위(상대방향, 그 시점 heading 기준)로 안 가본 팔 선택. 없으면 None.

        진입 팔의 반대(rel U)에 안 가본 팔이 남는 특수 배치도 놓치지 않게
        priority 뒤에 "U" 를 항상 붙인다.
        """
        todo = self.unexplored_dirs(nid)
        for rel in tuple(priority) + ("U",):
            d = turn_heading(heading, rel)
            if d in todo:
                return d
        return None

    def mark_cleared(self, nid, arm_dir):
        self.nodes[nid]["arms"][arm_dir]["state"] = ARM_CLEARED

    def link_child(self, nid, arm_dir, child_id):
        arm = self.nodes[nid]["arms"][arm_dir]
        arm["state"] = ARM_LINKED
        arm["child_id"] = child_id

    def path_to_root(self, nid):
        """nid → 루트까지 (node_id, 출구 절대방향=parent_dir) 리스트.

        트리이므로 부모 체인이 곧 최단경로(BFS 와 동일 결과).
        """
        chain = []
        cur = nid
        while cur is not None:
            node = self.nodes[cur]
            chain.append((cur, node["parent_dir"]))
            cur = node["parent_id"]
        return chain

    def pending_total(self):
        return sum(len(n["pending"]) for n in self.nodes.values())


# =====================================================================
# 판단층 3: 탐색 상태머신 — Explorer (순수)
#
# 상태(mode):
#   TO_FIRST        출발 후 첫 분기 탐색 주행
#   PROBE           작업 분기의 팔 하나에 진입해 주행 중
#   RETURN_TO_WORK  팔 끝(빨강/막다른길/초록)/pending 기록 후 작업 분기로 복귀 주행
#   GOTO_PENDING    작업 분기에서 pending 자식 분기로 이동 주행
#   BACKTRACK       정리 끝난 분기에서 부모 분기로 이동 주행
#   HOME            복귀(경로 소비) 주행
#
# 구동층(run)/시뮬레이터는 분기·팔끝 이벤트마다 아래 메서드를 호출하고,
# 반환된 move(L/R/S/U)를 실행한 뒤 apply_move 로 heading 을 갱신한다.
# =====================================================================

class Explorer(object):

    def __init__(self, priority=PRIORITY):
        self.map = MazeMap()
        self.priority = tuple(priority)
        self.heading = "N"           # 논리 방향(출발 heading 을 N 으로 고정)
        self.mode = "TO_FIRST"
        self.work_id = None          # 현재 작업 분기
        self.probe_arm = None        # PROBE 중인 팔(작업 분기 기준 절대방향)
        self.goto_arm = None         # GOTO_PENDING 목표 팔
        self.plan = []               # HOME 경로 [(node_id, 출구 절대방향), ...]

    # ---- heading (모든 실행된 회전은 여기로 보고된다 — 커브/유턴 포함) ----

    def apply_move(self, move):
        self.heading = turn_heading(self.heading, move)

    # ---- 분기 도착 ----

    def on_junction(self, has_left, has_right, has_straight):
        """가는 길(out) 분기 도착. (실행할 move, events) 반환.

        불변식(모듈 docstring): 전이 주행 중 처음 만나는 분기 = 목표 분기.
        """
        events = []

        if self.mode == "TO_FIRST":
            nid = self.map.add_junction(self.heading, has_left, has_right,
                                        has_straight, None)
            self.work_id = nid
            events.append(("NODE_NEW_JUNCTION", "FIRST", {
                "id": nid, "heading": self.heading,
                "arms": "".join(sorted(self.map.node(nid)["arms"]))}))
            move, more = self._select_next()
            return move, events + more

        if self.mode == "PROBE":
            # 새 분기 발견. 작업 분기 팔을 링크하고 pend/adopt 결정.
            nid = self.map.add_junction(self.heading, has_left, has_right,
                                        has_straight, self.work_id)
            self.map.link_child(self.work_id, self.probe_arm, nid)
            work = self.map.node(self.work_id)
            if self.map.unexplored_dirs(self.work_id):
                work["pending"].append(self.probe_arm)
                events.append(("NODE_NEW_JUNCTION", "PENDING_DISCOVERED", {
                    "id": nid, "parent_id": self.work_id, "heading": self.heading,
                    "arms": "".join(sorted(self.map.node(nid)["arms"]))}))
                events.append(("PENDING_SAVED", "WORK_HAS_ARMS", {
                    "work": self.work_id, "via_arm": self.probe_arm,
                    "pending_count": len(work["pending"])}))
                self.probe_arm = None
                self.mode = "RETURN_TO_WORK"
                return "U", events
            events.append(("NODE_NEW_JUNCTION", "ADOPT", {
                "id": nid, "parent_id": self.work_id, "heading": self.heading,
                "arms": "".join(sorted(self.map.node(nid)["arms"]))}))
            self.work_id = nid
            self.probe_arm = None
            move, more = self._select_next()
            return move, events + more

        if self.mode == "RETURN_TO_WORK":
            events.append(("BACK_TO_WORK", "PROBE_END_RETURN", {
                "work": self.work_id}))
            move, more = self._select_next()
            return move, events + more

        if self.mode == "GOTO_PENDING":
            child_id = self.map.node(self.work_id)["arms"][self.goto_arm]["child_id"]
            self.work_id = child_id
            self.goto_arm = None
            events.append(("BACK_TO_WORK", "PENDING_ARRIVED", {
                "work": self.work_id}))
            move, more = self._select_next()
            return move, events + more

        if self.mode == "BACKTRACK":
            parent_id = self.map.node(self.work_id)["parent_id"]
            self.work_id = parent_id
            events.append(("BACK_TO_WORK", "BACKTRACK_ARRIVED", {
                "work": self.work_id}))
            move, more = self._select_next()
            return move, events + more

        # HOME 은 on_junction_home 으로 — 여기 오면 호출부 버그.
        events.append(("RETURN_FALLBACK", "BAD_MODE", {"mode": self.mode}))
        return "S", events

    def _select_next(self):
        """작업 분기에서 다음 행동 선택: 팔 → pending → 부모 복귀 → EXPLORE_DONE."""
        events = []
        work = self.map.node(self.work_id)

        arm = self.map.pick_arm(self.work_id, self.heading, self.priority)
        if arm is not None:
            self.probe_arm = arm
            self.mode = "PROBE"
            move = abs_to_rel(self.heading, arm)
            events.append(("BRANCH_PROBE", "PRIORITY_" + "_".join(self.priority), {
                "work": self.work_id, "arm": arm, "move": move}))
            return move, events

        if work["pending"]:
            self.goto_arm = work["pending"].pop()      # LIFO
            self.mode = "GOTO_PENDING"
            move = abs_to_rel(self.heading, self.goto_arm)
            events.append(("WORK_CLEARED_GOTO_PENDING", "LIFO", {
                "work": self.work_id, "arm": self.goto_arm, "move": move,
                "pending_left": len(work["pending"])}))
            return move, events

        if work["parent_id"] is not None:
            self.mode = "BACKTRACK"
            move = abs_to_rel(self.heading, work["parent_dir"])
            events.append(("BACK_TO_WORK", "BACKTRACK_START", {
                "work": work["parent_id"], "from": self.work_id, "move": move}))
            return move, events

        # 루트까지 전부 정리 — 복귀 시작. 현재 이 분기 위에 서 있으므로
        # 경로의 첫 스텝(이 분기의 출구)을 즉시 소비한다.
        events.append(("EXPLORE_DONE", "MAP_COMPLETE", {
            "nodes": len(self.map.nodes)}))
        self.plan = self.map.path_to_root(self.work_id)
        events.append(("RETURN_PLAN", "PARENT_CHAIN", {
            "path": ">".join("{}:{}".format(n, d) for n, d in self.plan),
            "steps": len(self.plan)}))
        self.mode = "HOME"
        move, more = self._consume_plan(True, True, True)   # 자기 분기 — 출구 보장
        return move, events + more

    # ---- 팔 끝(빨강/막다른길/초록 — 유턴은 호출 전에 실행·보고됐다) ----

    def on_probe_end(self, kind):
        """PROBE 중 팔 끝 도달(kind: red/dead_end/goal). 팔 CLEARED + 복귀 모드."""
        events = []
        if self.mode != "PROBE" or self.work_id is None:
            # TO_FIRST 등에서의 팔 끝 — 지도가 없다. 로그만 남기고 계속(best effort).
            events.append(("RETURN_FALLBACK", "PROBE_END_NO_WORK", {
                "mode": self.mode, "kind": kind}))
            return events
        self.map.mark_cleared(self.work_id, self.probe_arm)
        events.append(("BRANCH_PROBE", "ARM_CLEARED", {
            "work": self.work_id, "arm": self.probe_arm, "kind": kind}))
        self.probe_arm = None
        self.mode = "RETURN_TO_WORK"
        return events

    # ---- 복귀(HOME) 분기 도착 ----

    def on_junction_home(self, has_left, has_right, has_straight):
        return self._consume_plan(has_left, has_right, has_straight)

    def _consume_plan(self, has_left, has_right, has_straight):
        events = []
        if not self.plan:
            events.append(("RETURN_FALLBACK", "STACK_EMPTY", {}))
            return self._fallback_move(has_left, has_right, has_straight), events

        node_id, exit_dir = self.plan.pop(0)
        move = abs_to_rel(self.heading, exit_dir)
        ok = ((move == "L" and has_left) or (move == "R" and has_right) or
              (move == "S" and has_straight) or move == "U")
        if not ok:
            events.append(("RETURN_FALLBACK", "PATH_MISMATCH", {
                "node_id": node_id, "exit": exit_dir, "move": move,
                "plan_left": len(self.plan)}))
            return self._fallback_move(has_left, has_right, has_straight), events

        events.append(("RETURN_STEP", "PLAN", {
            "node_id": node_id, "exit": exit_dir, "move": move,
            "plan_left": len(self.plan)}))
        return move, events

    def _fallback_move(self, has_left, has_right, has_straight):
        """계획이 깨졌을 때 즉석 선택(우선순위 그대로) — 멈추지 않는다."""
        avail = {"L": has_left, "R": has_right, "S": has_straight}
        for rel in self.priority:
            if avail.get(rel):
                return rel
        return "U"


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run(). v3 뼈대에서 판단층만 교체.
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
    ex = Explorer()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending_do = {"action": None}
    plock = threading.Lock()

    state = {"visits": 0, "goal_seen": False, "done": False, "grabbed": False}
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
        if action not in ("read_color", "read_reflect"):
            return {"error": "unknown action: {}".format(action)}
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

    def phase():
        return "home" if ex.mode == "HOME" else "out"

    def reset_steer():
        pd.reset()
        steer["last_turn"] = 0.0

    def log_events(events):
        for ev, rule, detail in events:
            log.log(ev, rule, **detail)

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
        ex.apply_move({"turn_left": "L", "turn_right": "R", "uturn": "U"}[cmd])

    def exec_move(move):
        if move == "L":
            do_turn("turn_left")
        elif move == "R":
            do_turn("turn_right")
        elif move == "U":
            do_turn("uturn")
        # "S" 는 회전 없음(heading 불변)

    def advance(distance_mm, speed):
        def on_adv_tick():
            _publish(tele, params, started, mode="advancing", phase=phase(),
                     enc_avg=hw.enc_avg() * MM_PER_DEG)
        advance_straight(hw, distance_mm, speed,
                         _tick_stop(should_stop, on_adv_tick), should_pause)

    def goal_sequence():
        """도착 시퀀스(v3 순서 그대로): 전진 → 그리퍼 오픈 → 후진 → 유턴.
        v4 는 종료하지 않고 PROBE 팔 끝(goal)으로 처리해 탐색을 잇는다."""
        hw.stop()
        snap = params.snapshot()
        state["goal_seen"] = True
        log.log("NODE_IS_GOAL", "COLOR_GREEN", color=COL_GOAL)
        advance(snap["goal_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return
        hw.grip_open(snap["grip_speed"], GRIP_SEC)
        hw.beep_ok()
        advance(snap["goal_advance_mm"], -STRAIGHT_SPEED)
        if should_stop():
            return
        do_turn("uturn")
        log_events(ex.on_probe_end("goal"))
        reset_steer()

    def handle_lost(bits):
        """000(선 유실) — v3 과 동일한 후진 복구. 유턴까지 가면 상태머신에 통지."""
        snap = params.snapshot()
        retry_ok = ((time.monotonic() - lost["last_recover_t"]) * 1000
                    >= LOST_RETRY_WINDOW_MS)
        if retry_ok:
            log.log("LINE_LOST", "ALL_WHITE_BACKUP", bits=bits_to_str(bits),
                    backup_mm=LOST_BACKUP_MM, phase=phase())

            def on_backup_tick():
                _publish(tele, params, started, mode="lost_backup", phase=phase(),
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
            log.log("DEAD_END", "BACKUP_NO_LINE", bits=bits_to_str(bits),
                    dist_mm=round(dist, 1), phase=phase())
        else:
            log.log("DEAD_END", "LOST_AGAIN_AFTER_RECOVER", bits=bits_to_str(bits),
                    phase=phase())
        do_turn("uturn")
        if ex.mode == "PROBE":
            log_events(ex.on_probe_end("dead_end"))
        elif ex.mode == "HOME":
            log.log("RETURN_FALLBACK", "DEAD_END_ON_RETURN", bits=bits_to_str(bits))
        else:
            # 전이 주행(RETURN/GOTO/BACKTRACK/TO_FIRST) 중 막다른길 — 불변식 밖.
            # 유턴한 채 계속 주행(best effort), 다음 분기에서 상태대로 처리된다.
            log.log("RETURN_FALLBACK", "DEAD_END_ON_TRANSIT", mode=ex.mode,
                    bits=bits_to_str(bits))

    def handle_node(bits):
        """분기/커브 처리(가는 길·복귀 공용): 정지 → 전진 → 색 재판정 →
        커브는 강제 이동, 분기는 Explorer(out)/경로 소비(home)."""
        hw.stop()

        if bits == (0, 0, 0):
            handle_lost(bits)
            return

        snap = params.snapshot()
        advance(snap["node_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if ex.mode != "HOME" and c == COL_GOAL:      # 전진했더니 도착 영역
            goal_sequence()
            return
        if ex.mode == "HOME" and c == COL_YELLOW:    # 전진했더니 집
            home_reached()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)
        n_options = int(has_left) + int(has_right) + int(has_straight)

        if n_options <= 1:
            # 커브 등 강제 이동 — 분기가 아니다(모든 상태 공통, 경로 소비 없음).
            if has_left:
                log.log("NODE_CURVE", "FORCED_LEFT", bits=bits_to_str(bits), color=c)
                do_turn("turn_left")
            elif has_right:
                log.log("NODE_CURVE", "FORCED_RIGHT", bits=bits_to_str(bits), color=c)
                do_turn("turn_right")
            elif has_straight:
                log.log("NODE_CURVE", "FORCED_STRAIGHT", bits=bits_to_str(bits), color=c)
            else:
                log.log("DEAD_END", "NO_EXIT_AFTER_ADVANCE", bits=bits_to_str(bits),
                        color=c, phase=phase())
                do_turn("uturn")
                if ex.mode == "PROBE":
                    log_events(ex.on_probe_end("dead_end"))
            return

        if ex.mode == "HOME":
            move, events = ex.on_junction_home(has_left, has_right, has_straight)
        else:
            move, events = ex.on_junction(has_left, has_right, has_straight)
        log_events(events)
        exec_move(move)

    def home_reached():
        hw.stop()
        state["done"] = True
        log.log("NODE_IS_HOME", "COLOR_YELLOW", color=COL_YELLOW,
                plan_left=len(ex.plan))
        hw.beep_ok()
        hw.beep_ok()

    print("run_maze_v4 ready. waiting YELLOW on center sensor... "
          "(Ctrl-C or robotctl stop to quit)")

    # ---------- 출발 대기 ----------
    snap0 = params.snapshot()
    hw.grip_open(snap0["grip_speed"], GRIP_SEC)
    while hw.read_center_color_value() != COL_YELLOW:
        if stop_flag["on"]:
            hw.stop()
            log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
            server.stop()
            print("run_maze_v4 stopped before start.")
            return
        action = take_pending()
        if action is not None:
            handle_pending(action)
        _publish(tele, params, started, mode="waiting_start")
        time.sleep(0.05)
    hw.beep_ok()
    log.log("NODE_IS_START", "COLOR_YELLOW", color=COL_YELLOW)
    advance_straight(hw, START_EXIT_MM, STRAIGHT_SPEED, should_stop, should_pause)
    reset_steer()

    # ---------- 메인 루프 (탐색 + 복귀) ----------
    cand = None
    cand_t0 = 0.0
    last_node_t = time.monotonic()
    last_visit_t = 0.0
    last_follow_log = time.monotonic() - REASON_THROTTLE_S

    print("run_maze_v4 running. stop via 'robotctl stop' or Ctrl-C.")
    try:
        while not state["done"]:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.stop()
                reset_steer()
                _publish(tele, params, started, mode="paused", paused=True,
                         phase=phase(), visits=state["visits"],
                         work_id=ex.work_id, nodes=len(ex.map.nodes),
                         pending_total=ex.map.pending_total(),
                         grabbed=state["grabbed"])
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            action = take_pending()
            if action is not None:
                handle_pending(action)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            snap = params.snapshot()
            now = time.monotonic()
            on_home = (ex.mode == "HOME")

            # (1) 중앙 색상(상시 컬러모드) — 노드/마커 판정 전용
            c_color = hw.read_center_color_value()

            if (not on_home) and c_color == COL_GOAL:
                goal_sequence()
                continue

            if on_home and c_color == COL_YELLOW:
                home_reached()
                break

            # 방문 마커(빨강): PROBE 중에만 유턴+카운트(팔 끝 처리).
            # 전이 주행 중엔 무시(방금 유턴한 마커 재감지 방지 — 디바운스 병행),
            # 복귀 중에도 무시(v3 과 동일).
            if (ex.mode == "PROBE" and c_color == COL_VISIT and
                    (now - last_visit_t) * 1000 >= COLOR_DEBOUNCE_MS):
                hw.stop()
                state["visits"] += 1
                log.log("VISIT_NODE", "RED_PROBE_END", color=c_color,
                        visits=state["visits"])
                do_turn("uturn")
                log_events(ex.on_probe_end("red"))
                last_visit_t = time.monotonic()
                cand = None
                reset_steer()
                continue

            # (2) 소스통 파지: 가는 길에만(복귀 중에는 이미 내려놓았다)
            if ((not on_home) and (not state["grabbed"]) and
                    hw.read_distance_cm() < snap["grab_dist_cm"]):
                hw.stop()
                hw.grip_close(snap["grip_speed"], GRIP_SEC)
                state["grabbed"] = True
                log.log("GRAB", "ULTRASONIC_NEAR", grab_dist_cm=snap["grab_dist_cm"],
                        grip_speed=snap["grip_speed"])
                hw.beep_ok()
                reset_steer()

            # (3) 좌/우 반사광 1회 판독 → 노드 bits 생성
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            nbits = bits_node(rl, c_color, rr, LEFT_TH_NODE, RIGHT_TH_NODE)

            # (4) 노드 후보 추적 (엄격 bits, confirm + debounce, 000 가드 — v2 동일)
            if nbits in CANDIDATES and not lost_candidate_blocked(
                    nbits, steer["last_turn"], LOST_GUARD_TURN):
                if cand != nbits:
                    cand = nbits
                    cand_t0 = now
                elif ((now - cand_t0) * 1000 >= snap["node_confirm_ms"] and
                      (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS):
                    handle_node(nbits)
                    last_node_t = time.monotonic()
                    cand = None
                    reset_steer()
                    continue
            else:
                cand = None

            # (5) PD 조향 — 좌/우 반사광 raw 차이만(중앙은 안 쓴다). v2/v3 동일.
            snap_eff = snap if nbits not in SLOW_ON else dict(snap, base_speed=SLOW_SPEED)
            left_speed, right_speed, err, _deriv, turn = pd.step((rl, 0, rr), snap_eff)
            hw.drive(left_speed, right_speed)
            steer["last_turn"] = turn

            if (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "PID", reflect_l=rl, reflect_r=rr,
                        bits=bits_to_str(nbits), error=err, turn=turn,
                        phase=phase())
                last_follow_log = now

            _publish(tele, params, started, mode="follow", phase=phase(),
                     reflect_l=rl, reflect_r=rr,
                     color=c_color, bits=bits_to_str(nbits), error=err, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     visits=state["visits"], arrived=state["goal_seen"],
                     work_id=ex.work_id, nodes=len(ex.map.nodes),
                     pending_total=ex.map.pending_total(),
                     plan_left=len(ex.plan), grabbed=state["grabbed"])

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()

    print("done. visits={} goal={} home={} nodes={}".format(
        state["visits"], state["goal_seen"], state["done"], len(ex.map.nodes)))


if __name__ == "__main__":
    run()
