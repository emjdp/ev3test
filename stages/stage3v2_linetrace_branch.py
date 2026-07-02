#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3 v2 — 라인추종 + 분기 탱크 회전 (실험 통합 트랙).

`stages/only_linetrace.py`(실기 1차 보정 완료, 커밋 069237d)를 정리·개명한 버전이다.
좌/중/우 3센서 PD 라인추종은 그대로 두고(raw 차 기반 `PdController`, 기존과 동일),
**회전만 Stage 2 확정 코드로 교체**한다:

  - 인라인 `run_encoder_turn`/`wheel_dirs`/`encoder_target` 를 **제거**하고
    `lib/turns.pivot`(엔코더 폴링 탱크 회전) + `lib/decide_turn.decide_turn`(목표각/보정계수
    계산 — Stage 2 판단층)을 **그대로 재사용**한다. 둘 다 여기서 고치지 않는다.
  - `branch_side` 로 좌/우 분기를 모두 감지한다(구 `is_left_branch` 는 좌만 봤다).
  - 분기 확정 후 **`advance_straight`(엔코더 직진)로 교차점 위까지 전진**한 다음
    회전한다(`branch_advance_mm` 손잡이 — only_linetrace 실기에서 confirm_count 를
    상한(19/20) 근처까지 올려도 회전이 일렀던 문제의 정공법).

**미해결(§11, docs/specs/stage3v2_linetrace_branch.md)**: 탱크/컴퍼스 실기 관측 불일치
원인, 라이브 6개 셋 확정, 좌/우 factor 분리, `do follow` 자동/수동. 이 구현은 **자동
시작**(only_linetrace 실기 검증된 동작 유지)을 기본으로 하고, 수동 `do turn_left/
turn_right/uturn` 은 별도 트리거로 둔다 — Codex 검증에서 이 선택을 재확인 요청.

독립 실행(브릭):  python3 stages/stage3v2_linetrace_branch.py
문법 점검(PC):    python3 -m py_compile stages/stage3v2_linetrace_branch.py lib/*.py
판단층 테스트(PC): python3 tests/test_stage3v2_logic.py

규약:
  - 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
  - ev3dev2 import 는 구동층(lib/hardware.py) 안에서만 → PC py_compile 통과.
  - BACK 버튼은 프로그램 입력으로 할당하지 않는다(ev3dev 기본 종료 동작으로 둠).
  - 정지는 네트워크 stop(robotctl stop / 대시보드 s) 또는 키보드 인터럽트.

자세한 명세: docs/specs/stage3v2_linetrace_branch.md
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

from lib.shared_params import SharedParams                       # noqa: E402
from lib.telemetry import Telemetry                               # noqa: E402
from lib.decision_log import DecisionLog                          # noqa: E402
from lib.tuning_server import TuningServer                        # noqa: E402
from lib.decide_turn import decide_turn, target_degrees            # noqa: E402 (Stage 2 판단층 재사용)
from lib.turns import pivot                                        # noqa: E402 (Stage 2 구동층 재사용, 미수정)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 파일 맨 위 상수 = 이 스테이지의 초기 params dict + 안전장치 (STAGES.md)
# =====================================================================

# 라이브 params (정확히 6개; 명세 §3 / LIVE_TUNING.md 한도). 회전 거동(속도·보정계수·분기
# 시점)에 초점. threshold/kd/turn_limit 등은 아래 config 상수로 내린다(§3 "대안 세트").
INITIAL_PARAMS = {
    "kp": 0.22,                  # 조향 게인(raw 차). 곡선 못 따라가면 ↑, 흔들리면 ↓
    "base_speed": 12,            # 직진 속도(%)
    "turn_speed": 6,             # 탱크 회전 속도(%)
    "turn_90_factor": 1.0,       # 90° 보정계수(Stage 2 BASE_PIVOT_DEG_90 에 곱함)
    "branch_confirm_count": 4,   # 분기 확정 연속횟수(오탐 방지). advance_mm 도입으로 낮게 시작
    "branch_advance_mm": 20,     # 확정 후 회전 전 전진거리(mm) = 회전 시점 손잡이
}

PARAM_LIMITS = {
    "kp": (0.0, 3.0),
    "base_speed": (5, 45),
    "turn_speed": (5, 40),
    "turn_90_factor": (0.5, 2.0),
    "branch_confirm_count": (1, 20),
    "branch_advance_mm": (0, 120),
}

# 한 번에 큰 변화 금지(한 번에 변수 하나 원칙 보조). 서버가 초과 set 을 거부한다.
MAX_STEP = {
    "kp": 0.1,
    "base_speed": 5,
    "turn_speed": 5,
    "turn_90_factor": 0.05,
    "branch_confirm_count": 2,
    "branch_advance_mm": 10,
}

# 대시보드 표시용 메타(안전과 무관).
UI_STEP = {
    "kp": 0.01,
    "base_speed": 1,
    "turn_speed": 1,
    "turn_90_factor": 0.01,
    "branch_confirm_count": 1,
    "branch_advance_mm": 10,
}
UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "turn_90_factor": "x",
    "branch_advance_mm": "mm",
}
PARAM_ORDER = [
    "kp", "base_speed", "turn_speed", "turn_90_factor",
    "branch_confirm_count", "branch_advance_mm",
]

# --- 라이브 param 이 아닌 파일 상수(6개 규칙 유지). only_linetrace.py 1차 실기 보정값을
#     시드로 쓴다(config/stage1_linetrace.json, 2026-07-01 커밋 069237d 저장분과 동일). ---
THR_LEFT = 43
THR_CENTER = 36
THR_RIGHT = 42
KD = 0.05                    # D항 게인(config, 라이브 아님). only_linetrace 1차 실기 보정값.
TURN_LIMIT = 16
TURN_180_FACTOR = 0.8        # U턴은 옵션(§11) — 수동 do uturn 트리거용으로만 유지
POST_TURN_SETTLE_MS = 90
BRANCH_COOLDOWN_MS = 1500
LOOP_DELAY_MS = 15
ADVANCE_SPEED = 15           # branch_advance_mm 전진 속도(%). 느리게 고정(config)
REASON_THROTTLE_S = 0.25     # LINE_FOLLOW events 폭주 방지(상태유지 중 주기 기록)

# Stage 2 확정 기하값과 동일 공식(lib/decide_turn.py 기준) — 여기서 재계산하지 않는다.
BASE_PIVOT_DEG_90 = 193.0
BASE_PIVOT_DEG_180 = BASE_PIVOT_DEG_90 * 2.0

# 바퀴 지름 → 1도당 이동거리(mm). Stage 3(아날로그 트랙)과 동일 가정(d≈56mm, 미실측).
WHEEL_DIAM_MM = 56.0
MM_PER_DEG = math.pi * WHEEL_DIAM_MM / 360.0

SAVE_PATH = os.path.join(_ROOT, "config", "stage3v2_linetrace_branch.json")
STAGE_NAME = "stage3v2_linetrace_branch"

# do 트리거로 누를 수 있는 동작(서버가 manifest 로 검증/노출). 좌/우 90 은 Stage 2 factor
# 보정용 수동 트리거(선 없이 제자리 회전만); uturn 은 옵션(§11).
ACTIONS = [
    {"name": "turn_left", "label": "Turn Left 90"},
    {"name": "turn_right", "label": "Turn Right 90"},
    {"name": "uturn", "label": "U-Turn 180"},
]


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def now_ms():
    return int(time.time() * 1000)


def bits_to_str(bits):
    return "".join(["1" if item else "0" for item in bits])


# =====================================================================
# 판단층 (순수, ev3dev2/시간/모터 없음) — PC 테스트/replay 가능
# =====================================================================

def black_bits(raw, thresholds):
    """좌/중/우 raw 반사광 → (l, c, r) 흑(1)/백(0) bits. thresholds=(thr_l, thr_c, thr_r)."""
    return tuple([1 if raw[i] < thresholds[i] else 0 for i in range(3)])


def branch_side(bits):
    """분기 방향 판정(명세 §2). 110/111→'left', 011→'right'.

    단독 드리프트(100/001)는 분기가 아니다(중앙이 살아 있어야 분기로 본다).
    """
    if bits == (1, 1, 0) or bits == (1, 1, 1):
        return "left"
    if bits == (0, 1, 1):
        return "right"
    return None


def branch_confirm_step(side, branch_seen, t_ms, last_turn_ms, confirm_count, cooldown_ms,
                        last_side=None):
    """분기 확정 카운터 갱신(순수). 쿨다운 중이거나 분기가 아니면 리셋.

    Codex 검증(2026-07-02)에서 지적된 버그 수정: **같은 방향이 연속으로** 잡혀야 카운트가
    쌓인다. `side is not None` 만 보면 `110/011/110/011` 처럼 좌/우가 번갈아 흔들려도
    (직전 side 와 달라도) 카운트가 계속 올라가 confirm_count 도달 시 마지막으로 본 방향
    으로 오회전할 수 있었다 — 실기에서 가장 위험한 케이스. `last_side` 가 바뀌면 1로
    다시 시작한다(0 이 아니라 1 — 지금 본 것 자체가 그 방향의 첫 감지이므로).

    반환: (new_branch_seen, confirmed:bool, new_last_side)
    """
    in_cooldown = (t_ms - last_turn_ms) < cooldown_ms
    if side is not None and not in_cooldown:
        branch_seen = branch_seen + 1 if side == last_side else 1
        new_last_side = side
    else:
        branch_seen = 0
        new_last_side = None
    confirmed = branch_seen >= int(confirm_count)
    return branch_seen, confirmed, new_last_side


def turn_target_deg(action, params):
    """action('LEFT90'/'RIGHT90'/'UTURN180') + 보정계수 → 목표 바퀴각(도).

    Stage 2 `lib.decide_turn.target_degrees` 를 그대로 재사용한다(같은 공식을 이 파일에
    중복 구현하지 않는다 — AGENTS §1). params 는 BASE_PIVOT_DEG_90/180·turn_90_factor·
    turn_180_factor 를 포함해야 한다.
    """
    return target_degrees(action, params)


def decide_branch(sensors, params, state):
    """`tools/replay.py --decider stages.stage3v2_linetrace_branch:decide_branch` 어댑터.

    기록된 샘플(반사광)을 순서대로 흘려 분기 확정 시점(confirm_count/advance_mm 조합별)을
    로봇 없이 재연한다(명세 §9). sensors 는 telemetry 샘플 1행(JSON), state 는 replay 가
    행마다 이어서 넘기는 dict(branch_seen/last_turn_ms 를 여기서 갱신).

    반환: (action, reason_code, detail) — 미확정이면 (None, None, {}).
    """
    reflect = sensors.get("reflect")
    if reflect is None:
        reflect = (sensors.get("reflect_l", 100), sensors.get("reflect_c", 100),
                   sensors.get("reflect_r", 100))
    thresholds = (
        params.get("thr_left", THR_LEFT),
        params.get("thr_center", THR_CENTER),
        params.get("thr_right", THR_RIGHT),
    )
    bits = black_bits(tuple(reflect), thresholds)
    side = branch_side(bits)
    t_ms = sensors.get("t_ms", 0)

    branch_seen = state.get("branch_seen", 0)
    last_turn_ms = state.get("last_turn_ms", -999999)
    last_side = state.get("last_branch_side")
    confirm_count = params.get("branch_confirm_count", INITIAL_PARAMS["branch_confirm_count"])
    cooldown_ms = params.get("branch_cooldown_ms", BRANCH_COOLDOWN_MS)

    branch_seen, confirmed, last_side = branch_confirm_step(
        side, branch_seen, t_ms, last_turn_ms, confirm_count, cooldown_ms, last_side)
    state["branch_seen"] = branch_seen
    state["last_branch_side"] = last_side

    if not confirmed:
        return None, None, {}

    state["last_turn_ms"] = t_ms
    state["branch_seen"] = 0
    state["last_branch_side"] = None
    action = "LEFT90" if side == "left" else "RIGHT90"
    reason_code = "BRANCH_LEFT" if side == "left" else "BRANCH_RIGHT"
    detail = {
        "bits": bits_to_str(bits),
        "branch_seen": branch_seen,
        "advance_mm": params.get("branch_advance_mm", INITIAL_PARAMS["branch_advance_mm"]),
    }
    return action, reason_code, detail


class PdController(object):
    """3센서 PD 라인추종(only_linetrace.py 와 동일 — raw 좌/우 차 기반, 변경 없음)."""

    def __init__(self):
        self.prev_error = 0.0
        self.prev_t = None

    def reset(self):
        self.prev_error = 0.0
        self.prev_t = None

    def step(self, raw, params):
        # Error convention:
        # left sensor black -> left reflect low, right reflect high -> positive error.
        # Positive turn slows left wheel and speeds right wheel, so the robot turns left.
        error = float(raw[2] - raw[0])
        t = time.time()
        if self.prev_t is None:
            dt = 0.001
            derivative = 0.0
        else:
            dt = t - self.prev_t
            if dt <= 0:
                dt = 0.001
            derivative = (error - self.prev_error) / dt

        turn = params["kp"] * error + KD * derivative
        turn = clamp(turn, -TURN_LIMIT, TURN_LIMIT)

        left_speed = params["base_speed"] - turn
        right_speed = params["base_speed"] + turn
        left_speed = clamp(left_speed, -100, 100)
        right_speed = clamp(right_speed, -100, 100)

        self.prev_error = error
        self.prev_t = t
        return left_speed, right_speed, error, derivative, turn


def pd_step(pd, raw, params):
    """명세 §2 `pd_step` — 기존 PdController 인스턴스로 위임(중복 구현 아님)."""
    return pd.step(raw, params)


# =====================================================================
# 구동층 (hw 경유 — ev3dev2 직접 의존 없음, 가짜 hw 로 PC 테스트 가능)
# =====================================================================

def deg_to_mm(deg):
    return deg * MM_PER_DEG


def advance_straight(hw, distance_mm, speed, should_stop=None, should_pause=None):
    """엔코더 기준 직진 전진(회전 전 차체 중심을 교차점 위로).

    lib/turns.pivot 과 동일한 폴링 패턴(엔코더 기준 정지, stop/pause 즉시 반응).
    distance_mm<=0 이면 전진 없이 0.0. 반환: 실제 전진 거리(mm).
    """
    hw.reset_encoders()
    if distance_mm <= 0:
        hw.stop()
        return 0.0
    if should_stop is not None and should_stop():
        hw.stop()
        return 0.0

    hw.drive(speed, speed)
    try:
        while True:
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
                hw.drive(speed, speed)
            if deg_to_mm(hw.enc_avg()) >= distance_mm:
                break
            time.sleep(0.005)
    finally:
        hw.stop()
    return deg_to_mm(hw.enc_avg())


def _tick_stop(base_should_stop, on_tick):
    """should_stop 콜백에 텔레메트리 부수효과를 얹는다.

    lib/turns.pivot·advance_straight 는 폴링마다 should_stop() 을 부르므로, 그 타이밍에
    얹어 회전/전진 중에도 telemetry 를 흘린다(pivot 자체는 수정하지 않는다 — 호출부에서만
    래핑).
    """
    def _fn():
        on_tick()
        return base_should_stop()
    return _fn


# =====================================================================
# telemetry 헬퍼 — 한 곳에서만 프레임을 만든다(인프라 공통 필드 + Stage 3 v2 키).
# =====================================================================

_TELEMETRY_DEFAULTS = {
    "mode": "follow",
    "paused": False,
    "reflect": [0, 0, 0],
    "bits": "000",
    "error": 0.0,
    "turn": 0.0,
    "left_speed": 0,
    "right_speed": 0,
    "branch_seen": 0,
    "target_deg": 0.0,
    "enc_l": 0,
    "enc_r": 0,
    "enc_avg": 0.0,
    "advance_mm": 0.0,
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
# 회전 1회 (판단 → 구동 → 로깅). 수동 do 트리거와 자동 분기 트리거가 공유한다.
# =====================================================================

def _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started):
    """decide_turn(Stage 2 판단층) + pivot(Stage 2 구동층)으로 회전 1회 실행+기록.

    cmd: 'turn_left' | 'turn_right' | 'uturn'. TURN_LEFT/TURN_RIGHT/UTURN reason 은
    Stage 2 카탈로그 그대로 재사용(신규 추가 없음). BRANCH_LEFT/RIGHT(분기 감지) 는
    호출부(run 의 분기 확정 블록)에서 이 함수 호출 전에 따로 남긴다.
    """
    snap = params.snapshot()
    snap["BASE_PIVOT_DEG_90"] = BASE_PIVOT_DEG_90
    snap["BASE_PIVOT_DEG_180"] = BASE_PIVOT_DEG_180
    snap["turn_180_factor"] = TURN_180_FACTOR
    param_rev = params.rev()

    action, reason_code, detail = decide_turn(cmd, snap, {})
    target = detail["target_deg"]
    turn_speed = snap["turn_speed"]

    def on_tick():
        el, er = hw.read_encoders()
        _publish(tele, params, started, mode="turning", target_deg=target,
                 enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

    stopper = _tick_stop(should_stop, on_tick)
    actual = pivot(hw, action, target, turn_speed, should_stop=stopper, should_pause=should_pause)

    if POST_TURN_SETTLE_MS > 0:
        time.sleep(POST_TURN_SETTLE_MS / 1000.0)

    enc_l, enc_r = hw.read_encoders()
    ev_detail = dict(detail)
    rule = ev_detail.pop("rule", "DO_TRIGGER")
    ev_detail["param_rev"] = param_rev
    ev_detail["enc_l"] = enc_l
    ev_detail["enc_r"] = enc_r
    ev_detail["enc_avg"] = actual
    ev_detail["error_deg"] = actual - target
    ev_detail["stopped_early"] = bool(should_stop())
    log.log(reason_code, rule, **ev_detail)

    _publish(tele, params, started, mode="follow", target_deg=target,
             enc_l=enc_l, enc_r=enc_r, enc_avg=actual)

    hw.beep_ok()
    return actual


def _maybe_follow_log(log, reflect, error, turn, now, last_follow_log):
    """LINE_FOLLOW 주기 로깅(폭주 방지). Codex 검증(2026-07-02) 지적 반영 — 명세 §4/
    DECISIONS.md 카탈로그가 요구하는 reason_code 인데 누락돼 있었다(telemetry 만 흘렸음).
    갱신된 last_follow_log 시각을 반환한다.
    """
    if (now - last_follow_log) >= REASON_THROTTLE_S:
        log.log("LINE_FOLLOW", "PID", reflect=list(reflect), error=error, turn=turn)
        return now
    return last_follow_log


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
#   자동 시작: 라인추종 + 좌/우 분기 탱크 회전(only_linetrace 실기 검증 동작 유지, §11).
#   do turn_left/turn_right/uturn 은 별도 수동 트리거(선 없이 제자리 회전, factor 보정용).
# =====================================================================

def run():
    from lib.hardware import Ev3Hardware  # ev3dev2 (브릭에서만)

    params = SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, SAVE_PATH,
                          ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)
    params.load_saved_into_defaults()

    tele = Telemetry()
    log = DecisionLog(telemetry=tele)
    hw = Ev3Hardware()
    pd = PdController()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"turn": None}
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
        # 네트워크 thread 에서 호출 — 회전을 여기서 돌리지 않고 제어 루프에 넘긴다(비차단).
        if action not in ("turn_left", "turn_right", "uturn"):
            return {"error": "unknown action: {}".format(action)}
        with plock:
            pending["turn"] = action
        return {"queued": action}

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

    print("stage3v2 linetrace+branch ready (auto follow). "
          "do turn_left/turn_right/uturn for manual calibration; "
          "stop via 'robotctl stop' or Ctrl-C.")

    try:
        while True:
            # (1) 네트워크 stop 정지 플래그 (BACK 버튼은 쓰지 않는다)
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.drive(0, 0)
                raw = hw.read_reflect()
                bits = black_bits(raw, thresholds)
                enc_l, enc_r = hw.read_encoders()
                _publish(tele, params, started, mode="paused", paused=True,
                         reflect=list(raw), bits=bits_to_str(bits),
                         branch_seen=branch_seen, enc_l=enc_l, enc_r=enc_r,
                         enc_avg=hw.enc_avg())
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # (2) 대기 중인 수동 회전 트리거(비차단 큐)
            with plock:
                turn_cmd = pending["turn"]
                pending["turn"] = None

            if turn_cmd is not None:
                _run_turn(hw, turn_cmd, params, log, tele, should_stop, should_pause, started)
                pd.reset()
                branch_seen = 0
                last_branch_side = None
                last_turn_ms = now_ms()
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            # (3) 3센서 읽기 + 분기 판정
            snap = params.snapshot()
            raw = hw.read_reflect()
            bits = black_bits(raw, thresholds)
            side = branch_side(bits)
            t_ms = now_ms()

            branch_seen, confirmed, last_branch_side = branch_confirm_step(
                side, branch_seen, t_ms, last_turn_ms,
                snap["branch_confirm_count"], BRANCH_COOLDOWN_MS, last_branch_side)

            if confirmed:
                hw.stop()
                reason = "BRANCH_LEFT" if side == "left" else "BRANCH_RIGHT"
                mode_name = "branch_left" if side == "left" else "branch_right"
                log.log(reason, "BITS_" + bits_to_str(bits), bits=bits_to_str(bits),
                        branch_seen=branch_seen, advance_mm=snap["branch_advance_mm"],
                        reflect=list(raw))
                enc_l, enc_r = hw.read_encoders()
                _publish(tele, params, started, mode=mode_name, reflect=list(raw),
                         bits=bits_to_str(bits), branch_seen=branch_seen,
                         enc_l=enc_l, enc_r=enc_r, enc_avg=hw.enc_avg(),
                         advance_mm=snap["branch_advance_mm"])

                # (a) 확정 후 전진(교차점 위로) — branch_advance_mm 손잡이
                def on_advance_tick():
                    el, er = hw.read_encoders()
                    _publish(tele, params, started, mode="advancing",
                             advance_mm=snap["branch_advance_mm"],
                             enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

                advance_straight(hw, snap["branch_advance_mm"], ADVANCE_SPEED,
                                 _tick_stop(should_stop, on_advance_tick), should_pause)

                pd.reset()
                branch_seen = 0
                last_branch_side = None
                last_turn_ms = now_ms()

                if should_stop():
                    # Codex 검증(2026-07-02): advance 중 stop 이 걸리면 회전은 건너뛴다.
                    # _run_turn 을 그대로 부르면 pivot() 은 안 돌지만(should_stop 즉시 체크)
                    # TURN_LEFT/RIGHT 로그·beep 은 남아 "실제로 안 돈 회전"이 기록으로
                    # 남는다 — 다음 루프 맨 위(1)에서 EMERGENCY_STOP 으로 정리한다.
                    continue

                # (b) 제자리 탱크 회전(Stage 2 재사용) — TURN_LEFT/RIGHT reason 공유
                cmd = "turn_left" if side == "left" else "turn_right"
                _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started)
                continue

            # (4) 라인추종 (PD, raw 차 기반 — only_linetrace 와 동일)
            left_speed, right_speed, error, derivative, turn = pd_step(pd, raw, snap)
            if bits == (0, 0, 0):
                # 전부 흰색이면 직전 조향 유지한 채 감속(only_linetrace 와 동일).
                left_speed *= 0.55
                right_speed *= 0.55
            hw.drive(left_speed, right_speed)

            now = time.monotonic()
            last_follow_log = _maybe_follow_log(log, raw, error, turn, now, last_follow_log)

            enc_l, enc_r = hw.read_encoders()
            _publish(tele, params, started, mode="follow", reflect=list(raw),
                     bits=bits_to_str(bits), error=error, turn=turn,
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
    print("stage3v2 linetrace+branch stopped.")


if __name__ == "__main__":
    run()
