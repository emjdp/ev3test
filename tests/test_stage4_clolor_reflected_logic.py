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
    BASE_PIVOT_DEG_180, TURN_180_FACTOR,
    MarkerCandidateTracker, marker_candidate, classify_marker_by_rgb,
    run_marker_uturn,
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


def _params():
    return SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                        os.path.join(_ROOT, "config", "_test_stage4_reflected_unused.json"),
                        ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)


def test_marker_candidate_tracker_confirms_immediately():
    params = dict(INITIAL_PARAMS)
    params["marker_candidate_min"] = 24
    params["marker_candidate_max"] = 35
    params["marker_stable_ms"] = 10

    assert marker_candidate(26, params) is True
    assert marker_candidate(35, params) is False

    tracker = MarkerCandidateTracker()
    seen, elapsed = tracker.push(26, 1000, params)
    assert seen is True and elapsed == 0
    seen, elapsed = tracker.push(26, 1001, params)
    assert seen is False and elapsed == 0
    seen, elapsed = tracker.push(80, 1002, params)
    assert seen is False and elapsed == 0
    seen, elapsed = tracker.push(26, 1003, params)
    assert seen is True and elapsed == 0
    print("marker candidate tracker ok")


def test_rgb_classifier_purple_and_brown():
    params = dict(INITIAL_PARAMS)
    assert classify_marker_by_rgb((60, 20, 60), params) == "purple"
    assert classify_marker_by_rgb((80, 30, 20), params) == "brown"
    assert classify_marker_by_rgb((10, 80, 10), params) is None
    print("rgb classifier ok")


def test_marker_uturn_reuses_uturn_without_extra_turn_beep():
    hw = FakeHw()
    tele = Telemetry()
    events = []
    log = DecisionLog(telemetry=tele, sink=events.append)
    params = _params()
    result = {
        "marker": "brown",
        "source": "rgb_raw",
        "center_reflect_avg": 32.0,
        "color_code": 7,
        "rgb": (80.0, 30.0, 20.0),
        "rgb_ratio": (0.615, 0.231, 0.154),
    }

    actual = run_marker_uturn(
        hw, params, log, tele,
        should_stop=lambda: False,
        should_pause=lambda: False,
        started=0.0,
        result=result,
        reflect=(80, 32, 80),
        bits_str="000")

    assert actual >= BASE_PIVOT_DEG_180 * TURN_180_FACTOR
    assert hw.el > 0 and hw.er < 0
    assert events[-2]["event"] == "MARKER_UTURN"
    assert events[-1]["event"] == "UTURN"
    assert hw.beep_count == 0
    print("marker uturn no extra beep ok")


if __name__ == "__main__":
    test_marker_candidate_tracker_confirms_immediately()
    test_rgb_classifier_purple_and_brown()
    test_marker_uturn_reuses_uturn_without_extra_turn_beep()
