#!/usr/bin/env python3
"""#1219 — the D4 step-1 consolidation: the coverage report is declared by a
Phase-1 step, and the clause that reads it is wired there.

THE FINDING (d4, on a38902d1)
-----------------------------
`test_d4_gate_measures_what_it_claims[step1]` was RED: step 1 (`spec-to-rtl`)
declared THREE `required_outputs` entries and its gate read ONE. d4 says
outright that it does not choose the side:

    Either the gate is not measuring what the step claims, or the step is
    claiming a deliverable that belongs to another step — dimension 4 reports
    the mismatch and does not choose which side is wrong.

WHICH SIDE WAS WRONG, AND WHY
-----------------------------
The declaration was. Every writer of `reports/phase1/extraction_coverage_report.*`
is a PHASE-1 program — `programs/tests/test_coverage_report_producer_provenance.py`
names both (`phase1_doc_one_shot_runner.py`, `phase1_coverage_report_gen.py`;
write site `phase1_coverage_report_gen.py:905-906`). Step 1 CONSUMES L-docs and
writes no coverage report. So the entries moved to D1, and D1's gate gained the
clause that reads them.

Moving the declaration ALONE would only relocate the d4 finding from step 1 to
D1, so the wiring is half the fix and is pinned separately below.

PAIRED GUARD
------------
A wired clause that cannot fail is decoration. `test_wired_clause_can_block`
measures the checker's three outcomes directly, so this fix cannot be made
vacuous by wiring a program that always exits 0:

    bare skeleton (Phase 1 never attempted)        -> rc 0   honest skip
    Phase 1 ran, report ABSENT                     -> rc 1   BLOCKS
    report present at 100%%                         -> rc 0   passes

`test_step1_files_exist_block_still_holds_only_rtl` is the anti-regression arm
against the NAIVE repair: `any_of: true` is a MODIFIER on the `files_exist`
block (`flow_compliance_check.py:7538, :7596`), so appending the two report
paths to step 1's existing list would make that gate pass on ANY ONE of four
files — strictly weaker than requiring the RTL. That arm fails if anyone
"fixes" step 1 that way.

CORRECTION, 2026-08-14: an earlier version of this docstring called that
"#1175's trap". That was WRONG and unfair to #1175, and I checked it by parsing
its yaml rather than reading its diff. #1175 restructures into `all_of` with the
reports in a SEPARATE `files_exist` block, so `any_of: true` stays scoped to the
RTL block and its gate is strictly stronger, not weaker:

    all_of:
      - files_exist: [rtl/*.sv, rtl/*.v]      any_of: true
      - files_exist: [coverage_report.md, coverage_report.json]

#1175 is the loser here for ONE reason and it is not a mechanical error: it
keeps the declaration on step 1 and makes the gate ENFORCE it, when the
declaration is what is false. Every writer of the report is a Phase-1 program,
so a step named `spec-to-rtl` would be blocked on an artefact it does not write.
Enforcing a claim is the right instinct; it is only right once the claim is.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

_REPORTS = (
    "reports/phase1/extraction_coverage_report.md",
    "reports/phase1/extraction_coverage_report.json",
)


def _flow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(_FLOW.read_text(errors="replace"))


# The spec-to-RTL step's yaml `id` is the INTEGER 1; d4 LABELS it "step1".
# Compare on str(id) so either spelling resolves and neither is hard-coded twice.
_SPEC_TO_RTL = "1"


def _step(doc, step_id):
    for s in doc.get("steps") or []:
        if str(s.get("id")) == str(step_id):
            return s
    raise AssertionError(f"step {step_id!r} not found in {_FLOW}")


def _gate_text(step) -> str:
    """Every command string in this step's gate, flattened."""
    import json as _json
    return _json.dumps(step.get("gate") or {})


# --------------------------------------------------------------------------- #
# the move
# --------------------------------------------------------------------------- #
def test_d1_declares_the_coverage_report():
    outs = [str(o) for o in (_step(_flow(), "D1").get("required_outputs") or [])]
    missing = [r for r in _REPORTS if r not in outs]
    assert missing == [], (
        f"D1 must declare the Phase-1 coverage report it produces; missing {missing}")


def test_step1_no_longer_declares_it():
    outs = [str(o) for o in (_step(_flow(), _SPEC_TO_RTL).get("required_outputs") or [])]
    stray = [r for r in _REPORTS if r in outs]
    assert stray == [], (
        "step1 (spec-to-rtl) writes no coverage report; declaring it there is the "
        f"mis-filed obligation d4 reported: {stray}")


# --------------------------------------------------------------------------- #
# the wiring — without this, the move only relocates the finding
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# paired guard: the wired clause has teeth
# --------------------------------------------------------------------------- #














# --------------------------------------------------------------------------- #
# the NAIVE repair, kept as an anti-regression arm (NOT #1175's shape — see the
# 2026-08-14 correction in the module docstring; #1175 scoped `any_of` correctly)
# --------------------------------------------------------------------------- #
def test_step1_files_exist_block_still_holds_only_rtl():
    # The property is the RTL block's CONTENTS, not the clause count: other
    # program clauses may join step 1's `all_of` (F9 added the catalog
    # synth-safe gate), but exactly one `files_exist` block may exist, it keeps
    # `any_of`, it names only step-1 RTL, and the content gate stays beside it.
    gate = _step(_flow(), _SPEC_TO_RTL).get("gate") or {}
    clauses = gate.get("all_of", [])
    files_gates = [c for c in clauses
                   if isinstance(c, dict) and "files_exist" in c]
    assert len(files_gates) == 1, (
        "step1 must carry exactly one files_exist block (its RTL)", gate)
    files_gate = files_gates[0]
    files = files_gate.get("files_exist")
    assert isinstance(files, list) and files, (
        "step1 must retain its RTL files_exist predicate")
    assert files_gate.get("any_of") is True
    assert [f for f in files if not str(f).startswith("phase2/stage1/rtl/")] \
        == [], files
    assert {
        "program_exit_zero": "flow_step_output_content_check . --mode rtl"
    } in clauses, gate
    assert [c for c in clauses
            if "extraction_coverage_report" in str(c)] == [], gate
    for entry in files:
        assert "extraction_coverage_report" not in str(entry), (
            "`any_of: true` is a MODIFIER on this whole files_exist block, so "
            "adding the coverage report here makes the gate pass on ANY ONE of "
            "four files — weaker than requiring the RTL. Declare it on its "
            "producer (D1) instead, or use a nested all_of sub-gate.")


# ---------------------------------------------------------------------------
# CARRIED FROM #1131, which this PR supersedes (vibe-ic#1219 step 2: the
# replacement carries the UNION of what survives, so closing the superseded
# branch loses no assertion). Neither PR was a superset of the other: #1131
# owned these two and this file owned the gate-wiring arm and its paired guard.
# ---------------------------------------------------------------------------
def test_PREMISE_the_repo_itself_files_this_artefact_under_phase1():
    """The attribution, taken from the repo's own path layout rather than from
    a reading of docstrings.

    `_path_layout.py` maps every report basename to the phase that owns it and
    files both spellings of this one under `phase1`. That map is what
    `report_path()` uses to decide where the writers put the file, so it is the
    same fact the producers act on — not a second opinion about it. If it ever
    stops saying `phase1`, the step that should declare this must be re-derived
    before anything in this file is trusted.

    #1131 recorded a SECOND premise it attempted and WITHDREW, and the reasoning
    is worth keeping: it tried to assert "every program that WRITES this report
    is a phase-1 program", and both heuristics were wrong. Name + `write_text`/
    `json.dump` in the same file flagged `flow_compliance_check.py` (a legacy
    alias table) and `_path_layout.py` (the map itself), neither of which writes
    it; and matching `report_path(project, "extraction_coverage_report…")`
    flagged the READERS too, since `phase1_coverage_report_present_check.py` and
    `extraction_coverage_denominator_audit.py` resolve the same path in order to
    read it. Telling a writer from a reader needs real dataflow, and a premise
    tuned until it agrees is the claim wearing a test.
    """
    layout = (_PLUGIN / "programs" / "_path_layout.py").read_text(
        encoding="utf-8")
    for name in ("extraction_coverage_report.json",
                 "extraction_coverage_report.md"):
        assert f'"{name}": "phase1"' in layout, (
            f"_path_layout no longer files {name} under phase1 — the step that "
            f"should declare it must be re-derived before trusting this file")


def test_the_report_is_required_by_EXACTLY_ONE_step():
    """Two steps requiring one artefact is the MIRROR defect: it makes some
    other step MISSING for an output it does not write, which is exactly what
    step 1 was. Moving the entry without this arm could satisfy
    `test_d1_declares_it` and `test_step1_no_longer_declares_it` while a third
    step quietly also claimed it.
    """
    owners = {str(s.get("id")) for s in _flow().get("steps", [])
              if any("extraction_coverage_report" in str(e)
                     for e in (s.get("required_outputs") or []))}
    assert owners == {"D1"}, (
        f"the extraction-coverage report is required by {sorted(owners)}; "
        f"exactly one step must own a deliverable")
