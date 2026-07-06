#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 photo-maze route integration.

Run on EV3:
    python3 stages/stage5_integration.py
    python3 stages/stage5_integration.py --seq "R L L R L L R L S S L R L L R L S S R L R R L L L"

This stage keeps the Stage 3 v2 line follower and Stage 4 reflected color
reader, but changes the branch behavior:

  - Stage 3/4 turn automatically toward a detected branch.
  - Stage 5 consumes a route sequence token at each confirmed junction.
  - Confirmed color markers trigger the same automatic U-turn used in Stage 4.

Default route is a photo-based direct path estimate from the shown maze:
start(bottom-right) -> dong1 -> dong2 -> dong3 -> dong4 -> top corridor.
It is intentionally easy to override with --seq during the first field run.

Python 3.5 compatible: no f-strings.
"""

import argparse
import json
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
    now_ms,
    PdController,
    pd_step,
)
from stages.stage4_clolor_reflected import (                      # noqa: E402
    INITIAL_PARAMS as STAGE4_COLOR_PARAMS,
    SAVE_PATH as STAGE4_COLOR_SAVE_PATH,
    beep_marker,
    marker_candidate,
    marker_candidate_kind,
    read_marker_at_rest,
    run_marker_uturn,
)


TOKEN_LEFT = "L"
TOKEN_STRAIGHT = "S"
TOKEN_RIGHT = "R"
TOKEN_UTURN = "U"

# Photo-based direct route estimate. The first real run should verify it with
# telemetry. If one decision is off, prefer --seq over editing code.
PHOTO_DIRECT_SEQ = "R L L R L L R L S S L R L L R L S S R L R R L L L"

TOKEN_ALIASES = {
    "L": TOKEN_LEFT,
    "LEFT": TOKEN_LEFT,
    "TURN_LEFT": TOKEN_LEFT,
    "S": TOKEN_STRAIGHT,
    "STRAIGHT": TOKEN_STRAIGHT,
    "F": TOKEN_STRAIGHT,
    "FORWARD": TOKEN_STRAIGHT,
    "R": TOKEN_RIGHT,
    "RIGHT": TOKEN_RIGHT,
    "TURN_RIGHT": TOKEN_RIGHT,
    "U": TOKEN_UTURN,
    "UTURN": TOKEN_UTURN,
    "U-TURN": TOKEN_UTURN,
}

TOKEN_REASONS = {
    TOKEN_LEFT: "TURN_LEFT",
    TOKEN_STRAIGHT: "NODE_STRAIGHT",
    TOKEN_RIGHT: "TURN_RIGHT",
    TOKEN_UTURN: "UTURN",
}

TOKEN_TO_CMD = {
    TOKEN_LEFT: "turn_left",
    TOKEN_RIGHT: "turn_right",
    TOKEN_UTURN: "uturn",
}


INITIAL_PARAMS = {
    "kp": 0.22,
    "base_speed": 17,
    "turn_speed": 6,
    "turn_90_factor": 0.66,
    "node_confirm_count": 2,
    "action_advance_mm": 30,
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "base_speed": (5, 45),
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "node_confirm_count": (1, 20),
    "action_advance_mm": (0, 120),
}

MAX_STEP = {
    "kp": 0.1,
    "base_speed": 5,
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "node_confirm_count": 2,
    "action_advance_mm": 10,
}

UI_STEP = {
    "kp": 0.01,
    "base_speed": 1,
    "turn_speed": 1,
    "turn_90_factor": 0.01,
    "node_confirm_count": 1,
    "action_advance_mm": 10,
}

UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "action_advance_mm": "mm",
}

PARAM_ORDER = [
    "kp", "base_speed", "turn_speed", "turn_90_factor",
    "node_confirm_count", "action_advance_mm",
]

SAVE_PATH = os.path.join(_ROOT, "config", "stage5_integration.json")
STAGE_NAME = "stage5_integration"

ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
    {"name": "read_marker", "label": "Read Marker"},
    {"name": "beep_test", "label": "Beep Test"},
    {"name": "next_step", "label": "Run Next Route Step"},
]

NODE_COOLDOWN_MS = BRANCH_COOLDOWN_MS
STRAIGHT_ADVANCE_FACTOR = 2.0

def load_stage4_color_defaults():
    """Load Stage 4 saved color tuning without exposing more Stage 5 params."""
    merged = dict(STAGE4_COLOR_PARAMS)
    try:
        with open(STAGE4_COLOR_SAVE_PATH, "r") as fp:
            saved = json.load(fp)
    except Exception:
        saved = None

    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in merged:
                merged[key] = value
    return merged


STAGE4_COLOR_DEFAULTS = load_stage4_color_defaults()
COLOR_COOLDOWN_MS = int(STAGE4_COLOR_DEFAULTS.get("marker_cooldown_ms", 1000))


def parse_sequence(text):
    """Parse route text into tokens L/S/R/U.

    Accepts compact ("RRLLS") and spaced/comma forms ("R R L L S").
    """
    if text is None:
        text = ""
    text = text.strip()
    if not text:
        return []

    normalized = text.replace(",", " ").replace("/", " ").replace(";", " ")
    parts = normalized.split()
    if len(parts) == 1 and len(parts[0]) > 1 and parts[0].upper() not in TOKEN_ALIASES:
        parts = list(parts[0])

    out = []
    for part in parts:
        key = part.strip().upper()
        if not key:
            continue
        if key not in TOKEN_ALIASES:
            raise ValueError("unknown route token: {}".format(part))
        out.append(TOKEN_ALIASES[key])
    return out


def sequence_to_text(seq):
    return " ".join(seq)


def classify_node_bits(bits):
    """Classify LCR bits into route-decision node kinds.

    Stage 3 v2 used 111 as left. Stage 5 keeps 111 as CROSS so the route
    sequence, not the bit tie-break, decides the action.
    """
    if bits == (1, 1, 1):
        return "CROSS"
    if bits == (1, 1, 0):
        return "LEFT_BRANCH"
    if bits == (0, 1, 1):
        return "RIGHT_BRANCH"
    return None


def node_confirm_step(kind, node_seen, t_ms, last_node_ms, confirm_count, cooldown_ms,
                      last_kind=None):
    """Route-node confirmation counter. Same-kind consecutive hits only."""
    in_cooldown = (t_ms - last_node_ms) < cooldown_ms
    if kind is not None and not in_cooldown:
        node_seen = node_seen + 1 if kind == last_kind else 1
        new_last_kind = kind
    else:
        node_seen = 0
        new_last_kind = None
    confirmed = node_seen >= int(confirm_count)
    return node_seen, confirmed, new_last_kind


def decide_turn_from_sequence(seq, idx, node_kind, bits_str):
    if idx >= len(seq):
        return None, "SEQUENCE_EXHAUSTED", {
            "node_index": idx,
            "node_kind": node_kind,
            "bits": bits_str,
        }

    token = seq[idx]
    reason_code = TOKEN_REASONS[token]
    return token, reason_code, {
        "node_index": idx,
        "selected": token,
        "rule": "PHOTO_ROUTE_SEQUENCE",
        "node_kind": node_kind,
        "bits": bits_str,
    }


def make_stage4_color_params(route_params):
    """Stage 4 color helpers expect their larger color params dict.

    Stage 5 exposes only six live params; color thresholds stay as Stage 4
    saved/default constants.
    """
    merged = dict(STAGE4_COLOR_DEFAULTS)
    for key in route_params:
        merged[key] = route_params[key]
    return merged


def _publish(tele, params, started, seq, route_idx, **overrides):
    now = time.monotonic()
    frame = {
        "t_ms": int((now - started) * 1000),
        "param_rev": params.rev(),
        "running": True,
        "mode": "follow",
        "paused": False,
        "reflect": [0, 0, 0],
        "bits": "000",
        "node_kind": None,
        "node_seen": 0,
        "node_index": route_idx,
        "last_token": None,
        "seq": sequence_to_text(seq),
        "seq_remaining": max(0, len(seq) - route_idx),
        "marker": None,
        "marker_source": None,
        "candidate_kind": None,
        "error": 0.0,
        "turn": 0.0,
        "left_speed": 0,
        "right_speed": 0,
    }
    frame.update(overrides)
    tele.publish(frame)


def _run_route_token(hw, token, snap, params, log, tele, should_stop, should_pause,
                     started, seq, route_idx):
    advance_mm = snap["action_advance_mm"]
    if token == TOKEN_STRAIGHT:
        target = advance_mm * STRAIGHT_ADVANCE_FACTOR
        moved = advance_straight(hw, target, ADVANCE_SPEED,
                                 _tick_stop(should_stop, lambda: None), should_pause)
        log.log("NODE_STRAIGHT", "PHOTO_ROUTE_SEQUENCE",
                node_index=route_idx, selected=token, advance_mm=target,
                moved_mm=moved)
        _publish(tele, params, started, seq, route_idx,
                 mode="straight", last_token=token, advance_mm=target,
                 moved_mm=moved)
        return moved

    if advance_mm > 0 and token in (TOKEN_LEFT, TOKEN_RIGHT):
        moved = advance_straight(hw, advance_mm, ADVANCE_SPEED,
                                 _tick_stop(should_stop, lambda: None), should_pause)
        _publish(tele, params, started, seq, route_idx,
                 mode="pre_turn_advance", last_token=token,
                 advance_mm=advance_mm, moved_mm=moved)
        if should_stop():
            return moved

    cmd = TOKEN_TO_CMD[token]
    return _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)


def _manual_marker_read(hw, snap, stop_flag):
    color_params = make_stage4_color_params(snap)
    return read_marker_at_rest(hw, color_params, stop_flag)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Stage 5 photo-maze route runner")
    parser.add_argument("--seq", default=PHOTO_DIRECT_SEQ,
                        help="route sequence using L/S/R/U tokens (default: photo direct route)")
    parser.add_argument("--dry-plan", action="store_true",
                        help="print parsed route and exit")
    return parser


def run(argv=None):
    from lib.hardware import Ev3Hardware  # ev3dev2 (brick only)

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    route_seq = parse_sequence(args.seq)
    if args.dry_plan:
        print("stage5 route: {}".format(sequence_to_text(route_seq)))
        return

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"turn": None, "marker": False, "beep": False, "next_step": False}
    plock = threading.Lock()

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "follow"}

    def on_do(action, args_obj):
        if action in ("turn_left", "turn_right", "uturn"):
            with plock:
                pending["turn"] = action
            return {"queued": action}
        if action == "read_marker":
            with plock:
                pending["marker"] = True
            return {"queued": action}
        if action == "beep_test":
            with plock:
                pending["beep"] = True
            return {"queued": action}
        if action == "next_step":
            with plock:
                pending["next_step"] = True
            return {"queued": action}
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
    route_idx = 0
    node_seen = 0
    last_node_kind = None
    last_node_ms = -999999
    last_marker_ms = -999999
    last_follow_log = started - REASON_THROTTLE_S

    print("stage5 route ready. seq={}. stop via robotctl stop or Ctrl-C.".format(
        sequence_to_text(route_seq)))

    try:
        while True:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            snap = params.snapshot()

            if pause_state["paused"]:
                hw.drive(0, 0)
                raw = hw.read_reflect()
                bits = black_bits(raw, thresholds)
                _publish(tele, params, started, route_seq, route_idx,
                         mode="paused", paused=True, reflect=list(raw),
                         bits=bits_to_str(bits), node_seen=node_seen)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            with plock:
                turn_cmd = pending["turn"]
                pending["turn"] = None
                manual_marker = pending["marker"]
                pending["marker"] = False
                beep_test = pending["beep"]
                pending["beep"] = False
                manual_next = pending["next_step"]
                pending["next_step"] = False

            if beep_test:
                beep_marker(hw, "purple")
                _publish(tele, params, started, route_seq, route_idx, mode="beep_test")
                continue

            if manual_marker:
                hw.stop()
                result = _manual_marker_read(hw, snap, stop_flag)
                if result["marker"] is not None:
                    beep_marker(hw, result["marker"])
                log.log("COLOR_READ", "MANUAL_STAGE5", marker=result["marker"],
                        marker_source=result["source"],
                        candidate_kind=result["candidate_kind"],
                        center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"], rgb=result["rgb"],
                        rgb_ratio=result["rgb_ratio"])
                _publish(tele, params, started, route_seq, route_idx,
                         mode="manual_marker", marker=result["marker"],
                         marker_source=result["source"],
                         candidate_kind=result["candidate_kind"],
                         center_reflect_avg=result["center_reflect_avg"],
                         color_code=result["color_code"], rgb=result["rgb"],
                         rgb_ratio=result["rgb_ratio"])
                pd.reset()
                continue

            if turn_cmd is not None:
                _run_turn(hw, turn_cmd, params, log, tele, should_stop, should_pause, started)
                pd.reset()
                last_node_ms = now_ms()
                node_seen = 0
                last_node_kind = None
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            raw = hw.read_reflect()
            bits = black_bits(raw, thresholds)
            bits_str = bits_to_str(bits)
            node_kind = classify_node_bits(bits)
            t_ms = now_ms()

            color_params = make_stage4_color_params(snap)
            candidate_kind = marker_candidate_kind(raw[1], color_params)
            in_marker_cooldown = (t_ms - last_marker_ms) < COLOR_COOLDOWN_MS
            if candidate_kind is not None and not in_marker_cooldown:
                hw.stop()
                result = read_marker_at_rest(hw, color_params, stop_flag, raw[1], candidate_kind)
                if result["marker"] is not None:
                    beep_marker(hw, result["marker"])
                log.log("COLOR_READ", "AUTO_REFLECT_GATE_STAGE5",
                        marker=result["marker"], marker_source=result["source"],
                        candidate_kind=result["candidate_kind"], reflect=list(raw),
                        bits=bits_str, center_reflect_avg=result["center_reflect_avg"],
                        color_code=result["color_code"], rgb=result["rgb"],
                        rgb_ratio=result["rgb_ratio"], node_index=route_idx)
                _publish(tele, params, started, route_seq, route_idx,
                         mode="marker", reflect=list(raw), bits=bits_str,
                         marker=result["marker"], marker_source=result["source"],
                         candidate_kind=result["candidate_kind"],
                         center_reflect_avg=result["center_reflect_avg"],
                         color_code=result["color_code"], rgb=result["rgb"],
                         rgb_ratio=result["rgb_ratio"])
                if result["marker"] is not None:
                    run_marker_uturn(hw, params, log, tele, should_stop,
                                     should_pause, started, result, raw, bits_str)
                pd.reset()
                node_seen = 0
                last_node_kind = None
                last_marker_ms = now_ms()
                last_node_ms = last_marker_ms
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            node_seen, confirmed, last_node_kind = node_confirm_step(
                node_kind, node_seen, t_ms, last_node_ms,
                snap["node_confirm_count"], NODE_COOLDOWN_MS, last_node_kind)

            if confirmed or manual_next:
                hw.stop()
                if manual_next and node_kind is None:
                    node_kind = "MANUAL"
                token, reason_code, detail = decide_turn_from_sequence(
                    route_seq, route_idx, node_kind, bits_str)
                if token is None:
                    log.log(reason_code, "NO_ROUTE_TOKEN", **detail)
                    _publish(tele, params, started, route_seq, route_idx,
                             mode="sequence_exhausted", reflect=list(raw),
                             bits=bits_str, node_kind=node_kind)
                    hw.stop()
                    break

                log.log("NODE_DECISION", "ROUTE_NODE_CONFIRMED",
                        node_index=route_idx, node_kind=node_kind,
                        bits=bits_str, selected=token, turn_reason=reason_code,
                        rule=detail.get("rule"), reflect=list(raw))
                _publish(tele, params, started, route_seq, route_idx,
                         mode="node_decision", reflect=list(raw), bits=bits_str,
                         node_kind=node_kind, node_seen=node_seen,
                         last_token=token)

                _run_route_token(hw, token, snap, params, log, tele,
                                 should_stop, should_pause, started,
                                 route_seq, route_idx)
                pd.reset()
                route_idx += 1
                node_seen = 0
                last_node_kind = None
                last_node_ms = now_ms()

                if route_idx >= len(route_seq):
                    log.log("SEQUENCE_DONE", "PHOTO_ROUTE_SEQUENCE", node_index=route_idx)
                    _publish(tele, params, started, route_seq, route_idx,
                             mode="sequence_done", last_token=token)
                    hw.stop()
                    break
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            left_speed, right_speed, error, derivative, turn = pd_step(pd, raw, snap)
            if bits == (0, 0, 0):
                left_speed *= 0.55
                right_speed *= 0.55
            hw.drive(left_speed, right_speed)

            now = time.monotonic()
            last_follow_log = _maybe_follow_log(log, raw, error, turn, now, last_follow_log)
            enc_l, enc_r = hw.read_encoders()
            _publish(tele, params, started, route_seq, route_idx,
                     mode="follow", reflect=list(raw), bits=bits_str,
                     node_kind=node_kind, node_seen=node_seen, error=error,
                     turn=turn, left_speed=left_speed, right_speed=right_speed,
                     marker_seen=marker_candidate(raw[1], color_params),
                     candidate_kind=candidate_kind,
                     enc_l=enc_l, enc_r=enc_r, enc_avg=hw.enc_avg())
            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage5 route stopped.")


if __name__ == "__main__":
    run()
