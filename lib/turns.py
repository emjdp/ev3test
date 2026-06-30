# -*- coding: utf-8 -*-
"""Stage 2 구동층 — 엔코더 각도 기반 제자리(탱크) 회전.

판단층(lib/decide_turn.py)이 고른 action 을 받아 **목표 바퀴각만큼** 좌/우 모터를
반대로 돌린다. 시간(ms)이 아니라 엔코더 각도를 기준으로 멈춘다(LIVE_TUNING.md 결정 5):
배터리/마찰이 변해도 '바퀴가 그 각도만큼 돈다'는 일정하고, 남는 변수는 보정계수 하나뿐.

`on_for_degrees` 같은 블로킹 호출 대신 **엔코더 폴링 루프**를 쓴다(stage2 명세 §5.3):
회전 도중에도 stop 플래그에 즉시 반응하고 telemetry 를 흘릴 수 있다.

이 모듈은 ev3dev2 를 직접 import 하지 않는다 — 모터 접근은 전부 `hw`(lib/hardware.py)를
거친다. 덕분에 가짜 hw 로 PC 단위테스트가 된다. 단, 의미 있는 동작은 브릭에서만.

규약: 브릭에서 도니 Python 3.5 안전(f-string 금지).
"""

import time

# action → (좌바퀴 방향, 우바퀴 방향). 좌회전 = 좌바퀴 후진/우바퀴 전진.
# U턴은 우회전과 같은 방향으로 약속(코스 제약에 따라 §11 에서 바뀔 수 있음).
# 실기에서 방향이 반대면 이 표의 부호만 뒤집는다(Stage 0 모터 극성 기준).
_DIRS = {
    "LEFT90": (-1, +1),
    "RIGHT90": (+1, -1),
    "UTURN180": (+1, -1),
}

POLL_DELAY = 0.005  # 엔코더 폴링 간격(초). 너무 길면 오버슛, 너무 짧으면 CPU.


def _avg_abs(el, er):
    return (abs(el) + abs(er)) / 2.0


def pivot(hw, action, target_deg, turn_speed, should_stop=None):
    """엔코더 각도 기준 제자리 회전 1회.

    hw          : 구동층(reset_encoders/read_encoders/drive_raw/stop 제공)
    action      : 'LEFT90' | 'RIGHT90' | 'UTURN180'
    target_deg  : 멈출 평균 바퀴각(도, 양수). 보정 적용된 값.
    turn_speed  : 회전 속도(%). 좌우에 부호만 달리해 적용.
    should_stop : 콜백() -> bool. True 면 즉시 정지(네트워크 stop/watchdog).

    반환: 실제로 돈 평균 엔코더 각도(검증/telemetry). 0 이하 target 은 회전 없이 0.0.
    """
    if action not in _DIRS:
        raise ValueError("unknown pivot action: {}".format(action))

    left_dir, right_dir = _DIRS[action]
    hw.reset_encoders()

    if target_deg <= 0:
        # BASE_PIVOT_DEG 미설정/계수 0 등. 안전하게 회전하지 않는다.
        hw.stop()
        return 0.0

    if should_stop is not None and should_stop():
        # 정지가 이미 걸려 있으면 모터를 아예 돌리지 않는다.
        hw.stop()
        return 0.0

    hw.drive_raw(left_dir * turn_speed, right_dir * turn_speed)
    try:
        while True:
            if should_stop is not None and should_stop():
                break
            el, er = hw.read_encoders()
            if _avg_abs(el, er) >= target_deg:
                break
            time.sleep(POLL_DELAY)
    finally:
        hw.stop()

    el, er = hw.read_encoders()
    return _avg_abs(el, er)


def _self_test():
    # 가짜 hw: 읽을 때마다 구동 방향으로 일정량 누적되는 엔코더 모사.
    class FakeHw(object):
        def __init__(self, step=12.0):
            self.l = 0.0
            self.r = 0.0
            self.step = step
            self.drive = None
            self.stopped = False

        def reset_encoders(self):
            self.l = 0.0
            self.r = 0.0

        def drive_raw(self, left_speed, right_speed):
            self.drive = (left_speed, right_speed)

        def read_encoders(self):
            if self.drive is not None:
                self.l += self.step if self.drive[0] > 0 else -self.step
                self.r += self.step if self.drive[1] > 0 else -self.step
            return self.l, self.r

        def stop(self):
            self.stopped = True

    hw = FakeHw()
    actual = pivot(hw, "LEFT90", 100.0, 18, should_stop=lambda: False)
    assert actual >= 100.0, actual
    assert hw.stopped is True
    # 좌회전: 좌바퀴 후진(-)/우바퀴 전진(+)
    assert hw.l < 0 and hw.r > 0

    hw = FakeHw()
    actual = pivot(hw, "RIGHT90", 100.0, 18, should_stop=lambda: False)
    assert hw.l > 0 and hw.r < 0

    # should_stop True → 거의 안 돌고 멈춤
    hw = FakeHw()
    actual = pivot(hw, "UTURN180", 1000.0, 18, should_stop=lambda: True)
    assert actual == 0.0 and hw.stopped is True

    # target<=0 → 회전 없음
    hw = FakeHw()
    assert pivot(hw, "LEFT90", 0.0, 18, should_stop=lambda: False) == 0.0
    assert hw.drive is None and hw.stopped is True
    print("turns self-test ok")


if __name__ == "__main__":
    _self_test()
