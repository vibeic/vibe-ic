#!/usr/bin/env python3
"""
Golden Model Auto-Generator from Datasheet (R2#8)
===================================================
Parses a datasheet.md and RTL .sv file, extracts register map and truth table,
and generates a Python golden model that implements the IC's behavior.

Supports:
    - Logic ICs: truth table extraction -> combinational/sequential model
    - I2C/SPI ICs: register map extraction -> register read/write + basic protocol
    - Complex ICs: behavioral stub template generation

Usage:
    python3 golden_model_auto.py --ds path/to/datasheet.md --rtl path/to/module.sv --output golden.py
    python3 golden_model_auto.py --ds datasheet.md --rtl module.sv --output golden.py --type logic
    python3 golden_model_auto.py --ds datasheet.md --rtl module.sv --output golden.py --type i2c
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class RegisterDef:
    """Single register from the register map."""
    address: int            # Register address / pointer value
    name: str               # Register name
    size_bits: int           # Width in bits (8, 16, 32)
    access: str              # "R", "R/W", "W"
    default_value: int       # Default/reset value
    description: str = ""
    bit_fields: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TruthTableEntry:
    """Single row of a truth table."""
    inputs: Dict[str, Any]   # input_name -> value (0, 1, 'X', '^')
    outputs: Dict[str, Any]  # output_name -> value (0, 1, 'X', 'Q_n')


@dataclass
class PortInfo:
    """Port from RTL."""
    name: str
    direction: str   # "input", "output", "inout"
    width: int = 1


@dataclass
class ICSpec:
    """Extracted IC specification."""
    name: str = ""
    description: str = ""
    ic_type: str = "unknown"         # "logic", "i2c", "spi", "protocol", "complex"
    ports: List[PortInfo] = field(default_factory=list)
    registers: List[RegisterDef] = field(default_factory=list)
    truth_table: List[TruthTableEntry] = field(default_factory=list)
    is_sequential: bool = False
    clock_ports: List[str] = field(default_factory=list)
    reset_ports: List[str] = field(default_factory=list)
    state_vars: List[str] = field(default_factory=list)
    protocol: str = ""               # "i2c", "spi", "uart", ""
    address_bits: int = 7            # I2C address width


# ============================================================================
# Datasheet Parser
# ============================================================================

def parse_datasheet(ds_path: str) -> ICSpec:
    """Parse a datasheet.md and extract register map, truth table, etc."""
    with open(ds_path, 'r', encoding='utf-8') as f:
        text = f.read()

    spec = ICSpec()

    # Extract IC name from title
    title_match = re.search(r'^#\s+(\S+)\s', text, re.MULTILINE)
    if title_match:
        spec.name = title_match.group(1)

    # Extract description from Section 2
    desc_match = re.search(
        r'(?:第\s*2\s*節|Section\s*2|##\s*.*?(?:描述|Description))\s*\n+(.*?)(?=\n##|\n---)',
        text, re.DOTALL | re.IGNORECASE
    )
    if desc_match:
        spec.description = desc_match.group(1).strip()[:200]

    # Detect IC type from content
    spec.ic_type = _detect_ic_type(text)
    spec.protocol = _detect_protocol(text)

    # Parse register map (Section 9.2 or anywhere with register tables)
    spec.registers = _parse_register_map(text)

    # Parse truth table
    spec.truth_table = _parse_truth_table(text)

    # Detect sequential behavior
    seq_keywords = ['flip-flop', 'flop', 'latch', 'register', 'counter',
                    'sequential', 'posedge', '正反器', '計數器', '暫存器']
    text_lower = text.lower()
    spec.is_sequential = any(kw in text_lower for kw in seq_keywords)

    return spec


def _detect_ic_type(text: str) -> str:
    """Detect IC type from datasheet content."""
    text_lower = text.lower()

    # I2C indicators
    i2c_keywords = ['i2c', 'i²c', 'scl', 'sda', 'slave address',
                    '從端地址', 'address byte']
    if any(kw in text_lower for kw in i2c_keywords):
        return "i2c"

    # SPI indicators
    spi_keywords = ['spi', 'sclk', 'mosi', 'miso', 'cs_n', 'chip select',
                    'serial peripheral']
    if any(kw in text_lower for kw in spi_keywords):
        return "spi"

    # Logic IC indicators
    logic_keywords = ['truth table', '真值表', 'gate', 'buffer', 'flip-flop',
                      'decoder', 'encoder', 'mux', 'counter', '正反器',
                      '解碼器', '編碼器', '閘']
    if any(kw in text_lower for kw in logic_keywords):
        return "logic"

    # Protocol ICs
    proto_keywords = ['uart', 'can', 'ethernet', 'usb', '1-wire',
                      'one-wire', 'modbus']
    if any(kw in text_lower for kw in proto_keywords):
        return "protocol"

    return "complex"


def _detect_protocol(text: str) -> str:
    """Detect communication protocol."""
    text_lower = text.lower()
    if 'i2c' in text_lower or 'i²c' in text_lower:
        return "i2c"
    if 'spi' in text_lower:
        return "spi"
    if 'uart' in text_lower:
        return "uart"
    if '1-wire' in text_lower or 'one-wire' in text_lower:
        return "1wire"
    return ""


def _parse_register_map(text: str) -> List[RegisterDef]:
    """Extract register definitions from datasheet."""
    registers = []

    # Pattern 1: Markdown table with Pointer/Address, Name, Size, Access, Default
    # e.g., | 0x00 | Temperature | 16-bit | R | 0x0000 |
    reg_table_pattern = re.compile(
        r'\|\s*(?:0x)?([0-9A-Fa-f]+)\s*\|\s*(\w[\w\s]*?)\s*\|\s*'
        r'(\d+)[\s-]*bit\s*\|\s*(R(?:/W)?|W|R/W)\s*\|\s*'
        r'(?:0x)?([0-9A-Fa-f]+)\s*\|',
        re.IGNORECASE
    )

    for m in reg_table_pattern.finditer(text):
        addr = int(m.group(1), 16)
        name = m.group(2).strip()
        size = int(m.group(3))
        access = m.group(4).upper()
        default = int(m.group(5), 16)

        reg = RegisterDef(
            address=addr,
            name=name,
            size_bits=size,
            access=access,
            default_value=default,
        )

        # Try to parse bit fields for this register
        reg.bit_fields = _parse_bit_fields(text, name)

        registers.append(reg)

    # Pattern 2: Simpler table format
    # | Pointer | Register | Size | Access | Default | Description |
    if not registers:
        reg_pattern2 = re.compile(
            r'\|\s*(?:0x)?([0-9A-Fa-f]+)\s*\|\s*(\w[\w\s_]*?)\s*\|'
            r'\s*(\d+)\s*\|\s*(R(?:/W)?|W|RO|RW|WO)\s*\|',
            re.IGNORECASE
        )
        for m in reg_pattern2.finditer(text):
            addr = int(m.group(1), 16)
            name = m.group(2).strip()
            size = int(m.group(3))
            access = m.group(4).upper().replace('RO', 'R').replace('RW', 'R/W').replace('WO', 'W')

            registers.append(RegisterDef(
                address=addr, name=name, size_bits=size,
                access=access, default_value=0,
            ))

    # Pattern 3: Pointer-only table (common in many datasheets)
    # | 0x00 | Temperature Register (default) |
    # Then look for individual register sections to get size/access/default
    if not registers:
        ptr_pattern = re.compile(
            r'\|\s*(?:0x)?([0-9A-Fa-f]+)\s*\|\s*'
            r'([\w\s_/]+?(?:Register|Reg)[\w\s()]*?)\s*\|',
            re.IGNORECASE
        )
        for m in ptr_pattern.finditer(text):
            addr = int(m.group(1), 16)
            name = m.group(2).strip()
            # Clean up name: remove trailing notes like "(default)"
            name = re.sub(r'\s*[（(].*?[)）]\s*$', '', name).strip()

            # Try to find size, access, default from register detail section
            size, access, default = _find_register_details(text, name, addr)

            registers.append(RegisterDef(
                address=addr, name=name, size_bits=size,
                access=access, default_value=default,
                bit_fields=_parse_bit_fields(text, name),
            ))

    return registers


def _find_register_details(text: str, reg_name: str, addr: int) -> Tuple[int, str, int]:
    """Find register size, access, and default from its detailed section."""
    size = 8  # default
    access = "R/W"
    default = 0

    # Search for a section describing this register
    # Look for patterns like "16-bit", "8-bit", "唯讀", "R/W" near the register name
    name_esc = re.escape(reg_name)
    section_match = re.search(
        rf'{name_esc}[^\n]*\n(.*?)(?=\n###|\n---|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )

    if section_match:
        section = section_match.group(1)[:500]  # limit search

        # Find size
        size_match = re.search(r'(\d+)[\s-]*bit', section, re.IGNORECASE)
        if size_match:
            size = int(size_match.group(1))

        # Find access
        if '唯讀' in section or 'read-only' in section.lower() or 'read only' in section.lower():
            access = 'R'
        elif 'R/W' in section or 'read/write' in section.lower():
            access = 'R/W'

        # Find default value
        default_match = re.search(r'(?:預設值?|default)[^\d]*(?:0x)?([0-9A-Fa-f]+)', section, re.IGNORECASE)
        if default_match:
            try:
                default = int(default_match.group(1), 16)
            except ValueError:
                pass

    return size, access, default


def _parse_bit_fields(text: str, reg_name: str) -> List[Dict[str, Any]]:
    """Parse bit field definitions for a specific register."""
    bit_fields = []

    # Look for a section about this register with a bit table
    # Pattern: | Bit | Name | Access | Default | Description |
    # or: | Bit | 7 | 6 | 5 | ... | 0 |
    reg_section = re.search(
        rf'(?:{re.escape(reg_name)}|{reg_name.replace("_", " ")})[^\n]*\n'
        r'(.*?)(?=\n###|\n---|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    if not reg_section:
        return bit_fields

    section = reg_section.group(1)

    # Parse bit field rows: | 7:5 | Reserved | R | 000 | ... |
    bf_pattern = re.compile(
        r'\|\s*(\d+(?::\d+)?)\s*\|\s*(\w[\w\s/()]*?)\s*\|\s*'
        r'(?:(R(?:/W)?|W|R/W)\s*\|)?',
        re.IGNORECASE
    )

    for m in bf_pattern.finditer(section):
        bit_range = m.group(1)
        name = m.group(2).strip()
        access = m.group(3).upper() if m.group(3) else "R/W"

        if ':' in bit_range:
            msb, lsb = bit_range.split(':')
            msb, lsb = int(msb), int(lsb)
        else:
            msb = lsb = int(bit_range)

        bit_fields.append({
            'msb': msb,
            'lsb': lsb,
            'name': name,
            'access': access,
            'width': msb - lsb + 1,
        })

    return bit_fields


def _parse_truth_table(text: str) -> List[TruthTableEntry]:
    """Extract truth table entries from datasheet."""
    entries = []

    # Find truth table section
    tt_section = re.search(
        r'(?:真值表|Truth\s+Table|功能表)[^\n]*\n(.*?)(?=\n##|\n---|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    if not tt_section:
        # Also try inline truth tables
        tt_section = re.search(
            r'(?:SET|RESET|CLK|D)\s*\|\s*(?:SET|RESET|CLK|D|Q|OUTPUT|OUT)',
            text, re.IGNORECASE
        )
        if tt_section:
            # Find the table containing this
            table_start = text.rfind('\n|', 0, tt_section.start())
            if table_start == -1:
                table_start = 0
            table_end = text.find('\n\n', tt_section.end())
            if table_end == -1:
                table_end = len(text)
            section_text = text[table_start:table_end]
        else:
            return entries
    else:
        section_text = tt_section.group(1)

    # Parse markdown table rows
    header_match = re.search(r'\|(.+)\|', section_text)
    if not header_match:
        return entries

    # Get header columns
    header_line = header_match.group(0)
    headers = [h.strip() for h in header_line.split('|') if h.strip()]

    # Find separator line
    lines = section_text.strip().split('\n')
    data_start = 0
    for i, line in enumerate(lines):
        if re.match(r'\s*\|[\s\-:]+\|', line):
            data_start = i + 1
            break

    # Parse data rows
    for line in lines[data_start:]:
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if len(cells) < len(headers):
            continue

        entry = TruthTableEntry(inputs={}, outputs={})
        for j, (hdr, val) in enumerate(zip(headers, cells)):
            hdr_clean = hdr.strip()
            val_clean = val.strip()

            # Determine if this is an input or output column
            # Common output names: Q, Q_bar, Y, OUT, OUTPUT, Z
            is_output = any(hdr_clean.upper().startswith(x)
                           for x in ['Q', 'Y', 'OUT', 'Z', 'O/P'])

            # Normalize value
            if val_clean in ('0', '1'):
                v = int(val_clean)
            elif val_clean.upper() in ('X', 'x', '-', 'DC'):
                v = 'X'
            elif val_clean in ('^', '↑', 'posedge', '上升沿'):
                v = '^'
            elif val_clean in ('v', '↓', 'negedge', '下降沿'):
                v = 'v'
            elif 'Q_n' in val_clean or 'Q(n)' in val_clean or '保持' in val_clean:
                v = 'hold'
            elif val_clean.startswith('~') or val_clean.endswith('bar'):
                v = 'complement'
            else:
                v = val_clean

            if is_output:
                entry.outputs[hdr_clean] = v
            else:
                entry.inputs[hdr_clean] = v

        if entry.inputs or entry.outputs:
            entries.append(entry)

    return entries


# ============================================================================
# RTL Parser (lightweight, reuses fpga_harness_gen logic)
# ============================================================================

def parse_rtl_ports(rtl_path: str) -> Tuple[str, List[PortInfo]]:
    """Parse RTL module ports."""
    with open(rtl_path, 'r') as f:
        content = f.read()

    # Remove comments
    content_clean = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content_clean = re.sub(r'/\*.*?\*/', '', content_clean, flags=re.DOTALL)

    # Find module
    mod_match = re.search(
        r'module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\(\s*(.*?)\)\s*;',
        content_clean, re.DOTALL
    )
    if not mod_match:
        return "", []

    mod_name = mod_match.group(1)
    port_block = mod_match.group(2)

    ports = []
    current_dir = "input"

    # Parse port declarations
    for line in port_block.split(','):
        line = line.strip()
        if not line:
            continue

        m = re.match(
            r'(input|output|inout)\s+(?:wire|logic|reg)?\s*'
            r'(?:\[(\d+):(\d+)\]\s+)?(\w+)',
            line
        )
        if m:
            current_dir = m.group(1)
            msb = int(m.group(2)) if m.group(2) else 0
            lsb = int(m.group(3)) if m.group(3) else 0
            width = abs(msb - lsb) + 1 if m.group(2) else 1
            ports.append(PortInfo(name=m.group(4), direction=current_dir, width=width))
        else:
            m2 = re.match(r'(?:\[(\d+):(\d+)\]\s+)?(\w+)', line)
            if m2:
                msb = int(m2.group(1)) if m2.group(1) else 0
                lsb = int(m2.group(2)) if m2.group(2) else 0
                width = abs(msb - lsb) + 1 if m2.group(1) else 1
                ports.append(PortInfo(name=m2.group(3), direction=current_dir, width=width))

    return mod_name, ports


# ============================================================================
# Golden Model Code Generator
# ============================================================================

def generate_golden_model(spec: ICSpec, mod_name: str, ports: List[PortInfo]) -> str:
    """Generate the complete Python golden model code."""
    if spec.ic_type == "logic":
        return _gen_logic_model(spec, mod_name, ports)
    elif spec.ic_type in ("i2c", "spi"):
        return _gen_protocol_model(spec, mod_name, ports)
    else:
        return _gen_template_model(spec, mod_name, ports)


def _gen_logic_model(spec: ICSpec, mod_name: str, ports: List[PortInfo]) -> str:
    """Generate golden model for a logic IC (truth table based)."""

    inputs = [p for p in ports if p.direction == "input"]
    outputs = [p for p in ports if p.direction == "output"]

    # Detect clock and reset
    clk_ports = [p.name for p in inputs if re.match(
        r'^(?:clk|CLK|clock|CLOCK)\d*$', p.name, re.IGNORECASE)]
    rst_ports = [p.name for p in inputs if re.match(
        r'^(?:rst|RST|reset|RESET|rst_n|RST_N|resetn|nrst).*$', p.name, re.IGNORECASE)]

    input_names = ', '.join(f'"{p.name}"' for p in inputs)
    output_names = ', '.join(f'"{p.name}"' for p in outputs)

    # Generate truth table code
    tt_code = _gen_truth_table_code(spec.truth_table, inputs, outputs)

    # State variables for sequential ICs
    state_init = ""
    if spec.is_sequential:
        state_vars = [p.name for p in outputs]
        state_dict = ', '.join(f'"{v}": 0' for v in state_vars)
        state_init = f"""
    # State (for sequential ICs)
    state = {{{state_dict}}}
"""

    return f'''\
#!/usr/bin/env python3
"""
{mod_name.upper()} Golden Model -- Auto-generated from Datasheet
{'=' * (len(mod_name) + 50)}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
IC Type: {spec.ic_type} ({'sequential' if spec.is_sequential else 'combinational'})
Description: {spec.description[:100] if spec.description else mod_name}

Usage:
    from {mod_name}_golden import {mod_name}_golden, {mod_name}_initial_state
    state = {mod_name}_initial_state()
    outputs, state = {mod_name}_golden(inputs, state)
"""

from typing import Dict, Tuple, Optional


# ============================================================================
# Constants
# ============================================================================
IC_NAME = "{mod_name.upper()}"
INPUT_NAMES = [{input_names}]
OUTPUT_NAMES = [{output_names}]
CLOCK_PORTS = {clk_ports}
RESET_PORTS = {rst_ports}
IS_SEQUENTIAL = {spec.is_sequential}


# ============================================================================
# State Management
# ============================================================================

def {mod_name}_initial_state() -> Dict[str, int]:
    """Return default power-on state."""
    return {{{', '.join(f'"{p.name}": 0' for p in outputs)}}}


# ============================================================================
# Golden Model
# ============================================================================

def {mod_name}_golden(
    inputs: Dict[str, int],
    state: Optional[Dict[str, int]] = None,
    prev_inputs: Optional[Dict[str, int]] = None
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Compute expected outputs for given inputs.

    Args:
        inputs: dict mapping input port names to values (0 or 1 for 1-bit)
        state: current state (for sequential ICs), None uses initial state
        prev_inputs: previous input values (for edge detection)

    Returns:
        (outputs_dict, new_state_dict)
    """
    if state is None:
        state = {mod_name}_initial_state()

    outputs = dict(state)  # start with current state
{tt_code}

    return outputs, outputs.copy()


# ============================================================================
# Vector-based Interface (for BIST cross-verification)
# ============================================================================

def {mod_name}_from_vector(
    input_vec: int,
    state: Optional[Dict[str, int]] = None,
    prev_vec: Optional[int] = None
) -> Tuple[int, Dict[str, int]]:
    """
    Compute golden output from packed input vector.

    Args:
        input_vec: packed input bits (MSB = first input port)
        state: current state dict
        prev_vec: previous input vector

    Returns:
        (output_packed_int, new_state)
    """
    # Unpack inputs
    inputs = {{}}
    bit_pos = {sum(p.width for p in inputs)} - 1
    for name in INPUT_NAMES:
        inputs[name] = (input_vec >> bit_pos) & 1
        bit_pos -= 1

    prev_inputs = None
    if prev_vec is not None:
        prev_inputs = {{}}
        bit_pos = {sum(p.width for p in inputs)} - 1
        for name in INPUT_NAMES:
            prev_inputs[name] = (prev_vec >> bit_pos) & 1
            bit_pos -= 1

    outputs, new_state = {mod_name}_golden(inputs, state, prev_inputs)

    # Pack outputs
    result = 0
    for name in OUTPUT_NAMES:
        result = (result << 1) | (outputs.get(name, 0) & 1)

    return result, new_state


# ============================================================================
# Validation Helpers
# ============================================================================

def validate_single(input_vec: int, expected_out: int,
                    state=None, prev_vec=None) -> Tuple[bool, int, Dict]:
    """Validate a single test vector against golden model."""
    actual, new_state = {mod_name}_from_vector(input_vec, state, prev_vec)
    return actual == expected_out, actual, new_state


def validate_vectors(vectors: list) -> Tuple[int, int, list]:
    """
    Validate a list of (input, expected_output) tuples.

    Returns:
        (pass_count, fail_count, failure_details_list)
    """
    state = {mod_name}_initial_state()
    passes = 0
    fails = 0
    failures = []
    prev_vec = None

    for i, (inp, exp) in enumerate(vectors):
        match, actual, state = validate_single(inp, exp, state, prev_vec)
        if match:
            passes += 1
        else:
            fails += 1
            failures.append({{
                'index': i,
                'input': f"0x{{inp:X}}",
                'expected': f"0x{{exp:X}}",
                'golden': f"0x{{actual:X}}",
            }})
        prev_vec = inp

    return passes, fails, failures


if __name__ == '__main__':
    print(f"{{IC_NAME}} Golden Model")
    print(f"  Inputs:  {{INPUT_NAMES}}")
    print(f"  Outputs: {{OUTPUT_NAMES}}")
    print(f"  Sequential: {{IS_SEQUENTIAL}}")

    # Quick self-test with initial state
    state = {mod_name}_initial_state()
    print(f"  Initial state: {{state}}")

    # Test all-zeros input
    inputs = {{name: 0 for name in INPUT_NAMES}}
    outputs, state = {mod_name}_golden(inputs, state)
    print(f"  All-zero input -> {{outputs}}")
'''


def _gen_truth_table_code(tt_entries: List[TruthTableEntry],
                          inputs: List[PortInfo],
                          outputs: List[PortInfo]) -> str:
    """Generate Python code implementing the truth table."""
    if not tt_entries:
        # No truth table found -- generate TODO stubs
        conditions = []
        for p in outputs:
            conditions.append(f'    # TODO: Implement {p.name} logic')
            conditions.append(f'    # outputs["{p.name}"] = ...')
        conditions.append('')
        conditions.append('    # NOTE: No truth table found in datasheet.')
        conditions.append('    # Please implement the IC behavior manually.')
        return '\n'.join(conditions)

    lines = []
    lines.append('')
    lines.append('    # Truth table implementation')

    for i, entry in enumerate(tt_entries):
        # Build condition
        conds = []
        for inp_name, val in entry.inputs.items():
            if val == 'X' or val == '-':
                continue
            elif val == '^':
                # Rising edge -- check current=1, prev=0
                conds.append(
                    f'inputs.get("{inp_name}", 0) == 1 and '
                    f'(prev_inputs or {{}}).get("{inp_name}", 0) == 0')
            elif val == 'v':
                conds.append(
                    f'inputs.get("{inp_name}", 0) == 0 and '
                    f'(prev_inputs or {{}}).get("{inp_name}", 0) == 1')
            elif isinstance(val, int):
                conds.append(f'inputs.get("{inp_name}", 0) == {val}')

        if_kw = "if" if i == 0 else "elif"
        if conds:
            cond_str = ' and '.join(conds)
            lines.append(f'    {if_kw} {cond_str}:')
        else:
            lines.append(f'    {"else" if i > 0 else "if True"}:')

        # Build assignments
        for out_name, val in entry.outputs.items():
            if isinstance(val, int):
                lines.append(f'        outputs["{out_name}"] = {val}')
            elif val == 'hold':
                lines.append(f'        outputs["{out_name}"] = state.get("{out_name}", 0)')
            elif val == 'complement':
                lines.append(f'        outputs["{out_name}"] = 1 - state.get("{out_name}", 0)')
            elif val == 'X':
                lines.append(f'        outputs["{out_name}"] = state.get("{out_name}", 0)  # don\'t care')
            else:
                lines.append(f'        outputs["{out_name}"] = state.get("{out_name}", 0)  # TODO: {val}')

    return '\n'.join(lines)


def _gen_protocol_model(spec: ICSpec, mod_name: str, ports: List[PortInfo]) -> str:
    """Generate golden model for an I2C/SPI protocol IC."""

    inputs = [p for p in ports if p.direction == "input"]
    outputs = [p for p in ports if p.direction == "output"]

    # Generate register definitions
    reg_defs = []
    reg_defaults = []
    for reg in spec.registers:
        reg_defs.append(
            f'    0x{reg.address:02X}: {{"name": "{reg.name}", "size": {reg.size_bits}, '
            f'"access": "{reg.access}", "default": 0x{reg.default_value:04X}}},'
        )
        reg_defaults.append(f'        0x{reg.address:02X}: 0x{reg.default_value:04X},')

    reg_def_block = '\n'.join(reg_defs)
    reg_default_block = '\n'.join(reg_defaults)

    protocol_state_machine = ""
    if spec.protocol == "i2c":
        protocol_state_machine = _gen_i2c_state_machine(spec)
    elif spec.protocol == "spi":
        protocol_state_machine = _gen_spi_state_machine(spec)

    return f'''\
#!/usr/bin/env python3
"""
{mod_name.upper()} Golden Model -- Auto-generated from Datasheet
{'=' * (len(mod_name) + 50)}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
IC Type: {spec.ic_type} ({spec.protocol} protocol)
Description: {spec.description[:100] if spec.description else mod_name}

Register Map:
{chr(10).join(f"    0x{r.address:02X}: {r.name} ({r.size_bits}-bit, {r.access})" for r in spec.registers)}

Usage:
    model = {mod_name.upper()}GoldenModel()
    model.write_register(0x01, 0x20)
    val = model.read_register(0x00)
"""

from typing import Dict, List, Optional, Tuple


# ============================================================================
# Register Map
# ============================================================================
REGISTER_MAP = {{
{reg_def_block}
}}


# ============================================================================
# Golden Model Class
# ============================================================================

class {mod_name.upper()}GoldenModel:
    """Behavioral model of {mod_name.upper()} with register-level access."""

    def __init__(self):
        """Initialize with default register values."""
        self.registers: Dict[int, int] = {{
{reg_default_block}
        }}
        self.pointer: int = 0x00     # Current register pointer
        self.state: str = "IDLE"     # Protocol state machine
        self._shift_reg: int = 0
        self._bit_count: int = 0

    def reset(self):
        """Power-on reset: restore all registers to defaults."""
        for addr, info in REGISTER_MAP.items():
            self.registers[addr] = info["default"]
        self.pointer = 0x00
        self.state = "IDLE"

    def read_register(self, addr: int) -> int:
        """Read a register by address."""
        if addr not in REGISTER_MAP:
            return 0
        info = REGISTER_MAP[addr]
        if 'R' not in info["access"] and 'r' not in info["access"]:
            return 0  # Write-only register
        return self.registers.get(addr, 0)

    def write_register(self, addr: int, value: int):
        """Write a register by address."""
        if addr not in REGISTER_MAP:
            return
        info = REGISTER_MAP[addr]
        if 'W' not in info["access"] and 'w' not in info["access"]:
            return  # Read-only register
        mask = (1 << info["size"]) - 1
        self.registers[addr] = value & mask

    def get_register_field(self, addr: int, msb: int, lsb: int) -> int:
        """Read a bit field from a register."""
        val = self.read_register(addr)
        mask = ((1 << (msb - lsb + 1)) - 1) << lsb
        return (val & mask) >> lsb

    def set_register_field(self, addr: int, msb: int, lsb: int, value: int):
        """Write a bit field in a register."""
        reg_val = self.registers.get(addr, 0)
        mask = ((1 << (msb - lsb + 1)) - 1) << lsb
        reg_val = (reg_val & ~mask) | ((value << lsb) & mask)
        self.write_register(addr, reg_val)

{protocol_state_machine}

    # ========================================================================
    # Output Computation
    # ========================================================================

    def compute_outputs(self) -> Dict[str, int]:
        """
        Compute IC output signals based on current register state.
        TODO: Implement IC-specific output logic.
        """
        outputs = {{}}
        # TODO: Map register values to output port signals
        # Example:
        #   outputs["os"] = 1 if temperature > t_os else 0
        return outputs

    def dump_state(self) -> Dict[str, int]:
        """Return complete register state for debugging."""
        return dict(self.registers)


# ============================================================================
# Convenience Functions
# ============================================================================

def {mod_name}_initial_state() -> Dict[str, int]:
    """Return initial register state."""
    model = {mod_name.upper()}GoldenModel()
    return model.dump_state()


def {mod_name}_golden(inputs: Dict[str, int],
                     state: Optional[Dict[str, int]] = None) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Stateless golden model interface.

    Args:
        inputs: input signal values
        state: register state dict

    Returns:
        (outputs, new_state)
    """
    model = {mod_name.upper()}GoldenModel()
    if state:
        model.registers = dict(state)
    outputs = model.compute_outputs()
    return outputs, model.dump_state()


if __name__ == '__main__':
    model = {mod_name.upper()}GoldenModel()
    print(f"{{model.__class__.__name__}} Golden Model")
    print(f"  Registers: {{len(REGISTER_MAP)}}")
    for addr, info in REGISTER_MAP.items():
        val = model.read_register(addr)
        print(f"    0x{{addr:02X}}: {{info['name']:20s}} = 0x{{val:04X}} ({{info['access']}})")
'''


def _gen_i2c_state_machine(spec: ICSpec) -> str:
    """Generate I2C protocol state machine methods."""
    return """\
    # ========================================================================
    # I2C Protocol State Machine
    # ========================================================================

    def i2c_start(self):
        \"\"\"I2C START condition.\"\"\"
        self.state = "ADDR"
        self._shift_reg = 0
        self._bit_count = 0

    def i2c_stop(self):
        \"\"\"I2C STOP condition.\"\"\"
        self.state = "IDLE"

    def i2c_bit(self, sda: int) -> Optional[int]:
        \"\"\"
        Clock in one bit of I2C data (called on SCL rising edge).
        Returns ACK/NACK (0=ACK, 1=NACK) when a byte boundary is reached,
        or None during data bits.
        \"\"\"
        if self.state == "IDLE":
            return None

        self._shift_reg = (self._shift_reg << 1) | (sda & 1)
        self._bit_count += 1

        if self._bit_count == 8:
            byte_val = self._shift_reg & 0xFF
            self._shift_reg = 0
            self._bit_count = 0

            if self.state == "ADDR":
                # Address byte: [7:1] = slave addr, [0] = R/W
                self._rw = byte_val & 1
                self.state = "POINTER" if self._rw == 0 else "READ"
                return 0  # ACK

            elif self.state == "POINTER":
                self.pointer = byte_val
                self.state = "WRITE"
                return 0  # ACK

            elif self.state == "WRITE":
                self.write_register(self.pointer, byte_val)
                self.pointer = (self.pointer + 1) & 0xFF
                return 0  # ACK

            elif self.state == "READ":
                return 0  # ACK (master will read)

        return None

    def i2c_read_byte(self) -> int:
        \"\"\"Return the next byte for I2C master read.\"\"\"
        val = self.read_register(self.pointer)
        self.pointer = (self.pointer + 1) & 0xFF
        return val & 0xFF
"""


def _gen_spi_state_machine(spec: ICSpec) -> str:
    """Generate SPI protocol state machine methods."""
    return """\
    # ========================================================================
    # SPI Protocol State Machine
    # ========================================================================

    def spi_select(self):
        \"\"\"CS_N asserted (active low).\"\"\"
        self.state = "CMD"
        self._shift_reg = 0
        self._bit_count = 0

    def spi_deselect(self):
        \"\"\"CS_N deasserted.\"\"\"
        self.state = "IDLE"

    def spi_clock_bit(self, mosi: int) -> int:
        \"\"\"
        Clock in one MOSI bit, return MISO bit.
        Called on SCLK active edge.
        \"\"\"
        self._shift_reg = (self._shift_reg << 1) | (mosi & 1)
        self._bit_count += 1

        miso_bit = 0

        if self._bit_count == 8:
            byte_val = self._shift_reg & 0xFF
            self._shift_reg = 0
            self._bit_count = 0

            if self.state == "CMD":
                # First byte: command/address
                self._rw = (byte_val >> 7) & 1  # MSB = R/W
                self.pointer = byte_val & 0x7F
                self.state = "DATA"
            elif self.state == "DATA":
                if self._rw == 0:
                    # Write
                    self.write_register(self.pointer, byte_val)
                    self.pointer = (self.pointer + 1) & 0xFF

        # For reads, shift out register data
        if self.state == "DATA" and hasattr(self, '_rw') and self._rw == 1:
            reg_val = self.read_register(self.pointer)
            bit_idx = 7 - (self._bit_count % 8)
            miso_bit = (reg_val >> bit_idx) & 1

        return miso_bit
"""


def _gen_template_model(spec: ICSpec, mod_name: str, ports: List[PortInfo]) -> str:
    """Generate a template/stub golden model for complex ICs."""

    inputs = [p for p in ports if p.direction == "input"]
    outputs = [p for p in ports if p.direction == "output"]

    input_list = '\n'.join(f'#    {p.name} [{p.width}-bit]' for p in inputs)
    output_list = '\n'.join(f'#    {p.name} [{p.width}-bit]' for p in outputs)

    output_stubs = []
    for p in outputs:
        output_stubs.append(f'    outputs["{p.name}"] = 0  # TODO: implement')

    reg_section = ""
    if spec.registers:
        reg_lines = []
        for reg in spec.registers:
            reg_lines.append(
                f'    0x{reg.address:02X}: {{"name": "{reg.name}", '
                f'"size": {reg.size_bits}, "default": 0x{reg.default_value:04X}}},')
        reg_section = f"""
# Register Map (extracted from datasheet)
REGISTER_MAP = {{
{chr(10).join(reg_lines)}
}}
"""

    return f'''\
#!/usr/bin/env python3
"""
{mod_name.upper()} Golden Model -- TEMPLATE (Auto-generated)
{'=' * (len(mod_name) + 45)}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
IC Type: {spec.ic_type}
Description: {spec.description[:100] if spec.description else mod_name}

WARNING: This is a TEMPLATE with behavioral stubs.
         You must implement the actual IC behavior.

Input Ports:
{input_list}

Output Ports:
{output_list}

Usage:
    from {mod_name}_golden import {mod_name}_golden
    outputs, state = {mod_name}_golden(inputs, state)
"""

from typing import Dict, Optional, Tuple

IC_NAME = "{mod_name.upper()}"
{reg_section}

def {mod_name}_initial_state() -> Dict[str, int]:
    """Return initial state."""
    return {{{', '.join(f'"{p.name}": 0' for p in outputs)}}}


def {mod_name}_golden(
    inputs: Dict[str, int],
    state: Optional[Dict[str, int]] = None,
    prev_inputs: Optional[Dict[str, int]] = None
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Compute expected outputs. TEMPLATE -- implement IC behavior.

    Args:
        inputs: input signal values
        state: current state
        prev_inputs: previous inputs (for edge detection)

    Returns:
        (outputs, new_state)
    """
    if state is None:
        state = {mod_name}_initial_state()

    outputs = dict(state)

    # ================================================================
    # TODO: Implement {mod_name.upper()} behavioral model here
    # ================================================================
{chr(10).join(output_stubs)}

    return outputs, outputs.copy()


if __name__ == '__main__':
    state = {mod_name}_initial_state()
    print(f"{{IC_NAME}} Golden Model (TEMPLATE)")
    print(f"  State: {{state}}")
    print(f"  WARNING: Behavioral stubs only. Please implement IC logic.")
'''


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Golden Model Auto-Generator from Datasheet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
    python3 golden_model_auto.py \\
        --ds ic_projects_v2/ic_001_CD4013B/04_datasheet.md \\
        --rtl ic_projects_v2/ic_001_CD4013B/phase2_design/rtl/cd4013b.sv \\
        --output golden.py
        """,
    )
    parser.add_argument('--ds', required=True, help='Path to datasheet.md')
    parser.add_argument('--rtl', required=True, help='Path to RTL .sv file')
    parser.add_argument('--output', required=True, help='Output golden model .py file')
    parser.add_argument('--type', choices=['logic', 'i2c', 'spi', 'auto'],
                        default='auto', help='IC type (default: auto-detect)')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    # Validate inputs
    if not os.path.isfile(args.ds):
        print(f"ERROR: Datasheet not found: {args.ds}")
        sys.exit(1)
    if not os.path.isfile(args.rtl):
        print(f"ERROR: RTL file not found: {args.rtl}")
        sys.exit(1)

    if not args.quiet:
        print(f"\n  Golden Model Auto-Generator")
        print(f"  {'=' * 50}")
        print(f"  Datasheet: {args.ds}")
        print(f"  RTL:       {args.rtl}")

    # Parse datasheet
    spec = parse_datasheet(args.ds)

    # Override type if specified
    if args.type != 'auto':
        spec.ic_type = args.type

    # Parse RTL
    mod_name, ports = parse_rtl_ports(args.rtl)
    if not mod_name:
        print("ERROR: Could not parse module from RTL file")
        sys.exit(1)

    if not args.quiet:
        print(f"  Module:    {mod_name}")
        print(f"  IC Type:   {spec.ic_type}")
        print(f"  Protocol:  {spec.protocol or 'none'}")
        print(f"  Registers: {len(spec.registers)}")
        print(f"  Truth table entries: {len(spec.truth_table)}")
        print(f"  Sequential: {spec.is_sequential}")
        print(f"  Ports:     {len(ports)} ({sum(1 for p in ports if p.direction == 'input')} in, "
              f"{sum(1 for p in ports if p.direction == 'output')} out)")

    # Generate golden model
    code = generate_golden_model(spec, mod_name, ports)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w') as f:
        f.write(code)

    if not args.quiet:
        print(f"\n  Output:    {args.output}")
        lines = code.count('\n')
        print(f"  Lines:     {lines}")
        print(f"  Type:      {spec.ic_type} -> "
              f"{'truth table model' if spec.ic_type == 'logic' else 'register model' if spec.ic_type in ('i2c', 'spi') else 'template stub'}")
        print()

    return spec, mod_name


if __name__ == '__main__':
    main()
