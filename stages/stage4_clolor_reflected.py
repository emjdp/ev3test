#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 color marker detection using the latest Stage 3 v2 line tracing.

Run on EV3:
    python3 stages/stage4_clolor_reflected.py

This stage keeps the Stage 3 v2 line-tracing/branch behavior and adds a quick
center-reflect gate for the brown node marker:

  - brown reflect was measured near 32
  - candidate reflect triggers a color-code read immediately

Reflect is only used as a candidate gate. Once the center sensor enters that
gate, the robot stops, switches the center sensor to color mode, reads the
marker, restores reflected-light mode, and then continues line tracing.

The EV3 color code for brown is stable in this setup, so COLOR_BROWN(7) alone
is treated as the node marker. RGB-RAW values are not used for node judgment.

Python 3.5 compatible: no f-strings.
"""

import os
import sys
import threading
import time


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams                       # noqa: E402
from lib.telemetry import Telemetry                               # noqa: E402
from lib.decision_log import DecisionLog                          # noqa: E402
from lib.tuning_server import TuningServer                        # noqa: E402
from stages.stage3v2_linetrace_branch import (                    # noqa: E402
    ADVANCE_SPEED,
    BASE_PIVOT_DEG_90,
    BASE_PIVOT_DEG_180,
    BRANCH_COOLDOWN_MS,
    LOOP_DELAY_MS,
    POST_TURN_SETTLE_MS,
    REASON_THROTTLE_S,
    THR_CENTER,
    THR_LEFT,
    THR_RIGHT,
    TURN_180_FACTOR,
    _maybe_follow_log,
    _run_turn,
    _tick_stop,
    advance_straight,
    bits_to_str,
    black_bits,
    branch_confirm_step,
    branch_side,
    now_ms,
    PdController,
    pd_step,
)


COLOR_NONE = 0
COLOR_BROWN = 7

# Seed Stage 4 with the latest committed Stage 3 v2 tuned values.
INITIAL_PARAMS = {
    "kp": 0.22,
    "base_speed": 17,
    "turn_speed": 6,
    "turn_90_factor": 0.66,
    "branch_confirm_count": 2,
    "branch_advance_mm": 30,
    "marker_candidate_min": 24,
    "marker_candidate_max": 35,
    "marker_stable_ms": 0,
    "marker_cooldown_ms": 1000,
    "marker_sample_count": 3,
    "marker_sample_delay_ms": 1,
    "color_mode_settle_ms": 10,
    "color_dummy_reads": 1,
    "purple_red_ratio_min": 0.25,
    "purple_blue_ratio_min": 0.30,
    "purple_green_ratio_max": 0.30,
    "brown_red_ratio_min": 0.42,
    "brown_blue_ratio_max": 0.25,
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "base_speed": (5, 45),
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "branch_confirm_count": (1, 20),
    "branch_advance_mm": (0, 120),
    "marker_candidate_min": (0, 100),
    "marker_candidate_max": (0, 100),
    "marker_stable_ms": (0, 1000),
    "marker_cooldown_ms": (0, 5000),
    "marker_sample_count": (1, 30),
    "marker_sample_delay_ms": (0, 100),
    "color_mode_settle_ms": (0, 500),
    "color_dummy_reads": (0, 10),
    "purple_red_ratio_min": (0.0, 1.0),
    "purple_blue_ratio_min": (0.0, 1.0),
    "purple_green_ratio_max": (0.0, 1.0),
    "brown_red_ratio_min": (0.0, 1.0),
    "brown_blue_ratio_max": (0.0, 1.0),
}

MAX_STEP = {
    "kp": 0.1,
    "base_speed": 5,
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "branch_confirm_count": 2,
    "branch_advance_mm": 10,
    "marker_candidate_min": 5,
    "marker_candidate_max": 5,
    "marker_stable_ms": 10,
    "marker_cooldown_ms": 200,
    "marker_sample_count": 2,
    "marker_sample_delay_ms": 10,
    "color_mode_settle_ms": 20,
    "color_dummy_reads": 1,
    "purple_red_ratio_min": 0.05,
    "purple_blue_ratio_min": 0.05,
    "purple_green_ratio_max": 0.05,
    "brown_red_ratio_min": 0.05,
    "brown_blue_ratio_max": 0.05,
}

UI_STEP = {
    "kp": 0.01,
    "base_speed": 1,
    "turn_speed": 1,
    "turn_90_factor": 0.01,
    "branch_confirm_count": 1,
    "branch_advance_mm": 10,
    "marker_candidate_min": 1,
    "marker_candidate_max": 1,
    "marker_stable_ms": 5,
    "marker_cooldown_ms": 50,
    "marker_sample_count": 1,
    "marker_sample_delay_ms": 1,
    "color_mode_settle_ms": 5,
    "color_dummy_reads": 1,
    "purple_red_ratio_min": 0.01,
    "purple_blue_ratio_min": 0.01,
    "purple_green_ratio_max": 0.01,
    "brown_red_ratio_min": 0.01,
    "brown_blue_ratio_max": 0.01,
}

UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "branch_advance_mm": "mm",
    "marker_candidate_min": "%",
    "marker_candidate_max": "%",
    "marker_stable_ms": "ms",
    "marker_cooldown_ms": "ms",
    "marker_sample_delay_ms": "ms",
    "color_mode_settle_ms": "ms",
    "purple_red_ratio_min": "x",
    "purple_blue_ratio_min": "x",
    "purple_green_ratio_max": "x",
    "brown_red_ratio_min": "x",
    "brown_blue_ratio_max": "x",
}

PARAM_ORDER = [
    "kp", "base_speed", "turn_speed", "turn_90_factor",
    "branch_confirm_count", "branch_advance_mm",
    "marker_candidate_min", "marker_candidate_max", "marker_stable_ms",
    "marker_cooldown_ms", "marker_sample_count", "marker_sample_delay_ms",
    "color_mode_settle_ms", "color_dummy_reads",
    "purple_red_ratio_min", "purple_blue_ratio_min", "purple_green_ratio_max",
    "brown_red_ratio_min", "brown_blue_ratio_max",
]

SAVE_PATH = os.path.join(_ROOT, "config", "stage4_clolor_reflected.json")
STAGE_NAME = "stage4_clolor_reflected"

ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
    {"name": "read_marker", "label": "Read Marker"},
    {"name": "beep_test", "label": "Beep Test"},
]


def marker_candidate(center_reflect, params):
    lo = params["marker_candidate_min"]
    hi = params["marker_candidate_max"]
    if lo >= hi:
        return False
    return center_reflect >= lo and center_reflect < hi


class MarkerCandidateTracker(object):
    def __init__(self):
        self.confirmed_inside = False

    def reset(self):
        self.confirmed_inside = False

    def push(self, center_reflect, t_ms, params):
        if not marker_candidate(center_reflect, params):
            self.reset()
            return False, 0

        if self.confirmed_inside:
            return False, 0

        self.confirmed_inside = True
        return True, 0


def classify_marker_by_color_code(color_code):
    if color_code == COLOR_BROWN:
        return "brown"
    return None


def classify_marker(color_code):
    color_kind = classify_marker_by_color_code(color_code)
    if color_kind == "brown":
        return "brown", "color_code_brown"

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


def beep_marker(hw, marker):
    try:
        hw.beep_ok()
    except Exception:
        pass


class _MuteTurnBeepHw(object):
    def __init__(self, hw):
        self._hw = hw

    def __getattr__(self, name):
        return getattr(self._hw, name)

    def beep_ok(self):
        pass


def run_marker_uturn(hw, params, log, tele, should_stop, should_pause,
                     started, result, reflect, bits_str):
    log.log("MARKER_UTURN", "COLOR_RECOGNIZED",
            marker=result["marker"], marker_source=result["source"],
            reflect=list(reflect), bits=bits_str,
            color_code=result["color_code"],
            center_reflect_avg=result["center_reflect_avg"])
    _publish(tele, params, started, mode="marker_uturn",
             marker=result["marker"], marker_source=result["source"],
             reflect=list(reflect), bits=bits_str,
             color_code=result["color_code"],
             center_reflect_avg=result["center_reflect_avg"])
    if should_stop():
        return 0.0
    return _run_turn(_MuteTurnBeepHw(hw), "uturn", params, log, tele,
                     should_stop, should_pause, started)


def read_marker_at_rest(hw, params, stop_flag, center_reflect_hint=None):
    sample_count = int(params["marker_sample_count"])
    sample_delay = params["marker_sample_delay_ms"] / 1000.0

    if center_reflect_hint is None:
        reflect_avg = hw.read_center_reflect()
        reflect_samples = 1
    else:
        reflect_avg = float(center_reflect_hint)
        reflect_samples = 1

    color_reads = []
    settle_s = params["color_mode_settle_ms"] / 1000.0
    dummy_reads = int(params["color_dummy_reads"])
    for _ in range(sample_count):
        if stop_flag["on"]:
            break
        color_reads.append(hw.read_center_color(settle_s, dummy_reads))
        if sample_delay > 0:
            time.sleep(sample_delay)
    hw.restore_reflect_mode(settle_s)

    color_code = majority(color_reads) if color_reads else COLOR_NONE
    marker, source = classify_marker(color_code)
    return {
        "marker": marker,
        "source": source,
        "center_reflect_avg": reflect_avg,
        "color_code": color_code,
        "reflect_samples": reflect_samples,
        "color_samples": len(color_reads),
    }


def _publish(tele, params, started, **overrides):
    now = time.monotonic()
    frame = {
        "t_ms": int((now - started) * 1000),
        "param_rev": params.rev(),
        "running": True,
        "mode": "follow",
        "reflect": [0, 0, 0],
        "bits": "000",
        "marker": None,
        "marker_source": None,
        "center_reflect_avg": None,
        "color_code": None,
        "marker_elapsed_ms": 0,
        "branch_seen": 0,
    }
    frame.update(overrides)
    tele.publish(frame)


def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (brick only)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()
    marker_tracker = MarkerCandidateTracker()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"turn": None, "marker": False, "beep": False}
    plock = threading.Lock()

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "follow"}

    def on_do(action, args):
        if action in ("turn_left", "turn_right", "uturn"):
            with plock:
                pending["turn"] = action
            return {"queued": action}
        if action == "read_marker":
            with plock:
                pending["marker"] = True
            return {"queued": action}
        if action == "beep_test":
            with plock:
                pending["beep"] = True
            return {"queued": action}
        return {"error": "unknown action: {}".format(action)}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    thresholds = (THR_LEFT, THR_CENTER, THR_RIGHT)
    started = time.monotonic()
    branch_seen = 0
    last_turn_ms = -999999
    last_branch_side = None
    last_marker_ms = -999999
    last_follow_log = started - REASON_THROTTLE_S

    print("stage4 color ready (Stage 3 v2 line trace + brown marker). "
          "stop via robotctl stop or Ctrl-C.")

    try:
        while True:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.drive(0, 0)
                raw = hw.read_reflect()
                bits = black_bits(raw, thresholds)
                _publish(tele, params, started, mode="paused", paused=True,
                         reflect=list(raw), bits=bits_to_str(bits),
                         branch_seen=branch_seen, enc_avg=hw.enc_avg())
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            with plock:
                turn_cmd = pending["turn"]
                pending["turn"] = None
                manual_marker = pending["marker"]
                pending["marker"] = False
                beep_test = pending["beep"]
                pending["beep"] = False

            if beep_test:
                beep_marker(hw, "brown")
                _publish(tele, params, started, mode="beep_test")
                continue

            snap = params.snapshot()

            if manual_marker:
                hw.stop()
                result = read_marker_at_rest(hw, snap, stop_flag)
                if result["marker"] is not None:
                    beep_marker(hw, result["marker"])
                log.log("COLOR_READ", "MANUAL", marker=result["marker"],
                        marker_source=result["source"],
                        center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"])
                _publish(tele, params, started, mode="manual_marker",
                         marker=result["marker"], marker_source=result["source"],
                         center_reflect_avg=result["center_reflect_avg"],
                         color_code=result["color_code"])
                pd.reset()
                marker_tracker.reset()
                continue

            if turn_cmd is not None:
                _run_turn(hw, turn_cmd, params, log, tele, should_stop, should_pause, started)
                pd.reset()
                branch_seen = 0
                last_branch_side = None
                last_turn_ms = now_ms()
                marker_tracker.reset()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            raw = hw.read_reflect()
            bits = black_bits(raw, thresholds)
            bits_str = bits_to_str(bits)
            side = branch_side(bits)
            t_ms = now_ms()

            marker_seen, marker_elapsed = marker_tracker.push(raw[1], t_ms, snap)
            in_marker_cooldown = (t_ms - last_marker_ms) < snap["marker_cooldown_ms"]
            if marker_seen and not in_marker_cooldown:
                hw.stop()
                result = read_marker_at_rest(hw, snap, stop_flag, raw[1])
                log.log("COLOR_READ", "AUTO_REFLECT_GATE", marker=result["marker"],
                        marker_source=result["source"], reflect=list(raw),
                        center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"],
                        marker_elapsed_ms=marker_elapsed)
                _publish(tele, params, started, mode="marker",
                         reflect=list(raw), bits=bits_str,
                         marker=result["marker"], marker_source=result["source"],
                         center_reflect_avg=result["center_reflect_avg"],
                         color_code=result["color_code"],
                         marker_elapsed_ms=marker_elapsed,
                         branch_seen=branch_seen)
                if result["marker"] is not None:
                    beep_marker(hw, result["marker"])
                    run_marker_uturn(hw, params, log, tele, should_stop,
                                     should_pause, started, result, raw, bits_str)
                pd.reset()
                marker_tracker.reset()
                branch_seen = 0
                last_branch_side = None
                last_marker_ms = now_ms()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            branch_seen, confirmed, last_branch_side = branch_confirm_step(
                side, branch_seen, t_ms, last_turn_ms,
                snap["branch_confirm_count"], BRANCH_COOLDOWN_MS, last_branch_side)

            if confirmed:
                hw.stop()
                reason = "BRANCH_LEFT" if side == "left" else "BRANCH_RIGHT"
                mode_name = "branch_left" if side == "left" else "branch_right"
                log.log(reason, "BITS_" + bits_str, bits=bits_str,
                        branch_seen=branch_seen, advance_mm=snap["branch_advance_mm"],
                        reflect=list(raw))
                _publish(tele, params, started, mode=mode_name, reflect=list(raw),
                         bits=bits_str, branch_seen=branch_seen,
                         enc_avg=hw.enc_avg(), advance_mm=snap["branch_advance_mm"])

                def on_advance_tick():
                    el, er = hw.read_encoders()
                    _publish(tele, params, started, mode="advancing",
                             advance_mm=snap["branch_advance_mm"],
                             enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

                advance_straight(hw, snap["branch_advance_mm"], ADVANCE_SPEED,
                                 _tick_stop(should_stop, on_advance_tick), should_pause)

                pd.reset()
                marker_tracker.reset()
                branch_seen = 0
                last_branch_side = None
                last_turn_ms = now_ms()

                if should_stop():
                    continue

                cmd = "turn_left" if side == "left" else "turn_right"
                _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)
                continue

            left_speed, right_speed, error, derivative, turn = pd_step(pd, raw, snap)
            if bits == (0, 0, 0):
                left_speed *= 0.55
                right_speed *= 0.55
            hw.drive(left_speed, right_speed)

            now = time.monotonic()
            last_follow_log = _maybe_follow_log(log, raw, error, turn, now, last_follow_log)

            enc_l, enc_r = hw.read_encoders()
            _publish(tele, params, started, mode="follow", reflect=list(raw),
                     bits=bits_str, error=error, turn=turn, left_speed=left_speed,
                     right_speed=right_speed, branch_seen=branch_seen,
                     marker_seen=marker_candidate(raw[1], snap),
                     marker_elapsed_ms=marker_elapsed,
                     enc_l=enc_l, enc_r=enc_r, enc_avg=hw.enc_avg())

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage4 color stopped.")


if __name__ == "__main__":
    run()
