"""A NOT-CHECKED classifier must not enter the gate denominator.

The defect
----------
`hold_area_budget_check` can never reach a verdict today: nothing in the plugin
writes `hold_buffer_area` / `total_cell_area` / a before-after total pair, so
project-directory mode always returns rc=2 NOT CHECKED. Wired at Step 20 in a
BLOCKING `program_exit_zero` slot, that rc=2 emits a `__VACUOUS_HINT__`, and
`check_step` promotes the whole STEP to `VACUOUS_PASS`.

`PASS_VOIDED_BY_DEPENDENCY` is only ever applied to a step whose status is
exactly `PASS`:

    if str(_r.id) != _tid or _r.status != "PASS":
        continue

so promoting the step to VACUOUS_PASS silently DELETES the stronger line

    PASS voided: dependency [19] CTS = FAIL, so this step's PASS certifies
    nothing about the design

`flow_compliance_check`'s own comment forbids the swap: "a vacuous step is one
nobody has to come back to, and a voided one is a step somebody does."
Published radius is 0 — Step 20 is MISSING on all 34 published run roots — so
it bites only on LIVE runs, which is worse, not better.

The repair
----------
Issue #1980 moves the classifier to the step's `program_outputs`. Its typed
NOT-CHECKED output remains reportable, but a program with no refusal predicate
cannot count as gate coverage or retier the step.

These tests drive the REAL entry point over a real fixture, and the second one
is the positive control: it re-runs the identical fixture against a yaml whose
only difference is the slot keyword, and asserts the defect comes back.
"""
from __future__ import annotations

from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

def test_the_classifier_is_a_program_output_not_a_gate():
    step20 = next(step for step in yaml.safe_load(FLOW.read_text())["steps"]
                  if step["id"] == 20)
    assert "hold_area_budget_check" in step20["programs"]
    assert "hold_area_budget_check" not in str(step20["gate"])
    assert step20["program_outputs"] == [{
        "program": "hold_area_budget_check",
        "path": "reports/phase3/pnr/hold_area_budget.json",
        "verdict_field": "verdict",
    }]
