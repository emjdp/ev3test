#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""라이브 SharedParams + 하위 스테이지 확정 상수를 합쳐 보이는 읽기 전용 뷰.

Stage 5 계열 공용(stage5_integration 에서 이동, 2026-07-06 하위 단계 분할 —
docs/specs/stage5_substages.md). _run_turn/pd_step/read_marker_at_rest 는
kp/turn_speed/마커값 등을 snapshot 에서 기대하므로, 확정값을 라이브로 노출하지
않으면서 같은 인터페이스(snapshot/rev)를 유지하기 위한 어댑터다.
"""


class ParamsView(object):
    """라이브 값이 확정값과 겹치면 라이브가 이긴다."""

    def __init__(self, shared, confirmed):
        self._shared = shared
        self._confirmed = dict(confirmed)

    def snapshot(self):
        snap = dict(self._confirmed)
        snap.update(self._shared.snapshot())
        return snap

    def rev(self):
        return self._shared.rev()
