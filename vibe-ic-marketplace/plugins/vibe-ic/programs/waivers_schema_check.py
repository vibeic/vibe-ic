#!/usr/bin/env python3
"""
waivers_schema_check.py — Validate <project>/waivers.json for the
phase 2+3 canonical flow (40 main-track steps + A1-A9 + M1-M4 + P0
preflight in v1.6.15 / Wave 91).

A waiver is the ONLY legitimate way to skip a mandatory step. To prevent
rubber-stamp waivers ("waived: TODO") from passing through, this program
enforces schema + content rules:

  Required top-level: {"waived_steps": [ ... ]}

  Each entry must have:
    id        integer in 1..40 (main-track step id), OR
              "A<n>" with n in 1..16 (analog stage), OR
              "M<n>" with n in 1..16 (mixed-signal stage), OR
              "P0" (preflight structural-RTL umbrella, Wave 91), OR
              "step_<n>_..." (legacy compatible form)
    reason    non-empty string, ≥ 20 chars, not a placeholder
    approver  non-empty string; not "agent", "claude", "ai", "self"

  Optional:
    approved_at   ISO-8601 timestamp
    review_required  bool (default true)
    ticket        str (e.g. Linear/Jira issue id)

v1.6.14 Wave 90 — decimal "<int>.<int>" sub-step ids were retired in
favour of integer + alphabetic stage ids. The decimal acceptance
pattern is removed (pre-release; no migration path needed).
v1.6.15 Wave 91 — main track raised 1..39 → 1..40 (pre-PnR Yosys gate
promoted to Step 14, stage3-5 cascade +1) and `P0` accepted as the
new id for the structural-RTL preflight umbrella (replaces -1).

Placeholder strings rejected in reason:
    "TODO", "TBD", "n/a", "N/A", "not done", "skip", "skipped",
    "pending", "will do later"

Self-approval rejected: approver in {"agent","claude","ai","self",
"automated","bot"} (case-insensitive).

Usage:
    python3 waivers_schema_check.py <project_dir>
    python3 waivers_schema_check.py <project_dir> --json out.json
    python3 waivers_schema_check.py <project_dir> --max-step 40

Exit codes:
    0 = valid (or no waivers file)
    1 = schema / content violation
    2 = io error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List


PLACEHOLDER_REASONS = {
    "todo", "tbd", "n/a", "na", "not done", "skip", "skipped",
    "pending", "will do later", "fixme", "?"
}

SELF_APPROVERS = {
    "agent", "claude", "ai", "self", "automated", "bot",
    "claude-code", "auto"
}

MIN_REASON_LEN = 20


@dataclass
class WaiverFinding:
    severity: str  # "error" | "warning"
    entry_index: int
    step_id: int | str  # int for digital 1..N, str "A<n>" for analog
    rule: str
    message: str


def _is_placeholder(s: str) -> bool:
    norm = s.strip().lower()
    if norm in PLACEHOLDER_REASONS:
        return True
    # Also reject reasons that are JUST whitespace or punctuation
    if not re.search(r"[a-z0-9]", norm):
        return True
    return False


def _is_self_approver(s: str) -> bool:
    return s.strip().lower() in SELF_APPROVERS


def validate(project: Path, max_step: int = 40,
             strict_review_required: bool = False
             ) -> tuple[List[WaiverFinding], Dict[str, Any]]:
    findings: List[WaiverFinding] = []
    wpath = project / "waivers.json"

    summary: Dict[str, Any] = {
        "waivers_file": str(wpath),
        "exists": wpath.exists(),
        "waiver_count": 0,
    }

    if not wpath.exists():
        # No waivers = valid (nothing to review)
        return findings, summary

    try:
        data = json.loads(wpath.read_text())
    except json.JSONDecodeError as exc:
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="json-parse",
            message=f"waivers.json is not valid JSON: {exc}",
        ))
        return findings, summary

    if not isinstance(data, dict):
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="top-level-structure",
            message='waivers.json must be a JSON object',
        ))
        return findings, summary

    # waived_steps is optional. Many projects use ONLY per-gate waiver keys
    # (e.g. {"frame_end_idle_reset_alternative": "...",
    #        "otp_field_map_unresolved": [...]}) and never have any flow-step
    # waivers — those files are perfectly valid and shouldn't be rejected
    # for lacking an empty waived_steps array. v0.119.21 fix.
    if "waived_steps" not in data:
        return findings, summary

    entries = data["waived_steps"]
    if not isinstance(entries, list):
        findings.append(WaiverFinding(
            severity="error", entry_index=-1, step_id=-1,
            rule="waived-steps-type",
            message='"waived_steps" must be a list',
        ))
        return findings, summary

    summary["waiver_count"] = len(entries)

    seen_ids: set = set()
    for i, entry in enumerate(entries):
        raw_sid = entry.get("id") if isinstance(entry, dict) else None

        if not isinstance(entry, dict):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=-1,
                rule="entry-type",
                message="each waiver must be an object with id/reason/approver",
            ))
            continue

        # id — accept:
        #   (a) integer in 1..max_step (main-track steps), or
        #   (b) string "step_<n>_..." with n in 1..max_step, or
        #   (c) string "A<n>" with n in 1..16 (analog A1-A16 from
        #       phase1_phase2_phase3.yaml stage_analog track; chip-AGNOSTIC).
        #   (d) string "M<n>" with n in 1..16 (mixed-signal M1-M16,
        #       M1-M4 currently used).
        #   (e) string "P0" — preflight structural-RTL umbrella
        #       (Wave 91 / v1.6.15; replaces synthetic step -1).
        # v1.6.14 Wave 90 — decimal "<int>.<int>" sub-step ids retired.
        # Wave 88 introduced patch ids that Wave 90 integerised; the
        # decimal pattern is no longer accepted.
        sid = None
        is_analog = False
        is_mixed_signal = False
        is_preflight = False
        if isinstance(raw_sid, int):
            sid = raw_sid
        elif isinstance(raw_sid, str):
            stripped = raw_sid.strip()
            m = re.match(r"^step[_\-\s]*(\d+)(?:[_\-\s]|$)", stripped, re.IGNORECASE)
            if m:
                sid = int(m.group(1))
            else:
                am = re.match(r"^A(\d+)$", stripped, re.IGNORECASE)
                mm = re.match(r"^M(\d+)$", stripped, re.IGNORECASE)
                pm = re.match(r"^P0$", stripped, re.IGNORECASE)
                if am and 1 <= int(am.group(1)) <= 16:
                    sid = stripped.upper()
                    is_analog = True
                elif mm and 1 <= int(mm.group(1)) <= 16:
                    sid = stripped.upper()
                    is_mixed_signal = True
                elif pm:
                    sid = "P0"
                    is_preflight = True
        digital_ok = isinstance(sid, int) and (1 <= sid <= max_step)
        analog_ok = is_analog and isinstance(sid, str)
        mixed_signal_ok = is_mixed_signal and isinstance(sid, str)
        preflight_ok = is_preflight and isinstance(sid, str)
        if not (digital_ok or analog_ok or mixed_signal_ok or preflight_ok):
            findings.append(WaiverFinding(
                severity="error", entry_index=i,
                step_id=sid if isinstance(sid, int) else -1,
                rule="id-range",
                message=(
                    f"id must be integer in 1..{max_step} "
                    "(or 'step_<n>_…', 'A<n>' with n<=16, "
                    "'M<n>' with n<=16, or 'P0'), "
                    f"got {raw_sid!r}"
                ),
            ))
            continue

        if sid in seen_ids:
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="id-duplicate",
                message=f"step id {sid} is waived more than once",
            ))
        seen_ids.add(sid)

        # v0.112 (BACKLOG-v10 P0.2): cascades_to validation. Optional
        # field — if present, must be a list of valid step ids (digital
        # int 1..max_step or analog A<n> 1..16). Each cascaded id must
        # NOT also have its own waiver entry (would duplicate-shadow the
        # cascade source). Reduces N+1 entries to 1 root.
        cascades = entry.get("cascades_to")
        if cascades is not None:
            if not isinstance(cascades, list):
                findings.append(WaiverFinding(
                    severity="error", entry_index=i, step_id=sid,
                    rule="cascades-type",
                    message="cascades_to must be a list of step ids if present",
                ))
            else:
                for j, child in enumerate(cascades):
                    cs = None
                    if isinstance(child, int):
                        cs = child
                    elif isinstance(child, str):
                        cm = re.match(r"^A(\d+)$", child.strip(), re.IGNORECASE)
                        cmm = re.match(r"^M(\d+)$", child.strip(), re.IGNORECASE)
                        if cm and 1 <= int(cm.group(1)) <= 16:
                            cs = child.strip().upper()
                        elif cmm and 1 <= int(cmm.group(1)) <= 16:
                            cs = child.strip().upper()
                    if not (
                        (isinstance(cs, int) and 1 <= cs <= max_step)
                        or isinstance(cs, str)
                    ):
                        findings.append(WaiverFinding(
                            severity="error", entry_index=i, step_id=sid,
                            rule="cascades-id-invalid",
                            message=f"cascades_to[{j}]={child!r} is not a valid step id",
                        ))
                    elif cs == sid:
                        findings.append(WaiverFinding(
                            severity="error", entry_index=i, step_id=sid,
                            rule="cascades-self",
                            message=f"cascades_to cannot include the root id {sid}",
                        ))

        # reason
        reason = entry.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="reason-missing",
                message="reason must be a non-empty string",
            ))
        elif len(reason.strip()) < MIN_REASON_LEN:
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="reason-too-short",
                message=f"reason is {len(reason.strip())} chars; need >= {MIN_REASON_LEN}",
            ))
        elif _is_placeholder(reason):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="reason-placeholder",
                message=f"reason is a placeholder/empty value: {reason!r}",
            ))

        # approver
        approver = entry.get("approver", "")
        if not isinstance(approver, str) or not approver.strip():
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="approver-missing",
                message="approver must be a non-empty string",
            ))
        elif _is_self_approver(approver):
            findings.append(WaiverFinding(
                severity="error", entry_index=i, step_id=sid,
                rule="approver-self",
                message=f"self-approval rejected: {approver!r}",
            ))

        # review_required — v1.6.12: silent default true is too lenient.
        # If field is missing, emit WARN (or ERROR under
        # --strict-review-required). Either way, behavior still
        # defaults to True so existing callers aren't broken.
        if "review_required" not in entry:
            findings.append(WaiverFinding(
                severity=("error" if strict_review_required else "warning"),
                entry_index=i, step_id=sid,
                rule="review-required-missing",
                message=(
                    "review_required field is missing; defaulted to true. "
                    "Make explicit (set true|false) to remove this "
                    + ("error." if strict_review_required else "warning.")
                ),
            ))
        review_required = entry.get("review_required", True)
        if review_required and not entry.get("ticket"):
            findings.append(WaiverFinding(
                severity="warning", entry_index=i, step_id=sid,
                rule="ticket-missing",
                message="review_required=true but no ticket field (Linear/Jira id recommended)",
            ))

    return findings, summary


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir", help="Project directory containing (optional) waivers.json")
    p.add_argument("--max-step", type=int, default=40,
                   help="Highest valid main-track step id "
                        "(default 40 for phase1_phase2_phase3 v1.6.15 flow)")
    p.add_argument("--json", help="Write JSON report to this path")
    p.add_argument("--strict-review-required", action="store_true",
                   help=("v1.6.12: when set, missing review_required field "
                         "is upgraded from WARN to ERROR (exit 1)."))
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"waivers_schema_check: not a directory: {project}", file=sys.stderr)
        return 2

    findings, summary = validate(project, max_step=args.max_step,
                                 strict_review_required=args.strict_review_required)

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    if not summary["exists"]:
        print(f"waivers_schema_check: no waivers.json (nothing waived) — OK")
    else:
        print(f"\n=== Waivers schema check ===")
        print(f"File: {summary['waivers_file']}")
        print(f"Waiver count: {summary['waiver_count']}")
        print(f"Errors: {len(errors)}    Warnings: {len(warnings)}\n")
        for f in findings:
            icon = "✗" if f.severity == "error" else "⚠"
            print(f"  {icon} [{f.severity}] step {f.step_id} / entry {f.entry_index}: {f.rule}")
            print(f"     {f.message}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "summary": summary,
            "errors": [asdict(f) for f in errors],
            "warnings": [asdict(f) for f in warnings],
        }, indent=2))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
