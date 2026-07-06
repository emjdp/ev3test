#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v3 판단층(순수) 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_run_maze_v3_logic.py
검증:  경로 기억/접기/반전(combine_moves/push_move/invert_move) +
       복귀 replay 안전장치(return_move_available) + params 안전 메타
       (12개 = v2 11개 + goal_advance_mm).
       v1/v2 에서 import 로 재사용하는 로직은 기존 테스트가 이미 덮는다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.run_maze_v3 import (                            # noqa: E402
    combine_moves, push_move, invert_move, return_move_available,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
)


# --- U턴 상쇄 합성(회전각 mod 360) ------------------------------------------------

def test_combine_moves_table():
    # 미로 되짚기 고전 규칙과 일치해야 한다 (X,U,Z → net)
    assert combine_moves("L", "L") == "S"   # 좌로 들어갔다 좌로 나옴 = 직진과 동일
    assert combine_moves("L", "S") == "R"
    assert combine_moves("R", "R") == "S"
    assert combine_moves("R", "S") == "L"
    assert combine_moves("S", "L") == "R"
    assert combine_moves("S", "R") == "L"
    assert combine_moves("S", "S") == "U"   # 직진-U-직진 = 결국 되돌아가는 중
    print("combine_moves table ok")


# --- 경로 기록 + 접기 --------------------------------------------------------------

def test_push_move_records_plain_moves():
    path = []
    push_move(path, "R")
    push_move(path, "L")
    push_move(path, "S")
    assert path == ["R", "L", "S"]
    print("push_move plain ok")


def test_push_move_collapses_dead_end():
    # 노드 A 에서 L 로 들어감 → 막다른길 U → A 복귀 후 S 선택
    # 직행자는 A 에서 R 을 했을 것 (L,U,S = R)
    path = []
    push_move(path, "L")
    push_move(path, "U")
    push_move(path, "S")
    assert path == ["R"]
    print("push_move dead-end collapse ok")


def test_push_move_collapse_keeps_earlier_moves():
    # 앞선 노드 기록은 접기에 휘말리지 않는다
    path = []
    push_move(path, "L")     # 노드 A
    push_move(path, "L")     # 노드 B 로 들어감
    push_move(path, "U")     # 막다른길
    push_move(path, "L")     # B 복귀 후 좌선택 → B 는 직진과 동일
    assert path == ["L", "S"]
    print("push_move keeps earlier moves ok")


def test_push_move_cascade():
    # 접은 결과가 또 U 면 연쇄로 접는다:
    # [L, S, U, S] → S,U,S=U → [L, U] → 다음 R 에서 L,U,R=U → [U]
    path = []
    push_move(path, "L")
    push_move(path, "S")
    push_move(path, "U")
    push_move(path, "S")
    assert path == ["L", "U"]
    push_move(path, "R")
    assert path == ["U"]
    print("push_move cascade ok")


# --- 복귀 반전 ---------------------------------------------------------------------

def test_invert_move():
    assert invert_move("L") == "R"
    assert invert_move("R") == "L"
    assert invert_move("S") == "S"
    assert invert_move("U") == "U"
    print("invert_move ok")


def test_return_move_available():
    # L 은 좌측 bit, R 은 우측 bit, S 는 전진 후 중앙 검정 필요. U 는 항상 가능.
    assert return_move_available("L", (1, 1, 0), False) is True
    assert return_move_available("L", (0, 1, 1), True) is False
    assert return_move_available("R", (0, 1, 1), False) is True
    assert return_move_available("R", (1, 1, 0), True) is False
    assert return_move_available("S", (0, 1, 0), True) is True
    assert return_move_available("S", (1, 1, 1), False) is False
    assert return_move_available("U", (0, 0, 0), False) is True
    print("return_move_available ok")


# --- 왕복 시나리오: 기록 → 반전 replay 가 물리적으로 말이 되는지 -----------------------

def test_round_trip_replay_order():
    # 출발 → A:R → (막다른길) U → A:S(접혀서 A:L) → B:L → 도착
    path = []
    push_move(path, "R")
    push_move(path, "U")
    push_move(path, "S")     # A 접힘: R,U,S = L
    push_move(path, "L")     # B
    assert path == ["L", "L"]
    # 복귀: 뒤에서부터 pop + 반전 → B 에서 R, A 에서 R
    replay = [invert_move(path.pop()) for _ in range(len(path))]
    assert replay == ["R", "R"]
    print("round trip replay order ok")


# --- params 안전 메타 (v2 11개 + goal_advance_mm = 12개) ------------------------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 12
    assert "goal_advance_mm" in INITIAL_PARAMS
    assert "kp" in INITIAL_PARAMS and "turn_speed" in INITIAL_PARAMS
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_combine_moves_table()
    test_push_move_records_plain_moves()
    test_push_move_collapses_dead_end()
    test_push_move_collapse_keeps_earlier_moves()
    test_push_move_cascade()
    test_invert_move()
    test_return_move_available()
    test_round_trip_replay_order()
    test_param_safety_metadata()
    print("ALL run_maze_v3 logic tests passed")


if __name__ == "__main__":
    main()
