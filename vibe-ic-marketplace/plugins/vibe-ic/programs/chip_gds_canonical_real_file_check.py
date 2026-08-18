#!/usr/bin/env python3
"""
chip_gds_canonical_real_file_check.py — top-level chip GDS files at
canonical paths must be REAL files, not symlinks pointing elsewhere.

Real-world inspiration: phase2+3_v10627 shipped three top-level chip
GDS as symlinks back to `phase3/stage3/pnr/<top>.gds`:

    phase3/stage4/gds/<top>.gds              → ../stage3/pnr/<top>.gds
    phase3/mixed_signal/top_merged.gds       → ../stage3/pnr/<top>.gds
    phase3/stage4/foundry_handoff/scribe_line_layout.gds → same target

Existing `gds_size_check` follows symlinks transparently and reports
the target's size, so a symlink masking a missing tape-out artefact
passes audit. This gate is the symlink-aware companion: it requires
the canonical destinations to be **real files** with their own bits.
v1.6.22 deleted 27 such symlinks from v10619 by hand; this gate makes
the discipline mechanical.

Why "first time at right folder"
--------------------------------
v1.6.21+ removed all backward-compat fallback. Symlinks to a different
location are the same anti-pattern: the runner that PRODUCED the file
should write it at its canonical home, not link from somewhere else.
A symlink at a canonical path is a band-aid that lets a sloppy runner
look correct in audit while the real artefact lives elsewhere.

Checks (chip-AGNOSTIC):
    phase3/stage4/gds/**/*.gds                     → real file required
    phase3/mixed_signal/**/*.gds                   → real file required
    phase3/stage4/foundry_handoff/**/*.gds         → real file required

v1.6.30: globs are RECURSIVE so a sub-cell symlink like
`phase3/stage4/gds/cells/ref.gds → ../../external/ref.gds` is also
caught. Broken symlinks (target missing) report size 0 and FAIL with
a `BROKEN_SYMLINK` rule rather than passing under the original
target-size-on-resolve behaviour.

Per-block analog GDS under analog/<block>/ and analog/hardmacro/<block>/
is covered by the substance gate, not here.

VACUOUS_PASS: no .gds files found at any canonical path → project
hasn't reached GDS-stream-out yet. Gate inapplicable.

Usage:
    python3 chip_gds_canonical_real_file_check.py <project_dir>
                                                   [--json <out>]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  one or more canonical chip GDS paths are symlinks
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Tuple


_CANONICAL_GDS_GLOBS = (
    "phase3/stage4/gds/**/*.gds",
    "phase3/mixed_signal/**/*.gds",
    "phase3/stage4/foundry_handoff/**/*.gds",
)


@dataclass
class SymlinkFinding:
    rel_path: str
    target: str
    size_bytes: int
    rule: str = "SYMLINK_AT_CANONICAL_PATH"
    # Other rules: BROKEN_SYMLINK (target missing).


def _resolve_size(p: Path) -> int:
    """Best-effort size for a path. For a broken symlink returns 0."""
    try:
        if p.is_symlink():
            target = p.resolve(strict=False)
            return target.stat().st_size if target.exists() else 0
        return p.stat().st_size
    except OSError:
        return 0


def audit(project: Path) -> Tuple[str, List[SymlinkFinding]]:
    paths: List[Path] = []
    for pat in _CANONICAL_GDS_GLOBS:
        # rglob via ** plus glob; dedupe by resolved path string.
        paths.extend(sorted(project.glob(pat)))
    # Dedupe; preserve order. (Recursive globs can otherwise visit the
    # same path twice if multiple pattern roots overlap — they don't
    # here, but the dedupe is cheap insurance.)
    seen: set = set()
    deduped: List[Path] = []
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    paths = deduped
    if not paths:
        return "VACUOUS_PASS", []
    findings: List[SymlinkFinding] = []
    for p in paths:
        if p.is_symlink():
            target = str(p.readlink())
            size = _resolve_size(p)
            # A symlink whose resolve target does NOT exist is a
            # BROKEN_SYMLINK (worse than a regular symlink: it's also
            # opaque to size-based gates which would resolve to 0).
            target_path = p.resolve(strict=False)
            rule = ("BROKEN_SYMLINK" if not target_path.exists()
                    else "SYMLINK_AT_CANONICAL_PATH")
            findings.append(SymlinkFinding(
                rel_path=str(p.relative_to(project)),
                target=target,
                size_bytes=size,
                rule=rule))
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify top-level chip GDS at canonical paths are "
                    "real files, not symlinks.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project)
    report = {
        "gate": "chip_gds_canonical_real_file_check",
        "verdict": verdict,
        "project": str(project),
        "checked_globs": list(_CANONICAL_GDS_GLOBS),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("no .gds files at any canonical chip-GDS "
                            "path; project hasn't reached GDS-stream-"
                            "out yet.")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: all chip-GDS at canonical paths are real files "
              f"(no symlink workarounds).")
        return 0
    print(f"FAIL: {len(findings)} canonical chip-GDS path(s) are "
          f"symlinks pointing elsewhere:", file=sys.stderr)
    for f in findings:
        print(f"  {f.rel_path} → {f.target} (target size {f.size_bytes}B)",
              file=sys.stderr)
    print("  → The runner that produced the GDS should write directly "
          "to the canonical path, not symlink from another location. "
          "v1.6.22 deleted 27 such symlinks from v10619.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
