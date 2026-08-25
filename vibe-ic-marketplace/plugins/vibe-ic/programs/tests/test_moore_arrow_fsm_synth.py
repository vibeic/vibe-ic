#!/usr/bin/env python3
r"""Tests for moore_arrow_fsm_synth — the Moore FSM stated as an ARROW diagram
(`A (0) --1--> B`), where the reset state and the output mapping are carried by
the arrow notation alone.

THE MACHINE, NOT THE TEXT. The positive arm compiles the emitted RTL with
iverilog, resets it, drives a fixed input sequence that visits every state, and
compares the output cycle-by-cycle against a Python model built INDEPENDENTLY
from the same arrow table. A solver that mis-encoded a transition, dropped a
Moore output, or reset into the wrong state produces a different waveform and
this goes red on the waveform.

§4.05: the solver may only ever emit the machine the diagram fully determines,
so each negative arm removes exactly one thing the emit depends on — the
synchronous reset, a single arrow, the single-bit input, the single output — and
requires None rather than a guessed machine.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import moore_arrow_fsm_synth as M  # noqa: E402

_HAVE_TOOLS = bool(shutil.which("iverilog") and shutil.which("vvp"))

_HDR = ("I would like you to implement a module named TopModule with the "
        "following\ninterface. All input and output ports are one bit unless "
        "otherwise specified.\n\n")

_PORTS = " - input  clk\n - input  reset\n - input  w\n - output z\n\n"

# The arrow table, ONCE, as data. The prose fixture and the Python reference
# model are both built from it, so the model is not a transcription of the
# emitted RTL — it is the diagram the spec states.
ARROWS = [
    ("A", 0, "1", "B"), ("A", 0, "0", "A"),
    ("B", 0, "1", "C"), ("B", 0, "0", "D"),
    ("C", 0, "1", "E"), ("C", 0, "0", "D"),
    ("D", 0, "1", "F"), ("D", 0, "0", "A"),
    ("E", 1, "1", "E"), ("E", 1, "0", "D"),
    ("F", 1, "1", "C"), ("F", 1, "0", "D"),
]
STATES = ["A", "B", "C", "D", "E", "F"]
NEXT = {(s, bit): nxt for s, _o, bit, nxt in ARROWS}
MOORE = {s: o for s, o, _b, _n in ARROWS}


def _diagram():
    return "".join(f"  {s} ({o}) --{b}--> {n}\n" for s, o, b, n in ARROWS)


def _spec(reset_sentence="Reset resets into state A and is synchronous "
                         "active-high."):
    return (_HDR + _PORTS
            + "The module should implement the state machine shown below:\n\n"
            + _diagram()
            + "\n" + reset_sentence + " Assume all sequential logic is\n"
              "triggered on the positive edge of the clock.\n")


# A fixed stimulus that walks the whole diagram (A->B->C->E->E->D->F->C->D->A...).
STIM = [1, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 0,
        1, 0, 1, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1]


def _model(reset_state="A"):
    """The output this diagram produces for STIM, computed from the arrow table."""
    state = reset_state
    out = []
    for bit in STIM:
        state = NEXT[(state, str(bit))]
        out.append(MOORE[state])
    return out


def _simulate(rtl, tmp_path):
    # Each step: drive w, clock it in, sample z ("V"), then FLIP w mid-cycle and
    # sample again ("W"). A MOORE output depends on the state alone, so the two
    # samples must agree; a Mealy emit would move under the flipped input.
    drive = "".join(
        f"    w = 1'b{b}; @(posedge clk); #1 $display(\"V %0d\", z);"
        f" w = ~w; #1 $display(\"W %0d\", z);"
        f" @(negedge clk);\n" for b in STIM)
    tb = ("module tb;\n"
          "  reg clk = 1'b0, reset, w;\n"
          "  wire z;\n"
          "  always #5 clk = ~clk;\n"
          "  TopModule dut(.clk(clk), .reset(reset), .w(w), .z(z));\n"
          "  initial begin\n"
          "    reset = 1'b1; w = 1'b0;\n"
          "    @(negedge clk); @(negedge clk);\n"
          "    reset = 1'b0;\n"
          + drive +
          "    $finish;\n"
          "  end\n"
          "endmodule\n")
    (tmp_path / "dut.v").write_text(rtl)
    (tmp_path / "tb.v").write_text(tb)
    exe = tmp_path / "sim.out"
    cp = subprocess.run(["iverilog", "-g2012", "-o", str(exe),
                         str(tmp_path / "dut.v"), str(tmp_path / "tb.v")],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    cp = subprocess.run(["vvp", str(exe)], capture_output=True, text=True,
                        cwd=str(tmp_path))
    assert cp.returncode == 0, cp.stderr
    after_edge = [int(m.group(1))
                  for m in re.finditer(r"^V (\d+)$", cp.stdout, re.M)]
    input_flipped = [int(m.group(1))
                     for m in re.finditer(r"^W (\d+)$", cp.stdout, re.M)]
    assert input_flipped == after_edge, (
        "the output moved when only the INPUT changed — that is a Mealy machine, "
        "not the Moore machine the diagram states")
    return after_edge


@pytest.mark.skipif(not _HAVE_TOOLS, reason="iverilog/vvp not installed on this host")
def test_emitted_fsm_reproduces_the_arrow_diagram_cycle_by_cycle(tmp_path):
    rtl = M.synth(_spec(), "TopModule")
    assert rtl is not None, "the solver must fire on a complete arrow diagram"
    observed = _simulate(rtl, tmp_path)
    assert observed == _model("A")
    # the stimulus must actually exercise the machine, or the comparison above
    # would be a constant against a constant.
    assert set(observed) == {0, 1}


@pytest.mark.skipif(not _HAVE_TOOLS, reason="iverilog/vvp not installed on this host")
def test_an_explicit_reset_sentence_beats_the_first_state_convention(tmp_path):
    """"Resets into state C" is AUTHORITATIVE over the diagram's leftmost state,
    and the difference is visible in the waveform, not only in the source."""
    rtl = M.synth(_spec("Reset resets into state C and is synchronous "
                        "active-high."), "TopModule")
    assert rtl is not None
    assert _simulate(rtl, tmp_path) == _model("C")
    assert _model("C") != _model("A"), "fixture no longer distinguishes the two"


def test_the_reset_is_synchronous_and_active_high():
    rtl = M.synth(_spec(), "TopModule")
    assert "always @(posedge clk) begin" in rtl
    assert "posedge reset" not in rtl
    assert "if (reset)" in rtl
    assert "state <= A;" in rtl


def test_the_moore_output_is_a_function_of_state_only():
    """Moore, not Mealy: the input must not appear in the output expression."""
    rtl = M.synth(_spec(), "TopModule")
    assign = [ln for ln in rtl.splitlines() if ln.strip().startswith("assign z")]
    assert assign, rtl
    assert "state == E" in assign[0] and "state == F" in assign[0]
    assert re.search(r"\bw\b", assign[0]) is None


def test_port_names_come_from_the_spec_interface():
    """chip-AGNOSTIC: rename the ports in the prose and the emit follows."""
    text = _spec().replace(" - input  reset\n", " - input  rst\n") \
                  .replace(" - input  w\n", " - input  in\n") \
                  .replace(" - output z\n", " - output out\n")
    rtl = M.synth(text, "MyBlock")
    assert rtl is not None
    assert "module MyBlock (" in rtl
    assert "  input rst,\n" in rtl and "  input in,\n" in rtl
    assert "if (rst)" in rtl
    assert "assign out = " in rtl


# --------------------------------------------------------------------------- #
# §4.05 — remove exactly one thing the emit depends on; require a SKIP
# --------------------------------------------------------------------------- #
def test_an_asynchronous_reset_spec_is_out_of_envelope():
    """This solver only emits a SYNCHRONOUS reset; emitting one for an async spec
    is a wrong machine, not an approximation."""
    assert M.synth(_spec("It should asynchronously reset into state A."),
                   "TopModule") is None
    assert M.synth(_spec().replace(" - input  reset\n", " - input  areset\n"),
                   "TopModule") is None


def test_an_incomplete_arrow_diagram_skips():
    """One missing arrow leaves a (state, input) pair undetermined."""
    partial = _spec().replace("  C (0) --0--> D\n", "")
    assert M.synth(partial, "TopModule") is None


def test_a_reset_target_that_is_not_a_state_skips():
    assert M.synth(_spec("Reset resets into state Z and is synchronous "
                         "active-high."), "TopModule") is None


def test_a_multi_bit_data_input_is_out_of_envelope():
    text = _spec().replace(" - input  w\n", " - input  w (2 bits)\n")
    assert M.synth(text, "TopModule") is None


def test_a_second_output_makes_the_moore_mapping_ambiguous():
    text = _spec().replace(" - output z\n", " - output z\n - output y\n")
    assert M.synth(text, "TopModule") is None


def test_prose_with_no_arrow_diagram_skips():
    assert M.synth(_HDR + _PORTS + "Implement a two-state toggle.\n",
                   "TopModule") is None
    assert M.synth("", "TopModule") is None
