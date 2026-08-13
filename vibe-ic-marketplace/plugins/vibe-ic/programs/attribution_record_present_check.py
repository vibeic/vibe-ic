#!/usr/bin/env python3
"""attribution_record_present_check.py — vendored third-party code may not lose
its attribution record while the code stays in the tree. vibe-ic#1043.

THE OBLIGATION DOES NOT TRAVEL WITH THE EVIDENCE
================================================
Apache-2.0 §4(b) and §4(d) attach to distributing the WORK, not to publishing a
run that used it. Withdrawing a run therefore does not withdraw the duty: if the
vendored RTL stays tracked, the record naming its origin and licence must stay
tracked too.

That is a licensing obligation rather than an engineering preference, which is
exactly why it must be a MECHANISM. #1043 was found by a human reading a diff.
A human reading a diff is not a control — it is the same "enforced by someone
noticing" this repo has spent versions retiring, and the review that catches it
is the one nobody schedules.

WHAT IS CHECKED
===============
For every tracked file under the scanned roots that carries a third-party
licence header (:data:`_LICENCE_MARKERS`), an attribution record
(:data:`RECORD_NAMES`) must be tracked at that file's directory or at any
ancestor of it. Missing record -> rc 1, and the finding names the file, the
copyright holder it declares, and the directory where a record would cover it.

WHY THE FILE'S OWN HEADER IS THE TRIGGER, AND NOT A LIST OF VENDOR PATHS
========================================================================
A curated list of "these directories are vendored" is a second thing to keep in
step with the first, and it goes stale in exactly the direction that hurts: a
new vendor drop lands in a path nobody added, and the check reports clean over
it. The licence header travels WITH the file, is written by the upstream author,
and is the same text the obligation attaches to. So the population is derived
from the artefact, not from a register somebody maintains.

MEASURED ON a38902d1 (v1.10.35)
===============================
    tracked files carrying an Apache-2.0 header : 486
    attribution records                          : 9
    UNCOVERED                                    : 2

Both uncovered files are `benchmark-data/ic/spm/*/phase2/stage2/dft/
cell_model_combined.v` — 39,971 lines of GlobalFoundries PDK cell models
(`Copyright 2022 GlobalFoundries PDK Authors`) and 152,616 lines of SkyWater PDK
cell models (`Copyright 2020 The SkyWater PDK Authors`), both Apache-2.0, both
vendored with their headers intact, under an IC directory that carries no record
at all.

WHAT THIS IS *NOT*, STATED BECAUSE #1043 REPORTS DIFFERENT NUMBERS
==================================================================
#1043 reports 297 files stranded by PR #1028 across two ICs, "5 of the 6
manifests" deleted. Re-measured on 2026-08-13 against
`origin/withdraw/nonpassing-published-runs` as it stands TODAY, that does not
reproduce: the branch deletes 2 records, both under
`caravel_user_project/clean_run_v1432*_commercial/`, the parent
`caravel_user_project/SOURCE_MANIFEST.md` survives, and the Apache-2.0 files
under those two roots go down with them —

    withdrawal branch: 336 apache files, 7 records, 0 UNCOVERED

The branch moved after the issue was filed. The specific gap #1043 names is
closed; the OBLIGATION it identified is not, and this check is what makes the
next occurrence impossible to land quietly rather than a thing someone has to
notice again.

THE BOUND
=========
This asks whether an attribution record EXISTS and covers the file. It does not
read the record and confirm the file is listed in it — a record that omits the
file it is meant to attribute would pass here. That is a real gap and it is
stated rather than implied; closing it needs a per-record parser and belongs in
its own change.

Exit: 0 = every licenced file is covered, 1 = at least one is not,
2 = the scan could not run (no roots, or git unavailable).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA = "vibe-ic/attribution-record/v1"

#: Filenames that constitute an attribution record for the tree they sit in.
RECORD_NAMES = ("SOURCE_MANIFEST.md", "NOTICE", "NOTICE.md", "NOTICE.txt")

#: Header text that marks a file as carrying a third-party licence obligation.
#: Apache-2.0 is the licence #1043 is about; the others are here because a
#: vendor drop under a different permissive licence has the same duty and a
#: check that only knew one would report clean over it.
_LICENCE_MARKERS = (
    "Licensed under the Apache License",
    "SPDX-License-Identifier: Apache-2.0",
    "Licensed under the Solderpad Hardware License",
    "SPDX-License-Identifier: BSD-3-Clause",
)

_COPYRIGHT = re.compile(r"Copyright\s+(?:\(c\)\s*)?((?:19|20)\d{2}[^\n\r*]{0,60})")

DEFAULT_ROOTS = ("benchmark-data",)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=900)
    return r.stdout


def tracked_records(repo: Path, ref: str, roots) -> set:
    """Directories that carry a tracked attribution record."""
    out = set()
    for root in roots:
        for line in _git(repo, "ls-tree", "-r", ref, "--name-only",
                         "--", root).strip().split("\n"):
            if line and Path(line).name in RECORD_NAMES:
                out.add(str(Path(line).parent))
    return out


def licenced_files(repo: Path, ref: str, roots) -> List[str]:
    """Tracked files carrying a third-party licence header, deduped and sorted.

    `git grep` on the REF, not on the working tree: the obligation is about what
    the commit distributes, and a check that read the worktree would answer a
    different question on a dirty checkout.
    """
    found = set()
    for marker in _LICENCE_MARKERS:
        for root in roots:
            out = _git(repo, "grep", "-lI", "--fixed-strings", marker, ref,
                       "--", root)
            for line in out.strip().split("\n"):
                if not line:
                    continue
                found.add(line[len(ref) + 1:] if line.startswith(ref + ":")
                          else line)
    return sorted(found)


def _covered(rel: str, record_dirs: set) -> bool:
    p = Path(rel).parent
    while True:
        if str(p) in record_dirs:
            return True
        if p == p.parent:
            return False
        p = p.parent


def declared_holder(repo: Path, ref: str, rel: str) -> str:
    """The copyright line the file itself declares. Quoted, never guessed."""
    blob = _git(repo, "show", f"{ref}:{rel}")[:4000]
    m = _COPYRIGHT.search(blob)
    return m.group(1).strip() if m else "(no copyright line found)"


def audit(repo: Path, ref: str = "HEAD",
          roots=DEFAULT_ROOTS) -> Tuple[int, Dict[str, object]]:
    present = [r for r in roots if _git(repo, "ls-tree", ref, "--", r).strip()]
    if not present:
        return 2, {"schema": SCHEMA, "verdict": "NO_SCOPE",
                   "disclosure": f"none of {list(roots)} exists at {ref}; "
                                 f"nothing was scanned, which is not a pass"}
    record_dirs = tracked_records(repo, ref, present)
    files = licenced_files(repo, ref, present)
    if not files:
        return 2, {"schema": SCHEMA, "verdict": "NO_LICENCED_FILES",
                   "disclosure": "no tracked file under the scanned roots "
                                 "carries a known licence header; the check "
                                 "examined nothing and that is not a pass"}
    uncovered = [f for f in files if not _covered(f, record_dirs)]
    report = {
        "schema": SCHEMA, "ref": ref, "roots": list(present),
        "counts": {"licenced_files": len(files),
                   "attribution_records": len(record_dirs),
                   "uncovered": len(uncovered)},
        "findings": [
            {"file": f, "declares": declared_holder(repo, ref, f),
             "a_record_here_would_cover_it": str(Path(f).parent)}
            for f in uncovered],
    }
    report["verdict"] = "UNATTRIBUTED" if uncovered else "COVERED"
    return (1 if uncovered else 0), report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".", help="repository root")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--root", action="append", dest="roots",
                    help="scan root (repeatable; default benchmark-data)")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    rc, report = audit(Path(args.repo), args.ref,
                       tuple(args.roots) if args.roots else DEFAULT_ROOTS)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2, sort_keys=True)
                                   + "\n", encoding="utf-8")
    if rc == 2:
        print(f"[REFUSED] attribution_record_present_check: "
              f"{report['disclosure']}")
        return rc
    c = report["counts"]
    for f in report["findings"]:
        print(f"[FAIL] {f['file']} declares '{f['declares']}' and no "
              f"attribution record covers it. A record at "
              f"{f['a_record_here_would_cover_it']}/ (or any ancestor) would.")
    if rc == 0:
        print(f"[PASS] attribution_record_present_check: all "
              f"{c['licenced_files']} licenced file(s) are covered by one of "
              f"{c['attribution_records']} attribution record(s).")
    else:
        print(f"[FAIL] attribution_record_present_check: {c['uncovered']} of "
              f"{c['licenced_files']} licenced file(s) have no attribution "
              f"record. Apache-2.0 §4(b)/§4(d) attach to distributing the WORK; "
              f"the code is still here, so the duty is too.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
