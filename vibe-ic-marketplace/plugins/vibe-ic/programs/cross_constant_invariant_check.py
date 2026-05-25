#!/usr/bin/env python3
"""
cross_constant_invariant_check.py — Verify named timing/protocol constants
in RTL honour the ordering invariants the spec requires.

THE PROBLEM
-----------
On the vendor run, two constants — IBT_max and FRAME_END_threshold — were
both derived numerically from the spec but the agent set IBT_max=22us and
FRAME_END_threshold=14us. The spec implicitly requires
``IBT_max < FRAME_END_threshold`` (otherwise IBT detection kills frames
mid-command). Each constant individually was within range; only the
relative ordering was wrong, and no existing gate caught it.

This program takes a list of invariants (a < b, a <= b, etc.) and a set
of constant definitions (parsed from RTL ``parameter`` / ``localparam``
statements OR provided as a JSON map) and reports any violation.

INPUTS
------
1. Constants — one of:
     a. ``--constants <map.json>`` :: {"IBT_MAX": 22000, "FRAME_END": 14000}
     b. ``--rtl <file_or_dir>``  — parse `parameter NAME = VAL;` statements
2. Invariants — one of:
     a. ``--invariants <invariants.json>`` ::
            [
              {"lhs": "IBT_MAX", "op": "<", "rhs": "FRAME_END"},
              {"lhs": "WAKE_PERIOD", "op": ">=", "rhs": "WAKE_PULSE_WIDTH"}
            ]
     b. CLI repeats: ``--inv "IBT_MAX < FRAME_END"`` (may be repeated)

USAGE
-----
    python3 cross_constant_invariant_check.py --rtl rtl/ \\
        --inv "IBT_MAX < FRAME_END" --inv "WAKE_PERIOD >= WAKE_PULSE"

    python3 cross_constant_invariant_check.py --constants tmp/c.json \\
        --invariants invariants.json --json reports/gates/cross_const.json

EXIT CODES
----------
    0 — every invariant holds.
    1 — at least one invariant violated.
    2 — IO / argument / parse error.
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
    message: str


# Verilog parameter / localparam definition with numeric value.
# Captures: name, value-expression. We then evaluate simple expressions
# (decimal, hex, binary, sized literals).
PARAM_RE = re.compile(
    r"^\s*(?:parameter|localparam)\s+(?:\[[^\]]*\]\s*)?"
    r"(\w+)\s*=\s*([^,;]+)\s*[,;]",
    re.MULTILINE,
)

VLOG_NUM_RE = re.compile(r"(\d+)?'(?:[bohdBOHD])([0-9a-fA-F_xXzZ]+)")


def _parse_verilog_value(expr: str) -> Optional[int]:
    expr = expr.strip()
    # Strip parens
    while expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1].strip()
    # Sized literal: 8'b00010001, 16'h12_34, 'd42, etc.
    m = VLOG_NUM_RE.match(expr)
    if m:
        digits = m.group(2).replace("_", "")
        # Detect base from the original literal (lowercased)
        base_chr = expr[expr.index("'") + 1].lower()
        base_map = {"b": 2, "o": 8, "h": 16, "d": 10}
        try:
            return int(digits, base_map.get(base_chr, 10))
        except ValueError:
            return None
    # Plain decimal / hex int
    try:
        return int(expr.replace("_", ""), 0)
    except ValueError:
        return None


def parse_rtl_constants(rtl_path: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if rtl_path.is_file():
        files = [rtl_path]
    else:
        files = sorted(list(rtl_path.rglob("*.v")) + list(rtl_path.rglob("*.sv"))
                       + list(rtl_path.rglob("*.vh")))
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        # Strip comments
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        text = re.sub(r"//[^\n]*", "", text)
        for m in PARAM_RE.finditer(text):
            name = m.group(1)
            val = _parse_verilog_value(m.group(2))
            if val is not None:
                # Last write wins; warn-worthy in real flows but fine here
                out[name] = val
    return out


def _normalise_invariant(s: str) -> Optional[Dict[str, str]]:
    m = re.match(r"^\s*(\w+)\s*(<=|>=|<|>|==|!=)\s*(\w+)\s*$", s)
    if not m:
        return None
    return {"lhs": m.group(1), "op": m.group(2), "rhs": m.group(3)}


def _eval_op(a: int, op: str, b: int) -> bool:
    return {
        "<": a < b, "<=": a <= b,
        ">": a > b, ">=": a >= b,
        "==": a == b, "!=": a != b,
    }[op]


def audit(constants: Dict[str, int],
          invariants: List[Dict[str, str]]) -> List[Finding]:
    findings: List[Finding] = []
    for inv in invariants:
        lhs = inv.get("lhs")
        rhs = inv.get("rhs")
        op = inv.get("op")
        if not (lhs and rhs and op):
            findings.append(Finding(
                "ERROR", "invariant_malformed",
                f"invariant entry missing lhs/op/rhs: {inv!r}",
            ))
            continue
        if lhs not in constants:
            findings.append(Finding(
                "ERROR", "constant_not_found",
                f"invariant {lhs} {op} {rhs}: lhs constant {lhs!r} not "
                f"found in RTL or constants map.",
            ))
            continue
        if rhs not in constants:
            findings.append(Finding(
                "ERROR", "constant_not_found",
                f"invariant {lhs} {op} {rhs}: rhs constant {rhs!r} not "
                f"found in RTL or constants map.",
            ))
            continue
        if not _eval_op(constants[lhs], op, constants[rhs]):
            findings.append(Finding(
                "ERROR", "invariant_violated",
                f"{lhs} ({constants[lhs]}) {op} {rhs} ({constants[rhs]}) "
                f"is FALSE — the spec-required ordering does not hold. "
                f"Either change the constant value or revisit the spec "
                f"derivation.",
            ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("--rtl", help="RTL file or directory (parsed for parameters)")
    ap.add_argument("--constants", help="JSON file with constants map")
    ap.add_argument("--invariants", help="JSON file with invariants list")
    ap.add_argument("--inv", action="append", default=[],
                    help="Inline invariant 'A op B' (repeatable)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args(argv)

    constants: Dict[str, int] = {}
    if args.constants:
        try:
            constants.update(json.loads(Path(args.constants).read_text()))
        except Exception as e:
            print(f"error: cannot read constants {args.constants}: {e}", file=sys.stderr)
            return 2
    if args.rtl:
        rtl_path = Path(args.rtl)
        if not rtl_path.exists():
            print(f"error: rtl path not found: {rtl_path}", file=sys.stderr)
            return 2
        constants.update(parse_rtl_constants(rtl_path))

    invariants: List[Dict[str, str]] = []
    if args.invariants:
        try:
            payload = json.loads(Path(args.invariants).read_text())
            if isinstance(payload, list):
                invariants.extend(payload)
        except Exception as e:
            print(f"error: cannot read invariants {args.invariants}: {e}", file=sys.stderr)
            return 2
    for s in args.inv:
        norm = _normalise_invariant(s)
        if norm is None:
            print(f"error: cannot parse --inv {s!r}", file=sys.stderr)
            return 2
        invariants.append(norm)

    if not constants:
        print("error: no constants supplied (--rtl or --constants)", file=sys.stderr)
        return 2
    if not invariants:
        print("error: no invariants supplied (--invariants or --inv)", file=sys.stderr)
        return 2

    findings = audit(constants, invariants)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "constants_seen": len(constants),
        "invariants_checked": len(invariants),
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
            print(f"[{f.severity}] {f.rule}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
