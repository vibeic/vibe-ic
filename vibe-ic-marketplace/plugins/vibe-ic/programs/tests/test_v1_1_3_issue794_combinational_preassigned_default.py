"""ORGANIC #794 — rule_case_coverage hard-WARNed a latch-FREE combinational FSM
where every case-body LHS is unconditionally pre-assigned before the case head.

CVDP round-10 blind: cvdp_copilot_elevator_control_0006 — a combinational
`always @(*)` FSM whose `next_state` / `current_floor_next` are pre-assigned at
statement-top BEFORE a partial `case (state)` with no default. That is the
canonical latch-free fallthrough idiom (verilator emits no %Warning-LATCH, only
CASEINCOMPLETE; iverilog compiles clean), but the gate hard-WARNed (rc=1,
block_eligible) and false-blocked correct RTL.

FIX: `_case_lhs_all_pre_assigned` downgrades to advisory when EVERY case-body LHS
is unconditionally pre-assigned (statement-top) before the case head in the same
always block. §4.05 no-leak: ANY case-body LHS lacking such a pre-case default
keeps the hard WARN (a genuine partial combinational assignment is a real latch).

chip-AGNOSTIC: synthetic Verilog, no chip literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402


def _case_finding(src):
    fs = [f for f in H.rule_case_coverage(src, "d.v")
          if f.rule == "case-no-default"]
    assert len(fs) == 1, [f.symbol for f in fs]
    return fs[0]


# elevator_control shape: BOTH case-body LHS pre-assigned at statement-top.
_LATCH_FREE = """\
module elevator_control(input [1:0] state, input up, output reg [1:0] next_state,
    output reg [3:0] current_floor_next);
  always @(*) begin
    next_state = state;
    current_floor_next = 4'd0;
    case (state)
      2'd0: next_state = 2'd1;
      2'd1: begin next_state = 2'd2; current_floor_next = 4'd5; end
      2'd2: next_state = 2'd0;
    endcase
  end
endmodule
"""


def test_794_latch_free_preassigned_combinational_is_advisory():
    f = _case_finding(_LATCH_FREE)
    assert f.block_eligible is False, "must downgrade to advisory (no latch)"
    assert "pre-assigned" in f.advisory_note


# ── §4.05 NO-LEAK negatives — each must STILL hard-WARN (block_eligible) ──────
_NO_PRE_ASSIGN = """\
module m(input [1:0] state, output reg [1:0] next_state);
  always @(*) begin
    case (state)
      2'd0: next_state = 2'd1;
      2'd1: next_state = 2'd2;
    endcase
  end
endmodule
"""

_PARTIAL_PRE_ASSIGN = """\
module m(input [1:0] state, output reg [1:0] next_state, output reg [3:0] floor);
  always @(*) begin
    next_state = state;            // only ONE of the two LHS pre-assigned
    case (state)
      2'd0: begin next_state = 2'd1; floor = 4'd3; end
      2'd1: next_state = 2'd2;
    endcase
  end
endmodule
"""

_CONDITIONAL_PRE_ASSIGN = """\
module m(input [1:0] state, input en, output reg [1:0] next_state);
  always @(*) begin
    if (en) next_state = state;    // pre-assign is CONDITIONAL → not provable
    case (state)
      2'd0: next_state = 2'd1;
      2'd1: next_state = 2'd2;
    endcase
  end
endmodule
"""


def test_794_noleak_no_pre_assign_still_hard_warns():
    f = _case_finding(_NO_PRE_ASSIGN)
    assert f.block_eligible is True


def test_794_noleak_partial_pre_assign_still_hard_warns():
    f = _case_finding(_PARTIAL_PRE_ASSIGN)
    assert f.block_eligible is True


def test_794_noleak_conditional_pre_assign_still_hard_warns():
    f = _case_finding(_CONDITIONAL_PRE_ASSIGN)
    assert f.block_eligible is True


# ── back-compat: clocked case stays advisory; comparison `<=` not an LHS ──────
_CLOCKED = """\
module m(input clk, input [1:0] state, output reg [1:0] q);
  always @(posedge clk) begin
    case (state)
      2'd0: q <= 2'd1;
      2'd1: q <= 2'd2;
    endcase
  end
endmodule
"""


def test_794_clocked_case_still_advisory_unchanged():
    f = _case_finding(_CLOCKED)
    assert f.block_eligible is False   # #770 r4 path, unaffected


def test_794_lhs_scanner_ignores_comparison_le_in_condition():
    # a `<=` inside an if-condition is a COMPARE, never an assignment LHS.
    lhs = H._procedural_assigned_lhs(
        "a = 1; if (floor_reg <= max_req) b = 2;")
    assert "a" in lhs            # statement-top assignment
    assert "floor_reg" not in lhs  # comparison operand, NOT an LHS
    assert "max_req" not in lhs


def test_794_lhs_scanner_handles_bit_select_lhs():
    lhs = H._procedural_assigned_lhs("bus[3:0] = 4'd5; word = 1;")
    assert lhs == {"bus", "word"}


# ── §4.05 LEAK (Step-2.7) — a CONCAT LHS in a case arm must NOT be missed ─────
_CONCAT_LATCH = """\
module m(input [1:0] s, output reg a, output reg b, output reg c);
  always @(*) begin
    c = 1'b0;                       // only c pre-assigned
    case (s)
      2'd0: {a,b} = 2'b10;          // a,b LATCH on s=2,3 (unlisted) → real latch
      2'd1: c = 1'b1;
    endcase
  end
endmodule
"""


def test_794_noleak_concat_lhs_not_preassigned_still_hard_warns():
    # the scalar scanner once read only the `}` and dropped a,b from the
    # case-body set → false downgrade of a genuine latch. Must stay hard WARN.
    f = _case_finding(_CONCAT_LATCH)
    assert f.block_eligible is True


def test_794_scanner_extracts_concat_lhs_identifiers():
    assert H._procedural_assigned_lhs("{a, b[1:0], c} = 3'b101;") == {
        "a", "b", "c"}


# ── §4.05 LEAK (Step-2.7) — bit/part-SELECT LHS must defeat coverage proof ────
_PARTSEL_LATCH = """\
module decoder(input [1:0] sel, output reg [3:0] dout);
  always @(*) begin
    dout[3:2] = 2'b00;              // pre-default on a DIFFERENT slice
    case (sel)
      2'b00: dout[1:0] = 2'b01;     // dout[1:0] LATCHes on unlisted sel
      2'b01: dout[1:0] = 2'b10;
    endcase
  end
endmodule
"""

_BITSEL_LATCH = """\
module m(input [1:0] sel, output reg [1:0] y);
  always @(*) begin
    y[0] = 1'b0;
    case (sel)
      2'b00: y[1] = 1'b1;           // y[1] LATCHes on unlisted sel
      2'b01: y[1] = 1'b0;
    endcase
  end
endmodule
"""


def test_794_noleak_part_select_lhs_still_hard_warns():
    # dout[3:2] pre-default cannot prove dout[1:0] (case-written) is defaulted.
    assert _case_finding(_PARTSEL_LATCH).block_eligible is True


def test_794_noleak_bit_select_lhs_still_hard_warns():
    assert _case_finding(_BITSEL_LATCH).block_eligible is True


def test_794_lhs_has_subscript_detects_slice_and_concat_slice():
    assert H._lhs_has_subscript("dout[1:0] = 2'b01;")
    assert H._lhs_has_subscript("{a, b[1:0]} = 2'b10;")
    assert not H._lhs_has_subscript("next_state = 2'd1; floor = 4'd0;")
    assert not H._lhs_has_subscript("{a, b} = 2'b10;")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
