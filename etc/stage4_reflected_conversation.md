# Stage 4 reflected 대화 정리

작성일: 2026-07-06

이 문서는 2026-07-03 Stage 4 reflected 색상 노드 판정 작업 중 오간 대화를,
다음 작업자가 빠르게 이어받을 수 있도록 정리한 기록이다. 원문 복사본의 UI 잡음과
반복 문구는 줄이고, 판단 흐름과 확정값 중심으로 다듬었다.

## 최종 결론

- 공식 Stage 4 트랙은 `stages/stage4_clolor_reflected.py` 이다.
- 보라색 노드는 EV3 색상코드에 안정적인 값이 없어서 RGB-RAW 비율로 직접 판정한다.
- 빨간색 노드는 반사광 후보 범위로 1차 필터링한 뒤 EV3 색상코드 `COLOR_RED(5)`로 확정한다.
- 갈색 판정은 제거했다.
- 색상 노드를 확정하면 부저 1번 후 자동 180도 U턴을 수행하고, 다시 라인트레이싱을 이어간다.
- 사용자가 아래 튜닝값으로 Stage 4 Done을 선언했다.

## 작업 흐름

### 1. 색상 인식 후 자동 180도 U턴 추가

요청:

- 기존에는 부저 1번으로 색상 인식 여부를 잘 확인하고 있었다.
- 해당 색으로 모든 노드를 만들 예정이므로, 색상을 인식하면 180도 회전하게 해 달라고 요청했다.
- 노드를 찍고 다시 돌아서 계속 라인트레이싱할 수 있게 기존 180도 회전 코드를 사용하기로 했다.

반영:

- 색 마커 인식 성공 시 자동 U턴을 수행하도록 `stage4_clolor_reflected.py`를 수정했다.
- 기존 색 인식 부저 1번은 유지했다.
- U턴 완료 부저는 막아서 인식 신호와 헷갈리지 않게 했다.
- `MARKER_UTURN` reason log를 추가했다.

관련 커밋:

- `796c3ba Stage4: 색 마커 인식 후 자동 U턴 추가`

### 2. 의심 반사광 안정 시간 제거

요청:

- 기존에는 의심 반사광 값이 0.01초 이상 유지되어야 색상센서를 켰다.
- 실기에서는 조건 없이 의심 반사광이 보이면 바로 색상센서를 켜는 쪽이 맞겠다고 판단했다.

반영:

- 의심 반사광 범위에 들어온 첫 틱에서 바로 정지하고 색상/RGB-RAW 센서를 읽게 했다.
- `marker_stable_ms`는 저장된 기존 params 호환 때문에 남겼지만, 판단에는 쓰지 않도록 했다.

관련 커밋:

- `196ff9b Stage4: 의심 반사광 즉시 색상 읽기`

### 3. 갈색 색상코드 판정 시도

요청:

- 직접 분석하던 RGB/RGB-RAW 값 대신, EV3 색상센서에 있는 `brown` 값이 안정적이니
  갈색이면 노드로 판단하도록 바꾸자는 요청이 있었다.

반영:

- 의심 반사광 감지 후 중앙 색상센서 color code를 읽었다.
- majority 결과가 `COLOR_BROWN(7)`이면 노드로 확정했다.
- brown이면 부저 1번 후 자동 180도 U턴을 수행했다.
- 이 방식은 이후 방향이 바뀌면서 최종 트랙에서는 제거됐다.

관련 커밋:

- `1fb865b Stage4: brown 색상코드만 노드로 판단`

### 4. 보라 RGB 판정 + 빨강 색상코드 판정으로 재구성

요청:

- 갈색 판단을 지우고, 보라색 반사광 의심값만 남겨 보라색 판단으로 되돌리기로 했다.
- 빨간색도 추가했다.
- 빨간색 반사광은 약 79, 흰색은 약 68이므로 흰색과 겹치지 않게 후보 범위를 잡기로 했다.
- 빨간색은 EV3 색상센서에 데이터값이 있으므로 색상코드로 확인한다.
- 보라색은 색상센서 코드가 없으므로 직접 RGB 값을 기준으로 판정한다.

반영:

- 갈색 후보 및 판정 로직을 제거했다.
- 보라색 후보: 반사광 후보 범위 진입 후 RGB-RAW 비율로 확정.
- 빨간색 후보: 반사광 후보 범위 진입 후 EV3 색상코드 `COLOR_RED(5)` majority로 확정.
- 보라/빨강 확정 시 부저 1번 후 자동 180도 U턴을 수행한다.
- 기본 빨강 후보 범위는 흰색 68, 노랑 70과 겹치지 않도록 잡았다.

관련 커밋:

- `bb266bb Stage4: 보라 RGB와 빨강 색상코드 노드 판정`
- `5b9c638 Stage4 reflected 색상 노드 판정 반영`

## 보라색 인식 실패 시 판단 기준

실기에서 의심 지점은 인식하는데, 보라색을 찍고도 보라색으로 확정하지 못한 상황이 있었다.
이때는 반사광 후보 범위보다 RGB 비율 판정 조건을 먼저 확인한다.

보라 판정 조건의 핵심:

```text
red_ratio >= purple_red_ratio_min
blue_ratio >= purple_blue_ratio_min
green_ratio <= purple_green_ratio_max
```

해석:

- `purple_red_ratio_min`을 낮추면 빨강 비율이 낮은 보라도 더 많이 보라로 인정한다.
- `purple_blue_ratio_min`을 낮추면 파랑 비율이 낮은 보라도 더 많이 보라로 인정한다.
- `purple_green_ratio_max`를 높이면 초록 비율이 섞여 보이는 보라도 더 많이 보라로 인정한다.

확인할 telemetry/detail:

```bash
python3 tools/robotctl.py latest
```

또는 `runs/current/latest_state.json`에서 아래 값을 확인한다.

- `candidate_kind`
- `marker`
- `marker_source`
- `rgb`
- `rgb_ratio`

판단 예시:

- `candidate_kind: "purple"`인데 `marker: null`이면 반사광 후보는 잡혔지만 RGB 판정에서 실패한 것이다.
- `rgb_ratio`가 `(0.38, 0.34, 0.28)`처럼 나오면 대체로 보라 판정에 유리하다.
- green 비율이 높아 탈락하면 `purple_green_ratio_max`를 올린다.
- blue 비율이 낮아 탈락하면 `purple_blue_ratio_min`을 낮춘다.
- red 비율도 낮으면 `purple_red_ratio_min`을 낮춘다.

튜닝은 한 번에 하나만 바꾼다.

## 최종 확정 params

사용자가 브릭에서 `robotctl save` 완료를 확인했고, 로컬
`config/stage4_clolor_reflected.json`에도 미러링한 값이다.

| param | value | 메모 |
|---|---:|---|
| `turn_90_factor` | 0.66 | Stage 3 v2 기반 회전값 |
| `branch_confirm_count` | 2 | Stage 3 v2 기반 |
| `branch_advance_mm` | 30 | Stage 3 v2 기반 |
| `marker_candidate_min` | 21 | 보라 후보 반사광 하한 |
| `marker_candidate_max` | 32 | 보라 후보 반사광 상한 |
| `red_candidate_min` | 73 | 빨강 후보 반사광 하한 |
| `red_candidate_max` | 86 | 빨강 후보 반사광 상한 |
| `marker_stable_ms` | 0 | 후보 즉시 색/RGB 읽기 |
| `marker_cooldown_ms` | 1000 | 중복 인식 방지 |
| `marker_sample_count` | 3 | 색/RGB 샘플 수 |
| `marker_sample_delay_ms` | 1 | 샘플 간 대기 |
| `color_mode_settle_ms` | 10 | 모드 전환 settle |
| `color_dummy_reads` | 1 | 전환 직후 더미 읽기 |
| `purple_red_ratio_min` | 0.20 | 보라 RGB 판정 |
| `purple_blue_ratio_min` | 0.23 | 보라 RGB 판정 |
| `purple_green_ratio_max` | 0.42 | 보라 RGB 판정 |

## 업로드 및 실행 명령

Stage 4 코드를 브릭에 다시 올릴 때:

```bash
ssh robot@ev3dev.local 'mkdir -p ~/ev3test/stages ~/ev3test/lib ~/ev3test/tools ~/ev3test/config'
scp stages/stage4_clolor_reflected.py stages/stage3v2_linetrace_branch.py robot@ev3dev.local:~/ev3test/stages/
scp lib/*.py robot@ev3dev.local:~/ev3test/lib/
scp tools/*.py robot@ev3dev.local:~/ev3test/tools/
scp config/stage4_clolor_reflected.json robot@ev3dev.local:~/ev3test/config/
```

브릭 실행 터미널:

```bash
ssh robot@ev3dev.local
cd ~/ev3test
python3 stages/stage4_clolor_reflected.py
```

SSH 터널 터미널:

```bash
ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local
```

telemetry watcher 터미널:

```bash
python3 tools/telemetry_watcher.py --stage stage4_clolor_reflected
```

dashboard/robotctl 터미널:

```bash
python3 tools/robotctl.py latest
python3 tools/robotctl.py do read_marker
python3 tools/robotctl.py do uturn
python3 tools/robotctl.py stop
```

## 관련 파일

- `stages/stage4_clolor_reflected.py`
- `tests/test_stage4_clolor_reflected_logic.py`
- `config/stage4_clolor_reflected.json`
- `docs/DECISIONS.md`
- `PROGRESS.md`
