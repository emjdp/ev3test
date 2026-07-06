#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v2 판단층(순수) 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_run_maze_v2_logic.py
검증:  lost_candidate_blocked(000 가드) + PD 재사용 성립 근거(pd.step 이 중앙 raw 를
       쓰지 않는다 — stage4v2 와 동일한 회귀 고정) + params 안전 메타
       (9개, v1 의 follow_gain → kp 교체).
       v1 에서 import 로 재사용하는 탐색/구동 로직(bits_node/choose_branch/
       backup_until_line/_run_turn 등)은 tests/test_run_maze_logic.py 가 이미 덮는다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.run_maze_v2 import (                            # noqa: E402
    lost_candidate_blocked, LOST_GUARD_TURN,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
)
from stages.stage3v2_linetrace_branch import PdController, TURN_LIMIT  # noqa: E402


# --- 000 가드: 보정 중(|turn| 큼)의 순간 이탈만 후보에서 제외 ---------------------

def test_lost_guard_blocks_only_000_while_turning():
    # 000 + 직전 turn 큼 → 차단 (좌/우 부호 무관)
    assert lost_candidate_blocked((0, 0, 0), LOST_GUARD_TURN + 1, LOST_GUARD_TURN) is True
    assert lost_candidate_blocked((0, 0, 0), -(LOST_GUARD_TURN + 1), LOST_GUARD_TURN) is True
    # 000 이라도 turn 이 작으면(직진 중 진짜 선 끝) 통과
    assert lost_candidate_blocked((0, 0, 0), 0.0, LOST_GUARD_TURN) is False
    assert lost_candidate_blocked((0, 0, 0), LOST_GUARD_TURN, LOST_GUARD_TURN) is False  # 경계
    # 진짜 커브/분기 bits 는 turn 이 커도 절대 막지 않는다
    assert lost_candidate_blocked((0, 1, 1), 99.0, LOST_GUARD_TURN) is False
    assert lost_candidate_blocked((1, 1, 0), 99.0, LOST_GUARD_TURN) is False
    assert lost_candidate_blocked((1, 1, 1), 99.0, LOST_GUARD_TURN) is False
    assert lost_candidate_blocked((1, 0, 1), 99.0, LOST_GUARD_TURN) is False
    print("lost_candidate_blocked 000-only guard ok")


# --- PD 재사용 성립 근거: pd.step 은 중앙 raw(raw[1])를 쓰지 않는다 -----------------
#     (중앙을 상시 컬러모드로 두고 자리에 0 을 넣는 v2/stage4v2 구조의 회귀 고정)

def test_pd_step_ignores_center_raw():
    params = {"kp": INITIAL_PARAMS["kp"], "base_speed": INITIAL_PARAMS["base_speed"]}
    a = PdController().step((60, 0, 40), params)
    b = PdController().step((60, 999, 40), params)
    assert a == b
    print("pd.step ignores center raw ok")


def test_pd_step_direction_and_clamp():
    params = {"kp": INITIAL_PARAMS["kp"], "base_speed": INITIAL_PARAMS["base_speed"]}
    # 왼쪽이 검정(좌 raw 낮음) → error 양수 → 좌바퀴 감속/우바퀴 가속(좌회전 복귀)
    left, right, error, _d, turn = PdController().step((30, 0, 70), params)
    assert error > 0 and turn > 0 and left < right
    # 극단 오차에서도 turn 은 TURN_LIMIT 으로 클램프
    _l, _r, _e, _d2, turn = PdController().step((0, 0, 100), {"kp": 3.0, "base_speed": 17})
    assert turn == TURN_LIMIT
    print("pd.step direction/clamp ok")


# --- params 안전 메타 (v1 9개에서 follow_gain → kp 교체, 키 집합 일치) ---------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 9
    assert "kp" in INITIAL_PARAMS
    assert "follow_gain" not in INITIAL_PARAMS
    assert "base_speed" in INITIAL_PARAMS
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_lost_guard_blocks_only_000_while_turning()
    test_pd_step_ignores_center_raw()
    test_pd_step_direction_and_clamp()
    test_param_safety_metadata()
    print("ALL run_maze_v2 logic tests passed")


if __name__ == "__main__":
    main()
