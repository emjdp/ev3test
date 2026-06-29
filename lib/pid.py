"""측정 dt를 사용하는 PID 제어기."""


class Pid(object):
    def __init__(self, kp, ki, kd, out_limit, ema_alpha=0.35, derivative_limit=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_limit = out_limit
        self.ema_alpha = ema_alpha
        self.derivative_limit = derivative_limit
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.prev_error = None
        self.derivative_ema = 0.0

    def set_gains(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def update(self, error, dt):
        if dt <= 0:
            dt = 0.001

        self.integral += error * dt
        if self.prev_error is None:
            derivative = 0.0
        else:
            derivative = (error - self.prev_error) / dt

        if self.derivative_limit is not None:
            derivative = self._clamp(derivative, -self.derivative_limit, self.derivative_limit)

        alpha = self.ema_alpha
        if alpha < 0.0:
            alpha = 0.0
        elif alpha > 1.0:
            alpha = 1.0
        self.derivative_ema = alpha * derivative + (1.0 - alpha) * self.derivative_ema

        out = self.kp * error + self.ki * self.integral + self.kd * self.derivative_ema
        self.prev_error = error
        if self.out_limit is not None:
            out = self._clamp(out, -self.out_limit, self.out_limit)
        return out

    def _clamp(self, value, lo, hi):
        if value < lo:
            return lo
        if value > hi:
            return hi
        return value


def _self_test():
    pid = Pid(1.0, 0.5, 0.2, 10.0, ema_alpha=0.5)
    first = pid.update(4.0, 0.1)
    second = pid.update(5.0, 0.2)
    assert first > 4.0
    assert second > first
    assert pid.update(100.0, 0.1) == 10.0
    pid.set_gains(0.0, 0.0, 0.0)
    assert pid.update(1.0, 0.1) == 0.0
    pid.reset()
    assert pid.prev_error is None
    print("pid self-test ok")


if __name__ == "__main__":
    _self_test()
