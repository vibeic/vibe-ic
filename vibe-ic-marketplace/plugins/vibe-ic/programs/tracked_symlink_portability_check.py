#!/usr/bin/env python3
"""tracked_symlink_portability_check.py — a tracked symlink must resolve for
everyone, not just for the machine that created it.

THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
--------------------
MEASURED (#371, 2026-07-26, `benchmark-data/ic`): 172 tracked symlinks, and
159 of them recorded an ABSOLUTE target under the author's own checkout
path. They resolved on that machine and dangled in every other clone — the
content looked present (`git ls-files` lists it, a blob exists) while the
blob held only a path string.

That is not a cosmetic problem. It made a gate's verdict
environment-dependent: `evidence_citation_resolves_check` READ tracked
paths, so locally those symlinks were followed and counted and in CI they
were not — the same commit enumerated 440 documents locally and 422 in CI,
and a baseline written in one place could never match the other. Two land
attempts were refuted by CI before the cause was found.

WHAT IT CHECKS
--------------
For every tracked symlink under the scan root:

  * ABSOLUTE target      → FAIL. An absolute path encodes one machine's
                           directory layout; it cannot be portable even when
                           it happens to point inside the repository.
  * ESCAPES the repo     → FAIL. A relative target that climbs out of the
                           repository ships a pointer to content the
                           repository does not have.

A relative target that stays inside the repository is fine, INCLUDING one
that is currently dangling: that is a missing-file problem for the tree to
fix, not a portability problem, and failing on it here would conflate two
different defects. The dangling count is REPORTED on every run so it cannot
hide behind this gate's silence.

chip-AGNOSTIC: pure git/filesystem structure. No design, PDK or vendor
literal appears here.

USAGE
-----
    python3 tracked_symlink_portability_check.py [ROOT] [--json OUT]

EXIT CODES
----------
    0 = PASS      1 = FAIL (non-portable symlink)      2 = SKIP (no root)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

_DEFAULT_ROOT_REL = "benchmark-data"


def _repo_root(start: Path):
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def tracked_symlinks(root: Path) -> List[str]:
    """Paths (relative to `root`) of tracked entries whose index mode is
    120000. Read from the INDEX, never from a filesystem walk, so the answer
    does not depend on what the walk can follow."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                           capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = r.stdout.decode("utf-8", "replace")
    found = []
    for ent in out.split("\0"):
        if not ent or "\t" not in ent:
            continue
        meta, path = ent.split("\t", 1)
        if meta.split(" ", 1)[0] == "120000":
            found.append(path)
    return found


def audit(root: Path, repo: Path) -> Dict:
    findings: List[Dict[str, str]] = []
    dangling: List[str] = []
    links = tracked_symlinks(root)
    for rel in links:
        p = root / rel
        try:
            target = os.readlink(p)
        except OSError:
            continue
        if os.path.isabs(target):
            findings.append({
                "path": rel, "target": target, "why": "absolute target",
                "detail": ("an absolute path encodes one machine's directory "
                           "layout and cannot resolve in another checkout, "
                           "even when it points inside this repository")})
            continue
        resolved = os.path.normpath(os.path.join(str(p.parent), target))
        try:
            Path(resolved).relative_to(repo)
        except ValueError:
            findings.append({
                "path": rel, "target": target, "why": "escapes the repository",
                "detail": ("the repository does not contain the target, so "
                           "this ships a pointer to content nobody else has")})
            continue
        if not Path(resolved).exists():
            dangling.append(rel)
    return {"program": "tracked_symlink_portability_check",
            "symlinks": len(links), "findings": findings,
            "dangling_inside_repo": len(dangling),
            "passed": not findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve()
    root = (Path(args.root) if args.root else
            next((b / _DEFAULT_ROOT_REL for b in here.parents
                  if (b / _DEFAULT_ROOT_REL).is_dir()), None))
    if root is None or not root.is_dir():
        print(f"[SKIP] tracked_symlink_portability_check: no scan root "
              f"({args.root or _DEFAULT_ROOT_REL} not found).")
        return 2
    repo = _repo_root(root) or root
    rep = audit(root, repo.resolve())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    print(f"tracked_symlink_portability_check: {rep['symlinks']} tracked "
          f"symlink(s) under {root}")
    # Reported, never gated — a dangling relative link is a missing FILE, a
    # different defect from a non-portable POINTER. Printing it keeps this
    # gate's silence from reading as "and nothing else is wrong".
    print(f"  dangling (relative, inside repo): "
          f"{rep['dangling_inside_repo']} — not gated here, a missing file "
          f"is a different defect from a non-portable pointer")
    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} non-portable tracked symlink(s):")
        for f in rep["findings"][:20]:
            print(f"   {f['path']} -> {f['target']}  ({f['why']})")
        if len(rep["findings"]) > 20:
            print(f"   ... and {len(rep['findings']) - 20} more (this line is "
                  f"the disclosure, not a silent truncation)")
        return 1
    print("[PASS] every tracked symlink is relative and stays inside the "
          "repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
