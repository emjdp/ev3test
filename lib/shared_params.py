"""스레드 안전 라이브 파라미터 저장소.

브릭 Python 3.5 호환을 위해 최신 문법을 쓰지 않는다.
"""

import json
import numbers
import os
import threading


class SharedParams(object):
    def __init__(self, defaults, limits, max_step, save_path):
        self._lock = threading.RLock()
        self._defaults = dict(defaults)
        self._limits = dict(limits)
        self._max_step = dict(max_step or {})
        self._save_path = save_path
        self._rev = 0

        missing_limits = []
        for name in self._defaults:
            if name not in self._limits:
                missing_limits.append(name)
        if missing_limits:
            raise ValueError("missing limits for: {}".format(", ".join(sorted(missing_limits))))

        missing_defaults = []
        for name in self._limits:
            if name not in self._defaults:
                missing_defaults.append(name)
        if missing_defaults:
            raise ValueError("missing defaults for: {}".format(", ".join(sorted(missing_defaults))))

        self._values = dict(self._defaults)
        ok, msg = self._validate_all(self._values)
        if not ok:
            raise ValueError(msg)

    def snapshot(self):
        with self._lock:
            return dict(self._values)

    def get(self, name):
        with self._lock:
            return self._values.get(name)

    def rev(self):
        with self._lock:
            return self._rev

    def set(self, name, value):
        with self._lock:
            if name not in self._limits:
                return False, "unknown param: {}".format(name)
            ok, msg = self._validate_value(name, value)
            if not ok:
                return False, msg
            if name in self._max_step:
                old = self._values[name]
                step = self._max_step[name]
                if abs(value - old) > step:
                    return False, "step too big for {} (max {}, old {}, new {})".format(
                        name, step, old, value
                    )
            self._values[name] = value
            self._rev += 1
            return True, "ok"

    def save(self):
        with self._lock:
            values = dict(self._values)
            save_path = self._save_path
        try:
            directory = os.path.dirname(save_path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            tmp_path = save_path + ".tmp"
            with open(tmp_path, "w") as fp:
                json.dump(values, fp, sort_keys=True, indent=2)
                fp.write("\n")
            os.rename(tmp_path, save_path)
            return True, save_path
        except Exception as exc:
            return False, str(exc)

    def rollback(self):
        if os.path.exists(self._save_path):
            ok, loaded, msg = self._read_saved()
            if not ok:
                return False, msg
        else:
            loaded = dict(self._defaults)
        with self._lock:
            changed = loaded != self._values
            self._values = dict(loaded)
            if changed:
                self._rev += 1
            return True, "ok"

    def load_saved_into_defaults(self):
        ok, loaded, msg = self._read_saved()
        if not ok:
            if os.path.exists(self._save_path):
                return False, msg
            return True, "no saved params"
        with self._lock:
            changed = loaded != self._values
            self._defaults = dict(loaded)
            self._values = dict(loaded)
            if changed:
                self._rev += 1
            return True, "ok"

    def _read_saved(self):
        try:
            with open(self._save_path, "r") as fp:
                loaded = json.load(fp)
        except Exception as exc:
            return False, None, str(exc)
        if not isinstance(loaded, dict):
            return False, None, "saved params must be an object"
        ok, msg = self._validate_all(loaded)
        if not ok:
            return False, None, msg
        return True, dict(loaded), "ok"

    def _validate_all(self, values):
        for name in values:
            if name not in self._limits:
                return False, "unknown param: {}".format(name)
        for name in self._limits:
            if name not in values:
                return False, "missing param: {}".format(name)
            ok, msg = self._validate_value(name, values[name])
            if not ok:
                return False, msg
        return True, "ok"

    def _validate_value(self, name, value):
        if isinstance(value, bool) or not isinstance(value, numbers.Number):
            return False, "param {} must be numeric".format(name)
        lo, hi = self._limits[name]
        if value < lo or value > hi:
            return False, "out of range [{}, {}] for {}: {}".format(lo, hi, name, value)
        return True, "ok"


def _self_test():
    import tempfile

    path = os.path.join(tempfile.mkdtemp(), "stage1.json")
    params = SharedParams(
        {"kp": 0.5, "base_speed": 20},
        {"kp": (0.0, 3.0), "base_speed": (5, 45)},
        {"kp": 0.1, "base_speed": 5},
        path,
    )
    assert params.rev() == 0
    assert params.set("missing", 1)[0] is False
    assert params.set("kp", 9)[0] is False
    assert params.set("kp", 0.8)[0] is False
    assert params.set("kp", 0.6)[0] is True
    assert params.rev() == 1
    assert params.save()[0] is True
    assert params.set("kp", 0.7)[0] is True
    assert params.rollback()[0] is True
    assert params.get("kp") == 0.6
    print("shared_params self-test ok")


if __name__ == "__main__":
    _self_test()
