# PROGRESS — 진행 상황 + TODO

모든 에이전트가 공통으로 기록한다. **작업 후 반드시 갱신·커밋.**
규칙은 [AGENTS.md](AGENTS.md), 단계 정의는 [docs/STAGES.md](docs/STAGES.md).

## 현재 단계

**Stage 0 — 연결/포트 확인** (시작 전)

## 단계 상태판

| 단계 | 상태 | 비고 |
|---|---|---|
| Stage 0 연결/포트 확인 | ⬜ 시작 전 | |
| Stage 1 기초 라인트레이싱 | ⬜ 시작 전 | |
| Stage 2 원시 회전(좌/우/U) | ⬜ 시작 전 | |
| Stage 3 노드 감지 | ⬜ 시작 전 | |
| Stage 4 색상코드 노드 판정 | ⬜ 시작 전 | |
| Stage 5 통합(트레이싱+회전) | ⬜ 시작 전 | |
| Stage 6 탐색/복귀 | ⬜ 시작 전 | |
| Stage 7 물체 집기 | ⬜ 시작 전 | |

상태 표기: ⬜ 시작 전 / 🟡 진행 중 / 🟢 실기 Done / 🔴 막힘

## 명세(docs/specs/) 검토 처리 현황

antigravity 검토 보고서(9개 지적)를 claude 가 재검토해 우선순위 재조정 후 반영. 상태 표기는
DRAFT/REVIEWED 2단계(실기 Done 은 명세가 아니라 이 PROGRESS 의 🟢 로 — [specs/README.md](docs/specs/README.md)).

- ✅ **near-term 반영 완료(REVIEWED 승격)**:
  - `00_infra_dashboard.md` — #2 브릭 통신 단일 채널(watcher만 상시접속·3~5Hz, 대시보드는 로컬 파일 읽기).
  - `stage1_linetrace.md` — #4 라인유실 상태전이 순수화(`decide_line`), #8 D항 EMA 필터(내부상수).
- ✅ **해당 스테이지 11절에 검토 메모만 추가(DRAFT 유지, 그 단계 착수 시 반영)**:
  - `stage5` #6 LEAF U턴 강제 / `stage6` #3 복귀 노드패턴 검증·#5 재귀→명시스택 /
    `stage7` #1 초음파 백그라운드 폴링·#7 그리퍼 스톨 보호.
- ⏸ **보류**: #9(pre_uturn 등 미리 라이브 개방) — 6개 규칙상 실기 튜닝이 요구할 때 개방.
- 판정 근거: High 로 분류됐던 #1/#3/#5 는 Stage 6/7(먼 미래 DRAFT)이라 Stage 0/1 을 막지 않음.

## TODO (다음 할 일)

- [ ] **Stage 0 스크립트**: 7개 장치(모터3·센서4) 포트 인식 + 값 읽기 확인.
      `python3 --version` 으로 EV3 Python 버전 확정(stretch=3.5면 f-string 불가).
- [ ] 실기에서 Stage 0 실행, 좌/우 모터 방향 확인.
- [ ] (Stage 1 착수 시) 라이브 튜닝 infra MVP 구현 — `00_infra_dashboard.md`(REVIEWED) 계약대로:
      `lib/` shared_params·telemetry·decision_log·tuning_server·pid + `tools/` robotctl·dashboard·watcher.
- [ ] SSH 포트포워딩 확인: `ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local`.

## 작업 로그 (최신이 위로)

### 2026-06-29 — antigravity 검토 보고서 재검토 + 반영 (Agent: claude)
- antigravity 보고서(9개 지적)를 명세 원문과 대조 검토(#2 통신·#4 Stage1 분리 직접 확인 — 보고서 정확).
- 우선순위 재조정: High 로 표시된 #1/#3/#5 는 Stage 6/7(먼 미래 DRAFT)이라 지금 막지 않음.
  지금 만들 것(인프라+Stage1)에 영향 주는 #2/#4/#8 만 즉시 반영.
- 반영: 00_infra(#2 단일 채널)·stage1(#4 순수전이·#8 EMA) → REVIEWED 승격.
  stage5(#6)·stage6(#3,#5)·stage7(#1,#7) 은 11절에 검토 메모 추가(DRAFT 유지).
- 상태 규약 정리: specs 는 DRAFT→REVIEWED 2단계, 실기 Done 은 PROGRESS 🟢 로 구분
  (보고서의 'APPROVED' 대신 — 실기검증과 의미 분리). specs/README.md 갱신.
- stage1 의 "00_infra 아직 없음" 스테일 문구 수정. 상세 현황은 위 "명세 검토 처리 현황".
- 참고: antigravity 가 남긴 analysis 링크는 `~/.gemini/...` 로컬 경로라 타 환경에선 안 열림.

### 2026-06-29 — 서브에이전트를 활용한 스테이지별 구현 명세 검토 (Agent: antigravity)
- 서브에이전트 3개를 띄워 `00_infra_dashboard.md` 및 `stage0~7` 스펙의 전반을 검증함.
- 핵심 검토 결과를 [analysis_results.md](file:///home/emjdp/.gemini/antigravity/brain/b9afc161-214b-499b-9d0a-29579839fa4b/analysis_results.md) 아티팩트로 작성 완료.
- 주요 지적 사항: 초음파 센서 동기식 읽기로 인한 제어 주기 붕괴 위험(High), 복귀 로직의 노이즈 취약성 및 재귀 구조 우려(High), Stage 1 판단-구동 분리 미흡(Medium) 등.
- **다음**: 지적 사항을 바탕으로 docs/specs/의 DRAFT 문서들을 보완 및 APPROVED 처리 후 Stage 0 실행.

### 2026-06-29 — 스테이지별 구현 명세 작성 (docs/specs/) (Agent: claude)
- 사람 인터페이스를 터미널 TUI 대시보드(`tools/dashboard.py`, curses)로 확정. 눌러서 실행
  + 키로 파라미터 즉석 조정. `robotctl` 은 스크립트/에이전트용 비대화형 CLI 로 병행.
- 서브 에이전트 5개 병렬로 [docs/specs/](docs/specs/) 에 구현 명세 9종 작성(이어받기용 11절 형식):
  00_infra_dashboard, stage0_connection, stage1_linetrace, stage2_turns, stage3_node_detect,
  stage4_color, stage5_integration, stage6_explore_return, stage7_gripper (총 ~3050줄, 모두 DRAFT).
- 검토: 11절 형식 준수, 브릭 코드 f-string 없음, 내부 링크 전부 유효 확인.
- **선행 의존성**: Stage 1 착수 전 `00_infra_dashboard.md` 의 lib/ 계약을 먼저 확정해야 함
  (stage1~3 명세가 이 인프라에 의존). EV3 Python 버전은 Stage 0 에서 확정.
- **다음**: Stage 0 코드 착수(또는 00_infra 명세 리뷰 후 Stage 1 인프라 MVP).

### 2026-06-29 — 판단 기록·재연·빠른 보정 루프 추가 (문서 반영) (Agent: claude)
- 실사용 페인포인트 반영: ① 좌회전 하나에 1시간(느린 반복) ② "왜 그렇게 움직였나" 안 보임
  ③ 오늘의 실패(분기/코너 오버슛, 노드 지나 빈 바닥 색 측정)를 실시간 수정·재연하고 싶음.
- 새 문서 [docs/DECISIONS.md](docs/DECISIONS.md): 판단층↔구동층 분리, reason_code 카탈로그,
  events.jsonl 스키마, 두 실패를 로그로 잡는 법, `robotctl do <action>` 단일 트리거,
  record/replay, "params 6개 이하 + 로그가 짚는 값만" 원칙.
- LIVE_TUNING: 대시보드는 *나중*, do/reason/replay 가 먼저. CLI 에 `do`·`replay.py` 추가.
  빌드순서에 reason logging·replay 끼워넣음.
- STAGES: Stage2(=`do turn_*` 보정 루프), Stage3(`node_advance`+실패#1), Stage4(색읽기 위치
  +실패#2) 반영. Stage1부터 reason_code 기록 명시.
- AGENTS: 판단층 분리·reason 로그·do 트리거·replay 를 코드 규약에 추가.
- README: 문서 목록/라이브튜닝 섹션에 DECISIONS 연결.
- 코드 미작성(문서 단계).

### 2026-06-29 — 라이브 튜닝 구조 채택 (문서 반영) (Agent: claude)
- "EV3=주행 / 노트북=관제소" 라이브 튜닝 구조를 검토·확정해 문서에 반영(코드는 아직).
- 새 문서 [docs/LIVE_TUNING.md](docs/LIVE_TUNING.md): 서버/CLI/telemetry/안전장치/빌드순서/
  에이전트 워크플로우. 핵심 결정: 제어루프↔네트워크 분리, threaded accept, dt 측정,
  telemetry 파일쓰기는 노트북, 회전은 엔코더+보정계수, BACK 1차 정지, 에이전트는 제안만.
- README/STAGES/AGENTS 갱신: 라이브 튜닝을 "스테이지가 아닌 공용 도구"로 못박고
  단계와 함께 자라게. 목표 디렉토리(lib/tools/config/runs/dashboard) 반영. `runs/` gitignore.
- **다음**: Stage 0 스크립트(여전히 plain 연결확인, 네트워크 없음).

### 2026-06-29 — 프로젝트 초기 세팅 (Agent: claude)
- 단계별 재구축 구조로 새 프로젝트 디렉토리(`ev3test`) 세팅.
- 공용 문서 작성: README.md(공용 설명), AGENTS.md(에이전트 규칙),
  CLAUDE.md / GEMINI.md(전용 포인터), docs/HARDWARE.md, docs/STAGES.md, 이 PROGRESS.md.
- 이전 구현(`ev3maze/robot`)에서 검증된 포트 배선만 가져옴. 거대 config 는 버리고
  단계별 독립 스크립트 방식 채택.
- git 로컬 저장소 초기화, 초기 커밋.
- **다음**: Stage 0 스크립트.
