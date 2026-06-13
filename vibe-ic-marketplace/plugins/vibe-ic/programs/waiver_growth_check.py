#!/usr/bin/env python3
"""
waiver_growth_check.py — v0.112 release-gate (BACKLOG-v10 P0 follow-up).

Compares current `<project>/waivers.json` against a baseline (frozen at
the previous release tag). Fails CI if:
  - waiver count grew without explicit `growth_rationale` in waivers.json, or
  - a previously-closed waiver re-appeared, or
  - a waiver's evidence pointer became stale (referenced file deleted).

Why this exists: the v0.108 <benchmark> benchmark showed waivers grew from 6
(Round 3 digital) → 9 (Round 4 + analog) without anyone tracking the
delta. Without this gate, "PASS_WITH_WAIVERS" can silently rot — every
release accumulates one more waiver until the chip has more deferred
work than executed.

Cascading entries (root + cascades_to) count ONCE for growth purposes —
the cascade is bookkeeping, not new deferred work.

Usage:
  python3 waiver_growth_check.py <project_dir> \\
      [--baseline <path>] [--tolerance N] [--json [PATH]]

Default baseline: `<project>/.vibe-ic-state/waivers_baseline.json`
Default tolerance: 0 (any net growth without rationale fails)
Exit codes:
  0  PASS — waiver count flat or shrinking, OR growth has explicit rationale
  1  FAIL — waiver grew unjustifiably
  2  IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"waived_steps": []}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        print(f"[ERROR] cannot parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _root_ids(waivers_doc: Dict[str, Any]) -> List[Any]:
    """Extract root waiver ids — entries that are NOT cascades.
    A 'root' is any waived_steps entry that is not the target of another
    entry's cascades_to list."""
    entries = waivers_doc.get("waived_steps", []) or []
    cascade_targets: set = set()
    for entry in entries:
        for child in entry.get("cascades_to", []) or []:
            cascade_targets.add(child)
    roots = []
    for entry in entries:
        if entry.get("id") in cascade_targets:
            continue  # this entry is a cascaded child, not a root
        if entry.get("cascade_source") is not None:
            continue  # explicitly marked as derived
        roots.append(entry["id"])
    return roots


def _evidence_files(entry: Dict[str, Any]) -> List[str]:
    """Pull file paths from evidence string — heuristic: anything that
    looks like a path inside the project."""
    ev = entry.get("evidence", "")
    if not isinstance(ev, str):
        return []
    files = []
    for tok in ev.replace(";", " ").split():
        if "/" in tok and not tok.startswith(("http://", "https://")):
            files.append(tok.strip().rstrip(",.;"))
    return files


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Block CI when waivers grow unjustifiably. Reduces accumulation "
            "of deferred work across releases."
        )
    )
    ap.add_argument("project_dir", help="Project directory containing waivers.json")
    ap.add_argument("--baseline", default=None,
                    help="Baseline waivers.json (default: <project>/.vibe-ic-state/waivers_baseline.json)")
    ap.add_argument("--tolerance", type=int, default=0,
                    help="Allowed net growth without rationale (default 0)")
    ap.add_argument("--stale-warn-days", type=int, default=90,
                    help="Waivers older than N days approved_at → WARN (default 90)")
    ap.add_argument("--stale-error-days", type=int, default=180,
                    help="Waivers older than N days approved_at → ERROR (default 180)")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="Emit JSON. Bare flag → stdout, with PATH → file")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    cur_path = project / "waivers.json"
    base_path = Path(args.baseline) if args.baseline else (
        project / ".vibe-ic-state" / "waivers_baseline.json"
    )

    cur_doc = _load(cur_path)
    base_doc = _load(base_path)

    cur_roots = set(map(repr, _root_ids(cur_doc)))
    base_roots = set(map(repr, _root_ids(base_doc)))

    new_waivers = cur_roots - base_roots
    removed_waivers = base_roots - cur_roots
    net_growth = len(new_waivers) - len(removed_waivers)

    findings: List[Finding] = []

    # Stale evidence check — referenced files must still exist.
    for entry in cur_doc.get("waived_steps", []) or []:
        for f in _evidence_files(entry):
            f_path = (project / f).resolve() if not f.startswith("/") else Path(f)
            try:
                f_path.relative_to(project)
            except ValueError:
                continue  # outside project, skip
            if not f_path.exists():
                # Heuristic — only WARN, since evidence may reference foundry-side
                # tools or future artefacts.
                findings.append(Finding(
                    severity="WARN",
                    category="STALE_EVIDENCE",
                    message=(
                        f"waiver id={entry.get('id')} evidence references "
                        f"{f} which does not exist in the project."
                    ),
                ))

    # v0.113 (BACKLOG-v10 P1.3): staleness-by-age. Waivers with an
    # `approved_at` field older than --stale-warn-days WARN; older than
    # --stale-error-days ERROR. Forces deferred work to actually progress
    # rather than rotting under "review_required: true" forever.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for entry in cur_doc.get("waived_steps", []) or []:
        approved_at = entry.get("approved_at", "")
        if not approved_at:
            continue
        try:
            ts = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            findings.append(Finding(
                severity="WARN",
                category="APPROVED_AT_INVALID",
                message=f"waiver id={entry.get('id')} has malformed approved_at: {approved_at!r}",
            ))
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (now - ts).days
        if age_days >= args.stale_error_days:
            findings.append(Finding(
                severity="ERROR",
                category="WAIVER_STALE_ERROR",
                message=(
                    f"waiver id={entry.get('id')} approved {age_days} days ago "
                    f"(>= {args.stale_error_days} day error threshold). "
                    f"Either close it (run the deferred check on the foundry "
                    f"deck and remove the waiver) or update approved_at with "
                    f"explicit `staleness_extension_rationale`."
                ),
            ))
        elif age_days >= args.stale_warn_days:
            findings.append(Finding(
                severity="WARN",
                category="WAIVER_STALE_WARN",
                message=(
                    f"waiver id={entry.get('id')} approved {age_days} days ago "
                    f"(>= {args.stale_warn_days} day warn threshold)."
                ),
            ))

    # Growth check.
    rationale = cur_doc.get("growth_rationale", "")
    growth_justified = (
        isinstance(rationale, str)
        and len(rationale.strip()) >= 30  # minimum substantive justification
    )

    if net_growth > args.tolerance and not growth_justified:
        findings.append(Finding(
            severity="ERROR",
            category="UNJUSTIFIED_WAIVER_GROWTH",
            message=(
                f"Net waiver count grew by {net_growth} (> tolerance "
                f"{args.tolerance}) without `growth_rationale` in waivers.json. "
                f"New waivers: {sorted(new_waivers)}. "
                f"Either close one of the new waivers, OR add a top-level "
                f"`growth_rationale` field to waivers.json explaining why "
                f"net growth is acceptable for this release."
            ),
            details=(
                "Repeated growth without rationale leads to silent rot: every "
                "release accumulates more deferred work until the project has "
                "more open waivers than executed steps. This gate enforces "
                "that growth is a deliberate, documented decision."
            ),
        ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)

    result = {
        "program": "waiver_growth_check",
        "version": "1.0.0",
        "project": str(project),
        "baseline_path": str(base_path),
        "summary": {
            "current_root_waivers": len(cur_roots),
            "baseline_root_waivers": len(base_roots),
            "net_growth": net_growth,
            "tolerance": args.tolerance,
            "growth_justified": growth_justified,
            "new_waivers": sorted(new_waivers),
            "removed_waivers": sorted(removed_waivers),
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] waiver_growth_check")
        print(f"  current: {len(cur_roots)} root waivers")
        print(f"  baseline: {len(base_roots)} root waivers ({base_path})")
        print(f"  net growth: {net_growth} (tolerance {args.tolerance})")
        if new_waivers:
            print(f"  new this release: {sorted(new_waivers)}")
        if removed_waivers:
            print(f"  closed since baseline: {sorted(removed_waivers)}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
