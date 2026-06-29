# AGENTS.md — 모든 AI 에이전트 공통 작업 규칙

이 파일은 **Claude(Claude Code) · Codex · Gemini · Antigravity** 등 이 저장소에서
작업하는 모든 AI 에이전트가 따르는 단일 규칙서다. 각 에이전트의 전용 파일
(`CLAUDE.md`, `GEMINI.md`)은 이 파일을 그대로 가리킨다.

> 도구별 메모: Codex 와 Google Antigravity 는 `AGENTS.md` 를 기본으로 읽는다.
> Claude Code 는 `CLAUDE.md`, Gemini CLI 는 `GEMINI.md` 를 읽으며, 둘 다 이 파일을
> 참조하도록 해 두었다. 그러므로 **규칙은 항상 이 `AGENTS.md` 한 곳만 고친다.**

## 0. 작업 시작 전 (매번)

1. [README.md](README.md) — 프로젝트 원칙·구조.
2. [docs/STAGES.md](docs/STAGES.md) — 단계별 통과 기준.
3. [PROGRESS.md](PROGRESS.md) — 지금까지 한 일과 다음 할 일(TODO).
4. `git log --oneline -15` 로 최근 변경 흐름 파악.

## 1. 핵심 원칙 (이 프로젝트의 존재 이유)

- **단계(Stage)별로만 작업한다.** 현재 단계가 실기에서 Done 되기 전에는 다음 단계
  코드를 쓰지 않는다. 단계 정의는 [docs/STAGES.md](docs/STAGES.md).
- **한 번에 변수 하나.** 막히면 값 하나만 바꾸고 실기 결과를 확인한 뒤 기록한다.
  여러 값을 동시에 바꿔 원인을 흐리지 않는다.
- **전역 거대 config 금지.** 각 단계 스크립트는 자기 튜닝 값을 자기 파일 맨 위에 둔다.
  이전 단계에서 확정된 코드/값은 재사용하되 **수정하지 않는다.** (라이브 튜닝에서는 그
  "파일 맨 위 상수"가 그 스테이지의 *초기 params dict + PARAM_LIMITS* 가 된다. 여전히
  per-stage·소수다. 부활시키면 안 되는 건 "모든 기능을 한 곳에 모은 거대 config".)
- **각 스테이지는 독립 실행 가능**해야 한다(`python3 stages/stageN_*.py`). 공용 코드는
  `lib/` 에 두고 import 해 재사용한다(복붙 금지, 그래도 단독 실행은 유지).
- 추측한 하드웨어 동작은 반드시 **실기에서 확인**하고 결과를 PROGRESS 에 남긴다.

### 라이브 튜닝 (있다면) — 구조는 [docs/LIVE_TUNING.md](docs/LIVE_TUNING.md)

- **제어 루프는 네트워크를 절대 기다리지 않는다.** params 는 snapshot 으로 읽고, 네트워크는
  별도 thread. 연결이 끊겨도 로봇은 마지막 안전값 유지 또는 안전 정지.
- **BACK 버튼 정지가 1차**, 네트워크 `stop` 은 보조.
- **에이전트는 제안만 한다(1단계).** 어떤 에이전트도 `tools/robotctl.py set` 을 직접
  실행하지 않는다. telemetry/로그를 읽고 조정안을 내면 **사람이** 적용한다.
- 값은 `PARAM_LIMITS`(범위)·`MAX_STEP`(1회 변화폭)을 넘지 않게 제안한다.

### 판단 기록 · 재연 (Stage 1부터) — 구조는 [docs/DECISIONS.md](docs/DECISIONS.md)

- **판단층(순수)↔구동층(ev3dev2) 분리.** 판단은 `(센서, params, 상태) → (행동, reason)`
  순수 함수로 두어 PC 에서 import·테스트·재연이 되게 한다.
- **모든 상태전이/행동 결정에 `reason_code` 를 붙여 events 로그에 남긴다.** 위치 의존
  버그를 잡게 `dist_mm`/`reflect` 같은 detail 도 함께 남긴다(빈 바닥 색 측정·분기 오버슛).
- 새 판단을 추가하면 DECISIONS.md 의 reason_code 카탈로그에 1줄 추가한다.
- 보정은 코드 수정·재배포가 아니라 **`robotctl do <action>` 단일 트리거 + 값 하나 변경**
  으로 돈다. 판단/타이밍 버그는 `tools/replay.py` 로 로봇 없이 먼저 재연해 본다.

## 2. 코드 규약

- 대상 런타임: **ev3dev (ev3dev2 파이썬 라이브러리), Python 3.** 브릭에서 실행.
- PC에는 ev3dev2 가 없다 → import 는 함수/`__main__` 안에서 하거나 try/except 로 감싸
  **`python3 -m py_compile` 문법 점검**이 PC에서도 되게 한다.
- 모든 주행 루프에 **BACK 버튼 즉시 정지**를 넣는다.
- 새 파일/주석/문서는 기존 톤에 맞춰 **한국어**로 쓴다.
- 파일명: `stages/stage<N>_<짧은이름>.py` (예: `stage1_linetrace.py`).

## 3. Git 규약 (원격 없음, 로컬 추적용)

원격은 연결하지 않는다. **변경 추적**이 목적이다. 각 에이전트는 *자기가 한 변경을
직접 커밋*한다.

- 의미 있는 변경 단위로 **자주, 작게** 커밋한다.
- 커밋 메시지: 한 줄 요약(한국어) + 본문에 무엇을/왜.
- 커밋 메시지 **맨 끝에 어느 에이전트인지 trailer 한 줄**을 넣는다:

  ```
  Stage1: 라인트레이싱 KP 0.6→0.8, 곡선 추종 개선

  실기에서 곡선 코너에서 선을 놓쳐 KP 상향. threshold 는 그대로.

  Agent: claude
  ```

  trailer 값: `claude` / `codex` / `gemini` / `antigravity` 중 하나.
- 코드를 바꿨으면 가능한 한 `python3 -m py_compile stages/*.py` 로 문법 점검 후 커밋.
- 실기 검증이 필요한 변경은 커밋 메시지나 PROGRESS 에 **"실기 검증 필요"**를 표시한다.

## 4. 작업 종료 전 (매번)

1. [PROGRESS.md](PROGRESS.md) 갱신: 한 일, 실기 결과, 바꾼 값, 다음 할 일(TODO).
2. 변경을 커밋(위 규약).
3. 다음 사람이/에이전트가 막힘없이 이어갈 수 있게 **현재 상태와 막힌 지점**을 명확히 남긴다.

## 5. 하지 말 것

- 현재 단계와 무관한 "겸사겸사" 리팩토링/기능 추가.
- 확정된 이전 단계 코드 수정(꼭 필요하면 PROGRESS 에 이유를 먼저 적고 별도 커밋).
- 한 커밋에 여러 단계/여러 관심사 섞기.
- 실기 미검증 결과를 "됨"으로 기록하기.
