#!/usr/bin/env python3
"""Publish the commit status that the `main` ruleset requires — GREEN ONLY.

WHY THIS EXISTS
===============
`tools/gatekeeper-land.sh` already refuses correctly: a red BLOCKING hygiene
gate reaches `run_emit`'s FAIL branch, sets `FAILED=1` (:431), and the tail
removes `.git/gatekeeper-stamp` (:2047) and exits non-zero (:2071).  Nothing in
the lane ignores that rc.

What the lane cannot do is make itself MANDATORY.  `.git/hooks/` is untracked,
`git push --no-verify` skips every client hook, `gatekeeper-ci.yml` has never
run once (Actions is disabled at the account level), and MEASURED 2026-08-29 on
`vibeic/vibe-ic`:

    GET /repos/vibeic/vibe-ic/branches/main/protection -> 404 Branch not protected
    GET /repos/vibeic/vibe-ic/rulesets                 -> []
    GET /repos/vibeic/vibe-ic/actions/permissions      -> {"enabled": false}

So the lane was skippable by anyone with push rights, and 49 version-stamped
landings skipped it.

THE ONLY THING THAT STOPS A DIRECT PUSH is a server-side rule.  MEASURED on the
same repository, single variable, probe ref `refs/heads/enforce-probe/**`:

    ruleset active, sha carries NO status   -> git push            EXIT 1
    ruleset active, sha carries NO status   -> git push --no-verify EXIT 1
    ruleset active, sha carries the status  -> git push            EXIT 0
    ruleset DELETED, same statusless commit -> git push            EXIT 0

    remote: error: GH013: Repository rule violations found ...
    remote: - Required status check "vibe-ic/landing-lane" is expected.

A `required_status_checks` rule needs no GitHub Actions: the context is fed by
the Commit Statuses API, which this program calls.  That is the half the LANE
owns.

WHAT THIS PROGRAM WILL NOT DO
=============================
It will never publish `success` for a landing it was not told was green, for a
sha that is not the stamped sha, or over a tree that moved.  Each of those is a
REFUSAL (exit 2) that publishes nothing — never a `failure` status either,
because "I could not tell" is not "the gates failed", and a reader of the
status page must not be handed one when the other happened.

HONEST LIMIT, STATED HERE AND NOT ONLY IN THE HANDBACK
======================================================
Anyone with push rights can also POST a status, because `status:write` travels
with push access.  This raises the bar from "type `--no-verify`" to "forge a
status deliberately"; it is not a cryptographic guarantee.  Closing that gap
needs a credential the lander does not hold (a GitHub App), which this repo does
not have today.  Do not read the ruleset as making a forged landing impossible —
read it as making an ACCIDENTAL one impossible, which is the failure that
actually happened.

Exit codes
    0  a status was published exactly as instructed
    2  nothing was published.  Two distinguishable shapes, both exit 2 because
       both leave the server-side rule unsatisfied, and both are safe in that
       one direction:
         REFUSED       — this program declined to judge, so there is no verdict
         NOT_PUBLISHED — a verdict WAS reached and its announcement failed; the
                         line names the verdict, so it is not lost with it
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

#: The context the `main` ruleset requires.  One spelling, here, so the rule and
#: the publisher cannot drift into two.
CONTEXT = "vibe-ic/landing-lane"

SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


class Refusal(RuntimeError):
    """Nothing was published, and nothing may be inferred about the gates."""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed rc={proc.returncode}: "
                      f"{proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def stamped_sha(repo: Path) -> str:
    """Line 1 of `.git/gatekeeper-stamp` — the commit the suites verified.

    Read with the SAME expression `gatekeeper-land.sh` writes it with
    (`--absolute-git-dir`), so a worktree resolves to its own per-worktree stamp
    rather than to a sibling's.
    """
    stamp = Path(_git(repo, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    if not stamp.is_file():
        raise Refusal(
            f"no landing stamp at {stamp} — the lane did not certify this "
            f"commit, so there is no green to publish")
    line = stamp.read_text(encoding="utf-8").splitlines()
    if not line or not SHA_RE.match(line[0].strip()):
        raise Refusal(f"the stamp's first line is not a 40-hex commit: "
                      f"{(line[0] if line else '')!r}")
    return line[0].strip()


def decide(repo: Path, failed: str, sha: str) -> str:
    """The state to publish, or a Refusal. NEVER returns 'success' on doubt.

    `failed` is `gatekeeper-land.sh`'s own `$FAILED`, handed over verbatim. Only
    the literal `0` is green: an empty string, `NORECORD`, or anything
    unparsable is the lane failing to say what happened, and that is a refusal
    rather than a red — a landing whose verdict was lost must not reach the
    status page as either answer.
    """
    if not SHA_RE.match(sha):
        raise Refusal(f"--sha is not a 40-hex commit: {sha!r}")
    if failed.strip() == "":
        raise Refusal("--failed was empty: the lane did not state a verdict")
    try:
        code = int(failed.strip())
    except ValueError:
        raise Refusal(f"--failed is not an integer: {failed!r}") from None
    if code != 0:
        return "failure"

    # GREEN IS THE ONLY CLAIM THAT NEEDS CORROBORATION, so it is the only one
    # that gets any. A `failure` is published on the lane's word alone; a
    # `success` has to survive both checks below.
    head = _git(repo, "rev-parse", "HEAD")
    if head != sha:
        raise Refusal(
            f"HEAD is {head[:12]} and the status was asked for {sha[:12]} — "
            f"the tree moved between the gates and this call")
    stamped = stamped_sha(repo)
    if stamped != sha:
        raise Refusal(
            f"the stamp names {stamped[:12]}, not {sha[:12]} — a green from "
            f"another commit is not this commit's")
    dirty = _git(repo, "status", "--porcelain")
    if dirty:
        n = len(dirty.splitlines())
        raise Refusal(
            f"the worktree carries {n} uncommitted change(s), so the gates did "
            f"not measure what would be pushed")
    return "success"


def not_published(state: str, sha: str, reason: str) -> int:
    """DEGRADE LOUDLY, AND IN THE SAFE DIRECTION. One name for one fact.

    A status that could not be published leaves the ruleset unsatisfied, so the
    push is refused by the server with a sentence that names the missing
    context. Nothing is silently allowed by this failing.

    THE VERDICT IS NAMED HERE ON PURPOSE. The gates reached `state` and that is
    a fact of the run; whether anyone could be told is a SECOND fact, and this
    line is where the second one is recorded without erasing the first. A
    reader of a failed announcement must still be able to read what was
    announced, so `state` appears in the message rather than only in the caller.

    NOT a `Refusal`: a refusal means this program declined to judge. Here it
    judged, and only the transport failed — the two must not arrive under one
    word (`tools/ci/test_landing_enforcement_hole.py` asserts they do not).
    """
    print(f"landing-status: NOT_PUBLISHED — the {state} verdict for "
          f"{sha[:12]} was NOT posted as {CONTEXT}: {reason}", file=sys.stderr)
    print("          The verdict stands as the lane measured it; only its "
          "publication failed. The `main` ruleset therefore still refuses "
          "this push, which is the correct direction.", file=sys.stderr)
    return 2


def publish(repo_slug: str, sha: str, state: str, target_url: str,
            dry_run: bool) -> int:
    argv = ["gh", "api", "-X", "POST", f"repos/{repo_slug}/statuses/{sha}",
            "-f", f"state={state}", "-f", f"context={CONTEXT}",
            "-f", f"description=gatekeeper-land.sh: {state}"]
    if target_url:
        argv += ["-f", f"target_url={target_url}"]
    if dry_run:
        print("DRY-RUN " + json.dumps(argv))
        return 0
    # A `gh` THAT CANNOT BE EXECUTED IS THE SAME FACT AS A `gh` THAT REFUSED —
    # no status is standing — AND IT WAS THE UNHANDLED ONE. MEASURED on the
    # v1.17.37 exact-tree stamp (repo b495bbc9d, tree cd2d7767f, pinned image
    # …66c33ff2): `gh` is not installed in that image (`command -v gh` exits 1
    # while `/usr/bin/git` is present), so this call raised
    # `FileNotFoundError: [Errno 2] No such file or directory: 'gh'` and the
    # program died with a traceback and rc 1. It walked past the honest
    # degradation directly below, which had been written for the rc != 0 case
    # only. The landing survived — `gatekeeper-land.sh` calls this program with
    # `|| true` — but a GREEN stamp's status would have gone unpublished with
    # nothing but a traceback to say so, which is a verdict announced as an
    # accident.
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError:
        return not_published(
            state, sha,
            f"the `{argv[0]}` CLI is not present on PATH in this environment, "
            f"so the Commit Statuses API was never called")
    except OSError as exc:
        return not_published(
            state, sha, f"`{argv[0]}` could not be executed: {exc}")
    if proc.returncode != 0:
        return not_published(
            state, sha,
            f"`{argv[0]}` exited {proc.returncode}: "
            f"{proc.stderr.strip()[:300] or '(no stderr)'}")
    print(f"landing-status: published {state} for {sha[:12]} "
          f"as {CONTEXT}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="the checkout the lane ran in")
    ap.add_argument("--repo-slug", default="vibeic/vibe-ic",
                    help="owner/name the status is posted to")
    ap.add_argument("--sha", default="",
                    help="the commit the status is about; defaults to HEAD")
    ap.add_argument("--failed", required=True,
                    help="gatekeeper-land.sh's $FAILED, verbatim")
    ap.add_argument("--target-url", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the exact API call and post nothing")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    try:
        sha = a.sha or _git(repo, "rev-parse", "HEAD")
        state = decide(repo, a.failed, sha)
    except Refusal as exc:
        print(f"[REFUSED] landing_status_publish: {exc}", file=sys.stderr)
        print("          Nothing was published. The `main` ruleset therefore "
              "still refuses this push, which is the correct direction.",
              file=sys.stderr)
        return 2
    return publish(a.repo_slug, sha, state, a.target_url, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
