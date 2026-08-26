#!/usr/bin/env python3
"""coverage_closure.py — coverage GAP ANALYSIS over the MEASURED artefact.

ENFORCEMENT: advisory

Reads the declared coverage MEASUREMENT
(``reports/phase2/coverage/coverage_verilator.json``) and reports which
measured categories sit below the closure goal. It is a GAP ANALYSIS, not the
floor: the blocking coverage floor for Step 4 is
``verilator_coverage_measure check``, wired unconditionally in the same gate
with its own thresholds, and reading the SAME artefact.

PATH: this used to read ``coverage/coverage_actual.json``, which has a second
producer — ``design_one_shot_runner`` writes a functional-verdict payload
there. Reading a path with two producers is why all 27 tracked artefacts
classified ``foreign``. The measurement now has its own path,
``verilator_coverage_measure.COVERAGE_MEASUREMENT_REL``, and this program
follows it.

WHAT IT READS — the real schema, measured
-----------------------------------------
``verilator_coverage_measure measure`` is the only producer of a coverage
MEASUREMENT at that path, and it writes::

    {"tool": "verilator", "coverage_dat": "...", "totals": {
        "line":   {"covered": .., "total": .., "pct": ..},
        "toggle": {"covered": .., "total": .., "pct": ..},
        "branch": {"covered": .., "total": .., "pct": ..}}}

This program used to read ``d.get("coverage_pct") or d.get("pct") or 0``.
Neither key exists in that payload, so ``or 0`` reported ``0% < 80%`` for a
genuine measurement — reproduced on a real 95/92/91 % artefact — while a bare
``{"coverage_pct": 95}`` with no measurement behind it reported ``[PASS] 95%``.
The check was inverted in BOTH directions: it FAILED real coverage and PASSED
a coverage CLAIM. It also reported ``0% < 80%`` against the live
spm x ihp-sg13g2 run, whose artefact at that path is a functional-verdict
payload written by ``design_one_shot_runner`` — i.e. it turned "nothing was
measured here" into a specific, false number.

Classification is delegated to
``verilator_coverage_measure.classify_coverage_artefact`` so this program and
the blocking Step-4 gate can never disagree about what sits at the shared path.

WHICH HALF THE CORPUS ACTUALLY WITNESSES — stated so neither is oversold
------------------------------------------------------------------------
Measured over ALL 27 tracked ``reports/phase2/coverage/coverage_actual.json``
in ``benchmark-data`` (the full tracked population, not a sample):

  * FAILED-A-REAL-MEASUREMENT direction — WITNESSED 27/27. Every one of the 27
    classifies ``foreign``, and every one produced
    ``[FAIL] coverage_closure: 0% < 80%`` rc=1 on origin/main. That is the
    invented number this change removes; they now answer rc=2.
  * PASSED-A-FORGERY direction — WITNESSED 0/27. NOT ONE of the 27 carries a
    ``coverage_pct`` or ``pct`` key, so no published run ever took the
    ``[PASS] 95%`` path. That direction is real in the code and reproducible
    on a fixture, but it has ZERO tracked population; it is fixture-only
    evidence and must not be cited as a corpus finding.

EXIT CODES
----------
    0  every measured category is at or above the closure goal
    1  a measured category is below the goal, OR the artefact at the declared
       path is corrupt / malformed / a forged coverage CLAIM
    2  no coverage MEASUREMENT exists at the path — nothing there (``absent``)
       or a payload another producer owns (``foreign``). Disclosed, never
       certified: ``flow_compliance_check`` renders rc=2 as a VACUOUS / "n/a"
       disclosure rather than a clean result. Deciding whether a missing
       measurement BLOCKS is not this program's job — that belongs to
       ``verilator_coverage_measure check``, which distinguishes "Verilator
       absent" (rc=3, named capability gap) from "Verilator present and never
       run" (rc=1).

chip-AGNOSTIC: no design / PDK / vendor literal; keys off the artefact only.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import _path_layout as _pl
from verilator_coverage_measure import (COVERAGE_MEASUREMENT_REL,
                                        classify_coverage_artefact)

#: The closure GOAL this gap analysis reports against. Deliberately higher than
#: the blocking floor in `verilator_coverage_measure check` (70/60/70): a gap
#: analysis names what is left to close, the floor names what may not ship.
DEFAULT_GOAL = 80.0

#: Categories a Verilator measurement carries. Absent ones are not invented.
CATEGORIES = ("line", "toggle", "branch")


def analyse(project: Path, goal: float = DEFAULT_GOAL) -> Tuple[int, List[str]]:
    """Return ``(exit_code, lines)`` for ``project``.

    Kept separate from ``main`` so tests can drive the decision directly
    instead of scraping stdout.
    """
    cov = _pl.report_path(project, COVERAGE_MEASUREMENT_REL)
    kind, detail, data = classify_coverage_artefact(cov)

    if kind in ("absent", "foreign"):
        # No measurement to analyse gaps in. Say so; do NOT invent a 0%.
        return 2, [
            f"[SKIP] coverage_closure: {detail}",
            f"VACUOUS_PASS: coverage_closure — no coverage MEASUREMENT at "
            f"{cov} ({kind}), so there are no gaps to analyse. This is a "
            f"DISCLOSED skip, not a coverage result; whether the missing "
            f"measurement blocks is decided by "
            f"`verilator_coverage_measure check`.",
        ]
    if kind != "measured":
        # corrupt / malformed / forged — a defect, never an exemption.
        return 1, [f"[FAIL] coverage_closure: {kind}: {detail}"]

    totals = data.get("totals") or {}
    measured: List[str] = []
    gaps: List[str] = []
    for cat in CATEGORIES:
        entry = totals.get(cat)
        pct = entry.get("pct") if isinstance(entry, dict) else None
        if pct is None:
            continue
        measured.append(f"{cat}={pct}%")
        if float(pct) < goal:
            gaps.append(f"{cat} {pct}% < {goal}%")

    if not measured:
        return 1, [
            f"[FAIL] coverage_closure: `totals` carries none of "
            f"{list(CATEGORIES)} — nothing measurable at {cov}"
        ]
    if gaps:
        return 1, [
            f"[FAIL] coverage_closure: gaps vs {goal}% goal: "
            + "; ".join(gaps),
            "        measured: " + " ".join(measured),
        ]
    return 0, ["[PASS] coverage_closure: " + " ".join(measured)
               + f" (goal {goal}%)"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project", type=Path)
    p.add_argument("--goal", type=float, default=DEFAULT_GOAL,
                   help=f"closure goal per category, %% (default {DEFAULT_GOAL})")
    args = p.parse_args(argv)
    rc, lines = analyse(args.project, args.goal)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
