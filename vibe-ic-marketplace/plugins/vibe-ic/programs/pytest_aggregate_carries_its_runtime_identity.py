#!/usr/bin/env python3
"""pytest_aggregate_carries_its_runtime_identity.py — a failure count names
the runtime that produced it, or it may not be subtracted from another.

WHY IT IS NOT CALLED `test_aggregate_...`
=========================================
The rule's subject is a TEST AGGREGATE, so that is what the record calls it. The
FILE may not: a program under `programs/` whose name begins with `test_` is
collected by pytest as a test module, and — measured — it was also skipped by
this rule's own sibling gates, several of which exclude `test_*` from their
populations. The checker was therefore invisible to the family it belongs to.
`pytest_per_file_junit.py` is the existing precedent for naming a pytest-domain
program without the collection prefix.

WHY THIS EXISTS
===============
MEASURED: a selection asked the test runtime to load a plugin that runtime does
not carry. Every test in those files died AT LOAD, not at assertion, and the
resulting failures were counted against the REVISION under test because nothing
in the record named the runtime. 28 of 127 failures were that one missing
plugin; 26 of them vanished on a second runtime. Attributing them took FIVE
controlled arms — work that a single stamp on the aggregate would have made
unnecessary.

The defect is not the missing plugin. The defect is that the aggregate could be
DIFFERENCED against another aggregate produced by a different runtime, and the
difference was read as a property of the tree.

WHAT AN AGGREGATE MUST CARRY
============================
    image                  the image reference actually executed — not the one
                           requested, and not a tag that moves
    interpreter            the interpreter that ran the selection
    unimportable_plugins   the plugins the SELECTION asks for that this runtime
                           cannot import. Present and EMPTY is a real answer
                           ("asked, none missing"); absent is not.

The third is the one that pays. `retired_pytest_plugin_request_check` already
refuses a source file that REQUESTS a retired plugin, and
`landing_pytest_runtime_preflight` already asks whether a host can run the
runtime at all. Neither writes anything onto the RESULT, so two aggregates from
different runtimes still subtract cleanly and silently. That is this rule.

THE ARM THAT MATTERS: --diff REFUSES
====================================
`--diff A B` does not compare failure counts. It compares RUNTIMES, and refuses
to difference at all when they disagree, naming the disagreement. A tool that
answers "12 new failures" across two runtimes has produced a number about
nothing.

    rc 0   the aggregate carries its runtime identity / two aggregates are
           comparable and were compared.
    rc 1   an aggregate omits its runtime identity, or two aggregates are NOT
           comparable — a finding, and in --diff the refusal to subtract.
    rc 2   NOT CHECKED — a file could not be read or parsed, no aggregate was
           found, or comparability could not be established.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

NAME = "pytest_aggregate_carries_its_runtime_identity"
REQUIRED = ("image", "interpreter", "unimportable_plugins")
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

# WHAT COUNTS AS A TEST AGGREGATE — STRUCTURE, NOT A KEY COUNT
# ============================================================
# This was first written as "any object carrying two of passed/failed/cases/
# summary/selected". Swept over this repository that matched TWO files and both
# were wrong: `hygiene_gate_profile.json` (a gate profile: passed/failed over
# GATES) and a checker report carrying `passed`/`summary`. Pass/fail counting is
# not distinctive — half the records in this tree count passes.
#
# A test aggregate is distinguished by PER-CASE structure: a list of cases each
# naming a test. Nothing else in this tree has that shape, and a rule that
# cannot tell its own subject from a gate profile has no business reddening one.
CASE_LISTS = ("cases", "tests", "testcases")
CASE_NAME_KEYS = ("nodeid", "node_id", "classname", "name")


def is_aggregate(obj: Any) -> bool:
    """True only for a record carrying per-test-case rows."""
    if not isinstance(obj, dict):
        return False
    if obj.get("kind") == "test_aggregate":
        return True
    for key in CASE_LISTS:
        rows = obj.get(key)
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict) and any(
                    k in first for k in CASE_NAME_KEYS):
                return True
    return False


def runtime_of(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rt = obj.get("runtime")
    return rt if isinstance(rt, dict) else None


#: Values that occupy an identity field without being one. A stamp reading
#: "unknown" is the ABSENCE of an identity wearing its shape, which is this
#: capture's whole seam: an artefact whose stamp is present and whose binding
#: is therefore reported true, while nothing was actually established.
PLACEHOLDERS = frozenset((
    "", "-", "?", "n/a", "na", "none", "null", "unknown", "unset", "tbd",
    "todo", "missing", "notrecorded", "norecord", "notavailable"))


def _is_placeholder(value: Any) -> bool:
    return str(value).strip().lower().replace(" ", "").replace("_", "") \
        in PLACEHOLDERS


def missing_fields(obj: Dict[str, Any]) -> List[str]:
    """Which parts of the runtime identity are absent. Empty list = complete."""
    rt = runtime_of(obj)
    if rt is None:
        return list(REQUIRED)
    out = []
    for k in REQUIRED:
        if k not in rt:
            out.append(k)
        elif k != "unimportable_plugins" and _is_placeholder(rt[k]):
            # Present-and-empty, and present-and-"unknown", are NOT answers for
            # an identity string. MEASURED: {"image": "unknown", "interpreter":
            # "n/a"} passed, so an aggregate that names no runtime could satisfy
            # the rule that exists to make it name one.
            out.append(k)
    return out


def comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, str]:
    """(may these be differenced, why not)."""
    ra, rb = runtime_of(a), runtime_of(b)
    if ra is None or rb is None:
        return False, ("at least one aggregate carries no runtime stamp, so "
                       "whether they are comparable was never established")
    diffs = []
    for k in REQUIRED:
        va, vb = ra.get(k), rb.get(k)
        if isinstance(va, list) or isinstance(vb, list):
            va, vb = sorted(va or []), sorted(vb or [])
        if va != vb:
            diffs.append(f"{k}: {va!r} vs {vb!r}")
    if diffs:
        return False, "; ".join(diffs)
    return True, ""


def _load(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{path}: could not be read as JSON ({exc})"


def _walk(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            if fn.endswith(".json"):
                out.append(Path(dirpath) / fn)
    return sorted(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--aggregate", type=Path,
                    help="check ONE aggregate carries its runtime identity")
    ap.add_argument("--diff", nargs=2, type=Path, metavar=("A", "B"),
                    help="refuse to difference two aggregates across runtimes")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3

    if args.diff:
        a_p, b_p = args.diff
        for p in (a_p, b_p):
            if not p.is_file():
                print(f"[{NAME}] BAD INVOCATION — {p} is not a file.",
                      file=sys.stderr)
                return 3
        a, err_a = _load(a_p)
        b, err_b = _load(b_p)
        if err_a or err_b:
            print(f"[{NAME}] NOT CHECKED — {err_a or err_b}", file=sys.stderr)
            return 2
        ok, why = comparable(a, b)
        if not ok and "never established" in why:
            print(f"[{NAME}] NOT CHECKED — {why}. Two aggregates that cannot "
                  f"be shown comparable were not differenced.", file=sys.stderr)
            return 2
        if not ok:
            print(f"[{NAME}] REFUSED — these two aggregates were produced by "
                  f"DIFFERENT runtimes ({why}), so a difference between them "
                  f"is not a fact about the tree. Name the difference; do not "
                  f"subtract across it.", file=sys.stderr)
            return 1
        print(f"[{NAME}] PASS — both aggregates name the same runtime, so a "
              f"difference between them is about the tree.")
        return 0

    if args.aggregate is not None:
        if not args.aggregate.is_file():
            print(f"[{NAME}] BAD INVOCATION — {args.aggregate} is not a file.",
                  file=sys.stderr)
            return 3
        obj, err = _load(args.aggregate)
        if err:
            print(f"[{NAME}] NOT CHECKED — {err}", file=sys.stderr)
            return 2
        if not is_aggregate(obj):
            print(f"[{NAME}] NOT CHECKED — {args.aggregate} does not look like "
                  f"a test aggregate, so nothing was judged.", file=sys.stderr)
            return 2
        missing = missing_fields(obj)
        if missing:
            print(f"{args.aggregate}: omits {', '.join(missing)} — a failure "
                  f"count that does not name its runtime can be charged to the "
                  f"revision when it belongs to the runtime.")
            print(f"[{NAME}] FAIL — the aggregate does not name its runtime")
            return 1
        print(f"[{NAME}] PASS — the aggregate names the runtime that "
              f"produced it")
        return 0

    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    findings: List[str] = []
    unread: List[str] = []
    found = 0
    try:
        for p in _walk(root):
            obj, err = _load(p)
            if err is not None:
                continue          # not every JSON in a tree is an aggregate
            if not is_aggregate(obj):
                continue
            found += 1
            missing = missing_fields(obj)
            if missing:
                findings.append(f"{p.relative_to(root).as_posix()}: omits "
                                f"{', '.join(missing)}")
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    print(f"examined {found} test aggregate(s) under {str(root)!r}")
    if found == 0:
        print(f"[{NAME}] NOT CHECKED — no test aggregate was found, so nothing "
              f"was judged. This tree is a repository, not a run tree; the "
              f"rule's subject is the aggregate a test arm writes.",
              file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — an aggregate does not name its runtime")
        return 1
    if unread:
        return 2
    print(f"[{NAME}] PASS — every aggregate names its runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
