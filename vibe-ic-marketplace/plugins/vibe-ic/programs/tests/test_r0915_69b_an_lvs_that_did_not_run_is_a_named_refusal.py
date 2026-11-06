"""R-0915-69(b) — LVS did not run, and step 31 said it could not find a report.

MEASURED, sha256 x sky130A, lane icsha2 run15 (main 385445351), front door.

`reports/phase3/lvs_verdict.json`, written by the flow itself:

    "status":  "FAIL",
    "finding": "LVS_EXTRACTION_ILLEGAL_OVERLAP",
    "message": "Magic's extraction feedback channel did not clear the
                zero-illegal-overlap gate (rc=1): ... netgen was NOT run — a
                compare against a netlist the extractor could not decide is not
                evidence about this design."

`steps/phase3/stage3/31_.../lvs.json`, written by the audit over the same tree:

    "rule": "LVS_REPORT_EXISTS",
    "message": "No LVS report found (searched *lvs*.rpt/log, *comp*.out)",
    "summary": {"files_found": 0}

Two artefacts about the same event, in the same directory, and the one that
reaches the verdict is the one that says nothing.  The refusal is CORRECT — a
netlist the extractor could not decide must not be compared — it is the naming
that failed, twice:

  * the runner filed a no-compare under `status: FAIL`, a word that claims a
    compare happened and disagreed;
  * `_lvs_blocked_verdict` honours the artifact only on a literal `BLOCKED`, so
    it returned None and the audit fell through to an unattributed absence.
"""
from __future__ import annotations

import json
from pathlib import Path


import eda_report_audit as A


# --------------------------------------------------------------------------
# the producer records whether anything was compared — measured, not declared
# --------------------------------------------------------------------------












# --------------------------------------------------------------------------
# the audit reports the runner's named refusal instead of an absence
# --------------------------------------------------------------------------
def _write_verdict(project: Path, **payload) -> None:
    d = project / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lvs_verdict.json").write_text(json.dumps(payload))


_RUN15 = {
    "status": "FAIL",
    "result": "FAIL",
    "finding": "LVS_EXTRACTION_ILLEGAL_OVERLAP",
    "message": ("Magic's extraction feedback channel did not clear the "
                "zero-illegal-overlap gate (rc=1): 22 illegal overlap(s); "
                "netgen was NOT run — a compare against a netlist the "
                "extractor could not decide is not evidence about this "
                "design."),
    "compare_performed": False,
    "compare_evidence": None,
}


def test_the_run15_record_is_now_recognised_as_a_refusal(tmp_path: Path):
    _write_verdict(tmp_path, **_RUN15)
    assert A._lvs_blocked_verdict(tmp_path) == _RUN15


def test_step31_names_the_refusal_instead_of_an_absence(tmp_path: Path):
    _write_verdict(tmp_path, **_RUN15)
    res = A._check_lvs(tmp_path)
    rules = [f.rule for f in res.findings]
    assert "LVS_REPORT_EXISTS" not in rules, rules
    assert rules == ["LVS_BLOCKED_NO_COMPARE"], rules
    msg = res.findings[0].message
    assert "netgen was NOT run" in msg
    assert "illegal overlap" in msg
    assert res.summary["terminal_verdict"] == "BLOCKED"
    assert res.summary["blocked_finding"] == "LVS_EXTRACTION_ILLEGAL_OVERLAP"


def test_the_refusal_is_still_not_a_pass(tmp_path: Path):
    """Nothing here grants anything: `passed` is False on both branches."""
    _write_verdict(tmp_path, **_RUN15)
    assert A._check_lvs(tmp_path).passed is False


def test_a_pass_status_with_no_transcript_is_also_a_refusal(tmp_path: Path):
    """The strongest direction: a record CLAIMING PASS while no compare
    happened must never reach a verdict as a pass."""
    _write_verdict(tmp_path, status="PASS", result="PASS", finding="LVS_CLEAN",
                   message="match", compare_performed=False)
    res = A._check_lvs(tmp_path)
    assert res.passed is False
    assert [f.rule for f in res.findings] == ["LVS_BLOCKED_NO_COMPARE"]


# ---- negative controls ---------------------------------------------------
def test_a_record_written_before_the_field_existed_behaves_exactly_as_before(
        tmp_path: Path):
    """NEGATIVE CONTROL for `is False` vs falsy: no key means no claim, and the
    old no-report branch still runs."""
    _write_verdict(tmp_path, status="FAIL", result="FAIL",
                   finding="LVS_EXTRACTION_ILLEGAL_OVERLAP", message="m")
    assert A._lvs_blocked_verdict(tmp_path) is None
    assert [f.rule for f in A._check_lvs(tmp_path).findings] == [
        "LVS_REPORT_EXISTS"]


def test_a_completed_compare_is_never_diverted_to_the_blocked_path(
        tmp_path: Path):
    """NEGATIVE CONTROL. compare_performed True -> the record is not a refusal,
    whatever its status."""
    _write_verdict(tmp_path, status="FAIL", result="FAIL",
                   finding="LVS_MISMATCH", message="m",
                   compare_performed=True)
    assert A._lvs_blocked_verdict(tmp_path) is None


def test_the_literal_blocked_status_keeps_its_own_token(tmp_path: Path):
    """NEGATIVE CONTROL. The pre-existing cause is untouched."""
    _write_verdict(tmp_path, status="BLOCKED", finding="LVS_TECH_INCAPABLE",
                   message="the tech file cannot support extraction",
                   tech_file="sky130A.tech")
    assert [f.rule for f in A._check_lvs(tmp_path).findings] == [
        "LVS_BLOCKED_INPUT_INCAPABLE"]


def test_a_stopped_run_keeps_its_own_token(tmp_path: Path):
    """NEGATIVE CONTROL. The CZT-19 cause is untouched, and it wins over the
    new one even with compare_performed False."""
    _write_verdict(tmp_path, status="FAIL", finding="LVS_NETGEN_STALLED",
                   message="no forward progress", compare_performed=False,
                   stopped_as="stalled")
    assert [f.rule for f in A._check_lvs(tmp_path).findings] == [
        "LVS_BLOCKED_RUN_STOPPED"]


def test_no_verdict_file_at_all_is_still_an_absence(tmp_path: Path):
    """NEGATIVE CONTROL. Nothing is invented where there is no record."""
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    assert A._lvs_blocked_verdict(tmp_path) is None
    assert [f.rule for f in A._check_lvs(tmp_path).findings] == [
        "LVS_REPORT_EXISTS"]


def test_a_malformed_verdict_file_is_still_an_absence(tmp_path: Path):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "lvs_verdict.json").write_text("{not json")
    assert A._lvs_blocked_verdict(tmp_path) is None


def test_a_real_lvs_report_still_wins_over_the_verdict_file(tmp_path: Path):
    """NEGATIVE CONTROL for ORDER: when a transcript exists the audit judges IT,
    and never diverts to the refusal path."""
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "lvs.rpt").write_text(
        "Contents of circuit 1:  Circuit: 'sha256'\n"
        "Netlists match uniquely.\n" + "x" * 2000)
    _write_verdict(tmp_path, **_RUN15)
    rules = [f.rule for f in A._check_lvs(tmp_path).findings]
    assert "LVS_BLOCKED_NO_COMPARE" not in rules, rules
