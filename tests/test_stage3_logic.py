#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 판단층(순수) + advance 구동 로직 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage3_logic.py
검증:  bits_from_raw / node_kind / classify_node / NodeDebouncer(후보·확정·debounce·
       노이즈 무시·000 처리) + decide_node(replay 어댑터) + advance(가짜 hw, 노드 확정 정지).
       실제 주행/센서 물리는 재연 불가 — 실기 do follow 루프로 잡는다(DECISIONS.md 5장).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.nodes import (                                  # noqa: E402
    bits_from_raw, bits_str, node_kind, classify_node,
    NodeDebouncer, decide_node, make_node_state,
    decide_line3, make_follow_state,
)
from stages.stage3_node_detect import (                  # noqa: E402
    advance, deg_to_mm, INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, FOLLOW_CONSTS,
)
from tools.dashboard import _telemetry_summary           # noqa: E402


def _params(**over):
    p = dict(INITIAL_PARAMS)
    p.update(over)
    return p


# --- threshold → bits 변환 ---------------------------------------------------

def test_bits_from_raw():
    # 밝음(큰 값)=0(흰 바닥), 어두움(작은 값)=1(검은 선)
    assert bits_from_raw((80, 80, 80), (40, 40, 40)) == (0, 0, 0)
    assert bits_from_raw((10, 80, 10), (40, 40, 40)) == (1, 0, 1)
    # 경계: raw < threshold 이면 1, 같으면 0
    assert bits_from_raw((40, 39, 41), (40, 40, 40)) == (0, 1, 0)
    # 센서별 threshold 가 다를 수 있다(좌/중/우 분리)
    assert bits_from_raw((6, 6, 6), (5, 7, 5)) == (0, 1, 0)
    assert bits_str((1, 1, 0)) == "110"
    print("bits_from_raw ok")


def test_node_kind_all_patterns():
    assert node_kind((0, 1, 0)) == "LINE"
    assert node_kind((0, 0, 0)) == "DEAD_END"
    assert node_kind((1, 1, 1)) == "CROSS"
    assert node_kind((1, 0, 1)) == "CROSS"
    assert node_kind((1, 1, 0)) == "CORNER_L"
    assert node_kind((1, 0, 0)) == "CORNER_L"
    assert node_kind((0, 1, 1)) == "CORNER_R"
    assert node_kind((0, 0, 1)) == "CORNER_R"
    print("node_kind all patterns ok")


def test_classify_node():
    kind, reason, detail = classify_node((0, 1, 0), {}, {})
    assert kind == "LINE" and reason is None and detail["bits"] == "010"
    kind, reason, _ = classify_node((1, 1, 1), {}, {})
    assert kind == "CROSS" and reason == "NODE_CANDIDATE"
    kind, reason, _ = classify_node((0, 0, 0), {}, {})
    assert kind == "DEAD_END" and reason == "NODE_CANDIDATE"
    print("classify_node ok")


# --- 3센서 라인트레이싱(decide_line3) -----------------------------------------

def _follow_params(**over):
    # 제어 루프가 하는 것처럼 follow 상수를 params 스냅샷에 병합한다.
    p = dict(INITIAL_PARAMS)
    p.update(FOLLOW_CONSTS)
    p.update(over)
    return p


def test_follow_straight_010():
    # 010: 좌우 raw 가 비슷 → 오차 0 → 직진(turn≈0, 좌=우).
    st = make_follow_state()
    a = decide_line3((80, 5, 80), (0, 1, 0), _follow_params(), st)
    assert abs(a["turn"]) < 1e-9
    assert a["left"] == a["right"]
    assert abs(a["line_error3"]) < 1e-9
    assert a["line"] == "ON"
    print("follow straight 010 ok")


def test_follow_left_correction_100_110():
    # 100/110: 왼쪽이 더 검음 → turn>0(왼쪽 보정), left<right.
    for bits, raw in (((1, 0, 0), (0, 80, 80)), ((1, 1, 0), (0, 0, 80))):
        st = make_follow_state()
        a = decide_line3(raw, bits, _follow_params(), st)
        assert a["turn"] > 0, bits
        assert a["left"] < a["right"], bits
        assert a["line_error3"] > 0, bits
        assert st["last_turn"] == a["turn"]      # 직전 조향 기록
    print("follow left correction 100/110 ok")


def test_follow_right_correction_001_011():
    # 001/011: 오른쪽이 더 검음 → turn<0(오른쪽 보정), left>right.
    for bits, raw in (((0, 0, 1), (80, 80, 0)), ((0, 1, 1), (80, 0, 0))):
        st = make_follow_state()
        a = decide_line3(raw, bits, _follow_params(), st)
        assert a["turn"] < 0, bits
        assert a["left"] > a["right"], bits
        assert a["line_error3"] < 0, bits
    print("follow right correction 001/011 ok")


def test_follow_node_candidate_slow_straight_111_101():
    # 111/101: 노드 후보 → 저속 직진(turn 0, 좌=우, base 보다 느림).
    base = FOLLOW_CONSTS["follow_base_speed"]
    slow = FOLLOW_CONSTS["follow_slow_speed"]
    for bits in ((1, 1, 1), (1, 0, 1)):
        st = make_follow_state()
        a = decide_line3((3, 3, 3), bits, _follow_params(), st)
        assert abs(a["turn"]) < 1e-9, bits
        assert a["left"] == a["right"] == slow, bits
        assert 0 < a["left"] < base, bits
        assert a["line"] == "NODE", bits
    print("follow node candidate slow straight 111/101 ok")


def test_follow_dead_end_000_holds_last_turn_and_stops():
    # 000: 막다른 길 후보 → 속도 0(정지) + 직전 조향(last_turn) 유지(보수).
    st = make_follow_state()
    # 먼저 왼쪽 코너로 조향해 last_turn>0 으로 만든다.
    decide_line3((0, 0, 80), (1, 1, 0), _follow_params(), st)
    held = st["last_turn"]
    assert held > 0
    a = decide_line3((80, 80, 80), (0, 0, 0), _follow_params(), st)
    assert a["left"] == 0 and a["right"] == 0          # 속도 0
    assert a["turn"] == held                            # 직전 조향 유지
    assert st["last_turn"] == held                      # 막다른 길에선 last_turn 갱신 안 함
    assert a["line"] == "LOST"
    print("follow dead end 000 holds last turn and stops ok")


# --- 후보 debounce -----------------------------------------------------------

def test_line_never_confirms():
    # 010(LINE) 만 들어오면 절대 후보/확정 없음
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    for t in range(0, 600, 20):
        status, info = deb.push((0, 1, 0), t, p)
        assert status is None
        assert info["count"] == 0
    print("line never confirms ok")


def test_candidate_then_confirm():
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    # 첫 틱: 후보 1회 알림
    s, info = deb.push((1, 1, 0), 0, p)
    assert s == "NODE_CANDIDATE" and info["kind"] == "CORNER_L" and info["count"] == 1
    # confirm_ms 미달: 조용
    s, _ = deb.push((1, 1, 0), 80, p)
    assert s is None
    # confirm_ms 도달: 확정
    s, info = deb.push((1, 1, 0), 120, p)
    assert s == "NODE_CONFIRMED" and info["duration_ms"] == 120
    print("candidate then confirm ok")


def test_node_debounce_prevents_duplicate():
    # 한 노드를 두 번 잡지 않는다(node_debounce_ms 안에는 재확정 금지).
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    deb.push((1, 1, 0), 0, p)
    assert deb.push((1, 1, 0), 120, p)[0] == "NODE_CONFIRMED"
    # 같은 패턴 지속 → 재확정 안 함
    for t in (200, 400, 800):
        assert deb.push((1, 1, 0), t, p)[0] is None

    # 가까운 '두 번째 노드'(라인 잠깐 거쳐 새 패턴)도 debounce 안이면 확정 안 됨
    deb2 = NodeDebouncer()
    deb2.push((0, 1, 1), 0, p)
    assert deb2.push((0, 1, 1), 120, p)[0] == "NODE_CONFIRMED"   # 첫 노드 확정 @120
    deb2.push((0, 1, 0), 200, p)                                  # 잠깐 라인(리셋)
    deb2.push((0, 1, 1), 260, p)                                  # 두 번째 노드 후보
    # 260+confirm=… 어쨌든 last_confirm(120) 기준 debounce 900 안 → 억제
    assert deb2.push((0, 1, 1), 380, p)[0] is None
    print("node debounce prevents duplicate ok")


def test_short_noise_ignored():
    # 짧은 흔들림(confirm_ms 미만)은 무시되고, 010 이 끼면 카운트가 리셋된다.
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    assert deb.push((1, 1, 0), 0, p)[0] == "NODE_CANDIDATE"
    assert deb.push((1, 1, 0), 40, p)[0] is None        # 40 < 100, 아직 확정 안 됨
    assert deb.push((0, 1, 0), 60, p)[0] is None        # 노이즈 끝 → 리셋
    # 새 후보로 다시 시작(이전 40ms 는 누적 안 됨)
    s, info = deb.push((1, 1, 0), 70, p)
    assert s == "NODE_CANDIDATE" and info["count"] == 1
    assert deb.push((1, 1, 0), 150, p)[0] is None       # 70~150=80 < 100
    assert deb.push((1, 1, 0), 175, p)[0] == "NODE_CONFIRMED"  # 105 >= 100
    print("short noise ignored ok")


def test_dead_end_000_handled():
    # 000(막다른 길)은 노드 후보/확정으로 다뤄진다(Stage1 LINE_LOST 와 분리).
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    s, info = deb.push((0, 0, 0), 0, p)
    assert s == "NODE_CANDIDATE" and info["kind"] == "DEAD_END"
    assert deb.push((0, 0, 0), 120, p)[0] == "NODE_CONFIRMED"
    print("dead end 000 handled ok")


def test_kind_change_restarts_candidate():
    # 노드 종류가 바뀌면 새 후보로 다시 시작(서로 다른 패턴이 confirm 으로 합쳐지지 않음).
    p = _params(node_confirm_ms=100, node_debounce_ms=900)
    deb = NodeDebouncer()
    assert deb.push((1, 1, 0), 0, p)[0] == "NODE_CANDIDATE"   # CORNER_L
    s, info = deb.push((1, 1, 1), 80, p)                      # CROSS 로 변경
    assert s == "NODE_CANDIDATE" and info["kind"] == "CROSS" and info["count"] == 1
    print("kind change restarts candidate ok")


# --- decide_node (replay 어댑터) --------------------------------------------

def test_decide_node_replay():
    st = make_node_state()
    pr = {"left_threshold": 5, "center_threshold": 5, "right_threshold": 5,
          "node_confirm_ms": 100, "node_debounce_ms": 900}
    # raw (3,3,3) → 모두 < 5 → bits 111 → CROSS 후보
    k, reason, d = decide_node({"reflect": (3, 3, 3), "t_ms": 0}, pr, st)
    assert k == "CROSS" and reason == "NODE_CANDIDATE" and d["reflect"] == [3, 3, 3]
    k, reason, d = decide_node({"reflect": (3, 3, 3), "t_ms": 120}, pr, st)
    assert reason == "NODE_CONFIRMED"
    # 개별 reflect_l/c/r 키로도 동작
    st2 = make_node_state()
    k, reason, d = decide_node(
        {"reflect_l": 80, "reflect_c": 1, "reflect_r": 80, "t_ms": 0}, pr, st2)
    assert k == "LINE" or reason is None  # 010 → 라인(노드 아님)
    print("decide_node replay ok")


# --- advance (구동, 가짜 hw) — 노드 확정 후 전진/정지 ------------------------

class FakeHw(object):
    """직진 시 호출마다 좌/우 엔코더가 같이 누적되는 가짜 구동층(물리 없음)."""

    def __init__(self, step=10.0):
        self.l = 0.0
        self.r = 0.0
        self.step = step
        self.drive_cmd = None
        self.drive_history = []
        self.stopped = False

    def drive(self, left, right):
        self.drive_cmd = (left, right)
        self.drive_history.append(self.drive_cmd)

    def stop(self):
        self.stopped = True

    def read_encoders(self):
        if self.drive_cmd is not None and self.drive_cmd != (0, 0):
            self.l += self.step
            self.r += self.step
        return self.l, self.r

    def enc_avg(self):
        el, er = self.read_encoders()
        return (abs(el) + abs(er)) / 2.0


def test_advance_reaches_and_stops():
    hw = FakeHw()
    moved = advance(hw, 20.0, should_stop=lambda: False)
    assert moved >= 20.0
    assert hw.drive_cmd is not None and hw.stopped is True
    print("advance reaches/stops ok")


def test_advance_zero_is_inplace():
    hw = FakeHw()
    moved = advance(hw, 0.0, should_stop=lambda: False)
    assert moved == 0.0 and hw.drive_cmd is None
    print("advance zero in-place ok")


def test_advance_stop_breaks_early():
    hw = FakeHw()
    moved = advance(hw, 1000.0, should_stop=lambda: True)
    # stop 이 걸리면 거의 못 가고 정지
    assert hw.stopped is True and moved < 1000.0
    print("advance stop breaks early ok")


def test_advance_pause_keeps_target():
    hw = FakeHw()
    checks = {"count": 0}

    def should_pause():
        checks["count"] += 1
        return checks["count"] <= 2

    moved = advance(hw, 20.0, should_stop=lambda: False, should_pause=should_pause)
    assert moved >= 20.0 and hw.stopped is True
    assert (0, 0) in hw.drive_history
    print("advance pause keeps target ok")


def test_node_confirm_stops_motor():
    """노드 확정 시 정지 action: 확정 status → hw.stop 이 불려야 한다(루프 로직 모사)."""
    p = _params(node_confirm_ms=100, node_debounce_ms=900, node_advance=0)
    deb = NodeDebouncer()
    hw = FakeHw()
    deb.push((1, 1, 1), 0, p)
    status, info = deb.push((1, 1, 1), 120, p)
    assert status == "NODE_CONFIRMED"
    # 루프는 확정 시 즉시 정지하고, node_advance=0 이면 제자리.
    hw.stop()
    advance(hw, p["node_advance"], should_stop=lambda: False)
    assert hw.stopped is True and hw.drive_cmd is None
    print("node confirm stops motor ok")


# --- dashboard _telemetry_summary (Stage 3 친화 요약, Stage 1 회귀) -----------

def test_dashboard_summary_stage3_keys():
    # Stage 3 telemetry 프레임의 핵심 키가 요약 문자열에 보여야 한다.
    frame = {
        "mode": "FOLLOW", "bits": "110",
        "reflect": [0, 0, 80], "reflect_l": 0, "reflect_c": 0, "reflect_r": 80,
        "node_candidate": True, "node_confirmed": False,
        "error": 80.0, "line_error3": 80.0,
        "turn": 35, "left_speed": -15, "right_speed": 55,
    }
    s = _telemetry_summary(frame)
    for token in ("bits=110", "mode=FOLLOW", "reflect_l=", "reflect_c=", "reflect_r=",
                  "node_candidate=", "node_confirmed=", "turn=",
                  "left_speed=", "right_speed="):
        assert token in s, token
    # error 또는 line_error3 중 하나는 보여야 한다.
    assert ("error=" in s) or ("line_error3=" in s)
    print("dashboard summary stage3 keys ok")


def test_dashboard_summary_stage1_not_broken():
    # Stage 1 프레임(스칼라 reflect, Stage3 키 없음)도 그대로 요약된다.
    frame = {"reflect": 6, "error": 0, "turn": 0.0, "left_speed": 20, "right_speed": 20}
    s = _telemetry_summary(frame)
    for token in ("reflect=", "error=", "turn=", "left_speed=", "right_speed="):
        assert token in s, token
    assert "bits=" not in s and "mode=" not in s        # Stage3 키는 끼지 않음
    print("dashboard summary stage1 not broken ok")


# --- params 안전 메타 --------------------------------------------------------

def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 6                      # 6개 한도 정확히
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    # deg_to_mm 단조 증가(환산계수 양수)
    assert deg_to_mm(0) == 0 and deg_to_mm(360) > deg_to_mm(180) > 0
    print("param safety metadata ok")


def main():
    test_bits_from_raw()
    test_node_kind_all_patterns()
    test_classify_node()
    test_follow_straight_010()
    test_follow_left_correction_100_110()
    test_follow_right_correction_001_011()
    test_follow_node_candidate_slow_straight_111_101()
    test_follow_dead_end_000_holds_last_turn_and_stops()
    test_line_never_confirms()
    test_candidate_then_confirm()
    test_node_debounce_prevents_duplicate()
    test_short_noise_ignored()
    test_dead_end_000_handled()
    test_kind_change_restarts_candidate()
    test_decide_node_replay()
    test_advance_reaches_and_stops()
    test_advance_zero_is_inplace()
    test_advance_stop_breaks_early()
    test_advance_pause_keeps_target()
    test_node_confirm_stops_motor()
    test_dashboard_summary_stage3_keys()
    test_dashboard_summary_stage1_not_broken()
    test_param_safety_metadata()
    print("ALL stage3 logic tests passed")


if __name__ == "__main__":
    main()
