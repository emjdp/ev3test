#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v2.py — 완주 통합 실행 파일 v2: 계단식 조향 → PD 조향 전환.

v1(run_maze.py, 유지)과의 차이 — 실기 증상(2026-07-06) 대응:
  증상: 라인에 똑바로 올라타 출발하면 괜찮은데, 한 번 비뚤어져 보정이 시작되면
  좌우로 왔다갔다(발진)하다가 오류(가짜 000/노드 검출 → 정지/후진/유턴)가 났다.
  원인 3가지:
    1) v1 line_error 는 계단식(0/±0.5/±1.0/±2.0) + 감쇠(D항) 없음 → 한 번 틀어지면
       조향이 점프하며 진동이 커진다.
    2) 중앙 색상값(center_black)이 조향에 들어가는데, 색상모드는 라인 경계에서
       값이 불안정(검정↔흰색↔갈색 깜빡임) → 오차가 ±1.0↔±2.0 을 오가며 악화.
    3) 크게 휘청이면 사이드 센서가 라인을 깊게 가로지르거나 셋 다 벗어나
       가짜 노드 bits / (0,0,0) 이 confirm 됐다.

v2 변경점 (조향만 교체, 탐색/노드 로직은 v1 그대로 재사용):
  - 조향: stage3v2 확정 PD(PdController — error = 우reflect - 좌reflect 연속값,
    kp 0.22 / KD 0.05 / TURN_LIMIT 16) 를 import 해 재사용. 중앙 색상은 조향에서
    제외한다(stage4v2 와 동일 원리 — pd_step 은 중앙 raw 를 쓰지 않는다).
  - 중앙 색상(상시 컬러모드, 모드 전환 0회 유지)은 노드/마커 판정에만 쓴다:
    검정=직진 길 있음, 노랑/파랑/빨강 마커. v1 과 동일.
  - 000 가드: 직전 turn 이 클 때(|turn| > LOST_GUARD_TURN, 한창 보정 중)는
    (0,0,0) 을 노드 후보로 잡지 않는다 — 보정 중 순간 이탈이 막다른 길로
    오검출되는 것 차단. 진짜 선 끝이면 turn 이 줄어든 다음 루프들에서 잡힌다.
    가드는 000 에만 건다 — (0,1,1) 같은 진짜 커브 bits 는 사이드 센서가 거의
    완전 검정(20/18 미만)이어야만 나와서 그 자체로 신뢰도가 높다.
  - PD 상태(prev_error/prev_t)는 회전/후진/일시정지 등으로 주행이 끊길 때마다
    reset 한다(끊긴 시간 동안의 오차 변화가 D항 스파이크가 되는 것 방지).

v1 에서 그대로 가져오는 것(import — 복붙 금지 규약):
  - 탐색 로직: bits_node / choose_branch / line_found / CANDIDATES / 우>좌>직
    우선순위 + 직전 분기 기억(returning/exclude).
  - 구동 헬퍼: advance_straight / backup_until_line / _run_turn(Stage 2 재사용).
  - 000 후진 복구, 파랑 유턴, 빨강 도착, 노랑 출발 대기, 그리퍼/초음파.

라이브 params: v1 의 follow_gain 을 kp 로 교체(시드 0.22 = stage3v2 실기 확정값).
base_speed 시드도 PD 확정 조합(17)으로 맞춘다. left/right_th_steer 는 조향에서
빠졌지만 후진 복구(line_found)의 감도로 여전히 쓰므로 라이브 유지.
팀 대시보드 패리티(2026-07-06 요청): stage3v2/stage4 가 노출하는 회전 속도
`turn_speed`(팀 확정값 6 시드 — v1 상수 18 은 팀 대비 빨라 교체)와 확정 손잡이
`node_confirm_ms`(v1 상수 120 시드)를 라이브로 추가 — 대시보드에서 팀원
스테이지와 같은 속도/회전 손잡이를 그대로 만질 수 있다.

실시간 대시보드/robotctl 사용법은 v1 과 동일(docs/LIVE_TUNING.md).

센서 운용: 중앙(in2)=항상 색상모드, 좌(in1)/우(in3)=항상 반사광모드. (v1 동일)

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 네트워크 stop(robotctl/대시보드) 또는 Ctrl-C.

독립 실행(브릭):  python3 stages/run_maze_v2.py
문법 점검(PC):    python3 -m py_compile stages/run_maze_v2.py lib/*.py
판단층 테스트(PC): python3 tests/test_run_maze_v2_logic.py
"""

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
# v1(run_maze) 확정 코드 재사용(미수정): 탐색 판단층 + 구동 헬퍼 + 타이밍/임계값.
from stages.run_maze import (                                        # noqa: E402
    bits_node, choose_branch, bits_to_str,
    advance_straight, backup_until_line, _tick_stop, _publish,
    COL_BLACK, COL_BLUE, COL_YELLOW, COL_RED,
    CANDIDATES, SLOW_ON, OPPOSITE,
    LEFT_TH_NODE, RIGHT_TH_NODE,
    NODE_DEBOUNCE_MS,
    BASE_PIVOT_DEG_90, BASE_PIVOT_DEG_180, POST_TURN_SETTLE_MS,
    LOST_BACKUP_MM, BACKUP_SPEED, LOST_RETRY_WINDOW_MS,
    COLOR_DEBOUNCE_MS, START_EXIT_MM, GRIP_SEC, LOOP_DELAY_MS,
    REASON_THROTTLE_S, STRAIGHT_SPEED, SLOW_SPEED, MM_PER_DEG,
)
# Stage 3 확정 조향 재사용(미수정): PD 수식 + KD/TURN_LIMIT 은 stage3v2 내부값.
from stages.stage3v2_linetrace_branch import PdController            # noqa: E402
# lib.hardware (ev3dev2) 는 run() 안에서 import 한다.


# =====================================================================
# 라이브 params — v1 의 9개에서 follow_gain → kp 교체 + 팀 대시보드 패리티
# (2026-07-06 요청): stage3v2/stage4(팀원 스테이지)가 노출하는 turn_speed(회전 속도),
# confirm 손잡이(여기서는 시간 기반 node_confirm_ms — LIVE_TUNING.md Stage 2~ 후보와
# 동일 키)를 추가 = 11개. "6개 이하" 가이드 초과는 ★ 실기 보정값 + 팀 공용 손잡이
# 맞춤이 이유(PROGRESS 2026-07-06 기록).
# =====================================================================

INITIAL_PARAMS = {
    "base_speed": 17,         # 주행 속도(%). PD 확정 조합(stage3v2/stage4v2) 시드
    "kp": 0.22,               # PD 조향 게인(좌/우 raw 차) — stage3v2 실기 확정값 시드
    "turn_speed": 6,          # 회전 속도(%) — 팀 스테이지(stage3v2/stage4) 확정값 시드
    "node_confirm_ms": 120,   # 노드 후보 확정 시간(ms) — v1 확정 상수 시드, 라이브 개방
    "left_th_steer": 69,      # 후진 복구 line_found 감도(조향에서는 더 이상 안 씀)
    "right_th_steer": 67,
    "node_advance_mm": 30,    # ★ 확정 후 재판정/회전 전 전진량
    "turn_90_factor": 0.75,   # ★ 과/부족 시 0.05 단위 미세조정
    "turn_180_factor": 0.75,  # ★ 유턴도 같은 비율로 과회전 가감 → 실기에서 확인
    "grab_dist_cm": 6.0,      # ★ 조립에 따라 실기값 다름
    "grip_speed": 30,         # ★ 조립에 따라 부호 반전
}

PARAM_LIMITS = {
    "base_speed": (5, 45),
    "kp": (0.0, 3.0),
    "turn_speed": (5, 40),
    "node_confirm_ms": (0, 1000),
    "left_th_steer": (0, 100),
    "right_th_steer": (0, 100),
    "node_advance_mm": (0, 120),
    "turn_90_factor": (0.3, 2.0),
    "turn_180_factor": (0.3, 2.0),
    "grab_dist_cm": (1.0, 20.0),
    "grip_speed": (5, 80),
}

MAX_STEP = {
    "base_speed": 5,
    "kp": 0.1,
    "turn_speed": 5,
    "node_confirm_ms": 60,
    "left_th_steer": 3,
    "right_th_steer": 3,
    "node_advance_mm": 10,
    "turn_90_factor": 0.05,
    "turn_180_factor": 0.05,
    "grab_dist_cm": 1.0,
    "grip_speed": 5,
}

UI_STEP = {
    "base_speed": 1,
    "kp": 0.01,
    "turn_speed": 1,
    "node_confirm_ms": 10,
    "left_th_steer": 1,
    "right_th_steer": 1,
    "node_advance_mm": 10,
    "turn_90_factor": 0.01,
    "turn_180_factor": 0.01,
    "grab_dist_cm": 0.5,
    "grip_speed": 1,
}
UNITS = {
    "base_speed": "%",
    "turn_speed": "%",
    "node_confirm_ms": "ms",
    "left_th_steer": "%",
    "right_th_steer": "%",
    "node_advance_mm": "mm",
    "turn_90_factor": "x",
    "turn_180_factor": "x",
    "grab_dist_cm": "cm",
    "grip_speed": "%",
}
PARAM_ORDER = [
    "base_speed", "kp", "turn_speed", "node_confirm_ms",
    "left_th_steer", "right_th_steer",
    "node_advance_mm", "turn_90_factor", "turn_180_factor",
    "grab_dist_cm", "grip_speed",
]

# =====================================================================
# v2 전용 config 상수 — 나머지 확정값은 전부 run_maze(v1) 에서 import.
# =====================================================================

# 000 노드 후보 가드: 직전 |turn| 이 이 값보다 크면(한창 보정 중) (0,0,0) 을
# 후보로 잡지 않는다. TURN_LIMIT(16, stage3v2)의 절반 — 실기에서 오검출이
# 남으면 낮추고, 진짜 유실 반응이 늦으면 올린다.
LOST_GUARD_TURN = 8.0

SAVE_PATH = os.path.join(_ROOT, "config", "run_maze_v2.json")
STAGE_NAME = "run_maze_v2"

ACTIONS = [
    {"name": "read_color", "label": "Read Center Color"},
    {"name": "read_reflect", "label": "Read L/R Reflect"},
]


# =====================================================================
# 판단층 (순수 — PC 테스트 가능)
# =====================================================================

def lost_candidate_blocked(nbits, last_turn, guard_turn):
    """000 가드: (0,0,0) 이고 직전 조향이 컸으면(보정 중 순간 이탈) 후보 제외.

    000 이외의 후보(진짜 커브/분기 bits)는 절대 막지 않는다.
    """
    return nbits == (0, 0, 0) and abs(last_turn) > guard_turn


# =====================================================================
# 구동층 헬퍼 — 회전 1회 (v1 _run_turn 의 v2 판: turn_speed 를 라이브 param 으로)
# =====================================================================

def _run_turn(hw, cmd, params, log, tele, should_stop, should_pause, started):
    """decide_turn(Stage 2 판단층) + pivot(Stage 2 구동층)으로 회전 1회 실행+기록.

    v1 run_maze._run_turn 과 동일하되 한 가지만 다르다: 회전 속도를 config 상수
    TURN_SPEED 로 고정하지 않고 **라이브 param `turn_speed`** 를 쓴다(팀 대시보드
    패리티, 2026-07-06). v1 은 확정 코드라 수정하지 않고 여기 별도 판을 둔다.
    """
    snap = params.snapshot()
    snap["BASE_PIVOT_DEG_90"] = BASE_PIVOT_DEG_90
    snap["BASE_PIVOT_DEG_180"] = BASE_PIVOT_DEG_180
    turn_speed = snap["turn_speed"]
    param_rev = params.rev()

    action, reason_code, detail = decide_turn(cmd, snap, {})
    target = detail["target_deg"]

    def on_tick():
        el, er = hw.read_encoders()
        _publish(tele, params, started, mode="turning", target_deg=target,
                 enc_l=el, enc_r=er, enc_avg=(abs(el) + abs(er)) / 2.0)

    stopper = _tick_stop(should_stop, on_tick)
    actual = pivot(hw, action, target, turn_speed, should_stop=stopper, should_pause=should_pause)

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
    pd = PdController()

    stop_flag = {"on": False, "source": None}
    pause_state = {"paused": False, "source": None}
    pending = {"action": None}
    plock = threading.Lock()

    state = {"visits": 0, "arrived": False, "grabbed": False,
             "last_turn": None, "returning": False}
    # 선 유실 복구 이력: 직전 복구 시각. LOST_RETRY_WINDOW_MS 안의 재유실은 막다른 길로 본다.
    lost = {"last_recover_t": -1e9}
    # 직전 루프의 PD turn — 000 가드 판정용. 주행이 끊기면 0 으로 리셋.
    steer = {"last_turn": 0.0}

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

    def reset_steer():
        """주행이 끊긴 뒤(회전/후진/정지) PD 이력과 000 가드 기준을 초기화한다."""
        pd.reset()
        steer["last_turn"] = 0.0

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

        if bits == (0, 0, 0):            # 전부 흰색: 커브 오인식 이탈 또는 진짜 선 끝
            snap = params.snapshot()
            retry_ok = ((time.monotonic() - lost["last_recover_t"]) * 1000
                        >= LOST_RETRY_WINDOW_MS)
            if retry_ok:
                log.log("LINE_LOST", "ALL_WHITE_BACKUP", bits=bits_to_str(bits),
                        backup_mm=LOST_BACKUP_MM)

                def on_backup_tick():
                    _publish(tele, params, started, mode="lost_backup",
                             enc_avg=hw.enc_avg() * MM_PER_DEG)

                found, dist = backup_until_line(
                    hw, LOST_BACKUP_MM, BACKUP_SPEED,
                    snap["left_th_steer"], snap["right_th_steer"],
                    _tick_stop(should_stop, on_backup_tick), should_pause)
                if should_stop():
                    return
                if found:
                    # 선 위로 복귀 — 추종 재개(유턴/returning 없음). 같은 자리서 곧바로
                    # 또 000 이 되면(진짜 선 끝) 다음 번엔 재시도 없이 유턴한다.
                    log.log("LINE_RECOVER", "BACKUP_FOUND_LINE", dist_mm=round(dist, 1))
                    lost["last_recover_t"] = time.monotonic()
                    return
                log.log("DEAD_END", "BACKUP_NO_LINE", bits=bits_to_str(bits),
                        dist_mm=round(dist, 1))
            else:
                log.log("DEAD_END", "LOST_AGAIN_AFTER_RECOVER", bits=bits_to_str(bits))
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

    print("run_maze_v2 ready. waiting YELLOW on center sensor... "
          "(Ctrl-C or robotctl stop to quit)")

    # ---------- 출발 대기 ----------
    snap0 = params.snapshot()
    hw.grip_open(snap0["grip_speed"], GRIP_SEC)
    while hw.read_center_color_value() != COL_YELLOW:
        if stop_flag["on"]:
            hw.stop()
            log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
            server.stop()
            print("run_maze_v2 stopped before start.")
            return
        action = take_pending()
        if action is not None:
            handle_pending(action)
        _publish(tele, params, started, mode="waiting_start")
        time.sleep(0.05)
    hw.beep_ok()
    log.log("NODE_IS_START", "COLOR_YELLOW", color=COL_YELLOW)
    advance_straight(hw, START_EXIT_MM, STRAIGHT_SPEED, should_stop, should_pause)
    reset_steer()

    # ---------- 메인 루프 ----------
    cand = None
    cand_t0 = 0.0
    last_node_t = time.monotonic()
    last_blue_t = 0.0
    last_follow_log = time.monotonic() - REASON_THROTTLE_S

    print("run_maze_v2 running. stop via 'robotctl stop' or Ctrl-C.")
    try:
        while not state["arrived"]:
            if stop_flag["on"]:
                hw.stop()
                log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
                break

            if pause_state["paused"]:
                hw.stop()
                reset_steer()
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

            # (1) 중앙 색상(상시 컬러모드) — 노드/마커 판정 전용(조향에는 안 쓴다)
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
                reset_steer()
                continue

            # (2) 소스통: 초음파 근접 → 파지 (1회)
            if (not state["grabbed"]) and hw.read_distance_cm() < snap["grab_dist_cm"]:
                hw.stop()
                hw.grip_close(snap["grip_speed"], GRIP_SEC)
                state["grabbed"] = True
                log.log("GRAB", "ULTRASONIC_NEAR", grab_dist_cm=snap["grab_dist_cm"],
                        grip_speed=snap["grip_speed"])
                hw.beep_ok()
                reset_steer()

            # (3) 좌/우 반사광 1회 판독 → 노드 bits 생성 (조향 임계값 판정은 없다)
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            nbits = bits_node(rl, c_color, rr, LEFT_TH_NODE, RIGHT_TH_NODE)

            # (4) 노드 후보 추적 (엄격 bits, confirm + debounce)
            #     000 만 가드: 한창 보정 중(직전 |turn| 큼)의 순간 이탈은 후보 제외.
            if nbits in CANDIDATES and not lost_candidate_blocked(
                    nbits, steer["last_turn"], LOST_GUARD_TURN):
                if cand != nbits:
                    cand = nbits
                    cand_t0 = now
                elif ((now - cand_t0) * 1000 >= snap["node_confirm_ms"] and
                      (now - last_node_t) * 1000 >= NODE_DEBOUNCE_MS):
                    handle_node(nbits)
                    last_node_t = time.monotonic()
                    cand = None
                    reset_steer()
                    continue
            else:
                cand = None

            # (5) PD 조향 — 좌/우 반사광 raw 차이만(중앙 raw 자리는 0, pd 는 안 쓴다).
            #     SLOW_ON bits 면 감속 주행(v1 동일 동작).
            snap_eff = snap if nbits not in SLOW_ON else dict(snap, base_speed=SLOW_SPEED)
            left_speed, right_speed, err, _deriv, turn = pd.step((rl, 0, rr), snap_eff)
            hw.drive(left_speed, right_speed)
            steer["last_turn"] = turn

            if (now - last_follow_log) >= REASON_THROTTLE_S:
                log.log("LINE_FOLLOW", "PID", reflect_l=rl, reflect_r=rr,
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
