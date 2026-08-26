#!/usr/bin/env python3
"""
mcp_execution_verify.py — Deterministic MCP tool execution verifier.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Closes the 3-layer verification loop:
  compliance (text) → program (structure) → MCP tool (execution)

Verifies that specific MCP tools were ACTUALLY CALLED by reading the
`latest_results.jsonl` manifest file that every MCP tool writes after
execution. This is the ONLY way to confirm an agent actually ran an
EDA tool vs. just writing "synthesis completed" in its output.

What it catches:
  1. NOT_FOUND — a required step has no entry in the manifest
  2. FOUND_FAIL — a required step ran but reported status FAIL
  3. STALE — a required step entry is older than --max-age-hours
  4. MANIFEST_MISSING — the manifest file itself does not exist
  5. FOUND_INCONCLUSIVE — a required step ran, the tool reported success, but
     the metrics that prove the work happened were absent, so the manifest
     recorded INCONCLUSIVE instead of PASS (see mcp-eda/src/lib/
     manifest_metrics.mjs). An INCONCLUSIVE step is NOT a pass: this program
     will not report verdict PASS for it and will not exit 0. It is also NOT a
     failure — the step may well have been fine and nobody measured it — so it
     is counted and reported under its own name rather than folded into
     FOUND_FAIL, and the overall verdict becomes INCONCLUSIVE when every
     shortfall is of this kind.

The manifest carries three states — PASS / FAIL / INCONCLUSIVE — and so does
this program's verdict. Any reader that tests `verdict != "FAIL"` to mean
"passed" is wrong: test `verdict == "PASS"`, or use the exit code.

Usage:
    python3 mcp_execution_verify.py \
      --manifest /path/to/latest_results.jsonl \
      --require-steps "synthesis,sta,pnr,gds" \
      --max-age-hours 168 \
      --out-dir /tmp/verify

Exit codes:
    0 = all required steps found with PASS status and within age limit
    1 = one or more steps missing, FAIL, INCONCLUSIVE, or stale

    Only verdict PASS exits 0. INCONCLUSIVE exits 1 exactly as FAIL does — the
    distinction is in the report, so a reader can tell "this is broken" from
    "nobody measured this", but neither of them is permission to proceed.

Generality: works for ANY MCP EDA Server manifest.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Known step names for partial matching
# ---------------------------------------------------------------------------
KNOWN_STEPS = [
    "synthesis", "lint", "simulation", "formal", "pnr", "gds", "sta",
    "dft", "drc", "lvs", "ir_drop", "equiv", "spice", "ic_search",
    "fpga_compile", "fpga_program", "extraction", "sta_mcorner",
    "rtl_audit", "cocotb",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class StepResult:
    step: str
    # FOUND_PASS, FOUND_FAIL, FOUND_INCONCLUSIVE, NOT_FOUND, STALE.
    # Only FOUND_PASS is a pass.
    status: str
    timestamp: Optional[str]
    tool: Optional[str]
    age_hours: Optional[float]
    raw_entry: Optional[dict] = None


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------
def parse_manifest(manifest_path: Path) -> List[dict]:
    """Parse a JSONL manifest file. Returns list of entry dicts."""
    entries: List[dict] = []
    if not manifest_path.exists():
        return entries

    text = manifest_path.read_text(errors="replace").strip()
    if not text:
        return entries

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
        except json.JSONDecodeError:
            continue

    return entries


def step_matches(manifest_step: str, required_step: str) -> bool:
    """Check if a manifest step matches a required step name.

    Case-insensitive. Supports partial match: required "synth" matches
    manifest "synthesis".
    """
    m = manifest_step.lower()
    r = required_step.lower()
    # Exact match
    if m == r:
        return True
    # Partial: required is prefix/substring of manifest step
    if r in m:
        return True
    # Partial: manifest step is prefix/substring of required
    if m in r:
        return True
    return False


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string to datetime."""
    if not ts_str:
        return None
    # Handle various ISO 8601 formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------
def verify_steps(
    entries: List[dict],
    required_steps: List[str],
    max_age_hours: float = 168.0,
    now: Optional[datetime] = None,
) -> List[StepResult]:
    """Verify that each required step has a PASS entry in the manifest.

    For duplicate step entries, uses the latest one (by timestamp).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    results: List[StepResult] = []

    for req_step in required_steps:
        # Find all matching entries for this step
        matching: List[Tuple[datetime, dict]] = []
        for entry in entries:
            manifest_step = entry.get("step", "")
            if step_matches(manifest_step, req_step):
                ts_str = entry.get("timestamp", "")
                ts = parse_timestamp(ts_str)
                if ts is None:
                    # Use epoch as fallback so we can still pick it
                    ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
                matching.append((ts, entry))

        if not matching:
            results.append(StepResult(
                step=req_step,
                status="NOT_FOUND",
                timestamp=None,
                tool=None,
                age_hours=None,
            ))
            continue

        # Use the latest entry
        matching.sort(key=lambda x: x[0], reverse=True)
        latest_ts, latest_entry = matching[0]
        age_hours = (now - latest_ts).total_seconds() / 3600.0

        entry_status = latest_entry.get("status", "").upper()
        ts_str = latest_entry.get("timestamp", "")
        tool = latest_entry.get("tool", None)

        if entry_status == "FAIL":
            results.append(StepResult(
                step=req_step,
                status="FOUND_FAIL",
                timestamp=ts_str,
                tool=tool,
                age_hours=round(age_hours, 1),
                raw_entry=latest_entry,
            ))
        elif entry_status == "INCONCLUSIVE":
            # The tool ran and did not fail, but the manifest could not record
            # PASS because the metrics that prove the work happened were
            # absent. Reported under its own name — not folded into
            # FOUND_FAIL, which would claim the design is bad when what we
            # actually know is that it was never measured.
            results.append(StepResult(
                step=req_step,
                status="FOUND_INCONCLUSIVE",
                timestamp=ts_str,
                tool=tool,
                age_hours=round(age_hours, 1),
                raw_entry=latest_entry,
            ))
        elif age_hours > max_age_hours:
            results.append(StepResult(
                step=req_step,
                status="STALE",
                timestamp=ts_str,
                tool=tool,
                age_hours=round(age_hours, 1),
                raw_entry=latest_entry,
            ))
        elif entry_status == "PASS":
            results.append(StepResult(
                step=req_step,
                status="FOUND_PASS",
                timestamp=ts_str,
                tool=tool,
                age_hours=round(age_hours, 1),
                raw_entry=latest_entry,
            ))
        else:
            # Unknown status — treat as FAIL
            results.append(StepResult(
                step=req_step,
                status="FOUND_FAIL",
                timestamp=ts_str,
                tool=tool,
                age_hours=round(age_hours, 1),
                raw_entry=latest_entry,
            ))

    return results


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------
def build_report(
    manifest_file: str,
    required_steps: List[str],
    step_results: List[StepResult],
) -> dict:
    """Build the output JSON report."""
    found_pass = sum(1 for r in step_results if r.status == "FOUND_PASS")
    found_fail = sum(1 for r in step_results if r.status == "FOUND_FAIL")
    found_inconclusive = sum(
        1 for r in step_results if r.status == "FOUND_INCONCLUSIVE")
    not_found = sum(1 for r in step_results if r.status == "NOT_FOUND")
    stale = sum(1 for r in step_results if r.status == "STALE")

    # Three-state verdict. PASS requires every required step to be FOUND_PASS —
    # an INCONCLUSIVE step can never earn one. When the ONLY thing standing
    # between us and a pass is a step nobody measured, say that, rather than
    # calling the design bad.
    if found_pass == len(required_steps):
        verdict = "PASS"
    elif found_fail or not_found or stale:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "program": "mcp_execution_verify",
        "version": "1.0.0",
        "manifest_file": manifest_file,
        "required_steps": required_steps,
        "results": [
            {
                "step": r.step,
                "status": r.status,
                "timestamp": r.timestamp,
                "tool": r.tool,
                "age_hours": r.age_hours,
            }
            for r in step_results
        ],
        "summary": {
            "total_required": len(required_steps),
            "found_pass": found_pass,
            "found_fail": found_fail,
            "found_inconclusive": found_inconclusive,
            "not_found": not_found,
            "stale": stale,
            "verdict": verdict,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify MCP tools were actually executed via manifest"
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to latest_results.jsonl manifest file",
    )
    parser.add_argument(
        "--require-steps", required=True,
        help="Comma-separated list of step names that must be present and PASS "
             "(a step whose manifest entry is INCONCLUSIVE does not count)",
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=168.0,
        help="Maximum age of manifest entries in hours (default: 168 = 1 week)",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Output directory for JSON report",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    required_steps = [s.strip() for s in args.require_steps.split(",") if s.strip()]

    entries = parse_manifest(manifest_path)
    step_results = verify_steps(entries, required_steps, args.max_age_hours)
    report = build_report(str(manifest_path), required_steps, step_results)

    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "mcp_execution_verify_report.json"
        out_file.write_text(report_json)

    print(report_json)
    # Only PASS exits 0. INCONCLUSIVE is not a pass.
    return 0 if report["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
