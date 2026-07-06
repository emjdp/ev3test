#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 route-decision logic tests."""

import os
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.stage5_integration import (  # noqa: E402
    TOKEN_LEFT,
    TOKEN_RIGHT,
    TOKEN_STRAIGHT,
    TOKEN_UTURN,
    PHOTO_DIRECT_SEQ,
    INITIAL_PARAMS,
    PARAM_LIMITS,
    MAX_STEP,
    PARAM_ORDER,
    UI_STEP,
    STAGE4_COLOR_DEFAULTS,
    parse_sequence,
    sequence_to_text,
    classify_node_bits,
    node_confirm_step,
    decide_turn_from_sequence,
    make_stage4_color_params,
)


def test_parse_sequence_forms():
    assert parse_sequence("R R L L S") == [
        TOKEN_RIGHT, TOKEN_RIGHT, TOKEN_LEFT, TOKEN_LEFT, TOKEN_STRAIGHT]
    assert parse_sequence("RRLLS") == [
        TOKEN_RIGHT, TOKEN_RIGHT, TOKEN_LEFT, TOKEN_LEFT, TOKEN_STRAIGHT]
    assert parse_sequence("right,left,straight,uturn") == [
        TOKEN_RIGHT, TOKEN_LEFT, TOKEN_STRAIGHT, TOKEN_UTURN]
    assert sequence_to_text(parse_sequence(PHOTO_DIRECT_SEQ)) == (
        "R L L R L L R L S S L R L L R L S S R L R R L L L")
    print("parse_sequence forms ok")


def test_classify_node_bits_keeps_cross_separate():
    assert classify_node_bits((1, 1, 1)) == "CROSS"
    assert classify_node_bits((1, 1, 0)) == "LEFT_BRANCH"
    assert classify_node_bits((0, 1, 1)) == "RIGHT_BRANCH"
    assert classify_node_bits((0, 1, 0)) is None
    assert classify_node_bits((1, 0, 0)) is None
    assert classify_node_bits((0, 0, 1)) is None
    print("classify_node_bits ok")


def test_node_confirm_step_counts_same_kind_only():
    seen = 0
    last_kind = None
    last_node_ms = -999999
    for _i in range(2):
        seen, confirmed, last_kind = node_confirm_step(
            "CROSS", seen, 1000, last_node_ms, 3, 1500, last_kind)
        assert confirmed is False
    seen, confirmed, last_kind = node_confirm_step(
        "CROSS", seen, 1000, last_node_ms, 3, 1500, last_kind)
    assert confirmed is True and seen == 3 and last_kind == "CROSS"

    seen, confirmed, last_kind = node_confirm_step(
        "LEFT_BRANCH", seen, 1000, last_node_ms, 3, 1500, last_kind)
    assert confirmed is False and seen == 1 and last_kind == "LEFT_BRANCH"

    seen, confirmed, last_kind = node_confirm_step(
        "LEFT_BRANCH", 2, 1200, last_node_ms=1000, confirm_count=3,
        cooldown_ms=1500, last_kind="LEFT_BRANCH")
    assert seen == 0 and confirmed is False and last_kind is None
    print("node_confirm_step ok")


def test_decide_turn_from_sequence_and_exhaustion():
    seq = parse_sequence("R L S U")
    token, reason, detail = decide_turn_from_sequence(seq, 0, "LEFT_BRANCH", "110")
    assert token == TOKEN_RIGHT
    assert reason == "TURN_RIGHT"
    assert detail["node_index"] == 0
    assert detail["rule"] == "PHOTO_ROUTE_SEQUENCE"

    token, reason, detail = decide_turn_from_sequence(seq, 2, "CROSS", "111")
    assert token == TOKEN_STRAIGHT
    assert reason == "NODE_STRAIGHT"

    token, reason, detail = decide_turn_from_sequence(seq, 4, "CROSS", "111")
    assert token is None
    assert reason == "SEQUENCE_EXHAUSTED"
    assert detail["node_index"] == 4
    print("decide_turn_from_sequence ok")


def test_stage5_params_and_color_merge():
    assert len(INITIAL_PARAMS) == 6
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())

    merged = make_stage4_color_params({"kp": 0.5, "base_speed": 11})
    assert merged["kp"] == 0.5 and merged["base_speed"] == 11
    assert "marker_candidate_min" in merged
    assert "purple_blue_ratio_min" in merged
    assert merged["marker_candidate_min"] == STAGE4_COLOR_DEFAULTS["marker_candidate_min"]
    assert merged["purple_green_ratio_max"] == STAGE4_COLOR_DEFAULTS["purple_green_ratio_max"]
    print("stage5 params/color merge ok")


def main():
    test_parse_sequence_forms()
    test_classify_node_bits_keeps_cross_separate()
    test_node_confirm_step_counts_same_kind_only()
    test_decide_turn_from_sequence_and_exhaustion()
    test_stage5_params_and_color_merge()
    print("ALL stage5 logic tests passed")


if __name__ == "__main__":
    main()
