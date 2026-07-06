#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 v2 — 중앙 상시 컬러 모드 라인추종 + 주행 중 마커 색 판정.

사용자 방향 전환(2026-07-03): 반사광↔컬러 모드 전환을 브릿지하던 후보 A~D 대신,
**중앙센서(in2)를 처음부터 끝까지 컬러 모드**로 두고 좌/우(in1/in3)만 반사광으로
라인추종한다 — 주행 중 모드 전환 0회.

성립 근거(코드 사실): stage3v2 의 PD 조향(`pd_step`)은 `error = raw[2] - raw[0]` 로
좌/우 반사광만 쓰고 중앙 raw 를 쓰지 않는다. 중앙의 흑백 정보(bits 가운데 비트,
000 감속)는 컬러코드(검정=1→bit 1, 흰색=6→bit 0)로 대체한다. 따라서 Stage 3 확정
조향 수식/게인(kp 0.22 / base_speed 17 시드)을 수정 없이 그대로 재사용한다.

이 파일이 하는 것:
  - 좌/우 반사광 PD 라인추종(stage3v2 의 PdController import — 미수정 재사용).
  - 주행 중 중앙 컬러코드가 같은 마커색으로 연속 color_confirm_count 회면 확정 →
    COLOR_READ(method:"driving") + NODE_IS_*(시작/체크포인트/도착) 로그. 주행은 계속.
  - `do read_color`: 정지 상태 색 다수결 판독 + 분류(§7 실측 도구).
안 하는 것: 분기 판단/회전(이 트랙의 2단계 — 사용자 "나중에"), 색에 따른 주행 결정.

주의(구현 함정, 명세 §8): 이 파일에서 hw.read_reflect() 를 부르면 중앙 반사광 속성
접근이 중앙 모드를 COL-REFLECT 로 되돌린다 — 반드시 hw.read_side_reflect() 만 쓴다.

독립 실행(브릭):  python3 stages/stage4v2_color_follow.py
문법 점검(PC):    python3 -m py_compile stages/stage4v2_color_follow.py lib/*.py
판단층 테스트(PC): python3 tests/test_stage4v2_logic.py

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다. 정지는 네트워크 stop / Ctrl-C.

자세한 명세: docs/specs/stage4v2_color_follow.md
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
# Stage 3 확정 코드 재사용(미수정): PD 조향 수식 + 좌/우 threshold(실기 1차 보정값 43/42).
from stages.stage3v2_linetrace_branch import (                     # noqa: E402
    PdController, pd_step, bits_to_str, THR_LEFT, THR_RIGHT,
)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# ev3dev2 ColorSensor.color 코드.
COLOR_NONE = 0
COLOR_BLACK = 1
COLOR_BLUE = 2
COLOR_GREEN = 3
COLOR_YELLOW = 4
COLOR_RED = 5
COLOR_WHITE = 6
COLOR_BROWN = 7

# 라이브 params (정확히 6개; 명세 §3). kp/base_speed 는 Stage 3 실기 확정값 시드.
INITIAL_PARAMS = {
    "kp": 0.22,                # 조향 게인(좌/우 raw 차) — Stage 3 확정값
    "base_speed": 17,          # 직진 속도(%) — Stage 3 확정값
    "color_confirm_count": 3,  # 같은 마커색 연속 루프 수(오탐 방지 vs 마커 놓침)
    "start_color": COLOR_YELLOW,      # 시작 마커 색코드(§7-0 실측으로 확정)
    "checkpoint_color": COLOR_BLUE,   # 체크포인트 마커 색코드
    "goal_color": COLOR_RED,          # 도착 마커 색코드
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "base_speed": (5, 45),
    "color_confirm_count": (1, 10),
    "start_color": (0, 7),
    "checkpoint_color": (0, 7),
    "goal_color": (0, 7),
}

# 색코드 MAX_STEP=7: 색코드는 연속 물리량이 아니라 라벨 — 2→5 를 나눠 갈 이유가 없고
# 중간 코드를 스치는 게 오히려 위험하다(명세 §3).
MAX_STEP = {
    "kp": 0.1,
    "base_speed": 5,
    "color_confirm_count": 1,
    "start_color": 7,
    "checkpoint_color": 7,
    "goal_color": 7,
}

UI_STEP = {
    "kp": 0.01,
    "base_speed": 1,
    "color_confirm_count": 1,
    "start_color": 1,
    "checkpoint_color": 1,
    "goal_color": 1,
}
UNITS = {
    "base_speed": "%",
}
PARAM_ORDER = [
    "kp", "base_speed", "color_confirm_count",
    "start_color", "checkpoint_color", "goal_color",
]

# --- config 상수(라이브 아님, 명세 §3). 좌/우 threshold 와 PD 내부값(KD/TURN_LIMIT)은
#     stage3v2 import 로 재사용한다(이 파일에 중복 정의하지 않는다). ---
COLOR_ENTER_SETTLE_S = 0.15   # 시작 시 컬러 모드 진입 settle(주행 전 1회뿐)
COLOR_ENTER_DUMMY_READS = 2   # 진입 직후 버리는 읽기(1회뿐)
MARKER_COOLDOWN_MS = 1500     # 마커 확정 후 재확정 금지 시간
LOOP_DELAY_MS = 15
LOST_SLOWDOWN = 0.55          # bits 000 감속 배율(stage3v2 와 동일 동작)
AT_REST_SAMPLES = 5           # do read_color 판독 횟수(다수결)
AT_REST_DELAY_S = 0.02
ALLOW_DUPLICATE_NODE_COLORS = False   # 개발용: 색 3개 중복 허용
REASON_THROTTLE_S = 0.25      # LINE_FOLLOW events 폭주 방지

SAVE_PATH = os.path.join(_ROOT, "config", "stage4v2_color_follow.json")
STAGE_NAME = "stage4v2_color_follow"

ACTIONS = [
    {"name": "read_color", "label": "Read Color (at rest)"},
]


def now_ms():
    return int(time.time() * 1000)


# =====================================================================
# 판단층 (순수, ev3dev2/시간/모터 없음) — PC 테스트/replay 가능
# =====================================================================

def center_bit_from_color(color):
    """중앙 컬러코드 → 흑백 bit. 흰색(6)/없음(0)만 0, 나머지(검정+마커색)는 1(선 위)."""
    return 0 if color in (COLOR_NONE, COLOR_WHITE) else 1


def is_marker_color(color):
    """마커 후보색 여부 — 검정/흰색/없음 이 아닌 색(2,3,4,5,7)."""
    return color not in (COLOR_NONE, COLOR_BLACK, COLOR_WHITE)


def classify_node_color(color, params):
    """color → 노드 종류(stage4_color.md §5 와 동일, 우선순위 GOAL→START→CHECKPOINT).

    반환: (kind, reason_code, detail).
    """
    if color == params["goal_color"]:
        return ("GOAL", "NODE_IS_GOAL", {"color": color})
    if color == params["start_color"]:
        return ("START", "NODE_IS_START", {"color": color})
    if color == params["checkpoint_color"]:
        return ("CHECKPOINT", "NODE_IS_CHECKPOINT", {"color": color})
    return ("UNKNOWN", "NODE_IS_UNKNOWN", {"color": color})


def validate_node_colors(params, allow_duplicate):
    """시작 자기검증: 색코드 0~7 범위 + 서로 다름(allow_duplicate 면 중복 허용)."""
    names = ("start_color", "checkpoint_color", "goal_color")
    values = []
    for name in names:
        value = int(params[name])
        if value < 0 or value > 7:
            raise ValueError("{} out of range 0..7: {}".format(name, value))
        values.append(value)
    if not allow_duplicate and len(set(values)) != len(values):
        raise ValueError(
            "node colors must differ (start/checkpoint/goal = {}) — "
            "set ALLOW_DUPLICATE_NODE_COLORS for dev".format(values))


def side_bits(l_raw, r_raw, thr_l, thr_r):
    """좌/우 raw 반사광 → (l_bit, r_bit). 경계 규약은 stage3v2 black_bits 와 동일(raw<thr)."""
    return (1 if l_raw < thr_l else 0, 1 if r_raw < thr_r else 0)


def line_bits(l_raw, r_raw, color, thr_l, thr_r):
    """좌/우 반사광 + 중앙 컬러코드 → (l, c, r) bits. 가운데는 color 기반."""
    l_bit, r_bit = side_bits(l_raw, r_raw, thr_l, thr_r)
    return (l_bit, center_bit_from_color(color), r_bit)


def marker_confirm_step(color, t_ms, state, confirm_count, cooldown_ms):
    """주행 중 마커 확정 스텝(순수). state dict 를 갱신하고 확정색 또는 None 을 반환.

    state 키: marker_last(직전 마커색), marker_count(연속 카운트),
    last_marker_ms(마지막 확정 시각 — 쿨다운 기준).
    같은 마커색이 연속 confirm_count 회면 확정하고 쿨다운을 시작한다. 마커색이 아니거나
    (검정/흰색/없음) 쿨다운 중이면 리셋. 다른 마커색으로 바뀌면 1부터 다시 센다.
    제어 루프(run)와 replay 어댑터(decide_marker)가 이 함수를 공유한다.
    """
    last_marker_ms = state.get("last_marker_ms", -999999)
    in_cooldown = (t_ms - last_marker_ms) < cooldown_ms
    if in_cooldown or not is_marker_color(color):
        state["marker_last"] = None
        state["marker_count"] = 0
        return None
    if color == state.get("marker_last"):
        state["marker_count"] = state.get("marker_count", 0) + 1
    else:
        state["marker_last"] = color
        state["marker_count"] = 1
    if state["marker_count"] >= int(confirm_count):
        state["last_marker_ms"] = t_ms
        state["marker_last"] = None
        state["marker_count"] = 0
        return color
    return None


def decide_marker(sensors, params, state):
    """`tools/replay.py --decider stages.stage4v2_color_follow:decide_marker` 어댑터.

    기록된 샘플(telemetry 의 color/t_ms)을 순서대로 흘려 confirm_count/쿨다운 조합별
    마커 확정 시점을 로봇 없이 재연한다(명세 §9).
    반환: (kind, reason_code, detail) — 미확정이면 (None, None, {}).
    """
    color = sensors.get("color", COLOR_NONE)
    t_ms = sensors.get("t_ms", 0)
    confirm_count = params.get("color_confirm_count", INITIAL_PARAMS["color_confirm_count"])
    cooldown_ms = params.get("marker_cooldown_ms", MARKER_COOLDOWN_MS)

    confirmed = marker_confirm_step(color, t_ms, state, confirm_count, cooldown_ms)
    if confirmed is None:
        return None, None, {}
    # replay 는 params 를 부분만 넘길 수 있다(--set 항목만) — 색코드는 기본값으로 채운다.
    merged = dict(INITIAL_PARAMS)
    merged.update(params)
    kind, reason_code, detail = classify_node_color(confirmed, merged)
    detail = dict(detail)
    detail["count"] = int(confirm_count)
    return kind, reason_code, detail


def majority(values):
    """다수결(동수면 먼저 다수에 도달한 값). do read_color 의 판독 집계."""
    counts = {}
    best_value = None
    best_count = -1
    for value in values:
        counts[value] = counts.get(value, 0) + 1
        if counts[value] > best_count:
            best_count = counts[value]
            best_value = value
    return best_value


# =====================================================================
# 구동층 (hw 경유 — ev3dev2 직접 의존 없음, 가짜 hw 로 PC 테스트 가능)
# =====================================================================

def read_color_at_rest(hw, samples, delay_s, should_stop=None):
    """정지 상태에서 color 를 samples 회 읽어 다수결. (color, reads) 반환.

    이미 컬러 모드인 전제(read_center_color_now — 전환 없음). stop 이 걸리면 그때까지
    읽은 것으로 집계한다(없으면 COLOR_NONE).
    """
    reads = []
    for _i in range(int(samples)):
        if should_stop is not None and should_stop():
            break
        reads.append(hw.read_center_color_now())
        if delay_s > 0:
            time.sleep(delay_s)
    color = majority(reads) if reads else COLOR_NONE
    return color, reads


# =====================================================================
# telemetry 헬퍼 — 한 곳에서만 프레임을 만든다.
# =====================================================================

_TELEMETRY_DEFAULTS = {
    "mode": "follow",
    "paused": False,
    "reflect_lr": [0, 0],
    "color": 0,
    "bits": "000",
    "error": 0.0,
    "turn": 0.0,
    "left_speed": 0,
    "right_speed": 0,
    "marker_count": 0,
    "last_marker": "",
    "last_marker_color": 0,
}


def _publish(tele, params, started, **overrides):
    now = time.monotonic()
    frame = dict(_TELEMETRY_DEFAULTS)
    frame["t_ms"] = int((now - started) * 1000)
    frame["param_rev"] = params.rev()
    frame["running"] = True
    frame.update(overrides)
    tele.publish(frame)


def _maybe_follow_log(log, l_raw, r_raw, color, bits, error, turn, now, last_follow_log):
    """LINE_FOLLOW 주기 로깅(폭주 방지, stage3v2 패턴). 갱신된 시각을 반환."""
    if (now - last_follow_log) >= REASON_THROTTLE_S:
        log.log("LINE_FOLLOW", "PID", reflect_lr=[l_raw, r_raw], color=color,
                bits=bits_to_str(bits), error=error, turn=turn)
        return now
    return last_follow_log


def _log_color_read(log, method, color, l_raw, r_raw, count, params_dict):
    """COLOR_READ + NODE_IS_* 이벤트 한 쌍을 남긴다(주행 중/정지 공용)."""
    log.log("COLOR_READ", "CENTER_COLOR_MODE", method=method, color=color,
            reflect_l=l_raw, reflect_r=r_raw, count=count)
    kind, reason_code, detail = classify_node_color(color, params_dict)
    log.log(reason_code, "COLOR_{}".format(color), **detail)
    return kind


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
#   자동 시작: 좌/우 반사광 라인추종 + 주행 중 마커 색 판정. 분기 회전 없음(2단계).
#   do read_color 는 정지 판독(네트워크는 큐잉만, 제어 루프가 실행 — 비차단).
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()
    validate_node_colors(params.snapshot(), ALLOW_DUPLICATE_NODE_COLORS)

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"action": None}
    plock = threading.Lock()

    def on_stop(source):
        # 네트워크 thread 에서 호출 — 플래그만 세팅(제어 루프가 안전한 시점에 처리).
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "follow"}

    def on_do(action, args):
        # 네트워크 thread 에서 호출 — 판독을 여기서 하지 않고 제어 루프에 넘긴다(비차단).
        if action != "read_color":
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
    marker_state = {}
    last_marker = ""          # 마지막 확정 노드 종류(telemetry 지속 표시)
    last_marker_color = 0
    last_follow_log = started - REASON_THROTTLE_S

    # 컬러 모드 진입(주행 전 1회뿐) — 이후 루프는 read_center_color_now 만 쓴다.
    color0 = hw.read_center_color(COLOR_ENTER_SETTLE_S, COLOR_ENTER_DUMMY_READS)
    log.log("COLOR_MODE_ENTER", "STARTUP", color=color0,
            settle_ms=int(COLOR_ENTER_SETTLE_S * 1000), dummy=COLOR_ENTER_DUMMY_READS)

    print("stage4v2 color follow ready (auto follow, center always COL-COLOR). "
          "do read_color for at-rest measurement; "
          "stop via 'robotctl stop' or Ctrl-C.")

    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            snap = params.snapshot()

            if pause_state["paused"]:
                hw.drive(0, 0)
                l_raw, r_raw = hw.read_side_reflect()
                color = hw.read_center_color_now()
                bits = line_bits(l_raw, r_raw, color, THR_LEFT, THR_RIGHT)
                _publish(tele, params, started, mode="paused", paused=True,
                         reflect_lr=[l_raw, r_raw], color=color, bits=bits_to_str(bits),
                         last_marker=last_marker, last_marker_color=last_marker_color)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # (2) 대기 중인 do read_color (비차단 큐) — 정지 판독, 주행 미재개(사람이 이동)
            with plock:
                action = pending["action"]
                pending["action"] = None

            if action == "read_color":
                hw.stop()
                color, reads = read_color_at_rest(hw, AT_REST_SAMPLES, AT_REST_DELAY_S,
                                                  should_stop)
                l_raw, r_raw = hw.read_side_reflect()
                last_marker = _log_color_read(log, "at_rest", color, l_raw, r_raw,
                                              len(reads), snap)
                last_marker_color = color
                _publish(tele, params, started, mode="read_color",
                         reflect_lr=[l_raw, r_raw], color=color,
                         last_marker=last_marker, last_marker_color=last_marker_color)
                hw.beep_ok()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # (3) 센서 읽기 — 중앙은 컬러 모드 유지(read_reflect 금지, 명세 §8)
            l_raw, r_raw = hw.read_side_reflect()
            color = hw.read_center_color_now()
            bits = line_bits(l_raw, r_raw, color, THR_LEFT, THR_RIGHT)

            # (4) 주행 중 마커 확정(판단층 공유 스텝) — 확정해도 주행은 계속(Stage 4 범위)
            confirmed = marker_confirm_step(color, now_ms(), marker_state,
                                            snap["color_confirm_count"], MARKER_COOLDOWN_MS)
            if confirmed is not None:
                last_marker = _log_color_read(log, "driving", confirmed, l_raw, r_raw,
                                              int(snap["color_confirm_count"]), snap)
                last_marker_color = confirmed

            # (5) 라인추종 — Stage 3 확정 수식 재사용. 가운데 0 은 pd_step 이 raw[1] 을
            #     쓰지 않기 때문(명세 §0 성립 근거 — 회귀 테스트로 고정).
            left_speed, right_speed, error, derivative, turn = pd_step(
                pd, (l_raw, 0, r_raw), snap)
            if bits == (0, 0, 0):
                # 전부 흰색이면 직전 조향 유지한 채 감속(stage3v2 와 동일 동작).
                left_speed *= LOST_SLOWDOWN
                right_speed *= LOST_SLOWDOWN
            hw.drive(left_speed, right_speed)

            now = time.monotonic()
            last_follow_log = _maybe_follow_log(log, l_raw, r_raw, color, bits,
                                                error, turn, now, last_follow_log)

            _publish(tele, params, started, mode="follow",
                     reflect_lr=[l_raw, r_raw], color=color, bits=bits_to_str(bits),
                     error=error, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     marker_count=marker_state.get("marker_count", 0),
                     last_marker=last_marker, last_marker_color=last_marker_color)

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()
    print("stage4v2 color follow stopped.")


if __name__ == "__main__":
    run()
