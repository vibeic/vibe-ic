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


# --------------------------------------------------------------------------
# ROUND CONTEXT: which PR owns each non-atomic declared-report write
# --------------------------------------------------------------------------
# `atomic_write_pr_attribution` (vibe-ic#1468) answers the question the landing
# gate cannot: `atomic_artifact_write_check` says "does THIS TREE contain a new
# offender", and the round needs "WHOSE PR put it there", because a site has to
# be converted on the branch that carries it. It had no caller. The map #1468
# built by hand instead — one shared tree, every PR's file dropped in, the gate
# run ONCE — under-reported in four of four measurable cases, because two PRs
# adding the same filename overwrote each other and only the survivor was
# scanned. Five PRs were told they had nothing to fix.
#
# THE POLL IS WHERE THE ROUND STARTS, so it is where the map belongs: this is
# the one place that already knows the actionable PR numbers, so the tool is
# handed them directly and never re-lists open PRs behind the poll's back.
#
# IT IS ADVISORY AND IT NEVER MOVES THE EXIT CODE. Same rule the module
# docstring states for `mergeable` / `mergeStateStatus`: the poll ENUMERATES
# candidates and does not decide mergeability. A PR carrying a site still needs
# the gatekeeper; silently dropping it would wedge it.
#
# A COUNT NOBODY COULD MEASURE IS NOT A ZERO. The tool's rc 2 (a PR whose file
# list or head blob could not be read, or the gate/residual absent) is recorded
# as `checked: false` with the reason, NEVER folded into "no PR owns a site".
_ATTRIB_REL = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
               "atomic_write_pr_attribution.py")


def _default_checkout() -> Optional[Path]:
    """The git checkout this skill ships inside, or None.

    `parents[6]` is the repo root: programs/gatekeeper-loop/skills/vibe-ic/
    plugins/vibe-ic-marketplace/<root>. Verified by the tool's presence, not by
    counting alone — a moved file must not silently point at a parent directory.
    """
    here = Path(__file__).resolve()
    for cand in here.parents:
        if (cand / _ATTRIB_REL).is_file() and (cand / ".git").exists():
            return cand
    return None


def _prune_stale_cache(cache: Path, entries: List[Dict[str, Any]]) -> None:
    """Drop cached file lists for PRs that have been pushed to since.

    The cache is what makes this affordable on a cron tick, and a cache keyed
    only by PR number is a cache that answers about the wrong commit. The
    sidecar records each PR's `updatedAt`; a change to it removes that PR's
    entry so the tool re-reads it.
    """
    side = cache / "updated_at.json"
    try:
        prev = json.loads(side.read_text()) if side.is_file() else {}
    except (OSError, ValueError):
        prev = {}
    now = {str(e["number"]): e.get("updated_at") or "" for e in entries
           if e.get("number")}
    for num, stamp in now.items():
        if prev.get(num) != stamp:
            try:
                (cache / f"{num}.tsv").unlink()
            except OSError:
                pass
    try:
        cache.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps({**prev, **now}, indent=1))
    except OSError:
        pass


def attribute_atomic_writes(report: Dict[str, Any],
                            checkout: Optional[Path] = None,
                            cache_dir: Optional[Path] = None,
                            timeout: int = 300) -> Dict[str, Any]:
    """Run `atomic_write_pr_attribution` over the PRs this poll just found."""
    numbers = [e["number"] for e in report.get("actionable", []) if e.get("number")]
    if not numbers:
        return {"checked": True, "prs": 0, "sites": 0, "by_pr": {},
                "why": "no actionable PR to attribute"}
    root = Path(checkout) if checkout else _default_checkout()
    if root is None:
        return {"checked": False, "prs": len(numbers), "by_pr": {},
                "why": ("no git checkout carrying "
                        f"{_ATTRIB_REL} was found above this file, so no PR "
                        "head could be read — this is NOT a clean result")}
    tool = root / _ATTRIB_REL
    cache = Path(cache_dir) if cache_dir else (root / ".git" / "vibeic-attribution-cache")
    _prune_stale_cache(cache, report.get("actionable", []))

    argv = [sys.executable, str(tool), "--repo", str(root),
            "--owner-repo", report.get("repo", _DEFAULT_REPO),
            "--cache-dir", str(cache)]
    for n in numbers:
        argv += ["--pr", str(n)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"checked": False, "prs": len(numbers), "by_pr": {},
                "why": f"{type(exc).__name__}: {exc}"}

    by_pr: Dict[str, List[str]] = {}
    for line in proc.stdout.splitlines():
        # `<file>:<line>   #<pr>` — the tool's own rendering, read for the two
        # tokens the round works from and nothing else.
        if "#" not in line:
            continue
        head, _, tail = line.rpartition("#")
        pr = tail.strip().split()[0] if tail.strip() else ""
        site = head.strip()
        if pr.isdigit() and site:
            by_pr.setdefault(pr, []).append(site)

    if proc.returncode == 2:
        return {"checked": False, "prs": len(numbers), "by_pr": by_pr,
                "sites_floor": sum(len(v) for v in by_pr.values()),
                "why": (proc.stderr.strip().splitlines() or
                        ["the tool reported NOT CHECKED"])[-1]}
    return {"checked": True, "prs": len(numbers), "by_pr": by_pr,
            "sites": sum(len(v) for v in by_pr.values()),
            "rc": proc.returncode,
            "why": "" if proc.returncode in (0, 1) else proc.stderr.strip()[:300]}


def _print_attribution(att: Dict[str, Any]) -> None:
    if not att.get("checked"):
        print(f"\n# atomic-write attribution: NOT CHECKED over "
              f"{att.get('prs', 0)} PR(s) — {att.get('why')}")
        if att.get("by_pr"):
            print(f"#   sites found anyway are a FLOOR, not a count: {att['by_pr']}")
        return
    if not att.get("by_pr"):
        print(f"\n# atomic-write attribution: 0 site(s) over "
              f"{att.get('prs', 0)} PR(s) examined")
        return
    print(f"\n# atomic-write attribution: {att['sites']} site(s) over "
          f"{att['prs']} PR(s) — each must be converted on the branch that "
          f"carries it")
    for pr, sites in sorted(att["by_pr"].items(), key=lambda kv: -int(kv[0])):
        print(f"  #{pr}\t{', '.join(sites)}")


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
    ap.add_argument("--no-atomic-attribution", action="store_true",
                    help="skip the atomic-write attribution map (round "
                         "context; never affects the exit code)")
    ap.add_argument("--attribution-checkout", default=None,
                    help="git checkout the PR heads are read from "
                         "(default: the checkout this skill ships inside)")
    ap.add_argument("--attribution-cache", default=None,
                    help="per-PR changed-file cache dir "
                         "(default: <checkout>/.git/vibeic-attribution-cache)")
    args = ap.parse_args(argv)

    try:
        report = poll(repo=args.repo, base=args.base, prefer_gh=not args.no_gh)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.no_atomic_attribution:
        report["atomic_write_attribution"] = attribute_atomic_writes(
            report,
            checkout=args.attribution_checkout,
            cache_dir=args.attribution_cache)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_text(report)
        if "atomic_write_attribution" in report:
            _print_attribution(report["atomic_write_attribution"])

    # THE ATTRIBUTION NEVER MOVES THIS. The poll's contract is "how many PRs
    # need gatekeeping", and a site attributed to a PR is context for the
    # gatekeeper, not a fourth exit state.
    return 1 if report["actionable_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
