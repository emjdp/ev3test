#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage5_integration 판단층(시퀀스 소비/강제 U턴/replay 어댑터) 테스트."""

import os
import sys


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.stage5_integration import (                        # noqa: E402
    CONFIRMED_PARAMS, INITIAL_PARAMS, MAX_STEP, PARAM_LIMITS, PARAM_ORDER,
    UI_STEP, ParamsView, TOKEN_TO_CMD, VALID_TOKENS,
    decide_sequence_turn, decide_turn_from_sequence, parse_seq,
)


def test_parse_seq_formats():
    assert parse_seq("L S R U") == ["L", "S", "R", "U"]
    assert parse_seq("LSRU") == ["L", "S", "R", "U"]
    assert parse_seq("l,s,r,u") == ["L", "S", "R", "U"]
    assert parse_seq("") == []
    try:
        parse_seq("LXR")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid token must raise ValueError")


def test_jct_tokens_map_to_reasons():
    seq = parse_seq("LSRU")
    expected = {0: ("L", "TURN_LEFT"), 1: ("S", "NODE_STRAIGHT"),
                2: ("R", "TURN_RIGHT"), 3: ("U", "UTURN")}
    for idx, (want_token, want_reason) in expected.items():
        token, reason, detail = decide_turn_from_sequence("JCT", seq, idx)
        assert token == want_token, (idx, token)
        assert reason == want_reason, (idx, reason)
        assert detail["rule"] == "FROM_SEQUENCE"
        assert detail["node_index"] == idx
        assert detail["selected"] == want_token


def test_leaf_with_uturn_token_is_normal():
    token, reason, detail = decide_turn_from_sequence("LEAF", ["U"], 0)
    assert token == "U"
    assert reason == "UTURN"
    assert "forced_from" not in detail


def test_leaf_forces_uturn_on_other_tokens():
    for wrong in ("L", "S", "R"):
        token, reason, detail = decide_turn_from_sequence("LEAF", [wrong], 0)
        assert token == "U", (wrong, token)
        assert reason == "LEAF_FORCE_UTURN"
        assert detail["forced_from"] == wrong
        assert detail["selected"] == "U"


def test_sequence_exhausted():
    token, reason, detail = decide_turn_from_sequence("JCT", [], 0)
    assert token is None
    assert reason == "SEQUENCE_EXHAUSTED"
    assert detail["node_index"] == 0

    token, reason, _ = decide_turn_from_sequence("LEAF", ["L"], 1)
    assert token is None
    assert reason == "SEQUENCE_EXHAUSTED"


def test_one_token_per_node_consumption():
    seq = parse_seq("LRSU")
    idx = 0
    seen = []
    while True:
        token, reason, _ = decide_turn_from_sequence("JCT", seq, idx)
        if token is None:
            break
        seen.append(token)
        idx += 1
    assert seen == ["L", "R", "S", "U"]
    assert idx == 4


def test_params_meta_consistent():
    keys = set(INITIAL_PARAMS)
    assert keys == set(PARAM_LIMITS)
    assert keys == set(MAX_STEP)
    assert keys == set(UI_STEP)
    assert keys == set(PARAM_ORDER)
    # 하위 스테이지 확정값은 라이브 param 과 겹치지 않는다(재노출 금지).
    assert not (keys & set(CONFIRMED_PARAMS))
    # 회전 실행에 쓰는 토큰은 전부 유효 토큰이다.
    assert set(TOKEN_TO_CMD) < set(VALID_TOKENS)


def test_params_view_merges_confirmed_and_live():
    class FakeShared(object):
        def snapshot(self):
            return {"base_speed": 12}

        def rev(self):
            return 7

    view = ParamsView(FakeShared(), {"kp": 0.22, "base_speed": 99})
    snap = view.snapshot()
    assert snap["kp"] == 0.22
    assert snap["base_speed"] == 12  # 라이브가 확정값보다 우선
    assert view.rev() == 7


def test_replay_decider_consumes_sequence():
    params = {"seq": "RL", "branch_confirm_count": 1, "branch_advance_mm": 30}
    state = {}
    # 좌 분기 bits(110) — thresholds 기본(43/36/42)보다 낮은 반사광 = 흑.
    left_branch = {"reflect": [10, 10, 60], "t_ms": 5000}
    follow = {"reflect": [60, 10, 60], "t_ms": 5100}

    token, reason, detail = decide_sequence_turn(left_branch, params, state)
    # 감지는 좌 분기지만 시퀀스 첫 토큰 R 을 따른다(불일치는 detail 로 진단).
    assert token == "R"
    assert reason == "TURN_RIGHT"
    assert detail["bits"] == "110"
    assert detail["detected"] == "BRANCH_LEFT"
    assert state["seq_idx"] == 1

    # 분기가 아니면 소비하지 않는다.
    token, reason, _ = decide_sequence_turn(follow, params, state)
    assert token is None
    assert state["seq_idx"] == 1

    # 쿨다운(1500ms) 이후 두 번째 분기 → 두 번째 토큰 L.
    second = {"reflect": [10, 10, 60], "t_ms": 9000}
    token, reason, _ = decide_sequence_turn(second, params, state)
    assert token == "L"
    assert reason == "TURN_LEFT"
    assert state["seq_idx"] == 2

    # 시퀀스 고갈 후 세 번째 분기 → SEQUENCE_EXHAUSTED, 소비 없음.
    third = {"reflect": [10, 10, 60], "t_ms": 13000}
    token, reason, _ = decide_sequence_turn(third, params, state)
    assert token is None
    assert reason == "SEQUENCE_EXHAUSTED"
    assert state["seq_idx"] == 2


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("ok - {}".format(test.__name__))
    print("{} tests passed".format(len(tests)))


if __name__ == "__main__":
    main()
