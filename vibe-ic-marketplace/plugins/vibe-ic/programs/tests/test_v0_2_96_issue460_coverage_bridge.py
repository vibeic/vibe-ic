#!/usr/bin/env python3
"""v0.2.96 — ORGANIC-20260606 #460 (REOPENED with field counter-evidence).

The first #460 fix (_emit_oracle_sim_bridge) wrote the Step-4 *simulation*
artifacts (phase2/stage1/sim/{results.xml,pass.flag}) from a genuine oracle
PASS. But its tests only asserted those bridge files exist — they never ran
the real flow_compliance_check, so they missed that Step 4 is an `all_of`
gate whose COVERAGE sub-input (reports/phase2/coverage/coverage_actual.json)
STAYED `SKIPPED-CONDITION`: the coverage-manifest block only rglob'd
`ref_tb.log`, and the oracle track only ever produces `oracle.log`. A
SKIPPED-CONDITION coverage required-output is read by the evidence-integrity
scan and propagates to the WHOLE step → Step 4 = SKIPPED-CONDITION, NOT
counted in executed-PASS, Overall FAIL.

This fix makes the coverage-manifest block treat the oracle track the SAME
way _emit_oracle_sim_bridge does: when the genuine-oracle-PASS conditions
hold (functional_verified, vectors_passed==vectors_total>0, oracle.log
present non-empty), extract the scenario / vector evidence FROM oracle.log
(ORACLE_VECTOR/ORACLE_TB_DONE lines — the SOLE evidence source, no canned
content) and write a coverage PASS pointing back at oracle.log. A
skeleton-WAIVED / FAILed run still gets SKIPPED-CONDITION.

Tests below:
  (A) the coverage-manifest block: oracle-PASS → coverage PASS citing
      oracle.log with REAL per-vector scenarios; FAIL/WAIVED/no-log → SKIP.
  (B) END-TO-END self-verification: build an oracle-track replica project,
      run the REAL flow_compliance_check --stage 1, assert Step 4 is lifted
      out of SKIPPED-CONDITION. (This is the gap the prior fix missed.)
      CORRECTED by the coverage-credit split: these used to assert Step 4 ==
      PASS and +1 executed-PASS. An oracle functional PASS is not Verilator
      coverage, and this replica measures none, so the honest tier is a
      disclosed WAIVED-DEFERRED (review_required, NOT executed-PASS) — and a
      plain FAIL on a host that HAS the toolchain. See the corrected tests'
      own docstrings for the old expectation and why it was wrong.
  (C) regression guards for the prior CORRECT behaviour (ref_tb path,
      negative SKIP self-reports) + anti-canned source guard.
  (D) incidental legacy stale-SKIP top-level sim/results.xml replacement.

chip-AGNOSTIC: synthetic generic fixtures only (datacore / no chip/SKU).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

RUNNER_SRC = (PROG_DIR / "design_one_shot_runner.py").read_text()

DUT = ("module datacore(input clk, input d, output reg q);\n"
       "  always @(posedge clk) q <= d;\nendmodule\n")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------








# ===========================================================================
# (helper) _oracle_coverage_evidence parses ONLY what the log carries
# ===========================================================================






# ===========================================================================
# (A) coverage-manifest block — oracle track
# ===========================================================================










# ===========================================================================
# (B) END-TO-END — the gap the prior fix missed
# ===========================================================================


#: Pin the Verilator-capability decision so these end-to-end assertions are a
#: property of the FLOW, not of whatever the CI host happens to have
#: installed. `verilator_coverage_measure check` reads this env var to decide
#: whether an absent coverage measurement is a disclosed capability gap
#: (rc=3 -> WAIVED-DEFERRED) or a defect (rc=1 -> FAIL).
_NO_VERILATOR = "__vibeic_no_such_verilator__"












# --- CORRECTED (coverage-credit split) -------------------------------------
# The two tests below used to assert that an oracle-track PASS makes Step 4
# a PASS and ADDS ONE to the headline "x/y executed PASS". They ENCODED THE
# DEFECT this file's own fix introduced at the flow level:
#
#   #460 resolved a Step-4 SKIPPED-CONDITION by having design_one_shot_runner
#   write a FUNCTIONAL-verification verdict payload (verdict / evidence /
#   verification_track=oracle_tb / scenarios_covered — no `totals` container)
#   to reports/phase2/coverage/coverage_actual.json, the path the flow
#   declares as the Verilator coverage artefact. Step 4's own gate then runs
#   `verilator_coverage_measure check` against that path. No line / toggle /
#   branch coverage exists anywhere in these replicas, and none was measured.
#
# An oracle functional PASS is a real verification result, but it is not
# coverage, and Step 4 is "Simulation (testbench-based + L10/L12 coverage +
# Verilator coverage)". A gate may EXPLAIN an absent artefact; it may not
# CERTIFY the step done without one. So the corrected requirement is:
#   * an oracle PASS still LIFTS Step 4 out of SKIPPED-CONDITION — that was
#     #460's actual complaint and it still holds;
#   * an oracle PASS is still DISTINGUISHABLE from an oracle FAIL;
#   * but it is a DISCLOSED, review_required deferral, NOT executed-PASS.
# The assertions are corrected to a stricter verdict, not relaxed.










# ===========================================================================
# (C) regression guards — prior CORRECT behaviour preserved
# ===========================================================================




def test_source_has_no_canned_scenarios():
    # the oracle coverage branch must extract from the log, never hardcode
    # scenario / vector names.
    assert '"GET_ID"' not in RUNNER_SRC
    assert '"GET_STATE"' not in RUNNER_SRC
    # the oracle branch cites #460 and delegates scenario extraction to the
    # helper (parsing lives there, not as an inline canned scenario list).
    i = RUNNER_SRC.index("Coverage manifest (#436)")
    window = RUNNER_SRC[i:i + 3200]
    assert "_oracle_coverage_evidence" in window
    assert "#460" in window
    # the vector-name parse is a regex over the log, not a hardcoded list
    helper = RUNNER_SRC[RUNNER_SRC.index("def _oracle_coverage_evidence"):]
    helper = helper[:helper.index("def _run_oracle_tb")]
    assert "re.findall" in helper and "ORACLE_VECTOR" in helper
    # no literal scenario-name list is assigned in the helper
    assert "scenarios_covered = [" not in helper


# ===========================================================================
# (D) incidental — legacy stale top-level sim/results.xml replacement
# ===========================================================================








if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
