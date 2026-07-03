#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage4_clolor_reflected 판단/자동 U턴 연결 테스트."""

import os
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.decision_log import DecisionLog                     # noqa: E402
from lib.shared_params import SharedParams                    # noqa: E402
from lib.telemetry import Telemetry                           # noqa: E402
from stages.stage4_clolor_reflected import (                  # noqa: E402
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
    BASE_PIVOT_DEG_180, TURN_180_FACTOR, COLOR_RED,
    MarkerCandidateTracker, marker_candidate, marker_candidate_kind,
    classify_marker_by_color_code, classify_purple_by_rgb,
    read_marker_at_rest, run_marker_uturn,
)


class FakeHw(object):
    def __init__(self, enc_step=24.0):
        self.el = 0.0
        self.er = 0.0
        self.enc_step = enc_step
        self.drive_cmd = None
        self.drive_history = []
        self.beep_count = 0
        self.reset_calls = 0

    def reset_encoders(self):
        self.el = 0.0
        self.er = 0.0
        self.reset_calls += 1

    def read_encoders(self):
        if self.drive_cmd is not None:
            left, right = self.drive_cmd
            if left > 0:
                self.el += self.enc_step
            elif left < 0:
                self.el -= self.enc_step
            if right > 0:
                self.er += self.enc_step
            elif right < 0:
                self.er -= self.enc_step
        return self.el, self.er

    def enc_avg(self):
        el, er = self.read_encoders()
        return (abs(el) + abs(er)) / 2.0

    def drive(self, left_speed, right_speed):
        self.drive_cmd = (left_speed, right_speed)
        self.drive_history.append(("drive", left_speed, right_speed))

    def drive_raw(self, left_speed, right_speed):
        self.drive_cmd = (left_speed, right_speed)
        self.drive_history.append(("drive_raw", left_speed, right_speed))

    def stop(self):
        self.drive_cmd = None

    def beep_ok(self):
        self.beep_count += 1


class FakeMarkerHw(FakeHw):
    def __init__(self, colors=None, rgbs=None):
        FakeHw.__init__(self)
        self.colors = list(colors or [])
        self.rgbs = list(rgbs or [])
        self.color_calls = 0
        self.rgb_calls = 0
        self.restore_calls = 0

    def read_center_reflect(self):
        return 32

    def read_center_color(self, settle_s, dummy_reads):
        self.color_calls += 1
        if self.colors:
            return self.colors.pop(0)
        return 0

    def read_center_rgb(self, settle_s, dummy_reads):
        self.rgb_calls += 1
        if self.rgbs:
            return self.rgbs.pop(0)
        return (0, 0, 0)

    def restore_reflect_mode(self, settle_s):
        self.restore_calls += 1


def _params():
    return SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                        os.path.join(_ROOT, "config", "_test_stage4_reflected_unused.json"),
                        ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)


def test_marker_candidate_tracker_confirms_immediately():
    params = dict(INITIAL_PARAMS)
    params["marker_candidate_min"] = 23
    params["marker_candidate_max"] = 30
    params["red_candidate_min"] = 74
    params["red_candidate_max"] = 86
    params["marker_stable_ms"] = 10

    assert marker_candidate_kind(26, params) == "purple"
    assert marker_candidate_kind(79, params) == "red"
    assert marker_candidate_kind(68, params) is None
    assert marker_candidate_kind(32, params) is None
    assert marker_candidate(26, params) is True
    assert marker_candidate(79, params) is True
    assert marker_candidate(68, params) is False
    assert marker_candidate(32, params) is False

    tracker = MarkerCandidateTracker()
    kind, elapsed = tracker.push(26, 1000, params)
    assert kind == "purple" and elapsed == 0
    kind, elapsed = tracker.push(26, 1001, params)
    assert kind is None and elapsed == 0
    kind, elapsed = tracker.push(80, 1002, params)
    assert kind == "red" and elapsed == 0
    kind, elapsed = tracker.push(68, 1003, params)
    assert kind is None and elapsed == 0
    kind, elapsed = tracker.push(26, 1004, params)
    assert kind == "purple" and elapsed == 0
    print("marker candidate tracker ok")


def test_purple_rgb_and_red_color_code_are_markers():
    params = dict(INITIAL_PARAMS)
    params["marker_sample_count"] = 3
    params["marker_sample_delay_ms"] = 0

    assert classify_marker_by_color_code(COLOR_RED) == "red"
    assert classify_marker_by_color_code(0) is None
    assert classify_purple_by_rgb((60, 20, 60), params) == "purple"
    assert classify_purple_by_rgb((10, 80, 10), params) is None

    hw = FakeMarkerHw(rgbs=[(60, 20, 60), (62, 18, 64), (58, 22, 61)])
    result = read_marker_at_rest(hw, params, {"on": False}, center_reflect_hint=26)
    assert result["marker"] == "purple"
    assert result["source"] == "rgb_raw_purple"
    assert result["candidate_kind"] == "purple"
    assert result["color_code"] == 0
    assert result["rgb"] is not None and result["rgb_ratio"] is not None
    assert result["rgb_samples"] == 3 and result["color_samples"] == 0
    assert hw.color_calls == 0 and hw.rgb_calls == 3

    hw = FakeMarkerHw(colors=[COLOR_RED, COLOR_RED, 0])
    result = read_marker_at_rest(hw, params, {"on": False}, center_reflect_hint=79)
    assert result["marker"] == "red"
    assert result["source"] == "color_code_red"
    assert result["candidate_kind"] == "red"
    assert result["color_code"] == COLOR_RED
    assert result["rgb"] is None and result["rgb_ratio"] is None
    assert result["color_samples"] == 3 and result["rgb_samples"] == 0
    assert hw.color_calls == 3 and hw.rgb_calls == 0

    hw = FakeMarkerHw(colors=[COLOR_RED, COLOR_RED, COLOR_RED])
    result = read_marker_at_rest(hw, params, {"on": False}, center_reflect_hint=32)
    assert result["marker"] is None
    assert result["source"] == "unknown"
    assert result["candidate_kind"] is None
    assert hw.color_calls == 0 and hw.rgb_calls == 0
    print("purple/red marker classification ok")


def test_marker_uturn_reuses_uturn_without_extra_turn_beep():
    hw = FakeHw()
    tele = Telemetry()
    events = []
    log = DecisionLog(telemetry=tele, sink=events.append)
    params = _params()
    result = {
        "marker": "purple",
        "source": "rgb_raw_purple",
        "candidate_kind": "purple",
        "center_reflect_avg": 26.0,
        "color_code": 0,
        "rgb": (60.0, 20.0, 60.0),
        "rgb_ratio": (0.429, 0.143, 0.429),
    }

    actual = run_marker_uturn(
        hw, params, log, tele,
        should_stop=lambda: False,
        should_pause=lambda: False,
        started=0.0,
        result=result,
        reflect=(80, 26, 80),
        bits_str="000")

    assert actual >= BASE_PIVOT_DEG_180 * TURN_180_FACTOR
    assert hw.el > 0 and hw.er < 0
    assert events[-2]["event"] == "MARKER_UTURN"
    assert events[-1]["event"] == "UTURN"
    assert hw.beep_count == 0
    print("marker uturn no extra beep ok")


if __name__ == "__main__":
    test_marker_candidate_tracker_confirms_immediately()
    test_purple_rgb_and_red_color_code_are_markers()
    test_marker_uturn_reuses_uturn_without_extra_turn_beep()
