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
for #1175's trap: `any_of: true` is a MODIFIER on the `files_exist` block
(`flow_compliance_check.py:7538, :7596`), so appending the two report paths to
step 1's list would make that gate pass on ANY ONE of four files — strictly
weaker than requiring the RTL. That arm fails if anyone "fixes" step 1 that way.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_GATE = _PLUGIN / "programs" / "phase1_coverage_report_present_check.py"

_REPORTS = (
    "reports/phase1/extraction_coverage_report.md",
    "reports/phase1/extraction_coverage_report.json",
)
_CLAUSE = "phase1_coverage_report_present_check"


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
def test_d1_gate_reads_what_d1_now_declares():
    assert _CLAUSE in _gate_text(_step(_flow(), "D1")), (
        f"D1 declares the coverage report but no clause of its gate reads it; "
        f"expected a program_exit_zero clause running {_CLAUSE}")


# --------------------------------------------------------------------------- #
# paired guard: the wired clause has teeth
# --------------------------------------------------------------------------- #
def _rc(project: Path) -> int:
    return subprocess.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True).returncode


def _phase1_ran(root: Path) -> Path:
    p = root / "proj"
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec_a.md").write_text("# spec a\nthe widget counts.\n")
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text('{"x": 1}')
    return p


def test_wired_clause_can_block(tmp_path):
    """The clause must FAIL when the property is genuinely violated."""
    p = _phase1_ran(tmp_path)
    assert _rc(p) != 0, (
        "Phase 1 ran and the coverage report is absent, yet the clause passed — "
        "a clause that cannot block is decoration, not a gate")


def test_wired_clause_passes_when_the_report_is_there(tmp_path):
    """...and must PASS when it is satisfied, so the fix is not just 'always red'."""
    p = _phase1_ran(tmp_path)
    rep = p / "reports" / "phase1"
    rep.mkdir(parents=True)
    (rep / "extraction_coverage_report.md").write_text("# coverage\n")
    (rep / "extraction_coverage_report.json").write_text(
        '{"overall": {"hit": 5, "total": 5, "pct": 100.0}, "per_doc": {}}')
    assert _rc(p) == 0


def test_wired_clause_skips_a_project_that_never_attempted_phase1(tmp_path):
    """D1 has no `condition:`, so it runs on every root. The clause must not
    fire on a bare skeleton, or wiring it would redden roots that never
    attempted Phase 1."""
    bare = tmp_path / "bare"
    bare.mkdir()
    assert _rc(bare) == 0


# --------------------------------------------------------------------------- #
# #1175's trap, kept as an anti-regression arm
# --------------------------------------------------------------------------- #
def test_step1_files_exist_block_still_holds_only_rtl():
    gate = _step(_flow(), _SPEC_TO_RTL).get("gate") or {}
    files = gate.get("files_exist")
    assert isinstance(files, list) and files, (
        "step1's gate is files_exist-only by design (see its AUDIT NOTE)")
    assert gate.get("any_of") is True
    for entry in files:
        assert "extraction_coverage_report" not in str(entry), (
            "`any_of: true` is a MODIFIER on this whole files_exist block, so "
            "adding the coverage report here makes the gate pass on ANY ONE of "
            "four files — weaker than requiring the RTL. Declare it on its "
            "producer (D1) instead, or use a nested all_of sub-gate.")
