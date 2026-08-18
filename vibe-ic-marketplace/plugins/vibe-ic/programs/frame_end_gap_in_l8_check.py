#!/usr/bin/env python3
"""frame_end_gap_in_l8_check.py — LL-2.

For half-duplex command-response ICs, L8_RTL_CONSTANTS.json MUST contain
a `frame_end_gap_*` field (or equivalent inter-byte-gap-timeout constant)
so the spec-to-rtl skill has an authoritative value to emit. Without it,
the agent has to invent a value freely — exactly how the v0118-vendor
<benchmark> bug happened (FRAME_END_GAP=80us instead of ~30us, pushing chip
response outside <half-duplex-tester>'s receive window).

Detection of "half-duplex command-response":
  - L2 has both `tSRS_*` (slave response slot) AND `ibt_us` (inter-byte
    gap) fields, OR
  - L3 has `command_table` with response_payload entries, OR
  - L1 datasheet description matches half-duplex keywords.

When detected, L8 must contain at least one of:
  - frame_end_gap_us
  - frame_end_gap_ticks_<rate>
  - inter_byte_gap_timeout_*
  - bus_idle_frame_end_*

False-alert escape hatches
==========================

  - Silent if L3 declares `frame_end_mechanism` ∈ {`length_field`,
    `trailing_br_pulse`, `master_driven`}. Some protocols delimit
    frames without inter-byte-gap detection.
  - Silent if `waivers.json` has entry id `frame_end_gap_alternative`
    with non-empty rationale.

Severity: ERROR (without --strict still emitted, exit 0 unless strict).
Use `--strict` to fail flow_compliance.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_HALF_DUPLEX_KEYWORDS = re.compile(
    r"\bhalf[-_ ]duplex\b|\bcommand[-_ ]response\b|"
    r"\bsingle[-_ ]wire\b|\bopen[-_ ]drain\b|"
    r"\bid[-_ ]bus\b|\bsdq\b",
    re.IGNORECASE,
)

_FRAME_END_KEYS = re.compile(
    r"frame[_ ]end[_ ]gap|inter[_ ]byte[_ ]gap[_ ]timeout|"
    r"bus[_ ]idle[_ ]frame[_ ]end|cyc[_ ]frame[_ ]end|"
    r"frame[_ ]end[_ ]ticks",
    re.IGNORECASE,
)


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


def _is_half_duplex(project: Path) -> tuple[bool, str]:
    """Return (is_half_duplex, reason)."""
    l2 = _load_layer(project, [
        "phase1/generated_docs/L2*.json",
        "input/docs/L2*.json",
        "L2*.json",
    ]) or {}
    has_tsrs = any(k.lower().startswith("tsrs") for k in l2.keys())
    has_ibt = "ibt_us" in l2 or any(
        "ibt" in k.lower() for k in l2.keys()
    )
    if has_tsrs and has_ibt:
        return True, "L2 has both tSRS and ibt fields"

    l3 = _load_layer(project, [
        "phase1/generated_docs/L3*.json",
        "input/docs/L3*.json",
    ]) or {}
    cmds = l3.get("command_table") or l3.get("commands")
    if isinstance(cmds, list) and any(
        isinstance(c, dict) and (
            c.get("response_payload") or c.get("response_bytes")
            or c.get("rsp_op")
        ) for c in cmds
    ):
        return True, "L3 command_table has response payloads"

    l1 = _load_layer(project, [
        "phase1/generated_docs/L1*.json",
        "input/docs/L1*.json",
    ]) or {}
    desc = json.dumps(l1).lower()
    if _HALF_DUPLEX_KEYWORDS.search(desc):
        return True, "L1 datasheet matches half-duplex keywords"

    return False, "no half-duplex indicators in L1/L2/L3"


def _l3_frame_end_mechanism(project: Path) -> str:
    """Return frame_end_mechanism from L3 if declared (else empty)."""
    l3 = _load_layer(project, [
        "phase1/generated_docs/L3*.json",
        "input/docs/L3*.json",
    ]) or {}
    mech = l3.get("frame_end_mechanism")
    if isinstance(mech, str):
        return mech.strip().lower()
    return ""


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    """Return non-empty rationale text if waivers.json has entry."""
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


def _l8_has_frame_end_constant(project: Path) -> tuple[bool, dict, list[str]]:
    """Return (present, l8_dict, matched_keys)."""
    l8 = _load_layer(project, [
        "phase1/generated_docs/L8_RTL_CONSTANTS.json",
        "input/docs/L8_RTL_CONSTANTS.json",
        "phase1/generated_docs/L8*.json",
    ]) or {}
    if not l8:
        return False, {}, []
    matched = [k for k in l8.keys() if _FRAME_END_KEYS.search(k)]
    return bool(matched), l8, matched


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "is_half_duplex": False,
        "half_duplex_reason": "",
        "l8_present": False,
        "frame_end_keys": [],
    }

    is_hd, reason = _is_half_duplex(project)
    summary["is_half_duplex"] = is_hd
    summary["half_duplex_reason"] = reason

    if not is_hd:
        summary["skipped_reason"] = "non-half-duplex project"
        return findings, summary

    # Escape hatch 1: L3 explicit alternative frame-end mechanism
    mech = _l3_frame_end_mechanism(project)
    summary["frame_end_mechanism_l3"] = mech
    if mech in ("length_field", "trailing_br_pulse", "master_driven"):
        summary["skipped_reason"] = (
            f"L3 declares frame_end_mechanism={mech} (gap-timeout not used)"
        )
        return findings, summary

    # Escape hatch 2: explicit waiver
    waiver = _waiver_rationale(project, "frame_end_gap_alternative")
    summary["waiver_rationale"] = waiver
    if waiver:
        summary["skipped_reason"] = (
            f"waiver frame_end_gap_alternative active: {waiver[:80]}"
        )
        return findings, summary

    present, l8, matched = _l8_has_frame_end_constant(project)
    summary["l8_present"] = bool(l8)
    summary["frame_end_keys"] = matched

    if not l8:
        findings.append(Finding(
            severity="ERROR",
            rule="L8_RTL_CONSTANTS_MISSING",
            message=(
                "Half-duplex IC project has no L8_RTL_CONSTANTS.json. "
                "rtl-constants-gen skill must generate this file with at "
                "minimum frame_end_gap_us derived from L2.ibt_us[1] + "
                "small margin (e.g. 5us)."
            ),
        ))
        return findings, summary

    if not matched:
        findings.append(Finding(
            severity="ERROR",
            rule="L8_FRAME_END_GAP_MISSING",
            message=(
                "Half-duplex IC project's L8_RTL_CONSTANTS.json does not "
                "contain a frame_end_gap_* field. Without it, the "
                "spec-to-rtl skill must invent a frame-end-gap timeout "
                "value when generating RTL — common cause of "
                "response-latency-window bugs (e.g. v0118-vendor <benchmark>: "
                "FRAME_END_GAP=80us instead of ~30us, FAIL on <half-duplex-tester>). "
                "Fix: extend rtl-constants-gen to emit frame_end_gap_us "
                "= L2.ibt_us[1] + 5us margin."
            ),
        ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="frame_end_gap_in_l8_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade ERROR to fail-flow exit code")
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
            "program": "frame_end_gap_in_l8_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== frame_end_gap_in_l8_check ({project.name}) ===")
    print(f"half-duplex: {summary['is_half_duplex']} "
          f"({summary['half_duplex_reason']})")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"L8 present: {summary['l8_present']} "
          f"matched_keys: {summary['frame_end_keys']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — half-duplex project has L8 frame_end_gap constant")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
