#!/usr/bin/env python3
"""§4.05 carve-out: the `shift-implemented-as-rotate` conformance rule must NOT
fire on a Galois LFSR, but MUST still fire on a pure data rotate.

The plugin's own deterministic `galois_lfsr` solver (spec_artifact_registry)
emits `q_next = {q[0], q[W-1:1]}; q_next[tap] ^= q[0];` — the SAME wrap concat a
right-rotate uses, but with tap-XOR linear FEEDBACK. Before this carve-out the
rotate-veto blocked that emit on EVERY Galois LFSR (Prob082/086), so the
solver's correct output never reached the host TB (no_sample). The blind run
failed while the tier-pipeline reported the design "Tier-1 solved" (it verified
the solver against iverilog only, never through this conformance gate).

POSITIVE: the LFSR wrap (with tap-XOR) is NOT a rotate signature.
NEGATIVE (no-leak): a PURE rotate (wrap concat, no tap-XOR) IS still a rotate
signature — the relaxation does not leak.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import spec_conformance_check as c  # noqa: E402


def test_galois_lfsr_self_xor_not_rotate():
    lfsr = (
        "reg [31:0] q_next;\n"
        "always @(*) begin\n"
        "  q_next = {q[0], q[31:1]};\n"
        "  q_next[21] = q_next[21] ^ q[0];\n"
        "  q_next[1]  = q_next[1]  ^ q[0];\n"
        "  q_next[0]  = q_next[0]  ^ q[0];\n"
        "end\n"
    )
    assert c._rtl_rotate_signatures(lfsr) == []


def test_galois_lfsr_compound_xor_not_rotate():
    lfsr = (
        "always @(*) begin\n"
        "  q_next = {q[0], q[31:1]};\n"
        "  q_next[21] ^= q[0];\n"
        "end\n"
    )
    assert c._rtl_rotate_signatures(lfsr) == []


def test_pure_right_rotate_still_flagged():
    # wrap concat, NO tap-XOR -> still a rotate (no leak)
    rot = "always @(*) begin\n  q_next = {q[0], q[31:1]};\nend\n"
    assert c._rtl_rotate_signatures(rot)


def test_pure_left_rotate_still_flagged():
    assert c._rtl_rotate_signatures("assign y = {x[30:0], x[31]};")


def test_or_of_opposite_shifts_rotate_still_flagged():
    # the other rotate family must be unaffected by the carve-out
    assert c._rtl_rotate_signatures("assign y = (x << 3) | (x >> 5);")
