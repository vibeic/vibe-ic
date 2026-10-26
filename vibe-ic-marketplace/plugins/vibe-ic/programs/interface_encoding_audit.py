#!/usr/bin/env python3
"""
interface_encoding_audit.py — Detect gray-code vs binary encoding mismatches
across module boundaries.

A critical bug class found during FPGA verification (<half-duplex-tester> debug, 2026-04-16):
The AI RX_PHY output `rx_data_length_cnt_2p5m` in binary format (incremented
via `cnt <= cnt + 1`), but the downstream module `rx_chk` compared it against
gray-code values like `6'b11_0000` for 32. Because binary 32 = 6'b10_0000
but gray-code 32 = 6'b11_0000, ALL packet validation failed silently.

This program:
  1. Parses the active Verilog/SystemVerilog source in a design directory,
     using shared bounded preprocessing and native configured hierarchy.
     Unsupported macro/include/generate syntax remains explicitly UNKNOWN.
  2. Builds a module hierarchy by parsing module definitions and instances
  3. For each output port, classifies the encoding used by the producer:
     - BINARY: counter increment (reg <= reg + 1), direct arithmetic
     - GRAY:   gray-code case mapping or binary-to-gray conversion
     - UNKNOWN: cannot determine encoding from static analysis
  4. For each input port consumption, classifies the comparison encoding:
     - BINARY: decimal/hex comparisons (== 6'd32, >= 8'h1A)
     - GRAY:   comparisons where the bit-pattern doesn't match its decimal
               equivalent (== 6'b11_0000 when that != decimal value in context)
     - UNKNOWN: cannot determine
  5. Flags MISMATCH when a producer uses one encoding and consumer uses another

Usage:
    python3 interface_encoding_audit.py --rtl-dir ./rtl/ --top-module DTOP --out-dir /tmp/audit

Output: JSON report listing each interface wire, its producer encoding,
consumer encoding, and MATCH/MISMATCH status.

Generality: works for ANY multi-module Verilog/SystemVerilog design, not tied
to any specific protocol or IC.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _rtl_audit_applicability as _applicability
import _interface_encoding_population as _population
import rtl_hierarchy_drivers as _hierarchy
from module_port_audit import (
    extract_balanced, split_top_level, lexical_mask, module_regions,
    parse_port_list_ansi, parse_non_ansi_ports)
from typing import List, Dict, Set, Tuple, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class PortInfo:
    name: str
    direction: str          # "input" | "output" | "inout"
    width: str              # e.g. "[5:0]" or ""
    module: str             # which module this port belongs to


@dataclass
class ModuleInfo:
    name: str
    file: str
    ports: List[PortInfo]
    body: str               # source code body (comments stripped)
    source_body: str = ''    # retain strings for configured generate selection
    native_widths: Dict[str, int] = field(default_factory=dict)


@dataclass
class InstanceInfo:
    inst_name: str
    module_type: str
    parent_module: str
    connections: Dict[str, str]   # port_name -> signal_name
    connection_expressions: Dict[str, str] = field(default_factory=dict)


@dataclass
class EncodingClassification:
    encoding: str           # BINARY | GRAY | UNKNOWN; closed proof: BIT_VALUE / PREDICATE
    evidence: str           # human-readable reason
    line: int               # source line where evidence was found


@dataclass
class InterfaceAuditResult:
    wire_name: str
    producer_module: str
    producer_port: str
    producer_encoding: str
    producer_evidence: str
    consumer_module: str
    consumer_port: str
    consumer_encoding: str
    consumer_evidence: str
    status: str             # MATCH | MISMATCH | NOT_APPLICABLE | UNKNOWN
    severity: str           # "ERROR" | "WARN" | "INFO"


# Discovery is a separate evidence dimension from the encoding result.  A
# zero-population report is certifiable only when the requested top and every
# source module/instance header were completely discovered.
_DISCOVERY_ISSUES: List[str] = []
_DISCOVERED_MODULE_COUNT = 0
_DISCOVERED_INSTANCE_COUNT = 0
_CONFIGURATION: dict = {}


def _discovery_issue(message: str) -> None:
    if message not in _DISCOVERY_ISSUES:
        _DISCOVERY_ISSUES.append(message)


# ---------------------------------------------------------------------------
# Comment stripper (shared pattern across programs)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove comments while preserving quoted strings and newlines."""
    out = []
    i = 0
    while i < len(src):
        if src[i] == '"':
            j = i + 1
            while j < len(src):
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(src[i:j])
            i = j
        elif src[i:i+2] == '/*':
            end = src.find('*/', i+2)
            if end == -1:
                # Keep the malformed suffix visible; lexical parsing will
                # disclose it as incomplete rather than certify a prefix.
                out.append(src[i:])
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                out.append(' ' * (len(src) - i))
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ---------------------------------------------------------------------------
# Module parser
# ---------------------------------------------------------------------------
def parse_modules(src: str, filepath: str) -> List[ModuleInfo]:
    """Extract complete module definitions using lexical balanced regions."""
    modules: List[ModuleInfo] = []
    issues: List[str] = []
    regions = list(module_regions(src, issues))
    for issue in issues:
        _discovery_issue(f"{issue} ({filepath})")
    for mod_name, header_start, body_start, body_end in regions:
        header = src[header_start:body_start]
        body = lexical_mask(src[body_start:body_end], attributes=True)
        # The shared region scanner already proved the header and endmodule
        # boundary. Locate the ANSI port group while skipping parameters/imports.
        masked = lexical_mask(header, attributes=True)
        name_match = re.search(r'\b' + re.escape(mod_name) + r'\b', masked)
        index = name_match.end() if name_match else 0
        while True:
            while index < len(masked) and masked[index].isspace():
                index += 1
            if not re.match(r'import\b', masked[index:]):
                break
            semi = masked.find(';', index)
            if semi < 0:
                _discovery_issue(f"unterminated import in module '{mod_name}' ({filepath})")
                break
            index = semi + 1
        if index < len(masked) and masked[index] == '#':
            index += 1
            while index < len(masked) and masked[index].isspace():
                index += 1
            result = extract_balanced(masked, index)
            if result is None:
                _discovery_issue(f"unbalanced parameter list in module '{mod_name}' ({filepath})")
                continue
            index = result[1] + 1
        while index < len(masked) and masked[index].isspace():
            index += 1
        port_text = ''
        if index < len(masked) and masked[index] == '(':
            result = extract_balanced(masked, index)
            if result is None:
                _discovery_issue(f"unbalanced port list in module '{mod_name}' ({filepath})")
                continue
            port_text = header[index + 1:result[1]]
        ports = _parse_port_list(port_text, body, mod_name)
        if any(p.direction == 'UNKNOWN' for p in ports):
            _discovery_issue(f"unresolved port direction in module '{mod_name}' ({filepath})")
        modules.append(ModuleInfo(name=mod_name, file=filepath,
                                  ports=ports, body=body,
                                  source_body=src[body_start:body_end]))
    return modules


def _parse_port_list(port_text: str, body: str, mod_name: str) -> List[PortInfo]:
    """Preserve formal order and resolve old-style direction placeholders."""
    clean_ports = lexical_mask(port_text, attributes=True)
    issues: List[str] = []
    parsed = parse_port_list_ansi(f'module {mod_name} ({clean_ports});', '', 1, issues)
    items = split_top_level(clean_ports) if clean_ports.strip() else []
    if len(parsed) != len(items):
        _discovery_issue(f'incomplete or duplicate port population in {mod_name}')
    body_ports = parse_non_ansi_ports(body, '', 1, issues)
    for issue in issues:
        _discovery_issue(f'{issue} in {mod_name}')
    for name, declared in body_ports.items():
        existing = parsed.get(name)
        if existing is None:
            _discovery_issue(f'body port {mod_name}.{name} missing from header')
        elif existing.direction == 'UNKNOWN':
            parsed[name] = declared
        elif (existing.direction, existing.width_expr) != (
                declared.direction, declared.width_expr):
            existing.direction = 'UNKNOWN'
            _discovery_issue(f'ambiguous direction/declaration for {mod_name}.{name}')
    return [PortInfo(name=port.name, direction=port.direction,
                     width=port.width_expr, module=mod_name)
            for port in parsed.values()]


def _split_ports(text: str) -> List[str]:
    """Backward-compatible wrapper around the shared balanced splitter."""
    return split_top_level(text)


def _fixed_nested_bit_select(text: str) -> Optional[str]:
    """Return a canonical fixed nested bit-select, or None if unsupported."""
    match = re.fullmatch(
        r'([A-Za-z_]\w*)((?:\s*\[\s*\d+\s*\]){2,})', text)
    if match is None:
        return None
    indices = re.findall(r'\[\s*(\d+)\s*\]', match.group(2))
    return match.group(1) + ''.join(f'[{index}]' for index in indices)


# ---------------------------------------------------------------------------
# Instance parser
# ---------------------------------------------------------------------------
def parse_instances(body: str, parent_module: str, *, native_checked: bool = False
                    ) -> List[InstanceInfo]:
    """Find named-port module instantiations using balanced delimiters."""
    instances: List[InstanceInfo] = []
    # Keywords that look like instances but aren't
    non_instance = {
        'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
        'logic', 'assign', 'always', 'always_ff', 'always_comb',
        'always_latch', 'initial', 'function', 'endfunction', 'task',
        'endtask', 'parameter', 'localparam', 'generate', 'endgenerate',
        'genvar', 'integer', 'real', 'if', 'else', 'case', 'casez',
        'casex', 'endcase', 'for', 'while', 'repeat', 'begin', 'end',
        'fork', 'join', 'wait', 'disable', 'typedef', 'struct', 'enum',
        'union', 'packed', 'signed', 'unsigned', 'return', 'automatic',
        'static',
    }

    cursor = 0
    candidate_re = re.compile(r'\b(\w+)\s+')
    while True:
        m = candidate_re.search(body, cursor)
        if m is None:
            break
        mod_type = m.group(1)
        if mod_type in non_instance:
            cursor = m.end()
            continue
        index = m.end()
        while index < len(body) and body[index].isspace():
            index += 1
        if index < len(body) and body[index] == '#':
            index += 1
            while index < len(body) and body[index].isspace():
                index += 1
            if index >= len(body) or body[index] != '(':
                cursor = m.end()
                continue
            params = extract_balanced(body, index)
            if params is None:
                _discovery_issue(
                    f"unbalanced parameter override in {parent_module}.{mod_type}")
                cursor = m.end()
                continue
            _, close_at = params
            index = close_at + 1
            while index < len(body) and body[index].isspace():
                index += 1
        inst_match = re.match(r'(\w+)\s*', body[index:])
        if inst_match is None:
            cursor = m.end()
            continue
        inst_name = inst_match.group(1)
        if inst_name in non_instance:
            cursor = m.end()
            continue
        index += inst_match.end()
        while index < len(body) and body[index].isspace():
            index += 1
        if index >= len(body) or body[index] != '(':
            cursor = m.end()
            continue
        conn_result = extract_balanced(body, index)
        if conn_result is None:
            _discovery_issue(
                f"unbalanced connection list in {parent_module}.{inst_name}")
            cursor = m.end()
            continue
        conn_text, close_at = conn_result
        if not conn_text.strip():
            cursor = close_at + 1
            continue

        connections: Dict[str, str] = {}
        connection_expressions: Dict[str, str] = {}
        malformed = False
        for item in split_top_level(conn_text):
            item = item.strip()
            if not item:
                continue
            if item == '.*':
                _discovery_issue(
                    f"wildcard instance connections in {parent_module}.{inst_name}")
                continue
            if not item.startswith('.'):
                # Positional interfaces require formal order/direction.  This
                # auditor has no such encoding consumer model, so disclose the
                # unsupported hierarchy shape rather than silently dropping it.
                _discovery_issue(
                    f"positional instance connections in {parent_module}.{inst_name}")
                continue
            port_match = re.match(r'^\.\s*(\w+)\s*(.*)$', item, re.DOTALL)
            if port_match is None:
                malformed = True
                continue
            port = port_match.group(1)
            tail = port_match.group(2).strip()
            if not tail:
                # `.port` is a legal implicit same-name connection.
                connections[port] = port
                connection_expressions[port] = port
                continue
            if not tail.startswith('('):
                malformed = True
                continue
            actual_result = extract_balanced(tail, 0)
            if actual_result is None or tail[actual_result[1] + 1:].strip():
                malformed = True
                continue
            sig = actual_result[0].strip()
            connection_expressions[port] = sig
            nested_select = _fixed_nested_bit_select(sig)
            sm = re.fullmatch(r'(\w+)(?:\s*\[[^\]]+\])?', sig)
            if nested_select is not None:
                # Retain a closed, fixed nested selection in the population.
                # Its encoding remains unsupported and is forced UNKNOWN by
                # run_audit rather than inferred from the formal port bodies.
                connections[port] = nested_select
            elif sm:
                connections[port] = sm.group(1)
            elif not sig:
                connections[port] = ''
            elif parse_verilog_literal(sig) is not None or isinstance(
                    _hierarchy.constant(sig, {}), int):
                # A literal input has no cross-module wire to trace. Keep
                # the instance for native hierarchy closure, without making
                # this constant an encoding result or inventing a wire name.
                connections[port] = ''
            elif native_checked:
                # Native elaboration validated this live expression. Retain
                # it verbatim as an opaque parent-side carrier: encoding
                # inference must not collapse a concat/ternary into one net.
                connections[port] = sig
                _CONFIGURATION.setdefault('opaque_connections', []).append({
                    'module': parent_module, 'instance': inst_name,
                    'port': port, 'expression': sig})
            else:
                malformed = True

        instances.append(InstanceInfo(
            inst_name=inst_name,
            module_type=mod_type,
            parent_module=parent_module,
            connections=connections,
            connection_expressions=connection_expressions))
        if malformed:
            _discovery_issue(
                f"unsupported connection syntax in {parent_module}.{inst_name}")
        cursor = close_at + 1
    return instances


# ---------------------------------------------------------------------------
# Encoding classifiers
# ---------------------------------------------------------------------------

# Gray code: known binary-to-gray mappings for common widths
# For a value N, gray(N) = N ^ (N >> 1)
def binary_to_gray(n: int) -> int:
    """Convert binary integer to gray code."""
    return n ^ (n >> 1)


def gray_to_binary(g: int, bits: int) -> int:
    """Convert gray code integer to binary."""
    mask = g
    while mask:
        mask >>= 1
        g ^= mask
    return g


def is_gray_code_value(bit_pattern: int, decimal_value: int) -> bool:
    """Check if bit_pattern is the gray-code encoding of decimal_value."""
    return binary_to_gray(decimal_value) == bit_pattern


def parse_verilog_literal(lit: str) -> Optional[Tuple[int, int]]:
    """Parse a Verilog literal like 6'b11_0000 or 8'hFF or 4'd12.
    Returns (width, value) or None if unparseable."""
    lit = lit.strip().replace('_', '')
    m = re.match(r"(\d+)'([bBoOdDhH])([0-9a-fA-F_xXzZ]+)", lit)
    if not m:
        return None
    width = int(m.group(1))
    base_ch = m.group(2).lower()
    digits = m.group(3).lower()
    if 'x' in digits or 'z' in digits:
        return None
    base_map = {'b': 2, 'o': 8, 'd': 10, 'h': 16}
    base = base_map.get(base_ch)
    if base is None:
        return None
    try:
        value = int(digits, base)
    except ValueError:
        return None
    return (width, value)


def _binary_counter_projection(body: str, signal_name: str) -> Optional[EncodingClassification]:
    """Recognize one fixed projection of an explicitly numeric counter.

    This is deliberately a closed grammar: one continuous output driver,
    literal state bounds, whole-state arithmetic updates and one literal reset
    value.
    Arbitrary aliases, transforms and partially written storage stay UNKNOWN.
    The caller supplies the native-selected module body.
    """
    clean = lexical_mask(body, attributes=True)
    name = re.escape(signal_name)
    # Concatenated LHS writes are not captured by a single-identifier driver.
    # Do not mistake one recognized write for the complete driver set.
    def other_write(target):
        return (re.search(r'\{[^;]*\b' + target + r'\b[^;]*\}\s*(?:<=|=(?!=))', clean)
                or re.search(r'(?:\+\+|--)\s*\b' + target + r'\b', clean))

    if other_write(name):
        return None
    drivers = list(re.finditer(r'\bassign\s+' + name + r'\s*=\s*([^;]+);', clean))
    writes = list(re.finditer(r'\b' + name + r'\s*(?:\[[^]]+\]\s*)?(?:<=|=(?!=))', clean))
    if len(drivers) != 1 or len(writes) != 1:
        return None
    projection = re.fullmatch(
        r'\s*([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\])?\s*',
        drivers[0].group(1))
    if not projection:
        return None
    state, high, low = projection.groups()
    if state == signal_name:
        return None
    state_name = re.escape(state)
    if other_write(state_name):
        return None
    declarations = list(re.finditer(
        r'\b(?:reg|logic|bit)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*' +
        state_name + r'\s*;', clean))
    if len(declarations) != 1:
        return None
    left, right = map(int, declarations[0].groups())
    if high is not None:
        start, end = int(high), int(low if low is not None else high)
        if not (min(left, right) <= start <= max(left, right)
                and min(left, right) <= end <= max(left, right)):
            return None
        if low is not None and (start > end) != (left > right) and start != end:
            return None
    # Reject partial/blocking drivers, unknown write forms and child drivers.
    assignments = list(re.finditer(
        r'\b' + state_name + r'\s*(\[[^]]+\])?\s*(<=|=(?!=))\s*([^;]+);', clean))
    if not assignments or re.search(r'\b' + state_name + r'\s*(?:\+\+|--|[+\-*/&|^]=)', clean):
        return None
    if re.search(r'\.\w+\s*\(\s*' + state_name + r'\s*(?:\[|\))', clean):
        return None
    literal = r"(?:\d+\s*'\s*[sS]?[bB][01_]+|\d+\s*'\s*[sS]?[oO][0-7_]+|\d+\s*'\s*[sS]?[dD][0-9_]+|\d+\s*'\s*[sS]?[hH][0-9a-fA-F_]+|'[01]|\d+)"
    atom = r'(?:' + literal + r'|[A-Za-z_]\w*(?:\s*\[\s*\d+\s*(?::\s*\d+\s*)?\])?)'
    term = r'(?:' + atom + r'|\{\s*' + atom + r'(?:\s*,\s*' + atom + r')+\s*\})'
    update = re.compile(state_name + r'\s*[+\-]\s*' + term)
    arithmetic = []
    reset_values = set()
    state_width = abs(left - right) + 1
    for assignment in assignments:
        selected, operator, expression = assignment.groups()
        if selected is not None or operator != '<=':
            return None
        expression = expression.strip()
        if update.fullmatch(expression):
            arithmetic.append(assignment)
        elif not re.fullmatch(literal, expression):
            return None
        else:
            # Distinct literal transitions do not establish counter reset
            # semantics. Compare effective state values, not spelling.
            token = re.sub(r"[\s_]", "", expression)
            if token in ("'0", "'1"):
                value = 0 if token == "'0" else (1 << state_width) - 1
            elif token.isdecimal():
                value = int(token)
            else:
                parsed = parse_verilog_literal(re.sub(r"'[sS]", "'", token))
                if parsed is None or parsed[0] <= 0:
                    return None
                bits, value = parsed
                value %= 1 << bits
                if re.search(r"'[sS]", token) and value & (1 << (bits - 1)):
                    value -= 1 << bits
            reset_values.add(value % (1 << state_width))
            if len(reset_values) > 1:
                return None
    if not arithmetic:
        return None
    line = clean.count('\n', 0, drivers[0].start()) + 1
    update_lines = ','.join(str(clean.count('\n', 0, a.start()) + 1) for a in arithmetic)
    return EncodingClassification(
        'BINARY',
        f'fixed counter projection: {signal_name} = {projection.group(0).strip()}; '
        f'{state}[{left}:{right}] whole-state arithmetic at line(s) {update_lines}', line)


def classify_producer_encoding(body: str, signal_name: str) -> EncodingClassification:
    """
    Classify how a signal is produced:
      - BINARY: incremented (reg <= reg + 1), arithmetic, direct assignment
      - GRAY: gray-code case mapping, or binary-to-gray conversion (^ >>1)
      - UNKNOWN: can't determine
    """
    lines = body.split('\n')

    # Pattern 1: Binary increment — signal <= signal + 1 (or + 'b1, + 'd1)
    inc_pattern = re.compile(
        r'\b' + re.escape(signal_name) + r'\s*<=\s*'
        r'\b' + re.escape(signal_name) + r'\s*\+\s*'
        r"(?:1(?:'[bdh]1)?|'[bdh]1|1'b1)\s*;",
        re.IGNORECASE)
    for lineno, line in enumerate(lines, 1):
        if inc_pattern.search(line):
            return EncodingClassification(
                "BINARY",
                f"counter increment: {signal_name} <= {signal_name} + 1",
                lineno)

    # Pattern 1b: Binary decrement — signal <= signal - 1
    dec_pattern = re.compile(
        r'\b' + re.escape(signal_name) + r'\s*<=\s*'
        r'\b' + re.escape(signal_name) + r'\s*-\s*'
        r"(?:1(?:'[bdh]1)?|'[bdh]1|1'b1)\s*;",
        re.IGNORECASE)
    for lineno, line in enumerate(lines, 1):
        if dec_pattern.search(line):
            return EncodingClassification(
                "BINARY",
                f"counter decrement: {signal_name} <= {signal_name} - 1",
                lineno)

    # Pattern 1c: Arithmetic operation — signal <= expr +/- expr (general)
    arith_pattern = re.compile(
        r'\b' + re.escape(signal_name) + r'\s*<=\s*'
        r'[^;]*[\+\-\*\/\%][^;]*;')
    for lineno, line in enumerate(lines, 1):
        if arith_pattern.search(line):
            return EncodingClassification(
                "BINARY",
                f"arithmetic assignment to {signal_name}",
                lineno)

    # Pattern 2: Binary-to-gray conversion — signal <= expr ^ (expr >> 1)
    b2g_pattern = re.compile(
        r'\b' + re.escape(signal_name) + r'\s*<=\s*'
        r'(\w+)\s*\^\s*\(\s*\1\s*>>\s*1\s*\)\s*;')
    for lineno, line in enumerate(lines, 1):
        if b2g_pattern.search(line):
            return EncodingClassification(
                "GRAY",
                f"binary-to-gray conversion: {signal_name} <= x ^ (x >> 1)",
                lineno)

    # Pattern 2b: Explicit gray-code case mapping
    # Look for case blocks that assign to signal_name with gray-code patterns
    gray_case = _detect_gray_case_producer(body, signal_name)
    if gray_case:
        return gray_case

    # Pattern 3: Direct constant assignment (decimal/hex = binary)
    dec_assign = re.compile(
        r'\b' + re.escape(signal_name) + r"\s*<=\s*\d+'[dDhH][0-9a-fA-F_]+\s*;")
    for lineno, line in enumerate(lines, 1):
        if dec_assign.search(line):
            return EncodingClassification(
                "BINARY",
                f"decimal/hex constant assignment to {signal_name}",
                lineno)

    projection = _binary_counter_projection(body, signal_name)
    if projection is not None:
        return projection
    return EncodingClassification("UNKNOWN", "encoding could not be determined", 0)


def _detect_gray_case_producer(body: str, signal_name: str) -> Optional[EncodingClassification]:
    """
    Detect if signal_name is assigned in a case block that maps sequential
    binary inputs to gray-code output values (or vice versa).
    """
    lines = body.split('\n')
    in_case = False
    case_line = 0
    assignments_in_case = []

    for lineno, line in enumerate(lines, 1):
        if re.search(r'\bcase[szx]?\s*\(', line):
            in_case = True
            case_line = lineno
            assignments_in_case = []
        if in_case:
            # Check for assignment to our signal
            am = re.search(
                r'\b' + re.escape(signal_name) + r"\s*<=\s*(\d+'[bBoOdDhH][0-9a-fA-F_]+)\s*;",
                line)
            if am:
                assignments_in_case.append(am.group(1))
        if in_case and 'endcase' in line:
            in_case = False
            # Analyze: if multiple binary-literal assignments, check if they
            # form a gray-code sequence
            if len(assignments_in_case) >= 3:
                values = []
                for lit in assignments_in_case:
                    parsed = parse_verilog_literal(lit)
                    if parsed:
                        values.append(parsed[1])
                if len(values) >= 3 and _looks_like_gray_sequence(values):
                    return EncodingClassification(
                        "GRAY",
                        f"case block maps to gray-code values for {signal_name}",
                        case_line)
    return None


def _looks_like_gray_sequence(values: List[int]) -> bool:
    """
    Check if a list of integer values looks like gray-code values for
    sequential indices. For each pair of adjacent values, only 1 bit should
    differ (the defining property of gray codes).
    """
    if len(values) < 2:
        return False
    one_bit_diffs = 0
    total_pairs = 0
    for i in range(len(values) - 1):
        xor = values[i] ^ values[i + 1]
        total_pairs += 1
        if xor != 0 and (xor & (xor - 1)) == 0:
            # Exactly one bit differs
            one_bit_diffs += 1
    # If most adjacent pairs differ by 1 bit, it's gray-like
    return one_bit_diffs >= (total_pairs * 0.6)


def classify_consumer_encoding(body: str, signal_name: str) -> EncodingClassification:
    """
    Classify how a signal is consumed (compared):
      - BINARY: compared with decimal/hex literals (== 6'd32, >= 8'hFF)
      - GRAY: compared with binary literals whose bit patterns suggest gray encoding
      - UNKNOWN: no comparison found or can't determine
    """
    lines = body.split('\n')

    binary_comparisons = []
    gray_comparisons = []
    binary_literal_comparisons = []

    for lineno, line in enumerate(lines, 1):
        # Pattern: signal == literal, signal >= literal, signal <= literal, signal != literal
        cmp_pattern = re.compile(
            r'\b' + re.escape(signal_name)
            + r"\s*(?:==|!=|>=|<=|>|<)\s*"
            + r"(\d+'[bBoOdDhH][0-9a-fA-F_]+)")
        for cm in cmp_pattern.finditer(line):
            literal = cm.group(1)
            parsed = parse_verilog_literal(literal)
            if not parsed:
                continue
            width, value = parsed

            # Check base specifier
            base_m = re.match(r"\d+'([bBoOdDhH])", literal.replace('_', ''))
            if not base_m:
                continue
            base_ch = base_m.group(1).lower()

            if base_ch in ('d', 'h'):
                # Decimal or hex literal → binary encoding assumption
                binary_comparisons.append((lineno, literal, value))
            elif base_ch == 'b':
                # Binary literal — need to determine if it represents
                # a gray-code or binary value
                binary_literal_comparisons.append((lineno, literal, value, width))

        # Also check for comparison with plain decimal: signal == 32
        plain_cmp = re.compile(
            r'\b' + re.escape(signal_name)
            + r'\s*(?:==|!=|>=|<=|>|<)\s*(\d+)\b'
            + r"(?!\s*')")  # not followed by a base specifier
        for pm in plain_cmp.finditer(line):
            try:
                val = int(pm.group(1))
                binary_comparisons.append((lineno, pm.group(1), val))
            except ValueError:
                pass

    # Analyze binary literal comparisons: are they gray-coded?
    for lineno, literal, value, width in binary_literal_comparisons:
        # Check if this binary pattern matches the gray-code of some
        # "round" or meaningful decimal number
        gray_match = _check_gray_code_comparison(value, width)
        if gray_match is not None:
            gray_comparisons.append((lineno, literal, value, gray_match))
        else:
            # The binary literal could just be a straight binary comparison
            binary_comparisons.append((lineno, literal, value))

    # Decision
    if gray_comparisons and not binary_comparisons:
        first = gray_comparisons[0]
        return EncodingClassification(
            "GRAY",
            f"compared with gray-code literal {first[1]} "
            f"(gray({first[3]}) = {first[2]})",
            first[0])
    elif binary_comparisons and not gray_comparisons:
        first = binary_comparisons[0]
        return EncodingClassification(
            "BINARY",
            f"compared with binary/decimal literal {first[1]}",
            first[0])
    elif binary_comparisons and gray_comparisons:
        # Mixed — report the gray ones as they are more suspicious
        first = gray_comparisons[0]
        return EncodingClassification(
            "GRAY",
            f"mixed comparisons detected; gray-code literal {first[1]} "
            f"(gray({first[3]}) = {first[2]}) found alongside binary literals",
            first[0])

    return EncodingClassification("UNKNOWN", "no comparison pattern found", 0)


def _check_gray_code_comparison(bit_value: int, width: int) -> Optional[int]:
    """
    Check if bit_value is the gray-code of some meaningful number.
    Returns the original decimal value if it is, None otherwise.

    "Meaningful" = a power of 2, a multiple of 8, or common protocol lengths
    (8, 16, 24, 32, 48, 64, 128, 256).
    """
    # Common comparison values in protocol designs
    interesting_values = set()
    # Powers of 2
    for exp in range(1, width + 1):
        interesting_values.add(1 << exp)
    # Multiples of 8 up to max value for width
    max_val = (1 << width) - 1
    for mult in range(8, max_val + 1, 8):
        interesting_values.add(mult)
    # Common protocol sizes
    for v in [8, 16, 24, 32, 48, 64, 128, 256]:
        if v <= max_val:
            interesting_values.add(v)

    for dec_val in interesting_values:
        gray_val = binary_to_gray(dec_val)
        if gray_val == bit_value and gray_val != dec_val:
            # The bit pattern IS the gray code of dec_val, and it's DIFFERENT
            # from the binary representation — this is a gray-code comparison
            return dec_val
    return None


_EXPRESSION_TOKEN = re.compile(
    r'[A-Za-z_$][A-Za-z0-9_$]*|'
    r'<<<=' + r'|>>>=' + r'|===' + r'|!==' + r'|<<=' + r'|>>=' +
    r'|==|!=|<=|>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|'
    r'::|&&|\|\||<<|>>|\+\+|--|->|=>|\*\*|\S')
_STATEMENT_OPENERS = {
    'begin', 'else', 'end', 'endcase', 'fork', 'join', 'join_any',
    'join_none', 'initial', 'always', 'always_ff', 'always_comb',
    'always_latch', 'do',
}


def _balanced_expression_tokens(body):
    """Return source-offset tokens plus delimiter pairs, or refuse imbalance.

    Physical lines are deliberately absent from this grammar.  Strings are
    masked without moving offsets, and every (), [] and {} must balance before
    a ternary condition can be certified.
    """
    try:
        masked = lexical_mask(body)
    except ValueError:
        return None, None
    tokens = [(match.group(0), match.start(), match.end())
              for match in _EXPRESSION_TOKEN.finditer(masked)]
    stack = []
    pairs = {}
    opener_for = {')': '(', ']': '[', '}': '{'}
    for index, (value, _, _) in enumerate(tokens):
        if value in '([{':
            stack.append((value, index))
        elif value in ')]}':
            if not stack or stack[-1][0] != opener_for[value]:
                return None, None
            _, opening = stack.pop()
            pairs[opening] = index
            pairs[index] = opening
    if stack:
        return None, None
    return tokens, pairs


def _nonblocking_assignment_boundary(tokens, pairs, operator):
    """Whether ``operator`` is a statement-initial bare-LHS ``<=``.

    The same token is relational inside expressions.  Requiring a bare LHS at
    a statement boundary prevents ``dst <= seed <= flag ?`` from treating the
    second operator as an assignment boundary.
    """
    lhs = operator - 1
    if lhs < 0 or not re.fullmatch(r'[A-Za-z_]\w*', tokens[lhs][0]):
        return False
    previous = lhs - 1
    if previous < 0:
        return True
    value = tokens[previous][0]
    if value == ';' or value in _STATEMENT_OPENERS:
        return True
    if value == ')':
        opening = pairs.get(previous)
        return (opening is not None and opening > 0
                and tokens[opening - 1][0] in {'if', 'else'})
    return False


def _whole_ternary_predicate_spans(body, port):
    """Offsets of ternary conditions whose complete expression is port/!port."""
    tokens, pairs = _balanced_expression_tokens(body)
    if tokens is None:
        return []
    spans = []
    for question, (value, _, _) in enumerate(tokens):
        if value != '?' or question == 0:
            continue
        port_token = question - 1
        if tokens[port_token][0] != port:
            continue
        condition = port_token
        if condition and tokens[condition - 1][0] == '!':
            condition -= 1
        boundary = condition - 1
        if boundary < 0:
            valid = True
        else:
            previous = tokens[boundary][0]
            # Preserve the deliberately closed grammar.  A predicate inside a
            # select or concatenation is still a data expression and remains
            # UNKNOWN, even when that nested ternary itself branches on port.
            valid = previous in {'(', ',', ':', '?', '='}
            if previous == '<=':
                valid = _nonblocking_assignment_boundary(tokens, pairs, boundary)
        if valid:
            spans.append((tokens[port_token][1], tokens[port_token][2],
                          tokens[condition][1]))
    return spans


_VERILOG_NUMBER = re.compile(
    r"(?:\b\d+\s*)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|\b\d+\b")


_DOMAIN_KEYWORDS = frozenset({
    'always', 'always_comb', 'always_ff', 'always_latch', 'assign', 'begin',
    'case', 'casex', 'casez', 'default', 'else', 'end', 'endcase', 'for',
    'if', 'integer', 'logic', 'reg', 'signed', 'unsigned', 'wire',
})


def _domain_expression_names(expression):
    """Return the identifiers in a bounded source expression, or ``None``.

    Calls, hierarchy, concatenation and preprocessing require a typed contract;
    accepting them from lexical width alone would recreate the false proof this
    helper is meant to prevent.
    """
    expression = _VERILOG_NUMBER.sub(' ', expression)
    if ('$' in expression or '{' in expression or '}' in expression
            or '`' in expression or '::' in expression or '\\' in expression
            or re.search(r'\b[A-Za-z_]\w*\s*\(', expression)):
        return None
    return {name for name in re.findall(
        r'(?<![\w$])[A-Za-z_]\w*(?![\w$])', expression)
            if name not in _DOMAIN_KEYWORDS}


def _domain_control_ranges(body):
    """Map each bounded ``if`` arm to the identifiers controlling that arm."""
    import rtl_hygiene_lint as lint

    ranges = []
    for match in re.finditer(r'\bif\s*\(', body):
        opening = body.find('(', match.start(), match.end())
        balanced = extract_balanced(body, opening)
        if balanced is None:
            return None
        condition, close = balanced
        names = _domain_expression_names(condition)
        arm_start = close + 1
        arm_end = lint._procedural_statement_end(body, arm_start)
        if arm_end <= arm_start:
            return None
        ranges.append((arm_start, arm_end, names))
        cursor = arm_end
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if body.startswith('else', cursor) and not re.match(r'\w', body[cursor + 4:cursor + 5]):
            else_start = cursor + 4
            else_end = lint._procedural_statement_end(body, else_start)
            if else_end <= else_start:
                return None
            ranges.append((else_start, else_end, names))
    return ranges


def _domain_assignment_dependencies(module):
    """Collect complete bounded data/control dependencies for scalar writes."""
    body = module.body
    controls = _domain_control_ranges(body)
    if controls is None:
        return None
    assignments = {}
    for match in re.finditer(
            r'(?<![\w$])([A-Za-z_]\w*)\s*(?:<=|=(?!=))\s*([^;]+);',
            body, re.MULTILINE | re.DOTALL):
        target, expression = match.group(1), match.group(2)
        names = _domain_expression_names(expression)
        for start, end, guard_names in controls:
            if start <= match.start() < end:
                if names is None or guard_names is None:
                    names = None
                    break
                names.update(guard_names)
        assignments.setdefault(target, []).append(names)
    return assignments


def _domain_local_roots(module, *, target=None, expression=None):
    """Resolve a scalar expression to its complete local input dependency set."""
    if (target is None) == (expression is None):
        return None
    assignments = _domain_assignment_dependencies(module)
    if assignments is None:
        return None
    inputs = {port.name for port in module.ports if port.direction == 'input'}
    if expression is not None:
        pending = _domain_expression_names(expression)
        if pending is None:
            return None
    else:
        if target not in assignments:
            return None
        pending = {target}
    roots = set()
    visiting = set()

    def visit(name):
        if module.native_widths.get(name) != 1 or name in visiting:
            return False
        if name in assignments:
            visiting.add(name)
            ok = all(row is not None and all(visit(dependency) for dependency in row)
                     for row in assignments[name])
            visiting.remove(name)
            return ok
        if name not in inputs:
            return False
        roots.add(name)
        return True

    if not all(visit(name) for name in pending):
        return None
    return roots


def _fixed_slice_equality_alias_domain(module, target):
    """Prove one closed Boolean producer grammar through local aliases.

    The terminal must be ``word[fixed:fixed] == N'b...`` with an explicit,
    fully-known literal whose width equals the selected width.  Every value
    above it is a whole one-bit alias and has no reference outside that chain.
    This proves that the boundary value is an equality predicate; it does not
    infer the encoding of ``word`` and deliberately excludes dynamic selects,
    inequalities, arithmetic and partial writes.
    """
    if module.native_widths.get(target) != 1:
        return None
    assignments = {}
    # The retained grammar needs declaration/continuous initializers and one
    # simple blocking alias.  Bare ``<=`` is intentionally absent: outside a
    # parsed procedural owner it is also the relational operator, so a legal
    # for-condition such as ``a <= b`` must never manufacture a write to a.
    for match in re.finditer(
            r'(?<![\w$])([A-Za-z_]\w*)\s*=(?!=)\s*([^;]+);',
            module.body, re.MULTILINE | re.DOTALL):
        assignments.setdefault(match.group(1), []).append(match)

    aliases = []
    proven = {}
    visiting = set()

    def visit(name):
        if module.native_widths.get(name) != 1 or name in visiting:
            return None
        rows = assignments.get(name, [])
        if len(rows) != 1:
            return None
        assignment = rows[0]
        expression = assignment.group(2).strip()
        visiting.add(name)
        alias = re.fullmatch(r'([A-Za-z_]\w*)', expression)
        if alias is not None:
            peer = alias.group(1)
            result = visit(peer)
            if result is not None:
                aliases.append((name, peer))
                proven.setdefault(name, set()).add(assignment.span(1))
                proven.setdefault(peer, set()).add(assignment.span(2))
        else:
            equality = re.fullmatch(
                r'([A-Za-z_]\w*)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*'
                r'==\s*(\d+)\s*\'\s*[bB]\s*([01_]+)', expression)
            result = None
            if equality is not None:
                base, high, low, literal_width, bits = equality.groups()
                high, low, literal_width = map(int, (high, low, literal_width))
                selected_width = abs(high - low) + 1
                base_width = module.native_widths.get(base)
                if (isinstance(base_width, int)
                        and max(high, low) < base_width
                        and literal_width == selected_width
                        and len(bits.replace('_', '')) == literal_width):
                    result = (base, high, low, literal_width, bits,
                              module.body.count('\n', 0, assignment.start()) + 1)
                    proven.setdefault(name, set()).add(assignment.span(1))
        visiting.remove(name)
        return result

    terminal = visit(target)
    if terminal is None:
        return None
    for name, spans in proven.items():
        refs = {match.span() for match in re.finditer(
            r'(?<![\w$])' + re.escape(name) + r'(?![\w$])', module.body)}
        if refs != spans:
            return None
    base, high, low, width, bits, line = terminal
    chain = ' -> '.join([f'{left}={right}' for left, right in reversed(aliases)])
    return (
        f'native fixed slice equality {base}[{high}:{low}] == {width}\'b{bits} '
        f'at body line {line} through complete one-bit alias chain {chain}; '
        'equality result is a predicate and source-word encoding is not inferred')


def _domain_parent_expression(module, expression, modules, instances, trail):
    """Trace a scalar actual through parent bindings to external one-bit roots."""
    roots = _domain_local_roots(module, expression=expression)
    if roots is None:
        return None
    parents = [instance for instance in instances if instance.module_type == module.name]
    if not parents:
        return {(module.name, root) for root in roots}
    resolved = set()
    for instance in parents:
        parent = modules.get(instance.parent_module)
        if parent is None:
            return None
        marker = (instance.parent_module, instance.inst_name, module.name)
        if marker in trail:
            return None
        for root in roots:
            actual = instance.connection_expressions.get(root)
            if not actual:
                return None
            upstream = _domain_parent_expression(
                parent, actual, modules, instances, trail | {marker})
            if upstream is None:
                return None
            resolved.update(upstream)
    return resolved


def _producer_one_bit_source_domain(producer, producer_port, parent,
                                    boundaries, modules, instances):
    """Return source-bound proof that every output value is one-bit sourced.

    A one-bit boundary width alone is insufficient: a producer can serialize a
    wider encoded word through that bit over time.  Admit the predicate lemma
    only when the complete transitive data/control closure, including parent
    bindings, reaches solely native one-bit inputs (or literals). Unknown
    functions, parameters and wider/select source nets remain outside this
    deliberately closed proof.
    """
    if (_CONFIGURATION.get('native', {}).get('status') != 'MEASURED'
            or producer.native_widths.get(producer_port) != 1):
        return None
    roots = _domain_local_roots(producer, target=producer_port)
    if roots is None:
        return _fixed_slice_equality_alias_domain(producer, producer_port)
    external = set()
    for boundary in boundaries:
        for root in roots:
            actual = boundary.connection_expressions.get(root)
            if not actual:
                return None
            upstream = _domain_parent_expression(
                parent, actual, modules, instances,
                {(parent.name, boundary.inst_name, producer.name)})
            if upstream is None:
                return None
            external.update(upstream)
    named = ','.join(f'{module}.{name}' for module, name in sorted(external))
    return ('native one-bit source domain with complete transitive data/control '
            f'and parent-binding closure: {named or "literal-only"}; '
            'no wider word projection inferred')


def _whole_scalar_predicate(wire, producer, producer_port, consumer,
                            consumer_port, parent, modules, instances):
    """Closed non-word grammar, not a scalar encoding default.

    Both declared boundary ports and the parent carrier must be native whole
    one-bit values, with unselected named connections. EVERY consumer reference
    must be the entire condition of if(p), if(!p), p?a:b or !p?a:b; a second data/arithmetic/
    comparison/instance use refuses. No alias chasing or partial proof applies.

    For this domain G(b)=b^(b>>1) has the same if-branch choice as b:
    0 -> 0, 1 -> 1, x -> x, z -> x (x and z both select the false arm).
    Negation preserves these choices too; ternary merges the same two arms
    for either unknown condition (x/z). This proves only Gray/Binary branch
    invariance, never producer encoding, data functionality or control polarity.
    """
    if (_DISCOVERY_ISSUES
            or not re.fullmatch(r'[A-Za-z_]\w*', wire)
            or producer.native_widths.get(producer_port) != 1
            or consumer.native_widths.get(consumer_port) != 1
            or parent.native_widths.get(wire) != 1
            or not any(p.name == producer_port and p.direction == 'output'
                       for p in producer.ports)
            or not any(p.name == consumer_port and p.direction == 'input'
                       for p in consumer.ports)):
        return None
    producer_boundaries = []
    for module, port in ((producer, producer_port), (consumer, consumer_port)):
        boundaries = [inst for inst in instances
                      if inst.parent_module == parent.name
                      and inst.module_type == module.name
                      and inst.connections.get(port) == wire]
        if not boundaries or any(inst.connection_expressions.get(port) != wire
                                 for inst in boundaries):
            return None
        if module is producer:
            producer_boundaries = boundaries
    producer_domain = _producer_one_bit_source_domain(
        producer, producer_port, parent, producer_boundaries, modules, instances)
    if producer_domain is None:
        return None
    name = re.escape(consumer_port)
    refs = list(re.finditer(r'(?<![\w$])' + name + r'(?![\w$])', consumer.body))
    guards = list(re.finditer(r'\bif\s*\(\s*!?\s*(' + name + r')\s*\)', consumer.body))
    # A physical newline is never an expression boundary.  Tokenise and
    # balance the containing expression so a suffix such as
    # ``1'bz ===\n p ? x : y`` cannot be promoted to a whole predicate.
    selectors = _whole_ternary_predicate_spans(consumer.body, consumer_port)
    proven = {m.span(1) for m in guards} | {(start, end)
                                            for start, end, _ in selectors}
    if not refs or {m.span() for m in refs} != proven:
        return None
    evidence_starts = [m.start() for m in guards] + [start for _, _, start in selectors]
    lines = ','.join(str(consumer.body.count('\n', 0, start) + 1)
                     for start in evidence_starts)
    return (
        EncodingClassification(
            'PREDICATE',
            f'native whole scalar ports/carrier; all references to {consumer_port} '
            f'are complete if(p)/if(!p) or p?a:b/!p?a:b conditions at body line(s) {lines}; '
            'Gray/Binary branch invariant over 0,1,x,z; producer encoding unclassified',
            consumer.body.count('\n', 0, evidence_starts[0]) + 1),
        producer_domain,
    )


def _whole_copy_assignments(module, signal, *, source=False):
    """Return closed whole-value copies for one port, or ``None``.

    This deliberately small grammar accepts only a bare port on one side of a
    whole assignment and a same-width declared port on the other.  A select,
    concat, operator, literal, call, partial write, local alias or second use is
    outside the grammar.  Native widths are part of the proof: spelling and a
    scalar-looking declaration are not enough.
    """
    width = module.native_widths.get(signal)
    if not isinstance(width, int) or width < 1:
        return None
    ports = {port.name: port for port in module.ports}
    signal_port = ports.get(signal)
    expected_direction = 'output' if source else 'input'
    if signal_port is None or signal_port.direction != expected_direction:
        return None

    refs = list(re.finditer(
        r'(?<![\w$])' + re.escape(signal) + r'(?![\w$])', module.body))
    if not refs:
        return None
    proven = set()
    peers = set()
    assignments = re.finditer(
        r'(?<![\w$])([A-Za-z_]\w*)\s*(?:<=|=(?!=))\s*'
        r'([A-Za-z_]\w*)\s*;', module.body, re.MULTILINE)
    for assignment in assignments:
        target, value = assignment.group(1), assignment.group(2)
        if source and target == signal:
            peer, span = value, assignment.span(1)
        elif not source and value == signal:
            peer, span = target, assignment.span(2)
        else:
            continue
        peer_port = ports.get(peer)
        peer_direction = 'input' if source else 'output'
        if (peer_port is None or peer_port.direction != peer_direction
                or module.native_widths.get(peer) != width):
            return None
        proven.add(span)
        peers.add(peer)
    if not proven or {ref.span() for ref in refs} != proven:
        return None
    lines = sorted({module.body.count('\n', 0, start) + 1
                    for start, _ in proven})
    return width, sorted(peers), lines


def _whole_nonencoding_value(wire, producer, producer_port, consumer,
                             consumer_port, parent, modules, instances):
    """Prove a finite source-bound edge has no encoding interpretation.

    This is not a BINARY default and it does not exempt scalar boundaries.
    Both actual connections must be unselected named whole values.  The
    consumer must copy the complete value to a same-width output and use the
    input nowhere else.  Multi-bit producers must likewise be same-width input
    copies.  One-bit producers may instead use the existing complete
    transitive Boolean source-domain proof.
    """
    if (_DISCOVERY_ISSUES
            or _CONFIGURATION.get('native', {}).get('status') != 'MEASURED'
            or not re.fullmatch(r'[A-Za-z_]\w*', wire)):
        return None
    width = producer.native_widths.get(producer_port)
    if (not isinstance(width, int) or width < 1
            or consumer.native_widths.get(consumer_port) != width
            or parent.native_widths.get(wire) != width):
        return None
    producer_boundaries = [
        inst for inst in instances
        if inst.parent_module == parent.name
        and inst.module_type == producer.name
        and inst.connections.get(producer_port) == wire]
    consumer_boundaries = [
        inst for inst in instances
        if inst.parent_module == parent.name
        and inst.module_type == consumer.name
        and inst.connections.get(consumer_port) == wire]
    if (not producer_boundaries or not consumer_boundaries
            or any(inst.connection_expressions.get(producer_port) != wire
                   for inst in producer_boundaries)
            or any(inst.connection_expressions.get(consumer_port) != wire
                   for inst in consumer_boundaries)):
        return None
    consumed = _whole_copy_assignments(consumer, consumer_port, source=False)
    if consumed is None:
        return None
    if width == 1:
        source_evidence = _producer_one_bit_source_domain(
            producer, producer_port, parent, producer_boundaries,
            modules, instances)
        if source_evidence is None:
            return None
        role = 'BOOLEAN_VALUE'
    else:
        produced = _whole_copy_assignments(producer, producer_port, source=True)
        if produced is None:
            return None
        _, peers, lines = produced
        source_evidence = (
            f'native whole {width}-bit value copied only from same-width input '
            f'port(s) {",".join(peers)} at body line(s) '
            f'{",".join(map(str, lines))}; encoding is not inferred')
        role = 'OPAQUE_VALUE'
    _, outputs, lines = consumed
    sink_evidence = (
        f'native whole {width}-bit value copied only to same-width output '
        f'port(s) {",".join(outputs)} at body line(s) '
        f'{",".join(map(str, lines))}; no comparison, transform, select, '
        'partial write or control interpretation')
    return (EncodingClassification(role, source_evidence, 0),
            EncodingClassification(role, sink_evidence, lines[0]))


# ---------------------------------------------------------------------------
# Cross-module interface tracing
# ---------------------------------------------------------------------------
def build_interface_map(
    modules: Dict[str, ModuleInfo],
    instances: List[InstanceInfo]
) -> List[Tuple[str, str, str, str, str, str]]:
    """
    Build list of cross-module interfaces with transitive resolution.

    When a wire in a parent module is produced by one child's output port and
    consumed by another child's input port, we create a DIRECT interface from
    the actual producer to the actual consumer, skipping the parent pass-through.

    Returns: [(wire_name, producer_mod, producer_port,
               consumer_mod, consumer_port, parent_mod)]
    """
    # Phase 1: collect per-parent-module signal producers and consumers
    # producers[parent_mod][signal_name] = (child_mod, child_port)
    # consumers[parent_mod][signal_name] = [(child_mod, child_port), ...]
    producers: Dict[str, Dict[str, Tuple[str, str]]] = {}
    consumers: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}

    for inst in instances:
        child_mod_name = inst.module_type
        child_mod = modules.get(child_mod_name)
        if not child_mod:
            continue

        child_port_map = {p.name: p for p in child_mod.ports}
        parent = inst.parent_module

        if parent not in producers:
            producers[parent] = {}
        if parent not in consumers:
            consumers[parent] = {}

        for port_name, signal_name in inst.connections.items():
            if not signal_name:
                continue
            port_info = child_port_map.get(port_name)
            if not port_info:
                continue

            if port_info.direction == 'output':
                # Child produces this signal in the parent scope
                producers[parent][signal_name] = (child_mod_name, port_name)
            elif port_info.direction == 'input':
                # Child consumes this signal from the parent scope
                if signal_name not in consumers[parent]:
                    consumers[parent][signal_name] = []
                consumers[parent][signal_name].append(
                    (child_mod_name, port_name))

    # Phase 2: resolve transitive connections
    # For each parent module, if a signal has BOTH a child producer and
    # child consumer(s), create direct producer->consumer interfaces
    interfaces = []
    resolved_signals: Dict[str, Set[str]] = {}  # parent -> set of resolved sigs

    for parent in set(list(producers.keys()) + list(consumers.keys())):
        prod_map = producers.get(parent, {})
        cons_map = consumers.get(parent, {})
        resolved_signals[parent] = set()

        for sig_name, (prod_child, prod_port) in prod_map.items():
            if sig_name in cons_map:
                # Transitive: child A output -> wire -> child B input
                resolved_signals[parent].add(sig_name)
                for cons_child, cons_port in cons_map[sig_name]:
                    interfaces.append((
                        sig_name,
                        prod_child, prod_port,
                        cons_child, cons_port,
                        parent))

    # Phase 3: for signals without transitive resolution, fall back to
    # parent-to-child or child-to-parent interfaces
    for inst in instances:
        child_mod_name = inst.module_type
        child_mod = modules.get(child_mod_name)
        if not child_mod:
            continue

        child_port_map = {p.name: p for p in child_mod.ports}
        parent = inst.parent_module
        resolved = resolved_signals.get(parent, set())

        for port_name, signal_name in inst.connections.items():
            if not signal_name or signal_name in resolved:
                continue
            port_info = child_port_map.get(port_name)
            if not port_info:
                continue

            if port_info.direction == 'output':
                interfaces.append((
                    signal_name,
                    child_mod_name, port_name,
                    parent, signal_name,
                    parent))
            elif port_info.direction == 'input':
                interfaces.append((
                    signal_name,
                    parent, signal_name,
                    child_mod_name, port_name,
                    parent))

    return interfaces


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------
#: Set by `run_audit` when it examined no RTL at all. Read by `main` so the
#: exit code cannot contradict the message.
#:
#: Before this, a missing RTL directory printed
#:     ERROR: RTL directory not found: /nope
#: and then exited 0, because the error path returned an empty list and the
#: verdict was `1 if mismatches > 0 else 0`. Zero files scanned and zero
#: mismatches found produced the same rc, so the P0 umbrella — which reads the
#: exit code — recorded "no encoding mismatch here" for a directory that does
#: not exist (#559).
_NOTHING_EXAMINED: List[str] = []


def _bind_native_instances(source_instances, children, parent_module):
    """Expand one live source template to its complete native replica set."""
    name_population = Counter(instance.inst_name for instance in source_instances)
    seen = set()
    active = []
    for instance in source_instances:
        candidates = sorted(cell for cell in children
                            if cell == instance.inst_name or
                            cell.endswith('.' + instance.inst_name))
        if (not candidates or
                (len(candidates) > 1 and name_population[instance.inst_name] != 1)):
            raise ValueError(
                f'unsupported source/native instance: {parent_module}.{instance.inst_name}')
        replicas = []
        for cell in candidates:
            if cell in seen:
                raise ValueError(
                    f'duplicate source/native instance: {parent_module}.{instance.inst_name}')
            seen.add(cell)
            replicas.append(cell)
            active.append(InstanceInfo(
                inst_name=cell,
                module_type=children[cell],
                parent_module=instance.parent_module,
                connections=dict(instance.connections),
                connection_expressions=dict(instance.connection_expressions)))
        if len(replicas) > 1:
            _CONFIGURATION.setdefault('native_instance_replicas', []).append({
                'module': parent_module, 'source_instance': instance.inst_name,
                'native_instances': replicas})
    if seen != set(children):
        raise ValueError(f'incomplete source/native child population: {parent_module}')
    return active


def _active_native_view(modules, headers, files, top, defines, parameters,
                        include_dirs, output_dir):
    """Bind configured source bodies to the existing native elaboration owner.

    The bounded shared preprocessor selects source text, never encoding. Native
    module variants supply their actual parameters and child types. Unsupported
    source constructs stay UNKNOWN; lowered netlist arithmetic is not used to
    guess an encoding for source that the lexical classifier cannot understand.
    """
    import hashlib
    import tempfile
    import rtl_hygiene_lint as lint

    work = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(
        prefix='encoding-active-source-'))
    work = work / 'active-source'
    work.mkdir(parents=True, exist_ok=True)
    def retain_context(context_file):
        if context_file.is_file():
            _CONFIGURATION['native'] = json.loads(context_file.read_text())
            _CONFIGURATION['native_context'] = str(context_file)
            _CONFIGURATION['native_context_sha256'] = hashlib.sha256(context_file.read_bytes()).hexdigest()
            log = context_file.parent / 'native.log'
            if (_CONFIGURATION['native'].get('status') == 'NOT_MEASURED'
                    and log.is_file()):
                errors = [line for line in log.read_text(errors='replace').splitlines()
                          if line.lstrip().startswith('ERROR:')]
                if errors:
                    _CONFIGURATION['native_error'] = errors[-1]
            script = context_file.parent / 'elaborate.ys'
            if script.is_file():
                _CONFIGURATION['native_script'] = {
                    'path': str(script), 'sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                    'text': script.read_text()}
    if any(Path(p).suffix.lower() == '.sv' for p in files):
        # The driver owner intentionally flattens SV. This audit needs native
        # module boundaries (as in _fmeda_mechanisms.native_script), so retain
        # hierarchy while using its existing executor and context contract.
        native_dir = Path(tempfile.mkdtemp(prefix='native-elaboration-', dir=work))
        files = [Path(p).resolve() for p in files]
        dirs = sorted({Path(p).resolve() for p in include_dirs} | {p.parent for p in files})
        context_file = native_dir / 'context.json'
        context = dict(top=top, files=list(map(str, files)), defines=defines,
                       parameters=parameters, include_dirs=list(map(str, dirs)))
        try:
            if (not re.fullmatch(r'[A-Za-z_]\w*', top) or
                    any(not re.fullmatch(r'[A-Za-z_]\w*(?:=[^\s;"\\]+)?', d) for d in defines) or
                    any(not re.fullmatch(r'[A-Za-z_]\w*=[0-9+-]+', p) for p in parameters) or
                    any(re.search(r'[\s;"\\]', str(p)) for p in [*files, *dirs])):
                raise ValueError('unsupported native compile context')
            tracked = set(files)
            for directory in dirs:
                tracked.update(p for p in directory.rglob('*')
                               if p.is_file() and p.suffix in {'.v', '.sv', '.vh', '.svh'})
            def hashes():
                return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tracked)}
            context['input_sha256'] = hashes()
            native_json = native_dir / 'design.json'
            script = native_dir / 'elaborate.ys'
            script.write_text(lint._native_driver_script(
                files, top, defines, parameters, dirs, native_json, keep_hierarchy=True))
            result = lint._native_driver_run(script, native_dir, dirs, context)
            (native_dir / 'native.log').write_text(result.stdout + result.stderr)
            if result.returncode != 0:
                raise ValueError(f'native Yosys elaboration failed (rc={result.returncode}); {native_dir}')
            if hashes() != context['input_sha256']:
                raise ValueError('native elaboration inputs changed during this invocation')
            design = json.loads(native_json.read_text())
            context.update(status='MEASURED', native_json_sha256=hashlib.sha256(native_json.read_bytes()).hexdigest())
        except (OSError, ValueError) as exc:
            context.update(status='NOT_MEASURED', reason=str(exc))
            raise
        finally:
            context_file.write_text(json.dumps(context, indent=2))
            retain_context(context_file)
    else:
        before = set(work.glob('native-elaboration-*'))
        try:
            design = lint._native_driver_view(
                files, top, defines, parameters, include_dirs, work)
        finally:
            # Keep the native receipt even when a live child is missing.
            created = set(work.glob('native-elaboration-*')) - before
            if len(created) == 1:
                context_file = created.pop() / 'context.json'
                retain_context(context_file)

    native_modules = design['modules']
    active_modules = {}
    active_instances = []
    for name, native in native_modules.items():
        original = native.get('attributes', {}).get('hdlname', name)
        if original not in modules and '$' in name:
            # Native Slang --keep-hierarchy uses declaration$full.instance.path.
            declaration, instance_path = name.split('$', 1)
            if declaration in modules and instance_path.startswith(top + '.'):
                original = declaration
        if original not in modules:
            raise ValueError(f'unsupported native module identity: {name}')
        source = modules[original]
        source_body = source.source_body or source.body
        expressions = _hierarchy.parameter_expressions(headers[original], source_body)
        defaults = _hierarchy.resolve_parameters(expressions)
        values = {}
        for key, value in native.get('parameter_default_values', {}).items():
            if (isinstance(defaults.get(key), str) and isinstance(value, str)
                    and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value)):
                # Native Yosys publishes a declared string as text. Keep
                # the selected specialization, rather than reading it as bits.
                values[key] = value
                continue
            if not isinstance(value, str) or not re.fullmatch('[01]+', value):
                raise ValueError(f'unsupported native parameter: {name}.{key}')
            values[key] = int(value, 2)
        params = _hierarchy.resolve_parameters(expressions, values)
        body = _hierarchy.active_body(source_body, params, lint._procedural_statement_end)
        native_ports = native.get('ports', {})
        if ({p.name: p.direction for p in source.ports} !=
                {p: spec['direction'] for p, spec in native_ports.items()}):
            raise ValueError(f'source/native port population differs: {name}')
        active_modules[name] = ModuleInfo(
            name, source.file,
            [PortInfo(p.name, p.direction, p.width, name) for p in source.ports],
            lexical_mask(body, attributes=True),
            native_widths={key: len(spec['bits']) for key, spec in
                           {**native.get('netnames', {}), **native_ports}.items()})
        children = {cell_name: cell['type']
                    for cell_name, cell in native.get('cells', {}).items()
                    if cell['type'] in native_modules}
        source_instances = parse_instances(
            lexical_mask(body, attributes=True), name, native_checked=True)
        active_instances.extend(_bind_native_instances(
            source_instances, children, name))
    return active_modules, active_instances


def run_audit(
    rtl_dir: str,
    top_module: str,
    *, defines=(), parameters=(), include_dirs=(), output_dir=None,
) -> List[InterfaceAuditResult]:
    """
    Run the full encoding audit on an RTL directory.
    Returns list of audit results for each cross-module interface.
    """
    global _DISCOVERED_MODULE_COUNT, _DISCOVERED_INSTANCE_COUNT
    _NOTHING_EXAMINED.clear()
    _DISCOVERY_ISSUES.clear()
    _DISCOVERED_MODULE_COUNT = 0
    _DISCOVERED_INSTANCE_COUNT = 0
    _CONFIGURATION.clear()
    _CONFIGURATION.update(top=top_module, defines=list(defines),
                          parameters=list(parameters),
                          include_dirs=[str(Path(p).resolve()) for p in include_dirs],
                          preprocessor='rtl_hierarchy_drivers.preprocess',
                          state='UNKNOWN')
    rtl_path = Path(rtl_dir)
    if not rtl_path.exists():
        print(f"ERROR: RTL directory not found: {rtl_dir}", file=sys.stderr)
        _NOTHING_EXAMINED.append(f"RTL directory not found: {rtl_dir}")
        return []

    # Collect all .v and .sv files
    vfiles = sorted(rtl_path.rglob('*.v')) + sorted(rtl_path.rglob('*.sv'))
    if not vfiles:
        print(f"WARNING: no .v/.sv files found in {rtl_dir}", file=sys.stderr)
        _NOTHING_EXAMINED.append(f"no .v/.sv files in {rtl_dir}")
        return []

    # Parse all modules
    all_modules: Dict[str, ModuleInfo] = {}
    all_instances: List[InstanceInfo] = []
    headers = {}
    selected_defines = {d.split('=', 1)[0] for d in defines}
    configured = bool(defines or parameters or include_dirs)

    for vf in vfiles:
        src = strip_comments(vf.read_text(errors='replace'))
        configured = configured or bool(re.search(
            r'`|\\|\b(?:parameter|defparam|generate|genvar)\b', lexical_mask(src)))
        try:
            src = _hierarchy.preprocess(src, selected_defines)
        except ValueError as exc:
            _discovery_issue(f'active source UNKNOWN ({vf}): {exc}')
            continue
        for name, start, body_start, _ in module_regions(src):
            headers[name] = src[start:body_start]
        mods = parse_modules(src, str(vf))
        for mod in mods:
            if mod.name in all_modules:
                _discovery_issue(f'duplicate module definition: {mod.name}')
            all_modules[mod.name] = mod
    lexical_instances = ([] if configured else [
        instance for mod in all_modules.values()
        for instance in parse_instances(mod.body, mod.name)])
    # Existing source-level interface classification retains source module
    # identity when a real subject is already present.  Native execution is
    # additionally mandatory for an apparent zero boundary: only elaboration,
    # through the selected executor, may prove that the lexical zero is real.
    native_required = configured or not build_interface_map(all_modules,
                                                             lexical_instances)
    if native_required and not _DISCOVERY_ISSUES:
        try:
            all_modules, all_instances = _active_native_view(
                all_modules, headers, vfiles, top_module, list(defines),
                list(parameters), list(include_dirs), output_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = _CONFIGURATION.get('native_error', '')
            _discovery_issue(f'active source UNKNOWN: {exc}' +
                             (f'; {detail}' if detail else ''))
    else:
        all_instances = lexical_instances
    _DISCOVERED_MODULE_COUNT = len(all_modules)
    _DISCOVERED_INSTANCE_COUNT = len(all_instances)

    if top_module and top_module not in all_modules:
        _discovery_issue(
            f"top module '{top_module}' not found in parsed modules; "
            f"available: {list(all_modules.keys())}")

    for inst in all_instances:
        if inst.module_type not in all_modules:
            _discovery_issue(
                f"instance '{inst.inst_name}' in '{inst.parent_module}' "
                f"references unresolved module '{inst.module_type}'")
    if _DISCOVERY_ISSUES:
        print("WARNING: incomplete hierarchy discovery: " +
              "; ".join(_DISCOVERY_ISSUES), file=sys.stderr)
    else:
        _CONFIGURATION['state'] = 'MEASURED'

    # Build interface map
    interfaces = build_interface_map(all_modules, all_instances)

    # Classify each interface
    results: List[InterfaceAuditResult] = []
    for (wire, prod_mod, prod_port,
         cons_mod, cons_port, parent_mod) in interfaces:
        # Get producer module body
        prod_module = all_modules.get(prod_mod)
        cons_module = all_modules.get(cons_mod)
        if not prod_module or not cons_module:
            continue

        nonencoding = None
        if _fixed_nested_bit_select(wire) is not None:
            evidence = (f'unsupported fixed nested bit-select carrier {wire}; '
                        'retained in interface population')
            prod_class = EncodingClassification('UNKNOWN', evidence, 0)
            cons_class = EncodingClassification('UNKNOWN', evidence, 0)
            predicate = None
        else:
            # Classify producer encoding (how the signal is generated)
            prod_class = classify_producer_encoding(prod_module.body, prod_port)

            # Classify consumer encoding (how the signal is compared)
            cons_class = classify_consumer_encoding(cons_module.body, cons_port)

            # A measured mismatch remains authoritative. A whole scalar boundary
            # consumed exclusively as a predicate has a finite encoding-invariance
            # proof; unsupported references remain in the same UNKNOWN population.
            predicate = _whole_scalar_predicate(
                wire, prod_module, prod_port, cons_module, cons_port,
                all_modules[parent_mod], all_modules, all_instances)
            nonencoding = _whole_nonencoding_value(
                wire, prod_module, prod_port, cons_module, cons_port,
                all_modules[parent_mod], all_modules, all_instances)

        # Determine match status
        if (nonencoding is not None
                and prod_class.encoding == cons_class.encoding == 'UNKNOWN'):
            prod_class, cons_class = nonencoding
            status = 'NOT_APPLICABLE'
            severity = 'INFO'
        elif predicate is not None and cons_class.encoding == 'UNKNOWN':
            predicate_class, producer_domain = predicate
            if prod_class.encoding == 'UNKNOWN':
                prod_class = EncodingClassification(
                    'BIT_VALUE',
                    producer_domain + '; Gray/Binary data encoding is not inferred', 0)
            cons_class = predicate_class
            status = 'MATCH'
            severity = 'INFO'
        elif prod_class.encoding == "UNKNOWN" or cons_class.encoding == "UNKNOWN":
            status = "UNKNOWN"
            severity = "INFO"
        elif prod_class.encoding == cons_class.encoding:
            status = "MATCH"
            severity = "INFO"
        else:
            status = "MISMATCH"
            severity = "ERROR"

        results.append(InterfaceAuditResult(
            wire_name=wire,
            producer_module=prod_mod,
            producer_port=prod_port,
            producer_encoding=prod_class.encoding,
            producer_evidence=prod_class.evidence,
            consumer_module=cons_mod,
            consumer_port=cons_port,
            consumer_encoding=cons_class.encoding,
            consumer_evidence=cons_class.evidence,
            status=status,
            severity=severity))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description='Detect gray-code vs binary encoding mismatches '
                    'across module boundaries.')
    ap.add_argument('--rtl-dir', required=True,
                    help='Directory containing Verilog/SystemVerilog files')
    ap.add_argument('--top-module', required=True,
                    help='Top-level module name')
    ap.add_argument('--out-dir', required=True,
                    help='Output directory for JSON report')
    ap.add_argument('-D', '--define', action='append', default=[],
                    help='Selected compile define (repeatable NAME or NAME=value)')
    ap.add_argument('-I', '--include-dir', action='append', default=[],
                    help='Declared native include directory (repeatable)')
    ap.add_argument('-P', '--parameter', action='append', default=[],
                    help='Selected top parameter NAME=integer (repeatable)')
    ap.add_argument('--severity', choices=['ERROR', 'WARN', 'INFO'],
                    default='INFO',
                    help='Minimum severity to report (default: INFO)')
    args = ap.parse_args()

    source_manifest = None
    source_error = None
    try:
        source_manifest = _applicability.source_census(Path(args.rtl_dir))
    except (OSError, ValueError, UnicodeError) as exc:
        source_error = str(exc)
    results = run_audit(args.rtl_dir, args.top_module, defines=args.define,
                        parameters=args.parameter, include_dirs=args.include_dir,
                        output_dir=args.out_dir)
    if source_manifest is not None:
        try:
            if _applicability.source_census(Path(args.rtl_dir)) != source_manifest:
                source_error = 'source_changed_during_audit'
        except (OSError, ValueError, UnicodeError) as exc:
            source_error = str(exc)

    sev_order = {'ERROR': 2, 'WARN': 1, 'INFO': 0}
    min_sev = sev_order[args.severity]
    filtered = [r for r in results if sev_order[r.severity] >= min_sev]

    # Summary
    mismatches = sum(1 for r in results if r.status == 'MISMATCH')
    matches = sum(1 for r in results if r.status == 'MATCH')
    not_applicable = sum(1 for r in results if r.status == 'NOT_APPLICABLE')
    unknowns = sum(1 for r in results if r.status == 'UNKNOWN')
    print(f"interface_encoding_audit: {mismatches} MISMATCH, "
          f"{matches} MATCH, {not_applicable} NOT_APPLICABLE, "
          f"{unknowns} UNKNOWN "
          f"({len(filtered)} interfaces analyzed)")
    print("-" * 70)
    for r in sorted(filtered, key=lambda x: (x.status != 'MISMATCH',
                                              x.wire_name)):
        marker = "***" if r.status == "MISMATCH" else "   "
        print(f"{marker} {r.wire_name}: "
              f"{r.producer_module}.{r.producer_port} ({r.producer_encoding}) "
              f"-> {r.consumer_module}.{r.consumer_port} ({r.consumer_encoding}) "
              f"= {r.status}")
        if r.status == "MISMATCH":
            print(f"      Producer: {r.producer_evidence}")
            print(f"      Consumer: {r.consumer_evidence}")

    # Write JSON report
    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / 'encoding_audit_report.json'
    interface_rows = [asdict(r) for r in results]
    report = {
        'report_schema': 'vibeic.interface_encoding_audit.v3',
        'summary': {
            'total_interfaces': len(results),
            'mismatches': mismatches,
            'matches': matches,
            'not_applicable': not_applicable,
            'unknowns': unknowns,
            'top_module': args.top_module,
            'rtl_dir': args.rtl_dir,
        },
        'interfaces': interface_rows,
        'interface_population': _population.binding(interface_rows),
        'semantic_coverage': {
            'complete': (not unknowns and not _DISCOVERY_ISSUES
                         and not _NOTHING_EXAMINED and source_error is None),
            'total_interfaces': len(results),
            'decided': matches + mismatches,
            'not_applicable': not_applicable,
            'unknown': unknowns,
        },
        'discovery': {
            'complete': (not _DISCOVERY_ISSUES and not _NOTHING_EXAMINED and
                         source_error is None),
            'modules_discovered': _DISCOVERED_MODULE_COUNT,
            'instances_discovered': _DISCOVERED_INSTANCE_COUNT,
            'issues': (list(_DISCOVERY_ISSUES) + list(_NOTHING_EXAMINED) +
                       ([f'source census: {source_error}']
                        if source_error else [])),
        },
        'source': source_manifest,
        'configuration': dict(_CONFIGURATION),
    }
    if not results:
        applicability = _applicability.assess(
            'interface_encoding_audit', Path(args.rtl_dir),
            top_module=args.top_module, configuration=_CONFIGURATION)
        report['applicability'] = applicability
        if (not _DISCOVERY_ISSUES and not _NOTHING_EXAMINED and
                applicability['state'] == _applicability.NOT_APPLICABLE):
            report['summary']['verdict'] = _applicability.NOT_APPLICABLE
    if mismatches:
        report['summary']['verdict'] = 'FAIL'
    elif _DISCOVERY_ISSUES:
        report['summary']['verdict'] = 'INCONCLUSIVE'
    elif source_error or _NOTHING_EXAMINED or unknowns:
        report['summary']['verdict'] = 'INCONCLUSIVE'
    elif 'verdict' not in report['summary']:
        report['summary']['verdict'] = 'FAIL' if mismatches else (
            'PASS' if results else 'INCONCLUSIVE')
    if mismatches:
        producer_returncode = 1
    elif _DISCOVERY_ISSUES or _NOTHING_EXAMINED or source_error:
        producer_returncode = 2
    else:
        # Preserve the CLI's established advisory status for encoding UNKNOWN
        # and zero interfaces.  The receipt consumer independently refuses both
        # populations; the report's INCONCLUSIVE verdict is never audit PASS.
        producer_returncode = 0
    report['producer_returncode'] = producer_returncode
    report_file.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report written to: {report_file}")

    if producer_returncode == 2:
        print(f"VACUOUS_PASS: interface_encoding_audit examined nothing "
              f"or could not prove its source/discovery closure — this is not "
              f"a clean audit",
              file=sys.stderr)
        return 2
    return producer_returncode


if __name__ == '__main__':
    sys.exit(main())
