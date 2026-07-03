#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 v2 판단층(순수) 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage4v2_logic.py
검증:  center_bit_from_color/is_marker_color/line_bits(판단) + classify_node_color/
       validate_node_colors + marker_confirm_step(연속확정/리셋/쿨다운) + decide_marker
       (replay 재연) + read_color_at_rest(가짜 hw, 다수결/조기정지) + pd_step 가운데값
       불변(명세 §0 성립 근거 회귀) + params 안전 메타.
       컬러 모드 판독 지연/검은 선 위 색 안정성은 실기로만 확인된다(명세 §11).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.stage4v2_color_follow import (                 # noqa: E402
    center_bit_from_color, is_marker_color, classify_node_color, validate_node_colors,
    side_bits, line_bits, marker_confirm_step, decide_marker, majority,
    read_color_at_rest,
    COLOR_NONE, COLOR_BLACK, COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW, COLOR_RED,
    COLOR_WHITE, COLOR_BROWN,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP,
    MARKER_COOLDOWN_MS,
)
from stages.stage3v2_linetrace_branch import (             # noqa: E402
    PdController, pd_step, THR_LEFT, THR_RIGHT,
)


def _params(**over):
    p = dict(INITIAL_PARAMS)
    p.update(over)
    return p


# --- 컬러코드 → bit / 마커색 ---------------------------------------------------

def test_center_bit_from_color():
    # 선 위(검정) + 마커색은 전부 1, 흰바닥/무효만 0.
    for color in (COLOR_BLACK, COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW, COLOR_RED, COLOR_BROWN):
        assert center_bit_from_color(color) == 1
    assert center_bit_from_color(COLOR_WHITE) == 0
    assert center_bit_from_color(COLOR_NONE) == 0
    print("center_bit_from_color ok")


def test_is_marker_color():
    for color in (COLOR_BLUE, COLOR_GREEN, COLOR_YELLOW, COLOR_RED, COLOR_BROWN):
        assert is_marker_color(color) is True
    for color in (COLOR_NONE, COLOR_BLACK, COLOR_WHITE):
        assert is_marker_color(color) is False
    print("is_marker_color ok")


def test_side_and_line_bits():
    # 경계 규약은 stage3v2 black_bits 와 동일: raw < thr 이면 1, 같으면 0.
    assert side_bits(THR_LEFT - 1, THR_RIGHT - 1, THR_LEFT, THR_RIGHT) == (1, 1)
    assert side_bits(THR_LEFT, THR_RIGHT, THR_LEFT, THR_RIGHT) == (0, 0)
    # 가운데 비트는 color 기반: 검정 선 위 = 010, 마커(파랑) 위도 가운데 1.
    assert line_bits(80, 80, COLOR_BLACK, THR_LEFT, THR_RIGHT) == (0, 1, 0)
    assert line_bits(80, 80, COLOR_BLUE, THR_LEFT, THR_RIGHT) == (0, 1, 0)
    assert line_bits(80, 80, COLOR_WHITE, THR_LEFT, THR_RIGHT) == (0, 0, 0)
    assert line_bits(10, 10, COLOR_BLACK, THR_LEFT, THR_RIGHT) == (1, 1, 1)
    print("side_bits/line_bits ok")


# --- 색 → 노드 종류 / 자기검증 ---------------------------------------------------

def test_classify_node_color():
    p = _params()   # start=4(노랑) checkpoint=2(파랑) goal=5(빨강)
    assert classify_node_color(COLOR_RED, p)[0:2] == ("GOAL", "NODE_IS_GOAL")
    assert classify_node_color(COLOR_YELLOW, p)[0:2] == ("START", "NODE_IS_START")
    assert classify_node_color(COLOR_BLUE, p)[0:2] == ("CHECKPOINT", "NODE_IS_CHECKPOINT")
    assert classify_node_color(COLOR_WHITE, p)[0:2] == ("UNKNOWN", "NODE_IS_UNKNOWN")
    assert classify_node_color(COLOR_NONE, p)[0:2] == ("UNKNOWN", "NODE_IS_UNKNOWN")
    # 우선순위 GOAL→START→CHECKPOINT: 중복 설정이면 먼저 매칭되는 쪽으로 고정.
    dup = _params(goal_color=COLOR_BLUE)
    assert classify_node_color(COLOR_BLUE, dup)[0] == "GOAL"
    print("classify_node_color ok")


def test_validate_node_colors():
    validate_node_colors(_params(), False)   # 기본값은 서로 다름 → 통과
    try:
        validate_node_colors(_params(goal_color=INITIAL_PARAMS["start_color"]), False)
        raise AssertionError("duplicate colors must raise")
    except ValueError:
        pass
    validate_node_colors(_params(goal_color=INITIAL_PARAMS["start_color"]), True)  # 개발용 우회
    try:
        validate_node_colors(_params(start_color=8), False)
        raise AssertionError("out-of-range color must raise")
    except ValueError:
        pass
    print("validate_node_colors ok")


# --- 주행 중 마커 확정 스텝(순수) -------------------------------------------------

def test_marker_confirm_step_confirms_consecutive():
    state = {}
    t = 0
    for i in range(2):
        assert marker_confirm_step(COLOR_BLUE, t + i * 15, state, 3, 1500) is None
    confirmed = marker_confirm_step(COLOR_BLUE, t + 30, state, 3, 1500)
    assert confirmed == COLOR_BLUE
    # 확정 직후엔 카운터 리셋 + 쿨다운 시작.
    assert state["marker_count"] == 0 and state["last_marker_ms"] == 30
    print("marker_confirm_step consecutive confirm ok")


def test_marker_confirm_step_resets_on_black_and_color_change():
    state = {}
    # 파랑 2회 후 검정이 끼면 리셋 → 다시 3회 연속이어야 확정.
    marker_confirm_step(COLOR_BLUE, 0, state, 3, 1500)
    marker_confirm_step(COLOR_BLUE, 15, state, 3, 1500)
    assert marker_confirm_step(COLOR_BLACK, 30, state, 3, 1500) is None
    assert state["marker_count"] == 0
    # 다른 마커색으로 바뀌면 1부터 다시 센다(직전 카운트 승계 금지).
    marker_confirm_step(COLOR_BLUE, 45, state, 3, 1500)
    marker_confirm_step(COLOR_BLUE, 60, state, 3, 1500)
    assert marker_confirm_step(COLOR_RED, 75, state, 3, 1500) is None
    assert state["marker_count"] == 1 and state["marker_last"] == COLOR_RED
    print("marker_confirm_step reset on black/color change ok")


def test_marker_confirm_step_cooldown_blocks():
    state = {}
    for i in range(3):
        confirmed = marker_confirm_step(COLOR_BLUE, i * 15, state, 3, 1500)
    assert confirmed == COLOR_BLUE
    # 쿨다운(1500ms) 안에서는 같은 마커가 계속 보여도 카운트가 쌓이지 않는다.
    for i in range(3, 10):
        assert marker_confirm_step(COLOR_BLUE, i * 15, state, 3, 1500) is None
        assert state["marker_count"] == 0
    # 쿨다운이 지나면 다시 확정 가능.
    t0 = 30 + 1500
    for i in range(2):
        assert marker_confirm_step(COLOR_BLUE, t0 + i * 15, state, 3, 1500) is None
    assert marker_confirm_step(COLOR_BLUE, t0 + 30, state, 3, 1500) == COLOR_BLUE
    print("marker_confirm_step cooldown ok")


# --- replay 어댑터(decide_marker) ------------------------------------------------

def _feed(samples, params):
    state = {}
    results = []
    for sample in samples:
        kind, reason, detail = decide_marker(sample, params, state)
        results.append((sample["t_ms"], kind, reason, detail))
    return results


def test_decide_marker_replay_confirm_timing():
    # 검은 선 주행 중 파랑 마커를 5틱 통과한 뒤 다시 검정으로 돌아오는 기록.
    samples = [{"t_ms": 0, "color": COLOR_BLACK}]
    for i in range(1, 6):
        samples.append({"t_ms": i * 20, "color": COLOR_BLUE})
    samples.append({"t_ms": 120, "color": COLOR_BLACK})

    results = _feed(samples, {"color_confirm_count": 3})
    confirmed = [(t, reason) for t, kind, reason, _ in results if kind is not None]
    assert confirmed == [(60, "NODE_IS_CHECKPOINT")]   # 3번째 파랑(t=60)에서 확정

    # confirm_count 손잡이를 낮추면 더 일찍 확정(로봇 없이 재연).
    results2 = _feed(samples, {"color_confirm_count": 2})
    confirmed2 = [t for t, kind, reason, _ in results2 if kind is not None]
    assert confirmed2 == [40]
    print("decide_marker replay confirm timing ok")


def test_decide_marker_flicker_not_confirmed():
    # 검정↔갈색이 번갈아 튀는 오독(연속이 아님)은 확정되지 않는다.
    samples = []
    for i in range(10):
        color = COLOR_BROWN if i % 2 == 0 else COLOR_BLACK
        samples.append({"t_ms": i * 20, "color": color})
    results = _feed(samples, {"color_confirm_count": 3})
    assert [t for t, kind, _, _ in results if kind is not None] == []
    print("decide_marker flicker not confirmed ok")


# --- 정지 판독(do read_color) — 가짜 hw ------------------------------------------

class FakeColorHw(object):
    def __init__(self, colors):
        self.colors = list(colors)
        self.i = 0

    def read_center_color_now(self):
        color = self.colors[min(self.i, len(self.colors) - 1)]
        self.i += 1
        return color


def test_read_color_at_rest_majority_and_stop():
    hw = FakeColorHw([COLOR_BLUE, COLOR_BLUE, COLOR_RED, COLOR_BLUE, COLOR_BLUE])
    color, reads = read_color_at_rest(hw, 5, 0)
    assert color == COLOR_BLUE and len(reads) == 5

    # majority: 동수면 먼저 다수에 도달한 값.
    assert majority([COLOR_RED, COLOR_BLUE, COLOR_RED]) == COLOR_RED

    # 조기 stop: 그때까지 읽은 것으로 집계, 하나도 못 읽으면 COLOR_NONE.
    hw = FakeColorHw([COLOR_BLUE] * 5)
    color, reads = read_color_at_rest(hw, 5, 0, should_stop=lambda: True)
    assert color == COLOR_NONE and reads == []
    print("read_color_at_rest majority/stop ok")


# --- pd_step 가운데 값 불변 (명세 §0 성립 근거의 회귀 테스트) ------------------------

def test_pd_step_ignores_center_value():
    p = {"kp": 0.5, "base_speed": 17}
    out1 = pd_step(PdController(), (20, 0, 80), p)
    out2 = pd_step(PdController(), (20, 999, 80), p)      # 가운데만 다름
    assert out1 == out2   # error=raw[2]-raw[0] — 중앙 raw 는 조향에 안 쓰인다
    print("pd_step ignores center value ok")


# --- params 안전 메타(6개 규칙) --------------------------------------------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 6
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    for name, (lo, hi) in PARAM_LIMITS.items():
        assert lo <= INITIAL_PARAMS[name] <= hi
    assert MARKER_COOLDOWN_MS > 0
    print("param safety metadata ok")


def main():
    test_center_bit_from_color()
    test_is_marker_color()
    test_side_and_line_bits()
    test_classify_node_color()
    test_validate_node_colors()
    test_marker_confirm_step_confirms_consecutive()
    test_marker_confirm_step_resets_on_black_and_color_change()
    test_marker_confirm_step_cooldown_blocks()
    test_decide_marker_replay_confirm_timing()
    test_decide_marker_flicker_not_confirmed()
    test_read_color_at_rest_majority_and_stop()
    test_pd_step_ignores_center_value()
    test_param_safety_metadata()
    print("ALL stage4v2 logic tests passed")


if __name__ == "__main__":
    main()


