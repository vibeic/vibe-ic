#!/usr/bin/env python3
"""When the SV frontend ladder exhausted, the FIRST rung's error was blamed on the design.

MEASURED DEFECT
===============
`_iverilog_compile_with_sv_fallback` runs a ladder: iverilog -g2012, then an
sv2v pre-pass, then a verilator (SV-2017) escape. When every rung failed it
returned rung ONE's error, and the caller labelled it::

    generic full-stack TB failed to compile against rtl/ - real structural
    defect. iverilog rc=2 stderr=.../aes_pkg.sv:19: syntax error  I give up.

Measured, rung by rung, on a staged-vendor-RTL IC:

  1. iverilog -g2012          fails on SystemVerilog      - the limit the ladder EXISTS to route around
  2. sv2v under -DSIMULATION  fails on an SVA ``[*``      - a KNOWN tool signature (ORGANIC #657)
  3. verilator escape fires   fails with MODMISSING       - the REAL cause, already diagnosed by synth
  4. the step reports rung 1 and calls it a design defect

So the operator was shown a SystemVerilog syntax error from the least capable
frontend, told the design was structurally defective, and the RTL repair loop
was driven at it — producing byte-identical RTL, declaring itself INERT, and
pointing at an RTL-repair skill and a Phase-1 re-run. Three wrong targets.

Verilator, the frontend that got furthest, had already named the informative
thing: a specific module was missing.

HONESTY IN BOTH DIRECTIONS
==========================
A genuine RTL defect that ALL frontends reject still FAILs — the last frontend
rejects it too; only WHICH rejection is shown changes. And an ABSENT verilator
produces no elaboration verdict at all, so it must NEVER be promoted to "the
design is broken": the historical iverilog failure stands instead. That guard
is what most of this file pins.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import design_one_shot_runner as D  # noqa: E402

_MODMISSING = ("%Error-MODMISSING: aes_sbox.sv:71:7: Cannot find file "
               "containing module: 'aes_sbox_dom'\n"
               "%Error: Exiting due to 1 error(s)\n")


def test_a_verilator_rejection_counts_as_a_reached_verdict():
    assert D._verilator_escape_was_reached(1, "", _MODMISSING) is True


def test_an_absent_verilator_is_not_a_design_verdict():
    """An absence must never be promoted to 'the design is broken'."""
    assert D._verilator_escape_was_reached(127, "", "") is False
    assert D._verilator_escape_was_reached(127, "", "   \n  ") is False


def test_a_compiler_not_found_is_not_a_design_verdict():
    rc, out, err = 127, "", "bash: verilator: command not found"
    assert D._compiler_was_not_found(rc, out, err) is True, (
        "precondition: this text is the flow's own not-found signature")
    assert D._verilator_escape_was_reached(rc, out, err) is False, (
        "a compiler that was never found produced no elaboration verdict, so "
        "its 'failure' says nothing about the design")


def test_the_first_rung_summary_names_how_iverilog_failed():
    text = ("Command line: iverilog -g2012 a.sv b.sv\n"
            "/x/rtl/aes_pkg.sv:19: syntax error\n"
            "I give up.\n")
    assert "aes_pkg.sv:19: syntax error" in D._first_rung_summary(text)


def test_the_first_rung_summary_degrades_without_raising():
    assert D._first_rung_summary("") == "(no iverilog diagnostic captured)"
    assert D._first_rung_summary("some other tool noise").startswith("some")


def test_the_disclosure_note_says_which_frontend_the_verdict_is_from():
    note = D._LADDER_EXHAUSTED_NOTE.format(first="aes_pkg.sv:19: syntax error",
                                           reason="sv2v produced NO conversion")
    assert "FRONTEND_LADDER_EXHAUSTED" in note
    assert "VERILATOR" in note
    assert "aes_pkg.sv:19: syntax error" in note, (
        "the iverilog failure must still be visible — it is demoted, not hidden")


def test_the_verdict_names_the_frontend_that_judged_it():
    """The message hardcoded "iverilog rc=..." whatever produced the verdict."""
    assert D._TB_FRONTEND_NAMES["verilator_sv2017"].startswith("verilator")
    assert D._TB_FRONTEND_NAMES["iverilog_g2012"] == "iverilog -g2012"
    assert D._TB_FRONTEND_NAMES["iverilog_sv2v"].startswith("iverilog")


def test_the_default_frontend_still_calls_a_rejection_a_structural_defect():
    """The narrower wording must apply ONLY to the ladder escape."""
    assert D._tb_compile_failure_label("iverilog_g2012") == \
        "real structural defect"
    assert D._tb_compile_failure_label("iverilog_sv2v") == \
        "real structural defect"


def test_the_ladder_escape_does_not_call_it_a_structural_defect():
    label = D._tb_compile_failure_label("verilator_sv2017")
    assert "structural defect" not in label
    assert "AS CONFIGURED" in label, (
        "an elaboration that fails because a parameter the input never stated "
        "selected an excluded variant is not a defect in the RTL; saying it is "
        "sends the operator to repair code that is correct")
