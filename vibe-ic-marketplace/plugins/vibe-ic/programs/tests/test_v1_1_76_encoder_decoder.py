#!/usr/bin/env python3
"""test_v1_1_76_encoder_decoder.py — tests for encoder_decoder_synth.py.

Covers:
  * POSITIVES — the two real dataset family members (Prob071 casez priority
    encoder, Prob112 dense-case priority encoder) FIRE and emit RTL that is
    structurally correct (the exact casez convention the dataset reference uses);
    plus a synthetic LSB-first encoder of a third width to prove width-generality.
  * §4.05 NO-LEAK NEGATIVES (>= 5) — every prompt that leaves the direction, the
    zero-input default, the widths, or the function itself ambiguous MUST return
    None (SKIP). Includes the real near-miss dataset prompts (a multiplexer, a
    scancode lookup table) that also speak about bits/positions but are NOT a
    priority encoder.

If iverilog is on PATH, the two real positives are additionally HOST-SCORED
against the dataset reference + testbench (0 mismatches is the authoritative
gate); otherwise that part is skipped.
"""
from __future__ import annotations

import importlib.util
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from _hostpaths import corpus_path  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_SPEC = importlib.util.spec_from_file_location(
    "encoder_decoder_synth", _PROGRAMS / "encoder_decoder_synth.py"
)
eds = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(eds)

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


def _ds(prob: str) -> str:
    return (_DS / f"{prob}_prompt.txt").read_text(errors="replace")


_HAVE_DS = _DS.is_dir()
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# --------------------------------------------------------------------------- #
# POSITIVES                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _HAVE_DS, reason="dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
@pytest.mark.parametrize("prob,inw,outw", [
    ("Prob071_always_casez", 8, 3),
    ("Prob112_always_case2", 4, 2),
])
def test_real_family_fires(prob, inw, outw):
    rtl = eds.synth(_ds(prob))
    assert rtl is not None, f"{prob} should FIRE"
    assert "module TopModule" in rtl
    assert "casez" in rtl
    # the input vector and the output position port, at the stated widths
    assert f"input [{inw-1}:0] in" in rtl
    assert f"output reg [{outw-1}:0] pos" in rtl
    # one explicit-1 arm per position, lowest-first, with don't-care elsewhere
    assert f"{inw}'b" + "z" * (inw - 1) + "1: pos = {}'d0".format(outw) in rtl
    assert f"{inw}'b1" + "z" * (inw - 1) + ": pos = {}'d{}".format(outw, inw - 1) in rtl
    # a zero default for the all-zero input
    assert re.search(r"default\s*:\s*pos = \d+'h0", rtl)


def test_synthetic_width16_fires_lsb_first():
    """A 16-bit LSB-first priority encoder with a stated zero default (width
    generality beyond the two dataset widths)."""
    prompt = (
        " - input  in  (16 bits)\n"
        " - output pos (4 bits)\n"
        "Implement a priority encoder. Report the position of the first (least\n"
        "significant) bit that is 1. If none of the input bits are high, output zero.\n"
    )
    rtl = eds.synth(prompt)
    assert rtl is not None
    assert "input [15:0] in" in rtl
    assert "output reg [3:0] pos" in rtl
    assert "16'b" + "z" * 15 + "1: pos = 4'd0" in rtl
    assert "16'b1" + "z" * 15 + ": pos = 4'd15" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK NEGATIVES (>= 5) — each MUST return None                       #
# --------------------------------------------------------------------------- #
def test_neg_direction_unstated():
    """Priority encoder whose direction (LSB vs MSB) is NOT stated -> SKIP."""
    prompt = (
        " - input  in  (8 bits)\n"
        " - output pos (3 bits)\n"
        "Implement a priority encoder. If none of the input bits are high,\n"
        "output zero.\n"  # which bit wins is never stated -> ambiguous
    )
    assert eds.synth(prompt) is None


def test_neg_msb_first_direction():
    """An MSB-first (highest set bit) encoder — direction stated but NOT the
    LSB-first one the solver authors -> SKIP (never mis-emit an LSB encoder)."""
    prompt = (
        " - input  in  (8 bits)\n"
        " - output pos (3 bits)\n"
        "Implement a priority encoder reporting the position of the highest\n"
        "(most significant) bit that is 1. If the input is zero, output zero.\n"
    )
    assert eds.synth(prompt) is None


def test_neg_zero_default_unstated():
    """Direction LSB-first but the all-zero-input behavior is NOT stated -> SKIP
    (priority-encoder zero convention is not universal)."""
    prompt = (
        " - input  in  (8 bits)\n"
        " - output pos (3 bits)\n"
        "Implement a priority encoder reporting the position of the first\n"
        "(least significant) bit that is 1.\n"  # nothing about all-zero input
    )
    assert eds.synth(prompt) is None


def test_neg_width_mismatch():
    """Output width does not equal ceil(log2(N)) — interface contradicts the
    stated behavior -> SKIP (do not silently truncate / pad)."""
    prompt = (
        " - input  in  (8 bits)\n"
        " - output pos (2 bits)\n"  # 8 needs 3 bits, not 2
        "Implement a priority encoder. Report the position of the first (least\n"
        "significant) set bit. If none of the input bits are high, output zero.\n"
    )
    assert eds.synth(prompt) is None


def test_neg_multiplexer_not_encoder():
    """A multiplexer prompt also speaks about a select value but is NOT a
    priority encoder -> SKIP."""
    if _HAVE_DS:
        prompt = _ds("Prob076_always_case")
    else:
        prompt = (
            " - input  sel (3 bits)\n - input data0 (4 bits)\n"
            " - output out (4 bits)\nImplement a 6-to-1 multiplexer. "
            "Otherwise output 0.\n"
        )
    assert eds.synth(prompt) is None


def test_neg_scancode_lookup_table():
    """A scancode lookup table (case-based, has a zero default, mentions bits)
    is NOT a priority encoder -> SKIP."""
    if _HAVE_DS:
        prompt = _ds("Prob114_bugs_case")
    else:
        prompt = (
            " - input  code (8 bits)\n - output out (4 bits)\n - output valid\n"
            "Recognize 8-bit keyboard scancodes. If no match, both outputs 0.\n"
        )
    assert eds.synth(prompt) is None


def test_neg_extra_clock_port():
    """A 'priority encoder' with a clock is sequential / not the pure combinational
    family -> SKIP."""
    prompt = (
        " - input  clk\n"
        " - input  in  (8 bits)\n"
        " - output pos (3 bits)\n"
        "Implement a priority encoder. Report the first (least significant) set\n"
        "bit. If none of the bits are high, output zero.\n"
    )
    assert eds.synth(prompt) is None


def test_neg_not_an_encoder_at_all():
    """An ordinary combinational prompt with no priority-encoder signature -> SKIP."""
    prompt = (
        " - input  a (8 bits)\n - input b (8 bits)\n - output s (8 bits)\n"
        "Implement an 8-bit adder that outputs the sum of a and b.\n"
    )
    assert eds.synth(prompt) is None


# --------------------------------------------------------------------------- #
# CORPUS NO-LEAK — only the family members fire across the whole dataset       #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _HAVE_DS, reason="dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_corpus_no_leak():
    fired = []
    for f in sorted(_DS.glob("*_prompt.txt")):
        if eds.synth(f.read_text(errors="replace")) is not None:
            fired.append(f.name.replace("_prompt.txt", ""))
    assert fired == ["Prob071_always_casez", "Prob112_always_case2"], fired


# --------------------------------------------------------------------------- #
# HOST-SCORE — authoritative: iverilog + the dataset ref + testbench           #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (_HAVE_DS and _HAVE_IVERILOG),
                    reason="dataset or iverilog not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
@pytest.mark.parametrize("prob", ["Prob071_always_casez", "Prob112_always_case2"])
def test_host_score_zero_mismatches(prob):
    rtl = eds.synth(_ds(prob))
    assert rtl is not None
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp = Path(d) / "sim.vvp"
        ref = _DS / f"{prob}_ref.sv"
        tb = _DS / f"{prob}_test.sv"
        cp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
            capture_output=True, text=True, cwd=d,
        )
        assert cp.returncode == 0, f"compile failed:\n{cp.stderr}"
        run = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, cwd=d)
        out = run.stdout + run.stderr
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", out)
        assert m, f"no mismatch line in output:\n{out}"
        assert int(m.group(1)) == 0, f"{prob} had {m.group(1)} mismatches:\n{out}"
        assert int(m.group(2)) > 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
