#!/usr/bin/env python3
"""A step the evaluator never receives cannot fail — and never appears.

THIS GATE BLOCKS (rc=1) when a declared flow step is absent from the tally.

WHY THIS EXISTS
===============
Matrix dimension D1 (`wiring`) publishes the claim "does something real parse
and execute this gate?". MEASURED (mutation probe, plugin v1.12.33): its
observation point sits INSIDE `_evaluate_gate`, and the test hands
`_evaluate_gate` the gate dict itself. The caller is supplied by the test, so
the caller can never be wrong.

    MUT-A  a gate names a program with no matching file      -> RED, correctly.
    MUT-B  remove what hands the executor its gate dict for
           step 21                                           -> GREEN, 86 passed.

MUT-B's behaviour is not subtle. On a real project the step vanishes from the
tally, from the per-step listing and from the blocker list; MISSING drops
40 -> 39, and 18 steps that were blocked-by-upstream silently unblock. The
matrix reads BETTER after the step stopped being evaluated, because a step
nobody evaluates contributes no failure.

D1 asks whether the walk INSIDE the executor is complete. This asks the seam
one level above: does every step the flow declares actually REACH the
executor? Neither question implies the other, and only this one dies when the
call site does.

HOW IT DECIDES
==============
It reads the step ids the flow declares, runs the SUBJECT tree's own
`flow_compliance_check` against a throwaway stub project (read-only, lenient
— the verdicts do not matter, only the census does), and compares the two
sets. A declared id absent from the tally is the finding. An id in the tally
that the flow does not declare is reported too: a tally that invents steps is
the same defect mirrored.

It deliberately does NOT assert anything about the verdicts. On a stub project
almost every gate legitimately skips; requiring a verdict would make this a
test of the fixture instead of the wiring.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

FLOW_REL = "vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml"
CHECK_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py"


def declared_step_ids(flow_path: Path) -> Set[str]:
    import yaml
    data = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    return {str(s.get("id")) for s in (data or {}).get("steps") or []
            if s.get("id") is not None}


def evaluated_step_ids(root: Path, timeout: int = 600) -> Tuple[Set[str], str]:
    """The ids the SUBJECT tree's evaluator actually reports, plus its stderr.

    The evaluator run is the subject's own copy, never this file's neighbour:
    a wiring gate that judged the runtime's evaluator would pass on a tree
    whose evaluator is broken, which is the ordering defect this repo has
    already paid for once.
    """
    checker = root / CHECK_REL
    if not checker.is_file():
        raise FileNotFoundError(f"{CHECK_REL} is not present under {root}")
    with tempfile.TemporaryDirectory(prefix="step-reach-") as tmp:
        project = Path(tmp) / "stub"
        (project / "input" / "docs").mkdir(parents=True)
        (project / "input" / "docs" / "design_description.md").write_text(
            "stub project — this gate reads the census, never the verdicts\n")
        out = Path(tmp) / "compliance.json"
        proc = subprocess.run(
            [sys.executable, str(checker), str(project), "--lenient",
             "--read-only", "--json", str(out)],
            capture_output=True, text=True, timeout=timeout)
        if not out.is_file():
            raise RuntimeError(
                f"the evaluator produced no census (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[-800:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    return {str(s.get("id")) for s in data.get("steps") or []}, proc.stderr


def audit(root: Path) -> dict:
    flow = root / FLOW_REL
    if not flow.is_file():
        raise FileNotFoundError(f"{FLOW_REL} is not present under {root}")
    declared = declared_step_ids(flow)
    evaluated, _ = evaluated_step_ids(root)
    return {
        "declared": len(declared),
        "evaluated": len(evaluated),
        "unreached": sorted(declared - evaluated),
        "uninvited": sorted(evaluated - declared),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".",
                    help="the SUBJECT tree to judge (its flow and its evaluator)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        report = audit(root)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"CANNOT CHECK: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['declared']} step(s) declared, "
              f"{report['evaluated']} reached the evaluator, under {root}")
        for sid in report["unreached"]:
            print(f"  [UNREACHED] step {sid} is declared by the flow and never "
                  f"handed to the evaluator — it can only ever be silent")
        for sid in report["uninvited"]:
            print(f"  [UNINVITED] step {sid} is in the tally and not in the flow")
        bad = report["unreached"] + report["uninvited"]
        print("PASS" if not bad else f"FAIL: {len(bad)} step(s) out of step")

    return 1 if (report["unreached"] or report["uninvited"]) else 0


if __name__ == "__main__":
    sys.exit(main())
