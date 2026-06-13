#!/usr/bin/env python3
"""waiver_staleness_check.py — BACKLOG-v10 P1.3.

Flag waivers that have aged past their review window. Open waivers
that have lived for many months without being closed are rotting
work — they accumulate, mask real regressions, and undermine the
"waiver = deferred open work" contract.

Severity ladder
===============

  age <  warn_days     → no finding
  warn_days ≤ age <  err_days  → WARNING
  age ≥ err_days       → ERROR

Defaults: warn_days = 90, err_days = 180. Override via CLI flags.

Schema
======

This gate reads `waivers.json` (top-level list OR `{"waivers": [...]}`
OR `{"waived_steps": [...]}`) and inspects each entry's `approved_at`
field (ISO-8601 date or datetime). If `approved_at` is missing,
`waivers_schema_check` already flags it — staleness gate is silent
on that entry to avoid double-counting.

False-alert guards
==================

  - Silent if no `waivers.json` exists (no open waivers, nothing to
    audit).
  - Silent for waiver entries that have a non-empty `closure_proof`
    field — the waiver is closed, not stale.
  - Silent for entries missing `approved_at` (other gate handles).
  - Silent for entries with `approved_at` that doesn't parse — would
    create noise; format is the schema gate's job.
  - Silent if `--warn-days <= 0` (gate explicitly disabled).

Exit codes: 0 PASS / 1 ERROR-class staleness / 2 skip
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


def _parse_iso(s: str) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    # Accept date-only (YYYY-MM-DD) or full ISO-8601
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.replace(tzinfo=timezone.utc)
        # Try fromisoformat (handles offsets and microseconds)
        # Strip trailing 'Z' for Python <3.11 compatibility
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, TypeError):
        return None


def _load_waivers(project: Path) -> tuple[Path | None, list]:
    for cand in (project / "waivers.json",
                 *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return cand, data
        if isinstance(data, dict):
            for k in ("waivers", "waived_steps", "entries"):
                v = data.get(k)
                if isinstance(v, list):
                    return cand, v
        return cand, []
    return None, []


def _is_closed(entry: dict) -> bool:
    cp = entry.get("closure_proof")
    if isinstance(cp, str) and cp.strip():
        return True
    if isinstance(cp, dict) and cp:
        return True
    if entry.get("status") in ("closed", "resolved", "fixed"):
        return True
    return False


def inspect(project: Path, warn_days: int = 90,
            err_days: int = 180,
            now: datetime | None = None
            ) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "waivers_path": None,
        "warn_days": warn_days,
        "err_days": err_days,
        "entries_examined": 0,
        "stale_warn": [],
        "stale_err": [],
        "skipped_reason": "",
    }
    if warn_days <= 0:
        summary["skipped_reason"] = "warn_days <= 0 (gate disabled)"
        return findings, summary

    cand, entries = _load_waivers(project)
    if cand is None:
        summary["skipped_reason"] = "no waivers.json"
        return findings, summary
    summary["waivers_path"] = str(cand.relative_to(project))
    if not entries:
        summary["skipped_reason"] = "waivers.json has no entries"
        return findings, summary

    now = now or datetime.now(timezone.utc)

    for e in entries:
        if not isinstance(e, dict):
            continue
        if _is_closed(e):
            continue
        approved = _parse_iso(e.get("approved_at", ""))
        if approved is None:
            continue
        summary["entries_examined"] += 1
        age_days = (now - approved).days
        wid = e.get("id", "?")
        reason = e.get("reason") or e.get("rationale") or "(no reason)"
        if age_days >= err_days:
            summary["stale_err"].append({
                "id": wid, "age_days": age_days,
                "approved_at": str(approved.date()),
            })
            findings.append(Finding(
                severity="ERROR",
                rule="WAIVER_STALE_ERR",
                message=(
                    f"waiver id={wid!r} approved {approved.date()} "
                    f"({age_days} days old) exceeds err threshold "
                    f"{err_days}. Either close the waiver "
                    f"(set `closure_proof`) or re-justify and bump "
                    f"`approved_at`. Reason: {reason[:80]!r}"
                ),
                file=summary["waivers_path"],
            ))
        elif age_days >= warn_days:
            summary["stale_warn"].append({
                "id": wid, "age_days": age_days,
                "approved_at": str(approved.date()),
            })
            findings.append(Finding(
                severity="WARNING",
                rule="WAIVER_STALE_WARN",
                message=(
                    f"waiver id={wid!r} approved {approved.date()} "
                    f"({age_days} days old) exceeds warn threshold "
                    f"{warn_days}. Plan closure or re-justify before "
                    f"{err_days}-day error gate."
                ),
                file=summary["waivers_path"],
            ))
    if summary["entries_examined"] == 0:
        summary["skipped_reason"] = (
            "no waiver entries with parseable approved_at and no "
            "closure_proof"
        )
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="waiver_staleness_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--warn-days", type=int, default=90)
    ap.add_argument("--err-days", type=int, default=180)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project,
                                warn_days=args.warn_days,
                                err_days=args.err_days)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "waiver_staleness_check",
            "passed": not any(f.severity == "ERROR" for f in findings),
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== waiver_staleness_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    err_count = sum(1 for f in findings if f.severity == "ERROR")
    warn_count = sum(1 for f in findings if f.severity == "WARNING")
    if not findings:
        print(f"  [PASS] {summary['entries_examined']} open waiver(s); "
              f"none stale ({summary['warn_days']}/{summary['err_days']} day "
              f"thresholds)")
        return 0
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: {'FAIL' if err_count else 'PASS (with warnings)'} "
          f"({err_count} stale-ERR, {warn_count} stale-WARN)")
    return 1 if err_count else 0


if __name__ == "__main__":
    sys.exit(main())
