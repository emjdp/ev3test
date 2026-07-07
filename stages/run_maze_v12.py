#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v12.py — v5(reset) 기반 안정화 실험판.

v12 변경점(2026-07-07, 사용자 요청):
  - v5 의 대시보드 reset 세션 구조는 유지한다.
  - v11 의 안정화 아이디어를 v5 기준으로 다시 반영한다:
    PD 조향(D=0.05), 브랜치 후보에서 PD off + 저속 직진 + 정지 재판정,
    빨강/노랑/초록 마커 즉시 정지+U턴+부저 2회.
  - 기본값은 base_speed=16, kp=0.17, turn_speed=6, node_confirm_ms=80,
    left_th_steer=66, right_th_steer=63, node_advance_mm=40, goal_advance_mm=20,
    turn_90_factor=0.66, turn_180_factor=0.71, grab_dist_cm=6, grip_speed=50,
    left_th_node=18, right_th_node=14.

아래 v5 설명은 reset 세션 구조의 원래 의도를 남긴 것이다.

run_maze_v5.py — v4(전 노드 방문 + 최단경로 복귀) + 대시보드 리셋(시작모드 복귀).

v4(run_maze_v4.py, 유지)와의 유일한 차이 — 사용자 요청(2026-07-07):
  대시보드에 **reset 액션**을 추가한다. 실행 중(탐색/복귀) 어느 시점이든, 또는
  완주해 멈춘 뒤든, 대시보드/robotctl 에서 reset 을 누르면 로봇이 정지하고 모든
  탐색 상태(지도/방문/경로/heading)를 버린 뒤 **다시 노랑에서 출발을 기다리는
  시작모드**로 돌아간다. 코스를 다시 깔거나 로봇을 출발점에 놓고 재시작할 때,
  프로그램을 껐다 켜지 않고 대시보드만으로 처음부터 다시 돌릴 수 있다.

구현: run() 을 **세션 루프**로 감쌌다.
  session = (출발 대기 → 탐색 → 복귀 → 완주 후 대기).
  reset 은 stop 처럼 플래그(네트워크 thread 가 세팅, 제어 루프가 안전한 시점에 소비)
  로, 감지하면 현재 세션을 접고 new_session() 으로 상태를 초기화한 뒤 새 세션을
  시작한다. stop(비상정지)만 프로그램을 끝내고, reset 은 프로그램을 살린 채 처음으로.
  완주(집 도착) 후에는 자동 재시작하지 않고(그 자리 노랑에서 무한 재시작 방지)
  reset 을 기다리는 idle 상태로 들어간다.

v12 는 v4 탐색 상태머신과 v5 reset 세션 루프를 유지하되, 주행/노드 후보/마커 처리만
별도 안정화한다. 라이브 params 는 v12 전용이며 좌/우 노드 임계값을 포함한다.

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C,
      재시작은 네트워크 reset(robotctl do reset / 대시보드 액션).

독립 실행(브릭):  python3 stages/run_maze_v12.py
문법 점검(PC):    python3 -m py_compile stages/run_maze_v12.py lib/*.py
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
# v2 확정 코드 재사용(미수정): 000 가드 + 라이브 turn_speed 회전 + 마커 색.
from stages.run_maze_v2 import (                                     # noqa: E402
    lost_candidate_blocked, LOST_GUARD_TURN, _run_turn,
    COL_VISIT, COL_GOAL,
)
# v4 탐색 판단층만 재사용(미수정) — v12 params 는 이 파일에서 별도 정의한다.
from stages.run_maze_v4 import (                                     # noqa: E402
    Explorer, PRIORITY,
)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# v12 라이브 params — v5(reset) + v11 안정화값.
# =====================================================================

INITIAL_PARAMS = {
    "base_speed": 16,
    "kp": 0.17,
    "turn_speed": 6,
    "node_confirm_ms": 80,
    "left_th_steer": 66,
    "right_th_steer": 63,
    "left_th_node": 18,
    "right_th_node": 14,
    "node_advance_mm": 40,
    "goal_advance_mm": 20,
    "turn_90_factor": 0.66,
    "turn_180_factor": 0.71,
    "grab_dist_cm": 6.0,
    "grip_speed": 50,
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "kp": (0.0, 3.0),
    "turn_speed": (5, 40),
    "node_confirm_ms": (0, 1000),
    "left_th_steer": (0, 100),
    "right_th_steer": (0, 100),
    "left_th_node": (0, 100),
    "right_th_node": (0, 100),
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
    "left_th_node": 3,
    "right_th_node": 3,
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
    "left_th_node": 1,
    "right_th_node": 1,
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
    "left_th_node": "%",
    "right_th_node": "%",
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
    "left_th_node", "right_th_node",
    "node_advance_mm", "goal_advance_mm",
    "turn_90_factor", "turn_180_factor",
    "grab_dist_cm", "grip_speed",
]

SAVE_PATH = os.path.join(_ROOT, "config", "run_maze_v12.json")
STAGE_NAME = "run_maze_v12"

# 대시보드 액션 — v4 의 read_color/read_reflect 에 reset 추가.
ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
    {"name": "reset", "label": "Reset to Start (wait YELLOW)"},
]

PD_KD = 0.05
PD_TURN_LIMIT = 16
PD_D_EMA_ALPHA = 0.35
PD_DERIV_LIMIT = 220.0

NODE_CONFIRM_SPEED = 7
NODE_CONFIRM_SETTLE_S = 0.08
MARKER_PAUSE_S = 0.08

MARKER_COLORS = (COL_VISIT, COL_GOAL, COL_YELLOW)
MARKER_NAMES = {
    COL_VISIT: "red",
    COL_GOAL: "green",
    COL_YELLOW: "yellow",
}


def clamp_value(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


class V12PdController(object):
    """좌/우 raw 반사광 기반 PD. D=0.05, derivative는 EMA/상한으로 완화한다."""

    def __init__(self):
        self.prev_error = 0.0
        self.prev_t = None
        self.prev_derivative = 0.0

    def reset(self):
        self.prev_error = 0.0
        self.prev_t = None
        self.prev_derivative = 0.0

    def step(self, raw, params):
        error = float(raw[2] - raw[0])
        t = time.monotonic()
        if self.prev_t is None:
            derivative = 0.0
        else:
            dt = t - self.prev_t
            if dt <= 0:
                dt = 0.001
            derivative = (error - self.prev_error) / dt
            derivative = clamp_value(derivative, -PD_DERIV_LIMIT, PD_DERIV_LIMIT)
            derivative = (PD_D_EMA_ALPHA * derivative +
                          (1.0 - PD_D_EMA_ALPHA) * self.prev_derivative)

        turn = params["kp"] * error + PD_KD * derivative
        turn = clamp_value(turn, -PD_TURN_LIMIT, PD_TURN_LIMIT)

        left_speed = clamp_value(params["base_speed"] - turn, -100, 100)
        right_speed = clamp_value(params["base_speed"] + turn, -100, 100)

        self.prev_error = error
        self.prev_t = t
        self.prev_derivative = derivative
        return left_speed, right_speed, error, derivative, turn


def attach_v12_hardware(hw):
    """run_maze_v5 계열이 기대하는 gripper/ultrasonic 별칭을 v12 안에서만 보강."""
    if not hasattr(hw, "read_center_color_value"):
        if hasattr(hw, "read_center_color_now"):
            hw.read_center_color_value = hw.read_center_color_now
        else:
            hw.read_center_color_value = lambda: hw.read_center_color(0, 0)

    need_grip = (not hasattr(hw, "grip_open")) or (not hasattr(hw, "grip_close"))
    if need_grip:
        from ev3dev2.motor import MediumMotor, SpeedPercent
        grip_motor = MediumMotor("outC")

        def grip_open(speed, seconds):
            grip_motor.on_for_seconds(SpeedPercent(speed), seconds, brake=False)

        def grip_close(speed, seconds):
            grip_motor.on_for_seconds(SpeedPercent(-speed), seconds, brake=True)

        hw.grip_open = grip_open
        hw.grip_close = grip_close

    if not hasattr(hw, "read_distance_cm"):
        from ev3dev2.sensor.lego import UltrasonicSensor
        ultrasonic = UltrasonicSensor("in4")

        def read_distance_cm():
            return ultrasonic.distance_centimeters

        hw.read_distance_cm = read_distance_cm


# =====================================================================
# 판단층(순수) — 세션 상태 초기화 값. reset/시작 시 이 값으로 되돌린다.
# =====================================================================

def fresh_session_state():
    """한 세션(출발→탐색→복귀→완주)의 가변 상태 초기값."""
    return {"visits": 0, "goal_seen": False, "done": False, "grabbed": False}


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run(). v4 뼈대 + 세션 루프 + reset.
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    attach_v12_hardware(hw)
    pd = V12PdController()
    ex = Explorer()                       # 세션마다 new_session 에서 새로 만든다

    stop_flag = {"on": False, "source": None}
    reset_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending_do = {"action": None}
    plock = threading.Lock()

    state = fresh_session_state()
    lost = {"last_recover_t": -1e9}
    steer = {"last_turn": 0.0}
    marker = {"last_t": -1e9}

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
            # stop 처럼 즉시 플래그만 세팅(제어 루프가 안전한 시점에 소비).
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

    def read_node_bits(snap):
        color = hw.read_center_color_value()
        rl = hw.read_left_reflect()
        rr = hw.read_right_reflect()
        bits = bits_node(rl, color, rr, snap["left_th_node"], snap["right_th_node"])
        return bits, color, rl, rr

    def handle_marker_color(color, context):
        """빨강/초록/노랑 마커는 주행/후보확정보다 우선해 즉시 정지+U턴한다."""
        if color not in MARKER_COLORS:
            return False
        now = time.monotonic()
        if (now - marker["last_t"]) * 1000 < COLOR_DEBOUNCE_MS:
            return False

        hw.stop()
        time.sleep(MARKER_PAUSE_S)
        name = MARKER_NAMES.get(color, "unknown")
        if color == COL_VISIT:
            state["visits"] += 1
        elif color == COL_GOAL:
            state["goal_seen"] = True

        log.log("MARKER_UTURN", "COLOR_{}_IMMEDIATE".format(name.upper()),
                color=color, context=context, phase=phase(),
                visits=state["visits"], mode=ex.mode, session=session_no["n"])
        do_turn("uturn")     # _run_turn 이 회전 완료음 1회를 낸다.
        hw.beep_ok()         # 총 2회 부저가 되도록 1회 추가.

        if ex.mode == "PROBE":
            log_events(ex.on_probe_end(name))
        else:
            log.log("MARKER_UTURN", "NO_PROBE_STATE_UPDATE",
                    color=color, marker=name, mode=ex.mode,
                    session=session_no["n"])

        marker["last_t"] = time.monotonic()
        reset_steer()
        return True

    def confirm_node_slow(first_bits, snap):
        """후보 지점에서 PD를 끄고 저속 직진 후 정지 상태에서 bits를 확정한다."""
        reset_steer()
        start = time.monotonic()
        confirm_s = max(0, snap["node_confirm_ms"]) / 1000.0
        last_bits = first_bits
        log.log("NODE_CANDIDATE", "PD_OFF_SLOW_STRAIGHT",
                bits=bits_to_str(first_bits), confirm_ms=snap["node_confirm_ms"],
                speed=NODE_CONFIRM_SPEED, phase=phase(), session=session_no["n"])

        while (time.monotonic() - start) < confirm_s:
            if should_stop():
                hw.stop()
                return None
            if reset_flag["on"]:
                hw.stop()
                return "reset"
            if should_pause():
                hw.stop()
                _publish(tele, params, started, mode="node_confirm_paused",
                         phase=phase(), session=session_no["n"])
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            bits, color, rl, rr = read_node_bits(snap)
            if handle_marker_color(color, "node_confirm"):
                return "marker"
            if bits not in CANDIDATES:
                hw.stop()
                log.log("NODE_CANDIDATE", "CANCELLED_DURING_SLOW_CONFIRM",
                        first_bits=bits_to_str(first_bits), bits=bits_to_str(bits),
                        reflect_l=rl, reflect_r=rr, color=color,
                        session=session_no["n"])
                return None

            last_bits = bits
            hw.drive(NODE_CONFIRM_SPEED, NODE_CONFIRM_SPEED)
            _publish(tele, params, started, mode="node_confirm_slow",
                     phase=phase(), reflect_l=rl, reflect_r=rr,
                     color=color, bits=bits_to_str(bits), session=session_no["n"])
            time.sleep(LOOP_DELAY_MS / 1000.0)

        hw.stop()
        time.sleep(NODE_CONFIRM_SETTLE_S)
        bits, color, rl, rr = read_node_bits(snap)
        if handle_marker_color(color, "node_confirm_stop"):
            return "marker"
        if bits in CANDIDATES:
            log.log("NODE_CONFIRMED", "SLOW_STRAIGHT_STOP",
                    first_bits=bits_to_str(first_bits),
                    last_bits=bits_to_str(last_bits),
                    bits=bits_to_str(bits), reflect_l=rl, reflect_r=rr,
                    color=color, settle_s=NODE_CONFIRM_SETTLE_S,
                    session=session_no["n"])
            return bits

        log.log("NODE_CANDIDATE", "CANCELLED_AT_STOP",
                first_bits=bits_to_str(first_bits), bits=bits_to_str(bits),
                reflect_l=rl, reflect_r=rr, color=color,
                session=session_no["n"])
        return None

    def goal_sequence():
        """도착 시퀀스(v4/v3 순서 그대로): 전진 → 그리퍼 오픈 → 후진 → 유턴."""
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
        """000(선 유실) — v4 과 동일한 후진 복구. 유턴까지 가면 상태머신에 통지."""
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
            log.log("RETURN_FALLBACK", "DEAD_END_ON_TRANSIT", mode=ex.mode,
                    bits=bits_to_str(bits))

    def handle_node(bits):
        """분기/커브 처리(가는 길·복귀 공용). v4 와 동일."""
        hw.stop()

        if bits == (0, 0, 0):
            handle_lost(bits)
            return

        snap = params.snapshot()
        advance(snap["node_advance_mm"], NODE_CONFIRM_SPEED)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if handle_marker_color(c, "after_node_advance"):
            return
        if ex.mode != "HOME" and c == COL_GOAL:
            goal_sequence()
            return
        if ex.mode == "HOME" and c == COL_YELLOW:
            home_reached()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)
        n_options = int(has_left) + int(has_right) + int(has_straight)

        if n_options <= 1:
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

    # ---- 세션 초기화 (시작/reset 공용) ----
    session_no = {"n": 0}

    def new_session():
        """탐색 상태를 전부 버리고 새 세션을 준비한다(시작/reset 공용)."""
        # ex 를 새 Explorer 로 교체 — 헬퍼 클로저들은 run() 의 ex 셀을 읽으므로
        # nonlocal 재할당으로 전부 새 지도를 보게 된다.
        nonlocal ex
        ex = Explorer()
        state.clear()
        state.update(fresh_session_state())
        lost["last_recover_t"] = -1e9
        marker["last_t"] = -1e9
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
                return "stop"
            if take_reset():
                return "reset"
            action = take_pending()
            if action is not None:
                handle_pending(action)
            _publish(tele, params, started, mode="waiting_start",
                     session=session_no["n"])
            time.sleep(0.05)
        hw.beep_ok()
        log.log("NODE_IS_START", "COLOR_YELLOW", color=COL_YELLOW)
        advance_straight(hw, START_EXIT_MM, STRAIGHT_SPEED, should_stop, should_pause)
        marker["last_t"] = time.monotonic()
        reset_steer()
        return "go"

    # ---- 탐색+복귀 루프 — 반환 status(stop/reset/done) ----
    def explore():
        last_node_t = time.monotonic()
        last_follow_log = time.monotonic() - REASON_THROTTLE_S

        while not state["done"]:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                return "stop"
            if take_reset():
                return "reset"

            if pause_state["paused"]:
                hw.stop()
                reset_steer()
                _publish(tele, params, started, mode="paused", paused=True,
                         phase=phase(), visits=state["visits"],
                         work_id=ex.work_id, nodes=len(ex.map.nodes),
                         pending_total=ex.map.pending_total(),
                         grabbed=state["grabbed"], session=session_no["n"])
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

            c_color = hw.read_center_color_value()

            if handle_marker_color(c_color, "loop"):
                continue

            if ((not on_home) and (not state["grabbed"]) and
                    hw.read_distance_cm() < snap["grab_dist_cm"]):
                hw.stop()
                hw.grip_close(snap["grip_speed"], GRIP_SEC)
                state["grabbed"] = True
                log.log("GRAB", "ULTRASONIC_NEAR", grab_dist_cm=snap["grab_dist_cm"],
                        grip_speed=snap["grip_speed"])
                hw.beep_ok()
                reset_steer()

            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            nbits = bits_node(rl, c_color, rr, snap["left_th_node"], snap["right_th_node"])

            if nbits in CANDIDATES and not lost_candidate_blocked(
                    nbits, steer["last_turn"], LOST_GUARD_TURN):
                if (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS:
                    confirmed = confirm_node_slow(nbits, snap)
                    last_node_t = time.monotonic()
                    reset_steer()
                    if confirmed == "reset":
                        return "reset"
                    if confirmed == "marker":
                        continue
                    if confirmed is not None:
                        handle_node(confirmed)
                    continue

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
                     plan_left=len(ex.plan), grabbed=state["grabbed"],
                     session=session_no["n"])

            time.sleep(LOOP_DELAY_MS / 1000.0)
        return "done"

    # ---- 완주 후 대기 — reset 을 눌러야 다음 세션. (그 자리 노랑 무한 재시작 방지) ----
    def idle_after_done():
        hw.stop()
        while True:
            if stop_flag["on"]:
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                return "stop"
            if take_reset():
                return "reset"
            action = take_pending()
            if action is not None:
                handle_pending(action)
            _publish(tele, params, started, mode="finished",
                     visits=state["visits"], nodes=len(ex.map.nodes),
                     session=session_no["n"])
            time.sleep(0.05)

    print("run_maze_v12 ready. dashboard 'reset' returns to YELLOW start any time. "
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
    finally:
        try:
            hw.stop()
        finally:
            server.stop()

    print("run_maze_v12 stopped. sessions={}".format(session_no["n"]))


if __name__ == "__main__":
    run()
