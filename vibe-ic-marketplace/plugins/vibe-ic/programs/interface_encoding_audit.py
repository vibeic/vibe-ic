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
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _rtl_audit_applicability as _applicability
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


@dataclass
class InstanceInfo:
    inst_name: str
    module_type: str
    parent_module: str
    connections: Dict[str, str]   # port_name -> signal_name


@dataclass
class EncodingClassification:
    encoding: str           # "BINARY" | "GRAY" | "UNKNOWN"
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
    status: str             # "MATCH" | "MISMATCH" | "UNKNOWN"
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
        'union', 'packed', 'signed', 'unsigned', 'return',
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
                continue
            if not tail.startswith('('):
                malformed = True
                continue
            actual_result = extract_balanced(tail, 0)
            if actual_result is None or tail[actual_result[1] + 1:].strip():
                malformed = True
                continue
            sig = actual_result[0].strip()
            sm = re.fullmatch(r'(\w+)(?:\s*\[[^\]]+\])?', sig)
            if sm:
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
            connections=connections))
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
    literal state bounds, whole-state arithmetic updates and literal resets.
    Arbitrary aliases, transforms and partially written storage stay UNKNOWN.
    The caller supplies the native-selected module body.
    """
    clean = lexical_mask(body, attributes=True)
    name = re.escape(signal_name)
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
    for assignment in assignments:
        selected, operator, expression = assignment.groups()
        if selected is not None or operator != '<=':
            return None
        expression = expression.strip()
        if update.fullmatch(expression):
            arithmetic.append(assignment)
        elif not re.fullmatch(literal, expression):
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
            script.write_text('read_slang --keep-hierarchy --single-unit --no-synthesis-define --top ' + top +
                ' ' + ' '.join(['-G ' + p for p in parameters] + ['-D ' + d for d in defines] +
                                ['-I ' + str(p) for p in dirs] + list(map(str, files))) +
                f'; hierarchy -check -top {top}; proc; check -assert; write_json {native_json}\n')
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
            lexical_mask(body, attributes=True))
        children = {cell_name: cell['type']
                    for cell_name, cell in native.get('cells', {}).items()
                    if cell['type'] in native_modules}
        seen = set()
        for instance in parse_instances(lexical_mask(body, attributes=True), name,
                                         native_checked=True):
            candidates = [cell for cell in children
                          if cell == instance.inst_name or
                          cell.endswith('.' + instance.inst_name)]
            if len(candidates) != 1 or candidates[0] in seen:
                raise ValueError(f'unsupported source/native instance: {name}.{instance.inst_name}')
            cell = candidates[0]
            seen.add(cell)
            instance.module_type = children[cell]
            active_instances.append(instance)
        if seen != set(children):
            raise ValueError(f'incomplete source/native child population: {name}')
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
        configured = configured or bool(re.search(r'`|\bgenerate\b', lexical_mask(src)))
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
    if configured and not _DISCOVERY_ISSUES:
        try:
            all_modules, all_instances = _active_native_view(
                all_modules, headers, vfiles, top_module, list(defines),
                list(parameters), list(include_dirs), output_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = _CONFIGURATION.get('native_error', '')
            _discovery_issue(f'active source UNKNOWN: {exc}' +
                             (f'; {detail}' if detail else ''))
    elif not configured:
        for mod in all_modules.values():
            all_instances.extend(parse_instances(mod.body, mod.name))
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

        # Classify producer encoding (how the signal is generated)
        prod_class = classify_producer_encoding(prod_module.body, prod_port)

        # Classify consumer encoding (how the signal is compared)
        cons_class = classify_consumer_encoding(cons_module.body, cons_port)

        # Determine match status
        if prod_class.encoding == "UNKNOWN" or cons_class.encoding == "UNKNOWN":
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
    unknowns = sum(1 for r in results if r.status == 'UNKNOWN')
    print(f"interface_encoding_audit: {mismatches} MISMATCH, "
          f"{matches} MATCH, {unknowns} UNKNOWN "
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
    report = {
        'report_schema': 'vibeic.interface_encoding_audit.v2',
        'summary': {
            'total_interfaces': len(results),
            'mismatches': mismatches,
            'matches': matches,
            'unknowns': unknowns,
            'top_module': args.top_module,
            'rtl_dir': args.rtl_dir,
        },
        'interfaces': [asdict(r) for r in results],
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
            top_module=args.top_module)
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
