#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage5_1_fixed_turn 판단층(고정 지시/replay 어댑터) + lib/seq_tokens 테스트."""

import os
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.seq_tokens import parse_token                          # noqa: E402
from stages.stage5_1_fixed_turn import (                        # noqa: E402
    CONFIRMED_PARAMS, INITIAL_PARAMS, MAX_STEP, PARAM_LIMITS, PARAM_ORDER,
    UI_STEP, decide_fixed, decide_fixed_turn,
)


def test_parse_token():
    assert parse_token("L") == "L"
    assert parse_token(" r ") == "R"
    assert parse_token("u") == "U"
    for bad in ("", "X", "LR", "1"):
        try:
            parse_token(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("must raise ValueError: {!r}".format(bad))


def test_fixed_turn_maps_to_reasons():
    expected = {"L": "TURN_LEFT", "R": "TURN_RIGHT",
                "U": "UTURN", "S": "NODE_STRAIGHT"}
    for token, want_reason in expected.items():
        got_token, reason, detail = decide_fixed_turn("BRANCH_LEFT", token)
        assert got_token == token
        assert reason == want_reason, (token, reason)
        assert detail["selected"] == token
        assert detail["detected"] == "BRANCH_LEFT"


def test_fixed_turn_ignores_detected_side():
    # 우 분기를 감지해도 지시가 L 이면 좌회전 — 불일치는 detail 로만 남는다.
    token, reason, detail = decide_fixed_turn("BRANCH_RIGHT", "L")
    assert token == "L"
    assert reason == "TURN_LEFT"
    assert detail["detected"] == "BRANCH_RIGHT"


def test_fixed_turn_rejects_invalid_token():
    try:
        decide_fixed_turn("BRANCH_LEFT", "X")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid token must raise ValueError")


def test_params_meta_consistent():
    keys = set(INITIAL_PARAMS)
    assert keys == set(PARAM_LIMITS)
    assert keys == set(MAX_STEP)
    assert keys == set(UI_STEP)
    assert keys == set(PARAM_ORDER)
    # 확정값은 라이브 param 과 겹치지 않는다(재노출 금지).
    assert not (keys & set(CONFIRMED_PARAMS))
    # 사용자 결정(2026-07-06): 속도·회전 factor 는 라이브로 유지한다.
    for must_live in ("base_speed", "turn_speed", "turn_90_factor"):
        assert must_live in keys, must_live


def test_replay_decider_fixed_turn():
    params = {"turn": "R", "branch_confirm_count": 1, "branch_advance_mm": 30}
    state = {}
    # 좌 분기 bits(110) — thresholds 기본(43/36/42)보다 낮은 반사광 = 흑.
    left_branch = {"reflect": [10, 10, 60], "t_ms": 5000}
    follow = {"reflect": [60, 10, 60], "t_ms": 5100}

    token, reason, detail = decide_fixed(left_branch, params, state)
    # 감지는 좌 분기지만 고정 지시 R 을 따른다(불일치는 detail 로 진단).
    assert token == "R"
    assert reason == "TURN_RIGHT"
    assert detail["bits"] == "110"
    assert detail["detected"] == "BRANCH_LEFT"

    # 분기가 아니면 판단 없음.
    token, reason, _ = decide_fixed(follow, params, state)
    assert token is None

    # 쿨다운(1500ms) 이후 두 번째 분기 → 같은 지시 반복(시퀀스 소비 없음).
    second = {"reflect": [10, 10, 60], "t_ms": 9000}
    token, reason, _ = decide_fixed(second, params, state)
    assert token == "R"
    assert reason == "TURN_RIGHT"


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("ok - {}".format(test.__name__))
    print("{} tests passed".format(len(tests)))


if __name__ == "__main__":
    main()
