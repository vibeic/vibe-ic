"""Neutral lifecycle controls through the existing gate and attempt journal.

These are source controls, not native signoff receipts or benchmark evidence.
"""
import hashlib
import json

import pytest

import l24_signoff_evidence_backed_check as gate
import phase1_post_process
import step_output_collector as versions
from flow_artifact_paths import gate_parameters


def project(tmp_path, text="Sign-off requires DRC clean.\n"):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text(text)
    doc = phase1_post_process.emit_l_doc_skeleton("L24", "unknown", project_dir=tmp_path)
    generated = tmp_path / "phase1/generated_docs"
    generated.mkdir(parents=True)
    (generated / "L24_SIGNOFF.json").write_text(json.dumps(doc))
    report = tmp_path / "reports/phase3/pnr/floorplan_pdn.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"program":"floorplan_pdn_check","verdict":"PASS"}')
    constraint = tmp_path / "phase2/stage2/constraints/neutral.sdc"
    constraint.parent.mkdir(parents=True)
    constraint.write_text("create_clock -period 20 [get_ports clk]\n")
    return tmp_path, constraint


def attempt(p, constraint, sid, status=None):
    binding = {str(constraint.relative_to(p)): hashlib.sha256(constraint.read_bytes()).hexdigest()}
    with gate_parameters(p, {"top": "neutral"}):
        row = versions.begin_step(p, sid, binding)
        if status is not None:
            versions.finish_step(p, row, verdict=status, result={"detail": "synthetic producer outcome"})
    return row


def read(p, tmp_path):
    out = tmp_path / "reading.json"
    rc = gate.main(["l24_signoff_evidence_backed_check", str(p), "--json", str(out)])
    return rc, json.loads(out.read_text())


def outcomes(record):
    return {row["check"]: row["outcome"] for row in record["requirements"]}


def test_floorplan_only_keeps_each_future_reading_pending(tmp_path):
    p, sdc = project(tmp_path, "DRC clean; LVS clean; STA met; antenna 100% clean.\n"
                                "Power network shall have no disconnected ports.\n")
    attempt(p, sdc, "15", "PASS")
    rc, record = read(p, tmp_path)
    assert rc == 0
    assert set(outcomes(record).values()) == {"NOT_YET_MEASURABLE"}
    assert record["reason_class"] == "ASKED_BEFORE_PRODUCER"
    assert {r["check"]: r["producer_step"] for r in record["requirements"]} == {
        "DRC": "31", "LVS": "31", "STA": "23", "antenna": "26", "power_network": "23"}


@pytest.mark.parametrize("status", [None, "FAIL", "PASS"])
def test_due_attempt_without_reading_is_unmet(tmp_path, status):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    attempt(p, sdc, "31", status)
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


def test_due_is_per_requirement_in_canonical_order(tmp_path):
    p, sdc = project(tmp_path, "DRC clean; STA met.\n")
    attempt(p, sdc, "23", "FAIL")
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record) == {"DRC": "NOT_YET_MEASURABLE", "STA": "UNMET_NO_READING"}


@pytest.mark.parametrize("sid", ["31", "36"])
def test_attempt_that_emits_no_phase3_json_still_makes_reading_due(tmp_path, sid):
    p, sdc = project(tmp_path)
    (p / "reports/phase3/pnr/floorplan_pdn.json").unlink()
    attempt(p, sdc, sid, "FAIL")
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


def test_actual_failure_precedes_future_producer(tmp_path):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    (p / "reports/phase3/drc_signoff.json").write_text('{"verdict":"FAIL"}')
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_MEASURED_FAILING"


def test_sibling_lvs_attempt_without_summary_makes_drc_due(tmp_path):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    (p / "reports/phase3/lvs_verdict.json").write_text('{"program":"native_lvs"}')
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


@pytest.mark.parametrize("sid,requirement", [("32", "STA met."), ("37", "DRC clean.")])
def test_canonical_order_is_not_numeric_order(tmp_path, sid, requirement):
    p, sdc = project(tmp_path, requirement)
    attempt(p, sdc, sid, "PASS")
    rc, record = read(p, tmp_path)
    assert rc == 0
    assert set(outcomes(record).values()) == {"NOT_YET_MEASURABLE"}


def test_existing_pass_still_requires_each_engine(tmp_path):
    p, sdc = project(tmp_path, "DRC clean using Magic and KLayout.\n")
    attempt(p, sdc, "15", "PASS")
    (p / "reports/phase3/drc_signoff.json").write_text('{"verdict":"PASS"}')
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_ENGINE_EVIDENCE"


@pytest.mark.parametrize("context", ["terminal", "whole_audit"])
def test_final_completion_without_readings_remains_unmet(tmp_path, monkeypatch, context):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    if context == "terminal":
        summary = p / "reports/orchestrator/phase3_one_shot.json"
        summary.parent.mkdir(parents=True)
        summary.write_text('{"program":"phase3_one_shot_runner","verdict":"PASS"}')
    else:
        monkeypatch.setenv("VIBEIC_FCC_ACTIVE_SCOPES", "ALL:stage2:stage1")
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


def test_asserted_pass_without_evidence_remains_false_certificate(tmp_path):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    path = p / "phase1/generated_docs/L24_SIGNOFF.json"
    doc = json.loads(path.read_text())
    doc["fields"]["drc_status"] = "PASS"
    path.write_text(json.dumps(doc))
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert "unevidenced" in " ".join(record["findings"]).lower() or any(
        "evidence" in item.lower() for item in record["findings"])


def test_stale_early_attempt_cannot_defer_missing_reports(tmp_path):
    p, sdc = project(tmp_path)
    attempt(p, sdc, "15", "PASS")
    sdc.write_text("create_clock -period 40 [get_ports clk]\n")
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


def test_legacy_without_canonical_attempt_keeps_strict_behavior(tmp_path):
    p, _ = project(tmp_path)
    rc, record = read(p, tmp_path)
    assert rc == 1
    assert outcomes(record)["DRC"] == "UNMET_NO_READING"


@pytest.mark.parametrize('producer_started', [False, True])
def test_preflight_refusal_is_not_a_signoff_producer_attempt(tmp_path, producer_started):
    p, sdc = project(tmp_path)
    attempt(p, sdc, '15', 'PASS')
    row = versions.begin_step(p, '31', {})
    versions.finish_step(p, row, verdict='NOT_MEASURED', result={
        'producer_started': producer_started,
        'preflight_verdict': 'READY' if producer_started else 'REFUSED',
        'finding': 'PRODUCER_ATTEMPTED' if producer_started else 'REQUIRED_INPUT_ABSENT'})
    rc, record = read(p, tmp_path)
    assert rc == (1 if producer_started else 0)
    assert outcomes(record)['DRC'] == (
        'UNMET_NO_READING' if producer_started else 'NOT_YET_MEASURABLE')


@pytest.mark.parametrize('status', ['NOT_MEASURED', 'FAIL'])
def test_known_upstream_canonical_halt_does_not_attempt_later_signoff(tmp_path, status):
    p, sdc = project(tmp_path)
    attempt(p, sdc, '15', 'PASS')
    attempt(p, sdc, '20', status)
    summary = p / 'reports/orchestrator/phase3_one_shot.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({'program': 'phase3_one_shot_runner',
        'verdict': status, 'steps': [{'name': 'pnr', 'status': status,
            'extras': {'canonical_steps': [{'name': 'default_step_20',
                'status': status, 'extras': {'step_id': '20'}}]}}]}))
    rc, record = read(p, tmp_path)
    assert rc == 0
    assert outcomes(record)['DRC'] == 'NOT_YET_MEASURABLE'
    assert record['reason_class'] == 'ASKED_BEFORE_PRODUCER'
