#!/usr/bin/env python3
"""
synth_netlist_check.py — Deterministic synthesis netlist validation checker.

Verifies that a synthesized Verilog netlist exists and contains a reasonable
number of cell instances. This catches the common failure where synthesis
either failed silently (producing an empty netlist) or produced a trivially
small design (suggesting major module omissions).

What it catches:
  1. MISSING_NETLIST — the netlist file does not exist
  2. EMPTY_NETLIST — the netlist file is empty or contains no Verilog
  3. TOO_FEW_CELLS — cell instance count is below the minimum threshold
     (WARNING only when the structure-aware floor cannot vouch — see below)
  4. NO_MODULE — no module definition found in the netlist
  5. STALE_NETLIST — the netlist is OLDER than the RTL it is judged against
     (ORGANIC-20260606-synth-netlist-stale-on-regate #426: a close-loop
     re-gate must never be judged against the previous run's ghost netlist)
  6. OUTPUTS_TIED_CONSTANT — every module output is driven only by constants
     (the real pruned-stub signature)

Structure-aware floor (ORGANIC-20260606-min-cells-floor-tiny-designs #427):
a legitimately tiny correct design (an 8-DFF shifter, a 3-cell pulse FSM, a
5-cell edge detector) cannot grow on retry, so a flat min-cells ERROR is
unactionable noise. Resolution order:
  (a) PASS when the netlist's sequential-cell count >= the RTL's declared
      register bit count (needs --rtl; a shift register legitimately
      synthesizes to exactly its DFFs);
  (b) zero cells / outputs tied constant stay hard ERRORs (real stubs);
  (c) otherwise a below-threshold count is a WARNING (disclosed, non-fatal).

Usage:
    python3 synth_netlist_check.py --netlist synth/netlist.v
        [--min-cells 10] [--rtl <rtl.v> ...]

Exit codes:
    0 = valid netlist (warnings allowed)
    1 = missing, empty, stale, stub, or structurally invalid
    2 = parse error / invalid arguments

Generality: works for ANY Verilog gate-level netlist.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # MISSING_NETLIST, EMPTY_NETLIST, TOO_FEW_CELLS, NO_MODULE
    message: str
    details: str = ""


# ---------------------------------------------------------------------------
# Verilog keywords — NOT cell instantiations
# ---------------------------------------------------------------------------
VERILOG_KEYWORDS = {
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
    'assign', 'always', 'initial', 'begin', 'end', 'if', 'else',
    'case', 'endcase', 'for', 'while', 'parameter', 'localparam',
    'generate', 'endgenerate', 'function', 'endfunction', 'task',
    'endtask', 'specify', 'endspecify', 'primitive', 'endprimitive',
    'table', 'endtable', 'supply0', 'supply1', 'tri', 'tri0', 'tri1',
    'wand', 'wor', 'trireg', 'integer', 'real', 'time', 'realtime',
    'genvar', 'default', 'posedge', 'negedge', 'or', 'and', 'not',
    'nand', 'nor', 'xor', 'xnor', 'buf', 'bufif0', 'bufif1',
    'notif0', 'notif1',
}

# Pattern: CellType InstanceName ( ... )
# v1.6.194 (#81 P1) — `\w` excludes `$`, so yosys primitive-form
# cells like `$_NAND_ u1 (.A(a), ...)` were silently uncounted.
# v1.6.195 (#82 P0) — `write_verilog -noexpr` emits primitives in
# Verilog escaped-identifier form `\$_NAND_  u1 (...)` because `$`
# is a special char inside identifiers. Accept optional leading
# `\` so the canonical yosys output form counts. Counter buckets
# strip the leading `\` so `\$_NAND_` and `$_NAND_` dedup to the
# same key.
# chip-AGNOSTIC: structural identifier shape, not chip class.
CELL_INST_RE = re.compile(
    # group 1 = cell type (with optional $ or \), group 2 = instance name.
    # v0.1.32 — instance name MUST allow yosys-escaped identifiers
    # `\<chars-until-whitespace>` (e.g. `\u.q_reg[0]`, `\$auto$_NN_`) since
    # those are EVERYWHERE in yosys -noexpr -nostr -noattr output.
    # Without this, DFF-heavy designs (JC_counter / right_shifter) emit
    # `$_DFF_PN0_ \u.q_reg[0] (` and the base `\w+` rejects everything
    # after the `\` because of the `.[]` chars.
    r'^\s*(\\?\$?[A-Za-z_$][\w$]*)\s+(\\\S+|\w+)\s*\(',
    re.MULTILINE,
)
# v0.1.32 — yosys `write_verilog -noexpr -nostr -noattr` emits cell-instance
# lines with /* _NNN_ */ block comments between the type and the instance
# name (e.g. `$_DFF_PN0_ /* _04_ */ s4_reg (`) AND between the instance name
# and the port-list paren (e.g. `\$_NOT_  _03_ /* _05_ */ (`). The base regex
# above rejects both forms. We strip the block comments before matching so
# DFF-heavy designs (JC_counter, right_shifter) are counted correctly.
# chip-AGNOSTIC.
_YOSYS_BLOCK_COMMENT_RE = re.compile(r"/\*[^*]*?\*/")
MODULE_RE = re.compile(r'^\s*module\s+(\w+)', re.MULTILINE)


def count_cell_instances(netlist_text: str) -> Tuple[int, Dict[str, int]]:
    """Count cell instances in a gate-level Verilog netlist.

    Returns (total_count, cell_type_counts).
    """
    cell_counts: Dict[str, int] = {}
    lines = netlist_text.split('\n')
    in_module_header = False

    for line in lines:
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//'):
            continue

        # Track module header
        if re.match(r'^\s*module\s+', stripped):
            if ');' in stripped:
                in_module_header = False
            else:
                in_module_header = True
            continue
        if in_module_header:
            if ');' in stripped:
                in_module_header = False
            continue

        # Skip non-instantiation lines
        if stripped.startswith(('wire', 'reg', 'assign', 'input', 'output',
                                'inout', 'parameter', 'localparam', '`',
                                'endmodule', '//')):
            continue

        # v0.1.32 — strip yosys `/* _NNN_ */` block comments embedded in
        # cell-instance lines so the regex can match. Without this, DFF-heavy
        # designs emit lines like `$_DFF_PN0_ /* _04_ */ s4_reg (` that the
        # CELL_INST_RE never matches → false TOO_FEW_CELLS / total_cells=0.
        stripped_nc = _YOSYS_BLOCK_COMMENT_RE.sub(" ", stripped).strip()
        m = CELL_INST_RE.match(stripped_nc) or CELL_INST_RE.match(stripped)
        if m:
            cell_type = m.group(1)
            # v1.6.195 (#82 P0) — yosys escaped-identifier `\$_*_`
            # and bare `$_*_` are the same cell type; dedup by
            # stripping any leading backslash before keying.
            canonical = cell_type.lstrip("\\")
            if canonical.lower() not in VERILOG_KEYWORDS:
                cell_counts[canonical] = cell_counts.get(canonical, 0) + 1

    total = sum(cell_counts.values())
    return total, cell_counts


# Sequential-cell fingerprint: yosys `$_DFF_*_` / `$_SDFF*_` / `$_DLATCH*_`
# primitives and PDK flop/latch cell names (…dfxtp…, …sdf…, …latch…).
# chip-AGNOSTIC: structural cell-family vocabulary, not a chip class.
_SEQ_CELL_RE = re.compile(r"(?i)(?:\$_S?DFF|\$_DLATCH|\$_SR|dff|sdf|latch)")

# RTL register declaration: `reg [h:l] name` / `reg name` (also `logic`).
_RTL_REG_DECL_RE = re.compile(
    r"^\s*(?:output\s+)?(?:reg|logic)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?"
    r"\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)", re.MULTILINE)
_RTL_NB_ASSIGN_RE = re.compile(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=")


def rtl_declared_register_bits(rtl_texts: List[str]) -> int:
    """Best-effort total bit count of RTL registers that are actually
    nonblocking-assigned somewhere (a `reg` used purely combinationally
    does not demand a flop). Used by the structure-aware floor (#427)."""
    total = 0
    for text in rtl_texts:
        assigned = set(_RTL_NB_ASSIGN_RE.findall(text))
        for m in _RTL_REG_DECL_RE.finditer(text):
            hi, lo, names = m.group(1), m.group(2), m.group(3)
            width = abs(int(hi) - int(lo)) + 1 if hi is not None else 1
            for nm in (n.strip() for n in names.split(",")):
                if nm in assigned:
                    total += width
    return total


def _outputs_tied_constant(text: str) -> List[str]:
    """Output ports of the FIRST module whose only drivers are constant
    assigns (`assign y = 1'b0;` / `1'hx`) — the real pruned-stub signature.
    Returns the constant-tied output names ONLY when every driven output is
    constant-tied (a partially-constant design is legitimate)."""
    # output declarations appear both as standalone lines AND inside the
    # module header port list (ANSI style) — no line anchor.
    outs = re.findall(r"\boutput\s+(?:reg\s+|wire\s+)?(?:\[[^\]]*\]\s*)?"
                      r"([A-Za-z_]\w*)", text)
    if not outs:
        return []
    const_tied, otherwise_driven = [], []
    for o in outs:
        drivers = re.findall(
            r"^\s*assign\s+" + re.escape(o) + r"\s*(?:\[[^\]]*\])?\s*=\s*([^;]+);",
            text, re.MULTILINE)
        if not drivers:
            otherwise_driven.append(o)   # cell-driven or undriven: not const
            continue
        if all(re.fullmatch(r"\s*\d+'[bhd][0-9a-fxz_]+\s*", d) for d in drivers):
            const_tied.append(o)
        else:
            otherwise_driven.append(o)
    return const_tied if const_tied and not otherwise_driven else []


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_netlist(
    netlist_path: Path,
    min_cells: int = 10,
    rtl_paths: List[Path] = (),
) -> Tuple[List[Finding], dict]:
    """Check netlist existence, freshness vs RTL, and structural substance.

    Returns (findings, stats).
    """
    findings: List[Finding] = []
    stats = {
        "file_exists": False,
        "file_size_bytes": 0,
        "has_module": False,
        "total_cells": 0,
        "unique_cell_types": 0,
        "cell_type_counts": {},
        "sequential_cells": 0,
        "rtl_register_bits": None,
        "outputs_tied_constant": [],
        "stale_vs_rtl": False,
    }

    # Check file exists
    if not netlist_path.exists():
        findings.append(Finding(
            severity="ERROR",
            category="MISSING_NETLIST",
            message=f"Netlist file not found: {netlist_path}",
        ))
        return findings, stats

    stats["file_exists"] = True
    stats["file_size_bytes"] = netlist_path.stat().st_size

    # Staleness guard (#426): a netlist OLDER than any RTL file it is judged
    # against is the previous run's ghost — a close-loop re-gate must refuse
    # it instead of grading the pre-edit design.
    rtl_files = [p for p in rtl_paths if p.is_file()]
    if rtl_files:
        nl_mtime = netlist_path.stat().st_mtime
        stale_against = [str(p) for p in rtl_files
                         if p.stat().st_mtime > nl_mtime]
        if stale_against:
            stats["stale_vs_rtl"] = True
            findings.append(Finding(
                severity="ERROR",
                category="STALE_NETLIST",
                message=(
                    f"Netlist is OLDER than the RTL it is judged against — "
                    f"re-run synthesis before gating (judging a re-gated "
                    f"design on the prior run's netlist grades ghost data)."),
                details=f"newer RTL: {stale_against}",
            ))
            return findings, stats

    # Read file
    text = netlist_path.read_text(errors='replace')

    # Check for empty
    non_comment_lines = [
        l for l in text.split('\n')
        if l.strip() and not l.strip().startswith('//')
    ]
    if not non_comment_lines:
        findings.append(Finding(
            severity="ERROR",
            category="EMPTY_NETLIST",
            message="Netlist file is empty or contains only comments",
        ))
        return findings, stats

    # Check for module definition
    modules = MODULE_RE.findall(text)
    stats["has_module"] = len(modules) > 0
    if not modules:
        findings.append(Finding(
            severity="ERROR",
            category="NO_MODULE",
            message="No module definition found in netlist",
        ))
        return findings, stats

    # Count cells
    total_cells, cell_counts = count_cell_instances(text)
    stats["total_cells"] = total_cells
    stats["unique_cell_types"] = len(cell_counts)
    stats["cell_type_counts"] = cell_counts

    if total_cells == 0:
        # v1.6.194 (#81 P1) — detect yosys expression-form output.
        # When yosys' write_verilog emits cells as `assign x = ~(...);`
        # / `always @(posedge clk) ...` instead of `$_NAND_` /
        # `$_DFF_*_` cell-instance lines, the netlist passes
        # signature checks (module + body content) but our cell
        # counter sees zero. The structural fingerprint of
        # expression-form output: ≥1 `always` keyword AND ≥1 `assign`
        # AND zero `$_*_` literals. When this pattern hits, point
        # the reviewer at the write_verilog flag rather than just
        # reporting an opaque "no cell instances".
        # chip-AGNOSTIC: purely structural detection of yosys
        # writer-flag-induced expression form.
        _expr_form = (
            re.search(r"^\s*always\b", text, re.MULTILINE) is not None
            and re.search(r"^\s*assign\s+", text,
                          re.MULTILINE) is not None
            and "$_" not in text
        )
        if _expr_form:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_NETLIST",
                message=(
                    "Netlist has module + assign/always content but "
                    "ZERO `$_*_` primitive cell instances — yosys "
                    "expression-form output detected. Add `-noexpr` "
                    "to the `write_verilog` invocation so primitives "
                    "are emitted as cell instances (see v1.6.194 / "
                    "#81 P0 — `-nostr` is NOT the right flag; "
                    "`-noexpr` is)."),
            ))
        else:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_NETLIST",
                message="Netlist contains a module definition but no cell instances",
            ))
    elif total_cells < min_cells:
        # Structure-aware floor (#427). A retry cannot grow a correct tiny
        # design, so a flat-count ERROR is unactionable; vouch structurally
        # first, hard-fail only on the real stub signatures, and otherwise
        # disclose as a WARNING.
        seq_cells = sum(c for t, c in cell_counts.items()
                        if _SEQ_CELL_RE.search(t))
        stats["sequential_cells"] = seq_cells
        const_outs = _outputs_tied_constant(text)
        stats["outputs_tied_constant"] = const_outs
        rtl_bits = None
        if rtl_files:
            rtl_bits = rtl_declared_register_bits(
                [p.read_text(errors="replace") for p in rtl_files])
            stats["rtl_register_bits"] = rtl_bits
        if const_outs:
            # (b) the real pruned-stub signature: every output constant-tied
            findings.append(Finding(
                severity="ERROR",
                category="OUTPUTS_TIED_CONSTANT",
                message=(
                    f"All module outputs are tied to constants "
                    f"({const_outs}) — synth pruned the design to a stub."),
                details=f"Cell types: {dict(sorted(cell_counts.items()))}",
            ))
        elif rtl_bits is not None and rtl_bits > 0 and seq_cells >= rtl_bits:
            # (a) sequential cells cover the RTL's register bits — a shift
            # register legitimately synthesizes to exactly its DFFs. PASS.
            findings.append(Finding(
                severity="INFO",
                category="TINY_DESIGN_VOUCHED",
                message=(
                    f"{total_cells} cells < min_cells={min_cells}, but "
                    f"sequential cells ({seq_cells}) cover the RTL's "
                    f"declared register bits ({rtl_bits}) — legitimately "
                    f"tiny design, structure-aware floor PASS."),
            ))
        else:
            # (c) cannot vouch structurally: disclose, do not block — the
            # flat count alone is not evidence of a stub (#427).
            findings.append(Finding(
                severity="WARNING",
                category="TOO_FEW_CELLS",
                message=(
                    f"Netlist has {total_cells} cell instance(s), below the "
                    f"advisory floor of {min_cells} — review whether the "
                    f"design is legitimately tiny (pass --rtl to let the "
                    f"structure-aware floor vouch via register-bit cover)."),
                details=f"Cell types: {dict(sorted(cell_counts.items()))}",
            ))

    return findings, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], stats: dict,
                 netlist_path: str, min_cells: int) -> dict:
    n_err = sum(1 for f in findings if f.severity == "ERROR")
    return {
        "program": "synth_netlist_check",
        "version": "1.1.0",
        "netlist": netlist_path,
        "min_cells": min_cells,
        "summary": {
            "file_exists": stats["file_exists"],
            "total_cells": stats["total_cells"],
            "unique_cell_types": stats["unique_cell_types"],
            "findings_count": len(findings),
            "error_count": n_err,
            # since v1.1.0 (#427): WARNING/INFO findings no longer fail the gate —
            # pass = no ERROR (TOO_FEW_CELLS alone is advisory now).
            "pass": n_err == 0,
        },
        "stats": stats,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify synthesis netlist exists and has reasonable cell count"
    )
    parser.add_argument('--netlist', required=True,
                        help="Path to synthesized Verilog netlist")
    parser.add_argument('--min-cells', type=int, default=10,
                        help="Advisory cell-count floor (default: 10)")
    parser.add_argument('--rtl', nargs='*', default=[],
                        help="RTL source files the netlist is judged against "
                             "(enables the staleness guard #426 and the "
                             "register-bit structure-aware floor #427)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    netlist_path = Path(args.netlist)
    findings, stats = audit_netlist(netlist_path, args.min_cells,
                                    [Path(p) for p in args.rtl])

    report = build_report(findings, stats, str(netlist_path), args.min_cells)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
