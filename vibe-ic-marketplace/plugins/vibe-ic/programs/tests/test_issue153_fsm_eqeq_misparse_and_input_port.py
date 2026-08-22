"""ORGANIC #153 — fsm_transition_completeness_check false inferred-latch when an
`==` comparison is misparsed as an `=` assignment and a module INPUT PORT is
picked as the next-state variable. DISTINCT from #138 (which swept module
PARAMETERS into the state set).

Root cause (instrumented on cvdp_copilot_dot_product_0005): the next-state vote
regex `\\b(\\w+)\\s*(?:<=|=)\\s*([^;]+);`
  1. matched the FIRST `=` of a `==` comparison → `if (len == K)` read as `len = …`;
  2. the RHS scan `[^;]+;` crossed the `if` header into the guarded body, pulling
     a state constant into the RHS → the compared identifier got a next-state vote;
  3. the compared identifier is an INPUT PORT (never a next-state reg); it tied
     the real state var 1-1 and `max()` returned the first-inserted key → the
     input port → every arm was flagged `fsm-inferred-latch`.

Fixes (chip-AGNOSTIC): (1) anchor the assignment operator so `==`/`!=`/`>=`/`<=`
-as-comparison is not an assignment + terminate the RHS at an unbalanced `)`;
(2) exclude module INPUT PORTS from next-state candidates; (3) on a vote tie,
prefer the case SELECTOR; (4) a non-assigning arm in a CLOCKED block HOLDS the
reg (legal self-loop) — not a latch. No-leak: a genuine COMBINATIONAL inferred
latch is STILL flagged.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402


def _res(rtl):
    fl, st = F.check_text(rtl)
    return st, [(x.rule, x.state) for x in fl if x.severity == "ERROR"]


# ── the discriminating repro: state gets exactly ONE constant-vote, so the
# `==`-misparse gave the input port a tying vote that won the max() tie on the
# OLD code (every arm → false fsm-inferred-latch). All arms DO assign `state`,
# so the corrected vote (input excluded + `==` anchored → next_var=state) checks
# clean WITHOUT relying on the clocked-hold rule. ──────────────────────────────
_TIE_INPUT_PORT = """\
module m (input clk, input [7:0] len, output reg done);
  localparam RUN = 1'd0, FIN = 1'd1;
  reg state;
  always @(posedge clk) case (state)
    RUN: if (len == 8'd0) state <= FIN; else state <= state;
    FIN: state <= state;
  endcase
endmodule
"""


def test_eqeq_on_input_port_no_false_latch():
    st, errs = _res(_TIE_INPUT_PORT)
    assert st == "CHECKED", st
    assert errs == [], f"false inferred-latch (input-port/==-misparse): {errs}"


def test_input_port_never_a_next_state_candidate():
    """The mechanism guard: the compared INPUT PORT must not be creditable as a
    next-state var — the fixed assignment iterator does not extract it, and the
    input-port set excludes it."""
    ports = F._module_input_ports(F._strip_comments(_TIE_INPUT_PORT))
    assert "len" in ports and "clk" in ports and "input" not in ports
    arm = "if (len == 8'd0) state <= FIN; else state <= state;"
    lhss = [lhs for lhs, _rhs in F._iter_assignments(arm)]
    assert "len" not in lhss                      # `==` no longer misparsed
    assert lhss.count("state") == 2               # both real assigns captured


# ── the dot_product shape (registered FSM, `==` on an input, all arms assign the
# state var): checks clean. ────────────────────────────────────────────────────
_DOT_PRODUCT_SHAPE = """\
module dp (input clk, input rst, input [7:0] length_in, input start,
           output reg done);
  localparam IDLE = 2'd0, COMPUTE = 2'd1, OUTPUT = 2'd2;
  reg [1:0] state;
  always @(posedge clk) begin
    if (rst) state <= IDLE;
    else case (state)
      IDLE:    begin if (start) state <= COMPUTE; else state <= IDLE; end
      COMPUTE: begin if (length_in == 8'd0) state <= OUTPUT;
                     else state <= COMPUTE; end
      OUTPUT:  begin done <= 1'b1; state <= IDLE; end
    endcase
  end
endmodule
"""


def test_dot_product_registered_shape_clean():
    st, errs = _res(_DOT_PRODUCT_SHAPE)
    assert st == "CHECKED", st
    assert errs == []


# ── fix 4: a CLOCKED FSM whose C arm does NOT assign the state reg HOLDS it (a
# legal flop self-loop) — must NOT be flagged. ─────────────────────────────────
_CLOCKED_HOLD = """\
module held (input clk, output reg y);
  localparam A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] state;
  always @(posedge clk) case (state)
    A: state <= B;
    B: state <= C;
    C: y <= 1'b1;
  endcase
endmodule
"""


def test_clocked_non_assigning_arm_is_a_hold_not_a_latch():
    st, errs = _res(_CLOCKED_HOLD)
    assert st == "CHECKED", st
    assert errs == [], f"clocked hold wrongly flagged as latch: {errs}"


# ── NO-LEAK (§4.05): a GENUINE COMBINATIONAL inferred latch — same C-omits-next
# shape but in an `always @(*)` next-state block — must STILL be flagged. ───────
_COMB_LATCH = """\
module leaky (output reg [1:0] next);
  localparam A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] state;
  always @(*) case (state)
    A: next = B;
    B: next = C;
    C: ;
  endcase
endmodule
"""


def test_combinational_latch_still_flagged():
    st, errs = _res(_COMB_LATCH)
    assert st == "CHECKED", st
    assert ("fsm-inferred-latch", "C") in errs, errs


# ── a `<=`-as-comparison inside an `if` header must also not be misparsed into a
# body-crossing bogus vote (the balanced-paren RHS terminator). ────────────────
_LE_COMPARE = """\
module m2 (input clk, input [7:0] cnt, output reg done);
  localparam RUN = 1'd0, FIN = 1'd1;
  reg state;
  always @(posedge clk) case (state)
    RUN: if (cnt <= 8'd3) state <= FIN; else state <= state;
    FIN: state <= state;
  endcase
endmodule
"""


def test_le_comparison_in_if_header_not_a_bogus_vote():
    st, errs = _res(_LE_COMPARE)
    assert st == "CHECKED", st
    assert errs == []
    lhss = [lhs for lhs, _r in F._iter_assignments(
        "if (cnt <= 8'd3) state <= FIN; else state <= state;")]
    # `cnt <= 8'd3` matches `<=`, but the RHS stops at the unbalanced ')' → the
    # RHS never reaches the state constant, so `cnt` gets no next-state vote.
    assert "cnt" in lhss  # the `<=` still matches structurally …
    cnt_rhs = [rhs for lhs, rhs in F._iter_assignments(
        "if (cnt <= 8'd3) state <= FIN;") if lhs == "cnt"][0]
    assert "FIN" not in cnt_rhs  # … but its RHS never crosses into the body


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
