#!/usr/bin/env python3
"""Tests for gate_evidence_completeness_check.py

THE THREE BRANCHES ARE TESTED TOGETHER ON PURPOSE. The change this file was
rewritten for moves ONE of them (absent report: rc 1 -> rc 2) and the value of
that change depends entirely on the other two NOT moving with it. A test file
that only pinned the branch under edit would pass just as happily against a
program that had stopped refusing altogether, which is the failure this gate
exists to prevent in other programs.

    absent report     rc 2  NOT CHECKED   -- changed here
    read, 0 PASS      rc 0  real result   -- control, must not move
    read, PASS w/o    rc 1  real gap      -- control, must not move: this is
      evidence                               the refusal the gate is FOR
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "gate_evidence_completeness_check.py"


def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_absent_report_is_not_checked_not_a_failure(tmp_path):
    """An empty project has no report, so no question was ever put to it.

    This asserted `returncode == 1` until 2026-08-31 and so pinned the defect:
    the program printed `FAIL: nothing to audit` over a design it had not read
    one byte of, and the flow's advisory slot recorded that as a FINDING. rc 2
    is this repo's NOT-CHECKED tier and the program's own docstring already
    assigned the two neighbouring I/O conditions to it.
    """
    r = _run([str(tmp_path)])
    assert r.returncode == 2, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "VACUOUS_PASS:" in combined, (
        "the sentinel `flow_compliance_check._stdout_signals_vacuous` matches "
        "must be present, or the advisory slot records this as a FINDING "
        "rather than as `n/a (input not present)`")
    assert "FAIL" not in r.stdout, (
        "a run that read nothing must not print FAIL: it has no design to "
        "return a verdict about")


def test_report_read_with_no_pass_claims_is_a_real_result(tmp_path):
    """CONTROL. An empty artefact is not a missing one.

    The report EXISTS and was parsed; it simply claims no PASS gate. That is a
    real result over a real artefact and stays rc 0 — the line
    `gate_zero_denominator_refuses_check` draws in its own words. If this moved
    with the change above, the change would have swept up the wrong branch.
    """
    (tmp_path / "FINAL_REPORT.md").write_text(
        "# Report\n\nNo gate reached a verdict in this run.\n", encoding="utf-8")
    r = _run([str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_pass_claim_without_evidence_still_refuses(tmp_path):
    """CONTROL, and the load-bearing one.

    A report that CLAIMS a PASS with no backing artefact is the exact defect
    this program exists to catch. It must still return 1 after the change. A
    fix that silenced the absent-report branch by weakening the gate would show
    up here and nowhere else.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "flow_compliance.json").write_text(json.dumps({
        "steps": [
            {"id": "1", "name": "a step that claims a pass",
             "gate": "no_such_evidence_gate", "status": "PASS"},
        ]
    }), encoding="utf-8")
    r = _run([str(tmp_path)])
    assert r.returncode == 1, (
        "a PASS claimed with no evidence file must still be a GAP: " +
        r.stdout + r.stderr)
