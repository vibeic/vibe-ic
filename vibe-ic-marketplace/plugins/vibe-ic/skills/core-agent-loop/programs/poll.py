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


def _api_get(url: str, token: str) -> Tuple[int, Any]:
    """Plain GET against the GitHub API. Returns (status_code, json)."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vibe-ic-agent-poll/1.0",
    })
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


def _api_post(url: str, token: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
    """Plain POST against the GitHub API. Returns (status_code, json).

    Same error encoding as :func:`_api_get` — a transport failure is status 0,
    never an empty success.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "vibe-ic-agent-poll/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.getcode(), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            parsed = {"message": str(exc)}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"message": f"network error: {exc!r}"}
    except ValueError as exc:
        # A 200 carrying a body that is not JSON. Status 0 like any other
        # "no answer", but SAID as what it is — calling an unparsable body a
        # network error is the same substitution this file exists to stop.
        return 0, {"message": f"unparsable response body: {exc!r}"}


#: The witness for a zero. GraphQL, deliberately — it is a DIFFERENT backend
#: from the REST list this program enumerates with, and on 2026-08-15 it was the
#: half that still answered correctly (42) while REST returned `[]`.
#:
#: `repository.issues` counts ISSUES ONLY. The obvious REST alternative,
#: `GET /repos/{o}/{r}` -> `open_issues_count`, INCLUDES pull requests: this
#: repository carries ~170 open PRs, so that field would read >0 on a genuinely
#: empty issue queue and the check would refuse every quiet tick forever. A
#: check that blocks real work is a check that gets switched off, so the witness
#: has to count the same population the listing does.
_GRAPHQL_OPEN_ISSUE_COUNT = (
    "query($owner:String!,$name:String!){"
    "repository(owner:$owner,name:$name){issues(states:OPEN){totalCount}}}"
)


def _declared_open_issue_count(repo: str, token: str) -> Optional[int]:
    """The repository's OWN count of open issues, or None if unreadable.

    None is NOT zero. A witness that could not be reached has said nothing, and
    folding it to 0 would manufacture the agreement this call exists to test.
    """
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return None
    status, data = _api_post(f"{_API_BASE}/graphql", token, {
        "query": _GRAPHQL_OPEN_ISSUE_COUNT,
        "variables": {"owner": owner, "name": name},
    })
    if status != 200 or not isinstance(data, dict) or data.get("errors"):
        return None
    try:
        return int(data["data"]["repository"]["issues"]["totalCount"])
    except (KeyError, TypeError, ValueError):
        return None


def _rate_limit_snapshot(token: str):
    """The quota, or None. `rate_limit` is EXEMPT from the secondary limit, so
    it still answers while everything else 403s — which is exactly why it is
    worth asking, and exactly why its 'healthy' answer misleads on its own."""
    status, payload = _api_get(f"{_API_BASE}/rate_limit", token)
    return payload if status == 200 else None


def _list_open_issues(repo: str, token: str) -> List[Dict[str, Any]]:
    """Return open non-PR issues, sorted by issue number (descending)."""
    out: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = (f"{_API_BASE}/repos/{repo}/issues"
               f"?state=open&per_page=100&page={page}")
        status, data = _api_get(url, token)
        if status != 200 or not isinstance(data, list):
            # vibe-ic#1319. A failed call is NOT evidence about the repository:
            # returning [] here would report "no open issues" to an agent whose
            # only problem is that it is blocked, and the queue would read that
            # as "nothing to claim". Raise, and say WHICH limit it is — a
            # secondary limit leaves the quota looking healthy, so the operator
            # is otherwise told to keep going.
            state = _health.classify(status, data, _rate_limit_snapshot(token))
            raise RuntimeError(
                f"GET {url} failed: status={status} [{state}] "
                f"{_health.advice(state, _rate_limit_snapshot(token))} "
                f"payload={data!r}")
        for it in data:
            if it.get("pull_request"):
                continue  # skip PRs
            out.append(it)
        if len(data) < 100:
            break
        page += 1
    if not out:
        # vibe-ic#1384. THE ONE RESULT NOTHING ABOVE CAN REFUSE: 200, a
        # well-formed list, and empty. It is byte-identical to a clean queue,
        # and it routes `main()` to rc 0 — "core agent exits this tick" — which
        # is the single worst response to "the issue list is broken".
        #
        # Asked ONLY on a zero: one extra call, on the tick where the agent
        # would otherwise go back to sleep, and never on a tick that already
        # has work. That is also exactly where a false zero does its damage.
        declared = _declared_open_issue_count(repo, token)
        if isinstance(declared, int) and declared > 0:
            raise RuntimeError(
                f"the REST issue listing for {repo} returned 0 open issues but "
                f"the repository declares {declared} open (GraphQL) — one of "
                f"these is wrong, so the queue state is UNKNOWN, not empty. "
                f"This is NOT 'no actionable issues': acting on it would exit "
                f"this tick with {declared} issue(s) open (vibe-ic#1384).")
        if declared is None:
            # Named, not fatal: the listing itself succeeded, and refusing here
            # would halt a genuinely quiet queue every time one extra call
            # hiccups. The zero is still reported — it is just reported as
            # resting on a single source, which is what it is.
            print(f"[UNWITNESSED] {repo}: the listing returned 0 open issues "
                  f"and the repository's own open count could not be read, so "
                  f"this zero rests on a single source (vibe-ic#1384).",
                  file=sys.stderr)
    out.sort(key=lambda x: x.get("number", 0), reverse=True)
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
