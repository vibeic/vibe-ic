#!/usr/bin/env python3
"""VE-Human tier pipeline gate parity (mirror of the VE-v2 fix).

`verilogeval_human_tier_pipeline` granted Tier-1 on `tier1_verify` (iverilog)
alone — the same stability-test-vs-blind-run gap the VE-v2 pipeline had: a solver
emit that the real gate (gates_atomic -> spec_conformance_check) would BLOCK read
as "Tier-1 solved". `conformance_emit_blocked` closes it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import deterministic_emit_chain as C  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DSH = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")


def test_pure_rotate_emit_is_gate_blocked():
    # a shifter-spec prompt + a PURE rotate emit must be flagged by the gate
    # (shift-implemented-as-rotate) — the parity check that demotes a false Tier-1.
    prob = {"prompt": "Build a 4-bit logical right shifter. The vacated MSB is "
                      "filled with 0 each clock.", "stem": "synthetic"}
    pure_rot = ("module TopModule(input clk, input [3:0] d, output reg [3:0] q);\n"
                "  always @(posedge clk) q <= {q[0], q[3:1]};\n"
                "endmodule\n")
    assert "shift-implemented-as-rotate" in C.emit_would_be_blocked(prob["prompt"], pure_rot)


def test_clean_emit_not_blocked():
    prob = {"prompt": "Assign out to a AND b.", "stem": "synthetic"}
    clean = ("module TopModule(input a, input b, output out);\n"
             "  assign out = a & b;\nendmodule\n")
    assert C.emit_would_be_blocked(prob["prompt"], clean) == []


@pytest.mark.skipif(not (_DSH / "Prob092_gatesv100_ifc.txt").exists(),
                    reason="VE-Human dataset absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_gatesv_emit_is_conformance_clean():
    """The property, restated without the pipeline: for these two problems the
    deterministic chain fires AND its emit is gate-clean. Previously this asked
    the pipeline for a tier; a tier is that pipeline's vocabulary, while
    "fired and would not be blocked" is the thing actually being claimed."""
    for stem in ("Prob092_gatesv100", "Prob094_gatesv"):
        prompt = (_DSH / f"{stem}_prompt.txt").read_text(errors="replace")
        ifc = (_DSH / f"{stem}_ifc.txt").read_text(errors="replace")
        kind, rtl = C.try_emit(prompt, ifc, "TopModule")
        assert rtl, f"{stem}: no deterministic emitter fired"
        blocked = C.emit_would_be_blocked(prompt, rtl)
        assert blocked == [], f"{stem}: emit fires but the gate blocks it: {blocked}"
