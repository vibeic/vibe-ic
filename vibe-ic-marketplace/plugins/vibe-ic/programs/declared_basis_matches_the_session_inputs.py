#!/usr/bin/env python3
"""declared_basis_matches_the_session_inputs.py — the stage a report claims must
be the stage its own session measured.

WHY THIS EXISTS
===============
A report header states one side of place-and-route. The analysis session beside
it declares what it actually read. When those disagree, the published number is
INVARIANT under every knob that changes the layout and still reads as a
measurement of the thing that was built.

MEASURED: a power report headed post-layout whose session linked a 287-instance
pre-layout netlist and loaded no extracted parasitics, against 3373 routed
instances. It published 0.306 mW where the post-route session publishes
0.573 mW — 46.6 % understated — and reported the whole CLOCK GROUP as
0.000 mW where the real measurement puts 33.7 % of total power. A zero for an
entire contributor is the clearest form of the general failure: an ABSENT input
read as a MEASURED zero.

THE STAGE IS DERIVED FROM THE INPUTS, NOT FROM THE LABEL
========================================================
The session is the ground truth, because it is what the tool actually executed:

    read_spef present   -> the session measured extracted parasitics: POST_ROUTE
    read_spef absent    -> whatever the header says, no parasitics were loaded,
                           so the numbers cannot move when the layout moves:
                           PRE_LAYOUT

The CLAIM is read from the report's `STA_BASIS:` stamp through
`_sta_basis.declared_basis` — THE one reader in this tree. It is imported, never
re-implemented: that module records that when five copies of the stamp reader
existed they disagreed on 7 of a 24-stamp corpus. Where no stamp is present the
file NAME is used as a weaker claim, and that fallback is reported as such.

    rc 0   N>0 pairs read; every claim agrees with its session.
    rc 1   a claim disagrees with its session.
    rc 2   NOT CHECKED — no (session, report) pair found, or one could not be
           read, or NOT ONE pair declares a stage (nothing was compared, so the
           run is undetermined rather than clean). An UNDECLARED pair beside at
           least one declared pair is counted and disclosed, never silently
           passed.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sta_basis                                          # noqa: E402

NAME = "declared_basis_matches_the_session_inputs"
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

#: `read_spef` AT A COMMAND POSITION, not merely at the start of a line.
#:
#: MEASURED: the previous form was `^\s*read_spef\b` and reported PRE_LAYOUT for
#:
#:     catch {read_spef design.spef} err        <- idiomatic, wraps a failing read
#:     [read_spef design.spef]                  <- command substitution
#:
#: Both DO load parasitics. Saying PRE_LAYOUT of a session that read SPEF makes
#: this gate emit a FALSE FINDING against any report correctly claiming
#: POST_ROUTE — a false accusation, which is the worst direction for a rule whose
#: whole subject is artefacts that claim more than they measured.
#:
#: In Tcl a command may begin at the start of a line or after `{`, `[` or `;`.
#: A word inside a quoted string is preceded by none of those, so
#: `puts "would read_spef here"` is still not a read — asserted in the tests.
#: Found by taking the census lane's "stop being a declaration-shaped regex"
#: and asking it of this scan.
_READ_SPEF = re.compile(r"(?:^|[;{\[])\s*read_spef\b", re.M)
_REPORTS = re.compile(r"^\s*report_(power|checks|timing)\b", re.M)
_POST_NAME = re.compile(r"post_?route|post_?layout|postpnr|post_?pnr", re.I)
_PRE_NAME = re.compile(r"pre_?layout|pre_?pnr|prelayout", re.I)


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    parts = rel.split("/")
    return (any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS)
            or "__pycache__" in parts)


def session_basis(script_text: str) -> str:
    """What the session ACTUALLY measured. The tool's own inputs decide."""
    return "POST_ROUTE" if _READ_SPEF.search(script_text) else "PRE_LAYOUT"


def claimed_basis(report_text: str, report_name: str) -> Tuple[Optional[str], str]:
    """(claim, how it was established). None means the report declares nothing."""
    stamped = _sta_basis.declared_basis(report_text)
    if stamped is not None:
        return stamped, "STA_BASIS stamp"
    if _POST_NAME.search(report_name):
        return "POST_ROUTE", "file name (no stamp — a weaker claim)"
    if _PRE_NAME.search(report_name):
        return "PRE_LAYOUT", "file name (no stamp — a weaker claim)"
    return None, "nothing"


class Finding:
    def __init__(self, script: str, report: str, claim: str, how: str,
                 actual: str):
        self.script, self.report = script, report
        self.claim, self.how, self.actual = claim, how, actual

    def __str__(self) -> str:
        extra = ("" if self.actual == "POST_ROUTE" else
                 " The session loads NO extracted parasitics, so this number "
                 "cannot move when the layout moves.")
        return (f"{self.report}: claims {self.claim} (from {self.how}) but its "
                f"session {self.script} measured {self.actual}.{extra}")


def _pairs(root: Path) -> List[Tuple[Path, Path]]:
    """(session script, report) pairs sharing a stem in one directory."""
    out: List[Tuple[Path, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        by_stem = {}
        for fn in filenames:
            stem, _, ext = fn.rpartition(".")
            if ext in ("tcl", "rpt"):
                by_stem.setdefault(stem, {})[ext] = Path(dirpath) / fn
        for stem, got in sorted(by_stem.items()):
            if "tcl" in got and "rpt" in got:
                out.append((got["tcl"], got["rpt"]))
    return out


def audit(root: Path) -> Tuple[List[Finding], List[str], List[str], int, int]:
    findings: List[Finding] = []
    undeclared: List[str] = []
    unread: List[str] = []
    pairs = 0
    declared_pairs = 0
    for script, report in _pairs(root):
        rs = script.relative_to(root).as_posix()
        rr = report.relative_to(root).as_posix()
        try:
            stext = script.read_text(encoding="utf-8", errors="replace")
            rtext = report.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unread.append(f"{rs}/{rr}: {exc}")
            continue
        if not _REPORTS.search(stext):
            continue            # not an analysis session that publishes a number
        pairs += 1
        actual = session_basis(stext)
        claim, how = claimed_basis(rtext, report.name)
        if claim is None:
            undeclared.append(rr)
            continue
        declared_pairs += 1
        if claim != actual:
            findings.append(Finding(rs, rr, claim, how, actual))
    return findings, undeclared, unread, pairs, declared_pairs


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
    try:
        findings, undeclared, unread, pairs, declared_pairs = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(str(f))
    for u in undeclared:
        print(f"UNDECLARED — {u} states no stage at all, so its basis was not "
              f"checked against its session.", file=sys.stderr)
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    print(f"examined {pairs} (session, report) pair(s) under {str(root)!r}; "
          f"{declared_pairs} declare a stage, {len(undeclared)} declare none")
    if pairs == 0:
        print(f"[{NAME}] NOT CHECKED — no analysis session with a report was "
              f"found.", file=sys.stderr)
        return 2
    if findings:
        print(f"[{NAME}] FAIL — a report claims a stage its session did not "
              f"measure")
        return 1
    # A CORPUS THAT DECLARES NOTHING WAS NOT CHECKED, AND MUST NOT READ AS CLEAN.
    #
    # MEASURED: over two pairs that both declared no stage at all, this printed
    # "PASS — every claimed stage matches its session's inputs" and returned 0,
    # having compared ZERO claims. That is a vacuous pass, and the capture this
    # implements settles it in as many words at RESULT.md row 4: "a report that
    # declares nothing is *undetermined*, not clean."
    #
    # One declared pair is enough to make the run a real comparison; the
    # undeclared ones are disclosed beside it.
    if declared_pairs == 0:
        print(f"[{NAME}] NOT CHECKED — {pairs} pair(s) were read and NOT ONE "
              f"declares a stage, so no claim was compared against any session. "
              f"A report that declares nothing is undetermined, not clean.",
              file=sys.stderr)
        return 2
    if unread:
        print(f"[{NAME}] NOT CHECKED — a pair could not be read")
        return 2
    print(f"[{NAME}] PASS — every claimed stage matches its session's inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
