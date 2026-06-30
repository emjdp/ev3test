# Infra — 라이브 튜닝 + 터미널 TUI 대시보드 + record/replay 구현 명세

> 상태: REVIEWED (설계 검토 완료, 실기 미검증) — 검토 반영: 통신 단일 채널화(#2, 6.1절).
> 선행: Stage 0 (EV3 Python 버전 확정 — 3.5 면 f-string 금지 확정). 인프라는 Stage 1 과
> **동시에** 최초 등장하지만, 인프라 자체는 스테이지가 아니라 **공용 도구(infra)** 다.
> 통과기준(Done): 이 인프라는 단독 "Done" 이 없다. **Stage 1 라인트레이싱을 노트북에서
> 라이브로 튜닝해 실기 Done 까지 끌고 갈 수 있으면** 인프라 MVP 가 제 역할을 한 것이다
> ([STAGES.md](../STAGES.md) Stage 1, [LIVE_TUNING.md](../LIVE_TUNING.md) 빌드순서 1~5).

이 문서는 `lib/` (브릭) + `tools/` (노트북) 으로 나뉜 라이브 튜닝 인프라의 구현 계획이다.
배경·기술결정·안전원칙은 [LIVE_TUNING.md](../LIVE_TUNING.md), 판단기록/재연 철학은
[DECISIONS.md](../DECISIONS.md), 배선은 [HARDWARE.md](../HARDWARE.md) 에 있다.
**여기서는 중복 설명을 피하고 "무엇을 어떤 인터페이스로 만드는가"만 구체화**한다.
각 스테이지 spec(`stage1_linetrace.md` 등)은 params/telemetry/reason_code 만 늘리고
공통 동작은 이 문서를 가리킨다.

> **Python 버전 규칙(절대)**: `lib/` 와 `stages/` 는 **EV3(브릭)에서 돈다 → Python 3.5
> 안전**. f-string 금지, `.format()` 사용, type hint 변수표기 금지(주석으로). `tools/` 는
> **노트북에서 돈다 → 최신 문법 OK**(f-string, dataclass, type hint 자유). 이 명세의
> 의사코드도 이 구분을 지킨다(`lib/` 의사코드엔 f-string 안 씀).

---

## 1. 목표 / 범위

### 하는 것 (인프라 MVP, Stage 1 과 함께)
- 제어 루프를 **절대 블록하지 않는** 스레드 안전 params 저장소(`lib/shared_params.py`).
- 최신 telemetry 프레임 1개 보관(`lib/telemetry.py`).
- reason_code 이벤트 기록 인터페이스 + **판단층↔구동층 분리**(`lib/decision_log.py`).
- 연결당 thread 로 도는 TCP newline-JSON 튜닝 서버(`lib/tuning_server.py`),
  명령 `get/set/stop/do/save/rollback/get_latest`, `127.0.0.1` bind.
- dt 를 측정값으로 쓰는 PID(`lib/pid.py`).
- 비대화형 CLI(`tools/robotctl.py`) — 스크립트·에이전트용.
- stdlib `curses` 터미널 TUI 대시보드(`tools/dashboard.py`) — 사람용.
- telemetry/이벤트/params 를 노트북 `runs/<ts>/` 에 기록(`tools/telemetry_watcher.py`).
- 기록한 samples 를 판단층에 재연(`tools/replay.py`).

### 명시적으로 안 하는 것 (다음으로 미룸)
- **무거운 웹 대시보드(Streamlit/실시간 그래프)** — 한참 뒤([LIVE_TUNING.md](../LIVE_TUNING.md) 빌드순서 8).
- **자동 튜닝/에이전트 자동 set** — 당분간 안 함. 에이전트는 *제안만*
  ([LIVE_TUNING.md](../LIVE_TUNING.md) "에이전트 워크플로우": 1단계 고정).
- 스테이지별 구체 params/telemetry/판단 로직 — 각 스테이지 spec 소관. 여기선 *그릇*만 만든다.
- 인증/암호화 — `127.0.0.1` bind + SSH 터널로 대체(아래 7절).

---

## 2. 파일 / 인터페이스

### 디렉토리
```
ev3test/
  lib/                # 브릭 (Python 3.5 안전)
    shared_params.py
    telemetry.py
    decision_log.py
    tuning_server.py
    pid.py
    hardware.py       # (Stage 0/1 에서 만듦; 인프라가 import 만 함, 본 명세 범위 아님)
  tools/              # 노트북 (최신 문법 OK)
    robotctl.py
    dashboard.py
    telemetry_watcher.py
    replay.py
  config/             # save 된 검증값 (git 추적). 예: config/stage1.json
  runs/               # 기록 (git 추적 안 함). runs/<ts>/{samples,events}.jsonl, params.json
```

### 판단층 ↔ 구동층 분리 (DECISIONS.md 0장)
- **판단층(pure)**: 하드웨어 없음. `decide_*(sensors, params, state) -> (action, reason_code, detail)`.
  각 스테이지 spec 이 자기 `decide_*` 를 정의한다(Stage 1 은 `decide_line(...)`).
  PC 에서 import 만으로 테스트/재연 가능. `replay.py` 가 바로 이 함수를 호출한다.
- **구동층(ev3dev2)**: `lib/hardware.py` + 각 스테이지 제어 루프. 판단 결과(action)를
  모터/센서 실제 동작으로 옮긴다.
- 인프라(`lib/`)는 둘 사이의 **배선**(params 전달, telemetry 수집, event 기록, 명령 수신)을
  담당하고 판단/구동 어느 쪽 로직도 갖지 않는다.

### 주요 인터페이스 (시그니처 — `lib/` 는 3.5 안전)

`lib/shared_params.py`
```text
class SharedParams:
    __init__(self, defaults, limits, max_step, save_path,
             ui_step=None, units=None, param_order=None)
        # dict, dict{name:(min,max)}, dict{name:step}, str,
        # dict{name:ui_step}, dict{name:unit}, [name,...]
    snapshot(self) -> dict        # 락 잡고 얕은 복사 반환 (제어 루프가 매 틱 호출)
    get(self, name)               # 단일 값
    rev(self) -> int              # param_rev (변경 카운터, 단조 증가)
    describe(self) -> list        # value/min/max/step/max_step/unit 메타 배열
    set(self, name, value) -> (ok: bool, msg: str)   # 범위/스텝 검증 후 반영, 거부 시 ok=False
    save(self) -> (ok, msg)       # 현재 값을 save_path(JSON)에 기록
    rollback(self) -> (ok, msg)   # save_path 의 마지막 저장값으로 되돌림(없으면 defaults)
    load_saved_into_defaults(self)# 시작 시 save_path 있으면 그 값으로 출발(선택)
```

`lib/telemetry.py`
```text
class Telemetry:
    __init__(self)
    publish(self, frame)   # 제어 루프가 매 틱: dict 한 개를 최신값으로 교체(락)
    latest(self) -> dict   # 네트워크 thread 가 읽음(락, 복사)
```

`lib/decision_log.py`
```text
class DecisionLog:
    __init__(self, telemetry=None, sink=None)
    log(self, event, reason, **detail)   # event=reason_code(대문자), reason=짧은 코드, detail=키값
                                         # t_ms 자동 부여. sink(소켓/콜백)로 흘려보냄.
    # 판단층은 (action, reason_code, detail) 만 반환하고,
    # 구동층(제어 루프)이 그 결과로 log() 를 호출한다(판단층은 I/O 안 함).
```

`lib/pid.py`
```text
class Pid:
    __init__(self, kp, ki, kd, out_limit)
    reset(self)
    update(self, error, dt) -> float     # dt 는 호출자가 측정해 넘긴다(가정 금지)
    set_gains(self, kp, ki, kd)          # 라이브 변경 반영
```

`lib/tuning_server.py`
```text
class TuningServer:
    __init__(self, params, telemetry, host="127.0.0.1", port=8765,
             do_handler=None, stop_handler=None, actions=None, stage="")
    start(self)   # accept thread 시작(데몬). 연결마다 핸들러 thread.
    stop(self)
    # do_handler(action, args) -> dict  : 단일 동작 큐잉/실행 결과(구동층이 제공)
    # stop_handler(source) -> None      : 네트워크 정지(구동층이 제공)
    # actions: [{"name","label"}, ...]  : 이 스테이지가 노출하는 do 액션 목록(describe 가 반환)
    # stage:   현재 스테이지 이름(describe 가 반환)
    # describe 명령은 params 메타데이터(SharedParams)+actions+stage 를 합쳐 응답한다(6.1 절).
```

---

## 3. 라이브 params (인프라 관점)

> 인프라는 *특정* params 를 정의하지 않는다. **각 스테이지 spec 이 자기 params dict +
> PARAM_LIMITS + MAX_STEP (+ 대시보드용 UI_STEP/UNIT) 를 정의**하고, 그것을
> `SharedParams(defaults, limits, max_step, save_path, ui_step=None, units=None)` 에
> 주입한다. 여기서는 **그릇의 규칙**만 명세한다. (Stage 1 의 실제 6개 값은
> [stage1_linetrace.md](stage1_linetrace.md) 와 [LIVE_TUNING.md](../LIVE_TUNING.md) "Stage 1" 참조.)

| 규칙 | 내용 |
|---|---|
| 개수 | 한 스테이지 라이브 노출 **6개 이하**. 나머지는 `config/` 에 묻음(상수). |
| PARAM_LIMITS | `{name: (min, max)}`. 범위 밖은 **거부**(클램프 아님, 에러 응답). |
| MAX_STEP | `{name: step}`. `abs(new - old) > step` 이면 거부(한 번에 큰 변화 방지). 정의 없으면 제한 없음. |
| 미정의 키 | limits 에 없는 이름은 `set` 거부(오타·미노출 값 보호). |
| param_rev | `set` 성공 시 +1. samples 에 같이 적어 "어느 값으로 찍힌 telemetry 인지" 추적. |
| save/rollback | `set` 은 메모리(현재 주행)만. `save` 가 `config/<stage>.json` 에 검증값 박음. `rollback` 은 마지막 save 로 복귀. |
| UI_STEP/UNIT | (대시보드 전용) `{name: step}` = +/- 한 칸 증분, `{name: unit}` = 표시 단위(선택). 안전과 무관, 표시·조작용. 미정의면 step 은 합리적 기본(예 MAX_STEP/10), unit 은 공백. |
| describe 노출 | 위 메타데이터(value·min·max·max_step·step·unit)를 `describe` 가 그대로 반환 → 대시보드가 이걸로 UI 를 자동 구성(하드코딩 X). |

예시(LIMITS/STEP 형식만 — 값은 LIVE_TUNING.md 기술결정/Stage 1 에서 확정):
```text
limits   = {"kp": (0.0, 3.0), "kd": (0.0, 1.0), "base_speed": (5, 45), ...}
max_step = {"kp": 0.1, "kd": 0.05, "base_speed": 5, ...}
```

---

## 4. telemetry 필드 / reason_code (인프라 공통)

### telemetry (프레임 = dict, 매 틱 1개로 교체)
인프라가 **항상** 넣는 공통 키 + 스테이지가 추가하는 키.

| 키 | 의미 | 누가 |
|---|---|---|
| `t_ms` | 부팅 후 경과(ms) | 인프라 |
| `dt_ms` | 직전 틱 측정 dt(ms) | 인프라 |
| `param_rev` | 현재 params 변경 카운터 | 인프라 |
| `running` | 제어 루프 주행/정지 상태 | 인프라 |
| `last_reason` | 마지막 reason_code(대시보드 한 줄 표시용) | 인프라 |
| (스테이지별) | `reflect`,`error`,`turn`,`left_speed`,`right_speed` 등 | 스테이지 spec |

### reason_code
인프라는 **카탈로그를 강제하지 않지만**, 모든 event 는 [DECISIONS.md](../DECISIONS.md) 1장
"reason_code 카탈로그" 와 **일치**해야 한다. 인프라가 직접 남기는 것은 정지/안전 관련뿐:

| reason_code | 언제 | detail |
|---|---|---|
| `EMERGENCY_STOP` | 네트워크 stop 또는 watchdog 안전정지 | `source`("network"/"watchdog") |

> 스테이지가 새 판단을 추가할 때마다 DECISIONS.md 카탈로그에 1줄 추가하고, 그 event 를
> `DecisionLog.log()` 로 남긴다. 인프라는 그것을 sink(소켓)로 흘려보내기만 한다.

---

## 5. 동작 로직 (의사코드)

### 5.1 제어 루프 골격 (`stages/stageN_*.py`, 브릭 — 3.5 안전)
> **절대 규칙**: 네트워크 I/O 가 이 루프를 한 순간도 블록하지 않는다(snapshot 패턴).
> BACK 버튼은 프로그램 입력으로 할당하지 않는다([LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 6).

```text
# stages/stageN_*.py (Python 3.5 안전: .format() 사용)
params = SharedParams(DEFAULTS, PARAM_LIMITS, MAX_STEP, "config/stageN.json")
tele   = Telemetry()
log    = DecisionLog(telemetry=tele)
hw     = Ev3Hardware()           # 구동층 (ev3dev2)
stop_flag = {"on": False, "source": None}

def on_do(action, args):         # 서버가 별도 thread 에서 호출 -> 큐에 넣기만
    do_queue.put((action, args)) # 제어 루프가 안전한 시점에 꺼내 실행
    return {"queued": action}

def on_stop(source):
    stop_flag["on"] = True; stop_flag["source"] = source

server = TuningServer(params, tele, do_handler=on_do, stop_handler=on_stop)
server.start()                   # accept thread (데몬)

last = monotonic()
while True:
    # (1) 네트워크 stop/watchdog 정지 플래그
    if stop_flag["on"]:
        hw.stop(); log.log("EMERGENCY_STOP", "NETWORK", source=stop_flag["source"])
        stop_flag["on"] = False
        # 주행 멈춤 상태 유지하되 루프는 계속(다시 do/get 받게)
    # (2) dt 측정 (가정 금지)
    now = monotonic(); dt = now - last; last = now
    # (3) params 스냅샷 (락 한 번, 이후 네트워크 안 건드림)
    p = params.snapshot()
    # (5) 센서 읽기 -> 판단층(pure) -> 구동
    sensors = hw.read_sensors()
    action, reason, detail = decide_stageN(sensors, p, state)   # 판단층
    apply_action(hw, action, p)                                 # 구동층
    if reason: log.log(reason, detail.pop("reason", reason), **detail)
    # (6) telemetry 갱신 (최신 1개 교체)
    tele.publish(make_frame(now, dt, params.rev(), sensors, action))
    # (7) 큐에 든 단일 동작 처리 (do)
    drain_do_queue(do_queue, hw, params, log)
    sleep(LOOP_DELAY)            # dt 는 (3)에서 실측하므로 이 sleep 을 dt 로 쓰지 않는다
```

### 5.2 SharedParams.set (검증 — 거부, 클램프 아님)
```text
def set(self, name, value):
    with self.lock:
        if name not in self.limits:
            return False, "unknown param: {}".format(name)
        lo, hi = self.limits[name]
        if not (lo <= value <= hi):
            return False, "out of range [{},{}]: {}".format(lo, hi, value)
        if name in self.max_step:
            if abs(value - self.values[name]) > self.max_step[name]:
                return False, "step too big (max {})".format(self.max_step[name])
        self.values[name] = value
        self._rev += 1
        return True, "ok"
```

### 5.3 TuningServer (연결당 thread, 비차단)
> [LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 2: 단일 blocking accept 는 telemetry 스트림이
> 연결을 잡으면 `set` 이 안 받힌다 → **연결마다 핸들러 thread**.

```text
def start(self):
    sock = socket(); sock.setsockopt(SO_REUSEADDR)
    sock.bind(("127.0.0.1", 8765)); sock.listen(8)
    Thread(target=self._accept_loop, args=(sock,), daemon=True).start()

def _accept_loop(self, sock):
    while True:
        conn, _ = sock.accept()
        Thread(target=self._handle, args=(conn,), daemon=True).start()

def _handle(self, conn):
    f = conn.makefile("rwb")           # newline-delimited JSON
    for line in f:                     # 한 줄 = 한 요청
        try:
            req = json.loads(line)
            resp = self._dispatch(req)  # get/set/stop/do/save/rollback/get_latest
        except Exception as exc:
            resp = {"ok": False, "error": str(exc)}
        f.write((json.dumps(resp) + "\n").encode()); f.flush()
```
- `_dispatch` 는 `params`/`telemetry`/`do_handler`/`stop_handler` 만 만진다. **제어 루프와
  공유하는 건 락으로 보호된 snapshot/publish 뿐** → 루프를 블록하지 않는다.
- JSON 파싱 실패·미지원 명령은 **응답으로 에러를 돌려주고 thread/서버는 죽지 않는다**.

### 5.4 PID dt (측정값)
```text
def update(self, error, dt):
    if dt <= 0: dt = 1e-3            # 0/음수 방어
    self.integral += error * dt
    deriv = (error - self.prev_error) / dt
    out = self.kp*error + self.ki*self.integral + self.kd*deriv
    self.prev_error = error
    return clamp(out, -self.out_limit, self.out_limit)
```

---

## 6. 대시보드 / CLI 연동

### 6.1 JSON 메시지 스키마 (요청/응답, newline 구분)
한 줄 = JSON 객체 1개 + `\n`. 응답엔 항상 `ok`(bool).

요청:
```jsonc
{"cmd":"get",  "name":"kp"}                      // 단일 값 (name 생략 시 전체)
{"cmd":"set",  "name":"kp", "value":0.82}        // 라이브 변경(메모리)
{"cmd":"stop", "source":"network"}               // 네트워크 정지(보조)
{"cmd":"do",   "action":"turn_left", "args":{}}  // 단일 동작 1회 트리거
{"cmd":"save"}                                    // 현재 값을 config/<stage>.json 에
{"cmd":"rollback"}                                // 마지막 save 로 복귀
{"cmd":"get_latest"}                              // 최신 telemetry 프레임 1개
{"cmd":"describe"}                                // 이 스테이지의 params 메타+actions (UI 자동구성용)
```

응답(예):
```jsonc
{"ok":true,  "value":0.82, "rev":7}                       // get/set
{"ok":false, "error":"out of range [0.0,3.0]: 5"}         // 거부
{"ok":true,  "queued":"turn_left"}                        // do
{"ok":true,  "saved":"config/stage1.json"}                // save
{"ok":true,  "latest":{"t_ms":13120,"reflect":34,...}}    // get_latest
```

`describe` 응답 (동결 계약 — 대시보드가 이걸로 UI 를 자동 구성한다):
```jsonc
{
  "ok": true,
  "stage": "stage2",
  "params": [
    // 순서대로 화면에 그린다. min/max/step/max_step/unit 은 SharedParams 메타에서.
    {"name":"turn_90_factor", "value":1.0, "min":0.5, "max":1.5, "step":0.01, "max_step":0.1, "unit":"x"},
    {"name":"turn_speed",     "value":20,  "min":5,   "max":60,  "step":1,    "max_step":10,  "unit":"%"}
  ],
  "actions": [
    {"name":"turn_left",  "label":"좌90"},
    {"name":"turn_right", "label":"우90"},
    {"name":"uturn",      "label":"U턴"}
  ]
}
```
- `params` 는 그 스테이지가 라이브로 노출한 것만(6개 이하), 화면 표시 순서대로.
- `actions` 는 그 스테이지의 `do` 액션 목록(name=프로토콜 인자, label=사람용 표기).
- 스테이지가 바뀌면 `describe` 결과가 바뀌고 **대시보드는 코드 변경 없이** 새 params/액션을 그린다.
  (데모 서버는 샘플 params+actions 로 describe 를 채워 PC 단독 테스트가 되게 한다.)
- telemetry 는 **push 안 함**(기본 pull): `get_latest` 를 주기적으로 polling.
  ([LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 2의 pull 모델, 기술결정 4와 부합.)

> **검토 반영 #2 — 브릭 연결은 단일 채널.** EV3 는 단일코어 ~300MHz 라, 대시보드와 watcher 가
> *각각* 브릭에 붙어 폴링하면 thread/GIL 경쟁으로 제어 주기가 흔들릴 수 있다. 그래서:
> - **`telemetry_watcher.py` 만 브릭에 상시 접속**해 `get_latest` 를 **저주파(3~5Hz)** 로 polling
>   하고 `runs/<ts>/` 에 기록한다(유일한 telemetry 소비자).
> - **`dashboard.py` 는 브릭이 아니라 watcher 가 쓴 로컬 파일(`runs/current/latest_state.json`)
>   을 읽어** 렌더링한다(브릭에 telemetry 폴링 안 함).
> - 사람이 키를 누를 때 발생하는 `set`/`do`/`stop` 같은 **명령만** 브릭에 보낸다(저빈도, 키 입력당
>   1회). 즉 상시 부하는 watcher 단일 연결 하나로 한정된다.
> - watcher 미실행 시를 위해 대시보드에 "브릭 직접 폴링" 폴백 모드를 옵션으로 둘 수 있다(기본 OFF).

### 6.2 `tools/robotctl.py` — 비대화형 CLI (노트북, 최신 문법 OK)
스크립트·에이전트용. 한 명령 = 한 요청 = 한 응답 후 종료.
```bash
python tools/robotctl.py get [name]
python tools/robotctl.py set <name> <value>
python tools/robotctl.py stop
python tools/robotctl.py do <action> [k=v ...]
python tools/robotctl.py save
python tools/robotctl.py rollback
python tools/robotctl.py latest          # get_latest 보기 좋게 출력
python tools/robotctl.py describe        # stage/params/actions 메타 확인
```
- 종료코드: 성공 0, 거부/에러 1(스크립트가 분기 가능). `--host/--port` 옵션(기본 127.0.0.1:8765).

### 6.3 `tools/dashboard.py` — stdlib curses TUI (노트북)
한 화면에 상태/최근 이벤트/조정 가능한 params + **큰 STOP**. 상태 표시는 watcher 가 쓴
로컬 `runs/current/latest_state.json` 을 읽어 갱신(브릭 직접 폴링 안 함, 검토 반영 #2).
키 입력 시에만 `set`/`do`/`stop` 명령을 브릭에 보낸다.

> **data-driven (검토 반영 — 스테이지마다 대시보드 재작성 방지):** 접속 시 `describe` 를 1회
> 호출해 **params 행과 actions 키를 동적으로 구성**한다. 특정 스테이지의 param 이름·액션을
> 코드에 하드코딩하지 않는다. Stage 2(회전)·Stage 4(색) 등에서 새 params/액션이 생겨도
> 대시보드 코드는 그대로다 — `describe` 가 알려주는 대로 그린다.

레이아웃(개념):
```
+---------------------------- ev3 dashboard (stage1) -----------------------------+
| RUNNING   t=13.1s  dt=16ms  rev=7        [ S = STOP ]                          |
| reflect 34  error -6  turn 12  L 28  R 16                                       |
|--------------------------------------------------------------------------------|
| params           value   limit         step    (TAB/↑↓ 선택, ←→ 또는 -/+ 조정) |
|  > kp            0.82    0.0..3.0       0.10                                    |
|    kd            0.06    0.0..1.0       0.05                                    |
|    base_speed    22      5..45          5                                       |
|--------------------------------------------------------------------------------|
| actions:  [f] follow_once   [n] nudge   ...   (스테이지별)                      |
| events (최근):                                                                  |
|  13.26 NODE_CONFIRMED bits=110 dist=18                                          |
|  13.43 TURN_LEFT 110 left-only                                                  |
+--------------------------------------------------------------------------------+
```

키맵 (명세 — actions 키는 `describe` 의 actions 로 **자동 배정**, 하드코딩 X):
| 키 | 동작 | 비고 |
|---|---|---|
| `Space` | **pause/resume** (`pause`) | 속도 0 일시정지. 프로그램/서버는 계속 살아 있음 |
| `s` | **STOP** (`stop`) | 네트워크 비상정지/종료 성격. 재개하려면 스테이지 재실행 |
| `↑` / `↓` 또는 `Tab` | params 행 선택 | describe 순서대로 |
| `←` / `-` | 선택 param **감소**(`set name value-step`) | UI `step` 만큼(coarse 면 ×5) |
| `→` / `+` | 선택 param **증가**(`set name value+step`) | 거부(범위/max_step)되면 에러 한 줄 표시 |
| `1`,`2`,`3`… | `do <action>` | **describe.actions 순서대로 자동 배정**(예 `1`=좌90 `2`=우90 `3`=U턴) |
| `.` | **마지막 do 액션 반복** | 회전 보정 루프용 |
| `a` | **"조정 후 자동 재실행" 토글** | ON 이면 `+/-` 직후 마지막 액션 자동 재실행 |
| `c` | **coarse/fine step 토글** | fine=`step`, coarse=`step`×5 (단 max_step 넘으면 서버가 거부) |
| `S`(대문자) | `save` (확인 프롬프트) | config/<stage>.json |
| `R` | `rollback` (확인 프롬프트) | |
| `g` | `describe`+`get` 전체 새로고침 | 스테이지 바뀌었을 때 |
| `q` | 대시보드 종료(로봇은 계속 주행) | 로봇 stop 아님 |

> 회전 튜닝 루프(Stage 2): `1`(좌90) → 각도 보고 → `+`/`-` 로 turn_90_factor 한 칸 → `.`
> (또는 `a` 토글 ON 시 자동) 로 다시 좌90. **터미널 타이핑 없이 키만으로** 반복한다.
> 대시보드 종료(`q`)는 **로봇을 멈추지 않는다**. 잠깐 멈춤은 `Space`(pause/resume),
> 완전 정지는 `s`(network stop) 로 한다.

---

## 7. 보정 절차 (실기, 한 번에 변수 하나)

> 인프라 자체 보정은 없다. 인프라의 *작동*을 확인하는 절차 + Stage 1 튜닝 루프의 골격.
> 실제 값 튜닝 순서는 [stage1_linetrace.md](stage1_linetrace.md) / [STAGES.md](../STAGES.md) Stage 1.

1. **터널 연결**: 노트북에서 `ssh -L 8765:127.0.0.1:8765 robot@ev3dev.local`.
   (블루투스 PAN·와이파이 어느 쪽이든 SSH 가 되면 동일하게 동작 — 7절 참고.)
2. **서버 살아있나**: 브릭에서 stage 실행 → 노트북 `python tools/robotctl.py latest`
   가 프레임을 돌려주면 서버/터널 OK.
3. **set 비차단 확인**: 대시보드를 띄워 telemetry 가 흐르는 *동안* `→` 로 `kp` 를 한 칸
   올려 본다. 값이 즉시 반영되고 주행이 끊기지 않으면 "연결당 thread + snapshot" OK.
4. **거부 확인**: 범위 밖(`set kp 5`) → `ok:false` 응답. 큰 변화(`set base_speed 45` 를 한 번에)
   → MAX_STEP 거부. 둘 다 확인.
5. **save/rollback**: 좋은 값에서 `S`(save) → 일부러 망친 뒤 `R`(rollback) 로 복귀 확인.
6. **그 다음** 비로소 Stage 1 의 한 값(예 `kp`)만 만지며 곡선 추종을 맞춘다(한 번에 변수 하나).

---

## 8. 실패 모드 & 진단

| 실패 | 증상 | 진단/대응 |
|---|---|---|
| 네트워크가 제어 루프를 블록 | `set` 보내면 주행이 끊긴다 | snapshot 패턴 위반 — `_dispatch` 가 락 밖에서 무거운 일 하는지, accept 가 단일 thread 인지 점검(기술결정 2). |
| JSON 한 줄 깨짐으로 서버 죽음 | 한 번 잘못된 입력 후 서버 무응답 | `_handle` 의 try/except 누락 — 파싱 실패는 **에러 응답**으로만 처리, thread 유지(5.3). |
| 네트워크 끊김 | 터널 죽었는데 로봇 거동 | 로봇은 **마지막 params 로 계속 주행**(set 안 오면 그대로). watchdog 토글 시 N초 무명령이면 안전정지(아래). |
| `s`/`robotctl stop` 이 안 먹힘 | 정지 명령을 보냈는데 계속 주행 | stop_handler, stop_flag, 제어 루프의 정지 플래그 확인 위치 점검. |
| 값이 튀어 위험 | 한 번에 큰 변화로 폭주 | MAX_STEP 거부 동작 확인(5.2). |
| telemetry 안 흐름 | 대시보드 빈 화면 | `get_latest` polling 주기/터널/`tele.publish` 호출 위치 점검. |

### 안전 (반드시)
- **BACK 버튼 미할당**: 프로그램 입력으로 쓰지 않는다. ev3dev 기본 종료 동작으로 남긴다.
- **network stop**: `stop` 명령 / 대시보드 `s`.
- **네트워크 끊겨도 안전**: 마지막 params 유지하며 계속 주행(기본) 또는 watchdog 안전정지.
- **watchdog 토글**: `WATCHDOG_SECONDS`(0 이면 끔). 마지막 명령/연결 후 N초 지나면 `stop`
  (source="watchdog"). 모드별로 켜고 끔([LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 6).
  Stage 1 기본은 **끔**(라인트레이싱은 명령 없이도 계속 도는 게 맞음). 회전/색읽기처럼
  사람이 지켜보는 `do` 위주 단계에서 켜는 걸 고려.

---

## 9. PC 검증

PC 엔 ev3dev2 가 없으므로 **문법/판단층만** 검증한다.
- `python3 -m py_compile lib/*.py tools/*.py stages/*.py` — **lib/stages 는 3.5 안전이라야**
  하므로, 가능하면 brick 의 Python(3.5)로도 `py_compile` 점검(f-string 들어가면 여기서 잡힘).
- `lib/shared_params.py` 단위: set 범위 거부 / MAX_STEP 거부 / 미정의 키 거부 / save→rollback
  왕복 / rev 증가 검증(하드웨어 없이).
- `lib/pid.py` 단위: dt 변화에 따른 출력, 적분 누적, out_limit 클램프.
- `lib/tuning_server.py`: 로컬에서 띄우고 소켓으로 get/set/do/get_latest 왕복(가짜 params/
  telemetry 주입). 깨진 JSON 한 줄 보내도 서버 안 죽는지.
- **판단층 재연**: `replay.py runs/<ts> --set kp=0.9` 로 기록 samples 를 `decide_*` 에 흘려
  events 가 어떻게 달라지는지(로봇 없이). 잘 재연되는 것/부분만 되는 것은
  [DECISIONS.md](../DECISIONS.md) 5장 참고.

---

## 10. 구현 체크리스트 (이어받는 사람/에이전트용 TODO)

> 아래 기본 항목은 인프라 MVP 1차에서 대부분 구현됨(PROGRESS 참조). **이번 `describe`/
> data-driven 확장에서 새로/추가로 해야 하는 것**은 각 항목 끝에 `[describe]` 로 표시한다.

- [ ] `lib/shared_params.py`: 락·snapshot·set(범위/스텝 거부)·rev·save/rollback. PC 단위 테스트.
      `[describe]` ui_step/units 메타 보관 + describe 용 메타 노출 메서드.
- [ ] `lib/telemetry.py`: publish/latest(락). PC 단위 테스트.
- [ ] `lib/pid.py`: dt 인자 update, gains 라이브 변경, out_limit. PC 단위 테스트.
- [ ] `lib/decision_log.py`: log(event,reason,**detail), t_ms 자동, sink 연결. 판단층 I/O 금지 확인.
- [ ] `lib/tuning_server.py`: threaded accept, newline-JSON dispatch(get/set/stop/do/save/
      rollback/get_latest), 127.0.0.1 bind, 깨진 입력에 안 죽음. 로컬 소켓 테스트.
- [ ] `tools/robotctl.py`: 7개 명령, 종료코드, --host/--port.
- [ ] `tools/dashboard.py`: curses TUI, get_latest polling, 키맵(6.3), STOP, save/rollback 확인 프롬프트.
- [ ] `tools/telemetry_watcher.py`: runs/<ts>/{samples,events}.jsonl + params.json 기록(스키마 11.x? → 아래 12절).
- [ ] `tools/replay.py`: samples → 판단층 재연, --set 로 params override, events diff 출력.
- [ ] `lib/`·`stages/` 가 **Python 3.5 로 py_compile** 통과(f-string 없음) 확인.
- [ ] SSH 터널로 노트북↔브릭 왕복(7절 보정절차 1~5) 실기 확인 → PROGRESS 기록.
- [ ] `config/` 는 git 추적, `runs/` 는 .gitignore 등록 확인.

---

## 11. 미해결 / 실기 확인 필요

- **EV3 Python 버전**: 3.5(stretch) 가정. Stage 0 에서 `python3 --version` 으로 확정.
  3.6+ 면 f-string 허용되지만 **안전하게 3.5 규칙 유지**.
- **포트 8765 충돌**: 다른 프로세스가 점유 시 동작 미확인. `SO_REUSEADDR` + 실패 시 명확한
  에러 메시지 필요. 포트 변경 옵션 둘지 미정.
- **연결당 thread 수 한도**: 대시보드+watcher+robotctl 동시 접속 시 thread 누적/정리
  타이밍 실기 미검증(makefile close, conn 정리).
- **watchdog 기본 ON/OFF**: 위에선 Stage 1 OFF 제안이나, 실기에서 "터널 끊김 시 폭주"
  위험을 보고 단계별로 재결정.
- **telemetry pull vs push / 폴링 주기**: 기본 pull, **watcher 단일 연결이 3~5Hz polling**
  (검토 반영 #2). 이 주기가 곡선 튜닝·대시보드 체감에 충분한지, push 가 필요한지 실기 판단.
  watcher↔대시보드 사이 로컬 갱신 방식(파일 vs 로컬 소켓)도 구현 시 확정.
- **`get_latest` 가 set 과 같은 thread 경쟁** 시 지연/락 보유시간 — 실측 필요(snapshot 으로
  최소화하지만 확인).
- **runs/ 타임스탬프 형식**: `2026-06-29T14-03` 같은 콜론 없는 형식(파일명 안전) 제안 —
  watcher 구현 시 확정.
- **블루투스 PAN 지연**: 와이파이보다 느릴 수 있음. SSH 만 되면 동작은 같으나, polling
  주기/응답 지연이 대시보드 체감에 어떤지 실기 확인.
- **save 포맷**: `config/<stage>.json`(JSON) 제안. 이전 로봇은 `config.py` 텍스트 치환
  방식이었음(calibrate.py 참고). JSON 으로 가는 게 본 프로젝트 방향(per-stage, 거대 config 금지)과 부합 — 실제 채택은 Stage 1 구현 시 확정.

---

## 12. 파일 스키마 (runs/ — 노트북이 기록)

`tools/telemetry_watcher.py` 가 EV3 소켓을 polling 해 **노트북** `runs/<ts>/` 에 기록한다
(EV3 SD 에 매 틱 쓰지 않음 — [LIVE_TUNING.md](../LIVE_TUNING.md) 기술결정 4).

`runs/<ts>/samples.jsonl` — 제어 틱마다 1줄(telemetry 프레임):
```jsonc
{"t_ms":13120,"dt_ms":16,"param_rev":7,"reflect":34,"error":-6,"turn":12,"left_speed":28,"right_speed":16}
```
- 공통 키(`t_ms`,`dt_ms`,`param_rev`) + 스테이지 telemetry 키. `replay.py` 가 이 줄을
  판단층에 다시 흘린다.

`runs/<ts>/events.jsonl` — 판단/행동 로그(reason_code), [DECISIONS.md](../DECISIONS.md) 형식 그대로:
```jsonc
{"t_ms":13260,"event":"NODE_CONFIRMED","reason":"BITS_STABLE_AND_DEBOUNCE_OK","bits":"110","duration_ms":140,"dist_mm":18}
```

`runs/<ts>/params.json` — 값 변경 타임라인(언제 무엇을 바꿨나):
```jsonc
{
  "stage": "stage1",
  "started": "2026-06-29T14-03",
  "initial": {"kp":0.75,"kd":0.06,"base_speed":22,"target_reflect":35},
  "changes": [
    {"t_ms":42010,"rev":6,"name":"kp","old":0.75,"new":0.82,"source":"dashboard"},
    {"t_ms":51220,"rev":7,"name":"kp","old":0.82,"new":0.90,"source":"robotctl"}
  ]
}
```
- `runs/` 는 git 추적 안 함(.gitignore). `config/<stage>.json`(save 결과)만 추적.
