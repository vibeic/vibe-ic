#!/usr/bin/env python3
"""rtl_precheck_gate.py — aggregate every RTL static auditor into a
single pass/fail gate. Intended to be called BEFORE any SOF/GDS burn
so a developer can't ship a known-buggy RTL tree just because they
didn't think to run each auditor individually.

# Motivation (v0.66)

Across v0.63 and v0.64 the plugin accumulated six static-pattern
auditors:

  • `tristate_self_rx_mask_check`        (v0.63)
  • `pulse_decoder_edge_check`           (v0.63)
  • `packet_length_check_present`        (v0.63)
  • `otp_write_lock_gate_check`          (v0.63)
  • `l12_sequence_implementation_check`  (v0.63; optional L12 JSON)
  • `timer_freeze_after_state_check`     (v0.64)

Each one catches a different class of RTL anti-pattern that has been
observed to produce silicon bugs (tristate self-echo, missed edge
classification, dispatch-without-length-check, unlocked OTP write,
un-implemented L12 sequence, counter-never-freezes-after-state). Each
one is a standalone `--rtl-dir`-taking tool.

The **v0.66 regression** that motivated bundling them: the user's
FPGA showed periodic wake pulses continuing forever after `0x74`.
`timer_freeze_after_state_check` would have flagged the offending
`wake_ctrl.v` at the edit-time, BUT it was never run as part of the
burn flow — so the bug reached silicon. Having the auditor without
running it = having no auditor.

This gate fixes that by providing a single invocation the burn flow
calls to ensure all auditors PASS before any programmer writes an SOF
to a real board. Individual auditors are still directly callable for
local development; this gate is the pre-burn checkpoint.

# CLI

    python3 rtl_precheck_gate.py \
        --rtl-dir /path/to/rtl \
        [--l12-json /path/to/L12_BEHAVIORAL_SEQUENCES.json] \
        [--skip tristate_self_rx_mask_check,...] \
        [--json out.json]

Exit codes
----------
    0 — every enabled auditor PASSed
    1 — at least one auditor FAILed; aggregated report on stdout
    2 — argument / IO error (rtl-dir missing, etc.)

# For the FPGA burn tool

Call from `mcp-eda/src/devices/terasic-de10lite/driver.py` in
`--mode program`:

    # Pseudocode
    gate = run([
        "python3", "rtl_precheck_gate.py",
        "--rtl-dir", args.rtl_dir,
        "--l12-json", args.l12_json or "",
        "--json", "/tmp/precheck.json",
    ])
    if gate.returncode != 0 and not args.allow_known_bugs:
        return {"success": False, "error": "rtl_precheck_gate FAIL",
                "findings": read_json("/tmp/precheck.json"), ...}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Auditor registry. Order = execution order. Each auditor takes --rtl-dir
# (the canonical interface); `extra_args_key` picks optional arg from CLI
# (`--l12-json`) and appends it when calling.
# ---------------------------------------------------------------------------
@dataclass
class Auditor:
    name: str
    script: str
    extra_args_key: Optional[str] = None   # None or "l12_json"
    required: bool = True                  # if False, OK to skip on missing input


_AUDITORS: List[Auditor] = [
    Auditor("tristate_self_rx_mask_check",       "tristate_self_rx_mask_check.py"),
    Auditor("pulse_decoder_edge_check",          "pulse_decoder_edge_check.py"),
    Auditor("packet_length_check_present",       "packet_length_check_present.py"),
    Auditor("otp_write_lock_gate_check",         "otp_write_lock_gate_check.py"),
    Auditor("l12_sequence_implementation_check", "l12_sequence_implementation_check.py",
            extra_args_key="l12_json", required=False),
    Auditor("timer_freeze_after_state_check",    "timer_freeze_after_state_check.py"),
    # reset-discipline: ERROR-only by default (sync/async-mode + polarity
    # contradictions on the same reset signal). incomplete-reset /
    # flop-without-reset stay WARN so the gate does not fail legit unreset
    # pipeline regs. Verified 0-ERROR across the spm/sha256/subservient RTL.
    Auditor("reset_discipline_check",            "reset_discipline_check.py"),
]


@dataclass
class AuditorResult:
    name: str
    passed: bool
    exit_code: int
    skipped: bool = False
    skip_reason: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core run loop
# ---------------------------------------------------------------------------
def _run_one(
    auditor: Auditor,
    scripts_dir: Path,
    rtl_dir: Path,
    extra_args: Dict[str, Optional[str]],
    timeout_s: int = 120,
) -> AuditorResult:
    script_path = scripts_dir / auditor.script
    if not script_path.is_file():
        return AuditorResult(
            name=auditor.name, passed=False, exit_code=-1,
            stderr_tail=f"script not found: {script_path}",
        )

    argv = ["python3", str(script_path), "--rtl-dir", str(rtl_dir)]
    if auditor.extra_args_key:
        val = extra_args.get(auditor.extra_args_key)
        if val:
            argv += [f"--{auditor.extra_args_key.replace('_', '-')}", val]
        elif not auditor.required:
            return AuditorResult(
                name=auditor.name, passed=True, exit_code=0,
                skipped=True,
                skip_reason=f"no --{auditor.extra_args_key.replace('_', '-')} supplied",
            )

    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return AuditorResult(
            name=auditor.name, passed=False, exit_code=-2,
            stderr_tail=f"timeout after {timeout_s}s",
        )
    return AuditorResult(
        name=auditor.name,
        passed=(r.returncode == 0),
        exit_code=r.returncode,
        stdout_tail=r.stdout[-1500:],
        stderr_tail=r.stderr[-800:],
    )


def run_gate(
    rtl_dir: Path,
    scripts_dir: Path,
    l12_json: Optional[str] = None,
    skip: Optional[List[str]] = None,
) -> Dict:
    """Run every non-skipped auditor. Returns a dict suitable for
    `json.dump`ing."""
    if not rtl_dir.is_dir():
        raise FileNotFoundError(f"rtl-dir not a directory: {rtl_dir}")
    skip_set = set(skip or [])
    extra = {"l12_json": l12_json}
    results: List[AuditorResult] = []
    for a in _AUDITORS:
        if a.name in skip_set:
            results.append(AuditorResult(
                name=a.name, passed=True, exit_code=0,
                skipped=True, skip_reason="--skip",
            ))
            continue
        results.append(_run_one(a, scripts_dir, rtl_dir, extra))

    n_total = len(results)
    n_pass = sum(1 for r in results if r.passed and not r.skipped)
    n_fail = sum(1 for r in results if not r.passed)
    n_skip = sum(1 for r in results if r.skipped)
    overall = n_fail == 0

    return {
        "program": "rtl_precheck_gate",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            "auditors_total": n_total,
            "passed": n_pass,
            "failed": n_fail,
            "skipped": n_skip,
            "overall_pass": overall,
        },
        "auditors": [r.as_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pre-burn RTL gate — aggregates every static auditor.",
    )
    ap.add_argument("--rtl-dir", required=True,
                    help="Directory of .v / .sv files to scan recursively")
    ap.add_argument("--l12-json",
                    help="Path to L12_BEHAVIORAL_SEQUENCES.json "
                         "(forwarded to l12_sequence_implementation_check; "
                         "that auditor is skipped when absent)")
    ap.add_argument("--skip",
                    help="Comma-separated auditor names to skip. "
                         f"Available: {','.join(a.name for a in _AUDITORS)}")
    ap.add_argument("--json",
                    help="Optional machine-readable report path")
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    if not rtl_dir.is_dir():
        print(f"ERROR: --rtl-dir not a directory: {rtl_dir}", file=sys.stderr)
        return 2

    scripts_dir = Path(__file__).resolve().parent
    skip_list = [s.strip() for s in (args.skip or "").split(",") if s.strip()]
    unknown = [s for s in skip_list
               if s not in {a.name for a in _AUDITORS}]
    if unknown:
        print(f"ERROR: unknown --skip auditor name(s): {unknown}",
              file=sys.stderr)
        return 2

    report = run_gate(
        rtl_dir=rtl_dir, scripts_dir=scripts_dir,
        l12_json=args.l12_json, skip=skip_list,
    )
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return 0 if report["summary"]["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
