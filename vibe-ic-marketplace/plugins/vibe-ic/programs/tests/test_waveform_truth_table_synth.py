"""v1.1.38 §4.2 absorption — deterministic combinational-waveform → RTL synth.

The circuitN family embeds a literal truth table; for a COMBINATIONAL circuit it
is a complete oracle-free spec, so the answer is deterministic (SOP over the 1-rows).
This was a per-round single-shot variance (a blind author re-derives the boolean
function by eye and flips it); the synth absorbs it as a PROGRAM so it is a
guaranteed first-pass PASS.

§4.05 no-leak: the synth FIRES only inside the proven-faithful envelope
(combinational, no-clock table, all-port columns, self-consistent) and SKIPs
everywhere else — it can never emit a wrong sample. These tests pin both halves:
the positive (fires + emits the correct SOP) AND the no-leak negatives
(SKIP on sequential / clock-column / contradiction / no-table / no-ports).
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import waveform_truth_table_synth as W  # noqa: E402


_COMB_PROMPT = """
Implement a module named TopModule.

  input a,
  input b,
  output q

The module should implement a combinational circuit. Read the simulation
waveforms to determine what the circuit does, then implement it.

  time  a  b  q
  0ns   0  0  0
  5ns   0  1  1
  10ns  1  0  1
  15ns  1  1  0
"""


# ── POSITIVE: fires, emits a correct XOR SOP, all minterms covered ────────────
def test_combinational_synth_fires_and_is_correct():
    rtl = W.synth(_COMB_PROMPT, "TopModule")
    assert rtl is not None, "combinational waveform must synthesize"
    assert "module TopModule" in rtl and "assign q" in rtl
    # q = a^b: 1-rows are (a=0,b=1) and (a=1,b=0)
    assert "(~a & b)" in rtl and "(a & ~b)" in rtl


def test_unobserved_combo_is_dont_care_zero():
    # only a couple of rows; absent combos emit 0 (canonical reading)
    p = _COMB_PROMPT.replace("  10ns  1  0  1\n", "").replace("  15ns  1  1  0\n", "")
    rtl = W.synth(p, "TopModule")
    assert rtl is not None
    assert "(~a & b)" in rtl  # the one observed 1-row
    assert "a & ~b" not in rtl  # unobserved -> not a minterm


# ── §4.05 NO-LEAK NEGATIVES: must SKIP (return None), never emit a guess ───────
def test_skip_sequential_flipflop():
    seq = _COMB_PROMPT.replace(
        "combinational circuit", "sequential circuit with one flip-flop")
    assert W.synth(seq, "TopModule") is None


def test_skip_when_table_has_clock_column():
    clk = """
Implement a module named TopModule.
  input clk,
  input a,
  output q
The module should implement a combinational circuit.
  time  clk a  q
  0ns   0   0  0
  5ns   1   1  1
"""
    assert W.synth(clk, "TopModule") is None


def test_skip_on_contradiction():
    # same inputs (a=0,b=0) give q=0 then q=1 -> not a clean function -> SKIP
    bad = _COMB_PROMPT + "  20ns  0  0  1\n"
    assert W.synth(bad, "TopModule") is None


def test_skip_when_no_table():
    assert W.synth("Implement a combinational module TopModule with input a.", "TopModule") is None


def test_skip_when_no_ports():
    notports = "The module is combinational.\n  time  a  q\n  0ns  0  0\n  5ns  1  1\n"
    assert W.synth(notports, "TopModule") is None


def test_skip_when_word_combinational_absent():
    # a sequential-or-unspecified prompt with a table but no 'combinational' word
    p = _COMB_PROMPT.replace("combinational ", "")
    assert W.synth(p, "TopModule") is None


# ── SEQUENTIAL 1-FF observable-state envelope ─────────────────────────────────
# A plain D flip-flop: next-state = a; q = state (combinational). The table pairs
# each posedge's `a` to the NEXT posedge's `state`. posedges at 5/15/25/35/45ns:
#   a@5=1 -> state@15=1 ; a@15=0 -> state@25=0 ; a@25=1 -> state@35=1 ;
#   a@35=1 -> state@45=1. q mirrors state each row.
_SEQ_FF_PROMPT = """
Implement a module named TopModule.
  input clk,
  input a,
  output q,
  output state

This is a sequential circuit consisting of combinational logic and one bit of
memory (i.e., one flip-flop). The output of the flip-flop has been made
observable through the output state.

  time  clk a   state q
  0ns   0   1   0     0
  5ns   1   1   0     0
  10ns  0   0   0     0
  15ns  1   0   1     1
  20ns  0   1   1     1
  25ns  1   1   0     0
  30ns  0   1   0     0
  35ns  1   1   1     1
  40ns  0   0   1     1
  45ns  1   0   1     1
"""


def test_sequential_1ff_fires_and_is_correct():
    rtl = W.synth(_SEQ_FF_PROMPT, "TopModule")
    assert rtl is not None, "1-FF observable-state sequential must synthesize"
    assert "always @(posedge clk)" in rtl
    assert "output reg state" in rtl
    assert "assign q" in rtl
    # next-state = a (D-FF): state'=1 exactly when a=1
    assert "(a & ~state)" in rtl and "(a & state)" in rtl


def test_sequential_skip_on_negedge_prompt():
    p = _SEQ_FF_PROMPT + "\nThe flip-flop is triggered on the negedge of clk."
    assert W.synth(p, "TopModule") is None


# ── Step-2.7 §4.05 remediations: never EMIT a wrong sample ────────────────────

def test_skip_multibit_declared_port_combinational():
    """A multi-bit declared port whose observed rows are 0/1 must SKIP (the SOP
    model is 1-bit-only; `assign q = …` over a bus is width-broken)."""
    assert W.synth(_COMB_PROMPT.replace("  output q", "  output q (4 bits)"),
                   "TopModule") is None


@pytest.mark.parametrize("mangle,desc", [
    (lambda p: p.replace("  10ns  1  0  1\n", "\n  10ns  1  0  1\n"), "blank-line grouping"),
    (lambda p: p.replace("  15ns  1  1  0\n", "  15ns  1  1  0  <- glitch\n"), "annotation token"),
    (lambda p: p.replace("  10ns  1  0  1\n", "  10  1  0  1\n"), "non-ns time unit"),
])
def test_skip_on_truncated_combinational_table(mangle, desc):
    """parse_table stops at the first un-parseable row; an SOP over the surviving
    prefix is a wrong function (and the sibling CHECK shares the parser) → SKIP."""
    assert W.synth(mangle(_COMB_PROMPT), "TopModule") is None, desc


def test_skip_when_declared_port_absent_from_table_combinational():
    """A declared port absent from the table columns would be dropped from the
    emitted interface (port-truncated wrong module) → SKIP."""
    p = _COMB_PROMPT.replace("  input b,\n", "  input b,\n  input c,\n")
    assert W.synth(p, "TopModule") is None


def test_sequential_skip_on_truncated_table():
    """The 1-FF path shares the parse_table truncation hazard — a blank-line-
    grouped table builds a wrong next-state SOP over a prefix → must SKIP."""
    trunc = _SEQ_FF_PROMPT.replace("  15ns  1   0   1     1\n",
                                   "  15ns  1   0   1     1\n\n")
    assert W.synth(trunc, "TopModule") is None


# A D-FF (state<=a, q=state) sampled every 5ns, the clock LEADING HIGH at 0ns.
# The real posedges are 10/20/30ns (each preceded by a clk=0). If row 0 (clk=1,
# no preceding clk=0) were wrongly counted as a posedge, the pair (a@0=1,state@0=0)
# →state@10=0 would CONTRADICT the real pair (a@10=1,state@10=0)→state@20=1 (same
# input combo, different next-state) → the contradiction guard would SKIP. So with
# the phantom-posedge BUG this fixture SKIPs; with the fix it FIRES `(a & ~state)`.
_SEQ_FF_LEADING_HIGH = """
Implement a module named TopModule.
  input clk,
  input a,
  output q,
  output state

This is a sequential circuit consisting of combinational logic and one bit of
memory (i.e., one flip-flop). The output of the flip-flop has been made
observable through the output state.

  time  clk a   state q
  0ns   1   1   0     0
  5ns   0   1   0     0
  10ns  1   1   0     0
  15ns  0   0   0     0
  20ns  1   0   1     1
  25ns  0   1   1     1
  30ns  1   1   0     0
"""


def test_sequential_skip_phantom_row0_posedge():
    """A waveform starting with clk already HIGH must NOT treat row 0 as a posedge
    (no preceding 0→1). With the bug, the phantom row-0 pair contradicts a real
    pair → SKIP; with the fix, row 0 is ignored and the synth FIRES the correct
    next-state. This fixture therefore FIRES only when the phantom is suppressed."""
    rtl = W.synth(_SEQ_FF_LEADING_HIGH, "TopModule")
    assert rtl is not None and "always @(posedge clk)" in rtl
    assert "(a & ~state)" in rtl  # the one real next-state minterm


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── code-complete port decl with a trailing comment (v1.1.41 prod gap) ─────────
def test_parse_ports_tolerates_trailing_comment():
    # VerilogEval code-complete headers annotate a port: `input [9:0] state, // ...`
    # The decl regex must not drop the port (Prob150 one-hot synth SKIPped without it).
    p = ("Implement TopModule.\n"
         "  input d,\n"
         "  input [9:0] state, // 10-bit one-hot current state\n"
         "  output q\n")
    ports = W.parse_ports(p)
    assert ports is not None
    assert "state" in ports and ports["state"][1] == 10
    assert "q" in ports
