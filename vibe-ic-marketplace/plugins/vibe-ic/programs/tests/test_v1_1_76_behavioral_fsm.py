#!/usr/bin/env python3
"""test_v1_1_76_behavioral_fsm.py — pins behavioral_fsm_synth.py.

behavioral_fsm_synth solves the STRICT mechanically-complete subset of the
behavioral-prose Moore-FSM family — the canonical hard case — and is HONEST about
the AI-floor for the rest. Two shapes FIRE (both host-verified to 0 mismatches
against the VerilogEval dataset reference):

  (A) Moore-LATCHED sequence detector  -> Prob096_review2015_fsmseq  (1101, latched)
  (B) reset-PULSE counter              -> Prob095_review2015_fsmshift (4 cycles)

Everything whose transitions are woven into narrative MUST SKIP (a wrong FSM is far
worse than a SKIP, §4.05). The FLOOR map below records, per resisting problem, the
exact sentence a general parser cannot mechanically turn into a complete unambiguous
transition table — confirming an independent blind read is required.

Run from the programs/ dir or via the suite; iverilog cases auto-skip if the tool
is absent, but the GENERATE + SKIP-discipline assertions always run.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
if _PROGRAMS not in sys.path:
    sys.path.insert(0, _PROGRAMS)

import behavioral_fsm_synth as bfsm  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

# Dataset location (host-scoring is best-effort; absent dataset -> those cases skip).
_DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def _prompt(name):
    p = os.path.join(_DS, name + "_prompt.txt")
    if not os.path.exists(p):
        pytest.skip(f"dataset prompt absent: {name}")
    return open(p, errors="replace").read()


def _host_score(name, rtl):
    """Compile generated rtl + ref + test; return mismatch count (int) or skip."""
    ref = os.path.join(_DS, name + "_ref.sv")
    tst = os.path.join(_DS, name + "_test.sv")
    if not (os.path.exists(ref) and os.path.exists(tst)):
        pytest.skip(f"dataset ref/test absent: {name}")
    with tempfile.TemporaryDirectory() as d:
        dut = os.path.join(d, "dut.sv")
        sim = os.path.join(d, "sim")
        with open(dut, "w") as f:
            f.write(rtl)
        c = subprocess.run(["iverilog", "-g2012", "-o", sim, dut, ref, tst],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed for {name}:\n{c.stderr}"
        r = subprocess.run(["vvp", sim], capture_output=True, text=True)
        out = r.stdout + r.stderr
        import re
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        assert m, f"no mismatch line for {name}:\n{out}"
        return int(m.group(1)), int(m.group(2))


# --------------------------------------------------------------------------- #
# POSITIVES — the two shapes FIRE and (when iverilog is present) host-verify 0.
# --------------------------------------------------------------------------- #
def test_latched_sequence_detector_fires():
    """(A) Prob096 — latched 1101 detector. Generated, not None."""
    rtl = bfsm.synth(_prompt("Prob096_review2015_fsmseq"))
    assert rtl is not None
    assert "module TopModule" in rtl
    # KMP table for 1101 (S=0,S1,S11,S110,Done) + a latched output on the accept state.
    assert "ACCEPT = 3'd4" in rtl
    assert "state == ACCEPT" in rtl
    # absorbing accept state self-loops on both bits
    assert "3'd4: nstate = data ? 3'd4 : 3'd4" in rtl


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_latched_sequence_detector_host_zero_mismatch():
    rtl = bfsm.synth(_prompt("Prob096_review2015_fsmseq"))
    assert rtl is not None
    mm, total = _host_score("Prob096_review2015_fsmseq", rtl)
    assert mm == 0, f"Prob096 had {mm}/{total} mismatches"
    assert total > 0


def test_reset_pulse_counter_fires():
    """(B) Prob095 — assert for 4 cycles then 0 forever. Generated, not None."""
    rtl = bfsm.synth(_prompt("Prob095_review2015_fsmshift"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "DONE = 3'd4" in rtl                    # 4 active cycles, Done is state 4
    assert "shift_ena = (state != DONE)" in rtl


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_reset_pulse_counter_host_zero_mismatch():
    rtl = bfsm.synth(_prompt("Prob095_review2015_fsmshift"))
    assert rtl is not None
    mm, total = _host_score("Prob095_review2015_fsmshift", rtl)
    assert mm == 0, f"Prob095 had {mm}/{total} mismatches"
    assert total > 0


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK NEGATIVES — the narrative behavioral FSMs MUST SKIP (>=5).
# Each carries a FLOOR-proof: the sentence a general parser cannot mechanically
# convert into a complete unambiguous transition table. SKIP, never a guess.
# --------------------------------------------------------------------------- #
# FLOOR MAP — (problem, resisting-sentence quote, why it resists mechanical parse)
_FLOOR_NEGATIVES = [
    (
        "Prob127_lemmings1",
        'if a Lemming is bumped on the left (by receiving a 1 on bump_left), it '
        'will walk right',
        "The two states (walk_left/walk_right) are never NAMED as states — they are "
        "OUTPUTS — and the arc is a SEMANTIC direction inversion (bump-left -> walk "
        "RIGHT). No 'in state X, on cond -> state Y' sentence exists to parse.",
    ),
    (
        "Prob142_lemmings2",
        'when ground=0, the Lemming will fall and say "aaah!". When the ground '
        'reappears (ground=1), the Lemming will resume walking in the same '
        'direction as before the fall',
        "'resume ... in the same direction as before the fall' requires MEMORY of the "
        "pre-fall direction encoded as a hidden FALLL/FALLR state split that the prose "
        "never enumerates — pure NL state-set inference.",
    ),
    (
        "Prob152_lemmings3",
        'If more than one of these conditions are satisfied, fall has higher '
        'precedence than dig, which has higher precedence than switching directions.',
        "The precedence ordering across fall/dig/switch plus the DIGL/DIGR latent "
        "state split must be synthesised from narrative — there is no transition "
        "table; a parser cannot derive the 6-state machine mechanically.",
    ),
    (
        "Prob155_lemmings4",
        'if a Lemming falls for more than 20 clock cycles then hits the ground, it '
        'will splatter and cease walking, falling, or digging',
        "A hidden 5-bit fall-duration COUNTER with a '>20 then ground' guard and a "
        "DEAD absorbing state — none of which is stated as states/arcs; deriving the "
        "counter datapath from prose is genuine NL understanding.",
    ),
    (
        "Prob128_fsm_ps2",
        'discard bytes until we see one with in[3]=1. We then assume that this is '
        'byte 1 of a message, and signal the receipt of a message once all 3 bytes '
        'have been received',
        "The bit-index gate (in[3]), the 3-byte count, the done-in-the-NEXT-cycle "
        "pulse, and the re-arm-on-in[3] semantics are described purely behaviorally; "
        "the state set (BYTE1..DONE) is unnamed and the re-arm arc is implicit.",
    ),
    (
        "Prob133_2014_q3fsm",
        'Once in state B the FSM examines the value of the input w in the next three '
        'clock cycles. If w = 1 in exactly two of these clock cycles, then the FSM '
        'has to set an output z to 1',
        "A sliding 3-cycle window with a population-count == 2 acceptance: the "
        "binary counting tree (S10/S11/S20/S21/S22) must be SYNTHESISED, it is not "
        "tabulated — genuine combinatorial-state inference.",
    ),
    (
        "Prob139_2013_q2bfsm",
        'When x has produced the values 1, 0, 1 in three successive clock cycles, '
        'then g should be set to 1 on the following clock cycle. While maintaining '
        'g = 1 the FSM has to monitor the y input. If y has the value 1 within at '
        'most two clock cycles, then the FSM should maintain g = 1 permanently',
        "A multi-phase controller (f-pulse -> 101-detect -> g -> y-within-2-window) "
        "whose phases and the 2-cycle y deadline are narrative; the 9-state machine "
        "is not enumerated anywhere.",
    ),
    (
        "Prob074_ece241_2014_q4",
        'Input x goes to three different two-input gates: an XOR, an AND, and a OR '
        'gate. Each of the three gates is connected to the input of a D flip-flop '
        'and then the flip-flop outputs all go to a three-input NOR gate',
        "This is a STRUCTURAL gate-network description (per-bit feedback equations), "
        "not a state-transition FSM at all; there is no enumerable state list to "
        "extract — it needs datapath synthesis from the wiring prose.",
    ),
    (
        "Prob136_m2014_q6",
        ' - input  reset',
        "The arrow diagram IS complete, but the prompt states NOTHING about the reset "
        "(no reset state, no sync/async, no active level) — only the port exists. "
        "full_moore_fsm_synth already SKIPs it for this reason; guessing reset->first "
        "state/active-high/sync would be a §4.05 leak.",
    ),
    (
        "Prob148_2013_q2afsm",
        'There is a priority system, in that device 0 has a higher priority than '
        'device 1, and device 2 has the lowest priority.',
        "The diagram is DEFECTIVE for a mechanical parser: state D has NO outgoing "
        "arcs and the A->D condition literally duplicates A->A; D's transitions and "
        "the request priority must be read from PROSE, not the diagram.",
    ),
]


@pytest.mark.parametrize("name,quote,_why", _FLOOR_NEGATIVES,
                         ids=[n for n, _, _ in _FLOOR_NEGATIVES])
def test_floor_negatives_skip_and_proof(name, quote, _why):
    """Each narrative behavioral FSM SKIPs (None), and its FLOOR-proof sentence is
    actually present in the prompt (the proof is grounded, not invented)."""
    text = _prompt(name)
    assert bfsm.synth(text) is None, (
        f"§4.05 LEAK: {name} must SKIP (narrative FSM, no mechanical table) but fired")
    # the resisting sentence is really in the prompt (proof is doc-grounded).
    norm = " ".join(text.split())
    qn = " ".join(quote.split())
    assert qn in norm, f"FLOOR-proof quote not found verbatim in {name} prompt"


# --------------------------------------------------------------------------- #
# Extra no-leak guards: the two shapes must not over-fire on near-miss prompts.
# --------------------------------------------------------------------------- #
def test_no_overfire_on_unrelated_clk_reset_modules():
    """A plain clk+reset prompt with no latch/pulse phrasing must SKIP."""
    txt = (
        "module TopModule ( input clk, input reset, output q );\n"
        "A simple register that loads its previous value. Reset is active high "
        "synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_pulse_requires_full_phrasing():
    """A prompt that merely mentions 'N cycles' without the assert+then-0-forever
    tail must SKIP (the count alone is not the reset-pulse shape)."""
    txt = (
        " - input  clk\n - input  reset\n - output q\n"
        "The signal q toggles for 4 clock cycles in some unrelated way. Reset is "
        "active high synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_sequence_requires_latch():
    """A stated sequence WITHOUT a latched-forever output must SKIP — that is the
    Mealy-pulse case mealy_sequence_synth owns, never ours."""
    txt = (
        " - input  clk\n - input  reset\n - input  data\n - output z\n"
        "Detect the sequence 1101 and pulse z high for one cycle. Reset is active "
        "high synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_missing_reset_spec_sequence():
    """Latched sequence detector with NO sync/async or level stated must SKIP."""
    txt = (
        " - input  clk\n - input  reset\n - input  data\n - output z\n"
        "Search for the sequence 1101; once found set z to 1 forever until reset.\n")
    # no 'synchronous'/'asynchronous' and no active level -> reset under-specified
    assert bfsm.synth(txt) is None


# --------------------------------------------------------------------------- #
# Generality guard: the parser is NOT keyword-overfit to any SKU/word.
# A re-skinned latched detector with a DIFFERENT sequence + renamed ports fires;
# a re-skinned pulse with a different N fires — proving structure, not keywords.
# --------------------------------------------------------------------------- #
def test_general_other_sequence_and_ports():
    txt = (
        " - input  clk\n - input  rst_n\n - input  serial_in\n - output found\n"
        "The block searches for the pattern 10110 in serial_in and must set found "
        "to 1, forever, until reset. Reset is active low synchronous.\n")
    rtl = bfsm.synth(txt)
    assert rtl is not None
    assert "serial_in" in rtl and "found" in rtl
    # 10110 -> accept state 5; active-low sync reset honoured.
    assert "ACCEPT = 3'd5" in rtl
    assert "if (!rst_n)" in rtl


def test_general_other_pulse_count_and_polarity():
    txt = (
        " - input  clk\n - input  areset\n - output en\n"
        "Whenever the machine is reset, assert en for exactly 7 cycles, then 0 "
        "forever (until reset). areset is asynchronous active high.\n")
    rtl = bfsm.synth(txt)
    assert rtl is not None
    assert "DONE = 3'd7" in rtl                     # 7 active cycles
    assert "posedge areset" in rtl                  # async edge emitted


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
