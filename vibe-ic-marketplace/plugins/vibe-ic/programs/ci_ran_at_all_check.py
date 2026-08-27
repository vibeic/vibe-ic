#!/usr/bin/env python3
"""Did CI actually run on this commit, or has it not run at all?

WHY THIS EXISTS (vibe-ic#550)
=============================
GitHub Actions was disabled at the ACCOUNT level on this repo and **561 commits
landed on main with no CI at all**, over nine days, while every question anyone
asked about CI came back clean. The repo-level setting still reported
``enabled=true``; the workflows were ``active``; the trigger blocks were
correct. Only the account was blocked, and from inside the repo that is
invisible:

    $ gh api repos/<r>/actions/permissions      -> enabled=true, allowed=all
    $ gh api "repos/<r>/actions/runs?per_page=1" -> total_count=2   (neither is CI)
    $ gh run list --workflow=<CI>                -> (nothing)
    $ gh workflow run <CI> --ref main            -> 422 Actions has been
                                                    disabled for this user

**The empty listing is the whole defect.** ``gh run list`` prints nothing when a
workflow has never run and prints nothing when a filter matched nothing, so
"CI has never run" and "no run matched my filter" are byte-identical at the
point of observation. Filtered by branch and event — the natural way to ask
"what happened to my push?" — an empty result reads as "nothing new since the
one I already saw". A maintainer (me) read a stale ``success`` line that way and
pushed on it.

So the state this program exists to name is NEVER_RAN, and the load-bearing
requirement is that it can never render the same as PASSED.

THE THREE STATES MUST BE THREE
==============================
    PASSED      a run exists for this SHA and concluded success  -> rc 0
    FAILED      a run exists for this SHA and did not            -> rc 1
    NEVER_RAN   no run exists for this SHA                       -> rc 1
    PENDING     a run exists and has not concluded               -> rc 2
    UNREACHABLE the API could not be asked                       -> rc 2

NEVER_RAN is rc 1, not rc 2. rc 2 means "I could not look"; here we looked and
the answer was "nothing ran", which is a finding about the commit, not a gap in
the measurement. Conflating the two is how this went unnoticed — the whole
lesson of #550 is that the absence of evidence was rendered as evidence.

UNREACHABLE is rc 2 and deliberately non-blocking: an offline maintainer, a
missing token, a rate limit. Making that fatal would push people to skip the
gate, which is worse than a loud NOT CHECKED (``_gate_dispatch.sh`` already has
this vocabulary and this program uses it rather than inventing a fourth answer).

WHY IT ASKS ABOUT THE SHA AND NOT ABOUT THE REPO
================================================
A repo-wide "has CI ever run" check goes green the moment ANY commit gets a run,
which is exactly the shape that lets a per-commit gap hide. The question that
matters at a merge is about the commit being merged.

REPO-HISTORY IMPLAUSIBILITY
===========================
``--min-total`` additionally reports when the repo's TOTAL run count is too low
to be credible for its commit count. That is what an account-level block looks
like from inside: not one missing run, but an entire history that never
happened. Off by default (it needs a repo-specific threshold); the merge gate
passes one.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

RC_PASS, RC_FAIL, RC_NOT_CHECKED = 0, 1, 2

#: Workflow names that do NOT constitute "CI ran". A repo can have automation
#: (dependency graphs, label bots) whose presence must never be read as the test
#: suite having run — that is the same substitution this program exists to stop,
#: one level down. Matched case-insensitively as substrings.
#:
#: A DENY-LIST IS THE WRONG SHAPE HERE AND IS KEPT ONLY AS A FALLBACK. Probed:
#: `CodeQL`, `Deploy Pages` and `Greetings` all classified as CI, so one green
#: run of any of them would have let this program report CI as passing. That is
#: precisely the substitution it exists to stop, arriving through the door it
#: left open — and the fix is not a longer list, because the next workflow
#: nobody thought of is not on that one either.
_NON_CI_WORKFLOWS = ("dependency graph", "graph update", "dependabot",
                     "labeler", "stale", "codeql", "deploy", "pages",
                     "greetings", "auto assign", "welcome", "release drafter")

#: Workflow FILES the repository itself declares under `.github/workflows/`.
#: Anything else — GitHub's dynamic dependabot graph, an org-level workflow, an
#: app acting on the repo — is automation the repo did not commit, and cannot be
#: the CI whose absence this program reports. Derived per-run from the API,
#: which is why it stays correct when a workflow is added tomorrow.
_WORKFLOW_PATH_PREFIX = ".github/workflows/"


def _gh(args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "gh not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


def _repo_slug(repo_dir: Path) -> Optional[str]:
    rc, out, _ = _gh(["repo", "view", "--json", "nameWithOwner",
                      "-q", ".nameWithOwner"])
    if rc == 0 and out.strip():
        return out.strip()
    r = _pr.run(["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                capture_output=True, text=True)
    if r.returncode != 0:
        return None
    url = r.stdout.strip()
    for pre in ("https://github.com/", "git@github.com:"):
        if url.startswith(pre):
            return url[len(pre):].removesuffix(".git")
    return None


def _head_sha(repo_dir: Path, rev: str) -> Optional[str]:
    r = _pr.run(["git", "-C", str(repo_dir), "rev-parse", rev],
                capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _is_ci_run(name: str, path: Optional[str] = None) -> bool:
    """Does this run count as "the repository's CI ran"?

    PATH FIRST, name second. Each run carries the workflow FILE it came from,
    and a workflow the repository committed under `.github/workflows/` is the
    only kind that can be the CI whose absence this program reports. GitHub's
    dependency graph arrives as `dynamic/dependabot/update-graph`; an org-level
    or app-injected workflow is likewise not something this repo declared.

    That inverts the shape from deny to allow, which matters because the
    failure directions are not symmetric. A name this program has never seen
    being treated as CI is a FALSE GREEN — one successful `CodeQL` or
    `Deploy Pages` run and it reports CI as passing, which is the exact
    substitution it exists to stop. Measured before this change: `CodeQL`,
    `Deploy Pages` and `Greetings` all classified as CI.

    The name list is kept for the case where `path` is absent from the payload
    — an older API shape, or a caller passing a bare name. Belt and braces, in
    that order.
    """
    if path:
        return path.startswith(_WORKFLOW_PATH_PREFIX)
    low = (name or "").lower()
    return not any(m in low for m in _NON_CI_WORKFLOWS)


def evaluate(slug: str, sha: str, min_total: Optional[int] = None) -> dict:
    """Ask the API and classify. Never raises; unreachable is a state."""
    rc, out, err = _gh(["api", f"repos/{slug}/actions/runs?head_sha={sha}"
                        "&per_page=50"])
    if rc != 0:
        return {"state": "UNREACHABLE", "sha": sha,
                "detail": (err or out).strip()[:200] or f"gh api rc={rc}"}
    try:
        doc = json.loads(out)
    except ValueError as exc:
        return {"state": "UNREACHABLE", "sha": sha,
                "detail": f"unparsable API response: {exc}"}

    runs = [r for r in doc.get("workflow_runs", [])
            if _is_ci_run(r.get("name", ""), r.get("path"))]
    result = {"sha": sha, "runs": len(runs),
              "workflows": sorted({r.get("name", "?") for r in runs})}

    if min_total is not None:
        rc2, out2, _ = _gh(["api", f"repos/{slug}/actions/runs?per_page=1"])
        try:
            result["repo_total_runs"] = json.loads(out2).get("total_count")
        except ValueError:
            result["repo_total_runs"] = None
        tot = result.get("repo_total_runs")
        if isinstance(tot, int) and tot < min_total:
            result["repo_history_implausible"] = tot

    if not runs:
        result["state"] = "NEVER_RAN"
        return result
    if any(r.get("status") != "completed" for r in runs):
        result["state"] = "PENDING"
        return result
    bad = [r for r in runs if r.get("conclusion") != "success"]
    result["state"] = "FAILED" if bad else "PASSED"
    if bad:
        result["failing"] = [f"{r.get('name')}={r.get('conclusion')}"
                             for r in bad]
    return result


def render(res: dict) -> Tuple[int, str]:
    st = res["state"]
    sha = res.get("sha", "?")[:9]
    if st == "PASSED":
        line = (f"[PASS] CI ran on {sha} and passed "
                f"({res['runs']} run(s): {', '.join(res['workflows'])})")
        rc = RC_PASS
    elif st == "FAILED":
        line = (f"[FAIL] CI ran on {sha} and did NOT pass: "
                f"{', '.join(res.get('failing', []))}")
        rc = RC_FAIL
    elif st == "NEVER_RAN":
        # rc 1, not rc 2: we looked, and nothing ran. That is a fact about the
        # commit, not a gap in the measurement.
        line = (f"[FAIL] NO CI RUN EXISTS for {sha}. This is not the same as a "
                f"passing run and must never render as one — an empty run "
                f"listing is what an account-level Actions block looks like "
                f"from inside the repo (vibe-ic#550: 561 commits, 9 days).")
        rc = RC_FAIL
    elif st == "PENDING":
        line = f"[NOT CHECKED] CI is still running on {sha}"
        rc = RC_NOT_CHECKED
    else:
        line = (f"[NOT CHECKED] could not ask GitHub about {sha}: "
                f"{res.get('detail', '')}. NOT a pass — 'I could not look' and "
                f"'I looked and it is fine' are different answers.")
        rc = RC_NOT_CHECKED
    imp = res.get("repo_history_implausible")
    if imp is not None:
        line += (f"\n[FAIL] the repo reports only {imp} workflow run(s) in its "
                 f"whole history — too few to be credible, which is the "
                 f"signature of Actions being disabled account-wide")
        rc = max(rc, RC_FAIL) if rc != RC_NOT_CHECKED else RC_FAIL
    return rc, line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo_dir", nargs="?", default=".")
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--repo", default=None, help="owner/name (else derived)")
    ap.add_argument("--min-total", type=int, default=None,
                    help="flag a repo whose TOTAL run count is below this")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    repo_dir = Path(a.repo_dir).resolve()
    sha = _head_sha(repo_dir, a.rev)
    if sha is None:
        print(f"[NOT CHECKED] cannot resolve {a.rev} in {repo_dir}",
              file=sys.stderr)
        return RC_NOT_CHECKED
    slug = a.repo or _repo_slug(repo_dir)
    if slug is None:
        print("[NOT CHECKED] cannot determine the GitHub repo", file=sys.stderr)
        return RC_NOT_CHECKED

    res = evaluate(slug, sha, a.min_total)
    rc, line = render(res)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "ci_ran_at_all_check", "repo": slug, **res,
             "rc": rc}, indent=1), encoding="utf-8")
    print(line, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the commit: reach the stamp as rc 2
    # (this gate's 'could not measure'), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
