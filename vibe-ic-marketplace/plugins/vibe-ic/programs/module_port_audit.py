#!/usr/bin/env python3
"""
module_port_audit.py — Deterministic port-name mismatch detector for multi-module
Verilog/SystemVerilog designs.

Detects the #1 cause of failure in v0.36: port name mismatches between a
top-level integration module and its submodule instantiations. When multiple
agents independently generate RTL modules and a separate agent generates the
integration (DTOP) module, port names can silently diverge. Quartus and other
synthesis tools compile with 0 errors because unconnected ports are silently
ignored — but the design doesn't work.

What it catches:
  1. MISMATCH — an instantiation references a port name that doesn't exist
     in the module's port declaration (e.g., `.sys_clk_5m(...)` but the module
     has no `sys_clk_5m` port)
  2. UNCONNECTED — a module port that is never connected in any instantiation
     across the design (potential integration oversight)
  3. WIDTH_MISMATCH — the width of a port connection doesn't match the port
     declaration (e.g., connecting 8-bit wire to a 1-bit port)

Usage:
    python3 module_port_audit.py --rtl-dir ./rtl/ --top-module OUR_DTOP --out-dir /tmp/audit

Exit codes:
    0 = no findings
    1 = findings issued (MISMATCH or UNCONNECTED detected)
    2 = parse error / invalid arguments

Generality: works for ANY multi-module Verilog/SystemVerilog design.
No external tool dependencies — pure Python regex parsing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class PortDecl:
    """A single port declaration extracted from a module definition."""
    name: str
    direction: str          # input / output / inout
    width: int              # bit-width (1 for scalar)
    width_expr: str         # original width expression, e.g. "[7:0]" or ""
    line: int               # line number in source file
    file: str               # source file path
    # The DECLARED type token, when the declaration names one:
    # `tlul_pkg::tl_h2d_t`, `prim_alert_pkg::alert_tx_t`, `ctrl_fsm_e`.
    # The ANSI parser's regex has always captured this group (it had to, to
    # stop package-qualified types from eating the port NAME — see the
    # comment on the `type` group below); it then threw the value away, so
    # every consumer that asked "what IS this port" got `width=1` for a
    # 100-bit struct. Empty string when the declaration names no type
    # (`input logic clk_i`) — never None, so a consumer can test it plainly.
    data_type: str = ""


@dataclass
class PortConnection:
    """A single .port_name(wire_expr) connection inside a module instantiation."""
    port_name: str          # name used in .port_name(...)
    wire_expr: str          # the expression connected to the port
    line: int
    file: str


@dataclass
class ModuleInstance:
    """A module instantiation found in the design."""
    module_name: str        # the module type being instantiated
    instance_name: str      # the instance label
    connections: List[PortConnection]
    is_implicit: bool       # True if .* was used
    line: int
    file: str


@dataclass
class ModuleDef:
    """A parsed module definition."""
    name: str
    ports: Dict[str, PortDecl]   # port_name -> PortDecl
    parameters: List[str]        # parameter names
    instances: List[ModuleInstance]  # sub-module instantiations
    file: str
    line: int


@dataclass
class Finding:
    """A single audit finding."""
    severity: str           # ERROR / WARN / INFO
    rule: str               # mismatch / unconnected / width-mismatch
    module: str             # module where the issue is found
    instance: str           # instance name (for mismatch) or ""
    port: str               # the port name in question
    message: str
    file: str
    line: int


# ---------------------------------------------------------------------------
# Comment stripping (shared pattern with rtl_hygiene_lint.py)
# ---------------------------------------------------------------------------
def strip_preproc_directives(src: str) -> str:
    """Blank out `` `ifdef`` / `` `endif`` / `` `else`` style lines, keeping the
    line count so reported line numbers stay right.

    A conditional block INSIDE a port list broke the parser completely. The
    directive lines take part in the comma split, produce fragments the anchored
    port pattern cannot match, and every port after the block disappears from
    the module's declared set — so each instantiation connecting one reports
    `Port '.x' … does not exist`.

    MEASURED on `ibex_core.sv`, which opens an `` `ifdef RVFI`` block at line 101:
    `parse_port_list_ansi` returned ONE port (`clk`) out of the whole header, and
    `.fetch_enable_i` — declared at line 104 — read as missing.

    Blanked rather than deleted: the CONDITIONAL ports are kept (they are real
    ports under some configuration, and this audit compares NAMES, not the
    active configuration), only the directive lines themselves go. Evaluating
    the conditions would need a define set this program does not have and must
    not invent — taking both arms is the conservative reading for a check whose
    finding is "this name is not declared anywhere".
    """
    out = []
    for line in src.split('\n'):
        out.append('' if line.lstrip().startswith('`') else line)
    return '\n'.join(out)


def strip_comments(src: str) -> str:
    """Remove // line comments and /* block */ comments, preserving newlines."""
    out = []
    i = 0
    while i < len(src):
        # String literals — skip over so we don't treat // inside strings as comments
        if src[i] == '"':
            j = i + 1
            while j < len(src) and src[j] != '"':
                if src[j] == '\\':
                    j += 1
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src[i:i + 2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end + 2]))
            i = end + 2
        elif src[i:i + 2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ---------------------------------------------------------------------------
# Width expression evaluation
# ---------------------------------------------------------------------------
#: One bracketed dimension, e.g. `[7:0]`. Used to walk a packed range list.
_DIM_RE = re.compile(r'\[[^\]]*\]')
#: A dimension whose bounds are both literal, so its size is known statically.
_NUMERIC_DIM_RE = re.compile(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]')


def eval_width_expr(expr: str) -> int:
    """
    Evaluate a Verilog width expression like [7:0] -> 8, [15:0] -> 16.
    Returns 1 for scalar (no range). Returns -1 if the expression contains
    parameters or cannot be evaluated.

    MULTI-DIMENSIONAL packed ranges multiply: `[3:0][3:0][7:0]` is 128 bits, as
    on `aes_sub_bytes.data_i`. This used `re.match`, which reads the FIRST
    dimension and stops — so widening the port pattern to accept the extra
    dimensions without this would have traded a MISSING port for a port carried
    at 4 bits instead of 128, and a wrong width is a false width-mismatch
    rather than a false does-not-exist. Same class of bogus finding, different
    message.

    A single non-literal dimension makes the whole product unknown, so it
    returns -1 rather than the product of the dimensions it could read.
    """
    expr = expr.strip()
    if not expr:
        return 1
    dims = _DIM_RE.findall(expr)
    if not dims:
        # Not a range at all — parameterized or complex expression.
        return -1
    total = 1
    for dim in dims:
        m = _NUMERIC_DIM_RE.fullmatch(dim.strip())
        if not m:
            return -1
        hi, lo = int(m.group(1)), int(m.group(2))
        total *= abs(hi - lo) + 1
    return total


# ---------------------------------------------------------------------------
# Verilog parser (regex-based, general purpose)
# ---------------------------------------------------------------------------
#: A module-level package import. Its `;` must not be read as the end of the
#: module header — see the comment at the header scan.
_IMPORT_LINE_RE = re.compile(r'\s*import\s+[\w:]+\s*(?:::\s*\*)?\s*;')

#: A package-import clause anywhere on a line, including the comma list form
#: `import a::*, b::pkg;`. Anchored on the `import` KEYWORD rather than on the
#: start of the line, because SystemVerilog permits the clause to sit on the
#: same line as the module name.
_IMPORT_CLAUSE_RE = re.compile(r'\bimport\s+[\w:*]+(?:\s*,\s*[\w:*]+)*\s*;')


def header_ends_on(line: str) -> bool:
    """Does this line carry the `;` that CLOSES a module header?

    A package import ends in `;` too, and that `;` does not close the header.
    `_IMPORT_LINE_RE` recognised the clause only when it OPENED the line:

        module aes_core
          import aes_pkg::*;      <- recognised, header continues
        #( ... ) ( ... );

        module aes_cipher_control_fsm import aes_pkg::*;   <- NOT recognised
        #( ... ) ( ... );                                     header stopped here

    The second form is equally legal and appears on 81 files in the tracked
    corpus. Its header ended on the module line, which declares no ports, so
    every connection in every instantiation of it reported

        does not exist in module '…' port declarations. Available ports: []

    — an empty parse rendering as a wall of design findings. Deciding on the
    CLAUSE rather than on the line handles both placements and the comma list.
    """
    return ';' in _IMPORT_CLAUSE_RE.sub('', line)


def parse_port_list_ansi(header: str, file_path: str, base_line: int) -> Dict[str, PortDecl]:
    """
    Parse ANSI-style port declarations from a module header.
    e.g., module foo (input wire [7:0] data, output reg valid);
    Handles parameterized modules: module foo #(parameter W=8)(input wire clk, ...);
    """
    ports: Dict[str, PortDecl] = {}

    # Find the port list parentheses. For parameterized modules like
    # module foo #(parameter W=8)(input wire clk, ...);
    # we must skip the #(...) parameter block first.

    # Check for #( parameter block
    param_match = re.search(r'#\s*\(', header)
    search_start = 0
    if param_match:
        # Skip over the parameter block by finding its matching close paren
        depth = 0
        skip_end = param_match.start() + len(param_match.group())
        # Start from the '(' of #(
        for i in range(param_match.end() - 1, len(header)):
            if header[i] == '(':
                depth += 1
            elif header[i] == ')':
                depth -= 1
                if depth == 0:
                    search_start = i + 1
                    break

    # Now find the actual port list parentheses
    paren_start = header.find('(', search_start)
    if paren_start == -1:
        return ports

    depth = 0
    paren_end = -1
    for i in range(paren_start, len(header)):
        if header[i] == '(':
            depth += 1
        elif header[i] == ')':
            depth -= 1
            if depth == 0:
                paren_end = i
                break
    if paren_end == -1:
        return ports

    port_text = header[paren_start + 1:paren_end]

    # Count newlines before port_text to get correct line numbers
    lines_before_ports = header[:paren_start + 1].count('\n')

    # Split by comma, handling multi-line declarations
    # We need to track the current direction/type across comma-separated ports
    current_dir = 'input'
    current_width_expr = ''
    current_width = 1
    current_line_offset = 0

    # Split by commas but respect nested brackets
    parts = _split_by_comma(port_text)

    # NOTE: `header` is expected to be comment-free. Both production entry
    # points (`scan_rtl_directory`, `scan_rtl_files`) call `strip_comments` on
    # the whole file first, so a comment never reaches the comma split here.
    #
    # I added a second comment strip at this point and measured its effect by
    # ablation: ibex 1 -> 1, opentitan_aes 241 -> 241. Zero. It was duplicating
    # work already done upstream, and the story I had attached to it — that
    # ibex_core lost 8 ports to comments — was an artifact of my probe calling
    # this function on RAW text. Removed rather than kept as defence in depth,
    # because a fix that changes nothing still has to be read by everyone after.
    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        # Count newlines within this part for line tracking
        newlines_in_part = part.count('\n')

        # Try to match a full port declaration: direction [width] name
        m = re.match(
            r'(?:(?P<dir>input|output|inout)\s+)?'
            # `\s*`, not `\s+`: `output reg[7:0] q` is legal Verilog and
            # common in real RTL — the width bracket binds to the net type
            # without needing a space. Requiring one made the whole anchored
            # match fail, the port vanished from the module's declared set,
            # and EVERY instantiation connecting it read as
            #     Port '.q' ... does not exist in module port declarations
            #
            # MEASURED by a minimal pair — the same file, one space moved:
            #     output  reg[7:0] data_out   -> ERROR mismatch
            #     output reg [7:0] data_out   -> clean
            # and over the 107-directory corpus this accounts for 7 of the
            # 7 rc=1 results: every failure this gate reported was its own
            # parser, not a design defect.
            r'(?:(?:wire|reg|logic|signed|unsigned)\s*)*'
            # A user-defined or package-qualified type, e.g.
            # `input ibex_pkg::pc_sel_e pc_mux_i`. Optional and non-greedy by
            # construction: on `input clk` there is no space-separated word
            # after it, so this group does not participate and `clk` is the
            # name. Without it ibex dropped 43 ports whose types come from a
            # package, and every instantiation of them read as a mismatch.
            r'(?:(?P<type>[A-Za-z_]\w*(?:::\w+)+|[A-Za-z_]\w*_[te])\s+)?'
            # PACKED dimensions, one or more. `input logic [3:0][3:0][7:0]
            # data_i` is a 128-bit port on aes_sub_bytes; with a single group
            # the anchored match failed and the port vanished, so all 5
            # multi-dimensional ports of that module read as "does not exist"
            # while its 7 scalar ones parsed. The unpacked group after the name
            # was already `*` — this is the same list on the other side.
            r'(?P<width>(?:\[[^\]]+\]\s*)+)?'
            r'(?P<name>\w+)'
            # An unpacked dimension after the name, e.g.
            # `input logic [33:0] imd_val_d_ex_i[2]`. Legal SystemVerilog, and
            # without it the anchored match fails and the port disappears.
            r'(?:\s*\[[^\]]+\])*\s*$',
            part_stripped
        )
        if m:
            if m.group('dir'):
                current_dir = m.group('dir')
            width_expr = (m.group('width') or '').strip()
            if width_expr:
                current_width_expr = width_expr
                current_width = eval_width_expr(width_expr)
            elif m.group('dir'):
                # New direction without width resets to scalar
                current_width_expr = ''
                current_width = 1
            name = m.group('name')
            line_num = base_line + lines_before_ports + current_line_offset
            ports[name] = PortDecl(
                name=name,
                direction=current_dir,
                width=current_width,
                width_expr=current_width_expr,
                line=line_num,
                file=file_path,
                data_type=(m.group('type') or '').strip(),
            )

        current_line_offset += newlines_in_part


    return ports


def _split_by_comma(text: str) -> List[str]:
    """Split text by commas, respecting nested brackets."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch in ('(', '[', '{'):
            depth += 1
            current.append(ch)
        elif ch in (')', ']', '}'):
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


def parse_non_ansi_ports(body: str, file_path: str, base_line: int) -> Dict[str, PortDecl]:
    """
    Parse non-ANSI port declarations found in the module body.
    e.g., input [7:0] data; output reg valid;
    Skips input/output declarations inside function/endfunction and
    task/endtask blocks, which are local parameters, not module ports.
    """
    ports: Dict[str, PortDecl] = {}
    lines = body.split('\n')
    func_task_depth = 0  # nesting depth inside function/task blocks
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Track function/task block boundaries
        if re.match(r'\b(function|task)\b', stripped):
            func_task_depth += 1
        if re.match(r'\b(endfunction|endtask)\b', stripped):
            func_task_depth = max(0, func_task_depth - 1)
            continue
        # Skip input/output declarations inside function/task blocks
        if func_task_depth > 0:
            continue
        m = re.match(
            r'\s*(input|output|inout)\s+'
            # `\s*`, not `\s+`: `output reg[7:0] q` is legal Verilog and
            # common in real RTL — the width bracket binds to the net type
            # without needing a space. Requiring one made the whole anchored
            # match fail, the port vanished from the module's declared set,
            # and EVERY instantiation connecting it read as
            #     Port '.q' ... does not exist in module port declarations
            #
            # MEASURED by a minimal pair — the same file, one space moved:
            #     output  reg[7:0] data_out   -> ERROR mismatch
            #     output reg [7:0] data_out   -> clean
            # and over the 107-directory corpus this accounts for 7 of the
            # 7 rc=1 results: every failure this gate reported was its own
            # parser, not a design defect.
            r'(?:(?:wire|reg|logic|signed|unsigned)\s*)*'
            # Packed dimensions, one or more — see the ANSI site. Outer group
            # captures, inner does not, so the numbered groups below keep their
            # positions.
            r'((?:\[[^\]]+\]\s*)+)?'
            r'([^;]+?)\s*;',
            line
        )
        if m:
            direction = m.group(1)
            width_expr = (m.group(2) or '').strip()
            width = eval_width_expr(width_expr)
            name_list = m.group(3)
            for name in name_list.split(','):
                name = name.strip()
                name = re.sub(r'\[.*', '', name).strip()
                if name and re.match(r'^\w+$', name):
                    ports[name] = PortDecl(
                        name=name,
                        direction=direction,
                        width=width,
                        width_expr=width_expr,
                        line=base_line + lineno,
                        file=file_path
                    )
    return ports


def parse_instantiations(body: str, file_path: str, base_line: int) -> List[ModuleInstance]:
    """
    Parse module instantiations from a module body.
    Handles:  module_name #(params) instance_name (.port(wire), ...);
    Also handles .* (implicit port connections).
    """
    instances: List[ModuleInstance] = []

    # Verilog keywords that cannot be module names in instantiations
    keywords = {
        'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
        'logic', 'assign', 'always', 'always_ff', 'always_comb', 'always_latch',
        'begin', 'end', 'if', 'else', 'case', 'endcase', 'default', 'for',
        'while', 'repeat', 'function', 'endfunction', 'task', 'endtask',
        'parameter', 'localparam', 'generate', 'endgenerate', 'genvar',
        'integer', 'real', 'initial', 'forever', 'wait', 'fork', 'join',
        'typedef', 'struct', 'union', 'enum', 'packed', 'signed', 'unsigned',
        'return', 'break', 'continue', 'import', 'export', 'virtual',
        'class', 'endclass', 'interface', 'endinterface', 'modport',
        'assert', 'assume', 'cover', 'property', 'sequence', 'disable',
    }

    # Strategy: find patterns like:  module_name [#(...)] instance_name (...)  ;
    # We use a multi-step approach:
    # 1. Find all semicolon-terminated statements that contain .port( patterns
    # 2. Parse them for module_name, instance_name, and connections

    # Build the full text with line tracking
    lines = body.split('\n')

    # Find instantiation candidates: statements with .identifier( pattern
    # Collect complete statements (from non-blank start to ;)
    statements = _collect_statements(body)

    for stmt_text, stmt_start_line in statements:
        # Must contain at least one .name( pattern or .*
        if not re.search(r'\.\s*\w+\s*\(', stmt_text) and '.*' not in stmt_text:
            continue

        # Try to parse: module_name [#(...)] instance_name (...)
        # First strip any parameter block #(...)
        cleaned = stmt_text.strip()

        # Match module_name
        m_mod = re.match(r'(\w+)\s*', cleaned)
        if not m_mod:
            continue
        mod_name = m_mod.group(1)
        if mod_name in keywords:
            continue

        rest = cleaned[m_mod.end():]

        # Skip optional parameter override #(...)
        if rest.startswith('#'):
            rest = rest[1:].lstrip()
            if rest.startswith('('):
                depth = 0
                for i, ch in enumerate(rest):
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                        if depth == 0:
                            rest = rest[i + 1:].lstrip()
                            break

        # Match instance_name
        m_inst = re.match(r'(\w+)\s*\(', rest)
        if not m_inst:
            continue
        inst_name = m_inst.group(1)
        if inst_name in keywords:
            continue

        rest = rest[m_inst.end() - 1:]  # include the opening paren

        # Extract port connection list from parentheses
        if not rest.startswith('('):
            continue
        depth = 0
        conn_end = -1
        for i, ch in enumerate(rest):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    conn_end = i
                    break
        if conn_end == -1:
            continue

        conn_text = rest[1:conn_end]

        # Parse connections
        connections: List[PortConnection] = []
        is_implicit = False

        if '.*' in conn_text:
            is_implicit = True

        # Find all .port_name(wire_expr) patterns
        for m_conn in re.finditer(r'\.(\w+)\s*\(([^)]*)\)', conn_text):
            port_name = m_conn.group(1)
            wire_expr = m_conn.group(2).strip()
            # Calculate approximate line number
            text_before = conn_text[:m_conn.start()]
            conn_line = base_line + stmt_start_line + text_before.count('\n')
            connections.append(PortConnection(
                port_name=port_name,
                wire_expr=wire_expr,
                line=conn_line,
                file=file_path
            ))

        if connections or is_implicit:
            instances.append(ModuleInstance(
                module_name=mod_name,
                instance_name=inst_name,
                connections=connections,
                is_implicit=is_implicit,
                line=base_line + stmt_start_line,
                file=file_path
            ))

    return instances


def _collect_statements(body: str) -> List[Tuple[str, int]]:
    """
    Collect semicolon-terminated statements with their starting line numbers.
    Returns list of (statement_text, start_line_offset).
    """
    statements = []
    lines = body.split('\n')
    current_stmt = []
    start_line = 0
    paren_depth = 0
    bracket_depth = 0

    for lineno, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        if not current_stmt:
            start_line = lineno

        current_stmt.append(line)

        for ch in line:
            if ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth -= 1
            elif ch == '[':
                bracket_depth += 1
            elif ch == ']':
                bracket_depth -= 1

        if ';' in line and paren_depth <= 0 and bracket_depth <= 0:
            stmt_text = '\n'.join(current_stmt)
            statements.append((stmt_text, start_line))
            current_stmt = []
            paren_depth = 0
            bracket_depth = 0

    return statements


def parse_modules(src: str, file_path: str) -> List[ModuleDef]:
    """
    Parse all module definitions from a Verilog/SystemVerilog source string.
    Returns a list of ModuleDef with ports and sub-module instantiations.
    """
    modules: List[ModuleDef] = []
    lines = src.split('\n')

    # Find module boundaries
    module_regions: List[Tuple[int, int, str]] = []  # (start_line, end_line, header)
    i = 0
    while i < len(lines):
        m = re.match(r'\s*module\s+(\w+)', lines[i])
        if m:
            mod_name = m.group(1)
            start_line = i
            # Find the end of module header (first ; that is not an import)
            #
            # SystemVerilog allows a package import list between the module name
            # and the parameter list:
            #
            #     module aes_core
            #       import aes_pkg::*;        <- the first `;` in the file
            #       import aes_reg_pkg::*;
            #     #( ... ) ( input logic clk_i, ... );
            #
            # Stopping at the first `;` made the header those two lines, which
            # contain no ports at all — so every instantiated port "did not
            # exist in the module". Measured on the corpus: 920 errors on
            # opentitan_aes alone, every one of them false (#559).
            header_lines = []
            j = i
            while j < len(lines):
                header_lines.append(lines[j])
                if header_ends_on(lines[j]):
                    break
                j += 1
            header_end = j
            # Find endmodule
            end_line = header_end
            for k in range(header_end + 1, len(lines)):
                if re.match(r'\s*endmodule\b', lines[k]):
                    end_line = k
                    break
            module_regions.append((start_line, end_line, mod_name))
            i = end_line + 1
        else:
            i += 1

    for start_line, end_line, mod_name in module_regions:
        # Extract header (everything from 'module' to first ';')
        header_lines = []
        for j in range(start_line, min(end_line + 1, len(lines))):
            header_lines.append(lines[j])
            if header_ends_on(lines[j]):
                break
        header = '\n'.join(header_lines)

        # Extract body (everything between header end and endmodule)
        header_end = start_line + len(header_lines)
        body = '\n'.join(lines[header_end:end_line])

        # Parse ports from ANSI header
        ports = parse_port_list_ansi(header, file_path, start_line + 1)

        # Also check for non-ANSI port declarations in body
        non_ansi_ports = parse_non_ansi_ports(body, file_path, header_end + 1)
        for name, port in non_ansi_ports.items():
            if name not in ports:
                ports[name] = port

        # Parse parameters
        parameters: List[str] = []
        for pm in re.finditer(r'\bparameter\s+(?:\w+\s+)?(\w+)\s*=', header + '\n' + body):
            parameters.append(pm.group(1))

        # Parse instantiations from body
        instances = parse_instantiations(body, file_path, header_end + 1)

        modules.append(ModuleDef(
            name=mod_name,
            ports=ports,
            parameters=parameters,
            instances=instances,
            file=file_path,
            line=start_line + 1
        ))

    return modules


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------
def audit_design(module_defs: Dict[str, ModuleDef],
                 top_module: Optional[str] = None) -> List[Finding]:
    """
    Cross-reference all module instantiations against module definitions.
    Returns a list of findings.

    If top_module is specified, also check for UNCONNECTED ports (module ports
    that are never connected in any instantiation).
    """
    findings: List[Finding] = []

    # Build a set of all instantiations per module type
    all_instances: Dict[str, List[Tuple[str, ModuleInstance]]] = {}
    for parent_name, parent_def in module_defs.items():
        for inst in parent_def.instances:
            if inst.module_name not in all_instances:
                all_instances[inst.module_name] = []
            all_instances[inst.module_name].append((parent_name, inst))

    # Check 1: MISMATCH — port in instantiation doesn't exist in module def
    for parent_name, parent_def in module_defs.items():
        for inst in parent_def.instances:
            if inst.module_name not in module_defs:
                # Module definition not found — skip (could be external IP)
                continue
            target_def = module_defs[inst.module_name]

            if inst.is_implicit:
                # .* connections — all ports are implicitly connected by name
                # Nothing to check for mismatch (synthesis will catch missing wires)
                continue

            for conn in inst.connections:
                if conn.port_name not in target_def.ports:
                    findings.append(Finding(
                        severity='ERROR',
                        rule='mismatch',
                        module=parent_name,
                        instance=inst.instance_name,
                        port=conn.port_name,
                        message=(
                            f"Port '.{conn.port_name}' in instantiation "
                            f"'{inst.instance_name}' ({inst.module_name}) "
                            f"does not exist in module '{inst.module_name}' "
                            f"port declarations. "
                            f"Available ports: "
                            f"{sorted(target_def.ports.keys())}"
                        ),
                        file=conn.file,
                        line=conn.line
                    ))

    # Check 2: WIDTH_MISMATCH — connected wire width doesn't match port width
    for parent_name, parent_def in module_defs.items():
        for inst in parent_def.instances:
            if inst.module_name not in module_defs:
                continue
            target_def = module_defs[inst.module_name]

            for conn in inst.connections:
                if conn.port_name not in target_def.ports:
                    continue  # already reported as mismatch
                port_decl = target_def.ports[conn.port_name]
                if port_decl.width <= 0:
                    continue  # parameterized, can't check

                # Try to infer wire width from the connection expression
                wire_width = _infer_connection_width(conn.wire_expr, parent_def)
                if wire_width > 0 and port_decl.width > 0 and wire_width != port_decl.width:
                    findings.append(Finding(
                        severity='WARN',
                        rule='width-mismatch',
                        module=parent_name,
                        instance=inst.instance_name,
                        port=conn.port_name,
                        message=(
                            f"Width mismatch on port '.{conn.port_name}' in "
                            f"'{inst.instance_name}' ({inst.module_name}): "
                            f"port is {port_decl.width}-bit "
                            f"({port_decl.width_expr or '1-bit scalar'}), "
                            f"but connected signal '{conn.wire_expr}' "
                            f"is {wire_width}-bit."
                        ),
                        file=conn.file,
                        line=conn.line
                    ))

    # Check 3: UNCONNECTED — module ports not connected in any instantiation
    for mod_name, mod_def in module_defs.items():
        if top_module and mod_name == top_module:
            # Skip top module — its ports connect to the outside world
            continue

        if mod_name not in all_instances:
            # Module is never instantiated (could be top or unused)
            continue

        instances_of_this = all_instances[mod_name]

        for port_name, port_decl in mod_def.ports.items():
            connected_anywhere = False
            for parent_name, inst in instances_of_this:
                if inst.is_implicit:
                    connected_anywhere = True
                    break
                for conn in inst.connections:
                    if conn.port_name == port_name:
                        # Check if connected to empty () — that's unconnected
                        if conn.wire_expr.strip():
                            connected_anywhere = True
                        break
                if connected_anywhere:
                    break

            if not connected_anywhere:
                findings.append(Finding(
                    severity='WARN',
                    rule='unconnected',
                    module=mod_name,
                    instance='',
                    port=port_name,
                    message=(
                        f"Port '{port_name}' ({port_decl.direction}) of module "
                        f"'{mod_name}' is never connected in any instantiation."
                    ),
                    file=port_decl.file,
                    line=port_decl.line
                ))

    return findings


def _infer_connection_width(wire_expr: str, parent_def: ModuleDef) -> int:
    """
    Try to infer the bit-width of a connection expression.
    Returns the width if deterministic, -1 if unknown.
    """
    wire_expr = wire_expr.strip()
    if not wire_expr:
        return -1

    # Constant like 1'b0, 8'hFF
    m = re.match(r"(\d+)'[bhd]", wire_expr)
    if m:
        return int(m.group(1))

    # Single-index select: `signal[3]`.
    #
    # 1 bit ONLY when `signal` is a one-dimensional packed vector. On a
    # multi-dimensional or unpacked signal the same syntax selects a whole
    # ELEMENT: `aes_cipher_core.state_q[0]` is one 128-bit share of
    # `logic [3:0][3:0][7:0] state_q [NumShares]`, and calling it 1 bit made a
    # correct connection to a 128-bit port read as a width mismatch.
    #
    # The dimension count is knowable only when the base is a port of the
    # parent module — this parser does not carry local signal declarations. So
    # the answer is UNKNOWN when it cannot be looked up, rather than 1 by
    # assumption. That drops the finding instead of inventing it; a stated
    # number nobody measured is the more expensive of the two errors, because
    # it reads exactly like a measured one.
    m = re.match(r'(\w+)\s*\[\s*\d+\s*\]$', wire_expr)
    if m:
        base = parent_def.ports.get(m.group(1))
        if base is None:
            return -1
        dims = _DIM_RE.findall(base.width_expr or '')
        if len(dims) > 1:
            # An element of a packed multi-dimensional port: total / outermost.
            outer = eval_width_expr(dims[0])
            return base.width // outer if base.width > 0 and outer > 0 else -1
        return 1 if base.width != 1 else -1

    # Part-select: signal[7:0] -> 8 bits
    m = re.match(r'(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]$', wire_expr)
    if m:
        return abs(int(m.group(2)) - int(m.group(3))) + 1

    # Concatenation: {a, b} — too complex, skip
    if wire_expr.startswith('{'):
        return -1

    # Simple identifier — look up in parent module ports or wire declarations
    m = re.match(r'^(\w+)$', wire_expr)
    if m:
        name = m.group(1)
        if name in parent_def.ports:
            return parent_def.ports[name].width
    return -1


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------
def scan_rtl_directory(rtl_dir: Path) -> Dict[str, ModuleDef]:
    """
    Scan all .v and .sv files in a directory (recursively) and parse
    all module definitions.
    """
    module_defs: Dict[str, ModuleDef] = {}
    extensions = {'.v', '.sv', '.vh', '.svh'}

    for fpath in sorted(rtl_dir.rglob('*')):
        if fpath.suffix.lower() not in extensions:
            continue
        try:
            src = fpath.read_text(errors='replace')
        except (IOError, OSError) as e:
            print(f"WARNING: cannot read {fpath}: {e}", file=sys.stderr)
            continue

        src_clean = strip_preproc_directives(strip_comments(src))
        modules = parse_modules(src_clean, str(fpath))
        for mod in modules:
            if mod.name in module_defs:
                print(f"WARNING: duplicate module '{mod.name}' in {fpath} "
                      f"(already seen in {module_defs[mod.name].file})",
                      file=sys.stderr)
            module_defs[mod.name] = mod

    return module_defs


def scan_rtl_files(file_list: List[str]) -> Dict[str, ModuleDef]:
    """Parse module definitions from an explicit list of files."""
    module_defs: Dict[str, ModuleDef] = {}
    for fpath_str in file_list:
        fpath = Path(fpath_str)
        if not fpath.exists():
            print(f"WARNING: file not found: {fpath}", file=sys.stderr)
            continue
        try:
            src = fpath.read_text(errors='replace')
        except (IOError, OSError) as e:
            print(f"WARNING: cannot read {fpath}: {e}", file=sys.stderr)
            continue

        src_clean = strip_preproc_directives(strip_comments(src))
        modules = parse_modules(src_clean, str(fpath))
        for mod in modules:
            module_defs[mod.name] = mod

    return module_defs


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(findings: List[Finding], module_defs: Dict[str, ModuleDef],
                    top_module: Optional[str]) -> dict:
    """Generate a structured JSON report."""
    # Group findings by instance
    by_instance: Dict[str, List[dict]] = {}
    for f in findings:
        key = f"{f.module}.{f.instance}" if f.instance else f.module
        if key not in by_instance:
            by_instance[key] = []
        by_instance[key].append(asdict(f))

    summary = {
        'total_findings': len(findings),
        'errors': sum(1 for f in findings if f.severity == 'ERROR'),
        'warnings': sum(1 for f in findings if f.severity == 'WARN'),
        'info': sum(1 for f in findings if f.severity == 'INFO'),
        'mismatches': sum(1 for f in findings if f.rule == 'mismatch'),
        'unconnected': sum(1 for f in findings if f.rule == 'unconnected'),
        'width_mismatches': sum(1 for f in findings if f.rule == 'width-mismatch'),
    }

    modules_summary = {}
    for name, mod in module_defs.items():
        modules_summary[name] = {
            'file': mod.file,
            'port_count': len(mod.ports),
            'ports': sorted(mod.ports.keys()),
            'instance_count': len(mod.instances),
            'instances': [
                {
                    'module': inst.module_name,
                    'name': inst.instance_name,
                    'connection_count': len(inst.connections),
                    'implicit': inst.is_implicit,
                }
                for inst in mod.instances
            ]
        }

    report = {
        'tool': 'module_port_audit',
        'version': '1.0.0',
        'top_module': top_module,
        'summary': summary,
        'modules': modules_summary,
        'findings_by_instance': by_instance,
        'findings': [asdict(f) for f in findings],
    }

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description='Detect port name mismatches between top-level integration '
                    'modules and their submodule instantiations.'
    )
    ap.add_argument('--rtl-dir', type=str,
                    help='Directory containing Verilog/SV files (recursive scan)')
    ap.add_argument('--files', nargs='+',
                    help='Explicit list of Verilog/SV files to check')
    ap.add_argument('--top-module', type=str, default=None,
                    help='Name of the top-level module (for UNCONNECTED checks)')
    ap.add_argument('--out-dir', type=str, default=None,
                    help='Output directory for the JSON report')
    ap.add_argument('--json', type=str, default=None,
                    help='Write findings JSON to this specific path')
    ap.add_argument('--severity', choices=['ERROR', 'WARN', 'INFO'], default='INFO',
                    help='Minimum severity to report (default: INFO)')
    args = ap.parse_args()

    if not args.rtl_dir and not args.files:
        ap.error("Must specify either --rtl-dir or --files")

    # Parse all modules
    if args.rtl_dir:
        rtl_path = Path(args.rtl_dir)
        if not rtl_path.is_dir():
            print(f"ERROR: {args.rtl_dir} is not a directory", file=sys.stderr)
            return 2
        module_defs = scan_rtl_directory(rtl_path)
    else:
        module_defs = scan_rtl_files(args.files)

    if not module_defs:
        print("ERROR: no modules found in provided files", file=sys.stderr)
        return 2

    # Validate top module if specified
    if args.top_module and args.top_module not in module_defs:
        print(f"WARNING: top module '{args.top_module}' not found in parsed modules. "
              f"Available: {sorted(module_defs.keys())}", file=sys.stderr)

    # Run the audit
    findings = audit_design(module_defs, args.top_module)

    # Filter by severity
    sev_order = {'ERROR': 2, 'WARN': 1, 'INFO': 0}
    min_sev = sev_order[args.severity]
    filtered = [f for f in findings if sev_order[f.severity] >= min_sev]

    # Text report to stdout
    err_count = sum(1 for f in filtered if f.severity == 'ERROR')
    warn_count = sum(1 for f in filtered if f.severity == 'WARN')
    info_count = sum(1 for f in filtered if f.severity == 'INFO')
    print(f"module_port_audit: {err_count} errors, {warn_count} warnings, {info_count} info")
    print(f"  Parsed {len(module_defs)} modules")
    print("-" * 70)
    for fd in sorted(filtered, key=lambda x: (x.file, x.line, x.severity)):
        print(f"{fd.file}:{fd.line}: [{fd.severity}] {fd.rule}: {fd.message}")

    # JSON output
    report = generate_report(filtered, module_defs, args.top_module)

    if args.out_dir:
        out_path = Path(args.out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        json_file = out_path / 'module_port_audit_report.json'
        json_file.write_text(json.dumps(report, indent=2))
        print(f"\nReport written to {json_file}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"\nReport written to {args.json}")

    return 1 if err_count > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
