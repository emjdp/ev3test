#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 — 통합: 시퀀스 기반 노드 회전 (stage3v2 + stage4 reflected 트랙).

브릭 실행:
    python3 stages/stage5_integration.py --seq "L S R U"

Stage 3 v2(bits+PD 라인추종 + 분기 탱크회전)와 Stage 4 reflected(보라/빨강 색 마커
판정)를 기반으로, 노드마다 **미리 정한 회전 시퀀스**를 소비하며 코스를 통과한다.
명세: docs/specs/stage5_integration.md (단, 2026-07-02 §11 메모대로 v2 트랙으로 구현 —
decide_line3/follow_to_node 재사용 지시는 stale, 실제 재사용 대상은 stage3v2 의
black_bits/branch_side/branch_confirm_step/pd_step/advance_straight/_run_turn 과
stage4 의 MarkerCandidateTracker/read_marker_at_rest 다).

노드 종류와 시퀀스 소비:
  - JCT(분기): Stage 3 v2 의 좌/우 분기 확정(bits 110/111/011)이 노드 도착.
    시퀀스 토큰대로 회전한다 — L=좌90, R=우90, U=180, S=직진 통과(straight_nudge_mm
    전진 후 계속 추종). 감지된 분기 방향과 토큰이 달라도 **토큰을 따른다**(감지/시퀀스
    불일치는 BRANCH_*.bits vs TURN_*.selected 로그 비교로 가른다 — 명세 §8).
  - LEAF(막다른 길): Stage 4 색 마커(보라/빨강) 확정이 노드 도착. 색은 기록만 하고
    (주행 결정 아님 — Stage 6 몫), 시퀀스 토큰과 무관하게 **강제 U턴**한다
    (LEAF_FORCE_UTURN — 명세 §11 antigravity #6 반영: 시퀀스 실수로 벽 충돌 방지).
    토큰은 똑같이 1개 소비한다.
  - 시퀀스를 다 소비하면 SEQUENCE_DONE 후 정지(대기 모드 — `do set_seq` 로 재시작 가능).
    시퀀스가 빈 채 노드를 더 만나면 SEQUENCE_EXHAUSTED 후 정지.

라이브 params 는 통합 연결부 3개만(base_speed / branch_advance_mm / straight_nudge_mm).
하위 스테이지 확정값(kp, turn_speed, turn_90_factor, 마커/색 판정값 등)은 CONFIRMED_PARAMS
파일 상수로 묻고 다시 노출하지 않는다(명세 §3 — 틀리면 그 스테이지로 돌아가 보정).

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
from stages.stage4_clolor_reflected import (                      # noqa: E402
    MarkerCandidateTracker,
    _MuteTurnBeepHw,
    beep_marker,
    read_marker_at_rest,
)


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params + 하위 스테이지 확정값
# =====================================================================

# 라이브 params (연결부 3개 — 명세 §3 "3개로 시작"). 통합 연속 주행에서만 새로 맞춘다.
INITIAL_PARAMS = {
    "base_speed": 17,          # 통합 주행 속도(%). 관성 누적으로 실패 #1/#2 재발 시 ↓
    "branch_advance_mm": 30,   # 분기 확정 후 회전 전 전진(mm) = 회전 시점 손잡이(Stage3 30 시드)
    "straight_nudge_mm": 60,   # S 토큰: 분기 지나 다음 라인 올라타기 전진(mm). 못 지나면 ↑
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "branch_advance_mm": (0, 120),
    "straight_nudge_mm": (0, 200),
}

MAX_STEP = {
    "base_speed": 5,
    "branch_advance_mm": 10,
    "straight_nudge_mm": 20,
}

UI_STEP = {
    "base_speed": 1,
    "branch_advance_mm": 10,
    "straight_nudge_mm": 10,
}

UNITS = {
    "base_speed": "%",
    "branch_advance_mm": "mm",
    "straight_nudge_mm": "mm",
}

PARAM_ORDER = ["base_speed", "branch_advance_mm", "straight_nudge_mm"]

# 하위 스테이지 실기 Done 확정값(config/stage4_clolor_reflected.json 2026-07-03 저장분).
# **여기서 다시 노출/보정하지 않는다** — 틀리면 해당 스테이지로 돌아간다(명세 §3/§7).
CONFIRMED_PARAMS = {
    # Stage 3 v2 확정(주행/회전)
    "kp": 0.22,
    "turn_speed": 6,
    "turn_90_factor": 0.66,
    "branch_confirm_count": 2,
    # Stage 4 reflected 확정(색 마커 판정)
    "marker_candidate_min": 21,
    "marker_candidate_max": 32,
    "red_candidate_min": 73,
    "red_candidate_max": 86,
    "marker_stable_ms": 0,
    "marker_cooldown_ms": 1000,
    "marker_sample_count": 3,
    "marker_sample_delay_ms": 1,
    "color_mode_settle_ms": 10,
    "color_dummy_reads": 1,
    "purple_red_ratio_min": 0.20,
    "purple_blue_ratio_min": 0.23,
    "purple_green_ratio_max": 0.42,
}

# U턴 직전 전진(mm). 원본 pre_uturn 은 0 — 실기에서 필요해지면 라이브로 승격(명세 §11).
UTURN_ADVANCE_MM = 0

SAVE_PATH = os.path.join(_ROOT, "config", "stage5_integration.json")
STAGE_NAME = "stage5_integration"

ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
    {"name": "read_marker", "label": "Read Marker"},
    {"name": "set_seq", "label": "Set Sequence (args: seq=LSRU)"},
]


class ParamsView(object):
    """라이브 SharedParams + 하위 스테이지 확정 상수를 합쳐 보이는 읽기 전용 뷰.

    _run_turn/pd_step/read_marker_at_rest 는 kp/turn_speed/마커값 등을 snapshot 에서
    기대하므로, 확정값을 라이브로 노출하지 않으면서 같은 인터페이스(snapshot/rev)를
    유지하기 위한 어댑터다. 라이브 값이 확정값과 겹치면 라이브가 이긴다(현재 겹침 없음).
    """

    def __init__(self, shared, confirmed):
        self._shared = shared
        self._confirmed = dict(confirmed)

    def snapshot(self):
        snap = dict(self._confirmed)
        snap.update(self._shared.snapshot())
        return snap

    def rev(self):
        return self._shared.rev()


# =====================================================================
# 판단층 (순수, ev3dev2/시간/모터 없음) — PC 테스트/replay 가능
# =====================================================================

VALID_TOKENS = ("L", "S", "R", "U")

TOKEN_REASON = {
    "L": "TURN_LEFT",
    "R": "TURN_RIGHT",
    "U": "UTURN",
    "S": "NODE_STRAIGHT",
}

TOKEN_TO_CMD = {
    "L": "turn_left",
    "R": "turn_right",
    "U": "uturn",
}


def parse_seq(text):
    """시퀀스 문자열 → 토큰 리스트. 'L S R U' / 'LSRU' / 'l,s,r,u' 모두 허용.

    유효 토큰(L/S/R/U) 외 문자는 ValueError.
    """
    tokens = []
    for ch in text.upper():
        if ch in (" ", ",", "\t", "\n"):
            continue
        if ch not in VALID_TOKENS:
            raise ValueError("invalid sequence token: {}".format(ch))
        tokens.append(ch)
    return tokens


def decide_turn_from_sequence(arrival_kind, seq, idx):
    """이번 노드에서 실행할 회전을 시퀀스에서 고른다(순수 — 명세 §2 판단층).

    arrival_kind: "JCT"(분기) | "LEAF"(색 마커 막다른 길).
    LEAF 면 토큰과 무관하게 강제 U턴(LEAF_FORCE_UTURN — 명세 §11 antigravity #6).
    토큰 소비(idx 증가)는 호출부 몫 — 노드당 정확히 1개.

    반환: (token, reason_code, detail). 시퀀스가 비면 (None, "SEQUENCE_EXHAUSTED", ...).
    """
    if idx >= len(seq):
        return None, "SEQUENCE_EXHAUSTED", {"node_index": idx}
    token = seq[idx]
    detail = {"node_index": idx, "selected": token, "rule": "FROM_SEQUENCE"}
    if arrival_kind == "LEAF" and token != "U":
        detail["forced_from"] = token
        detail["selected"] = "U"
        return "U", "LEAF_FORCE_UTURN", detail
    return token, TOKEN_REASON[token], detail


def decide_sequence_turn(sensors, params, state):
    """`tools/replay.py --decider stages.stage5_integration:decide_sequence_turn` 어댑터.

    기록된 반사광 샘플을 stage3v2 `decide_branch`(분기 확정 재연)에 흘리고, 확정된
    노드마다 params["seq"] 시퀀스를 소비해 매 노드 selected 가 코스와 맞물리는지
    로봇 없이 확인한다(명세 §9). 색 마커(LEAF)는 정지 후 센서 모드 전환이라 재연 불가 —
    분기(JCT) 소비만 재연한다.
    """
    action, reason, detail = decide_branch(sensors, params, state)
    if action is None:
        return None, None, {}

    seq = state.get("seq_tokens")
    if seq is None:
        seq = parse_seq(params.get("seq", ""))
        state["seq_tokens"] = seq
    idx = state.get("seq_idx", 0)

    token, s_reason, s_detail = decide_turn_from_sequence("JCT", seq, idx)
    if token is None:
        return None, s_reason, s_detail
    state["seq_idx"] = idx + 1
    s_detail["bits"] = detail.get("bits")
    s_detail["detected"] = reason
    return token, s_reason, s_detail


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
# =====================================================================

def _publish(tele, pview, started, seqinfo, **overrides):
    now = time.monotonic()
    frame = {
        "t_ms": int((now - started) * 1000),
        "param_rev": pview.rev(),
        "running": True,
        "mode": "follow",
        "reflect": [0, 0, 0],
        "bits": "000",
        "branch_seen": 0,
        # Stage 5 시퀀스 상태(명세 §4)
        "node_index": seqinfo["idx"],
        "last_token": seqinfo["last_token"],
        "seq_remaining": len(seqinfo["seq"]) - seqinfo["idx"],
        "seq": "".join(seqinfo["seq"]),
    }
    frame.update(overrides)
    tele.publish(frame)


def run(seq_text):
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    seq = parse_seq(seq_text)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()
    pview = ParamsView(params, CONFIRMED_PARAMS)

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()
    marker_tracker = MarkerCandidateTracker()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"turn": None, "marker": False, "seq": None}
    plock = threading.Lock()

    # 시퀀스 상태는 제어 루프만 만진다(네트워크는 pending 큐로 전달).
    seqinfo = {"seq": seq, "idx": 0, "last_token": None, "finished": None}

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
        if action == "read_marker":
            with plock:
                pending["marker"] = True
            return {"queued": action}
        if action == "set_seq":
            try:
                tokens = parse_seq(str(args.get("seq", "")))
            except ValueError as exc:
                return {"error": str(exc)}
            with plock:
                pending["seq"] = tokens
            return {"queued": action, "seq": "".join(tokens)}
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
    last_marker_ms = -999999
    last_follow_log = started - REASON_THROTTLE_S

    def reset_after_node():
        pd.reset()
        marker_tracker.reset()
        return 0, None, now_ms()

    def consume_token(token):
        seqinfo["idx"] += 1
        seqinfo["last_token"] = token
        if seqinfo["idx"] >= len(seqinfo["seq"]):
            log.log("SEQUENCE_DONE", "COURSE_COMPLETE", node_index=seqinfo["idx"])
            seqinfo["finished"] = "done"
            hw.stop()
            try:
                hw.beep_ok()
            except Exception:
                pass

    print("stage5 integration ready (seq={}). ".format("".join(seq) or "(empty)") +
          "do set_seq seq=LSRU to (re)start a course; "
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
                _publish(tele, pview, started, seqinfo, mode="paused", paused=True,
                         reflect=list(raw), bits=bits_to_str(bits),
                         branch_seen=branch_seen, enc_avg=hw.enc_avg())
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            with plock:
                turn_cmd = pending["turn"]
                pending["turn"] = None
                manual_marker = pending["marker"]
                pending["marker"] = False
                new_seq = pending["seq"]
                pending["seq"] = None

            if new_seq is not None:
                seqinfo["seq"] = new_seq
                seqinfo["idx"] = 0
                seqinfo["last_token"] = None
                seqinfo["finished"] = None
                log.log("SEQ_SET", "DO_TRIGGER", seq="".join(new_seq))
                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                continue

            snap = pview.snapshot()

            if manual_marker:
                hw.stop()
                result = read_marker_at_rest(hw, snap, stop_flag)
                if result["marker"] is not None:
                    beep_marker(hw, result["marker"])
                log.log("COLOR_READ", "MANUAL", marker=result["marker"],
                        marker_source=result["source"],
                        candidate_kind=result["candidate_kind"],
                        center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"],
                        rgb=result["rgb"], rgb_ratio=result["rgb_ratio"])
                _publish(tele, pview, started, seqinfo, mode="manual_marker",
                         marker=result["marker"], marker_source=result["source"])
                pd.reset()
                marker_tracker.reset()
                continue

            if turn_cmd is not None:
                _run_turn(hw, turn_cmd, pview, log, tele, should_stop, should_pause, started)
                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # 시퀀스 종료/고갈 상태 — 정지 유지, do set_seq 재시작 대기(수동 do 는 위에서 처리).
            if seqinfo["finished"] is not None:
                hw.drive(0, 0)
                _publish(tele, pview, started, seqinfo, mode=seqinfo["finished"])
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            raw = hw.read_reflect()
            bits = black_bits(raw, thresholds)
            bits_str = bits_to_str(bits)
            side = branch_side(bits)
            t_ms = now_ms()

            # ---- LEAF: 색 마커 게이트(Stage 4 재사용) → 기록 + 강제 U턴 ----
            candidate_kind, _elapsed = marker_tracker.push(raw[1], t_ms, snap)
            in_marker_cooldown = (t_ms - last_marker_ms) < snap["marker_cooldown_ms"]
            if candidate_kind is not None and not in_marker_cooldown:
                hw.stop()
                result = read_marker_at_rest(hw, snap, stop_flag, raw[1], candidate_kind)
                log.log("COLOR_READ", "AUTO_REFLECT_GATE", marker=result["marker"],
                        marker_source=result["source"], reflect=list(raw),
                        candidate_kind=result["candidate_kind"],
                        center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"],
                        rgb=result["rgb"], rgb_ratio=result["rgb_ratio"])
                _publish(tele, pview, started, seqinfo, mode="marker",
                         reflect=list(raw), bits=bits_str,
                         marker=result["marker"], marker_source=result["source"])

                if result["marker"] is not None and not should_stop():
                    # 색 마커 = LEAF 노드. 색은 기록만(위 COLOR_READ), 회전은 시퀀스 소비.
                    beep_marker(hw, result["marker"])
                    token, reason, detail = decide_turn_from_sequence(
                        "LEAF", seqinfo["seq"], seqinfo["idx"])
                    if token is None:
                        log.log("SEQUENCE_EXHAUSTED", "LEAF", **detail)
                        seqinfo["finished"] = "exhausted"
                        hw.stop()
                    else:
                        detail["marker"] = result["marker"]
                        log.log(reason, "FROM_SEQUENCE", **detail)
                        if UTURN_ADVANCE_MM > 0:
                            advance_straight(hw, UTURN_ADVANCE_MM, ADVANCE_SPEED,
                                             should_stop, should_pause)
                        _run_turn(_MuteTurnBeepHw(hw), "uturn", pview, log, tele,
                                  should_stop, should_pause, started)
                        consume_token(token)

                branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                last_marker_ms = now_ms()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # ---- JCT: 분기 확정(Stage 3 v2 재사용) → 시퀀스 토큰대로 회전 ----
            branch_seen, confirmed, last_branch_side = branch_confirm_step(
                side, branch_seen, t_ms, last_turn_ms,
                snap["branch_confirm_count"], BRANCH_COOLDOWN_MS, last_branch_side)

            if confirmed:
                hw.stop()
                detected = "BRANCH_LEFT" if side == "left" else "BRANCH_RIGHT"
                log.log(detected, "BITS_" + bits_str, bits=bits_str,
                        branch_seen=branch_seen, advance_mm=snap["branch_advance_mm"],
                        reflect=list(raw))
                _publish(tele, pview, started, seqinfo, mode="node",
                         reflect=list(raw), bits=bits_str, branch_seen=branch_seen)

                token, reason, detail = decide_turn_from_sequence(
                    "JCT", seqinfo["seq"], seqinfo["idx"])
                if token is None:
                    log.log("SEQUENCE_EXHAUSTED", "JCT", bits=bits_str, **detail)
                    seqinfo["finished"] = "exhausted"
                    branch_seen, last_branch_side, last_turn_ms = reset_after_node()
                    continue

                # 감지/시퀀스 불일치 진단용으로 감지 결과도 함께 남긴다(명세 §8).
                detail["bits"] = bits_str
                detail["detected"] = detected
                log.log(reason, "FROM_SEQUENCE", **detail)

                def on_advance_tick():
                    el, er = hw.read_encoders()
                    _publish(tele, pview, started, seqinfo, mode="advancing",
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

                if not should_stop():
                    consume_token(token)
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
            _publish(tele, pview, started, seqinfo, mode="follow", reflect=list(raw),
                     bits=bits_str, error=error, turn=turn, left_speed=left_speed,
                     right_speed=right_speed, branch_seen=branch_seen,
                     enc_l=enc_l, enc_r=enc_r, enc_avg=hw.enc_avg())

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage5 integration stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 5 integration: sequence-driven course run")
    parser.add_argument("--seq", default="",
                        help="turn sequence, e.g. 'L S R U' or 'LSRU' (L/S/R/U)")
    cli = parser.parse_args()
    run(cli.seq)
