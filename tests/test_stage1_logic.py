#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 판단층(순수) 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage1_logic.py
검증:  classify_line / to_wheel_speeds / decide_line(PID·유실·복구 상태전이).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.stage1_linetrace import (  # noqa: E402
    classify_line,
    to_wheel_speeds,
    decide_line,
    make_state,
    INITIAL_PARAMS,
    LINE_LOST_MARGIN,
    RECOVER_SPEED,
)


def _params(**over):
    p = dict(INITIAL_PARAMS)
    p.update(over)
    return p


def test_classify_line():
    p = _params(target_reflect=35)
    # 선 위(어두움, 작은 reflect) → ON
    assert classify_line(10, p) == "ON"
    assert classify_line(35, p) == "ON"
    # target+margin 경계
    assert classify_line(35 + LINE_LOST_MARGIN - 1, p) == "ON"
    assert classify_line(35 + LINE_LOST_MARGIN, p) == "LOST"
    # 흰바닥 수준 → LOST
    assert classify_line(80, p) == "LOST"
    print("classify_line ok")


def test_to_wheel_speeds():
    # base±turn 대칭
    assert to_wheel_speeds(22, 0) == (22, 22)
    left, right = to_wheel_speeds(22, 10)
    assert left == 12 and right == 32
    assert (left + right) / 2.0 == 22
    print("to_wheel_speeds ok")


def test_pid_sign_and_clamp():
    # error>0 (reflect<target=선 쪽) 이면 turn 부호 일정, 반대쪽이면 반대 부호.
    p = _params(kp=1.0, ki=0.0, kd=0.0, turn_limit=35, target_reflect=35)
    s = make_state()
    a1, _, _ = decide_line({"reflect": 25, "t_ms": 0}, p, s)   # error=+10
    s = make_state()
    a2, _, _ = decide_line({"reflect": 45, "t_ms": 0}, p, s)   # error=-10
    assert a1["turn"] > 0 and a2["turn"] < 0
    assert (a1["turn"] > 0) != (a2["turn"] > 0)

    # turn_limit 클램프: 큰 error 라도 ±turn_limit 안.
    s = make_state()
    a3, _, _ = decide_line({"reflect": 0, "t_ms": 0}, p, s)    # error=+35, kp=1 → 35, 한계
    assert abs(a3["turn"]) <= p["turn_limit"] + 1e-9

    # 첫 틱(dt=0) 은 D항 0 → turn ~= kp*error (적분 영향 미미).
    p2 = _params(kp=1.0, ki=0.0, kd=5.0, target_reflect=35)
    s2 = make_state()
    a4, _, _ = decide_line({"reflect": 25, "t_ms": 0}, p2, s2)
    assert abs(a4["turn"] - 10.0) < 1e-6, a4["turn"]
    print("pid sign/clamp/first-tick ok")


def test_lost_and_recover_transitions():
    p = _params(target_reflect=35)
    s = make_state()

    # 선 위 → 전이 없음
    a, reason, _ = decide_line({"reflect": 20, "t_ms": 0}, p, s)
    assert a["line"] == "ON" and reason is None

    # 흰바닥 진입 → LINE_LOST 1회만, 정지 속도
    a, reason, detail = decide_line({"reflect": 80, "t_ms": 100}, p, s)
    assert a["line"] == "LOST" and reason == "LINE_LOST"
    assert a["left"] == RECOVER_SPEED and a["right"] == RECOVER_SPEED
    assert detail["lost_ms"] == 0

    # 유실 지속 → 새 이벤트 안 남김
    a, reason, _ = decide_line({"reflect": 85, "t_ms": 200}, p, s)
    assert a["line"] == "LOST" and reason is None

    # 선 재포착 → LINE_RECOVER + lost_ms 누적
    a, reason, detail = decide_line({"reflect": 20, "t_ms": 350}, p, s)
    assert a["line"] == "ON" and reason == "LINE_RECOVER"
    assert detail["lost_ms"] == 250  # 350 - 100
    print("lost/recover transitions ok")


def test_state_mutated_in_place():
    # replay.py 는 state 를 제자리로 갱신한다고 가정 → 반환값 아닌 같은 dict 갱신 확인.
    p = _params()
    s = make_state()
    decide_line({"reflect": 20, "t_ms": 0}, p, s)
    assert "pid" in s and s.get("line") == "ON"
    decide_line({"reflect": 80, "t_ms": 50}, p, s)
    assert s.get("line") == "LOST" and s.get("lost_since_ms") == 50
    print("state in-place mutation ok")


def main():
    test_classify_line()
    test_to_wheel_speeds()
    test_pid_sign_and_clamp()
    test_lost_and_recover_transitions()
    test_state_mutated_in_place()
    print("ALL stage1 logic tests passed")


if __name__ == "__main__":
    main()
