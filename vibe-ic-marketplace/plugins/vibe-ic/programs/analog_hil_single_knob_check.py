#!/usr/bin/env python3
"""analog_hil_single_knob_check.py — one-knob-per-iteration discipline.

The analog-hw-tuning-loop skill states: "Do not adjust more than 1 component per
hardware iteration — debugging is harder than in SPICE." That is a deterministic
diff of the sizing snapshots recorded across consecutive hardware iterations: if
more than one device parameter (W / L / M, or any sizing key) changed between
iteration N and N+1, the discipline was violated.

Input: a per-block sizing-history file recording the device sizing AS APPLIED at
each hardware iteration. Default path analog/<block>/hw_sizing_history.json, or a
single file via --file. Shape:

    {
      "block_name": "ldo_1v8",
      "iterations": [
        { "iter": 1, "sizing": {"M1": {"W": 4.0, "L": 0.5, "M": 2},
                                "M2": {"W": 8.0, "L": 0.5, "M": 1}, "Rfb": 50000} },
        { "iter": 2, "sizing": {"M1": {"W": 4.0, "L": 0.5, "M": 2},
                                "M2": {"W": 8.0, "L": 0.5, "M": 1}, "Rfb": 52000} },
        ...
      ]
    }

A "knob" is a single (device, parameter) leaf — e.g. ("M1","W"), ("Rfb",) for a
scalar. Between two consecutive iterations the program counts the number of leaves
whose value changed (added / removed / numerically differing). > 1 changed leaf →
FAIL for that step.

PASS  iff every consecutive-iteration transition changed at most ONE knob.
FAIL  iff any transition changed two or more knobs (the real defect this catches:
      multi-knob bench edits that make a HW regression un-bisectable), OR a
      history file exists but its iterations / sizing structure is malformed —
      a garbage file must not vacuously pass.
NOT CHECKED (exit 2) iff there are no history files, or every block has < 2
      iterations (nothing to diff).

EXIT-CODE CONTRACT (repaired — the two tiers used to be the wrong way round)
---------------------------------------------------------------------------
Same measurement as `analog_hil_iteration_cap_check`: exit 2 is the consumer's
CANNOT-JUDGE tier — `flow_compliance_check.__check_program_exit_zero` maps it to
`__VACUOUS_HINT__` and returns True (counted as a pass), and the advisory slot
renders it "n/a (input not present)". Returning 2 for a malformed history made
"this file is garbage" indistinguishable from "there is no such file", and both
read as a pass. So:
    * malformed history file   -> 1 (a defect, and it blocks)
    * nothing to diff          -> 2 (disclosed cannot-judge)

Usage:
    python3 analog_hil_single_knob_check.py <project_dir> [--json <out>]
    python3 analog_hil_single_knob_check.py --file <history.json> [--json <out>]

Exit codes:
    0  PASS
    1  FAIL (a transition changed >1 knob, or a malformed history file)
    2  NOT CHECKED (no history / nothing to diff) / argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl


def _flatten(sizing: dict, prefix: str = "") -> Dict[str, object]:
    """Flatten a nested sizing dict into {device.param: value} leaves."""
    flat: Dict[str, object] = {}
    for k, v in sizing.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            flat.update(_flatten(v, key))
        else:
            flat[key] = v
    return flat


def _changed_knobs(prev: Dict[str, object], cur: Dict[str, object]) -> List[str]:
    changed: List[str] = []
    for key in set(prev) | set(cur):
        a = prev.get(key, "__absent__")
        b = cur.get(key, "__absent__")
        if a != b:
            changed.append(key)
    return sorted(changed)


@dataclass
class StepDiff:
    from_iter: object
    to_iter: object
    changed_knobs: List[str]
    n_changed: int
    verdict: str       # PASS / FAIL


@dataclass
class BlockKnob:
    block: str
    source: str
    verdict: str       # PASS / FAIL / SKIP / ERROR
    steps: List[StepDiff] = field(default_factory=list)
    reason: str = ""


def evaluate_file(path: Path) -> BlockKnob:
    block_name = path.parent.name
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return BlockKnob(block=block_name, source=str(path), verdict="ERROR",
                         reason="unreadable / malformed JSON")
    if not isinstance(data, dict):
        return BlockKnob(block=block_name, source=str(path), verdict="ERROR",
                         reason="top-level JSON is not an object")
    block = data.get("block_name") or data.get("block") or block_name
    iters = data.get("iterations")
    if not isinstance(iters, list):
        return BlockKnob(block=block, source=str(path), verdict="ERROR",
                         reason="iterations field missing or not a list")
    # Build flattened sizing per iteration; reject malformed entries.
    snaps: List[Tuple[object, Dict[str, object]]] = []
    for it in iters:
        if not isinstance(it, dict) or not isinstance(it.get("sizing"), dict):
            return BlockKnob(block=block, source=str(path), verdict="ERROR",
                             reason="an iteration is missing a sizing object")
        snaps.append((it.get("iter"), _flatten(it["sizing"])))
    if len(snaps) < 2:
        return BlockKnob(block=block, source=str(path), verdict="SKIP",
                         reason=f"only {len(snaps)} iteration(s); nothing to diff")

    steps: List[StepDiff] = []
    any_fail = False
    for (i_prev, prev), (i_cur, cur) in zip(snaps, snaps[1:]):
        changed = _changed_knobs(prev, cur)
        v = "FAIL" if len(changed) > 1 else "PASS"
        if v == "FAIL":
            any_fail = True
        steps.append(StepDiff(from_iter=i_prev, to_iter=i_cur,
                              changed_knobs=changed, n_changed=len(changed),
                              verdict=v))
    reason = ("a transition changed >1 knob" if any_fail
              else "every transition changed <=1 knob")
    return BlockKnob(block=block, source=str(path),
                     verdict="FAIL" if any_fail else "PASS",
                     steps=steps, reason=reason)


def run(project: Optional[Path], single_file: Optional[Path]) -> dict:
    blocks: List[BlockKnob] = []
    if single_file is not None:
        blocks.append(evaluate_file(single_file))
    else:
        analog_dir = _pl.analog_dir(project)
        if not analog_dir.is_dir():
            return {"gate": "analog_hil_single_knob_check", "verdict": "SKIP",
                    "reason": "no phase3/analog directory", "blocks": []}
        hist = sorted(analog_dir.glob("*/hw_sizing_history.json"))
        if not hist:
            return {"gate": "analog_hil_single_knob_check", "verdict": "SKIP",
                    "reason": "no hw_sizing_history.json under analog/", "blocks": []}
        for hp in hist:
            blocks.append(evaluate_file(hp))

    has_error = any(b.verdict == "ERROR" for b in blocks)
    has_fail = any(b.verdict == "FAIL" for b in blocks)
    if has_error:
        overall = "ERROR"
    elif has_fail:
        overall = "FAIL"
    elif all(b.verdict == "SKIP" for b in blocks):
        overall = "SKIP"
    else:
        overall = "PASS"
    return {
        "gate": "analog_hil_single_knob_check",
        "verdict": overall,
        "blocks": [asdict(b) for b in blocks],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?", default=None)
    ap.add_argument("--file", default=None,
                    help="evaluate a single hw_sizing_history.json directly")
    ap.add_argument("--json", default=None, help="write JSON report to this path")
    args = ap.parse_args(argv)

    single = Path(args.file) if args.file else None
    project = Path(args.project_dir).resolve() if args.project_dir else None
    if single is None and project is None:
        print("error: provide <project_dir> or --file <history.json>", file=sys.stderr)
        return 2
    if single is not None and not single.is_file():
        print(f"error: file not found: {single}", file=sys.stderr)
        return 2
    if single is None and not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    report = run(project, single)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    label = "NOT CHECKED" if verdict == "SKIP" else verdict
    print(f"[{label}] analog_hil_single_knob_check"
          + (f" — {report.get('reason', 'nothing to diff')}"
             if verdict == "SKIP" else ""))
    for b in report["blocks"]:
        print(f"  [{b['verdict']}] block={b['block']}: {b['reason']}")
        for s in b.get("steps", []):
            if s["verdict"] == "FAIL":
                print(f"      iter {s['from_iter']}→{s['to_iter']} changed "
                      f"{s['n_changed']} knobs: {s['changed_knobs']}")

    # 0 PASS / 1 FAIL (incl. ERROR) / 2 NOT CHECKED — see the module docstring
    # for the measurement that swapped the ERROR and no-artefact tiers.
    if verdict == "SKIP":
        return 2
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
