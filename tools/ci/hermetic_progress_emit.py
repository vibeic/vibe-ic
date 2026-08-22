#!/usr/bin/env python3
"""Emit one exact checkpoint from the parent-owned hermetic progress plan."""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence


_SPEC = importlib.util.spec_from_file_location(
    "_vibeic_progress_transition_json",
    Path(__file__).resolve().with_name("protected_landing_transition.py"),
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("strict JSON authority is unavailable")
strict = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = strict
_SPEC.loader.exec_module(strict)

SCHEMA = 1
PROTOCOL = "VIBEIC_PROGRESS/1"
NONCE_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_UNITS = 100_000


class Refusal(RuntimeError):
    pass


def _bounded(value: Any, what: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 4096
            or "\x00" in value or "\n" in value or "\r" in value):
        raise Refusal(f"{what} is not one bounded string")
    return value


def _plan() -> dict[str, Any]:
    nonce = os.environ.get("VIBEIC_HERMETIC_PROGRESS_NONCE")
    scope = os.environ.get("VIBEIC_HERMETIC_PROGRESS_SCOPE")
    path = os.environ.get("VIBEIC_HERMETIC_PROGRESS_PATH")
    prefix = os.environ.get("VIBEIC_HERMETIC_PROGRESS_PREFIX")
    if (not isinstance(nonce, str) or NONCE_RE.fullmatch(nonce) is None
            or not isinstance(scope, str) or not scope
            or path != "/input/progress-plan.json"
            or prefix != "VIBEIC_PROGRESS "):
        raise Refusal("hermetic progress environment is missing or ambiguous")
    try:
        raw = Path(path).read_bytes()
        doc = strict.strict_loads(raw, what="hermetic runtime progress plan")
    except (OSError, strict.Refusal) as exc:
        raise Refusal(f"cannot read hermetic progress plan: {exc}") from exc
    if (not isinstance(doc, dict) or set(doc) != {
            "nonce", "protocol", "schema", "scope", "units"}
            or type(doc.get("schema")) is not int or doc["schema"] != SCHEMA
            or doc.get("protocol") != PROTOCOL
            or doc.get("nonce") != nonce or doc.get("scope") != scope):
        raise Refusal("runtime progress plan disagrees with its environment")
    units = doc.get("units")
    if (not isinstance(units, list) or not units or len(units) > MAX_UNITS):
        raise Refusal("runtime progress plan has no finite non-empty unit list")
    parsed = [_bounded(unit, "progress unit") for unit in units]
    if len(parsed) != len(set(parsed)):
        raise Refusal("runtime progress plan repeats a unit")
    return {"nonce": nonce, "scope": scope, "units": parsed,
            "prefix": prefix}


def record(state: str, unit: str | None = None) -> bytes:
    plan = _plan()
    units = plan["units"]
    common = {
        "nonce": plan["nonce"], "schema": SCHEMA,
        "scope": plan["scope"], "total": len(units),
    }
    if state == "start":
        if unit is not None:
            raise Refusal("start cannot carry a unit")
        row = {**common, "seq": 0, "state": "start"}
    elif state == "checkpoint":
        if unit not in units:
            raise Refusal("checkpoint is not in the parent-owned plan")
        completed = units.index(unit) + 1
        row = {**common, "completed": completed, "seq": completed,
               "state": "checkpoint", "unit": unit}
    elif state == "terminal":
        if unit is not None:
            raise Refusal("terminal cannot carry a unit")
        row = {**common, "completed": len(units), "seq": len(units) + 1,
               "state": "terminal"}
    else:
        raise Refusal("unknown progress state")
    return plan["prefix"].encode("ascii") + strict.canonical_bytes(row)


def emit(state: str, unit: str | None = None) -> None:
    raw = record(state, unit)
    view = memoryview(raw)
    while view:
        written = os.write(sys.stdout.fileno(), view)
        if written <= 0:
            raise OSError("short progress write")
        view = view[written:]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=("start", "checkpoint", "terminal"))
    parser.add_argument("unit", nargs="?")
    args = parser.parse_args(argv)
    try:
        emit(args.state, args.unit)
    except (OSError, Refusal) as exc:
        print(f"[NORECORD] hermetic progress emit: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
