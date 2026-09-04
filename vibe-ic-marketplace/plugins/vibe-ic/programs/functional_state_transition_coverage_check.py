#!/usr/bin/env python3
"""
functional_state_transition_coverage_check.py — Verify TBs exercise the
state-changing side-effects of every cmd opcode, not just byte-stream
correctness.

ENFORCEMENT: advisory

The line above is a declaration in the anchored form consumed by
`flow_gate_enforcement_audit.declared_intent`: this checker is not consumed
inline by the artifact-producing runner that audit measures. Its verdict is
nevertheless required by strict Step 4 through a `program_exit_zero` clause.
When L3 declares command opcodes, missing transition evidence is a real finding
and can refuse Step 4. When L3 explicitly declares no opcodes, the program
returns typed DESIGN_DECLARED_NA and the flow records that executed
applicability decision without treating it as an empty-scan failure.
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


def _find_l3(tb_path: Path) -> Optional[Path]:
    """Find the canonical L3 by walking from the TB target to project root."""
    try:
        start = tb_path.resolve()
    except OSError:
        return None
    for root in [start] + list(start.parents):
        l3 = root / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
        if l3.is_file():
            return l3
    return None


def _l3_declares_no_opcodes(tb_path: Path) -> str:
    """Return the L3 declaration that rules opcodes out, or "" when it does not.

    Walks up from the TB path to the project root that holds
    `phase1/generated_docs/L3_CMD_PROTOCOL.json` (the canonical Phase-1 L3)
    and reads its own typed flags. Only an explicit declaration counts: an
    absent L3 returns "" and the caller keeps its error path.
    """
    l3 = _find_l3(tb_path)
    if l3 is None:
        return ""
    try:
        doc = json.loads(l3.read_text(errors="replace"))
    except (OSError, ValueError):
        return ""
    if not isinstance(doc, dict):
        return ""
    if doc.get("no_opcodes_in_input") is True and not doc.get("opcodes"):
        return "L3_CMD_PROTOCOL.no_opcodes_in_input=true, opcodes=[]"
    if doc.get("command_protocol_applicable") is False:
        return "L3_CMD_PROTOCOL.command_protocol_applicable=false"
    return ""


def _l3_declared_opcode_count(tb_path: Path) -> int:
    """Return the explicit non-empty L3 opcode population, or zero.

    This is intentionally not an inference from protocol prose. Only the
    canonical L3 ``opcodes`` field can turn an absent coverage population into
    a design finding rather than an invocation error.
    """
    l3 = _find_l3(tb_path)
    if l3 is None:
        return 0
    try:
        doc = json.loads(l3.read_text(errors="replace"))
    except (OSError, ValueError):
        return 0
    if not isinstance(doc, dict):
        return 0
    opcodes = doc.get("opcodes")
    if isinstance(opcodes, (list, dict)):
        return len(opcodes)
    return 0


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
        # v1.15.45 (sha256 capture) — per-opcode state-transition coverage is
        # a question about a COMMAND PROTOCOL. When the design's own L3
        # declares no opcodes, an empty coverage list is that declaration,
        # not a missing input: disclose the design-declared N/A (the phrase is
        # the one `_flow_reason_taxonomy` classifies as DESIGN_DECLARED_NA)
        # instead of an execution error that read as INCOMPLETE.
        _l3_na = _l3_declares_no_opcodes(Path(args.tb))
        if _l3_na:
            msg = ("VACUOUS_PASS: no command protocol — the design's L3 "
                   f"declares no opcodes ({_l3_na}); per-opcode "
                   "state-transition coverage is N/A for this non-protocol IC "
                   "(0 coverage entries, nothing to assert)")
            print(msg)
            if args.json:
                l3_path = _find_l3(Path(args.tb))
                if l3_path is None:  # guarded by `_l3_na`, defensive only
                    return 2
                project_root = l3_path.parents[2]
                report = {
                          "program": "functional_state_transition_coverage_check",
                          "target": str(args.tb), "coverage_entries": 0,
                          "errors": 0, "findings": [],
                          "verdict": "VACUOUS_PASS",
                          "reason_class": "DESIGN_DECLARED_NA",
                          "skip_kind": "class-not-applicable",
                          "reason": msg,
                          "applicability_evidence": {
                              "kind": "design-declared-zero-population",
                              "declaration_path": str(
                                  l3_path.relative_to(project_root)),
                              "population_paths": ["opcodes"],
                              "declared_population": 0,
                              "assertions": [
                                  {"path": "no_opcodes_in_input",
                                   "equals": True},
                                  {"path": "opcodes", "equals": []},
                              ],
                          }}
                if args.json == '-':
                    print(json.dumps(report, indent=2))
                else:
                    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.json).write_text(json.dumps(report, indent=2))
            return 2
        _opcode_count = _l3_declared_opcode_count(Path(args.tb))
        if _opcode_count:
            print(
                "FAIL: L3 declares "
                f"{_opcode_count} command opcode(s), but the supplied "
                "functional coverage artifact contains 0 transition "
                "entries; declared protocol behavior has no execution "
                "evidence",
                file=sys.stderr,
            )
            return 1
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
