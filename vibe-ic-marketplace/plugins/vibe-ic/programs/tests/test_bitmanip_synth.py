#!/usr/bin/env python3
"""test_bitmanip_synth.py — positives + §4.05 negatives for the CVDP
BIT-MANIPULATION solver (popcount / Hamming-distance, CLZ/CTZ, find-first/last,
bit-reverse, selective/segmented reverse, byte-swap, thermometer<->binary).

The solver is chip-AGNOSTIC: it keys on STATED structure (the function name in
prose, the stated width / direction, a stated parameter default), never on a
design id. These tests pin:
  * POSITIVES (functionally host-verified via iverilog when available):
      - whole-vector bit-reverse, parameterized Hamming-distance popcount(a^b),
        selective/segmented bit-reverse — the three REAL CVDP dataset shapes;
      - the general emitters popcount-weight / CLZ / CTZ / find-first / find-last
        / byte-swap / thermometer<->binary all EMIT and SIMULATE correctly
        (proving the solver is GENERAL, not overfit to the three dataset ids).
  * §4.05 NEGATIVES — a clocked stream set-bit accumulator SKIPs; a pipelined
    first-bit decoder SKIPs; an UNSTATED CLZ-vs-CTZ direction SKIPs; an UNSTATED
    data-path width SKIPs; a composite operation-mode wrapper SKIPs; a deferred
    special-mapping (gray/BCD/one-hot-decoder) SKIPs.
  * CHIP-AGNOSTIC — the emit is independent of the module name (rename invariance)
    and the solver source hard-codes no design-id token.

The iverilog functional checks are GATED on the iverilog binary; the structural /
§4.05 / chip-agnostic checks run unconditionally.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import bitmanip_synth as B  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None

DATASET = corpus_path("_extbench/cvdp_open_v110/"
                      "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# helpers                                                                       #
# --------------------------------------------------------------------------- #
def _make_record(top, prompt, cocotb_test="", rtl_path=None):
    rtl_path = rtl_path or f"rtl/{top}.sv"
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"VERILOG_SOURCES = /code/{rtl_path}\n"
                f"TOPLEVEL        = {top}\n"
                f"MODULE          = test_{top}\n"
            ),
            f"src/test_{top}.py": cocotb_test,
        }},
    }


def _iverilog_ok(rtl: str, top: str, tb: str) -> str:
    d = tempfile.mkdtemp()
    try:
        rp = os.path.join(d, f"{top}.sv"); Path(rp).write_text(rtl)
        tp = os.path.join(d, "tb.sv"); Path(tp).write_text(tb)
        out = os.path.join(d, "a.out")
        c = subprocess.run(["iverilog", "-g2012", "-o", out, tp, rp],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}\n---RTL---\n{rtl}"
        r = subprocess.run(["vvp", out], capture_output=True, text=True)
        return r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _find_dataset_record(rec_id):
    if not DATASET.exists():
        pytest.skip("CVDP dataset not present")
    for l in DATASET.open():
        r = json.loads(l)
        if r["id"] == rec_id:
            return r
    pytest.skip(f"record {rec_id} not in dataset")


# --------------------------------------------------------------------------- #
# prose fixtures (paraphrased general shapes; NO design-name dependence)        #
# --------------------------------------------------------------------------- #
P_BITREV = """Design a combinational module to reverse the bits of a 16-bit input.
The least significant bit (LSB) of the input becomes the most significant bit
(MSB) of the output, and so on. The design must be purely combinational.
Inputs:
- d_in [15:0]: 16-bit input
Outputs:
- d_out [15:0]: bit-reversed 16-bit output"""

P_POPCOUNT = """Design a purely combinational module that outputs the population
count (the number of set bits) of an 8-bit input.
Inputs:
- data_in [7:0]: 8-bit input vector
Outputs:
- count [3:0]: number of set bits in data_in"""

P_DISTANCE = """Design a parameterized combinational module that computes the
Hamming distance between two input vectors of equal width — the number of bit
positions where the two inputs differ. **WIDTH** has a default value of 6.
Inputs:
- a [WIDTH-1:0]: first input vector
- b [WIDTH-1:0]: second input vector
Outputs:
- diff_count [COUNT_WIDTH-1:0]: the number of differing bits. COUNT_WIDTH is the
  width required to represent the maximum possible Hamming distance."""

P_CLZ = """Design a purely combinational module that counts the number of leading
zeros in an 8-bit input, scanning from the most-significant bit.
Inputs:
- in_vec [7:0]: 8-bit input
Outputs:
- lead_zeros [3:0]: count of leading zero bits"""

P_CTZ = """Design a purely combinational module that counts the number of trailing
zeros in an 8-bit input, scanning from the least-significant bit.
Inputs:
- in_vec [7:0]: 8-bit input
Outputs:
- trail_zeros [3:0]: count of trailing zero bits"""

P_FIND_FIRST = """Design a combinational module that finds the index of the first
(lowest) set bit in an 8-bit input and asserts a valid flag.
Inputs:
- vec [7:0]: 8-bit input
Outputs:
- idx [2:0]: index of the lowest set bit
- valid: high when any bit is set"""

P_FIND_LAST = """Design a combinational module that finds the index of the last
(highest) set bit — the most-significant set bit — in an 8-bit input and asserts
a found flag.
Inputs:
- vec [7:0]: 8-bit input
Outputs:
- idx [2:0]: index of the highest set bit
- found: high when any bit is set"""

P_BYTESWAP = """Design a purely combinational module that performs a byte-swap
(endian reverse) on a 32-bit input: the order of the four bytes is reversed.
Inputs:
- in_word [31:0]: 32-bit input
Outputs:
- out_word [31:0]: byte-reversed output"""

P_THERMO2BIN = """Design a purely combinational module that converts an 8-bit
thermometer code into its binary count value (the number of set bits).
Inputs:
- thermo [7:0]: 8-bit thermometer code input
Outputs:
- value [3:0]: binary count output"""

P_BIN2THERMO = """Design a purely combinational module that converts a binary
count value into an 8-bit thermometer code, where the k low-order bits are set.
Inputs:
- value [3:0]: binary count input
Outputs:
- thermo [7:0]: thermometer code output"""

# §4.05 negatives
P_SEQ_ACCUM = """Design a Set Bit Calculator that counts the number of 1 bits in a
bitstream received on the positive edge of a clock when a ready signal is asserted.
The count saturates and resets when ready re-asserts.
Inputs:
- i_bit_in: single-bit stream input
- i_clk: clock
- i_ready: enable
- i_rst_n: active-low asynchronous reset
Outputs:
- o_set_bit_count [7:0]: total count of 1 bits since reset"""

P_PIPELINED_FFB = """A first-bit decoder that returns the index of the lowest set
bit in a vector using pipelined stages. The number of pipeline registers is
PlRegs_g. Outputs are registered on the rising clock edge.
Inputs:
- In_Data [31:0]: input vector
- clk: clock
Outputs:
- Out_FirstBit [4:0]: index of the first set bit
- Out_Found: any set bit
- Out_Valid: output valid"""

P_UNSTATED_DIR = """Design a combinational module that counts zeros in an 8-bit
input.
Inputs:
- in_vec [7:0]: 8-bit input
Outputs:
- zcount [3:0]: count of zero bits"""

P_UNSTATED_WIDTH = """Design a combinational popcount that outputs the number of
set bits in the input.
Inputs:
- data_in: input vector
Outputs:
- count: number of set bits"""

P_OPMODE_WRAPPER = """Enhance the swizzler with an operation_mode interface
selecting passthrough, reverse, rotate, and invert on the swizzled data, with
pipeline registers for swizzle and output stages.
Inputs:
- data_in [63:0]: input
- operation_mode [2:0]: transform selector
- clk: clock
Outputs:
- data_out [63:0]: output"""

P_GRAY_DEFER = """Design a combinational module that reverses the bits of a gray
coded 8-bit input.
Inputs:
- g_in [7:0]: gray-coded input
Outputs:
- g_out [7:0]: output"""


# =========================================================================== #
# POSITIVES — structural emit                                                   #
# =========================================================================== #
def test_bitreverse_emits():
    rtl = B.synth(P_BITREV, top="rev16")
    assert rtl is not None and "module rev16" in rtl
    assert "in[15-_i]" in rtl.replace("d_", "in")  # reversal index present
    assert "always @(posedge" not in rtl  # combinational only


def test_distance_emits_parameterized():
    rtl = B.synth(P_DISTANCE, top="hdist")
    assert rtl is not None and "module hdist" in rtl
    assert "parameter WIDTH = 6" in rtl
    assert "COUNT_WIDTH = $clog2(WIDTH+1)" in rtl
    assert "a ^ b" in rtl


def test_popcount_weight_emits():
    rtl = B.synth(P_POPCOUNT, top="pcnt")
    assert rtl is not None and "module pcnt" in rtl
    assert "data_in[_i]" in rtl
    assert "always @(posedge" not in rtl


def test_clz_emits():
    rtl = B.synth(P_CLZ, top="clz")
    assert rtl is not None and "module clz" in rtl
    assert "in_vec[(7 - _i)]" in rtl  # leading == scan from MSB


def test_ctz_emits():
    rtl = B.synth(P_CTZ, top="ctz")
    assert rtl is not None and "module ctz" in rtl
    assert "in_vec[_i]" in rtl  # trailing == scan from LSB


def test_find_first_emits_with_valid():
    rtl = B.synth(P_FIND_FIRST, top="ffb")
    assert rtl is not None and "module ffb" in rtl
    assert "valid" in rtl and "_found" in rtl


def test_find_last_emits_with_found():
    rtl = B.synth(P_FIND_LAST, top="flb")
    assert rtl is not None and "module flb" in rtl
    assert "found" in rtl


def test_byteswap_emits():
    rtl = B.synth(P_BYTESWAP, top="bsw")
    assert rtl is not None and "module bsw" in rtl
    # four byte assignments, reversed order
    assert rtl.count("assign out_word[") == 4


def test_thermo2binary_emits():
    rtl = B.synth(P_THERMO2BIN, top="t2b")
    assert rtl is not None and "module t2b" in rtl
    assert "thermo[_i]" in rtl


def test_binary2thermo_emits():
    rtl = B.synth(P_BIN2THERMO, top="b2t")
    assert rtl is not None and "module b2t" in rtl
    assert "(_i < value)" in rtl


# =========================================================================== #
# POSITIVES — functional (iverilog)                                             #
# =========================================================================== #
@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_bitreverse_functional():
    rtl = B.synth(P_BITREV, top="rev16")
    tb = """module tb; reg [15:0] d; wire [15:0] o; rev16 dut(.d_in(d),.d_out(o));
integer k,i,f; reg [15:0] e; initial begin f=0;
 for(k=0;k<3000;k=k+1) begin d=$random;#1; e=0; for(i=0;i<16;i=i+1) e[i]=d[15-i]; if(o!==e) f=f+1; end
 d=16'h1;#1; if(o!==16'h8000) f=f+1;
 if(f==0) $display("RESULT 0"); else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "rev16", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("W", [3, 4, 6, 10])
def test_distance_functional(W):
    rtl = B.synth(P_DISTANCE, top="hdist")
    tb = f"""module tb; localparam W={W};
 reg [W-1:0] a,b; wire [$clog2(W+1)-1:0] c; hdist #(.WIDTH(W)) dut(.a(a),.b(b),.diff_count(c));
 integer k,i,e,f; reg [W-1:0] x; initial begin f=0;
 for(k=0;k<3000;k=k+1) begin a=$random;b=$random;#1; x=a^b; e=0; for(i=0;i<W;i=i+1) e=e+x[i];
  if(c!==e[$clog2(W+1)-1:0]) f=f+1; end
 if(f==0) $display("RESULT 0"); else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "hdist", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_popcount_weight_functional():
    rtl = B.synth(P_POPCOUNT, top="pcnt")
    tb = """module tb; reg [7:0] d; wire [3:0] c; pcnt dut(.data_in(d),.count(c));
integer k,i,e,f; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0; for(i=0;i<8;i=i+1) e=e+d[i];
 if(c!==e) f=f+1; end if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "pcnt", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_clz_functional():
    rtl = B.synth(P_CLZ, top="clz")
    tb = """module tb; reg [7:0] d; wire [3:0] c; clz dut(.in_vec(d),.lead_zeros(c));
integer k,i,e,f; reg dn; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0;dn=0;
 for(i=7;i>=0;i=i-1) if(!dn) begin if(d[i]) dn=1; else e=e+1; end if(c!==e) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "clz", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_ctz_functional():
    rtl = B.synth(P_CTZ, top="ctz")
    tb = """module tb; reg [7:0] d; wire [3:0] c; ctz dut(.in_vec(d),.trail_zeros(c));
integer k,i,e,f; reg dn; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0;dn=0;
 for(i=0;i<8;i=i+1) if(!dn) begin if(d[i]) dn=1; else e=e+1; end if(c!==e) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "ctz", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_find_first_functional():
    rtl = B.synth(P_FIND_FIRST, top="ffb")
    tb = """module tb; reg [7:0] d; wire [2:0] x; wire v; ffb dut(.vec(d),.idx(x),.valid(v));
integer k,i,e,ev,f; reg dn; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0;dn=0;ev=0;
 for(i=0;i<8;i=i+1) if(!dn&&d[i]) begin e=i;ev=1;dn=1; end
 if(v!==ev[0:0]) f=f+1; if(ev&&x!==e[2:0]) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "ffb", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_find_last_functional():
    rtl = B.synth(P_FIND_LAST, top="flb")
    tb = """module tb; reg [7:0] d; wire [2:0] x; wire v; flb dut(.vec(d),.idx(x),.found(v));
integer k,i,e,ev,f; reg dn; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0;dn=0;ev=0;
 for(i=7;i>=0;i=i-1) if(!dn&&d[i]) begin e=i;ev=1;dn=1; end
 if(v!==ev[0:0]) f=f+1; if(ev&&x!==e[2:0]) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "flb", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_byteswap_functional():
    rtl = B.synth(P_BYTESWAP, top="bsw")
    tb = """module tb; reg [31:0] d; wire [31:0] o; bsw dut(.in_word(d),.out_word(o));
integer k,f; reg [31:0] e; initial begin f=0; for(k=0;k<3000;k=k+1) begin d=$random;#1;
 e={d[7:0],d[15:8],d[23:16],d[31:24]}; if(o!==e) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "bsw", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_thermo2binary_functional():
    rtl = B.synth(P_THERMO2BIN, top="t2b")
    tb = """module tb; reg [7:0] d; wire [3:0] c; t2b dut(.thermo(d),.value(c));
integer k,i,e,f; initial begin f=0; for(k=0;k<256;k=k+1) begin d=k;#1; e=0; for(i=0;i<8;i=i+1) e=e+d[i];
 if(c!==e) f=f+1; end if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "t2b", tb)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_binary2thermo_functional():
    rtl = B.synth(P_BIN2THERMO, top="b2t")
    tb = """module tb; reg [3:0] d; wire [7:0] o; b2t dut(.value(d),.thermo(o));
integer k,i,f; reg [7:0] e; initial begin f=0; for(k=0;k<=8;k=k+1) begin d=k;#1; e=0;
 for(i=0;i<8;i=i+1) if(i<k) e[i]=1; if(o!==e) f=f+1; end
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
    assert "RESULT 0" in _iverilog_ok(rtl, "b2t", tb)


# =========================================================================== #
# §4.05 NEGATIVES — SKIP discipline                                             #
# =========================================================================== #
def test_clocked_stream_accumulator_skips():
    assert B.synth(P_SEQ_ACCUM, top="acc") is None


def test_pipelined_first_bit_decoder_skips():
    assert B.synth(P_PIPELINED_FFB, top="fbd") is None


def test_unstated_clz_ctz_direction_skips():
    # "counts zeros" with no leading/trailing direction -> ambiguous -> SKIP
    assert B.synth(P_UNSTATED_DIR, top="zc") is None


def test_unstated_width_skips():
    assert B.synth(P_UNSTATED_WIDTH, top="pc") is None


def test_operation_mode_wrapper_skips():
    assert B.synth(P_OPMODE_WRAPPER, top="sw") is None


def test_special_mapping_gray_defers():
    assert B.synth(P_GRAY_DEFER, top="g") is None


def test_find_first_without_valid_or_zero_default_skips():
    p = """Design a combinational module that outputs the index of the first
(lowest) set bit in an 8-bit input.
Inputs:
- vec [7:0]: 8-bit input
Outputs:
- idx [2:0]: index of the lowest set bit"""
    # no valid flag AND no stated all-zero default -> cannot pin the all-zero
    # output -> SKIP (no guessing).
    assert B.synth(p, top="ff") is None


# =========================================================================== #
# CHIP-AGNOSTIC                                                                  #
# =========================================================================== #
def test_emit_is_chip_agnostic_rename():
    # the SAME prose under two different top names yields the same RTL modulo the
    # module name — the solver keys on stated structure, not the name.
    a = B.synth(P_BITREV, top="alpha")
    b = B.synth(P_BITREV, top="beta")
    assert a and b
    assert a.replace("alpha", "X") == b.replace("beta", "X")


def test_no_designname_keys_in_source():
    src = (_PROG / "bitmanip_synth.py").read_text()
    for banned in ("cvdp_copilot", "reverse_bits", "nbit_swizzling",
                   "Bit_Difference_Counter", "set_bit_calculator",
                   "decode_firstbit", "swizzler"):
        assert banned not in src, f"design-name token {banned!r} leaked into solver"


# =========================================================================== #
# REAL DATASET — the three clean atomic bit-manip shapes EMIT; nothing else     #
# =========================================================================== #
def test_dataset_reverse_bits_emits_and_simulates():
    r = _find_dataset_record("cvdp_copilot_reverse_bits_0001")
    rtl = B.solve(r)
    assert rtl is not None and "module reverse_bits" in rtl
    if HAVE_IVERILOG:
        tb = """module tb; reg [31:0] d; wire [31:0] o; reverse_bits dut(.num_in(d),.num_out(o));
integer k,i,f; reg [31:0] e; initial begin f=0; for(k=0;k<3000;k=k+1) begin d=$random;#1;
 e=0; for(i=0;i<32;i=i+1) e[i]=d[31-i]; if(o!==e) f=f+1; end
 d=32'h1;#1; if(o!==32'h80000000) f=f+1;
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
        assert "RESULT 0" in _iverilog_ok(rtl, "reverse_bits", tb)


def test_dataset_hamming_distance_emits_and_simulates():
    r = _find_dataset_record("cvdp_copilot_word_reducer_0008")
    rtl = B.solve(r)
    assert rtl is not None and "module Bit_Difference_Counter" in rtl
    # COUNT_WIDTH is DERIVED from the function (popcount needs $clog2(N+1) bits) +
    # the prompt-stated BIT_WIDTH param — NOT read from the (now-stripped) cocotb
    # harness's dut.COUNT_WIDTH nor the golden RTL. The prose states the relationship
    # ("the width required to represent the maximum possible number of differing
    # bits"), so this is a compliant recovery, not a harness read.
    assert "COUNT_WIDTH = $clog2(BIT_WIDTH+1)" in rtl
    if HAVE_IVERILOG:
        for W in (4, 10, 3, 20):  # the runner's BIT_WIDTH set
            tb = f"""module tb; localparam BW={W};
 reg [BW-1:0] a,b; wire [$clog2(BW+1)-1:0] c;
 Bit_Difference_Counter #(.BIT_WIDTH(BW)) dut(.input_A(a),.input_B(b),.bit_difference_count(c));
 integer k,i,e,f; reg [BW-1:0] x; initial begin f=0;
 for(k=0;k<2000;k=k+1) begin a=$random;b=$random;#1; x=a^b; e=0; for(i=0;i<BW;i=i+1) e=e+x[i];
  if(c!==e[$clog2(BW+1)-1:0]) f=f+1; end
 a={{BW{{1'b1}}}};b={{BW{{1'b0}}}};#1; if(c!==BW) f=f+1;
 if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule"""
            assert "RESULT 0" in _iverilog_ok(rtl, "Bit_Difference_Counter", tb), f"W={W}"


def test_dataset_nbit_swizzling_emits_and_simulates():
    r = _find_dataset_record("cvdp_copilot_nbit_swizzling_0001")
    rtl = B.solve(r)
    assert rtl is not None and "module nbit_swizzling" in rtl
    assert "parameter DATA_WIDTH = 64" in rtl
    if HAVE_IVERILOG:
        # the exact cocotb reverse_data oracle, generated in python.
        def ref(d, sel, W):
            s = f"{d:0{W}b}"
            if sel == 0:
                return int(s[::-1], 2)
            if sel == 1:
                h = W // 2
                return int(s[:h][::-1] + s[h:][::-1], 2)
            if sel == 2:
                q = W // 4
                return int("".join(s[k * q:(k + 1) * q][::-1] for k in range(4)), 2)
            if sel == 3:
                e = W // 8
                return int("".join(s[k * e:(k + 1) * e][::-1] for k in range(8)), 2)
            return d
        import random
        rng = random.Random(7)
        for W in (16, 32, 40, 48, 64):  # the runner's DATA_WIDTH set
            checks = []
            for _ in range(150):
                d = rng.randint(0, (1 << W) - 1)
                s = rng.randint(0, 3)
                checks.append((d, s, ref(d, s, W)))
            hexw = (W + 3) // 4
            body = "\n".join(
                f"    din={W}'h{d:0{hexw}x}; sel=2'd{s}; #1; "
                f"if(dout!=={W}'h{e:0{hexw}x}) f=f+1;"
                for d, s, e in checks)
            tb = (f"module tb; localparam DW={W};\n"
                  f" reg [DW-1:0] din; reg [1:0] sel; wire [DW-1:0] dout;\n"
                  f" nbit_swizzling #(.DATA_WIDTH(DW)) dut(.data_in(din),.sel(sel),.data_out(dout));\n"
                  f" integer f; initial begin f=0;\n{body}\n"
                  f' if(f==0)$display("RESULT 0");else $display("RESULT %0d",f); end endmodule')
            assert "RESULT 0" in _iverilog_ok(rtl, "nbit_swizzling", tb), f"W={W}"


@pytest.mark.skipif(not DATASET.exists(), reason="CVDP dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_dataset_only_three_clean_shapes_emit():
    recs = [json.loads(l) for l in DATASET.open()]
    emitted = {r["id"] for r in recs if B.solve(r)}
    assert emitted == {
        "cvdp_copilot_reverse_bits_0001",
        "cvdp_copilot_word_reducer_0008",
        "cvdp_copilot_nbit_swizzling_0001",
    }, emitted
    # no false emit anywhere in the bit-manip-keyword set (sequential / composite
    # / already-encoder-solved one-hot decoders must SKIP).
    kw = re.compile(r"(?i)\bpopulation\s+count\b|\bpopcount\b|\bleading\b|\btrailing\b|"
                    r"\bfind[-\s]?(?:first|last)\b|\bbit[-\s]?revers|\bbyte[-\s]?swap\b|"
                    r"\bendian|\bthermomet|\bone[-\s]?hot\b|\bhamming\b|\brun[-\s]?length\b")
    for r in recs:
        p = (r.get("input") or {}).get("prompt") or ""
        if kw.search(p) and r["id"] not in emitted:
            assert B.solve(r) is None, f"false emit on {r['id']}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
