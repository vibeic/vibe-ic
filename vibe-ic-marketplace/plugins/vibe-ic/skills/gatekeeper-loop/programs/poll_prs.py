#!/usr/bin/env python3
"""programs/poll_prs.py — deterministic gatekeeper-loop PR poll
(part of the vibe-ic:gatekeeper-loop skill).

The single gatekeeper agent that OWNS ``main`` calls this FIRST at every
cron wake-up. It is the PR-merge counterpart of the issue-fix
``core-agent-loop/programs/poll.py``: where ``poll.py`` answers "which
issues need fixing?", ``poll_prs.py`` answers "which open PRs against
``main`` need gatekeeping?".

The rule is intentionally simple so the agent never drifts into an
LLM-judgement loop at the POLL stage (judgement belongs only in the
Step-2.7 adversarial gate, never here):

    ACTIONABLE = ANY OPEN, NON-DRAFT PR targeting the base branch
                 (default: ``main``).

There is NO label gating and NO comment classifier. A draft PR is the
author still declaring "not ready" — it is excluded (the author has not
asked for the gate). Everything else open against the base is actionable
and is handed to the gatekeeper newest-first (highest PR number first),
so a freshly-pushed PR is serviced before stale ones.

The poll DOES NOT decide mergeability — that is the job of the machine
gates (``gatekeeper_review.py``) and the Step-2.7 adversarial review in
later loop steps. The poll only enumerates candidates. ``mergeable`` /
``mergeStateStatus`` / ``labels`` are surfaced in the report as
ADVISORY context for the agent, never as a filter (a PR that GitHub
currently reports ``CONFLICTING`` still needs the gatekeeper to eject it
back to the author — silently dropping it from the poll would wedge it).

Usage
-----
    # default — print a human report of actionable PRs, newest-first.
    python3 .../gatekeeper-loop/programs/poll_prs.py

    # json output for machine consumption.
    python3 .../gatekeeper-loop/programs/poll_prs.py --json

    # different repo / base branch (defaults: vibeic/vibe-ic, main).
    python3 .../gatekeeper-loop/programs/poll_prs.py --repo owner/name --base main

Exit codes
----------
    0   No actionable PRs. Gatekeeper idles this tick (healthy idle —
        NOT a stop signal; see SKILL.md §STOP CONDITION).
    1   >=1 actionable PR. Gatekeeper must process the listed numbers.
    2   I/O or auth error (no PAT, network error, bad repo, etc.). DOES
        NOT count as actionable — the gatekeeper retries next tick.

Auth
----
    Prefers the ``gh`` CLI when present (it carries the operator's
    existing GitHub auth and handles enterprise hosts), falling back to
    the REST API with a PAT from $GITHUB_TOKEN, then $GH_TOKEN, then
    ~/.config/github/token (mode 0600 preferred). chip-AGNOSTIC: keys
    only on repo / base / PR metadata, never on any chip / vendor / SKU.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The gatekeeper owns ``main`` of the vibe-ic repo. Issues AND PRs both live in
# vibeic/vibe-ic — the issue-fix core-agent loop polls vibeic/vibe-ic ISSUES and
# the gatekeeper polls vibeic/vibe-ic PRs (same repo, different object type).
# (`AI_IC_design` is the local design WORKSPACE directory, not an issue repo.)
# Override with --repo.
_DEFAULT_REPO = "vibeic/vibe-ic"
_DEFAULT_BASE = "main"
_API_BASE = "https://api.github.com"

# The exact field set the gatekeeper needs. Kept as a constant so the
# gh-CLI path and the REST projection cannot drift apart.
_PR_FIELDS = ["number", "headRefName", "baseRefName", "author",
              "isDraft", "mergeable", "mergeStateStatus", "labels",
              "title", "updatedAt", "url"]


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
def _load_pat() -> Optional[str]:
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(env)
        if v and v.strip():
            return v.strip()
    token_path = Path.home() / ".config" / "github" / "token"
    if token_path.is_file():
        try:
            return token_path.read_text().strip() or None
        except OSError:
            return None
    return None


def _have_gh() -> bool:
    return shutil.which("gh") is not None


# --------------------------------------------------------------------------
# gh-CLI path (preferred)
# --------------------------------------------------------------------------
def _list_open_prs_gh(repo: str, base: str) -> List[Dict[str, Any]]:
    """List OPEN PRs via the gh CLI. Raises RuntimeError on failure so
    the caller maps it to exit-code 2 (retry next tick)."""
    cmd = [
        "gh", "pr", "list",
        "--repo", repo,
        "--base", base,
        "--state", "open",
        "--limit", "200",
        "--json", ",".join(_PR_FIELDS),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"gh pr list failed to launch: {exc!r}")
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr list exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()}")
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr list emitted non-JSON: {exc}")
    if not isinstance(data, list):
        raise RuntimeError(f"gh pr list emitted non-list: {data!r}")
    return data


# --------------------------------------------------------------------------
# REST path (fallback when gh is absent)
# --------------------------------------------------------------------------
def _api_get(url: str, token: str) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vibe-ic-gatekeeper-poll/1.0",
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


def _list_open_prs_rest(repo: str, base: str, token: str) -> List[Dict[str, Any]]:
    """List OPEN PRs against ``base`` via the REST API, projected into the
    SAME shape the gh path returns so downstream code is path-agnostic.

    GitHub's REST ``mergeable`` is only computed on a single-PR GET (the
    list endpoint omits it), so we deliberately leave ``mergeable`` /
    ``mergeStateStatus`` as None here — they are ADVISORY only and never
    gate the poll, so a second round-trip per PR is not worth it."""
    out: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = (f"{_API_BASE}/repos/{repo}/pulls"
               f"?state=open&base={base}&per_page=100&page={page}")
        status, data = _api_get(url, token)
        if status != 200 or not isinstance(data, list):
            raise RuntimeError(
                f"GET {url} failed: status={status} payload={data!r}")
        for pr in data:
            out.append({
                "number":          pr.get("number"),
                "headRefName":     (pr.get("head") or {}).get("ref"),
                "baseRefName":     (pr.get("base") or {}).get("ref"),
                "author":          {"login": (pr.get("user") or {}).get("login")},
                "isDraft":         bool(pr.get("draft")),
                "mergeable":       None,   # list endpoint does not compute it
                "mergeStateStatus": None,
                "labels":          [{"name": l.get("name")}
                                    for l in (pr.get("labels") or [])],
                "title":           pr.get("title") or "",
                "updatedAt":       pr.get("updated_at"),
                "url":             pr.get("html_url"),
            })
        if len(data) < 100:
            break
        page += 1
    return out


# --------------------------------------------------------------------------
# Normalisation + projection
# --------------------------------------------------------------------------
def _author_login(pr: Dict[str, Any]) -> str:
    author = pr.get("author") or {}
    if isinstance(author, dict):
        return author.get("login") or author.get("name") or "?"
    return str(author)


def _label_names(pr: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for lbl in (pr.get("labels") or []):
        if isinstance(lbl, dict):
            name = lbl.get("name")
        else:
            name = lbl
        if name:
            out.append(name)
    return out


def _to_entry(pr: Dict[str, Any]) -> Dict[str, Any]:
    """Project a raw PR (from either path) into the report entry shape."""
    return {
        "number":           pr.get("number"),
        "title":            pr.get("title") or "",
        "head":             pr.get("headRefName"),
        "base":             pr.get("baseRefName"),
        "author":           _author_login(pr),
        "labels":           _label_names(pr),
        # ADVISORY context only — NOT a poll filter (see module docstring).
        "mergeable":        pr.get("mergeable"),
        "mergeStateStatus": pr.get("mergeStateStatus"),
        "actionable":       True,
        "updated_at":       pr.get("updatedAt"),
        "html_url":         pr.get("url"),
    }


def _is_actionable(pr: Dict[str, Any], base: str) -> bool:
    """ACTIONABLE = open, non-draft, targeting ``base``.

    The state=open filter is applied at the source query, so here we only
    enforce non-draft + base-branch. (The gh/REST base filter is belt-and-
    braces re-checked here so a future query change can't leak a foreign-
    base PR into the queue.)"""
    if pr.get("isDraft"):
        return False
    pr_base = pr.get("baseRefName")
    # If the source did not populate base (shouldn't happen), don't drop
    # the PR on a missing field — fail OPEN to the gatekeeper, never
    # silently swallow a candidate.
    if pr_base is not None and pr_base != base:
        return False
    return True


def poll(repo: str = _DEFAULT_REPO,
         base: str = _DEFAULT_BASE,
         token: Optional[str] = None,
         prefer_gh: bool = True) -> Dict[str, Any]:
    """Public entry point. Returns the report dict shape used by both the
    CLI and any downstream programmatic caller (e.g. the cron wrapper).

    Rule: every OPEN, NON-DRAFT PR against ``base`` is actionable. No
    label gating, no comment classifier. ``skipped_drafts`` is surfaced
    for transparency (a draft is the author's own "not ready" signal)."""
    raw: List[Dict[str, Any]]
    if prefer_gh and _have_gh():
        raw = _list_open_prs_gh(repo, base)
    else:
        tok = token or _load_pat()
        if not tok:
            raise RuntimeError(
                "no GitHub auth — install the `gh` CLI (preferred) or set "
                "$GITHUB_TOKEN / $GH_TOKEN / ~/.config/github/token")
        raw = _list_open_prs_rest(repo, base, tok)

    drafts = [pr for pr in raw if pr.get("isDraft")]
    actionable = [_to_entry(pr) for pr in raw if _is_actionable(pr, base)]
    # Newest-first: highest PR number first.
    actionable.sort(key=lambda x: (x.get("number") or 0), reverse=True)

    return {
        "repo":             repo,
        "base":             base,
        "total_open":       len(raw),
        "actionable_count": len(actionable),
        "skipped_drafts":   len(drafts),
        "actionable":       actionable,
        "draft_numbers":    sorted(
            (pr.get("number") for pr in drafts if pr.get("number")),
            reverse=True),
    }


def _print_text(report: Dict[str, Any]) -> None:
    print(f"# gatekeeper PR poll @ {report['repo']} (base={report['base']})")
    print(f"# total open PRs: {report['total_open']}")
    print(f"# actionable:     {report['actionable_count']}")
    print(f"# skipped drafts: {report['skipped_drafts']}"
          + (f"  {report['draft_numbers']}" if report["draft_numbers"] else ""))
    if not report["actionable"]:
        print("(no actionable PRs)")
        return
    print()
    print("ACTIONABLE_PRS (open, non-draft, newest-first):")
    for it in report["actionable"]:
        labels_s = ",".join(it["labels"]) or "-"
        merge_s = it.get("mergeable") or "?"
        print(f"  #{it['number']}\t[{labels_s}]\t"
              f"head={it['head']}\tby={it['author']}\t"
              f"mergeable={merge_s}\t{it['title'][:70]}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--repo", default=_DEFAULT_REPO,
                    help=f"GitHub OWNER/REPO (default: {_DEFAULT_REPO})")
    ap.add_argument("--base", default=_DEFAULT_BASE,
                    help=f"base branch the PRs target (default: {_DEFAULT_BASE})")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON report (machine-readable)")
    ap.add_argument("--no-gh", action="store_true",
                    help="force the REST/PAT path (skip the gh CLI)")
    args = ap.parse_args(argv)

    try:
        report = poll(repo=args.repo, base=args.base, prefer_gh=not args.no_gh)
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
