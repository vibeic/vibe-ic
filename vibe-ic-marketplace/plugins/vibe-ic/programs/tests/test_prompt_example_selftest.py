#!/usr/bin/env python3
"""Tests for prompt_example_selftest.py — RUN the prompt's own worked examples
as a blind, deterministic self-test against the authored RTL.

Run:  python3 -m pytest test_prompt_example_selftest.py -q
(or)  python3 test_prompt_example_selftest.py

Cases (mirror the program contract):
  (a) combinational worked-arithmetic  — CORRECT RTL PASSes, WRONG RTL FAILs;
  (b) cycle-table (sequential)         — CORRECT RTL PASSes, WRONG RTL FAILs;
  (c) unextractable prompt             — SKIP (no false block, exit 0);
  (d) ports-don't-map                  — SKIP (no false block, exit 0);
  (e) Observed-vs-Expected table       — a correct design whose "Observed"
      column differs from "Expected" is NOT blocked (we assert Expected only);
  (f) cache-lru shape (unlisted input) — SKIP (output may depend on it);
  (g) iverilog absent                  — graceful SKIP, exit 0.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "prompt_example_selftest.py"
sys.path.insert(0, str(_PROGRAMS))

import prompt_example_selftest as P  # noqa: E402

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)
_skip_no_iv = pytest.mark.skipif(not _HAVE_IVERILOG,
                                 reason="iverilog/vvp not installed")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
_MULT_PROMPT = "Module mult. Example: 6 * 7 = 42. Inputs a[7:0], b[7:0]; output [15:0] p.\n"
_MULT_OK = ("module mult(input [7:0] a, input [7:0] b, output [15:0] p);\n"
            "  assign p = a * b;\nendmodule\n")
_MULT_BAD = ("module mult(input [7:0] a, input [7:0] b, output [15:0] p);\n"
             "  assign p = a + b;\nendmodule\n")

_ACC_PROMPT = (
    "Accumulator acc adds input x to a running sum each clock.\n\n"
    "| Cycle | x | sum (Expected) |\n"
    "|-------|---|----------------|\n"
    "| 0     | 1 | 1              |\n"
    "| 1     | 2 | 3              |\n"
    "| 2     | 3 | 6              |\n")
_ACC_OK = ("module acc(input clk, input rst, input [3:0] x, output reg [7:0] sum);\n"
           "  always @(posedge clk or posedge rst)\n"
           "    if (rst) sum <= 0; else sum <= sum + x;\nendmodule\n")
_ACC_BAD = ("module acc(input clk, input rst, input [3:0] x, output reg [7:0] sum);\n"
            "  always @(posedge clk or posedge rst)\n"
            "    if (rst) sum <= 0; else sum <= x;\nendmodule\n")


def _run_api(prompt, rtl, top, latency=None):
    return P.run_selftest(prompt, rtl, top, latency=latency)


def _run_cli(tmp_path, prompt, rtl, top, suffix=".v", env=None):
    p = tmp_path / "p.txt"
    r = tmp_path / ("dut" + suffix)
    p.write_text(prompt)
    r.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(p), "--rtl", str(r),
         "--top", top], capture_output=True, text=True, env=env)


# --------------------------------------------------------------------------
# (a) combinational worked-arithmetic
# --------------------------------------------------------------------------
@_skip_no_iv
def test_a_arith_correct_passes():
    res = _run_api(_MULT_PROMPT, _MULT_OK, "mult")
    assert res.verdict == "PASS", res
    assert res.shape == "arithmetic" and res.ran and res.vectors == 1


@_skip_no_iv
def test_a_arith_wrong_fails():
    res = _run_api(_MULT_PROMPT, _MULT_BAD, "mult")
    assert res.verdict == "FAIL", res
    assert res.failures, "a real mismatch must populate failures"


@_skip_no_iv
def test_a_arith_cli_exit_codes(tmp_path):
    ok = _run_cli(tmp_path, _MULT_PROMPT, _MULT_OK, "mult")
    bad = _run_cli(tmp_path, _MULT_PROMPT, _MULT_BAD, "mult")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert bad.returncode == 1, bad.stdout + bad.stderr


# --------------------------------------------------------------------------
# (b) cycle-table (sequential, clocked)
# --------------------------------------------------------------------------
@_skip_no_iv
def test_b_table_correct_passes():
    res = _run_api(_ACC_PROMPT, _ACC_OK, "acc")
    assert res.verdict == "PASS", res
    assert res.shape == "table" and res.vectors == 3


@_skip_no_iv
def test_b_table_wrong_fails():
    res = _run_api(_ACC_PROMPT, _ACC_BAD, "acc")
    assert res.verdict == "FAIL", res


# --------------------------------------------------------------------------
# (c) unextractable prompt -> SKIP (no false block)
# --------------------------------------------------------------------------
def test_c_no_example_skips():
    res = _run_api("Design a module foo. No worked example here.\n",
                   _ACC_OK, "acc")
    assert res.verdict == "SKIP" and res.shape == "none", res


def test_c_cli_no_example_exit0(tmp_path):
    r = _run_cli(tmp_path, "Just prose, no example.\n", _ACC_OK, "acc")
    assert r.returncode == 0


# --------------------------------------------------------------------------
# (d) ports-don't-map -> SKIP (ambiguous: 3 data inputs for a binary op)
# --------------------------------------------------------------------------
def test_d_ambiguous_ports_skip():
    rtl = ("module m3(input [7:0] a, input [7:0] b, input [7:0] c2, "
           "output [15:0] p);\n assign p = a * b;\nendmodule\n")
    res = _run_api("Example: 6 * 7 = 42.\n", rtl, "m3")
    assert res.verdict == "SKIP", res
    assert any("not 2->1" in s or "ambiguous" in s for s in res.skips)


def test_d_names_dont_resolve_skip():
    # named example whose names match NO port, no operator form either
    rtl = ("module q(input [7:0] foo, input [7:0] bar, output [7:0] baz);\n"
           " assign baz = foo + bar;\nendmodule\n")
    res = _run_api("Example: alpha=3 -> beta=7.\n", rtl, "q")
    assert res.verdict == "SKIP", res


# --------------------------------------------------------------------------
# (e) Observed-vs-Expected: assert Expected, ignore Observed -> no false block
# --------------------------------------------------------------------------
_OE_PROMPT = (
    "The table shows expected vs the buggy observed behaviour.\n\n"
    "| Cycle | x | sum (Expected) | sum (Observed) |\n"
    "|-------|---|----------------|----------------|\n"
    "| 0     | 1 | 1              | 9              |\n"
    "| 1     | 2 | 3              | 9              |\n"
    "| 2     | 3 | 6              | 9              |\n")


@_skip_no_iv
def test_e_observed_column_ignored_no_false_block():
    # The correct RTL produces the EXPECTED column (1,3,6), never the Observed
    # (9,9,9). It must PASS — proving the Observed column is not asserted.
    res = _run_api(_OE_PROMPT, _ACC_OK, "acc")
    assert res.verdict == "PASS", res
    assert res.vectors == 3


# --------------------------------------------------------------------------
# (f) cache-lru shape: a module input not listed in the table -> SKIP
# --------------------------------------------------------------------------
def test_f_unlisted_input_skips():
    prompt = (
        "| Cycle | access | hit | way_replace (Expected) |\n"
        "|-------|--------|-----|------------------------|\n"
        "| 0     | 1      | 1   | 1                      |\n"
        "| 1     | 1      | 0   | 3                      |\n")
    rtl = ("module fp(input clock, input reset, input [4:0] index, "
           "input access, input hit, output [1:0] way_replace);\n"
           " assign way_replace = 2'b0;\nendmodule\n")
    res = _run_api(prompt, rtl, "fp")
    assert res.verdict == "SKIP", res
    assert any("not in the table" in s for s in res.skips)


# --------------------------------------------------------------------------
# (g) iverilog absent -> graceful SKIP (extraction still happened)
# --------------------------------------------------------------------------
def test_g_iverilog_absent_graceful(monkeypatch):
    monkeypatch.setattr(P.shutil, "which", lambda _x: None)
    res = _run_api(_MULT_PROMPT, _MULT_OK, "mult")
    assert res.verdict == "SKIP"
    assert res.vectors == 1 and "iverilog" in res.reason


# --------------------------------------------------------------------------
# pure-unit: value parsing + Observed/Expected column resolution
# --------------------------------------------------------------------------
def test_unit_value_parsing():
    assert P._lit_to_int("0x57") == 0x57
    assert P._lit_to_int("8'hFF") == 255
    assert P._lit_to_int("4'b1010") == 10
    assert P._lit_to_int("-3") == -3
    assert P._lit_to_int("8'hxx") is None            # unknown bits -> None
    assert P._cell_value("Updated (0x02)") == 0x02   # prose + one literal
    assert P._cell_value("Unchanged") == "DONTCARE"
    assert P._cell_value("3 or 5") is None           # two distinct -> drop


def test_unit_arith_no_recompute_uses_stated_result():
    # Galois trap: `*` is GF-multiply, 0x57*0x13 == 0xFE in the prompt though
    # integer 0x57*0x13 != 0xFE. We must assert the STATED 0xFE, never compute.
    ins = [P.PortModel("a", 8, False), P.PortModel("b", 8, False)]
    outs = [P.PortModel("p", 8, False)]
    vecs, _skips, _sw = P.extract_arith_vectors(
        "Example: if a multiplication, 0x57 * 0x13 = 0xFE.\n", ins, outs)
    assert len(vecs) == 1
    assert vecs[0].expected["p"] == 0xFE     # stated, not recomputed


# --------------------------------------------------------------------------
# (h) STATED-CONSTANT input: a config/key operand pinned by prose is driven as
#     a held constant so a `c = (a op b) op key` design with an extra fixed
#     input still maps fully and runs (CORRECT PASSes / WRONG FAILs).
# --------------------------------------------------------------------------
_CONST_PROMPT = ("Module secure. The key is fixed at 5.\n"
                 "Example: a=3, b=4 -> out=2.\n")          # (3+4)^5 == 2
_CONST_OK = ("module secure(input [7:0] a, input [7:0] b, input [7:0] key,\n"
             " output [7:0] out);\n assign out = (a + b) ^ key;\nendmodule\n")
_CONST_BAD = ("module secure(input [7:0] a, input [7:0] b, input [7:0] key,\n"
              " output [7:0] out);\n assign out = a + b;\nendmodule\n")


def test_h_unit_extract_stated_constant_exact_name():
    ins = [P.PortModel("a", 8, False), P.PortModel("b", 8, False),
           P.PortModel("key", 8, False)]
    assert P.extract_stated_constants(_CONST_PROMPT, ins) == {"key": 5}
    # no fuzzy mapping: a value with no matching port name is dropped
    assert P.extract_stated_constants("the gain is fixed at 9.\n", ins) == {}


@_skip_no_iv
def test_h_stated_constant_correct_passes():
    res = _run_api(_CONST_PROMPT, _CONST_OK, "secure")
    assert res.verdict == "PASS", res
    assert res.ran and res.vectors == 1


@_skip_no_iv
def test_h_stated_constant_wrong_fails():
    res = _run_api(_CONST_PROMPT, _CONST_BAD, "secure")
    assert res.verdict == "FAIL", res
    assert res.failures


# --------------------------------------------------------------------------
# (i) >2-input table: EVERY listed column maps to its port (no 2-in/1-out bail).
# --------------------------------------------------------------------------
_ADD3_PROMPT = ("Three-input adder add3.\n\n"
                "| a | b | c | sum (Expected) |\n"
                "|---|---|---|----------------|\n"
                "| 1 | 2 | 3 | 6 |\n"
                "| 4 | 5 | 6 | 15 |\n")
_ADD3_OK = ("module add3(input [7:0] a, input [7:0] b, input [7:0] c,\n"
            " output [9:0] sum);\n assign sum = a + b + c;\nendmodule\n")
_ADD3_BAD = ("module add3(input [7:0] a, input [7:0] b, input [7:0] c,\n"
             " output [9:0] sum);\n assign sum = a + b;\nendmodule\n")


@_skip_no_iv
def test_i_multi_input_table_correct_passes():
    res = _run_api(_ADD3_PROMPT, _ADD3_OK, "add3")
    assert res.verdict == "PASS", res
    assert res.shape == "table" and res.vectors == 2


@_skip_no_iv
def test_i_multi_input_table_wrong_fails():
    res = _run_api(_ADD3_PROMPT, _ADD3_BAD, "add3")
    assert res.verdict == "FAIL", res


# --------------------------------------------------------------------------
# (j) BINARY column: a zero-padded 0/1 table reads base-2, not decimal — so a
#     correct excess-3 (`0000`->`0011`) is NOT false-blocked as 0->11.
# --------------------------------------------------------------------------
_BCD_PROMPT = ("Excess-3 combinational.\n\n"
               "| x | y (Expected) |\n"
               "|------|------|\n"
               "| 0000 | 0011 |\n"
               "| 1001 | 1100 |\n")
_BCD_OK = "module e3(input [3:0] x, output [3:0] y);\n assign y = x + 3;\nendmodule\n"
_BCD_BAD = "module e3(input [3:0] x, output [3:0] y);\n assign y = x;\nendmodule\n"


def test_j_unit_column_base():
    assert P._column_base(["0000", "1001", "1100"], 4) == "bin"   # zero-padded
    assert P._column_base(["1000", "10"], 4) == "bin"             # 1000 o'flows dec
    assert P._column_base(["7FFFFFFF", "A1B2C3D4", "00000000"], 32) == "hex"
    assert P._column_base(["10", "20", "30"], 8) == "dec"         # plain decimal
    assert P._column_base(["0x10", "0x20"], 8) == "dec"           # self-declared
    assert P._cell_value("0011", "bin") == 3
    assert P._cell_value("FE", "hex") == 0xFE
    assert P._cell_value("0x12", "bin") == 0x12                   # self-declared wins


@_skip_no_iv
def test_j_binary_column_correct_passes():
    res = _run_api(_BCD_PROMPT, _BCD_OK, "e3")
    assert res.verdict == "PASS", res


@_skip_no_iv
def test_j_binary_column_wrong_fails():
    res = _run_api(_BCD_PROMPT, _BCD_BAD, "e3")
    assert res.verdict == "FAIL", res


# --------------------------------------------------------------------------
# (k) PARAMETER-WIDTH guard: an example mapping to a parameter-width port may
#     assume non-default parameters -> SKIP (advisory), never a false block.
# --------------------------------------------------------------------------
def test_k_param_width_port_skips():
    prompt = ("Adder.\n\n| a | b | s (Expected) |\n|---|---|---|\n"
              "| 1 | 2 | 3 |\n| 3 | 4 | 7 |\n")
    rtl = ("module padd #(parameter W=8)(input [W-1:0] a, input [W-1:0] b,\n"
           " output [W-1:0] s);\n assign s = a + b;\nendmodule\n")
    res = _run_api(prompt, rtl, "padd")
    assert res.verdict == "SKIP", res
    assert any("parameter" in s.lower() for s in [res.reason])


# --------------------------------------------------------------------------
# (l) RESET-NAME generalization: rst_async_n is recognized as the reset (driven
#     by the reset sequence, not mistaken for an unlisted data input).
# --------------------------------------------------------------------------
_RSTN_PROMPT = ("Accumulator.\n\n| Cycle | x | sum (Expected) |\n|--|--|--|\n"
                "| 0 | 1 | 1 |\n| 1 | 2 | 3 |\n| 2 | 3 | 6 |\n")
_RSTN_OK = ("module acc2(input clk, input rst_async_n, input [3:0] x,\n"
            " output reg [7:0] sum);\n always @(posedge clk or negedge rst_async_n)\n"
            "  if(!rst_async_n) sum<=0; else sum<=sum+x;\nendmodule\n")


def test_l_unit_reset_name_general():
    for nm in ("rst_async_n", "rst_sync_n", "async_rst_n", "resetb", "arst_n",
               "rst_n", "reset", "nreset"):
        assert P._is_rst(nm), nm
    for nm in ("reset_value", "first", "burst", "data", "wstrb_reset_count"):
        assert not P._is_rst(nm), nm


@_skip_no_iv
def test_l_rst_async_n_recognized_passes():
    res = _run_api(_RSTN_PROMPT, _RSTN_OK, "acc2")
    assert res.verdict == "PASS", res
    assert res.shape == "table" and res.vectors == 3


@_skip_no_iv
def test_l_rst_async_n_wrong_fails():
    res = _run_api(_RSTN_PROMPT, _RSTN_OK.replace("sum<=sum+x", "sum<=x"), "acc2")
    assert res.verdict == "FAIL", res


# --------------------------------------------------------------------------
# (m) TRIGGER guard: a clocked arithmetic example with an un-timed start/valid
#     handshake -> SKIP (cannot reproduce the pulse), never a false block.
# --------------------------------------------------------------------------
#     The gate is on because the assertion is about WHICH skip: without iverilog
#     the selftest skips for a different and equally correct reason ("iverilog/vvp
#     not on PATH"), so `"handshake" in res.reason` failed on a host that simply
#     could not run the check (vibe-ic#1357). Every other simulating test in this
#     file already carries this marker; this one was missed.
@_skip_no_iv
def test_m_untimed_trigger_skips():
    prompt = "Pipelined mult. Example: 6 * 7 = 42.\n"
    rtl = ("module pm(input clk, input start, input [7:0] a, input [7:0] b,\n"
           " output reg [15:0] p);\n always @(posedge clk) if(start) p<=a*b;\n"
           "endmodule\n")
    res = _run_api(prompt, rtl, "pm")
    assert res.verdict == "SKIP", res
    assert "handshake" in res.reason or "trigger" in res.reason.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
