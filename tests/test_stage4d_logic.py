#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4-D 관문(1단계) 판단층 + bench 폴링 로직 단위 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_stage4d_logic.py
검증:  blind_budget_ok(go/no-go 경계, max 기준) + read_color_slot/bench_toggle(가짜 hw —
       왕복 횟수/색 기록/zero_reads/조기 정지) + params 안전 메타.
       실제 모드 전환 소요(ms)는 커널 드라이버 고유라 **PC 재연 불가** — §7-0b 실기
       `do bench_toggle` 전용이다(명세 §9). 여기서는 계측/집계 로직만 검증한다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from stages.stage4d_mode_interleave import (      # noqa: E402
    blind_budget_ok, read_color_slot, bench_toggle,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP,
    ACTIONS, BLIND_BUDGET_MS, BENCH_K,
)


class FakeColorHw(object):
    """가짜 구동층: 모드 전환/판독을 물리 없이 모사(호출 횟수만 기록)."""

    def __init__(self, colors=None):
        self.colors = list(colors) if colors else []
        self.color_calls = 0
        self.restore_calls = 0
        self.reflect_calls = 0
        self.seen_settle = []
        self.seen_dummy = []

    def read_center_color(self, settle_s, dummy_reads):
        self.color_calls += 1
        self.seen_settle.append(settle_s)
        self.seen_dummy.append(dummy_reads)
        if self.colors:
            return self.colors.pop(0)
        return 5

    def restore_reflect_mode(self, settle_s):
        self.restore_calls += 1
        self.seen_settle.append(settle_s)

    def read_center_reflect(self):
        self.reflect_calls += 1
        return 42


def test_blind_budget_ok_boundaries():
    # max 기준(명세 §7-0b): max <= budget 이면 go. avg 는 판정에 안 쓴다.
    assert blind_budget_ok(50.0, 80.0, 80) is True     # 경계 = go
    assert blind_budget_ok(50.0, 80.1, 80) is False    # 최악 슬롯 초과 = no-go
    assert blind_budget_ok(79.9, 79.9, 80) is True
    assert blind_budget_ok(0.0, 0.0, 80) is True


def test_read_color_slot_round_trip():
    hw = FakeColorHw(colors=[3])
    color, slot_ms = read_color_slot(hw, 0.0, 2)
    assert color == 3
    assert slot_ms >= 0.0
    # 왕복 1회 = 컬러 판독 1 + 반사광 복귀 1 + 복귀 후 반사광 판독 1.
    assert hw.color_calls == 1
    assert hw.restore_calls == 1
    assert hw.reflect_calls == 1
    # settle 은 왕복 양쪽(진입/복귀)에 같은 값으로 지불된다(명세 §3).
    assert hw.seen_settle == [0.0, 0.0]
    assert hw.seen_dummy == [2]


def test_bench_toggle_counts_and_zero_reads():
    hw = FakeColorHw(colors=[5, 0, 5, 0, 5])
    result = bench_toggle(hw, 5, 0.0, 2)
    assert result["k"] == 5
    assert hw.color_calls == 5 and hw.restore_calls == 5
    assert result["colors"] == [5, 0, 5, 0, 5]
    assert result["zero_reads"] == 2                   # 색=0 = 전환 직후 무효값 신호
    assert result["avg_ms"] >= 0.0
    assert result["max_ms"] >= result["avg_ms"]


def test_bench_toggle_stops_early():
    hw = FakeColorHw()
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] > 2                          # 3번째 검사부터 stop

    result = bench_toggle(hw, 10, 0.0, 0, should_stop=should_stop)
    assert result["k"] == 2                            # 2왕복만 수행하고 중단
    assert len(result["colors"]) == 2


def test_bench_toggle_zero_trips():
    hw = FakeColorHw()
    result = bench_toggle(hw, 10, 0.0, 0, should_stop=lambda: True)
    assert result["k"] == 0
    assert result["avg_ms"] == 0.0 and result["max_ms"] == 0.0
    # k=0 은 호출부(do_bench)에서 go 로 치지 않는다(run() 의 result["k"] > 0 조건).


def test_bench_toggle_on_trip_hook():
    hw = FakeColorHw()
    seen = []
    bench_toggle(hw, 3, 0.0, 0, on_trip=lambda i, c, ms: seen.append((i, c)))
    assert [s[0] for s in seen] == [0, 1, 2]
    assert [s[1] for s in seen] == [5, 5, 5]


def test_params_safety_meta():
    # 라이브 params 는 6개 이하(LIVE_TUNING 규칙), 메타가 전부 채워져 있어야 한다.
    assert len(INITIAL_PARAMS) <= 6
    assert set(INITIAL_PARAMS) == set(PARAM_LIMITS) == set(MAX_STEP)
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS)
    assert set(UI_STEP) == set(INITIAL_PARAMS)
    for name, value in INITIAL_PARAMS.items():
        lo, hi = PARAM_LIMITS[name]
        assert lo <= value <= hi, name
        assert MAX_STEP[name] > 0, name
    # §7-0b 절차(0 부터 +20 씩)와 손잡이 보폭이 일치해야 한다.
    assert MAX_STEP["switch_settle_ms"] == 20
    assert BLIND_BUDGET_MS == 80 and BENCH_K == 20


def test_actions_manifest():
    names = [a["name"] for a in ACTIONS]
    assert names == ["bench_toggle", "read_color", "read_reflect"]


def main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS {}".format(name))
        except AssertionError as exc:
            failed += 1
            print("FAIL {}: {}".format(name, exc))
    print("{} tests, {} failed".format(len(tests), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
