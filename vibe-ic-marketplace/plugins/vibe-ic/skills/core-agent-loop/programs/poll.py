#!/usr/bin/env python3
"""programs/poll.py — deterministic core-agent poll
(part of the vibe-ic:core-agent-loop skill).

The core-agent calls this FIRST at every cron wake-up. The rule is
intentionally simple so the agent doesn't drift into LLM-judgement
loops:

    ACTIONABLE = ANY open non-PR issue (new OR reopened).

There is NO label gating and NO comment classifier. The
`wait-for-verification` flag is RETIRED: an open issue is always
actionable, because the new state machine makes CLOSED the terminal
state. The core-agent self-verifies + closes each issue (adding the
`core-closed` label); the field-agent audits closed issues and
reopens any it finds inadequate. A reopened issue is just an open
issue again — so it is actionable by the same predicate, with no
special-casing.

Usage
-----
    # default — print actionable issue numbers, one per line.
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py

    # json output for machine consumption.
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py --json

    # different repo (default: vibeic/vibe-ic).
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py --repo owner/name

Exit codes
----------
    0   No actionable issues. Core agent exits this tick.
    1   ≥1 actionable issue. Core agent must process the listed numbers.
    2   I/O or auth error (no PAT, network error, etc.), OR a listing that
        cannot be believed (see below). DOES NOT count as actionable — the
        core agent should retry next tick.

AN EMPTY REST LISTING IS NOT A ZERO (vibe-ic#1384)
--------------------------------------------------
`#1319` taught this program that a FAILED call is not evidence, and
`_list_open_issues` raises on any non-200. That left the harder half open: a
listing that SUCCEEDS and is empty. Measured 2026-08-15 on `vibeic/vibe-ic`,
core quota healthy (`X-Ratelimit-Remaining: 4751`, so not throttling):

    gh api -i repos/vibeic/vibe-ic/issues          HTTP 200, Content-Length: 2
    gh api repos/vibeic/vibe-ic/issues             []
    gh issue list --state open --limit 200         42   (GraphQL)
    gh repo view --json issues -q .issues.totalCount  42

Individual GETs work; only the REST LIST is empty. This program reads that
list, so it printed `(no actionable issues)` and exited 0 — "core agent exits
this tick" — with 42 issues open. rc 0 and rc 0 for two opposite worlds.

So a zero from the listing now needs a SECOND SOURCE before it is believed.
Two sources agreeing is weak evidence; two sources DISAGREEING proves one of
them is wrong, and that is the answer worth having: the queue state is
UNKNOWN, which is rc 2, not empty, which is rc 0.

Auth
----
    Reads GitHub PAT from $GITHUB_TOKEN, then $GH_TOKEN, then the live `gh`
    CLI auth (`gh auth token`), then ~/.config/github/token. The `gh` CLI
    fallback matters because the issue repo (vibeic/vibe-ic) is PRIVATE: a
    stale/public-scoped file PAT gets a 404 (GitHub masks a private repo it
    cannot see), whereas `gh` is authenticated as the maintainer and is the
    same auth the rest of the loop uses for `gh pr`/`gh issue`. chip-AGNOSTIC.

Why the enumeration is GraphQL (vibe-ic#1645)
---------------------------------------------
    This program used to enumerate with the REST listing:

        GET /repos/{repo}/issues?state=open&per_page=100&page=N

    #1319 already made a FAILED call raise instead of returning `[]`. What
    was left was the case where the call SUCCEEDS and the answer is wrong:
    that endpoint answers HTTP 200 with an empty array for a repository
    that has open issues. Measured 2026-08-15 on `vibeic/vibe-ic`:

        gh issue list --state open --limit 200        ->  33   (GraphQL)
        gh api 'repos/vibeic/vibe-ic/issues?state=open&per_page=100'
                                                      ->   0   (REST)
        gh api 'search/issues?q=repo:vibeic/vibe-ic+is:issue+is:open'
                                                      ->   0   (index)
        gh api repos/vibeic/vibe-ic --jq .open_issues_count
                                                      ->   0
        gh api repos/vibeic/vibe-ic/issues/1645 --jq .state
                                                      -> "open"
        gh api 'repos/vibeic/vibe-ic/pulls?state=open&per_page=100'
                                                      ->   6   (REST is fine)

    and this program, run against that repository on that day, printed
    `total open: 0 / (no actionable issues)` and exited 0 — which the
    skill defines as "No actionable issues. Core agent exits this tick."
    33 open issues, every agent on the loop told the queue was empty, and
    the output identical to a genuinely clear queue.

    A 200 with `[]` cannot be refused by looking at it, so the fix is not
    a better refusal: it is asking the source that answers correctly.
    GraphQL is what `gh issue list` uses, and it is already the authority
    for `open_organic_issue_count.py` (#554) and `org_open_work_poll.py`.
    Truncation is still refused rather than paged over silently.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_REPO = "vibeic/vibe-ic"
_health = None
try:  # sibling module; loaded by path so the shim's callers work unchanged
    import importlib.util as _ilu
    from pathlib import Path as _P
    _spec = _ilu.spec_from_file_location(
        "api_health", _P(__file__).resolve().parent / "api_health.py")
    _health = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_health)
except Exception:  # pragma: no cover - degraded, and it SAYS so below
    class _health:  # type: ignore
        SECONDARY_LIMIT = "SECONDARY_LIMIT"
        @staticmethod
        def classify(*a, **k): return "UNCLASSIFIED (api_health.py unavailable)"
        @staticmethod
        def advice(*a, **k): return "Treat the response as NO EVIDENCE."


_API_BASE = "https://api.github.com"


def _gh_cli_token() -> Optional[str]:
    """The token the `gh` CLI is authenticated with, or None if gh is absent /
    not logged in. This is the SAME identity the loop's `gh pr`/`gh issue`
    commands use, so it reaches the private vibeic/vibe-ic repo."""
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True,
                             text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    tok = (out.stdout or "").strip()
    return tok or None


def _load_pat() -> Optional[str]:
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(env)
        if v and v.strip():
            return v.strip()
    # Prefer the live `gh` CLI auth over the on-disk file token: the file token
    # may be stale / scoped only to a public repo and 404 on the private issue
    # repo, while `gh` is authenticated as the maintainer.
    gh_tok = _gh_cli_token()
    if gh_tok:
        return gh_tok
    token_path = Path.home() / ".config" / "github" / "token"
    if token_path.is_file():
        try:
            return token_path.read_text().strip() or None
        except OSError:
            return None
    return None


def _api_request(url: str, token: str,
                 payload: Optional[dict] = None) -> Tuple[int, Any]:
    """The ONE network seam. GET when `payload` is None, else POST JSON.

    Returns (status_code, json). Kept as a single function so that every
    call this program makes — REST or GraphQL — is faked in one place by
    the tests, and so a future caller cannot add a second, differently
    behaved transport beside it.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vibe-ic-agent-poll/1.0",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
            return r.getcode(), json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            payload = {"message": str(exc)}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"message": f"network error: {exc!r}"}


def _api_get(url: str, token: str) -> Tuple[int, Any]:
    """Plain GET against the GitHub API. Returns (status_code, json)."""
    return _api_request(url, token)


def _rate_limit_snapshot(token: str):
    """The quota, or None. `rate_limit` is EXEMPT from the secondary limit, so
    it still answers while everything else 403s — which is exactly why it is
    worth asking, and exactly why its 'healthy' answer misleads on its own."""
    status, payload = _api_get(f"{_API_BASE}/rate_limit", token)
    return payload if status == 200 else None


#: `repository.issues` never contains pull requests, so no PR filter is
#: needed on this side — that is a property of the connection, not luck.
#: 100 is GraphQL's per-page maximum.
_OPEN_ISSUES_QUERY = """
query($owner:String!, $name:String!, $after:String) {
  repository(owner:$owner, name:$name) {
    hasIssuesEnabled
    issues(first:100, after:$after, states:OPEN,
           orderBy:{field:CREATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url updatedAt labels(first:100){nodes{name}} }
    }
  }
}
"""

#: 100 issues per page; a repository needing more pages than this is not
#: paged over silently, it is refused. Far above any plausible backlog.
_MAX_PAGES = 60


def _entry_from_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """GraphQL node -> the REST-shaped issue dict `_to_entry` speaks."""
    labels = ((node.get("labels") or {}).get("nodes")) or []
    return {
        "number": node.get("number"),
        "title": node.get("title") or "",
        "labels": [{"name": l.get("name")} for l in labels if l],
        "updated_at": node.get("updatedAt"),
        "html_url": node.get("url"),
    }


def _list_open_issues(repo: str, token: str) -> List[Dict[str, Any]]:
    """Return open non-PR issues, sorted by issue number (descending).

    Over GraphQL (vibe-ic#1645): the REST listing answers 200 with `[]`
    for this repository while the issues are intact, and a successful
    empty answer cannot be told apart from an empty queue by inspecting
    it. Every way this can go wrong RAISES — none of them returns `[]`.
    """
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise RuntimeError(f"--repo must be OWNER/NAME, got {repo!r}")
    out: List[Dict[str, Any]] = []
    after: Optional[str] = None
    for _page in range(_MAX_PAGES):
        status, body = _api_request(
            f"{_API_BASE}/graphql", token,
            {"query": _OPEN_ISSUES_QUERY,
             "variables": {"owner": owner, "name": name, "after": after}})
        if status != 200 or not isinstance(body, dict):
            # vibe-ic#1319. A failed call is NOT evidence about the repository:
            # returning [] here would report "no open issues" to an agent whose
            # only problem is that it is blocked, and the queue would read that
            # as "nothing to claim". Raise, and say WHICH limit it is — a
            # secondary limit leaves the quota looking healthy, so the operator
            # is otherwise told to keep going.
            state = _health.classify(status, body, _rate_limit_snapshot(token))
            raise RuntimeError(
                f"POST {_API_BASE}/graphql failed: status={status} [{state}] "
                f"{_health.advice(state, _rate_limit_snapshot(token))} "
                f"payload={body!r}")
        if body.get("errors"):
            # GraphQL reports a rejected query with HTTP 200 and an `errors`
            # array. Reading `data` past that would turn a refusal into a
            # count, which is the whole subject of this program's docstring.
            raise RuntimeError(
                f"GraphQL errors from {_API_BASE}/graphql: {body['errors']!r}")
        repo_obj = (body.get("data") or {}).get("repository")
        if repo_obj is None:
            raise RuntimeError(
                f"GraphQL returned no `repository` for {repo!r} — the repo "
                f"could not be read, which is NOT a repo with no open issues")
        if repo_obj.get("hasIssuesEnabled") is False:
            # The REST listing answered 410 here and this function raised.
            # GraphQL answers an EMPTY CONNECTION instead, so without this the
            # transport change would quietly convert a repository with its
            # issue tracker switched off into a repository with nothing open.
            # Same rule as `org_open_work_poll`: that zero is a fact about the
            # SETTINGS, not about the backlog. (The field is guaranteed present
            # on a successful query — GraphQL rejects an unknown field, and
            # that rejection is raised above.)
            raise RuntimeError(
                f"the issue TRACKER is DISABLED for {repo!r}; zero open issues "
                f"here would be a fact about the repository settings, not "
                f"about the queue")
        conn = repo_obj.get("issues") or {}
        for node in (conn.get("nodes") or []):
            out.append(_entry_from_node(node))
        page_info = conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            raise RuntimeError(
                "GraphQL says there is another page but gave no cursor; the "
                "listing would be truncated, and a floor is not a count")
    else:
        raise RuntimeError(
            f"open-issue listing did not finish within {_MAX_PAGES} pages; "
            f"refusing to report a truncated queue as the whole queue")
    out.sort(key=lambda x: x.get("number") or 0, reverse=True)
    return out


def _to_entry(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Project a raw GitHub issue into the report entry shape."""
    labels = [lbl.get("name") for lbl in (issue.get("labels") or [])]
    labels = [l for l in labels if l]
    return {
        "number":   issue.get("number"),
        "title":    issue.get("title") or "",
        "labels":   labels,
        "actionable": True,
        "updated_at": issue.get("updated_at"),
        "html_url":  issue.get("html_url"),
    }


def _print_text(report: Dict[str, Any]) -> None:
    print(f"# core-agent poll @ {report['repo']}")
    print(f"# total open: {report['total_open']}")
    print(f"# actionable: {report['actionable_count']}")
    print(f"# waiting:    {report['waiting_count']}")
    if not report["actionable"]:
        print("(no actionable issues)")
        return
    print()
    print("ACTIONABLE_ISSUES (every open non-PR issue):")
    for it in report["actionable"]:
        labels_s = ",".join(it["labels"]) or "-"
        print(f"  #{it['number']}\t[{labels_s}]\t{it['updated_at']}\t"
              f"{it['title'][:80]}")


def poll(repo: str = _DEFAULT_REPO,
         token: Optional[str] = None) -> Dict[str, Any]:
    """Public entry point. Returns the report dict shape used by both
    the CLI and any downstream programmatic caller (e.g. cron wrapper).

    New rule: every open non-PR issue is actionable. No label gating,
    no comment classifier. `waiting` is always empty (kept in the
    report shape for backwards compatibility)."""
    tok = token or _load_pat()
    if not tok:
        raise RuntimeError(
            "no GitHub PAT found — set $GITHUB_TOKEN, $GH_TOKEN, "
            "or place at ~/.config/github/token")
    issues = _list_open_issues(repo, tok)
    actionable = [_to_entry(it) for it in issues]
    return {
        "repo":             repo,
        "total_open":       len(actionable),
        "actionable_count": len(actionable),
        "waiting_count":    0,
        "actionable":       actionable,
        "waiting":          [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--repo", default=_DEFAULT_REPO,
                    help=f"GitHub OWNER/REPO (default: {_DEFAULT_REPO})")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON report (machine-readable)")
    args = ap.parse_args(argv)

    try:
        report = poll(repo=args.repo)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)

    return 1 if report["actionable_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
