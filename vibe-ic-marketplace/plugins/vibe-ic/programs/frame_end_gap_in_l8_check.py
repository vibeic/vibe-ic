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

Severity, and WHY IT IS TIERED
==============================

The gate's own remedy is arithmetic on the project's own spec:
``frame_end_gap_us = L2.ibt_us[1] + margin``. That instruction is only
actionable when the project HAS an inter-byte-gap range to derive from.
So the finding's severity is decided by HOW half-duplex was detected:

  - STRUCTURAL detection (L2 carries tSRS + ibt fields, or L3 carries a
    command_table with response payloads) — the derivation input exists,
    the missing constant is a real defect: severity ERROR, and under
    ``--strict`` the process exits 1.
  - KEYWORD-ONLY detection (a half-duplex phrase somewhere in the L1
    free text, with no timing range and no command table anywhere) — the
    gate has a suspicion it cannot substantiate and no value it could tell
    the author to write down. Demanding a constant here is demanding an
    INVENTED number, which is the exact bug this gate exists to prevent.
    Severity WARNING, disclosed in stdout and in the JSON report with
    ``detection_strength: keyword``; exit stays 0 even under ``--strict``.

``summary.detection_strength`` records which tier fired on every run, so a
reader never has to infer the severity from the message.

Use `--strict` to fail flow_compliance. The P0 umbrella supplies it (see
``flow_compliance_check._STRUCTURAL_GATE_BARE_FLAGS``); without it a detected
ERROR is printed and the process still exits 0, which is a gate that cannot
fail for the reason it exists.

Exit codes: 0 PASS / 1 FAIL (strict, structural ERROR) / 2 caller error
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


#: The two tiers of half-duplex detection, and the severity each licenses.
#: `structural` means the project's own spec carries the value the remedy is
#: derived FROM; `keyword` means only free text said so.
STRUCTURAL = "structural"
KEYWORD = "keyword"
NONE = "none"


def _is_half_duplex(project: Path) -> tuple[bool, str, str]:
    """Return (is_half_duplex, reason, detection_strength).

    ``detection_strength`` is one of ``STRUCTURAL`` / ``KEYWORD`` / ``NONE``
    and is what decides finding severity — see the module docstring.
    """
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
        return True, "L2 has both tSRS and ibt fields", STRUCTURAL

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
        return True, "L3 command_table has response payloads", STRUCTURAL

    l1 = _load_layer(project, [
        "phase1/generated_docs/L1*.json",
        "input/docs/L1*.json",
    ]) or {}
    desc = json.dumps(l1).lower()
    if _HALF_DUPLEX_KEYWORDS.search(desc):
        return True, "L1 datasheet matches half-duplex keywords", KEYWORD

    return False, "no half-duplex indicators in L1/L2/L3", NONE


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
        "detection_strength": NONE,
        "l8_present": False,
        "frame_end_keys": [],
    }

    is_hd, reason, strength = _is_half_duplex(project)
    summary["is_half_duplex"] = is_hd
    summary["half_duplex_reason"] = reason
    summary["detection_strength"] = strength
    # The severity the detection tier licenses. A keyword-only match has no
    # ibt range to derive the constant from, so it can only WARN.
    sev = "ERROR" if strength == STRUCTURAL else "WARNING"
    unsubstantiated = (
        " Detected from L1 free text only — the project declares no L2 "
        "inter-byte-gap range and no L3 command table, so this gate cannot "
        "say what the value should be and will not fail the flow on it. "
        "Declare L3.frame_end_mechanism, or emit the L2 ibt range, to make "
        "this decidable."
    ) if strength == KEYWORD else ""

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
            severity=sev,
            rule="L8_RTL_CONSTANTS_MISSING",
            message=(
                "Half-duplex IC project has no L8_RTL_CONSTANTS.json. "
                "rtl-constants-gen skill must generate this file with at "
                "minimum frame_end_gap_us derived from L2.ibt_us[1] + "
                "small margin (e.g. 5us)." + unsubstantiated
            ),
        ))
        return findings, summary

    if not matched:
        findings.append(Finding(
            severity=sev,
            rule="L8_FRAME_END_GAP_MISSING",
            message=(
                "Half-duplex IC project's L8_RTL_CONSTANTS.json does not "
                "contain a frame_end_gap_* field. Without it, the "
                "spec-to-rtl skill must invent a frame-end-gap timeout "
                "value when generating RTL — common cause of "
                "response-latency-window bugs (e.g. v0118-vendor <benchmark>: "
                "FRAME_END_GAP=80us instead of ~30us, FAIL on <half-duplex-tester>). "
                "Fix: extend rtl-constants-gen to emit frame_end_gap_us "
                "= L2.ibt_us[1] + 5us margin." + unsubstantiated
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
    errors = [f for f in findings if f.severity == "ERROR"]
    passed = not errors or not args.strict

    # The verdict LABEL this run reached, decided once and used for the report
    # and the first stdout line. The umbrella records a failing gate's FIRST
    # stdout line as the evidence for the FAIL, so that line has to name the
    # rule rather than repeat the program's own name back at the reader.
    #
    # The label is deliberately NOT the exit code, and every `return` below
    # stays a LITERAL. `gate_skip_routing_check` resolves each terminator's rc
    # statically; returning a variable makes this gate "unanalysable" to it and
    # drops its tracked skip-routing entry to 0 — which reads as that entry
    # having been FIXED while nothing about the skip changed. Measured: with
    # `return rc` the ratchet printed
    # `[RATCHET-FIXED] frame_end_gap_in_l8_check: 1 -> 0`. A defect that
    # vanishes from a ratchet without a behaviour change is worse than the
    # defect, so the exit codes stay literal and that entry stays open.
    if summary.get("skipped_reason"):
        verdict = "SKIP"
    elif errors and args.strict:
        verdict = "FAIL"
    elif errors:
        # Detected, but this caller did not ask for a fail-flow exit. Say so
        # rather than printing an ERROR under a silent rc 0.
        verdict = "ERROR-NOT-ENFORCED"
    elif findings:
        verdict = "WARN"
    else:
        verdict = "PASS"

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "frame_end_gap_in_l8_check",
            "passed": passed,
            "verdict": verdict,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    named = ",".join(f.rule for f in findings)
    print(f"=== frame_end_gap_in_l8_check ({project.name}) — {verdict}"
          f"{': ' + named if named else ''} ===")
    print(f"half-duplex: {summary['is_half_duplex']} "
          f"({summary['half_duplex_reason']}) "
          f"detection={summary['detection_strength']}")
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
    if errors and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
