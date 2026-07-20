#!/usr/bin/env python3
"""Tests for dff_primitive_synth.py + its wiring into verilogeval_tier_pipeline.

Covers:
  * POSITIVE: the bare D-FF and the sync-reset D-FF emit correct RTL, and both
    score `Mismatches: 0` against the official VerilogEval-v2 testbench (Tier1).
  * §4.05 NEGATIVE no-leak: the solver SKIPs (returns None) on every fixture that
    sits JUST OUTSIDE the bare-single-bit-D-FF envelope — async reset, non-zero
    reset value, a vector data path, an enable/load, an FSM cue, a multiplexer
    cue, a missing d/q port, and a d-declared-as-output contradiction. A too-wide
    primitive solver would emit a WRONG register for these, so the negative proof
    is the load-bearing half.
  * MIS-FIRE sweep: across the whole dataset the solver fires on EXACTLY the two
    intended D-FF problems and nothing else.

The iverilog-dependent end-to-end checks are SKIPPED when iverilog is absent.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dff_primitive_synth as D          # noqa: E402
import verilogeval_tier_pipeline as P    # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)
_HAVE_DATASET = _DATASET.is_dir()
_needs_iv = pytest.mark.skipif(not _HAVE_IVERILOG,
                               reason="iverilog/vvp not installed")
_needs_ds = pytest.mark.skipif(not _HAVE_DATASET,
                               reason="VerilogEval dataset absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")

# --------------------------------------------------------------------------- #
# Prompt fixtures (prose shapes only — no golden RTL is read by the solver)
# --------------------------------------------------------------------------- #
_BARE_DFF = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input clk
 - input d
 - input q

The module should implement a single D flip-flop. Assume all sequential
logic is triggered on the positive edge of the clock.
"""

_SYNC_RESET_DFF = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  d
 - input  r
 - output q

The module should implement a simple D flip flop with active high
synchronous reset (reset output to 0).
"""

# §4.05 negative fixtures — each is JUST OUTSIDE the envelope.
_ASYNC_DFF = """
 - input  clk
 - input  areset
 - input  d
 - output q

The module should implement a D flip-flop with an asynchronous reset.
"""

_PRESET_DFF = """
 - input  clk
 - input  d
 - input  set
 - output q

The module should implement a D flip-flop. When set is asserted, reset the
output to 1.
"""

_VECTOR_DFF = """
 - input  clk
 - input  d (8 bits)
 - output q (8 bits)

The module should implement a D flip-flop (8-bit wide register).
"""

_ENABLE_DFF = """
 - input  clk
 - input  d
 - input  ena
 - output q

The module should implement a D flip-flop with an enable. Hold the value
when ena is 0.
"""

_FSM_NOT_DFF = """
 - input  clk
 - input  d
 - output q

The module should implement a finite state machine built from D flip-flops.
"""

_MUX_NOT_DFF = """
 - input  clk
 - input  d
 - input  sel
 - output q

A 2-to-1 multiplexer feeds a D flip-flop.
"""

_NO_Q_DFF = """
 - input  clk
 - input  d
 - output result

The module should implement a single D flip-flop.
"""

_D_IS_OUTPUT = """
 - input  clk
 - output d
 - input  q

The module should implement a single D flip-flop.
"""


# --------------------------------------------------------------------------- #
# POSITIVE — correct emit shape
# --------------------------------------------------------------------------- #
def test_bare_dff_emits_register():
    rtl = D.synth(_BARE_DFF, "TopModule")
    assert rtl is not None
    assert "module TopModule" in rtl
    # output q regardless of the prompt's `input q` typo (primitive shape wins).
    assert "output reg q" in rtl
    assert "q <= d;" in rtl
    assert "posedge clk" in rtl
    # bare D-FF has no reset branch.
    assert "if (" not in rtl


def test_sync_reset_dff_emits_reset_to_zero():
    rtl = D.synth(_SYNC_RESET_DFF, "TopModule")
    assert rtl is not None
    assert "input r" in rtl
    assert "if (r)" in rtl
    assert "q <= 1'b0;" in rtl
    assert "q <= d;" in rtl
    assert "posedge clk" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE no-leak — every boundary-outside fixture must SKIP
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt,why", [
    (_ASYNC_DFF, "async reset out of sync-only envelope"),
    (_PRESET_DFF, "non-zero (set-to-1) reset value out of reset-to-0 envelope"),
    (_VECTOR_DFF, "vector data path is not a single-bit primitive"),
    (_ENABLE_DFF, "enable/hold is not a bare D-FF"),
    (_FSM_NOT_DFF, "FSM cue out of envelope"),
    (_MUX_NOT_DFF, "multiplexer cue out of envelope"),
    (_NO_Q_DFF, "no canonical q output port"),
    (_D_IS_OUTPUT, "d declared as output is a genuine contradiction"),
])
def test_dff_skips_outside_envelope(prompt, why):
    assert D.synth(prompt, "TopModule") is None, f"LEAK: emitted for {why}"


def test_dff_skips_when_no_dff_cue():
    # No "D flip-flop" primitive name -> never fires.
    no_cue = _BARE_DFF.replace("D flip-flop", "circuit")
    assert D.synth(no_cue, "TopModule") is None


# --------------------------------------------------------------------------- #
# MIS-FIRE sweep + end-to-end Tier1 (iverilog) — the load-bearing verified claim
# --------------------------------------------------------------------------- #
@_needs_ds
def test_dff_solver_fires_on_exactly_the_two_dff_problems():
    fires = []
    for p in sorted(_DATASET.glob("*_prompt.txt")):
        if D.synth(p.read_text(errors="replace"), "TopModule"):
            fires.append(p.name[: -len("_prompt.txt")])
    assert fires == ["Prob031_dff", "Prob048_m2014_q4c"], fires


@_needs_iv
@_needs_ds
@pytest.mark.parametrize("stem", ["Prob031_dff", "Prob048_m2014_q4c"])
def test_dff_problem_classifies_tier1_with_verify(stem):
    probs = {p.stem: p for p in P.discover(str(_DATASET))}
    assert stem in probs
    res = P.tier_result(probs[stem], verify=True)
    assert res["tier"] == P.TIER_PROGRAM, res
    assert res["verified"] is True
    assert "Mismatches: 0" in res["detail"]
