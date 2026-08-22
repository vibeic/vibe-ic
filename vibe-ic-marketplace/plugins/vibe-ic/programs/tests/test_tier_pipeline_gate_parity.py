#!/usr/bin/env python3
"""Tier-1 gate parity: the stability/tier pipeline must verify a Tier-1 solver
emit through the SAME conformance gate the real blind run applies — not iverilog
alone.

WHY: the tier pipeline classified galois_lfsr (Prob082/086) and comb_advanced
(Prob092/094) as "Tier-1 solved" because the solver emit passed iverilog — but
the real gate (gates_atomic -> spec_conformance_check) then BLOCKED/corrupted the
emit, so the blind run failed. A stability-pass did not equal a blind-run pass
(the "why not history-high" gap). `conformance_emit_blocked` closes it: a Tier-1
emit the gate would block is demoted.

DRIFT GUARD: the EMIT-BLOCKING rule set is a single source of truth in
spec_conformance_check; this asserts gates_atomic's gate uses the SAME set.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verilogeval_tier_pipeline as P  # noqa: E402
import spec_conformance_check as scc   # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


_GATE_SRC = _PROGRAMS.parent / "benchmark" / "gates_atomic.py"


def _load_gates_atomic():
    """Import gates_atomic BY PATH. It is not importable as `benchmark.…` from
    here, and what this file has to check is the object the gate really binds,
    not a string that looks like it."""
    spec = importlib.util.spec_from_file_location("gates_atomic_under_test",
                                                  _GATE_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_blocking_ruleset_single_source_matches_gate():
    """gates_atomic's emit-blocking set MUST BE the canonical constant — not a
    copy that equals it. A drift here is exactly what let a gate-blocked emit
    read as 'Tier-1 solved'.

    WHY THIS ASSERTS IDENTITY AND NOT EQUALITY, and why it reads the loaded
    module instead of the file's text. Until v1.11.70 gates_atomic declared its
    OWN literal copy of the set and this test compared the two by regex. That
    compares two hand-kept lists; it cannot say they will still agree tomorrow,
    and it did not: `ordered-phase-monitoring-early` entered the canonical set
    in b444b42c67 (#1701, 2026-08-17) and never reached the copy, so for 515
    commits the gate did not block a rule the canonical set declared
    emit-blocking. Equality of two definitions is a property that has to be
    re-established after every edit. Identity of ONE definition is a property
    that cannot lapse. So the assertion is now `is`, and the second half forbids
    the copy from coming back — without it, re-adding a literal that happens to
    match today would pass.
    """
    gate = _load_gates_atomic()
    assert gate._BLOCKING_CONFORMANCE_RULES is scc.EMIT_BLOCKING_CONFORMANCE_RULES, (
        "gates_atomic does not bind THE canonical set; it binds a separate "
        "object, which is how the two drifted before:\n"
        f"  gate-only:  {set(gate._BLOCKING_CONFORMANCE_RULES) - set(scc.EMIT_BLOCKING_CONFORMANCE_RULES)}\n"
        f"  const-only: {set(scc.EMIT_BLOCKING_CONFORMANCE_RULES) - set(gate._BLOCKING_CONFORMANCE_RULES)}")

    # And the literal must not be re-introduced alongside the import. An `is`
    # check alone would still pass the moment someone re-typed the set and
    # left the import above it shadowed or unused.
    literal = re.search(r"_BLOCKING_CONFORMANCE_RULES\s*=\s*\{", _GATE_SRC.read_text())
    assert not literal, (
        "gates_atomic re-declares _BLOCKING_CONFORMANCE_RULES as its own "
        "literal. Import it from spec_conformance_check instead — a set that "
        "is re-typed in two files is the drift this test exists to stop")


@pytest.mark.skipif(not (_DS / "Prob082_lfsr32_prompt.txt").exists(),
                    reason="dataset absent; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_gate_blocked_emit_is_not_tier1_but_clean_emit_is():
    prob = P.Problem(_DS / "Prob082_lfsr32_prompt.txt")
    # a PURE rotate (no tap-XOR) under the LFSR/shifter spec is exactly what the
    # gate's shift-implemented-as-rotate rule must still block (§4.05 no-leak):
    pure_rot = ("module TopModule(input clk, input reset, output reg [31:0] q);\n"
                "  always @(posedge clk) if(reset) q<=1; else q <= {q[0], q[31:1]};\n"
                "endmodule\n")
    blocked = P.conformance_emit_blocked(prob, pure_rot)
    assert "shift-implemented-as-rotate" in blocked, \
        "a pure rotate under a shifter spec must be gate-blocked"

    # the fixed galois_lfsr registry emit is conformance-clean -> NOT blocked
    import spec_artifact_registry as reg
    kind, lfsr = reg.generate(prob.prompt_path.read_text(), "TopModule")
    assert lfsr, "galois_lfsr solver must emit"
    assert P.conformance_emit_blocked(prob, lfsr) == [], \
        "the fixed galois_lfsr emit must pass the conformance gate"

    # end-to-end: Prob082 is Tier-1 (iverilog-pass AND gate-clean)
    res = P.tier_result(prob, verify=True)
    assert res["tier"] == P.TIER_PROGRAM and res["verified"] is True
