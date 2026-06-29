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

## TODO (다음 할 일)

- [ ] Stage 0 스크립트 작성: 7개 장치(모터3·센서4) 포트 인식 + 값 읽기 확인.
- [ ] 실기에서 Stage 0 실행, 좌/우 모터 방향 확인.
- [ ] Stage 0 Done 후 Stage 1(기초 라인트레이싱) 착수.

## 작업 로그 (최신이 위로)

### 2026-06-29 — 프로젝트 초기 세팅 (Agent: claude)
- 단계별 재구축 구조로 새 프로젝트 디렉토리(`ev3test`) 세팅.
- 공용 문서 작성: README.md(공용 설명), AGENTS.md(에이전트 규칙),
  CLAUDE.md / GEMINI.md(전용 포인터), docs/HARDWARE.md, docs/STAGES.md, 이 PROGRESS.md.
- 이전 구현(`ev3maze/robot`)에서 검증된 포트 배선만 가져옴. 거대 config 는 버리고
  단계별 독립 스크립트 방식 채택.
- git 로컬 저장소 초기화, 초기 커밋.
- **다음**: Stage 0 스크립트.
