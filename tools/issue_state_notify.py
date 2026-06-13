#!/usr/bin/env python3
"""issue_state_notify.py — diff GitHub issue state across cron fires.

Compares the current open/closed state + labels of every recently
touched issue in reyerchu/AI_IC_design against a local snapshot
at ~/.config/vibe-ic-issue-state.json. Emits a JSON event list on
stdout (one line per change), then rewrites the snapshot.

Event kinds:
  * state_change       — open <-> closed
  * label_added        — new label appeared
  * label_removed      — label gone
  * new_issue          — first time we've seen this number

Cron fire reads stdout; non-empty event list → emit PushNotification.

Why a separate snapshot file rather than diff-from-comments:
  * comments don't transition state (closing an issue can be
    button-only, no comment) — must read `state` directly
  * snapshot is durable across cron fires + manual triggers
  * o(open + recent-closed) per fire, bounded
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = "reyerchu/AI_IC_design"
STATE_PATH = Path.home() / ".config" / "vibe-ic-issue-state.json"
TOKEN_PATH = Path.home() / ".config" / "github" / "token"


def _gh(path: str, token: str) -> Any:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _fetch_recent(token: str) -> list[dict]:
    open_issues = _gh(
        f"/repos/{REPO}/issues?state=open&per_page=50", token)
    closed = _gh(
        f"/repos/{REPO}/issues?state=closed&per_page=20"
        "&sort=updated&direction=desc",
        token,
    )
    seen = set()
    out: list[dict] = []
    for d in (*open_issues, *closed):
        if d.get("pull_request"):
            continue
        if d["number"] in seen:
            continue
        seen.add(d["number"])
        out.append(d)
    return out


def _load_snapshot() -> dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_snapshot(snap: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(snap, indent=2, sort_keys=True))


def _diff(prev: dict, cur: dict, num: int) -> list[dict]:
    events: list[dict] = []
    if not prev:
        events.append({
            "kind": "new_issue",
            "number": num,
            "state": cur["state"],
            "title": cur["title"],
        })
        return events
    if prev.get("state") != cur["state"]:
        events.append({
            "kind": "state_change",
            "number": num,
            "from": prev.get("state"),
            "to": cur["state"],
            "title": cur["title"],
        })
    prev_labels = set(prev.get("labels", []))
    cur_labels = set(cur["labels"])
    for added in sorted(cur_labels - prev_labels):
        events.append({
            "kind": "label_added",
            "number": num,
            "label": added,
            "title": cur["title"],
        })
    for removed in sorted(prev_labels - cur_labels):
        events.append({
            "kind": "label_removed",
            "number": num,
            "label": removed,
            "title": cur["title"],
        })
    return events


def comment_is_core_agent(body: str) -> bool:
    """Classify a GitHub issue comment as core-agent push vs field-agent
    verification report.

    A core-agent push comment starts with ``## v<X.Y.Z> -`` (em-dash or
    hyphen after the version, no ``verification`` keyword in the first
    line). A field-agent verification report starts with
    ``## v<X.Y.Z> verification ...`` -- same version prefix but with the
    keyword ``verification`` somewhere on the first line.

    Returns ``True`` only if the comment looks like a core-agent push.
    Comments that don't match the ``## v<X.Y.Z>`` shape return ``False``.
    """
    if not body:
        return False
    first_line = body.lstrip().split('\n', 1)[0]
    if not re.match(r'^##\s*v\d+\.\d+\.\d+\b', first_line, re.IGNORECASE):
        return False
    if re.search(r'\bverification\b', first_line, re.IGNORECASE):
        return False
    return True


_FIELD_FAIL_MARKERS_RE = re.compile(
    r'\b(?:reopen(?:ing)?|residual|regress(?:ion|ed)?|leak(?:ing|s)?|'
    r'still\s+(?:fires|leaks|emits|fails|broken)|'
    r'NOT\s+fixed|partial(?:ly)?\s+(?:fix|fail)|'
    r'fail(?:ed|ure)?\b(?!\s+to\s+reject))\b',
    re.IGNORECASE,
)


def classify_comment(body: str) -> str:
    """Three-way classifier.

    Returns one of:
      * ``core``        — core-agent push comment (no fix needed)
      * ``field_pass``  — field-agent verification confirming PASS
                          (no fix needed, just waiting for the field
                          agent to actually close the issue)
      * ``field_fail``  — field-agent verification reporting a residual
                          / regression / leak (core agent must fix)

    Cron triage logic: ``field_fail`` is the only ACTIONABLE class.
    A ``field_pass`` PASS-report is a no-op for the core agent — it
    merely awaits the field agent's close button.
    """
    if comment_is_core_agent(body):
        return 'core'
    if not body:
        return 'field_fail'
    # field-agent comment. Distinguish PASS vs FAIL by scanning for
    # FAIL-marker words anywhere in the body.
    if _FIELD_FAIL_MARKERS_RE.search(body):
        return 'field_fail'
    # No FAIL marker present → treat as PASS (closing-confirmation,
    # verified, fixed across all N projects, etc.). Conservative
    # default: any field comment lacking explicit FAIL signals is a
    # PASS, which prevents the false-positive cron loop on
    # closing-confirmation reports.
    return 'field_pass'


def _classify_stdin() -> int:
    """CLI: emit a single label for a comment body on stdin.

    With ``--three-way`` flag emits one of {core, field_pass, field_fail}.
    Without flag (default) emits the older ``core`` / ``field`` labels
    for backwards-compat with v1.6.77-era cron prompts. Cron prompts
    that need the PASS-vs-FAIL distinction must opt in.
    """
    body = sys.stdin.read()
    if '--three-way' in sys.argv[1:]:
        print(classify_comment(body))
    else:
        print('core' if comment_is_core_agent(body) else 'field')
    return 0


def main() -> int:
    if '--classify-comment-stdin' in sys.argv[1:]:
        return _classify_stdin()
    if not TOKEN_PATH.exists():
        print(json.dumps({"error": "no_github_token"}))
        return 2
    token = TOKEN_PATH.read_text().strip()

    issues = _fetch_recent(token)
    snapshot = _load_snapshot()
    new_snapshot: dict[str, dict] = {}
    all_events: list[dict] = []

    for d in issues:
        num = d["number"]
        cur = {
            "state": d["state"],
            "labels": [l["name"] for l in d.get("labels", [])],
            "updated_at": d["updated_at"],
            "title": d["title"][:120],
        }
        new_snapshot[str(num)] = cur
        prev = snapshot.get(str(num), {})
        all_events.extend(_diff(prev, cur, num))

    # Preserve snapshot entries we didn't see this fire (older
    # closed issues) — don't drop them, or a future re-open
    # would falsely fire as "new_issue".
    for k, v in snapshot.items():
        new_snapshot.setdefault(k, v)

    _save_snapshot(new_snapshot)

    out = {
        "events": all_events,
        "tracked": len(new_snapshot),
        "fetched": len(issues),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
