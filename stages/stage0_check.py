#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 0 — 연결/포트 확인 (ev3dev 브릭에서 실행).

목적: 모터 3개·센서 4개가 HARDWARE.md 배선대로 인식되는지, 센서값이 읽히는지,
좌/우 주행 모터 방향이 기대와 맞는지, 그리고 EV3 Python 버전을 확정한다.
이 단계는 "튜닝"이 아니라 "확인"이다. 라인추종/PID/노드/색/그리퍼 없음.

독립 실행:  python3 stages/stage0_check.py
문법 점검:  python3 -m py_compile stages/stage0_check.py   (PC 에서도 통과)

규약: 브릭에서 도는 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
ev3dev2 import 는 main() 안에서 한다(PC 에는 ev3dev2 가 없으므로 py_compile 안전).
BACK 버튼은 언제나 즉시 중단(최우선).

자세한 명세: docs/specs/stage0_connection.md
"""

import platform
import time

# --- 파일 맨 위 상수 (live param 아님; Stage 0 은 라이브 튜닝 인프라 이전) ---
NUDGE_SPEED = 15   # 방향 확인용 구동 속도(%). HARDWARE.md "첫 실행 15~20%".
NUDGE_MS = 400     # 방향 확인 구동 시간(ms). 아주 짧게.


def back_pressed(button):
    """BACK 버튼 = 즉시 정지/중단 (최우선)."""
    return bool(button.backspace)


def wait_ms_or_back(button, ms):
    """ms 동안 대기하되 BACK 누르면 즉시 빠져나온다. BACK 눌렀으면 True 반환."""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if back_pressed(button):
            return True
        time.sleep(0.01)
    return False


def probe_motor(cls, port, label):
    """모터 1개 열기 시도. (motor_or_None, detail_str) 반환."""
    try:
        m = cls(port)
    except Exception as exc:
        return None, "{} {} FAIL: {}".format(port, label, exc)
    # position 접근이 일부 펌웨어에서 예외일 수 있으므로 따로 감싼다(명세 11절).
    try:
        detail = "{} {} OK (pos={})".format(port, label, m.position)
    except Exception:
        detail = "{} {} OK (position 읽기 불가, 열림 OK)".format(port, label)
    return m, detail


def probe_sensor(cls, port, label, read):
    """센서 1개 열기 + 값 1회 읽기. (ok, detail_str) 반환."""
    try:
        s = cls(port)
        val = read(s)
        return True, "{} {} OK value={}".format(port, label, val)
    except Exception as exc:
        return False, "{} {} FAIL: {}".format(port, label, exc)


def nudge_drive(left_motor, right_motor, speed_percent_cls, speed, ms, button):
    """좌/우 모터를 짧게 저속으로 같은 방향(전진)으로 돌려 방향을 눈으로 확인.

    BACK 을 누르면 즉시 멈춘다. 마지막엔 항상 브레이크로 정지하고 관성 settle.
    """
    if back_pressed(button):
        return
    left_motor.on(speed_percent_cls(speed))    # 좌 = 전진(+)
    right_motor.on(speed_percent_cls(speed))   # 우 = 전진(+)
    try:
        wait_ms_or_back(button, ms)
    finally:
        left_motor.off(brake=True)
        right_motor.off(brake=True)
        time.sleep(0.1)   # 관성 settle


def main():
    # ev3dev2 는 여기서 import (PC py_compile 안전).
    from ev3dev2.motor import LargeMotor, MediumMotor, SpeedPercent
    from ev3dev2.sensor.lego import ColorSensor, UltrasonicSensor
    from ev3dev2.button import Button

    # --- 0) Python 버전 (가장 중요한 산출물) ---
    # 3.5.x 면 이후 모든 브릭 코드 f-string 금지 확정.
    print("python " + platform.python_version())

    button = Button()
    ok_count = 0
    fail_count = 0

    # --- 1) 모터 3개 열기 ---
    print("--- 모터 ---")
    motors = [
        ("outA", "LargeMotor(주행 좌)", LargeMotor),
        ("outB", "LargeMotor(주행 우)", LargeMotor),
        ("outC", "MediumMotor(그립)", MediumMotor),
    ]
    opened = {}
    for port, label, cls in motors:
        m, detail = probe_motor(cls, port, label)
        print(detail)
        if m is not None:
            opened[port] = m
            ok_count += 1
        else:
            fail_count += 1

    # --- 2) 센서 4개 열기 + 값 1회 읽기 ---
    # 컬러센서는 반사광(reflected_light_intensity)만 1회 — 모드전환 안 함(Stage 4 일).
    print("--- 센서 ---")
    sensors = [
        ("in1", "ColorSensor 좌", ColorSensor, lambda s: s.reflected_light_intensity),
        ("in2", "ColorSensor 중", ColorSensor, lambda s: s.reflected_light_intensity),
        ("in3", "ColorSensor 우", ColorSensor, lambda s: s.reflected_light_intensity),
        ("in4", "Ultrasonic", UltrasonicSensor, lambda s: s.distance_centimeters),
    ]
    for port, label, cls, read in sensors:
        ok, detail = probe_sensor(cls, port, label, read)
        print(detail)
        if ok:
            ok_count += 1
        else:
            fail_count += 1

    # --- 3) 좌/우 모터 방향 확인 (짧게 저속, BACK 으로 중단) ---
    print("--- 방향 확인 ---")
    if "outA" in opened and "outB" in opened:
        print("forward nudge: 두 바퀴가 같은 '전진' 방향인지 보세요.")
        print("(바퀴를 띄워 방향만 확인 권장) ENTER=실행, BACK=건너뛰기")
        # 모터가 갑자기 돌지 않게 시작 전 확인 대기. BACK 이면 건너뛴다.
        skipped = False
        while True:
            if back_pressed(button):
                skipped = True
                break
            if button.enter:
                break
            time.sleep(0.02)
        if not skipped:
            nudge_drive(opened["outA"], opened["outB"], SpeedPercent,
                        NUDGE_SPEED, NUDGE_MS, button)
        else:
            print("방향 확인 건너뜀(BACK).")
    else:
        print("좌/우 주행 모터(outA/outB) 둘 다 열리지 않아 방향 확인 생략.")

    # --- 요약 ---
    print("--- 요약 ---")
    print("OK={} FAIL={} (기대: OK=7)".format(ok_count, fail_count))
    print("DONE. python 버전·7개 포트 결과·좌우 방향을 PROGRESS.md 에 적으세요.")


if __name__ == "__main__":
    main()
