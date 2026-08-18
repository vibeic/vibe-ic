#!/usr/bin/env python3
"""
fpga_wrapper_input_polluter_check.py — flag FPGA wrappers that AND/OR
multiple inout pins where typically only one is wired to bench hardware.

Background
----------
A common defensive pattern in FPGA wrappers for single-wire / open-drain
protocols (single-wire ID buses, 1-Wire, I2C SDA, single-pin pulse
modems) is to drive the same conceptual signal on N candidate FPGA pins
and read it back via AND of all N — the intent being to "hedge against
bench-cable uncertainty about which pin the host expects."

Failure mode: typically only one pin is actually wired. The other N-1
float on the FPGA's internal weak pullup (~25 kΩ on most parts), pick
up crosstalk from neighbouring traces, and any single glitch low pulls
the AND'd input low. The decoder/FSM sees a spurious falling edge,
break/symbol detection thrashes, and the DUT goes silent on the line.

Symptom: simulation passes (all "inout" pins driven cleanly by the
testbench), hardware fails because the ghost pins float in the real
world and pollute the input.

Rule
----
Inside any module:
  * Collect all `inout` ports declared on its port list (or via `inout`
    declarations).
  * Find any wire / variable assignment whose RHS contains an AND (`&`)
    or OR (`|`) of two or more of those inout names.
  * Severity:
      - WARN by default
      - ERROR with --strict
      - ERROR if --qsf <file> is given AND the QSF binds fewer than the
        number of AND'd pins via set_location_assignment

Allowlist marker on the *previous* line:
    // fpga-input-polluter-allow: <reason>

Usage
-----
    fpga_wrapper_input_polluter_check.py --rtl <file_or_dir> [--qsf <file>] [--strict] [--json]

Exit codes
----------
    0 = pass (no ERROR)
    1 = fail (>=1 ERROR)
    2 = arg / IO error

Generic rationale
-----------------
This check is IC-agnostic. It applies to any single-wire protocol class
(open-drain bus, 1-Wire-style, I2C SDA, RGMII RX_CTL hand-tied) where a
wrapper might over-defensively probe multiple FPGA pins.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

ALLOW_MARKER = "fpga-input-polluter-allow"

# Match `module <name> ( ... );` and `endmodule`. Greedy module body.
_MOD_RE = re.compile(
    r"\bmodule\s+(?P<name>\w+)\s*(?:#\([^)]*\))?\s*\((?P<ports>.*?)\)\s*;"
    r"(?P<body>.*?)\bendmodule\b",
    re.DOTALL,
)

# Match `inout [reg|wire] [packed_range] name` with optional commas/newlines.
_INOUT_DECL_RE = re.compile(
    r"\binout\s+(?:reg\s+|wire\s+|logic\s+)?(?:\[[^\]]+\]\s*)?"
    r"(?P<name>\w+)\b"
)

# Single line stripped of // and /* */ comments
_LINE_COMMENT = re.compile(r"//.*?$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# `assign foo = a & b & c;` or `wire foo = a & b;`
# Also `wire foo = a | b;`
_ASSIGN_RE = re.compile(
    r"(?:assign|wire(?:\s*\[[^\]]+\])?)\s+(?P<lhs>\w+)\s*=\s*(?P<rhs>[^;]+);"
)

# Identifier followed by & / | followed by identifier (chained)
_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*)\b")

# QSF: set_location_assignment PIN_X -to <signal>
_QSF_LOC_RE = re.compile(
    r"^\s*set_location_assignment\s+\S+\s+-to\s+(?P<sig>\S+)",
    re.MULTILINE,
)


@dataclass
class Finding:
    file: str
    line: int
    severity: str  # ERROR / WARN
    rule: str
    detail: str
    snippet: str
    module: str = ""
    pins: list[str] | None = None


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub("", text)
    text = _LINE_COMMENT.sub("", text)
    return text


def _collect_inouts(port_block: str, body: str) -> set[str]:
    """Find all inout port names — both ANSI port-list form and
    legacy `inout name;` declarations inside the module body."""
    names: set[str] = set()
    for m in _INOUT_DECL_RE.finditer(port_block):
        names.add(m.group("name"))
    for m in _INOUT_DECL_RE.finditer(body):
        names.add(m.group("name"))
    return names


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _line_text(text: str, lineno: int) -> str:
    lines = text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ""


def _has_allowlist(text: str, lineno: int) -> bool:
    """Check if the previous non-blank line contains the allowlist marker."""
    lines = text.splitlines()
    i = lineno - 2  # zero-based, one line above
    while i >= 0 and not lines[i].strip():
        i -= 1
    return i >= 0 and ALLOW_MARKER in lines[i]


def _and_or_operands(rhs: str) -> tuple[list[str], str | None]:
    """Return (operand identifiers, operator) if RHS is a chain of '&' or
    '|' between identifiers. Returns ([], None) if it isn't."""
    s = rhs.strip()
    # Strip surrounding parens
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()

    op: str | None = None
    if "&" in s and "|" not in s and "&&" not in s:
        op = "&"
    elif "|" in s and "&" not in s and "||" not in s:
        op = "|"
    else:
        return [], None

    parts = [p.strip() for p in s.split(op)]
    operands: list[str] = []
    for part in parts:
        # Allow `~name` (unary not) and bare ident
        part = part.lstrip("~").strip()
        m = _IDENT_RE.fullmatch(part)
        if not m:
            return [], None
        operands.append(m.group(1))
    return operands, op


def parse_qsf(path: Path) -> set[str]:
    text = path.read_text(errors="replace")
    return {m.group("sig") for m in _QSF_LOC_RE.finditer(text)}


def scan_file(
    path: Path,
    strict: bool,
    qsf_pins: set[str] | None,
) -> list[Finding]:
    raw = path.read_text(errors="replace")
    text = _strip_comments(raw)

    out: list[Finding] = []

    for mmod in _MOD_RE.finditer(text):
        modname = mmod.group("name")
        ports = mmod.group("ports")
        body = mmod.group("body")
        body_offset = mmod.start("body")

        inouts = _collect_inouts(ports, body)
        if len(inouts) < 2:
            continue  # need at least 2 inouts to AND together

        for ma in _ASSIGN_RE.finditer(body):
            rhs = ma.group("rhs")
            ops, op_sym = _and_or_operands(rhs)
            if not ops or len(ops) < 2:
                continue
            inout_ops = [o for o in ops if o in inouts]
            if len(inout_ops) < 2:
                continue
            # Found: assignment that combines >=2 inout pins with & or |
            assign_offset = body_offset + ma.start()
            lineno = _line_no(text, assign_offset)
            # raw-text allowlist check uses original (un-stripped) text
            if _has_allowlist(raw, lineno):
                continue

            severity = "ERROR" if strict else "WARN"
            detail = (
                f"Module '{modname}': '{ma.group('lhs')}' combines "
                f"{len(inout_ops)} inout pins via '{op_sym}' "
                f"({', '.join(inout_ops)}). "
                "Likely poisons input from floating pins on the bench."
            )
            if qsf_pins is not None:
                bound = [p for p in inout_ops if p in qsf_pins]
                # Escalate when QSF commits fewer pins than are AND'd
                if len(bound) < len(inout_ops):
                    severity = "ERROR"
                    detail += (
                        f" QSF binds only {len(bound)} of "
                        f"{len(inout_ops)}: bound={bound}, "
                        f"unbound={[p for p in inout_ops if p not in qsf_pins]}."
                    )

            snippet = _line_text(raw, lineno).strip()[:160]
            out.append(Finding(
                file=str(path), line=lineno, severity=severity,
                rule="multi_inout_combine", detail=detail,
                snippet=snippet, module=modname, pins=inout_ops,
            ))
    return out


def collect_rtl_paths(roots: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for r in roots:
        p = Path(r)
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            for ext in ("*.v", "*.sv", "*.svh", "*.vh"):
                paths.extend(p.rglob(ext))
    return sorted(set(paths))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Flag FPGA wrappers that AND/OR multiple inout pins where "
            "typically only one is wired to bench hardware."
        ))
    ap.add_argument("--rtl", action="append", default=[],
                    help="RTL file or directory (recursive). May be repeated.")
    ap.add_argument("--qsf", help="Optional QSF file; escalates findings to "
                                  "ERROR when fewer pins are bound than AND'd.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat WARN findings as ERROR.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    if not args.rtl:
        print("error: --rtl is required (file or directory)", file=sys.stderr)
        return 2

    paths = collect_rtl_paths(args.rtl)
    if not paths:
        print("error: no .v/.sv files found under --rtl", file=sys.stderr)
        return 2

    qsf_pins: set[str] | None = None
    if args.qsf:
        q = Path(args.qsf)
        if not q.is_file():
            print(f"error: --qsf not found: {q}", file=sys.stderr)
            return 2
        qsf_pins = parse_qsf(q)

    findings: list[Finding] = []
    for p in paths:
        try:
            findings.extend(scan_file(p, strict=args.strict, qsf_pins=qsf_pins))
        except OSError as e:
            print(f"error: {p}: {e}", file=sys.stderr)
            return 2

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARN"]
    verdict = "FAIL" if errors else "PASS"

    if args.json:
        _txt = json.dumps({
            "files_scanned": len(paths),
            "qsf_used": args.qsf or None,
            "qsf_bound_signals": sorted(qsf_pins) if qsf_pins else None,
            "total_errors": len(errors),
            "total_warnings": len(warnings),
            "findings": [asdict(f) for f in findings],
            "verdict": verdict,
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"\n{f.file}:{f.line}  [{f.severity}]  {f.rule} ({f.module})")
            print(f"  {f.detail}")
            print(f"  > {f.snippet}")
        print()
        print(f"Files scanned : {len(paths)}")
        print(f"Errors        : {len(errors)}")
        print(f"Warnings      : {len(warnings)}")
        print(verdict)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
