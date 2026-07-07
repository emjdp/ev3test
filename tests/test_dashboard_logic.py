#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""대시보드 표시 로직 테스트 — EV3 없이 PC 에서 돈다."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.dashboard import (                         # noqa: E402
    _navigation_items, _wrap_move_items,
)


def test_navigation_items_pair_moves_with_last_confirmed_bits():
    events = [
        {"event": "NODE_IS_START", "reason": "COLOR_YELLOW", "color": 4},
        {"event": "NODE_CONFIRMED", "reason": "SLOW_STRAIGHT_STOP", "bits": "110"},
        {"event": "BRANCH_PROBE", "reason": "PRIORITY_R_L_S", "move": "L"},
        {"event": "NODE_CONFIRMED", "reason": "SLOW_STRAIGHT_STOP", "bits": "011"},
        {"event": "RETURN_STEP", "reason": "PLAN", "move": "R"},
        {"event": "NODE_CONFIRMED", "reason": "SLOW_STRAIGHT_STOP", "bits": "111"},
        {"event": "BRANCH_PROBE", "reason": "PRIORITY_R_L_S", "move": "S"},
        {"event": "MARKER_UTURN", "reason": "COLOR_RED_IMMEDIATE", "color": 5},
    ]

    assert _navigation_items(events) == [
        "START(yellow)",
        "L(110)",
        "R(011)",
        "S(111)",
        "U(red)",
    ]
    print("navigation items pair moves with bits ok")


def test_navigation_items_curve_and_dead_end():
    events = [
        {"event": "NODE_CONFIRMED", "bits": [1, 1, 0]},
        {"event": "NODE_CURVE", "reason": "FORCED_LEFT", "bits": "110"},
        {"event": "NODE_CONFIRMED", "bits": "000"},
        {"event": "DEAD_END", "reason": "BACKUP_NO_LINE"},
    ]

    assert _navigation_items(events) == ["L(110)", "U(000)"]
    print("navigation items curve and dead end ok")


def test_wrap_move_items_keeps_numbered_tokens():
    lines = _wrap_move_items(["START(yellow)", "L(110)", "R(011)", "U(node)"], 60, 3)
    joined = "\n".join(lines)
    assert "01:START(yellow)" in joined
    assert "02:L(110)" in joined
    assert "04:U(node)" in joined
    print("wrap move items keeps numbered tokens ok")


def main():
    test_navigation_items_pair_moves_with_last_confirmed_bits()
    test_navigation_items_curve_and_dead_end()
    test_wrap_move_items_keeps_numbered_tokens()
    print("ALL dashboard logic tests passed")


if __name__ == "__main__":
    main()
