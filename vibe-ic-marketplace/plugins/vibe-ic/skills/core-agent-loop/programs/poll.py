#!/usr/bin/env python3
"""programs/poll.py — deterministic core-agent poll
(part of the vibe-ic:core-agent-loop skill).

The core-agent calls this FIRST at every cron wake-up. The rule is
intentionally simple so the agent doesn't drift into LLM-judgement
loops:

    ACTIONABLE = any open non-PR issue that has NO `wait-for-verification`
                 label.

`NEW`, `FEEDBACK`, `WAITING` classifications are collapsed into this one
predicate: an issue is actionable iff the verification flag is absent.
Once the core-agent fixes the issue and re-applies the label, the issue
becomes non-actionable until the field-agent removes the flag (signalling
counter-evidence).

Usage
-----
    # default — print actionable issue numbers, one per line.
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py

    # json output for machine consumption.
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py --json

    # different repo (default: reyerchu/AI_IC_design).
    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py --repo owner/name

Exit codes
----------
    0   No actionable issues. Core agent exits this tick.
    1   ≥1 actionable issue. Core agent must process the listed numbers.
    2   I/O or auth error (no PAT, network error, etc.). DOES NOT
        count as actionable — the core agent should retry next tick.

Auth
----
    Reads GitHub PAT from $GITHUB_TOKEN, then $GH_TOKEN, then
    ~/.config/github/token (mode 0600 preferred). chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_REPO = "reyerchu/AI_IC_design"
_WAIT_LABEL = "wait-for-verification"
_API_BASE = "https://api.github.com"


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


def _list_open_issues(repo: str, token: str) -> List[Dict[str, Any]]:
    """Return open non-PR issues, sorted by issue number (descending)."""
    out: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = (f"{_API_BASE}/repos/{repo}/issues"
               f"?state=open&per_page=100&page={page}")
        status, data = _api_get(url, token)
        if status != 200 or not isinstance(data, list):
            raise RuntimeError(
                f"GET {url} failed: status={status} payload={data!r}")
        for it in data:
            if it.get("pull_request"):
                continue  # skip PRs
            out.append(it)
        if len(data) < 100:
            break
        page += 1
    out.sort(key=lambda x: x.get("number", 0), reverse=True)
    return out


_FEEDBACK_MARKERS = (
    "not verified",
    "removing wait-for-verification",
    "round-2 verify",
    "round-3 verify",
    "round-4 verify",
    "round-5 verify",
)

# v1.6.276 — feedback-override false-positive guard. Any comment
# starting with one of these prefixes is a core-agent self-emitted
# fix-summary template (the canonical 繁體中文 5-section comment).
# Such comments routinely QUOTE the field-agent's prior NOT VERIFIED
# marker in their root-cause / round-N text, which previously tripped
# the v1.6.268 feedback override and kept already-labelled issues
# falsely actionable. Skip override when latest comment is clearly
# the core agent's own self-acknowledgement.
_CORE_AGENT_SELF_COMMENT_PREFIXES = (
    "core agent 已推送修復",
    "core agent 已推送 round",
    # v1.6.276 — alternative round-N fix-summary template the
    # core agent emits. Match optional leading `**` markdown bold
    # the strip-lstrip in the caller does not remove.
    "**v1.6.",
    "v1.6.",
    "修復摘要",
)


_CORE_AGENT_SELF_SIGNATURE_RE = re.compile(
    # Match a comment that opens with any canonical core-agent
    # fix-announcement template. Case-insensitive; leading
    # markdown markers (#, *, whitespace combos) tolerated.
    #
    # Variants observed in the wild (any one is sufficient):
    #   * "Core agent 已推送修復" / "Core agent 已推送 round-N"
    #     — the 5-section 繁體中文 canonical template
    #   * "**v1.6.X 修復摘要 ..."
    #     — round-N alt template (issue-prefixed)
    #   * "**Fixed — v1.6.X 已 push**"
    #     — v1.6.278 worktree-agent variant (English "Fixed" +
    #       Chinese "已 push" + commit SHA)
    #   * "**修復完成 v1.6.X** / **修復完成 vX.Y.Z（round-N）**"
    #     — alternative round-N template
    #   * "**修復摘要**"
    #     — bare 修復摘要 opener
    #   * "## v1.6.X 修復 — round-N ..." (v1.6.282)
    #     — ATX-heading round-N self-acknowledgement form
    #   * "## 修復確認 — v1.6.X 已發佈" (v1.6.282)
    #     — ATX-heading initial fix confirmation form
    #   * "## v1.6.X 修復報告（#NNN round-N）" (v1.6.292)
    #     — ATX-heading round-N detailed-report variant
    # v1.6.282 widening — prefix changed from `\s*\*{0,2}\s*` to
    # `[\s#*]*` so leading `##` ATX-heading markers are consumed;
    # added `v\d+\.\d+\.\d+\s+修復` (no 摘要 required) and
    # `修復確認` variants. Existing alternatives retained.
    # v1.6.292 widening — added `修復報告` variant and extended
    # `v\d+\.\d+\.\d+\s+修復` continuation set to also accept
    # `報告` / `（` (full-width paren) for the round-N report form.
    r"^[\s#*]*"
    r"(?:core[-\s]+agent\s*已推送|"
    r"fixed\s*[—-]+\s*v\d+\.\d+\.\d+|"
    r"修復完成\s+v\d+\.\d+\.\d+|"
    r"v\d+\.\d+\.\d+\s+修復(?:摘要|報告|\s*[—\-（(])|"
    r"#\d+\s+round|"
    r"修復確認|"
    r"修復報告|"
    r"修復摘要)",
    re.IGNORECASE,
)


def _classify(issue: Dict[str, Any],
              latest_comment_body: Optional[str] = None) -> Dict[str, Any]:
    """Classify an issue as actionable or waiting.

    Primary rule: actionable iff `wait-for-verification` label absent.

    v1.6.268 — for #123/#124/#125 round-2 shared-login blind spot.
    Secondary rule (race-condition guard): when `latest_comment_body`
    is provided and contains a feedback marker (e.g. `NOT VERIFIED`,
    `Removing wait-for-verification`, `Round-N verify`), force the
    issue actionable even if the label is still present. This catches
    the race where the field-agent has posted counter-evidence but
    label removal lagged, AND the legacy case where both core-agent
    and field-agent share the same GitHub login (login-based
    classifiers cannot distinguish them, but the comment body still
    carries the field-agent's verdict markers).

    v1.6.276 — false-positive guard. When the latest comment opens
    with the core-agent self-template prefix
    (`Core agent 已推送修復` / `Core agent 已推送 round-N`), the
    feedback override is SUPPRESSED even if the comment quotes
    `NOT VERIFIED` in its root-cause narrative. The label state
    alone governs actionability for this case — quoting the
    field-agent's prior feedback in a fix-summary must not flip the
    issue back to actionable until the field-agent themself posts a
    fresh verdict.
    """
    labels = [lbl.get("name") for lbl in (issue.get("labels") or [])]
    labels = [l for l in labels if l]
    waiting = _WAIT_LABEL in labels
    feedback_override = False
    if latest_comment_body:
        body_low = latest_comment_body.lower()
        is_core_self_template = (
            _CORE_AGENT_SELF_SIGNATURE_RE.match(latest_comment_body)
            is not None
        )
        if not is_core_self_template:
            for marker in _FEEDBACK_MARKERS:
                if marker in body_low:
                    feedback_override = True
                    break
    actionable = (not waiting) or feedback_override
    return {
        "number":   issue.get("number"),
        "title":    issue.get("title") or "",
        "labels":   labels,
        "actionable": actionable,
        "feedback_override": feedback_override,
        "updated_at": issue.get("updated_at"),
        "html_url":  issue.get("html_url"),
    }


def _latest_comment_body(repo: str, issue_number: int,
                        token: str) -> Optional[str]:
    """Fetch the most recent comment body on an issue (or None)."""
    url = (f"{_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
           f"?per_page=100")
    status, data = _api_get(url, token)
    if status != 200 or not isinstance(data, list) or not data:
        return None
    return data[-1].get("body") or ""


def _print_text(report: Dict[str, Any]) -> None:
    print(f"# core-agent poll @ {report['repo']}")
    print(f"# total open: {report['total_open']}")
    print(f"# actionable: {report['actionable_count']}")
    print(f"# waiting:    {report['waiting_count']}")
    if not report["actionable"]:
        print("(no actionable issues)")
        return
    print()
    print("ACTIONABLE_ISSUES (no `wait-for-verification` label):")
    for it in report["actionable"]:
        labels_s = ",".join(it["labels"]) or "-"
        print(f"  #{it['number']}\t[{labels_s}]\t{it['updated_at']}\t"
              f"{it['title'][:80]}")
    if report["waiting"]:
        print()
        print("WAITING (skipped — has `wait-for-verification`):")
        for it in report["waiting"]:
            print(f"  #{it['number']}\t{it['title'][:80]}")


def poll(repo: str = _DEFAULT_REPO,
         token: Optional[str] = None) -> Dict[str, Any]:
    """Public entry point. Returns the report dict shape used by both
    the CLI and any downstream programmatic caller (e.g. cron wrapper)."""
    tok = token or _load_pat()
    if not tok:
        raise RuntimeError(
            "no GitHub PAT found — set $GITHUB_TOKEN, $GH_TOKEN, "
            "or place at ~/.config/github/token")
    issues = _list_open_issues(repo, tok)
    classified: List[Dict[str, Any]] = []
    for it in issues:
        # v1.6.268 — for #123/#124/#125 round-2. Cross-check the
        # latest-comment body for feedback markers when the label
        # is present, so a stale `wait-for-verification` doesn't
        # mask fresh field-agent counter-evidence (shared-login
        # blind spot).
        labels = [lbl.get("name") for lbl in (it.get("labels") or [])]
        labels = [l for l in labels if l]
        body: Optional[str] = None
        if _WAIT_LABEL in labels:
            try:
                body = _latest_comment_body(repo, it.get("number") or 0, tok)
            except Exception:
                body = None
        classified.append(_classify(it, latest_comment_body=body))
    actionable = [c for c in classified if c["actionable"]]
    waiting = [c for c in classified if not c["actionable"]]
    return {
        "repo":             repo,
        "total_open":       len(classified),
        "actionable_count": len(actionable),
        "waiting_count":    len(waiting),
        "actionable":       actionable,
        "waiting":          waiting,
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
