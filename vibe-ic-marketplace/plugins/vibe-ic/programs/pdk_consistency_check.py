#!/usr/bin/env python3
"""
pdk_consistency_check.py — Deterministic PDK-netlist consistency checker.

Verifies that every cell instantiated in a synthesized netlist exists in the
specified PDK liberty files. This catches a common failure mode where the
synthesis tool targeted a different PDK than the one specified in project.json
(e.g., GF180 cells appearing in a SKY130 project).

What it catches:
  1. CELL_NOT_IN_PDK — a cell instance in the netlist has no matching cell
     definition in any of the provided liberty files.
  2. NO_CELLS — the netlist contains no cell instances at all.
  3. PDK_MISMATCH — summary when cells from a different PDK family are detected.

Usage:
    python3 pdk_consistency_check.py \\
        --netlist synth/netlist.v \\
        --project-json input/project.json \\
        --pdk-lib input/pdk/liberty/*.lib

Exit codes:
    0 = all netlist cells found in liberty
    1 = mismatch detected (cells not in PDK, or no cells found)
    2 = parse error / invalid arguments

Generality: works for ANY Verilog gate-level netlist and ANY liberty file set.
No external tool dependencies — pure Python parsing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # CELL_NOT_IN_PDK, NO_CELLS, PDK_MISMATCH
    cell_name: str
    message: str
    line: int = 0
    file: str = ""


# ---------------------------------------------------------------------------
# Parsing: netlist cell extraction
# ---------------------------------------------------------------------------
# Matches cell instantiation lines like:
#   sky130_fd_sc_hd__inv_2 _42_ (.A(net1), .Y(net2));
#   INVD1 U17 ( .I(n1), .ZN(n2) );
#   gf180mcu_fd_sc_mcu7t5v0__buf_1 _123_ (.I(a), .Z(b));
# Does NOT match:
#   module my_mod (...);
#   wire [7:0] data;
#   assign x = y;

# Verilog keywords that are NOT cell types
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
CELL_INST_RE = re.compile(
    r'^\s*(\w+)\s+(\w+)\s*\(',
    re.MULTILINE
)


def extract_netlist_cells(netlist_text: str, file_path: str = "") -> List[dict]:
    """Extract cell instantiations from a gate-level Verilog netlist.

    Returns list of dicts with keys: cell_name, instance_name, line.
    """
    cells = []
    lines = netlist_text.split('\n')
    in_module_header = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//'):
            continue

        # Track module header (ports section) — don't parse ports as cells
        if re.match(r'^\s*module\s+', stripped):
            # If the header closes on the same line, no need to enter header mode
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

        m = CELL_INST_RE.match(stripped)
        if m:
            cell_type = m.group(1)
            inst_name = m.group(2)
            # Filter out Verilog keywords
            if cell_type.lower() not in VERILOG_KEYWORDS:
                cells.append({
                    'cell_name': cell_type,
                    'instance_name': inst_name,
                    'line': i,
                    'file': file_path,
                })

    return cells


# ---------------------------------------------------------------------------
# Parsing: liberty cell extraction
# ---------------------------------------------------------------------------
LIBERTY_CELL_RE = re.compile(r'^\s*cell\s*\(\s*"?(\w+)"?\s*\)', re.MULTILINE)


def extract_liberty_cells(lib_text: str) -> Set[str]:
    """Extract all cell names from a liberty (.lib) file."""
    return set(LIBERTY_CELL_RE.findall(lib_text))


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_pdk_consistency(
    netlist_cells: List[dict],
    pdk_cells: Set[str],
    pdk_name: str = "",
) -> List[Finding]:
    """Check that all netlist cells exist in the PDK cell library.

    Returns list of findings. Empty list = PASS.
    """
    findings: List[Finding] = []

    if not netlist_cells:
        findings.append(Finding(
            severity="ERROR",
            category="NO_CELLS",
            cell_name="",
            message="Netlist contains no cell instances",
        ))
        return findings

    if not pdk_cells:
        findings.append(Finding(
            severity="ERROR",
            category="NO_CELLS",
            cell_name="",
            message="No cells found in PDK liberty files",
        ))
        return findings

    # Check each unique cell
    unique_cells = {}
    for c in netlist_cells:
        name = c['cell_name']
        if name not in unique_cells:
            unique_cells[name] = c

    missing = []
    for cell_name, info in sorted(unique_cells.items()):
        if cell_name not in pdk_cells:
            missing.append(cell_name)
            findings.append(Finding(
                severity="ERROR",
                category="CELL_NOT_IN_PDK",
                cell_name=cell_name,
                message=f"Cell '{cell_name}' not found in PDK liberty",
                line=info.get('line', 0),
                file=info.get('file', ''),
            ))

    if missing:
        findings.append(Finding(
            severity="ERROR",
            category="PDK_MISMATCH",
            cell_name="",
            message=(
                f"{len(missing)} cell type(s) not found in PDK"
                + (f" ({pdk_name})" if pdk_name else "")
                + f": {', '.join(sorted(missing)[:10])}"
                + ("..." if len(missing) > 10 else "")
            ),
        ))

    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], netlist_path: str,
                 pdk_name: str, total_cells: int,
                 unique_cells: int, pdk_cell_count: int) -> dict:
    """Build JSON report."""
    return {
        "program": "pdk_consistency_check",
        "version": "1.0.0",
        "netlist": netlist_path,
        "pdk": pdk_name,
        "summary": {
            "total_cell_instances": total_cells,
            "unique_cell_types": unique_cells,
            "pdk_cell_count": pdk_cell_count,
            "findings_count": len(findings),
            "pass": len(findings) == 0,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify synthesis netlist cells match PDK liberty files"
    )
    parser.add_argument('--netlist', required=True,
                        help="Path to synthesized Verilog netlist")
    parser.add_argument('--project-json', required=False, default=None,
                        help="Path to project.json (for PDK name extraction)")
    parser.add_argument('--pdk-lib', nargs='+', required=True,
                        help="Path(s) to PDK liberty (.lib) files")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    # Read netlist
    netlist_path = Path(args.netlist)
    if not netlist_path.exists():
        print(f"ERROR: Netlist file not found: {netlist_path}", file=sys.stderr)
        return 2

    netlist_text = netlist_path.read_text(errors='replace')

    # Read project.json for PDK name
    pdk_name = ""
    if args.project_json:
        pj_path = Path(args.project_json)
        if pj_path.exists():
            try:
                pj = json.loads(pj_path.read_text())
                pdk_name = pj.get("pdk", pj.get("target_pdk", ""))
            except json.JSONDecodeError:
                pass

    # Read liberty files
    pdk_cells: Set[str] = set()
    for lib_path_str in args.pdk_lib:
        lib_path = Path(lib_path_str)
        if not lib_path.exists():
            print(f"WARNING: Liberty file not found: {lib_path}", file=sys.stderr)
            continue
        lib_text = lib_path.read_text(errors='replace')
        pdk_cells.update(extract_liberty_cells(lib_text))

    # Extract and audit
    netlist_cells = extract_netlist_cells(netlist_text, str(netlist_path))
    findings = audit_pdk_consistency(netlist_cells, pdk_cells, pdk_name)

    unique_cell_names = set(c['cell_name'] for c in netlist_cells)
    report = build_report(
        findings, str(netlist_path), pdk_name,
        total_cells=len(netlist_cells),
        unique_cells=len(unique_cell_names),
        pdk_cell_count=len(pdk_cells),
    )

    # Output
    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)

    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
