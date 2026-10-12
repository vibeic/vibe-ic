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
    # Positional actuals are kept separately from named connections.  A caller
    # may use them only after resolving the child formal order and direction;
    # an unqualified signal in this list is not evidence of a driver by itself.
    positional_actuals: List[str] = field(default_factory=list)
    has_mixed_connections: bool = False
    malformed_connections: bool = False


@dataclass
class ModuleDef:
    """A parsed module definition."""
    name: str
    ports: Dict[str, PortDecl]   # port_name -> PortDecl
    parameters: List[str]        # parameter names
    instances: List[ModuleInstance]  # sub-module instantiations
    file: str
    line: int
    # Formal order is needed to resolve positional actuals.  Dict insertion
    # order is not sufficient for non-ANSI declarations whose body order can
    # differ from the old-style header order.
    port_order: List[str] = field(default_factory=list)
    body: str = ""
    discovery_issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Balanced source helpers
# ---------------------------------------------------------------------------
def extract_balanced(text: str, open_at: int, *, opener: str = '(',
                     closer: str = ')') -> Optional[Tuple[str, int]]:
    """Return the contents and closing index of one balanced delimiter pair.

    Regexes with ``[^)]*`` silently truncate legal parameter expressions such
    as ``$clog2(N+1)``.  This small source-backed helper is shared by the
    hierarchy parser and the encoding audit; it understands nested delimiters
    and quoted strings, and returns ``None`` for malformed input so consumers
    can disclose incomplete discovery instead of certifying an empty census.
    """
    if open_at < 0 or open_at >= len(text) or text[open_at] != opener:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_at, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[open_at + 1:index], index
            if depth < 0:
                return None
    return None


def split_top_level(text: str, separator: str = ',') -> List[str]:
    """Split source at separators outside nested (), [] and {} groups."""
    parts: List[str] = []
    current: List[str] = []
    stack: List[str] = []
    pairs = {')': '(', ']': '[', '}': '{'}
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
        elif ch in '([{':
            stack.append(ch)
            current.append(ch)
        elif ch in ')]}':
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
            else:
                # Keep malformed text visible to the caller.  It will be
                # treated as unsupported rather than partially classified.
                stack.append(ch)
            current.append(ch)
        elif ch == separator and not stack:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    parts.append(''.join(current))
    return parts


def _attribute_start(src: str, pos: int) -> bool:
    """An event wildcard ``@(*)`` is not a SystemVerilog attribute."""
    if not src.startswith('(*', pos):
        return False
    previous = pos - 1
    while previous >= 0 and src[previous].isspace():
        previous -= 1
    return previous < 0 or src[previous] != '@'


def lexical_mask(src: str, *, attributes: bool = False) -> str:
    """Blank comments and strings without moving any source offset.

    Structural keywords/delimiters inside literals are never syntax. An
    unfinished token refuses discovery rather than truncating the file.
    """
    out = list(src)
    i = 0
    while i < len(src):
        start = i
        if src.startswith('//', i):
            end = src.find('\n', i + 2)
            i = len(src) if end < 0 else end
        elif src.startswith('/*', i):
            end = src.find('*/', i + 2)
            if end < 0:
                raise ValueError('unterminated_comment')
            i = end + 2
        elif src[i] == '"':
            i += 1
            while i < len(src) and src[i] != '"':
                i += 2 if src[i] == '\\' else 1
            if i >= len(src):
                raise ValueError('unterminated_string')
            i += 1
        elif attributes and _attribute_start(src, i):
            end = lexical_mask(src[i + 2:]).find('*)')
            if end < 0:
                raise ValueError('unterminated_attribute')
            i += 2 + end + 2
        else:
            i += 1
            continue
        for j in range(start, i):
            out[j] = '\n' if src[j] == '\n' else ' '
    return ''.join(out)


def mask_attributes_only(src: str) -> str:
    """Blank SystemVerilog attributes while preserving comments and strings.

    ``parse_port_list_ansi`` is also a small public parser helper used by
    callers that deliberately provide raw text.  Its historical contract is
    that comment stripping belongs to the caller, so use this narrower mask
    there instead of changing how raw comments are tokenized.
    """
    out = list(src)
    i = 0
    state = 'code'
    while i < len(src):
        if state == 'code' and src.startswith('//', i):
            state = 'line_comment'
            i += 2
            continue
        if state == 'line_comment':
            if src[i] == '\n':
                state = 'code'
            i += 1
            continue
        if state == 'code' and src.startswith('/*', i):
            state = 'block_comment'
            i += 2
            continue
        if state == 'block_comment':
            if src.startswith('*/', i):
                state = 'code'
                i += 2
            else:
                i += 1
            continue
        if state == 'code' and src[i] == '"':
            state = 'string'
            i += 1
            continue
        if state == 'string':
            if src[i] == '\\':
                i += 2
            elif src[i] == '"':
                state = 'code'
                i += 1
            else:
                i += 1
            continue
        if state == 'code' and _attribute_start(src, i):
            start = i
            i += 2
            depth = 1
            while i < len(src) and depth:
                if src.startswith('(*', i):
                    depth += 1
                    i += 2
                elif src.startswith('*)', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError('unterminated_attribute')
            for j in range(start, i):
                out[j] = '\n' if src[j] == '\n' else ' '
            continue
        i += 1
    return ''.join(out)


def module_regions(src: str, issues: Optional[List[str]] = None):
    """Yield complete (name, header start, body start, body end) regions.

    Balanced headers and lexical keyword boundaries cover both single-line
    and multi-line modules. Unsupported identifiers remain disclosed.
    """
    issues = issues if issues is not None else []
    try:
        mask = lexical_mask(src, attributes=True)
    except ValueError as exc:
        issues.append(str(exc))
        return
    cursor = 0
    token_re = re.compile(r'\b(module|endmodule)\b')
    while (match := token_re.search(mask, cursor)) is not None:
        if match.group() != 'module':
            issues.append('endmodule_without_module')
            cursor = match.end()
            continue
        name_match = re.match(r'\s+(?:automatic\s+|static\s+)?([A-Za-z_]\w*)\b',
                              mask[match.end():])
        if name_match is None:
            issues.append('unsupported_module_identifier')
            cursor = match.end()
            continue
        name = name_match.group(1)
        index = match.end() + name_match.end()
        while True:
            while index < len(mask) and mask[index].isspace():
                index += 1
            if not re.match(r'import\b', mask[index:]):
                break
            semi = mask.find(';', index)
            if semi < 0:
                break
            index = semi + 1
        if index < len(mask) and mask[index] == '#':
            index += 1
            while index < len(mask) and mask[index].isspace():
                index += 1
            result = extract_balanced(mask, index)
            if result is None:
                issues.append(f'unbalanced parameter list in module {name}')
                cursor = index + 1
                continue
            index = result[1] + 1
        while index < len(mask) and mask[index].isspace():
            index += 1
        if index < len(mask) and mask[index] == '(':
            result = extract_balanced(mask, index)
            if result is None:
                issues.append(f'unbalanced port list in module {name}')
                cursor = index + 1
                continue
            index = result[1] + 1
        while index < len(mask) and mask[index].isspace():
            index += 1
        if index >= len(mask) or mask[index] != ';':
            issues.append(f'incomplete header in module {name}')
            cursor = index + 1
            continue
        body_start = index + 1
        end = token_re.search(mask, body_start)
        if end is None or end.group() != 'endmodule':
            issues.append(f'missing endmodule in module {name}')
            cursor = body_start
            continue
        yield name, match.start(), body_start, end.start()
        cursor = end.end()


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


def parse_port_list_ansi(header: str, file_path: str, base_line: int,
                         issues: Optional[List[str]] = None) -> Dict[str, PortDecl]:
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
    current_dir = 'UNKNOWN'
    current_width_expr = ''
    current_width = 1
    current_line_offset = 0

    # Split by commas but respect nested brackets
    parts = split_top_level(mask_attributes_only(port_text))

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
            duplicate = name in ports
            if duplicate and issues is not None:
                issues.append(f'duplicate header port: {name}')
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
            if duplicate:
                ports[name].direction = 'UNKNOWN'
        elif issues is not None:
            issues.append(f'unsupported header port: {part_stripped}')

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


def parse_non_ansi_ports(body: str, file_path: str, base_line: int,
                         issues: Optional[List[str]] = None) -> Dict[str, PortDecl]:
    """
    Parse non-ANSI port declarations found in the module body.
    e.g., input [7:0] data; output reg valid;
    Skips input/output declarations inside function/endfunction and
    task/endtask blocks, which are local parameters, not module ports.
    """
    ports: Dict[str, PortDecl] = {}
    mask = lexical_mask(body, attributes=True)
    mask = re.sub(r'\b(function|task)\b.*?\b(endfunction|endtask)\b',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()),
                  mask, flags=re.DOTALL)
    for declaration in re.finditer(r'\b(input|output|inout)\b([^;]*);', mask):
        direction = declaration.group(1)
        text = declaration.group(2).strip()
        # The ANSI declaration parser owns type/range/name continuation rules.
        parsed = parse_port_list_ansi(
            'module _ (' + direction + ' ' + text + ');', file_path,
            base_line + body[:declaration.start()].count('\n'))
        if len(parsed) != len(split_top_level(text)) and issues is not None:
            issues.append('incomplete body port declaration')
        for name, port in parsed.items():
            if name in ports:
                port.direction = 'UNKNOWN'
                if issues is not None:
                    issues.append(f'duplicate body port declaration: {name}')
            ports[name] = port

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

    # Strategy: find semicolon-terminated statements and parse the module,
    # optional parameter override, instance and balanced connection list in
    # order.  The old implementation selected only statements containing a
    # named ``.port(...)`` token, so an ordinary positional instance was absent
    # from the census before any direction resolution could happen.

    # Build the full text with line tracking
    lines = body.split('\n')

    # Find instantiation candidates: statements with .identifier( pattern
    # Collect complete statements (from non-blank start to ;)
    statements = _collect_statements(body)

    for stmt_text, stmt_start_line in statements:
        cleaned = stmt_text.strip()
        # Block closers carry no semicolon. The collector consequently keeps
        # them at the front of the next module-level instance statement.
        # Remove only closing keywords, never an opening/conditional prefix;
        # a generate/procedural branch is not proved active by this parser.
        closers = re.match(
            r'(?:(?:endgenerate|endcase|endfunction|endtask|end)\b'
            r'(?:\s*:\s*[A-Za-z_]\w*)?\s*)+', cleaned)
        if closers:
            stmt_start_line += cleaned[:closers.end()].count('\n')
            cleaned = cleaned[closers.end():]

        # A generate block's first instance shares a statement with its
        # opening condition/begin label. Discover the syntax, without claiming
        # the branch active; runtime lint keeps this scope unresolved.
        if re.match(r'(?:generate|if|else|for|case|begin)\b', cleaned):
            openings = list(re.finditer(r'\bbegin\b(?:\s*:\s*[A-Za-z_]\w*)?', cleaned))
            if openings:
                prefix = openings[-1].end()
                stmt_start_line += cleaned[:prefix].count('\n')
                tail = cleaned[prefix:]
                leading = len(tail) - len(tail.lstrip())
                stmt_start_line += tail[:leading].count('\n')
                cleaned = tail.lstrip()

        # Match module_name
        m_mod = re.match(r'(\w+)\s*', cleaned)
        if not m_mod:
            continue
        mod_name = m_mod.group(1)
        if mod_name in keywords:
            continue

        rest = cleaned[m_mod.end():]

        # Skip optional parameter override #(...), preserving nested calls such
        # as ``#(.WIDTH($clog2(N+1)))``.
        if rest.startswith('#'):
            rest = rest[1:].lstrip()
            if rest.startswith('('):
                balanced = extract_balanced(rest, 0)
                if balanced is None:
                    continue
                _, close_at = balanced
                rest = rest[close_at + 1:].lstrip()

        # Match instance_name
        m_inst = re.match(r'(\w+)\s*\(', rest)
        if not m_inst:
            continue
        inst_name = m_inst.group(1)
        if inst_name in keywords:
            continue

        rest = rest[m_inst.end() - 1:]  # include the opening paren

        # Extract the complete, balanced port connection list.
        if not rest.startswith('('):
            continue
        balanced = extract_balanced(rest, 0)
        if balanced is None:
            continue
        conn_text, conn_end = balanced

        # Parse connections
        connections: List[PortConnection] = []
        positional_actuals: List[str] = []
        is_implicit = False
        has_named = False
        has_positional = False
        malformed_connections = rest[conn_end + 1:].strip() != ';'

        named_ports: Set[str] = set()
        items = [] if not conn_text.strip() else split_top_level(conn_text)
        item_offset = 0
        for item in items:
            item_start = conn_text.find(item, item_offset)
            if item_start < 0:
                item_start = item_offset
            item_offset = item_start + len(item) + 1
            item_stripped = item.strip()
            if not item_stripped:
                # Empty positional actuals are meaningful placeholders.  Keep
                # them so later positions are not shifted, but never treat an
                # empty expression as a driver.
                positional_actuals.append('')
                has_positional = True
                continue
            text_before = conn_text[:item_start]
            conn_line = base_line + stmt_start_line + text_before.count('\n')
            if item_stripped == '.*':
                is_implicit = True
                has_named = True
                continue
            if item_stripped.startswith('.'):
                named = re.match(r'^\.\s*(\w+)\s*(.*)$',
                                 item_stripped, re.DOTALL)
                if named is None:
                    malformed_connections = True
                    continue
                tail = named.group(2).strip()
                if tail:
                    actual = extract_balanced(tail, 0)
                    if actual is None or tail[actual[1] + 1:].strip():
                        malformed_connections = True
                        continue
                    wire_expr = actual[0].strip()
                else:
                    wire_expr = named.group(1)
                has_named = True
                if named.group(1) in named_ports:
                    malformed_connections = True
                named_ports.add(named.group(1))
                connections.append(PortConnection(
                    port_name=named.group(1),
                    wire_expr=wire_expr,
                    line=conn_line,
                    file=file_path
                ))
                continue
            # A positional actual is retained verbatim.  Consumers resolve
            # only simple identifiers and simple concatenations; arbitrary
            # expressions remain conservative and cannot bless a wire.
            has_positional = True
            positional_actuals.append(item_stripped)

        if connections or positional_actuals or is_implicit:
            instances.append(ModuleInstance(
                module_name=mod_name,
                instance_name=inst_name,
                connections=connections,
                is_implicit=is_implicit,
                line=base_line + stmt_start_line,
                file=file_path,
                positional_actuals=positional_actuals,
                has_mixed_connections=has_named and has_positional,
                malformed_connections=malformed_connections,
            ))

    return instances


def _collect_statements(body: str) -> List[Tuple[str, int]]:
    """
    Collect semicolon-terminated statements with their starting line numbers.
    Returns list of (statement_text, start_line_offset).
    """
    statements = []
    mask = lexical_mask(body, attributes=True)
    start = 0
    stack = []
    for index, ch in enumerate(mask):
        if ch in '([{':
            stack.append(ch)
        elif ch in ')]}':
            if stack and stack[-1] == {')': '(', ']': '[', '}': '{'}[ch]:
                stack.pop()
            else:
                stack.append(ch)
        elif ch == ';' and not stack:
            text = mask[start:index + 1]
            leading = len(text) - len(text.lstrip())
            statements.append((text, mask[:start + leading].count('\n')))
            start = index + 1
    return statements



def parse_modules(src: str, file_path: str) -> List[ModuleDef]:
    """
    Parse all module definitions from a Verilog/SystemVerilog source string.
    Returns a list of ModuleDef with ports and sub-module instantiations.
    """
    modules: List[ModuleDef] = []
    issues: List[str] = []
    for mod_name, start, body_start, body_end in module_regions(src, issues):
        header = lexical_mask(src[start:body_start], attributes=True)
        body = lexical_mask(src[body_start:body_end], attributes=True)
        start_line = src[:start].count('\n') + 1
        body_line = src[:body_start].count('\n') + 1
        local_issues = []
        ports = parse_port_list_ansi(header, file_path, start_line, local_issues)
        non_ansi_ports = parse_non_ansi_ports(body, file_path, body_line, local_issues)
        for name, port in non_ansi_ports.items():
            if name in ports:
                existing = ports[name]
                if existing.direction == 'UNKNOWN':
                    ports[name] = port
                elif (existing.direction, existing.width_expr) != (
                        port.direction, port.width_expr):
                    existing.direction = 'UNKNOWN'
                    local_issues.append(f'ambiguous declaration: {name}')
            else:
                local_issues.append(f'body port absent from header: {name}')
        if any(p.direction == 'UNKNOWN' for p in ports.values()):
            local_issues.append(f'unresolved port directions in module {mod_name}')
        parameters = [m.group(1) for m in re.finditer(
            r'\bparameter\s+(?:\w+\s+)?(\w+)\s*=', header + '\n' + body)]
        modules.append(ModuleDef(
            name=mod_name, ports=ports, parameters=parameters,
            instances=parse_instantiations(body, file_path, body_line),
            file=file_path, line=start_line, port_order=list(ports), body=body,
            discovery_issues=local_issues))
    for mod in modules:
        mod.discovery_issues.extend(issues)

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
