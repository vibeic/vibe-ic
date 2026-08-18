#!/usr/bin/env python3
"""protocol_ip_simulation_required_check.py — BACKLOG-v11 P2.1.

Workflow gate sitting between Step 5 (lint / formal / sim) and Step 6
(FPGA compile + on-board test). For protocol-IP designs (any chip
that declares byte-level RX/TX framing in L8/L9), require that a full-
stack cocotb / Verilator simulation has run AND PASSed AND is fresher
than every RTL file before allowing FPGA-compile / on-board test work
to count toward Phase 2+3 PASS.

Motivation
==========

v0.116 <benchmark> went straight from `spec-to-rtl` to `eda_fpga_compile`
+ on-board <half-duplex-tester> testing without first running a synthesisable
cocotb / Verilator full-stack TB driving the host BR + bytes through
the chip top. Each on-board iteration cost ~60 seconds (compile +
burn + test); each sim iteration would cost ~5–30 seconds. The
12-bug debug spent multiple hours of iteration time that simulation
could have collapsed to minutes.

This gate forces the simulation step to actually happen and produce
a positive result before FPGA compile is treated as a meaningful
verification step.

Gate behaviour
==============

Trigger conditions (gate considers the design "protocol-IP-class"):
  - L9_INTEGRATION_SPEC.json declares any of:
      protocol_layer != "none"
      cmd_response_cycle == true
      response_required == true
  - OR L3_CMD_PROTOCOL.json declares an opcode_table / command_protocol
  - OR L8_RTL_CONSTANTS.json declares any of:
      inter_byte_time_ticks / tsrs_min_ticks / frame_end_gap_ticks /
      ibt_ticks / bus_turnaround_ticks

For protocol-IP-class designs, demand:
  1. `sim_full_stack/results.json` exists with `verdict: PASS`.
     Acceptable alternate paths:
       - sim/results.json
       - sim_unit/results.json (only if marked `full_stack: true`)
       - reports/sim_full_stack.json
  2. The sim results file's mtime is newer than EVERY `*.v` / `*.sv`
     file's mtime under the project (excluding build dirs). Otherwise
     the sim ran on stale RTL.
  3. The sim transcript / coverage record (`sim_full_stack/transcript.log`
     or equivalent) demonstrates at least one full host BR + opcode +
     CRC sequence — heuristic: contains tokens like
     "BR_PULSE", "rx_byte", "TX_RESP", "crc_match" (case-insensitive).

False-alert guards
==================

  - Silent if L9 declares `protocol_layer: none` (analog harness,
    free-running counter, non-protocol IP).
  - Silent if `waivers.json` contains an entry with
    `id: "P21_skip_stack_sim"` and a non-empty `rationale`. This is
    an explicit engineer escape — must be reviewed at tapeout.
  - Silent if no FPGA artefacts exist (no `output_files/*.sof`,
    no `*.bit`, no on-board BIST log) — the design has not entered
    Step 6 territory yet, so this gate is not yet applicable.
  - Silent for non-protocol designs.

Severity: ERROR (workflow-level skip is silent failure to verify).

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_rtl_files as _rtl_files
from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_PROTOCOL_TOKENS = (
    "ibt_ticks", "inter_byte_time_ticks", "tsrs_min_ticks",
    "frame_end_gap_ticks", "tx_ibt_ticks", "bus_turnaround_ticks",
    "cmd_response_cycle", "response_required", "opcode_table",
    "command_protocol", "byte_framing", "byte_stream_protocol",
)


def _is_protocol_ip(project: Path) -> tuple[bool, str]:
    """Return (is_protocol, evidence_string)."""
    # Explicit L9 protocol_layer field
    for f in (
        list(project.glob("phase1/generated_docs/L9*.json"))
        + list(project.glob("L9*.json"))
        + list(project.glob("input/docs/L9*.json"))
    ):
        try:
            data = json.loads(_read(f) or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            pl = data.get("protocol_layer")
            if isinstance(pl, str) and pl.lower() == "none":
                return False, "L9.protocol_layer=none"
            if isinstance(pl, str) and pl.lower() not in ("", "auto"):
                return True, f"L9.protocol_layer={pl}"

    # Token scan over L1-L23
    for f in (
        list(project.glob("phase1/generated_docs/L*.json"))
        + list(project.glob("L*.json"))
        + list(project.glob("input/docs/L*.json"))
    ):
        text = _read(f).lower()
        for tok in _PROTOCOL_TOKENS:
            if tok in text:
                return True, f"{f.name}:{tok}"
    return False, ""


def _waiver_skip(project: Path) -> str:
    for f in list(project.glob("waivers.json")) + list(
        project.glob("**/waivers.json")
    ):
        try:
            data = json.loads(_read(f) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else data.get("waivers", [])
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == "P21_skip_stack_sim":
                rationale = e.get("rationale") or e.get("reason") or ""
                if isinstance(rationale, str) and rationale.strip():
                    return rationale
    return ""


def _has_fpga_artefacts(project: Path) -> bool:
    """True if any FPGA build artefact suggests Step 6 has been entered."""
    patterns = ("**/output_files/*.sof", "**/*.bit", "**/*.bof",
                "**/output_files/*.rbf", "**/bist_*.log",
                "**/onboard_*.log")
    for pat in patterns:
        for f in project.glob(pat):
            if f.is_file():
                return True
    return False


_FULL_STACK_RESULTS = (
    "phase2/stage1/sim_full_stack/results.json",
    "phase2/stage1/sim/full_stack_results.json",
    "phase2/stage1/sim/results.json",
    "reports/sim_full_stack.json",
)


def _load_sim_results(project: Path) -> tuple[Path | None, dict]:
    for rel in _FULL_STACK_RESULTS:
        f = project / rel
        if f.exists():
            try:
                return f, json.loads(_read(f) or "{}")
            except json.JSONDecodeError:
                continue
    # Also try sim_unit/results.json IF it declares full_stack:true
    for rel in ("sim_unit/results.json",):
        f = project / rel
        if f.exists():
            try:
                data = json.loads(_read(f) or "{}")
                if isinstance(data, dict) and data.get("full_stack") is True:
                    return f, data
            except json.JSONDecodeError:
                continue
    return None, {}


def _newest_rtl_mtime(rtl_files: list[Path]) -> float:
    best = 0.0
    for f in rtl_files:
        try:
            best = max(best, f.stat().st_mtime)
        except OSError:
            continue
    return best


_TRANSCRIPT_TOKENS_RE = re.compile(
    r"\b(BR_PULSE|rx_byte|TX_RESP|crc_match|cmd_pass|opcode|tx_done)\b",
    re.IGNORECASE,
)


_COMMENT_LINE_RE = re.compile(r"^\s*(?://|#)")


def _transcript_has_full_sequence(project: Path,
                                  results_file: Path) -> bool:
    """True if a transcript / log near the results file shows evidence
    of a full host→chip→host sequence: ≥3 distinct tokens, found on
    ≥3 distinct non-comment lines.

    v0.118-stable hardening:
      - threshold raised 2 → 3 distinct tokens (was too low: any TB
        with `cmd_pass` + `tx_done` printf for stub coverage trivially
        matched)
      - comment-only lines (`//` or `#` prefix) are stripped before
        matching, so `// stub for tx_done / cmd_pass — TODO` no longer
        counts as evidence
      - tokens must appear on ≥3 distinct lines (one printf line dumping
        all tokens at once doesn't count as a sequence)
    """
    candidates: set[Path] = set()
    for p in (results_file.with_suffix(".log"),
              results_file.parent / "transcript.log",
              results_file.parent / "sim.log",
              results_file.parent / "results.log"):
        candidates.add(p)
    for sib in results_file.parent.glob("*.log"):
        candidates.add(sib)
    for c in candidates:
        if not c.exists():
            continue
        text = _read(c)
        distinct_tokens: set[str] = set()
        hit_lines: set[int] = set()
        for ln_no, line in enumerate(text.splitlines(), start=1):
            if _COMMENT_LINE_RE.match(line):
                continue
            for m in _TRANSCRIPT_TOKENS_RE.finditer(line):
                distinct_tokens.add(m.group(1).lower())
                hit_lines.add(ln_no)
        if len(distinct_tokens) >= 3 and len(hit_lines) >= 3:
            return True
    return False


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "is_protocol_ip": False,
        "trigger_evidence": "",
        "waiver_rationale": "",
        "fpga_artefacts_present": False,
        "sim_results_path": None,
        "sim_verdict": None,
        "sim_results_mtime": None,
        "newest_rtl_mtime": None,
        "skipped_reason": "",
    }

    is_proto, evidence = _is_protocol_ip(project)
    summary["is_protocol_ip"] = is_proto
    summary["trigger_evidence"] = evidence
    if not is_proto:
        summary["skipped_reason"] = "non-protocol design"
        return findings, summary

    rationale = _waiver_skip(project)
    summary["waiver_rationale"] = rationale
    if rationale:
        summary["skipped_reason"] = (
            f"explicit waiver P21_skip_stack_sim: {rationale[:80]}"
        )
        return findings, summary

    has_fpga = _has_fpga_artefacts(project)
    summary["fpga_artefacts_present"] = has_fpga
    if not has_fpga:
        summary["skipped_reason"] = (
            "no FPGA artefacts detected — Step 6 not yet entered"
        )
        return findings, summary

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files"
        return findings, summary

    results_file, results = _load_sim_results(project)
    if results_file is None:
        findings.append(Finding(
            severity="ERROR",
            rule="FULL_STACK_SIM_MISSING",
            message=(
                "Protocol-IP design has FPGA artefacts but no full-stack "
                "simulation results found at any of: "
                + ", ".join(_FULL_STACK_RESULTS)
                + ". Run a cocotb / Verilator TB that drives a complete "
                "host BR + opcode + CRC sequence and writes "
                "sim_full_stack/results.json before claiming FPGA-step "
                "verification. v0.116 <benchmark> lesson: skipping sim cost "
                "hours of FPGA iteration time."
            ),
        ))
        return findings, summary

    summary["sim_results_path"] = str(results_file.relative_to(project))
    verdict = (results or {}).get("verdict")
    summary["sim_verdict"] = verdict
    if verdict not in ("PASS", "pass"):
        findings.append(Finding(
            severity="ERROR",
            rule="FULL_STACK_SIM_NOT_PASS",
            message=(
                f"Full-stack sim results "
                f"({results_file.relative_to(project)}) verdict="
                f"{verdict!r}, expected 'PASS' before FPGA-step "
                f"verification can count."
            ),
            file=str(results_file.relative_to(project)),
        ))

    sim_mtime = results_file.stat().st_mtime
    rtl_mtime = _newest_rtl_mtime(rtl_files)
    summary["sim_results_mtime"] = sim_mtime
    summary["newest_rtl_mtime"] = rtl_mtime
    if sim_mtime < rtl_mtime:
        findings.append(Finding(
            severity="ERROR",
            rule="FULL_STACK_SIM_STALE",
            message=(
                f"sim results ({results_file.relative_to(project)}) "
                f"mtime is older than at least one RTL file. The sim "
                f"ran on stale RTL — re-run before treating Step 6 as "
                f"verified."
            ),
            file=str(results_file.relative_to(project)),
        ))

    if not _transcript_has_full_sequence(project, results_file):
        findings.append(Finding(
            severity="ERROR",
            rule="FULL_STACK_SIM_TRIVIAL",
            message=(
                "sim_full_stack transcript does not show evidence of a "
                "full host→chip→host sequence (looked for tokens "
                "BR_PULSE / rx_byte / TX_RESP / crc_match / cmd_pass "
                "/ opcode / tx_done in adjacent *.log files; need "
                "≥ 2 distinct hits). The sim may be a smoke-test only."
            ),
            file=str(results_file.relative_to(project)),
        ))

    return findings, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="protocol_ip_simulation_required_check",
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "protocol_ip_simulation_required_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2, default=str))

    print(f"=== protocol_ip_simulation_required_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print("  [PASS] full-stack sim ran on current RTL with PASS verdict")
        return 0
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: FAIL ({len(findings)} sim-gate violation(s))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
