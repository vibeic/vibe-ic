#!/usr/bin/env python3
"""backlog_status.py — core ↔ field agent backlog tracker.

Backlog = internal tracker for "issues the core agent owes a fix".
Distinct from GitHub issue state (which only the field agent
closes after real-benchmark verification).

Storage: community/backlogs/issue_fix_log.json (committed to repo
so the next cron / next session sees the same state).

Lifecycle:
  open    — field agent filed a GitHub issue, core agent has not
            yet pushed a fix
  closed  — core agent pushed a fix; awaiting field-agent
            verification on GitHub
  (deleted) — never; we keep the audit trail

CLI:
  --list-open
  --ensure-tracked <issue#> --title <t> [--source github]
       (idempotent: creates entry if missing, NEVER flips status)
  --reopen <issue#>
       (explicit; called only on field-agent reopen signal)
  --mark-closed <issue#> --version <vX.Y.Z> --commit <sha>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("~/AI_IC_design")
LOG_PATH = REPO_ROOT / "community" / "backlogs" / "issue_fix_log.json"


def _load() -> dict:
    if not LOG_PATH.exists():
        return {"_schema": 1, "items": {}}
    return json.loads(LOG_PATH.read_text())


def _save(data: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_list_open(args) -> int:
    data = _load()
    open_items = [
        v for v in data["items"].values() if v["status"] == "open"
    ]
    print(json.dumps(open_items, indent=2))
    return 0


def cmd_ensure_tracked(args) -> int:
    """Idempotent: creates a NEW backlog entry only if the issue
    is unknown. NEVER flips status. A closed backlog with the
    GitHub issue still in `state=open` is normal — that's the
    `wait-for-verification` window before the field agent runs
    the real-benchmark sweep.
    """
    data = _load()
    key = str(args.issue_number)
    if key in data["items"]:
        print(f"already tracked #{args.issue_number} "
              f"(status={data['items'][key]['status']}, no-op)")
        return 0
    data["items"][key] = {
        "issue_number": args.issue_number,
        "title": args.title,
        "source": args.source,
        "status": "open",
        "opened_at": _now(),
        "fix_version": None,
        "fix_commit": None,
        "closed_at": None,
    }
    _save(data)
    print(f"opened #{args.issue_number}")
    return 0


def cmd_reopen(args) -> int:
    """Explicit reopen, called only when the field agent has
    actually reverted the GitHub issue from closed → open OR
    removed the wait-for-verification label with new feedback.
    Preserves prior fix in history[].
    """
    data = _load()
    key = str(args.issue_number)
    item = data["items"].get(key)
    if item is None:
        print(f"error: #{args.issue_number} not in backlog",
              file=sys.stderr)
        return 1
    if item["status"] == "open":
        print(f"already open #{args.issue_number} (no-op)")
        return 0
    item.setdefault("history", []).append({
        "fix_version": item["fix_version"],
        "fix_commit": item["fix_commit"],
        "closed_at": item["closed_at"],
        "reopened_at": _now(),
    })
    item["status"] = "open"
    item["fix_version"] = None
    item["fix_commit"] = None
    item["closed_at"] = None
    _save(data)
    print(f"reopened #{args.issue_number}")
    return 0


def cmd_mark_closed(args) -> int:
    data = _load()
    key = str(args.issue_number)
    item = data["items"].get(key)
    if item is None:
        print(f"error: #{args.issue_number} not in backlog",
              file=sys.stderr)
        return 1
    if item["status"] == "closed":
        print(f"already closed #{args.issue_number} (no-op)")
        return 0
    item["status"] = "closed"
    item["fix_version"] = args.version
    item["fix_commit"] = args.commit
    item["closed_at"] = _now()
    _save(data)
    print(f"closed #{args.issue_number} at {args.version}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list-open")
    sp.set_defaults(func=cmd_list_open)

    sp = sub.add_parser("ensure-tracked")
    sp.add_argument("--issue-number", type=int, required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--source", default="github")
    sp.set_defaults(func=cmd_ensure_tracked)

    sp = sub.add_parser("reopen")
    sp.add_argument("--issue-number", type=int, required=True)
    sp.set_defaults(func=cmd_reopen)

    sp = sub.add_parser("mark-closed")
    sp.add_argument("--issue-number", type=int, required=True)
    sp.add_argument("--version", required=True)
    sp.add_argument("--commit", required=True)
    sp.set_defaults(func=cmd_mark_closed)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
