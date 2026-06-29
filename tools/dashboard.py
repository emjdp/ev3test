#!/usr/bin/env python3
"""runs/current/latest_state.json 기반 curses 대시보드."""

from __future__ import annotations

import argparse
import curses
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path("runs/current/latest_state.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_ACTIONS = {"f": "follow_once", "n": "nudge"}
META_KEYS = {
    "stage",
    "latest",
    "telemetry",
    "frame",
    "params",
    "param_values",
    "param_limits",
    "limits",
    "max_step",
    "steps",
    "events",
    "recent_events",
    "last_events",
    "actions",
}


@dataclass
class ParamRow:
    name: str
    value: Any
    limit: Any = None
    step: Any = None


@dataclass
class DashboardModel:
    stage: str
    frame: dict[str, Any]
    params: list[ParamRow]
    events: list[dict[str, Any]]
    selected: int = 0
    status: str = ""
    state_error: str = ""
    state_age_s: float | None = None
    pending_confirm: str = ""


def load_latest_state(path: Path) -> tuple[dict[str, Any], str, float | None]:
    try:
        raw = path.read_text(encoding="utf-8")
        state = json.loads(raw)
    except FileNotFoundError:
        return {}, f"state file not found: {path}", None
    except json.JSONDecodeError as exc:
        return {}, f"state JSON error: {exc}", None
    except OSError as exc:
        return {}, f"state read error: {exc}", None

    if not isinstance(state, dict):
        return {}, "state root must be a JSON object", None

    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        age = None
    return state, "", age


def send_command(
    request: dict[str, Any],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 1.5,
) -> dict[str, Any]:
    data = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(data)
        with sock.makefile("rb") as reader:
            line = reader.readline()
    if not line:
        return {"ok": False, "error": "empty response"}
    try:
        response = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"bad response: {exc}"}
    if isinstance(response, dict):
        return response
    return {"ok": False, "error": "response root is not an object", "raw": response}


def build_model(
    state: dict[str, Any],
    selected: int = 0,
    status: str = "",
    state_error: str = "",
    state_age_s: float | None = None,
    pending_confirm: str = "",
) -> DashboardModel:
    frame = _extract_frame(state)
    params = _extract_params(state, frame)
    events = _extract_events(state, frame)
    if params:
        selected = max(0, min(selected, len(params) - 1))
    else:
        selected = 0

    stage = str(state.get("stage") or frame.get("stage") or "-")
    return DashboardModel(
        stage=stage,
        frame=frame,
        params=params,
        events=events,
        selected=selected,
        status=status,
        state_error=state_error,
        state_age_s=state_age_s,
        pending_confirm=pending_confirm,
    )


def render_lines(model: DashboardModel, width: int = 100, height: int = 32) -> list[str]:
    width = max(40, width)
    height = max(8, height)
    sep = "-" * width
    frame = model.frame

    running = _truth_label(frame.get("running"))
    t_ms = _as_number(frame.get("t_ms"))
    dt_ms = _as_number(frame.get("dt_ms"))
    rev = frame.get("param_rev", frame.get("rev", "-"))
    age = "-" if model.state_age_s is None else f"{model.state_age_s:.1f}s"
    title = f" ev3 dashboard ({model.stage}) "

    lines: list[str] = [title.center(width, "-")]
    lines.append(
        _fit(
            f"{running:<8} t={_format_seconds(t_ms)}  dt={_format_ms(dt_ms)}  "
            f"rev={rev}  state_age={age}    [s/Space STOP]",
            width,
        )
    )
    lines.append(_fit(_telemetry_summary(frame), width))
    lines.append(sep)
    lines.append(_fit("params           value        limit          step", width))

    if model.params:
        param_room = max(3, min(len(model.params), height // 3))
        start = _window_start(model.selected, len(model.params), param_room)
        for idx in range(start, min(len(model.params), start + param_room)):
            row = model.params[idx]
            marker = ">" if idx == model.selected else " "
            lines.append(
                _fit(
                    f"{marker} {row.name:<15} {_format_value(row.value):<12} "
                    f"{_format_limit(row.limit):<14} {_format_step(row.step, row.value):<8}",
                    width,
                )
            )
    else:
        lines.append(_fit("  (latest_state.json has no params)", width))

    lines.append(sep)
    lines.append(_fit("actions: [f] follow_once   [n] nudge   [g] get   [S] save   [R] rollback   [q] quit", width))
    if model.pending_confirm:
        lines.append(_fit(f"confirm {model.pending_confirm}: press y to run, n/Esc to cancel", width))
    elif model.status:
        lines.append(_fit(f"status: {model.status}", width))
    elif model.state_error:
        lines.append(_fit(f"state: {model.state_error}", width))
    else:
        lines.append(_fit("status: ready", width))

    lines.append(sep)
    lines.append(_fit("events (recent):", width))
    event_room = max(1, height - len(lines))
    for event in model.events[-event_room:]:
        lines.append(_fit("  " + _format_event(event), width))
    while len(lines) < height:
        lines.append("")
    return [line[:width] for line in lines[:height]]


def handle_key(
    key: int,
    model: DashboardModel,
    host: str,
    port: int,
    actions: dict[str, str] | None = None,
) -> tuple[int, str, str, bool]:
    actions = actions or DEFAULT_ACTIONS
    selected = model.selected
    status = ""
    pending = model.pending_confirm
    should_quit = False

    if pending:
        if key in (ord("y"), ord("Y")):
            status = _send_and_describe({"cmd": pending}, host, port)
            pending = ""
        elif key in (27, ord("n"), ord("N")):
            status = f"{pending} canceled"
            pending = ""
        return selected, status, pending, should_quit

    if key in (ord("q"), ord("Q")):
        should_quit = True
    elif key in (curses.KEY_UP,):
        selected = max(0, selected - 1)
    elif key in (curses.KEY_DOWN, 9):
        selected = (selected + 1) % len(model.params) if model.params else 0
    elif key in (curses.KEY_LEFT, ord("-")):
        status = _adjust_selected(model, -1, host, port)
    elif key in (curses.KEY_RIGHT, ord("+"), ord("=")):
        status = _adjust_selected(model, 1, host, port)
    elif key in (ord("s"), ord(" ")):
        status = _send_and_describe({"cmd": "stop", "source": "dashboard"}, host, port)
    elif key == ord("S"):
        pending = "save"
        status = "confirm save"
    elif key == ord("R"):
        pending = "rollback"
        status = "confirm rollback"
    elif key in (ord("g"), ord("G")):
        status = _send_and_describe({"cmd": "get"}, host, port)
    elif 0 <= key < 256 and chr(key) in actions:
        status = _send_and_describe({"cmd": "do", "action": actions[chr(key)], "args": {}}, host, port)

    return selected, status, pending, should_quit


def run_curses(args: argparse.Namespace) -> int:
    return curses.wrapper(_curses_main, args)


def _curses_main(stdscr: Any, args: argparse.Namespace) -> int:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    stdscr.timeout(200)

    selected = 0
    status = ""
    pending = ""

    while True:
        state, state_error, age = load_latest_state(args.state)
        model = build_model(state, selected, status, state_error, age, pending)
        selected = model.selected
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        for row, line in enumerate(render_lines(model, width, height)):
            try:
                stdscr.addnstr(row, 0, line, max(0, width - 1))
            except curses.error:
                pass
        stdscr.refresh()

        key = stdscr.getch()
        if key == -1:
            continue
        selected, status, pending, should_quit = handle_key(key, model, args.host, args.port)
        if should_quit:
            return 0


def _extract_frame(state: dict[str, Any]) -> dict[str, Any]:
    for key in ("latest", "telemetry", "frame"):
        value = state.get(key)
        if isinstance(value, dict):
            return dict(value)
    frame = {key: value for key, value in state.items() if key not in META_KEYS}
    return frame if frame else {}


def _extract_params(state: dict[str, Any], frame: dict[str, Any]) -> list[ParamRow]:
    source = state.get("params")
    if source is None:
        source = frame.get("params")

    limits = _dict_or_empty(state.get("param_limits") or state.get("limits"))
    steps = _dict_or_empty(state.get("max_step") or state.get("steps"))

    if isinstance(source, dict):
        limits.update(_dict_or_empty(source.get("limits") or source.get("param_limits")))
        steps.update(_dict_or_empty(source.get("max_step") or source.get("steps")))
        values = source.get("values") or source.get("current") or source.get("params")
        if not isinstance(values, dict):
            values = {k: v for k, v in source.items() if k not in {"limits", "param_limits", "max_step", "steps"}}
        rows = []
        for name in values:
            value = values[name]
            if isinstance(value, dict) and "value" in value:
                rows.append(
                    ParamRow(
                        name=name,
                        value=value.get("value"),
                        limit=value.get("limit") or value.get("limits") or limits.get(name),
                        step=value.get("step") or value.get("max_step") or steps.get(name),
                    )
                )
            else:
                rows.append(ParamRow(name=name, value=value, limit=limits.get(name), step=steps.get(name)))
        return rows

    values = state.get("param_values")
    if isinstance(values, dict):
        return [ParamRow(name=name, value=values[name], limit=limits.get(name), step=steps.get(name)) for name in values]
    return []


def _extract_events(state: dict[str, Any], frame: dict[str, Any]) -> list[dict[str, Any]]:
    value = state.get("recent_events") or state.get("events") or state.get("last_events")
    if value is None:
        value = frame.get("recent_events") or frame.get("events") or frame.get("last_events")
    if not isinstance(value, list):
        return []
    events = []
    for item in value:
        if isinstance(item, dict):
            events.append(item)
        else:
            events.append({"event": str(item)})
    return events


def _adjust_selected(model: DashboardModel, direction: int, host: str, port: int) -> str:
    if not model.params:
        return "no params to adjust"
    row = model.params[model.selected]
    current = _as_number(row.value)
    if current is None:
        return f"{row.name}: non-numeric value"
    step = _as_number(row.step)
    if step is None or step == 0:
        step = _infer_step(current)
    new_value = _normalize_number(current + direction * step, row.value)
    return _send_and_describe({"cmd": "set", "name": row.name, "value": new_value}, host, port)


def _send_and_describe(request: dict[str, Any], host: str, port: int) -> str:
    try:
        response = send_command(request, host, port)
    except OSError as exc:
        return f"{request.get('cmd')}: connect error: {exc}"
    return f"{request.get('cmd')}: {_compact_response(response)}"


def _compact_response(response: dict[str, Any]) -> str:
    if response.get("ok") is False:
        return "error: " + str(response.get("error", response))
    if "value" in response:
        return f"ok value={_format_value(response.get('value'))} rev={response.get('rev', '-')}"
    if "queued" in response:
        return f"ok queued={response.get('queued')}"
    if "saved" in response:
        return f"ok saved={response.get('saved')}"
    if "latest" in response:
        latest = response.get("latest")
        if isinstance(latest, dict):
            return "ok latest " + _telemetry_summary(latest)
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"))[:160]


def _telemetry_summary(frame: dict[str, Any]) -> str:
    priority = ["reflect", "error", "turn", "left_speed", "right_speed", "last_reason"]
    parts = []
    for key in priority:
        if key in frame:
            parts.append(f"{key}={_format_value(frame[key])}")
    if parts:
        return "  ".join(parts)
    items = [(k, v) for k, v in frame.items() if k not in META_KEYS and not isinstance(v, (dict, list))]
    return "  ".join(f"{k}={_format_value(v)}" for k, v in items[:6]) or "(no telemetry frame)"


def _format_event(event: dict[str, Any]) -> str:
    t_ms = _as_number(event.get("t_ms"))
    prefix = ""
    if t_ms is not None:
        prefix = f"{t_ms / 1000.0:6.2f} "
    name = str(event.get("event") or event.get("reason_code") or "-")
    reason = event.get("reason")
    skip = {"t_ms", "event", "reason_code", "reason"}
    detail = " ".join(f"{k}={_format_value(v)}" for k, v in event.items() if k not in skip)
    if reason and detail:
        return f"{prefix}{name} {reason} {detail}"
    if reason:
        return f"{prefix}{name} {reason}"
    if detail:
        return f"{prefix}{name} {detail}"
    return f"{prefix}{name}"


def _format_seconds(t_ms: float | None) -> str:
    if t_ms is None:
        return "-"
    return f"{t_ms / 1000.0:.1f}s"


def _format_ms(dt_ms: float | None) -> str:
    if dt_ms is None:
        return "-"
    return f"{dt_ms:.0f}ms"


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _format_limit(limit: Any) -> str:
    if limit is None:
        return "-"
    if isinstance(limit, dict):
        lo = limit.get("min", limit.get("lo"))
        hi = limit.get("max", limit.get("hi"))
        if lo is not None and hi is not None:
            return f"{lo}..{hi}"
    if isinstance(limit, (list, tuple)) and len(limit) >= 2:
        return f"{limit[0]}..{limit[1]}"
    return str(limit)


def _format_step(step: Any, value: Any) -> str:
    if step is None:
        number = _as_number(value)
        return _format_value(_infer_step(number)) if number is not None else "-"
    return _format_value(step)


def _truth_label(value: Any) -> str:
    if value is True:
        return "RUNNING"
    if value is False:
        return "STOPPED"
    return "UNKNOWN"


def _window_start(selected: int, total: int, room: int) -> int:
    if total <= room:
        return 0
    return min(max(0, selected - room // 2), total - room)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_step(value: float) -> float:
    magnitude = abs(value)
    if magnitude >= 10:
        return 1.0
    if magnitude >= 1:
        return 0.1
    return 0.01


def _normalize_number(number: float, old_value: Any) -> int | float:
    if isinstance(old_value, int) and not isinstance(old_value, bool):
        return int(round(number))
    return round(number, 6)


def _fit(text: str, width: int) -> str:
    if len(text) > width:
        return text[: max(0, width - 1)]
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render EV3 live-tuning dashboard")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="latest_state.json path")
    parser.add_argument("--host", default=DEFAULT_HOST, help="tuning server host for key commands")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="tuning server port for key commands")
    parser.add_argument("--once", action="store_true", help="render once to stdout and exit")
    parser.add_argument("--no-curses", action="store_true", help="alias for --once smoke rendering")
    parser.add_argument("--width", type=int, default=100, help="stdout render width")
    parser.add_argument("--height", type=int, default=32, help="stdout render height")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.once or args.no_curses:
        state, state_error, age = load_latest_state(args.state)
        model = build_model(state, state_error=state_error, state_age_s=age)
        print("\n".join(render_lines(model, args.width, args.height)))
        return 1 if state_error else 0
    return run_curses(args)


if __name__ == "__main__":
    raise SystemExit(main())
