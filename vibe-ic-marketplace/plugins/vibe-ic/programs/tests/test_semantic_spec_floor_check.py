"""Regression tests for semantic_spec_floor_check — the SEMANTIC dataset-defect
floor detector (golden passes its own golden-derived test yet contradicts the
prompt's own machine-extractable spec).

Uses SELF-CONTAINED synthetic fixtures (no external dataset). The §4.05 no-leak
proof is the pair (a contradicting golden FIRES) AND (a faithful golden NEAR the
same boundary does NOT) — a relaxed/over-wide detector would false-floor the
faithful one.
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic_spec_floor_check as S  # noqa: E402

HAVE_IVERILOG = shutil.which("iverilog") and shutil.which("vvp")
pytestmark = pytest.mark.skipif(not HAVE_IVERILOG, reason="needs iverilog+vvp")


# --- a 3-variable direct K-map: out = a | b | c --------------------------- #
KMAP_OR = """
I would like you to implement a module named TopModule.

 - input  a
 - input  b
 - input  c
 - output out

The module should implement the circuit described by the Karnaugh map below.

          a
   bc   0   1
   00 | 0 | 1 |
   01 | 1 | 1 |
   11 | 1 | 1 |
   10 | 1 | 1 |
"""
GOLD_OR_FAITHFUL = "module RefModule(input a,input b,input c,output out);\n  assign out = a|b|c;\nendmodule\n"
GOLD_OR_CONTRADICT = "module RefModule(input a,input b,input c,output out);\n  assign out = a&b&c;\nendmodule\n"


def test_kmap_faithful_golden_no_fire():
    assert S.semantic_floor_evidence(KMAP_OR, GOLD_OR_FAITHFUL) is None


def test_kmap_contradicting_golden_fires():
    r = S.semantic_floor_evidence(KMAP_OR, GOLD_OR_CONTRADICT)
    assert r is not None and "Karnaugh" in r


# --- the embedded 2:1-mux "fix the bug" polarity class -------------------- #
MUX_BUG_PROMPT = """
Find the bug and fix this 8-bit wide 2-to-1 mux.

  module top_module (input sel, input [7:0] a, input [7:0] b, output out);
    assign out = (~sel & a) | (sel & b);
  endmodule
"""
GOLD_MUX_FAITHFUL = "module RefModule(input sel,input [7:0] a,input [7:0] b,output [7:0] out);\n  assign out = sel ? b : a;\nendmodule\n"
GOLD_MUX_INVERTED = "module RefModule(input sel,input [7:0] a,input [7:0] b,output [7:0] out);\n  assign out = sel ? a : b;\nendmodule\n"


def test_mux_faithful_polarity_no_fire():
    # golden keeps the snippet's polarity (sel=1 -> b): NOT a floor.
    assert S.semantic_floor_evidence(MUX_BUG_PROMPT, GOLD_MUX_FAITHFUL) is None


def test_mux_inverted_polarity_fires():
    # golden inverts the select (sel=1 -> a): a semantic floor.
    r = S.semantic_floor_evidence(MUX_BUG_PROMPT, GOLD_MUX_INVERTED)
    assert r is not None and "polarity" in r.lower()


# --- negatives: nothing extractable -> never fires ------------------------ #
def test_no_kmap_no_bug_returns_none():
    prompt = "Implement a module TopModule with input a and output out where out = a."
    gold = "module RefModule(input a, output out);\n assign out = ~a;\nendmodule\n"
    assert S.semantic_floor_evidence(prompt, gold) is None


def test_sequential_golden_skipped():
    # a clocked golden is out of the combinational K-map class -> never floors.
    gold = "module RefModule(input clk,input a,input b,input c,output reg out);\n always @(posedge clk) out<=a&b&c;\nendmodule\n"
    assert S.semantic_floor_evidence(KMAP_OR, gold) is None
