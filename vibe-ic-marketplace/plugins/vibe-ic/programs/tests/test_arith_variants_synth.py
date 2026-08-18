#!/usr/bin/env python3
"""Tests for arith_variants_synth — the CVDP integer adder/subtractor/
multiplier VARIANT solver.

Positives (every EMIT is iverilog-host-verified against a faithful replica of the
record's cocotb function check):
  * a SEQUENTIAL any-latency start/done wrapper around `A+B` (the real dataset
    kogge_stone_adder_0007, 16-bit -> 17-bit);
  * a COMBINATIONAL signed two's-complement adder with a signed-OVERFLOW flag
    (a named-architecture variant; overflow is signed-ness dependent);
  * a COMBINATIONAL Wallace-tree multiplier == `a*b` (architecture irrelevant);
  * a COMBINATIONAL saturating unsigned adder with a stated max bound.

§4.05 negatives (must SKIP -> solve() returns None):
  * a GF(2^n) carry-less multiplier (function is NOT `a*b`);
  * a fixed-point adder with rounding (function is NOT plain integer add);
  * an adder that requests an overflow flag but does NOT state signed-ness;
  * a cycle-EXACT-latency-pinned pipelined multiplier (protocol the wrapper
    cannot match);
  * an FSM-state-pinned add/sub (the test asserts exact o_status codes).

chip-AGNOSTIC: the solver carries no design-name keys; a renamed TOPLEVEL still
solves, and the emitted module binds to whatever TOPLEVEL the harness states.
"""
import json
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

import arith_variants_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mk_record(top: str, prompt: str, tb: str) -> dict:
    """A minimal CVDP record dict: prompt + harness (.env TOPLEVEL + cocotb test).
    output.context is EMPTY (as in CVDP v1.1.0) — the solver never reads it."""
    return {
        "id": f"synthetic_{top}",
        "input": {"prompt": prompt},
        "harness": {"files": {
            "src/.env": f"SIM=icarus\nTOPLEVEL={top}\nMODULE=test_{top}\n",
            f"src/test_{top}.py": tb,
        }},
        "output": {"context": {f"rtl/{top}.sv": ""}},
    }


def _iverilog_ok(rtl: str, tb_v: str, pass_token: str) -> bool:
    """Compile rtl + a Verilog testbench, run, return True iff pass_token printed."""
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        tb = Path(d) / "tb.v"
        dut.write_text(rtl)
        tb.write_text(tb_v)
        sim = Path(d) / "sim"
        r = subprocess.run([_IVERILOG, "-g2012", "-o", str(sim), str(dut), str(tb)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("IVERILOG ERR:", r.stderr)
            return False
        r = subprocess.run([_VVP, str(sim)], capture_output=True, text=True)
        print(r.stdout)
        return pass_token in r.stdout


_need_iverilog = pytest.mark.skipif(
    not (_IVERILOG and _VVP), reason="iverilog/vvp not installed")


# =========================================================================== #
# POSITIVE 1 — real dataset: sequential any-latency A+B wrapper (kogge_stone).
# =========================================================================== #
def _load_record(rid: str):
    if not _DATASET.exists():
        pytest.skip(f"dataset not present: {_DATASET}")
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    pytest.skip(f"record {rid} not in dataset")


def test_kogge_stone_emits_seq_wrapper():
    r = _load_record("cvdp_copilot_kogge_stone_adder_0007")
    rtl = S.solve(r)
    assert rtl is not None
    assert "module kogge_stone_adder" in rtl
    assert "input clk" in rtl
    assert "output reg [16:0] Sum" in rtl     # 17-bit result (carry in MSB)
    assert "input [15:0] A" in rtl and "input [15:0] B" in rtl
    assert "A + B" in rtl
    assert "done" in rtl


@_need_iverilog
def test_kogge_stone_host_verified():
    r = _load_record("cvdp_copilot_kogge_stone_adder_0007")
    rtl = S.solve(r)
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb;
  reg clk=0, reset, start; reg [15:0] A, B; wire [16:0] Sum; wire done;
  integer i, errors=0; reg [16:0] expected;
  kogge_stone_adder dut(.clk(clk),.reset(reset),.A(A),.B(B),.start(start),.Sum(Sum),.done(done));
  always #5 clk=~clk;
  initial begin
    reset=1; start=0; A=0; B=0; #20; reset=0; @(posedge clk);
    for (i=0;i<200;i=i+1) begin
      A=$random; B=$random; expected=(A+B)&17'h1FFFF;
      start=1; @(posedge clk); start=0; while(done==0) @(posedge clk);
      if (Sum!==expected) begin errors=errors+1; $display("MISMATCH"); end
      @(posedge clk);
    end
    A=16'hFFFF; B=16'h0001; expected=(A+B)&17'h1FFFF;
    start=1; @(posedge clk); start=0; while(done==0)@(posedge clk);
    if (Sum!==expected) errors=errors+1;
    if (errors==0) $display("PASS_OK"); else $display("FAIL %0d",errors);
    $finish;
  end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 2 — combinational signed adder + signed-OVERFLOW flag.
# =========================================================================== #
_SIGNED_OVF_PROMPT = """\
Design a 8-bit **carry-select adder** named `csel_adder`. The module adds two
**signed** two's complement operands and reports a signed **overflow**.

### Inputs
- **`a`** (8-bits, [7:0]): first signed operand.
- **`b`** (8-bits, [7:0]): second signed operand.

### Outputs
- **`sum`** (8-bits, [7:0]): the signed sum a + b.
- **`overflow`** (1-bit): asserted on signed overflow.
"""
_SIGNED_OVF_TB = """\
import cocotb
@cocotb.test()
async def t(dut):
    dut.a.value = 1
    dut.b.value = 2
    s = dut.sum.value.signed_integer
    o = dut.overflow.value
"""


def test_signed_overflow_comb_emits():
    r = _mk_record("csel_adder", _SIGNED_OVF_PROMPT, _SIGNED_OVF_TB)
    rtl = S.solve(r)
    assert rtl is not None
    assert "module csel_adder" in rtl
    assert "assign sum =" in rtl and "$signed" in rtl
    assert "overflow" in rtl


@_need_iverilog
def test_signed_overflow_host_verified():
    r = _mk_record("csel_adder", _SIGNED_OVF_PROMPT, _SIGNED_OVF_TB)
    rtl = S.solve(r)
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb;
  reg signed [7:0] a, b; wire signed [7:0] sum; wire overflow;
  integer i, errors=0; reg signed [8:0] full; reg exp_ovf;
  csel_adder dut(.a(a),.b(b),.sum(sum),.overflow(overflow));
  initial begin
    for (i=0;i<2000;i=i+1) begin
      a=$random; b=$random; full=a+b;
      exp_ovf = (full > 127) || (full < -128);
      #1;
      if (sum !== full[7:0]) begin errors=errors+1; $display("SUM MISMATCH"); end
      if (overflow !== exp_ovf) begin errors=errors+1; $display("OVF MISMATCH a=%0d b=%0d got=%b exp=%b",a,b,overflow,exp_ovf); end
    end
    if (errors==0) $display("PASS_OK"); else $display("FAIL %0d",errors);
    $finish;
  end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 3 — combinational Wallace-tree multiplier == a*b.
# =========================================================================== #
_WALLACE_PROMPT = """\
Implement an 8-bit unsigned **Wallace tree multiplier** named `wallace_mult`.
The Wallace tree reduces the partial products in parallel; the result is the
16-bit product of the two operands.

### Inputs
- **`a`** (8-bits, [7:0]): the multiplicand.
- **`b`** (8-bits, [7:0]): the multiplier.

### Outputs
- **`product`** (16-bits, [15:0]): the 16-bit product a * b.
"""
_WALLACE_TB = """\
import cocotb
@cocotb.test()
async def t(dut):
    dut.a.value = 3
    dut.b.value = 4
    p = int(dut.product.value)
"""


def test_wallace_mult_emits():
    r = _mk_record("wallace_mult", _WALLACE_PROMPT, _WALLACE_TB)
    rtl = S.solve(r)
    assert rtl is not None
    assert "module wallace_mult" in rtl
    assert "a * b" in rtl
    assert "output [15:0] product" in rtl


@_need_iverilog
def test_wallace_mult_host_verified():
    r = _mk_record("wallace_mult", _WALLACE_PROMPT, _WALLACE_TB)
    rtl = S.solve(r)
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb;
  reg [7:0] a, b; wire [15:0] product; integer i, errors=0;
  wallace_mult dut(.a(a),.b(b),.product(product));
  initial begin
    for (i=0;i<3000;i=i+1) begin
      a=$random; b=$random; #1;
      if (product !== a*b) begin errors=errors+1; $display("MISMATCH"); end
    end
    if (errors==0) $display("PASS_OK"); else $display("FAIL %0d",errors);
    $finish;
  end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 4 — combinational saturating UNSIGNED adder (stated max bound).
# =========================================================================== #
_SAT_PROMPT = """\
Design an 8-bit unsigned **saturating adder** named `sat_adder`. The module adds
two unsigned operands and **saturates to the maximum** representable value on
overflow (the result never wraps).

### Inputs
- **`a`** (8-bits, [7:0]): first operand.
- **`b`** (8-bits, [7:0]): second operand.

### Outputs
- **`sum`** (8-bits, [7:0]): a + b, clamped to the maximum value on overflow.
"""
_SAT_TB = """\
import cocotb
@cocotb.test()
async def t(dut):
    dut.a.value = 200
    dut.b.value = 100
    s = int(dut.sum.value)
"""


def test_saturating_adder_emits():
    r = _mk_record("sat_adder", _SAT_PROMPT, _SAT_TB)
    rtl = S.solve(r)
    assert rtl is not None
    assert "module sat_adder" in rtl
    assert "saturating" in rtl.splitlines()[0]


@_need_iverilog
def test_saturating_adder_host_verified():
    r = _mk_record("sat_adder", _SAT_PROMPT, _SAT_TB)
    rtl = S.solve(r)
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb;
  reg [7:0] a, b; wire [7:0] sum; integer i, errors=0; reg [8:0] full; reg [7:0] exp;
  sat_adder dut(.a(a),.b(b),.sum(sum));
  initial begin
    for (i=0;i<3000;i=i+1) begin
      a=$random; b=$random; full=a+b; exp = full[8] ? 8'hFF : full[7:0]; #1;
      if (sum !== exp) begin errors=errors+1; $display("MISMATCH a=%0d b=%0d got=%0d exp=%0d",a,b,sum,exp); end
    end
    if (errors==0) $display("PASS_OK"); else $display("FAIL %0d",errors);
    $finish;
  end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# §4.05 NEGATIVE 1 — GF(2^n) carry-less multiply: SKIP (function != a*b).
# =========================================================================== #
def test_gf_multiplier_skips():
    prompt = """\
Implement a `gf_multiplier` performing **Galois field** GF(2^8) multiplication
with the irreducible polynomial 0x11B (carry-less multiply then reduce).

### Inputs
- **`A`** (8-bits, [7:0]): operand A.
- **`B`** (8-bits, [7:0]): operand B.

### Outputs
- **`result`** (8-bits, [7:0]): the GF(2^8) product.
"""
    tb = "import cocotb\n@cocotb.test()\nasync def t(dut):\n    dut.A.value=1\n    dut.B.value=2\n    r=int(dut.result.value)\n"
    assert S.solve(_mk_record("gf_multiplier", prompt, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 2 — fixed-point adder: SKIP (function != plain integer add).
# =========================================================================== #
def test_fixed_point_skips():
    prompt = """\
Design a **fixed-point** adder `fp_add` in Q4.4 format that rounds the result to
nearest.

### Inputs
- **`a`** (8-bits, [7:0]): first fixed-point operand.
- **`b`** (8-bits, [7:0]): second fixed-point operand.

### Outputs
- **`c`** (8-bits, [7:0]): the rounded fixed-point sum.
"""
    tb = "import cocotb\n@cocotb.test()\nasync def t(dut):\n    dut.a.value=1\n    dut.b.value=2\n    c=int(dut.c.value)\n"
    assert S.solve(_mk_record("fp_add", prompt, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 3 — overflow requested but signed-ness UNSTATED: SKIP.
# =========================================================================== #
def test_unstated_signedness_with_overflow_skips():
    prompt = """\
Design an 8-bit **Han-Carlson adder** `hc_adder` that adds two operands and
reports an **overflow** flag.

### Inputs
- **`a`** (8-bits, [7:0]): first operand.
- **`b`** (8-bits, [7:0]): second operand.

### Outputs
- **`sum`** (8-bits, [7:0]): the sum.
- **`overflow`** (1-bit): overflow flag.
"""
    tb = "import cocotb\n@cocotb.test()\nasync def t(dut):\n    dut.a.value=1\n    dut.b.value=2\n    s=int(dut.sum.value)\n    o=dut.overflow.value\n"
    # signed-ness is NOT stated, an overflow flag IS requested -> must SKIP.
    assert S.solve(_mk_record("hc_adder", prompt, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 4 — cycle-EXACT-latency-pinned pipelined multiplier: SKIP.
# =========================================================================== #
def test_latency_pinned_pipeline_mult_skips():
    prompt = """\
Implement a pipelined signed **Booth multiplier** `pipe_booth` that computes the
32-bit product over several pipeline stages.

### Inputs
- **`a`** (16-bits, [15:0]): multiplicand.
- **`b`** (16-bits, [15:0]): multiplier.

### Outputs
- **`result`** (32-bits, [31:0]): the product.
- **`done`** (1-bit): asserted when the result is valid.
"""
    tb = """\
import cocotb
@cocotb.test()
async def t(dut):
    dut.a.value = 3
    dut.b.value = 4
    latency = 0
    while dut.done.value == 0:
        latency = latency + 1
    assert latency == 5, "Valid output should have latency of 5 clk cycles"
    r = dut.result.value.signed_integer
"""
    # the test pins the EXACT latency (==5) -> a functional wrapper cannot match.
    assert S.solve(_mk_record("pipe_booth", prompt, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 5 — FSM-state-pinned add/sub: SKIP.
# =========================================================================== #
def test_fsm_state_pinned_addsub_skips():
    prompt = """\
Complete `fsm_addsub`: a signed two's complement add/subtract controlled by a
state machine. `i_mode`: `0`: addition, `1`: subtraction. An `o_status` signal
reports the current state.

### Inputs
- **`i_clk`** (1-bit): clock.
- **`i_rst_n`** (1-bit): active-low reset.
- **`i_start`** (1-bit): start.
- **`i_a`** (8-bits, [7:0]): operand a.
- **`i_b`** (8-bits, [7:0]): operand b.
- **`i_mode`** (1-bit): 0 add, 1 subtract.

### Outputs
- **`o_sum`** (8-bits, [7:0]): the result.
- **`o_status`** (2-bits, [1:0]): the FSM state code.
"""
    tb = """\
import cocotb
@cocotb.test()
async def t(dut):
    dut.i_start.value = 1
    dut.i_a.value = 20
    dut.i_b.value = 10
    assert dut.o_status.value == 1, "Expected state to be LOAD"
    assert dut.o_status.value == 2, "Expected state to be COMPUTE"
"""
    # the test asserts EXACT FSM state codes -> SKIP.
    assert S.solve(_mk_record("fsm_addsub", prompt, tb)) is None


# =========================================================================== #
# chip-AGNOSTIC — the solver has no design-name keys; a renamed module solves and
# binds to whatever TOPLEVEL the harness states.
# =========================================================================== #
def test_chip_agnostic_rename():
    r1 = _mk_record("wallace_mult", _WALLACE_PROMPT, _WALLACE_TB)
    # rename the TOPLEVEL + prompt module to an arbitrary unrelated name.
    prompt2 = _WALLACE_PROMPT.replace("wallace_mult", "zzz_qux_mul")
    r2 = _mk_record("zzz_qux_mul", prompt2, _WALLACE_TB)
    rtl2 = S.solve(r2)
    assert rtl2 is not None
    assert "module zzz_qux_mul" in rtl2
    assert "a * b" in rtl2
    # no design-name token leaked into the solver's EXECUTABLE code (comments and
    # the module docstring legitimately cite architecture examples; logic must
    # not). Strip docstrings + comments, then scan the remaining code lines.
    import io
    import tokenize
    src = (_PROG / "arith_variants_synth.py").read_text()
    skip_types = {tokenize.COMMENT, tokenize.STRING}
    for nm in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, nm):
            skip_types.add(getattr(tokenize, nm))
    code_only = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in skip_types:
            continue
        code_only.append(tok.string)
    code_blob = " ".join(code_only)
    for banned in ("kogge_stone", "wallace_mult", "brent_kung", "booth_mul",
                   "cascaded_adder", "signedadder", "gf_multiplier"):
        assert banned not in code_blob, f"design-name key in executable code: {banned}"


def test_solve_handles_garbage():
    assert S.solve(None) is None
    assert S.solve({}) is None
    assert S.solve({"input": {"prompt": ""}}) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
