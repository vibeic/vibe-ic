#!/usr/bin/env python3
"""generated_test_list_min_guard.py — a generated test list is checked against a
MINIMUM and a resolvable path set, never against emptiness.

THIS GATE BLOCKS (rc=1). It is meant to be called between the selector and the
runner, so a bad list never reaches the runner at all.

TWO SILENT FAILURES, MEASURED TWICE IN ONE DAY (2026-08-21)
===========================================================
Both read as green. They fail in OPPOSITE directions, which is why guarding one
of them does not guard the other.

  AN EMPTY LIST RUNS EVERYTHING. ``xargs -a <empty> python3 -m pytest`` invokes
  pytest with NO path arguments, so pytest falls back to its configured
  ``testpaths`` and collects the entire suite. Measured: a selector timed out
  against a large difference, wrote a zero-byte list, and two comparison arms
  launched an unbounded sweep across two clones — a machine somebody had to go
  and rescue.

  A LIST NAMING A PATH THAT DOES NOT EXIST RUNS NOTHING. Measured separately:
  one non-existent path among five produced a zero-test run reported with a
  success code.

``tools/gatekeeper-land.sh`` tests ``[ ! -s "$sel" ]`` — file non-empty. That
catches the first failure and not the second, and it catches the first one only
in its extreme form.

WHY A MINIMUM AND NOT "NOT EMPTY"
=================================
A list holding three entries where nine hundred were expected is the SAME CLASS
OF WRONG as a list holding zero, and an emptiness test cannot see it. The floor
has to come from OUTSIDE the list — the caller states what the selection is
worth, exactly as ``hygiene_shard_aggregate --expect`` states its denominator
outside the records it checks. A guard that derives its own floor from the file
it is checking agrees with itself by construction.

DISTINCT ENTRIES, BECAUSE A MINIMUM IS OTHERWISE TRIVIAL TO SATISFY
===================================================================
The floor is compared against the number of DISTINCT entries. A list of nine
hundred copies of one path clears a ``--min 900`` written over line-counting,
runs one file, and reports success — the first failure above wearing the
second's clothes. Duplicates are reported as well as discounted, because a
selector emitting them is a defect in the selector.

EXIT CODES
==========
    0  at least ``--min`` distinct entries, and every one of them exists
    1  REFUSED — too few entries, or an entry that does not resolve; the count
       seen against the count required and every unresolvable path are printed
    2  VACUOUS — ``--root`` is not a directory, so whether the entries exist
       could not be decided and NOTHING was verified (`_vacuous_exit`'s tier,
       announced rather than silently passed)
    3  the command line was rejected — no ``--min``, a ``--min`` below 1, an
       unreadable list. NOTHING was examined (`_gate_usage_exit`)

USAGE
-----
    generated_test_list_min_guard.py <list-file> --min N --root DIR [--json OUT]

chip-AGNOSTIC: a text file and a directory. No design, PDK, vendor or SKU.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac

TOOL = "generated_test_list_min_guard"


def entries(text: str) -> List[str]:
    """Every non-blank line, in order, whitespace-trimmed.

    Deliberately NO comment syntax. A generated list is machine output; teaching
    this reader to drop ``#`` lines would let a selector that emitted a comment
    where a path belongs shrink the selection without changing the count.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse a generated test list below a declared minimum, or "
                    "naming a path that does not exist")
    ap.add_argument("list", type=Path, help="the generated list, one path per line")
    ap.add_argument("--min", type=int, required=True, dest="minimum",
                    help="the floor the CALLER declares this selection is worth; "
                         "it must come from outside the list")
    ap.add_argument("--root", type=Path, required=True,
                    help="the directory the entries are relative to")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if args.minimum < 1:
        return _usage.usage_error(
            TOOL, f"--min {args.minimum} is not a floor; a selection worth zero "
                  f"files is the failure this program exists to refuse")
    try:
        text = args.list.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _usage.usage_error(TOOL, f"cannot read {args.list}: {exc}")

    rows = entries(text)
    counts = Counter(rows)
    dupes = sorted(p for p, n in counts.items() if n > 1)
    distinct = sorted(counts)

    if not args.root.is_dir():
        _vac.announce_vacuous(TOOL, "root-not-a-directory")
        print(f"[VACUOUS] {TOOL}: --root {args.root} is not a directory, so "
              f"whether the {len(distinct)} listed path(s) exist could not be "
              f"decided; NOTHING was verified and this is NOT a pass")
        return _vac.RC_VACUOUS

    missing = [p for p in distinct if not (args.root / p).exists()]

    report = {
        "tool": TOOL, "list": str(args.list), "root": str(args.root),
        "minimum": args.minimum, "lines": len(rows), "distinct": len(distinct),
        "duplicates": dupes, "missing": missing,
    }
    if args.json:
        _atomic.write_json(args.json, report)

    problems: List[str] = []
    if len(distinct) < args.minimum:
        problems.append(
            f"{len(distinct)} distinct entr(ies) against a declared minimum of "
            f"{args.minimum} — a selection this far below its floor is not a "
            f"smaller run, it is a broken selector"
            + (f" ({len(rows)} line(s), {len(dupes)} duplicated path(s))"
               if dupes else ""))
    if missing:
        problems.append(
            f"{len(missing)} of {len(distinct)} listed path(s) do not exist "
            f"under {args.root}; a runner handed them collects nothing and "
            f"reports success: " + ", ".join(missing[:6])
            + (" …" if len(missing) > 6 else ""))

    if problems:
        for p in problems:
            print(f"  [SELECTION] {p}")
        print(f"[FAIL] {TOOL}: the generated list may not be handed to a runner")
        return _vac.RC_FAIL

    extra = (f"; {len(dupes)} duplicated path(s) discounted" if dupes else "")
    print(f"[PASS] {TOOL}: {len(distinct)} distinct entr(ies) >= minimum "
          f"{args.minimum}, all resolvable under {args.root}{extra}")
    return _vac.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
