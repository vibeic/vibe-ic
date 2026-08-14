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
#: Inner bound for the gate subprocess. The suite runs at ``--timeout=180
#: --timeout-method=thread``; a bound ABOVE that lets a hang kill the SESSION
#: instead of this one test, and every other result in the run is then lost with
#: no name attached to it. 60s is the repo ceiling
#: (``ci_harness_timeout_ceiling_check``, 180 // 3).
_GATE_TIMEOUT_S = 60


def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S)


def _rc(project: Path) -> int:
    return _run_gate(project).returncode


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
    BLOCK a bare skeleton, or wiring it would redden every root that never
    attempted Phase 1.

    THE EXPECTED CODE IS 2, NOT 0, AND THAT IS A STRENGTHENING. When this test
    was written the program answered rc 0 here. #1185 measured what that bought:
    a step resolving PASS while this clause had examined nothing, because
    `flow_compliance_check` reads the return code plus a line-start sentinel, and
    a bare `SKIP —` at rc 0 has NO channel to the tier. The program now answers
    rc 2 — its own long-standing "cannot look" convention — and
    `test_skip_when_phase1_not_attempted_is_not_counted_as_a_pass` pins that on
    main. Asserting 0 here would re-pin the defect that change removed.

    WHY rc 2 STILL SATISFIES THIS TEST'S ACTUAL CLAIM. The claim is about
    BLOCKING, not about the digit. `flow_compliance_check.py:3126` answers a
    program_exit_zero clause with `return True` on rc 2, surfacing it as
    `VACUOUS_PASS` — so the wired clause does not redden a never-attempted root,
    and it says out loud that it looked at nothing. Both halves are asserted
    below, because the rc alone is one edit from meaning something else.

    The paired arm is `test_wired_clause_can_block`: a root that DID attempt
    Phase 1 and is missing the report still fails. Tolerated-when-absent and
    blocking-when-genuinely-violated are two claims and this file makes both.
    """
    bare = tmp_path / "bare"
    bare.mkdir()
    r = _run_gate(bare)
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout.splitlines()[0].startswith("VACUOUS_PASS"), r.stdout
    assert "not attempted" in r.stdout, r.stdout


# --------------------------------------------------------------------------- #
# the NAIVE repair, kept as an anti-regression arm (NOT #1175's shape — see the
# 2026-08-14 correction in the module docstring; #1175 scoped `any_of` correctly)
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
