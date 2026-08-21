#!/usr/bin/env python3
"""
signaltap_gen — Auto-Generate Quartus SignalTap II Configuration
================================================================
Generates .stp (SignalTap) XML files from RTL port lists for FPGA debugging.

Usage:
    # Parse ports from SystemVerilog file
    python3 signaltap_gen.py --module cd4013b --sv rtl/cd4013b.sv

    # Custom trigger and depth
    python3 signaltap_gen.py --module cd4013b --sv rtl/cd4013b.sv \\
        --trigger bist_fail --depth 2048 --clock clk_50

    # Manual port list
    python3 signaltap_gen.py --module cd4013b \\
        --ports "clk:I:1,rst_n:I:1,d:I:1,q:O:1,q_bar:O:1"

Output: <module>_debug.stp — Quartus SignalTap configuration XML
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Port:
    name: str
    direction: str  # I, O, IO
    width: int = 1
    msb: int = 0
    lsb: int = 0


# ============================================================================
# RTL Port Parser
# ============================================================================

def parse_ports_from_sv(sv_path: str, module_name: str) -> List[Port]:
    """Parse port list from a SystemVerilog file.

    Handles common port declaration formats:
        input  logic       clk,
        input  logic [7:0] data_in,
        output logic       q,
        output wire  [3:0] addr,
        inout  wire        sda,
    """
    if not os.path.exists(sv_path):
        print(f"ERROR: File not found: {sv_path}", file=sys.stderr)
        return []

    with open(sv_path, 'r') as f:
        content = f.read()

    # Find the module declaration
    # Match from 'module <name>' to the end of port list or first ';'
    module_pattern = rf'module\s+{re.escape(module_name)}\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;'
    m = re.search(module_pattern, content, re.DOTALL)
    if not m:
        # Try simpler pattern: module name ( ... );
        module_pattern2 = rf'module\s+{re.escape(module_name)}\s*\((.*?)\)\s*;'
        m = re.search(module_pattern2, content, re.DOTALL)

    ports = []

    if m:
        port_block = m.group(1)
        # Parse ANSI-style port declarations within the module header
        port_regex = re.compile(
            r'(input|output|inout)\s+'
            r'(?:logic|wire|reg|)\s*'
            r'(?:\[(\d+):(\d+)\]\s*)?'
            r'(\w+)',
            re.IGNORECASE
        )
        for pm in port_regex.finditer(port_block):
            direction = pm.group(1).upper()[0]  # I, O, I (for inout)
            if pm.group(1).upper() == 'INOUT':
                direction = 'IO'
            msb = int(pm.group(2)) if pm.group(2) else 0
            lsb = int(pm.group(3)) if pm.group(3) else 0
            width = abs(msb - lsb) + 1
            name = pm.group(4)
            ports.append(Port(name=name, direction=direction, width=width, msb=msb, lsb=lsb))
    else:
        # Fallback: search for port declarations in the entire file after module keyword
        module_start = re.search(rf'module\s+{re.escape(module_name)}', content)
        if module_start:
            rest = content[module_start.start():]
            port_regex = re.compile(
                r'(input|output|inout)\s+'
                r'(?:logic|wire|reg|)\s*'
                r'(?:\[(\d+):(\d+)\]\s*)?'
                r'(\w+)',
                re.IGNORECASE
            )
            for pm in port_regex.finditer(rest):
                direction = pm.group(1).upper()[0]
                if pm.group(1).upper() == 'INOUT':
                    direction = 'IO'
                msb = int(pm.group(2)) if pm.group(2) else 0
                lsb = int(pm.group(3)) if pm.group(3) else 0
                width = abs(msb - lsb) + 1
                name = pm.group(4)
                ports.append(Port(name=name, direction=direction, width=width, msb=msb, lsb=lsb))

    return ports


def parse_ports_from_string(port_str: str) -> List[Port]:
    """Parse ports from a comma-separated string.

    Format: "name:dir:width,name:dir:width,..."
    Example: "clk:I:1,data:I:8,q:O:1"
    """
    ports = []
    for item in port_str.split(','):
        item = item.strip()
        if not item:
            continue
        parts = item.split(':')
        if len(parts) >= 3:
            name = parts[0].strip()
            direction = parts[1].strip().upper()
            width = int(parts[2].strip())
        elif len(parts) == 2:
            name = parts[0].strip()
            direction = parts[1].strip().upper()
            width = 1
        else:
            name = parts[0].strip()
            direction = 'I'
            width = 1
        msb = width - 1 if width > 1 else 0
        ports.append(Port(name=name, direction=direction, width=width, msb=msb, lsb=0))
    return ports


# ============================================================================
# BIST signals (standard infrastructure)
# ============================================================================

BIST_SIGNALS = [
    Port(name='bist_state', direction='I', width=3, msb=2, lsb=0),
    Port(name='test_index', direction='I', width=5, msb=4, lsb=0),
    Port(name='pass_count', direction='I', width=8, msb=7, lsb=0),
    Port(name='fail_count', direction='I', width=8, msb=7, lsb=0),
    Port(name='bist_running', direction='I', width=1),
    Port(name='bist_done', direction='I', width=1),
    Port(name='bist_fail', direction='I', width=1),
]


# ============================================================================
# STP XML Generator
# ============================================================================

def generate_stp_xml(
    module_name: str,
    ports: List[Port],
    trigger_signal: str = 'bist_fail',
    depth: int = 1024,
    clock: str = 'CLOCK_50',
    include_bist: bool = True,
) -> str:
    """Generate SignalTap II .stp XML content."""

    # Build signal list
    all_signals = list(ports)
    if include_bist:
        # Add BIST signals (skip duplicates)
        existing_names = {p.name for p in all_signals}
        for bist_sig in BIST_SIGNALS:
            if bist_sig.name not in existing_names:
                all_signals.append(bist_sig)

    # Create XML structure
    root = ET.Element('session')
    root.set('version', '1.0')

    # Global settings
    global_settings = ET.SubElement(root, 'global_settings')
    ET.SubElement(global_settings, 'setting').text = f'SignalTap auto-generated for {module_name}'
    ET.SubElement(global_settings, 'device').text = '5CSEBA6U23I7'
    ET.SubElement(global_settings, 'sld_hub_entity').text = f'{module_name}_fpga_top'

    # Instance
    instance = ET.SubElement(root, 'instance')
    instance.set('entity_name', f'{module_name}_fpga_top')
    instance.set('is_auto_node', 'yes')
    instance.set('source', 'JTAG')

    # Signal set
    signal_set = ET.SubElement(instance, 'signal_set')
    signal_set.set('name', f'{module_name}_debug')
    signal_set.set('is_expanded', 'yes')

    # Clock
    clock_elem = ET.SubElement(signal_set, 'clock')
    clock_elem.set('name', clock)
    clock_elem.set('edge', 'rising')

    # DUT signals
    dut_group = ET.SubElement(signal_set, 'signal_group')
    dut_group.set('name', f'{module_name}_dut')

    dut_inst_prefix = f'{module_name}_inst'
    for port in ports:
        sig = ET.SubElement(dut_group, 'signal')
        if port.width > 1:
            sig.set('name', f'{dut_inst_prefix}|{port.name}[{port.msb}:{port.lsb}]')
        else:
            sig.set('name', f'{dut_inst_prefix}|{port.name}')
        sig.set('tap_mode', 'classic')
        sig.set('type', port.direction)
        sig.set('width', str(port.width))

    # BIST signals group
    if include_bist:
        bist_group = ET.SubElement(signal_set, 'signal_group')
        bist_group.set('name', 'bist_engine')

        for bist_sig in BIST_SIGNALS:
            sig = ET.SubElement(bist_group, 'signal')
            if bist_sig.width > 1:
                sig.set('name', f'bist_engine|{bist_sig.name}[{bist_sig.msb}:{bist_sig.lsb}]')
            else:
                sig.set('name', f'bist_engine|{bist_sig.name}')
            sig.set('tap_mode', 'classic')
            sig.set('width', str(bist_sig.width))

    # Trigger
    trigger = ET.SubElement(instance, 'trigger')
    trigger.set('attribute_mem_mode', 'false')
    trigger.set('gap_record', 'false')
    trigger.set('global_temp', '1')
    trigger.set('power_up_trigger_mode', 'false')
    trigger.set('record_data_gap', 'true')
    trigger.set('segment_size', str(depth))
    trigger.set('storage_mode', 'off')
    trigger.set('storage_qualifier_disabled', 'no')
    trigger.set('trigger_in', 'dont_care')
    trigger.set('trigger_out', 'active high')

    basic_trigger = ET.SubElement(trigger, 'basic_trigger')
    trigger_input = ET.SubElement(basic_trigger, 'trigger_input')
    trigger_input.set('signal', trigger_signal)
    trigger_input.set('edge', 'rising')
    trigger_input.set('condition', 'rising_edge')

    # Pre-trigger / post-trigger split
    trigger_position = ET.SubElement(trigger, 'trigger_position')
    trigger_position.set('pre_trigger', str(depth // 4))  # 25% pre-trigger
    trigger_position.set('post_trigger', str(depth - depth // 4))

    # Buffer
    buffer_elem = ET.SubElement(instance, 'buffer')
    buffer_elem.set('depth', str(depth))
    buffer_elem.set('type', 'internal')

    # Signal configuration
    config = ET.SubElement(instance, 'configuration')
    ET.SubElement(config, 'data_log').text = 'off'
    ET.SubElement(config, 'jtag_info').text = 'auto'
    ET.SubElement(config, 'power_up_trigger').text = 'false'

    # Pretty-print XML
    rough_string = ET.tostring(root, encoding='unicode')
    dom = minidom.parseString(rough_string)
    return dom.toprettyxml(indent='  ', encoding=None)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='SignalTap II Auto-Generator for FPGA debugging'
    )
    parser.add_argument('--module', required=True, help='DUT module name')
    parser.add_argument('--sv', default=None, help='SystemVerilog source file to parse ports from')
    parser.add_argument('--ports', default=None,
                        help='Manual port list: "name:dir:width,..." (alternative to --sv)')
    parser.add_argument('--trigger', default='bist_fail', help='Trigger signal (default: bist_fail)')
    parser.add_argument('--depth', type=int, default=1024, help='Capture depth (default: 1024)')
    parser.add_argument('--clock', default='CLOCK_50', help='Capture clock (default: CLOCK_50)')
    parser.add_argument('--output', '-o', default=None, help='Output .stp file path')
    parser.add_argument('--no-bist', action='store_true', help='Skip BIST signals')
    args = parser.parse_args()

    # Get ports
    if args.sv:
        ports = parse_ports_from_sv(args.sv, args.module)
        if not ports:
            print(f"WARNING: No ports found in {args.sv} for module {args.module}", file=sys.stderr)
            print("Falling back to empty port list. Use --ports for manual entry.", file=sys.stderr)
    elif args.ports:
        ports = parse_ports_from_string(args.ports)
    else:
        print("ERROR: Must provide --sv or --ports", file=sys.stderr)
        sys.exit(1)

    print(f"Module: {args.module}")
    print(f"Ports found: {len(ports)}")
    for p in ports:
        width_str = f"[{p.msb}:{p.lsb}]" if p.width > 1 else ""
        print(f"  {p.direction:2s} {p.name}{width_str}")

    # Generate STP
    stp_content = generate_stp_xml(
        module_name=args.module,
        ports=ports,
        trigger_signal=args.trigger,
        depth=args.depth,
        clock=args.clock,
        include_bist=not args.no_bist,
    )

    # Write output
    output_path = args.output or f"{args.module}_debug.stp"
    with open(output_path, 'w') as f:
        f.write(stp_content)

    print(f"\nSignalTap configuration written to: {output_path}")
    print(f"  Trigger: {args.trigger} (rising edge)")
    print(f"  Depth: {args.depth} samples")
    print(f"  Clock: {args.clock}")
    print(f"  Total signals: {len(ports) + (len(BIST_SIGNALS) if not args.no_bist else 0)}")
    # The recompile instruction block. It MUST name all four stages.
    #
    # This block used to print `quartus_stp` and nothing else. `quartus_stp`
    # only ATTACHES the .stp to the project database — it does not re-map,
    # re-fit or re-assemble, so following the instruction as written produced
    # the previous SOF, unchanged, with no logic analyzer in it. You then
    # program the board, run the BIST, and SignalTap shows nothing: the exact
    # ~30-minute-round-trip defect that
    # programs/signaltap_recompile_sequence_check.py exists to catch, emitted
    # by this repo's own generator. Piping this program's real stdout into that
    # gate returned rc=1 with 3 x STAGE_MISSING (map, fit, asm).
    #
    # skills/fpga-signaltap/SKILL.md lines 65-68 already declared the full
    # sequence; only this block disagreed with it.
    proj = f"{args.module}_fpga"
    print(f"\nUsage in Quartus:")
    print(f"  1. Open {output_path} in SignalTap II Logic Analyzer")
    print(f"  2. Re-compile — ALL FOUR stages, in this order. `quartus_stp`")
    print(f"     alone only attaches the .stp; without map/fit/asm the SOF is")
    print(f"     unchanged and contains NO logic analyzer:")
    print(f"       quartus_stp {proj} --stp_file={output_path}")
    print(f"       quartus_map {proj}")
    print(f"       quartus_fit {proj}")
    print(f"       quartus_asm {proj}")
    print(f"  3. Program FPGA and run BIST")


if __name__ == '__main__':
    main()
