#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v3.py — 왕복 완주: v2(PD 조향) + 경로 기억 복귀.

v2(run_maze_v2.py, 유지)와의 차이 — 사용자 요청(2026-07-06):
  편도(노랑→초록)에서 끝내지 않고, 초록(도착)을 찍으면
    ① goal_advance_mm 만큼 조금 더 직진 → 그리퍼 오픈(물체 내려놓기)
    ② 같은 거리만큼 후진 → 유턴
    ③ **왔던 길을 기억했다가 그대로 되짚어** 노랑(출발=집)으로 복귀, 종료.
  복귀 전략 3안(같은 탐색 로직/경로 기억 복귀/최적 경로) 중 2안(경로 기억) 채택.

경로 기억(판단층, 순수):
  - 가는 길(out)에 노드/커브에서 실행한 이동을 path 리스트에 기록: "L"/"R"/"S".
    막다른길·방문마커 유턴은 "U" 로 기록한다.
  - "U" 는 직전 이동과 다음 이동을 상쇄한다 — push_move() 가 [X, U, Z] 를
    회전각 합성으로 즉시 접는다(예: L,U,S → R. 90+180+0=270°=우회전과 동일).
    덕분에 path 에는 **출발→도착 직행 경로만** 남는다(막다른길 왕복 제외).
    "온 길 그대로"의 의미: 성공한 경로를 그대로 되짚는 것 — 막다른길까지
    다시 들어갔다 나오지는 않는다.
  - 복귀(home)에는 path 를 뒤에서부터 pop 하며 **좌우 반전**(L↔R, S 유지)해
    실행한다. 같은 노드를 반대 방향에서 지나므로 반전이 곧 "그대로 돌아가기".

복귀 중 안전장치:
  - pop 한 이동이 현재 노드 bits/색과 안 맞으면(RETURN_FALLBACK mismatch)
    또는 path 가 바닥나면(stack_empty) 즉석 탐색(우>좌>직)으로 폴백 — 멈춰서
    사람 손을 기다리는 대신 최대한 계속 간다(로그로 표시).
  - 복귀 중 초록/빨강 마커는 무시(도착 재판정·방문 유턴 금지), 초음파 파지도
    비활성(이미 내려놓았다). 노랑을 다시 보면 집 도착 → 정지+비프 2회 종료.

v2 에서 그대로 가져오는 것(import — 복붙 금지 규약):
  - PD 조향 전환/000 가드/마커 색 재배치(방문=빨강, 도착=초록)/라이브 turn_speed
    회전(_run_turn)/탐색 로직(우>좌>직+직전 분기 기억)/000 후진 복구/그리퍼/초음파.

라이브 params: v2 의 12개(= v2 11개 + goal_advance_mm). goal_advance_mm 은
도착 시퀀스 ①/② 의 전진/후진 거리(★ 실기에서 소스통 내려놓을 위치로 보정).

센서/마커: 중앙(in2)=항상 색상모드, 좌(in1)/우(in3)=반사광.
  노랑=출발(집), 빨강=방문 노드(유턴), 초록=도착. (v2 와 동일)

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C.

독립 실행(브릭):  python3 stages/run_maze_v3.py
문법 점검(PC):    python3 -m py_compile stages/run_maze_v3.py lib/*.py
판단층 테스트(PC): python3 tests/test_run_maze_v3_logic.py
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
# v1(run_maze) 확정 코드 재사용(미수정): 탐색 판단층 + 구동 헬퍼 + 타이밍/임계값.
from stages.run_maze import (                                        # noqa: E402
    bits_node, choose_branch, bits_to_str,
    advance_straight, backup_until_line, _tick_stop, _publish,
    COL_BLACK, COL_YELLOW,
    CANDIDATES, SLOW_ON, OPPOSITE,
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
# Stage 3 확정 조향 재사용(미수정): PD 수식 + KD/TURN_LIMIT 은 stage3v2 내부값.
from stages.stage3v2_linetrace_branch import PdController            # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 라이브 params — v2 의 11개 + goal_advance_mm = 12개.
# =====================================================================

INITIAL_PARAMS = {
    "base_speed": 17,         # 주행 속도(%). PD 확정 조합(stage3v2/stage4v2) 시드
    "kp": 0.22,               # PD 조향 게인(좌/우 raw 차) — stage3v2 실기 확정값 시드
    "turn_speed": 6,          # 회전 속도(%) — 팀 스테이지(stage3v2/stage4) 확정값 시드
    "node_confirm_ms": 120,   # 노드 후보 확정 시간(ms)
    "left_th_steer": 69,      # 후진 복구 line_found 감도
    "right_th_steer": 67,
    "node_advance_mm": 30,    # ★ 확정 후 재판정/회전 전 전진량
    "goal_advance_mm": 50,    # ★ 도착 시퀀스: 초록 후 추가 전진(=후진) 거리
    "turn_90_factor": 0.75,   # ★ 과/부족 시 0.05 단위 미세조정
    "turn_180_factor": 0.75,  # ★ 유턴도 같은 비율로 과회전 가감
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

SAVE_PATH = os.path.join(_ROOT, "config", "run_maze_v3.json")
STAGE_NAME = "run_maze_v3"

ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
]


# =====================================================================
# 판단층 (순수 — PC 테스트 가능): 경로 기억/접기/반전
# =====================================================================

# 이동 → 노드 통과 시 진행 방향 변화(도). U턴 상쇄 합성용.
_MOVE_ANGLE = {"L": 90, "S": 0, "R": 270, "U": 180}
_ANGLE_MOVE = {90: "L", 0: "S", 270: "R", 180: "U"}


def combine_moves(first, second):
    """[first, U, second] 를 한 이동으로 접는다(회전각 합성, mod 360).

    예: L,U,S → 90+180+0=270° → R. 같은 노드를 지나는 직행자가 했을 이동과 동일.
    """
    total = (_MOVE_ANGLE[first] + 180 + _MOVE_ANGLE[second]) % 360
    return _ANGLE_MOVE[total]


def push_move(path, move):
    """가는 길 이동 기록. [X, U, Z] 패턴이 생기면 즉시 접는다(연쇄 포함).

    path 를 제자리 갱신하고 그대로 반환한다. 접기가 연쇄되면(합성 결과가 또 U)
    계속 접는다 — path 에는 항상 U 없는 직행 경로만 남는다(맨 앞 U 예외:
    첫 노드 전 막다른길, 물리적으로 비정상 코스라 그대로 둔다).
    """
    path.append(move)
    while len(path) >= 3 and path[-2] == "U":
        second = path.pop()
        path.pop()                      # "U"
        first = path.pop()
        path.append(combine_moves(first, second))
        if path[-1] != "U":
            break
    return path


def invert_move(move):
    """복귀 방향에서 같은 노드를 지날 때 필요한 이동(좌우 반전, S/U 유지)."""
    if move == "L":
        return "R"
    if move == "R":
        return "L"
    return move


def return_move_available(move, bits, has_straight):
    """복귀 replay 안전장치: 반전된 이동이 현재 노드에서 물리적으로 가능한가.

    bits 는 노드 확정 시점의 (l, c, r), has_straight 는 전진 후 중앙 색 판정.
    U 는 항상 가능(제자리 회전)으로 본다.
    """
    if move == "L":
        return bits[0] == 1
    if move == "R":
        return bits[2] == 1
    if move == "S":
        return has_straight
    return True


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
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

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"action": None}
    plock = threading.Lock()

    state = {"visits": 0, "arrived": False, "done": False, "grabbed": False,
             "last_turn": None, "returning": False, "phase": "out"}
    path = []                        # 가는 길 이동 기록("L"/"R"/"S", U 는 접힘)
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
            pending["action"] = action
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

    def take_pending():
        with plock:
            action = pending["action"]
            pending["action"] = None
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
        _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)

    def advance(distance_mm, speed):
        def on_adv_tick():
            _publish(tele, params, started, mode="advancing", phase=state["phase"],
                     enc_avg=hw.enc_avg() * MM_PER_DEG)
        advance_straight(hw, distance_mm, speed,
                         _tick_stop(should_stop, on_adv_tick), should_pause)

    def goal_sequence():
        """도착 시퀀스: 정지 → 추가 전진 → 그리퍼 오픈(내려놓기) → 후진 → 유턴 →
        복귀(home) 단계 시작."""
        hw.stop()
        snap = params.snapshot()
        state["arrived"] = True
        log.log("NODE_IS_GOAL", "COLOR_GREEN", color=COL_GOAL)

        advance(snap["goal_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return
        hw.grip_open(snap["grip_speed"], GRIP_SEC)
        hw.beep_ok()
        advance(snap["goal_advance_mm"], -STRAIGHT_SPEED)   # 같은 거리 후진
        if should_stop():
            return
        do_turn("uturn")

        state["phase"] = "home"
        log.log("GOAL_RETURN_START", "PATH_MEMORY", path="".join(path),
                path_len=len(path), goal_advance_mm=snap["goal_advance_mm"])
        reset_steer()

    def handle_lost(bits):
        """000(선 유실) 처리 — v2 와 동일한 후진 복구. 복귀 중에도 같은 동작.

        유턴까지 가면 가는 길에는 "U" 를 기록하고(경로 접기), 복귀 중에는 경로
        replay 가 깨진 것이므로 RETURN_FALLBACK 로만 남긴다(best effort 지속).
        """
        snap = params.snapshot()
        retry_ok = ((time.monotonic() - lost["last_recover_t"]) * 1000
                    >= LOST_RETRY_WINDOW_MS)
        if retry_ok:
            log.log("LINE_LOST", "ALL_WHITE_BACKUP", bits=bits_to_str(bits),
                    backup_mm=LOST_BACKUP_MM, phase=state["phase"])

            def on_backup_tick():
                _publish(tele, params, started, mode="lost_backup", phase=state["phase"],
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
                    dist_mm=round(dist, 1), phase=state["phase"])
        else:
            log.log("DEAD_END", "LOST_AGAIN_AFTER_RECOVER", bits=bits_to_str(bits),
                    phase=state["phase"])
        do_turn("uturn")
        if state["phase"] == "out":
            push_move(path, "U")
            state["returning"] = True
        else:
            log.log("RETURN_FALLBACK", "DEAD_END_ON_RETURN", bits=bits_to_str(bits),
                    path_left=len(path))

    def handle_node_out(bits):
        """가는 길 노드 처리: v2 탐색 로직 + 이동 기록(push_move)."""
        hw.stop()

        if bits == (0, 0, 0):
            handle_lost(bits)
            return

        snap = params.snapshot()
        advance(snap["node_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if c == COL_GOAL:                # 전진했더니 도착 영역
            goal_sequence()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)
        n_options = int(has_left) + int(has_right) + int(has_straight)

        if n_options <= 1:
            # 커브 등 강제 이동: 선택이 아니므로 기억(last_turn/returning) 유지.
            # 경로에는 기록한다 — 복귀 때 같은 커브를 반대로 돈다.
            if has_left:
                log.log("NODE_CURVE", "FORCED_LEFT", bits=bits_to_str(bits), color=c)
                do_turn("turn_left")
                push_move(path, "L")
            elif has_right:
                log.log("NODE_CURVE", "FORCED_RIGHT", bits=bits_to_str(bits), color=c)
                do_turn("turn_right")
                push_move(path, "R")
            elif has_straight:
                log.log("NODE_CURVE", "FORCED_STRAIGHT", bits=bits_to_str(bits), color=c)
                push_move(path, "S")
            else:
                log.log("DEAD_END", "NO_EXIT_AFTER_ADVANCE", bits=bits_to_str(bits), color=c)
                do_turn("uturn")
                push_move(path, "U")
                state["returning"] = True
            return

        exclude = None
        if state["returning"] and state["last_turn"] is not None:
            exclude = OPPOSITE[state["last_turn"]]

        choice = choose_branch(has_left, has_right, has_straight, exclude)
        log.log("NODE_CHOICE", "PRIORITY_R_L_S", bits=bits_to_str(bits), color=c,
                has_left=has_left, has_right=has_right, has_straight=has_straight,
                exclude=exclude, returning=state["returning"], choice=choice)

        if choice == "L":
            do_turn("turn_left")
        elif choice == "R":
            do_turn("turn_right")
        elif choice == "U":
            do_turn("uturn")
        # "S" 는 그대로 직진(회전 없음)

        push_move(path, choice)
        if choice == "U":
            state["returning"] = True
        else:
            state["last_turn"] = choice
            state["returning"] = False

    def exec_return_move(move):
        if move == "L":
            do_turn("turn_left")
        elif move == "R":
            do_turn("turn_right")
        elif move == "U":
            do_turn("uturn")
        # "S" 는 그대로 직진

    def handle_node_home(bits):
        """복귀 노드 처리: 기록된 이동을 뒤에서부터 꺼내 좌우 반전해 실행."""
        hw.stop()

        if bits == (0, 0, 0):
            handle_lost(bits)
            return

        snap = params.snapshot()
        advance(snap["node_advance_mm"], STRAIGHT_SPEED)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if c == COL_YELLOW:              # 전진했더니 집(출발지)
            home_reached()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)

        if not path:
            log.log("RETURN_FALLBACK", "STACK_EMPTY", bits=bits_to_str(bits), color=c)
            choice = choose_branch(has_left, has_right, has_straight, None)
            exec_return_move(choice)
            return

        recorded = path.pop()
        inv = invert_move(recorded)
        if not return_move_available(inv, bits, has_straight):
            log.log("RETURN_FALLBACK", "PATH_MISMATCH", recorded=recorded,
                    inverted=inv, bits=bits_to_str(bits), color=c,
                    path_left=len(path))
            choice = choose_branch(has_left, has_right, has_straight, None)
            exec_return_move(choice)
            return

        log.log("RETURN_STEP", "PATH_MEMORY", recorded=recorded, inverted=inv,
                bits=bits_to_str(bits), color=c, path_left=len(path))
        exec_return_move(inv)

    def home_reached():
        hw.stop()
        state["done"] = True
        log.log("NODE_IS_HOME", "COLOR_YELLOW", color=COL_YELLOW,
                path_left=len(path))
        hw.beep_ok()
        hw.beep_ok()

    print("run_maze_v3 ready. waiting YELLOW on center sensor... "
          "(Ctrl-C or robotctl stop to quit)")

    # ---------- 출발 대기 ----------
    snap0 = params.snapshot()
    hw.grip_open(snap0["grip_speed"], GRIP_SEC)
    while hw.read_center_color_value() != COL_YELLOW:
        if stop_flag["on"]:
            hw.stop()
            log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
            server.stop()
            print("run_maze_v3 stopped before start.")
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

    # ---------- 메인 루프 (가는 길 + 복귀) ----------
    cand = None
    cand_t0 = 0.0
    last_node_t = time.monotonic()
    last_visit_t = 0.0
    last_follow_log = time.monotonic() - REASON_THROTTLE_S

    print("run_maze_v3 running. stop via 'robotctl stop' or Ctrl-C.")
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
                         phase=state["phase"], visits=state["visits"],
                         arrived=state["arrived"], last_turn=state["last_turn"],
                         returning=state["returning"], grabbed=state["grabbed"])
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            action = take_pending()
            if action is not None:
                handle_pending(action)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            snap = params.snapshot()
            now = time.monotonic()
            on_out = (state["phase"] == "out")

            # (1) 중앙 색상(상시 컬러모드) — 노드/마커 판정 전용
            c_color = hw.read_center_color_value()

            if on_out and c_color == COL_GOAL:
                goal_sequence()
                continue

            if (not on_out) and c_color == COL_YELLOW:
                home_reached()
                break

            # 방문 마커(빨강) 유턴은 가는 길에만. 복귀 중에는 무시(경로 replay 우선).
            if (on_out and c_color == COL_VISIT and
                    (now - last_visit_t) * 1000 >= COLOR_DEBOUNCE_MS):
                hw.stop()
                state["visits"] += 1
                log.log("VISIT_NODE", "RED_REVISIT", color=c_color, visits=state["visits"])
                do_turn("uturn")
                push_move(path, "U")
                state["returning"] = True
                last_visit_t = time.monotonic()
                cand = None
                reset_steer()
                continue

            # (2) 소스통 파지: 가는 길에만(복귀 중에는 이미 내려놓았다)
            if (on_out and (not state["grabbed"]) and
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

            # (4) 노드 후보 추적 (엄격 bits, confirm + debounce, 000 가드는 v2 동일)
            if nbits in CANDIDATES and not lost_candidate_blocked(
                    nbits, steer["last_turn"], LOST_GUARD_TURN):
                if cand != nbits:
                    cand = nbits
                    cand_t0 = now
                elif ((now - cand_t0) * 1000 >= snap["node_confirm_ms"] and
                      (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS):
                    if on_out:
                        handle_node_out(nbits)
                    else:
                        handle_node_home(nbits)
                    last_node_t = time.monotonic()
                    cand = None
                    reset_steer()
                    continue
            else:
                cand = None

            # (5) PD 조향 — 좌/우 반사광 raw 차이만(중앙은 안 쓴다). v2 동일.
            snap_eff = snap if nbits not in SLOW_ON else dict(snap, base_speed=SLOW_SPEED)
            left_speed, right_speed, err, _deriv, turn = pd.step((rl, 0, rr), snap_eff)
            hw.drive(left_speed, right_speed)
            steer["last_turn"] = turn

            if (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "PID", reflect_l=rl, reflect_r=rr,
                        bits=bits_to_str(nbits), error=err, turn=turn,
                        phase=state["phase"])
                last_follow_log = now

            _publish(tele, params, started, mode="follow", phase=state["phase"],
                     reflect_l=rl, reflect_r=rr,
                     color=c_color, bits=bits_to_str(nbits), error=err, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     visits=state["visits"], arrived=state["arrived"],
                     last_turn=state["last_turn"], returning=state["returning"],
                     grabbed=state["grabbed"], path_len=len(path))

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()

    print("done. visits={} arrived={} home={} path_left={}".format(
        state["visits"], state["arrived"], state["done"], len(path)))


if __name__ == "__main__":
    run()
