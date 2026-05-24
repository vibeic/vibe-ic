#!/usr/bin/env python3
"""l8_frame_end_gap_derivation_check.py — LL-3.

Companion to LL-2. When L8 has a `frame_end_gap_*` field, verify the
value is in the legal derivation range from L2 spec:

    L2.ibt_us[1] + small_margin <= frame_end_gap_us <= 2 * L2.ibt_us[1]

A value below the lower bound risks classifying a real IBT as
end-of-frame (chip dispatches mid-frame).

A value above the upper bound risks chip response missing the master's
receive window (the v0118-noris bug: 80us > 2*22us = 44us → FAIL).

False-alert escape hatches
==========================

  - L2 may declare `frame_end_gap_max_factor` (default 2.0) to allow
    wider gap if the protocol genuinely needs one.
  - L2 may declare `frame_end_gap_min_margin_us` (default 3us) to set a
    different lower-bound margin.
  - waivers.json entry `frame_end_gap_derivation_override` skips the
    gate when present with non-empty rationale.

Severity: ERROR (with `--strict` for fail-flow exit).

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import read_text as _read

# Plugin DEFAULTS — overridable per-project via L2 fields:
#   frame_end_gap_min_margin_us  → SAFETY_MARGIN_US
#   frame_end_gap_max_factor     → MAX_FACTOR
DEFAULT_SAFETY_MARGIN_US = 3.0
DEFAULT_MAX_FACTOR = 2.0


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    for cand in (project / "waivers.json", *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or []
        )
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and rat.strip():
                    return rat.strip()
    return ""


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


def _load_layer(project: Path, glob_patterns: list[str]) -> dict | None:
    for pattern in glob_patterns:
        for cand in project.glob(pattern):
            try:
                data = json.loads(_read(cand) or "{}")
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    return None


def _frame_end_us_from_l8(l8: dict) -> tuple[float | None, str]:
    """Try to extract frame_end_gap value in microseconds from L8."""
    # Direct us field
    for k, v in l8.items():
        kl = k.lower()
        if "frame_end_gap" in kl and "us" in kl and isinstance(v, (int, float)):
            return float(v), k
        if "inter_byte_gap_timeout" in kl and "us" in kl and isinstance(v, (int, float)):
            return float(v), k

    # Tick field with rate hint in name
    for k, v in l8.items():
        kl = k.lower()
        if not isinstance(v, (int, float)):
            continue
        if "frame_end" not in kl and "inter_byte_gap_timeout" not in kl:
            continue
        if "ticks" not in kl:
            continue
        # Parse rate from key (e.g. ticks_5MHz / ticks_at_50MHz)
        for rate_str, rate_mhz in (("50mhz", 50), ("5mhz", 5),
                                   ("100mhz", 100), ("25mhz", 25)):
            if rate_str in kl:
                return float(v) / rate_mhz, k  # ticks → us
    return None, ""


def _ibt_max_us(l2: dict) -> float | None:
    ibt = l2.get("ibt_us")
    if isinstance(ibt, list) and len(ibt) >= 2:
        try:
            return float(ibt[1])
        except (TypeError, ValueError):
            return None
    if isinstance(ibt, (int, float)):
        return float(ibt)
    # try ibt_max_us
    for k, v in l2.items():
        kl = k.lower()
        if "ibt" in kl and "max" in kl and isinstance(v, (int, float)):
            return float(v)
    return None


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "ibt_max_us": None,
        "frame_end_us": None,
        "frame_end_key": "",
        "lower_bound_us": None,
        "upper_bound_us": None,
        "skipped_reason": "",
    }

    l8 = _load_layer(project, [
        "phase1/generated_docs/L8_RTL_CONSTANTS.json",
        "input/docs/L8_RTL_CONSTANTS.json",
        "phase1/generated_docs/L8*.json",
    ])
    if not l8:
        summary["skipped_reason"] = "no L8_RTL_CONSTANTS.json"
        return findings, summary

    fe_us, fe_key = _frame_end_us_from_l8(l8)
    summary["frame_end_us"] = fe_us
    summary["frame_end_key"] = fe_key
    if fe_us is None:
        summary["skipped_reason"] = (
            "no frame_end_gap_* field in L8 (LL-2 reports this)"
        )
        return findings, summary

    l2 = _load_layer(project, [
        "phase1/generated_docs/L2_TIMING_WAVEFORM.json",
        "phase1/generated_docs/L2*.json",
        "input/docs/L2*.json",
    ])
    if not l2:
        summary["skipped_reason"] = "no L2 timing spec to derive bounds"
        return findings, summary

    ibt_max = _ibt_max_us(l2)
    summary["ibt_max_us"] = ibt_max
    if ibt_max is None:
        summary["skipped_reason"] = "L2 has no ibt_us[1] / ibt_max_us"
        return findings, summary

    # Escape hatch: explicit waiver
    waiver = _waiver_rationale(project, "frame_end_gap_derivation_override")
    summary["waiver_rationale"] = waiver
    if waiver:
        summary["skipped_reason"] = (
            f"waiver frame_end_gap_derivation_override: {waiver[:80]}"
        )
        return findings, summary

    # Spec-driven overrides — let L2 dictate bounds when project knows
    # better than plugin defaults
    margin = l2.get("frame_end_gap_min_margin_us")
    if not isinstance(margin, (int, float)):
        margin = DEFAULT_SAFETY_MARGIN_US
    factor = l2.get("frame_end_gap_max_factor")
    if not isinstance(factor, (int, float)):
        factor = DEFAULT_MAX_FACTOR
    summary["margin_us"] = margin
    summary["max_factor"] = factor

    lower = ibt_max + margin
    upper = ibt_max * factor
    summary["lower_bound_us"] = lower
    summary["upper_bound_us"] = upper

    if fe_us < lower:
        findings.append(Finding(
            severity="ERROR",
            rule="L8_FRAME_END_GAP_TOO_TIGHT",
            message=(
                f"L8.{fe_key}={fe_us}us is below ibt_us[1] + safety "
                f"margin ({lower}us, margin={margin}us). A real "
                f"inter-byte IBT may exceed this gap and trigger a false "
                f"end-of-frame mid-command. Override via L2."
                f"frame_end_gap_min_margin_us if intentional."
            ),
        ))
    elif fe_us > upper:
        findings.append(Finding(
            severity="ERROR",
            rule="L8_FRAME_END_GAP_TOO_WIDE",
            message=(
                f"L8.{fe_key}={fe_us}us exceeds {factor}*ibt_us[1] "
                f"({upper}us). Wide gap delays chip response past the "
                f"half-duplex master's receive window — exact failure "
                f"mode of v0118-noris <benchmark> (set 80us, master expected "
                f"~30us). Recommended: ibt_us[1] + {margin}us = "
                f"{ibt_max + margin}us. Override via L2."
                f"frame_end_gap_max_factor if master genuinely tolerates."
            ),
        ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="l8_frame_end_gap_derivation_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    passed = not any(f.severity == "ERROR" for f in findings) or not args.strict

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "l8_frame_end_gap_derivation_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== l8_frame_end_gap_derivation_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"L2.ibt_us[1] = {summary['ibt_max_us']}us  legal range: "
          f"[{summary['lower_bound_us']}, {summary['upper_bound_us']}]us")
    print(f"L8.{summary['frame_end_key']} = "
          f"{summary['frame_end_us']}us")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — L8 frame_end_gap derived from L2 within legal range")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
