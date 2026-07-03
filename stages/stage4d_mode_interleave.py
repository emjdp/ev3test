#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4-D 관문(1단계) — 반사광↔컬러 모드 전환 벤치마크 (`do bench_toggle`).

명세: docs/specs/stage4d_mode_interleave.md §1(1단계)/§7-0b.
후보 D(반사광↔컬러 고속 교대)는 4개 브릿지 후보 중 위험이 가장 커서 **구현 전
go/no-go 관문**이 있다. 이 파일은 그 관문까지만 구현한다:

  - `do bench_toggle` : 정지 상태에서 반사광→컬러→반사광 왕복을 BENCH_K 회 실측 →
                        평균/최대 ms + 전환 직후 무효값(0) 횟수 → `BENCH_TOGGLE` 이벤트
                        (GO/NO_GO 판정 포함, max 기준 — 최악 슬롯이 선을 놓치게 한다).
  - `do read_color`   : 현재 위치에서 색 1회(전환 왕복 포함) + 직전 반사광 → `COLOR_READ`.
  - `do read_reflect` : 좌/중/우 반사광 1회 → `REFLECT_READ`. (§7-0a 공통 선결 실측용)

**교대 루프 본체(SlotScheduler/SlotColorConfirmer/주행)는 여기 없다** — 실기 bench 가
go 를 통과한 뒤에만 이 파일에 이어서 구현한다(§10: "no-go 면 여기서 종료, C 로").
이 스크립트는 주행하지 않는다(모터 명령 없음, 로봇은 손으로 마커 위에 놓고 잰다).

독립 실행(브릭):  python3 stages/stage4d_mode_interleave.py
문법 점검(PC):    python3 -m py_compile stages/stage4d_mode_interleave.py lib/*.py
판단층 테스트(PC): python3 tests/test_stage4d_logic.py

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다. 정지는 네트워크 stop / Ctrl-C.
"""

import os
import sys
import threading
import time

# stages/ 에서 단독 실행해도 lib/ 를 import 하도록 저장소 루트를 경로에 넣는다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams                       # noqa: E402
from lib.telemetry import Telemetry                               # noqa: E402
from lib.decision_log import DecisionLog                          # noqa: E402
from lib.tuning_server import TuningServer                        # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# 관문 단계 라이브 params 는 2개만 노출한다(명세 §7-0b 가 만지는 손잡이).
# 나머지 4개(interleave_every_n/color_confirm_samples/blind_speed_scale/base_speed)는
# 교대 루프(2단계) 구현 시점에 추가한다 — 지금 넣으면 죽은 손잡이만 는다.
INITIAL_PARAMS = {
    "switch_settle_ms": 0,     # §7-0b: 0 부터 +20 씩 올리며 "색이 유효한 최소 settle" 탐색
    "color_dummy_reads": 2,    # 전환 후 버리는 읽기 수. settle 올려도 첫 값 튀면 ↑
}

PARAM_LIMITS = {
    "switch_settle_ms": (0, 300),
    "color_dummy_reads": (0, 6),
}

MAX_STEP = {
    "switch_settle_ms": 20,
    "color_dummy_reads": 1,
}

UI_STEP = {
    "switch_settle_ms": 20,
    "color_dummy_reads": 1,
}
UNITS = {
    "switch_settle_ms": "ms",
}
PARAM_ORDER = ["switch_settle_ms", "color_dummy_reads"]

# --- config 상수(라이브 아님, 명세 §3) ---
BLIND_BUDGET_MS = 80    # 슬롯 1회 허용 blind 시간. go/no-go 기준(max 기준, §7-0b)
BENCH_K = 20            # bench 왕복 횟수
LOOP_DELAY_MS = 50      # 대기 루프 주기(주행 없음 — telemetry 갱신용)

SAVE_PATH = os.path.join(_ROOT, "config", "stage4d_mode_interleave.json")
STAGE_NAME = "stage4d_mode_interleave"

ACTIONS = [
    {"name": "bench_toggle", "label": "Bench Toggle (go/no-go)"},
    {"name": "read_color", "label": "Read Color 1x"},
    {"name": "read_reflect", "label": "Read Reflect LCR"},
]


# =====================================================================
# 판단층 (순수, ev3dev2/시간/모터 없음) — PC 테스트 가능
# =====================================================================

def blind_budget_ok(avg_ms, max_ms, budget_ms):
    """go/no-go 판정(순수, 명세 §2/§7-0b). 초과 판정은 **max 기준** — 최악 슬롯 한 번이
    곡선에서 선을 놓치게 하므로 평균이 좋아도 max 가 예산을 넘으면 no-go 다.
    avg_ms 는 판정에 쓰지 않지만 기록/보고용 시그니처(명세 §2)를 유지한다."""
    return max_ms <= budget_ms


# =====================================================================
# 구동층 (hw 경유 — ev3dev2 직접 의존 없음, 가짜 hw 로 PC 테스트 가능)
# =====================================================================

def read_color_slot(hw, settle_s, dummy_reads):
    """컬러 슬롯 1회: 컬러 전환 → settle/dummy → color 1샘플 → 반사광 복귀(+판독 1회).

    반환 (color, slot_ms). slot_ms 가 곧 라인추종이 눈 감는 시간(blind) — 명세 §2.
    settle 은 왕복 양쪽(컬러 진입/반사광 복귀)에 지불한다(명세 §3 "슬롯당 왕복 2회").
    """
    t0 = time.monotonic()
    color = hw.read_center_color(settle_s, dummy_reads)
    hw.restore_reflect_mode(settle_s)
    hw.read_center_reflect()  # 왕복 완결: 복귀 후 반사광 유효 판독 1회 포함
    slot_ms = (time.monotonic() - t0) * 1000.0
    return color, slot_ms


def bench_toggle(hw, k, settle_s, dummy_reads, should_stop=None, on_trip=None):
    """반사광↔컬러 왕복 k회 실측(명세 §2). 정지 상태 전용 — 주행 없음.

    반환 dict: avg_ms/max_ms/k(실제 수행 횟수)/colors(왕복별 판독색)/zero_reads(색=0 횟수).
    zero_reads>0 이면 settle/dummy 부족 신호(§7-0b "색이 유효하게 나오는 최소 settle").
    on_trip(i, color, slot_ms) 은 왕복마다 telemetry 를 흘리는 훅(선택).
    """
    times = []
    colors = []
    for i in range(int(k)):
        if should_stop is not None and should_stop():
            break
        color, slot_ms = read_color_slot(hw, settle_s, dummy_reads)
        times.append(slot_ms)
        colors.append(color)
        if on_trip is not None:
            on_trip(i, color, slot_ms)
    if not times:
        return {"avg_ms": 0.0, "max_ms": 0.0, "k": 0, "colors": [], "zero_reads": 0}
    return {
        "avg_ms": round(sum(times) / len(times), 1),
        "max_ms": round(max(times), 1),
        "k": len(times),
        "colors": colors,
        "zero_reads": len([c for c in colors if c == 0]),
    }


# =====================================================================
# telemetry 헬퍼 — 한 곳에서만 프레임을 만든다.
# =====================================================================

_TELEMETRY_DEFAULTS = {
    "mode": "idle",
    "paused": False,
    "reflect": [0, 0, 0],
    "color": None,
    "slot_ms": 0.0,
    "bench_avg_ms": None,
    "bench_max_ms": None,
    "bench_k": 0,
    "bench_go": None,
    "budget_ms": BLIND_BUDGET_MS,
}


def _publish(tele, params, started, **overrides):
    now = time.monotonic()
    frame = dict(_TELEMETRY_DEFAULTS)
    frame["t_ms"] = int((now - started) * 1000)
    frame["param_rev"] = params.rev()
    frame["running"] = True
    frame.update(overrides)
    tele.publish(frame)


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
#   주행 없음. do bench_toggle / read_color / read_reflect 트리거만 처리한다.
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"action": None}
    plock = threading.Lock()
    # 직전 bench 결과 — 이후 모든 telemetry 프레임에 계속 실어 대시보드에서 보이게 한다.
    last_bench = {"avg_ms": None, "max_ms": None, "k": 0, "go": None}

    def on_stop(source):
        # 네트워크 thread 에서 호출 — 플래그만 세팅(제어 루프가 안전한 시점에 처리).
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "idle"}

    def on_do(action, args):
        # 네트워크 thread 에서 호출 — 하드웨어를 여기서 만지지 않고 제어 루프에 넘긴다(비차단).
        if action not in ("bench_toggle", "read_color", "read_reflect"):
            return {"error": "unknown action: {}".format(action)}
        with plock:
            pending["action"] = action
        return {"queued": action}

    def should_stop():
        return stop_flag["on"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    started = time.monotonic()

    def bench_frame(**overrides):
        base = {"bench_avg_ms": last_bench["avg_ms"], "bench_max_ms": last_bench["max_ms"],
                "bench_k": last_bench["k"], "bench_go": last_bench["go"]}
        base.update(overrides)
        _publish(tele, params, started, **base)

    def do_bench():
        snap = params.snapshot()
        settle_ms = snap["switch_settle_ms"]
        dummy = int(snap["color_dummy_reads"])

        def on_trip(i, color, slot_ms):
            bench_frame(mode="bench", color=color, slot_ms=round(slot_ms, 1))

        result = bench_toggle(hw, BENCH_K, settle_ms / 1000.0, dummy,
                              should_stop=should_stop, on_trip=on_trip)
        go = result["k"] > 0 and blind_budget_ok(result["avg_ms"], result["max_ms"],
                                                 BLIND_BUDGET_MS)
        last_bench["avg_ms"] = result["avg_ms"]
        last_bench["max_ms"] = result["max_ms"]
        last_bench["k"] = result["k"]
        last_bench["go"] = go
        log.log("BENCH_TOGGLE", "GO" if go else "NO_GO",
                avg_ms=result["avg_ms"], max_ms=result["max_ms"], k=result["k"],
                settle_ms=settle_ms, dummy=dummy,
                zero_reads=result["zero_reads"], budget_ms=BLIND_BUDGET_MS)
        print("BENCH_TOGGLE k={} avg={}ms max={}ms budget={}ms -> {}".format(
            result["k"], result["avg_ms"], result["max_ms"], BLIND_BUDGET_MS,
            "GO" if go else "NO-GO"))
        if result["zero_reads"] > 0:
            print("  주의: 색=0(무효) {}회 — settle/dummy 부족 신호. "
                  "switch_settle_ms +20 후 재실행 (§7-0b).".format(result["zero_reads"]))
        print("  colors={}".format(result["colors"]))
        bench_frame(mode="idle")
        hw.beep_ok()

    def do_read_color():
        snap = params.snapshot()
        # 색 읽기 직전 반사광(빈 바닥 판별용, stage4_color.md §5) — 반사광 모드일 때 읽는다.
        reflect = hw.read_center_reflect()
        color, slot_ms = read_color_slot(hw, snap["switch_settle_ms"] / 1000.0,
                                         int(snap["color_dummy_reads"]))
        log.log("COLOR_READ", "DO_TRIGGER", color=color, reflect=reflect,
                slot_ms=round(slot_ms, 1), settle_ms=snap["switch_settle_ms"],
                dummy=int(snap["color_dummy_reads"]), method="at_rest")
        print("COLOR_READ color={} reflect={} slot_ms={}".format(
            color, reflect, round(slot_ms, 1)))
        bench_frame(mode="read_color", color=color, slot_ms=round(slot_ms, 1),
                    reflect=[0, reflect, 0])

    def do_read_reflect():
        raw = hw.read_reflect()
        log.log("REFLECT_READ", "DO_TRIGGER", reflect=list(raw))
        print("REFLECT_READ l={} c={} r={}".format(raw[0], raw[1], raw[2]))
        bench_frame(mode="read_reflect", reflect=list(raw))

    print("stage4d gate ready (no driving). do bench_toggle / read_color / read_reflect; "
          "stop via 'robotctl stop' or Ctrl-C.")

    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                # 주행이 없으므로 pause 는 "단발 동작 실행 보류"만 의미한다(인프라 공통 동작).
                bench_frame(mode="paused", paused=True)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # (2) 대기 중인 단발 트리거(비차단 큐)
            with plock:
                action = pending["action"]
                pending["action"] = None

            if action == "bench_toggle":
                do_bench()
            elif action == "read_color":
                do_read_color()
            elif action == "read_reflect":
                do_read_reflect()
            else:
                # (3) 대기: 중앙 반사광만 흘린다(§7-0a 실측 시 마커 위 값 확인용).
                reflect_c = hw.read_center_reflect()
                bench_frame(mode="idle", reflect=[0, reflect_c, 0])

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage4d gate stopped.")


if __name__ == "__main__":
    run()
