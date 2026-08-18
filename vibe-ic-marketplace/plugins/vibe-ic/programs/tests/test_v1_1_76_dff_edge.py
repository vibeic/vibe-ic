#!/usr/bin/env python3
"""test_v1_1_76_dff_edge.py — pins dff_edge_synth.py, the deterministic SOLVER for
the D-flip-flop / edge-detect / edge-capture family.

POSITIVES: each firing VerilogEval-Human problem emits the expected RTL structure
(host-verified 0-mismatch in the PR's corpus sweep — these tests pin the EMITTED
LINES so a refactor can't silently change the synthesized logic).

NEGATIVES (§4.05 NO-LEAK): >=5 fixtures JUST outside the proven envelope that MUST
return None (a wrong sample is strictly worse than a SKIP).
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
if _PROGRAMS not in sys.path:
    sys.path.insert(0, _PROGRAMS)

import dff_edge_synth as M  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))


def _prompt(prob):
    p = os.path.join(DS, f"{prob}_prompt.txt")
    if not os.path.isfile(p):
        pytest.skip(f"dataset prompt {prob} not present on this host")
    with open(p, errors="replace") as f:
        return f.read()


# --------------------------------------------------------------------------- #
# POSITIVES — fire + key emitted lines (real VerilogEval prompts)
# --------------------------------------------------------------------------- #
def test_plain_dff8_fires_with_initial_zero():
    rtl = M.synth(_prompt("Prob034_dff8"))
    assert rtl is not None
    assert "input [7:0] d" in rtl
    assert "output reg [7:0] q" in rtl
    assert "initial" in rtl and "q = 8'b0" in rtl
    assert "always @(posedge clk)" in rtl
    assert "q <= d;" in rtl


def test_unstated_edge_plain_dff_defaults_posedge():
    # A plain clocked D-FF whose prompt does NOT name the edge is posedge by
    # universal HDL convention (VE-Human Prob031 "Create a single D flip-flop.";
    # Prob048 "a simple D flip flop with active high synchronous reset" — neither
    # states the edge). This is the corrected policy: unstated edge SOLVES as
    # posedge (was over-conservatively SKIP, which regressed Prob031/048).
    rtl = M.synth(
        " - input clk\n - input d\n - output q\n"
        "The module should implement a D flip-flop.")
    assert rtl is not None, "unstated-edge plain DFF must solve as posedge"
    assert "always @(posedge clk)" in rtl
    assert "q <= d;" in rtl


def test_contradictory_edge_still_skips():
    # BOTH positive and negative edge named -> genuinely ambiguous -> MUST SKIP.
    rtl = M.synth(
        " - input clk\n - input d\n - output q\n"
        "A D flip-flop triggered on the positive edge and the negative edge of clk.")
    assert rtl is None, "contradictory edge must SKIP (§4.05 no-leak)"


def test_dff8_sync_reset_zero():
    rtl = M.synth(_prompt("Prob041_dff8r"))
    assert rtl is not None
    assert "always @(posedge clk)" in rtl
    assert "if (reset)" in rtl
    assert "q <= 8'b0;" in rtl
    assert "q <= d;" in rtl
    # synchronous => reset NOT in the sensitivity list
    assert "posedge reset" not in rtl


def test_dff8_sync_reset_to_hex_value_negedge():
    rtl = M.synth(_prompt("Prob046_dff8p"))
    assert rtl is not None
    assert "always @(negedge clk)" in rtl          # negative-edge triggered
    assert "if (reset)" in rtl
    assert "q <= 8'h34;" in rtl                     # reset VALUE = 0x34, not zero
    assert "q <= d;" in rtl


def test_dff8_async_reset_zero():
    rtl = M.synth(_prompt("Prob047_dff8ar"))
    assert rtl is not None
    # asynchronous => reset IS in the sensitivity list, active-high => posedge
    assert "always @(posedge clk, posedge areset)" in rtl
    assert "if (areset)" in rtl
    assert "q <= 8'b0;" in rtl


def test_dff1_async_reset_bare_name():
    rtl = M.synth(_prompt("Prob049_m2014_q4b"))
    assert rtl is not None
    assert "always @(posedge clk, posedge ar)" in rtl
    assert "if (ar)" in rtl
    assert "q <= 1'b0;" in rtl
    assert "q <= d;" in rtl


def test_xor_self_feedback_dff():
    rtl = M.synth(_prompt("Prob053_m2014_q4d"))
    assert rtl is not None
    assert "always @(posedge clk)" in rtl
    assert "out <= in ^ out;" in rtl
    assert "initial" in rtl and "out = 1'b0" in rtl


def test_byte_enable_register():
    rtl = M.synth(_prompt("Prob073_dff16e"))
    assert rtl is not None
    # active-low synchronous reset
    assert "if (!resetn)" in rtl
    assert "q <= 16'b0;" in rtl
    # byte-enable slices
    assert "if (byteena[0])" in rtl
    assert "q[7:0] <= d[7:0];" in rtl
    assert "if (byteena[1])" in rtl
    assert "q[15:8] <= d[15:8];" in rtl


def test_positive_edge_detect():
    rtl = M.synth(_prompt("Prob054_edgedetect"))
    assert rtl is not None
    assert "reg [7:0] d_last;" in rtl
    assert "d_last <= in;" in rtl
    assert "pedge <= in & ~d_last;" in rtl          # 0->1 transition formula
    assert "reset" not in rtl                        # pure detect => NO reset


def test_any_edge_detect():
    rtl = M.synth(_prompt("Prob045_edgedetect2"))
    assert rtl is not None
    assert "d_last <= in;" in rtl
    assert "anyedge <= in ^ d_last;" in rtl          # any-edge XOR formula


def test_edge_capture_set_and_hold():
    rtl = M.synth(_prompt("Prob066_edgecapture"))
    assert rtl is not None
    assert "reg [31:0] d_last;" in rtl
    assert "if (reset)" in rtl                       # synchronous reset
    assert "out <= 32'b0;" in rtl
    # set-and-hold (1->0 capture): out keeps its value until reset
    assert "out <= out | (~in & d_last);" in rtl


def test_dual_edge_flip_flop():
    rtl = M.synth(_prompt("Prob078_dualedge"))
    assert rtl is not None
    assert "always @(posedge clk)" in rtl
    assert "always @(negedge clk)" in rtl
    assert "qp <= d;" in rtl
    assert "qn <= d;" in rtl
    # the delta-cycle mux on clk
    assert "q <= clk ? qp : qn;" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVES — MUST return None (no-leak boundary)
# --------------------------------------------------------------------------- #
NEG_FIXTURES = {
    # 2. contradictory edge (both posedge & negedge prose, NOT the dual-edge form)
    "contradictory_edge": """
 - input clk
 - input d
 - output q
A D flip-flop triggered on the positive edge and the negative edge of clk.""",

    # 3. edge CAPTURE without a reset port (capture needs set-and-hold-to-reset)
    "capture_without_reset": """
 - input clk
 - input in (8 bits)
 - output out (8 bits)
Capture when the input changes from 1 to 0.
Triggered on the positive edge of the clock.""",

    # 4. transition direction not stated -> ambiguous (pos/neg/any all undecided)
    "ambiguous_transition": """
 - input clk
 - input in (8 bits)
 - output out (8 bits)
Detect when the input transitions.
Triggered on the positive edge of the clock.""",

    # 5. reset value mentioned but NON-numeric -> not pinned -> SKIP
    "reset_value_unpinned": """
 - input clk
 - input reset
 - input d (8 bits)
 - output q (8 bits)
8 D flip-flops with active high synchronous reset to some configured value.
All DFFs triggered by the positive edge of clk.""",

    # 6. a counter, not a register (out-of-scope keyword)
    "counter_out_of_scope": """
 - input clk
 - input reset
 - output q (4 bits)
A 4-bit counter that increments every clock. Positive edge triggered.""",

    # 7. multi-control load/enable shift stage (Prob061-shape) -> not a plain DFF
    "load_enable_shift_stage": """
 - input clk
 - input w
 - input R
 - input E
 - input L
 - output Q
One stage of a shift register. L loads R, E enables shift of w.
Positive edge triggered.""",

    # 8. two un-disambiguated data inputs feeding one FF -> ambiguous
    "two_data_inputs": """
 - input clk
 - input a
 - input b
 - output q
A flip-flop. Positive edge triggered.""",

    # 9. data width != output width -> structurally inconsistent
    "width_mismatch": """
 - input clk
 - input d (4 bits)
 - output q (8 bits)
8 D flip-flops, positive edge triggered.""",

    # 10. stated DFF count != output width -> inconsistent
    "count_width_mismatch": """
 - input clk
 - input d (8 bits)
 - output q (8 bits)
The module should include 4 D flip-flops, positive edge triggered.""",
}


@pytest.mark.parametrize("name", sorted(NEG_FIXTURES))
def test_no_leak_negative_must_skip(name):
    assert M.synth(NEG_FIXTURES[name]) is None, f"{name} LEAKED a sample (must SKIP)"


def test_at_least_five_negatives():
    assert len(NEG_FIXTURES) >= 5


# --------------------------------------------------------------------------- #
# structural guards
# --------------------------------------------------------------------------- #
def test_empty_and_garbage_skip():
    assert M.synth("") is None
    assert M.synth("   \n  ") is None
    assert M.synth("hello world, this is not a chip spec") is None


def test_skip_returns_none_not_exception():
    # FSM / kmap / lfsr prompts must SKIP cleanly (handled by another solver)
    assert M.synth("""
 - input clk
 - input in
 - output out
A Moore finite state machine. Positive edge triggered.""") is None
