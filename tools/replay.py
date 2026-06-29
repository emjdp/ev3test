#!/usr/bin/env python3
"""기록한 samples.jsonl 을 판단층 decide 함수에 다시 흘려본다."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable


DecideFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Any]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("{}:{} is not a JSON object".format(path, lineno))
            rows.append(value)
    return rows


def load_params(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and isinstance(doc.get("initial"), dict):
        return dict(doc["initial"])
    if isinstance(doc, dict):
        return dict(doc)
    return {}


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_overrides(groups: list[list[str]] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for group in groups or []:
        for item in group:
            if "=" not in item:
                raise ValueError("--set value must be key=value: {}".format(item))
            name, raw = item.split("=", 1)
            if not name:
                raise ValueError("--set key is empty")
            overrides[name] = parse_value(raw)
    return overrides


def resolve_run_path(path: Path) -> tuple[Path, Path | None, Path | None]:
    if path.is_dir():
        return path / "samples.jsonl", path / "events.jsonl", path / "params.json"
    run_dir = path.parent
    events = run_dir / "events.jsonl"
    params = run_dir / "params.json"
    return path, events if events.exists() else None, params if params.exists() else None


def stub_decide(sensors: dict[str, Any], params: dict[str, Any], state: dict[str, Any]) -> tuple[None, None, dict[str, Any]]:
    """Stage 판단층이 생기기 전까지 쓰는 빈 decide."""

    state["samples_seen"] = state.get("samples_seen", 0) + 1
    return None, None, {}


def load_decider(spec: str | None) -> DecideFn:
    if not spec:
        return stub_decide
    if ":" not in spec:
        raise ValueError("--decider must be module:function")
    module_name, func_name = spec.split(":", 1)
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):
        raise TypeError("{} is not callable".format(spec))
    return func


def normalize_decision(result: Any, sample: dict[str, Any]) -> list[dict[str, Any]]:
    """decide 반환값을 events.jsonl 형태 후보로 맞춘다."""

    if result is None:
        return []
    if isinstance(result, dict):
        if isinstance(result.get("events"), list):
            return [event for event in result["events"] if isinstance(event, dict)]
        if result.get("event"):
            return [dict(result)]
        return []
    if not isinstance(result, tuple) or len(result) < 2:
        return []

    action = result[0]
    reason_code = result[1]
    detail = dict(result[2]) if len(result) >= 3 and isinstance(result[2], dict) else {}
    if not reason_code:
        return []

    event = {
        "t_ms": sample.get("t_ms"),
        "event": reason_code,
        "reason": detail.pop("reason", reason_code),
    }
    if action is not None:
        event["action"] = action
    event.update(detail)
    return [event]


def event_names(events: list[dict[str, Any]]) -> list[str]:
    return [str(event.get("event", "")) for event in events]


def compare_events(generated: list[dict[str, Any]], recorded: list[dict[str, Any]]) -> dict[str, Any]:
    gen_names = event_names(generated)
    rec_names = event_names(recorded)
    matched_prefix = 0
    for gen, rec in zip(gen_names, rec_names):
        if gen != rec:
            break
        matched_prefix += 1

    first_diff = None
    if gen_names != rec_names:
        first_diff = {
            "index": matched_prefix,
            "generated": gen_names[matched_prefix] if matched_prefix < len(gen_names) else None,
            "recorded": rec_names[matched_prefix] if matched_prefix < len(rec_names) else None,
        }
    return {
        "generated_count": len(generated),
        "recorded_count": len(recorded),
        "matched_prefix": matched_prefix,
        "first_diff": first_diff,
    }


def replay(samples: list[dict[str, Any]], params: dict[str, Any], decide: DecideFn) -> list[dict[str, Any]]:
    state: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    for sample in samples:
        result = decide(sample, params, state)
        events.extend(normalize_decision(result, sample))
    return events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay samples.jsonl through a decide function")
    parser.add_argument("run", type=Path, help="runs/<ts>/ directory or samples.jsonl")
    parser.add_argument("--decider", default=None, help="module:function, default is stub")
    parser.add_argument("--params", type=Path, default=None, help="params.json override path")
    parser.add_argument(
        "--set",
        dest="sets",
        nargs="+",
        action="append",
        default=[],
        metavar="key=value",
        help="params override; may contain multiple key=value pairs",
    )
    parser.add_argument("--emit-events", action="store_true", help="print generated events as JSONL")
    parser.add_argument("--output", type=Path, default=None, help="write generated events JSONL")
    parser.add_argument("--strict", action="store_true", help="exit 1 when event sequence differs")
    return parser


def write_events(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    samples_path, events_path, default_params_path = resolve_run_path(args.run)
    params_path = args.params if args.params is not None else default_params_path

    samples = load_jsonl(samples_path)
    recorded = load_jsonl(events_path) if events_path is not None and events_path.exists() else []
    params = load_params(params_path)
    overrides = parse_overrides(args.sets)
    params.update(overrides)

    decide = load_decider(args.decider)
    generated = replay(samples, params, decide)
    comparison = compare_events(generated, recorded)

    if args.output:
        write_events(args.output, generated)
    if args.emit_events:
        for event in generated:
            print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    else:
        print("samples: {}".format(len(samples)))
        print("params: {} keys (overrides: {})".format(len(params), ", ".join(sorted(overrides)) or "-"))
        print("generated events: {}".format(comparison["generated_count"]))
        print("recorded events: {}".format(comparison["recorded_count"]))
        print("matched prefix: {}".format(comparison["matched_prefix"]))
        if comparison["first_diff"]:
            print("first diff: {}".format(json.dumps(comparison["first_diff"], ensure_ascii=False)))
        elif recorded or generated:
            print("event sequence: match")
        else:
            print("event sequence: no events (stub decide)")

    if args.strict and comparison["first_diff"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
