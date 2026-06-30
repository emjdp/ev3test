#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 — 기초 라인트레이싱 (중앙 컬러센서 in2 1개, PID) + 인프라 MVP 통합.

중앙센서 반사광으로 검은 선을 PID(처음엔 P, 필요시 D/I)로 추종한다.
판단층(순수, ev3dev2 없음)과 구동층(lib/hardware.py)을 분리한다 — DECISIONS.md 0장.

독립 실행(브릭):  python3 stages/stage1_linetrace.py
문법 점검(PC):    python3 -m py_compile stages/stage1_linetrace.py lib/*.py
판단층 재연(PC):  python3 tools/replay.py runs/<ts> --decider stages.stage1_linetrace:decide_line

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다(ev3dev 기본 종료 동작으로 둠).
  - 정지는 네트워크 stop(robotctl stop / 대시보드 s) 또는 키보드 인터럽트.

자세한 명세: docs/specs/stage1_linetrace.md
"""

import os
import sys
import time

# stages/ 에서 단독 실행해도 lib/ 를 import 하도록 저장소 루트를 경로에 넣는다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams      # noqa: E402
from lib.telemetry import Telemetry             # noqa: E402
from lib.decision_log import DecisionLog        # noqa: E402
from lib.pid import Pid                          # noqa: E402 (ev3dev2 비의존, 순수)
from lib.tuning_server import TuningServer       # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# 라이브 params (정확히 6개; LIVE_TUNING.md "Stage 1" / stage1_linetrace.md §3 과 일치)
INITIAL_PARAMS = {
    "kp": 0.75,
    "ki": 0.0,
    "kd": 0.06,
    "base_speed": 20,
    "turn_limit": 35,
    "target_reflect": 6,
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "ki": (0.0, 0.5),
    "kd": (0.0, 1.0),
    "base_speed": (5, 45),
    "turn_limit": (5, 60),
    "target_reflect": (0, 100),
}

# 한 번에 큰 변화 금지(한 번에 변수 하나 원칙 보조). 서버가 초과 set 을 거부한다.
MAX_STEP = {
    "kp": 0.1,
    "ki": 0.02,
    "kd": 0.05,
    "base_speed": 5,
    "turn_limit": 10,
    "target_reflect": 5,
}

# 대시보드 표시용 메타(안전과 무관).
UI_STEP = {"kp": 0.05, "ki": 0.01, "kd": 0.01, "base_speed": 1, "turn_limit": 5, "target_reflect": 1}
UNITS = {"base_speed": "%", "turn_limit": "%", "target_reflect": "%"}
PARAM_ORDER = ["kp", "ki", "kd", "base_speed", "turn_limit", "target_reflect"]

# 라이브 param 이 아닌 내부 상수(6개 규칙 유지) — 필요 시에만 노출.
LINE_LOST_MARGIN = 25   # reflect >= target+margin 이면 흰바닥 수준 → 선 유실 후보 (§11 실기 확정)
D_EMA_ALPHA = 0.35      # D항 노이즈 평활 EMA(검토 #8). 라이브 개방 안 함.
RECOVER_SPEED = 0       # 선 유실 시 좌/우 속도. 0=정지(기본). 저속 직진이면 양수 (§11 실기 확정)

LOOP_DELAY = 0.015      # 제어 루프 sleep(초). dt 는 가정 말고 실측(LIVE_TUNING 결정 3)
REASON_THROTTLE_S = 0.25  # LINE_FOLLOW events 폭주 방지(상태유지 중 주기 기록)
SAVE_PATH = os.path.join(_ROOT, "config", "stage1.json")
STAGE_NAME = "stage1"


# =====================================================================
# 판단층 (순수, ev3dev2 없음) — PC import/test/replay 가능
#   decide_line(sensors, params, state) -> (action, reason_code, detail)
#   * state 를 제자리(in place)로 갱신한다(replay.py 호환).
#   * reason_code 는 상태 전이(LINE_LOST/LINE_RECOVER)에서만 채운다. 매 틱
#     LINE_FOLLOW 는 events 폭주를 막으려 제어 루프가 throttle 해서 남긴다.
# =====================================================================

def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def classify_line(reflect, params):
    """선 위(ON)인지 흰바닥으로 유실(LOST)인지. 선=어두움=작은 reflect."""
    if reflect >= params["target_reflect"] + LINE_LOST_MARGIN:
        return "LOST"
    return "ON"


def to_wheel_speeds(base, turn):
    """조향량(turn) → 좌/우 바퀴 속도. 부호/좌우 대응은 실기 확정(§11)."""
    return base - turn, base + turn


def recover_speeds(params):
    """선 유실 시 좌/우 속도. 기본은 정지(RECOVER_SPEED=0). Stage 1 은 회전/막다른길 판정 안 함."""
    return RECOVER_SPEED, RECOVER_SPEED


def make_state():
    """판단층 상태 초기값. (decide_line 은 빈 dict 로도 동작 — replay 호환.)"""
    return {}


def _ensure_pid(params, state):
    pid = state.get("pid")
    if pid is None:
        pid = Pid(params["kp"], params["ki"], params["kd"], params["turn_limit"], ema_alpha=D_EMA_ALPHA)
        state["pid"] = pid
    return pid


def decide_line(sensors, params, state):
    """중앙센서 reflect → (action, reason_code, detail). state 제자리 갱신.

    sensors: {"reflect": int, "t_ms": int}  (replay 의 samples.jsonl 한 줄)
    action:  {"line","turn","left","right","error"}
    """
    reflect = sensors.get("reflect")
    t_ms = sensors.get("t_ms")
    pid = _ensure_pid(params, state)
    line = classify_line(reflect, params)
    reason = None
    detail = {}

    if line == "LOST":
        if state.get("lost_since_ms") is None:
            state["lost_since_ms"] = t_ms
            reason = "LINE_LOST"
            detail = {"reason": "REFLECT_ABOVE_TARGET_MARGIN", "lost_ms": 0, "reflect": reflect}
        # 유실 중 PID 누적/미분 리셋(복귀 시 windup 방지), 회전 0.
        pid.reset()
        state["last_t_ms"] = t_ms
        state["line"] = "LOST"
        left, right = recover_speeds(params)
        action = {"line": "LOST", "turn": 0.0, "left": left, "right": right,
                  "error": params["target_reflect"] - reflect}
        return action, reason, detail

    # line == "ON"
    if state.get("lost_since_ms") is not None:
        if t_ms is not None and state["lost_since_ms"] is not None:
            lost_ms = t_ms - state["lost_since_ms"]
        else:
            lost_ms = 0
        reason = "LINE_RECOVER"
        detail = {"reason": "LINE_REACQUIRED", "lost_ms": lost_ms}
        state["lost_since_ms"] = None

    error = params["target_reflect"] - reflect
    last_t_ms = state.get("last_t_ms")
    if last_t_ms is None or t_ms is None:
        dt = 0.0   # 첫 틱: dt=0 → D항 0 (Pid 내부 방어)
    else:
        dt = (t_ms - last_t_ms) / 1000.0
    # 라이브 변경 반영(매 틱 snapshot 기준).
    pid.set_gains(params["kp"], params["ki"], params["kd"])
    pid.out_limit = params["turn_limit"]
    turn = pid.update(error, dt)
    state["last_t_ms"] = t_ms
    state["line"] = "ON"
    left, right = to_wheel_speeds(params["base_speed"], turn)
    action = {"line": "ON", "turn": turn, "left": left, "right": right, "error": error}
    return action, reason, detail


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()

    stop_flag = {"on": False, "source": None}

    def on_stop(source):
        # 네트워크 thread 에서 호출 — 플래그만 세팅(제어 루프가 안전한 시점에 처리).
        stop_flag["on"] = True
        stop_flag["source"] = source

    # Stage 1 은 단발 do 액션이 없다(stop 만 필수). actions=[] → describe 가 빈 액션.
    server = TuningServer(params, tele, do_handler=None, stop_handler=on_stop,
                          actions=[], stage=STAGE_NAME)
    server.start()

    state = make_state()
    started = time.monotonic()
    last = started
    last_follow_log = started - REASON_THROTTLE_S

    print("stage1 linetrace running. stop via 'robotctl stop' or Ctrl-C.")
    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            # (2) dt 실측 (가정 금지)
            now = time.monotonic()
            dt = now - last
            last = now
            t_ms = int((now - started) * 1000)

            # (3) 센서 읽기
            reflect = hw.read_center_reflect()

            # (4) params snapshot (네트워크 비차단: 복사본만)
            p = params.snapshot()

            # (5) 판단층(순수) → 행동
            sensors = {"reflect": reflect, "t_ms": t_ms}
            action, reason, detail = decide_line(sensors, p, state)

            # (6) 구동층 출력
            hw.drive(action["left"], action["right"])

            # (7) 상태전이 reason 로깅(LINE_LOST / LINE_RECOVER)
            if reason is not None:
                ev_detail = dict(detail)
                short = ev_detail.pop("reason", reason)
                log.log(reason, short, **ev_detail)

            # (8) telemetry 갱신 (최신 1프레임 교체)
            tele.publish({
                "t_ms": t_ms,
                "dt_ms": int(dt * 1000),
                "param_rev": params.rev(),
                "running": True,
                "reflect": reflect,
                "error": action["error"],
                "turn": action["turn"],
                "left_speed": action["left"],
                "right_speed": action["right"],
            })

            # (9) LINE_FOLLOW throttle(상태유지 추종 중 주기 기록)
            if action["line"] == "ON" and (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "PID", reflect=reflect,
                        error=action["error"], turn=action["turn"])
                last_follow_log = now

            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage1 linetrace stopped.")


if __name__ == "__main__":
    run()
