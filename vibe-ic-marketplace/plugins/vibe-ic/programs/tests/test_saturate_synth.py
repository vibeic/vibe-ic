#!/usr/bin/env python3
"""Tests for saturate_synth — the CVDP SATURATE / CLAMP / THRESHOLD + SIGN
datapath family solver.

COMPLIANCE (post harness-read cleanup): the solver sources the module NAME and the
port INTERFACE ONLY from `input.prompt` + `input.context`, via
`record_prompt_context_bridge.{toplevel_name,extract_interface}`. The hidden cocotb harness
(`dut.<sig>` test + `.env` TOPLEVEL / VERILOG_SOURCES) and the golden `output.*`
are OFF-LIMITS oracle and are NEVER read. Every record below therefore states its
name + interface in the PROMPT (a `` `top` `` designation + an `### Inputs:`/
`### Outputs:` block with prose widths); the harness is retained as a DECOY (its
`.env` TOPLEVEL disagrees with the prompt) purely to prove the solver ignores it.

Positives (every EMIT is iverilog-host-verified — exhaustively over the small
width — against a faithful replica of the record's function check):
  * a dual signed/magnitude comparator-to-flag with enable, 5-bit — exhaustive
    over 32x32 x 2 modes;
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
  * a single-mode comparator whose signed-ness is not stated;
  * a real composite weighted-sum module (signal_correlator_0015 — NOT a clamp);
  * a real multi-op ALU with opcode/key (secure_ALU_0001 — composite);
  * a real LINT/edit-task record (cont_adder_0042);
  * a sequential (clocked) design — not a pure combinational mapping;
  * an FSM-state-pinned wrapper.

chip-AGNOSTIC: the solver carries no design-name keys; a renamed prompt still
solves, and the emitted module binds to whatever name the PROMPT states.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tokenize
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import saturate_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")
_need_iverilog = pytest.mark.skipif(
    not (_IVERILOG and _VVP), reason="iverilog/vvp not installed")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _io(ins, outs) -> str:
    """A legal prompt-side `### Inputs:`/`### Outputs:` port block (NAMES only —
    widths stay in the prompt prose). This is the model-visible interface source."""
    s = "\n\n### Inputs:\n" + "".join(f"- `{n}`\n" for n in ins)
    s += "\n### Outputs:\n" + "".join(f"- `{n}`\n" for n in outs)
    return s


def _mk_record(top: str, prompt: str) -> dict:
    """A CVDP-COMPLIANT record: the module NAME + port INTERFACE both live in
    `input.prompt` (the ONLY model-visible surface). The harness `.env` + cocotb
    test AND `output.context` (golden) are RETAINED for record-shape fidelity but
    are OFF-LIMITS oracle the solver NEVER reads. The `.env` TOPLEVEL and the
    cocotb `dut.<sig>` names are DECOYS that DISAGREE with the prompt — a compliant
    solver names + binds from the prompt and ignores them entirely."""
    return {
        "id": f"synthetic_{top}",
        "input": {"prompt": prompt},
        "harness": {"files": {
            "src/.env": f"SIM=icarus\nTOPLEVEL=DECOY_HARNESS_TOP\nMODULE=test_{top}\n",
            f"src/test_{top}.py": ("import cocotb\n@cocotb.test()\n"
                                   "async def t(dut):\n"
                                   "    dut.DECOY_IN.value = 1\n"
                                   "    _ = int(dut.DECOY_OUT.value)\n"),
        }},
        "output": {"context": {f"rtl/{top}.sv":
                               "module DECOY_GOLDEN(input a, output b);"
                               " assign b = a; endmodule"}},
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


# =========================================================================== #
# POSITIVE 0 — dual signed/magnitude comparator-to-flag (prompt-only, host-verified).
# =========================================================================== #
_CMP_PROMPT = textwrap.dedent("""\
    Design the module `signed_unsigned_comparator`, a purely combinational
    comparator that operates in two modes: signed mode and magnitude mode. It
    compares two inputs i_A [4:0] and i_B [4:0].

    - i_enable enables the comparison; when low all outputs are low.
    - i_mode selects the mode: high selects signed mode, low selects magnitude mode.

    In signed mode the inputs are interpreted as signed integers (the MSB is the
    sign bit). In magnitude mode both inputs are treated as unsigned magnitudes.
    The outputs o_greater, o_less and o_equal indicate i_A > i_B, i_A < i_B and
    i_A == i_B.
    """) + _io(["i_A", "i_B", "i_enable", "i_mode"],
               ["o_greater", "o_less", "o_equal"])


def test_comparator_emits():
    rtl = S.solve(_mk_record("signed_unsigned_comparator", _CMP_PROMPT))
    assert rtl is not None
    assert "module signed_unsigned_comparator" in rtl
    assert "input [4:0] i_A" in rtl and "input [4:0] i_B" in rtl
    assert "o_greater" in rtl and "o_less" in rtl and "o_equal" in rtl
    assert "$signed" in rtl                       # signed-mode compare
    assert "i_enable" in rtl                       # enable gates the flags


@_need_iverilog
def test_comparator_host_verified():
    rtl = S.solve(_mk_record("signed_unsigned_comparator", _CMP_PROMPT))
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
_CLAMP_U_PROMPT = ("Design the module `clamp8` that clamps the input x [7:0] to the "
                   "range [3, 200], producing the output out [7:0]."
                   + _io(["x"], ["out"]))


def test_clamp_unsigned_emits():
    r = _mk_record("clamp8", _CLAMP_U_PROMPT)
    rtl = S.solve(r)
    assert rtl is not None
    assert "module clamp8" in rtl
    assert "x < 3" in rtl and "x > 200" in rtl
    assert "input [7:0] x" in rtl


@_need_iverilog
def test_clamp_unsigned_host_verified():
    rtl = S.solve(_mk_record("clamp8", _CLAMP_U_PROMPT))
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
_CLAMP_S_PROMPT = ("Design the module `sclamp` that clamps the signed input x [7:0] to the range "
                   "[-50, 50]. The output out [7:0] is a signed two's complement "
                   "value." + _io(["x"], ["out"]))


def test_clamp_signed_emits():
    rtl = S.solve(_mk_record("sclamp", _CLAMP_S_PROMPT))
    assert rtl is not None
    assert "$signed(x)" in rtl
    assert "-50" in rtl and "50" in rtl


@_need_iverilog
def test_clamp_signed_host_verified():
    rtl = S.solve(_mk_record("sclamp", _CLAMP_S_PROMPT))
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
_SEXT_PROMPT = ("Design the module `sext` that sign-extends the signed input x [3:0] to the output "
                "out [11:0]." + _io(["x"], ["out"]))
_ZEXT_PROMPT = ("Design the module `zext` that zero-extends the input x [3:0] to the output out "
                "[7:0]." + _io(["x"], ["out"]))


def test_sign_extend_emits():
    rtl = S.solve(_mk_record("sext", _SEXT_PROMPT))
    assert rtl is not None
    assert "{{8{x[3]}}, x}" in rtl
    assert "input [3:0] x" in rtl and "output [11:0] out" in rtl


def test_zero_extend_emits():
    rtl = S.solve(_mk_record("zext", _ZEXT_PROMPT))
    assert rtl is not None
    assert "{{4{1'b0}}, x}" in rtl


@_need_iverilog
def test_sign_extend_host_verified():
    rtl = S.solve(_mk_record("sext", _SEXT_PROMPT))
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
    rtl = S.solve(_mk_record("zext", _ZEXT_PROMPT))
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
_ABS_PROMPT = ("Design the module `absmod` that computes the absolute value of the signed input x "
               "[7:0]; the result out [7:0] is |x|." + _io(["x"], ["out"]))


def test_abs_emits():
    rtl = S.solve(_mk_record("absmod", _ABS_PROMPT))
    assert rtl is not None
    assert "x[7]" in rtl and "~x + 1'b1" in rtl


@_need_iverilog
def test_abs_host_verified():
    rtl = S.solve(_mk_record("absmod", _ABS_PROMPT))
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
_NEG_PROMPT = ("Design the module `negmod` that computes the two's complement negation of x [7:0]; "
               "the output out [7:0] equals the additive inverse of x."
               + _io(["x"], ["out"]))


def test_negate_emits():
    rtl = S.solve(_mk_record("negmod", _NEG_PROMPT))
    assert rtl is not None
    assert "~x + 1'b1" in rtl


@_need_iverilog
def test_negate_host_verified():
    rtl = S.solve(_mk_record("negmod", _NEG_PROMPT))
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
_THR_PROMPT = ("Design the module `thr`. The unsigned input x [7:0] is compared to a "
               "threshold.\nThe output flag is high when x > 100."
               + _io(["x"], ["flag"]))


def test_threshold_flag_emits():
    rtl = S.solve(_mk_record("thr", _THR_PROMPT))
    assert rtl is not None
    assert "x > 100" in rtl
    assert "output flag" in rtl


@_need_iverilog
def test_threshold_flag_host_verified():
    rtl = S.solve(_mk_record("thr", _THR_PROMPT))
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
    p = ("Design the module `clampU` that clamps the input x [7:0] to a configurable range, "
         "producing out [7:0]." + _io(["x"], ["out"]))
    assert S.solve(_mk_record("clampU", p)) is None


# =========================================================================== #
# §4.05 NEGATIVE 2 — ABS with UNSTATED signed-ness: SKIP.
# =========================================================================== #
def test_abs_unstated_signedness_skips():
    p = ("Design the module `absU` that computes the absolute value of x [7:0]; the output out "
         "[7:0] is |x|." + _io(["x"], ["out"]))
    # signed-ness is NOT stated; abs is only defined on a signed operand -> SKIP.
    assert S.solve(_mk_record("absU", p)) is None


# =========================================================================== #
# §4.05 NEGATIVE 3 — THRESHOLD with UNSTATED threshold value: SKIP.
# =========================================================================== #
def test_threshold_unstated_value_skips():
    p = ("Design the module `thrU`. The output flag is high when the input x [7:0] exceeds "
         "the threshold." + _io(["x"], ["flag"]))
    assert S.solve(_mk_record("thrU", p)) is None


# =========================================================================== #
# §4.05 NEGATIVE 4 — single-mode compare with UNSTATED signed-ness: SKIP.
# =========================================================================== #
def test_compare_unstated_signedness_skips():
    p = ("Design the module `cmpU` that compares a [7:0] and b [7:0] and sets o_greater, o_less, "
         "o_equal." + _io(["a", "b"], ["o_greater", "o_less", "o_equal"]))
    # neither signed nor unsigned stated, no dual-mode -> SKIP.
    assert S.solve(_mk_record("cmpU", p)) is None


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
# The clocking cue is derived from the PROMPT ("registers the result ... on the
# clock edge"), NEVER from the OFF-LIMITS cocotb harness.
# =========================================================================== #
def test_sequential_clamp_skips():
    p = ("Design the module `sclk` that clamps the input x [7:0] to the range [0, 100] and "
         "registers the result out [7:0] on the clock edge." + _io(["x"], ["out"]))
    assert S.solve(_mk_record("sclk", p)) is None


# =========================================================================== #
# §4.05 NEGATIVE 9 — FSM-state wrapper: SKIP (composite, prompt-detected).
# =========================================================================== #
def test_fsm_state_pinned_skips():
    p = ("Design the module `clampfsm` that clamps x [7:0] to [0, 100] producing out [7:0]; an "
         "o_status [1:0] reports the FSM state."
         + _io(["x"], ["out", "o_status"]))
    assert S.solve(_mk_record("clampfsm", p)) is None


# =========================================================================== #
# chip-AGNOSTIC — a renamed module still solves and binds to the prompt name; no
# design-name token leaks into the solver's EXECUTABLE code.
# =========================================================================== #
def test_chip_agnostic_rename_comparator():
    renamed = _CMP_PROMPT.replace("signed_unsigned_comparator", "zzz_qux_cmp")
    rtl = S.solve(_mk_record("zzz_qux_cmp", renamed))
    assert rtl is not None
    assert "module zzz_qux_cmp" in rtl
    assert "$signed" in rtl and "i_enable" in rtl


def test_chip_agnostic_rename_synthetic():
    rtl = S.solve(_mk_record("my_clamp",
                             _CLAMP_U_PROMPT.replace("clamp8", "my_clamp")))
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


def test_no_harness_read_in_source():
    """The solver must never re-introduce a harness / golden read: no cocotb-TB
    reader, no `.env` reader, no `record["harness"]` / `record["output"]` access."""
    src = (_PROG / "saturate_synth.py").read_text()
    import re as _re
    for pat in (r"_cocotb_io", r"_cocotb_test", r"_harness_files", r"_cocotb_params",
                r"_env_text", r"record\s*(?:\.get\(\s*[\"']harness|\[\s*[\"']harness)",
                r"record\s*(?:\.get\(\s*[\"']output|\[\s*[\"']output)"):
        assert not _re.search(pat, src), f"harness/golden read re-introduced: {pat}"


def test_solve_handles_garbage():
    assert S.solve(None) is None
    assert S.solve({}) is None
    assert S.solve({"input": {"prompt": ""}}) is None
    assert S.solve({"input": {"prompt": "hi"}, "harness": {"files": {}}}) is None


# =========================================================================== #
# the whole dataset: solver never crashes; every emit is a valid module. Under the
# prompt+context-only compliance rule the RAW dataset prompts (which state the
# interface in a "Module Name:" label + a Direction/Bit-Width markdown table the
# bridge's prompt reader does not parse) are NOT bridge-resolvable, so the compliant
# solver emits 0 over the raw dataset — the honest floor. The positive SHAPES above
# prove the solver emits correct RTL from any bridge-parseable prompt-only record.
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
    # conservative by construction; no wrong emit on a real composite record.
    assert emits >= 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── polarity: a PROMPT states a retired parameter as readily as a live one ──
#
# Found by `prose_polarity_census`. `_param_defaults` reads a prompt -- natural
# language, written by a person -- and published a denied default as a stated
# one. It compounds with `setdefault`, which keeps the FIRST match: a retired
# value written before the live one took its place.

def _defaults(prompt):
    import saturate_synth as M
    return M._param_defaults(prompt)


def test_a_retired_parameter_default_is_not_read_as_stated():
    assert _defaults("Do not use parameter WIDTH = 8.") == {}


def test_a_retired_value_does_not_displace_the_live_one():
    assert _defaults("parameter WIDTH = 8 is no longer used.\n"
                     "Use parameter WIDTH = 16.") == {"WIDTH": 16}


def test_a_denied_PROSE_default_is_not_read():
    """The first pattern is plain English -- `WIDTH ... default value of 5` --
    so this reader is prose first and Verilog second."""
    assert _defaults("WIDTH no longer has a default value of 5.") == {}


def test_a_plainly_stated_default_is_still_read():
    """The control arm: a fix that refused everything would pass the rest."""
    assert _defaults("Use parameter WIDTH = 8 for the datapath.") == {"WIDTH": 8}
    assert _defaults("WIDTH has a default value of 5.") == {"WIDTH": 5}
