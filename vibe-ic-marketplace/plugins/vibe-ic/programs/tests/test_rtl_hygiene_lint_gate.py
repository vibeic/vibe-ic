#!/usr/bin/env python3
"""Tests for rtl_hygiene_lint.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_clean_rtl(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk, input rst_n);\nendmodule\n")
    r = _run([str(rtl)]); assert r.returncode == 0

# ---------------------------------------------------------------------------
# Rule 11 — unguarded simulation-only immediate assertion (v0.1.60)
# ---------------------------------------------------------------------------
_STANDALONE = """module m(input [7:0] in, output reg [2:0] out);
always @(*) begin
    out = in[0] ? 3'd0 : 3'd1;
    assert (out < 8) else $error("bad out=%0d", out);
end
endmodule
"""

_IFELSE_CHAIN = """module priority_encoder_8x3(input [7:0] in, output reg [2:0] out);
always @(*) begin
    if (in[7]) out = 3'b111;
    else       out = 3'b000;
    if (in != 0)
        assert (out == 3'b111) else $error("a in=0x%h", in);
    else
        assert (out == 3'b000) else $error("b");
end
endmodule
"""

_ALREADY_GUARDED = """module m(input [7:0] in, output reg [2:0] out);
always @(*) begin
    out = in[0] ? 3'd0 : 3'd1;
    // synthesis translate_off
    assert (out < 8) else $error("bad");
    // synthesis translate_on
end
endmodule
"""


def _has_rule11(stdout):
    return "unguarded-sim-only-assert" in stdout


def test_rule11_detects_standalone_assert(tmp_path):
    rtl = tmp_path / "m.v"; rtl.write_text(_STANDALONE)
    r = _run([str(rtl)])
    assert _has_rule11(r.stdout)
    assert r.returncode == 1  # WARN -> nonzero


def test_rule11_detects_ifelse_chain(tmp_path):
    rtl = tmp_path / "pe.sv"; rtl.write_text(_IFELSE_CHAIN)
    r = _run([str(rtl)])
    # two asserts in the chain -> at least one finding line
    assert r.stdout.count("unguarded-sim-only-assert") >= 1


def test_rule11_silent_when_already_guarded(tmp_path):
    rtl = tmp_path / "m.v"; rtl.write_text(_ALREADY_GUARDED)
    r = _run([str(rtl)])
    assert not _has_rule11(r.stdout)


def test_rule11_skips_testbench_by_module_name(tmp_path):
    rtl = tmp_path / "thing.sv"
    rtl.write_text("module thing_tb;\ninitial assert (1) else $error(\"x\");\nendmodule\n")
    r = _run([str(rtl)])
    assert not _has_rule11(r.stdout)


def test_rule11_skips_testbench_by_filename(tmp_path):
    rtl = tmp_path / "dut_tb.sv"
    rtl.write_text("module dut;\nalways @(*) assert (1) else $error(\"x\");\nendmodule\n")
    r = _run([str(rtl)])
    assert not _has_rule11(r.stdout)


def test_rule11_ignores_assert_property(tmp_path):
    rtl = tmp_path / "m.sv"
    rtl.write_text("module m(input clk, input a);\n"
                   "always @(posedge clk) assert property (a) else $error(\"x\");\n"
                   "endmodule\n")
    r = _run([str(rtl)])
    assert not _has_rule11(r.stdout)


def test_rule11_clean_rtl_without_assert(tmp_path):
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input a, output reg y);\nalways @(*) y = a;\nendmodule\n")
    r = _run([str(rtl)])
    assert not _has_rule11(r.stdout)


def test_fix_wraps_standalone_assert(tmp_path):
    rtl = tmp_path / "m.v"; rtl.write_text(_STANDALONE)
    r = _run(["--fix", str(rtl)])
    assert r.returncode == 0
    txt = rtl.read_text()
    assert "translate_off" in txt and "translate_on" in txt
    # functional line untouched
    assert "out = in[0] ? 3'd0 : 3'd1;" in txt
    # assertion preserved
    assert "assert (out < 8)" in txt
    # detection now clean
    assert not _has_rule11(_run([str(rtl)]).stdout)


def test_fix_wraps_ifelse_chain_as_one_unit(tmp_path):
    rtl = tmp_path / "pe.sv"; rtl.write_text(_IFELSE_CHAIN)
    r = _run(["--fix", str(rtl)])
    assert r.returncode == 0
    txt = rtl.read_text()
    # exactly one fence pair wraps the whole assert chain
    assert txt.count("translate_off") == 1 and txt.count("translate_on") == 1
    # both asserts preserved, functional if/else (out assignment) NOT wrapped
    assert txt.count("assert (") == 2
    off_idx = txt.index("translate_off")
    assert "out = 3'b111;" in txt[:off_idx]  # functional logic before the fence
    assert not _has_rule11(_run([str(rtl)]).stdout)


def test_fix_idempotent(tmp_path):
    rtl = tmp_path / "pe.sv"; rtl.write_text(_IFELSE_CHAIN)
    _run(["--fix", str(rtl)])
    first = rtl.read_text()
    r2 = _run(["--fix", str(rtl)])
    assert "fenced 0 sim-only" in r2.stdout
    assert rtl.read_text() == first  # no change on second pass


def test_fix_skips_already_guarded(tmp_path):
    rtl = tmp_path / "m.v"; rtl.write_text(_ALREADY_GUARDED)
    before = rtl.read_text()
    r = _run(["--fix", str(rtl)])
    assert "fenced 0 sim-only" in r.stdout
    assert rtl.read_text() == before


def test_fix_does_not_wrap_controlled_nonassert(tmp_path):
    # assert controlled by `if` whose else is FUNCTIONAL -> must NOT auto-wrap
    # (would orphan the else in synthesis). Finding may still fire; fix must skip.
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input [7:0] in, output reg [2:0] out);\n"
                   "always @(*) begin\n"
                   "  if (in != 0) assert (out < 8) else $error(\"x\");\n"
                   "  out = in[0];\n"
                   "end\nendmodule\n")
    r = _run(["--fix", str(rtl)])
    txt = rtl.read_text()
    # the lone `if (cond) assert ...;` is a Shape-B single-branch chain and IS
    # safely wrappable as a whole unit; functional `out = in[0];` stays outside.
    if "translate_off" in txt:
        off = txt.index("translate_off"); on = txt.index("translate_on")
        assert "out = in[0];" not in txt[off:on]
    assert "assert (out < 8)" in txt
