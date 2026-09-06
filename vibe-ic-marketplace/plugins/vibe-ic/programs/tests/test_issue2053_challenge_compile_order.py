#!/usr/bin/env python3
"""Argument order is not a verdict input, and the declared timescale is read.

MEASURED 2026-09-06 (RTLLM blind run, finding BR-08; reproduced independently
on 8HD-8 before this fix). ``benchmark_dispatch`` compiled the AI challenge as
``[*rtl_paths, test_path]`` -- candidate RTL FIRST. ```timescale`` is a compiler
directive that applies from its point of appearance FORWARD, across files, in
compile order, so a candidate that declares none inherits the challenge's unit
when the challenge is compiled first and iverilog's default when it is not. On
a CORRECT ``clkgenerator`` candidate:

    RTL-first                             FAIL   (period read as 10000000000)
    testbench-first                       PASS
    RTL-first + a `timescale on a copy    PASS

The runner therefore rejected a correct candidate with "the frozen candidate
must pass its required test". A verdict that argument order can flip is not a
verdict -- the same principle as ``_challenge_forbidden_hit``, where a comment
could flip a guard about code.

The fix states the DECLARED unit once, ahead of every source, so every file
shares it in any order. It is never guessed: with no declaration anywhere there
is no prelude, and every file keeps the same default, which is already
order-independent. A candidate and challenge that declare DIFFERENT units are
refused by name, because imposing either one would put compile order back in
charge of the answer.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import test_challenge_compile_attribution as att

bd = att.bd
_NEEDS_SIMULATOR = att._NEEDS_SIMULATOR

# A correct candidate that declares no timescale of its own: a 10-unit period.
_CLKGEN_RTL = """module candidate(output reg clk);
  initial clk = 1'b0;
  always #5 clk = ~clk;
endmodule
"""

# The challenge declares the unit. Under it, one period is exactly 10.
_CLKGEN_TB = """`timescale 1ns/1ps
module vibeic_ai_challenge_tb;
  wire clk;
  candidate u(.clk(clk));
  time t0, t1;
  initial begin
    @(posedge clk); t0 = $time;
    @(posedge clk); t1 = $time;
    if ((t1 - t0) == 10) $display("VIBEIC_AI_CHALLENGE=PASS");
    else $display("VIBEIC_AI_CHALLENGE=FAIL");
    $finish;
  end
endmodule
"""

_RTL_WITH_TIMESCALE = "`timescale 1ps/1ps\n" + _CLKGEN_RTL


def _pair(tmp_path, rtl=_CLKGEN_RTL, tb=_CLKGEN_TB):
    run, task = att._task(tmp_path, rtl)
    return task["candidate_snapshot"], att._challenge(task, tb)


def _swap_sources(monkeypatch):
    """Compile the SAME files in the opposite order, and nothing else.

    Everything up to ``-o <out>`` is the fixed part of the command; the rest is
    the source list. Reversing only that list is exactly the perturbation under
    test -- if the verdict moves, compile order decided it.
    """
    real = subprocess.run

    def reordered(argv, *args, **kwargs):
        argv = list(argv)
        if argv and str(argv[0]).endswith("iverilog") and "-o" in argv:
            cut = argv.index("-o") + 2
            argv = argv[:cut] + list(reversed(argv[cut:]))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", reordered)


# --- the defect itself -------------------------------------------------

@_NEEDS_SIMULATOR
def test_a_correct_candidate_with_no_timescale_passes_its_challenge(tmp_path):
    """The frozen clkgenerator shape. Before the fix this was a FAIL, and the
    runner reported it as the candidate failing its required test."""
    candidate, challenge = _pair(tmp_path)
    result = bd._run_verification_challenge(candidate, challenge)
    assert result["status"] == "PASS", result


@_NEEDS_SIMULATOR
def test_swapping_the_compile_order_cannot_move_the_verdict(
        tmp_path, monkeypatch):
    """The property, asserted directly: same files, opposite order, same answer."""
    candidate, challenge = _pair(tmp_path)
    forward = bd._run_verification_challenge(candidate, challenge)
    _swap_sources(monkeypatch)
    reversed_ = bd._run_verification_challenge(candidate, challenge)
    assert forward["status"] == reversed_["status"] == "PASS", (forward, reversed_)


@_NEEDS_SIMULATOR
def test_order_independence_holds_for_a_WRONG_candidate_too(tmp_path, monkeypatch):
    """Order independence must not be bought by making everything pass.

    This candidate has the wrong period, so the honest verdict is FAIL in both
    orders. Without this half, a fix that forced PASS would satisfy the test
    above and still be wrong.
    """
    wrong = _CLKGEN_RTL.replace("#5", "#3")
    candidate, challenge = _pair(tmp_path, rtl=wrong)
    forward = bd._run_verification_challenge(candidate, challenge)
    _swap_sources(monkeypatch)
    reversed_ = bd._run_verification_challenge(candidate, challenge)
    assert forward["status"] == reversed_["status"] == "FAIL", (forward, reversed_)


@_NEEDS_SIMULATOR
def test_a_challenge_declaring_no_timescale_is_left_alone(tmp_path, monkeypatch):
    """Never guess a unit. With nothing declared anywhere there is no prelude,
    every file keeps the same default, and the answer is already the same in
    both orders."""
    tb = _CLKGEN_TB.replace("`timescale 1ns/1ps\n", "")
    candidate, challenge = _pair(tmp_path, tb=tb)
    forward = bd._run_verification_challenge(candidate, challenge)
    _swap_sources(monkeypatch)
    reversed_ = bd._run_verification_challenge(candidate, challenge)
    assert forward["status"] == reversed_["status"] == "PASS", (forward, reversed_)


@_NEEDS_SIMULATOR
def test_disagreeing_timescales_are_refused_by_name(tmp_path):
    """Two different declared units have no single right answer to impose, and
    choosing one would put compile order back in charge. Refused, not decided."""
    candidate, challenge = _pair(tmp_path, rtl=_RTL_WITH_TIMESCALE)
    result = bd._run_verification_challenge(candidate, challenge)
    assert result["status"] == "INVALID", result
    assert any("different timescales" in r for r in result["reasons"]), result
    assert any("1ps/1ps" in r and "1ns/1ps" in r for r in result["reasons"]), result


@_NEEDS_SIMULATOR
def test_agreeing_timescales_are_not_refused(tmp_path):
    """The negative control for the refusal above: a candidate that declares
    the SAME unit as the challenge must still be judged, not refused."""
    candidate, challenge = _pair(
        tmp_path, rtl="`timescale 1ns/1ps\n" + _CLKGEN_RTL)
    result = bd._run_verification_challenge(candidate, challenge)
    assert result["status"] == "PASS", result


# --- reading the declared unit ----------------------------------------

@pytest.mark.parametrize("source, expected", [
    ("`timescale 1ns/1ps\nmodule m; endmodule\n", "1ns/1ps"),
    ("`timescale 10 ns / 100 ps\n", "10ns/100ps"),
    ("`timescale 1s/1s\n", "1s/1s"),
    ("module m; endmodule\n", None),
    # A directive that is COMMENTED OUT is prose. Same rule, and the same
    # comment stripper, as `_challenge_forbidden_hit`.
    ("// `timescale 1ns/1ps\nmodule m; endmodule\n", None),
    ("/* `timescale 1ns/1ps */\nmodule m; endmodule\n", None),
    # The FIRST declaration is the one in force at the top of the file.
    ("`timescale 1ns/1ps\nmodule a; endmodule\n`timescale 1ps/1ps\n", "1ns/1ps"),
])
def test_the_declared_timescale_is_read_never_guessed(source, expected):
    assert bd._declared_timescale(source) == expected


def test_an_unreadable_candidate_file_is_not_a_disagreement():
    """"Could not read it" is not "read it and it disagreed"."""
    assert bd._timescale_disagreement(["/nonexistent/dut.v"], "1ns/1ps") is None


def test_no_declared_unit_is_never_a_disagreement(tmp_path):
    rtl = tmp_path / "dut.v"
    rtl.write_text(_RTL_WITH_TIMESCALE)
    assert bd._timescale_disagreement([str(rtl)], None) is None
    assert bd._timescale_disagreement([str(rtl)], "1ps/1ps") is None
    assert bd._timescale_disagreement([str(rtl)], "1ns/1ps") is not None
