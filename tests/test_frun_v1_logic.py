#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frun_v1 판단층(순수) 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_frun_v1_logic.py

검증:
  (a) pick_move 우선순위(L>S>R), 출구 없음(U), D형 예외(111+최초방문→S),
      재방문 십자(is_new_cross=False→L), B형(좌우만 개방→L).
  (b) FrunMap: 새 노드 is_new=True, 같은 경로 재도착 is_new=False, arm 불일치 시
      trusted=False 강등 + 이후 is_new_cross 항상 False(호출부 계약대로).
  (c) OR-latch 순수 헬퍼 latch_bits: 110 다음 011 이 스쳐도 111 로 합산.
  (d) trail 항목 문자열 형식("L(110)" 등).
  (e) params 안전 메타(limits/max_step/order 키 일치) + v4 값 참고(복사, import 아님).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.frun_v1 import (                                  # noqa: E402
    pick_move, latch_bits, trail_entry, trail_tail, trail_append,
    FrunMap, fresh_session_state,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
    ACTIONS, STAGE_NAME, SAVE_PATH,
)
from stages.run_maze_v4 import turn_heading, abs_to_rel, opposite  # noqa: E402


# --- pick_move -----------------------------------------------------------------

def test_pick_move_priority_lsr():
    # 셋 다 열려 있어도 재방문(is_new_cross=False)이면 좌수법(L 우선).
    move, reason = pick_move(True, True, True, False)
    assert move == "L" and reason == "LEFT_HAND_PICK", (move, reason)

    move, reason = pick_move(True, False, True, False)
    assert move == "L", move

    move, reason = pick_move(False, True, True, False)
    assert move == "S", move   # L 없음 → S 우선(S>R)

    move, reason = pick_move(False, True, False, False)
    assert move == "R", move
    print("pick_move priority L>S>R ok")


def test_pick_move_dead_end():
    move, reason = pick_move(False, False, False, False)
    assert (move, reason) == ("U", "DEAD_END")
    print("pick_move dead end ok")


def test_pick_move_cross_first_visit_exception():
    # D형(111) 최초 방문 → 직진부터(CROSS_STRAIGHT_FIRST).
    move, reason = pick_move(True, True, True, True)
    assert (move, reason) == ("S", "CROSS_STRAIGHT_FIRST"), (move, reason)
    print("pick_move D-type first-visit straight-first ok")


def test_pick_move_revisit_cross_falls_back_to_left_hand():
    # 같은 111 인데 is_new_cross=False(재방문) → 좌수법으로 강등(L).
    move, reason = pick_move(True, True, True, False)
    assert (move, reason) == ("L", "LEFT_HAND_PICK"), (move, reason)
    print("pick_move revisited cross -> left-hand ok")


def test_pick_move_tee_left_first():
    # B형(좌우만 개방, 직진 막힘) → is_new_cross 값과 무관하게 항상 L.
    move, reason = pick_move(True, True, False, False)
    assert (move, reason) == ("L", "TEE_LEFT_FIRST"), (move, reason)
    move, reason = pick_move(True, True, False, True)
    assert (move, reason) == ("L", "TEE_LEFT_FIRST"), (move, reason)
    print("pick_move B-type tee left-first ok")


# --- OR-latch --------------------------------------------------------------

def test_latch_bits_or_merge():
    # 110 다음에 011 이 스쳐도 합산하면 111 (confirm 창 중 깜빡임 보강).
    latched = (1, 1, 0)
    latched = latch_bits(latched, (0, 1, 1))
    assert latched == (1, 1, 1), latched
    # 이미 111 이면 더 합산해도 그대로.
    latched = latch_bits(latched, (1, 0, 1))
    assert latched == (1, 1, 1), latched
    print("latch_bits OR merge (110+011=111) ok")


# --- trail 문자열 ------------------------------------------------------------

def test_trail_entry_format():
    assert trail_entry("L", (1, 1, 0)) == "L(110)"
    assert trail_entry("R", (0, 1, 1)) == "R(011)"
    assert trail_entry("S", (1, 1, 1)) == "S(111)"
    assert trail_entry("U", (0, 0, 0)) == "U(000)"
    print("trail_entry format ok")


def test_trail_tail_and_append_cap():
    trail = []
    for i in range(25):
        trail_append(trail, "L(110)#{}".format(i))
    assert len(trail) <= 400   # TRAIL_KEEP_MAX 이내
    tail = trail_tail(trail, limit=20)
    assert tail.count("#") == 20
    assert tail.split(" ")[-1] == "L(110)#24"   # 최신이 오른쪽 끝
    assert trail_tail([]) == ""
    print("trail_tail/trail_append ok")


# --- FrunMap ----------------------------------------------------------------

def test_frunmap_new_node_is_new():
    m = FrunMap()
    nid, is_new, mismatch = m.arrive("N", True, True, True)
    assert nid == 0 and is_new is True and mismatch is None
    assert m.trusted is True
    print("FrunMap first node is_new ok")


def test_frunmap_revisit_same_path_is_not_new():
    # node0: heading N 진입, 좌(=W)/직진(=N) 개방. arms={W,N}.
    m = FrunMap()
    nid0, is_new0, _ = m.arrive("N", True, False, True)
    assert is_new0 is True

    m.depart("S")                       # 직진으로 나간다(heading 그대로 N)
    m.apply_move("S")
    # node1: 그 다음 분기(다른 노드) — 여기선 내용은 중요치 않다.
    nid1, is_new1, _ = m.arrive("N", False, True, True)
    assert is_new1 is True and nid1 != nid0

    # node1 에서 U턴해 정확히 node0 로 되짚어간다(heading N→S).
    m.depart("U")
    m.apply_move("U")
    # node0 를 남쪽에서 진입(heading S)해 되짚어보면: 원래 좌(W)가 이번엔
    # "우"(heading S 기준 right=W) 로 보인다 — 물리적으로 일관된 재관측이므로
    # W 가 다시 확인되는 한(has_right=True) mismatch 가 아니다. 처음 보는 S
    # 방향(원래 진입 시엔 "뒤"라 못 봤다)은 새로 학습될 뿐 mismatch 가 아니다.
    nid_back, is_new_back, mismatch_back = m.arrive("S", False, True, True)
    assert nid_back == nid0
    assert is_new_back is False
    assert mismatch_back is None
    print("FrunMap revisit via same edge is_new=False ok")


def test_frunmap_leaf_uturn_returns_to_known_node():
    # 분기에서 팔로 들어가 잎(빨강/막다른길)에서 U턴해 되돌아오면, 원래 분기가
    # 새 노드(phantom)로 중복 등록되지 않고 같은 노드(is_new=False)로 인식돼야
    # 한다 — 구동층 leaf_uturn() 시퀀스(잎 arrive → U턴 → depart("S")) 재연.
    m = FrunMap()
    nid0, _, _ = m.arrive("N", True, True, True)     # 십자 최초 방문
    m.depart("S")                                     # 직진 팔로 진입
    leaf, leaf_new, _ = m.arrive("N", False, False, False)   # 잎(출구 없음)
    assert leaf_new is True and leaf != nid0
    m.apply_move("U")                                 # U턴(heading N→S)
    m.depart("S")                                     # 스텁을 되짚어 나간다
    nid_back, is_new_back, mismatch = m.arrive("S", True, True, True)
    assert nid_back == nid0
    assert is_new_back is False
    assert mismatch is None
    print("FrunMap leaf U-turn returns to known node (no phantom) ok")


def test_frunmap_mismatch_demotes_trusted_and_disables_new_cross():
    m = FrunMap()
    nid0, _, _ = m.arrive("N", True, False, True)   # arms={W,N} (좌=W 확인됨)
    m.depart("S")
    m.apply_move("S")
    nid1, is_new1, _ = m.arrive("N", False, True, True)
    assert is_new1 is True

    m.depart("U")
    m.apply_move("U")
    # 되짚어 왔는데 이번엔 이미 확인됐던 W(heading S 기준 right)가 안 보임
    # (has_right=False) — 이전에 확인된 팔이 사라졌다 = 진짜 mismatch.
    nid_back, is_new_back, mismatch = m.arrive("S", False, False, True)
    assert nid_back == nid0
    assert is_new_back is False
    assert mismatch is not None
    assert m.trusted is False

    # trusted 가 False 로 강등된 뒤에는, 완전히 새 노드를 만나도(is_new=True)
    # 호출부 계약(is_new_cross = is_new and fmap.trusted)에 의해 D형 예외가 꺼진다.
    m.depart("L")
    m.apply_move("L")
    nid2, is_new2, _ = m.arrive("W", True, True, True)
    assert is_new2 is True
    is_new_cross = is_new2 and m.trusted
    assert is_new_cross is False
    print("FrunMap mismatch demotes trusted, disables is_new_cross ok")


# --- 세션 상태 ---------------------------------------------------------------

def test_fresh_session_state():
    s = fresh_session_state()
    assert s == {"visits": 0, "goal_seen": False, "done": False, "grabbed": False, "trail": []}
    a = fresh_session_state()
    a["trail"].append("L(110)")
    assert fresh_session_state()["trail"] == []   # 독립 리스트(세션 간 누수 방지)
    print("fresh_session_state ok")


# --- params 안전 메타 --------------------------------------------------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 15
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    for name in ("left_th_node", "right_th_node", "peek_backup_mm"):
        assert name in INITIAL_PARAMS, name
    assert STAGE_NAME == "frun_v1"
    assert SAVE_PATH.endswith("frun_v1.json")
    names = [a["name"] for a in ACTIONS]
    assert "reset" in names and "read_color" in names and "read_reflect" in names
    print("param safety metadata ok")


def test_heading_helpers_reused_from_v4():
    # v4 의 순수 heading 헬퍼를 그대로 재사용(복붙 아님) — 간단 스모크.
    assert turn_heading("N", "L") == "W"
    assert abs_to_rel("N", "E") == "R"
    assert opposite("N") == "S"
    print("heading helpers reused from v4 ok")


def main():
    test_pick_move_priority_lsr()
    test_pick_move_dead_end()
    test_pick_move_cross_first_visit_exception()
    test_pick_move_revisit_cross_falls_back_to_left_hand()
    test_pick_move_tee_left_first()
    test_latch_bits_or_merge()
    test_trail_entry_format()
    test_trail_tail_and_append_cap()
    test_frunmap_new_node_is_new()
    test_frunmap_revisit_same_path_is_not_new()
    test_frunmap_leaf_uturn_returns_to_known_node()
    test_frunmap_mismatch_demotes_trusted_and_disables_new_cross()
    test_fresh_session_state()
    test_param_safety_metadata()
    test_heading_helpers_reused_from_v4()
    print("ALL frun_v1 logic tests passed")


if __name__ == "__main__":
    main()
