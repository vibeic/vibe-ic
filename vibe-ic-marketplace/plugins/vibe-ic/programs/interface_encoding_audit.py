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
  1. Parses Verilog/SystemVerilog RTL files in a design directory
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


# ---------------------------------------------------------------------------
# Comment stripper (shared pattern across programs)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // line comments and /* block */ comments, preserving newlines."""
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i+2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
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
# Module parser
# ---------------------------------------------------------------------------
def parse_modules(src: str, filepath: str) -> List[ModuleInfo]:
    """Extract all module definitions from a Verilog/SV source file."""
    modules = []
    # Match module ... endmodule blocks
    mod_pattern = re.compile(
        r'\bmodule\s+(\w+)\s*'       # module name
        r'(?:#\s*\([^)]*\)\s*)?'     # optional parameters
        r'\(([^)]*)\)\s*;'           # port list
        r'(.*?)'                     # body
        r'\bendmodule\b',
        re.DOTALL
    )
    for m in mod_pattern.finditer(src):
        mod_name = m.group(1)
        port_text = m.group(2)
        body = m.group(3)
        ports = _parse_port_list(port_text, body, mod_name)
        modules.append(ModuleInfo(
            name=mod_name, file=filepath, ports=ports, body=body))
    return modules


def _parse_port_list(port_text: str, body: str, mod_name: str) -> List[PortInfo]:
    """Parse ports from ANSI-style port declarations."""
    ports = []
    # ANSI-style: input wire [7:0] name, input clk, output reg [5:0] data
    # Split by comma, but handle multi-line
    port_text = re.sub(r'\s+', ' ', port_text.strip())
    if not port_text:
        return ports

    # Split on commas that are not inside brackets
    items = _split_ports(port_text)

    current_dir = "input"  # default if not specified
    for item in items:
        item = item.strip()
        if not item:
            continue
        # Match: [input|output|inout] [wire|reg|logic] [signed] [width] name
        pm = re.match(
            r'(input|output|inout)\s+'
            r'(?:wire|reg|logic)?\s*'
            r'(?:signed\s+)?'
            r'(\[[^\]]+\]\s*)?'
            r'(\w+)',
            item)
        if pm:
            current_dir = pm.group(1)
            width = (pm.group(2) or "").strip()
            name = pm.group(3)
            ports.append(PortInfo(name=name, direction=current_dir,
                                  width=width, module=mod_name))
        else:
            # Might be a continuation with same direction: just a name
            nm = re.match(r'(\[[^\]]+\]\s*)?(\w+)', item)
            if nm:
                width = (nm.group(1) or "").strip()
                name = nm.group(2)
                ports.append(PortInfo(name=name, direction=current_dir,
                                      width=width, module=mod_name))

    # Also check body for non-ANSI port declarations
    for dm in re.finditer(
        r'\b(input|output|inout)\s+(?:wire|reg|logic)?\s*'
        r'(?:signed\s+)?'
        r'(\[[^\]]+\]\s*)?'
        r'(\w+)\s*;',
        body
    ):
        direction = dm.group(1)
        width = (dm.group(2) or "").strip()
        name = dm.group(3)
        # Only add if not already in ports (avoid duplicates)
        if not any(p.name == name for p in ports):
            ports.append(PortInfo(name=name, direction=direction,
                                  width=width, module=mod_name))

    return ports


def _split_ports(text: str) -> List[str]:
    """Split port list by commas, respecting bracket depth."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


# ---------------------------------------------------------------------------
# Instance parser
# ---------------------------------------------------------------------------
def parse_instances(body: str, parent_module: str) -> List[InstanceInfo]:
    """Find module instantiations in a module body."""
    instances = []
    # Pattern: module_type [#(...)] inst_name ( .port(sig), ... );
    # We match the instance and then extract port connections
    inst_pattern = re.compile(
        r'\b(\w+)\s+'                # module type
        r'(?:#\s*\([^)]*\)\s+)?'     # optional parameter override
        r'(\w+)\s*\('               # instance name
        r'([^;]*?)'                 # connection list
        r'\)\s*;',
        re.DOTALL
    )
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

    for m in inst_pattern.finditer(body):
        mod_type = m.group(1)
        inst_name = m.group(2)
        conn_text = m.group(3)

        if mod_type in non_instance:
            continue
        # Must have named port connections (.port(sig) pattern)
        if '.' not in conn_text:
            continue

        connections = {}
        for cm in re.finditer(r'\.(\w+)\s*\(\s*([^)]*?)\s*\)', conn_text):
            port = cm.group(1)
            sig = cm.group(2).strip()
            # Take the base signal name (strip bit selects)
            sm = re.match(r'(\w+)', sig)
            if sm:
                connections[port] = sm.group(1)
            elif sig == '':
                # Unconnected port
                connections[port] = ''

        if connections:
            instances.append(InstanceInfo(
                inst_name=inst_name,
                module_type=mod_type,
                parent_module=parent_module,
                connections=connections))
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


def run_audit(
    rtl_dir: str,
    top_module: str
) -> List[InterfaceAuditResult]:
    """
    Run the full encoding audit on an RTL directory.
    Returns list of audit results for each cross-module interface.
    """
    _NOTHING_EXAMINED.clear()
    rtl_path = Path(rtl_dir)
    if not rtl_path.exists():
        print(f"ERROR: RTL directory not found: {rtl_dir}", file=sys.stderr)
        _NOTHING_EXAMINED.append(f"RTL directory not found: {rtl_dir}")
        return []

    # Collect all .v and .sv files
    vfiles = sorted(rtl_path.glob('*.v')) + sorted(rtl_path.glob('*.sv'))
    if not vfiles:
        print(f"WARNING: no .v/.sv files found in {rtl_dir}", file=sys.stderr)
        _NOTHING_EXAMINED.append(f"no .v/.sv files in {rtl_dir}")
        return []

    # Parse all modules
    all_modules: Dict[str, ModuleInfo] = {}
    all_instances: List[InstanceInfo] = []

    for vf in vfiles:
        src = strip_comments(vf.read_text(errors='replace'))
        mods = parse_modules(src, str(vf))
        for mod in mods:
            all_modules[mod.name] = mod
            insts = parse_instances(mod.body, mod.name)
            all_instances.extend(insts)

    if top_module and top_module not in all_modules:
        print(f"WARNING: top module '{top_module}' not found in parsed modules. "
              f"Available: {list(all_modules.keys())}", file=sys.stderr)

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
    ap.add_argument('--severity', choices=['ERROR', 'WARN', 'INFO'],
                    default='INFO',
                    help='Minimum severity to report (default: INFO)')
    args = ap.parse_args()

    results = run_audit(args.rtl_dir, args.top_module)

    sev_order = {'ERROR': 2, 'WARN': 1, 'INFO': 0}
    min_sev = sev_order[args.severity]
    filtered = [r for r in results if sev_order[r.severity] >= min_sev]

    # Summary
    mismatches = sum(1 for r in filtered if r.status == 'MISMATCH')
    matches = sum(1 for r in filtered if r.status == 'MATCH')
    unknowns = sum(1 for r in filtered if r.status == 'UNKNOWN')
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
        'summary': {
            'total_interfaces': len(filtered),
            'mismatches': mismatches,
            'matches': matches,
            'unknowns': unknowns,
            'top_module': args.top_module,
            'rtl_dir': args.rtl_dir,
        },
        'interfaces': [asdict(r) for r in filtered]
    }
    report_file.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report written to: {report_file}")

    if _NOTHING_EXAMINED:
        print(f"VACUOUS_PASS: interface_encoding_audit examined nothing "
              f"(reason: {_NOTHING_EXAMINED[0]}) — this is not a clean audit",
              file=sys.stderr)
        return 2
    return 1 if mismatches > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
