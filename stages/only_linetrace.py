#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3-sensor PD line tracing with encoder based turns.

Run on EV3:
    python3 stages/stage1_linetrace.py

This is intentionally small and practical:
- 3 reflected-light sensors: in1/in2/in3 = left/center/right.
- Black/white threshold is 40 by default.
- PD control only. kd is kept as a variable, but defaults to 0.0.
- If a left branch/intersection is confirmed, turn left by encoder degrees.

Python 3.5 compatible: no f-strings.
"""

import os
import sys
import time
import threading


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib.shared_params import SharedParams
from lib.telemetry import Telemetry
from lib.tuning_server import TuningServer


# Drive ports from docs/HARDWARE.md.
LEFT_MOTOR_PORT = "outA"
RIGHT_MOTOR_PORT = "outB"

LEFT_SENSOR_PORT = "in1"
CENTER_SENSOR_PORT = "in2"
RIGHT_SENSOR_PORT = "in3"

# Stage 2 values from the saved calibration photo.
TURN_SPEED = 18
TURN_90_FACTOR = 0.9
TURN_180_FACTOR = 0.8
POST_TURN_SETTLE_MS = 120

# Geometric first guess for a common EV3 chassis:
# 90 * wheel_track_mm / wheel_diameter_mm ~= 90 * 120 / 56 ~= 193.
BASE_PIVOT_DEG_90 = 193.0
BASE_PIVOT_DEG_180 = BASE_PIVOT_DEG_90 * 2.0

INITIAL_PARAMS = {
    "kp": 0.60,
    "kd": 0.0,
    "base_speed": 22,
    "turn_limit": 35,
    "target_reflect": 40,
    "thr_left": 40,
    "thr_center": 40,
    "thr_right": 40,
    "turn_speed": TURN_SPEED,
    "turn_90_factor": TURN_90_FACTOR,
    "turn_180_factor": TURN_180_FACTOR,
    "post_turn_settle_ms": POST_TURN_SETTLE_MS,
    "branch_confirm_count": 4,
    "branch_cooldown_ms": 700,
    "loop_delay_ms": 15,
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "kd": (0.0, 1.0),
    "base_speed": (5, 45),
    "turn_limit": (5, 60),
    "target_reflect": (0, 100),
    "thr_left": (0, 100),
    "thr_center": (0, 100),
    "thr_right": (0, 100),
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "turn_180_factor": (0.5, 2.0),
    "post_turn_settle_ms": (0, 400),
    "branch_confirm_count": (1, 20),
    "branch_cooldown_ms": (0, 3000),
    "loop_delay_ms": (5, 50),
}

MAX_STEP = {
    "kp": 0.1,
    "kd": 0.05,
    "base_speed": 5,
    "turn_limit": 10,
    "target_reflect": 5,
    "thr_left": 3,
    "thr_center": 3,
    "thr_right": 3,
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "post_turn_settle_ms": 40,
    "branch_confirm_count": 2,
    "branch_cooldown_ms": 100,
    "loop_delay_ms": 5,
}

UI_STEP = {
    "kp": 0.01,
    "kd": 0.01,
    "base_speed": 1,
    "turn_limit": 1,
    "target_reflect": 1,
    "thr_left": 1,
    "thr_center": 1,
    "thr_right": 1,
    "turn_speed": 1,
    "turn_90_factor": 0.01,
    "turn_180_factor": 0.01,
    "post_turn_settle_ms": 10,
    "branch_confirm_count": 1,
    "branch_cooldown_ms": 50,
    "loop_delay_ms": 1,
}

UNITS = {
    "base_speed": "%",
    "turn_limit": "%",
    "target_reflect": "%",
    "thr_left": "%",
    "thr_center": "%",
    "thr_right": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "post_turn_settle_ms": "ms",
    "branch_cooldown_ms": "ms",
    "loop_delay_ms": "ms",
}

PARAM_ORDER = [
    "kp",
    "kd",
    "base_speed",
    "turn_limit",
    "target_reflect",
    "thr_left",
    "thr_center",
    "thr_right",
    "turn_speed",
    "turn_90_factor",
    "turn_180_factor",
    "post_turn_settle_ms",
    "branch_confirm_count",
    "branch_cooldown_ms",
    "loop_delay_ms",
]

SAVE_PATH = os.path.join(ROOT, "config", "stage1_linetrace.json")


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def now_ms():
    return int(time.time() * 1000)


def bits_to_str(bits):
    return "".join(["1" if item else "0" for item in bits])


def black_bits(raw, params):
    thresholds = (params["thr_left"], params["thr_center"], params["thr_right"])
    return tuple([1 if raw[i] < thresholds[i] else 0 for i in range(3)])


def is_left_branch(bits):
    # Left branch or intersection. Plain left-only drift (100) is not enough.
    return bits == (1, 1, 0) or bits == (1, 1, 1)


def encoder_target(action, params):
    if action == "uturn":
        return BASE_PIVOT_DEG_180 * params["turn_180_factor"]
    return BASE_PIVOT_DEG_90 * params["turn_90_factor"]


def wheel_dirs(action):
    if action == "turn_left":
        return (-1, 1)
    if action == "turn_right":
        return (1, -1)
    if action == "uturn":
        return (1, -1)
    raise ValueError("unknown turn action: {}".format(action))


class PdController(object):
    def __init__(self):
        self.prev_error = 0.0
        self.prev_t = None

    def reset(self):
        self.prev_error = 0.0
        self.prev_t = None

    def step(self, raw, params):
        # Error convention:
        # left sensor black -> left reflect low, right reflect high -> positive error.
        # Positive turn slows left wheel and speeds right wheel, so the robot turns left.
        error = float(raw[2] - raw[0])
        t = time.time()
        if self.prev_t is None:
            dt = 0.001
            derivative = 0.0
        else:
            dt = t - self.prev_t
            if dt <= 0:
                dt = 0.001
            derivative = (error - self.prev_error) / dt

        turn = params["kp"] * error + params["kd"] * derivative
        turn = clamp(turn, -params["turn_limit"], params["turn_limit"])

        left_speed = params["base_speed"] - turn
        right_speed = params["base_speed"] + turn
        left_speed = clamp(left_speed, -100, 100)
        right_speed = clamp(right_speed, -100, 100)

        self.prev_error = error
        self.prev_t = t
        return left_speed, right_speed, error, derivative, turn


class Ev3Hardware(object):
    def __init__(self):
        from ev3dev2.motor import LargeMotor, SpeedPercent
        from ev3dev2.sensor.lego import ColorSensor

        self._speed_percent = SpeedPercent
        self.left_motor = LargeMotor(LEFT_MOTOR_PORT)
        self.right_motor = LargeMotor(RIGHT_MOTOR_PORT)
        self.left_sensor = ColorSensor(LEFT_SENSOR_PORT)
        self.center_sensor = ColorSensor(CENTER_SENSOR_PORT)
        self.right_sensor = ColorSensor(RIGHT_SENSOR_PORT)

    def read_reflect(self):
        return (
            self.left_sensor.reflected_light_intensity,
            self.center_sensor.reflected_light_intensity,
            self.right_sensor.reflected_light_intensity,
        )

    def drive(self, left_speed, right_speed):
        self.left_motor.on(self._speed_percent(left_speed))
        self.right_motor.on(self._speed_percent(right_speed))

    def stop(self):
        self.left_motor.off(brake=True)
        self.right_motor.off(brake=True)

    def reset_encoders(self):
        try:
            self.left_motor.position = 0
            self.right_motor.position = 0
        except Exception:
            # Some ev3dev2 setups prefer reset(); keep both paths available.
            self.left_motor.reset()
            self.right_motor.reset()

    def read_encoders(self):
        return self.left_motor.position, self.right_motor.position

    def enc_avg(self):
        left, right = self.read_encoders()
        return (abs(left) + abs(right)) / 2.0


def run_encoder_turn(hw, action, params, telemetry, stop_event):
    target = encoder_target(action, params)
    left_dir, right_dir = wheel_dirs(action)
    speed = params["turn_speed"]
    started = now_ms()

    hw.reset_encoders()
    hw.drive(left_dir * speed, right_dir * speed)
    try:
        while not stop_event.is_set():
            enc_l, enc_r = hw.read_encoders()
            enc_avg = (abs(enc_l) + abs(enc_r)) / 2.0
            telemetry.publish({
                "mode": action,
                "turning": True,
                "target_deg": target,
                "enc_l": enc_l,
                "enc_r": enc_r,
                "enc_avg": enc_avg,
            })
            if enc_avg >= target:
                break
            time.sleep(0.005)
    finally:
        hw.stop()

    settle_ms = params["post_turn_settle_ms"]
    if settle_ms > 0:
        time.sleep(settle_ms / 1000.0)

    enc_l, enc_r = hw.read_encoders()
    enc_avg = (abs(enc_l) + abs(enc_r)) / 2.0
    telemetry.publish({
        "mode": action,
        "turning": False,
        "target_deg": target,
        "enc_l": enc_l,
        "enc_r": enc_r,
        "enc_avg": enc_avg,
        "elapsed_ms": now_ms() - started,
    })
    return enc_avg


def main():
    params = SharedParams(
        INITIAL_PARAMS,
        PARAM_LIMITS,
        MAX_STEP,
        SAVE_PATH,
        UI_STEP,
        UNITS,
        PARAM_ORDER,
    )
    params.load_saved_into_defaults()

    telemetry = Telemetry()
    stop_event = threading.Event()
    hw = Ev3Hardware()
    pd = PdController()
    started = now_ms()
    branch_seen = 0
    last_branch_turn_ms = -999999

    def stop_handler(source):
        stop_event.set()

    def do_handler(action, args):
        snap = params.snapshot()
        if action in ("turn_left", "turn_right", "uturn"):
            actual = run_encoder_turn(hw, action, snap, telemetry, stop_event)
            pd.reset()
            return {"action": action, "enc_avg": actual}
        return {"error": "unknown action: {}".format(action)}

    server = TuningServer(
        params,
        telemetry,
        do_handler=do_handler,
        stop_handler=stop_handler,
        actions=[
            {"name": "turn_left", "label": "Turn Left"},
            {"name": "turn_right", "label": "Turn Right"},
            {"name": "uturn", "label": "U-Turn"},
        ],
        stage="stage1_linetrace_pd",
    )
    server.start()

    print("stage1 linetrace PD start")
    print("threshold=40, kd=0.0, turn factors: 90={}, 180={}".format(
        TURN_90_FACTOR, TURN_180_FACTOR
    ))

    try:
        while not stop_event.is_set():
            snap = params.snapshot()
            raw = hw.read_reflect()
            bits = black_bits(raw, snap)
            bits_str = bits_to_str(bits)
            t_ms = now_ms()

            in_cooldown = (t_ms - last_branch_turn_ms) < snap["branch_cooldown_ms"]
            if is_left_branch(bits) and not in_cooldown:
                branch_seen += 1
            else:
                branch_seen = 0

            if branch_seen >= int(snap["branch_confirm_count"]):
                hw.stop()
                telemetry.publish({
                    "mode": "branch_left",
                    "reason": "LEFT_BRANCH",
                    "reflect": raw,
                    "bits": bits_str,
                    "branch_seen": branch_seen,
                })
                run_encoder_turn(hw, "turn_left", snap, telemetry, stop_event)
                pd.reset()
                branch_seen = 0
                last_branch_turn_ms = now_ms()
                continue

            left_speed, right_speed, error, derivative, turn = pd.step(raw, snap)

            # If all sensors see white, keep the previous steering hint but slow down.
            if bits == (0, 0, 0):
                left_speed *= 0.55
                right_speed *= 0.55

            hw.drive(left_speed, right_speed)
            telemetry.publish({
                "t_ms": t_ms - started,
                "mode": "follow",
                "reflect": raw,
                "bits": bits_str,
                "error": error,
                "derivative": derivative,
                "turn": turn,
                "left_speed": left_speed,
                "right_speed": right_speed,
                "branch_seen": branch_seen,
                "param_rev": params.rev(),
            })
            time.sleep(snap["loop_delay_ms"] / 1000.0)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        hw.stop()
        server.stop()
        print("stage1 linetrace PD stopped")


if __name__ == "__main__":
    main()
