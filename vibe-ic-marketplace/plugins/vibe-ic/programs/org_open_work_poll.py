#!/usr/bin/env python3
"""Every open PR and issue across a GitHub ORG, with the cap refused.

WHY THIS EXISTS
===============
The gatekeeper round begins by polling `vibeic/*` for open PRs and open issues,
and the shell one-liner that did it carried the defect this repo keeps finding:

    gh repo list vibeic --limit 60

The org has 63 repositories. Three were never looked at — `vibe-ic-before-v1.0`,
`vibeic.github.io`, `Xyce` — across every round of a long session. They happened
to be empty, so every "no open PRs" was correct; it was correct BY LUCK, and a
truncated listing is byte-for-byte indistinguishable from a complete one.

That is the same shape as `open_organic_issue_count` (vibe-ic#554), which exists
because `gh issue list` defaults to 30 and a repository with more would
under-count silently. This is that program's org-level sibling, and it is a
program rather than a shell line for the same reason: the shell line was rewritten
from memory every round, and the cap was re-typed wrong.

WHAT IT REFUSES TO DO
=====================
* Report a count when the repo listing came back AT the cap. At the cap there is
  no way to tell a full page from a truncated one, and the number would be a
  floor, not a count. rc 2, and NOTHING on stdout, so `N=$(...) || exit 1` fires.
* Report 0 for a repository whose PR/issue listing failed. A query that could not
  run is not a clean repository.
* Silently skip a repository with issues DISABLED. Forks default to
  `has_issues=false`, so "0 open issues" there is not a fact about the backlog —
  it is a fact about the settings. Those are counted separately and named.

Exit: 0 counted (a JSON summary on stdout), 2 could not count.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

RC_OK, RC_CANNOT_COUNT = 0, 2

#: Far above any plausible repository count for one org, so reaching it means
#: something is wrong rather than that the org is large.
DEFAULT_REPO_LIMIT = 500
#: Per-repository listing cap, same reasoning.
DEFAULT_ITEM_LIMIT = 200


def _gh(args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "gh not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


def _json_len(out: str) -> Optional[int]:
    try:
        v = json.loads(out or "[]")
    except ValueError:
        return None
    return len(v) if isinstance(v, list) else None


def repos(org: str, limit: int = DEFAULT_REPO_LIMIT) -> dict:
    """Every repository in the org, or an error — never a truncated list."""
    rc, out, err = _gh(["repo", "list", org, "--limit", str(limit),
                        "--json", "name,hasIssuesEnabled"], timeout=120)
    if rc != 0:
        return {"error": f"gh repo list failed (rc={rc}): "
                         f"{(err or out).strip()[:200]}"}
    try:
        rows = json.loads(out or "[]")
    except ValueError as exc:
        return {"error": f"unparsable repo listing: {exc}"}
    if not isinstance(rows, list):
        return {"error": f"repo listing was {type(rows).__name__}, not a list"}
    if len(rows) >= limit:
        return {"error": f"repo listing came back at the --repo-limit cap "
                         f"({limit}); the count would be a floor, not a count"}
    return {"repos": rows}


def poll(org: str, repo_limit: int = DEFAULT_REPO_LIMIT,
         item_limit: int = DEFAULT_ITEM_LIMIT) -> dict:
    got = repos(org, repo_limit)
    if "error" in got:
        return got
    rows = got["repos"]

    open_prs: Dict[str, int] = {}
    open_issues: Dict[str, int] = {}
    issues_disabled: List[str] = []
    failures: List[str] = []

    for row in rows:
        name = row.get("name")
        if not name:
            continue
        full = f"{org}/{name}"

        rc, out, err = _gh(["pr", "list", "--repo", full, "--state", "open",
                            "--limit", str(item_limit), "--json", "number"])
        n = _json_len(out) if rc == 0 else None
        if n is None:
            failures.append(f"{full}: pr list ({(err or out).strip()[:80]})")
        elif n >= item_limit:
            failures.append(f"{full}: pr list hit the {item_limit} cap")
        elif n:
            open_prs[full] = n

        if not row.get("hasIssuesEnabled"):
            # Not "no backlog" — no issue TRACKER. A fork defaults to this, and
            # counting it as a clean zero is how a real backlog would hide.
            issues_disabled.append(full)
            continue
        rc, out, err = _gh(["issue", "list", "--repo", full, "--state", "open",
                            "--limit", str(item_limit), "--json", "number"])
        n = _json_len(out) if rc == 0 else None
        if n is None:
            failures.append(f"{full}: issue list ({(err or out).strip()[:80]})")
        elif n >= item_limit:
            failures.append(f"{full}: issue list hit the {item_limit} cap")
        elif n:
            open_issues[full] = n

    return {"org": org, "repos_scanned": len(rows),
            "issues_disabled": sorted(issues_disabled),
            "open_prs": open_prs, "open_issues": open_issues,
            "open_pr_total": sum(open_prs.values()),
            "open_issue_total": sum(open_issues.values()),
            "failures": failures}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("org", help="GitHub org, e.g. vibeic")
    ap.add_argument("--repo-limit", type=int, default=DEFAULT_REPO_LIMIT)
    ap.add_argument("--item-limit", type=int, default=DEFAULT_ITEM_LIMIT)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    res = poll(a.org, a.repo_limit, a.item_limit)
    if a.json:
        from pathlib import Path
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "org_open_work_poll", **res}, indent=2) + "\n",
            encoding="utf-8")

    if "error" in res:
        print(f"[NOT POLLED] {res['error']}. This is NOT 'no open work' — a "
              f"caller that reads zero here would start a round believing the "
              f"queue is empty.", file=sys.stderr)
        return RC_CANNOT_COUNT

    if res["failures"]:
        # A repository that could not be queried is not a repository with
        # nothing open, and the round must not proceed as though it were.
        print(f"[NOT POLLED] {len(res['failures'])} repositor(ies) could not be "
              f"queried:\n  " + "\n  ".join(res["failures"]), file=sys.stderr)
        return RC_CANNOT_COUNT

    print(json.dumps({"open_pr_total": res["open_pr_total"],
                      "open_issue_total": res["open_issue_total"],
                      "open_prs": res["open_prs"],
                      "open_issues": res["open_issues"]}, indent=1))
    print(f"[OK] {res['repos_scanned']} repositor(ies) in {res['org']} — "
          f"{res['open_pr_total']} open PR(s), {res['open_issue_total']} open "
          f"issue(s). {len(res['issues_disabled'])} have no issue TRACKER, which "
          f"is a settings fact and not a backlog fact.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
