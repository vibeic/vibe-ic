#!/usr/bin/env python3
"""analog_hil_iteration_cap_check.py — deterministic hard-cap on HIL iterations.

The analog-hw-tuning-loop skill states: "Do not exceed 3 hardware iterations — if
not converging, escalate model accuracy issue." That is a pure counter, not a
judgment. This program counts the hardware iterations recorded for each analog
block and FAILs when the cap is exceeded.

Hardware-iteration count is read, in priority order, from
analog/<block>/hw_tuning_report.json:
  1. total_iterations.hardware  (explicit integer — preferred)
  2. else len(hardware_iterations) if that key holds a list
  3. else count of entries in final_comparison whose iteration markers are
     hardware — N/A here; falls through to (1)/(2).

The cap defaults to 3 and is overridable with --max-iters (a different process
node / bench may justify a different bar; the constant lives here, not in prose).

PASS  iff every block's hardware iteration count is an integer in [0, max].
FAIL  iff any block exceeds the cap (real defect: an un-converging loop that
      should have been escalated), OR a report exists but its
      hardware-iteration field is missing / non-integer / negative.
NOT CHECKED (exit 2) iff there are no hw_tuning_report.json files.

EXIT-CODE CONTRACT (repaired — the two tiers used to be the wrong way round)
---------------------------------------------------------------------------
This program's docstring has always said "a malformed report must NOT silently
pass", and it returned exit 2 for that case. Measured against the consumer:
`flow_compliance_check.__check_program_exit_zero` maps exit 2 to
`__VACUOUS_HINT__` and returns True — i.e. a PASS
(`pass_count = counts["PASS"] + counts["VACUOUS_PASS"]`); the advisory slot
renders exit 2 as "n/a (input not present)". So under EVERY wiring, the exact
case this gate was written to refuse to pass was reported as a pass, and the
no-artefact case (exit 0) was reported as "ran and found nothing wrong".

The two tiers are therefore swapped to match what the consumer means:
    * malformed / uncountable report -> 1 (a defect, and it blocks)
    * no report present at all       -> 2 (disclosed cannot-judge)

Usage:
    python3 analog_hil_iteration_cap_check.py <project_dir> [--max-iters N] [--json <out>]
    python3 analog_hil_iteration_cap_check.py --file <report.json> [--max-iters N] [--json <out>]

Exit codes:
    0  PASS
    1  FAIL (cap exceeded, or malformed / uncountable report)
    2  NOT CHECKED (no report present) / argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl


DEFAULT_MAX_HW_ITERS = 3


@dataclass
class BlockCap:
    block: str
    source: str
    hw_iterations: Optional[int]
    verdict: str          # PASS / FAIL / ERROR
    reason: str = ""


def _extract_hw_count(data: dict) -> Optional[int]:
    """Return the hardware iteration count, or None if not determinable."""
    ti = data.get("total_iterations")
    if isinstance(ti, dict):
        hw = ti.get("hardware")
        if isinstance(hw, bool):
            return None
        if isinstance(hw, int):
            return hw
    hi = data.get("hardware_iterations")
    if isinstance(hi, list):
        return len(hi)
    return None


def evaluate_file(path: Path, max_iters: int) -> BlockCap:
    block_name = path.parent.name
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return BlockCap(block=block_name, source=str(path), hw_iterations=None,
                        verdict="ERROR", reason="unreadable / malformed JSON")
    if not isinstance(data, dict):
        return BlockCap(block=block_name, source=str(path), hw_iterations=None,
                        verdict="ERROR", reason="top-level JSON is not an object")
    block = data.get("block_name") or data.get("block") or block_name
    count = _extract_hw_count(data)
    if count is None:
        return BlockCap(block=block, source=str(path), hw_iterations=None,
                        verdict="ERROR",
                        reason=("no integer total_iterations.hardware or "
                                "hardware_iterations list — cannot count"))
    if count < 0:
        return BlockCap(block=block, source=str(path), hw_iterations=count,
                        verdict="ERROR", reason="negative hardware iteration count")
    if count > max_iters:
        return BlockCap(block=block, source=str(path), hw_iterations=count,
                        verdict="FAIL",
                        reason=(f"{count} hardware iterations exceed cap of "
                                f"{max_iters}; loop should have escalated a "
                                f"model-accuracy issue instead of iterating"))
    return BlockCap(block=block, source=str(path), hw_iterations=count,
                    verdict="PASS",
                    reason=f"{count} hardware iteration(s) <= cap {max_iters}")


def run(project: Optional[Path], single_file: Optional[Path], max_iters: int) -> dict:
    blocks: List[BlockCap] = []
    if single_file is not None:
        blocks.append(evaluate_file(single_file, max_iters))
    else:
        analog_dir = _pl.analog_dir(project)
        if not analog_dir.is_dir():
            return {"gate": "analog_hil_iteration_cap_check", "verdict": "SKIP",
                    "reason": "no phase3/analog directory", "max_iters": max_iters,
                    "blocks": []}
        reports = sorted(analog_dir.glob("*/hw_tuning_report.json"))
        if not reports:
            return {"gate": "analog_hil_iteration_cap_check", "verdict": "SKIP",
                    "reason": "no hw_tuning_report.json under analog/",
                    "max_iters": max_iters, "blocks": []}
        for rp in reports:
            blocks.append(evaluate_file(rp, max_iters))

    has_error = any(b.verdict == "ERROR" for b in blocks)
    has_fail = any(b.verdict == "FAIL" for b in blocks)
    if has_error:
        overall = "ERROR"
    elif has_fail:
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "gate": "analog_hil_iteration_cap_check",
        "verdict": overall,
        "max_iters": max_iters,
        "blocks": [asdict(b) for b in blocks],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?", default=None)
    ap.add_argument("--file", default=None,
                    help="evaluate a single hw_tuning_report.json directly")
    ap.add_argument("--max-iters", type=int, default=DEFAULT_MAX_HW_ITERS)
    ap.add_argument("--json", default=None, help="write JSON report to this path")
    args = ap.parse_args(argv)

    if args.max_iters < 0:
        print("error: --max-iters must be >= 0", file=sys.stderr)
        return 2

    single = Path(args.file) if args.file else None
    project = Path(args.project_dir).resolve() if args.project_dir else None
    if single is None and project is None:
        print("error: provide <project_dir> or --file <report.json>", file=sys.stderr)
        return 2
    if single is not None and not single.is_file():
        print(f"error: file not found: {single}", file=sys.stderr)
        return 2
    if single is None and not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    report = run(project, single, args.max_iters)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    label = "NOT CHECKED" if verdict == "SKIP" else verdict
    print(f"[{label}] analog_hil_iteration_cap_check (cap={args.max_iters})"
          + (f" — {report.get('reason', 'nothing to count')}"
             if verdict == "SKIP" else ""))
    for b in report["blocks"]:
        print(f"  [{b['verdict']}] block={b['block']} hw_iters={b['hw_iterations']}: {b['reason']}")

    # 0 PASS / 1 FAIL (incl. ERROR) / 2 NOT CHECKED — see the module docstring
    # for the measurement that swapped the ERROR and no-artefact tiers.
    if verdict == "SKIP":
        return 2
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
