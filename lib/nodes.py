# -*- coding: utf-8 -*-
"""Stage 3 판단층 (순수, ev3dev2 없음) — 좌/중/우 3센서 bits 노드 감지.

판단층 ↔ 구동층 분리(DECISIONS.md 0장). 여기에는 하드웨어/모터가 없고, 시간은
바깥에서 ms 로 받는다. PC 에서 import·단위테스트·replay(로봇 없이)가 된다.

세 가지만 한다:
  - bits_from_raw : 좌/중/우 raw 반사광 → 좌/중/우 threshold 로 자른 0/1 bits.
  - classify_node : bits(LCR) → 노드 종류(LINE/CORNER_L/CORNER_R/CROSS/DEAD_END).
  - NodeDebouncer : 주행 흔들림 속에서 노드 후보→확정을 debounce 로 가른다.

약속(STAGES.md / stage3_node_detect.md §1 과 일치):
  - bits 극성: 1 = 검은 선(어두움), 0 = 흰 바닥(밝음).
    반사광은 흰 바닥=큰 값, 검은 선=작은 값 → 'raw < threshold' 이면 1.
  - bits 순서: LCR (좌, 중, 우).
  - Stage 3 은 회전/색 판정을 하지 않는다. '코너냐 분기냐(직진 생존)' 정밀 구분(peek)은
    Stage 5 로 미룬다 — 여기선 'bits 패턴 종류'까지만 확정한다.

규약: 브릭에서도 import 될 수 있으니 Python 3.5 안전(f-string 금지).
"""

# 좌/우 센서 실측 전 기본 threshold. Stage 1 중앙센서 실측(검정 0 / 흰색 10)을 따라
# 흑·백 중간값 부근으로 둔다. 실기에서 센서별로 라이브 보정한다(좌/우는 미실측 — §11).
DEFAULT_THRESHOLD = 5

# 노드 종류별 reason_code (DECISIONS.md 카탈로그와 일치; 새 코드 추가 없음).
KIND_TO_REASON = {
    "CORNER_L": "CORNER_LEFT",
    "CORNER_R": "CORNER_RIGHT",
}


def bits_from_raw(raw, thresholds):
    """raw 반사광 3개(L,C,R)를 좌/중/우 threshold 로 잘라 0/1 비트로.

    어두울수록(작을수록) 1 = 검은 선. 반환: (l, c, r) 0/1 정수 튜플.
    """
    return tuple(1 if v < t else 0 for v, t in zip(raw, thresholds))


def bits_str(bits):
    """(l,c,r) → "LCR" 문자열(예 (1,1,0) → "110")."""
    return "".join(str(int(b)) for b in bits)


def node_kind(bits):
    """bits(LCR, 0/1) → 노드 종류 문자열.

      010            -> LINE      (정상 라인, 노드 아님)
      000            -> DEAD_END  (선 없음 = 막다른 길 후보; LINE_LOST 와 구분)
      111 / 101      -> CROSS     (십자/교차)
      110 / 100      -> CORNER_L  (좌측 갈래; 코너/분기 구분은 Stage5)
      011 / 001      -> CORNER_R  (우측 갈래)
    """
    l, c, r = bits
    if (l, c, r) == (0, 1, 0):
        return "LINE"
    if (l, c, r) == (0, 0, 0):
        return "DEAD_END"
    if (l, c, r) == (1, 1, 1) or (l, c, r) == (1, 0, 1):
        return "CROSS"
    if l == 1 and r == 0:
        return "CORNER_L"
    if r == 1 and l == 0:
        return "CORNER_R"
    # 이론상 위에서 8가지가 모두 잡힌다. 방어적으로 교차 취급.
    return "CROSS"


# =====================================================================
# 3센서 라인트레이싱(순수) — 노드 확정 전 FOLLOW 상태의 주행 판단.
#   Stage 1 중앙센서 PID 가 아니라 좌/중/우 bits/raw 로 추종한다.
#   구동층(stages/stage3_node_detect.py)이 follow 상수를 params 에 병합해 넘긴다
#   (lib 가 stages 를 import 하지 않게 — 순환 참조 방지).
# =====================================================================

# 구동층이 병합을 빠뜨려도 동작하게 하는 안전 기본값(실제 값은 stage3 파일 상수).
FOLLOW_DEFAULTS = {
    "follow_base_speed": 20,    # 직진 기본 속도(%)
    "follow_gain": 12.0,        # line_error3(bits 위치 오차, ±1/±2) 당 turn
    "follow_turn_limit": 35,    # turn 클램프(±)
    "follow_slow_speed": 12,    # 노드 후보(111/101) 저속 직진 속도(%)
}

# 노드 후보(확정 전 저속 직진)·막다른 길 후보 bits 패턴.
_NODE_CANDIDATE_BITS = ((1, 1, 1), (1, 0, 1))
_DEAD_END_BITS = (0, 0, 0)


def _clampf(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def make_follow_state():
    """decide_line3 용 상태. last_turn(직전 조향) 보관 — 막다른 길에서 유지한다."""
    return {"last_turn": 0.0}


def decide_line3(raw, bits, params, state):
    """좌/중/우 3센서 라인트레이싱 1틱(순수). 노드 확정 전 FOLLOW 에서 쓴다.

    raw   : (l, c, r) raw 반사광. 흰 바닥=큰 값, 검은 선=작은 값.
    bits  : (l, c, r) 0/1. 1=검은 선.
    params: 구동층이 병합한 스냅샷 + Stage 3 follow 상수
            (follow_base_speed/follow_gain/follow_turn_limit/follow_slow_speed).
    state : make_follow_state() 결과. last_turn 을 제자리 갱신(라인 추종 시에만).

    반환 action(dict): {line, turn, error, line_error3, left, right}

    ⚠️ 조향은 raw 차(r-l)가 아니라 **bits 위치 오차**로 만든다. 정상 추종 중엔 좌/우
    센서가 둘 다 흰 바닥이라 raw 차는 선 위치가 아니라 두 센서의 '흰색 읽는 값'
    불일치(상시 편향)만 먹어 시작하자마자 한쪽으로 꺾인다. bits 는 이미 센서별
    threshold 로 잘려 그 편향이 없다(2026-07-01 실기 재설계).

    부호 약속(Stage 1 to_wheel_speeds 와 동일):
      turn > 0 → left=base-turn, right=base+turn → 로봇이 왼쪽으로 돈다.

      010            -> 중앙만 선 위 → line_error3=0 → 직진(중앙 폭 안은 데드밴드).
      110/100        -> 왼쪽이 선 위 → line_error3>0 → turn>0(왼쪽 보정). 중앙이
                        선을 놓친 100 은 이탈이 크다고 ×2 가중(더 세게).
      011/001        -> 오른쪽이 선 위 → line_error3<0 → turn<0(오른쪽 보정). 001 은 ×2.
      111/101        -> 노드 후보 → 저속(slow_speed) 직진(turn 0). 멈춤은 debounce 가.
      000            -> 막다른 길 후보 → 속도 0(정지) + 직전 조향(last_turn) 유지(보수).
    """
    base = params.get("follow_base_speed", FOLLOW_DEFAULTS["follow_base_speed"])
    gain = params.get("follow_gain", FOLLOW_DEFAULTS["follow_gain"])
    turn_limit = params.get("follow_turn_limit", FOLLOW_DEFAULTS["follow_turn_limit"])
    slow = params.get("follow_slow_speed", FOLLOW_DEFAULTS["follow_slow_speed"])

    pattern = (int(bits[0]), int(bits[1]), int(bits[2]))

    # 노드 후보(111/101): 확정 전에는 저속 직진(노드 위에서 멈추기 유리하게). turn 0.
    if pattern in _NODE_CANDIDATE_BITS:
        return {"line": "NODE", "turn": 0.0, "error": 0.0, "line_error3": 0.0,
                "left": slow, "right": slow}

    # 막다른 길 후보(000): 확정 전 짧은 순간엔 직전 조향 유지 + 속도 0(보수적 정지).
    if pattern == _DEAD_END_BITS:
        held = state.get("last_turn", 0.0)
        return {"line": "LOST", "turn": held, "error": 0.0, "line_error3": 0.0,
                "left": 0, "right": 0}

    # 라인 추종(010/100/110/001/011): '어느 센서가 선 위인가'(bits)로 위치 오차.
    #   raw 차(r-l)는 흰바닥 편향을 먹으니 쓰지 않는다(상단 docstring ⚠️ 참고).
    #   왼쪽 센서가 선 위면 (l_b - r_b) > 0 → turn>0 → 왼쪽 보정(선 쪽으로).
    #   중앙이 선을 놓쳤으면(c_b=0) 이탈이 크다고 보고 ×2 가중.
    l_b, c_b, r_b = pattern
    weight = 2 if c_b == 0 else 1
    line_error3 = float((l_b - r_b) * weight)   # 010→0, 110→+1, 100→+2, 011→-1, 001→-2
    turn = _clampf(gain * line_error3, -turn_limit, turn_limit)
    state["last_turn"] = turn
    left = base - turn
    right = base + turn
    return {"line": "ON", "turn": turn, "error": line_error3,
            "line_error3": line_error3, "left": left, "right": right}


def classify_node(bits, params, state):
    """bits → (kind, reason_code, detail). 순수(부작용 없음, replay 대상).

    kind        : 'LINE' | 'CORNER_L' | 'CORNER_R' | 'CROSS' | 'DEAD_END'
    reason_code : LINE 이면 None, 그 외 노드 후보는 'NODE_CANDIDATE'
                  (확정 승격은 NodeDebouncer 가 'NODE_CONFIRMED' 로 한다)
    detail      : {"bits": "LCR", "kind": kind}
    """
    kind = node_kind(bits)
    detail = {"bits": bits_str(bits), "kind": kind}
    if kind == "LINE":
        return kind, None, detail
    return kind, "NODE_CANDIDATE", detail


class NodeDebouncer(object):
    """노드 이벤트를 주행 흔들림 속에서 확정한다(순수, 시간은 ms/샘플로 받음).

    - 같은 노드 종류가 node_confirm_ms 만큼 연속 지속되면 NODE_CONFIRMED.
    - 새 노드 후보가 처음 잡힌 틱에 NODE_CANDIDATE 를 1회 낸다(이후 확정 전까지 조용).
    - 010(LINE) 이 끼면 카운트 리셋(통과 중 순간 흔들림/노이즈 무시).
    - 직전 확정 뒤 node_debounce_ms 안에는 재확정 금지(같은 노드/가까운 노드 중복 방지).

    push(bits, t_ms, params, dist_mm) -> (status, info)
      status : 'NODE_CONFIRMED' | 'NODE_CANDIDATE' | None
      info   : {kind, bits, duration_ms, dist_mm, count, debounce_ms}
    """

    def __init__(self):
        self.candidate_kind = None      # 현재 누적 중인 노드 종류
        self.candidate_since_ms = None  # 그 후보가 시작된 t_ms
        self.count = 0                  # 현재 후보 연속 지속 카운트(telemetry/디버그)
        self.last_confirm_ms = None     # 직전 확정 시각(debounce 기준)
        self.last_confirm_kind = None

    def reset(self):
        """후보 누적만 리셋(확정 이력/last_confirm 은 유지 — debounce 가 계속 유효)."""
        self.candidate_kind = None
        self.candidate_since_ms = None
        self.count = 0

    def push(self, bits, t_ms, params, dist_mm=0.0):
        kind = node_kind(bits)
        confirm_ms = params.get("node_confirm_ms", 120)
        debounce_ms = params.get("node_debounce_ms", 900)

        if kind == "LINE":
            # 정상 라인 → 후보 누적 리셋. 노드 아님.
            self.reset()
            return None, {"kind": "LINE", "bits": bits_str(bits),
                          "duration_ms": 0, "dist_mm": dist_mm, "count": 0,
                          "debounce_ms": debounce_ms}

        # --- 노드 후보(LINE 이외) ---
        new_candidate = (kind != self.candidate_kind)
        if new_candidate:
            self.candidate_kind = kind
            self.candidate_since_ms = t_ms
            self.count = 1
        else:
            self.count += 1

        if self.candidate_since_ms is None:
            duration = 0
        else:
            duration = t_ms - self.candidate_since_ms

        info = {"kind": kind, "bits": bits_str(bits), "duration_ms": duration,
                "dist_mm": dist_mm, "count": self.count, "debounce_ms": debounce_ms}

        # 확정 조건: 같은 종류가 confirm_ms 이상 지속.
        if duration >= confirm_ms:
            recently_confirmed = (self.last_confirm_ms is not None and
                                  (t_ms - self.last_confirm_ms) < debounce_ms)
            if recently_confirmed:
                # 직전 확정 후 debounce 안 → 같은/가까운 노드 중복 확정 금지.
                return None, info
            self.last_confirm_ms = t_ms
            self.last_confirm_kind = kind
            return "NODE_CONFIRMED", info

        # 아직 confirm_ms 미달 — 후보가 막 시작한 틱이면 후보 1회 알림.
        if new_candidate:
            return "NODE_CANDIDATE", info
        return None, info


def make_node_state():
    """decide_node 용 판단층 상태(빈 dict 로 시작해도 push 가 채운다 — replay 호환)."""
    return {"deb": NodeDebouncer()}


def decide_node(sensors, params, state):
    """replay 계약 어댑터: 기록한 sample → (kind|None, reason_code|None, detail).

    sensors: {"reflect": (l,c,r)} 또는 {"reflect_l","reflect_c","reflect_r"} +
             {"t_ms", "dist_mm"}  (samples.jsonl 의 telemetry 프레임 한 줄)
    params : {"left_threshold","center_threshold","right_threshold",
              "node_confirm_ms","node_debounce_ms", ...}
    state  : 제자리 갱신(NodeDebouncer 보관) — replay.py 가 run 전체에 걸쳐 재사용.

    reason_code 로 status(NODE_CANDIDATE/NODE_CONFIRMED)를 그대로 돌려줘
    replay.py 가 같은 events 를 다시 만들게 한다.
    """
    deb = state.get("deb")
    if deb is None:
        deb = NodeDebouncer()
        state["deb"] = deb

    raw = sensors.get("reflect")
    if raw is None:
        raw = (sensors.get("reflect_l"), sensors.get("reflect_c"), sensors.get("reflect_r"))
    raw = tuple(raw)

    thr = (params.get("left_threshold", DEFAULT_THRESHOLD),
           params.get("center_threshold", DEFAULT_THRESHOLD),
           params.get("right_threshold", DEFAULT_THRESHOLD))
    bits = bits_from_raw(raw, thr)

    t_ms = sensors.get("t_ms", 0)
    dist_mm = sensors.get("dist_mm", 0.0)
    status, info = deb.push(bits, t_ms, params, dist_mm)

    detail = dict(info)
    detail["reflect"] = list(raw)
    if status is None:
        return None, None, detail
    return info["kind"], status, detail


def _self_test():
    # bits_from_raw: 밝음(큰 값)=0, 어두움(작은 값)=1
    assert bits_from_raw((80, 80, 80), (40, 40, 40)) == (0, 0, 0)
    assert bits_from_raw((10, 80, 10), (40, 40, 40)) == (1, 0, 1)
    assert bits_str((1, 1, 0)) == "110"

    # node_kind 8가지
    assert node_kind((0, 1, 0)) == "LINE"
    assert node_kind((0, 0, 0)) == "DEAD_END"
    assert node_kind((1, 1, 1)) == "CROSS"
    assert node_kind((1, 0, 1)) == "CROSS"
    assert node_kind((1, 1, 0)) == "CORNER_L"
    assert node_kind((1, 0, 0)) == "CORNER_L"
    assert node_kind((0, 1, 1)) == "CORNER_R"
    assert node_kind((0, 0, 1)) == "CORNER_R"

    # classify_node
    kind, reason, detail = classify_node((0, 1, 0), {}, {})
    assert kind == "LINE" and reason is None and detail["bits"] == "010"
    kind, reason, _ = classify_node((1, 1, 0), {}, {})
    assert kind == "CORNER_L" and reason == "NODE_CANDIDATE"

    # NodeDebouncer: 010 만 들어오면 절대 확정/후보 없음
    p = {"node_confirm_ms": 100, "node_debounce_ms": 900}
    deb = NodeDebouncer()
    for t in range(0, 500, 20):
        status, _ = deb.push((0, 1, 0), t, p)
        assert status is None

    # 110 지속: 첫 틱 CANDIDATE, confirm_ms 도달 시 CONFIRMED
    deb = NodeDebouncer()
    s0, _ = deb.push((1, 1, 0), 0, p)
    assert s0 == "NODE_CANDIDATE"
    s1, _ = deb.push((1, 1, 0), 80, p)
    assert s1 is None                      # 80 < 100
    s2, _ = deb.push((1, 1, 0), 120, p)
    assert s2 == "NODE_CONFIRMED"          # 120 >= 100

    # debounce: 확정 직후 같은 패턴은 재확정 안 함
    s3, _ = deb.push((1, 1, 0), 200, p)
    assert s3 is None
    # 짧은 노이즈(010 한 틱) 끼면 카운트 리셋 → 다시 confirm_ms 필요
    deb = NodeDebouncer()
    assert deb.push((1, 1, 0), 0, p)[0] == "NODE_CANDIDATE"
    assert deb.push((0, 1, 0), 40, p)[0] is None        # 노이즈로 리셋
    assert deb.push((1, 1, 0), 60, p)[0] == "NODE_CANDIDATE"  # 새 후보
    assert deb.push((1, 1, 0), 130, p)[0] is None       # 60~130=70 < 100

    # decide_line3 3센서 follow: 010 직진, 110 왼쪽(turn>0), 011 오른쪽(turn<0),
    # 111 노드후보 저속 직진, 000 막다른 길 정지+직전 조향 유지.
    fs = make_follow_state()
    a = decide_line3((80, 5, 80), (0, 1, 0), {}, fs)
    assert abs(a["turn"]) < 1e-9 and a["left"] == a["right"] and a["line"] == "ON"
    a = decide_line3((0, 0, 80), (1, 1, 0), {}, fs)
    assert a["turn"] > 0 and a["left"] < a["right"] and a["line_error3"] > 0
    assert fs["last_turn"] > 0
    a = decide_line3((80, 0, 0), (0, 1, 1), {}, fs)
    assert a["turn"] < 0 and a["left"] > a["right"] and a["line_error3"] < 0
    a = decide_line3((3, 3, 3), (1, 1, 1), {}, fs)
    assert abs(a["turn"]) < 1e-9 and a["left"] == a["right"] and a["line"] == "NODE"
    # bits 위치 오차: 중앙 놓친 이탈(100/001)은 근접(110/011)보다 ×2 세게.
    fs3 = make_follow_state()
    near = decide_line3((0, 0, 80), (1, 1, 0), {}, fs3)   # 110
    far = decide_line3((0, 80, 80), (1, 0, 0), {}, fs3)   # 100 (중앙 놓침)
    assert far["line_error3"] == 2 * near["line_error3"] > 0
    assert abs(far["turn"]) >= abs(near["turn"])
    # 재설계 회귀 방지: 좌/우 흰바닥 raw 불일치(20 vs 14)가 있어도 010 이면 직진.
    straight = decide_line3((20, 0, 14), (0, 1, 0), {}, fs3)
    assert straight["turn"] == 0.0 and straight["left"] == straight["right"]
    fs2 = make_follow_state()
    decide_line3((0, 0, 80), (1, 1, 0), {}, fs2)        # 왼쪽 조향으로 last_turn>0
    a = decide_line3((80, 80, 80), (0, 0, 0), {}, fs2)
    assert a["left"] == 0 and a["right"] == 0 and a["turn"] == fs2["last_turn"] > 0

    # decide_node replay 어댑터
    st = make_node_state()
    pr = {"left_threshold": 5, "center_threshold": 5, "right_threshold": 5,
          "node_confirm_ms": 100, "node_debounce_ms": 900}
    # 밝은 raw(threshold 초과) → bits 000 → DEAD_END 후보
    k, reason, d = decide_node({"reflect": (80, 80, 80), "t_ms": 0}, pr, st)
    assert reason == "NODE_CANDIDATE" and k == "DEAD_END" and d["reflect"] == [80, 80, 80]
    print("nodes self-test ok")


if __name__ == "__main__":
    _self_test()
