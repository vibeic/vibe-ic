#!/usr/bin/env python3
"""ORGANIC #755 — latency_conformance_check: based-literal/$clog2 param
defaults, multi-file --context, and the synchronous-clear + multi-bit-event
TIMEOUT false-positive.

These tests pin the THREE confirmed defects (and their §4.05 no-leak guards)
that #755 fixes against the shipped 1.0.81/1.0.82 gate:

  D1 PARAM-DEFAULT PARSE — `safe_eval_arith` chokes on Verilog based literals
     (`'d128`, `8'hFF`) and `$clog2(...)`; `resolve_params` then silently
     DROPPED those params so the generated TB kept `[NBW-1:0]` verbatim →
     iverilog 'Unable to bind parameter' rc 2. FIX: normalise based literals to
     decimal + whitelist a side-effect-free `$clog2`.
  D2 MULTI-FILE — `measure_latency` compiled `--rtl` alone, so a DUT that
     instantiates a prompt-provided submodule failed 'Unknown module type'
     rc 2. FIX: an opt-in `--context FILE` (repeatable, dir-expanding) compiled
     ALONGSIDE --rtl; with --rtl alone the behaviour is byte-identical.
  D3 TIMEOUT FALSE-POSITIVE — `classify_ports` did not treat a synchronous
     CLEAR (`clr`/`clear`/`flush`) as reset-class (pinned all-ones, permanently
     flushing the pipe) AND drove a multi-bit event vector with scalar `1'b1`
     (LSB only) → a consensus/AND-reduction output never asserted → false
     LATENCY-TIMEOUT. FIX: a NARROW name-anchored clear-class held inactive +
     drive a multi-bit event all-ones.

§4.05 no-leak guards in here: the clear-class is NARROW (a data input merely
CONTAINING 'clr' is NOT held inactive); the $clog2 whitelist REJECTS any other
function call / attribute access; and --rtl-alone behaviour is unchanged.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import latency_conformance_check as lcc  # noqa: E402

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)
_iverilog = pytest.mark.skipif(
    not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")


# ─── D1 — based-literal / $clog2 param-default parse (pure, no iverilog) ──────
def test_safe_eval_based_decimal_literal():
    assert lcc.safe_eval_arith("'d128", {}) == 128
    assert lcc.safe_eval_arith("8'hFF", {}) == 255
    assert lcc.safe_eval_arith("4'b1010", {}) == 10
    assert lcc.safe_eval_arith("'hDEAD_BEEF", {}) == 0xDEADBEEF
    # a based literal embedded in arithmetic over a param
    assert lcc.safe_eval_arith("NBW-1", {"NBW": 128}) == 127


def test_safe_eval_clog2_whitelist_values():
    assert lcc.safe_eval_arith("$clog2(256)", {}) == 8
    assert lcc.safe_eval_arith("$clog2(33)", {}) == 6
    assert lcc.safe_eval_arith("$clog2(32)", {}) == 5
    # $clog2(0)=$clog2(1)=0 per the Verilog definition
    assert lcc.safe_eval_arith("$clog2(1)", {}) == 0
    assert lcc.safe_eval_arith("$clog2(0)", {}) == 0
    # composes with arithmetic and a param
    assert lcc.safe_eval_arith("$clog2(W)+1", {"W": 256}) == 9


def test_clog2_helper_definition():
    assert lcc._clog2(0) == 0
    assert lcc._clog2(1) == 0
    assert lcc._clog2(2) == 1
    assert lcc._clog2(32) == 5
    assert lcc._clog2(33) == 6


def test_xz_literal_left_verbatim_rejected_honestly():
    # an x/z don't-care literal is NOT a resolvable constant; the normaliser
    # leaves it verbatim so the AST step rejects it (an apostrophe is not valid
    # Python) rather than silently resolving to a bogus number.
    with pytest.raises(lcc.ExpectError):
        lcc.safe_eval_arith("8'hXX", {})
    with pytest.raises(lcc.ExpectError):
        lcc.safe_eval_arith("4'bzz", {})


def test_resolve_params_based_literal_default():
    rtl = ("module a #(parameter NBW = 'd128, parameter AW = 8'h10)"
           "(input clk, input start, input [NBW-1:0] x, output reg done);"
           "always @(posedge clk) done <= start; endmodule")
    params = lcc.resolve_params(rtl, "a", {})
    # pre-fix: BOTH dropped (ast.parse threw on the apostrophe) → verbatim width
    assert params.get("NBW") == 128
    assert params.get("AW") == 0x10


def test_resolve_params_clog2_default():
    rtl = ("module m #(parameter DEPTH = 256, "
           "parameter ADDR_W = $clog2(DEPTH))"
           "(input clk, input start, input [ADDR_W-1:0] a, output reg q);"
           "always @(posedge clk) q <= start; endmodule")
    params = lcc.resolve_params(rtl, "m", {})
    assert params.get("DEPTH") == 256
    assert params.get("ADDR_W") == 8  # $clog2(256)


# ─── §4.05 — the $clog2 whitelist is TIGHT (no arbitrary code) ────────────────
@pytest.mark.parametrize("bad", [
    '__import__("os")',
    'open("/etc/passwd")',
    'eval("1")',
    'foo(1)',             # a non-whitelisted function name
    'os.system("x")',     # attribute access
    'clog2(2, 3)',        # wrong arity
    'clog2()',            # wrong arity
])
def test_disallowed_calls_and_attrs_raise(bad):
    with pytest.raises(lcc.ExpectError):
        lcc.safe_eval_arith(bad, {})


# ─── §4.05 — the clear-class is NARROW (name-anchored, not substring) ─────────
def test_clear_class_exact_names_only():
    for nm in ("clr", "clear", "flush", "sclr", "aclr", "clrn", "clr_n",
               "clear_n", "clra", "clrb"):
        assert lcc._looks_like_clear(nm), nm
        assert lcc._looks_like_reset(nm), nm  # reset-class for measurement
    # an ordinary DATA input that merely CONTAINS 'clr'/'clear' as a substring
    # must NOT be treated as a clear (would be wrongly held inactive).
    for nm in ("clr_data", "clrcnt", "color", "declared", "nuclear",
               "clear_count", "flusher", "sclr_value"):
        assert not lcc._looks_like_clear(nm), nm


def test_data_input_with_clr_substring_not_held_inactive():
    # classify_ports must keep a 'clr_data' DATA input in `others`
    # (constant-driven), NOT in `resets` (held inactive).
    ports = [("input", "", "clk"), ("input", "", "start"),
             ("input", "[7:0]", "clr_data"), ("output", "", "done")]
    clk, resets, ev, out, others = lcc.classify_ports(
        ports, "start", "done", None)
    other_names = [o.name for o in others]
    reset_names = [r.name for r in resets]
    assert "clr_data" in other_names
    assert "clr_data" not in reset_names


def test_clear_held_inactive_even_with_explicit_reset_override():
    # an explicit --reset names `rst`, but a sibling `clr` (clear-class) must
    # STILL be held inactive — leaving it all-ones would flush the pipe.
    ports = [("input", "", "clk"), ("input", "", "rst"), ("input", "", "clr"),
             ("input", "", "start"), ("output", "", "done")]
    clk, resets, ev, out, others = lcc.classify_ports(
        ports, "start", "done", "rst")
    reset_names = [r.name for r in resets]
    assert "rst" in reset_names
    assert "clr" in reset_names           # clear pulled into reset-class
    assert "clr" not in [o.name for o in others]


# ─── D3 — multi-bit event is driven ALL-ONES, scalar stays 1'b1 ──────────────
def test_multibit_event_all_ones_in_tb():
    ports = [("input", "", "clk"), ("input", "", "clr"),
             ("input", "[3:0]", "inp"), ("output", "", "out")]
    clk, resets, ev, out, others = lcc.classify_ports(ports, "inp", "out", None)
    ralm = {r.name: lcc._reset_is_active_low(r.name) for r in resets}
    tb = lcc.build_measurement_tb("mc", clk, resets, ev, out, others,
                                  ralm, -1, 64, params={})
    # multi-bit event asserted with a replication, not a scalar
    assert "{1'b1}}" in tb and "inp = 1'b1;" not in tb
    # clr is deasserted (held inactive) during measurement
    assert "clr = 1'b0;" in tb


def test_scalar_event_stays_plain_1b1():
    ports = [("input", "", "clk"), ("input", "", "start"),
             ("output", "", "done")]
    clk, resets, ev, out, others = lcc.classify_ports(
        ports, "start", "done", None)
    tb = lcc.build_measurement_tb("m", clk, resets, ev, out, others,
                                  {}, -1, 64, params={})
    assert "start = 1'b1;" in tb  # a scalar event is plain 1'b1


# ─── D3 end-to-end — consensus DUT (multi-bit event + clr) now PASSes ─────────
_CONSENSUS = """
module mc #(parameter N = 4)(input clk, input rst, input clr,
                             input [N-1:0] inp, output reg out);
  reg stage;
  always @(posedge clk) begin
    if (rst || clr) begin stage <= 1'b0; out <= 1'b0; end
    else            begin stage <= &inp;  out <= stage; end
  end
endmodule
"""


@_iverilog
def test_consensus_clr_multibit_measures_pipe_depth_plus1(tmp_path):
    rtl = tmp_path / "mc.sv"
    rtl.write_text(_CONSENSUS)
    # PIPE_DEPTH = 1 (stage), so event->out latency is PIPE_DEPTH+1 = 2.
    rc, rep = lcc.run_latency_conformance(
        rtl, "mc", "inp", "out", "2", {}, None, None, -1, None)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 2
    # clr was pulled into the reset-class (held inactive), not held constant
    assert "clr" in rep["resets"]


@_iverilog
def test_consensus_via_main_cli(tmp_path):
    rtl = tmp_path / "mc.sv"
    rtl.write_text(_CONSENSUS)
    rc = lcc.main(["--rtl", str(rtl), "--top", "mc", "--event", "inp",
                   "--output", "out", "--expect", "2"])
    assert rc == 0


# ─── D1 end-to-end — based-literal param default now compiles/PASSes ──────────
@_iverilog
def test_based_literal_param_default_compiles_and_passes(tmp_path):
    rtl = tmp_path / "a.sv"
    rtl.write_text(
        "module a #(parameter NBW = 'd128)"
        "(input clk, input rst_n, input start, input [NBW-1:0] x,"
        " output reg done);\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) done <= 1'b0; else done <= start;\n"
        "endmodule\n")
    rc, rep = lcc.run_latency_conformance(
        rtl, "a", "start", "done", "1", {}, None, None, -1, None)
    # pre-fix: NBW dropped → [NBW-1:0] verbatim → 'Unable to bind parameter' rc2
    assert rep["resolved_params"].get("NBW") == 128
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 1


# ─── D2 — multi-file --context resolves an instantiated submodule ─────────────
_LZC_SUB = """
module lzc(input [3:0] v, output reg z);
  always @(*) z = (v == 4'b0000);
endmodule
"""
_DUT_WITH_SUB = """
module top(input clk, input rst, input start, input [3:0] data, output reg done);
  wire is_zero;
  lzc u_lzc(.v(data), .z(is_zero));
  always @(posedge clk) if (rst) done <= 1'b0; else done <= start & ~is_zero;
endmodule
"""


@_iverilog
def test_multifile_context_resolves_submodule(tmp_path):
    rtl = tmp_path / "top.sv"
    rtl.write_text(_DUT_WITH_SUB)
    sub = tmp_path / "lzc.sv"
    sub.write_text(_LZC_SUB)
    # WITHOUT --context: 'Unknown module type' → compile ERROR rc 2.
    rc_no = lcc.main(["--rtl", str(rtl), "--top", "top", "--event", "start",
                      "--output", "done", "--expect", "1"])
    assert rc_no == 2  # cannot elaborate the unresolved submodule
    # WITH --context: the submodule resolves and the gate reaches a verdict.
    out = tmp_path / "rep.json"
    rc_ctx = lcc.main(["--rtl", str(rtl), "--top", "top", "--event", "start",
                       "--output", "done", "--expect", "1",
                       "--context", str(sub), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc_ctx == 0 and rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 1
    assert str(sub) in rep["context_files"]


@_iverilog
def test_context_dir_expands_and_skips_rtl_itself(tmp_path):
    rtl = tmp_path / "top.sv"
    rtl.write_text(_DUT_WITH_SUB)
    sub = tmp_path / "lzc.sv"
    sub.write_text(_LZC_SUB)
    # a directory --context expands to its .v/.sv, never duplicating --rtl
    out = tmp_path / "rep.json"
    rc = lcc.main(["--rtl", str(rtl), "--top", "top", "--event", "start",
                   "--output", "done", "--expect", "1",
                   "--context", str(tmp_path), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 0 and rep["verdict"] == "PASS"
    # the --rtl file itself is NOT duplicated in the context list
    ctx = [Path(p).resolve() for p in rep["context_files"]]
    assert rtl.resolve() not in ctx
    assert sub.resolve() in ctx


def test_context_not_found_errors(tmp_path):
    rtl = tmp_path / "a.sv"
    rtl.write_text("module a(input clk, input start, output reg done);\n"
                   "always @(posedge clk) done <= start; endmodule\n")
    rc = lcc.main(["--rtl", str(rtl), "--top", "a", "--event", "start",
                   "--output", "done", "--expect", "1",
                   "--context", str(tmp_path / "nope.sv")])
    assert rc == 2


# ─── §4.05 — --rtl-alone behaviour is UNCHANGED (byte-identical) ──────────────
@_iverilog
def test_rtl_alone_behaviour_unchanged(tmp_path):
    # a plain 2-stage shift-register DUT (no clear, scalar event, single file):
    # all three fixes are inert → the report must be exactly what shipped emits.
    rtl = tmp_path / "sr.sv"
    rtl.write_text(
        "module sr(input clk, input rst_n, input start, output reg done);\n"
        "  reg r;\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) begin r <= 1'b0; done <= 1'b0; end\n"
        "    else begin r <= start; done <= r; end\n"
        "endmodule\n")
    rc, rep = lcc.run_latency_conformance(
        rtl, "sr", "start", "done", "2", {}, None, None, -1, None)
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 2  # 2-stage shift reg ⇒ exactly 2
    # no context, no clear, scalar event held constant set is unchanged
    assert rep["context_files"] == []
    assert rep["resets"] == ["rst_n"]


# ─── §4.05 — a REAL latency MISMATCH still hard-BLOCKS (no leak) ──────────────
@_iverilog
def test_real_mismatch_still_blocks(tmp_path):
    rtl = tmp_path / "sr.sv"
    rtl.write_text(
        "module sr(input clk, input rst_n, input start, output reg done);\n"
        "  reg r;\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) begin r <= 1'b0; done <= 1'b0; end\n"
        "    else begin r <= start; done <= r; end\n"
        "endmodule\n")
    # the design is 2-cycle; claim 1 → must MISMATCH rc 1, not silently pass.
    rc, rep = lcc.run_latency_conformance(
        rtl, "sr", "start", "done", "1", {}, None, None, -1, None)
    assert rc == 1 and rep["verdict"] == "MISMATCH"


# ─── §4.05 — a REAL TIMEOUT still fires (output never asserts) ────────────────
@_iverilog
def test_real_timeout_still_fires(tmp_path):
    # an output that NEVER asserts (tied low) must still TIMEOUT rc 1 — the
    # clear/event fixes must not paper over a genuinely stuck design.
    rtl = tmp_path / "stuck.sv"
    rtl.write_text(
        "module stuck(input clk, input rst, input start, output done);\n"
        "  assign done = 1'b0;\n"
        "endmodule\n")
    rc, rep = lcc.run_latency_conformance(
        rtl, "stuck", "start", "done", "2", {}, None, None, -1, None)
    assert rc == 1 and rep["verdict"] == "TIMEOUT"


# ─── §4.05 — precondition-high (idle-high output) still refused ───────────────
@_iverilog
def test_precondition_high_still_refused(tmp_path):
    # an output that is HIGH out of reset (an idle-high `done`, the AES shape)
    # must still be refused as a meaningless measurement, not papered to PASS.
    rtl = tmp_path / "idle.sv"
    rtl.write_text(
        "module idle(input clk, input rst, input start, output reg done);\n"
        "  always @(posedge clk) if (rst) done <= 1'b1; else done <= done;\n"
        "  initial done = 1'b1;\n"
        "endmodule\n")
    rc, rep = lcc.run_latency_conformance(
        rtl, "idle", "start", "done", "1", {}, None, None, -1, None)
    assert rc == 2 and rep["verdict"] == "PRECONDITION_HIGH"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
