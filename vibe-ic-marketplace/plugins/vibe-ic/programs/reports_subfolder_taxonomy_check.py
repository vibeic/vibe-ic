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

VACUOUS_PASS: no `reports/` directory at all → vacuous PASS (project
hasn't run any phase yet).

Usage:
    python3 reports_subfolder_taxonomy_check.py <project_dir> [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  one or more stray entries under reports/
    2  argument or I/O error

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
        print(f"[VACUOUS_PASS] reports_subfolder_taxonomy_check: "
              f"{r.summary.get('reason', 'no reports/ yet')}")
        return 0
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
