#!/usr/bin/env python3
"""protocol_fsm_topology_check.py — BACKLOG-v11 P0.1.

Detect modular protocol-FSM with 1-cycle cross-module pulse handshakes,
and recommend the v099-style single-FSM topology.

Motivation
==========

The v0.116 fresh-agent benchmark on <chip-class> produced RTL with at least
12 distinct independent bugs that compounded into byte[6]=0x02 hardware
FAIL. Several of those bugs were 1-cycle cross-module pulse races
between the agent's modular FSMs (cmd_decoder ↔ main_fsm ↔
cmd_dispatcher ↔ tx_phy):

  - cmd_decoder.cmd_pass (1-cycle pulse) → main_fsm.S_DECODE arrives
    2 cycles later, pulse missed
  - main_fsm.tsrs_ok (1-cycle pulse) → dispatcher.D_WAIT_TURN arrives
    ≥ 18 cycles later (OTP read latency), pulse missed
  - dispatcher.kick_wake_pulse defaulted low every cycle, tx_phy saw
    TXOP_WAKE for 1 cycle then flipped back to dispatcher's stale
    TXOP_BR mid-flight

The v099 oracle (working reference for the same chip class) uses ONE
monolithic FSM that owns RX collection → validate → dispatch → TX in
a single always_ff and has zero such races.

Gate behaviour
==============

Trigger conditions (gate considers the design "protocol-IP-class"):
  1. L8 RTL constants declares any of: inter_byte_time_ticks,
     tsrs_min_ticks, frame_end_gap_ticks, ibt_ticks, tx_ibt_ticks,
     bus_turnaround_ticks (any spec-microsecond inter-byte / inter-frame
     timing constant indicates a byte-level protocol).
  2. OR L9 declares cmd_response_cycle: true / response_required: true.
  3. OR L3 declares an opcode table (presence of opcode_table /
     command_protocol field).

If the design qualifies as protocol-IP-class, count the number of
distinct modules that hold protocol state (modules whose RTL
contains any always_ff transitioning on rx_byte_vld /
rx_byte_valid / cmd_pass / cmd_done / tx_done / tx_busy /
tx_byte_valid / tsrs_ok / kick_wake_pulse / dispatcher_busy or
similar protocol-handshake signals).

If count ≥ 3 AND there exists ≥ 1 cross-module 1-cycle pulse signal
(pattern: `<= 1'b1;` in one module, port-connected to another module's
input, with the originating module also re-defaulting the signal to 0
the next cycle):

  → emit WARNING "MODULAR_PROTOCOL_FSM_RACE_RISK", recommend
    fsm_topology=single_fsm with reference to v099-style template.

Verdict policy
==============

Default verdict = PASS with WARNING (gate raises issues but does not
fail the build) — matches v0.104 structural-gate norm of warning-class
checks. Set --strict to upgrade WARNING → ERROR.

False-alert guards
==================

  - Gate is silent for designs whose L9 declares
    fsm_topology=modular_split with an explicit non-empty rationale
    field (engineer override).
  - Gate is silent for designs whose L9 declares fsm_topology=single_fsm
    (no further check needed).
  - Gate is silent for non-protocol designs (no protocol-IP-class
    triggers above).
  - Gate is silent if RTL directory is missing or empty (exit-2,
    same convention as the rest of the v0.104 structural family).

Exit codes
==========

  0  PASS (no findings, or gate exempt)
  1  WARNING raised (or ERROR if --strict)
  2  Input missing / not applicable (gate skipped)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from gate_utils import find_rtl_files as _find_rtl_files
from gate_utils import read_text as _read


# ---------------------------------------------------------------------------
# Trigger detection: is this a protocol-IP-class design?
# ---------------------------------------------------------------------------

# Tokens that, when present in any L1-L23 doc, suggest byte-level protocol IP.
# Patterns match against `text.lower()` so they are case-insensitive.
_PROTOCOL_TOKEN_PATTERNS: tuple[str, ...] = (
    # inter-byte time / IBT in any spelling — IBT_MIN, ibt_us, ibt_ticks…
    r"\bibt[_-]?(?:ticks|min|max|us|cyc|cycles)?\b",
    r"\binter[_-]?byte",
    # tSRS gap (slave-response-start) in any spelling
    r"\btsrs[_-]?(?:min|max|us|ticks)?\b",
    # frame-end gap / bus-turnaround
    r"\bframe[_-]?end[_-]?gap",
    r"\bbus[_-]?turnaround",
    # explicit declarative phrases
    r"\bcmd[_-]?response[_-]?cycle",
    r"\bcommand[_-]?protocol",
    r"\bbyte[_-]?stream[_-]?protocol",
    r"\bend[_-]?of[_-]?frame",
    r"\bbyte[_-]?framing\b",
    # opcode table — match either the field name or a key-value style
    r"\bopcode[_-]?table",
    r"\bopcode\b\s*[:=]",
)

# Two distinct token classes:
#
#   ORCHESTRATION tokens are HIGH-LEVEL control-flow signals — only modules
#   that decide cmd validation / dispatch / response are flagged. A module
#   merely emitting a byte-level signal (rx_byte_vld) is NOT orchestration.
#
#   This split prevents false alerts on PHY-layer modules: in the v099
#   oracle, rx_phy / tx_phy / bit_assembler all reference rx_byte_valid /
#   tx_done but only cmd_dispatcher.v holds the orchestration FSM. Without
#   this split, every protocol IP would trip the gate even when it has a
#   correct single-FSM control plane.
_ORCHESTRATION_TOKENS: tuple[str, ...] = (
    "cmd_pass",
    "cmd_done",
    "dispatcher_busy",
    "set_awake",
    "wake_done_cmd",
    "wake_done",
    "response",       # rsp_op, response_ready, etc.
    "rsp_op",
    "rsp_total",
    "validate_now",
    "kick_wake_pulse",
    "tsrs_ok",
)

# A module also needs an EXPLICIT state machine (case decode of an enum or
# parameter-defined state register) — not just a free-running counter or
# pulse strobe. This second filter tightens the gate further.
_FSM_STATE_PATTERNS: tuple[str, ...] = (
    r"\bcase\s*\(\s*\w*st\b",       # case (st) / case (state) / case (ps)
    r"\bcase\s*\(\s*\w*state\w*\)",  # case (state) / case (cur_state)
    r"\bcase\s*\(\s*ps\b",
    r"\bcase\s*\(\s*d_st\b",
    r"\btypedef\s+enum\b[^;]*\bst[a-z_]*_e\b",
    r"\blocalparam\b[^;]*\bS_[A-Z_]+\s*=",
)


@dataclass
class Finding:
    severity: str          # WARNING / ERROR
    rule: str              # MODULAR_PROTOCOL_FSM_RACE_RISK
    message: str
    file: str = ""
    line: int = 0


def _is_protocol_ip(project: Path) -> tuple[bool, list[str]]:
    """Return (is_protocol, evidence_strings)."""
    evidence: list[str] = []

    # Walk L1-L23 doc-style files (L*.json, L*.md, generated_docs/L*.*).
    candidate_globs = (
        "phase1/generated_docs/L*.json",
        "phase1/generated_docs/L*.md",
        "L*.json",
        "L*.md",
        "input/docs/L*.json",
        "input/docs/L*.md",
        "input/L*.json",
    )
    for pat in candidate_globs:
        for f in project.glob(pat):
            text = _read(f)
            if not text:
                continue
            lower = text.lower()
            for tok in _PROTOCOL_TOKEN_PATTERNS:
                if re.search(tok, lower):
                    evidence.append(f"{f.name}:{tok}")
                    break  # one hit per file is enough

    return (bool(evidence), evidence)


def _read_l9_topology(project: Path) -> tuple[str | None, str]:
    """Return (fsm_topology, rationale) from L9 if declared, else (None, '')."""
    l9_candidates = list(project.glob("phase1/generated_docs/L9*.json")) + list(
        project.glob("L9*.json")
    ) + list(project.glob("input/docs/L9*.json"))
    for f in l9_candidates:
        try:
            data = json.loads(_read(f) or "{}")
        except json.JSONDecodeError:
            continue
        topo = data.get("fsm_topology")
        rationale = data.get("fsm_topology_rationale", "") or ""
        if topo in ("single_fsm", "modular_split", "auto"):
            return topo, rationale
    return None, ""


# ---------------------------------------------------------------------------
# Module discovery + protocol-state classification
# ---------------------------------------------------------------------------

_MODULE_RE = re.compile(r"^\s*module\s+(\w+)\b", re.MULTILINE)
_ALWAYS_FF_RE = re.compile(r"\balways_ff\b|\balways\s*@\s*\(\s*posedge\b",
                           re.MULTILINE)


def _module_holds_orchestration_fsm(rtl: str) -> bool:
    """Heuristic: module text holds an orchestration FSM if it has BOTH
    (a) an always_ff block,
    (b) an explicit case-on-state-register pattern (FSM dispatch),
    (c) at least one orchestration-class token (cmd_pass, dispatcher_busy,
        rsp_op, set_awake, etc.).

    This deliberately EXCLUDES PHY-layer modules (rx_phy / tx_phy /
    bit_assembler) which have always_ff + state but only emit/consume
    byte-level signals (rx_byte_vld, tx_done) and do NOT make
    cmd-validation / dispatch decisions."""
    if not _ALWAYS_FF_RE.search(rtl):
        return False
    if not any(re.search(pat, rtl, re.MULTILINE) for pat in _FSM_STATE_PATTERNS):
        return False
    if not any(tok in rtl for tok in _ORCHESTRATION_TOKENS):
        return False
    return True


# ---------------------------------------------------------------------------
# Cross-module 1-cycle pulse detection
# ---------------------------------------------------------------------------

# Pattern: `signal <= 1'b1;` somewhere AND `signal <= 1'b0;` later in the
# same always_ff block. We use a simple line-based heuristic.
_PULSE_HIGH_RE = re.compile(r"^\s*(\w+)\s*<=\s*1'b1\s*;", re.MULTILINE)
_PULSE_LOW_RE = re.compile(r"^\s*(\w+)\s*<=\s*1'b0\s*;", re.MULTILINE)


def _find_module_output_ports(rtl: str) -> set[str]:
    """Return set of output port names declared at the module header."""
    ports: set[str] = set()
    # find header (between `module ... (` and `)`)
    m = re.search(r"\bmodule\b[^(]*\(", rtl)
    if not m:
        return ports
    header_start = m.end()
    # find matching closing paren — naive (no nested parens in port list)
    depth = 1
    i = header_start
    while i < len(rtl) and depth:
        if rtl[i] == "(":
            depth += 1
        elif rtl[i] == ")":
            depth -= 1
        i += 1
    header = rtl[header_start:i - 1]
    for tok in re.finditer(r"output\s+(?:logic|wire|reg)?\s*"
                           r"(?:\[[^\]]+\])?\s*(\w+)", header):
        ports.add(tok.group(1))
    return ports


def _find_pulse_outputs(rtl: str) -> set[str]:
    """Return the set of output ports that are driven as 1-cycle pulses
    (assigned both <= 1'b1 and <= 1'b0 somewhere)."""
    outs = _find_module_output_ports(rtl)
    if not outs:
        return set()
    high = set(_PULSE_HIGH_RE.findall(rtl))
    low = set(_PULSE_LOW_RE.findall(rtl))
    pulse = outs & high & low
    return pulse


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def inspect(project: Path) -> tuple[list[Finding], dict]:
    """Return (findings, summary)."""
    findings: list[Finding] = []
    summary: dict = {
        "is_protocol_ip": False,
        "protocol_ip_evidence": [],
        "fsm_topology_declared": None,
        "modules_with_protocol_state": [],
        "cross_module_pulse_outputs": [],
        "skipped_reason": "",
    }

    # 1) Protocol-IP gate
    is_protocol, evidence = _is_protocol_ip(project)
    summary["is_protocol_ip"] = is_protocol
    summary["protocol_ip_evidence"] = evidence
    if not is_protocol:
        summary["skipped_reason"] = (
            "L1-L23 docs do not declare any byte-level-protocol timing "
            "constants or opcode table — gate not applicable"
        )
        return findings, summary

    # 2) L9 fsm_topology override
    topo, rationale = _read_l9_topology(project)
    summary["fsm_topology_declared"] = topo
    if topo == "single_fsm":
        summary["skipped_reason"] = "L9 declares fsm_topology=single_fsm"
        return findings, summary
    if topo == "modular_split":
        if rationale.strip():
            summary["skipped_reason"] = (
                "L9 declares fsm_topology=modular_split with rationale "
                "(engineer override)"
            )
            return findings, summary
        # No rationale — still warn.
        findings.append(Finding(
            severity="WARNING",
            rule="MODULAR_SPLIT_WITHOUT_RATIONALE",
            message=("L9 declares fsm_topology=modular_split but no "
                     "non-empty fsm_topology_rationale provided. "
                     "Engineer override requires explicit justification."),
        ))

    # 3) RTL discovery
    rtl_files = _find_rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found in project"
        return findings, summary

    # 4) Per-module classification
    modules_with_state: list[tuple[str, Path]] = []
    pulse_outputs: dict[str, set[str]] = {}  # module_name -> set of pulse ports
    for f in rtl_files:
        rtl = _read(f)
        if not rtl:
            continue
        if not _module_holds_orchestration_fsm(rtl):
            continue
        # find module name(s) in this file
        for mname_match in _MODULE_RE.finditer(rtl):
            mname = mname_match.group(1)
            modules_with_state.append((mname, f))
            pulses = _find_pulse_outputs(rtl)
            if pulses:
                pulse_outputs[mname] = pulses

    summary["modules_with_protocol_state"] = [
        f"{m}@{p.relative_to(project)}" for m, p in modules_with_state
    ]
    summary["cross_module_pulse_outputs"] = [
        f"{m}.{port}" for m, ports in pulse_outputs.items() for port in ports
    ]

    # 5) Verdict
    n_modules = len(modules_with_state)
    n_pulses = sum(len(s) for s in pulse_outputs.values())
    if n_modules >= 3 and n_pulses >= 1:
        findings.append(Finding(
            severity="WARNING",
            rule="MODULAR_PROTOCOL_FSM_RACE_RISK",
            message=(
                f"Protocol-IP design split across {n_modules} modules with "
                f"protocol state, {n_pulses} cross-module 1-cycle "
                f"pulse output(s). Each pulse → consumer-module boundary "
                f"is a missed-handshake risk if the consumer is not in "
                f"the same cycle. Recommend fsm_topology=single_fsm — "
                f"see vibe-ic/skills/spec-to-rtl/templates/"
                f"protocol_single_fsm.sv.j2 (BACKLOG-v11 P0.1)."
            ),
        ))

    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="protocol_fsm_topology_check",
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None,
                    help="Write JSON report to this path")
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade WARNING findings to ERROR (exit 1)")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)

    if args.json:
        out = {
            "program": "protocol_fsm_topology_check",
            "passed": all(f.severity != "ERROR" and not args.strict
                          for f in findings),
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out, indent=2))

    print(f"=== protocol_fsm_topology_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print("  [PASS] no protocol-FSM topology issues detected")
        return 0
    rc = 0
    for f in findings:
        sev = f.severity
        if args.strict and sev == "WARNING":
            sev = "ERROR"
        if sev == "ERROR":
            rc = 1
        print(f"  [{sev.lower()}] {f.rule}: {f.message}")
    print(f"\nOverall: {'FAIL' if rc else 'PASS (with warnings)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
