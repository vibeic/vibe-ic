#!/usr/bin/env python3
"""
functional_state_transition_coverage_check.py — Verify TBs exercise the
state-changing side-effects of every cmd opcode, not just byte-stream
correctness.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
THE PROBLEM
-----------
The vendor dispatcher TB drove every cmd opcode through and confirmed
the response bytes matched. The TB never checked:
  - awake-state register set/cleared after the right opcodes
  - register echo back on read commands
  - periodic timers starting/stopping after enable/disable opcodes
Bugs in those side-effect paths shipped to FPGA undetected.

This gate cross-references a "coverage spec" (the side-effects each
opcode is required to produce) against TB content and reports any
opcode whose matching side-effect is not asserted in the TB.

INPUTS
------
A coverage spec JSON or repeat-CLI:
  ``--coverage <coverage.json>``::
    [
      {"opcode": "0x74",
       "must_assert_set": ["awake_q == 1'b1"]},
      {"opcode": "0x70",
       "must_assert_set": ["reg_q == data_in"]},
      {"opcode": "0x76",
       "must_assert_set": ["wake_pulse_active == 1'b0"]}
    ]

  ``--cov "0x74:awake_q == 1'b1"`` (may repeat)

USAGE
-----
    python3 functional_state_transition_coverage_check.py sim/ \\
        --coverage tb_coverage.json \\
        --json reports/gates/state_cov.json

EXIT CODES
----------
    0 — every opcode's required state assertion appears in some TB.
    1 — at least one opcode lacks the required assertion.
    2 — IO / argument error.
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


def _parse_inline(s: str) -> Optional[Dict[str, Any]]:
    # Format: "OPCODE:assertion text"
    m = re.match(r"^\s*(0x[0-9a-fA-F]+|\d+)\s*:\s*(.+)$", s)
    if not m:
        return None
    return {"opcode": m.group(1), "must_assert_set": [m.group(2).strip()]}


def audit(tb_target: Path, coverage: List[Dict[str, Any]]) -> List[Finding]:
    findings: List[Finding] = []
    if tb_target.is_file():
        files = [tb_target]
    else:
        files = sorted(
            list(tb_target.rglob("tb_*.v")) +
            list(tb_target.rglob("tb_*.sv")) +
            list(tb_target.rglob("*_tb.v")) +
            list(tb_target.rglob("*_tb.sv"))
        )
    if not files:
        findings.append(Finding(
            "WARN", "no_tb_files", str(tb_target), 0,
            f"no tb_*.v/.sv under {tb_target}",
        ))
        return findings

    blob = "\n\n".join(_strip_comments(f.read_text(errors="replace"))
                        for f in files)

    for entry in coverage:
        op = str(entry.get("opcode", "")).strip()
        asserts = entry.get("must_assert_set") or []
        if not op:
            findings.append(Finding(
                "ERROR", "coverage_malformed", "(none)", 0,
                f"coverage entry missing opcode: {entry!r}",
            ))
            continue

        # The opcode should appear in the TB (either as send_cmd(0x..) or
        # `cmd = 0x..` or written into a packet). If absent, the test
        # never exercises the opcode at all.
        op_norm = op.lower()
        op_pattern = re.compile(
            r"\b(?:0x" + re.escape(op_norm.lstrip("0x")) + r"|"
            r"8'h" + re.escape(op_norm.lstrip("0x")) + r")\b",
            re.IGNORECASE,
        )
        if not op_pattern.search(blob):
            findings.append(Finding(
                "ERROR", "opcode_not_exercised", "(none)", 0,
                f"opcode {op!r} is not driven by any TB (no send_cmd, "
                f"no 8'h... literal). The state-transition coverage for "
                f"this opcode is zero by definition.",
            ))
            continue

        # Each assertion needs both operands (LHS and RHS of the
        # comparison) to appear close together (within ~120 chars) in
        # at least one TB. This tolerates `==` / `!==` / `!=` swaps
        # that always happen in `if (x !== expected) $fatal;`-style
        # checks.
        for assertion in asserts:
            tok = assertion.strip()
            if not tok:
                continue
            split = re.split(r"\s*(?:==|!=|!==|>=|<=|>|<)\s*", tok, maxsplit=1)
            if len(split) == 2:
                lhs, rhs = split[0].strip(), split[1].strip()
            else:
                lhs, rhs = tok, ""
            if not lhs:
                continue
            lhs_re = re.compile(re.escape(lhs), re.IGNORECASE)
            present = False
            for m in lhs_re.finditer(blob):
                window = blob[max(0, m.start() - 60):m.end() + 60]
                if not rhs or rhs.lower() in window.lower():
                    present = True
                    break
            if not present:
                findings.append(Finding(
                    "ERROR", "assertion_missing", "(none)", 0,
                    f"opcode {op!r}: required side-effect assertion "
                    f"{tok!r} is NOT present in any TB (looked for "
                    f"{lhs!r} in proximity to {rhs!r}). The TB drives "
                    f"the opcode but never checks the state change the "
                    f"spec requires.",
                ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("tb", help="TB file or directory")
    ap.add_argument("--coverage", help="JSON list of {opcode, must_assert_set}")
    ap.add_argument("--cov", action="append", default=[],
                    help="Inline 'OPCODE:assertion' (repeatable)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    coverage: List[Dict[str, Any]] = []
    if args.coverage:
        try:
            payload = json.loads(Path(args.coverage).read_text())
            if isinstance(payload, list):
                coverage.extend(payload)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    for s in args.cov:
        norm = _parse_inline(s)
        if norm is None:
            print(f"error: cannot parse --cov {s!r}", file=sys.stderr)
            return 2
        coverage.append(norm)

    if not coverage:
        print("error: no coverage entries (--coverage or --cov)", file=sys.stderr)
        return 2

    target = Path(args.tb)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, coverage)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "coverage_entries": len(coverage),
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
