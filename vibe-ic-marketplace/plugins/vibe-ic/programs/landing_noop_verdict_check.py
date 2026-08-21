#!/usr/bin/env python3
"""landing_noop_verdict_check.py — "nothing to land" is a claim about the TWO
TREES, and a merge tool can only answer for its own staging area.

THIS GATE BLOCKS (rc=1). It refuses a no-op landing verdict that the trees do
not support, and prints every path that contradicts it.

THE DEFECT, MEASURED 2026-08-21
===============================
A batch landing logged ``NOTHING TO LAND`` for a lane whose branch, hashed file
by file against the trunk, differed in FOUR files — three of them not generated.
That lane's work was one push away from being dropped without a word.

The tool was not lying. It was answering a different question. In a repository
that SQUASH-lands, content reaches the trunk WITHOUT ancestry:

    merge base ─────────────────────────► lane tip      (the work, as commits)
         └──────────► trunk (a squash of some of it, as ONE unrelated commit)

so the merge base stays far behind whatever has already landed, and the tool
re-derives the lane's WHOLE difference every time. A conflict path that resolves
one file, stages it, and then reads ``git status --porcelain`` is asking the
staging area — which is empty because the resolution is finished — instead of
asking the trees. "My index is clean" and "these two trees agree" are different
sentences, and only the second one is a landing verdict.

WHAT THIS ASKS INSTEAD
======================
For every path the LANE ITSELF touches (``merge-base(branch, target)..branch``),
compare the branch's blob against the target's blob. A git blob object name IS
the content hash — the same instrument ``tools/ci/trusted_worktree_attest.py``
uses — so "byte-identical" is decided, never estimated.

Four outcomes per path, and each is a different remedy, so each is named:

    IDENTICAL   the two trees hold the same bytes; this path really did land
    CONTENT     both trees hold the path, with different bytes
    ABSENT      the branch adds/holds it, the target has never seen it
    UNDELETED   the branch deletes it, the target still carries it

Anything but IDENTICAL refuses. The no-op verdict is a claim of universal
identity, and one counter-example is enough to end it.

WHY GENERATED PATHS ARE LABELLED AND NOT EXCLUDED
=================================================
``--generated PATTERN`` (repeatable, ``fnmatch`` syntax) does NOT waive a path.
It labels one, because the two remedies differ and the operator has to pick:
a generated file is repaired by RE-RUNNING its generator on the merged tree,
and everything else is repaired by applying the lane's bytes. Excluding them
instead would reintroduce the defect one category down — the measured lane had
three non-generated files and one generated one, and an exclusion would have
made the report say "one file" about a four-file loss.

THE EXIT CODE IS ABOUT THE CLAIM, NOT ABOUT THE TREES
=====================================================
Two callers ask opposite questions of the same measurement, so the CLAIM is an
argument rather than something a reader has to invert in their head:

    --claim noop   (default)  "nothing to land"      — a batch landing's verdict
    --claim work              "there is work here"   — a landing gate's premise

`--claim work` exists because this repository already carries the weak form of
the same mistake: `tools/gatekeeper-land-differential.sh` refuses a landing when
`BASE_SHA = HEAD_SHA`, which is ANCESTRY. A branch that was squash-landed and
then rebased has a different HEAD and identical bytes, and an hour of gates runs
over a landing with nothing in it.

EXIT CODES
==========
    0  the CLAIM holds — no touched path differs under `--claim noop`, at least
       one does under `--claim work`
    1  REFUSED — the claim does not hold; the differing paths are printed
    2  VACUOUS — the branch touches NO path relative to the merge base, so
       there is no landing claim to check (`_vacuous_exit`'s tier, and it is
       announced, never a silent pass)
    3  the command line was rejected — a ref that does not resolve, a path
       that is not a repository. NOTHING was examined (`_gate_usage_exit`)

USAGE
-----
    landing_noop_verdict_check.py --branch <ref> --target <ref>
                                 [--claim noop|work] [--repo DIR]
                                 [--generated GLOB]... [--json OUT]

chip-AGNOSTIC: git plumbing only. No design, PDK, vendor, node or SKU literal.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac

TOOL = "landing_noop_verdict_check"

#: Per-path verdicts. IDENTICAL is the only one a no-op claim survives.
IDENTICAL = "IDENTICAL"
CONTENT = "CONTENT"
ABSENT_FROM_TARGET = "ABSENT"
UNDELETED_IN_TARGET = "UNDELETED"

_WHY = {
    CONTENT: "both trees hold it, with different bytes",
    ABSENT_FROM_TARGET: "the branch holds it, the target has never seen it",
    UNDELETED_IN_TARGET: "the branch deletes it, the target still carries it",
}


class Refused(Exception):
    """A command line this program will not act on. Maps to rc 3."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=300)


def resolve(repo: Path, ref: str, what: str) -> str:
    """The commit `ref` names, or a refusal that says which argument was wrong.

    ``^{commit}`` is appended so a tag or a tree given where a commit belongs is
    rejected here rather than producing an empty file list two calls later.
    """
    r = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if r.returncode != 0 or not r.stdout.strip():
        raise Refused(f"--{what} {ref!r} does not resolve to a commit in {repo}")
    return r.stdout.strip()


def touched_paths(repo: Path, base: str, branch: str) -> List[str]:
    """Every path the LANE touches, from its own merge base forward.

    NOT ``diff target branch``: that answers "how do these trees differ", which
    over a squash-landing trunk includes every path anybody else moved since the
    fork. The question here is what THIS lane claims to carry.
    """
    r = _git(repo, "diff", "--name-only", "-z", f"{base}..{branch}")
    if r.returncode != 0:
        raise Refused(f"git diff {base}..{branch} failed: {r.stderr.strip()[:200]}")
    return sorted(p for p in r.stdout.split("\0") if p)


def blob_index(repo: Path, commit: str) -> Dict[str, str]:
    """``{path: "<type>:<object name>"}`` for one commit, in a single git call.

    A blob's object name is the hash of its content, so equality of two names is
    equality of two files. Read with ``-z`` because a path may legitimately
    contain anything but NUL.

    THE TYPE IS PART OF THE KEY, and filtering to ``blob`` would be a false pass.
    A gitlink (``160000 commit``) is a real content change at a real path; drop
    it here and the path is absent from BOTH indexes, which :func:`classify`
    reads as "both trees deleted it" — IDENTICAL. This repository carries no
    submodule today, so nothing exercises it; a rule that is wrong only while a
    fact happens to hold is the shape this whole batch is about.
    """
    r = _git(repo, "ls-tree", "-r", "-z", commit)
    if r.returncode != 0:
        raise Refused(f"git ls-tree {commit} failed: {r.stderr.strip()[:200]}")
    out: Dict[str, str] = {}
    for rec in r.stdout.split("\0"):
        if not rec:
            continue
        meta, _, path = rec.partition("\t")
        parts = meta.split()
        if len(parts) >= 3:
            out[path] = f"{parts[1]}:{parts[2]}"
    return out


def classify(paths: List[str], branch_blobs: Dict[str, str],
             target_blobs: Dict[str, str]) -> List[Tuple[str, str]]:
    """``[(path, verdict)]`` for every touched path, in path order."""
    rows: List[Tuple[str, str]] = []
    for p in paths:
        b, t = branch_blobs.get(p), target_blobs.get(p)
        if b is None and t is None:
            rows.append((p, IDENTICAL))       # both trees deleted it
        elif b is None:
            rows.append((p, UNDELETED_IN_TARGET))
        elif t is None:
            rows.append((p, ABSENT_FROM_TARGET))
        else:
            rows.append((p, IDENTICAL if b == t else CONTENT))
    return rows


def is_generated(path: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def main(argv: Optional[List[str]] = None) -> int:
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse a no-op landing verdict the two trees do not support")
    ap.add_argument("--branch", required=True, help="the lane being landed")
    ap.add_argument("--target", required=True,
                    help="the tree it claims to have landed on")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--generated", action="append", default=[], metavar="GLOB",
                    help="label (never waive) a differing path as generated, so "
                         "the report names the right remedy; repeatable")
    ap.add_argument("--claim", choices=("noop", "work"), default="noop",
                    help="what the caller asserts about these two trees; the "
                         "exit code answers THAT, so neither caller has to "
                         "invert a verdict")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    repo = args.repo
    try:
        if not (repo / ".git").exists() and not (repo / "HEAD").exists():
            raise Refused(f"--repo {repo} is not a git repository")
        branch = resolve(repo, args.branch, "branch")
        target = resolve(repo, args.target, "target")
        mb = _git(repo, "merge-base", branch, target)
        if mb.returncode != 0 or not mb.stdout.strip():
            raise Refused(
                f"{args.branch} and {args.target} share no merge base, so what "
                f"this lane touches cannot be derived and no verdict is possible")
        base = mb.stdout.strip()
        paths = touched_paths(repo, base, branch)
        branch_blobs = blob_index(repo, branch)
        target_blobs = blob_index(repo, target)
    except Refused as exc:
        return _usage.usage_error(TOOL, str(exc))

    rows = classify(paths, branch_blobs, target_blobs)
    differing = [(p, v) for p, v in rows if v != IDENTICAL]
    gen = [p for p, _ in differing if is_generated(p, args.generated)]

    report = {
        "tool": TOOL,
        "branch": branch, "target": target, "merge_base": base,
        "claim": args.claim,
        "touched": len(rows),
        "identical": len(rows) - len(differing),
        "differing": [{"path": p, "verdict": v,
                       "generated": is_generated(p, args.generated)}
                      for p, v in differing],
    }
    if args.json:
        _atomic.write_json(args.json, report)

    if not rows:
        _vac.announce_vacuous(
            TOOL, "branch-touches-nothing")
        print(f"[VACUOUS] {TOOL}: {args.branch} touches no path relative to its "
              f"merge base with {args.target}; there is no landing claim to "
              f"check, and this is NOT a verified no-op")
        return _vac.RC_VACUOUS

    if differing:
        for p, v in differing:
            tag = " [generated]" if is_generated(p, args.generated) else ""
            print(f"  [{'NOT LANDED' if args.claim == 'noop' else 'TO LAND'}] "
                  f"{p}{tag} — {_WHY[v]}")
        if args.claim == "noop":
            print(f"[FAIL] {TOOL}: {len(differing)} of {len(rows)} path(s) the "
                  f"branch touches are NOT byte-identical to {args.target} "
                  f"({len(gen)} generated, {len(differing) - len(gen)} not). A "
                  f"no-op landing verdict over this pair is wrong: re-run the "
                  f"generator on the merged tree for the generated ones and "
                  f"apply the lane's bytes for the rest.")
            return _vac.RC_FAIL
        print(f"[PASS] {TOOL}: {len(differing)} of {len(rows)} path(s) the "
              f"branch touches differ from {args.target}; there is work to land")
        return _vac.RC_PASS

    if args.claim == "work":
        print(f"[FAIL] {TOOL}: all {len(rows)} path(s) the branch touches are "
              f"already byte-identical to {args.target}, so this landing "
              f"carries nothing. Ancestry says otherwise — a squash-landed "
              f"branch that was then rebased has a different HEAD and the same "
              f"bytes — and an hour of gates over an empty landing measures "
              f"the base.")
        return _vac.RC_FAIL

    print(f"[PASS] {TOOL}: all {len(rows)} path(s) the branch touches are "
          f"byte-identical to {args.target}; the no-op verdict is verified")
    return _vac.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
