"""v1.1.75 — directive-3 ②->① : EXTRACTION-COMPLETENESS for the named-input arrow
Moore FSM. The load-bearing gap was the EXTRACTION layer — the baseline parser read
only `A (0) --1--> B` and the tabular form, so VerilogEval-Human Prob107/110/111
extracted ONLY their pinout and DROPPED the entire FSM (program_baseline returned
just `pinout_table`). Once the transition structure is recognised the RTL is a free
deterministic formula (the TB observes only the Moore output, so internal encoding
is free), flipping these three from AI-authored (②) to program-solved (①).

The two new written forms (real Prob107/110/111 lines embedded VERBATIM):
  - NAMED single-input arrow:  `B (out=1) --in=0--> A`  + "The reset state is B"
  - TWO-input arrow (each state gates on its OWN input): `OFF (out=0) --j=1--> ON`

§4.05 NO-LEAK is the load-bearing half: a named-input relaxation that is too wide
would emit RTL that silently drops a real module input. The negative fixtures sit
JUST OUTSIDE the intended boundary and must STILL SKIP (return None).
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import full_moore_fsm_synth as FM          # noqa: E402

# ---- real VerilogEval-Human prompt bodies (transition table embedded VERBATIM) ----

PROB107 = """\
 - input  clk
 - input  reset
 - input  in
 - output out

Implement the following Moore state machine with two states, one input,
and one output. The reset state is B and reset is active-high
synchronous.

  B (out=1) --in=0--> A
  B (out=1) --in=1--> B
  A (out=0) --in=0--> B
  A (out=0) --in=1--> A
"""

PROB110 = """\
 - input  clk
 - input  areset
 - input  j
 - input  k
 - output out

The module should implement a Moore state machine with two states, two
inputs, and one output according to diagram described below. Reset is an
active-high asynchronous reset to state OFF.

  OFF (out=0) --j=0--> OFF
  OFF (out=0) --j=1--> ON
  ON  (out=1) --k=0--> ON
  ON  (out=1) --k=1--> OFF
"""

PROB111 = PROB110.replace(" - input  areset", " - input  reset").replace(
    "asynchronous reset to state OFF", "synchronous reset to state OFF")


# =========================== POSITIVE — fire + correct ===========================

def test_prob107_single_named_input_fires():
    rtl = FM.synth(PROB107, "TopModule")
    assert rtl is not None
    # B outputs 1, A outputs 0; B on in=0 -> A, in=1 -> B; A on in=0 -> B, in=1 -> A
    assert "S_B: nstate = in ? S_B : S_A;" in rtl
    assert "S_A: nstate = in ? S_A : S_B;" in rtl
    assert "S_B: out = 1'b1;" in rtl and "S_A: out = 1'b0;" in rtl
    assert "if (reset) state <= S_B;" in rtl       # reset state B, active-high sync
    assert "posedge clk)" in rtl and " or " not in rtl.split("always @(")[2]  # sync


def test_prob110_two_input_async_fires():
    rtl = FM.synth(PROB110, "TopModule")
    assert rtl is not None
    assert "input j" in rtl and "input k" in rtl   # BOTH inputs emitted
    assert "S_OFF: nstate = j ? S_ON : S_OFF;" in rtl     # OFF gates on j
    assert "S_ON: nstate = k ? S_OFF : S_ON;" in rtl      # ON gates on k
    assert "posedge clk or posedge areset" in rtl         # async active-high
    assert "if (areset) state <= S_OFF;" in rtl


def test_prob111_two_input_sync_fires():
    rtl = FM.synth(PROB111, "TopModule")
    assert rtl is not None
    assert "S_OFF: nstate = j ? S_ON : S_OFF;" in rtl
    assert "S_ON: nstate = k ? S_OFF : S_ON;" in rtl
    assert "if (reset) state <= S_OFF;" in rtl
    # synchronous: the state-register sensitivity list is posedge clk ONLY
    reg_block = rtl.split("// state register")[1]
    assert "posedge clk)" in reg_block and "areset" not in reg_block


def test_bare_arrow_still_fires():
    # the ORIGINAL bare `A (0) --1--> B` form must keep working (regression guard)
    p = (" - input clk\n - input reset\n - input in\n - output out\n"
         "Synchronous active-high reset to state A.\n"
         "  A (0) --0--> A\n  A (0) --1--> B\n  B (1) --0--> A\n  B (1) --1--> B\n")
    rtl = FM.synth(p, "TopModule")
    assert rtl is not None and "S_A: nstate = in ?" in rtl


def test_tabular_still_fires():
    # the tabular Prob119 form must keep working (regression guard)
    p = (" - input clk\n - input areset\n - input in\n - output out\n"
         "positive edge triggered asynchronous reset that resets the FSM to state A.\n"
         "  state | next state in=0, next state in=1 | output\n"
         "  A     | A, B | 0\n  B     | C, B | 0\n  C     | A, D | 0\n  D     | C, B | 1\n")
    rtl = FM.synth(p, "TopModule")
    assert rtl is not None and "S_A: nstate = in ? S_B : S_A;" in rtl


# ===================== NEGATIVE — §4.05 no-leak, must SKIP =======================

def test_skip_two_inputs_one_never_governs():
    # k is a module input but NO arrow names k -> emitting would silently DROP k.
    p = (" - input clk\n - input areset\n - input j\n - input k\n - output out\n"
         "active-high asynchronous reset to state OFF.\n"
         "  OFF (out=0) --j=0--> OFF\n  OFF (out=0) --j=1--> ON\n"
         "  ON  (out=1) --j=0--> ON\n  ON  (out=1) --j=1--> OFF\n")
    assert FM.synth(p, "TopModule") is None


def test_skip_state_gates_on_two_different_inputs():
    # OFF names BOTH j and k -> ambiguous priority -> never guess.
    p = (" - input clk\n - input areset\n - input j\n - input k\n - output out\n"
         "active-high asynchronous reset to state OFF.\n"
         "  OFF (out=0) --j=0--> OFF\n  OFF (out=0) --k=1--> ON\n"
         "  ON  (out=1) --k=0--> ON\n  ON  (out=1) --k=1--> OFF\n")
    assert FM.synth(p, "TopModule") is None


def test_skip_mixed_named_and_bare_arrows():
    p = (" - input clk\n - input reset\n - input in\n - output out\n"
         "active-high synchronous reset to state A.\n"
         "  A (out=0) --in=0--> A\n  A (out=0) --in=1--> B\n"
         "  B (1) --0--> A\n  B (1) --1--> B\n")           # B uses bare form
    assert FM.synth(p, "TopModule") is None


def test_skip_incomplete_named_table():
    # OFF only has its j=1 arrow -> incomplete -> SKIP
    p = (" - input clk\n - input areset\n - input j\n - input k\n - output out\n"
         "active-high asynchronous reset to state OFF.\n"
         "  OFF (out=0) --j=1--> ON\n"
         "  ON  (out=1) --k=0--> ON\n  ON  (out=1) --k=1--> OFF\n")
    assert FM.synth(p, "TopModule") is None


def test_skip_reset_unspecified():
    # no reset state / polarity named -> never guess
    p = (" - input clk\n - input reset\n - input in\n - output out\n"
         "  A (out=0) --in=0--> A\n  A (out=0) --in=1--> B\n"
         "  B (out=1) --in=0--> A\n  B (out=1) --in=1--> B\n")
    assert FM.synth(p, "TopModule") is None


def test_skip_foreign_governing_input():
    # arrows name 'm', which is NOT a module input -> set(gov) != fsm_ins -> SKIP
    p = (" - input clk\n - input reset\n - input in\n - output out\n"
         "active-high synchronous reset to state A.\n"
         "  A (out=0) --m=0--> A\n  A (out=0) --m=1--> B\n"
         "  B (out=1) --m=0--> A\n  B (out=1) --m=1--> B\n")
    assert FM.synth(p, "TopModule") is None


def test_skip_multibit_input_present():
    # §4.05 belt-and-suspenders: a complete 1-bit Moore arrow table PLUS an
    # unrelated multi-bit input would silently drop that wide input from the
    # emitted ports -> SKIP (do not emit RTL that ignores a real input).
    p = (" - input clk\n - input reset\n - input in\n - input data (8 bits)\n"
         " - output out\n"
         "active-high synchronous reset to state A.\n"
         "  A (out=0) --in=0--> A\n  A (out=0) --in=1--> B\n"
         "  B (out=1) --in=0--> A\n  B (out=1) --in=1--> B\n")
    assert FM.synth(p, "TopModule") is None
