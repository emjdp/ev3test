#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2 판단층(순수) + 구동 폴링 로직 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage2_logic.py
검증:  decide_turn / target_degrees(판단) + pivot(엔코더 폴링, 가짜 hw).
       실제 회전 각도(물리)는 재연 불가 — 실기 do 루프로 잡는다(DECISIONS.md 5장).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.decide_turn import decide_turn, target_degrees   # noqa: E402
from lib.turns import pivot                                # noqa: E402
from stages.stage2_turns import (                          # noqa: E402
    BASE_PIVOT_DEG_90,
    BASE_PIVOT_DEG_180,
    INITIAL_PARAMS,
    PARAM_LIMITS,
    MAX_STEP,
)


def _params(**over):
    p = dict(INITIAL_PARAMS)
    p["BASE_PIVOT_DEG_90"] = BASE_PIVOT_DEG_90
    p["BASE_PIVOT_DEG_180"] = BASE_PIVOT_DEG_180
    p.update(over)
    return p


class FakeHw(object):
    """읽을 때마다 구동 방향으로 일정량 누적되는 엔코더 모사(물리 없음)."""

    def __init__(self, step=12.0):
        self.l = 0.0
        self.r = 0.0
        self.step = step
        self.drive = None
        self.drive_history = []
        self.stopped = False
        self.reset_calls = 0

    def reset_encoders(self):
        self.l = 0.0
        self.r = 0.0
        self.reset_calls += 1

    def drive_raw(self, left_speed, right_speed):
        self.drive = (left_speed, right_speed)
        self.drive_history.append(self.drive)

    def read_encoders(self):
        if self.drive is not None:
            if self.drive[0] > 0:
                self.l += self.step
            elif self.drive[0] < 0:
                self.l -= self.step
            if self.drive[1] > 0:
                self.r += self.step
            elif self.drive[1] < 0:
                self.r -= self.step
        return self.l, self.r

    def stop(self):
        self.stopped = True


def test_decide_turn_actions():
    p = _params()
    a, reason, detail = decide_turn("turn_left", p, {})
    assert a == "LEFT90" and reason == "TURN_LEFT"
    assert detail["target_deg"] == BASE_PIVOT_DEG_90 * p["turn_90_factor"]
    assert detail["selected"] == "LEFT" and detail["rule"] == "DO_TRIGGER"
    assert detail["turn_speed"] == p["turn_speed"]

    a, reason, detail = decide_turn("turn_right", p, {})
    assert a == "RIGHT90" and reason == "TURN_RIGHT" and detail["selected"] == "RIGHT"

    a, reason, detail = decide_turn("uturn", p, {})
    assert a == "UTURN180" and reason == "UTURN"
    assert detail["target_deg"] == BASE_PIVOT_DEG_180 * p["turn_180_factor"]
    assert detail["factor"] == p["turn_180_factor"]
    print("decide_turn actions ok")


def test_target_degrees_linear():
    # 보정계수에 선형으로 반응(0.5 / 1.0 / 2.0).
    assert target_degrees("LEFT90", _params(turn_90_factor=0.5)) == BASE_PIVOT_DEG_90 * 0.5
    assert target_degrees("LEFT90", _params(turn_90_factor=1.0)) == BASE_PIVOT_DEG_90
    assert target_degrees("LEFT90", _params(turn_90_factor=2.0)) == BASE_PIVOT_DEG_90 * 2.0
    assert target_degrees("UTURN180", _params(turn_180_factor=1.1)) == BASE_PIVOT_DEG_180 * 1.1
    # 90 계수 변경은 U턴 목표각에 영향 없음(분리 확인).
    assert target_degrees("UTURN180", _params(turn_90_factor=2.0)) == BASE_PIVOT_DEG_180
    print("target_degrees linear ok")


def test_decide_turn_unknown_command():
    try:
        decide_turn("spin", _params(), {})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("decide_turn unknown command ok")


def test_pivot_reaches_target_and_direction():
    hw = FakeHw()
    actual = pivot(hw, "LEFT90", 100.0, 18, should_stop=lambda: False)
    assert actual >= 100.0
    assert hw.reset_calls == 1 and hw.stopped is True
    # 좌회전: 좌바퀴 후진(-) / 우바퀴 전진(+)
    assert hw.l < 0 and hw.r > 0

    hw = FakeHw()
    pivot(hw, "RIGHT90", 100.0, 18, should_stop=lambda: False)
    assert hw.l > 0 and hw.r < 0   # 우회전은 반대
    print("pivot reach/direction ok")


def test_pivot_stop_and_zero_target():
    # stop 즉시 → 거의 안 돌고 멈춤
    hw = FakeHw()
    actual = pivot(hw, "UTURN180", 1000.0, 18, should_stop=lambda: True)
    assert actual == 0.0 and hw.stopped is True

    # target<=0 → 회전 자체를 시작하지 않음(BASE 미설정 방어)
    hw = FakeHw()
    actual = pivot(hw, "LEFT90", 0.0, 18, should_stop=lambda: False)
    assert actual == 0.0 and hw.drive is None and hw.stopped is True
    print("pivot stop/zero-target ok")


def test_pivot_pause_keeps_target():
    hw = FakeHw()
    checks = {"count": 0}

    def should_pause():
        checks["count"] += 1
        return checks["count"] <= 2

    actual = pivot(hw, "LEFT90", 100.0, 18,
                   should_stop=lambda: False, should_pause=should_pause)
    assert actual >= 100.0 and hw.stopped is True
    assert (0, 0) in hw.drive_history
    print("pivot pause keeps target ok")


def test_param_safety_metadata():
    # 라이브 params 4개, 6 이하. LIMITS/MAX_STEP 가 모든 param 을 덮는다.
    assert len(INITIAL_PARAMS) == 4
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_decide_turn_actions()
    test_target_degrees_linear()
    test_decide_turn_unknown_command()
    test_pivot_reaches_target_and_direction()
    test_pivot_stop_and_zero_target()
    test_pivot_pause_keeps_target()
    test_param_safety_metadata()
    print("ALL stage2 logic tests passed")


if __name__ == "__main__":
    main()
