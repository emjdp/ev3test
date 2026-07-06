#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v2 판단층(순수) 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_run_maze_v2_logic.py
검증:  lost_candidate_blocked(000 가드) + PD 재사용 성립 근거(pd.step 이 중앙 raw 를
       쓰지 않는다 — stage4v2 와 동일한 회귀 고정) + v2 _run_turn 이 라이브
       turn_speed 를 쓰는지(팀 대시보드 패리티) + params 안전 메타
       (11개 = v1 9개에서 follow_gain → kp 교체 + turn_speed/node_confirm_ms 추가).
       v1 에서 import 로 재사용하는 탐색/구동 로직(bits_node/choose_branch/
       backup_until_line 등)은 tests/test_run_maze_logic.py 가 이미 덮는다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.decision_log import DecisionLog                    # noqa: E402
from lib.telemetry import Telemetry                          # noqa: E402
from lib.shared_params import SharedParams                   # noqa: E402
from stages.run_maze_v2 import (                            # noqa: E402
    lost_candidate_blocked, LOST_GUARD_TURN, _run_turn,
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


# --- v2 _run_turn: 라이브 turn_speed 사용 (팀 대시보드 패리티) -----------------------

class FakeHw(object):
    """pivot 이 요구하는 최소 구동층: 엔코더 누적 + drive_raw 기록(물리 없음)."""

    def __init__(self, enc_step=12.0):
        self.el = 0.0
        self.er = 0.0
        self.enc_step = enc_step
        self.drive_cmd = None
        self.raw_speeds = []

    def reset_encoders(self):
        self.el = 0.0
        self.er = 0.0

    def read_encoders(self):
        if self.drive_cmd is not None:
            left, right = self.drive_cmd
            if left > 0:
                self.el += self.enc_step
            elif left < 0:
                self.el -= self.enc_step
            if right > 0:
                self.er += self.enc_step
            elif right < 0:
                self.er -= self.enc_step
        return self.el, self.er

    def drive_raw(self, left_speed, right_speed):
        self.drive_cmd = (left_speed, right_speed)
        self.raw_speeds.append((left_speed, right_speed))

    def stop(self):
        self.drive_cmd = None

    def beep_ok(self):
        pass


def test_run_turn_uses_live_turn_speed():
    hw = FakeHw()
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                          os.path.join(_ROOT, "config", "_test_run_maze_v2_unused.json"),
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    events = []
    log.sink = events.append

    _run_turn(hw, "turn_left", params, log, tele,
              should_stop=lambda: False, should_pause=lambda: False, started=0.0)
    # pivot 에 들어간 회전 속도가 config 상수가 아니라 라이브 param 값이어야 한다
    speeds = set(abs(s) for pair in hw.raw_speeds for s in pair if s != 0)
    assert speeds == {INITIAL_PARAMS["turn_speed"]}, speeds
    assert hw.el < 0 and hw.er > 0   # 좌회전: 좌바퀴 후진/우바퀴 전진
    assert events[-1]["event"] == "TURN_LEFT"
    assert "error_deg" in events[-1]
    print("run_turn live turn_speed ok")


# --- params 안전 메타 (v1 9개 → kp 교체 + turn_speed/node_confirm_ms 추가 = 11개) -----

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 11
    assert "kp" in INITIAL_PARAMS
    assert "follow_gain" not in INITIAL_PARAMS
    assert "base_speed" in INITIAL_PARAMS
    # 팀 대시보드 패리티(stage3v2/stage4 와 같은 손잡이)
    assert "turn_speed" in INITIAL_PARAMS
    assert "node_confirm_ms" in INITIAL_PARAMS
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
    test_run_turn_uses_live_turn_speed()
    test_param_safety_metadata()
    print("ALL run_maze_v2 logic tests passed")


if __name__ == "__main__":
    main()
