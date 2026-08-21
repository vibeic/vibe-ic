#!/usr/bin/env python3
"""landing_is_one_commit_check.py — a landing is ONE commit, not two.

THE DEFECT (vibe-ic#459), which is mine
=======================================
The standing instruction is squash-merge. Three landings left TWO commits on
main: the authoring branch's original (no version) plus a version commit
carrying ONLY the three manifest files.

    v1.7.37   0680f728d (2 files, no version)  +  f5b1156b7 (3 manifests only)
    v1.7.38   7bf4ec927 (8 files, no version)  +  16d5250ac (3 manifests only)
    v1.7.39   bd80e9271 (3 files, no version)  +  fe51754f1 (3 manifests only)

ROOT CAUSE: after `git rebase origin/main`, `git commit --amend` touches only
the TOP commit; the authoring commit underneath survives. The correct sequence
includes `git reset --soft <base>` first, which flattens it. Dropping that one
step changes the shape silently — nothing failed, nothing warned.

WHY IT IS NOT MERELY UNTIDY: GitHub runs CI on the LAST commit of a push, so
the intermediate commit has no CI record of its own. An audit of "every version
is green" reads as a hole there. And reverting one landing becomes two reverts.

WHAT THIS DETECTS, AND WHY IT IS THIS NARROW
=============================================
MEASURED over the last 200 commits of main before this landed:

    commits with no version tag                     89
    the actual defect shape (a version commit that
    carries ONLY manifests, sitting directly on an
    unversioned commit)                              4

So keying on "unversioned commit" would fire 89 times, and 85 of those are
legitimate: data-only landings, security bumps and doc commits that
`ships_to_users()` correctly exempts from versioning altogether. The signal is
the PAIR — a version commit that changed nothing but the manifests, directly
above a commit that changed real files and carries no version. That is
mechanically what an un-squashed landing looks like and what nothing else does.

A population of four is small, and a detector for a population of ONE earns
deletion rather than a landing (vibe-ic#439). Four is above that floor, three of
them were made on a single day, and the failure is silent — which is the
combination that justifies a check rather than a note.

v1.7.65 — THE CHECK WAS MEASURING THE WRONG TREE
=================================================
`head_is_one_commit` hard-coded `base..HEAD`, and `gatekeeper_review` never
passed the `--head` it was reviewing. So a REVIEW of somebody else's branch
counted the REVIEWER'S OWN working checkout instead of the branch under
review. Reproduced end to end: with the working tree parked on a clean
one-commit landing, reviewing a three-commit branch whose tip carries only the
version manifests — this program's exact defect shape — returned

    [PASS] landing_is_one_commit: one commit ahead of <base> - a squashed landing

rc 0, over a tree nobody was reviewing. The gate that exists to catch an
unsquashed landing certified one. `head` is now a parameter, defaulting to
HEAD so the pre-push use is unchanged, and an unresolvable ref is rc 2 (NOT
CHECKED) rather than a verdict about some other branch.

chip-AGNOSTIC: pure git history shape; no design, PDK or vendor name.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_VERSION_RE = re.compile(r"\[v\d+\.\d+\.\d+\]")

# The manifests a version bump touches, and NOTHING else. A landing that only
# rewrites these is not a change; it is the tail of a change that was left
# behind.
_MANIFEST_SUFFIXES = (".claude-plugin/plugin.json",
                      ".claude-plugin/marketplace.json")


def _git(repo: Path, *args: str) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return r.returncode, r.stdout


def _is_manifest_only(repo: Path, sha: str) -> Optional[bool]:
    """True when this commit changed manifests and nothing else.

    None when the file list cannot be read — never False, because "I could not
    look" must not read the same as "I looked and it was fine".
    """
    rc, out = _git(repo, "show", "--name-only", "--format=", sha)
    if rc != 0:
        return None
    files = [f for f in out.split() if f]
    if not files:
        return None
    return all(f.endswith(_MANIFEST_SUFFIXES) for f in files)


def find_unsquashed(repo: Path, limit: int = 200) -> Tuple[List[Dict], int]:
    """Landings that left two commits. Returns (findings, commits_examined)."""
    rc, out = _git(repo, "log", "--format=%H|%s", f"-{limit}")
    if rc != 0:
        return [], 0
    rows = [line.split("|", 1) for line in out.splitlines() if "|" in line]
    findings: List[Dict] = []
    for top, below in zip(rows, rows[1:]):
        top_sha, top_subject = top
        low_sha, low_subject = below
        if not _VERSION_RE.search(top_subject):
            continue                       # not a version commit
        if _VERSION_RE.search(low_subject):
            continue                       # the one below is its own landing
        if _is_manifest_only(repo, top_sha) is not True:
            continue                       # a real landing; carries content
        findings.append({
            "version_commit": top_sha[:9],
            "version_sha": top_sha,
            "version_subject": top_subject[:100],
            "authoring_commit": low_sha[:9],
            "authoring_subject": low_subject[:100],
        })
    return findings, len(rows)


#: The ref that decides whether a finding is still this operator's to fix.
PUBLISHED_REF = "refs/remotes/origin/main"


def published_head(repo: Path, ref: str = PUBLISHED_REF) -> Optional[str]:
    """The commit everyone else already has, or None if it cannot be resolved.

    None is NOT "nothing is published". It is "this program could not find out",
    and the caller must treat the two differently — see :func:`split_by_reach`.
    """
    rc, out = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    sha = out.strip()
    return sha if rc == 0 and sha else None


def split_by_reach(repo: Path, findings: List[Dict],
                   ref: str = PUBLISHED_REF) -> Tuple[List[Dict], List[Dict], Optional[str]]:
    """Split findings into (already published, still local, why-unknown).

    A finding reachable from the published ref is HISTORY. Nobody can squash it
    now without rewriting a branch other people have, so refusing it does not
    prevent the defect — it only bans every future landing until the commit
    scrolls out of `--limit`. A gate that refuses every landing is the ban this
    repo already learned to distrust: `landing_merge_verdict.py` says so in its own
    docstring, and the reason it says so is that a ban teaches the operator to
    bypass, which is how the landing path lost its gate in the first place.

    A finding NOT reachable from it is the one this operator can still fix with
    `git reset --soft <base>` — the exact missing step in #459 — and it is the only
    moment the defect can be prevented. That one still REFUSES.

    If the ref cannot be resolved the split is UNKNOWN, and the caller degrades
    toward the stricter side: everything counts as still-local and refuses. Reading
    an unresolvable ref as "it must all be published" would turn one absent ref into
    a blanket exemption.
    """
    head = published_head(repo, ref)
    if head is None:
        return [], list(findings), (
            f"{ref} does not resolve here, so no finding could be shown to be "
            f"already published; every one is judged as still local")
    published, local = [], []
    for f in findings:
        sha = f.get("version_sha") or f.get("version_commit")
        rc, _ = _git(repo, "merge-base", "--is-ancestor", sha, head)
        (published if rc == 0 else local).append(f)
    return published, local, None


def head_is_one_commit(repo: Path, base: str,
                       batch: bool = False,
                       head: str = "HEAD") -> Tuple[bool, int, str]:
    """The pre-push form: `base..head` must be exactly one commit.

    `head` defaults to the working HEAD, which is the pre-push use. A REVIEW
    of somebody else's branch MUST pass the ref under review — see the
    v1.7.65 note in the module docstring for why leaving it implicit produced
    a PASS over a tree nobody was reviewing.

    This is the check that would have caught #459 at the time, and it costs one
    `rev-list`. Returns (ok, count, detail)."""
    # An UNCOUNTABLE range (a synthetic ref, a shallow clone) has told us
    # nothing. It returns n = -1, which main() reports as rc 2 / NOT CHECKED —
    # never rc 1, which would block a landing on the strength of a ref this
    # program could not resolve. Same rule the sibling landing-method guard
    # follows, and the rc-2-is-not-a-pass discipline used across this tree.
    rc, out = _git(repo, "rev-list", "--count", f"{base}..{head}")
    if rc != 0:
        return False, -1, (f"could not count commits in {base}..{head}: "
                           f"{out.strip()}")
    try:
        n = int(out.strip())
    except ValueError:
        return False, -1, f"unreadable rev-list output: {out.strip()!r}"
    if n == 0:
        return False, n, (f"NOTHING to land: {head} == {base}. This is not a "
                          f"pass; a landing that adds no commit landed "
                          f"nothing.")
    if n == 1:
        return True, n, f"one commit ahead of {base} — a squashed landing"
    if not batch:
        return False, n, (
            f"{n} commits ahead of {base} — a single landing must be ONE commit. "
            f"`git commit --amend` after a rebase touches only the top commit and "
            f"leaves the authoring commit underneath; run "
            f"`git reset --soft {base}` first, then a single `git commit`. "
            f"If this is a deliberate BATCH of several PR landings, pass "
            f"--batch, which checks the batch's own shape instead.")

    # BATCH MODE — several PR landings pushed together under one version bump
    # and one CI run. The per-landing rule does not apply, but the defect it
    # exists for still does, so the batch is checked for a STRICTLY STRONGER
    # property rather than waved through:
    #
    #   * no commit in the range may be manifest-only — that is exactly the
    #     stranded version commit this program was written for, and a batch is
    #     not a licence to leave one;
    #   * exactly ONE commit may carry a version bump, and it must be the LAST,
    #     so the pushed tip is the version the batch publishes and every
    #     intermediate commit is a real landing.
    rc, out = _git(repo, "rev-list", "--reverse", f"{base}..{head}")
    shas = [s for s in out.split() if s]
    if rc != 0 or len(shas) != n:
        return False, -1, f"could not list the {n} commits in {base}..{head}"
    bare, versioned = [], []
    for sha in shas:
        if _is_manifest_only(repo, sha) is True:
            bare.append(sha[:9])
        rc2, subj = _git(repo, "log", "-1", "--format=%s", sha)
        if rc2 == 0 and _VERSION_RE.search(subj):
            versioned.append(sha[:9])
    if bare:
        return False, n, (
            f"batch of {n}, but {len(bare)} commit(s) carry ONLY the version "
            f"manifests: {bare}. A batch does not excuse a stranded version "
            f"commit — that is the defect this check exists for.")
    if len(versioned) != 1:
        return False, n, (
            f"batch of {n} carries {len(versioned)} version-tagged commit(s) "
            f"{versioned}; a batch publishes exactly ONE version.")
    if versioned[0] != shas[-1][:9]:
        return False, n, (
            f"batch of {n} bumps the version at {versioned[0]}, which is not "
            f"the tip ({shas[-1][:9]}). The pushed tip must be the version the "
            f"batch publishes, or CI green refers to a tree nobody released.")
    return True, n, (
        f"batch of {n} landing(s) ahead of {base}: no manifest-only commit, "
        f"one version bump, carried by the tip")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--base", default=None,
                    help="pre-push mode: assert base..HEAD is exactly one commit")
    ap.add_argument("--head", default="HEAD",
                    help="pre-push mode: the ref UNDER REVIEW (default HEAD, "
                         "the reviewer's own working checkout). A review of "
                         "somebody else's branch MUST pass it, or the answer "
                         "describes the wrong tree.")
    ap.add_argument("--batch", action="store_true",
                    help="several PR landings under one version bump and one CI "
                         "run: check the batch's shape instead of demanding one "
                         "commit (see head_is_one_commit)")
    ap.add_argument("--limit", type=int, default=200,
                    help="history mode: how many commits to examine")
    ap.add_argument("--published-ref", default=PUBLISHED_REF,
                    help="history mode: the ref that decides whether a finding is "
                         "still fixable. A finding reachable from it is history and "
                         "is reported; one that is not is refused.")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    if a.base:
        ok, n, detail = head_is_one_commit(repo, a.base, batch=a.batch,
                                           head=a.head)
        label = "PASS" if ok else ("NOT CHECKED" if n < 0 else "FAIL")
        print(f"[{label}] landing_is_one_commit: {detail}", file=sys.stderr)
        if a.json_out:
            Path(a.json_out).write_text(json.dumps(
                {"mode": "pre_push", "base": a.base, "head": a.head,
                 "ok": ok, "commits": n, "detail": detail}, indent=2) + "\n")
        return 0 if ok else (2 if n < 0 else 1)

    findings, examined = find_unsquashed(repo, a.limit)

    if examined == 0:
        # This program's own denominator. Reporting clean over an unread
        # history is the false-certificate class this repo keeps closing.
        print("[NOTHING_SCANNED] landing_is_one_commit: read 0 commits — this "
              "is NOT a pass, no landing was examined.", file=sys.stderr)
        return 2

    published, local, unknown_why = split_by_reach(repo, findings, a.published_ref)
    if a.json_out:
        # The split is in the record, not only the total: a reader who sees one
        # number cannot tell a landing that must be fixed from one that cannot be.
        Path(a.json_out).write_text(json.dumps(
            {"mode": "history", "commits_examined": examined,
             "published_ref": a.published_ref,
             "findings": findings,
             "unpublished_findings": local,
             "published_findings": published,
             "reach_unknown": unknown_why}, indent=2) + "\n")

    for f in local:
        print(f"  [UNSQUASHED_LANDING] {f['version_commit']} carries only the "
              f"version manifests", file=sys.stderr)
        print(f"      sitting on {f['authoring_commit']} "
              f"{f['authoring_subject'][:70]}", file=sys.stderr)
        print(f"      NOT YET PUBLISHED — fix it with "
              f"`git reset --soft <base>` and recommit as one.", file=sys.stderr)
    for f in published:
        print(f"  [ALREADY_PUBLISHED] {f['version_commit']} on "
              f"{f['authoring_commit']} — recorded, not refused; squashing it now "
              f"would rewrite a branch other people have.", file=sys.stderr)
    if unknown_why:
        print(f"  [REACH_UNKNOWN] {unknown_why}", file=sys.stderr)

    if local:
        # Refuse ONLY for what this operator can still change. This is the one
        # moment the defect is preventable, and it stays a hard refusal.
        print(f"[FAIL] landing_is_one_commit: {len(local)} unpublished landing(s) "
              f"of {examined} commit(s) examined left the authoring commit AND a "
              f"version commit. ({len(published)} further finding(s) are already on "
              f"{a.published_ref} and are reported, not refused.)", file=sys.stderr)
        return 1
    if published:
        # A finding nobody can act on must not hold the gate shut forever. It is
        # still printed above, with its shas, so it is on the record — the record
        # is what a check like this is for once the commit is immutable.
        print(f"[PASS] landing_is_one_commit: {examined} commit(s) examined; "
              f"{len(published)} historical unsquashed landing(s) are already "
              f"published and are REPORTED above. No unpublished landing has the "
              f"defect.", file=sys.stderr)
        return 0
    print(f"[PASS] landing_is_one_commit: {examined} commit(s) examined, every "
          f"landing is a single squashed commit.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
