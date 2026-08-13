#!/usr/bin/env python3
"""Step 1 claimed a deliverable it does not write (d4 `criteria_match[step1]`).

THE DEFECT
==========
`test_matrix_d4_criteria_match` asks, per step, whether the step's gate measures
what the step CLAIMS. Step 1 (Spec-to-RTL) was the one failing cell, and the
last red node on main that no PR covered:

    step 1 / d4 criteria_match: 2 of 3 declared required_outputs ENTRIES are
    read by no clause of this step's gate. The gate checks
    ['phase2/stage1/rtl/*.sv', 'phase2/stage1/rtl/*.v']; the step claims to
    deliver [... 'reports/phase1/extraction_coverage_report.md',
    'reports/phase1/extraction_coverage_report.json']

d4 reports the mismatch and deliberately does NOT choose which side is wrong.
The producers choose it:

  * `phase1_coverage_report_gen.py` — its own docstring: "Phase 1
    (doc-extraction) extraction-coverage REPORT ... always runs at end-of-Phase
    1", measuring which literals reached `generated_docs/L*.json`;
  * `phase1_doc_one_shot_runner.py` — the other writer, also phase-1;
  * and the yaml's own comment at the old site called it the "Phase 1
    extraction-coverage REPORT" while declaring it as step 1's output.

Spec-to-RTL CONSUMES L-docs and emits RTL. It does not write a report about how
well the documents were extracted. So the claim was misattributed, and the
repair is to move it to `D1`, not to make step 1's gate check another step's
artefact.

WHY THIS FILE EXISTS RATHER THAN JUST THE YAML EDIT
===================================================
Deleting two entries from a step's `required_outputs` makes its d4 cell green
whether or not the obligation survives anywhere. That is the cheapest way to
turn this red green and it is indistinguishable from the correct fix by looking
at d4 alone. So the MOVE is asserted as a move: gone from step 1, PRESENT on
D1. If a future edit drops it from D1, this fails even though d4 stays green.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"
PROGRAMS = PLUGIN_ROOT / "programs"

_REPORT_ENTRIES = (
    "reports/phase1/extraction_coverage_report.md",
    "reports/phase1/extraction_coverage_report.json",
)


def _steps():
    return yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))["steps"]


def _step(sid):
    return next(s for s in _steps() if str(s.get("id")) == str(sid))


def test_PREMISE_the_repo_itself_files_this_artefact_under_phase1():
    """The attribution, taken from the repo's own path layout rather than from
    my reading of docstrings.

    `_path_layout.py` maps every report basename to the phase that owns it, and
    it files both spellings of this one under `phase1`. That map is what
    `report_path()` uses to decide where the writers put the file, so it is the
    same fact the producers act on — not a second opinion about it.

    An earlier version of this premise grepped for `write_text`/`json.dump`
    beside the report's name and flagged `flow_compliance_check.py` and
    `_path_layout.py`, neither of which writes it: one carries a legacy-path
    alias table and the other IS the map. A heuristic that cannot tell a writer
    from a mention is not a premise.
    """
    lay = (PROGRAMS / "_path_layout.py").read_text()
    for name in ("extraction_coverage_report.json", "extraction_coverage_report.md"):
        assert f'"{name}": "phase1"' in lay, (
            f"_path_layout no longer files {name} under phase1 — the step that "
            f"should declare it must be re-derived before trusting this file")


# A SECOND PREMISE WAS ATTEMPTED AND WITHDRAWN, on purpose.
# It tried to assert "every program that WRITES this report is a phase-1
# program". Two heuristics were tried and both were wrong:
#   * name + `write_text`/`json.dump` anywhere in the file flagged
#     `flow_compliance_check.py` (a legacy-path alias table) and
#     `_path_layout.py` (the map itself), neither of which writes it;
#   * `report_path(project, "extraction_coverage_report…")` flagged the READERS
#     too — `phase1_coverage_report_present_check.py` and
#     `extraction_coverage_denominator_audit.py` resolve the same path in order
#     to read it.
# Telling a writer from a reader needs real dataflow, and a premise that has to
# be tuned until it agrees is not evidence — it is the claim wearing a test.
# The `_path_layout` assertion above is the repo's own authoritative statement
# of which phase owns the artefact, and it needs no heuristic, so it stands
# alone.


def test_step1_no_longer_claims_a_report_it_does_not_write():
    """Half 1 of the move."""
    declared = _step(1).get("required_outputs") or []
    leaked = [e for e in declared if "extraction_coverage_report" in e]
    assert not leaked, (
        f"Spec-to-RTL still claims {leaked}; it consumes L-docs and emits RTL, "
        f"it does not write a report about document extraction")


def test_D1_DOES_claim_it_so_the_obligation_moved_and_was_not_dropped():
    """Half 2, and the one that makes half 1 honest.

    Deleting the entries from step 1 turns the d4 cell green on its own. This
    assertion separates 'moved' from 'deleted' — if it fails, a required
    deliverable has quietly stopped being required anywhere.
    """
    declared = _step("D1").get("required_outputs") or []
    missing = [e for e in _REPORT_ENTRIES if e not in declared]
    assert not missing, (
        f"D1 does not declare {missing} — the obligation was DROPPED, not "
        f"moved. Every writer is a phase-1 program, so if D1 does not require "
        f"it, no step does.")


def test_the_report_is_required_by_EXACTLY_ONE_step():
    """Two steps requiring one artefact is the mirror defect: it makes the
    wrong step MISSING for someone else's output, which is what step 1 was."""
    owners = {str(s.get("id")) for s in _steps()
              if any("extraction_coverage_report" in e
                     for e in (s.get("required_outputs") or []))}
    assert owners == {"D1"}, (
        f"the extraction-coverage report is required by {sorted(owners)}; "
        f"exactly one step must own a deliverable")


def test_step1_still_requires_the_RTL_it_actually_writes():
    """Negative control for the deletion. A fix that emptied step 1's
    `required_outputs` would also make d4 green — and would stop Spec-to-RTL
    being MISSING when it produced no RTL, which is the one thing it is for."""
    declared = _step(1).get("required_outputs") or []
    assert declared, "step 1 declares no deliverable at all"
    assert any("phase2/stage1/rtl/" in e for e in declared), declared


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
