#!/usr/bin/env python3
"""
phase1_rotation_state_advance.py — deterministic rotation for the
phase1-coverage-loop field-agent.

Extracted from skills/phase1-coverage-loop/SKILL.md. The skill prose
described two deterministic procedures that this program now owns:

  1. ic_rotation CONSTRUCTION
     The rotation is the sorted list of immediate subdirectories of a
     target benchmark folder that contain a Phase 1 prompt — either
     `README.md` or `input/prompt.md`. (A directory with neither is not
     an IC and is excluded.)

  2. ic_rotation ADVANCE / WRAP
     Given a current index, the next index is
     `(current_index + 1) % len(rotation)`. When the index wraps back to
     0, `rotation_passes_completed` is incremented by 1. This is pure
     modular arithmetic — no judgment.

Two sub-commands:

    build  --target <dir> [--json <out>]
        Enumerate the rotation. Exit 0 if >=1 IC found, 1 if the target
        has zero IC subdirs (honest FAIL — a benchmark folder with no
        README/prompt cannot be rotated), 2 on usage / missing-dir error.

    advance --current-index N --count K \
            [--passes P] [--json <out>]
        Compute the next index and the new passes counter. `K` is the
        rotation length (len(ic_rotation)). Exit 0 on a valid advance,
        1 if the inputs are inconsistent (e.g. current-index out of
        range, count<=0), 2 on usage error.

Honest-failure contract:
  * `build` on a non-existent dir            -> exit 2 (usage/input err)
  * `build` on a dir with no IC subdirs      -> exit 1 (FAIL, empty)
  * `advance` with count<=0 or index oob      -> exit 1 (FAIL)
  * garbage numeric args                      -> exit 2

A JSON report is written to --json when supplied, and always echoed in a
human one-liner to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List


PROMPT_REL_CANDIDATES = (
    Path("README.md"),
    Path("input") / "prompt.md",
)


def discover_rotation(target: Path) -> List[str]:
    """Return the sorted list of immediate sub-dir names of `target`
    that contain a Phase 1 prompt (README.md or input/prompt.md)."""
    names: List[str] = []
    for child in sorted(target.iterdir()):
        if not child.is_dir():
            continue
        if any((child / rel).is_file() for rel in PROMPT_REL_CANDIDATES):
            names.append(child.name)
    return names


def _emit(report: dict, json_out: str | None) -> None:
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2))


def _cmd_build(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"ERROR — target dir not found: {target}")
        return 2
    rotation = discover_rotation(target)
    report = {
        "gate": "phase1_rotation_state_advance",
        "command": "build",
        "target_folder": str(target),
        "ic_rotation": rotation,
        "rotation_length": len(rotation),
        "verdict": "PASS" if rotation else "FAIL",
    }
    _emit(report, args.json)
    if not rotation:
        print(f"FAIL — no IC subdirs (README.md / input/prompt.md) "
              f"under {target}; nothing to rotate.")
        return 1
    print(f"PASS — {len(rotation)} IC(s) in rotation: "
          f"{', '.join(rotation)}")
    return 0


def _cmd_advance(args: argparse.Namespace) -> int:
    cur = args.current_index
    count = args.count
    passes = args.passes
    if count <= 0:
        print(f"FAIL — rotation length must be >0 (got {count}).")
        _emit({
            "gate": "phase1_rotation_state_advance",
            "command": "advance",
            "verdict": "FAIL",
            "reason": "count<=0",
        }, args.json)
        return 1
    if cur < 0 or cur >= count:
        print(f"FAIL — current-index {cur} out of range "
              f"[0,{count}).")
        _emit({
            "gate": "phase1_rotation_state_advance",
            "command": "advance",
            "verdict": "FAIL",
            "reason": "current_index_out_of_range",
        }, args.json)
        return 1
    if passes < 0:
        print(f"FAIL — passes_completed must be >=0 (got {passes}).")
        _emit({
            "gate": "phase1_rotation_state_advance",
            "command": "advance",
            "verdict": "FAIL",
            "reason": "passes_negative",
        }, args.json)
        return 1

    next_index = (cur + 1) % count
    wrapped = next_index == 0
    new_passes = passes + 1 if wrapped else passes
    report = {
        "gate": "phase1_rotation_state_advance",
        "command": "advance",
        "verdict": "PASS",
        "current_index": cur,
        "rotation_length": count,
        "next_index": next_index,
        "wrapped": wrapped,
        "rotation_passes_completed": new_passes,
    }
    _emit(report, args.json)
    print(f"PASS — next_index={next_index} "
          f"wrapped={wrapped} "
          f"rotation_passes_completed={new_passes}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Deterministic phase1-coverage-loop rotation "
                    "construction + advance.")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build",
                       help="Enumerate the IC rotation under --target.")
    b.add_argument("--target", required=True,
                   help="Benchmark folder whose IC subdirs to rotate.")
    b.add_argument("--json", default=None,
                   help="Write the JSON report here.")
    b.set_defaults(func=_cmd_build)

    a = sub.add_parser("advance",
                       help="Advance the rotation index by one.")
    a.add_argument("--current-index", type=int, required=True,
                   dest="current_index")
    a.add_argument("--count", type=int, required=True,
                   help="Rotation length len(ic_rotation).")
    a.add_argument("--passes", type=int, default=0,
                   help="Current rotation_passes_completed.")
    a.add_argument("--json", default=None,
                   help="Write the JSON report here.")
    a.set_defaults(func=_cmd_advance)
    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
