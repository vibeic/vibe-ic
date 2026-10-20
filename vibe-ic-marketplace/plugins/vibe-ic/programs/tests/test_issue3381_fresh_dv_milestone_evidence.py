"""#3381: fresh DV milestone evidence is separate from imported status."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import l10_tb_conformance_check as gate  # noqa: E402
from _hostpaths import require_repo  # noqa: E402

SCHEMA = "vibeic.dv-milestone-assessment.v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_sha(row: dict) -> str:
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def _project(tmp_path: Path, *, source_status=None, verdict="PASS",
             evidence=True, assessment_id="LINE_COVERAGE_COMPLETE"):
    project = tmp_path / "project"
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    row = {"name": "LINE_COVERAGE_COMPLETE",
           "kind": "verification_checklist"}
    if source_status is not None:
        row["status"] = source_status
    l10 = generated / "L10_TEST_CASES.json"
    l10.write_text(json.dumps({"test_cases": [row]}))

    rtl = project / "phase2" / "stage1" / "rtl" / "core.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module core; endmodule\n")
    tb = project / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_core.sv").write_text(
        "module tb_core; core u_dut(); endmodule\n")
    summary = project / "phase2" / "stage1" / "sim" / "work" / "summary.txt"
    summary.parent.mkdir(parents=True)
    summary.write_text("current run\n")
    measured = project / "reports" / "coverage" / "line.json"
    measured.parent.mkdir(parents=True)
    measured.write_text('{"line_percent": 100.0, "uncovered": 0}\n')

    assessment = project / "reports" / "phase2" / "dv_milestone_assessment.json"
    assessment.parent.mkdir(parents=True)
    evidence_rows = ([{"path": "reports/coverage/line.json",
                       "sha256": _sha(measured)}] if evidence else [])
    assessment.write_text(json.dumps({
        "schema": SCHEMA,
        "l10_sha256": _sha(l10),
        "rtl_files_sha256": {"phase2/stage1/rtl/core.sv": _sha(rtl)},
        "rows": [{
            "id": assessment_id,
            "source_row_sha256": _row_sha(row),
            "verdict": verdict,
            "producer": "coverage-runner",
            "acceptance_condition": "measured line coverage reaches 100%",
            "signed_by": "dv-reviewer",
            "review": "checked the current report and uncovered-line census",
            "evidence": evidence_rows,
        }],
    }))
    return project, l10, row, rtl, measured, assessment


def _run(project: Path, l10: Path):
    out = project / "reports" / "gates" / "l10.json"
    rc = gate.main([
        "--l10", str(l10),
        "--project", str(project),
        "--tb-dir", str(project / "phase2/stage1/sim/tb"),
        "--summary", str(project / "phase2/stage1/sim/work/summary.txt"),
        "--out", str(out),
    ])
    return rc, json.loads(out.read_text())


def test_current_pass_closes_blank_source_without_rewriting_it(tmp_path):
    project, l10, _row, _rtl, _measured, _assessment = _project(tmp_path)
    rc, report = _run(project, l10)
    assert rc == 0
    result = report["results"][0]
    assert result["source_status"] is None
    assert result["source_classification"] == "checklist_gap"
    assert result["current_assessment"]["verdict"] == "PASS"
    assert result["current_assessment"]["producer"] == "coverage-runner"
    assert report["dv_milestone_assessment"]["sha256"] == _sha(_assessment)
    assert result["status"] == "pass"


def test_current_fail_reopens_done_while_preserving_source_history(tmp_path):
    project, l10, _row, _rtl, _measured, _assessment = _project(
        tmp_path, source_status="Done", verdict="FAIL")
    rc, report = _run(project, l10)
    assert rc == 3
    result = report["results"][0]
    assert result["source_status"] == "done"
    assert result["source_classification"] == "satisfied"
    assert result["current_assessment"]["verdict"] == "FAIL"
    assert result["status"] == "checklist_gap"


def test_stale_l10_assessment_cannot_close_blank_source(tmp_path):
    project, l10, *_ = _project(tmp_path)
    doc = json.loads(l10.read_text())
    doc["test_cases"][0]["note"] = "source changed"
    l10.write_text(json.dumps(doc))
    rc, report = _run(project, l10)
    assert rc == 3
    assert report["dv_milestone_assessment"]["available"] is False
    assert report["dv_milestone_assessment"]["reason"] \
        == "assessment_l10_hash_mismatch"


def test_changed_rtl_invalidates_current_assessment(tmp_path):
    project, l10, _row, rtl, *_ = _project(tmp_path)
    rtl.write_text("module core; wire changed; endmodule\n")
    rc, report = _run(project, l10)
    assert rc == 3
    assert report["dv_milestone_assessment"]["reason"] \
        == "assessment_rtl_context_mismatch"


def test_wrong_source_row_scope_cannot_close_milestone(tmp_path):
    project, l10, _row, _rtl, _measured, assessment = _project(tmp_path)
    doc = json.loads(assessment.read_text())
    doc["rows"][0]["source_row_sha256"] = "0" * 64
    assessment.write_text(json.dumps(doc))
    rc, report = _run(project, l10)
    assert rc == 3
    current = report["results"][0]["current_assessment"]
    assert current["available"] is False
    assert "source_row_hash_mismatch" in current["refusals"]


def test_changed_or_missing_evidence_cannot_close_milestone(tmp_path):
    project, l10, _row, _rtl, measured, _assessment = _project(tmp_path)
    measured.write_text('{"line_percent": 96.77, "uncovered": 70}\n')
    rc, report = _run(project, l10)
    assert rc == 3
    assert "evidence_0_hash_mismatch" in \
        report["results"][0]["current_assessment"]["refusals"]


def test_evidence_free_pass_is_refused(tmp_path):
    project, l10, *_ = _project(tmp_path, evidence=False)
    rc, report = _run(project, l10)
    assert rc == 3
    assert "no_evidence" in \
        report["results"][0]["current_assessment"]["refusals"]


def test_unnamed_measurement_producer_is_refused(tmp_path):
    project, l10, _row, _rtl, _measured, assessment = _project(tmp_path)
    doc = json.loads(assessment.read_text())
    doc["rows"][0].pop("producer")
    assessment.write_text(json.dumps(doc))
    rc, report = _run(project, l10)
    assert rc == 3
    assert "missing_producer" in \
        report["results"][0]["current_assessment"]["refusals"]


def test_wrong_milestone_id_is_disclosed_and_does_not_close(tmp_path):
    project, l10, *_ = _project(tmp_path, assessment_id="OTHER_MILESTONE")
    rc, report = _run(project, l10)
    assert rc == 3
    assert report["dv_milestone_assessment"]["unclaimed_rows"] \
        == ["OTHER_MILESTONE"]
    assert report["results"][0]["current_assessment"]["reason"] \
        == "milestone_absent_from_current_assessment"


def test_writer_hashes_live_inputs_instead_of_accepting_claimed_hashes(tmp_path):
    project, l10, row, _rtl, _measured, assessment = _project(tmp_path)
    assessment.unlink()
    import _dv_milestone_assessment as contract
    target = contract.write_record(project, l10, [row], [{
        "id": row["name"],
        "verdict": "PASS",
        "producer": "coverage-runner",
        "acceptance_condition": "measured line coverage reaches 100%",
        "signed_by": "dv-reviewer",
        "review": "checked current measurement",
        "evidence": [{"path": "reports/coverage/line.json",
                      "sha256": "0" * 64}],
    }])
    doc = json.loads(target.read_text())
    assert doc["rows"][0]["evidence"][0]["sha256"] \
        == _sha(project / "reports/coverage/line.json")
    rc, report = _run(project, l10)
    assert rc == 0
    assert report["results"][0]["current_assessment"]["available"] is True


def test_checked_in_phase1_plan_cannot_masquerade_as_current_measurement(
        tmp_path):
    project, l10, _row, _rtl, _measured, assessment = _project(tmp_path)
    source = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "phase1_local", "coverage_goal_table_local",
        "verification_plan.md")
    copied = project / "phase1" / "input_doc" / "verification_plan.md"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(source.read_bytes())
    doc = json.loads(assessment.read_text())
    doc["rows"][0]["evidence"] = [{
        "path": "phase1/input_doc/verification_plan.md",
        "sha256": _sha(copied),
    }]
    assessment.write_text(json.dumps(doc))

    rc, report = _run(project, l10)
    assert rc == 3
    assert "evidence_0_not_current_run_output" in \
        report["results"][0]["current_assessment"]["refusals"]
