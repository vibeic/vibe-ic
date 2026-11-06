#!/usr/bin/env python3
"""The coverage-report gate must STATE where its verdict is enforced.

THE DEFECT (vibe-ic#886's class, hit by the gate #1219/#1235 wires).
`flow_gate_enforcement_audit` returned rc=1 on the #1235 branch with:

    [FAIL] 1 NEW gate(s) are AUDIT_ONLY and declare no intent at all —
    nothing invokes them where they could block, and nothing in the gate says
    that was the decision:
       undeclared::phase1_coverage_report_present_check

This was found by MEASUREMENT, not review: an 8-PR candidate batch returned
rc=1 from `repo_hygiene_gates.sh` and the failure attributed two-arm to #1235
alone (`flow_gate_enforcement_audit` rc=0 on main, rc=1 on #1235; the gate name
appears 8x in its diff and 0x on main). Wiring a NEW gate into the flow is what
creates the obligation — the audit's ratchet is bidirectional, so a new
audit-only gate that declares nothing is new debt and fails.

WHY `advisory` AND NOT `blocking` — settled by measurement, not preference.
The audit has two failing registers, and `blocking` would merely move the red
from one to the other:

    AUDIT_ONLY + declares blocking   -> "declares an intent it is not wired
                                        for"        0 gates do this
    AUDIT_ONLY + declares advisory   -> clean       25 gates do this

Every `phase1_*` gate in the flow that declares at all declares `advisory`
(`phase1_expert_track_evidence_check`, `phase1_planned_consumer_starved_check`,
and `phase1_expert_parse_track`). There is no counter-example anywhere in the
flow. Declaring `blocking` here would be asserting a wiring that does not
exist, and the audit would correctly say so.

`advisory` IS NOT A DEMOTION. It answers only "does a runner spawn this inline"
— no `_RUNNERS` entry does. The flow SLOT is a separate axis and is unchanged:
the clause stays in D1's `program_exit_zero`, where `flow_compliance_check`
fails the step on rc=1, and the gate still exits 1 on a violation. Both halves
are pinned below, because the failure mode of this kind of fix is that
`advisory` gets read as permission — either to move the clause to
`advisory_program_exit_zero` (finding recorded, step passes anyway) or to
soften the gate's own verdict.

EVERY ASSERTION IS ON A RETURNED VALUE, AN EXIT CODE OR EMITTED JSON — never on
the presence of a string in a source file. A test that greps for
`ENFORCEMENT: advisory` would pass on a file where the audit cannot see it (the
declaration must OPEN a line and sit in the first 4000 characters), which is
the #886 defect wearing a test's clothing.

PAIRED, because "the audit does not report this gate" is trivially satisfied by
an audit that reports nothing. The two synthetic controls prove the same code
path still flags an undeclared audit-only gate and still stays silent for one
that declares.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent

_GATE = "phase1_coverage_report_present_check"
_STEP = "D1"










# --------------------------------------------------------------------------
# `advisory` did not soften the gate itself — the severity axis, unchanged
# --------------------------------------------------------------------------
def test_the_gate_still_exits_nonzero_when_the_report_is_missing(tmp_path):
    """The declaration is about WIRING. If it ever coincided with the gate
    going quiet on a real violation, the fix would have defanged the thing it
    was documenting — so this measures the exit code directly.

    Mirrors `test_wired_clause_can_block` in the #1219 file deliberately: that
    one guards the flow wiring, this one guards it against the DECLARATION."""
    p = tmp_path / "proj"
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec_a.md").write_text("# spec a\nthe widget counts.\n")
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text('{"x": 1}')
    rc = _pr.run(
        [sys.executable, str(_PROGRAMS / f"{_GATE}.py"), str(p)],
        capture_output=True, text=True).returncode
    assert rc != 0, (
        "Phase 1 ran and the coverage report is absent, yet the gate passed — "
        "`ENFORCEMENT: advisory` describes the wiring; it must not soften the "
        "verdict")


# --------------------------------------------------------------- the control

_SILENT = '''"""A gate that says nothing about where its verdict is enforced."""
'''
_DECLARING = '''"""A gate that says so.

ENFORCEMENT: advisory
"""
'''








if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
