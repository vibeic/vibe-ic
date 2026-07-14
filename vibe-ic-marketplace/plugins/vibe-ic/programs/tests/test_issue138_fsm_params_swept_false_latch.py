"""ORGANIC #138 — module parameters (N, WIDTH) swept into the FSM state set
false-BLOCK a correct FSM as an inferred latch.

`parse_states()` returns not only the case-item FSM constants but also module
parameters used as loop bounds / bit-widths (`parameter N`, `parameter WIDTH`).
`check_text()` used to vote for the next-state variable by intersecting each
arm-body assignment's RHS against that broad `declared` set. A data load loop
inside a state arm —

    for (k = 0; k < N; k = k + 1)
        arr[k] <= in_data[k*WIDTH +: WIDTH];

— has an increment `k = k + 1) ... in_data[k*WIDTH +: WIDTH];` whose RHS text
(scanned to the next ';') contains `WIDTH`. That credited the loop index `k` as
a next-state assignment; `k` then tied with (and, being inserted first, won the
max() tie over) the real `state` var, and every arm that did not assign `k` was
reported `fsm-inferred-latch` — a false positive that BLOCKED a correct design.

Surfaced by the v1.4.14 CVDP clean-run on `cvdp_copilot_sorter_0001`.

Fix: vote for the next-state variable using ONLY the confirmed case-item STATE
labels (`item_states`), never the broader `declared` set (which sweeps in
parameters). `item_states` never contains a parameter.

chip-AGNOSTIC: synthetic Verilog FSMs, no chip/vendor/state literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import fsm_transition_completeness_check as F  # noqa: E402


def _res(rtl):
    fl, st = F.check_text(rtl)
    return st, [(x.rule, x.state) for x in fl if x.severity == "ERROR"]


# A CORRECT sorter-shape FSM: clocked case with a `state <= state` pre-assign
# hold and a terminal DONE state; a for(k=0;k<N;...) arr[k]<=in[k*WIDTH+:WIDTH]
# load loop inside a state arm. `state` is properly held in every state, so
# there is NO real latch — the only "latch" the OLD code reported was the loop
# index `k` wrongly promoted to the next-state variable.
_SORTER_PARAMS_SWEPT = """\
module cvdp_copilot_sorter #(parameter N = 4, parameter WIDTH = 8) (
  input clk,
  input rst,
  input load,
  input [N*WIDTH-1:0] in_data,
  output reg busy,
  output reg [N*WIDTH-1:0] out_data
);
  localparam S_LOAD = 2'd0, S_WORK = 2'd1, S_DONE = 2'd2;
  reg [1:0] state;
  reg [WIDTH-1:0] arr [0:N-1];
  integer k;
  always @(posedge clk) begin
    if (rst) begin
      state <= S_LOAD;
    end else begin
      state <= state;                          // default hold (pre-assign)
      case (state)
        S_LOAD: begin
          for (k = 0; k < N; k = k + 1)
            arr[k] <= in_data[k*WIDTH +: WIDTH];
          if (load) state <= S_WORK;
        end
        S_WORK: begin
          for (k = 0; k < N; k = k + 1)
            out_data[k*WIDTH +: WIDTH] <= arr[k];
          state <= S_DONE;
        end
        S_DONE: begin
          out_data <= out_data;                // terminal hold (correct)
        end
      endcase
    end
  end
  always @(*) busy = (state != S_DONE);
endmodule
"""


def test_params_swept_into_states_no_false_latch():
    """The #138 repro: params N/WIDTH must NOT be treated as states, so the
    correct sorter FSM checks clean instead of a false inferred-latch."""
    st, errs = _res(_SORTER_PARAMS_SWEPT)
    assert st == "CHECKED", st
    assert errs == [], f"false inferred-latch on a correct FSM: {errs}"


def test_parse_states_still_sweeps_params_but_check_ignores_them():
    """Guard the exact mechanism: `parse_states` still returns the params (it is
    a broad collector), so the fix must live in check_text's vote, not here."""
    declared = set(F.parse_states(F._strip_comments(_SORTER_PARAMS_SWEPT)))
    assert {"N", "WIDTH"} <= declared          # params ARE still collected
    assert {"S_LOAD", "S_WORK", "S_DONE"} <= declared
    # ...yet the check no longer mis-fires (covered by the test above).


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK guard: the fix must NOT blind the gate. A GENUINE combinational #
# inferred latch — a separate `next_state`, NOT pre-assigned, an arm (S_C) that #
# omits it, no default — MUST still be caught, even in a module that ALSO       #
# carries the N/WIDTH parameters and for-loops that used to derail the vote.    #
# (Proven against the pre-fix code too: it flagged the same S_C, so the fix     #
# removes only the false positive and never weakens real detection.)            #
# --------------------------------------------------------------------------- #
_REAL_LATCH_WITH_PARAMS = """\
module leaky #(parameter N = 4, parameter WIDTH = 8) (
  input clk, input rst, input go, input [N*WIDTH-1:0] in_data,
  output reg [N*WIDTH-1:0] out_data
);
  localparam S_A = 2'd0, S_B = 2'd1, S_C = 2'd2;
  reg [1:0] state, next_state;
  reg [WIDTH-1:0] arr [0:N-1];
  integer k;
  always @(posedge clk) if (rst) state <= S_A; else state <= next_state;
  always @(*) begin
    case (state)                               // NOTE: no pre-assign, no default
      S_A: begin
        for (k = 0; k < N; k = k + 1) arr[k] = in_data[k*WIDTH +: WIDTH];
        next_state = S_B;
      end
      S_B: begin
        if (go) next_state = S_C;              // genuinely covered
        else    next_state = S_A;
      end
      S_C: begin
        for (k = 0; k < N; k = k + 1) out_data[k*WIDTH +: WIDTH] = arr[k];
        // BUG: S_C never assigns next_state, no default, no pre-assign -> LATCH.
      end
    endcase
  end
endmodule
"""


def test_real_inferred_latch_still_caught_with_params():
    """NO-LEAK: a true inferred latch on S_C must STILL be flagged after the fix
    — the vote correctly identifies `next_state` (not `k`) as the next-state var
    and reports S_C's missing transition."""
    st, errs = _res(_REAL_LATCH_WITH_PARAMS)
    assert st == "CHECKED", st
    assert ("fsm-inferred-latch", "S_C") in errs, errs
    # and it must NOT mis-attribute the latch to the loop index / other arms.
    assert ("fsm-inferred-latch", "S_A") not in errs
    assert ("fsm-inferred-latch", "S_B") not in errs


# NO-LEAK, harder shape: an FSM whose transition TARGETS are declared states that
# have NO case-arm of their own (X, Y) — so `item_states` alone would not see
# them. The next-state variable is identified via the CLEAN bare-target scan
# (`= X ;` / `= Y ;`), so a genuine latch on C is STILL caught. This is the
# pathological shape that a naive "item_states only" narrowing would have MISSED
# (SKIP-no-next-state-assignment); the bare/ternary transition-target scan keeps
# it covered while still excluding parameters (which never appear as a bare RHS
# value, only inside an index/width expression).
_LATCH_TARGETS_NOT_CASE_ITEMS = """\
module adv (input clk, input rst, input g, output reg y);
  localparam A = 3'd0, B = 3'd1, C = 3'd2, X = 3'd3, Y = 3'd4;
  reg [2:0] state, next_state;
  always @(posedge clk) if (rst) state <= A; else state <= next_state;
  always @(*) begin
    case (state)
      A: next_state = X;
      B: next_state = Y;
      C: y = 1'b1;   // latch: C never assigns next_state, no default/pre-assign
    endcase
  end
endmodule
"""


def test_latch_with_non_case_item_targets_still_caught():
    """NO-LEAK (pathological): transitions target declared states with no arm;
    the latch on C is still caught via the bare transition-target scan."""
    st, errs = _res(_LATCH_TARGETS_NOT_CASE_ITEMS)
    assert st == "CHECKED", st
    assert ("fsm-inferred-latch", "C") in errs, errs
