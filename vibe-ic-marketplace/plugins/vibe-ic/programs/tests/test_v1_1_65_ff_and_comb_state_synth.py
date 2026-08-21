"""v1.1.65 — ff_truth_table_synth + comb_state_table_synth deterministic SOLVERS.

Two more table-artifact families moved bucket-② -> bucket-①:
  * flip-flop truth table with Qold/~Qold cells (JK/D/T/SR) — Prob056_ece241_2013_q7
  * combinational next_state+output from a table + GIVEN encoding — Prob100_fsm3comb,
    Prob079_fsm3onehot (one-hot encoding handled too)
All host-score PASS. §4.05: SKIP on any incomplete table / missing encoding /
unrecognized cell token.
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import ff_truth_table_synth as FF       # noqa: E402
import comb_state_table_synth as CS      # noqa: E402

import pytest

#: The repo's existing tool gate (197 files use this shape). Without
#: it this module raises FileNotFoundError on a host that lacks the
#: tool, instead of disclosing a skip.
_HAVE_TOOLS = bool(shutil.which("iverilog"))

_HDR = ("I would like you to implement a module named TopModule with the following\n"
        "interface. All input and output ports are one bit unless otherwise specified.\n\n")

JK = _HDR + (
    " - input  clk\n - input  j\n - input  k\n - output Q\n\n"
    "Implement a JK flip-flop with the following truth table. Qold is the output\n"
    "before the positive clock edge.\n\n"
    "  J | K | Q\n  0 | 0 | Qold\n  0 | 1 | 0\n  1 | 0 | 1\n  1 | 1 | ~Qold\n")

COMB = _HDR + (
    " - input  in\n - input  state (2 bits)\n - output next_state (2 bits)\n - output out\n\n"
    "Moore state machine; combinational portion only. Use the encoding A=2'b00,\n"
    "B=2'b01, C=2'b10, D=2'b11.\n\n"
    "  State | Next state in=0, Next state in=1 | Output\n"
    "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n")

ONEHOT = COMB.replace("state (2 bits)", "state (4 bits)").replace(
    "next_state (2 bits)", "next_state (4 bits)").replace(
    "A=2'b00,\nB=2'b01, C=2'b10, D=2'b11", "A=4'b0001, B=4'b0010, C=4'b0100, D=4'b1000")


def _compiles(rtl, tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    f = tmp_path / "m.sv"
    f.write_text(rtl)
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(f)],
                        capture_output=True, text=True)
    return cp.returncode == 0, cp.stderr


def test_jk_ff_fires_and_maps_cells(tmp_path):
    rtl = FF.synth(JK, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    assert "2'b00: Q <= Q;" in rtl          # Qold
    assert "2'b01: Q <= 1'b0;" in rtl
    assert "2'b10: Q <= 1'b1;" in rtl
    assert "2'b11: Q <= ~Q;" in rtl         # ~Qold


def test_ff_skip_incomplete_table():
    bad = JK.replace("  1 | 1 | ~Qold\n", "")     # drop a row
    assert FF.synth(bad, "TopModule") is None


def test_ff_skip_unknown_cell_token():
    bad = JK.replace("1 | 1 | ~Qold", "1 | 1 | toggle")   # non-{Qold,~Qold,0,1}
    assert FF.synth(bad, "TopModule") is None


def test_ff_skip_when_not_a_flipflop():
    assert FF.synth(JK.replace("JK flip-flop", "logic block"), "TopModule") is None


def test_comb_state_binary_fires_and_compiles(tmp_path):
    rtl = CS.synth(COMB, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # A=00: in?B(01):A(00) ; out 0 ; D=11: in?B(01):C(10) ; out 1
    assert "2'd0: begin next_state = in ? 2'd1 : 2'd0; out = 1'b0; end" in rtl
    assert "2'd3: begin next_state = in ? 2'd1 : 2'd2; out = 1'b1; end" in rtl


def test_comb_state_onehot_encoding(tmp_path):
    rtl = CS.synth(ONEHOT, "TopModule")
    assert rtl is not None
    ok, err = _compiles(rtl, tmp_path)
    assert ok, err
    # A=0001(1): in?B(0010=2):A(1) ; the case key is the one-hot code
    assert "4'd1: begin next_state = in ? 4'd2 : 4'd1;" in rtl


def test_comb_state_skip_without_encoding():
    no_enc = COMB.replace("Use the encoding A=2'b00,\nB=2'b01, C=2'b10, D=2'b11.", "")
    assert CS.synth(no_enc, "TopModule") is None


def test_comb_state_skip_with_clock():
    # a clocked (sequential) FSM is NOT this combinational-portion artifact
    seq = COMB.replace(" - input  in\n", " - input  clk\n - input  in\n")
    assert CS.synth(seq, "TopModule") is None


def test_ff_skip_conflicting_duplicate_row():
    # Step-2.7 F1: a contradictory duplicate (J,K) row must SKIP, not last-write-win
    bad = JK + "  1 | 1 | 0\n"     # conflicts with the real (1,1): ~Qold
    assert FF.synth(bad, "TopModule") is None


def test_comb_skip_conflicting_reencoding():
    # Step-2.7 F2: a later 'C=1'b1' that re-encodes a state must SKIP
    bad = COMB + "\nNote: the control bit C=1'b1 enables the path.\n"
    assert CS.synth(bad, "TopModule") is None


def test_comb_skip_duplicate_codes():
    # Step-2.7 F3: two states sharing a code is contradictory -> SKIP
    bad = COMB.replace("B=2'b01", "B=2'b00")
    assert CS.synth(bad, "TopModule") is None
