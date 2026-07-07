#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze.py — 완주 전용 통합 실행 파일 (v4: 우>좌>직 우선순위 + 직전 분기 기억).

v4 탐색 로직 (미로를 모른다는 전제):
  - 모든 노드/커브 후보에서: 정지 → 조금 전진(NODE_ADVANCE_MM) → 중앙 색상으로
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

v3 유지: 임계값 2단 분리 — 조향용(좌69/우67)은 반걸침부터 보정,
  노드 판정용(좌20/우18)은 거의 완전 덮임만 후보. 드리프트 오검출 차단.
  실측: 흰바닥 74/78, 반걸침 65/57, 2/3걸침 30/26, 완전검정(추정) 11~12.

센서 운용: 중앙(in2)=항상 색상모드, 좌(in1)/우(in3)=항상 반사광모드.

스테이지 발췌값/규약 (팀원 코드):
  Stage 0 포트: outA=좌주행, outB=우주행, outC=그리퍼,
                in1=좌컬러, in2=중앙컬러, in3=우컬러, in4=초음파.
  Stage 1: left = base - turn, right = base + turn.
  Stage 2: 회전 = 엔코더 각도 + 보정계수 (90°=193°, 180°=386°, settle 120ms).
  Stage 3: bits 추종(gain=12, limit 35), confirm 120ms + debounce 900ms.

규약: Python 3.5 안전(f-string 금지) / ev3dev2 는 run() 안 import /
      BACK 버튼 미사용, 정지는 Ctrl-C.

독립 실행(브릭):  python3 run_maze.py
문법 점검(PC):    python3 -m py_compile run_maze.py
"""

import time

# =====================================================================
# 상수 (★ = 실기에서 보정/실측 필요)
# =====================================================================

# --- 조향용 임계값 ---
# 실측(좌/우): 흰바닥 74/78, 반걸침 65/57, 2/3걸침 30/26.
# 완전검정 미실측 → 중앙센서 실측(검정 9~10, 흰 68)을 흰바닥 비율로 환산해
# 좌우 완전검정 ≈ 11~12 로 추정.
# 조향 = (흰바닥과 반걸침의 중간): 반걸침부터 바로 보정 시작.
# ⚠ 왼쪽은 흰바닥(74)과 반걸침(65) 차이가 9뿐이라 여유 4~5로 빠듯함.
#   직선에서 이유 없이 좌우로 잘게 떠는 증상이 나오면 LEFT 를 66~67 로 낮출 것.
LEFT_TH_STEER = 69
RIGHT_TH_STEER = 67

# --- 노드 판정용 임계값 (가로선이 센서를 거의 완전히 덮었을 때만 1) ---
# 노드 = (추정 완전검정 11~12 과 2/3걸침 30/26 의 중간):
# 최대 드리프트(2/3걸침)에서도 6 이상 여유를 두고 노드로 오검출되지 않음.
LEFT_TH_NODE = 20
RIGHT_TH_NODE = 18

# --- Stage 3 확정값: bits 추종 ---
BASE_SPEED = 20
FOLLOW_GAIN = 12.0
TURN_LIMIT = 35
SLOW_SPEED = 12

# --- Stage 3 확정값: 노드 판정 ---
NODE_CONFIRM_MS = 120
NODE_DEBOUNCE_MS = 900
NODE_ADVANCE_MM = 30     # ★ 확정 후 재판정/회전 전 전진량

# --- Stage 2 확정값: 회전 ---
TURN_SPEED = 18
PIVOT_90 = 193.0
PIVOT_180 = 386.0
TURN_90_FACTOR = 1.0     # ★
TURN_180_FACTOR = 1.0    # ★
SETTLE_S = 0.12

# v2 이후 파일들이 import 하는 Stage 2 호환 이름.
BASE_PIVOT_DEG_90 = PIVOT_90
BASE_PIVOT_DEG_180 = PIVOT_180
POST_TURN_SETTLE_MS = int(SETTLE_S * 1000)

# --- 기하 (바퀴지름 56mm 가정) ---
MM_PER_DEG = 3.14159265 * 56.0 / 360.0
STRAIGHT_SPEED = 15

# --- 선 유실(000) 후진 복구 ---
LOST_BACKUP_MM = 100
BACKUP_SPEED = 10
LOST_RETRY_WINDOW_MS = 4000

# --- 이벤트 ---
GRAB_DIST_CM = 6.0       # ★
COLOR_DEBOUNCE_MS = 1500
START_EXIT_MM = 50
GRIP_SPEED = 30          # ★ 조립에 따라 부호 반전
GRIP_SEC = 0.8
LOOP_DELAY = 0.015
LOOP_DELAY_MS = int(LOOP_DELAY * 1000)
REASON_THROTTLE_S = 0.25

# ev3dev2 ColorSensor.color 값 (0=없음 1=검정 2=파랑 3=초록 4=노랑 5=빨강 6=흰 7=갈)
COL_BLACK, COL_BLUE, COL_YELLOW, COL_RED = 1, 2, 4, 5

# 노드 후보 bits (엄격 임계값 bits 기준)
CANDIDATES = ((1, 1, 0), (0, 1, 1), (1, 1, 1), (1, 0, 1), (0, 0, 0))
SLOW_ON = ((1, 1, 1), (1, 0, 1))

# 복귀(returning) 시 제외할 방향: 진입 턴의 반대가 "왔던 길"
OPPOSITE = {"L": "R", "R": "L", "S": "S"}


# =====================================================================
# 판단 헬퍼 (순수 — PC 테스트 가능)
# =====================================================================

def bits_steer(reflect_l, center_color, reflect_r):
    """조향용 bits (느슨한 임계값 — 가장자리 걸침에도 반응)."""
    return (1 if reflect_l < LEFT_TH_STEER else 0,
            1 if center_color == COL_BLACK else 0,
            1 if reflect_r < RIGHT_TH_STEER else 0)


def bits_node(reflect_l, center_color, reflect_r,
              left_th_node=LEFT_TH_NODE, right_th_node=RIGHT_TH_NODE):
    """노드 판정용 bits (엄격한 임계값 — 완전 검정에서만 1)."""
    return (1 if reflect_l < left_th_node else 0,
            1 if center_color == COL_BLACK else 0,
            1 if reflect_r < right_th_node else 0)


def line_error(bits):
    """bits 위치 오차. +면 선이 왼쪽 → 왼쪽 보정 (left=base-turn 규약)."""
    l, c, r = bits
    if c == 1 and l == 0 and r == 0:
        return 0.0
    if l == 1 and c == 1:
        return 1.0
    if r == 1 and c == 1:
        return -1.0
    if l == 1:
        return 2.0
    if r == 1:
        return -2.0
    return 0.0


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


def line_found(reflect_l, center_color, reflect_r, th_left, th_right):
    """후진 복구 중 선을 다시 만났는지 판정한다."""
    return (center_color == COL_BLACK or
            reflect_l < th_left or reflect_r < th_right)


def advance_straight(hw, distance_mm, speed, should_stop=None, should_pause=None):
    """엔코더 기준 직진. v2 이후 run_maze 계열이 공유하는 구동 헬퍼."""
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


def backup_until_line(hw, max_mm, speed, th_left, th_right,
                      should_stop=None, should_pause=None):
    """000(선 유실) 시 저속 후진하며 선을 재탐색한다."""
    hw.reset_encoders()
    if max_mm <= 0:
        hw.stop()
        return False, 0.0
    if should_stop is not None and should_stop():
        hw.stop()
        return False, 0.0

    target_deg = max_mm / MM_PER_DEG
    found = False
    hw.drive(-speed, -speed)
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
                hw.drive(-speed, -speed)
            c = hw.read_center_color_value()
            rl = hw.read_left_reflect()
            rr = hw.read_right_reflect()
            if line_found(rl, c, rr, th_left, th_right):
                found = True
                break
            if hw.enc_avg() >= target_deg:
                break
            time.sleep(0.005)
    finally:
        hw.stop()

    return found, hw.enc_avg() * MM_PER_DEG


def _tick_stop(base_should_stop, on_tick):
    """stop 콜백에 telemetry tick 부수효과를 얹는다."""
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


# =====================================================================
# 구동층 (ev3dev2 는 run() 안에서만)
# =====================================================================

def run():
    from ev3dev2.motor import LargeMotor, MediumMotor, SpeedPercent
    from ev3dev2.sensor.lego import ColorSensor, UltrasonicSensor
    from ev3dev2.sound import Sound

    lm = LargeMotor("outA")          # 좌 주행
    rm = LargeMotor("outB")          # 우 주행
    gm = MediumMotor("outC")         # 그리퍼
    cs_l = ColorSensor("in1")        # 반사광 전용
    cs_c = ColorSensor("in2")        # 색상 전용
    cs_r = ColorSensor("in3")        # 반사광 전용
    us = UltrasonicSensor("in4")
    snd = Sound()

    # ---------- 저수준 ----------
    def drive(left, right):
        lm.on(SpeedPercent(clamp(left, -100, 100)))
        rm.on(SpeedPercent(clamp(right, -100, 100)))

    def stop():
        lm.off(brake=True)
        rm.off(brake=True)

    def enc_avg():
        return (abs(lm.position) + abs(rm.position)) / 2.0

    def reset_enc():
        lm.position = 0
        rm.position = 0

    def straight_mm(mm):
        if mm == 0:
            return
        sp = 15 if mm > 0 else -15
        target = abs(mm) / MM_PER_DEG
        reset_enc()
        drive(sp, sp)
        while enc_avg() < target:
            time.sleep(0.005)
        stop()
        time.sleep(0.1)

    def pivot(target_deg, direction):
        reset_enc()
        drive(TURN_SPEED * direction, -TURN_SPEED * direction)
        while enc_avg() < target_deg:
            time.sleep(0.005)
        stop()
        time.sleep(SETTLE_S)

    def turn_left():
        pivot(PIVOT_90 * TURN_90_FACTOR, -1)

    def turn_right():
        pivot(PIVOT_90 * TURN_90_FACTOR, +1)

    def uturn():
        pivot(PIVOT_180 * TURN_180_FACTOR, +1)

    def grip_open():
        gm.on_for_seconds(SpeedPercent(GRIP_SPEED), GRIP_SEC, brake=False)

    def grip_close():
        gm.on_for_seconds(SpeedPercent(-GRIP_SPEED), GRIP_SEC, brake=True)

    # ---------- 탐색 상태 ----------
    # last_turn : 직전 "분기점"에서의 선택 ("L"/"R"/"S"). 커브(강제 이동)는 미갱신.
    # returning : 막다른 곳(파랑/000)에서 유턴해 돌아오는 중. 다음 분기점에서
    #             OPPOSITE[last_turn] 을 제외하고 소거된다.
    state = {"visits": 0, "arrived": False,
             "last_turn": None, "returning": False}

    def arrive():
        stop()
        grip_open()
        snd.beep()
        snd.beep()
        state["arrived"] = True

    def execute(choice):
        if choice == "L":
            turn_left()
        elif choice == "R":
            turn_right()
        elif choice == "U":
            uturn()
        # "S" 는 그대로 직진

    # ---------- 노드/커브 처리 (v4 로직) ----------
    def handle_node(bits):
        stop()

        if bits == (0, 0, 0):            # 색 없는 막다른 길/선 유실 → 유턴 복귀
            uturn()
            state["returning"] = True
            return

        straight_mm(NODE_ADVANCE_MM)     # 매번: 조금 전진 후 재판정

        c = cs_c.color
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
                turn_left()
            elif has_right:
                turn_right()
            elif has_straight:
                pass
            else:
                uturn()
                state["returning"] = True
            return

        # 분기점: 복귀 중이면 "왔던 길" 방향 제외
        exclude = None
        if state["returning"] and state["last_turn"] is not None:
            exclude = OPPOSITE[state["last_turn"]]

        choice = choose_branch(has_left, has_right, has_straight, exclude)
        execute(choice)

        if choice == "U":
            state["returning"] = True    # 고를 길이 없었음 → 되돌아감
        else:
            state["last_turn"] = choice
            state["returning"] = False

    # ---------- 출발 대기 ----------
    grip_open()
    print("waiting YELLOW on center sensor... (Ctrl-C to quit)")
    while cs_c.color != COL_YELLOW:
        time.sleep(0.05)
    snd.beep()
    straight_mm(START_EXIT_MM)

    # ---------- 메인 루프 ----------
    grabbed = False
    cand = None
    cand_t0 = 0.0
    last_node_t = time.monotonic()
    last_blue_t = 0.0

    print("running. stop with Ctrl-C.")
    try:
        while not state["arrived"]:
            now = time.monotonic()

            # (1) 중앙 색상 + 색 이벤트
            c_color = cs_c.color

            if c_color == COL_RED:
                arrive()
                break

            if (c_color == COL_BLUE and
                    (now - last_blue_t) * 1000 >= COLOR_DEBOUNCE_MS):
                stop()                               # 방문 노드 → 유턴, 복귀 시작
                state["visits"] += 1
                snd.beep()
                uturn()
                state["returning"] = True
                last_blue_t = time.monotonic()
                cand = None
                continue

            # (2) 소스통: 초음파 근접 → 파지 (1회)
            if (not grabbed) and us.distance_centimeters < GRAB_DIST_CM:
                stop()
                grip_close()
                grabbed = True
                snd.beep()

            # (3) 반사광 1회 판독 → 조향/노드 bits 각각 생성
            rl = cs_l.reflected_light_intensity
            rr = cs_r.reflected_light_intensity
            sbits = bits_steer(rl, c_color, rr)
            nbits = bits_node(rl, c_color, rr)

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

            # (5) bits 추종 (느슨 bits)
            err = line_error(sbits)
            turn = clamp(FOLLOW_GAIN * err, -TURN_LIMIT, TURN_LIMIT)
            base = SLOW_SPEED if nbits in SLOW_ON else BASE_SPEED
            drive(base - turn, base + turn)

            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        print("keyboard interrupt.")
    finally:
        stop()

    print("done. visits={} arrived={}".format(state["visits"], state["arrived"]))


if __name__ == "__main__":
    run()
