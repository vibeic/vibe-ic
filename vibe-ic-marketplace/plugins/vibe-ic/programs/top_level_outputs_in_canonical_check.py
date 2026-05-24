#!/usr/bin/env python3
"""
top_level_outputs_in_canonical_check.py — enforce that the project root
contains ONLY the canonical Phase/Stage/Step folders + 3 cross-phase
metadata files (v1.6.25 hygiene gate).

Whitelist (defined in `_path_layout.TOP_LEVEL_VALID_DIRS` +
`TOP_LEVEL_VALID_FILES`):
    Dirs:  input/, phase1/, phase2/, phase3/, analog/, reports/
    Files: provenance.jsonl, rig_topology.json, waivers.json

Anything else at the project root — `rtl/`, `synth/`, `pnr/`, `sim/`,
`run_logs/`, `rtl.pre_gen_backup/`, `extraction_patterns.json`,
`completeness_check_config.json`, `ai_deep_review_patches.json`,
top-level `*.log`, etc. — is a layout violation, regardless of how it
got there.

Real-world inspiration: phase2+3_v10623 shipped 7 stray top-level
entries (`extraction_patterns.json`, `extraction_patterns.auto.json`,
`completeness_check_config.json`, `ai_deep_review_patches.json`,
`rtl.pre_gen_backup/`, `run_logs/`, `sim/`) plus a dozen flat report
files. The plugin runners had been writing them to the project root
even though `_path_layout.py` already defined canonical homes; v1.6.25
moved every writer to use the helper API and added this gate so the
discipline doesn't drift again.

VACUOUS_PASS: empty project (no top-level entries at all) → vacuous PASS.

Usage:
    python3 top_level_outputs_in_canonical_check.py <project_dir> [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  one or more stray top-level entries
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


@dataclass
class Result:
    program: str = "top_level_outputs_in_canonical_check"
    passed: bool = True
    stray_dirs: List[str] = field(default_factory=list)
    stray_files: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def audit(project: Path) -> Result:
    r = Result()
    if not project.is_dir():
        r.passed = False
        r.summary = {"reason": "not a directory"}
        return r
    entries = list(project.iterdir())
    r.summary["total_entries"] = len(entries)
    if not entries:
        r.summary["vacuous_pass"] = True
        return r
    valid_dirs = set(_pl.TOP_LEVEL_VALID_DIRS)
    valid_files = set(_pl.TOP_LEVEL_VALID_FILES)
    for entry in sorted(entries):
        name = entry.name
        # Hidden files (.git, .DS_Store, .gitignore etc.) and pure
        # markdown read-mes are treated as project housekeeping, not
        # plugin-output violations.
        if name.startswith(".") or name.endswith(".md"):
            continue
        if entry.is_dir() or entry.is_symlink():
            if name not in valid_dirs:
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
        print("[VACUOUS_PASS] top_level_outputs_in_canonical_check: empty project")
        return 0
    if r.passed:
        n = r.summary.get("total_entries", 0)
        print(f"[PASS] top_level_outputs_in_canonical_check: "
              f"all {n} top-level entries are within canonical whitelist")
        return 0
    msg_parts = []
    if r.stray_dirs:
        msg_parts.append(f"{len(r.stray_dirs)} stray dir(s): {', '.join(r.stray_dirs)}")
    if r.stray_files:
        msg_parts.append(f"{len(r.stray_files)} stray file(s): {', '.join(r.stray_files)}")
    print(f"[FAIL] top_level_outputs_in_canonical_check: " + "; ".join(msg_parts))
    print(f"  Allowed dirs:  {', '.join(_pl.TOP_LEVEL_VALID_DIRS)}")
    print(f"  Allowed files: {', '.join(_pl.TOP_LEVEL_VALID_FILES)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
