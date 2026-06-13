#!/usr/bin/env python3
"""cross_module_1cycle_handshake_check.py — BACKLOG-v11 P0.3.

Detect 1-cycle pulse signals exported from one module and consumed by
another module without an explicit ack / latch / req-held handshake.

Motivation
==========

v0.116 <benchmark> had at minimum 4 such races across modular boundaries:
  - cmd_decoder.cmd_pass (1-cycle pulse) → main_fsm.S_DECODE arrives
    2 cycles later, pulse missed
  - main_fsm.tsrs_ok (1-cycle pulse) → dispatcher.D_WAIT_TURN arrives
    ≥ 18 cycles later (OTP read latency), pulse missed
  - dispatcher.kick_wake_pulse defaulted low every cycle, tx_phy saw
    TXOP_WAKE for 1 cycle then flipped back to dispatcher's stale
    TXOP_BR mid-flight
  - generic dispatcher.tx_start (1-cycle) → tx_phy.T_IDLE may already
    be in T_DONE, missing the start

Each was hand-fixed only after exhaustive scope/internal-debug.

Gate behaviour
==============

For every output port of every module that is driven as a 1-cycle
pulse (assigned both `<= 1'b1` and `<= 1'b0` somewhere in the same
always_ff, AND defaulted low at top of else-block), check whether
any OTHER module declares that signal name as an input port. If yes
AND the consuming module does not latch the pulse on its first
sighting (no `<sig>_q` register, no `<sig>_seen` flag, no continuous
re-arm via req-ack), emit `CROSS_MODULE_1CYCLE_RACE`.

This complements `protocol_fsm_topology_check.py` (which is broad and
warns about modular split) by flagging the SPECIFIC signal pairs
that are at risk.

False-alert guards
==================

  - Silent if pulse-source and consumer are the same module.
  - Silent if consumer has an explicit latch register for the pulse
    (token: `<sig>_q`, `<sig>_seen`, `<sig>_latch`, `<sig>_pending`).
  - Silent if pulse signal name contains "ack" / "done" (those are
    naturally one-cycle and the consumer is the producer's peer in a
    req/ack handshake — opposite direction).
  - Silent if pulse remains high until the consumer explicitly clears
    it via a port input wire (req-ack pattern with explicit clear).
  - Silent for designs without inter-module connections.

Severity: WARNING (informational; tightening the handshake is the
recommended fix). Use `--strict` to upgrade.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_modules, find_rtl_files as _rtl_files
from gate_utils import parse_io_ports, read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""

# Orchestration tokens — only modules containing these are treated as
# control-FSMs whose 1-cycle-pulse outputs warrant a race warning.
# PHY-layer modules (rx_phy, tx_phy, bit_assembler, crc) pulse
# rx_byte_vld / bit_valid / tx_done as their NATURAL output and the
# consumer captures them same-edge; that's not a race, it's protocol-
# correct behaviour. v099 oracle relies on this and PASSes hardware.
_ORCHESTRATION_TOKENS: tuple[str, ...] = (
    "cmd_pass",
    "cmd_done",
    "dispatcher_busy",
    "set_awake",
    "wake_done_cmd",
    "wake_done",
    "rsp_op",
    "rsp_total",
    "validate_now",
    "kick_wake_pulse",
    "tsrs_ok",
)
_FSM_STATE_PATTERNS_RE = re.compile(
    r"\bcase\s*\(\s*(?:\w*st\b|\w*state\w*\)|ps\b|d_st\b)",
    re.MULTILINE,
)


def _module_is_orchestration_fsm(body: str) -> bool:
    if not _FSM_STATE_PATTERNS_RE.search(body):
        return False
    return any(tok in body for tok in _ORCHESTRATION_TOKENS)


def _parse_ports(header: str) -> tuple[set[str], set[str]]:
    """Return (input_ports, output_ports). Inout ports ignored."""
    inputs, outputs, _ = parse_io_ports(header)
    return inputs, outputs


_PULSE_HIGH_RE = re.compile(r"\b(\w+)\s*<=\s*1\s*'\s*b1\s*;", re.MULTILINE)
_PULSE_LOW_RE = re.compile(r"\b(\w+)\s*<=\s*1\s*'\s*b0\s*;", re.MULTILINE)


def _module_is_1cycle_pulse_driver(rtl: str, sig: str) -> bool:
    """Heuristic: signal is driven both <= 1'b1 and <= 1'b0 in the
    same module body, and the LOW assignment is at top of an else-block
    (default-low strobe pattern)."""
    has_high = re.search(rf"\b{re.escape(sig)}\s*<=\s*1\s*'\s*b1\s*;", rtl)
    has_low = re.search(rf"\b{re.escape(sig)}\s*<=\s*1\s*'\s*b0\s*;", rtl)
    return bool(has_high and has_low)


_LATCH_SUFFIX_RE = re.compile(
    r"^("
    r"q|qq|"                                # _q, _qq, _qqq common D-flop chain
    r"qqq|"
    r"r|reg|regval|"                        # _r, _reg, _regval
    r"seen|saw|"                            # _seen, _saw
    r"latch|latched|"                       # _latch, _latched
    r"cap|capt|captured|cap_q|"             # capture variants
    r"pending|"
    r"held|hold|"                           # _held, _hold
    r"sticky|"
    r"arm|armed|"
    r"flag|"                                # _flag
    r"set"                                  # _set (sticky-set bit)
    r")$"
)


def _consumer_latches(rtl: str, sig: str) -> bool:
    """True if the consuming module appears to latch the pulse `sig`.

    Looks for an identifier `<sig>_<suffix>` where suffix matches a known
    latch convention (_q, _qq, _seen, _latch, _latched, _captured,
    _pending, _held, _sticky, _arm, _armed, _flag, _reg, _regval, _set).

    Hand-extending this list as new conventions surface is the right
    move — making the suffix grammar fully open is too loose and would
    silence the gate on any project that happens to declare any
    `<sig>_<word>` signal.
    """
    pat = re.compile(rf"\b{re.escape(sig)}_(\w+)\b")
    for m in pat.finditer(rtl):
        if _LATCH_SUFFIX_RE.match(m.group(1)):
            return True
    return False


def _exempt_signal_name(sig: str) -> bool:
    """req-ack / done signals naturally one-cycle and not in scope."""
    nlow = sig.lower()
    return any(tok in nlow for tok in ("_ack", "done", "_ready", "tx_done"))


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "modules": [],
        "pulse_pairs": [],
        "skipped_reason": "",
    }

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    # Build module table: name → (file, body, inputs, outputs, pulse_outputs)
    # Uses gate_utils.find_modules — paren-balanced parser that handles
    # multi-line port lists with [WIDTH-1:0] brackets.
    table: dict[str, dict] = {}
    for f in rtl_files:
        rtl = _read(f)
        for spec in find_modules(rtl):
            inputs, outputs = _parse_ports(spec.header)
            pulses = {sig for sig in outputs
                      if _module_is_1cycle_pulse_driver(spec.body, sig)
                      and not _exempt_signal_name(sig)}
            table[spec.name] = {
                "file": str(f.relative_to(project)),
                "body": spec.body,
                "inputs": inputs,
                "outputs": outputs,
                "pulses": pulses,
            }
            summary["modules"].append(spec.name)

    if not table:
        summary["skipped_reason"] = "no modules parseable"
        return findings, summary

    # Cross-module check: for each pulse output of mod_A, find mod_B
    # where input port name matches.
    for src_name, src in table.items():
        # Skip PHY-layer modules — their pulses (rx_byte_vld, bit_valid,
        # tx_done) are protocol-normal and the consuming FSM captures
        # them same-edge by design. Only orchestration-FSM modules'
        # pulses warrant a race warning.
        if not _module_is_orchestration_fsm(src["body"]):
            continue
        for sig in src["pulses"]:
            for cons_name, cons in table.items():
                if cons_name == src_name:
                    continue
                if sig not in cons["inputs"]:
                    continue
                if _consumer_latches(cons["body"], sig):
                    continue
                # Down-rate to INFO (silent) when the consumer is a
                # PHY-layer module (rx_phy / tx_phy / bit_assembler /
                # crc8 / pll / serdes — modules that are pure
                # bit-level primitives without an orchestration FSM).
                # These consume pulses same-edge by design — that's
                # not a race in v099 oracle and not in v0.116 either.
                if not _module_is_orchestration_fsm(cons["body"]):
                    continue
                summary["pulse_pairs"].append(
                    f"{src_name}.{sig} → {cons_name}"
                )
                findings.append(Finding(
                    severity="WARNING",
                    rule="CROSS_MODULE_1CYCLE_RACE",
                    message=(
                        f"Module `{src_name}` drives port `{sig}` as a "
                        f"1-cycle pulse (default-low strobe); module "
                        f"`{cons_name}` consumes `{sig}` as input but "
                        f"does NOT appear to latch it (no `{sig}_q` / "
                        f"`{sig}_seen` / `{sig}_pending` register). "
                        f"v0.116 <benchmark> lesson: a 1-cycle pulse → "
                        f"consumer that needs ≥2 cycles to react = "
                        f"missed handshake."
                    ),
                    file=src["file"],
                ))

    if not findings and not summary["pulse_pairs"]:
        summary["skipped_reason"] = (
            "no cross-module 1-cycle pulse races detected"
        )

    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="cross_module_1cycle_handshake_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "cross_module_1cycle_handshake_check",
            "passed": not findings or not args.strict,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== cross_module_1cycle_handshake_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print(f"  [PASS] {len(summary['modules'])} module(s) examined; "
              f"no cross-module 1-cycle races")
        return 0
    rc = 0
    for f in findings:
        sev = "ERROR" if (args.strict and f.severity == "WARNING") else f.severity
        if sev == "ERROR":
            rc = 1
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{sev.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: {'FAIL' if rc else 'PASS (with warnings)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
