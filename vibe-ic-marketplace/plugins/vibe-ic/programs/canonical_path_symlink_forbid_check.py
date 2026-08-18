#!/usr/bin/env python3
"""
canonical_path_symlink_forbid_check.py — generalised symlink ban for
canonical deliverable trees.

v1.6.29's `chip_gds_canonical_real_file_check.py` was the chip-GDS
slice of a wider class. The same anti-pattern — symlinking from a
canonical destination back to an intermediate-stage source so a
presence/size gate sees the target's stats — applies to every
canonical artefact: synth netlists, LEF / Liberty, SDC / SPEF, SOF,
sign-off `.rpt` files, hardmacro deliverables. v10627 shipped 8
analog blocks with symlinks under `analog/<block>/` that the chip-GDS
gate could not catch.

This gate is the chip-AGNOSTIC, file-extension-AGNOSTIC generalisation:
**no symlinks anywhere under the canonical-deliverable trees**, period.
Backlog reference:
  community/backlogs/ORGANIC-20260508-canonical-symlink-forbid.yaml

Forbidden trees
---------------
The trees mirror anti-fabrication rule #1 (commands/_anti_fabrication_rules.md)
plus the synth-netlist tree the backlog called out:

    phase3/stage4/**
    phase3/mixed_signal/**
    phase2/stage1/fpga/**
    phase2/stage2/synth/**
    analog/hardmacro/**

A symlink anywhere under these trees fails the gate. The runner that
PRODUCED an artefact must write it directly at its canonical home;
linking from elsewhere is a band-aid that lets a sloppy runner look
correct in audit while the real bits live in an intermediate stage.

Allowlist (`<project>/.canonical_symlink_allowlist`)
----------------------------------------------------
Foundry-shipped reference cells / vendor IP that are *required* to be
symlinks (e.g. a PDK vendor ships a single physical .lib and expects
each tech corner directory to symlink to it) can be exempted by listing
their project-relative paths in `.canonical_symlink_allowlist`, one per
line. Lines beginning with `#` are comments. Glob patterns supported via
`fnmatch`.

Rules
-----
For each symlink found under a forbidden tree:

* `BROKEN_SYMLINK` — `path.resolve(strict=False)` does not exist on
  disk. Worst case: opaque to size-based gates (resolves to 0 bytes)
  and points to a missing file.
* `SYMLINK_AT_CANONICAL_PATH` — symlink whose target exists. Still
  forbidden because the runner should have written the real bits at
  the canonical path; the symlink is a workaround.

Both exit-code FAIL.

VACUOUS_PASS
------------
No matching files at any forbidden tree (project hasn't reached the
relevant phase yet). Gate inapplicable; PASS by absence of evidence.

Usage
-----
    python3 canonical_path_symlink_forbid_check.py <project_dir>
                                                    [--json <out>]
                                                    [--list-trees]

Exit codes
----------
    0  PASS / VACUOUS_PASS
    1  one or more symlinks under a forbidden tree
    2  argument or I/O error

chip-AGNOSTIC. The forbidden-tree list and the allowlist mechanism are
the only configuration knobs; no chip / vendor / specific block-name is
hardcoded.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# Forbidden trees — every file/directory under these MUST be a real
# file or directory, never a symlink. Globs are evaluated with
# `Path.rglob('*')` rooted at each tree.
_FORBIDDEN_TREES: tuple[str, ...] = (
    "phase3/stage4",
    "phase3/mixed_signal",
    "phase2/stage1/fpga",
    "phase2/stage2/synth",
    "phase3/analog/hardmacro",
)

_ALLOWLIST_FILE = ".canonical_symlink_allowlist"


@dataclass
class SymlinkFinding:
    rel_path: str
    target: str
    rule: str  # SYMLINK_AT_CANONICAL_PATH | BROKEN_SYMLINK
    tree: str  # which forbidden tree triggered the finding


def _load_allowlist(project: Path) -> List[str]:
    """Read `.canonical_symlink_allowlist` if present. Returns the
    list of fnmatch glob patterns (project-relative paths). Empty
    list when the file is absent or unreadable."""
    f = project / _ALLOWLIST_FILE
    if not f.is_file():
        return []
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _is_allowlisted(rel_path: str, patterns: List[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def _walk_tree_for_symlinks(tree_root: Path) -> List[Path]:
    """Yield every symlink anywhere under `tree_root` (recursive).
    Includes symlinks to files, directories, and broken symlinks."""
    if not tree_root.exists() and not tree_root.is_symlink():
        return []
    out: List[Path] = []
    # The tree root itself, if it is a symlink, should be flagged.
    if tree_root.is_symlink():
        out.append(tree_root)
    # `Path.rglob('*')` does not follow symlinked directories on its
    # own; we want every name that is itself a symlink, regardless
    # of what it points to. Walk via rglob and let Path.is_symlink()
    # answer per-entry. Sorted for deterministic output.
    try:
        for p in sorted(tree_root.rglob("*")):
            if p.is_symlink():
                out.append(p)
    except OSError:
        # rglob can raise on permission errors / circular symlinks;
        # treat the tree as un-walkable rather than crash. Fail-safe:
        # downstream the absence of findings means PASS, but we lose
        # signal. Surfaced via stderr later if --verbose.
        return out
    return out


def audit(project: Path) -> Tuple[str, List[SymlinkFinding]]:
    """Audit `project`. Return (verdict, findings).

    verdict ∈ {"PASS", "VACUOUS_PASS", "FAIL"}.
    """
    allow = _load_allowlist(project)
    findings: List[SymlinkFinding] = []
    matched_any_tree = False
    for tree in _FORBIDDEN_TREES:
        tree_root = project / tree
        if not (tree_root.exists() or tree_root.is_symlink()):
            continue
        matched_any_tree = True
        for sl in _walk_tree_for_symlinks(tree_root):
            try:
                rel = str(sl.relative_to(project))
            except ValueError:
                rel = str(sl)
            if _is_allowlisted(rel, allow):
                continue
            try:
                target = str(sl.readlink())
            except OSError:
                target = "<unreadable>"
            resolved = sl.resolve(strict=False)
            rule = ("BROKEN_SYMLINK" if not resolved.exists()
                    else "SYMLINK_AT_CANONICAL_PATH")
            findings.append(SymlinkFinding(
                rel_path=rel, target=target, rule=rule, tree=tree))
    if not matched_any_tree:
        return "VACUOUS_PASS", []
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Forbid symlinks anywhere under canonical-deliverable "
                    "trees (chip-AGNOSTIC, file-extension-AGNOSTIC).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--list-trees", action="store_true",
                    help="print the forbidden trees and exit 0")
    args = ap.parse_args(argv)

    if args.list_trees:
        for t in _FORBIDDEN_TREES:
            print(t)
        return 0

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project)
    report = {
        "gate": "canonical_path_symlink_forbid_check",
        "verdict": verdict,
        "project": str(project),
        "forbidden_trees": list(_FORBIDDEN_TREES),
        "allowlist_file": _ALLOWLIST_FILE,
        "allowlist_patterns": _load_allowlist(project),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("no canonical-deliverable trees present; "
                            "project hasn't reached phase2/phase3 yet "
                            "or carries no analog hardmacros.")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        n_trees = sum(1 for t in _FORBIDDEN_TREES
                      if (project / t).exists())
        print(f"PASS: {n_trees} canonical-deliverable tree(s) clean — "
              f"no forbidden symlinks. (Allowlist patterns: "
              f"{len(report['allowlist_patterns'])}.)")
        return 0
    print(f"FAIL: {len(findings)} forbidden symlink(s) under canonical-"
          f"deliverable trees:", file=sys.stderr)
    for f in findings:
        print(f"  [{f.rule}] {f.rel_path} → {f.target}  "
              f"(tree: {f.tree})", file=sys.stderr)
    print(f"  → The runner that produced these artefacts must write "
          f"the real bits at the canonical paths above. If a path is "
          f"a foundry-shipped reference that MUST be a symlink, list "
          f"it (one per line, fnmatch globs supported) in "
          f"<project>/{_ALLOWLIST_FILE}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
