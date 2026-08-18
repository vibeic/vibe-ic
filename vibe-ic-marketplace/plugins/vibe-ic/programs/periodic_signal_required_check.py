#!/usr/bin/env python3
"""
periodic_signal_required_check.py — Verify that for every protocol-mandated
periodic device-side activity (wake pulse, heartbeat, keepalive), the RTL
contains a generator module that actually emits the signal.

THE PROBLEM
-----------
The vendor run defined `WAKE_ITO_CYCLES` as a constant but no module
instantiated a wake-pulse generator. The RTL parameter existed; nothing
ever drove a periodic wake pulse to the host. Since a static lint sees
the constant defined and the lint passes, the bug only manifests on the
rig.

This gate cross-references a "periodic-signal manifest" (from spec or
CLI) against the RTL. For each entry, it requires:
  1. A generator-style sequential block: a counter that resets when it
     reaches a threshold AND toggles or pulses an output signal.
  2. The output signal of that generator must be wired to a port (top
     module) OR consumed by another module via instantiation.

A constant existing without a generator block → FAIL.

INPUTS
------
A manifest — one of:
  a. ``--periodic <m.json>`` ::
       [
         {"name": "wake_pulse", "period_const": "WAKE_ITO_CYCLES",
          "output_port": "wake_out"},
         {"name": "heartbeat",  "period_const": "HEARTBEAT_PERIOD",
          "output_port": "hb"}
       ]
  b. CLI: ``--required NAME=PERIOD_CONST,OUTPUT_PORT`` (repeatable)

USAGE
-----
    python3 periodic_signal_required_check.py rtl/ \\
        --required "wake=WAKE_ITO_CYCLES,wake_out" \\
        --json reports/gates/periodic.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _parse_required(s: str) -> Optional[Dict[str, str]]:
    # NAME=PERIOD_CONST,OUTPUT_PORT
    m = re.match(r"^\s*([\w-]+)\s*=\s*(\w+)\s*,\s*(\w+)\s*$", s)
    if not m:
        return None
    return {"name": m.group(1),
            "period_const": m.group(2),
            "output_port": m.group(3)}


def has_counter_generator(text: str, period_const: str, output: str) -> bool:
    """Return True iff there is a sequential block where:
      - a counter is being compared against `period_const` (or is reset
        when reaching it), AND
      - the output signal is toggled / pulsed in the same `always` block.

    This is a heuristic — false positives possible.
    """
    # Find any always-block where both period_const and output are mentioned
    for m in re.finditer(
        r"always(?:_ff|_comb)?\s*@\s*\([^)]*\)([\s\S]*?)(?=\balways|\bendmodule)",
        text,
    ):
        body = m.group(1)
        if period_const in body and re.search(r"\b" + re.escape(output) + r"\b",
                                              body):
            # Confirm a counter compare exists (== / >= / <= involving constant)
            if re.search(
                r"(?:==|>=|<=|<|>)\s*" + re.escape(period_const) + r"\b",
                body,
            ) or re.search(
                r"\b" + re.escape(period_const) + r"\s*(?:==|>=|<=)", body):
                return True
    return False


def output_port_declared(text: str, output: str) -> bool:
    """Check the output signal is declared as a port somewhere."""
    return bool(re.search(
        r"\b(?:output|inout)\b[\w\s,\[\]]+\b" + re.escape(output) + r"\b",
        text,
    ))


def audit(rtl_target: Path,
          required: List[Dict[str, str]]) -> List[Finding]:
    findings: List[Finding] = []
    if rtl_target.is_file():
        files = [rtl_target]
    else:
        files = sorted(list(rtl_target.rglob("*.v")) + list(rtl_target.rglob("*.sv")))
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    blob = "\n\n".join(_strip_comments(f.read_text(errors="replace"))
                        for f in files if f.is_file())

    for entry in required:
        name = entry.get("name", "")
        period = entry.get("period_const", "")
        out = entry.get("output_port", "")
        if not (name and period and out):
            findings.append(Finding(
                "ERROR", "manifest_malformed",
                "(none)", 0,
                f"manifest entry missing fields: {entry!r}",
            ))
            continue

        const_present = bool(re.search(
            r"(?:parameter|localparam|`define)\s+(?:\[[^\]]*\]\s*)?"
            + re.escape(period) + r"\b",
            blob,
        )) or re.search(r"\b" + re.escape(period) + r"\b", blob) is not None

        if not const_present:
            findings.append(Finding(
                "ERROR", "period_const_missing",
                "(none)", 0,
                f"required periodic signal {name!r} declared with "
                f"period_const={period!r} but that constant is not "
                f"defined or referenced anywhere in the RTL.",
            ))
            continue

        if not output_port_declared(blob, out):
            findings.append(Finding(
                "ERROR", "output_port_missing",
                "(none)", 0,
                f"required periodic signal {name!r}: expected output port "
                f"{out!r} not declared in any module — the device cannot "
                f"emit the signal.",
            ))
            continue

        if not has_counter_generator(blob, period, out):
            findings.append(Finding(
                "ERROR", "generator_missing",
                "(none)", 0,
                f"required periodic signal {name!r}: constant {period!r} "
                f"and port {out!r} both exist, but no `always` block "
                f"counts against {period} and toggles/pulses {out}. "
                f"The constant is dead — the device will never emit the "
                f"signal even though the spec mandates it.",
            ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--periodic", help="JSON manifest of required periodic signals")
    ap.add_argument("--required", action="append", default=[],
                    help="Inline 'NAME=PERIOD_CONST,OUTPUT_PORT' (repeatable)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    required: List[Dict[str, str]] = []
    if args.periodic:
        try:
            payload = json.loads(Path(args.periodic).read_text())
            if isinstance(payload, list):
                required.extend(payload)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    for s in args.required:
        norm = _parse_required(s)
        if norm is None:
            print(f"error: cannot parse --required {s!r}", file=sys.stderr)
            return 2
        required.append(norm)

    if not required:
        print("error: no required signals supplied (--periodic or --required)",
              file=sys.stderr)
        return 2

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, required)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "required_signals": len(required),
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
