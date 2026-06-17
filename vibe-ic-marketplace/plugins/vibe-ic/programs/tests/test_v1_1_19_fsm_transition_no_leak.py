"""Step-2.7 §4.05 guards for PR #14 (#810 fsm prompt-transition cross-check).

Step-2.7 reproduced 2 HIGH:
  F1 FALSE-FIRE — a CORRECT state-DEPENDENT but case-less FSM
     (`if (state==A) state<=in?B:A; else state<=in?A:B;`) was blocked: the
     inline state-INDEPENDENT fallback grabbed state A's ternary and applied it
     to ALL states, fabricating a state-B mismatch.
  F2 FALSE-SKIP — a genuine next-state bug was silently passed when the
     output-decode `case (state)` was written BEFORE the next-state
     `case (state)`: `_select_next_state_case` counted case LABELS as state
     constants and returned the output case (non-ternary arms → SKIP).

FIXES: (1) `_select_next_state_case` counts state constants only on the
assignment RHS (never the label), so the next-state case is selected; (2) the
inline fallback collects ALL next-state ternary mappings — ≥2 distinct → SKIP
(state-dependent, fail-safe), exactly 1 → apply to all (genuinely
state-independent, still flagged against a state-dependent table).

chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402


def _check(rtl, spec):
    return F.check_single_input_moore(rtl, spec)


_SPEC = ("A (0) --0--> A\nA (0) --1--> B\n"
         "B (1) --0--> B\nB (1) --1--> A\n")

# F1: a CORRECT state-dependent case-less FSM — must NOT be flagged.
_F1_CORRECT_CASELESS = (
    "module fsm(input clk, input rst, input in, output out);\n"
    "  localparam A = 1'b0, B = 1'b1; reg state;\n"
    "  always @(posedge clk) begin\n"
    "    if (rst) state <= A;\n"
    "    else begin if (state == A) state <= in ? B : A;\n"
    "               else            state <= in ? A : B; end\n"
    "  end\n  assign out = (state == B);\nendmodule\n")

_SPEC2 = ("IDLE (0) --in=0--> IDLE\nIDLE (0) --in=1--> RUN\n"
          "RUN (1) --in=0--> IDLE\nRUN (1) --in=1--> RUN\n")

# F2: genuine RUN,in=1->IDLE bug, output-decode case written FIRST — must FIRE.
_F2_BUG_OUTPUT_CASE_FIRST = (
    "module fsm(input clk, input reset, input in, output reg out);\n"
    "  localparam IDLE = 1'b0, RUN = 1'b1; reg state, next;\n"
    "  always @(*) begin case (state) IDLE: out=1'b0; RUN: out=1'b1; endcase end\n"
    "  always @(*) begin case (state)\n"
    "    IDLE: next = in ? RUN : IDLE;\n"
    "    RUN:  next = in ? IDLE : IDLE;\n"  # BUG: RUN,in=1 -> IDLE (spec: RUN)
    "  endcase end\n"
    "  always @(posedge clk) if (reset) state <= IDLE; else state <= next;\n"
    "endmodule\n")


def test_f1_correct_caseless_state_dependent_not_blocked():
    findings, status = _check(_F1_CORRECT_CASELESS, _SPEC)
    mismatches = [f for f in findings if f.rule == "fsm-prompt-transition-mismatch"]
    assert mismatches == [], (status, [f.detail for f in mismatches])
    assert status.startswith("SKIP-state-dependent")


def test_f2_genuine_bug_with_output_case_first_still_fires():
    findings, status = _check(_F2_BUG_OUTPUT_CASE_FIRST, _SPEC2)
    assert status == "CHECKED-MOORE", status
    assert any(f.rule == "fsm-prompt-transition-mismatch" for f in findings)


def test_state_independent_contradicting_table_still_flagged():
    # exactly ONE next-state ternary applied to all states, contradicts a
    # state-dependent table → must still be flagged (not skipped by the F1 fix).
    rtl = ("module m(input clk, input in, input areset, output out);\n"
           "  localparam A=1'b0, B=1'b1; reg state;\n"
           "  always @(posedge clk or posedge areset)\n"
           "    if (areset) state <= B; else state <= in ? B : A;\n"
           "  assign out = (state == B);\nendmodule\n")
    findings, status = _check(rtl, _SPEC)
    assert status == "CHECKED-MOORE"
    assert any(f.rule == "fsm-prompt-transition-mismatch" for f in findings)


def test_select_next_state_case_skips_output_decode_case():
    sc = {"IDLE": 0, "RUN": 1}
    out_then_ns = ("case (state) IDLE: out=1'b0; RUN: out=1'b1; endcase "
                   "case (state) IDLE: next=in?RUN:IDLE; RUN: next=in?RUN:IDLE; endcase")
    sel = F._select_next_state_case(out_then_ns, sc)
    assert sel is not None
    # the selected case must be the NEXT-STATE one (its arms assign state consts)
    assert "next" in sel[1]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
