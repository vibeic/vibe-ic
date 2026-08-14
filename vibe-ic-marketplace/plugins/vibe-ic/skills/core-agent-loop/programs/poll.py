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
    2   I/O or auth error (no PAT, network error, etc.). DOES NOT
        count as actionable — the core agent should retry next tick.

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
