#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 color marker detection on top of the tuned 3-sensor line tracer.

Run on EV3:
    python3 stages/stage4_color.py

This file intentionally does not modify Stage 1/3 line tracing. It follows the
same line-tracing behavior, then adds this Stage 4 experiment:

1. While following the line, watch the center reflected-light value.
2. If it stays in the candidate range for at least marker_stable_ms, stop.
3. Sample the marker at rest, read the center color code, and also record the
   reflected-light average for later calibration.
4. If brown/purple is recognized, beep immediately.

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


LEFT_MOTOR_PORT = "outA"
RIGHT_MOTOR_PORT = "outB"

LEFT_SENSOR_PORT = "in1"
CENTER_SENSOR_PORT = "in2"
RIGHT_SENSOR_PORT = "in3"

TURN_SPEED = 18
TURN_90_FACTOR = 0.9
TURN_180_FACTOR = 0.8
POST_TURN_SETTLE_MS = 120

BASE_PIVOT_DEG_90 = 193.0
BASE_PIVOT_DEG_180 = BASE_PIVOT_DEG_90 * 2.0

COLOR_NONE = 0
COLOR_BLACK = 1
COLOR_BLUE = 2
COLOR_GREEN = 3
COLOR_YELLOW = 4
COLOR_RED = 5
COLOR_WHITE = 6
COLOR_BROWN = 7

INITIAL_PARAMS = {
    "kp": 0.60,
    "kd": 0.0,
    "base_speed": 22,
    "turn_limit": 35,
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
    # Purple was measured near 26 and brown near 32. The candidate window is
    # intentionally narrow so the color-mode read only happens around markers.
    "marker_candidate_min": 23,
    "marker_candidate_max": 35,
    "marker_stable_ms": 50,
    "marker_cooldown_ms": 1000,
    "marker_sample_count": 7,
    "marker_sample_delay_ms": 10,
    "color_mode_settle_ms": 80,
    "color_dummy_reads": 2,
    "purple_reflect_min": 23,
    "purple_reflect_max": 29,
    "brown_reflect_min": 29,
    "brown_reflect_max": 35,
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "kd": (0.0, 1.0),
    "base_speed": (5, 45),
    "turn_limit": (5, 60),
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
    "marker_candidate_min": (0, 100),
    "marker_candidate_max": (0, 100),
    "marker_stable_ms": (10, 1000),
    "marker_cooldown_ms": (0, 5000),
    "marker_sample_count": (1, 30),
    "marker_sample_delay_ms": (0, 100),
    "color_mode_settle_ms": (0, 500),
    "color_dummy_reads": (0, 10),
    "purple_reflect_min": (0, 100),
    "purple_reflect_max": (0, 100),
    "brown_reflect_min": (0, 100),
    "brown_reflect_max": (0, 100),
}

MAX_STEP = {
    "kp": 0.1,
    "kd": 0.05,
    "base_speed": 5,
    "turn_limit": 10,
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
    "marker_candidate_min": 5,
    "marker_candidate_max": 5,
    "marker_stable_ms": 20,
    "marker_cooldown_ms": 200,
    "marker_sample_count": 2,
    "marker_sample_delay_ms": 10,
    "color_mode_settle_ms": 20,
    "color_dummy_reads": 1,
    "purple_reflect_min": 5,
    "purple_reflect_max": 5,
    "brown_reflect_min": 5,
    "brown_reflect_max": 5,
}

UI_STEP = {
    "kp": 0.01,
    "kd": 0.01,
    "base_speed": 1,
    "turn_limit": 1,
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
    "marker_candidate_min": 1,
    "marker_candidate_max": 1,
    "marker_stable_ms": 10,
    "marker_cooldown_ms": 50,
    "marker_sample_count": 1,
    "marker_sample_delay_ms": 5,
    "color_mode_settle_ms": 10,
    "color_dummy_reads": 1,
    "purple_reflect_min": 1,
    "purple_reflect_max": 1,
    "brown_reflect_min": 1,
    "brown_reflect_max": 1,
}

UNITS = {
    "base_speed": "%",
    "turn_limit": "%",
    "thr_left": "%",
    "thr_center": "%",
    "thr_right": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "post_turn_settle_ms": "ms",
    "branch_cooldown_ms": "ms",
    "loop_delay_ms": "ms",
    "marker_candidate_min": "%",
    "marker_candidate_max": "%",
    "marker_stable_ms": "ms",
    "marker_cooldown_ms": "ms",
    "marker_sample_delay_ms": "ms",
    "color_mode_settle_ms": "ms",
    "purple_reflect_min": "%",
    "purple_reflect_max": "%",
    "brown_reflect_min": "%",
    "brown_reflect_max": "%",
}

PARAM_ORDER = [
    "kp", "kd", "base_speed", "turn_limit",
    "thr_left", "thr_center", "thr_right",
    "turn_speed", "turn_90_factor", "turn_180_factor",
    "post_turn_settle_ms", "branch_confirm_count", "branch_cooldown_ms",
    "loop_delay_ms", "marker_candidate_min", "marker_candidate_max",
    "marker_stable_ms", "marker_cooldown_ms", "marker_sample_count",
    "marker_sample_delay_ms", "color_mode_settle_ms", "color_dummy_reads",
    "purple_reflect_min", "purple_reflect_max",
    "brown_reflect_min", "brown_reflect_max",
]

SAVE_PATH = os.path.join(ROOT, "config", "stage4_color.json")


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


def marker_candidate(center_reflect, params):
    lo = params["marker_candidate_min"]
    hi = params["marker_candidate_max"]
    if lo >= hi:
        return False
    return center_reflect >= lo and center_reflect < hi


class MarkerCandidateTracker(object):
    def __init__(self):
        self.since_ms = None
        self.confirmed_inside = False

    def reset(self):
        self.since_ms = None
        self.confirmed_inside = False

    def push(self, center_reflect, t_ms, params):
        if not marker_candidate(center_reflect, params):
            self.reset()
            return False, 0

        if self.since_ms is None:
            self.since_ms = t_ms
            elapsed = 0
        else:
            elapsed = t_ms - self.since_ms

        if self.confirmed_inside:
            return False, elapsed

        if elapsed >= int(params["marker_stable_ms"]):
            self.confirmed_inside = True
            return True, elapsed
        return False, elapsed


def _range_hit(value, lo, hi):
    return lo < hi and value >= lo and value < hi


def classify_marker_by_reflect(center_reflect, params):
    if _range_hit(center_reflect, params["purple_reflect_min"], params["purple_reflect_max"]):
        return "purple"
    if _range_hit(center_reflect, params["brown_reflect_min"], params["brown_reflect_max"]):
        return "brown"
    return None


def classify_marker_by_color_code(color_code):
    if color_code == COLOR_BROWN:
        return "brown"
    return None


def classify_marker(center_reflect, color_code, params):
    reflect_kind = classify_marker_by_reflect(center_reflect, params)
    if reflect_kind is not None:
        return reflect_kind, "reflect_range"
    color_kind = classify_marker_by_color_code(color_code)
    if color_kind is not None:
        return color_kind, "color_code"
    return None, "unknown"


def majority(values):
    counts = {}
    best_value = None
    best_count = -1
    for value in values:
        counts[value] = counts.get(value, 0) + 1
        if counts[value] > best_count:
            best_count = counts[value]
            best_value = value
    return best_value


class PdController(object):
    def __init__(self):
        self.prev_error = 0.0
        self.prev_t = None

    def reset(self):
        self.prev_error = 0.0
        self.prev_t = None

    def step(self, raw, params):
        error = float(raw[2] - raw[0])
        t = time.time()
        if self.prev_t is None:
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
        self._sound = None
        try:
            from ev3dev2.sound import Sound
            self._sound = Sound()
        except Exception:
            self._sound = None

    def read_reflect(self):
        return (
            self.left_sensor.reflected_light_intensity,
            self.center_sensor.reflected_light_intensity,
            self.right_sensor.reflected_light_intensity,
        )

    def read_center_reflect(self):
        return self.center_sensor.reflected_light_intensity

    def read_center_color(self, settle_ms, dummy_reads):
        self.prepare_center_color(settle_ms, dummy_reads)
        return self.read_center_color_value()

    def prepare_center_color(self, settle_ms, dummy_reads):
        try:
            self.center_sensor.mode = "COL-COLOR"
        except Exception:
            pass
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        for _ in range(int(dummy_reads)):
            _ = self.center_sensor.color
            time.sleep(0.01)

    def read_center_color_value(self):
        return self.center_sensor.color

    def restore_center_reflect(self):
        try:
            self.center_sensor.mode = "COL-REFLECT"
        except Exception:
            pass
        _ = self.center_sensor.reflected_light_intensity

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
            self.left_motor.reset()
            self.right_motor.reset()

    def read_encoders(self):
        return self.left_motor.position, self.right_motor.position

    def enc_avg(self):
        left, right = self.read_encoders()
        return (abs(left) + abs(right)) / 2.0

    def beep_marker(self, marker):
        if self._sound is None:
            return
        count = 1
        if marker == "purple":
            count = 2
        try:
            for _ in range(count):
                self._sound.beep()
                time.sleep(0.08)
        except Exception:
            pass

    def beep_unknown(self):
        if self._sound is None:
            return
        try:
            self._sound.beep()
        except Exception:
            pass


def run_encoder_turn(hw, action, params, telemetry, stop_event):
    target = encoder_target(action, params)
    left_dir, right_dir = wheel_dirs(action)
    speed = params["turn_speed"]
    left_turn_speed = left_dir * speed
    right_turn_speed = right_dir * speed
    started = now_ms()

    hw.reset_encoders()
    hw.drive(left_turn_speed, right_turn_speed)
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


def read_marker_at_rest(hw, params, stop_event):
    sample_count = int(params["marker_sample_count"])
    sample_delay = params["marker_sample_delay_ms"] / 1000.0
    reflects = []
    for _ in range(sample_count):
        if stop_event.is_set():
            break
        reflects.append(hw.read_center_reflect())
        if sample_delay > 0:
            time.sleep(sample_delay)

    if reflects:
        reflect_avg = sum(reflects) / float(len(reflects))
    else:
        reflect_avg = 100.0

    color_reads = []
    hw.prepare_center_color(params["color_mode_settle_ms"], params["color_dummy_reads"])
    for _ in range(sample_count):
        if stop_event.is_set():
            break
        color_reads.append(hw.read_center_color_value())
        if sample_delay > 0:
            time.sleep(sample_delay)
    hw.restore_center_reflect()

    color_code = majority(color_reads) if color_reads else COLOR_NONE
    marker, source = classify_marker(reflect_avg, color_code, params)
    return {
        "marker": marker,
        "source": source,
        "center_reflect_avg": reflect_avg,
        "color_code": color_code,
        "reflect_samples": len(reflects),
        "color_samples": len(color_reads),
    }


def publish_follow(telemetry, t_ms, raw, bits_str, action, derivative, branch_seen,
                   marker_seen, marker_elapsed_ms, params):
    telemetry.publish({
        "t_ms": t_ms,
        "mode": "follow",
        "reflect": raw,
        "bits": bits_str,
        "error": action["error"],
        "derivative": derivative,
        "turn": action["turn"],
        "left_speed": action["left"],
        "right_speed": action["right"],
        "branch_seen": branch_seen,
        "marker_seen": marker_seen,
        "marker_elapsed_ms": marker_elapsed_ms,
        "param_rev": params.rev(),
    })


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
    marker_tracker = MarkerCandidateTracker()
    started = now_ms()
    branch_seen = 0
    last_branch_turn_ms = -999999
    last_marker_ms = -999999

    def stop_handler(source):
        stop_event.set()

    def do_handler(action, args):
        snap = params.snapshot()
        if action in ("turn_left", "turn_right", "uturn"):
            actual = run_encoder_turn(hw, action, snap, telemetry, stop_event)
            pd.reset()
            return {"action": action, "enc_avg": actual}
        if action == "read_marker":
            hw.stop()
            result = read_marker_at_rest(hw, snap, stop_event)
            if result["marker"] is not None:
                hw.beep_marker(result["marker"])
            else:
                hw.beep_unknown()
            telemetry.publish({
                "mode": "manual_marker",
                "marker": result["marker"],
                "marker_source": result["source"],
                "center_reflect_avg": result["center_reflect_avg"],
                "color_code": result["color_code"],
                "param_rev": params.rev(),
            })
            pd.reset()
            return result
        if action == "beep_test":
            hw.beep_marker("purple")
            return {"beep": True}
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
            {"name": "read_marker", "label": "Read Marker"},
            {"name": "beep_test", "label": "Beep Test"},
        ],
        stage="stage4_color",
    )
    server.start()

    print("stage4 color marker start")
    print("candidate center reflect: [{}, {}) for {} ms".format(
        INITIAL_PARAMS["marker_candidate_min"],
        INITIAL_PARAMS["marker_candidate_max"],
        INITIAL_PARAMS["marker_stable_ms"],
    ))

    try:
        while not stop_event.is_set():
            snap = params.snapshot()
            raw = hw.read_reflect()
            bits = black_bits(raw, snap)
            bits_str = bits_to_str(bits)
            t_ms_abs = now_ms()
            t_ms = t_ms_abs - started

            in_branch_cooldown = (t_ms_abs - last_branch_turn_ms) < snap["branch_cooldown_ms"]
            if is_left_branch(bits) and not in_branch_cooldown:
                branch_seen += 1
            else:
                branch_seen = 0

            marker_seen, marker_elapsed = marker_tracker.push(raw[1], t_ms_abs, snap)
            in_marker_cooldown = (t_ms_abs - last_marker_ms) < snap["marker_cooldown_ms"]
            if marker_seen and not in_marker_cooldown:
                hw.stop()
                result = read_marker_at_rest(hw, snap, stop_event)
                if result["marker"] is not None:
                    hw.beep_marker(result["marker"])
                telemetry.publish({
                    "t_ms": t_ms,
                    "mode": "marker",
                    "reflect": raw,
                    "bits": bits_str,
                    "marker": result["marker"],
                    "marker_source": result["source"],
                    "center_reflect_avg": result["center_reflect_avg"],
                    "color_code": result["color_code"],
                    "marker_elapsed_ms": marker_elapsed,
                    "param_rev": params.rev(),
                })
                pd.reset()
                marker_tracker.reset()
                branch_seen = 0
                last_marker_ms = now_ms()
                time.sleep(snap["loop_delay_ms"] / 1000.0)
                continue

            if branch_seen >= int(snap["branch_confirm_count"]):
                hw.stop()
                telemetry.publish({
                    "t_ms": t_ms,
                    "mode": "branch_left",
                    "reason": "LEFT_BRANCH",
                    "reflect": raw,
                    "bits": bits_str,
                    "branch_seen": branch_seen,
                    "param_rev": params.rev(),
                })
                run_encoder_turn(hw, "turn_left", snap, telemetry, stop_event)
                pd.reset()
                marker_tracker.reset()
                branch_seen = 0
                last_branch_turn_ms = now_ms()
                continue

            left_speed, right_speed, error, derivative, turn = pd.step(raw, snap)
            if bits == (0, 0, 0):
                left_speed *= 0.55
                right_speed *= 0.55

            hw.drive(left_speed, right_speed)
            publish_follow(
                telemetry, t_ms, raw, bits_str,
                {"left": left_speed, "right": right_speed, "error": error, "turn": turn},
                derivative, branch_seen, marker_candidate(raw[1], snap),
                marker_elapsed, params,
            )
            time.sleep(snap["loop_delay_ms"] / 1000.0)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        hw.stop()
        server.stop()
        print("stage4 color marker stopped")


if __name__ == "__main__":
    main()
