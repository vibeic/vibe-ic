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
import sys
# ONE `gh` invoker for every polling program in this directory. It was copied
# into this file and into its sibling, byte for byte — the shape of
# vibeic-eda#29, where two copies of `branch_is_ours` gave opposite answers
# about the same pins. The error encoding (127 not-installed / 126 could not
# run) is the part that must not drift, so it has one home.
from _gh_cli import gh as _gh  # noqa: E402
from typing import Dict, List, Optional, Tuple

RC_OK, RC_CANNOT_COUNT = 0, 2

#: Far above any plausible repository count for one org, so reaching it means
#: something is wrong rather than that the org is large.
DEFAULT_REPO_LIMIT = 500
#: Per-repository listing cap, same reasoning.
DEFAULT_ITEM_LIMIT = 200


def _json_len(out: str) -> Optional[int]:
    try:
        v = json.loads(out or "[]")
    except ValueError:
        return None
    return len(v) if isinstance(v, list) else None


#: GitHub says this in plain words when an account is restricted, and it is the
#: only place it says it. Matched case-insensitively on a substring because the
#: surrounding JSON shape is not contractual.
_SPAM_FLAG = "flagged as spammy"


def search_index_health(org: str) -> dict:
    """Is this org's work VISIBLE to anyone but us?

    Every listing in this program goes through GraphQL, which keeps working for
    a restricted account. GitHub's own web UI does not: `/issues` and `/pulls`
    are rendered from the SEARCH index, and for a flagged account that index
    returns HTTP 200 with `total_count: 0` — a success, an empty set, and no
    indication anywhere that anything is being withheld.

    On 2026-07-30 vibeic/vibe-ic had 205 issues and 353 pull requests and both
    pages rendered empty. The poll was unaffected and would have reported a
    healthy queue every round while the repository looked abandoned to every
    visitor. Nothing in a listing can reveal that, because the listing is right.

    So it is asked directly. Two endpoints name the condition outright; the
    issue/PR endpoint only goes quiet, which is why the loud one is the probe.
    """
    rc, out, err = _gh(["api", f"search/repositories?q=user:{org}&per_page=1"],
                       timeout=60)
    blob = f"{out}{err}"
    if _SPAM_FLAG in blob.lower():
        return {"searchable": False,
                "reason": "GitHub reports the account as flagged; issues and "
                          "PRs are absent from the search index, so the repo's "
                          "/issues and /pulls pages render EMPTY to everyone "
                          "even though the data is intact over GraphQL"}
    if rc != 0:
        # Not a verdict — a probe that could not run. Reported, never inferred
        # from, because "I could not ask" is not "the answer is yes".
        return {"searchable": None,
                "reason": f"probe failed (rc={rc}): {(err or out).strip()[:120]}"}
    return {"searchable": True, "reason": ""}


def repos(org: str, limit: int = DEFAULT_REPO_LIMIT) -> dict:
    """Every repository in the org, or an error — never a truncated list."""
    # `issues.totalCount` rides along on the SAME call — free, and it is the
    # second opinion the zero-check below needs.
    rc, out, err = _gh(["repo", "list", org, "--limit", str(limit),
                        "--json", "name,hasIssuesEnabled,issues"], timeout=120)
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
    visibility = search_index_health(org)
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

        # 60s per repository, not the shared 120s default: this runs once per
        # repo in a 63-iteration loop, where a slow default compounds.
        rc, out, err = _gh(["pr", "list", "--repo", full, "--state", "open",
                            "--limit", str(item_limit), "--json", "number"],
                           timeout=60)
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
                            "--limit", str(item_limit), "--json", "number"],
                           timeout=60)
        n = _json_len(out) if rc == 0 else None
        if n is None:
            failures.append(f"{full}: issue list ({(err or out).strip()[:80]})")
        elif n >= item_limit:
            failures.append(f"{full}: issue list hit the {item_limit} cap")
        elif n:
            open_issues[full] = n
        else:
            # A LISTING THAT CONFIDENTLY RETURNS ZERO IS THE ONE CASE THIS
            # PROGRAM COULD NOT REFUSE. It already rejects a capped listing and
            # a failed query; a healthy-looking empty result was the remaining
            # hole, and on 2026-07-30 that hole was live: GitHub's REST issue
            # enumeration and `open_issues_count` both returned 0 for
            # vibeic/vibe-ic while #551 was open, and the web UI rendered
            # empty. The poll only kept working because `gh issue list` is
            # GraphQL — luck, not design.
            #
            # So a zero now needs a SECOND SOURCE to agree. Cross-checked only
            # when the answer is "nothing", which costs nothing on a quiet org
            # and is exactly where a false zero does its damage. Two sources
            # agreeing is weak evidence; two sources DISAGREEING proves one is
            # wrong, and that is what gets reported.
            declared = (row.get("issues") or {}).get("totalCount")
            if isinstance(declared, int) and declared > 0:
                failures.append(
                    f"{full}: issue listing returned 0 but the repository "
                    f"declares {declared} open — one of these is wrong, so the "
                    f"queue state is UNKNOWN, not empty")

    return {"org": org, "repos_scanned": len(rows),
            "visibility": visibility,
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
    vis = res.get("visibility") or {}
    if vis.get("searchable") is False:
        # NOT a failure of the poll: the enumeration above is correct and the
        # round can proceed. It is reported because the round is the only place
        # anyone would notice, and nobody browsing the org can see it at all.
        print(f"[VISIBILITY] {res['org']}: {vis['reason']}.", file=sys.stderr)
    elif vis.get("searchable") is None:
        print(f"[VISIBILITY] {res['org']}: could not check whether this org is "
              f"publicly searchable — {vis.get('reason', '')}", file=sys.stderr)

    print(f"[OK] {res['repos_scanned']} repositor(ies) in {res['org']} — "
          f"{res['open_pr_total']} open PR(s), {res['open_issue_total']} open "
          f"issue(s). {len(res['issues_disabled'])} have no issue TRACKER, which "
          f"is a settings fact and not a backlog fact.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
