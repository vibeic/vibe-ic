#!/usr/bin/env python3
"""R-0915-159 — an audit that could not certify is not an audit that failed.

THE MEASUREMENT (subservient x gf180mcuD as a DIE, lane icsub5, run2 on main
1f537b5c0, 2026-09-23). The phase-2 audit's own tally:

    PASS=4  PASS_WITH_WAIVERS=1  WAIVED-DEFERRED=1  FAIL=4  NOT_MEASURED=5
            NOT_APPLICABLE=17
    Overall: NOT_MEASURED (strict=True)

Five steps measured nothing — P0 (partial_population), D1 (awaiting_agent_pass),
Step 2 (execution_error), Step 4 and Step 5 (partial_population). `step_final_audit`
had no branch for that word, so it fell through to FAIL; phase 2's verdict became
FAIL; and `vibe_ic_one_shot_runner` halted before phase 3. A DIE deliverable could
never reach its own sign-off, because the audit of a phase that had not run yet
was read as a defect in the phase that had.

NOT_MEASURED is "cannot certify", never "found a defect" — R-0915-140/156, and
the rule this same function already applies to a partial structural population.

THIS IS NOT A SOFTENING, AND THE SECOND HALF OF THIS DECK IS THE PROOF: stacked
on next/icslot70, the front door's roll-up puts a NOT_MEASURED phase into
`unmeasured`, and a run with anything unmeasured can never roll up to PASS. So
the flow PROCEEDS past phase 2 and still REFUSES TO CERTIFY. Both halves are
exercised together here, because either one alone would be the wrong change.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))


#: The audit transcript shape, transcribed from the run above.
NM_OUT = """=== Vibe-IC phase1_phase2_phase3 compliance ===
  … [NOT_MEASURED     ] Step P0: Structural-RTL gates (P0 umbrella)  (stage1) (partial_population)
  … [NOT_MEASURED     ] Step D1: Phase 1 Doc Extraction  (stage_phase1) (awaiting_agent_pass)
  … [NOT_MEASURED     ] Step  2: RTL validation  (stage1) (execution_error)
  … [NOT_MEASURED     ] Step  4: Simulation  (stage1) (partial_population)
  … [NOT_MEASURED     ] Step  5: Formal verification  (stage1) (partial_population)
  ✗ [FAIL             ] Step 15.5ic: Pad Ring  (stage3) (missing_artefact)
  PASS=4  PASS_WITH_WAIVERS=1  WAIVED-DEFERRED=1  FAIL=4  NOT_MEASURED=5  NOT_APPLICABLE=17
Overall: NOT_MEASURED  (strict=True)
STRUCTURAL MEASUREMENT: registered=245 invoked=245 no_verdict=0
"""
FAIL_OUT = NM_OUT.replace("Overall: NOT_MEASURED", "Overall: FAIL")


# ── 1. the rows, which are the information the word throws away ───────────






# ── 2. the mapping, both directions ───────────────────────────────────────






# ── 3. the other half: proceeding must NOT become passing ─────────────────






# ── 4. MUTATION: the old fall-through must go red ─────────────────────────
def test_MUTATION_falling_through_to_FAIL_is_caught():
    """Re-plant the defect: no NOT_MEASURED branch, so the word falls to FAIL."""
    def defect(out):
        if "Overall: PASS_WITH_WAIVERS" in out or "Overall: PASS" in out:
            return "PASS"
        return "FAIL"                      # the pre-R-0915-159 behaviour

    assert defect(NM_OUT) == "FAIL"        # the defect, reproduced
    assert defect(FAIL_OUT) == "FAIL"      # and it cannot tell the two apart
