#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_maze_v5 판단층/리셋 배선 테스트 — ev3dev2 없이 PC 에서 돈다.

실행:  python3 tests/test_run_maze_v5_logic.py
검증:  (1) 세션 초기상태(fresh_session_state), (2) reset 이 대시보드 액션 매니페스트
       에 있고 TuningServer 의 do 경로로 전달되며 on_do 유사 핸들러가 reset 플래그를
       세운다(하드웨어 없이 배선만), (3) 탐색 알고리즘/params 는 v4 를 그대로 재사용
       (import 동일성 + params 키 일치 = config 이식 가능).
       탐색 로직 자체는 tests/test_run_maze_v4_logic.py 가 이미 덮는다.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.shared_params import SharedParams                   # noqa: E402
from lib.telemetry import Telemetry                           # noqa: E402
from lib.tuning_server import TuningServer                    # noqa: E402
from stages import run_maze_v4 as v4                          # noqa: E402
from stages.run_maze_v5 import (                              # noqa: E402
    fresh_session_state, ACTIONS, STAGE_NAME, SAVE_PATH,
    Explorer, PRIORITY,
    INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP, PARAM_ORDER, UI_STEP, UNITS,
)


# --- 세션 초기 상태 ---------------------------------------------------------------

def test_fresh_session_state():
    s = fresh_session_state()
    assert s == {"visits": 0, "goal_seen": False, "done": False, "grabbed": False}
    # 매 호출이 독립 dict(세션 간 상태 누수 방지)
    a = fresh_session_state()
    a["visits"] = 5
    assert fresh_session_state()["visits"] == 0
    print("fresh_session_state ok")


# --- reset 액션이 매니페스트에 있다 -------------------------------------------------

def test_reset_action_in_manifest():
    names = [a["name"] for a in ACTIONS]
    assert "reset" in names
    assert "read_color" in names and "read_reflect" in names
    print("reset action in manifest ok")


# --- reset 배선: TuningServer do 경로가 reset 을 핸들러로 넘긴다(하드웨어 없이) --------

def _make_params():
    return SharedParams(INITIAL_PARAMS, PARAM_LIMITS, MAX_STEP,
                        os.path.join(_ROOT, "config", "_test_run_maze_v5_unused.json"),
                        ui_step=UI_STEP, units=UNITS, param_order=PARAM_ORDER)


def test_reset_routes_through_tuning_server():
    reset_flag = {"on": False, "source": None}

    def on_do(action, args):
        # run() 의 on_do reset 분기와 동일 구조(하드웨어 무관 부분만).
        if action not in ("read_color", "read_reflect", "reset"):
            return {"error": "unknown action: {}".format(action)}
        if action == "reset":
            reset_flag["on"] = True
            reset_flag["source"] = (args or {}).get("source", "dashboard")
            return {"queued": "reset"}
        return {"queued": action}

    server = TuningServer(_make_params(), Telemetry(), do_handler=on_do,
                          actions=ACTIONS, stage=STAGE_NAME)
    # start() 없이 명령 처리 경로만 직접 호출(소켓 바인딩 회피).
    resp = server._cmd_do({"action": "reset", "args": {"source": "unit"}})
    assert resp["ok"] is True and resp["queued"] == "reset"
    assert reset_flag["on"] is True and reset_flag["source"] == "unit"

    # 알 수 없는 액션은 거부(reset 오타 등이 조용히 통과하지 않게)
    bad = server._cmd_do({"action": "restart"})
    assert bad["ok"] is False

    # describe 에 reset 이 노출되어 대시보드가 버튼을 그린다
    desc = server._cmd_describe({})
    assert "reset" in [a["name"] for a in desc["actions"]]
    print("reset routes through tuning server ok")


# --- v4 알고리즘/params 재사용(복붙 아님) ------------------------------------------

def test_reuses_v4_explorer_and_params():
    # Explorer/PRIORITY 는 v4 의 것을 그대로 import(동일 객체) — 알고리즘 복제 없음
    assert Explorer is v4.Explorer
    assert PRIORITY is v4.PRIORITY
    # params 매니페스트도 v4 를 그대로 import — 키/한계/시드 동일(config 이식 가능)
    assert INITIAL_PARAMS is v4.INITIAL_PARAMS
    assert PARAM_LIMITS is v4.PARAM_LIMITS
    print("reuses v4 explorer/params ok")


def test_param_safety_metadata():
    assert len(INITIAL_PARAMS) == 12
    assert set(PARAM_LIMITS.keys()) == set(INITIAL_PARAMS.keys())
    assert set(MAX_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(PARAM_ORDER) == set(INITIAL_PARAMS.keys())
    assert set(UI_STEP.keys()) == set(INITIAL_PARAMS.keys())
    assert set(UNITS.keys()) <= set(INITIAL_PARAMS.keys())
    assert STAGE_NAME == "run_maze_v5"
    assert SAVE_PATH.endswith("run_maze_v5.json")
    print("param safety metadata ok")


def main():
    test_fresh_session_state()
    test_reset_action_in_manifest()
    test_reset_routes_through_tuning_server()
    test_reuses_v4_explorer_and_params()
    test_param_safety_metadata()
    print("ALL run_maze_v5 logic tests passed")


if __name__ == "__main__":
    main()
