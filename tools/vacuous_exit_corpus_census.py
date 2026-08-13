#!/usr/bin/env python3
"""How many PUBLISHED runs change verdict when a gate's refusal changes channel.

WHY THIS EXISTS (vibe-ic#1052)
==============================
`_vacuous_exit` repairs move a refusal from a laundered `return 0` onto the
disclosed rc-2 tier. The repair is right and it is cheap to write. What is NOT
cheap, and what has twice been discovered at the wrong moment, is its effect on
the CORPUS: every published run whose record says PASS because the gate examined
nothing now says VACUOUS_PASS instead.

#1018 hit 92 published run directories. #1052 asked for the same number for its
own four clauses BEFORE landing them, in its own words: *"That needs its own
corpus census and its own two-arm control, not a rider on the instrument that
found it."* Nothing in the repo could answer it, so it was answered by hand — and
a number produced by hand once is a number nobody can reproduce after the tree
moves. This is that measurement, executing.

MEASURED at `947547716` (v1.10.33) against #1055's four commits:

    133 published run director(ies) x 4 clause(s) = 532 (run,clause) pair(s)
      verdict MOVED : 267      verdict SAME : 265      NOT MEASURED : 0
      published run dir(s) with at least one moved verdict: 129 of 133

    every one of the 267 transitions was rc 0 -> rc 2

**129, not the 92 this issue cited from #1018.** #1018's figure was for a
different clause set and does not carry over; sizing a landing from it is low by
roughly 40%. That is the whole reason this is a program and not a paragraph.

WHAT IT IS NOT
==============
It is a REPORTER. It asserts nothing about which verdict is correct, it does not
decide whether the moved records should be regenerated, and it never rewrites a
published artefact. It answers one question — *how many, and which* — and exits 0
having answered it. rc 2 is reserved for "I could not measure", never for "I
measured and did not like the answer".

THE CLAUSE SET IS AN ARGUMENT, NOT A LIST IN THIS FILE
======================================================
Deliberately. A hard-coded roster of gate names is the shape that rots the first
time a gate is added or renamed, and this repo has paid for that twice
(`ci_targeted_test_select`'s tools/ hole, vibe-ic#1057). The caller names the
clauses it is landing; the tool answers for exactly those, and PRINTS the set it
was handed so a verdict can never be read as covering more than it did.

DEGRADING LOUDLY
================
A zero denominator REFUSES (rc 2). "0 published runs move" and "there were no
published runs to ask about" are opposite facts and must never share an exit
code. Any clause that cannot be executed in either arm is counted as NOT
MEASURED and named — never silently folded into SAME.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_OK = 0
RC_UNMEASURABLE = 2

#: Per-invocation bound. The clauses this exists for answer in well under a
#: second on a run directory; anything slower is a hang, and a hang inside a
#: census is indistinguishable from a verdict unless it is bounded and named.
#: 55s, not 60+: `ci_harness_timeout_ceiling_check` refuses any inner bound
#: above 60s, because the pytest harness kills at 180s and an inner bound that
#: can outlive it takes the SESSION down instead of the measurement.
_TIMEOUT_S = 55

_PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"


def published_run_dirs(root: Path) -> List[Path]:
    """Every published run directory: the parent of a `reports/` folder.

    Keyed on the shape the corpus actually has rather than on a manifest, for
    the reason the docstring gives about rosters: a manifest of run directories
    is one more thing that has to be remembered.
    """
    data = root / "benchmark-data"
    if not data.is_dir():
        return []
    return sorted({p.parent for p in data.rglob("reports") if p.is_dir()})


def clause_rc(worktree: Path, clause: str, subject: Path) -> Optional[int]:
    """Exit code of `clause` over `subject`, or None if it could not be run."""
    plugin = worktree / _PLUGIN_REL
    script = plugin / "programs" / f"{clause}.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script.relative_to(plugin)), str(subject)],
            cwd=str(plugin), capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode


def census(red: Path, green: Path, clauses: Sequence[str]) -> Dict:
    subjects = published_run_dirs(red)
    moved: List[Tuple[str, str, int, int]] = []
    same = 0
    unmeasured: List[Tuple[str, str]] = []
    per_clause = {c: 0 for c in clauses}

    for subject in subjects:
        rel = str(subject.relative_to(red))
        for clause in clauses:
            a = clause_rc(red, clause, subject)
            b = clause_rc(green, clause, subject)
            if a is None or b is None:
                unmeasured.append((rel, clause))
                continue
            if a != b:
                moved.append((rel, clause, a, b))
                per_clause[clause] += 1
            else:
                same += 1

    return {
        "subjects": len(subjects),
        "clauses": list(clauses),
        "pairs": len(subjects) * len(clauses),
        "moved": moved,
        "same": same,
        "unmeasured": unmeasured,
        "per_clause": per_clause,
        "runs_moved": sorted({m[0] for m in moved}),
    }


def render(rep: Dict) -> List[str]:
    out = [
        f"[INFO] clause set under census ({len(rep['clauses'])}): "
        f"{', '.join(rep['clauses'])}",
        f"CORPUS CENSUS — {rep['subjects']} published run director(ies) "
        f"x {len(rep['clauses'])} clause(s) = {rep['pairs']} (run,clause) pair(s)",
        f"  verdict MOVED : {len(rep['moved'])}",
        f"  verdict SAME  : {rep['same']}",
        f"  NOT MEASURED  : {len(rep['unmeasured'])}",
    ]
    for clause, n in rep["per_clause"].items():
        out.append(f"    {clause:42} moved {n}")
    transitions: Dict[Tuple[int, int], int] = {}
    for _, _, a, b in rep["moved"]:
        transitions[(a, b)] = transitions.get((a, b), 0) + 1
    for (a, b), n in sorted(transitions.items()):
        out.append(f"  rc {a} -> rc {b} : {n} pair(s)")
    out.append(f"  published run dir(s) with at least one moved verdict: "
               f"{len(rep['runs_moved'])} of {rep['subjects']}")
    for name, clause in rep["unmeasured"][:20]:
        out.append(f"  [NOT MEASURED] {clause} over {name}")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--red", required=True, type=Path,
                    help="worktree WITHOUT the change (usually origin/main)")
    ap.add_argument("--green", required=True, type=Path,
                    help="worktree WITH the change applied")
    ap.add_argument("--clause", action="append", default=[], metavar="NAME",
                    help="a programs/<NAME>.py to census; repeatable, required")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    if not args.clause:
        sys.stderr.write(
            "NOT_MEASURED: no --clause given. This tool answers for the clause "
            "set it is handed and never guesses one, because a roster in the "
            "tool is the thing that rots.\n")
        return RC_UNMEASURABLE

    rep = census(args.red, args.green, args.clause)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, indent=1), encoding="utf-8")

    if rep["subjects"] == 0:
        sys.stderr.write(
            f"NOT_MEASURED: 0 published run director(ies) under "
            f"{args.red / 'benchmark-data'}. A census over an empty corpus "
            f"reports 0 moved for the same reason it reports 0 anything, and "
            f"that is NOT the same fact as 'this change moves nothing'.\n")
        return RC_UNMEASURABLE

    for line in render(rep):
        print(line)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
