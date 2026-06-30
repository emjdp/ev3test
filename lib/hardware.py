"""Stage 1~2 구동층 (ev3dev2).

판단층(순수)과 분리된 구동층이다. 여기만 ev3dev2 에 의존한다.
PC 에는 ev3dev2 가 없으므로 import 는 __init__ 안에서 한다(py_compile 안전).

배선(HARDWARE.md / Stage 0 실기 확정):
  - 주행 좌 라지 모터: outA  (전진 방향 정상)
  - 주행 우 라지 모터: outB  (전진 방향 정상)
  - 중앙 컬러센서:      in2  (Stage 0 OK)
Stage 1 은 중앙센서 1개만 쓴다(in1/in3/in4 는 다음 단계).

Stage 2 추가(2026-06-30): 엔코더 각도 기반 제자리 회전을 위해 아래 메서드를 **추가만** 한다.
  - reset_encoders() / read_encoders() : 누적 회전각(도) 리셋/읽기
  - drive_raw()                        : 트림 미적용 좌/우 명령(회전엔 트림 X — stage2 명세 §5.3)
  - beep_ok()                          : 회전 완료 신호(보정 루프 리듬). best-effort.
Stage 1 확정 메서드(drive/stop/read_center_reflect)와 __init__ 기존 동작은 수정하지 않는다.

규약: 브릭 코드는 Python 3.5 안전 — f-string 금지, .format() 사용.
"""

# --- 파일 맨 위 상수 (live param 아님; STAGES.md "좌/우 트림은 상수로 시작") ---
LEFT_MOTOR_PORT = "outA"
RIGHT_MOTOR_PORT = "outB"
CENTER_SENSOR_PORT = "in2"

# 곱셈 트림(쏠림 보정). Stage 1 보정②에서 실측해 한쪽만 미세 조정한다.
# 1.0 = 보정 없음. 빠른 쪽을 1.0 미만으로 낮추거나 느린 쪽을 그대로 둔다.
LEFT_MOTOR_TRIM = 1.0
RIGHT_MOTOR_TRIM = 1.0

MAX_SPEED = 100  # SpeedPercent 한계(±)


def clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


class Ev3Hardware(object):
    """중앙센서 1개 + 좌/우 주행 모터 구동층."""

    def __init__(self):
        # ev3dev2 는 여기서 import (PC py_compile 안전).
        from ev3dev2.motor import LargeMotor, SpeedPercent
        from ev3dev2.sensor.lego import ColorSensor

        self._SpeedPercent = SpeedPercent
        self._left = LargeMotor(LEFT_MOTOR_PORT)
        self._right = LargeMotor(RIGHT_MOTOR_PORT)
        self._center = ColorSensor(CENTER_SENSOR_PORT)

        # Stage 2 회전 완료음(선택). 없거나 실패해도 주행/회전에 영향 없게 best-effort.
        # (Stage 1 도 Ev3Hardware 를 쓰므로 여기서 예외가 나면 안 된다.)
        self._sound = None
        try:
            from ev3dev2.sound import Sound
            self._sound = Sound()
        except Exception:
            self._sound = None

    def read_center_reflect(self):
        """in2 반사광(0~100). 속성 접근이 모드를 COL-REFLECT 로 맞춘다(Stage 0 과 동일)."""
        return self._center.reflected_light_intensity

    def drive(self, left_speed, right_speed):
        """좌/우 바퀴 속도(%) 명령. 트림 적용 후 ±MAX_SPEED 로 클램프."""
        left = clamp(left_speed * LEFT_MOTOR_TRIM, -MAX_SPEED, MAX_SPEED)
        right = clamp(right_speed * RIGHT_MOTOR_TRIM, -MAX_SPEED, MAX_SPEED)
        self._left.on(self._SpeedPercent(left))
        self._right.on(self._SpeedPercent(right))

    def stop(self):
        """양 바퀴 정지(brake)."""
        self._left.off(brake=True)
        self._right.off(brake=True)

    # --- Stage 2 추가(엔코더 회전). Stage 1 코드는 위에서 건드리지 않았다. ---

    def drive_raw(self, left_speed, right_speed):
        """좌/우 바퀴 속도(%) 명령(트림 미적용). 제자리 회전은 좌우 대칭이어야 하므로
        직진 쏠림 보정용 LEFT/RIGHT_MOTOR_TRIM 을 적용하지 않는다(stage2 명세 §5.3)."""
        left = clamp(left_speed, -MAX_SPEED, MAX_SPEED)
        right = clamp(right_speed, -MAX_SPEED, MAX_SPEED)
        self._left.on(self._SpeedPercent(left))
        self._right.on(self._SpeedPercent(right))

    def reset_encoders(self):
        """좌/우 모터 누적 회전각(도)을 0 으로. position 만 0 으로 둬 다른 상태는 안 건드림."""
        self._left.position = 0
        self._right.position = 0

    def read_encoders(self):
        """좌/우 모터 누적 회전각(도) 튜플. 부호는 회전 방향을 따른다."""
        return self._left.position, self._right.position

    def beep_ok(self):
        """회전 완료 신호음(best-effort). Sound 가 없으면 조용히 통과."""
        if self._sound is None:
            return
        try:
            self._sound.beep()
        except Exception:
            pass
