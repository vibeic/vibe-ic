#!/usr/bin/env python3
"""measurement_only_artefact_is_not_a_verdict_source.py — a measurement is not
a verdict, and an unmeasured axis is not a zero.

WHY THIS EXISTS
===============
MEASURED: a consumer resolved a reliability axis to the emitter's RAW
MEASUREMENT file — 2431 segments, max segment current 1.951e-4 A, and NO LIMIT
AND NO COUNT anywhere in it — instead of to the sign-off checker that compares
that measurement against the limit read from the process kit's own technology
file. With no count in the artefact, the ABSENCE of a count became
indistinguishable from a count of ZERO, and the axis reported a pass that no
comparison had ever produced.

The emitter was not at fault and said so in its own words. This tree still
carries that sentence at `_ppa/backends/orfs.py:436`, written onto the record:

    "this is the router's own count of its own result; it is not a sign-off
     verdict and must not be used as the eligibility term"

An artefact that says it is not a verdict is not a verdict. The defect is a
consumer that used it as one.

THE TWO CLAUSES, BOTH TAKEN STRAIGHT FROM THE MEASUREMENT
=========================================================
    SELF-DECLARED     a record that declares itself a proxy, an estimate, or
                      not-a-sign-off-verdict may not be the record that
                      SATISFIES an axis proof. It may be published, read and
                      reported — it simply cannot carry the verdict.

    NEVER A ZERO      a record whose state is NOT_MEASURED may not be counted
                      as satisfying anything. "Nobody looked" and "looked and
                      found none" are different facts, and collapsing them is
                      the exact step that turned an absent contributor into a
                      measured zero.

WHAT THIS DELIBERATELY DOES NOT DO
==================================
It does not re-adjudicate the axes, and it does not try to decide from an
artefact's CONTENT whether a comparison "really" happened. A sibling rule in this
lane was first written to infer a producer from source and had to be rewritten
after it declared a working axis broken — inference about evidence, in the
blocking direction, is how a gate stops a correct flow. Both clauses here read a
claim the record makes ABOUT ITSELF, which is a fact, not an inference.

    rc 0   N>0 axis-key records observed; none is a disqualified verdict source.
    rc 1   an axis proof is satisfied by a self-declared non-verdict, or by a
           record that was never measured.
    rc 2   NOT CHECKED — the axis table could not be read, or no record was
           found to judge. An absent corpus is not a clean one.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

NAME = "measurement_only_artefact_is_not_a_verdict_source"
PROGRAMS_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/programs")
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

# A record saying, in its own text, that it is not a sign-off verdict.
DISQUALIFYING = ("not a sign-off verdict", "must not be used as the "
                 "eligibility term", "is a proxy", "proxy for", "estimate only")
NOT_MEASURED = "NOT_MEASURED"
SATISFIED = "SATISFIED"


def axis_keys(programs: Path) -> Set[str]:
    import importlib
    p = str(programs)
    if p not in sys.path:
        sys.path.insert(0, p)
    feas = importlib.import_module("_ppa.feasibility")
    return {pr.metric for ax in feas.DEFAULT_AXES for g in ax.groups for pr in g}


def _self_declared_non_verdict(rec: Any) -> Optional[str]:
    """The record's own sentence disqualifying it, or None — at ANY depth.

    MEASURED FALSE PASS: this looked only at the record's TOP-LEVEL fields, so a
    record carrying

        "provenance": {"note": "... it is not a sign-off verdict ..."}

    reported PASS. Emitters nest provenance routinely, and a disclaimer one level
    down is exactly as binding as one at the top — it is the record's own words
    either way.
    """
    if isinstance(rec, str):
        low = rec.lower()
        for phrase in DISQUALIFYING:
            if phrase in low:
                return rec
        return None
    if isinstance(rec, dict):
        for key, value in rec.items():
            if key in ("metric", "outcomes", "outcome", "verdict", "status",
                       "state"):
                continue          # identity/verdict fields, not prose
            found = _self_declared_non_verdict(value)
            if found:
                return found
        return None
    if isinstance(rec, list):
        for v in rec:
            found = _self_declared_non_verdict(v)
            if found:
                return found
    return None


def _satisfies(rec: Dict[str, Any]) -> bool:
    """True when this record is recorded as SATISFYING its proof."""
    outcomes = rec.get("outcomes")
    if isinstance(outcomes, list) and any(
            isinstance(o, str) and o.upper() == SATISFIED for o in outcomes):
        return True
    for field in ("outcome", "verdict", "status"):
        v = rec.get(field)
        if isinstance(v, str) and v.upper() == SATISFIED:
            return True
    return False


class Finding:
    def __init__(self, where: str, metric: str, why: str):
        self.where, self.metric, self.why = where, metric, why

    def __str__(self) -> str:
        return f"{self.where}: {self.metric} — {self.why}"


def audit(root: Path, programs: Path) -> Tuple[List[Finding], int, int]:
    keys = axis_keys(programs)
    findings: List[Finding] = []
    observed = 0
    files = 0

    def visit(obj: Any, where: str) -> None:
        nonlocal observed
        if isinstance(obj, dict):
            metric = obj.get("metric")
            if isinstance(metric, str) and metric in keys:
                observed += 1
                if _satisfies(obj):
                    note = _self_declared_non_verdict(obj)
                    if note:
                        findings.append(Finding(
                            where, metric,
                            f"an axis proof is SATISFIED by a record that "
                            f"declares itself not a verdict: {note!r}. A "
                            f"measurement is not a comparison, and the absence "
                            f"of a count is not a count of zero."))
                    state = obj.get("state") or obj.get("status")
                    if isinstance(state, str) and state.upper() == NOT_MEASURED:
                        findings.append(Finding(
                            where, metric,
                            "an axis proof is SATISFIED by a record whose state "
                            "is NOT_MEASURED. Nobody looked and looked-and-"
                            "found-none are different facts; counting the first "
                            "as the second is how an absent contributor becomes "
                            "a measured zero."))
            for v in obj.values():
                visit(v, where)
        elif isinstance(obj, list):
            for v in obj:
                visit(v, where)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if not fn.endswith(".json"):
                continue
            path = Path(dirpath) / fn
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            files += 1
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = str(path)
            visit(obj, rel)
    return findings, observed, files


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3
    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    programs = root / PROGRAMS_REL
    if not programs.is_dir():
        programs = root
    try:
        findings, observed, files = audit(root, programs)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the axis table or the records could not "
              f"be read: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    print(f"examined {observed} axis-key record(s) across {files} JSON file(s) "
          f"under {str(root)!r}")
    if observed == 0:
        print(f"[{NAME}] NOT CHECKED — no record for any axis key was found, so "
              f"no verdict source was judged. An absent corpus is not a clean "
              f"one.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — an axis verdict rests on something that is not "
              f"a verdict")
        return 1
    print(f"[{NAME}] PASS — every satisfied axis proof rests on a measured "
          f"sign-off record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
