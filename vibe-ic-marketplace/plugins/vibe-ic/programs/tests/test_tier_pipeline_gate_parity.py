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


def test_blocking_ruleset_single_source_matches_gate():
    """gates_atomic's emit-blocking set MUST equal the canonical constant — a drift
    here is exactly what let a gate-blocked emit read as 'Tier-1 solved'."""
    gate_src = (_PROGRAMS.parent / "benchmark" / "gates_atomic.py").read_text()
    m = re.search(r"_BLOCKING_CONFORMANCE_RULES\s*=\s*\{(.*?)\}", gate_src, re.S)
    assert m, "gates_atomic._BLOCKING_CONFORMANCE_RULES not found"
    gate_rules = set(re.findall(r'"([a-z0-9-]+)"', m.group(1)))
    assert gate_rules == set(scc.EMIT_BLOCKING_CONFORMANCE_RULES), (
        "gates_atomic emit-blocking rules drifted from "
        "spec_conformance_check.EMIT_BLOCKING_CONFORMANCE_RULES:\n"
        f"  gate-only:  {gate_rules - set(scc.EMIT_BLOCKING_CONFORMANCE_RULES)}\n"
        f"  const-only: {set(scc.EMIT_BLOCKING_CONFORMANCE_RULES) - gate_rules}")


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
