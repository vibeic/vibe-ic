#!/usr/bin/env python3
"""ORGANIC #716 / Prob098_circuit7 [P2, chip-AGNOSTIC] — waveform-table
conformance gate.

A "read the simulation waveform, then implement it" prompt (the VerilogEval
circuitN family) embeds a literal ``time [clk] <input...> <output>`` table. A
blind agent that MIS-COUNTS pipeline stages — reading the early X-window (an
input-sampling NBA race) as an EXTRA register stage and authoring a TWO-stage
``q1<=~a; q<=q1`` pipeline where the spec is the ONE-stage ``q<=~a`` — produces
RTL whose self-TB still "passes" but scores 58/123 mismatches on the hidden TB.
``waveform_table_conformance_check.py`` is the independent yard-stick: it replays
the published table the way the scorer compares (X in the table matches anything;
X in the DUT only matches a table X) inside a PROVEN-FAITHFUL envelope, and
BLOCKS on any mismatch.

§4.05 NO-LEAK (load-bearing both directions):
  POSITIVE — the CORRECT one-stage design (and a correct combinational design)
    MUST PASS (emit).
  NEGATIVE — the wrong two-stage pipeline, a missing-inversion register, a wrong
    combinational function, AND a genuinely-accidental incomplete-if latch MUST
    all still BLOCK.
  NO FALSE-BLOCK — designs OUTSIDE the proven-faithful envelope (negedge /
    level-sensitive latch / multi-bit output / multiple observable outputs /
    non-binary table) MUST be SKIPPED (rc 0), never blocked.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "waveform_table_conformance_check.py"

_HAVE_IVERILOG = bool(shutil.which("iverilog") and shutil.which("vvp"))

# --- a single-bit single-clock posedge waveform table (Prob098-style) ----------
# q settles to ~a one posedge after a is sampled; the t<=10 X-window is the input
# NBA race, NOT a second pipeline stage.
_SEQ_TABLE = (
    "This is a sequential circuit. Read the simulation waveforms.\n\n"
    "  time  clk a   q\n"
    "  0ns   0   x   x\n"
    "  5ns   1   0   x\n"
    "  10ns  0   0   x\n"
    "  15ns  1   0   1\n"
    "  20ns  0   0   1\n"
    "  25ns  1   0   1\n"
    "  30ns  0   0   1\n"
    "  35ns  1   1   1\n"
    "  40ns  0   1   1\n"
    "  45ns  1   1   0\n"
    "  50ns  0   1   0\n"
    "  55ns  1   1   0\n"
    "  60ns  0   1   0\n")

_RTL_ONE_STAGE = (
    "module TopModule(input clk, input a, output reg q);\n"
    "  always @(posedge clk) q <= ~a;\n"
    "endmodule\n")

_RTL_TWO_STAGE = (  # the round-18 FAIL: extra phantom stage
    "module TopModule(input clk, input a, output reg q);\n"
    "  reg q1;\n"
    "  always @(posedge clk) begin q1 <= ~a; q <= q1; end\n"
    "  initial begin q=0; q1=0; end\n"
    "endmodule\n")

_RTL_NO_INVERT = (  # forgot the inversion
    "module TopModule(input clk, input a, output reg q);\n"
    "  always @(posedge clk) q <= a;\n"
    "endmodule\n")

# --- a combinational waveform table (Prob090-style q = a & b) -------------------
_COMB_TABLE = (
    "This is a combinational circuit. Read the simulation waveforms.\n\n"
    "  time  a  b  q\n"
    "  0ns   0  0  0\n"
    "  5ns   0  1  0\n"
    "  10ns  1  0  0\n"
    "  15ns  1  1  1\n"
    "  20ns  0  0  0\n"
    "  25ns  1  1  1\n")

_RTL_COMB_OK = (
    "module TopModule(input a, input b, output q);\n"
    "  assign q = a & b;\n"
    "endmodule\n")

_RTL_COMB_WRONG = (  # wrong function
    "module TopModule(input a, input b, output q);\n"
    "  assign q = a | b;\n"
    "endmodule\n")

_RTL_ACCIDENTAL_LATCH = (  # incomplete-if comb -> accidental latch, wrong fn
    "module TopModule(input a, input b, output reg q);\n"
    "  always @(*) if (a & b) q = 1'b1;\n"
    "endmodule\n")

# --- out-of-envelope designs that MUST be SKIPped (no false-block) --------------
_LATCH_TABLE = (
    "This is a sequential circuit.\n\n"
    "  time  clock a   p   q\n"
    "  0ns   0     1   x   x\n"
    "  5ns   1     1   1   x\n"
    "  10ns  0     0   1   1\n"
    "  15ns  1     0   0   1\n")

_RTL_TRANSPARENT_LATCH = (  # an INTENDED transparent latch + negedge FF
    "module TopModule(input clock, input a, output reg p, output reg q);\n"
    "  always @(negedge clock) q <= a;\n"
    "  always @(*) if (clock) p = a;\n"
    "endmodule\n")

_MULTIBIT_TABLE = (
    "This is a sequential circuit.\n\n"
    "  time  clk a   q\n"
    "  0ns   0   1   x\n"
    "  5ns   1   1   4\n"
    "  10ns  0   1   4\n"
    "  15ns  1   0   4\n"
    "  20ns  0   0   5\n")

_RTL_MULTIBIT = (
    "module TopModule(input clk, input a, output reg [2:0] q);\n"
    "  always @(posedge clk) if (a) q <= 4; else q <= q + 1;\n"
    "endmodule\n")


def _run(tmp_path, table, rtl):
    p = tmp_path / "prompt.txt"
    r = tmp_path / "rtl.sv"
    p.write_text(table)
    r.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(p), "--rtl", str(r),
         "--top", "TopModule"],
        capture_output=True, text=True)


def test_program_exists():
    assert _PROG.exists(), f"missing program: {_PROG}"


# ---------------- POSITIVE: correct designs must PASS (emit) -------------------
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_one_stage_registered_passes(tmp_path):
    r = _run(tmp_path, _SEQ_TABLE, _RTL_ONE_STAGE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WTC_PASS" in r.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_combinational_correct_passes(tmp_path):
    r = _run(tmp_path, _COMB_TABLE, _RTL_COMB_OK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WTC_PASS" in r.stdout


# ---------------- NEGATIVE: wrong designs must BLOCK --------------------------
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_two_stage_pipeline_blocks(tmp_path):
    """The actual round-18 FAIL: phantom extra register stage."""
    r = _run(tmp_path, _SEQ_TABLE, _RTL_TWO_STAGE)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WTC_FAIL" in r.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_missing_inversion_blocks(tmp_path):
    r = _run(tmp_path, _SEQ_TABLE, _RTL_NO_INVERT)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WTC_FAIL" in r.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_wrong_combinational_function_blocks(tmp_path):
    r = _run(tmp_path, _COMB_TABLE, _RTL_COMB_WRONG)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WTC_FAIL" in r.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_accidental_incomplete_if_latch_blocks(tmp_path):
    """A genuinely-accidental latch (incomplete if, no else) computing a wrong
    function MUST still BLOCK — the negative no-leak case."""
    r = _run(tmp_path, _COMB_TABLE, _RTL_ACCIDENTAL_LATCH)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WTC_FAIL" in r.stdout


# ---------------- NO FALSE-BLOCK: out-of-envelope must SKIP -------------------
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_intended_transparent_latch_not_blocked(tmp_path):
    """An INTENDED transparent latch / negedge design (multiple observable
    outputs, level-sensitive) is OUTSIDE the faithful envelope -> SKIP, NEVER a
    false block."""
    r = _run(tmp_path, _LATCH_TABLE, _RTL_TRANSPARENT_LATCH)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WTC_SKIP_" in r.stdout
    assert "WTC_FAIL" not in r.stdout


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp required")
def test_multibit_output_not_blocked(tmp_path):
    """A correct multi-bit (hex-column) design must be SKIPped, never blocked."""
    r = _run(tmp_path, _MULTIBIT_TABLE, _RTL_MULTIBIT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WTC_SKIP_" in r.stdout
    assert "WTC_FAIL" not in r.stdout


def test_no_table_is_skip(tmp_path):
    r = _run(tmp_path, "No waveform here, just prose about a counter.\n",
             _RTL_ONE_STAGE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WTC_NO_TABLE" in r.stdout
