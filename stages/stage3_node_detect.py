#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 — 노드(분기) 감지 (좌/중/우 3센서 bits 패턴) + 3센서 라인트레이싱.

좌/중/우 3센서로 선을 따라가다(중앙센서가 라인 위, 좌/우가 보조) 같은 3센서 bits
패턴으로 노드 후보를 감지하면 멈추고 패턴/거리를 로그로 남긴다. **회전·색 판정은 하지
않는다**(Stage 5/4). 노드 확정 시 정지.

주행 판단은 Stage 1 중앙센서 PID 가 아니라 `decide_line3`(좌/중/우 bits/raw) 이다.
"010 이면 직진, 왼쪽이 더 검으면 왼쪽 보정, 오른쪽이 더 검으면 오른쪽 보정." Stage 1 의
하드웨어/주행 부호 기반(left=base-turn, right=base+turn)은 그대로 유지한다.

빠른 보정 루프: `robotctl do follow` 로 '선 따라가다 노드에서 1정지' 1세트를 돌리고,
값 하나(threshold / node_confirm_ms / node_debounce_ms / node_advance)만 고쳐 다시
`do follow`. 한 번에 변수 하나(README 황금률).

판단층(순수, lib/nodes.py) ↔ 구동층(lib/hardware.py) 분리. follow 상수는 이 파일 상단에
두고 제어 루프가 params 스냅샷에 병합해 `decide_line3` 으로 넘긴다(lib 가 stages 를
import 하지 않게 — 순환 참조 방지). Stage 1/2 확정 코드/값은 수정하지 않는다.

독립 실행(브릭):  python3 stages/stage3_node_detect.py
문법 점검(PC):    python3 -m py_compile stages/stage3_node_detect.py lib/*.py
판단층 테스트(PC): python3 tests/test_stage3_logic.py
판단층 재연(PC):  python3 tools/replay.py runs/<ts> --decider lib.nodes:decide_node \\
                    --set node_confirm_ms=80 node_advance=8

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다(ev3dev 기본 종료 동작으로 둠).
  - 정지는 네트워크 stop(robotctl stop / 대시보드 s) 또는 키보드 인터럽트.

자세한 명세: docs/specs/stage3_node_detect.md
"""

import math
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
from lib.nodes import (                          # noqa: E402 (순수, ev3dev2 비의존)
    bits_from_raw, bits_str, classify_node, NodeDebouncer, KIND_TO_REASON,
    decide_line3, make_follow_state,
)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# 라이브 params (정확히 6개; LIVE_TUNING.md 한도). threshold 는 Stage 1 중앙센서 실측
# (검정 0 / 흰색 10)을 따라 흑·백 중간값 부근(5)으로 시작. 좌/우 센서는 미실측 → 실기 보정.
INITIAL_PARAMS = {
    "left_threshold": 5,      # 좌센서: raw < 이 값이면 1(검은 선)
    "center_threshold": 5,    # 중앙센서 threshold (라인추종 PID 와 별개 — 노드 bits 전용)
    "right_threshold": 5,     # 우센서 threshold
    "node_confirm_ms": 120,   # 같은 패턴이 이만큼 지속돼야 노드 확정
    "node_debounce_ms": 900,  # 직전 확정 후 재확정 금지(중복 방지)
    "node_advance": 0,        # 노드 확정 후 회전/색읽기 전 전진량(mm). 실패#1 손잡이.
}

PARAM_LIMITS = {
    "left_threshold": (0, 100),
    "center_threshold": (0, 100),
    "right_threshold": (0, 100),
    "node_confirm_ms": (20, 400),
    "node_debounce_ms": (200, 2000),
    "node_advance": (0, 60),
}

# 한 번에 큰 변화 금지(한 번에 변수 하나 원칙 보조). 서버가 초과 set 을 거부한다.
MAX_STEP = {
    "left_threshold": 3,
    "center_threshold": 3,
    "right_threshold": 3,
    "node_confirm_ms": 20,
    "node_debounce_ms": 100,
    "node_advance": 5,
}

# 대시보드 표시용 메타(안전과 무관).
UI_STEP = {
    "left_threshold": 1,
    "center_threshold": 1,
    "right_threshold": 1,
    "node_confirm_ms": 20,
    "node_debounce_ms": 100,
    "node_advance": 5,
}
UNITS = {
    "left_threshold": "%", "center_threshold": "%", "right_threshold": "%",
    "node_confirm_ms": "ms", "node_debounce_ms": "ms", "node_advance": "mm",
}
PARAM_ORDER = [
    "left_threshold", "center_threshold", "right_threshold",
    "node_confirm_ms", "node_debounce_ms", "node_advance",
]

# --- 라이브 param 이 아닌 파일 상수(6개 규칙 유지). 검증되면 config/stage3.json 에 묻는다. ---
# 바퀴 지름 → 1도당 이동거리(mm). Stage 2 BASE_PIVOT 과 동일한 가정(d≈56mm)을 쓴다.
#   1 바퀴도(度) = π·d / 360 mm.  ⚠️ d 는 실측 아님(가정) → 실기 줄자 측정 후 갱신(§11).
#   미확정이면 dist_mm 는 상대 비교용으로만 본다(보정 손잡이 node_advance 는 그대로 동작).
WHEEL_DIAM_MM = 56.0
MM_PER_DEG = math.pi * WHEEL_DIAM_MM / 360.0

ADVANCE_SPEED = 15        # 노드 확정 후 전진(advance)/nudge 속도(%). 느리게 고정(config).
DEFAULT_NUDGE_MM = 10     # do nudge 인자 없을 때 기본 전진량(mm).
CONTINUE_AFTER_NODE = False  # True 면 확정 후에도 계속 주행(debounce 가 중복 막음). 기본은 1노드 1정지.

# --- 3센서 라인트레이싱(decide_line3) follow 상수 — 라이브 param 아님(6개 규칙 유지). ---
# 제어 루프가 params 스냅샷에 병합해 decide_line3 으로 넘긴다(lib↔stages 순환 참조 방지).
# 부호/속도 기조는 Stage 1 확정값(base_speed 20, turn_limit 35)을 따른다. 실기 보정 §11.
FOLLOW_BASE_SPEED = 20    # 직진 기본 속도(%) — Stage 1 base_speed 기조
FOLLOW_GAIN = 2.0         # line_error3(좌우 raw 차) 당 turn. 실기에서 한 값만 보정.
FOLLOW_TURN_LIMIT = 35    # turn 클램프(±) — Stage 1 turn_limit 기조
FOLLOW_SLOW_SPEED = 12    # 노드 후보(111/101) 저속 직진 속도(%). base 보다 작게.
FOLLOW_CONSTS = {
    "follow_base_speed": FOLLOW_BASE_SPEED,
    "follow_gain": FOLLOW_GAIN,
    "follow_turn_limit": FOLLOW_TURN_LIMIT,
    "follow_slow_speed": FOLLOW_SLOW_SPEED,
}

LOOP_DELAY = 0.015        # 제어 루프 sleep(초). dt 는 가정 말고 실측(LIVE_TUNING 결정 3)
REASON_THROTTLE_S = 0.25  # LINE_FOLLOW events 폭주 방지(상태유지 중 주기 기록)
SAVE_PATH = os.path.join(_ROOT, "config", "stage3.json")
STAGE_NAME = "stage3"

# do 트리거 동작(서버가 manifest 로 검증/노출). 라벨은 표시 전용.
ACTIONS = [
    {"name": "follow", "label": "Follow until node"},
    {"name": "nudge", "label": "Nudge forward (mm)"},
]


# =====================================================================
# 거리 환산 + 전진(구동, 짧고 느리게) — ev3dev2 비의존(hw 경유라 PC 테스트 가능)
# =====================================================================

def deg_to_mm(deg):
    """엔코더 각도(도) → 이동거리(mm). 환산계수는 §11 실기 확정 전까지 가정."""
    return deg * MM_PER_DEG


def advance(hw, distance_mm, should_stop, should_pause=None):
    """노드 확정 후(또는 nudge) 직진으로 distance_mm 만큼 전진. 거리는 엔코더 기준.

    distance_mm <= 0 이면 제자리. 느린 고정 속도(ADVANCE_SPEED). stop 에 즉시 반응.
    pause 중에는 속도 0 으로 기다렸다가 같은 거리 목표를 이어간다.
    반환: 실제 전진 거리(mm, 검증/telemetry).
    """
    if distance_mm <= 0:
        return 0.0
    start = hw.enc_avg()
    hw.drive(ADVANCE_SPEED, ADVANCE_SPEED)
    try:
        while deg_to_mm(hw.enc_avg() - start) < distance_mm:
            if should_stop is not None and should_stop():
                break
            if should_pause is not None and should_pause():
                hw.drive(0, 0)
                while should_pause():
                    if should_stop is not None and should_stop():
                        break
                    time.sleep(0.01)
                if should_stop is not None and should_stop():
                    break
                hw.drive(ADVANCE_SPEED, ADVANCE_SPEED)
            time.sleep(0.005)
    finally:
        hw.stop()
    return deg_to_mm(hw.enc_avg() - start)


# =====================================================================
# telemetry 헬퍼 — 한 곳에서만 프레임을 만든다(인프라 공통 필드 + Stage 3 키).
# =====================================================================

def _publish(tele, params, started, dt_ms, raw, bits, dist_mm, enc_avg, count,
             node_candidate, node_confirmed, mode, action, paused=False):
    now = time.monotonic()
    l, c, r = raw
    frame = {
        "t_ms": int((now - started) * 1000),
        "dt_ms": dt_ms,
        "param_rev": params.rev(),
        "running": True,
        "paused": bool(paused),
        "mode": mode,
        # 노드 감지(좌/중/우)
        "reflect": [l, c, r],
        "reflect_l": l,
        "reflect_c": c,
        "reflect_r": r,
        "bits": bits_str(bits),
        "node_candidate": node_candidate,
        "node_confirmed": node_confirmed,
        "dist_mm": dist_mm,
        "enc_avg": enc_avg,
        "confirm_count": count,
        # 3센서 라인트레이싱(decide_line3) 필드
        "error": action.get("error", 0),
        "line_error3": action.get("line_error3", 0.0),
        "turn": action.get("turn", 0.0),
        "left_speed": action.get("left", 0),
        "right_speed": action.get("right", 0),
    }
    tele.publish(frame)


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
#   IDLE: 정지 대기. do follow 로 FOLLOW 진입.
#   FOLLOW: 3센서(decide_line3) 라인추종 + 3센서 노드 감지. 노드 확정 시 정지(→ IDLE).
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()

    deb = NodeDebouncer()                 # 순수 판정기(노드 후보→확정)
    follow_state = make_follow_state()    # 3센서 follow 상태(직전 조향 last_turn 보관)
    node_state = {"node_dist0_deg": 0.0}  # 직전 노드(또는 follow 시작) 이후 거리 기준점

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"follow": False, "nudge": None}
    plock = threading.Lock()
    mode = {"value": "IDLE"}

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD",
                source=source)
        return {"mode": "paused" if paused else mode["value"].lower()}

    def on_do(action, args):
        with plock:
            if action == "follow":
                pending["follow"] = True
            elif action == "nudge":
                mm = args.get("mm", DEFAULT_NUDGE_MM)
                pending["nudge"] = mm
        return {"queued": action}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    hw.reset_encoders()
    started = time.monotonic()
    last = started
    last_follow_log = started - REASON_THROTTLE_S
    idle_action = {"error": 0, "turn": 0.0, "left": 0, "right": 0}

    print("stage3 node detect ready. do follow; stop via 'robotctl stop' or Ctrl-C.")
    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.drive(0, 0)
                now = time.monotonic()
                dt = now - last
                last = now
                raw = hw.read_reflect()
                p = params.snapshot()
                thr = (p["left_threshold"], p["center_threshold"], p["right_threshold"])
                bits = bits_from_raw(raw, thr)
                enc_avg = hw.enc_avg()
                dist_mm = deg_to_mm(enc_avg - node_state["node_dist0_deg"])
                _publish(tele, params, started, int(dt * 1000), raw, bits, dist_mm,
                         enc_avg, deb.count, False, False, mode["value"], idle_action,
                         paused=True)
                time.sleep(LOOP_DELAY)
                continue

            # (2) 대기 중인 do 명령(비차단)
            with plock:
                start_follow = pending["follow"]
                pending["follow"] = False
                nudge_mm = pending["nudge"]
                pending["nudge"] = None

            if start_follow:
                # follow 1세트 시작: 후보 누적/follow 상태/거리 기준점 리셋.
                deb.reset()
                follow_state = make_follow_state()
                node_state["node_dist0_deg"] = hw.enc_avg()
                mode["value"] = "FOLLOW"

            if nudge_mm is not None:
                # 노드 확정 위치 미세 확인용 전진(구동만). reason 로그 없이 telemetry 로 거리 본다.
                advance(hw, nudge_mm, should_stop, should_pause)

            # (3) dt 실측 + 센서/거리
            now = time.monotonic()
            dt = now - last
            last = now
            t_ms = int((now - started) * 1000)

            raw = hw.read_reflect()                      # (l, c, r)
            p = params.snapshot()                        # 네트워크 비차단(복사본)
            # follow 상수를 스냅샷에 병합해 decide_line3 으로 넘긴다(lib↔stages 순환 방지).
            follow_p = dict(p)
            follow_p.update(FOLLOW_CONSTS)
            thr = (p["left_threshold"], p["center_threshold"], p["right_threshold"])
            bits = bits_from_raw(raw, thr)
            enc_avg = hw.enc_avg()
            dist_mm = deg_to_mm(enc_avg - node_state["node_dist0_deg"])

            node_candidate = False
            node_confirmed = False
            action = idle_action

            if mode["value"] != "FOLLOW":
                # IDLE: 정지 유지(노드 위에서 멈춤 상태). 모터는 이미 정지.
                hw.stop()
            else:
                status, info = deb.push(bits, t_ms, p, dist_mm)

                if status == "NODE_CONFIRMED":
                    node_confirmed = True
                    hw.stop()
                    kind = info["kind"]
                    # 코너 패턴이면 방향 reason 도 함께(카탈로그 일치). 000 은 DEAD_END.
                    if kind in KIND_TO_REASON:
                        log.log(KIND_TO_REASON[kind], "BITS_" + info["bits"], bits=info["bits"])
                    log.log("NODE_CONFIRMED", "BITS_STABLE_AND_DEBOUNCE_OK",
                            bits=info["bits"], kind=kind, reflect=list(raw),
                            duration_ms=info["duration_ms"],
                            debounce_ms=p["node_debounce_ms"], dist_mm=dist_mm)
                    # 확정 후 전진량(실패#1 손잡이). 0 이면 제자리.
                    advance(hw, p["node_advance"], should_stop, should_pause)
                    hw.beep_ok()
                    node_state["node_dist0_deg"] = hw.enc_avg()
                    mode["value"] = "FOLLOW" if CONTINUE_AFTER_NODE else "IDLE"
                elif status == "NODE_CANDIDATE":
                    node_candidate = True
                    log.log("NODE_CANDIDATE", "BITS_" + info["bits"],
                            bits=info["bits"], kind=info["kind"], reflect=list(raw),
                            duration_ms=info["duration_ms"], dist_mm=dist_mm)
                    # 후보 단계에서는 노드 중심까지 계속 추종(아직 멈추지 않음).
                    action = _follow3(hw, raw, bits, follow_p, follow_state)
                    last_follow_log = _maybe_follow_log(
                        log, action, raw[1], now, last_follow_log)
                else:
                    # 노드 아님(LINE) 또는 debounce 억제 → 3센서 라인추종 계속.
                    action = _follow3(hw, raw, bits, follow_p, follow_state)
                    last_follow_log = _maybe_follow_log(
                        log, action, raw[1], now, last_follow_log)

            # (4) telemetry
            _publish(tele, params, started, int(dt * 1000), raw, bits, dist_mm,
                     enc_avg, deb.count, node_candidate, node_confirmed,
                     mode["value"], action, paused=False)

            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage3 node detect stopped.")


def _follow3(hw, raw, bits, follow_p, follow_state):
    """좌/중/우 3센서로 라인추종 1틱 → 구동. 노드 미확정 구간의 조향.

    Stage 1 중앙센서 PID 가 아니라 lib.nodes.decide_line3(순수)을 호출한다. 상태전이
    reason 은 노드 감지(debouncer)가 따로 내므로 여기서는 구동만 한다. LINE_FOLLOW 주기
    로깅은 호출부에서 _maybe_follow_log 가 처리한다.
    """
    action = decide_line3(raw, bits, follow_p, follow_state)
    hw.drive(action["left"], action["right"])
    return action


def _maybe_follow_log(log, action, reflect, now, last_follow_log):
    """LINE_FOLLOW 주기 로깅(폭주 방지). 갱신된 last_follow_log 시각을 반환."""
    if action.get("line") == "ON" and (now - last_follow_log) >= REASON_THROTTLE_S:
        log.log("LINE_FOLLOW", "PID", reflect=reflect,
                error=action.get("error"), turn=action.get("turn"))
        return now
    return last_follow_log


if __name__ == "__main__":
    run()
