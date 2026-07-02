# 구현 명세 (specs/) — 이어받아 작업하기 위한 형식

이 폴더는 각 스테이지/인프라의 **구체적 구현 명세**를 담는다. 목적은 *어느 에이전트
(claude/codex/gemini/antigravity)나 사람이든 이 문서 하나로 그 단계를 구현할 수 있게* 하는 것.

상위 규칙은 [../../AGENTS.md](../../AGENTS.md), 단계 통과기준은 [../STAGES.md](../STAGES.md),
라이브 튜닝/대시보드 구조는 [../LIVE_TUNING.md](../LIVE_TUNING.md), 판단기록/재연은
[../DECISIONS.md](../DECISIONS.md), 배선은 [../HARDWARE.md](../HARDWARE.md).

> 명세는 **계획**이다. 명세 상태는 3단계로 표기한다(파일 맨 위 `> 상태:`):
> - `DRAFT` — 작성됨, 설계 검토 전.
> - `REVIEWED` — 설계 검토 완료, **구현 착수 가능**(아직 실기 미검증).
> - 실기 검증(코드가 실기에서 Done)은 명세 상태가 아니라 [../../PROGRESS.md](../../PROGRESS.md)
>   의 🟢 로 구분한다. (즉 명세는 "실기 Done" 상태를 갖지 않는다.)
>
> 명세대로 구현이 끝나고 실기 Done 이면 PROGRESS 에 반영한다. 명세와 실제 구현이
> 어긋나면 **명세를 고쳐** 최신으로 유지한다.

## 파일 목록

| 파일 | 내용 |
|---|---|
| [00_infra_dashboard.md](00_infra_dashboard.md) | 라이브 튜닝 인프라 + 터미널 TUI 대시보드 + record/replay (Stage 1과 함께 등장) |
| [stage0_connection.md](stage0_connection.md) | 연결/포트 확인, EV3 Python 버전 확정 |
| [stage1_linetrace.md](stage1_linetrace.md) | 기초 라인트레이싱 + 인프라 MVP 최초 통합 |
| [stage2_turns.md](stage2_turns.md) | 좌90/우90/U턴 (엔코더+보정계수, `do` 보정 루프) |
| [stage3_node_detect.md](stage3_node_detect.md) | ⚠️ 폐기(2026-07-02, 아날로그 centroid 트랙, 코드 미착수) — stage3v2 로 대체됨 |
| [stage3v2_linetrace_branch.md](stage3v2_linetrace_branch.md) | **공식 Stage 3**(2026-07-02 채택). only_linetrace 기반 라인추종 + 분기 **탱크 회전**(`lib/turns.pivot` 재사용, factor 90°, 회전 시점 튜닝) |
| [stage3v3_anchor_pivot_idea.md](stage3v3_anchor_pivot_idea.md) | DRAFT 아이디어 메모. stage3v2 의 사전 회전 보상 편법을 나중에 제거하기 위한 후보 위치(anchor)+확정 후 보정 구상(구현 의무 없음) |
| [stage4_color.md](stage4_color.md) | 색상코드 노드 판정, 색 읽기 위치, 실패#2 대응 — 공통 부품(모드 전환·ColorConfirmer·COLOR_* reason)의 기준 문서 |
| [stage4a_reflect_only.md](stage4a_reflect_only.md) | Stage 4 **브릿지 후보 A** — 반사광 단독 노드색 판정(노드별 반사광 대역 + 유지시간, 컬러 전환 0회) |
| [stage4b_suspect_backup_color.md](stage4b_suspect_backup_color.md) | Stage 4 **브릿지 후보 B** — `010`→`000` 의심지점에서만 컬러 전환 + 후진 판독(막다른 길 마커) |
| [stage4c_reflect_gate_color.md](stage4c_reflect_gate_color.md) | Stage 4 **브릿지 후보 C(기본 권장)** — 반사광 의심대역 게이트 + 컬러 모드 확정(A+B 결합) |
| [stage4d_mode_interleave.md](stage4d_mode_interleave.md) | Stage 4 **브릿지 후보 D** — 반사광↔컬러 고속 교대(구현 전 `do bench_toggle` go/no-go 관문) |
| [stage5_integration.md](stage5_integration.md) | 라인트레이싱 + 노드 분기 회전 통합 |
| [stage6_explore_return.md](stage6_explore_return.md) | 탐색/복귀 알고리즘 |
| [stage7_gripper.md](stage7_gripper.md) | 초음파 + 그리퍼 물체 집기 |

## 명세 작성 형식 (모든 spec 파일이 따른다)

각 spec 파일은 아래 11개 절을 순서대로 채운다. 칸을 못 채우면 "미정"이라고 쓰고
11절(미해결 질문)에 옮긴다. **추측을 사실처럼 쓰지 않는다.**

```markdown
# Stage N — <이름> 구현 명세

> 상태: DRAFT (실기 미검증)
> 선행: <먼저 Done 이어야 하는 스테이지/인프라>
> 통과기준(Done): STAGES.md 의 해당 단계 인용

## 1. 목표 / 범위
- 이 단계가 하는 것 / 명시적으로 안 하는 것(다음 단계로 미루는 것).

## 2. 파일 / 인터페이스
- 새로 만들/수정할 파일 경로.
- 판단층(순수 함수)과 구동층(ev3dev2) 분리: 주요 함수 시그니처와 입출력.
  예) `decide_node(bits, params, state) -> (action, reason_code, detail)`

## 3. 라이브 params (6개 이하)
- 이름 / 의미 / 기본값 / PARAM_LIMITS(min,max) / MAX_STEP / 어떤 증상일 때 올리고 내리나.
- 표로. 6개 초과면 무엇을 config/ 에 묻을지 명시.

## 4. telemetry 필드 / reason_code
- 이 단계가 추가하는 telemetry 키, events 의 새 reason_code(detail 포함). DECISIONS.md 카탈로그와 일치.

## 5. 동작 로직 (의사코드)
- 제어 루프 / 판단 함수 / 구동 동작을 의사코드로. EV3 코드는 Python 3.5 안전(f-string 금지).
- BACK 버튼은 프로그램 입력으로 할당하지 않고, 정지는 네트워크 stop/키보드 인터럽트/필요 시
  별도 안전 입력으로 처리한다. 네트워크 비차단(snapshot) 포함.

## 6. 대시보드 / CLI 연동
- 이 단계에서 누를 수 있는 동작(`do <action>`)과 조정 가능한 키/파라미터.

## 7. 보정 절차 (실기, 한 번에 변수 하나)
- 무슨 순서로 어떤 값을 어떻게 맞추는지. 측정 → 조정 → 재현 루프.

## 8. 실패 모드 & 진단
- 알려진/예상 실패와, 로그(어떤 필드)로 원인을 어떻게 짚고 어떤 값을 고치는지.

## 9. PC 검증
- `python3 -m py_compile`, 판단 함수 단위 테스트/재연(`replay.py`) 시나리오.

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)
- [ ] 순서대로 체크 가능한 작업 항목.

## 11. 미해결 / 실기 확인 필요
- 가정, 확정 안 된 값, 실기로만 알 수 있는 것.
```

## 작성 규칙

- **한국어**, 기존 문서 톤.
- EV3(브릭)에서 도는 코드는 **Python 3.5 안전**(`.format()`, f-string 금지). 노트북 도구는 최신 OK.
- 이전 구현 참고 원본: `/home/emjdp/dev/ev3maze/robot` (검증된 값/구조만 골라 인용, 그대로 복사 금지).
- 명세끼리 중복 설명 말고 **상호 링크**한다(인프라 내용은 00_infra_dashboard.md 를 가리킴).
