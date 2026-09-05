"""A typed vacuity may say "I examined nothing". It may not claim credit.

WHY THIS TEST EXISTS SEPARATELY
===============================
`l9_floorplan_contract_check` now publishes a typed `reason_class` so the flow
stops booking "the design mandates no floorplan" as EXECUTION_ERROR. That moves
2,283 project roots on the measured host out of INCOMPLETE, which is the only
greenward move in that change and therefore the one that has to be pinned.

There are TWO tiers on the far side of a skip-eligible class, and they mean
opposite things:

    VACUOUS_PASS    the gate examined NOTHING. Claims nothing.
    NOT_APPLICABLE  the gate EXECUTED a design-owned N/A contract. Claims that
                    the design itself declared a typed zero population.

`flow_compliance_check._report_proves_executed_design_na` is the door to the
second, and it requires a single project-relative declaration file with named
population paths and a declared population of zero. This gate's condition is an
ABSENCE across a scanned file set, which is not that, and must never be laundered
into it — inventing such a path is how future emptiness becomes credit.

This test asserts the refusal against the REAL predicate, imported from the real
module, rather than trusting the reasoning above.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as rt              # noqa: E402
import flow_compliance_check as fc              # noqa: E402

GATE = PROGRAMS / "l9_floorplan_contract_check.py"
REL = "reports/phase1/gates/l9_floorplan_contract.json"
CMD = f"l9_floorplan_contract_check . --json {REL}"


def _silent_l9_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_constraints.md").write_text(
        "# L9 constraints\n\n| knob | value |\n| --- | --- |\n"
        "| CLOCK_PERIOD | 10 |\n")
    return proj


def _run_as_the_flow_does(proj: Path) -> subprocess.CompletedProcess:
    """cwd=project with a RELATIVE --json, which is how
    `flow_compliance_check` invokes gate commands (`cwd=str(project)`, never
    `os.chdir`). The reader resolves the same relative path against the same
    project, so this also proves the wiring lands where the reader looks."""
    return subprocess.run([sys.executable, str(GATE), ".", "--json", REL],
                          cwd=str(proj), capture_output=True, text=True)


def test_the_flow_finds_the_report_at_the_wired_relative_path(tmp_path):
    proj = _silent_l9_project(tmp_path)
    assert _run_as_the_flow_does(proj).returncode == 2
    report = fc._command_json_report(proj, CMD)
    assert report is not None
    assert rt.report_reason_class(report) == rt.DESIGN_DECLARED_NA


def test_the_typed_vacuity_is_refused_by_the_executed_na_predicate(tmp_path):
    """THE GUARD. A skip-eligible class is not a licence to claim execution."""
    proj = _silent_l9_project(tmp_path)
    _run_as_the_flow_does(proj)
    report = fc._command_json_report(proj, CMD)
    assert fc._report_proves_executed_design_na(proj, report, CMD) is False


def test_the_report_carries_no_forged_applicability_evidence(tmp_path):
    """The predicate above refuses on the evidence block being absent. Assert
    the absence directly too, so a later edit cannot supply one and leave the
    test above passing for a different reason."""
    proj = _silent_l9_project(tmp_path)
    _run_as_the_flow_does(proj)
    report = json.loads((proj / REL).read_text())
    assert "applicability_evidence" not in report
    assert "applicability_evidence" not in report.get("summary", {})
