#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 v2 판단층(순수) + 구동 폴링 로직 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage3v2_logic.py
검증:  black_bits/branch_side/branch_confirm_step(판단) + turn_target_deg(Stage 2 재사용
       선형성) + PdController.step(부호/클램프) + advance_straight(가짜 hw, 도달/조기정지/
       zero-distance/pause) + _run_turn(가짜 hw, TURN_LEFT/RIGHT 로깅) + params 안전 메타.
       실제 회전/주행 물리(관성·미끄러짐)는 재연 불가 — 실기 do 루프로 잡는다(DECISIONS.md 5장).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.decision_log import DecisionLog                 # noqa: E402
from lib.telemetry import Telemetry                       # noqa: E402
from stages.stage3v2_linetrace_branch import (            # noqa: E402
    black_bits, branch_side, branch_confirm_step, turn_target_deg, decide_branch,
    PdController, pd_step, advance_straight, _run_turn, _maybe_follow_log,
    BASE_PIVOT_DEG_90, BASE_PIVOT_DEG_180, TURN_180_FACTOR, REASON_THROTTLE_S,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
    THR_LEFT, THR_CENTER, THR_RIGHT, TURN_LIMIT,
)
from lib.shared_params import SharedParams                # noqa: E402


def _params(**over):
    p = dict(INITIAL_PARAMS)
    p.update(over)
    return p


class FakeHw(object):
    """가짜 구동층: drive/stop/read_reflect/엔코더 누적을 물리 없이 모사."""

    def __init__(self, enc_step=12.0):
        self.el = 0.0
        self.er = 0.0
        self.enc_step = enc_step
        self.drive_cmd = None
        self.drive_history = []
        self.stopped = False
        self.reset_calls = 0
        self.reflect = (80, 80, 80)

    def reset_encoders(self):
        self.el = 0.0
        self.er = 0.0
        self.reset_calls += 1

    def read_encoders(self):
        # lib/turns.py 의 자체 테스트/가짜 hw 와 동일한 관례: drive_cmd 가 켜져 있는 동안
        # '읽을 때마다' 그 방향으로 누적된다(모터가 실제로 도는 시간=폴링 횟수를 흉내).
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

    def read_reflect(self):
        return self.reflect

    def beep_ok(self):
        pass


# --- threshold → bits --------------------------------------------------------

def test_black_bits():
    thr = (THR_LEFT, THR_CENTER, THR_RIGHT)
    assert black_bits((80, 80, 80), thr) == (0, 0, 0)
    assert black_bits((10, 80, 10), thr) == (1, 0, 1)
    assert black_bits((10, 10, 10), thr) == (1, 1, 1)
    # 경계: raw < threshold 이면 1, 같으면 0
    assert black_bits((43, 36, 42), thr) == (0, 0, 0)
    assert black_bits((42, 35, 41), thr) == (1, 1, 1)
    print("black_bits ok")


# --- 분기 방향 판정 ------------------------------------------------------------

def test_branch_side_all_patterns():
    assert branch_side((0, 1, 0)) is None          # 직선
    assert branch_side((0, 0, 0)) is None           # 선 없음
    assert branch_side((1, 0, 0)) is None           # 단독 좌 드리프트(분기 아님)
    assert branch_side((0, 0, 1)) is None           # 단독 우 드리프트(분기 아님)
    assert branch_side((1, 1, 0)) == "left"
    assert branch_side((1, 1, 1)) == "left"         # 명세: 111 은 left 로 타이브레이크
    assert branch_side((0, 1, 1)) == "right"
    print("branch_side all patterns ok")


# --- 분기 확정 카운터(순수) ------------------------------------------------------

def test_branch_confirm_step_counts_and_resets():
    branch_seen = 0
    last_turn_ms = -999999
    last_side = None
    for _ in range(3):
        branch_seen, confirmed, last_side = branch_confirm_step(
            "left", branch_seen, 1000, last_turn_ms, confirm_count=4, cooldown_ms=1500,
            last_side=last_side)
        assert confirmed is False and last_side == "left"
    branch_seen, confirmed, last_side = branch_confirm_step(
        "left", branch_seen, 1000, last_turn_ms, confirm_count=4, cooldown_ms=1500,
        last_side=last_side)
    assert confirmed is True and branch_seen == 4

    # 분기가 아니면 즉시 리셋
    branch_seen, confirmed, last_side = branch_confirm_step(
        None, branch_seen, 1000, last_turn_ms, confirm_count=4, cooldown_ms=1500,
        last_side=last_side)
    assert branch_seen == 0 and confirmed is False and last_side is None

    # 쿨다운 중이면 분기가 보여도 리셋(중복 회전 방지)
    branch_seen, confirmed, last_side = branch_confirm_step(
        "left", 3, 1000, last_turn_ms=200, confirm_count=4, cooldown_ms=1500,
        last_side="left")
    assert branch_seen == 0 and confirmed is False and last_side is None
    print("branch_confirm_step counts/resets ok")


def test_branch_confirm_step_ignores_oscillation():
    # Codex 검증(2026-07-02) 지적: 좌/우가 번갈아 흔들리면(같은 방향 연속이 아니면)
    # side is not None 이라는 이유만으로 카운트가 쌓이면 안 된다 — 마지막 방향으로
    # 오회전할 수 있는 실기 위험 케이스.
    branch_seen = 0
    last_turn_ms = -999999
    last_side = None
    sides = ["left", "right", "left", "right", "left", "right"]
    confirmed_any = False
    for side in sides:
        branch_seen, confirmed, last_side = branch_confirm_step(
            side, branch_seen, 1000, last_turn_ms, confirm_count=4, cooldown_ms=1500,
            last_side=last_side)
        assert branch_seen == 1   # 방향이 바뀔 때마다 1로 재시작
        confirmed_any = confirmed_any or confirmed
    assert confirmed_any is False
    print("branch_confirm_step ignores oscillation ok")


# --- 회전 목표각(Stage 2 lib.decide_turn.target_degrees 재사용) 선형성 --------------

def test_turn_target_deg_linear():
    p = {"BASE_PIVOT_DEG_90": BASE_PIVOT_DEG_90, "BASE_PIVOT_DEG_180": BASE_PIVOT_DEG_180,
         "turn_90_factor": 0.5, "turn_180_factor": TURN_180_FACTOR}
    assert turn_target_deg("LEFT90", p) == BASE_PIVOT_DEG_90 * 0.5
    p["turn_90_factor"] = 1.0
    assert turn_target_deg("RIGHT90", p) == BASE_PIVOT_DEG_90
    p["turn_90_factor"] = 2.0
    assert turn_target_deg("LEFT90", p) == BASE_PIVOT_DEG_90 * 2.0
    p["turn_180_factor"] = 1.1
    assert abs(turn_target_deg("UTURN180", p) - BASE_PIVOT_DEG_180 * 1.1) < 1e-9
    print("turn_target_deg linear ok")


# --- PD 조향 부호/클램프 --------------------------------------------------------

def test_pd_step_sign_and_clamp():
    pd = PdController()
    # 오른쪽이 더 검음(raw[2] < raw[0]) -> error 음수 -> 오른쪽으로 보정(turn<0 -> 왼쪽 감속 X)
    # 여기서는 부호 규약만 확인: error = raw[2]-raw[0]
    left, right, error, derivative, turn = pd_step(pd, (80, 80, 20), _params(kp=0.5))
    assert error == -60.0
    assert turn < 0
    assert left > right   # turn<0 -> left=base-turn(커짐), right=base+turn(작아짐)

    pd.reset()
    left, right, error, derivative, turn = pd_step(pd, (20, 80, 80), _params(kp=0.5))
    assert error == 60.0
    assert turn > 0
    assert right > left

    # 클램프: 큰 kp 로도 TURN_LIMIT 을 넘지 않음
    pd.reset()
    left, right, error, derivative, turn = pd_step(pd, (0, 80, 100), _params(kp=3.0))
    assert abs(turn) <= TURN_LIMIT + 1e-9
    print("pd_step sign/clamp ok")


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


# --- 회전 1회(_run_turn) — 판단(Stage2 재사용)+구동(pivot)+로깅 통합 -----------------

def test_run_turn_logs_turn_left_and_right():
    hw = FakeHw()
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                          os.path.join(_ROOT, "config", "_test_stage3v2_unused.json"),
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


# --- replay 어댑터(decide_branch) — confirm_count 별 확정 시점 재연 ----------------

def _feed(samples, params):
    state = {}
    results = []
    for sample in samples:
        action, reason, detail = decide_branch(sample, params, state)
        results.append((sample["t_ms"], action, reason, detail))
    return results


def test_decide_branch_replay_confirm_timing():
    # 왼쪽 분기(110)가 5틱 연속 보인 뒤 다시 010 으로 돌아오는 기록.
    samples = []
    for i in range(5):
        samples.append({"t_ms": i * 20, "reflect": (10, 10, 80)})   # 110
    samples.append({"t_ms": 200, "reflect": (80, 10, 80)})          # 010

    results = _feed(samples, {"branch_confirm_count": 4})
    confirmed_at = [t for t, action, reason, _ in results if action is not None]
    assert confirmed_at == [60]   # 4번째 110(t_ms=60)에서 확정(0-index 3번째 반복)
    assert results[3][2] == "BRANCH_LEFT"

    # confirm_count 를 낮추면 더 일찍 확정된다(로봇 없이 손잡이 영향 재연).
    results2 = _feed(samples, {"branch_confirm_count": 2})
    confirmed_at2 = [t for t, action, reason, _ in results2 if action is not None]
    assert confirmed_at2 == [20]
    print("decide_branch replay confirm timing ok")


def test_decide_branch_cooldown_prevents_immediate_reconfirm():
    samples = []
    for i in range(4):
        samples.append({"t_ms": i * 20, "reflect": (10, 10, 80)})  # 110, confirm_count=4 에서 확정
    for i in range(4, 8):
        samples.append({"t_ms": i * 20, "reflect": (10, 10, 80)})  # 곧바로 다시 110 지속(같은 분기)

    results = _feed(samples, {"branch_confirm_count": 4, "branch_cooldown_ms": 1500})
    confirmed = [t for t, action, reason, _ in results if action is not None]
    assert confirmed == [60]   # 쿨다운(1500ms) 안이라 재확정되지 않음
    print("decide_branch cooldown ok")


def test_decide_branch_ignores_oscillating_sides():
    # Codex 검증 재현: 좌/우가 번갈아 지속되면(같은 방향 연속이 아니면) 마지막 방향으로
    # 오확정되면 안 된다.
    samples = []
    for i in range(8):
        reflect = (10, 10, 80) if i % 2 == 0 else (80, 10, 10)  # 110/011 번갈아
        samples.append({"t_ms": i * 20, "reflect": reflect})

    results = _feed(samples, {"branch_confirm_count": 4})
    confirmed = [t for t, action, reason, _ in results if action is not None]
    assert confirmed == []
    print("decide_branch ignores oscillating sides ok")


# --- LINE_FOLLOW 주기 로깅(throttle) --------------------------------------------

def test_maybe_follow_log_throttles():
    events = []
    log = DecisionLog(telemetry=Telemetry(), sink=events.append)
    # run() 과 동일한 초기화 관례: last_follow_log 를 과거로 밀어 첫 틱은 바로 로그.
    initial = 100.0 - REASON_THROTTLE_S
    last = _maybe_follow_log(log, (80, 80, 80), 0.0, 0.0, 100.0, initial)
    assert len(events) == 1 and events[0]["event"] == "LINE_FOLLOW"
    assert last == 100.0
    # 임계시간 이내 재호출은 로그를 남기지 않음
    last2 = _maybe_follow_log(log, (80, 80, 80), 0.0, 0.0, 100.0 + 0.01, last)
    assert len(events) == 1 and last2 == last
    # 임계시간을 넘기면 다시 로그
    last3 = _maybe_follow_log(log, (80, 80, 80), 1.0, 2.0, 100.0 + REASON_THROTTLE_S + 0.01, last)
    assert len(events) == 2 and last3 > last
    print("maybe_follow_log throttles ok")


# --- params 안전 메타(6개 규칙) --------------------------------------------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 6
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    print("param safety metadata ok")


def main():
    test_black_bits()
    test_branch_side_all_patterns()
    test_branch_confirm_step_counts_and_resets()
    test_branch_confirm_step_ignores_oscillation()
    test_turn_target_deg_linear()
    test_pd_step_sign_and_clamp()
    test_advance_straight_reaches_distance_and_zero()
    test_advance_straight_stop_and_pause()
    test_run_turn_logs_turn_left_and_right()
    test_decide_branch_replay_confirm_timing()
    test_decide_branch_cooldown_prevents_immediate_reconfirm()
    test_decide_branch_ignores_oscillating_sides()
    test_maybe_follow_log_throttles()
    test_param_safety_metadata()
    print("ALL stage3v2 logic tests passed")


if __name__ == "__main__":
    main()
