#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze.py — 완주 전용 통합 실행 파일 (v4: 우>좌>직 우선순위 + 직전 분기 기억).

v4 탐색 로직 (미로를 모른다는 전제):
  - 모든 노드/커브 후보에서: 정지 → 조금 전진(node_advance_mm) → 중앙 색상으로
    직진 길 유무 재판정 (매번 수행).
  - 갈 수 있는 길이 1개뿐이면 강제 이동(커브): 그쪽으로 회전. 기억 갱신 없음.
  - 갈 수 있는 길이 2개 이상이면 분기점: 우측 > 좌측 > 직진 우선순위로 선택.
    단, 막다른 노드(파랑/000)에서 유턴해 돌아오는 길(returning)이라면
    "왔던 길로 되돌아가는 방향"을 제외하고 고른다:
      진입을 좌회전으로 했으면 → 복귀 시 우측 제외
      진입을 우회전으로 했으면 → 복귀 시 좌측 제외
      진입을 직진으로 했으면   → 복귀 시 직진 제외
    (직전 분기 1개만 기억. 가지 안에 커브가 있어도 그대로 되짚어 나오므로
     분기점에서의 상대 방향 관계는 유지된다.)
  - 파랑(방문 노드): 즉시 정지+유턴, returning 세팅. 빨강: 도착. 노랑: 출발 대기.
  - 이 로직으로 지도상 노드 3개(우상단 2, 중앙 1)는 방문 못함 — 완주 우선,
    노드 살리기는 다음 단계.

라이브 튜닝(이 파일이 실제로 만지는 손잡이만, docs/LIVE_TUNING.md): 원문(첨부 v4)에 ★/⚠
로 "실기에서 보정 필요"라고 표시된 값만 SharedParams 로 노출한다 — 조향/노드 임계값,
Stage 2/3 확정 게인·타이밍은 이미 검증된 값이라 이 파일 상단 config 상수로 고정한다.
  - `left_th_steer` / `right_th_steer` : ⚠ 흔들리면 66~67 로 낮출 것(원문 경고).
  - `node_advance_mm`                  : ★ 확정 후 재판정/회전 전 전진량.
  - `turn_90_factor` / `turn_180_factor`: ★ 과/부족 시 0.05 단위 미세조정.
  - `grab_dist_cm` / `grip_speed`      : ★ 조립에 따라 실기값·부호가 다름.

실시간 대시보드(다른 스테이지와 동일한 인프라, docs/LIVE_TUNING.md):
  1) 브릭에서 이 파일 실행(아래) → tuning 서버가 127.0.0.1:8765 에 뜬다.
  2) 노트북에서 SSH 터널: ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local
  3) 노트북에서 tools/dashboard.py 실행(curses TUI) — 파라미터 조정/이벤트/telemetry 확인.
     또는 tools/robotctl.py get/set/stop/do/save/rollback (비대화형).

v3 유지: 임계값 2단 분리 — 조향용(좌69/우67)은 반걸침부터 보정,
  노드 판정용(좌20/우18)은 거의 완전 덮임만 후보. 드리프트 오검출 차단.
  실측: 흰바닥 74/78, 반걸침 65/57, 2/3걸침 30/26, 완전검정(추정) 11~12.

센서 운용: 중앙(in2)=항상 색상모드, 좌(in1)/우(in3)=항상 반사광모드.

스테이지 발췌값/규약 (팀원 코드):
  Stage 0 포트: outA=좌주행, outB=우주행, outC=그리퍼,
                in1=좌컬러, in2=중앙컬러, in3=우컬러, in4=초음파.
  Stage 1: left = base - turn, right = base + turn.
  Stage 2: 회전 = lib/turns.pivot(엔코더 각도 + 보정계수, 90°=193°, 180°=386°) 재사용.
  Stage 3: bits 추종(gain=12, limit 35), confirm 120ms + debounce 900ms(확정값, config 상수).

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C.

독립 실행(브릭):  python3 stages/run_maze.py
문법 점검(PC):    python3 -m py_compile stages/run_maze.py lib/*.py
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

from lib.shared_params import SharedParams                         # noqa: E402
from lib.telemetry import Telemetry                                 # noqa: E402
from lib.decision_log import DecisionLog                            # noqa: E402
from lib.tuning_server import TuningServer                          # noqa: E402
from lib.decide_turn import decide_turn                              # noqa: E402 (Stage 2 판단층 재사용)
from lib.turns import pivot                                          # noqa: E402 (Stage 2 구동층 재사용, 미수정)
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 라이브 params — 원문(v4)이 ★/⚠ 로 실기 보정 필요라고 표시한 값만(7개).
# =====================================================================

INITIAL_PARAMS = {
    "left_th_steer": 69,      # ⚠ 흔들림 증상 나오면 66~67 로 낮출 것(원문 경고)
    "right_th_steer": 67,
    "node_advance_mm": 30,    # ★ 확정 후 재판정/회전 전 전진량
    "turn_90_factor": 0.75,   # ★ 과/부족 시 0.05 단위 미세조정
    "turn_180_factor": 0.75,  # ★ 유턴도 같은 비율로 과회전 가감 → 실기에서 확인
    "grab_dist_cm": 6.0,      # ★ 조립에 따라 실기값 다름
    "grip_speed": 30,         # ★ 조립에 따라 부호 반전
}

PARAM_LIMITS = {
    "left_th_steer": (0, 100),
    "right_th_steer": (0, 100),
    "node_advance_mm": (0, 120),
    "turn_90_factor": (0.3, 2.0),
    "turn_180_factor": (0.3, 2.0),
    "grab_dist_cm": (1.0, 20.0),
    "grip_speed": (5, 80),
}

MAX_STEP = {
    "left_th_steer": 3,
    "right_th_steer": 3,
    "node_advance_mm": 10,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "grab_dist_cm": 1.0,
    "grip_speed": 5,
}

UI_STEP = {
    "left_th_steer": 1,
    "right_th_steer": 1,
    "node_advance_mm": 10,
    "turn_90_factor": 0.01,
    "turn_180_factor": 0.01,
    "grab_dist_cm": 0.5,
    "grip_speed": 1,
}
UNITS = {
    "left_th_steer": "%",
    "right_th_steer": "%",
    "node_advance_mm": "mm",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "grab_dist_cm": "cm",
    "grip_speed": "%",
}
PARAM_ORDER = [
    "left_th_steer", "right_th_steer", "node_advance_mm",
    "turn_90_factor", "turn_180_factor", "grab_dist_cm", "grip_speed",
]

# =====================================================================
# config 상수(라이브 아님) — 이미 확정된 Stage 2/3 게인·타이밍, 기하값.
# =====================================================================

# --- 깊은 조향/노드 판정 임계값(Stage 3 확정 감도, 원문 그대로) ---
LEFT_TH_DEEP = 47
RIGHT_TH_DEEP = 41
LEFT_TH_NODE = 20
RIGHT_TH_NODE = 18

# --- Stage 3 확정값: bits 추종 ---
BASE_SPEED = 20
FOLLOW_GAIN = 12.0
TURN_LIMIT = 35
SLOW_SPEED = 12

# --- Stage 3 확정값: 노드 판정 타이밍 ---
NODE_CONFIRM_MS = 120
NODE_DEBOUNCE_MS = 900

# --- Stage 2 확정값: 회전(BASE_PIVOT_DEG_90/180 은 lib/decide_turn.py 계약과 동일 키) ---
TURN_SPEED = 18
BASE_PIVOT_DEG_90 = 193.0
BASE_PIVOT_DEG_180 = 386.0
POST_TURN_SETTLE_MS = 120

# --- 기하(바퀴지름 56mm 가정) + 직진/전진 속도 ---
WHEEL_DIAM_MM = 56.0
MM_PER_DEG = math.pi * WHEEL_DIAM_MM / 360.0
STRAIGHT_SPEED = 15

# --- 이벤트 타이밍 ---
COLOR_DEBOUNCE_MS = 1500
START_EXIT_MM = 50
GRIP_SEC = 0.8
LOOP_DELAY_MS = 15
REASON_THROTTLE_S = 0.25   # LINE_FOLLOW 이벤트 폭주 방지

# ev3dev2 ColorSensor.color 값 (0=없음 1=검정 2=파랑 3=초록 4=노랑 5=빨강 6=흰 7=갈)
COL_BLACK, COL_BLUE, COL_YELLOW, COL_RED = 1, 2, 4, 5

# 노드 후보 bits (엄격 임계값 bits 기준)
CANDIDATES = ((1, 1, 0), (0, 1, 1), (1, 1, 1), (1, 0, 1), (0, 0, 0))
SLOW_ON = ((1, 1, 1), (1, 0, 1))

# 복귀(returning) 시 제외할 방향: 진입 턴의 반대가 "왔던 길"
OPPOSITE = {"L": "R", "R": "L", "S": "S"}

SAVE_PATH = os.path.join(_ROOT, "config", "run_maze.json")
STAGE_NAME = "run_maze"

# do 트리거: 자율주행 중에도 언제든 큐잉되며, 제어 루프가 한 틱을 써서 처리한다
# (bench/stage4d 패턴과 동일 — 비차단). 출발 대기/paused 중 임계값 캘리브레이션용.
ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
]


# =====================================================================
# 판단층 (순수 — PC 테스트 가능). 입력은 전부 인자로 받는다(전역 참조 없음).
# =====================================================================

def steer_level(reflect, th_shallow, th_deep):
    """걸침 깊이 단계: 0=흰바닥, 1=얕은 걸침(반 정도), 2=깊은 걸침(2/3 이상)."""
    if reflect < th_deep:
        return 2
    if reflect < th_shallow:
        return 1
    return 0


def line_error(l_lv, center_black, r_lv):
    """계단식 위치 오차. +면 선이 왼쪽 → 왼쪽 보정 (left=base-turn 규약).

    중앙이 라인 위: 얕은 걸침 ±0.5, 깊은 걸침 ±1.0 (걸친 만큼 틀기)
    중앙이 놓침:   해당 방향 ±2.0 (복구 우선)
    양쪽이 같은 단계면 0 (직진).
    """
    if l_lv == r_lv:
        return 0.0
    if center_black:
        if l_lv > r_lv:
            return 0.5 if l_lv == 1 else 1.0
        return -0.5 if r_lv == 1 else -1.0
    if l_lv > r_lv:
        return 2.0
    return -2.0


def bits_node(reflect_l, center_color, reflect_r, left_th_node, right_th_node):
    """노드 판정용 bits (엄격한 임계값 — 완전 검정에서만 1)."""
    return (1 if reflect_l < left_th_node else 0,
            1 if center_color == COL_BLACK else 0,
            1 if reflect_r < right_th_node else 0)


def choose_branch(has_left, has_right, has_straight, exclude):
    """분기 선택: 우 > 좌 > 직진, exclude 방향은 후보에서 제외.

    반환 "R"/"L"/"S", 고를 게 없으면 "U"(유턴).
    """
    for opt, ok in (("R", has_right), ("L", has_left), ("S", has_straight)):
        if ok and opt != exclude:
            return opt
    return "U"


def clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def bits_to_str(bits):
    return "".join(["1" if item else "0" for item in bits])


# =====================================================================
# 구동층 헬퍼(hw 경유, ev3dev2 직접 의존 없음 — 가짜 hw 로 PC 테스트 가능)
# =====================================================================

def advance_straight(hw, distance_mm, speed, should_stop=None, should_pause=None):
    """엔코더 기준 직진 전진(lib/turns.pivot 과 동일한 폴링 패턴).

    distance_mm<=0 이면 전진 없이 0.0. 반환: 실제 전진 거리(mm).
    """
    hw.reset_encoders()
    if distance_mm <= 0:
        hw.stop()
        return 0.0
    if should_stop is not None and should_stop():
        hw.stop()
        return 0.0

    target_deg = distance_mm / MM_PER_DEG
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
            if hw.enc_avg() >= target_deg:
                break
            time.sleep(0.005)
    finally:
        hw.stop()

    return hw.enc_avg() * MM_PER_DEG


def _tick_stop(base_should_stop, on_tick):
    """should_stop 콜백에 telemetry 부수효과를 얹는다(pivot/advance_straight 는 수정하지
    않고 호출부에서만 래핑 — stage3v2 와 동일 패턴)."""
    def _fn():
        on_tick()
        return base_should_stop()
    return _fn


_TELEMETRY_DEFAULTS = {
    "mode": "idle",
    "paused": False,
    "reflect_l": 0,
    "reflect_r": 0,
    "color": None,
    "bits": "000",
    "error": 0.0,
    "turn": 0.0,
    "left_speed": 0,
    "right_speed": 0,
    "visits": 0,
    "arrived": False,
    "last_turn": None,
    "returning": False,
    "grabbed": False,
}


def _publish(tele, params, started, **overrides):
    frame = dict(_TELEMETRY_DEFAULTS)
    frame["t_ms"] = int((time.monotonic() - started) * 1000)
    frame["param_rev"] = params.rev()
    frame["running"] = True
    frame.update(overrides)
    tele.publish(frame)


def _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started):
    """decide_turn(Stage 2 판단층) + pivot(Stage 2 구동층)으로 회전 1회 실행+기록.

    cmd: 'turn_left' | 'turn_right' | 'uturn'. TURN_LEFT/TURN_RIGHT/UTURN reason 은
    DECISIONS.md 카탈로그 그대로 재사용(신규 추가 없음). 분기/커브의 "왜"는 호출부가
    이 함수 호출 전에 NODE_CHOICE/NODE_CURVE/DEAD_END 로 따로 남긴다.
    """
    snap = params.snapshot()
    snap["BASE_PIVOT_DEG_90"] = BASE_PIVOT_DEG_90
    snap["BASE_PIVOT_DEG_180"] = BASE_PIVOT_DEG_180
    snap["turn_speed"] = TURN_SPEED
    param_rev = params.rev()

    action, reason_code, detail = decide_turn(cmd, snap, {})
    target = detail["target_deg"]

    def on_tick():
        el, er = hw.read_encoders()
        _publish(tele, params, started, mode="turning", target_deg=target,
                 enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

    stopper = _tick_stop(should_stop, on_tick)
    actual = pivot(hw, action, target, TURN_SPEED, should_stop=stopper, should_pause=should_pause)

    if POST_TURN_SETTLE_MS > 0:
        time.sleep(POST_TURN_SETTLE_MS / 1000.0)

    ev_detail = dict(detail)
    rule = ev_detail.pop("rule", "DO_TRIGGER")
    ev_detail["param_rev"] = param_rev
    ev_detail["enc_avg"] = actual
    ev_detail["error_deg"] = actual - target
    ev_detail["stopped_early"] = bool(should_stop())
    log.log(reason_code, rule, **ev_detail)

    hw.beep_ok()
    return actual


# =====================================================================
# 구동층 제어 루프 (브릭, ev3dev2) — run()
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

    state = {"visits": 0, "arrived": False, "grabbed": False,
             "last_turn": None, "returning": False}

    def on_stop(source):
        stop_flag["on"] = True
        stop_flag["source"] = source

    def on_pause(paused, source):
        pause_state["paused"] = bool(paused)
        pause_state["source"] = source
        log.log("PAUSE" if paused else "RESUME", "SPEED_ZERO_HOLD", source=source)
        return {"mode": "paused" if paused else "run"}

    def on_do(action, args):
        if action not in ("read_color", "read_reflect"):
            return {"error": "unknown action: {}".format(action)}
        with plock:
            pending["action"] = action
        return {"queued": action}

    def should_stop():
        return stop_flag["on"]

    def should_pause():
        return pause_state["paused"]

    server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop,
                          pause_handler=on_pause, actions=ACTIONS, stage=STAGE_NAME)
    server.start()

    started = time.monotonic()

    def take_pending():
        with plock:
            action = pending["action"]
            pending["action"] = None
        return action

    def handle_pending(action):
        if action == "read_color":
            color = hw.read_center_color_value()
            log.log("COLOR_READ", "DO_TRIGGER", color=color, method="in_place")
            _publish(tele, params, started, mode="read_color", color=color)
        elif action == "read_reflect":
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            log.log("REFLECT_READ", "DO_TRIGGER", reflect_l=rl, reflect_r=rr)
            _publish(tele, params, started, mode="read_reflect", reflect_l=rl, reflect_r=rr)

    def arrive():
        hw.stop()
        snap = params.snapshot()
        hw.grip_open(snap["grip_speed"], GRIP_SEC)
        hw.beep_ok()
        hw.beep_ok()
        state["arrived"] = True
        log.log("NODE_IS_GOAL", "COLOR_RED", color=COL_RED)

    def handle_node(bits):
        hw.stop()

        if bits == (0, 0, 0):            # 선/색 모두 없는 막다른 지점 → 유턴 복귀
            log.log("DEAD_END", "NO_LINE_NO_COLOR", bits=bits_to_str(bits))
            _run_turn(hw, "uturn", params, log, tele, should_stop, should_pause, started)
            state["returning"] = True
            return

        snap = params.snapshot()

        def on_adv_tick():
            _publish(tele, params, started, mode="advancing",
                     enc_avg=hw.enc_avg() * MM_PER_DEG)

        advance_straight(hw, snap["node_advance_mm"], STRAIGHT_SPEED,
                         _tick_stop(should_stop, on_adv_tick), should_pause)
        if should_stop():
            return

        c = hw.read_center_color_value()
        if c == COL_RED:                 # 전진했더니 도착 영역
            arrive()
            return

        has_left = (bits[0] == 1)
        has_right = (bits[2] == 1)
        has_straight = (c == COL_BLACK)
        n_options = int(has_left) + int(has_right) + int(has_straight)

        if n_options <= 1:
            # 커브 등 강제 이동: 선택이 아니므로 기억(last_turn/returning) 유지
            if has_left:
                log.log("NODE_CURVE", "FORCED_LEFT", bits=bits_to_str(bits), color=c)
                _run_turn(hw, "turn_left", params, log, tele, should_stop, should_pause, started)
            elif has_right:
                log.log("NODE_CURVE", "FORCED_RIGHT", bits=bits_to_str(bits), color=c)
                _run_turn(hw, "turn_right", params, log, tele, should_stop, should_pause, started)
            elif has_straight:
                log.log("NODE_CURVE", "FORCED_STRAIGHT", bits=bits_to_str(bits), color=c)
            else:
                log.log("DEAD_END", "NO_EXIT_AFTER_ADVANCE", bits=bits_to_str(bits), color=c)
                _run_turn(hw, "uturn", params, log, tele, should_stop, should_pause, started)
                state["returning"] = True
            return

        # 분기점: 복귀 중이면 "왔던 길" 방향 제외
        exclude = None
        if state["returning"] and state["last_turn"] is not None:
            exclude = OPPOSITE[state["last_turn"]]

        choice = choose_branch(has_left, has_right, has_straight, exclude)
        log.log("NODE_CHOICE", "PRIORITY_R_L_S", bits=bits_to_str(bits), color=c,
                has_left=has_left, has_right=has_right, has_straight=has_straight,
                exclude=exclude, returning=state["returning"], choice=choice)

        if choice == "L":
            _run_turn(hw, "turn_left", params, log, tele, should_stop, should_pause, started)
        elif choice == "R":
            _run_turn(hw, "turn_right", params, log, tele, should_stop, should_pause, started)
        elif choice == "U":
            _run_turn(hw, "uturn", params, log, tele, should_stop, should_pause, started)
        # "S" 는 그대로 직진(회전 없음)

        if choice == "U":
            state["returning"] = True    # 고를 길이 없었음 → 되돌아감
        else:
            state["last_turn"] = choice
            state["returning"] = False

    print("run_maze ready. waiting YELLOW on center sensor... (Ctrl-C or robotctl stop to quit)")

    # ---------- 출발 대기 ----------
    snap0 = params.snapshot()
    hw.grip_open(snap0["grip_speed"], GRIP_SEC)
    while hw.read_center_color_value() != COL_YELLOW:
        if stop_flag["on"]:
            hw.stop()
            log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
            server.stop()
            print("run_maze stopped before start.")
            return
        action = take_pending()
        if action is not None:
            handle_pending(action)
        _publish(tele, params, started, mode="waiting_start")
        time.sleep(0.05)
    hw.beep_ok()
    log.log("NODE_IS_START", "COLOR_YELLOW", color=COL_YELLOW)
    advance_straight(hw, START_EXIT_MM, STRAIGHT_SPEED, should_stop, should_pause)

    # ---------- 메인 루프 ----------
    cand = None
    cand_t0 = 0.0
    last_node_t = time.monotonic()
    last_blue_t = 0.0
    last_follow_log = time.monotonic() - REASON_THROTTLE_S

    print("run_maze running. stop via 'robotctl stop' or Ctrl-C.")
    try:
        while not state["arrived"]:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.stop()
                _publish(tele, params, started, mode="paused", paused=True,
                         visits=state["visits"], arrived=state["arrived"],
                         last_turn=state["last_turn"], returning=state["returning"],
                         grabbed=state["grabbed"])
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            action = take_pending()
            if action is not None:
                handle_pending(action)
                time.sleep(LOOP_DELAY_MS / 1000.0)
                continue

            snap = params.snapshot()
            now = time.monotonic()

            # (1) 중앙 색상(상시 컬러모드) + 색 이벤트
            c_color = hw.read_center_color_value()

            if c_color == COL_RED:
                arrive()
                break

            if (c_color == COL_BLUE and
                    (now - last_blue_t) * 1000 >= COLOR_DEBOUNCE_MS):
                hw.stop()
                state["visits"] += 1
                log.log("VISIT_NODE", "BLUE_REVISIT", color=c_color, visits=state["visits"])
                _run_turn(hw, "uturn", params, log, tele, should_stop, should_pause, started)
                state["returning"] = True
                last_blue_t = time.monotonic()
                cand = None
                continue

            # (2) 소스통: 초음파 근접 → 파지 (1회)
            if (not state["grabbed"]) and hw.read_distance_cm() < snap["grab_dist_cm"]:
                hw.stop()
                hw.grip_close(snap["grip_speed"], GRIP_SEC)
                state["grabbed"] = True
                log.log("GRAB", "ULTRASONIC_NEAR", grab_dist_cm=snap["grab_dist_cm"],
                        grip_speed=snap["grip_speed"])
                hw.beep_ok()

            # (3) 좌/우 반사광 1회 판독 → 조향 레벨 / 노드 bits 생성
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            l_lv = steer_level(rl, snap["left_th_steer"], LEFT_TH_DEEP)
            r_lv = steer_level(rr, snap["right_th_steer"], RIGHT_TH_DEEP)
            nbits = bits_node(rl, c_color, rr, LEFT_TH_NODE, RIGHT_TH_NODE)

            # (4) 노드 후보 추적 (엄격 bits, confirm + debounce)
            if nbits in CANDIDATES:
                if cand != nbits:
                    cand = nbits
                    cand_t0 = now
                elif ((now - cand_t0) * 1000 >= NODE_CONFIRM_MS and
                      (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS):
                    handle_node(nbits)
                    last_node_t = time.monotonic()
                    cand = None
                    continue
            else:
                cand = None

            # (5) 계단식 조향 (걸친 만큼 틀기)
            err = line_error(l_lv, c_color == COL_BLACK, r_lv)
            turn = clamp(FOLLOW_GAIN * err, -TURN_LIMIT, TURN_LIMIT)
            base = SLOW_SPEED if nbits in SLOW_ON else BASE_SPEED
            left_speed = clamp(base - turn, -100, 100)
            right_speed = clamp(base + turn, -100, 100)
            hw.drive(left_speed, right_speed)

            if (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "STEP", reflect_l=rl, reflect_r=rr,
                        bits=bits_to_str(nbits), error=err, turn=turn)
                last_follow_log = now

            _publish(tele, params, started, mode="follow", reflect_l=rl, reflect_r=rr,
                     color=c_color, bits=bits_to_str(nbits), error=err, turn=turn,
                     left_speed=left_speed, right_speed=right_speed,
                     visits=state["visits"], arrived=state["arrived"],
                     last_turn=state["last_turn"], returning=state["returning"],
                     grabbed=state["grabbed"])

            time.sleep(LOOP_DELAY_MS / 1000.0)
    except KeyboardInterrupt:
        log.log("EMERGENCY_STOP", "KEYBOARD", source="keyboard")
    finally:
        try:
            hw.stop()
        finally:
            server.stop()

    print("done. visits={} arrived={}".format(state["visits"], state["arrived"]))


if __name__ == "__main__":
    run()
