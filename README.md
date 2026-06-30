# ev3test — 라인트레이싱 + 노드탐색 (단계별 재구축)

ev3dev 기반 EV3 로봇으로 **라인트레이싱 + 노드(분기) 탐색 + 색상코드 노드 판정**을
구현한다. 이 문서는 **사람과 모든 AI 에이전트(Claude / Codex / Gemini / Antigravity)가
공통으로 읽는 단일 설명서**다. 시작 전에 이 README → [docs/STAGES.md](docs/STAGES.md) →
[PROGRESS.md](PROGRESS.md) 순으로 읽는다.

## 왜 새로 만드는가 (핵심 원칙)

이전 구현(`/home/emjdp/dev/ev3maze/robot`)은 **모든 기능을 한 번에 넣고 `config.py`의
수십 개 값을 하나씩 고치는 방식**이었다. 값들이 서로 얽혀 있어 **문제가 어디서 생기는지
특정할 수 없었고**, 결국 진행 불가 상태가 되었다.

그래서 이 프로젝트는 정반대로 간다:

1. **단계(Stage)별로 쪼갠다.** 각 단계는 *독립 실행 가능한 하나의 작은 스크립트*다.
2. **한 번에 하나만 검증한다.** 라인트레이싱이 실기에서 확실히 될 때까지 회전을 건드리지
   않는다. 회전이 될 때까지 노드 감지를 안 한다.
3. **단계가 통과하면 그 코드는 더 이상 건드리지 않고** 다음 단계가 그것을 가져다 쓴다.
4. **튜닝 값은 그 단계 파일 안에, 그 단계가 쓰는 것만** 둔다. 전역 거대 config 금지.
5. 실기에서 **"통과 기준(Done)"을 만족**해야 그 단계를 끝낸 것으로 본다.

> 황금률: **한 번에 변수 하나.** 어떤 단계에서 막히면, 그 단계의 값 *하나만* 바꾸고
> 실기에서 결과를 확인한 뒤 [PROGRESS.md](PROGRESS.md)에 무엇을 바꿨고 어떻게 됐는지 적는다.

## 라이브 튜닝: EV3는 주행, 노트북은 관제소

`scp → 실행 → 실패 → 수정` 반복은 너무 느리고, 현실값(조명·배터리·바닥·속도)은 계속
변한다. 그래서 **EV3에서 주행 코드가 도는 동안 노트북에서 파라미터를 실시간으로 바꾸고
telemetry를 보며 튜닝**하는 구조를 쓴다(SSH 터널 + JSON 소켓).

핵심은 **이 라이브 튜닝이 "스테이지"가 아니라 "공용 도구"** 라는 점이다 — 단계와 함께
*최소한으로* 등장해 *단계마다 조금씩* 자란다. Stage 1 라인트레이싱이 실기에서 되기도 전에
대시보드·자동튜닝까지 다 지으면 이전 프로젝트가 망한 방식을 그대로 반복하는 것이다.

전체 설계·기술결정·안전장치·빌드순서·에이전트 워크플로우: **[docs/LIVE_TUNING.md](docs/LIVE_TUNING.md)**.

대시보드보다 먼저 만드는 것: ① 단일 동작 원격 트리거(`robotctl do`)로 **빠른 보정
루프**(회전 하나 1시간 → 1분), ② **판단 기록**("110 코너 → 좌회전"처럼 왜 그 행동을
했는지), ③ **재연**(기록한 센서로 로봇 없이 판단 다시 돌려보기). → **[docs/DECISIONS.md](docs/DECISIONS.md)**.

## 하드웨어 배선 (이전 로봇에서 검증됨)

자세한 내용·튜닝 주의점은 [docs/HARDWARE.md](docs/HARDWARE.md).

| 역할 | 포트 |
|---|---|
| 주행 좌 / 우 라지 모터 | `outA` / `outB` |
| 그립&리프트 미디엄 모터 | `outC` |
| 컬러센서 좌 / 중 / 우 | `in1` / `in2` / `in3` |
| 초음파 센서 | `in4` |

> 실제 로봇에 맞는지 **Stage 0에서 반드시 먼저 확인**한다.

## 단계 로드맵 (요약)

전체·통과기준은 [docs/STAGES.md](docs/STAGES.md) 참고.

| 단계 | 내용 | 상태 |
|---|---|---|
| Stage 0 | 연결/포트 확인 (모터·센서 인식) | 실기 Done |
| Stage 1 | 기초 라인트레이싱 (중앙센서 1개, 비례제어) | 시작 전 |
| Stage 2 | 원시 회전 (좌90 / 우90 / U턴) 각각 보정 | 시작 전 |
| Stage 3 | 노드 감지 (좌·중·우 3센서 bits 패턴) | 시작 전 |
| Stage 4 | 색상코드 노드 판정 (중앙센서 컬러모드) | 시작 전 |
| Stage 5 | 라인트레이싱 + 노드에서 분기 회전 통합 | 시작 전 |
| Stage 6 | 노드 탐색/복귀 알고리즘 | 시작 전 |
| Stage 7 | 물체 집기 (그리퍼 + 초음파) | 시작 전 |

## 디렉토리 구조

```
ev3test/
├── README.md          # ← 지금 이 문서 (공용 설명)
├── AGENTS.md          # 모든 에이전트 공통 작업 규칙 (Codex/Gemini/Antigravity)
├── CLAUDE.md          # Claude 전용 (AGENTS.md 를 그대로 가져옴)
├── GEMINI.md          # Gemini 전용 (AGENTS.md 참조)
├── PROGRESS.md        # 진행 상황 + TODO (모든 에이전트 공통 기록)
├── docs/
│   ├── HARDWARE.md    # 검증된 배선/포트/주의점
│   ├── STAGES.md      # 단계별 상세 + 통과 기준(Done)
│   ├── LIVE_TUNING.md # 라이브 튜닝 구조(서버/CLI/telemetry/안전/에이전트)
│   └── DECISIONS.md   # 판단 기록(reason)·재연(replay)·단일동작 트리거(do)
├── lib/               # 브릭에서 import 하는 공용 모듈 (shared_params/telemetry/tuning_server/pid/hardware)
├── stages/            # 단계별 독립 실행 진입점 (stageN_*.py, lib import)
├── tools/             # 노트북 쪽: robotctl, telemetry_watcher 등
├── config/            # save 된 검증값 (stage별, git 추적함)
├── runs/current/      # telemetry.jsonl, latest_state.json, params.json (git 추적 안 함)
└── dashboard/         # (나중)
```

> 위 `lib/` `tools/` `config/` `runs/` `dashboard/` 는 **목표 구조**다. 라이브 튜닝이
> 처음 필요해지는 Stage 1에서 최소한으로 생긴다(지금은 docs/STAGES 만 있는 상태).

## 실행 (ev3dev 브릭에서)

각 단계 스크립트는 독립 실행한다. 예:

```bash
python3 stages/stage0_check.py      # 포트/센서 인식 확인
python3 stages/stage1_linetrace.py  # 기초 라인트레이싱
```

PC에서는 ev3dev2 가 없으므로 **문법 점검만** 가능:

```bash
python3 -m py_compile stages/*.py
```

## 에이전트에게

- 작업 규칙·커밋 규약은 [AGENTS.md](AGENTS.md)에 있다. **작업 시작 전 반드시 읽는다.**
- 진행 상황·다음 할 일은 [PROGRESS.md](PROGRESS.md)에 있다. **작업 후 반드시 갱신·커밋한다.**
