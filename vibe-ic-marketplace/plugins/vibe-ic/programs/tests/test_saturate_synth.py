#!/usr/bin/env python3
"""Tests for saturate_synth — the CVDP SATURATE / CLAMP / THRESHOLD + SIGN
datapath family solver.

Positives (every EMIT is iverilog-host-verified — exhaustively over the small
width — against a faithful replica of the record's function check):
  * the REAL dataset cvdp_copilot_comparator_0001 (a dual signed/magnitude
    comparator-to-flag with enable, 5-bit) — exhaustive over 32x32 x 2 modes;
  * a combinational unsigned CLAMP to a stated [3,200];
  * a combinational signed CLAMP to a stated [-50,50];
  * a combinational SIGN-EXTEND 4->12 and ZERO-EXTEND 4->8;
  * a combinational ABSOLUTE VALUE of a signed operand;
  * a combinational NEGATE (two's complement);
  * a combinational THRESHOLD FLAG (x > T).

§4.05 PARSE-OR-SKIP negatives (must SKIP -> solve() returns None):
  * a CLAMP whose bound is not stated (configurable range);
  * an ABS whose signed-ness is not stated;
  * a THRESHOLD whose threshold value is not stated;
  * a clamp record that is actually a composite weighted-sum module
    (signal_correlator_0015 — the function is NOT a clamp of an input);
  * a multi-op ALU with opcode/key (secure_ALU_0001 — composite);
  * a LINT/edit-task record (cont_adder_0042);
  * a sequential (clocked) design — not a pure combinational mapping;
  * an FSM-state-pinned / latency-pinned wrapper.

chip-AGNOSTIC: the solver carries no design-name keys; a renamed TOPLEVEL still
solves, and the emitted module binds to whatever TOPLEVEL the harness states.
"""
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import saturate_synth as S  # noqa: E402

_DATASET = Path("/home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/"
                "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")
_need_iverilog = pytest.mark.skipif(
    not (_IVERILOG and _VVP), reason="iverilog/vvp not installed")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mk_record(top: str, prompt: str, tb: str) -> dict:
    """A minimal CVDP record: prompt + harness (.env TOPLEVEL + cocotb test).
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


def _load_record(rid: str):
    if not _DATASET.exists():
        pytest.skip(f"dataset not present: {_DATASET}")
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    pytest.skip(f"record {rid} not in dataset")


# A data-only cocotb TB with a single driven operand `x` read into `out`.
_TB_X_OUT = ("import cocotb\n@cocotb.test()\nasync def t(dut):\n"
             "    dut.x.value = 1\n    y = int(dut.out.value)\n")
_TB_X_FLAG = ("import cocotb\n@cocotb.test()\nasync def t(dut):\n"
              "    dut.x.value = 1\n    f = int(dut.flag.value)\n")


# =========================================================================== #
# POSITIVE 0 — REAL dataset: dual signed/magnitude comparator-to-flag.
# =========================================================================== #
def test_dataset_comparator_emits():
    r = _load_record("cvdp_copilot_comparator_0001")
    rtl = S.solve(r)
    assert rtl is not None
    assert "module signed_unsigned_comparator" in rtl
    assert "input [4:0] i_A" in rtl and "input [4:0] i_B" in rtl
    assert "o_greater" in rtl and "o_less" in rtl and "o_equal" in rtl
    assert "$signed" in rtl                       # signed-mode compare
    assert "i_enable" in rtl                       # enable gates the flags


@_need_iverilog
def test_dataset_comparator_host_verified():
    r = _load_record("cvdp_copilot_comparator_0001")
    rtl = S.solve(r)
    assert rtl is not None
    # exhaustive over all 32x32 inputs x 2 modes x enable, vs a reference.
    tb = r"""
`timescale 1ns/1ns
module tb;
  reg [4:0] i_A, i_B; reg i_enable, i_mode;
  wire o_greater, o_less, o_equal; integer errors=0;
  signed_unsigned_comparator dut(.i_A(i_A),.i_B(i_B),.i_enable(i_enable),
    .i_mode(i_mode),.o_greater(o_greater),.o_less(o_less),.o_equal(o_equal));
  integer ai, bi, en2, md2; reg signed [4:0] sa, sb; integer eg, el, ee;
  initial begin
    for (en2=0;en2<2;en2=en2+1)
    for (md2=0;md2<2;md2=md2+1)
    for (ai=0;ai<32;ai=ai+1)
    for (bi=0;bi<32;bi=bi+1) begin
      i_A=ai[4:0]; i_B=bi[4:0]; i_enable=en2[0]; i_mode=md2[0]; #1;
      sa=ai[4:0]; sb=bi[4:0];
      if (en2==0) begin eg=0; el=0; ee=0; end
      else if (md2==1) begin eg=(sa>sb); el=(sa<sb); ee=(ai[4:0]==bi[4:0]); end
      else begin eg=(ai[4:0]>bi[4:0]); el=(ai[4:0]<bi[4:0]); ee=(ai[4:0]==bi[4:0]); end
      if (o_greater!==eg[0] || o_less!==el[0] || o_equal!==ee[0]) begin
        errors=errors+1; $display("MIS en=%0d md=%0d A=%0d B=%0d",en2,md2,ai,bi); end
    end
    if (errors==0) $display("PASS_OK"); else $display("FAIL %0d",errors);
    $finish;
  end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 1 — combinational unsigned CLAMP to a stated [3,200].
# =========================================================================== #
_CLAMP_U_PROMPT = ("Design module clamp8 that clamps the 8-bit input x "
                   "(8-bits, [7:0]) to the range [3, 200], producing an 8-bit "
                   "output out (8-bits, [7:0]).")


def test_clamp_unsigned_emits():
    r = _mk_record("clamp8", _CLAMP_U_PROMPT, _TB_X_OUT)
    rtl = S.solve(r)
    assert rtl is not None
    assert "module clamp8" in rtl
    assert "x < 3" in rtl and "x > 200" in rtl
    assert "input [7:0] x" in rtl


@_need_iverilog
def test_clamp_unsigned_host_verified():
    rtl = S.solve(_mk_record("clamp8", _CLAMP_U_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [7:0] x; wire [7:0] out; integer i,e=0; reg [7:0] exp;
  clamp8 d(.x(x),.out(out));
  initial begin
    for (i=0;i<256;i=i+1) begin x=i[7:0]; exp=(x<3)?8'd3:((x>200)?8'd200:x); #1;
      if (out!==exp) begin e=e+1; $display("MIS x=%0d got=%0d exp=%0d",x,out,exp); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 2 — combinational signed CLAMP to a stated [-50,50].
# =========================================================================== #
_CLAMP_S_PROMPT = ("Module sclamp clamps the signed input x (8-bits, [7:0]) to "
                   "the range [-50, 50]. The output out (8-bits, [7:0]) is a "
                   "signed two's complement value.")


def test_clamp_signed_emits():
    rtl = S.solve(_mk_record("sclamp", _CLAMP_S_PROMPT, _TB_X_OUT))
    assert rtl is not None
    assert "$signed(x)" in rtl
    assert "-50" in rtl and "50" in rtl


@_need_iverilog
def test_clamp_signed_host_verified():
    rtl = S.solve(_mk_record("sclamp", _CLAMP_S_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [7:0] x; wire [7:0] out; integer i,e=0; reg signed [7:0] sx, exp;
  sclamp d(.x(x),.out(out));
  initial begin
    for (i=0;i<256;i=i+1) begin x=i[7:0]; sx=i[7:0];
      exp=(sx<-50)?-50:((sx>50)?50:sx); #1;
      if ($signed(out)!==exp) begin e=e+1; $display("MIS x=%0d got=%0d exp=%0d",sx,$signed(out),exp); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 3 — SIGN-EXTEND 4->12 and ZERO-EXTEND 4->8.
# =========================================================================== #
_SEXT_PROMPT = ("Module sext sign-extends the signed input x (4-bits, [3:0]) to "
                "a 12-bit output out (12-bits, [11:0]).")
_ZEXT_PROMPT = ("Module zext zero-extends the input x (4-bits, [3:0]) to an "
                "8-bit output out (8-bits, [7:0]).")


def test_sign_extend_emits():
    rtl = S.solve(_mk_record("sext", _SEXT_PROMPT, _TB_X_OUT))
    assert rtl is not None
    assert "{{8{x[3]}}, x}" in rtl
    assert "input [3:0] x" in rtl and "output [11:0] out" in rtl


def test_zero_extend_emits():
    rtl = S.solve(_mk_record("zext", _ZEXT_PROMPT, _TB_X_OUT))
    assert rtl is not None
    assert "{{4{1'b0}}, x}" in rtl


@_need_iverilog
def test_sign_extend_host_verified():
    rtl = S.solve(_mk_record("sext", _SEXT_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [3:0] x; wire [11:0] out; integer i,e=0; reg signed [3:0] sx; reg signed [11:0] exp;
  sext d(.x(x),.out(out));
  initial begin
    for (i=0;i<16;i=i+1) begin x=i[3:0]; sx=i[3:0]; exp=sx; #1;
      if ($signed(out)!==exp) begin e=e+1; $display("MIS x=%0d got=%0d exp=%0d",sx,$signed(out),exp); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


@_need_iverilog
def test_zero_extend_host_verified():
    rtl = S.solve(_mk_record("zext", _ZEXT_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [3:0] x; wire [7:0] out; integer i,e=0; reg [7:0] exp;
  zext d(.x(x),.out(out));
  initial begin
    for (i=0;i<16;i=i+1) begin x=i[3:0]; exp={4'b0, x}; #1;
      if (out!==exp) begin e=e+1; $display("MIS"); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 4 — ABSOLUTE VALUE of a signed operand.
# =========================================================================== #
_ABS_PROMPT = ("Module absmod computes the absolute value of the signed input x "
               "(8-bits, [7:0]); the result out (8-bits, [7:0]) is |x|.")


def test_abs_emits():
    rtl = S.solve(_mk_record("absmod", _ABS_PROMPT, _TB_X_OUT))
    assert rtl is not None
    assert "x[7]" in rtl and "~x + 1'b1" in rtl


@_need_iverilog
def test_abs_host_verified():
    rtl = S.solve(_mk_record("absmod", _ABS_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [7:0] x; wire [7:0] out; integer i,e=0; reg signed [7:0] sx; reg [7:0] exp;
  absmod d(.x(x),.out(out));
  initial begin
    for (i=0;i<256;i=i+1) begin x=i[7:0]; sx=i[7:0]; exp=sx[7]?(-sx):sx; #1;
      if (out!==exp) begin e=e+1; $display("MIS x=%0d got=%0d exp=%0d",sx,out,exp); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 5 — NEGATE (two's complement).
# =========================================================================== #
_NEG_PROMPT = ("Module negmod computes the two's complement negation of x "
               "(8-bits, [7:0]); the output out (8-bits, [7:0]) equals the "
               "additive inverse of x.")


def test_negate_emits():
    rtl = S.solve(_mk_record("negmod", _NEG_PROMPT, _TB_X_OUT))
    assert rtl is not None
    assert "~x + 1'b1" in rtl


@_need_iverilog
def test_negate_host_verified():
    rtl = S.solve(_mk_record("negmod", _NEG_PROMPT, _TB_X_OUT))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [7:0] x; wire [7:0] out; integer i,e=0; reg [7:0] exp;
  negmod d(.x(x),.out(out));
  initial begin
    for (i=0;i<256;i=i+1) begin x=i[7:0]; exp=(~x + 8'd1); #1;
      if (out!==exp) begin e=e+1; $display("MIS"); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# POSITIVE 6 — THRESHOLD FLAG (x > T).
# =========================================================================== #
_THR_PROMPT = ("Module thr produces flag (1-bit) high when the unsigned input x "
               "(8-bits, [7:0]) exceeds the threshold, i.e. flag = (x > 100).")


def test_threshold_flag_emits():
    rtl = S.solve(_mk_record("thr", _THR_PROMPT, _TB_X_FLAG))
    assert rtl is not None
    assert "x > 100" in rtl
    assert "output flag" in rtl


@_need_iverilog
def test_threshold_flag_host_verified():
    rtl = S.solve(_mk_record("thr", _THR_PROMPT, _TB_X_FLAG))
    assert rtl is not None
    tb = r"""
`timescale 1ns/1ns
module tb; reg [7:0] x; wire flag; integer i,e=0; reg exp;
  thr d(.x(x),.flag(flag));
  initial begin
    for (i=0;i<256;i=i+1) begin x=i[7:0]; exp=(x>100); #1;
      if (flag!==exp) begin e=e+1; $display("MIS"); end end
    if (e==0) $display("PASS_OK"); else $display("FAIL %0d",e); $finish; end
endmodule
"""
    assert _iverilog_ok(rtl, tb, "PASS_OK")


# =========================================================================== #
# §4.05 NEGATIVE 1 — CLAMP with UNSTATED bound: SKIP.
# =========================================================================== #
def test_clamp_unstated_bound_skips():
    p = ("Module clampU clamps the input x (8-bits, [7:0]) to a configurable "
         "range, producing out (8-bits, [7:0]).")
    assert S.solve(_mk_record("clampU", p, _TB_X_OUT)) is None


# =========================================================================== #
# §4.05 NEGATIVE 2 — ABS with UNSTATED signed-ness: SKIP.
# =========================================================================== #
def test_abs_unstated_signedness_skips():
    p = ("Module absU computes the absolute value of x (8-bits, [7:0]); the "
         "output out (8-bits, [7:0]) is |x|.")
    # signed-ness is NOT stated; abs is only defined on a signed operand -> SKIP.
    assert S.solve(_mk_record("absU", p, _TB_X_OUT)) is None


# =========================================================================== #
# §4.05 NEGATIVE 3 — THRESHOLD with UNSTATED threshold value: SKIP.
# =========================================================================== #
def test_threshold_unstated_value_skips():
    p = ("Module thrU sets flag (1-bit) high when x (8-bits, [7:0]) exceeds the "
         "threshold.")
    assert S.solve(_mk_record("thrU", p, _TB_X_FLAG)) is None


# =========================================================================== #
# §4.05 NEGATIVE 4 — single-mode compare with UNSTATED signed-ness: SKIP.
# =========================================================================== #
def test_compare_unstated_signedness_skips():
    p = ("Module cmpU compares a (8-bits, [7:0]) and b (8-bits, [7:0]) and sets "
         "o_greater (1-bit), o_less (1-bit), o_equal (1-bit).")
    tb = ("import cocotb\n@cocotb.test()\nasync def t(dut):\n"
          "    dut.a.value = 1\n    dut.b.value = 2\n"
          "    g = int(dut.o_greater.value)\n")
    # neither signed nor unsigned stated, no dual-mode -> SKIP.
    assert S.solve(_mk_record("cmpU", p, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 5 — a real composite clamp record: SKIP.
# (signal_correlator_0015 clamps at 15, but the FUNCTION is a weighted bit-match
#  sum, NOT a clamp of an input — a wrong emit would be far worse than a skip.)
# =========================================================================== #
def test_real_composite_correlator_skips():
    r = _load_record("cvdp_copilot_signal_correlator_0015")
    assert S.solve(r) is None


# =========================================================================== #
# §4.05 NEGATIVE 6 — a real composite multi-op ALU record: SKIP.
# =========================================================================== #
def test_real_composite_alu_skips():
    r = _load_record("cvdp_copilot_secure_ALU_0001")
    assert S.solve(r) is None


# =========================================================================== #
# §4.05 NEGATIVE 7 — a real LINT/edit-task record: SKIP.
# =========================================================================== #
def test_real_lint_edit_task_skips():
    r = _load_record("cvdp_copilot_cont_adder_0042")
    assert S.solve(r) is None


# =========================================================================== #
# §4.05 NEGATIVE 8 — a SEQUENTIAL (clocked) clamp: SKIP (not combinational).
# =========================================================================== #
def test_sequential_clamp_skips():
    p = ("Module sclk clamps the input x (8-bits, [7:0]) to the range [0, 100] "
         "and registers the result out (8-bits, [7:0]) on the clock edge.")
    tb = ("import cocotb\nfrom cocotb.clock import Clock\n"
          "from cocotb.triggers import RisingEdge\n@cocotb.test()\n"
          "async def t(dut):\n"
          "    cocotb.start_soon(Clock(dut.clk, 10, units='ns').start())\n"
          "    dut.x.value = 1\n    await RisingEdge(dut.clk)\n"
          "    y = int(dut.out.value)\n")
    assert S.solve(_mk_record("sclk", p, tb)) is None


# =========================================================================== #
# §4.05 NEGATIVE 9 — FSM-state-pinned wrapper: SKIP.
# =========================================================================== #
def test_fsm_state_pinned_skips():
    p = ("Module clampfsm clamps x (8-bits, [7:0]) to [0, 100] producing out "
         "(8-bits, [7:0]); an o_status (2-bits, [1:0]) reports the FSM state.")
    tb = ("import cocotb\n@cocotb.test()\nasync def t(dut):\n"
          "    dut.x.value = 5\n"
          "    assert dut.o_status.value == 1, 'expected LOAD'\n")
    assert S.solve(_mk_record("clampfsm", p, tb)) is None


# =========================================================================== #
# chip-AGNOSTIC — a renamed TOPLEVEL still solves and binds to it; no design-name
# token leaks into the solver's EXECUTABLE code.
# =========================================================================== #
def test_chip_agnostic_rename_dataset():
    r = _load_record("cvdp_copilot_comparator_0001")
    r2 = copy.deepcopy(r)
    r2["harness"]["files"]["src/.env"] = r2["harness"]["files"]["src/.env"].replace(
        "signed_unsigned_comparator", "zzz_qux_cmp")
    r2["input"]["prompt"] = r2["input"]["prompt"].replace(
        "signed_unsigned_comparator", "zzz_qux_cmp")
    rtl2 = S.solve(r2)
    assert rtl2 is not None
    assert "module zzz_qux_cmp" in rtl2


def test_chip_agnostic_rename_synthetic():
    rtl = S.solve(_mk_record("my_clamp", _CLAMP_U_PROMPT.replace("clamp8", "my_clamp"),
                             _TB_X_OUT))
    assert rtl is not None and "module my_clamp" in rtl


def test_no_design_name_in_executable_code():
    src = (_PROG / "saturate_synth.py").read_text()
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
    for banned in ("signed_unsigned_comparator", "signal_correlator", "secure_alu",
                   "cont_adder", "comparator_0001", "perceptron", "sobel"):
        assert banned not in code_blob.lower(), \
            f"design-name key in executable code: {banned}"


def test_solve_handles_garbage():
    assert S.solve(None) is None
    assert S.solve({}) is None
    assert S.solve({"input": {"prompt": ""}}) is None
    assert S.solve({"input": {"prompt": "hi"}, "harness": {"files": {}}}) is None


# =========================================================================== #
# the whole dataset: solver is conservative (emits only a recognizable atomic
# combinational mapping; never crashes on any record).
# =========================================================================== #
def test_dataset_no_crash_and_conservative():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    recs = [json.loads(l) for l in _DATASET.read_text().splitlines()]
    emits = 0
    for r in recs:
        rtl = S.solve(r)              # must never raise
        if rtl:
            emits += 1
            assert "module" in rtl
    # at least the dataset comparator is solved; conservative by construction.
    assert emits >= 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
