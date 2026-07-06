#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5-1 — 분기에서 고정 지시 회전 (감지 방향 ↔ 실행 회전 분리).

브릭 실행:
    python3 stages/stage5_1_fixed_turn.py --turn R

Stage 5 를 한 번에 통합(stage5_integration.py)했더니 신규 변수가 많아 실기
디버깅이 안 됐다. 그래서 하위 단계로 쪼갠 첫 단계다 — 분할 계획/Done 기준:
docs/specs/stage5_substages.md.

이 단계가 새로 검증하는 것은 딱 하나:
  - 분기 확정 시 감지된 방향이 아니라 **고정 지시 토큰 1개**(L/R/U/S)를 실행한다.
    모든 노드에서 같은 동작 → 시퀀스 상태(node_index 등)가 없어 디버깅이 단순하다.
  - S 는 회전 없이 straight_nudge_mm 전진으로 분기를 지나 계속 추종 — Stage 5-3
    시퀀스의 S 토큰 연결부를 여기서 먼저 단독 검증한다.
  - 지시 교체는 재배포 없이 `robotctl do set_turn turn=L` (TURN_SET 로그).
  - 감지(BRANCH_*.bits)와 실행(TURN_*.selected, rule=FIXED_TURN)을 함께 로깅해
    감지 문제와 회전 문제를 로그로 가른다.

이 단계에 없는 것(다음 하위 단계 몫): 111 십자 구분(5-2 — 여기선 stage3v2 그대로
111=좌 분기 취급), 시퀀스 소비(5-3), 색 마커 LEAF(5-4).

라이브 params 5개: base_speed / turn_speed / turn_90_factor / branch_advance_mm /
straight_nudge_mm. **속도·회전 factor 는 하위 단계 내내 대시보드에 남긴다**(사용자
결정 2026-07-06 — stage5_integration 처럼 CONFIRMED 로 묻지 않는다). kp 와
branch_confirm_count 는 Stage 3 v2 확정값을 파일 상수로 묻는다.

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 run() 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다. 정지는 네트워크 stop / Ctrl-C.
"""

import argparse
import os
import sys
import threading
import time


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams                       # noqa: E402
from lib.telemetry import Telemetry                               # noqa: E402
from lib.decision_log import DecisionLog                          # noqa: E402
from lib.tuning_server import TuningServer                        # noqa: E402
from lib.params_view import ParamsView                            # noqa: E402
from lib.seq_tokens import (                                       # noqa: E402
    TOKEN_REASON,
    TOKEN_TO_CMD,
    VALID_TOKENS,
    parse_token,
)
from stages.stage3v2_linetrace_branch import (                    # noqa: E402
    ADVANCE_SPEED,
    BRANCH_COOLDOWN_MS,
    LOOP_DELAY_MS,
    REASON_THROTTLE_S,
    THR_CENTER,
    THR_LEFT,
    THR_RIGHT,
    _maybe_follow_log,
    _run_turn,
    _tick_stop,
    advance_straight,
    bits_to_str,
    black_bits,
    branch_confirm_step,
    branch_side,
    decide_branch,
    now_ms,
    PdController,
    pd_step,
)


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params + 하위 스테이지 확정값
# =====================================================================

# 라이브 params 5개 — 공통 3(속도·회전, substages §1) + 연결부 2. 시드는 Stage 3 v2 확정값.
INITIAL_PARAMS = {
    "base_speed": 17,          # 주행 속도(%). 통합 관성으로 오버슛/오독 재발 시 ↓
    "turn_speed": 6,           # 탱크 회전 속도(%)
    "turn_90_factor": 0.66,    # 90° 보정계수(Stage 2 BASE_PIVOT_DEG_90 에 곱함)
    "branch_advance_mm": 30,   # 분기 확정 후 회전 전 전진(mm) = 회전 시점 손잡이
    "straight_nudge_mm": 60,   # S 지시: 분기 지나 다음 라인 올라타기 전진(mm). 못 지나면 ↑
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "branch_advance_mm": (0, 120),
    "straight_nudge_mm": (0, 200),
}

MAX_STEP = {
    "base_speed": 5,
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "branch_advance_mm": 10,
    "straight_nudge_mm": 20,
}

UI_STEP = {
    "base_speed": 1,
    "turn_speed": 1,
    "turn_90_factor": 0.01,
    "branch_advance_mm": 10,
    "straight_nudge_mm": 10,
}

UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "branch_advance_mm": "mm",
    "straight_nudge_mm": "mm",
}

PARAM_ORDER = [
    "base_speed", "turn_speed", "turn_90_factor",
    "branch_advance_mm", "straight_nudge_mm",
]

# 하위 스테이지 확정값 — 여기서 다시 노출/보정하지 않는다(틀리면 그 스테이지로 돌아간다).
CONFIRMED_PARAMS = {
    "kp": 0.22,                # Stage 3 v2 확정(조향 게인)
    "branch_confirm_count": 2, # Stage 3 v2 확정(분기 확정 연속횟수)
}

# U턴 직전 전진(mm). 0 유지 — 실기에서 필요해지면 라이브로 승격(stage5 명세 §11 동일).
UTURN_ADVANCE_MM = 0

SAVE_PATH = os.path.join(_ROOT, "config", "stage5_1_fixed_turn.json")
STAGE_NAME = "stage5_1_fixed_turn"

ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
    {"name": "set_turn", "label": "Set Fixed Turn (args: turn=L|R|U|S)"},
]


# =====================================================================
# 판단층 (순수, ev3dev2/시간/모터 없음) — PC 테스트/replay 가능
# =====================================================================

def decide_fixed_turn(detected, token):
    """분기 확정(detected='BRANCH_LEFT'/'BRANCH_RIGHT') 시 실행할 고정 지시 판단(순수).

    감지 방향과 무관하게 지시 token 을 그대로 따른다 — 감지/지시 불일치는 detail 의
    detected vs selected 비교로 로그에서 가른다(substages §2).

    반환: (token, reason_code, detail). rule 은 호출부가 "FIXED_TURN" 으로 남긴다.
    """
    if token not in VALID_TOKENS:
        raise ValueError("invalid fixed turn token: {!r}".format(token))
    detail = {"selected": token, "detected": detected}
    return token, TOKEN_REASON[token], detail


def decide_fixed(sensors, params, state):
    """`tools/replay.py --decider stages.stage5_1_fixed_turn:decide_fixed` 어댑터.

    기록된 반사광 샘플을 stage3v2 `decide_branch`(분기 확정 재연)에 흘리고, 확정된
    노드마다 params["turn"] 고정 지시가 어떤 reason 으로 남는지 로봇 없이 확인한다.
    """
    action, reason, detail = decide_branch(sensors, params, state)
    if action is None:
        return None, None, {}
    token = parse_token(str(params.get("turn", "L")))
    f_token, f_reason, f_detail = decide_fixed_turn(reason, token)
    f_detail["bits"] = detail.get("bits")
    return f_token, f_reason, f_detail


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
# =====================================================================

def _publish(tele, pview, started, fixed_token, **overrides):
    now = time.monotonic()
    frame = {
        "t_ms": int((now - started) * 1000),
        "param_rev": pview.rev(),
        "running": True,
        "mode": "follow",
        "reflect": [0, 0, 0],
        "bits": "000",
        "branch_seen": 0,
        "fixed_turn": fixed_token,   # Stage 5-1 상태 — 지금 지시된 토큰
    }
    frame.update(overrides)
    tele.publish(frame)


def run(turn_text):
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    fixed = {"token": parse_token(turn_text)}

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()
    pview = ParamsView(params, CONFIRMED_PARAMS)

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"turn": None, "set_turn": None}
    plock = threading.Lock()

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "follow"}

    def on_do(action, args):
        if action in ("turn_left", "turn_right", "uturn"):
            with plock:
                pending["turn"] = action
            return {"queued": action}
        if action == "set_turn":
            try:
                token = parse_token(str(args.get("turn", "")))
            except ValueError as exc:
                return {"error": str(exc)}
            with plock:
                pending["set_turn"] = token
            return {"queued": action, "turn": token}
        return {"error": "unknown action: {}".format(action)}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    thresholds = (THR_LEFT, THR_CENTER, THR_RIGHT)
    started = time.monotonic()
    branch_seen = 0
    last_turn_ms = -999999
    last_branch_side = None
    last_follow_log = started - REASON_THROTTLE_S

    def reset_after_node():
        pd.reset()
        return 0, None, now_ms()

    print("stage5-1 fixed turn ready (turn={}). ".format(fixed["token"]) +
          "do set_turn turn=L|R|U|S to change; "
          "stop via robotctl stop or Ctrl-C.")

    try:
        while True:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.drive(0, 0)
                raw = hw.read_reflect()
                bits = black_bits(raw, thresholds)
                _publish(tele, pview, started, fixed["token"], mode="paused",
                         paused=True, reflect=list(raw), bits=bits_to_str(bits),
                         branch_seen=branch_seen, enc_avg=hw.enc_avg())
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            with plock:
                turn_cmd = pending["turn"]
                pending["turn"] = None
                new_token = pending["set_turn"]
                pending["set_turn"] = None

            if new_token is not None:
                fixed["token"] = new_token
                log.log("TURN_SET", "DO_TRIGGER", turn=new_token)
                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                continue

            if turn_cmd is not None:
                _run_turn(hw, turn_cmd, pview, log, tele, should_stop, should_pause, started)
                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            snap = pview.snapshot()
            raw = hw.read_reflect()
            bits = black_bits(raw, thresholds)
            bits_str = bits_to_str(bits)
            side = branch_side(bits)
            t_ms = now_ms()

            # ---- 분기 확정(Stage 3 v2 재사용) → 고정 지시대로 실행 ----
            branch_seen, confirmed, last_branch_side = branch_confirm_step(
                side, branch_seen, t_ms, last_turn_ms,
                snap["branch_confirm_count"], BRANCH_COOLDOWN_MS, last_branch_side)

            if confirmed:
                hw.stop()
                detected = "BRANCH_LEFT" if side == "left" else "BRANCH_RIGHT"
                log.log(detected, "BITS_" + bits_str, bits=bits_str,
                        branch_seen=branch_seen, advance_mm=snap["branch_advance_mm"],
                        reflect=list(raw))
                _publish(tele, pview, started, fixed["token"], mode="node",
                         reflect=list(raw), bits=bits_str, branch_seen=branch_seen)

                token, reason, detail = decide_fixed_turn(detected, fixed["token"])
                detail["bits"] = bits_str
                log.log(reason, "FIXED_TURN", **detail)

                def on_advance_tick():
                    el, er = hw.read_encoders()
                    _publish(tele, pview, started, fixed["token"], mode="advancing",
                             enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

                if token in ("L", "R"):
                    advance_straight(hw, snap["branch_advance_mm"], ADVANCE_SPEED,
                                     _tick_stop(should_stop, on_advance_tick), should_pause)
                    if not should_stop():
                        _run_turn(hw, TOKEN_TO_CMD[token], pview, log, tele,
                                  should_stop, should_pause, started)
                elif token == "U":
                    if UTURN_ADVANCE_MM > 0:
                        advance_straight(hw, UTURN_ADVANCE_MM, ADVANCE_SPEED,
                                         _tick_stop(should_stop, on_advance_tick),
                                         should_pause)
                    if not should_stop():
                        _run_turn(hw, "uturn", pview, log, tele,
                                  should_stop, should_pause, started)
                else:  # "S": 회전 없이 분기를 지나 다음 라인에 올라탄다
                    advance_straight(hw, snap["straight_nudge_mm"], ADVANCE_SPEED,
                                     _tick_stop(should_stop, on_advance_tick), should_pause)

                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                continue

            # ---- 라인추종 (Stage 3 v2 PD 재사용) ----
            left_speed, right_speed, error, derivative, turn = pd_step(pd, raw, snap)
            if bits == (0, 0, 0):
                left_speed *= 0.55
                right_speed *= 0.55
            hw.drive(left_speed, right_speed)

            now = time.monotonic()
            last_follow_log = _maybe_follow_log(log, raw, error, turn, now, last_follow_log)

            enc_l, enc_r = hw.read_encoders()
            _publish(tele, pview, started, fixed["token"], mode="follow",
                     reflect=list(raw), bits=bits_str, error=error, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     branch_seen=branch_seen, enc_l=enc_l, enc_r=enc_r,
                     enc_avg=hw.enc_avg())

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage5-1 fixed turn stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 5-1: fixed instructed turn at every branch")
    parser.add_argument("--turn", default="L",
                        help="fixed turn token at every node: L / R / U / S")
    cli = parser.parse_args()
    run(cli.turn)
