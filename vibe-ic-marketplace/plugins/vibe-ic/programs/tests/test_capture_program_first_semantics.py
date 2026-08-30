"""Post-blind-run capture regressions for reusable Program First emitters.

These fixtures encode only prompt-visible contracts.  They do not import the
RTLLM dataset, golden RTL, hidden testbenches, or scorer output.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _progress_run as progress  # noqa: E402

# MODULE-LEVEL, and that is the whole point rather than a style preference.
# `test_tool_gate_opens_when_the_tool_is_present` derives its population by
# scanning this directory for `_HA(VE|S)_*` module constants and then proves,
# per gate, that it is SHUT under `which -> None` and OPEN under `which -> path`.
# A skip written as an inline `shutil.which(...)` inside the decorator is
# invisible to that scan: measured on this tree, the register ran 212 green
# while these four gates sat outside its population entirely. A gate nothing
# proves can open is the silenced test that register exists to catch.
_HAVE_IVERILOG = bool(shutil.which("iverilog"))
_HAVE_TOOLS = bool(shutil.which("iverilog") and shutil.which("vvp"))
import arith_ext_synth as arith_ext  # noqa: E402
import arithmetic_synth as arithmetic  # noqa: E402
import canonical_primitive_synth as canonical  # noqa: E402
import counter_advanced_synth as counters  # noqa: E402
import lfsr_synth as lfsr  # noqa: E402
import memory_array_synth as memory  # noqa: E402


def test_captured_templates_preserve_prompt_visible_architecture():
    odd = canonical.emit_rtl("odd_clock_divider")
    assert "clk_div1 <= 1'b1" in odd
    assert "clk_div1 <= (cnt1 < (NUM_DIV / 2))" in odd
    assert "clk_div2 <= (cnt2 < (NUM_DIV / 2))" in odd
    assert "cnt1 + 32'd1) <" not in odd
    assert "cnt2 + 32'd1) <" not in odd

    pulse = canonical.emit_rtl("pulse_detect_0to1to0")
    assert "output reg data_out" in pulse
    assert "data_out <= ~data_in" in pulse
    assert "assign data_out" not in pulse

    serial = canonical.emit_rtl("serial_to_parallel_8")
    assert "output_pending" in serial
    assert "else if (output_pending)" in serial
    assert "if (din_valid)" in serial

    fifo = canonical.emit_rtl("async_gray_fifo")
    assert "wptr      <= bin2gray(waddr_bin)" in fifo
    assert "rptr      <= bin2gray(raddr_bin)" in fifo
    assert "wptr_next" not in fifo
    assert "rptr_next" not in fifo

    pipe = canonical.emit_rtl("pipelined_unsigned_multiplier_8")
    assert "assign mul_en_out = mul_en_out_reg[2]" in pipe
    assert "assign mul_out = mul_en_out ? mul_out_reg : 'd0" in pipe
    assert "output reg              mul_en_out" not in pipe

    barrel = canonical.emit_rtl("barrel_shifter_right_8")
    assert "module mux2X1" in barrel
    assert barrel.count("mux2X1 u_shift_") == 3
    assert "for (i = 0; i < 8; i = i + 1)" in barrel

    traffic = canonical.emit_rtl("traffic_light_fsm")
    assert traffic.count("if (cnt == 8'd3)") == 3
    assert "pass_request && green && cnt > 8'd10" in traffic


def test_arithmetic_capture_emits_stated_structure_not_operator_shortcuts():
    ripple = arith_ext.synth(
        "Implement an 8-bit adder using a series of bit-level full adders.",
        [("a", 8), ("b", 8), ("cin", 1)],
        [("sum", 8), ("cout", 1)], "adder_generic")
    assert "adder_generic_full_adder" in ripple
    assert "for (i=0; i<8" in ripple
    assert "assign {cout, sum}" not in ripple

    block = arith_ext.synth(
        "Implement a 16-bit adder. Design a small bit-width adder (8-bit adder), "
        "which will be instantiated multiple times.",
        [("a", 16), ("b", 16), ("Cin", 1)],
        [("y", 16), ("Co", 1)], "adder_hier")
    assert "module adder_hier_block8" in block
    assert "for (j=0; j<2" in block

    shift_add = arithmetic._emit_mult_comb({
        "a": "A", "b": "B", "prod": "product", "aw": 8, "bw": 8,
        "pw": 16, "signed": False, "shift_add": True,
        "ins": [("A", 8), ("B", 8)], "outs": [("product", 16)]}, "mult")
    assert "for (bit_index = 0; bit_index < 8" in shift_add
    assert "assign product = A * B" not in shift_add

    sequential = arithmetic._emit_mult_seq_done({
        "clk": "clk", "rst": "rst_n", "rst_active_high": False,
        "start": "start", "done": "done", "a": "ain", "b": "bin",
        "prod": "yout", "aw": 16, "bw": 16, "pw": 32,
        "bound": 17, "raise_at": 16, "clear_at": 17,
        "ins": [("clk", 1), ("rst_n", 1), ("start", 1),
                ("ain", 16), ("bin", 16)],
        "outs": [("yout", 32), ("done", 1)]}, "seq_mult")
    assert "areg[i-1]" in sequential and "breg" in sequential
    assert "ain * bin" not in sequential

    booth = arithmetic._emit_mult_seq_rdy({
        "clk": "clk", "rst": "reset", "a": "a", "b": "b",
        "prod": "p", "rdy": "rdy", "aw": 8, "bw": 8, "pw": 16,
        "raise_at": 16, "bound": 16, "radix4": True,
        "ins": [("clk", 1), ("reset", 1), ("a", 8), ("b", 8)],
        "outs": [("p", 16), ("rdy", 1)]}, "booth_mult")
    assert "case (multiplier[2:0])" in booth
    assert "multiplicand <<< 2" in booth
    assert "$signed(a) * $signed(b)" not in booth

    piped = arithmetic._emit_mult_pipe_plain({
        "clk": "clk", "rst": "rst_n", "a": "mul_a", "b": "mul_b",
        "prod": "mul_out", "aw": 4, "bw": 4, "pw": 8, "stages": 2,
        "param_name": "size", "param_default": 4,
        "ins": [], "outs": []}, "pipe_mult")
    assert "gi<size" in piped and "sum_chain[size]" in piped
    assert "partial_product[3]" not in piped

    fixed_sub = arithmetic._emit_fixed_sub(
        {"a": "a", "b": "b", "c": "c"}, "fixed_sub")
    assert "res[N-2:0] = a[N-2:0] + b[N-2:0]" in fixed_sub
    assert "res[N-1] = (res[N-2:0] == 0) ? 1'b0" in fixed_sub

    alu = arithmetic._emit_alu({
        "a": "a", "b": "b", "ctl": "aluc", "r": "r", "rw": 32,
        "opcodes": {"ADD": "6'b100000", "ADDU": "6'b100001",
                    "SUB": "6'b100010", "SUBU": "6'b100011",
                    "SLT": "6'b101010", "SLTU": "6'b101011"},
        "ins": [("a", 32), ("b", 32), ("aluc", 6)],
        "outs": [("r", 32), ("zero", 1), ("carry", 1),
                 ("negative", 1), ("overflow", 1), ("flag", 1)]}, "alu")
    assert "reg [32:0] res" in alu
    assert "assign carry = res[32]" in alu
    assert "assign overflow =" in alu
    assert "? 1'b1 : 1'bz" in alu
    assert "default: res = {33{1'bz}}" in alu


_FIXED_POINT_ADD_PROMPT = r"""
Implement a fixed-point adder.
Module name:
    fixed_point_adder
Input ports:
    a [N-1:0]: first sign-magnitude fixed-point operand.
    b [N-1:0]: second sign-magnitude fixed-point operand.
Output ports:
    c [N-1:0]: sign-magnitude sum.
Parameter:
    Q = 4
    N = 8
If a and b have the same sign, their absolute values are added. If their signs
are different, the smaller absolute value is subtracted from the larger one and
the result takes the sign of the larger absolute value.
"""


def test_fixed_point_adder_operation_is_bound_to_the_declared_purpose():
    """An adder's opposite-sign branch says 'subtracted'; that does not make
    the top-level task a subtractor."""
    spec = arithmetic.recognize(_FIXED_POINT_ADD_PROMPT)
    assert spec is not None and spec["op"] == "fixed_add"
    rtl = arithmetic.synth(_FIXED_POINT_ADD_PROMPT, "fixed_point_adder")
    assert rtl is not None
    assert "res[N-2:0] = a[N-2:0] + b[N-2:0]" in rtl
    assert "res[N-2:0] = a[N-2:0] - b[N-2:0]" in rtl


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="Icarus Verilog is required")
def test_fixed_point_adder_capture_passes_prompt_derived_sign_cases(tmp_path):
    rtl = arithmetic.synth(_FIXED_POINT_ADD_PROMPT, "fixed_point_adder")
    dut = tmp_path / "fixed_point_adder.sv"
    tb = tmp_path / "tb.sv"
    simv = tmp_path / "simv"
    dut.write_text(rtl)
    tb.write_text(r"""
module tb;
  reg [7:0] a, b; wire [7:0] c;
  fixed_point_adder #(.Q(4), .N(8)) d(.a(a), .b(b), .c(c));
  initial begin
    a=8'h03; b=8'h02; #1;
    if (c !== 8'h05) $fatal(1, "same-sign addition failed: %h", c);
    a=8'h03; b=8'h82; #1;
    if (c !== 8'h01) $fatal(1, "opposite-sign subtraction failed: %h", c);
    a=8'h02; b=8'h83; #1;
    if (c !== 8'h81) $fatal(1, "larger-magnitude sign failed: %h", c);
    $display("PASS fixed-point adder capture");
    $finish;
  end
endmodule
""")
    comp = progress.run(
        ["iverilog", "-g2012", "-o", str(simv), str(dut), str(tb)],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert comp.returncode == 0, comp.stderr
    run = progress.run(["vvp", str(simv)], capture_output=True, text=True,
                       cwd=str(tmp_path))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS fixed-point adder capture" in run.stdout


def test_contract_capture_preserves_parameters_and_reset_timing():
    ram = memory._try_ram(
        "Dual-port RAM. WIDTH = 6; DEPTH = 8. Register array. "
        "Synchronous posedge read_data register with second always block.",
        "generic_ram",
        [("clk", 1), ("rst_n", 1), ("write_en", 1), ("write_addr", 3),
         ("write_data", 6), ("read_en", 1), ("read_addr", 3)],
        [("read_data", 6)])
    assert "parameter WIDTH = 6" in ram and "parameter DEPTH = 8" in ram
    assert "[$clog2(DEPTH)-1:0]" in ram and "RAM [0:DEPTH-1]" in ram

    lfsr_rtl = lfsr._dia_lfsr(
        """A 4-bit Linear Feedback Shift Register (LFSR).
Input ports:
 clk: clock
 rst: active high reset
Output ports:
 out [3:0]: state
The feedback XORs out[3] and out[2], then is inverted. The register is shifted
left and inserts feedback at the LSB. On the rising edge of clk, if rst is high,
initialize the register to zero.
""", "generic_lfsr")
    assert "always @(posedge clk)" in lfsr_rtl
    assert "or posedge rst" not in lfsr_rtl

    updown = counters._dia_up_down(
        "A 16-bit up/down counter. up_down = 1 increments; up_down = 0 "
        "decrements. The module uses a synchronous process triggered by the "
        "rising edge of clk.",
        [("clk", 1), ("reset", 1), ("up_down", 1)],
        [("count", 16)], "generic_counter")
    assert "always @(posedge clk)" in updown
    assert "or posedge reset" not in updown


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="Icarus Verilog is required")
def test_captured_multiplier_algorithms_compute_prompt_visible_products(tmp_path):
    """Exercise the captured algorithms without an RTLLM oracle or fixture."""
    cases = []

    booth = arithmetic._emit_mult_seq_rdy({
        "clk": "clk", "rst": "reset", "a": "a", "b": "b",
        "prod": "p", "rdy": "rdy", "aw": 8, "bw": 8, "pw": 16,
        "raise_at": 16, "bound": 16, "radix4": True,
        "ins": [("clk", 1), ("reset", 1), ("a", 8), ("b", 8)],
        "outs": [("p", 16), ("rdy", 1)]}, "booth_mult")
    cases.append(("booth", booth, r"""
module tb;
  reg clk=0, reset=0; reg signed [7:0] a, b;
  wire signed [15:0] p; wire rdy;
  booth_mult d(.clk(clk),.reset(reset),.a(a),.b(b),.p(p),.rdy(rdy));
  always #1 clk=~clk;
  initial begin
    a=7; b=-3; reset=1; #3; reset=0; wait(rdy); #1;
    if (p !== -16'sd21) begin $display("FAIL booth p=%0d",p); $fatal(1); end
    $display("PASS booth"); $finish;
  end
endmodule
"""))

    sequential = arithmetic._emit_mult_seq_done({
        "clk": "clk", "rst": "rst_n", "rst_active_high": False,
        "start": "start", "done": "done", "a": "ain", "b": "bin",
        "prod": "yout", "aw": 16, "bw": 16, "pw": 32,
        "bound": 17, "raise_at": 16, "clear_at": 17,
        "ins": [("clk", 1), ("rst_n", 1), ("start", 1),
                ("ain", 16), ("bin", 16)],
        "outs": [("yout", 32), ("done", 1)]}, "seq_mult")
    cases.append(("sequential", sequential, r"""
module tb;
  reg clk=0, rst_n=0, start=0; reg [15:0] ain=13, bin=17;
  wire [31:0] yout; wire done;
  seq_mult d(.clk(clk),.rst_n(rst_n),.start(start),.ain(ain),.bin(bin),
             .yout(yout),.done(done));
  always #1 clk=~clk;
  initial begin
    #3; rst_n=1; start=1; wait(done); #1;
    if (yout !== 32'd221) begin $display("FAIL seq yout=%0d",yout); $fatal(1); end
    $display("PASS sequential"); $finish;
  end
endmodule
"""))

    pipeline = arithmetic._emit_mult_pipe_plain({
        "clk": "clk", "rst": "rst_n", "a": "mul_a", "b": "mul_b",
        "prod": "mul_out", "aw": 4, "bw": 4, "pw": 8, "stages": 2,
        "param_name": "size", "param_default": 4,
        "ins": [], "outs": []}, "pipe_mult")
    cases.append(("pipeline", pipeline, r"""
module tb;
  reg clk=0, rst_n=0; reg [4:0] mul_a=19, mul_b=23; wire [9:0] mul_out;
  pipe_mult #(.size(5)) d(.clk(clk),.rst_n(rst_n),.mul_a(mul_a),
                           .mul_b(mul_b),.mul_out(mul_out));
  always #1 clk=~clk;
  initial begin
    #3; rst_n=1; repeat(3) @(posedge clk); #1;
    if (mul_out !== 10'd437) begin $display("FAIL pipe=%0d",mul_out); $fatal(1); end
    $display("PASS pipeline size=5"); $finish;
  end
endmodule
"""))

    for name, rtl_text, tb_text in cases:
        case_dir = tmp_path / name
        case_dir.mkdir()
        rtl = case_dir / "dut.v"
        tb = case_dir / "tb.v"
        out = case_dir / "simv"
        rtl.write_text(rtl_text)
        tb.write_text(tb_text)
        comp = progress.run(
            [shutil.which("iverilog"), "-g2012", "-s", "tb", "-o", str(out),
             str(rtl), str(tb)], capture_output=True, text=True)
        assert comp.returncode == 0, f"{name}: {comp.stderr}"
        sim = progress.run([shutil.which("vvp"), str(out)],
                           capture_output=True, text=True)
        assert sim.returncode == 0, f"{name}: {sim.stdout}{sim.stderr}"
        assert f"PASS {name}" in sim.stdout


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="Icarus Verilog is required")
def test_pulse_output_is_clocked_and_matches_disclosed_trace(tmp_path):
    rtl = tmp_path / "pulse_detect.v"
    rtl.write_text(canonical.emit_rtl("pulse_detect_0to1to0"))
    tb = tmp_path / "tb.v"
    tb.write_text(r"""
module tb;
  reg clk=0, rst_n=0, data_in=0;
  wire data_out;
  reg [4:0] got;
  reg [4:0] stim=5'b01010;
  integer i;
  pulse_detect dut(.clk(clk),.rst_n(rst_n),.data_in(data_in),.data_out(data_out));
  always #5 clk=~clk;
  initial begin
    #2; rst_n=0; #6; rst_n=1;
    for (i=0; i<5; i=i+1) begin
      data_in = stim[4-i];
      @(posedge clk); #1; got[4-i]=data_out;
    end
    if (got !== 5'b00101) begin $display("FAIL got=%b",got); $fatal; end
    $display("PASS pulse trace=%b",got); $finish;
  end
endmodule
""")
    out = tmp_path / "simv"
    comp = progress.run([shutil.which("iverilog"), "-g2012", "-s", "tb",
                         "-o", str(out), str(rtl), str(tb)],
                        capture_output=True, text=True)
    assert comp.returncode == 0, comp.stderr
    sim = progress.run([shutil.which("vvp"), str(out)],
                       capture_output=True, text=True)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    assert "PASS pulse trace=00101" in sim.stdout


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="Icarus Verilog is required")
def test_odd_divider_current_state_decode_preserves_first_half_phase(tmp_path):
    rtl = tmp_path / "freq_divbyodd.v"
    rtl.write_text(canonical.emit_rtl("odd_clock_divider"))
    tb = tmp_path / "tb.v"
    tb.write_text(r"""
module tb;
  reg clk=1, rst_n=0;
  wire clk_div;
  integer i;
  reg [31:0] prior;
  freq_divbyodd #(.NUM_DIV(5)) dut(.clk(clk),.rst_n(rst_n),.clk_div(clk_div));
  always #5 clk=~clk;
  initial begin
    #12 rst_n=1;
    for (i=0; i<8; i=i+1) begin
      @(negedge clk); #1; prior = dut.cnt1;
      @(posedge clk); #1;
      if (dut.clk_div1 !== (prior < (5/2))) begin
        $display("FAIL posedge prior=%0d got=%b",prior,dut.clk_div1);
        $fatal;
      end
    end
    for (i=0; i<8; i=i+1) begin
      @(posedge clk); #1; prior = dut.cnt2;
      @(negedge clk); #1;
      if (dut.clk_div2 !== (prior < (5/2))) begin
        $display("FAIL negedge prior=%0d got=%b",prior,dut.clk_div2);
        $fatal;
      end
    end
    $display("PASS odd-divider-current-state-phase"); $finish;
  end
endmodule
""")
    out = tmp_path / "simv"
    comp = progress.run([shutil.which("iverilog"), "-g2012", "-s", "tb",
                         "-o", str(out), str(rtl), str(tb)],
                        capture_output=True, text=True)
    assert comp.returncode == 0, comp.stderr
    sim = progress.run([shutil.which("vvp"), str(out)],
                       capture_output=True, text=True)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    assert "PASS odd-divider-current-state-phase" in sim.stdout


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="Icarus Verilog is required")
def test_fifo_gray_pointer_registers_current_binary_position(tmp_path):
    rtl = tmp_path / "asyn_fifo.v"
    rtl.write_text(canonical.emit_rtl("async_gray_fifo"))
    tb = tmp_path / "tb.v"
    tb.write_text(r"""
module tb;
  reg wclk=0, rclk=0, wrstn=0, rrstn=0, winc=0, rinc=0;
  reg [7:0] wdata=0;
  wire wfull, rempty; wire [7:0] rdata;
  asyn_fifo #(.WIDTH(8),.DEPTH(16)) dut(
    .wclk(wclk),.rclk(rclk),.wrstn(wrstn),.rrstn(rrstn),
    .winc(winc),.rinc(rinc),.wdata(wdata),.wfull(wfull),
    .rempty(rempty),.rdata(rdata));
  always #5 wclk=~wclk;
  always #17 rclk=~rclk;
  initial begin
    #2; wrstn=0; rrstn=0; #40;
    @(negedge wclk); wrstn=1; rrstn=1; winc=1; wdata=8'h11;
    @(posedge wclk); #1;
    if (dut.waddr_bin !== 5'd1 || dut.wptr !== 5'd0) begin
      $display("FAIL first-position bin=%0d gray=%0d",dut.waddr_bin,dut.wptr);
      $fatal;
    end
    @(negedge wclk); wdata=8'h22; @(posedge wclk); #1;
    if (dut.waddr_bin !== 5'd2 || dut.wptr !== 5'd1) begin
      $display("FAIL second-position bin=%0d gray=%0d",dut.waddr_bin,dut.wptr);
      $fatal;
    end
    $display("PASS registered-current-position-gray"); $finish;
  end
endmodule
""")
    out = tmp_path / "simv"
    comp = progress.run([shutil.which("iverilog"), "-g2012", "-s", "tb",
                         "-o", str(out), str(rtl), str(tb)],
                        capture_output=True, text=True)
    assert comp.returncode == 0, comp.stderr
    sim = progress.run([shutil.which("vvp"), str(out)],
                       capture_output=True, text=True)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    assert "PASS registered-current-position-gray" in sim.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG,
                    reason="Icarus Verilog is required")
@pytest.mark.parametrize("shape", [
    "odd_clock_divider",
    "pulse_detect_0to1to0",
    "serial_to_parallel_8",
    "traffic_light_fsm",
    "async_gray_fifo",
    "pipelined_unsigned_multiplier_8",
    "barrel_shifter_right_8",
])
def test_captured_template_elaborates(shape, tmp_path):
    rtl = tmp_path / f"{shape}.v"
    rtl.write_text(canonical.emit_rtl(shape))
    out = tmp_path / "simv"
    comp = progress.run([shutil.which("iverilog"), "-g2012", "-o", str(out),
                         str(rtl)], capture_output=True, text=True)
    assert comp.returncode == 0, comp.stderr
