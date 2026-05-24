#!/usr/bin/env python3
"""
Branch Coverage Instrumentation Generator
==========================================
Parses an RTL SystemVerilog file, finds all if/else and case branches,
and generates a companion coverage module that tracks which branches
have been exercised during BIST.

Each branch in the DUT's RTL gets a 1-bit flag that latches when that
branch condition is taken. After BIST, read out the bitmap to compute
coverage %.

Usage:
    python3 branch_coverage_gen.py --rtl path/to/module.sv --output path/to/module_branch_cov.sv
    python3 branch_coverage_gen.py --rtl path/to/module.sv  # output to same dir

Generated module interface:
    - clk, rst_n, cov_reset        : control signals
    - <condition signals>           : wired from DUT internals/outputs
    - cov_bits [N-1:0]             : one bit per branch (latching)
    - cov_count                     : popcount of covered bits
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class Branch:
    """Represents a single branch in the RTL."""
    index: int
    description: str
    condition: str          # SystemVerilog condition expression
    branch_type: str        # 'if', 'else_if', 'else', 'case_item', 'default'
    line_number: int = 0
    module_name: str = ""
    parent_construct: str = ""  # enclosing if/case description

    def __repr__(self):
        return f"Branch({self.index}: {self.branch_type} @ line {self.line_number}: {self.description})"


@dataclass
class PortInfo:
    """Port parsed from RTL module."""
    name: str
    direction: str   # "input" or "output"
    width: int = 1
    msb: int = 0
    lsb: int = 0


@dataclass
class ModuleInfo:
    """Parsed module information."""
    name: str
    ports: List[PortInfo] = field(default_factory=list)
    branches: List[Branch] = field(default_factory=list)
    source_file: str = ""


# ============================================================================
# RTL Parser
# ============================================================================

def strip_comments(text: str) -> str:
    """Remove // and /* */ comments from SystemVerilog source."""
    # Remove block comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Remove line comments
    text = re.sub(r'//[^\n]*', '', text)
    return text


def parse_module_header(text: str) -> Optional[Tuple[str, List[PortInfo]]]:
    """Parse the first module's name and ports from RTL source."""
    # Find module declaration
    mod_match = re.search(
        r'module\s+(\w+)\s*(?:#\s*\(.*?\))?\s*\((.*?)\)\s*;',
        text, re.DOTALL
    )
    if not mod_match:
        return None

    mod_name = mod_match.group(1)
    port_block = mod_match.group(2)

    ports = []
    # Match port declarations: input/output [wire|logic] [msb:lsb] name
    port_pattern = re.compile(
        r'(input|output|inout)\s+(?:wire|logic|reg)?\s*'
        r'(?:\[(\d+):(\d+)\]\s*)?(\w+)',
        re.MULTILINE
    )
    for m in port_pattern.finditer(port_block):
        direction = m.group(1)
        msb = int(m.group(2)) if m.group(2) else 0
        lsb = int(m.group(3)) if m.group(3) else 0
        name = m.group(4)
        width = abs(msb - lsb) + 1 if m.group(2) else 1
        ports.append(PortInfo(name=name, direction=direction,
                              width=width, msb=msb, lsb=lsb))

    return mod_name, ports


def find_branches(text: str, module_name: str = "") -> List[Branch]:
    """
    Parse RTL source and extract all if/else/case branches.
    Returns a list of Branch objects with sequential indices.
    """
    branches = []
    lines = text.split('\n')
    branch_idx = 0

    # Track nesting for context
    in_always = False
    always_type = ""

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track always blocks
        if re.match(r'always\s*@|always_ff|always_comb|always_latch', stripped):
            in_always = True
            always_type = stripped.split()[0] if stripped.split() else "always"

        # ----- if statements -----
        if_match = re.match(r'(?:end\s+)?if\s*\((.+?)\)\s*(?:begin)?', stripped)
        if if_match:
            condition = if_match.group(1).strip()
            branches.append(Branch(
                index=branch_idx,
                description=f"if ({condition})",
                condition=condition,
                branch_type='if',
                line_number=line_num,
                module_name=module_name,
            ))
            branch_idx += 1
            continue

        # ----- else if -----
        elif_match = re.match(
            r'(?:end\s+)?else\s+if\s*\((.+?)\)\s*(?:begin)?', stripped
        )
        if elif_match:
            condition = elif_match.group(1).strip()
            branches.append(Branch(
                index=branch_idx,
                description=f"else if ({condition})",
                condition=condition,
                branch_type='else_if',
                line_number=line_num,
                module_name=module_name,
            ))
            branch_idx += 1
            continue

        # ----- else -----
        else_match = re.match(r'(?:end\s+)?else\s*(?:begin)?$', stripped)
        if else_match:
            branches.append(Branch(
                index=branch_idx,
                description="else (default path)",
                condition="/* else */",
                branch_type='else',
                line_number=line_num,
                module_name=module_name,
            ))
            branch_idx += 1
            continue

        # ----- case statements -----
        case_match = re.match(
            r'(?:unique\s+)?(?:priority\s+)?case[xz]?\s*\((.+?)\)',
            stripped
        )
        if case_match:
            case_expr = case_match.group(1).strip()
            # Read subsequent lines for case items until endcase
            continue

        # ----- case items -----
        # Match patterns like: 4'b0001: begin  or  VALUE:  or  default:
        case_item_match = re.match(
            r"(\d+'[bhdo][\w?xz]+|[\w']+)\s*:\s*(?:begin)?", stripped
        )
        if case_item_match and not stripped.startswith('//'):
            value = case_item_match.group(1).strip()
            if value.lower() != 'default':
                branches.append(Branch(
                    index=branch_idx,
                    description=f"case item: {value}",
                    condition=f"/* case == {value} */",
                    branch_type='case_item',
                    line_number=line_num,
                    module_name=module_name,
                ))
                branch_idx += 1

        # ----- default case -----
        default_match = re.match(r'default\s*:', stripped)
        if default_match:
            branches.append(Branch(
                index=branch_idx,
                description="case default",
                condition="/* default */",
                branch_type='default',
                line_number=line_num,
                module_name=module_name,
            ))
            branch_idx += 1

    return branches


def extract_condition_signals(branches: List[Branch],
                              ports: List[PortInfo]) -> List[str]:
    """
    Extract the set of signal names referenced in branch conditions.
    These will become inputs to the coverage module.
    """
    all_port_names = {p.name for p in ports}
    signals = set()

    for b in branches:
        cond = b.condition
        # Extract identifiers from condition
        ids = re.findall(r'\b([a-zA-Z_]\w*)\b', cond)
        for ident in ids:
            # Skip SystemVerilog keywords and numeric literals
            if ident in ('begin', 'end', 'if', 'else', 'case', 'default',
                         'posedge', 'negedge', 'always', 'assign',
                         'logic', 'wire', 'reg', 'int', 'integer'):
                continue
            if ident in all_port_names:
                signals.add(ident)

    # Also add all ports as potential condition signals
    for p in ports:
        signals.add(p.name)

    return sorted(signals)


# ============================================================================
# Coverage Module Generator
# ============================================================================

def generate_branch_coverage_sv(module_info: ModuleInfo,
                                 condition_signals: List[str]) -> str:
    """
    Generate a SystemVerilog branch coverage module.

    The module has:
    - clk, rst_n, cov_reset inputs
    - One input per DUT condition signal
    - cov_bits output (one bit per branch, latching)
    - cov_count output (popcount)
    """
    mod = module_info
    n_branches = len(mod.branches)
    if n_branches == 0:
        n_branches = 1  # minimum 1 bit

    # Calculate bit widths
    bits_width = n_branches
    count_bits = (n_branches - 1).bit_length() + 1 if n_branches > 1 else 2

    # Build port list for condition signals
    port_lines = []
    for sig in condition_signals:
        # Find width from original ports
        width = 1
        for p in mod.ports:
            if p.name == sig:
                width = p.width
                break
        if width > 1:
            port_lines.append(f"    input logic [{width-1}:0] {sig},")
        else:
            port_lines.append(f"    input logic {sig},")

    ports_str = "\n".join(port_lines)

    # Build branch definitions comment
    branch_defs = []
    for b in mod.branches:
        branch_defs.append(
            f"    // [{b.index:2d}] Line {b.line_number:4d}: "
            f"{b.branch_type:10s} — {b.description}"
        )
    branch_defs_str = "\n".join(branch_defs)

    # Build coverage latch logic
    latch_lines = []
    for b in mod.branches:
        cond = b.condition
        if b.branch_type == 'else':
            # 'else' is taken when none of the prior if/else-if were taken
            # We approximate: the else bit latches when the coverage module
            # observes it (needs external signal). Use a placeholder.
            latch_lines.append(
                f"            // [{b.index}] {b.description} "
                f"(latches via external observation)"
            )
            latch_lines.append(
                f"            // cov_bits[{b.index}] is set by external "
                f"logic or wrapper"
            )
        elif b.branch_type == 'default':
            latch_lines.append(
                f"            // [{b.index}] {b.description} "
                f"(case default — set by external observation)"
            )
        elif b.branch_type in ('if', 'else_if'):
            # Clean up condition for use in coverage
            clean_cond = cond
            # Replace !rst_n style with actual signal checks
            latch_lines.append(
                f"            if ({clean_cond}) "
                f"cov_bits[{b.index}] <= 1'b1;  "
                f"// {b.description}"
            )
        elif b.branch_type == 'case_item':
            latch_lines.append(
                f"            // [{b.index}] {b.description}"
            )
        else:
            latch_lines.append(
                f"            // [{b.index}] {b.description}"
            )

    latch_str = "\n".join(latch_lines)

    # Generate the module
    sv = f"""\
// ============================================================================
// {mod.name}_branch_cov — Auto-generated Branch Coverage Module
// ============================================================================
// Source: {mod.source_file}
// Total branches detected: {n_branches}
//
// Each bit in cov_bits latches to 1 when the corresponding branch
// condition is observed TRUE. After BIST, read cov_bits to determine
// which RTL branches were exercised.
//
// Usage:
//   - Wire DUT condition signals to this module's inputs
//   - After BIST completes, read cov_bits and cov_count
//   - cov_reset clears all coverage bits for a new run
// ============================================================================

module {mod.name}_branch_cov (
    input logic clk,
    input logic rst_n,
    input logic cov_reset,

    // DUT condition signals
{ports_str}

    // Coverage bitmap output
    output logic [{bits_width - 1}:0] cov_bits,
    output logic [{count_bits - 1}:0] cov_count
);

    // ========================================================================
    // Branch Definitions
    // ========================================================================
{branch_defs_str}

    // ========================================================================
    // Coverage Latch Logic
    // ========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n || cov_reset) begin
            cov_bits <= {bits_width}'d0;
        end else begin
{latch_str}
        end
    end

    // ========================================================================
    // Popcount: count number of covered branches
    // ========================================================================
    always_comb begin
        cov_count = {count_bits}'d0;
        for (int i = 0; i < {bits_width}; i++) begin
            if (cov_bits[i]) cov_count = cov_count + {count_bits}'d1;
        end
    end

endmodule
"""
    return sv


def generate_report_header(module_info: ModuleInfo) -> str:
    """Generate a human-readable branch coverage report header."""
    mod = module_info
    lines = [
        f"# Branch Coverage Report: {mod.name}",
        f"# Source: {mod.source_file}",
        f"# Total branches: {len(mod.branches)}",
        f"#",
        f"# {'Idx':>3s}  {'Type':10s}  {'Line':>5s}  Description",
        f"# {'---':>3s}  {'----':10s}  {'----':>5s}  -----------",
    ]
    for b in mod.branches:
        lines.append(
            f"# {b.index:3d}  {b.branch_type:10s}  "
            f"{b.line_number:5d}  {b.description}"
        )
    lines.append(f"#")
    lines.append(f"# Coverage = (popcount of cov_bits) / {len(mod.branches)} * 100%")
    return "\n".join(lines) + "\n"


# ============================================================================
# Main entry point
# ============================================================================

def parse_rtl_file(rtl_path: str) -> Optional[ModuleInfo]:
    """Parse an RTL file and return ModuleInfo with branches."""
    if not os.path.isfile(rtl_path):
        print(f"ERROR: File not found: {rtl_path}", file=sys.stderr)
        return None

    with open(rtl_path, 'r') as f:
        raw_text = f.read()

    clean_text = strip_comments(raw_text)
    result = parse_module_header(clean_text)
    if not result:
        print(f"ERROR: No module declaration found in {rtl_path}",
              file=sys.stderr)
        return None

    mod_name, ports = result
    branches = find_branches(clean_text, mod_name)

    return ModuleInfo(
        name=mod_name,
        ports=ports,
        branches=branches,
        source_file=rtl_path,
    )


def generate(rtl_path: str, output_path: Optional[str] = None) -> Tuple[str, str]:
    """
    Main generation function.
    Returns (sv_content, report_header) or raises on error.
    """
    module_info = parse_rtl_file(rtl_path)
    if module_info is None:
        raise ValueError(f"Failed to parse RTL file: {rtl_path}")

    cond_signals = extract_condition_signals(
        module_info.branches, module_info.ports
    )
    sv_content = generate_branch_coverage_sv(module_info, cond_signals)
    report = generate_report_header(module_info)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(sv_content)
        print(f"Generated: {output_path}")

        # Write report header alongside
        report_path = output_path.replace('.sv', '_report.txt')
        with open(report_path, 'w') as f:
            f.write(report)
        print(f"Report:    {report_path}")

    return sv_content, report


def main():
    parser = argparse.ArgumentParser(
        description='Branch Coverage Instrumentation Generator')
    parser.add_argument('--rtl', required=True,
                        help='Path to RTL .sv file')
    parser.add_argument('--output', default=None,
                        help='Output path for coverage module .sv file')
    args = parser.parse_args()

    if args.output is None:
        base = os.path.splitext(args.rtl)[0]
        args.output = f"{base}_branch_cov.sv"

    try:
        sv_content, report = generate(args.rtl, args.output)
        print(f"\nBranch coverage summary:")
        print(report)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
