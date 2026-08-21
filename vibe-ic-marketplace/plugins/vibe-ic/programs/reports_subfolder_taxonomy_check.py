#!/usr/bin/env python3
"""
reports_subfolder_taxonomy_check.py — enforce that `<project>/reports/`
contains ONLY the 6 phase-aligned subfolders + 2 top-level summary
markdown files (v1.6.25 hygiene gate).

Whitelist:
    Subdirs: phase1/, phase2/, phase3/, analog/, audit/, orchestrator/
    Files:   final_summary.md, chip_specific_summary.md

Anything else under reports/ — flat-file reports like `synth_netlist.json`
at top level, stray subdirs like `legacy/` or `tmp/`, or files at
reports/ root that aren't one of the 2 allowed summaries — is a
violation.

Real-world inspiration: pre-v1.6.25 projects shipped 50+ flat report
files at `reports/` root (`drc_signoff.json`, `lvs.rpt`, `power.rpt`,
`em.rpt`, etc.) intermixed with subdirectory buckets. v1.6.25 partitions
reports/ into a 6-folder phase taxonomy and adds this gate so the
partition holds.

VACUOUS: the gate examined ZERO entries — either there is no `reports/`
directory at all, or there is one and it is empty (both mean the project has
not run any phase yet). Reported as rc 2.

Usage:
    python3 reports_subfolder_taxonomy_check.py <project_dir> [--json <out>]

Exit codes:
    0  PASS — every entry under reports/ matches the taxonomy (and there was
       at least one entry to match)
    1  one or more stray entries under reports/
    2  argument or I/O error, OR VACUOUS: zero entries were examined. TWO
       branches, one per spelling of the same zero:
         (a) no reports/ directory     -> reason `no reports/ directory`
         (b) reports/ exists, is empty -> reason `reports/ directory is empty`

    #528 — the vacuous branch used to exit 0 and announce itself as
    `[VACUOUS_PASS] ...`. `flow_compliance_check._stdout_signals_vacuous`
    matches `line.lstrip().startswith("VACUOUS_PASS")`, which the leading
    bracket defeats, so BOTH channels the tier-deciding consumer reads were
    silent and the run was credited a plain PASS over a project with no
    reports/ at all. Routed through `_vacuous_exit`, which returns rc 2 AND
    writes the sentinel in the shape the matcher wants.

    #528 follow-up — branch (b) was added after the neighbour sweep. The
    vacuous tier was routed from an INPUT SHAPE (`reports.is_dir()`), so an
    existing-but-empty reports/ answered `[PASS] ... all 0 reports/ entries
    match the phase-aligned taxonomy` — the same zero, credited. Measured:
    absent -> VACUOUS, empty -> PASS. `top_level_outputs_in_canonical_check`
    already routed from its count (`if not entries`), and comparing the two is
    what made this visible.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

import _path_layout as _pl
import _vacuous_exit as _vx


_VALID_TOP_LEVEL_FILES = ("final_summary.md", "chip_specific_summary.md")


@dataclass
class Result:
    program: str = "reports_subfolder_taxonomy_check"
    passed: bool = True
    stray_dirs: List[str] = field(default_factory=list)
    stray_files: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def audit(project: Path) -> Result:
    r = Result()
    reports = _pl.reports_dir(project)
    if not reports.is_dir():
        r.summary["vacuous_pass"] = True
        r.summary["reason"] = "no reports/ directory"
        return r
    valid_subdirs = set(_pl.REPORTS_VALID_SUBDIRS)
    valid_files = set(_VALID_TOP_LEVEL_FILES)
    entries = sorted(reports.iterdir())
    r.summary["total_entries"] = len(entries)
    if not entries:
        # #528 follow-up — ABSENT AND EMPTY ARE THE SAME DENOMINATOR.
        #
        # The branch above routes the vacuous tier from an INPUT SHAPE ("is
        # there a reports/ directory?"). A reports/ that exists and holds
        # nothing was examined exactly as much — zero entries — and answered a
        # plain `[PASS] ... all 0 reports/ entries match the phase-aligned
        # taxonomy`. Measured: absent -> VACUOUS, empty -> PASS, from the same
        # zero.
        #
        # This is the same spelling as `marketplace_version_sync_check`'s
        # `.get("plugins", [])`, in a different alphabet: there a default
        # value collapsed absent into empty, here a directory test never asked
        # about empty at all. `top_level_outputs_in_canonical_check` gets this
        # right already (`if not entries: vacuous_pass = True`), which is what
        # made the difference visible.
        r.summary["vacuous_pass"] = True
        r.summary["reason"] = "reports/ directory is empty"
        return r
    for entry in entries:
        name = entry.name
        # Hidden files are housekeeping, not violations
        if name.startswith("."):
            continue
        if entry.is_dir() or entry.is_symlink():
            if name not in valid_subdirs:
                r.stray_dirs.append(name)
        else:
            if name not in valid_files:
                r.stray_files.append(name)
    if r.stray_dirs or r.stray_files:
        r.passed = False
    r.summary["stray_dir_count"] = len(r.stray_dirs)
    r.summary["stray_file_count"] = len(r.stray_files)
    return r


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = Path(args.project_dir)
    if not project.exists():
        print(f"ERROR: not found: {project}", file=sys.stderr)
        return 2
    r = audit(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(asdict(r), indent=2) + "\n")
    if r.summary.get("vacuous_pass"):
        # #528 — the token was written `[VACUOUS_PASS]`, and the consumer that
        # decides the tier matches `line.lstrip().startswith("VACUOUS_PASS")`.
        # A bracketed token does not match, so this branch announced the
        # vacuous tier in the one form nothing could read, and exited 0: a
        # plain PASS credited to a run that opened no reports/ directory.
        # Routed through the shared site, which gives BOTH channels at once —
        # rc 2, and the sentinel in the exact shape the matcher wants.
        reason = r.summary.get("reason", "no reports/ yet")
        _vx.announce_vacuous("reports_subfolder_taxonomy_check", reason)
        print(_vx.verdict_line("reports_subfolder_taxonomy_check",
                               passed=True, skipped=True, reason=reason))
        return _vx.exit_code(passed=True, skipped=True)
    if r.passed:
        n = r.summary.get("total_entries", 0)
        print(f"[PASS] reports_subfolder_taxonomy_check: "
              f"all {n} reports/ entries match the phase-aligned taxonomy")
        return 0
    msg_parts = []
    if r.stray_dirs:
        msg_parts.append(f"{len(r.stray_dirs)} stray subdir(s): {', '.join(r.stray_dirs[:8])}")
    if r.stray_files:
        msg_parts.append(f"{len(r.stray_files)} stray file(s): {', '.join(r.stray_files[:8])}")
    print(f"[FAIL] reports_subfolder_taxonomy_check: " + "; ".join(msg_parts))
    print(f"  Allowed subdirs: {', '.join(_pl.REPORTS_VALID_SUBDIRS)}")
    print(f"  Allowed files:   {', '.join(_VALID_TOP_LEVEL_FILES)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
