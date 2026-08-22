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
`waivers_schema_check` flags it (`approved-at-missing`) — this gate
stays silent on that entry to avoid double-counting, but COUNTS it
and says so in `skipped_reason`, because an entry that cannot be
aged is a hole in this gate's coverage, not a clean result. #519:
that cross-reference used to be false (the schema gate did not flag
it), so 0 of the corpus's 19 entries were ageable and this gate had
never aged a single waiver anywhere while reporting a clean skip.

False-alert guards
==================

  - Silent if no `waivers.json` exists (no open waivers, nothing to
    audit).
  - Silent for waiver entries that have a non-empty `closure_proof`
    field — the waiver is closed, not stale.
  - Silent for entries missing `approved_at` (other gate handles) —
    but counted in `entries_unageable` and named in `skipped_reason`.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)


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
            # #519 — the UNION of both canonical keys, via the shared reader.
            # This was a first-list-wins scan, so a file carrying entries under
            # BOTH keys had one of them silently dropped: whichever key came
            # later in the tuple was never read, and the gate aged only half
            # the file while reporting on all of it. `entries` is retained
            # after them as this gate's own historical third spelling.
            found = _we.entries(data)
            if found:
                return cand, found
            v = data.get("entries")
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
        "entries_unageable": 0,
        "entries_closed": 0,
        "entries_total": 0,
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
    summary["entries_total"] = len(entries)
    if not entries:
        summary["skipped_reason"] = "waivers.json has no entries"
        return findings, summary

    now = now or datetime.now(timezone.utc)

    for e in entries:
        if not isinstance(e, dict):
            continue
        if _is_closed(e):
            summary["entries_closed"] += 1
            continue
        approved = _parse_iso(e.get("approved_at", ""))
        if approved is None:
            # #519 — NOT silence. This gate deferred to `waivers_schema_check`
            # ("already flags it") for entries lacking `approved_at`; that gate
            # did not in fact flag it, so an un-ageable waiver was reported by
            # nobody. Measured over the corpus, 0 of 19 entries carried an
            # `approved_at`, meaning this gate had never aged a single waiver
            # anywhere while reporting a clean skip. The schema gate now warns
            # (`approved-at-missing`); this gate COUNTS the population so its
            # own output states how much of the file it could not audit
            # instead of implying it audited all of it.
            summary["entries_unageable"] += 1
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
        # #519 — say WHICH silence this is. "no entries with parseable
        # approved_at" read identically whether the file held 0 waivers or 19
        # un-ageable ones; only the second is a coverage hole worth knowing
        # about, and it was the universal case.
        if summary["entries_unageable"]:
            summary["skipped_reason"] = (
                f"{summary['entries_unageable']} of "
                f"{summary['entries_total']} open waiver entr"
                f"{'y' if summary['entries_unageable'] == 1 else 'ies'} carr"
                f"{'ies' if summary['entries_unageable'] == 1 else 'y'} no "
                f"parseable `approved_at`, so NONE could be aged — this gate "
                f"audited nothing. `approved_at` is the human approver's "
                f"dated signature and is never stamped automatically, because "
                f"a machine-written approval date would be a self-approval. "
                f"An entry deferred under a machine-generated attestation "
                f"(`waivers` dialect) legitimately carries none and is tracked "
                f"by its `ticket` instead; for the entries that a human did "
                f"approve, `waivers_schema_check` reports the missing "
                f"signature date as `approved-at-missing`."
            )
        else:
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
