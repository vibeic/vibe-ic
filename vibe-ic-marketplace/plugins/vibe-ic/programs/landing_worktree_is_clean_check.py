#!/usr/bin/env python3
"""landing_worktree_is_clean_check.py — the gate verifies COMMITS; a tracked
file still modified in the worktree means what was verified is not what the
author has.

THIS GATE BLOCKS (rc=1).

THE DEFECT (vibe-ic, v1.9.12), which is mine
============================================
`3e7f1490f` landed under the subject "undecided silence is a hard error, not a
report" and did not contain the hard error. #591 changes four files; the landing
carried two of them. Measured on the remote by the string only the new branch
prints:

    origin/main   "NO recorded decision anywhere"   0 occurrences
    PR #591       "NO recorded decision anywhere"   1

So the checker went on printing the undecided count and returning 0 — the exact
defect that PR exists to end — under a commit message asserting otherwise.

HOW. Rebuilding the batch to move the version onto the tip:

    git reset --soft HEAD~1        # the changes go to the INDEX
    git stash push --staged        # ... and into the stash
    git commit --amend ...         # fix the commit below
    git stash pop                  # WITHOUT --index -> they return UNSTAGED
    git add <3 manifests> flow_compliance_check.py    # an incomplete list

`git stash pop` without `--index` does not restore staged-ness, and an explicit
`git add` — the right habit, and the reason nothing junk ever lands — names a
list that a human wrote. Two of the four files were not on it. They sat unstaged
through the gate, the push, and the following round's `git status`.

WHY EVERY OTHER GATE PASSED
===========================
The test file was left behind together with the code it tests. So main received
the OLD checker and the OLD tests, and they agree with each other. The landed
state is SELF-CONSISTENT, and self-consistency is what a test suite measures. A
partial land whose omissions are mutually consistent is invisible to anything
reasoning about the tree alone — the suite, the audits, the compliance checks all
read a coherent repository.

The only thing that distinguishes it is that the author's worktree still held
the missing half.

WHAT THIS MEASURES
==================
Tracked modifications (M / A / D / R) under the paths that SHIP, at the moment
the landing gate runs. UNTRACKED files are ignored on purpose: benchmark runs
scatter reports through the corpus, they are never committed by an explicit
`git add`, and failing on them would make this a gate people route around.

Scope is stated rather than "the repo", because a gatekeeper's checkout also
holds scratch clones and probe output that have nothing to do with the batch.

chip-AGNOSTIC: reads git status. No design, PDK or vendor input.

USAGE
-----
    landing_worktree_is_clean_check.py [<repo>] [--json OUT]

EXIT CODES
----------
    0 = PASS     1 = a tracked file is modified     2 = not a git repo
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: The paths whose contents reach a user. A modification here at land time is
#: either work that belongs in the batch or work that does not belong in the
#: repo; both need an answer before the push.
SHIPPED_PATHS = (
    "vibe-ic-marketplace",
    "tools",
    ".claude-plugin",
)

RC_OK, RC_DIRTY, RC_CANNOT_MEASURE = 0, 1, 2


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=120)


def modified_tracked(repo: Path, paths=SHIPPED_PATHS):
    """`[(status, path)]` for every TRACKED modification under `paths`.

    `--porcelain` statuses are two columns (index, worktree). A `??` is
    untracked and excluded; everything else means git is tracking the file and
    it differs from HEAD in one column or the other.
    """
    present = [p for p in paths if (repo / p).exists()]
    if not present:
        return None
    r = _git(repo, "status", "--porcelain", "--", *present)
    if r.returncode != 0:
        return None
    out = []
    for line in (r.stdout or "").splitlines():
        if not line.strip() or line.startswith("??"):
            continue
        out.append((line[:2], line[3:].strip()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    if _git(repo, "rev-parse", "--git-dir").returncode != 0:
        print(f"[SKIP] landing_worktree_is_clean: {repo} is not a git "
              f"repository — nothing was measured, which is not a pass",
              file=sys.stderr)
        return RC_CANNOT_MEASURE

    dirty = modified_tracked(repo)
    if dirty is None:
        print("[SKIP] landing_worktree_is_clean: none of the shipped paths "
              f"({', '.join(SHIPPED_PATHS)}) exist here, so nothing was "
              f"compared — a gap in the check, not a pass", file=sys.stderr)
        return RC_CANNOT_MEASURE

    report = {"repo": str(repo), "scope": list(SHIPPED_PATHS),
              "modified_tracked": [{"status": s, "path": p} for s, p in dirty]}
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(report, indent=2) + "\n")

    if dirty:
        print(f"[FAIL] landing_worktree_is_clean: {len(dirty)} tracked file(s) "
              f"modified under {', '.join(SHIPPED_PATHS)}:", file=sys.stderr)
        for s, p in dirty:
            print(f"    {s}  {p}", file=sys.stderr)
        print("\n  This gate verifies COMMITS. A tracked modification here means "
              "the tree\n  it verified is not the tree you have — either the "
              "change belongs in the\n  batch and was dropped, or it does not "
              "belong in the repo.\n\n  v1.9.12 landed half of #591 exactly this "
              "way: two of its four files sat\n  unstaged after a `git stash pop` "
              "(which does not restore staged-ness)\n  and an explicit `git add` "
              "that named the other two. The suite passed,\n  because the test "
              "file was left behind with the code it tests.",
              file=sys.stderr)
        return RC_DIRTY

    print("[PASS] landing_worktree_is_clean: no tracked modification under "
          + ", ".join(SHIPPED_PATHS))
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
