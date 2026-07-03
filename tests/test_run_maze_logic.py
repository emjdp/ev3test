#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze 판단층(순수) + 구동 폴링 로직 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_run_maze_logic.py
검증:  steer_level/line_error/bits_node/choose_branch/clamp(판단) + advance_straight
       (가짜 hw, 도달/조기정지/pause) + _run_turn(가짜 hw, TURN_LEFT/RIGHT 로깅) +
       params 안전 메타(7개, ★/⚠ 로 표시된 실기 보정값만 라이브).
       실제 회전/주행 물리(관성·미끄러짐)는 재연 불가 — 실기 do 루프로 잡는다(DECISIONS.md 5장).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.decision_log import DecisionLog                 # noqa: E402
from lib.telemetry import Telemetry                       # noqa: E402
from lib.shared_params import SharedParams                # noqa: E402
from stages.run_maze import (                              # noqa: E402
    steer_level, line_error, bits_node, choose_branch, clamp, bits_to_str,
    line_found, advance_straight, backup_until_line, _run_turn,
    COL_BLACK, COL_YELLOW, BASE_PIVOT_DEG_90,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
    LEFT_TH_DEEP, RIGHT_TH_DEEP, LEFT_TH_NODE, RIGHT_TH_NODE,
)


class FakeHw(object):
    """가짜 구동층: drive/drive_raw/stop/엔코더 누적을 물리 없이 모사(stage3v2 관례 동일)."""

    def __init__(self, enc_step=12.0):
        self.el = 0.0
        self.er = 0.0
        self.enc_step = enc_step
        self.drive_cmd = None
        self.drive_history = []
        self.stopped = False
        self.reset_calls = 0

    def reset_encoders(self):
        self.el = 0.0
        self.er = 0.0
        self.reset_calls += 1

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

    def enc_avg(self):
        el, er = self.read_encoders()
        return (abs(el) + abs(er)) / 2.0

    def drive(self, left_speed, right_speed):
        self.drive_cmd = (left_speed, right_speed)
        self.drive_history.append(("drive", left_speed, right_speed))

    def drive_raw(self, left_speed, right_speed):
        self.drive_cmd = (left_speed, right_speed)
        self.drive_history.append(("drive_raw", left_speed, right_speed))

    def stop(self):
        self.stopped = True
        self.drive_cmd = None

    def beep_ok(self):
        pass

    # backup_until_line 용 센서(기본: 전부 흰 바닥)
    def read_center_color_value(self):
        return 6  # 흰색

    def read_left_reflect(self):
        return 80

    def read_right_reflect(self):
        return 80


# --- 걸침 깊이 단계 -----------------------------------------------------------

def test_steer_level_thresholds():
    # th_shallow=69, th_deep=47(원문 좌측값)
    assert steer_level(80, 69, 47) == 0     # 흰바닥
    assert steer_level(60, 69, 47) == 1     # 얕은 걸침(반 정도)
    assert steer_level(30, 69, 47) == 2     # 깊은 걸침
    # 경계: reflect < threshold 일 때만 다음 단계
    assert steer_level(69, 69, 47) == 0
    assert steer_level(68, 69, 47) == 1
    assert steer_level(47, 69, 47) == 1
    assert steer_level(46, 69, 47) == 2
    print("steer_level thresholds ok")


# --- 계단식 조향 오차 ----------------------------------------------------------

def test_line_error_symmetry_and_deadband():
    assert line_error(0, True, 0) == 0.0     # 양쪽 흰바닥, 중앙 라인 위 -> 직진
    assert line_error(2, True, 2) == 0.0     # 양쪽 같은 깊은 단계 -> 직진
    assert line_error(1, True, 0) == 0.5     # 왼쪽 얕은 걸침만
    assert line_error(2, True, 0) == 1.0     # 왼쪽 깊은 걸침만
    assert line_error(0, True, 1) == -0.5
    assert line_error(0, True, 2) == -1.0
    # 중앙이 라인을 놓치면(=검정 아님) 복구 우선으로 폭이 커진다
    assert line_error(1, False, 0) == 2.0
    assert line_error(0, False, 1) == -2.0
    print("line_error symmetry/deadband ok")


# --- 노드 판정 bits ------------------------------------------------------------

def test_bits_node_strict_threshold():
    assert bits_node(80, COL_BLACK, 80, LEFT_TH_NODE, RIGHT_TH_NODE) == (0, 1, 0)
    assert bits_node(10, COL_BLACK, 10, LEFT_TH_NODE, RIGHT_TH_NODE) == (1, 1, 1)
    assert bits_node(10, 6, 10, LEFT_TH_NODE, RIGHT_TH_NODE) == (1, 0, 1)  # 중앙 흰색(6)
    # 경계: raw < threshold 일 때만 1
    assert bits_node(LEFT_TH_NODE, COL_BLACK, RIGHT_TH_NODE, LEFT_TH_NODE, RIGHT_TH_NODE) == (0, 1, 0)
    assert bits_node(LEFT_TH_NODE - 1, COL_BLACK, RIGHT_TH_NODE - 1,
                     LEFT_TH_NODE, RIGHT_TH_NODE) == (1, 1, 1)
    print("bits_node strict threshold ok")


# --- 분기 선택: 우 > 좌 > 직진, exclude 제외 -------------------------------------

def test_choose_branch_priority_and_exclude():
    assert choose_branch(True, True, True, None) == "R"
    assert choose_branch(True, True, False, None) == "R"
    assert choose_branch(True, False, True, None) == "L"
    assert choose_branch(False, False, True, None) == "S"
    assert choose_branch(False, False, False, None) == "U"
    # exclude: 진입 방향의 반대(왔던 길)를 뺀다
    assert choose_branch(True, True, True, "R") == "L"
    assert choose_branch(True, True, True, "L") == "R"
    # exclude 해도 다른 옵션이 없으면 유턴
    assert choose_branch(True, False, False, "L") == "U"
    print("choose_branch priority/exclude ok")


def test_clamp_and_bits_to_str():
    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
    assert bits_to_str((1, 0, 1)) == "101"
    assert bits_to_str((0, 0, 0)) == "000"
    print("clamp/bits_to_str ok")


# --- 엔코더 직진 전진(advance_straight) -----------------------------------------

def test_advance_straight_reaches_distance_and_zero():
    hw = FakeHw()
    actual = advance_straight(hw, 50.0, 15, should_stop=lambda: False)
    assert actual >= 50.0
    assert hw.reset_calls == 1 and hw.stopped is True

    hw = FakeHw()
    actual = advance_straight(hw, 0, 15, should_stop=lambda: False)
    assert actual == 0.0 and hw.drive_history == [] and hw.stopped is True
    print("advance_straight reach/zero ok")


def test_advance_straight_stop_and_pause():
    hw = FakeHw()
    actual = advance_straight(hw, 1000.0, 15, should_stop=lambda: True)
    assert actual == 0.0 and hw.stopped is True and hw.drive_history == []

    hw = FakeHw()
    checks = {"n": 0}

    def should_pause():
        checks["n"] += 1
        return checks["n"] <= 2

    actual = advance_straight(hw, 50.0, 15, should_stop=lambda: False, should_pause=should_pause)
    assert actual >= 50.0
    assert ("drive", 0, 0) in hw.drive_history
    print("advance_straight stop/pause ok")


# --- 선 유실(000) 후진 복구 ------------------------------------------------------

def test_line_found_conditions():
    # 중앙 검정이면 발견
    assert line_found(80, COL_BLACK, 80, 69, 67) is True
    # 좌/우가 조향 임계값 아래면 발견
    assert line_found(50, 6, 80, 69, 67) is True
    assert line_found(80, 6, 50, 69, 67) is True
    # 전부 흰 바닥이면 미발견
    assert line_found(80, 6, 80, 69, 67) is False
    # 경계: reflect < threshold 일 때만
    assert line_found(69, 6, 67, 69, 67) is False
    assert line_found(68, 6, 80, 69, 67) is True
    print("line_found conditions ok")


class LineAppearsHw(FakeHw):
    """센서 판독 appear_after 회 이후 중앙에 검정 선이 나타나는 가짜 hw(후진 복구 모사)."""

    def __init__(self, appear_after=3, enc_step=12.0):
        FakeHw.__init__(self, enc_step=enc_step)
        self.appear_after = appear_after
        self.color_reads = 0

    def read_center_color_value(self):
        self.color_reads += 1
        return COL_BLACK if self.color_reads > self.appear_after else 6


def test_backup_until_line_finds_line():
    hw = LineAppearsHw(appear_after=3)
    found, dist = backup_until_line(hw, 100.0, 10, 69, 67, should_stop=lambda: False)
    assert found is True
    assert hw.stopped is True
    assert hw.drive_history[0] == ("drive", -10, -10)   # 후진으로 출발
    assert dist < 100.0                                  # 최대 거리 전에 발견
    print("backup_until_line finds line ok")


def test_backup_until_line_gives_up_at_max():
    hw = FakeHw()   # 센서가 계속 흰 바닥
    found, dist = backup_until_line(hw, 60.0, 10, 69, 67, should_stop=lambda: False)
    assert found is False
    assert dist >= 60.0
    assert hw.stopped is True
    print("backup_until_line gives up at max ok")


def test_backup_until_line_stop_and_zero():
    hw = FakeHw()
    found, dist = backup_until_line(hw, 100.0, 10, 69, 67, should_stop=lambda: True)
    assert found is False and dist == 0.0 and hw.drive_history == []

    hw = FakeHw()
    found, dist = backup_until_line(hw, 0, 10, 69, 67)
    assert found is False and dist == 0.0 and hw.stopped is True
    print("backup_until_line stop/zero ok")


# --- 회전 1회(_run_turn) — 판단(Stage2 재사용)+구동(pivot)+로깅 통합 -----------------

def test_run_turn_logs_turn_left_and_right():
    hw = FakeHw()
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                          os.path.join(_ROOT, "config", "_test_run_maze_unused.json"),
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    events = []
    log.sink = events.append

    actual = _run_turn(hw, "turn_left", params, log, tele,
                       should_stop=lambda: False, should_pause=lambda: False, started=0.0)
    assert actual >= BASE_PIVOT_DEG_90 * INITIAL_PARAMS["turn_90_factor"]
    assert hw.el < 0 and hw.er > 0   # 좌회전: 좌바퀴 후진/우바퀴 전진
    assert events[-1]["event"] == "TURN_LEFT"
    assert "error_deg" in events[-1]

    hw = FakeHw()
    _run_turn(hw, "turn_right", params, log, tele,
             should_stop=lambda: False, should_pause=lambda: False, started=0.0)
    assert hw.el > 0 and hw.er < 0  # 우회전은 반대
    assert events[-1]["event"] == "TURN_RIGHT"
    print("run_turn TURN_LEFT/RIGHT ok")


# --- params 안전 메타(★/⚠ 7개 + base_speed/follow_gain 실기 요청 = 9개만 라이브) -----

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 9
    assert "base_speed" in INITIAL_PARAMS
    assert "follow_gain" in INITIAL_PARAMS
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_steer_level_thresholds()
    test_line_error_symmetry_and_deadband()
    test_bits_node_strict_threshold()
    test_choose_branch_priority_and_exclude()
    test_clamp_and_bits_to_str()
    test_advance_straight_reaches_distance_and_zero()
    test_advance_straight_stop_and_pause()
    test_line_found_conditions()
    test_backup_until_line_finds_line()
    test_backup_until_line_gives_up_at_max()
    test_backup_until_line_stop_and_zero()
    test_run_turn_logs_turn_left_and_right()
    test_param_safety_metadata()
    print("ALL run_maze logic tests passed")


if __name__ == "__main__":
    main()
