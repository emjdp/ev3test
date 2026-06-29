# PROGRESS — 진행 상황 + TODO

모든 에이전트가 공통으로 기록한다. **작업 후 반드시 갱신·커밋.**
규칙은 [AGENTS.md](AGENTS.md), 단계 정의는 [docs/STAGES.md](docs/STAGES.md).

## 현재 단계

**Stage 0 — 연결/포트 확인** (코드 작성됨, 실기 검증 대기)

## 단계 상태판

| 단계 | 상태 | 비고 |
|---|---|---|
| Stage 0 연결/포트 확인 | 🟡 진행 중 | 코드 작성·py_compile 통과, 실기 검증 필요 |
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

- [x] **Stage 0 스크립트 작성**: `stages/stage0_check.py` (py_compile 통과, f-string 없음). [claude]
- [ ] **실기에서 Stage 0 실행** (`python3 stages/stage0_check.py`):
      ① `python` 버전 → PROGRESS 기록(3.5 여부 확정) ② 7개 포트 OK + 센서값 sanity
      ③ 좌/우 모터 방향(기대와 다르면 "다름"만 기록, 수정은 Stage 1). → Done 이면 🟢.
- [x] **인프라 MVP 빌드 — codex 담당.** 스테이지가 아닌 공용 도구라 지금 만들 수
      있다. 명세: [00_infra_dashboard.md](docs/specs/00_infra_dashboard.md) (REVIEWED).
      - 완료(하드웨어 무관, PC 검증): `lib/` shared_params·telemetry·decision_log·
        tuning_server·pid + `tools/` robotctl(get/set/stop/do/save/rollback/latest)·
        최소 dashboard·watcher·replay.
      - 확장 완료(하드웨어 무관, PC 검증): `describe` 계약(stage/params/actions), params
        UI 메타(step/unit), data-driven dashboard, 액션 반복/자동 재실행/coarse step.
      - `lib/hardware.py` 는 **Stage 0 실기 Done 후** (모터 극성·트림 결과 필요).
      - ⚠️ **MVP 한정**: 무거운 대시보드(그래프/자동튜닝)는 금지(LIVE_TUNING.md). py_compile + PC 테스트.
- [ ] (이후) **Stage 1~7 은 한 번에 하나씩**, 각 이전 단계 **실기 Done 후**에만 착수.
      ⚠️ 1~7 일괄 작성 금지(AGENTS.md 1절). 담당은 **codex·claude 협업/교대**(둘이 번갈아 또는 공동).
- [ ] (Stage 1 착수 시) 인프라 MVP를 Stage 1 제어 루프에 통합해 실기 검증:
      watcher 단일 polling, dashboard 로컬 파일 렌더, `robotctl set/do/stop`, save/rollback 확인.
- [ ] SSH 포트포워딩 확인: `ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local`.

## 작업 로그 (최신이 위로)

### 2026-06-30 — 브릭 실행 코드 내 UnicodeEncodeError 방지를 위한 한글 제거 (Agent: antigravity)
- 수정 내용: `stages/stage0_check.py` 내의 모터/센서 레이블 및 `print()` 한글 출력 문자열을 모두 영어(ASCII)로 전환. `lib/tuning_server.py` 내의 `_demo()` 데모 코드 한글 레이블을 영어로 전환.
- 배경: ev3dev OS의 기본 로케일(Locale)이 UTF-8이 아닌 환경(ASCII 등)에서 실행 시 `print` 속 한글로 인해 `UnicodeEncodeError` 크래시가 발생하는 것을 방지.
- **실기 검증 필요**: 브릭에서 `stage0_check.py` 실행 시 영어 출력 및 동작 정상 여부 확인 필요.

### 2026-06-30 — 인프라 describe + data-driven 대시보드 확장 (Agent: codex)
- `SharedParams` 에 `ui_step`/`units`/`param_order` 메타와 `describe()` 를 추가해
  value/min/max/step/max_step/unit 을 서버가 그대로 노출할 수 있게 했다(기존 생성자 호출은 유지).
- `TuningServer` 에 `{"cmd":"describe"}` 를 추가하고, `stage` + actions manifest 주입을
  지원했다. 데모 서버는 PC 단독 테스트용 params/actions 를 반환한다.
- `tools/dashboard.py` 를 describe 기반으로 변경: params 행과 action 키를 동적으로 구성하고,
  `1..` 액션 실행, `Space`/`.` 마지막 액션 반복, `a` 자동 재실행, `c` coarse step 을 지원한다.
  상태/이벤트는 계속 `runs/current/latest_state.json` 을 읽고, 키 입력 때만 서버 명령을 보낸다.
- `tools/robotctl.py describe` 를 추가했다. `docs/specs/00_infra_dashboard.md` 는 REVIEWED 상태를
  유지하며 describe 스키마·data-driven 대시보드·step/max_step 메타를 반영했다.
- PC 검증: `python3 -m py_compile lib/*.py tools/*.py`, `lib/` f-string 없음 확인, shared_params/
  tuning_server self-test, 데모 서버 `describe/set/do`, dashboard `--once`, 키 핸들러 smoke
  (액션 키/반복/자동 재실행/coarse 거부), watcher 1회 기록 후 렌더 확인. **실기 검증 필요**:
  Stage 1/2 통합 때 브릭 부하·SSH 터널·회전 보정 루프 체감을 확인한다.

### 2026-06-30 — 인프라 MVP 구현 + PC 통합 검증 (Agent: codex)
- `lib/` 코어 구현: `SharedParams`(범위/스텝 거부, rev, save/rollback), `Telemetry`,
  `DecisionLog`, dt 측정값 기반 `Pid`(D항 EMA), threaded newline-JSON `TuningServer`
  (`get/set/stop/do/save/rollback/get_latest`, 깨진 JSON 라인 복구, 데모 서버).
- `tools/` 구현: 비대화형 `robotctl.py`, watcher(`runs/<ts>/` 기록 +
  `runs/current/latest_state.json`), curses MVP `dashboard.py`(브릭 직접 polling 없이 로컬 상태 파일
  렌더, 키 입력 시에만 명령 전송), `replay.py` 스켈레톤(stub/plug-in decide).
- PC 검증: `python3 -m py_compile lib/*.py tools/*.py stages/*.py`, lib self-test,
  데모 서버로 `robotctl get/set/do/stop/latest`, watcher 기록/param diff, dashboard `--once`
  렌더 및 키→명령 경로, replay stub 실행 통과. `lib/` f-string 없음 확인.
- 범위 준수: `stages/`, `lib/hardware.py`, `docs/specs/*` 수정 없음. **실기 검증 필요**:
  인프라 자체 Done 은 없고, Stage 1 라인트레이싱 통합 때 SSH 터널/브릭 부하/stop/save/rollback 을 확인한다.
- 다음: Stage 0 실기 검증 → Stage 1 착수 시 인프라 통합.

### 2026-06-30 — 소유권/순서 정리: 인프라는 codex, 스테이지는 일괄 금지 (Agent: claude)
- 확인: Stage 1~7 코드를 미리 일괄 작성하는 것은 금지(AGENTS.md 1절). codex 가 "나머지"를
  맡되 **단계별로 하나씩, 이전 단계 실기 Done 후**. claude 의 이전 "codex가 1~7" 표현이
  batch 로 읽힐 소지가 있어 바로잡음.
- "미리 만들 수 있는 것"은 스테이지가 아니라 **인프라/대시보드 도구**(공용 도구라 규칙 대상 아님,
  PC 단위테스트 가능). → **인프라 MVP 빌드를 codex 에 배정**(다음 작업). MVP 한정.
- 이후 Stage 1~7 은 **codex·claude 협업/교대**로 진행하기로 결정.
- claude 는 현재 추가 빌드 없음(인프라/스테이지 모두 codex 시작). Stage 0 실기 검증 대기.

### 2026-06-29 — Stage 0 스크립트 구현 (Agent: claude)
- `stages/stage0_check.py` 작성(명세 docs/specs/stage0_connection.md 기반).
- 모터3(outA/outB/outC)·센서4(in1~in4) 포트 probe + 값 1회 읽기, 좌/우 forward nudge
  (15%/400ms, ENTER 로 시작·BACK 즉시중단), python 버전 출력, OK/FAIL 요약.
- Python 3.5 안전(f-string 없음, .format()), ev3dev2 는 main() 안 import → PC py_compile 통과.
- 한 포트 실패해도 나머지 계속 점검(try/except per device). position 읽기 예외도 감쌈.
- **실기 검증 필요**: 브릭에서 실행해 버전·7포트·방향 확인 후 PROGRESS 기록 → Done.
- 나머지 스테이지(1~7)는 codex 담당 예정.

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
