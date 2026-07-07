#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v4 판단층(순수) 테스트 — 실제 코스를 그래프 픽스처로 시뮬레이션.

실행:  python3 tests/test_run_maze_v4_logic.py

코스(사양 원문의 트리):
  출발 → 코너 → T1(스퍼: 막다른 빨강) → T2(스퍼: 막다른 빨강)
  → 사거리 X(스퍼 2개: 막다른 빨강×2) → T3(스퍼: 막다른 빨강)
  → T4(스퍼: 막다른 빨강, 남은 팔 끝: 초록)

검증:
  (a) 빨강 6개 + 초록 1개 전부 방문(중복 없음)
  (b) 초록이 마지막 방문
  (c) 새 분기 발견 시 유턴 → 직전 분기 스퍼부터 정리하는 순서
      (PENDING_SAVED → 남은 스퍼 VISIT → WORK_CLEARED_GOTO_PENDING)
  (d) 복귀 경로가 트렁크(직행) 경로와 일치, 마커 노드를 안 지남
  (e) 우선순위를 우>좌>직으로 바꿔도 (a)(b)(d) 동일 통과

불변식(모듈 docstring 참조): 전이 주행(RETURN_TO_WORK/GOTO_PENDING/BACKTRACK) 중
처음 만나는 분기 = 목표 분기. 이 시뮬레이션은 그 불변식 그대로 — 전이 중 만난
첫 분기를 목표로 처리 — 돌기 때문에, 전 마커 방문/복귀가 통과하면 불변식 위에서
알고리즘이 완결된다는 검증이 된다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.run_maze_v4 import (                            # noqa: E402
    Explorer, MazeMap, PRIORITY,
    turn_heading, abs_to_rel, opposite, arms_from_bits,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
)
from stages.run_maze_v3 import INITIAL_PARAMS as V3_PARAMS  # noqa: E402 (키 대조용)


# =====================================================================
# 코스 그래프 픽스처 — 노드: junction/curve/terminal, 팔: 절대 방향 → 이웃 이름
# =====================================================================

COURSE = {
    "start": {"kind": "terminal", "color": "yellow", "arms": {"N": "c1"}},
    "c1":    {"kind": "curve", "arms": {"S": "start", "E": "t1"}},
    "t1":    {"kind": "junction", "arms": {"W": "c1", "N": "red1", "E": "t2"}},
    "red1":  {"kind": "terminal", "color": "red", "arms": {"S": "t1"}},
    "t2":    {"kind": "junction", "arms": {"W": "t1", "S": "red2", "E": "x"}},
    "red2":  {"kind": "terminal", "color": "red", "arms": {"N": "t2"}},
    "x":     {"kind": "junction", "arms": {"W": "t2", "N": "red3", "S": "red4", "E": "t3"}},
    "red3":  {"kind": "terminal", "color": "red", "arms": {"S": "x"}},
    "red4":  {"kind": "terminal", "color": "red", "arms": {"N": "x"}},
    "t3":    {"kind": "junction", "arms": {"W": "x", "N": "red5", "E": "t4"}},
    "red5":  {"kind": "terminal", "color": "red", "arms": {"S": "t3"}},
    "t4":    {"kind": "junction", "arms": {"W": "t3", "S": "red6", "E": "green"}},
    "red6":  {"kind": "terminal", "color": "red", "arms": {"N": "t4"}},
    "green": {"kind": "terminal", "color": "green", "arms": {"W": "t4"}},
}

REDS = set(["red1", "red2", "red3", "red4", "red5", "red6"])


def simulate(priority):
    """코스 위에서 Explorer 를 끝(집 복귀)까지 돌린다.

    반환 dict: visits(방문 마커 순서), trace(이벤트/방문 인터리브),
    home_nodes(복귀 주행이 지난 노드), id_to_name(지도 노드 id → 코스 이름), ex.
    """
    ex = Explorer(priority=priority)
    visits = []
    trace = []
    home_nodes = []
    id_to_name = {}

    node = "start"
    exit_dir = "N"                       # 출발: 노랑에서 북쪽 복도로
    prev = node
    node = COURSE[node]["arms"][exit_dir]

    for _guard in range(300):
        info = COURSE[node]
        if ex.mode == "HOME" and node != prev:
            home_nodes.append(node)

        if info["kind"] == "curve":
            # 출구 1개 강제 이동(분기 아님) — 경로 소비/상태 전이 없음.
            outs = [d for d in info["arms"] if d != opposite(ex.heading)]
            assert len(outs) == 1, "curve must have exactly one exit"
            move = abs_to_rel(ex.heading, outs[0])
            ex.apply_move(move)

        elif info["kind"] == "terminal":
            color = info["color"]
            if color == "yellow":
                assert ex.mode == "HOME", "yellow reached before exploration done"
                return {"visits": visits, "trace": trace, "home_nodes": home_nodes,
                        "id_to_name": id_to_name, "ex": ex}
            # 빨강/초록 = PROBE 팔 끝. (초록은 도착 시퀀스가 유턴으로 끝난다.)
            assert ex.mode == "PROBE", \
                "marker {} hit outside PROBE (mode={})".format(node, ex.mode)
            visits.append(node)
            trace.append(("VISIT", node))
            ex.apply_move("U")
            events = ex.on_probe_end("goal" if color == "green" else "red")
            trace.extend([("EVENT", e[0]) for e in events])

        else:                            # junction
            entry = opposite(ex.heading)
            has = {}
            for rel in ("L", "R", "S"):
                d = turn_heading(ex.heading, rel)
                has[rel] = (d in info["arms"] and d != entry)
            if ex.mode == "HOME":
                move, events = ex.on_junction_home(has["L"], has["R"], has["S"])
            else:
                move, events = ex.on_junction(has["L"], has["R"], has["S"])
            for e in events:
                trace.append(("EVENT", e[0]))
                if e[0] == "NODE_NEW_JUNCTION":
                    id_to_name[e[2]["id"]] = node
            assert move is not None
            ex.apply_move(move)

        prev = node
        node = COURSE[node]["arms"][ex.heading]

    raise AssertionError("simulation did not finish within guard limit")


# =====================================================================
# 기하 유틸 단위 테스트
# =====================================================================

def test_heading_math():
    assert turn_heading("N", "L") == "W" and turn_heading("N", "R") == "E"
    assert turn_heading("N", "U") == "S" and turn_heading("N", "S") == "N"
    assert abs_to_rel("N", "W") == "L" and abs_to_rel("N", "E") == "R"
    assert abs_to_rel("N", "N") == "S" and abs_to_rel("N", "S") == "U"
    assert opposite("E") == "W"
    assert sorted(arms_from_bits("E", True, True, True)) == ["E", "N", "S"]
    print("heading math ok")


def test_pick_arm_priority():
    m = MazeMap()
    nid = m.add_junction("N", True, True, True, None)   # arms W/E/N 전부 미탐색
    assert m.pick_arm(nid, "N", ("L", "R", "S")) == "W"
    assert m.pick_arm(nid, "N", ("R", "L", "S")) == "E"
    m.mark_cleared(nid, "W")
    m.mark_cleared(nid, "E")
    assert m.pick_arm(nid, "N", ("L", "R", "S")) == "N"
    # rel U(뒤쪽)에만 미탐색 팔이 남는 배치도 놓치지 않는다
    m.mark_cleared(nid, "N")
    m2 = m.add_junction("S", False, False, True, None)  # arm S 하나
    assert m.pick_arm(m2, "N", ("L", "R", "S")) == "S"  # heading N 기준 rel U
    print("pick_arm priority ok")


def test_home_plan_consume_and_fallback():
    ex = Explorer()
    ex.mode = "HOME"
    ex.heading = "W"
    ex.plan = [(2, "W"), (1, "S")]
    move, events = ex.on_junction_home(True, True, True)
    assert move == "S" and events[-1][0] == "RETURN_STEP"      # W에서 W = 직진
    # 다음 스텝: S 출구 = heading W 기준 L — 그런데 좌측 팔이 없으면 폴백
    move, events = ex.on_junction_home(False, True, False)
    assert events[0][0] == "RETURN_FALLBACK" and events[0][1] == "PATH_MISMATCH"
    assert move == "R"                                          # 즉석 선택(L>R>S 중 가능한 것)
    # 경로 소진 → STACK_EMPTY 폴백
    move, events = ex.on_junction_home(True, False, False)
    assert events[0][0] == "RETURN_FALLBACK" and events[0][1] == "STACK_EMPTY"
    assert move == "L"
    print("home plan consume/fallback ok")


# =====================================================================
# 코스 시뮬레이션 (a)~(e)
# =====================================================================

def _assert_full_visit(result):
    visits = result["visits"]
    assert len(visits) == 7 and len(set(visits)) == 7, visits          # (a) 중복 없음
    assert set(visits) == REDS | set(["green"]), visits                # (a) 전부 방문
    assert visits[-1] == "green", visits                               # (b) 초록 마지막


def _assert_home_direct(result):
    # (d) 복귀가 마커 노드를 안 지나고, 지도상 T4→루트 부모 체인 = 트렁크
    for n in result["home_nodes"]:
        assert n not in REDS and n != "green", result["home_nodes"]
    name_of = result["id_to_name"]
    ex = result["ex"]
    t4_id = [i for i, name in name_of.items() if name == "t4"][0]
    chain = [name_of[nid] for nid, _d in ex.map.path_to_root(t4_id)]
    assert chain == ["t4", "t3", "x", "t2", "t1"], chain


def test_course_full_exploration_lrs():
    result = simulate(("L", "R", "S"))
    _assert_full_visit(result)
    _assert_home_direct(result)

    # (c) 새 분기 발견 시: pending 저장 → 유턴 복귀 → 남은 스퍼(red4) 정리 →
    #     그 다음에야 pending 분기로 이동. 이벤트/방문 순서로 검증.
    trace = result["trace"]
    kinds = [t[1] if t[0] == "VISIT" else t[1] for t in trace]  # 이름 나열
    i_pend = kinds.index("PENDING_SAVED")
    i_goto = kinds.index("WORK_CLEARED_GOTO_PENDING")
    assert i_pend < i_goto
    between = kinds[i_pend:i_goto]
    assert "BACK_TO_WORK" in between                  # 유턴 복귀가 먼저
    assert "red4" in between, between                 # 남은 스퍼부터 정리(L>R>S 코스 기준)
    # pending 분기 이동 전에 초록이 나오면 안 된다(스퍼 정리 우선 확인)
    assert "green" not in between
    print("course exploration (L>R>S) ok, visits: {}".format(result["visits"]))


def test_course_full_exploration_rls():
    # (e) 우선순위 우>좌>직으로 바꿔도 (a)(b)(d) 동일 통과
    result = simulate(("R", "L", "S"))
    _assert_full_visit(result)
    _assert_home_direct(result)
    # pending 메커니즘도 여전히 발동한다(이 코스에선 X 사거리에서)
    kinds = [t[1] for t in result["trace"]]
    assert "PENDING_SAVED" in kinds and "WORK_CLEARED_GOTO_PENDING" in kinds
    print("course exploration (R>L>S) ok, visits: {}".format(result["visits"]))


def test_explore_done_and_plan_logged():
    result = simulate(PRIORITY)
    kinds = [t[1] for t in result["trace"]]
    assert "EXPLORE_DONE" in kinds
    assert "RETURN_PLAN" in kinds
    assert kinds.index("EXPLORE_DONE") < kinds.index("RETURN_PLAN")
    # 복귀 중 폴백이 없어야 한다(계획이 코스와 일치)
    assert "RETURN_FALLBACK" not in kinds
    print("explore done + return plan ok")


# =====================================================================
# params 안전 메타 — v3 와 완전 동일 12개(config 이식 가능해야 한다)
# =====================================================================

def test_param_safety_metadata():
    assert set(INITIAL_PARAMS.keys()) == set(V3_PARAMS.keys())
    assert len(INITIAL_PARAMS) == 12
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_heading_math()
    test_pick_arm_priority()
    test_home_plan_consume_and_fallback()
    test_course_full_exploration_lrs()
    test_course_full_exploration_rls()
    test_explore_done_and_plan_logged()
    test_param_safety_metadata()
    print("ALL run_maze_v4 logic tests passed")


if __name__ == "__main__":
    main()
