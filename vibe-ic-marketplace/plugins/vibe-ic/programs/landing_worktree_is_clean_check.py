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

THE SECOND EDGE (v1.9.16, also mine)
====================================
Closing the BEFORE edge left the AFTER edge open. This check sits in the landing
gate's cheap tier; the full tier then runs for MINUTES, and the stamp is written
at the end. Measured on the v1.9.16 run:

    10:28:14   gate starts, tree clean, this check PASSES
    10:35:50   `mixed_signal_top_lvs_run.py` edited   (#597, uncommitted)
    10:37:49   a new test file written
    10:41      targeted tests run, "ALL GATES PASS - stamped 9fd81bb45"

The 16 targeted test files were selected from the COMMIT RANGE and executed
against a worktree carrying an unrelated uncommitted change. The stamp names a
commit; the suites read a tree that is not that commit and never was. Either
direction is wrong: the edit could have broken something the batch is blamed
for, or it could have repaired something the batch would otherwise have failed.

So the question is not only "is the tree clean when we start" but "is it the
SAME tree when we stamp". `--emit-fingerprint` records it at the start,
`--expect-fingerprint` re-checks and compares before the stamp is written.

WHAT THE FINGERPRINT DOES NOT COVER, stated because a bound nobody states gets
read as a guarantee: a change made AND reverted entirely inside the full tier
leaves an identical fingerprint. The suites still read the mutated tree. This
narrows the window from "the whole expensive tier" to "an edit undone within
it"; it does not eliminate it, and only running the gates on a private checkout
would.

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
    landing_worktree_is_clean_check.py <repo> --emit-fingerprint <file>
    landing_worktree_is_clean_check.py <repo> --expect-fingerprint <file>

EXIT CODES
----------
    0 = PASS     1 = a tracked file is modified, or the tree moved under the
                     gates since the fingerprint was taken
    2 = not a git repo, or a fingerprint was expected and none was recorded
"""
from __future__ import annotations

import argparse
import hashlib
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
    # v1.9.35 — the repo-root install docs, added because leaving them out cost
    # exactly what this check exists to prevent. `sync_image_version --check`
    # validates 24 image pointers across 9 files and reads them FROM THE
    # WORKTREE; two of those files (`README.md`, `docs/INSTALL.md`) live outside
    # the three roots above. A landing advanced the image anchor to 0.2.53,
    # `--check` passed on the worktree, and the doc edits were never committed —
    # so main went on telling users to pull an image tag one release stale while
    # every gate said the pointers were consistent.
    #
    # THE RULE THIS ENCODES: a path that any landing gate READS must be a path
    # this check GUARDS, or the gate is certifying a tree the commit does not
    # contain. `test_landing_worktree_is_clean` pins the two lists together.
    "README.md",
    "docs",
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


def fingerprint(repo: Path, paths=SHIPPED_PATHS):
    """A digest of what the suites will READ, or None if it cannot be taken.

    Three parts, because three different things move a tree out from under a
    running gate:

      HEAD          a commit landing mid-run
      tracked diff  an edit to a file already in the repo   <- the v1.9.16 case
      untracked set an added file pytest can collect

    The untracked part is NAMES only. Hashing their contents would flip on every
    tool that writes beside the code, and `git status` already drops anything
    .gitignore covers, which is what keeps `__pycache__` out of it. Verified by
    taking the fingerprint on both sides of a pytest run rather than assumed.
    """
    present = [p for p in paths if (repo / p).exists()]
    if not present:
        return None
    head = _git(repo, "rev-parse", "HEAD")
    diff = _git(repo, "diff", "HEAD", "--", *present)
    stat = _git(repo, "status", "--porcelain", "--", *present)
    if any(r.returncode != 0 for r in (head, diff, stat)):
        return None
    untracked = sorted(l[3:].strip() for l in (stat.stdout or "").splitlines()
                       if l.startswith("??"))
    h = hashlib.sha256()
    h.update(head.stdout.strip().encode())
    h.update(b"\0")
    h.update((diff.stdout or "").encode())
    h.update(b"\0")
    h.update("\n".join(untracked).encode())
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--emit-fingerprint", metavar="FILE",
                    help="record the tree state for a later --expect-fingerprint")
    ap.add_argument("--expect-fingerprint", metavar="FILE",
                    help="fail if the tree moved since FILE was written")
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

    # The tree is clean NOW. Whether it is the same tree the gates started on
    # is a different question, and the one v1.9.16 got wrong.
    fp = fingerprint(repo)
    if a.expect_fingerprint:
        want_path = Path(a.expect_fingerprint)
        if not want_path.is_file():
            print(f"[SKIP] landing_worktree_is_clean: --expect-fingerprint "
                  f"{want_path} does not exist, so the tree was NOT compared "
                  f"against its state at the start of the run. Not a pass.",
                  file=sys.stderr)
            return RC_CANNOT_MEASURE
        want = want_path.read_text(errors="replace").strip()
        if fp is None or not want:
            print("[SKIP] landing_worktree_is_clean: the fingerprint could not "
                  "be taken on one side, so no comparison was made",
                  file=sys.stderr)
            return RC_CANNOT_MEASURE
        if fp != want:
            print(f"[FAIL] landing_worktree_is_clean: the worktree MOVED while "
                  f"the gates were running.\n    at start  {want[:16]}\n"
                  f"    now       {fp[:16]}\n\n"
                  "  The expensive tier reads the worktree; the stamp names a "
                  "COMMIT. If the\n  two disagree, the suites did not verify "
                  "what is about to be pushed —\n  an edit made during the run "
                  "can hide a failure in the batch or take the\n  blame for "
                  "one. Re-run the gate on a settled tree.",
                  file=sys.stderr)
            return RC_DIRTY
    if a.emit_fingerprint:
        if fp is None:
            print("[SKIP] landing_worktree_is_clean: could not take a "
                  "fingerprint; the end-of-run comparison will refuse",
                  file=sys.stderr)
            return RC_CANNOT_MEASURE
        Path(a.emit_fingerprint).write_text(fp + "\n")

    print("[PASS] landing_worktree_is_clean: no tracked modification under "
          + ", ".join(SHIPPED_PATHS)
          + (f"; tree unchanged since the gates started ({fp[:12]})"
             if a.expect_fingerprint and fp else ""))
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())

# selector-probe: no-op line added by the xdist equivalence experiment
