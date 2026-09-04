#!/usr/bin/env python3
"""step_metrics_adoption_check.py — the one metrics schema, and who still is not
using it.

ENFORCEMENT: BLOCKING on the DELTA. A step that gains a program and does not
emit through `step_metrics` FAILS; the 46 steps that never did are recorded as a
residual and reported by name every run. The ratchet shape is
`atomic_artifact_write_check`'s, because it is the shape that has worked in this
tree: a 46-step sweep nobody can review would be waived wholesale, and a gate
that fires on everything gets read as noise.

WHAT IS ALREADY BUILT, AND WHY THIS IS NOT ANOTHER MECHANISM
============================================================
`step_metrics.py` already IS the unified schema, adopted from
OpenROAD-flow-scripts, and its own docstring states the problem it was written
for:

    We had 63 declared step entries, 62 carrying a gate, many writing
    `--json reports/.../xxx.json`, and every checker chose its own shape.
    Measured on v1.10.32: `ls programs/ | grep -iE "metric|qor"` returns no
    per-step QoR aggregator and nothing computes a run-to-run delta.

It diagnosed the disease and shipped the cure. MEASURED 2026-09-04: of the 50
flow steps that declare programs, **4 emit through it**. Adoption is 8 %.

So nothing here invents a schema. This measures who uses the one that exists,
and stops the number going backwards.

WHY "RUN-TO-RUN DIFF" IS THE POINT, NOT TIDINESS
================================================
ORFS gets `is this run better or worse than the last one` from one `diff`
because every stage writes flat, fixed-prefix keys into one file. At 8 %
adoption that question is answered by reading prose across a dozen differently
shaped JSONs — which is how a 393-violation DRC run and a 0-violation one were
compared by hand, and how a `0` that meant "nothing was measured" was read as
"nothing was wrong".

WHAT COUNTS AS ADOPTION
=======================
A step counts when at least one program it DECLARES imports `step_metrics`. Not
"a metrics file exists" — a file can exist and be written by something else —
and not "the program name contains metric", which is a name, not a behaviour.

exit 0 = PASS         no step regressed; the residual is reported by name
exit 1 = FAIL         a step that emitted stopped, or a new step declares
                      programs and emits nothing
exit 2 = NOT CHECKED  the flow or the programs directory could not be read
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

ATTRIBUTION = "step_metrics_adoption_check"
MODULE = "step_metrics"
BASELINE_REL = "_step_metrics_adoption_residual.json"


def emitting_programs(programs_dir: Path) -> Set[str]:
    """Program stems that import the shared emitter.

    IMPORT, not filename. `coverage_metric_check` carries the word and
    `placement_legality_check` does not; only one of them is the question.
    """
    out: Set[str] = set()
    for f in sorted(programs_dir.glob("*.py")):
        if f.stem == MODULE:
            continue
        try:
            src = f.read_text(errors="replace")
        except OSError:
            continue
        if f"import {MODULE}" in src or f"from {MODULE}" in src:
            out.add(f.stem)
    return out


def steps_with_programs(flow_yaml: Path) -> List[Tuple[str, List[str]]]:
    try:
        import yaml
    except ImportError:
        return []
    try:
        doc = yaml.safe_load(flow_yaml.read_text())
    except (OSError, ValueError):
        return []
    steps: List[Tuple[str, List[str]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "programs" in node:
                steps.append((str(node["id"]),
                              [str(x) for x in (node["programs"] or [])]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(doc)
    return steps


def audit(plugin_dir: Path) -> Dict[str, Any]:
    programs_dir = plugin_dir / "programs"
    steps = steps_with_programs(
        plugin_dir / "flow" / "phase1_phase2_phase3.yaml")
    emitters = emitting_programs(programs_dir)
    adopted, missing = [], []
    for sid, progs in steps:
        (adopted if any(p in emitters for p in progs) else missing).append(sid)
    return {
        "program": ATTRIBUTION,
        "steps_declaring_programs": len(steps),
        "adopted": sorted(set(adopted)),
        "not_yet": sorted(set(missing)),
        "adoption_percent": (100 * len(set(adopted)) // len(steps)) if steps
        else 0,
        "emitting_programs": sorted(emitters),
    }


def _load_baseline(path: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and "not_yet" in doc else None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plugin_dir", nargs="?", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--write-residual", action="store_true",
                    help="record TODAY's residual as the baseline. Legitimate "
                         "only when there is none: it can lower the bar for "
                         "everyone, so it never runs by accident.")
    args = ap.parse_args(argv)

    pdir = Path(args.plugin_dir) if args.plugin_dir else _HERE.parent
    rep = audit(pdir)
    if not rep["steps_declaring_programs"]:
        print(f"NOT CHECKED: no step under {pdir} declares programs — the "
              f"flow was unreadable, and an unreadable population must not "
              f"read as a population of zero.", file=sys.stderr)
        return 2

    bl_path = Path(args.baseline) if args.baseline \
        else pdir / "programs" / BASELINE_REL
    baseline = _load_baseline(bl_path)

    if baseline is None and args.write_residual:
        atomic_write_text(bl_path, json.dumps(
            {"not_yet": rep["not_yet"], "adopted": rep["adopted"],
             "recorded_by": ATTRIBUTION}, indent=2) + "\n", encoding="utf-8")
        print(f"recorded the residual at {bl_path}: {len(rep['not_yet'])} step(s) "
              f"do not emit through {MODULE}")
        baseline = _load_baseline(bl_path)

    if args.json_out:
        atomic_write_text(Path(args.json_out),
                          json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    if baseline is None:
        print(f"NOT CHECKED: no residual baseline at {bl_path} — "
              f"{len(rep['not_yet'])} of {rep['steps_declaring_programs']} "
              f"step(s) do not emit through {MODULE}, but with nothing to "
              f"compare against none of them can be called NEW. Record it with "
              f"--write-residual.", file=sys.stderr)
        return 2

    was_adopted = set(baseline.get("adopted") or [])
    now_adopted = set(rep["adopted"])
    regressed = sorted(was_adopted - now_adopted)
    new_missing = sorted(set(rep["not_yet"]) - set(baseline.get("not_yet") or []))

    print(f"{ATTRIBUTION}: {len(now_adopted)} of "
          f"{rep['steps_declaring_programs']} step(s) emit through {MODULE} "
          f"({rep['adoption_percent']}%)")
    if rep["not_yet"]:
        print(f"  residual, not yet emitting ({len(rep['not_yet'])}): "
              + ", ".join(rep["not_yet"][:12])
              + (" …" if len(rep["not_yet"]) > 12 else ""))
    if regressed:
        print(f"[FAIL] {len(regressed)} step(s) STOPPED emitting through "
              f"{MODULE}: {', '.join(regressed)}", file=sys.stderr)
    if new_missing:
        print(f"[FAIL] {len(new_missing)} step(s) declare programs and emit "
              f"nothing, and are not in the residual: "
              f"{', '.join(new_missing)}", file=sys.stderr)
    if regressed or new_missing:
        return 1
    print(f"[PASS] no step regressed; the residual is named above and is the "
          f"work, not the verdict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
