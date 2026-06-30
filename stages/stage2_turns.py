#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2 — 원시 회전 (좌90 / 우90 / U턴) 각각 독립 보정.

`robotctl do turn_left / turn_right / uturn` 단일 트리거로 회전 1회를 실행하고,
값 하나(turn_90_factor / turn_180_factor)만 고쳐 다시 트리거하는 **빠른 보정 루프**가
이 단계의 핵심이다(좌회전 하나에 1시간 → 1분). 회전은 시간(ms)이 아니라 **엔코더 각도 +
보정계수**로 멈춘다(LIVE_TUNING.md 결정 5).

판단층(순수, lib/decide_turn.py) ↔ 구동층(lib/turns.py, lib/hardware.py) 분리.
이 파일은 둘을 잇는 대기 루프 + telemetry/reason 로깅이다.

독립 실행(브릭):  python3 stages/stage2_turns.py
문법 점검(PC):    python3 -m py_compile stages/stage2_turns.py lib/*.py
판단층 테스트(PC): python3 tests/test_stage2_logic.py

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다(ev3dev 기본 종료 동작으로 둠).
  - 정지는 네트워크 stop(robotctl stop / 대시보드 s) 또는 키보드 인터럽트.

자세한 명세: docs/specs/stage2_turns.md
"""

import os
import sys
import threading
import time

# stages/ 에서 단독 실행해도 lib/ 를 import 하도록 저장소 루트를 경로에 넣는다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams      # noqa: E402
from lib.telemetry import Telemetry             # noqa: E402
from lib.decision_log import DecisionLog        # noqa: E402
from lib.tuning_server import TuningServer       # noqa: E402
from lib.decide_turn import decide_turn          # noqa: E402 (순수, ev3dev2 비의존)
from lib.turns import pivot                       # noqa: E402 (구동층, hw 경유)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# 라이브 params (정확히 4개; stage2_turns.md §3 / LIVE_TUNING.md 한도 6 이하).
#   좌90·우90 은 하나의 turn_90_factor 로 시작(제자리라 좌우 대칭 기대). 실기에서 좌/우
#   오차가 계속 다른 방향이면 turn_90_left/right_factor 로 분리(→5개, 여전히 6 이하). §11.
INITIAL_PARAMS = {
    "turn_speed": 18,            # 제자리 회전 속도(%)
    "turn_90_factor": 1.0,       # 좌·우 90° 보정계수
    "turn_180_factor": 1.0,      # U턴 180° 보정계수
    "post_turn_settle_ms": 120,  # 회전 정지 후 관성 멎을 때까지 대기(측정 안정화)
}

PARAM_LIMITS = {
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "turn_180_factor": (0.5, 2.0),
    "post_turn_settle_ms": (0, 400),
}

# 한 번에 큰 변화 금지(한 번에 변수 하나 원칙 보조). 서버가 초과 set 을 거부한다.
MAX_STEP = {
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "post_turn_settle_ms": 40,
}

# 대시보드 표시용 메타(안전과 무관).
UI_STEP = {
    "turn_speed": 1,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "post_turn_settle_ms": 20,
}
UNITS = {"turn_speed": "%", "post_turn_settle_ms": "ms"}
PARAM_ORDER = ["turn_speed", "turn_90_factor", "turn_180_factor", "post_turn_settle_ms"]

# --- 라이브 param 이 아닌 파일 상수(4개 규칙 유지). 검증되면 config/stage2.json 에 묻는다. ---
# BASE_PIVOT_DEG_90: 제자리 90° 회전 시 '각 바퀴가 도는 각도(도)'의 기하 1차 추정.
#   제자리(탱크) 회전에서 각 바퀴 호 길이 = (트레드/2) * θ.
#   바퀴 회전각(도) = 호 / (π·바퀴지름) * 360.
#   가정: 바퀴지름 d≈56mm, 트레드 T≈120mm, θ=90°(π/2):
#     호 = 60 * 1.5708 = 94.25mm,  둘레 = π·56 = 175.93mm,
#     deg = 94.25 / 175.93 * 360 ≈ 193°.
#   ⚠️ d/T 는 실측 아님(가정). 실기에서 줄자로 측정해 이 1차값을 갱신하고, 그 다음 미세조정은
#      turn_90_factor 로만 한다(§11). U턴은 약 2배에서 시작.
BASE_PIVOT_DEG_90 = 193.0
BASE_PIVOT_DEG_180 = 386.0
TURN_RAMP = False        # 가감속 사용 여부(기본 off; 관성 영향 최소화 위해 일정속도)

LOOP_DELAY = 0.02        # 대기 루프 sleep(초). 네트워크는 절대 제어를 블록하지 않음(snapshot)
SAVE_PATH = os.path.join(_ROOT, "config", "stage2.json")
STAGE_NAME = "stage2"

# do 트리거로 누를 수 있는 동작(서버가 manifest 로 검증/노출). 라벨은 표시 전용.
ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
]


# =====================================================================
# telemetry 헬퍼 — 한 곳에서만 프레임을 만든다(인프라 공통 필드 + Stage 2 키).
# =====================================================================

def _publish(tele, params, started, **extra):
    now = time.monotonic()
    frame = {
        "t_ms": int((now - started) * 1000),
        "param_rev": params.rev(),
        "running": True,
    }
    for key in extra:
        frame[key] = extra[key]
    tele.publish(frame)


# =====================================================================
# 회전 1회 (판단 → 구동 → 로깅). 구동층은 hw 를 통해서만 접근.
# =====================================================================

def run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started):
    """do 로 들어온 한 회전 명령을 판단→구동→기록한다.

    cmd: 'turn_left' | 'turn_right' | 'uturn'.
    회전 종료에 별도 reason_code 를 만들지 않고(stage2 명세 §4), TURN_* 이벤트 detail 에
    실제 돈 각도(enc_avg)와 좌/우 엔코더를 덧붙여 한 번에 남긴다.
    """
    # 회전 도중 params 변경에 흔들리지 않게 snapshot + 파일 상수(BASE_*)를 합쳐 판단층에 넘김.
    snap = params.snapshot()
    snap["BASE_PIVOT_DEG_90"] = BASE_PIVOT_DEG_90
    snap["BASE_PIVOT_DEG_180"] = BASE_PIVOT_DEG_180
    param_rev = params.rev()

    action, reason_code, detail = decide_turn(cmd, snap, {})   # 판단층(순수)
    target = detail["target_deg"]
    turn_speed = snap["turn_speed"]

    # 회전 시작 telemetry
    _publish(tele, params, started, turning=True, target_deg=target,
             enc_l=0, enc_r=0, enc_avg=0.0, paused=bool(should_pause()))

    actual = pivot(hw, action, target, turn_speed, should_stop=should_stop,
                   should_pause=should_pause)

    settle_ms = snap["post_turn_settle_ms"]
    if settle_ms:
        time.sleep(settle_ms / 1000.0)

    enc_l, enc_r = hw.read_encoders()

    # reason 로그: 시작 의도(target/factor/speed) + 실제 결과(enc_avg/enc_l/enc_r)를 한 이벤트로.
    ev_detail = dict(detail)
    rule = ev_detail.pop("rule", "DO_TRIGGER")
    ev_detail["param_rev"] = param_rev
    ev_detail["enc_l"] = enc_l
    ev_detail["enc_r"] = enc_r
    ev_detail["enc_avg"] = actual
    ev_detail["error_deg"] = actual - target
    ev_detail["stopped_early"] = bool(should_stop())
    log.log(reason_code, rule, **ev_detail)

    # 회전 종료 telemetry
    _publish(tele, params, started, turning=False, target_deg=target,
             enc_l=enc_l, enc_r=enc_r, enc_avg=actual, paused=bool(should_pause()))

    hw.beep_ok()   # 사람이 "끝났다" 인지(보정 루프 리듬)
    return actual


# =====================================================================
# 구동층 대기 루프 (브릭, ev3dev2) — run()
#   Stage 1 처럼 연속 제어가 아니라 '트리거 대기 → 회전 1회' 구조.
#   그래도 telemetry/네트워크 비차단/stop 플래그 규칙은 동일하게 지킨다.
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"cmd": None}
    plock = threading.Lock()

    def on_stop(source):
        # 네트워크 thread 에서 호출 — 플래그만 세팅(제어 루프/회전 폴링이 안전한 시점에 처리).
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD",
                source=source)
        return {"mode": "paused" if paused else "running"}

    def on_do(action, args):
        # 네트워크 thread 에서 호출 — 회전을 여기서 돌리지 않고 대기 루프에 넘긴다(비차단).
        with plock:
            pending["cmd"] = action
        return {"queued": action}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    started = time.monotonic()

    print("stage2 turns ready. do turn_left/turn_right/uturn; stop via 'robotctl stop' or Ctrl-C.")
    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.drive_raw(0, 0)
                enc_l, enc_r = hw.read_encoders()
                _publish(tele, params, started, turning=False, paused=True,
                         enc_l=enc_l, enc_r=enc_r,
                         enc_avg=(abs(enc_l) + abs(enc_r)) / 2.0)
                time.sleep(LOOP_DELAY)
                continue

            # (2) 대기 중인 do 회전 명령 꺼내기(비차단)
            with plock:
                cmd = pending["cmd"]
                pending["cmd"] = None

            if cmd is not None:
                run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)
            else:
                # (3) idle telemetry — 현재 엔코더/회전중 아님
                enc_l, enc_r = hw.read_encoders()
                _publish(tele, params, started, turning=False, paused=False,
                         enc_l=enc_l, enc_r=enc_r,
                         enc_avg=(abs(enc_l) + abs(enc_r)) / 2.0)

            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage2 turns stopped.")


if __name__ == "__main__":
    run()
