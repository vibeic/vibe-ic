#!/usr/bin/env python3
"""
FPGA Test Harness Template Generator (R2#3)
============================================
Parses an IC RTL file (.sv), extracts module name and ports, and generates
a complete FPGA test project for the DE10-Nano board (5CSEBA6U23I7).

Generated files:
    1. <module>_bist.sv      -- BIST engine with configurable test vectors
    2. <module>_fpga_top.sv  -- DE10-Nano top wrapper (DUT + BIST + UART TX/RX + LEDs)
    3. <module>_fpga.qsf     -- Quartus project settings
    4. <module>_fpga.qpf     -- Quartus QPF
    5. <module>_fpga.sdc     -- Timing constraints
    6. fpga_test.py          -- Python UART test script (based on fpga_test_v5 template)
    7. README.md             -- Usage guide

Usage:
    python3 fpga_harness_gen.py --rtl path/to/module.sv --output path/to/fpga_test/
    python3 fpga_harness_gen.py --rtl ic_projects_v2/ic_001_CD4013B/phase2_design/rtl/cd4013b.sv --output /tmp/test_harness/
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PortInfo:
    """Single port parsed from RTL."""
    name: str
    direction: str       # "input", "output", "inout"
    width: int = 1       # bit width
    msb: int = 0         # MSB index for multi-bit
    lsb: int = 0         # LSB index for multi-bit
    is_wire: bool = True  # wire vs logic
    comment: str = ""


@dataclass
class ModuleInfo:
    """Parsed module information."""
    name: str
    ports: List[PortInfo] = field(default_factory=list)
    file_path: str = ""
    clock_port: Optional[str] = None
    reset_port: Optional[str] = None
    reset_active_low: bool = True

    @property
    def inputs(self) -> List[PortInfo]:
        return [p for p in self.ports if p.direction == "input"]

    @property
    def outputs(self) -> List[PortInfo]:
        return [p for p in self.ports if p.direction == "output"]

    @property
    def inouts(self) -> List[PortInfo]:
        return [p for p in self.ports if p.direction == "inout"]

    @property
    def input_width(self) -> int:
        """Total input bits (excluding clock/reset)."""
        return sum(p.width for p in self.inputs
                   if p.name != self.clock_port and p.name != self.reset_port)

    @property
    def output_width(self) -> int:
        """Total output bits."""
        return sum(p.width for p in self.outputs)

    @property
    def total_pins(self) -> int:
        return sum(p.width for p in self.ports)


# ============================================================================
# CLK / RST Detection Patterns
# ============================================================================

CLK_PATTERNS = [
    r'^clk$', r'^CLK$', r'^clock$', r'^CLOCK$',
    r'^clk\d*$', r'^CLK\d*$', r'^sys_clk$', r'^SYS_CLK$',
    r'^i_clk$', r'^i_clock$', r'^clk_i$', r'^clock_i$',
    r'^HCLK$', r'^PCLK$', r'^ACLK$', r'^FCLK$',
    r'^mclk$', r'^MCLK$', r'^sclk$', r'^SCLK$',
]

RST_PATTERNS_ACTIVE_LOW = [
    r'^rst_n$', r'^RST_N$', r'^reset_n$', r'^RESET_N$',
    r'^rstn$', r'^RSTN$', r'^resetn$', r'^RESETN$',
    r'^nrst$', r'^NRST$', r'^nreset$', r'^NRESET$',
    r'^i_rst_n$', r'^rst_ni$', r'^arst_n$', r'^ARST_N$',
    r'^HRESETn$', r'^PRESETn$', r'^ARESETn$',
]

RST_PATTERNS_ACTIVE_HIGH = [
    r'^rst$', r'^RST$', r'^reset$', r'^RESET$',
    r'^i_rst$', r'^rst_i$', r'^arst$', r'^ARST$',
    r'^HRESET$', r'^PRESET$', r'^ARESET$',
]


# ============================================================================
# RTL Parser
# ============================================================================

def parse_sv_module(filepath: str) -> ModuleInfo:
    """Parse a SystemVerilog file and extract the first module's ports."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Remove single-line comments but keep them for later reference
    content_no_comments = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove block comments
    content_no_comments = re.sub(r'/\*.*?\*/', '', content_no_comments, flags=re.DOTALL)

    # Find the first module declaration
    mod_match = re.search(
        r'module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\(\s*(.*?)\)\s*;',
        content_no_comments, re.DOTALL
    )
    if not mod_match:
        print(f"ERROR: No module found in {filepath}")
        sys.exit(1)

    mod_name = mod_match.group(1)
    port_block = mod_match.group(2)

    ports = _parse_port_block(port_block)

    info = ModuleInfo(
        name=mod_name,
        ports=ports,
        file_path=os.path.abspath(filepath),
    )

    # Auto-detect clock
    for p in info.inputs:
        for pat in CLK_PATTERNS:
            if re.match(pat, p.name, re.IGNORECASE):
                info.clock_port = p.name
                break
        if info.clock_port:
            break

    # Auto-detect reset (active-low first)
    for p in info.inputs:
        for pat in RST_PATTERNS_ACTIVE_LOW:
            if re.match(pat, p.name, re.IGNORECASE):
                info.reset_port = p.name
                info.reset_active_low = True
                break
        if info.reset_port:
            break

    if not info.reset_port:
        for p in info.inputs:
            for pat in RST_PATTERNS_ACTIVE_HIGH:
                if re.match(pat, p.name, re.IGNORECASE):
                    info.reset_port = p.name
                    info.reset_active_low = False
                    break
            if info.reset_port:
                break

    return info


def _parse_port_block(block: str) -> List[PortInfo]:
    """Parse the port declaration block."""
    ports = []
    # Split by commas, respecting nested brackets
    entries = _split_ports(block)

    current_dir = "input"
    current_type = "wire"

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        # Match: input/output/inout [wire|logic|reg] [N:M] name [, name2]
        m = re.match(
            r'(input|output|inout)\s+'
            r'(?:(wire|logic|reg)\s+)?'
            r'(?:\[(\d+):(\d+)\]\s+)?'
            r'(\w+)',
            entry
        )
        if m:
            current_dir = m.group(1)
            if m.group(2):
                current_type = m.group(2)
            msb = int(m.group(3)) if m.group(3) else 0
            lsb = int(m.group(4)) if m.group(4) else 0
            width = abs(msb - lsb) + 1 if m.group(3) else 1
            name = m.group(5)
            ports.append(PortInfo(
                name=name, direction=current_dir, width=width,
                msb=msb, lsb=lsb, is_wire=(current_type in ('wire', 'logic')),
            ))
        else:
            # Might be a continuation like just a name after comma in same direction
            m2 = re.match(r'(?:\[(\d+):(\d+)\]\s+)?(\w+)', entry)
            if m2:
                msb = int(m2.group(1)) if m2.group(1) else 0
                lsb = int(m2.group(2)) if m2.group(2) else 0
                width = abs(msb - lsb) + 1 if m2.group(1) else 1
                name = m2.group(3)
                ports.append(PortInfo(
                    name=name, direction=current_dir, width=width,
                    msb=msb, lsb=lsb,
                ))

    return ports


def _split_ports(block: str) -> List[str]:
    """Split port block by commas, ignoring commas inside brackets."""
    parts = []
    depth = 0
    current = []
    for ch in block:
        if ch in ('(', '['):
            depth += 1
            current.append(ch)
        elif ch in (')', ']'):
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


# ============================================================================
# File Generators
# ============================================================================

def gen_bist_sv(mod: ModuleInfo) -> str:
    """Generate <module>_bist.sv -- BIST engine with test vectors."""

    # Separate DUT inputs (excluding clk/rst) and outputs
    dut_inputs = [p for p in mod.inputs
                  if p.name != mod.clock_port and p.name != mod.reset_port]
    dut_outputs = mod.outputs

    inp_w = sum(p.width for p in dut_inputs)
    out_w = sum(p.width for p in dut_outputs)

    # Build port list for BIST module
    bist_ports = []
    bist_ports.append("    input  logic        clk,")
    bist_ports.append("    input  logic        rst_n,")
    bist_ports.append("    input  logic        start,")
    bist_ports.append("    input  logic [7:0]  cmd_byte,")
    bist_ports.append("    input  logic        cmd_valid,")
    bist_ports.append("")

    # DUT drive outputs (BIST drives DUT inputs)
    for p in dut_inputs:
        w = f"[{p.msb}:{p.lsb}]" if p.width > 1 else "       "
        bist_ports.append(f"    output logic {w} dut_{p.name},")
    # DUT read inputs (BIST reads DUT outputs)
    for p in dut_outputs:
        w = f"[{p.msb}:{p.lsb}]" if p.width > 1 else "       "
        bist_ports.append(f"    input  logic {w} dut_{p.name},")

    bist_ports.append("")
    bist_ports.append("    output logic        running, done, all_pass,")
    bist_ports.append(f"    output logic [7:0]  test_num, pass_count, fail_count, total_tests,")
    bist_ports.append("")
    bist_ports.append("    output logic [7:0]  tx_byte,")
    bist_ports.append("    output logic        tx_valid,")
    bist_ports.append("    input  logic        tx_ready")

    bist_ports_str = '\n'.join(bist_ports)

    # Generate basic test vectors
    # Pattern: reset test + all-zeros + all-ones + walking-one
    num_basic_tests = 3 + inp_w  # reset + all-0 + all-1 + walking-one
    num_basic_tests = min(num_basic_tests, 64)  # cap at 64

    tv_lines = []
    tv_idx = 0

    # Test 0: all zeros
    tv_lines.append(f"        tv_in[{tv_idx}] = {inp_w}'d0;")
    tv_lines.append(f"        tv_exp[{tv_idx}] = {out_w}'d0; // TODO: set expected output for all-zero input")
    tv_lines.append(f"        tv_group[{tv_idx}] = 4'd0; // Group 0: Reset")
    tv_idx += 1

    # Test 1: all ones
    tv_lines.append(f"        tv_in[{tv_idx}] = {{{inp_w}{{1'b1}}}};")
    tv_lines.append(f"        tv_exp[{tv_idx}] = {out_w}'d0; // TODO: set expected output for all-ones input")
    tv_lines.append(f"        tv_group[{tv_idx}] = 4'd1; // Group 1: All-ones")
    tv_idx += 1

    # Walking-one patterns (up to 16 or inp_w, whichever is smaller)
    walk_count = min(inp_w, 16)
    for i in range(walk_count):
        tv_lines.append(f"        tv_in[{tv_idx}] = {inp_w}'d{1 << i};")
        tv_lines.append(f"        tv_exp[{tv_idx}] = {out_w}'d0; // TODO: set expected output for walking-one bit {i}")
        tv_lines.append(f"        tv_group[{tv_idx}] = 4'd2; // Group 2: Walking-one")
        tv_idx += 1

    # Walking-zero patterns (up to 8)
    walk0_count = min(inp_w, 8)
    for i in range(walk0_count):
        mask = ((1 << inp_w) - 1) ^ (1 << i)
        tv_lines.append(f"        tv_in[{tv_idx}] = {inp_w}'d{mask};")
        tv_lines.append(f"        tv_exp[{tv_idx}] = {out_w}'d0; // TODO: set expected output for walking-zero bit {i}")
        tv_lines.append(f"        tv_group[{tv_idx}] = 4'd3; // Group 3: Walking-zero")
        tv_idx += 1
        if tv_idx >= 64:
            break

    total_tests = tv_idx
    tv_init = '\n'.join(tv_lines)

    # Build DUT input assignment from test vector
    assign_lines = []
    bit_pos = inp_w - 1
    for p in dut_inputs:
        if p.width == 1:
            assign_lines.append(f"            dut_{p.name} <= tv_in[cur][{bit_pos}];")
        else:
            assign_lines.append(f"            dut_{p.name} <= tv_in[cur][{bit_pos}:{bit_pos - p.width + 1}];")
        bit_pos -= p.width
    assign_block = '\n'.join(assign_lines)

    # Build actual output capture
    capture_parts = []
    for p in dut_outputs:
        capture_parts.append(f"dut_{p.name}")
    capture_expr = ', '.join(capture_parts)

    # Build pin list for coverage
    pin_parts = []
    for p in dut_inputs:
        pin_parts.append(f"dut_{p.name}")
    for p in dut_outputs:
        pin_parts.append(f"dut_{p.name}")
    pin_list = ', '.join(pin_parts)
    total_pins = sum(p.width for p in dut_inputs) + out_w

    return f"""\
// ============================================================================
// {mod.name.upper()} BIST Engine -- Auto-generated by fpga_harness_gen.py
// ============================================================================
// Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
// Source RTL: {mod.file_path}
//
// UART Commands:
//   'R' = Run BIST (single pass)
//   'L' + 2-byte count = Stress loop
//   'C' = Query coverage
//   'D' = Toggle debug trace
//   'S' = Query status
//
// Test Vectors: {total_tests} vectors, {inp_w}-bit input, {out_w}-bit expected output
//   Group 0: Reset (all-zeros)
//   Group 1: All-ones
//   Group 2: Walking-one
//   Group 3: Walking-zero
//   TODO: Add IC-specific test vectors for Groups 4+
// ============================================================================

module {mod.name}_bist (
{bist_ports_str}
);

    localparam N = {total_tests};
    localparam SETTLE = 100;  // clock cycles to wait for DUT to settle
    assign total_tests = 8'd{total_tests};

    // ========================================================================
    // Test Vectors
    // TODO: Replace expected values (tv_exp) with correct values for your IC
    // ========================================================================
    logic [{inp_w - 1}:0] tv_in  [0:N-1];
    logic [{out_w - 1}:0] tv_exp [0:N-1];
    logic [3:0]  tv_group [0:N-1];

    initial begin
{tv_init}
    end

    // ========================================================================
    // BIST State Machine
    // ========================================================================
    typedef enum logic [3:0] {{
        S_IDLE, S_APPLY, S_SETTLE, S_CHECK, S_REPORT,
        S_TX_WAIT, S_TX_LINE, S_TX_CHAR,
        S_LOOP_INIT, S_LOOP_RUN, S_LOOP_REPORT
    }} state_t;

    state_t      state, next_after_tx;
    logic [7:0]  cur;                // current test index
    logic [15:0] settle_cnt;         // settle counter
    logic [{out_w - 1}:0] actual;    // captured output
    logic [7:0]  p_cnt, f_cnt;       // pass/fail counts
    logic        debug_mode;
    logic        loop_mode;
    logic [15:0] loop_total, loop_cur, loop_pass, loop_fail, loop_first_fail;
    logic [1:0]  loop_byte_cnt;
    logic [15:0] loop_count_buf;

    // UART TX buffer
    logic [7:0]  tx_buf [0:79];      // max 80 chars per line
    logic [6:0]  tx_len, tx_idx;

    assign running    = (state != S_IDLE);
    assign done       = (state == S_IDLE && (p_cnt + f_cnt) > 0);
    assign all_pass   = (f_cnt == 0) && (p_cnt > 0);
    assign pass_count = p_cnt;
    assign fail_count = f_cnt;
    assign test_num   = cur;

    // ========================================================================
    // Hex-to-ASCII helper
    // ========================================================================
    function automatic logic [7:0] hex_char(input logic [3:0] v);
        return (v < 10) ? (8'h30 + {{4'b0, v}}) : (8'h41 + {{4'b0, v}} - 8'd10);
    endfunction

    // ========================================================================
    // Command Receiver
    // ========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state         <= S_IDLE;
            cur           <= 0;
            p_cnt         <= 0;
            f_cnt         <= 0;
            settle_cnt    <= 0;
            debug_mode    <= 0;
            loop_mode     <= 0;
            loop_byte_cnt <= 0;
            tx_valid      <= 0;
        end else begin
            tx_valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (start) begin
                        // Hardware start button
                        cur   <= 0;
                        p_cnt <= 0;
                        f_cnt <= 0;
                        state <= S_APPLY;
                    end else if (cmd_valid) begin
                        case (cmd_byte)
                            "R": begin
                                cur   <= 0;
                                p_cnt <= 0;
                                f_cnt <= 0;
                                loop_mode <= 0;
                                state <= S_APPLY;
                            end
                            "D": debug_mode <= ~debug_mode;
                            "C": begin
                                // Send coverage query response
                                state <= S_REPORT;
                            end
                            "L": begin
                                loop_byte_cnt <= 0;
                                loop_mode     <= 1;
                            end
                            default: ;
                        endcase
                    end

                    // Collect 2-byte loop count
                    if (loop_mode && !loop_byte_cnt[1] && cmd_valid && cmd_byte != "L") begin
                        if (loop_byte_cnt == 0) begin
                            loop_count_buf[15:8] <= cmd_byte;
                            loop_byte_cnt <= 1;
                        end else begin
                            loop_count_buf[7:0] <= cmd_byte;
                            loop_byte_cnt <= 2;
                            // Start loop
                            loop_total <= {{loop_count_buf[15:8], cmd_byte}};
                            loop_cur   <= 0;
                            loop_pass  <= 0;
                            loop_fail  <= 0;
                            loop_first_fail <= 0;
                            cur   <= 0;
                            p_cnt <= 0;
                            f_cnt <= 0;
                            state <= S_APPLY;
                        end
                    end
                end

                S_APPLY: begin
                    // Apply test vector to DUT
{assign_block}
                    settle_cnt <= 0;
                    state <= S_SETTLE;
                end

                S_SETTLE: begin
                    if (settle_cnt >= SETTLE) begin
                        // Capture DUT output
                        actual <= {{{capture_expr}}};
                        state <= S_CHECK;
                    end else begin
                        settle_cnt <= settle_cnt + 1;
                    end
                end

                S_CHECK: begin
                    if (actual == tv_exp[cur]) begin
                        p_cnt <= p_cnt + 1;
                    end else begin
                        f_cnt <= f_cnt + 1;
                        if (loop_mode && loop_first_fail == 0)
                            loop_first_fail <= loop_cur + 1;
                    end

                    // Format UART output line
                    if (!loop_mode || actual != tv_exp[cur]) begin
                        // Build: "T<nn>:<P/F> I=XX A=XX E=XX G=X\\n"
                        tx_buf[0] <= "T";
                        tx_buf[1] <= 8'h30 + (cur / 10);
                        tx_buf[2] <= 8'h30 + (cur % 10);
                        tx_buf[3] <= ":";
                        tx_buf[4] <= (actual == tv_exp[cur]) ? "P" : "F";
                        tx_buf[5] <= " ";
                        tx_buf[6] <= "I";
                        tx_buf[7] <= "=";
                        tx_buf[8] <= hex_char(tv_in[cur][{inp_w - 1}:{max(inp_w - 4, 0)}]);
                        tx_buf[9] <= hex_char(tv_in[cur][{min(inp_w - 1, 3)}:0]);
                        tx_buf[10] <= " ";
                        tx_buf[11] <= "A";
                        tx_buf[12] <= "=";
                        tx_buf[13] <= hex_char(actual[{out_w - 1}:{max(out_w - 4, 0)}]);
                        tx_buf[14] <= (({out_w}) > 4) ? hex_char(actual[{min(out_w - 1, 3)}:0]) : " ";
                        tx_buf[15] <= " ";
                        tx_buf[16] <= "E";
                        tx_buf[17] <= "=";
                        tx_buf[18] <= hex_char(tv_exp[cur][{out_w - 1}:{max(out_w - 4, 0)}]);
                        tx_buf[19] <= (({out_w}) > 4) ? hex_char(tv_exp[cur][{min(out_w - 1, 3)}:0]) : " ";
                        tx_buf[20] <= " ";
                        tx_buf[21] <= "G";
                        tx_buf[22] <= "=";
                        tx_buf[23] <= 8'h30 + {{4'b0, tv_group[cur]}};
                        tx_buf[24] <= 8'h0A;  // newline
                        tx_len <= 25;
                        tx_idx <= 0;
                        next_after_tx <= (cur + 1 >= N) ? S_REPORT : S_APPLY;
                        state <= S_TX_CHAR;
                    end else begin
                        // Loop mode, pass: skip UART, go to next
                        if (cur + 1 >= N) begin
                            state <= S_REPORT;
                        end else begin
                            cur <= cur + 1;
                            state <= S_APPLY;
                        end
                    end

                    if (cur + 1 < N && (loop_mode && actual == tv_exp[cur]))
                        ; // handled above
                    else
                        cur <= cur + 1;
                end

                S_TX_CHAR: begin
                    if (tx_ready) begin
                        tx_byte  <= tx_buf[tx_idx];
                        tx_valid <= 1'b1;
                        if (tx_idx + 1 >= tx_len) begin
                            state <= next_after_tx;
                        end else begin
                            tx_idx <= tx_idx + 1;
                        end
                    end
                end

                S_REPORT: begin
                    if (loop_mode) begin
                        // Check if more iterations
                        loop_cur <= loop_cur + 1;
                        if (f_cnt > 0) loop_fail <= loop_fail + 1;
                        else           loop_pass <= loop_pass + 1;

                        if (loop_cur + 1 < loop_total) begin
                            cur   <= 0;
                            p_cnt <= 0;
                            f_cnt <= 0;
                            state <= S_APPLY;
                        end else begin
                            // Send loop summary
                            // "LOOP:XXXX PASS:XXXX FAIL:XXXX FF:XXXX\\n"
                            _format_loop_report();
                            next_after_tx <= S_IDLE;
                            state <= S_TX_CHAR;
                        end
                    end else begin
                        // Single run: send summary
                        // "RES P:<p> F:<f> T:<t>\\n"
                        tx_buf[0]  <= "R"; tx_buf[1]  <= "E"; tx_buf[2]  <= "S";
                        tx_buf[3]  <= " ";
                        tx_buf[4]  <= "P"; tx_buf[5]  <= ":";
                        tx_buf[6]  <= hex_char(p_cnt[7:4]);
                        tx_buf[7]  <= hex_char(p_cnt[3:0]);
                        tx_buf[8]  <= " ";
                        tx_buf[9]  <= "F"; tx_buf[10] <= "A"; tx_buf[11] <= "I";
                        tx_buf[12] <= "L"; tx_buf[13] <= ":";
                        tx_buf[14] <= hex_char(f_cnt[7:4]);
                        tx_buf[15] <= hex_char(f_cnt[3:0]);
                        tx_buf[16] <= 8'h0A;
                        tx_len <= 17;
                        tx_idx <= 0;
                        next_after_tx <= S_IDLE;
                        state <= S_TX_CHAR;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    // ========================================================================
    // Loop report formatter (task)
    // ========================================================================
    task automatic _format_loop_report();
        tx_buf[0]  <= "L"; tx_buf[1]  <= "O"; tx_buf[2]  <= "O"; tx_buf[3]  <= "P"; tx_buf[4]  <= ":";
        tx_buf[5]  <= hex_char(loop_total[15:12]); tx_buf[6]  <= hex_char(loop_total[11:8]);
        tx_buf[7]  <= hex_char(loop_total[7:4]);   tx_buf[8]  <= hex_char(loop_total[3:0]);
        tx_buf[9]  <= " ";
        tx_buf[10] <= "P"; tx_buf[11] <= "A"; tx_buf[12] <= "S"; tx_buf[13] <= "S"; tx_buf[14] <= ":";
        tx_buf[15] <= hex_char(loop_pass[15:12]); tx_buf[16] <= hex_char(loop_pass[11:8]);
        tx_buf[17] <= hex_char(loop_pass[7:4]);   tx_buf[18] <= hex_char(loop_pass[3:0]);
        tx_buf[19] <= " ";
        tx_buf[20] <= "F"; tx_buf[21] <= "A"; tx_buf[22] <= "I"; tx_buf[23] <= "L"; tx_buf[24] <= ":";
        tx_buf[25] <= hex_char(loop_fail[15:12]); tx_buf[26] <= hex_char(loop_fail[11:8]);
        tx_buf[27] <= hex_char(loop_fail[7:4]);   tx_buf[28] <= hex_char(loop_fail[3:0]);
        tx_buf[29] <= " ";
        tx_buf[30] <= "F"; tx_buf[31] <= "F"; tx_buf[32] <= ":";
        tx_buf[33] <= hex_char(loop_first_fail[15:12]); tx_buf[34] <= hex_char(loop_first_fail[11:8]);
        tx_buf[35] <= hex_char(loop_first_fail[7:4]);   tx_buf[36] <= hex_char(loop_first_fail[3:0]);
        tx_buf[37] <= 8'h0A;
        tx_len <= 38;
        tx_idx <= 0;
    endtask

endmodule
"""


def gen_fpga_top_sv(mod: ModuleInfo) -> str:
    """Generate <module>_fpga_top.sv -- DE10-Nano wrapper."""

    dut_inputs = [p for p in mod.inputs
                  if p.name != mod.clock_port and p.name != mod.reset_port]
    dut_outputs = mod.outputs

    # DUT signal declarations
    dut_sigs = []
    for p in dut_inputs:
        w = f"[{p.msb}:{p.lsb}]" if p.width > 1 else ""
        dut_sigs.append(f"    logic {w:10s} dut_{p.name};")
    for p in dut_outputs:
        w = f"[{p.msb}:{p.lsb}]" if p.width > 1 else ""
        dut_sigs.append(f"    logic {w:10s} dut_{p.name};")
    dut_sig_block = '\n'.join(dut_sigs)

    # DUT instantiation port connections
    dut_conns = []
    for p in mod.ports:
        if p.name == mod.clock_port:
            dut_conns.append(f"        .{p.name:20s} (CLOCK_50),")
        elif p.name == mod.reset_port:
            if mod.reset_active_low:
                dut_conns.append(f"        .{p.name:20s} (rst_n),")
            else:
                dut_conns.append(f"        .{p.name:20s} (!rst_n),")
        else:
            dut_conns.append(f"        .{p.name:20s} (dut_{p.name}),")
    # Remove trailing comma from last
    if dut_conns:
        dut_conns[-1] = dut_conns[-1].rstrip(',')
    dut_conn_block = '\n'.join(dut_conns)

    # BIST port connections
    bist_conns = []
    bist_conns.append(f"        .clk              (CLOCK_50),")
    bist_conns.append(f"        .rst_n            (rst_n),")
    bist_conns.append(f"        .start            (start_pulse),")
    bist_conns.append(f"        .cmd_byte         (uart_rx_data),")
    bist_conns.append(f"        .cmd_valid        (uart_rx_valid),")
    for p in dut_inputs:
        bist_conns.append(f"        .dut_{p.name:14s} (dut_{p.name}),")
    for p in dut_outputs:
        bist_conns.append(f"        .dut_{p.name:14s} (dut_{p.name}),")
    bist_conns.append(f"        .running          (bist_running),")
    bist_conns.append(f"        .done             (bist_done),")
    bist_conns.append(f"        .all_pass         (bist_all_pass),")
    bist_conns.append(f"        .test_num         (bist_test_num),")
    bist_conns.append(f"        .pass_count       (bist_pass_count),")
    bist_conns.append(f"        .fail_count       (bist_fail_count),")
    bist_conns.append(f"        .total_tests      (),")
    bist_conns.append(f"        .tx_byte          (bist_tx_byte),")
    bist_conns.append(f"        .tx_valid         (bist_tx_valid),")
    bist_conns.append(f"        .tx_ready         (uart_tx_ready)")
    bist_conn_block = '\n'.join(bist_conns)

    # LED mapping: first 8 output bits -> LEDR
    led_assigns = []
    out_bit = 0
    for p in dut_outputs:
        for b in range(p.width):
            if out_bit < 5:
                if p.width == 1:
                    led_assigns.append(f"    assign LEDR[{out_bit}]   = dut_{p.name};")
                else:
                    led_assigns.append(f"    assign LEDR[{out_bit}]   = dut_{p.name}[{b}];")
            out_bit += 1
    # Fill remaining LEDs with status
    while out_bit < 5:
        led_assigns.append(f"    assign LEDR[{out_bit}]   = 1'b0;")
        out_bit += 1
    led_assigns.append(f"    assign LEDR[5]   = bist_running & blink_cnt[23];  // RUNNING (blink)")
    led_assigns.append(f"    assign LEDR[6]   = bist_done & ~bist_all_pass;    // ANY FAIL")
    led_assigns.append(f"    assign LEDR[7]   = bist_done & bist_all_pass;     // ALL PASS")
    led_block = '\n'.join(led_assigns)

    return f"""\
// ============================================================================
// {mod.name.upper()} FPGA Test Top -- DE10-Nano (Cyclone V 5CSEBA6U23I7)
// ============================================================================
// Auto-generated by fpga_harness_gen.py
// Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
// Source RTL: {mod.file_path}
//
// Connections:
//   CLOCK_50  -> system clock (50 MHz)
//   KEY[0]    -> reset (active low)
//   KEY[1]    -> start BIST (active low, edge-detect)
//   LEDR[0:4] -> DUT output bits
//   LEDR[5]   -> RUNNING (blink)
//   LEDR[6]   -> ANY FAIL (solid)
//   LEDR[7]   -> ALL PASS (solid)
//   GPIO_0[0] -> UART TX to PC (115200 baud)
//   GPIO_0[1] -> UART RX from PC (115200 baud)
// ============================================================================

module {mod.name}_fpga_top (
    input  logic       CLOCK_50,
    input  logic [1:0] KEY,
    input  logic [3:0] SW,
    output logic [7:0] LEDR,
    inout  logic [5:0] GPIO_0
);

    // ---- Reset & Clock ----
    logic rst_n;
    assign rst_n = KEY[0];  // KEY[0] active-low = reset

    // ---- Start edge detect (KEY[1]) ----
    logic key1_sync1, key1_sync2, key1_prev;
    logic start_pulse;

    always_ff @(posedge CLOCK_50) begin
        if (!rst_n) begin
            key1_sync1 <= 1'b1;
            key1_sync2 <= 1'b1;
            key1_prev  <= 1'b1;
        end else begin
            key1_sync1 <= KEY[1];
            key1_sync2 <= key1_sync1;
            key1_prev  <= key1_sync2;
        end
    end
    assign start_pulse = key1_prev & ~key1_sync2;  // falling edge of KEY[1]

    // ---- DUT Signals ----
{dut_sig_block}

    // ---- DUT Instance ----
    {mod.name} u_dut (
{dut_conn_block}
    );

    // ---- BIST Engine ----
    logic       bist_running, bist_done, bist_all_pass;
    logic [7:0] bist_test_num, bist_pass_count, bist_fail_count;
    logic [7:0] bist_tx_byte;
    logic       bist_tx_valid;
    logic       uart_tx_ready;

    {mod.name}_bist u_bist (
{bist_conn_block}
    );

    // ---- UART TX ----
    logic uart_tx_pin;

    uart_tx #(
        .CLK_FREQ(50_000_000),
        .BAUD(115200)
    ) u_uart_tx (
        .clk      (CLOCK_50),
        .rst_n    (rst_n),
        .tx_data  (bist_tx_byte),
        .tx_valid (bist_tx_valid),
        .tx_ready (uart_tx_ready),
        .tx_pin   (uart_tx_pin)
    );

    // ---- UART RX ----
    logic [7:0] uart_rx_data;
    logic       uart_rx_valid;

    uart_rx #(
        .CLK_FREQ(50_000_000),
        .BAUD(115200)
    ) u_uart_rx (
        .clk      (CLOCK_50),
        .rst_n    (rst_n),
        .rx_pin   (GPIO_0[1]),
        .rx_data  (uart_rx_data),
        .rx_valid (uart_rx_valid)
    );

    // ---- GPIO Assignment ----
    assign GPIO_0[0] = uart_tx_pin;   // TX output
    // GPIO_0[1] is input (RX)
    assign GPIO_0[2] = bist_running;  // Debug: BIST running
    assign GPIO_0[3] = bist_done;     // Debug: BIST done
    assign GPIO_0[4] = bist_all_pass; // Debug: all pass
    assign GPIO_0[5] = 1'b0;

    // ---- LED Display ----
    logic [24:0] blink_cnt;
    always_ff @(posedge CLOCK_50) begin
        if (!rst_n)
            blink_cnt <= 25'd0;
        else
            blink_cnt <= blink_cnt + 25'd1;
    end

{led_block}

endmodule
"""


def gen_qsf(mod: ModuleInfo, rtl_rel_path: str) -> str:
    """Generate Quartus .qsf file."""
    return f"""\
# {mod.name.upper()} FPGA Test -- DE10-Nano Quartus Settings
# Auto-generated by fpga_harness_gen.py
# Device: Cyclone V 5CSEBA6U23I7

set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEBA6U23I7
set_global_assignment -name TOP_LEVEL_ENTITY {mod.name}_fpga_top
set_global_assignment -name PROJECT_CREATION_TIME_DATE "{datetime.now().strftime('%Y-%m-%d')}"
set_global_assignment -name MIN_CORE_JUNCTION_TEMP "-40"
set_global_assignment -name MAX_CORE_JUNCTION_TEMP 100
set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 256

# RTL Sources
set_global_assignment -name SYSTEMVERILOG_FILE {mod.name}_fpga_top.sv
set_global_assignment -name SYSTEMVERILOG_FILE {mod.name}_bist.sv
set_global_assignment -name SYSTEMVERILOG_FILE uart_tx.sv
set_global_assignment -name SYSTEMVERILOG_FILE uart_rx.sv
set_global_assignment -name SYSTEMVERILOG_FILE {rtl_rel_path}

# SDC
set_global_assignment -name SDC_FILE {mod.name}_fpga.sdc

# ============================================================
# Clock (Table 3-5) -- FPGA_CLK1_50 = 50 MHz
# ============================================================
set_location_assignment PIN_V11  -to CLOCK_50

# ============================================================
# KEY (Table 3-7) -- active low push-buttons
# ============================================================
set_location_assignment PIN_AH17 -to KEY[0]
set_location_assignment PIN_AH16 -to KEY[1]

# ============================================================
# SW (Table 3-6) -- slide switches
# ============================================================
set_location_assignment PIN_Y24  -to SW[0]
set_location_assignment PIN_W24  -to SW[1]
set_location_assignment PIN_W21  -to SW[2]
set_location_assignment PIN_W20  -to SW[3]

# ============================================================
# LED (Table 3-8) -- active high, 8 LEDs
# ============================================================
set_location_assignment PIN_W15  -to LEDR[0]
set_location_assignment PIN_AA24 -to LEDR[1]
set_location_assignment PIN_V16  -to LEDR[2]
set_location_assignment PIN_V15  -to LEDR[3]
set_location_assignment PIN_AF26 -to LEDR[4]
set_location_assignment PIN_AE26 -to LEDR[5]
set_location_assignment PIN_Y16  -to LEDR[6]
set_location_assignment PIN_AA23 -to LEDR[7]

# ============================================================
# GPIO 0 (JP1) -- Table 3-10
# GPIO_0[0] = PIN_V12 -> UART TX
# GPIO_0[1] = PIN_E8  -> UART RX
# ============================================================
set_location_assignment PIN_V12  -to GPIO_0[0]
set_location_assignment PIN_E8   -to GPIO_0[1]
set_location_assignment PIN_W12  -to GPIO_0[2]
set_location_assignment PIN_D11  -to GPIO_0[3]
set_location_assignment PIN_D8   -to GPIO_0[4]
set_location_assignment PIN_AH13 -to GPIO_0[5]

# ============================================================
# I/O Standards
# ============================================================
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to CLOCK_50
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to KEY[0]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to KEY[1]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to SW[*]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to LEDR[*]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to GPIO_0[*]

# ============================================================
# Partitioning
# ============================================================
set_global_assignment -name GENERATE_JBF_FILE ON
set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -section_id Top
set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -section_id Top
set_global_assignment -name PARTITION_COLOR 16764057 -section_id Top
set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -section_id Top
"""


def gen_qpf(mod: ModuleInfo) -> str:
    """Generate Quartus .qpf file."""
    return f"""\
QUARTUS_VERSION = "25.1"
DATE = "{datetime.now().strftime('%Y-%m-%d')}"
PROJECT_REVISION = "{mod.name}_fpga"
"""


def gen_sdc(mod: ModuleInfo) -> str:
    """Generate SDC timing constraints."""
    return f"""\
# Timing Constraints for {mod.name.upper()} FPGA Verification
# Board: DE10-Nano, 50 MHz oscillator (PIN_V11)

# 50 MHz board clock
create_clock -name CLOCK_50 -period 20.000 [get_ports {{CLOCK_50}}]

# GPIO is async -- no timing requirement
set_false_path -from [get_ports {{GPIO_0[*]}}]
set_false_path -to   [get_ports {{GPIO_0[*]}}]
set_false_path -from [get_ports {{KEY[*]}}]
set_false_path -from [get_ports {{SW[*]}}]
set_false_path -to   [get_ports {{LEDR[*]}}]
"""


def gen_fpga_test_py(mod: ModuleInfo) -> str:
    """Generate fpga_test.py -- Python UART test script."""

    dut_inputs = [p for p in mod.inputs
                  if p.name != mod.clock_port and p.name != mod.reset_port]
    dut_outputs = mod.outputs
    inp_w = sum(p.width for p in dut_inputs)
    out_w = sum(p.width for p in dut_outputs)

    # Build pin name lists
    input_pin_names = []
    for p in dut_inputs:
        if p.width == 1:
            input_pin_names.append(f'"{p.name}"')
        else:
            for b in range(p.width - 1, -1, -1):
                input_pin_names.append(f'"{p.name}[{b}]"')
    output_pin_names = []
    for p in dut_outputs:
        if p.width == 1:
            output_pin_names.append(f'"{p.name}"')
        else:
            for b in range(p.width - 1, -1, -1):
                output_pin_names.append(f'"{p.name}[{b}]"')

    # Basic test count matches BIST
    num_tests = 3 + min(inp_w, 16) + min(inp_w, 8)
    num_tests = min(num_tests, 64)

    return f'''\
#!/usr/bin/env python3
"""
{mod.name.upper()} FPGA Test Script
{'=' * (len(mod.name) + 22)}
Auto-generated by fpga_harness_gen.py
Based on Vibe-IC FPGA Verification Program v5 template.

Stages:
    1. Connection Check
    2. BIST Execution (single run)
    3. Per-Test Results (real-time)
    3.5 Stress Loop (optional)
    4. Report Generation

Usage:
    python3 fpga_test.py [--port /dev/ttyUSB0] [--auto] [--stress N]
"""

import argparse
import sys
import os
import time
import json
import struct
from datetime import datetime
from typing import Tuple, List, Dict, Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: pip install pyserial")
    sys.exit(1)

# ============================================================================
# IC Configuration
# ============================================================================
IC_NAME = "{mod.name.upper()}"
IC_DESC = "{mod.name} -- auto-generated test"
TOTAL_TESTS = {num_tests}
INPUT_WIDTH = {inp_w}
OUTPUT_WIDTH = {out_w}

INPUT_PINS = [{', '.join(input_pin_names)}]
OUTPUT_PINS = [{', '.join(output_pin_names)}]

GROUP_NAMES = {{
    0: "Reset (all-zeros)",
    1: "All-ones",
    2: "Walking-one",
    3: "Walking-zero",
    # TODO: Add IC-specific group names
}}


def sep(title=""):
    w = 64
    if title:
        pad = (w - len(title) - 2) // 2
        return f"\\n{{\\'=\\' * pad}} {{title}} {{\\'=\\' * pad}}\\n"
    return "\\n" + "=" * w + "\\n"


def find_port():
    for p in serial.tools.list_ports.comports():
        if any(k in p.description.upper()
               for k in [\'USB\', \'UART\', \'CH340\', \'CP210\', \'FTDI\']):
            return p.device
    return None


# ============================================================================
# Stage 1: Connection
# ============================================================================
def stage1(port, baud, auto):
    print(sep("STAGE 1: CONNECTION CHECK"))
    if not port:
        port = find_port()
    if not port:
        print("  [FAIL] No USB-UART found.")
        if not auto:
            port = input("  Enter port: ").strip()
        if not port:
            return None, None

    print(f"  Port: {{port}}  Baud: {{baud}}")
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(0.5)
        ser.reset_input_buffer()
        print(f"  [OK] Connected")
    except serial.SerialException as e:
        print(f"  [FAIL] {{e}}")
        return None, port

    if not auto:
        input("  Press ENTER to start BIST...")
    return ser, port


# ============================================================================
# Stage 2+3: BIST + Per-Test Results
# ============================================================================
def stage2_3(ser, debug=False):
    print(sep("STAGE 2: BIST EXECUTION"))
    print(f"  IC: {{IC_NAME}}  Tests: {{TOTAL_TESTS}}")

    ser.reset_input_buffer()
    ser.write(b\'R\')
    print(f"  Sending \'R\'...\\n")
    print(sep("STAGE 3: PER-TEST RESULTS"))

    results = []
    fail_details = []
    start = time.time()

    while time.time() - start < 120:
        if ser.in_waiting:
            line = ser.readline().decode(\'ascii\', errors=\'replace\').strip()
            if not line:
                continue

            if line.startswith(\'T\'):
                try:
                    test_part = line.split()[0]
                    tid, status = test_part.split(\':\')
                    tnum = int(tid[1:])
                    tokens = line.split()
                    inp = tokens[1].split(\'=\')[1] if len(tokens) > 1 else \'??\'
                    act = tokens[2].split(\'=\')[1] if len(tokens) > 2 else \'??\'
                    exp = tokens[3].split(\'=\')[1] if len(tokens) > 3 else \'??\'
                    grp = \'0\'
                    for t in tokens[4:]:
                        if t.startswith(\'G=\'): grp = t.split(\'=\')[1]
                except (ValueError, IndexError):
                    tnum = len(results)
                    status = \'?\'
                    inp = act = exp = \'??\'
                    grp = \'0\'

                passed = (status == \'P\')
                gi = int(grp) if grp.isdigit() else 0

                r = {{
                    \'num\': tnum, \'status\': status, \'input\': inp,
                    \'actual\': act, \'expected\': exp, \'pass\': passed,
                    \'group_idx\': gi, \'raw\': line,
                }}
                results.append(r)

                icon = \'[OK]\' if passed else \'[FAIL]\'
                print(f"    {{icon}} T{{tnum:02d}}: In=0x{{inp}} -> Out=0x{{act}} "
                      f"Exp=0x{{exp}}", end=\'\')
                if not passed:
                    print(f"  <- MISMATCH!", end=\'\')
                    fail_details.append(r)
                print()

            elif line.startswith(\'RES\'):
                break
        else:
            time.sleep(0.01)

    elapsed = time.time() - start
    return results, fail_details, elapsed


# ============================================================================
# Stage 3.5: Stress Loop
# ============================================================================
def stage3_5_stress(ser, iterations=1000, auto=False):
    print(sep("STAGE 3.5: STRESS LOOP"))
    print(f"  Iterations: {{iterations}}")

    if not auto:
        confirm = input(f"  Run stress loop? [Y/n] ").strip().lower()
        if confirm not in ("", "y", "yes"):
            print("  Skipped.")
            return None

    if iterations < 1 or iterations > 65535:
        print(f"  Error: iterations must be 1-65535.")
        return None

    count_bytes = struct.pack(\'>H\', iterations)
    ser.reset_input_buffer()
    ser.write(b\'L\')
    time.sleep(0.05)
    ser.write(count_bytes)

    print(f"  Sent: L + 0x{{count_bytes.hex().upper()}} ({{iterations}} iterations)")
    print(f"  Waiting...")

    stress_result = {{
        \'iterations\': iterations,
        \'loop_pass\': 0, \'loop_fail\': 0, \'first_fail_iter\': 0,
        \'fail_lines\': [],
    }}

    start = time.time()
    timeout = max(iterations * 0.1, 30)

    while time.time() - start < timeout:
        if ser.in_waiting:
            line = ser.readline().decode(\'ascii\', errors=\'replace\').strip()
            if not line:
                continue
            if line.startswith(\'T\') and \':F\' in line:
                stress_result[\'fail_lines\'].append(line)
                if len(stress_result[\'fail_lines\']) <= 20:
                    print(f"    [FAIL] {{line}}")
            elif line.startswith(\'LOOP:\'):
                for token in line.split():
                    if token.startswith(\'LOOP:\'):
                        stress_result[\'iterations\'] = int(token.split(\':\')[1], 16)
                    elif token.startswith(\'PASS:\'):
                        stress_result[\'loop_pass\'] = int(token.split(\':\')[1], 16)
                    elif token.startswith(\'FAIL:\'):
                        stress_result[\'loop_fail\'] = int(token.split(\':\')[1], 16)
                    elif token.startswith(\'FF:\'):
                        stress_result[\'first_fail_iter\'] = int(token.split(\':\')[1], 16)
                break
        else:
            time.sleep(0.05)

    elapsed = time.time() - start
    stress_result[\'elapsed\'] = round(elapsed, 2)

    lp = stress_result[\'loop_pass\']
    lf = stress_result[\'loop_fail\']
    total = lp + lf
    print(f"\\n  Stress: {{total}} iterations, {{lp}} pass, {{lf}} fail")
    if lf == 0 and total > 0:
        print(f"  [OK] Zero failures.")
    elif lf > 0:
        print(f"  [FAIL] {{lf}} failed iterations. First fail: {{stress_result[\'first_fail_iter\']}}")

    return stress_result


# ============================================================================
# Report Generation
# ============================================================================
def generate_report(results, fail_details, elapsed, port, stress_result):
    print(sep("REPORT GENERATION"))
    ts = datetime.now().strftime(\'%Y%m%d_%H%M%S\')
    pc = sum(1 for r in results if r[\'pass\'])
    fc = len(results) - pc
    verdict = \'PASS\' if fc == 0 else \'FAIL\'

    report = {{
        \'ic\': IC_NAME,
        \'description\': IC_DESC,
        \'board\': \'DE10-Nano (Cyclone V 5CSEBA6U23I7)\',
        \'date\': datetime.now().isoformat(),
        \'port\': port,
        \'elapsed_sec\': round(elapsed, 2),
        \'verdict\': verdict,
        \'test_results\': {{\'pass\': pc, \'fail\': fc, \'total\': len(results)}},
        \'stress_loop\': stress_result,
        \'per_test\': results,
    }}

    jf = f"test_report_{{ts}}.json"
    with open(jf, \'w\') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  JSON: {{jf}}")

    print(f"\\n  VERDICT: {{verdict}}")
    print(f"  Pass: {{pc}}  Fail: {{fc}}  Total: {{len(results)}}")
    print(f"  Elapsed: {{elapsed:.1f}}s")
    return report


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description=f"{{IC_NAME}} FPGA Test")
    parser.add_argument(\'--port\', default=None, help=\'Serial port\')
    parser.add_argument(\'--baud\', type=int, default=115200)
    parser.add_argument(\'--auto\', action=\'store_true\', help=\'Non-interactive\')
    parser.add_argument(\'--stress\', type=int, default=0, help=\'Stress loop iterations\')
    args = parser.parse_args()

    print(f"\\n  Vibe-IC FPGA Test: {{IC_NAME}}")
    print(f"  Board: DE10-Nano (5CSEBA6U23I7)")
    print(f"  {{datetime.now().strftime(\'%Y-%m-%d %H:%M:%S\')}}\\n")

    ser, port = stage1(args.port, args.baud, args.auto)
    if not ser:
        print("  Cannot connect. Exiting.")
        sys.exit(1)

    results, fail_details, elapsed = stage2_3(ser)

    stress_result = None
    if args.stress > 0:
        stress_result = stage3_5_stress(ser, args.stress, auto=True)
    elif not args.auto and results:
        do_stress = input("\\n  Run stress loop? [y/N] ").strip().lower()
        if do_stress in (\'y\', \'yes\'):
            n = input("  Iterations [1000]: ").strip()
            n = int(n) if n.isdigit() else 1000
            stress_result = stage3_5_stress(ser, n, auto=False)

    generate_report(results, fail_details, elapsed, port, stress_result)

    ser.close()
    print("\\n  Done.")


if __name__ == \'__main__\':
    main()
'''


def gen_readme(mod: ModuleInfo) -> str:
    """Generate README.md."""
    dut_inputs = [p for p in mod.inputs
                  if p.name != mod.clock_port and p.name != mod.reset_port]
    dut_outputs = mod.outputs

    inp_list = '\n'.join(f'    - {p.name} [{p.width}-bit]' for p in dut_inputs)
    out_list = '\n'.join(f'    - {p.name} [{p.width}-bit]' for p in dut_outputs)

    return f"""\
# {mod.name.upper()} FPGA Test Harness

Auto-generated by `fpga_harness_gen.py` for DE10-Nano (Cyclone V 5CSEBA6U23I7).

## DUT Information

- **Module**: `{mod.name}`
- **Source**: `{mod.file_path}`
- **Clock port**: `{mod.clock_port or 'none detected'}`
- **Reset port**: `{mod.reset_port or 'none detected'}` ({'active-low' if mod.reset_active_low else 'active-high'})

### Inputs (excluding clock/reset)
{inp_list}

### Outputs
{out_list}

## Files

| File | Description |
|------|-------------|
| `{mod.name}_fpga_top.sv` | Top-level wrapper (DUT + BIST + UART) |
| `{mod.name}_bist.sv` | BIST engine with test vectors |
| `{mod.name}_fpga.qsf` | Quartus project settings |
| `{mod.name}_fpga.qpf` | Quartus project file |
| `{mod.name}_fpga.sdc` | Timing constraints |
| `uart_tx.sv` | UART transmitter (115200 baud) |
| `uart_rx.sv` | UART receiver (115200 baud) |
| `fpga_test.py` | Python test script |

## Quick Start

1. **Customize BIST vectors**: Edit `{mod.name}_bist.sv`, fill in `tv_exp[]` with correct expected outputs for your IC.

2. **Compile in Quartus**:
   ```bash
   quartus_sh --flow compile {mod.name}_fpga
   ```

3. **Program DE10-Nano**:
   ```bash
   quartus_pgm -m jtag -o "P;{mod.name}_fpga.sof@2"
   ```

4. **Run test**:
   ```bash
   pip install pyserial
   python3 fpga_test.py --port /dev/ttyUSB0 --auto
   ```

5. **Stress test**:
   ```bash
   python3 fpga_test.py --port /dev/ttyUSB0 --stress 10000
   ```

## Hardware Setup

- Connect USB-UART adapter:
  - GPIO_0[0] (PIN_V12) -> UART RX (adapter side)
  - GPIO_0[1] (PIN_E8)  -> UART TX (adapter side)
  - GND -> GND
- Press KEY[0] to reset
- Press KEY[1] to start BIST manually
- Or send 'R' via UART to start

## LED Mapping

| LED | Signal |
|-----|--------|
| LEDR[0:4] | DUT output bits |
| LEDR[5] | BIST running (blink) |
| LEDR[6] | Any test failed |
| LEDR[7] | All tests passed |

## TODO

- [ ] Fill in correct expected values in `{mod.name}_bist.sv`
- [ ] Add IC-specific test groups (Groups 4+)
- [ ] Create golden model for cross-verification
- [ ] Verify on actual hardware
"""


# ============================================================================
# Copy UART modules
# ============================================================================

def copy_uart_modules(output_dir: str):
    """Copy uart_tx.sv and uart_rx.sv to output directory."""
    script_dir = Path(__file__).resolve().parent
    # Look for UART modules in known locations. Override search root via
    # VIBE_IC_FPGA_COMMON_RTL env var when running outside the bundled tree.
    search_paths = [
        script_dir.parent / "fpga_verification" / "common_rtl",
        script_dir.parent.parent / "fpga_verification" / "common_rtl",
    ]
    env_override = os.environ.get("VIBE_IC_FPGA_COMMON_RTL")
    if env_override:
        search_paths.insert(0, Path(env_override))

    for uart_file in ["uart_tx.sv", "uart_rx.sv"]:
        found = False
        for sp in search_paths:
            src = sp / uart_file
            if src.exists():
                dst = Path(output_dir) / uart_file
                if not dst.exists():
                    import shutil
                    shutil.copy2(str(src), str(dst))
                    print(f"  Copied: {uart_file}")
                found = True
                break
        if not found:
            print(f"  WARNING: {uart_file} not found in search paths, "
                  f"you'll need to provide it manually.")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="FPGA Test Harness Template Generator for DE10-Nano",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
    python3 fpga_harness_gen.py \\
        --rtl ic_projects_v2/ic_001_CD4013B/phase2_design/rtl/cd4013b.sv \\
        --output /tmp/test_harness/
        """,
    )
    parser.add_argument('--rtl', required=True, help='Path to IC RTL file (.sv)')
    parser.add_argument('--output', required=True, help='Output directory')
    parser.add_argument('--quiet', action='store_true', help='Suppress info output')
    args = parser.parse_args()

    # Validate input
    if not os.path.isfile(args.rtl):
        print(f"ERROR: RTL file not found: {args.rtl}")
        sys.exit(1)

    # Parse RTL
    if not args.quiet:
        print(f"\n  FPGA Harness Generator")
        print(f"  {'=' * 50}")
        print(f"  RTL: {args.rtl}")

    mod = parse_sv_module(args.rtl)

    if not args.quiet:
        print(f"  Module: {mod.name}")
        print(f"  Ports: {len(mod.ports)} ({len(mod.inputs)} in, "
              f"{len(mod.outputs)} out, {len(mod.inouts)} inout)")
        print(f"  Clock: {mod.clock_port or 'not detected'}")
        print(f"  Reset: {mod.reset_port or 'not detected'} "
              f"({'active-low' if mod.reset_active_low else 'active-high'})")
        print(f"  Input width: {mod.input_width} bits")
        print(f"  Output width: {mod.output_width} bits")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Compute relative path from output dir to RTL file
    rtl_abs = os.path.abspath(args.rtl)
    out_abs = os.path.abspath(args.output)
    try:
        rtl_rel = os.path.relpath(rtl_abs, out_abs)
    except ValueError:
        rtl_rel = rtl_abs

    # Generate files
    files = {
        f"{mod.name}_bist.sv": gen_bist_sv(mod),
        f"{mod.name}_fpga_top.sv": gen_fpga_top_sv(mod),
        f"{mod.name}_fpga.qsf": gen_qsf(mod, rtl_rel),
        f"{mod.name}_fpga.qpf": gen_qpf(mod),
        f"{mod.name}_fpga.sdc": gen_sdc(mod),
        "fpga_test.py": gen_fpga_test_py(mod),
        "README.md": gen_readme(mod),
    }

    for fname, content in files.items():
        fpath = os.path.join(args.output, fname)
        with open(fpath, 'w') as f:
            f.write(content)
        if not args.quiet:
            print(f"  Generated: {fname}")

    # Copy UART modules
    copy_uart_modules(args.output)

    if not args.quiet:
        print(f"\n  Output: {args.output}")
        print(f"  Total files: {len(files) + 2} (including UART modules)")
        print(f"\n  Next steps:")
        print(f"    1. Edit {mod.name}_bist.sv to fill in expected outputs (tv_exp)")
        print(f"    2. quartus_sh --flow compile {mod.name}_fpga")
        print(f"    3. python3 fpga_test.py --port /dev/ttyUSB0 --auto")
        print()

    return mod


if __name__ == '__main__':
    main()
