#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 5 계열 공용 — 회전 지시 토큰(L/S/R/U) 어휘와 파서.

stage5_integration(시퀀스 소비)과 stage5-x 하위 단계(고정 지시 등,
docs/specs/stage5_substages.md)가 같은 토큰 어휘를 쓴다. 공용 코드는 lib/ 에
두고 import 한다(AGENTS §1 — 복붙 금지). 순수 모듈 — ev3dev2/시간 의존 없음.
"""

VALID_TOKENS = ("L", "S", "R", "U")

# 토큰 → 판단 reason_code (DECISIONS.md 카탈로그와 일치).
TOKEN_REASON = {
    "L": "TURN_LEFT",
    "R": "TURN_RIGHT",
    "U": "UTURN",
    "S": "NODE_STRAIGHT",
}

# 토큰 → _run_turn 회전 명령(S 는 회전이 아니라 전진 — 매핑 없음).
TOKEN_TO_CMD = {
    "L": "turn_left",
    "R": "turn_right",
    "U": "uturn",
}


def parse_seq(text):
    """시퀀스 문자열 → 토큰 리스트. 'L S R U' / 'LSRU' / 'l,s,r,u' 모두 허용.

    유효 토큰(L/S/R/U) 외 문자는 ValueError.
    """
    tokens = []
    for ch in text.upper():
        if ch in (" ", ",", "\t", "\n"):
            continue
        if ch not in VALID_TOKENS:
            raise ValueError("invalid sequence token: {}".format(ch))
        tokens.append(ch)
    return tokens


def parse_token(text):
    """단일 토큰 문자열 → 'L'/'S'/'R'/'U'. 정확히 1개가 아니면 ValueError."""
    tokens = parse_seq(text)
    if len(tokens) != 1:
        raise ValueError("expected exactly one token, got: {!r}".format(text))
    return tokens[0]
