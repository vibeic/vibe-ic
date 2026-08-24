#!/usr/bin/env python3
"""Post a REQUIRED commit status by running the real gate. vibe-ic#1019/#1036.

WHY THIS EXISTS
---------------
Three independent paths let a change reach `main` unchecked, and all three were
measured, not assumed:

  1. `gh pr merge` runs no gate — GitHub Actions is disabled at the ACCOUNT
     level. Re-measured 2026-08-12: with the repository switch forced to
     `enabled:true`, a branch carrying an `on: push` workflow whose pattern
     matched was pushed and produced ZERO runs in 105 s; GitHub never even
     registered the workflow. A self-hosted runner does NOT help — scheduling
     is the blocked layer, not execution.
  2. `main` was unprotected, so nothing server-side inspected a push.
  3. Enforcement lived only in a local `pre-push` hook, and `.git/hooks/` is
     untracked — on the machine this was written, it was EMPTY. A hook that is
     not installed is not a gate.

The consequence was measured on a clean detached `origin/main` worktree over a
184-file targeted selection: 49 failed, 3871 passed. `main` was red and had
been for a long time, and nobody saw it.

WHAT CLOSES IT
--------------
Branch protection IS available on this repo (public repo, free org plan), and
it accepts an arbitrary required status context fed by the Statuses API — which
is NOT Actions and does work here. Both arms were proven on throwaway branches
before this file was written:

    push without the status -> GH006: Protected branch update failed.
                               Required status check "vibe-ic/gatekeeper-land"
                               is expected.                      REJECTED
    post green, push same SHA ->                                  ACCEPTED

The rejection happened to a repository ADMIN with `enforce_admins:true`, so it
is not a convention anyone can step around.

This poller is the thing that decides that status. It runs `tools/gatekeeper-
land.sh` — the SAME script a human runs to land — and never a reimplementation
of it. Two gates that can disagree is a new lie waiting to happen, so there is
exactly one gate and this file only transports its verdict.

THE DISTINCTION THIS FILE REFUSES TO BLUR
-----------------------------------------
A gate that could not RUN is not a gate that FAILED. `python3 -m pytest` with
plugin autoload on will load every installed pytest11 entry point, and one
broken third-party plugin (web3's `pytest_ethereum`) kills the session AT
COLLECTION — zero tests run. That reads like an error but it really means "you
measured nothing". If this poller reported that as `failure`, a red main would
be indistinguishable from an unrunnable gate, and the first person to see red
would go looking for a bug that does not exist.

So the verdict is three-valued, and `error` is never silently folded into
`failure`:

    success  exit 0 AND tests were observably collected and run
    failure  the gate ran and DISAGREED — real violations
    error    the gate could not run, or this poller itself broke

`error` blocks a merge exactly as `failure` does — GitHub requires the context
to be `success` — so the fail-closed property holds either way. The difference
is only in what a human is told, which is the entire point.

Everything here is fail-closed: any unexpected exception posts `error`. There
is no code path that posts `success` without a zero exit AND evidence that the
suite actually ran.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: The required status context. This exact string is what branch protection on
#: `main` is configured to require, so it is load-bearing: change it here and
#: the protection rule silently stops ever being satisfied, which fails closed
#: (nothing lands) rather than open. Kept as one constant for that reason.
CONTEXT = "vibe-ic/gatekeeper-land"

REPO = os.environ.get("GATEKEEPER_REPO", "vibeic/vibe-ic")

#: pytest prints one of these when it ran nothing. Matching them is what
#: separates `error` from `failure`; see the module docstring.
_NOTHING_RAN = (
    re.compile(r"no tests ran", re.I),
    re.compile(r"^ERROR.*not found", re.I | re.M),
    re.compile(r"INTERNALERROR", re.I),
    re.compile(r"error(?:s)? during collection", re.I),
)
#: ...and this is the positive evidence that it DID run. Absence of this, on an
#: otherwise-zero exit, is treated as `error` rather than `success` — the
#: asymmetry is deliberate.
_DID_RUN = re.compile(r"\b(\d+)\s+passed\b")


def _run(cmd, cwd=None, env=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, text=True)


def gh_api(args, check=True):
    r = _run(["gh", "api", *args])
    if check and r.returncode != 0:
        raise RuntimeError(f"gh api {' '.join(args)} -> {r.returncode}: {r.stderr.strip()}")
    return r


def post_status(sha: str, state: str, description: str, target_url: str | None = None) -> None:
    """Publish the verdict. Description is truncated to GitHub's 140-char limit.

    Never raises — a poller that dies while reporting a failure would convert a
    red into a silence, which is the failure mode this whole file exists to
    prevent.
    """
    args = ["-X", "POST", f"repos/{REPO}/statuses/{sha}",
            "-f", f"state={state}", "-f", f"context={CONTEXT}",
            "-f", f"description={description[:139]}"]
    if target_url:
        args += ["-f", f"target_url={target_url}"]
    r = gh_api(args, check=False)
    if r.returncode != 0:
        print(f"  !! could not post status for {sha[:12]}: {r.stderr.strip()}", file=sys.stderr)
    else:
        print(f"  -> {state}: {description[:100]}")


def existing_state(sha: str) -> str | None:
    """Our context's current state on this SHA, or None.

    Used only to skip work already done. A `pending` is deliberately NOT
    terminal: if the poller died mid-run the next tick must pick the commit up
    again rather than leave it pending forever, which would look like "still
    working" and block nothing while telling nobody.
    """
    r = gh_api(["-X", "GET", f"repos/{REPO}/commits/{sha}/status"], check=False)
    if r.returncode != 0:
        return None
    try:
        for s in json.loads(r.stdout).get("statuses", []):
            if s.get("context") == CONTEXT:
                return s.get("state")
    except Exception:
        return None
    return None


def classify(rc: int, out: str) -> tuple[str, str]:
    """(state, description) from the gate's exit code and output.

    The ordering matters: "could not run" is checked BEFORE the exit code is
    trusted, because a collection death exits non-zero and would otherwise be
    filed as an ordinary failure.
    """
    if any(p.search(out) for p in _NOTHING_RAN):
        return "error", "gate COULD NOT RUN (collection died / no tests ran) — nothing was measured"
    m = _DID_RUN.search(out)
    if rc == 0:
        if not m:
            return "error", "gate exited 0 but no test ran — refusing to call that a pass"
        fails = re.search(r"\b(\d+)\s+failed\b", out)
        if fails:
            return "error", f"gate exited 0 with {fails.group(1)} failed — contradictory, treating as unmeasured"
        return "success", f"gatekeeper-land PASS ({m.group(1)} passed)"
    failed = re.search(r"\b(\d+)\s+failed\b", out)
    if failed:
        return "failure", f"gatekeeper-land FAIL — {failed.group(1)} failed" + (f", {m.group(1)} passed" if m else "")
    return "failure", f"gatekeeper-land FAIL (gate exit {rc})"



def _refusal_without_the_repetition(text: str, checkout: str,
                                    limit: int = 600) -> str:
    """Bound a refusal by removing what REPEATS, never what it says.

    MEASURED 2026-08-24. This site used `[:300]`, and the preflight it quotes
    names the offending checkout FOUR times -- once as the subject, once inside
    the alternates path, and twice more in the remedy. Under a long TMPDIR
    those four copies alone exceed 300 characters, so the message stopped at
    `.../objects/info` and the word `alternates` -- the CAUSE -- was cut off.
    `test_the_prepared_checkout_is_PROVED_self_contained_not_assumed` asserts
    that word is present, so the same code passed alone and failed in a full
    session. That is not flakiness: it is a truncation that removes text by
    POSITION, applied to a message whose informative half is at the end.

    Two repairs were tried first and BOTH still lose the cause:
      * a bigger limit moves the cliff to a deeper temp directory;
      * eliding the MIDDLE keeps the rule name and the remedy and drops
        `alternates`, which sits between two copies of the path.

    So the path is written ONCE and every later copy becomes `<checkout>`. No
    word of the reason is removed at any path length. The positional bound
    stays as a last resort and says where it cut, so nobody reads the result as
    the whole of the message.
    """
    text = " ".join(text.split())
    if checkout and checkout in text:
        first = text.index(checkout)
        head = text[:first + len(checkout)]
        text = head + text[first + len(checkout):].replace(checkout, "<checkout>")
    if len(text) <= limit:
        return text
    half = (limit - 24) // 2
    return f"{text[:half]} …[{len(text) - 2 * half} chars elided]… {text[-half:]}"

def prepare_gate_checkout(repo_root: Path, sha: str, dest: Path
                          ) -> tuple[Path, str | None]:
    """`(checkout, refusal)` — a SELF-CONTAINED clone of `sha`, or why not.

    THIS USED TO BE `git worktree add`, AND THAT IS THE DEFECT (job TIER).
    A linked worktree's registration lives in `repo_root`, which this run does
    not own. `git worktree prune` there — routine on a host where several agents
    share one clone — unregisters the tree MID-TIER, after which every git call
    inside it fails. MEASURED: one tier run lost four gates to pure collateral
    that way, and the run's third measurement was lost to something outside the
    measurement.

    A clone has no external registration and cannot be pruned. On a local
    filesystem `git clone` HARDLINKS the object files, which are immutable, so
    this costs seconds and survives anything the source repository later does to
    itself. `--no-hardlinks` is deliberately NOT used: it would copy the whole
    object store to buy nothing, because a hardlinked inode already outlives the
    source's own `git gc`.

    `origin/main` is carried over EXPLICITLY. `gatekeeper-land.sh` resolves its
    base through it, and a clone's `origin/*` are built from the source's LOCAL
    branches — so without this the base would silently become `repo_root`'s
    `main` rather than the remote-tracking ref the gate means.
    """
    # `--no-checkout`: the requested commit is checked out below, and it is not
    # necessarily the source's HEAD.
    r = _run(["git", "clone", "--quiet", "--no-checkout", "--no-single-branch",
              str(repo_root), str(dest)])
    if r.returncode != 0:
        return dest, (f"could not clone {repo_root} for {sha[:12]}: "
                      f"{(r.stderr or r.stdout).strip()[:200]}")
    # A clone transfers refs/heads and tags. A PR head can live under
    # refs/pull/* or a remote-tracking ref instead, so fetch EVERY ref the
    # source has before asking for the commit.
    _run(["git", "fetch", "--quiet", "--no-tags", str(repo_root),
          "+refs/*:refs/vibeic-source/*"], cwd=dest)
    base_ref = "refs/remotes/origin/main"
    base = _run(["git", "rev-parse", "--verify", "--quiet", base_ref],
                cwd=repo_root)
    if base.returncode == 0 and base.stdout.strip():
        _run(["git", "update-ref", base_ref, base.stdout.strip()], cwd=dest)
    co = _run(["git", "checkout", "--quiet", "--detach", sha], cwd=dest)
    if co.returncode != 0:
        return dest, (f"{sha[:12]} is not reachable from any ref in "
                      f"{repo_root}, so it could not be cloned: "
                      f"{(co.stderr or co.stdout).strip()[:200]}")
    # ASK, do not assume. `git clone` is SUPPOSED to produce a self-contained
    # checkout, and the whole point of this function is that the tier's hour
    # depends on it actually having done so. A clone made with `--shared` or
    # against a repository that itself borrows objects would satisfy every check
    # above and still be exactly the shape this replaced. The preflight is the
    # one place that sentence lives; reading its answer here is cheaper than
    # discovering it an hour later, and it means the refusal text cannot drift
    # from the refusal.
    preflight = (Path(__file__).resolve().parents[2] / "vibe-ic-marketplace"
                 / "plugins" / "vibe-ic" / "programs"
                 / "landing_tier_checkout_preflight.py")
    if preflight.is_file():
        pf = _run([sys.executable, str(preflight), "--root", str(dest)])
        if pf.returncode != 0:
            return dest, ("the checkout prepared for "
                          f"{sha[:12]} is not self-contained: "
                          f"{_refusal_without_the_repetition((pf.stderr or pf.stdout).strip(), str(dest))}")
    return dest, None


def run_gate(repo_root: Path, sha: str, workdir: Path, cheap_only: bool,
             log_dir: Path, timeout: int) -> tuple[str, str, Path]:
    """Clone `sha` into its own self-contained checkout and run the real gate.

    NOT a worktree — see `prepare_gate_checkout`. The tier is an hour long and
    it must not be able to lose its own repository to a `git worktree prune`
    somebody else runs.
    """
    wt = workdir / f"clone_{sha[:12]}"
    log = log_dir / f"{sha[:12]}.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        wt, refusal = prepare_gate_checkout(repo_root, sha, wt)
        if refusal is not None:
            return "error", refusal, log

        gate = wt / "tools" / "gatekeeper-land.sh"
        if not gate.exists():
            return "error", "tools/gatekeeper-land.sh absent at this commit", log

        env = dict(os.environ)
        # The gate compares against `origin/main` and reads this itself. It is
        # an override rather than a hard-code for one reason: proving this
        # mechanism against a HISTORICAL commit requires the base that commit
        # actually had, not today's tip. Left unset — which is the case for
        # every real PR — it is `origin/main`.
        env["GATEKEEPER_BASE"] = os.environ.get("GATEKEEPER_BASE", "origin/main")
        cmd = ["bash", str(gate)] + (["--cheap-only"] if cheap_only else [])
        try:
            g = _run(cmd, cwd=wt, env=env, timeout=timeout)
            out = (g.stdout or "") + (g.stderr or "")
            rc = g.returncode
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            log.write_text(out + f"\n\n!! TIMEOUT after {timeout}s\n")
            return "error", f"gate TIMED OUT after {timeout}s — nothing was measured", log

        log.write_text(out)
        state, desc = classify(rc, out)
        if cheap_only and state == "success":
            # A cheap-only run is a partial measurement. Saying PASS for it
            # would let the fast tier stand in for the slow one, which is
            # exactly how an expensive gate quietly stops being run.
            state, desc = "error", "cheap tier only — full tier not run, so this is NOT a pass"
        return state, desc, log
    finally:
        # A clone owns everything under its own directory and is registered
        # nowhere else, so removing it is a plain delete — and, unlike
        # `git worktree remove`, it cannot fail because a third party already
        # pruned the registration.
        shutil.rmtree(wt, ignore_errors=True)


def open_pr_heads() -> list[dict]:
    r = _run(["gh", "pr", "list", "--repo", REPO, "--state", "open", "--limit", "100",
              "--json", "number,headRefOid,headRefName,baseRefName,isDraft"])
    if r.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {r.stderr.strip()}")
    return [p for p in json.loads(r.stdout)
            if not p.get("isDraft") and p.get("baseRefName") == "main"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=os.environ.get("GATEKEEPER_REPO_ROOT", str(Path.home() / "vibe-ic")))
    ap.add_argument("--state-dir", default=os.environ.get("GATEKEEPER_STATE_DIR", str(Path.home() / ".gatekeeper-poller")))
    ap.add_argument("--cheap-only", action="store_true",
                    help="run only the fast tier; the verdict is then reported as `error`, never `success`")
    # MEASURED 2026-08-12: the full tier ran past 2400 s on a host that was
    # concurrently running `repo_hygiene_gates.sh` for another session, and the
    # poller correctly reported `error: gate TIMED OUT — nothing was measured`
    # rather than inventing a verdict. Honest, but a timeout that trips on
    # ordinary contention turns every tick into `error` and teaches people to
    # ignore the context. The ceiling is a backstop against a hang, not a
    # performance budget, so it is set well above the observed worst case.
    ap.add_argument("--timeout", type=int, default=7200, help="per-commit gate timeout in seconds")
    ap.add_argument("--include-main", action="store_true", default=True,
                    help="also status origin/main's tip, so a red main is LOUD even though "
                         "protection already prevents new red from landing")
    ap.add_argument("--pr", type=int, default=None, help="only this PR number (for proving the mechanism)")
    ap.add_argument("--sha", default=None, help="only this SHA (for proving the mechanism)")
    ap.add_argument("--force", action="store_true", help="re-run even if a terminal status exists")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    state_dir = Path(args.state_dir).resolve()
    work = state_dir / "work"
    logs = state_dir / "logs"
    work.mkdir(parents=True, exist_ok=True)

    if not (repo_root / ".git").exists():
        print(f"FATAL: {repo_root} is not a git repo", file=sys.stderr)
        return 2

    _run(["git", "fetch", "--quiet", "origin"], cwd=repo_root)

    targets: list[tuple[str, str]] = []          # (label, sha)
    if args.sha:
        targets.append((f"sha {args.sha[:12]}", args.sha))
    else:
        for pr in open_pr_heads():
            if args.pr and pr["number"] != args.pr:
                continue
            targets.append((f"PR #{pr['number']} ({pr['headRefName']})", pr["headRefOid"]))
        if args.include_main and not args.pr:
            r = _run(["git", "rev-parse", "origin/main"], cwd=repo_root)
            if r.returncode == 0:
                targets.append(("origin/main tip", r.stdout.strip()))

    if not targets:
        print("nothing to gate")
        return 0

    worst = 0
    for label, sha in targets:
        prior = existing_state(sha)
        if prior in ("success", "failure", "error") and not args.force:
            print(f"{label} {sha[:12]}: already {prior}, skipping")
            continue
        print(f"{label} {sha[:12]}: running gate…")
        post_status(sha, "pending", "gatekeeper-land running…")
        try:
            state, desc, log = run_gate(repo_root, sha, work, args.cheap_only, logs, args.timeout)
        except Exception as e:                    # fail-closed, always
            state, desc, log = "error", f"poller crashed: {type(e).__name__}: {e}", logs / f"{sha[:12]}.log"
        post_status(sha, state, desc, target_url=None)
        print(f"   log: {log}")
        if state != "success":
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
