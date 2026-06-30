# -*- coding: utf-8 -*-
"""Stage 2 판단층 (순수, ev3dev2 없음) — '어느 회전을 왜 하는가'.

판단층 ↔ 구동층 분리(DECISIONS.md 0장). 여기는 하드웨어/시간/모터가 없다.
PC 에서 import·단위테스트·(원하면) 재연이 된다.

Stage 2 의 '왜'는 단순하다 — 사람이 `robotctl do turn_*` 로 고른 한 동작을 그대로
구동층에 넘긴다. 그래도 Stage 5~6 에서 노드/출구 기반 선택으로 자랄 자리를
detail(node_id/available_exits/selected/rule)로 미리 비워 둔다.

규약: 브릭에서도 import 될 수 있으니 Python 3.5 안전(f-string 금지).
"""

# do 트리거 명령(사람이 고른 것) → 구동층 action
COMMAND_TO_ACTION = {
    "turn_left": "LEFT90",
    "turn_right": "RIGHT90",
    "uturn": "UTURN180",
}

# 구동층 action → reason_code (DECISIONS.md 카탈로그와 일치; 새 코드 추가 안 함)
ACTION_TO_REASON = {
    "LEFT90": "TURN_LEFT",
    "RIGHT90": "TURN_RIGHT",
    "UTURN180": "UTURN",
}

# reason detail 의 selected(어느 출구를 골랐나). Stage 2 는 do 가 곧 선택.
ACTION_TO_SELECTED = {
    "LEFT90": "LEFT",
    "RIGHT90": "RIGHT",
    "UTURN180": "UTURN",
}


def target_degrees(action, params):
    """회전 종류 + 보정계수 → 모터에 줄 '바퀴 회전 각도(도)'.

    BASE_PIVOT_DEG_90 / BASE_PIVOT_DEG_180 (stage 파일 상수, 기하 1차 추정)에
    live 보정계수를 곱한다. 반환은 양수(절댓값); 회전 방향은 구동층이 정한다.
    """
    if action == "UTURN180":
        return params["BASE_PIVOT_DEG_180"] * params["turn_180_factor"]
    return params["BASE_PIVOT_DEG_90"] * params["turn_90_factor"]


def factor_for(action, params):
    """이 회전에 적용되는 보정계수(검증/로그용)."""
    if action == "UTURN180":
        return params["turn_180_factor"]
    return params["turn_90_factor"]


def decide_turn(command, params, state):
    """'어느 회전을 왜' 결정 (순수).

    command : do 트리거가 넘긴 'turn_left' | 'turn_right' | 'uturn'
    params  : live params(turn_speed/turn_90_factor/turn_180_factor/...) +
              BASE_PIVOT_DEG_90/180 (stage 파일 상수)를 합친 snapshot
    state   : Stage 2 미사용(빈 dict). Stage 5~6 확장 자리.

    반환: (action, reason_code, detail)
      action      : 'LEFT90' | 'RIGHT90' | 'UTURN180'
      reason_code : 'TURN_LEFT' | 'TURN_RIGHT' | 'UTURN'
      detail      : command/rule/selected/node_id/available_exits/target_deg/factor/turn_speed
    """
    action = COMMAND_TO_ACTION.get(command)
    if action is None:
        raise ValueError("unknown turn command: {}".format(command))
    reason_code = ACTION_TO_REASON[action]
    target = target_degrees(action, params)
    detail = {
        "command": command,
        "rule": "DO_TRIGGER",          # Stage 2: 사람이 do 로 고름. Stage 5~6 에서 규칙으로 확장.
        "selected": ACTION_TO_SELECTED[action],
        "node_id": None,               # Stage 2 미사용(노드 감지 없음)
        "available_exits": [],         # Stage 2 미사용(분기 선택 없음)
        "target_deg": target,
        "factor": factor_for(action, params),
        "turn_speed": params.get("turn_speed"),
    }
    return action, reason_code, detail


def _self_test():
    params = {
        "BASE_PIVOT_DEG_90": 190.0,
        "BASE_PIVOT_DEG_180": 380.0,
        "turn_90_factor": 1.0,
        "turn_180_factor": 1.0,
        "turn_speed": 18,
    }
    a, reason, detail = decide_turn("turn_left", params, {})
    assert a == "LEFT90" and reason == "TURN_LEFT"
    assert detail["target_deg"] == 190.0
    assert detail["selected"] == "LEFT" and detail["factor"] == 1.0
    assert detail["turn_speed"] == 18

    a, reason, detail = decide_turn("turn_right", params, {})
    assert a == "RIGHT90" and reason == "TURN_RIGHT" and detail["selected"] == "RIGHT"

    a, reason, detail = decide_turn("uturn", params, {})
    assert a == "UTURN180" and reason == "UTURN"
    assert detail["target_deg"] == 380.0 and detail["factor"] == 1.0

    # 보정계수 선형 반응
    p2 = dict(params)
    p2["turn_90_factor"] = 0.5
    assert target_degrees("LEFT90", p2) == 95.0
    p2["turn_90_factor"] = 2.0
    assert target_degrees("LEFT90", p2) == 380.0
    p2["turn_180_factor"] = 1.1
    assert abs(target_degrees("UTURN180", p2) - 418.0) < 1e-9

    try:
        decide_turn("spin", params, {})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("decide_turn self-test ok")


if __name__ == "__main__":
    _self_test()
