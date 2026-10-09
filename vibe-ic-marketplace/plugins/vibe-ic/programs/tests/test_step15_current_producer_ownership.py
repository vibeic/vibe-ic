from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_backend_producers as backend_producers
import execution_backend_worker as backend_worker
import flow_declared_producer_run as declared


def _step15_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    # `owed` requires a sibling output to prove that this step actually ran.
    (pnr / "floorplan.def").write_text("synthetic floorplan\n")
    (pnr / "pdn.done").write_text("synthetic pdn\n")
    return project


def test_current_step_producer_scope_stamps_step15_and_skips_other_steps(tmp_path):
    project = _step15_project(tmp_path)

    record = declared.run_for_step(project, "15", timeout=30)

    assert record["scope"] == "current-step"
    assert record["step_id"] == "15"
    assert record["owed"] == 1
    assert record["executed"] == 1
    # The producer writes its stamped report, but the deliberately tiny
    # project makes stage2_compliance return rc=1.  Presence alone is not a
    # producer success signal.
    assert record["documents_now_present"] == 0
    assert record["verdict"] == "INCOMPLETE"
    assert record["results"][0]["target_exists_after"] is True
    assert record["results"][0]["authorship"] == "producer"
    assert all(row["step"] == "15" for row in record["results"])
    assert not any(row["step"] == "26" for row in record["results"])

    report = project / "reports/phase2/gates/stage2_compliance.json"
    assert report.is_file()
    assert json.loads(report.read_text())["invoked_as"] == "producer"


def test_current_step_replaces_audit_authored_target_with_producer_receipt(tmp_path):
    project = _step15_project(tmp_path)
    report = project / "reports/phase2/gates/stage2_compliance.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"invoked_as": "audit", "verdict": "PASS"}) + "\n")

    record = declared.run_for_step(project, "15", timeout=30)

    assert record["owed"] == 1
    assert record["executed"] == 1
    assert json.loads(report.read_text())["invoked_as"] == "producer"


def test_current_step_scope_filters_before_owed_and_run(tmp_path, monkeypatch):
    clauses = [
        {"step": "15", "program": "stage2_compliance", "target": "15.json"},
        {"step": "26", "program": "antenna_report_check", "target": "26.json"},
    ]
    owed_seen = []
    run_seen = []

    def fake_owed(project, selected):
        owed_seen.extend(selected)
        return list(selected), []

    def fake_run_one(project, row, timeout):
        run_seen.append(row["step"])
        return {"step": row["step"], "executed": True,
                "rc": 0, "target_exists_after": True, "authorship": "producer"}

    monkeypatch.setattr(declared, "declared_producer_clauses", lambda: clauses)
    monkeypatch.setattr(declared, "owed", fake_owed)
    monkeypatch.setattr(declared, "_run_one", fake_run_one)

    record = declared.run_for_step(tmp_path, "15")

    assert [row["step"] for row in owed_seen] == ["15"]
    assert run_seen == ["15"]
    assert record["step_id"] == "15"
    assert record["executed"] == 1


def test_backend_producer_orders_current_declared_outputs_before_consumer(
        tmp_path, monkeypatch):
    events = []

    def fake_native(project, params):
        events.append("native")
        return {"verdict": "PASS", "detail": "fixture"}

    def fake_declared(project, step_id):
        events.append(("declared", str(step_id)))
        return {"scope": "current-step", "step_id": str(step_id),
                "verdict": "PRODUCED", "executed": 1, "population": 1,
                "invalid_results": [], "unexecutable": [],
                "results": [{"rc": 0, "executed": True, "target_exists_after": True,
                              "authorship": "producer"}]}

    monkeypatch.setattr(backend_producers, "produce_pnr", fake_native)
    # Inject the existing producer module seam instead of stubbing the new
    # private helper.  On the parent revision `produce` never imports this
    # module, so the control observes the missing current-step invocation as a
    # value (the event list), rather than failing only because a new symbol is
    # absent.
    fake_module = types.SimpleNamespace(run_for_step=fake_declared)
    monkeypatch.setitem(sys.modules, "flow_declared_producer_run", fake_module)

    result = backend_producers.produce(tmp_path, {"step_id": "15"})

    assert events == ["native", ("declared", "15")]
    assert result["current_step_declared_producers"]["step_id"] == "15"


def test_real_backend_worker_runs_declared_producer_before_consumer(
        tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    project_input = inputs / "project"
    project_input.mkdir(parents=True)
    (project_input / "fixture.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    outputs = tmp_path / "outputs"
    events = []

    def fake_native(project, params):
        events.append("native")
        pnr = project / "phase3/stage3/pnr"
        pnr.mkdir(parents=True, exist_ok=True)
        (pnr / "floorplan.def").write_text("synthetic floorplan\n")
        (pnr / "pdn.done").write_text("synthetic pdn\n")
        return {"verdict": "PASS", "detail": "fixture native"}

    def observed_consumer(project, row):
        report = project / "reports/phase2/gates/stage2_compliance.json"
        assert json.loads(report.read_text())["invoked_as"] == "producer"
        events.append("consumer")
        return {"status": "PASS", "ledger": []}

    monkeypatch.setattr(backend_producers, "produce_pnr", fake_native)
    def fake_declared(project, step_id):
        events.append(("declared", str(step_id)))
        report = project / "reports/phase2/gates/stage2_compliance.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"invoked_as": "producer", "verdict": "PASS"}) + "\n")
        return {"scope": "current-step", "step_id": str(step_id),
                "verdict": "PRODUCED", "executed": 1, "population": 1,
                "invalid_results": [], "unexecutable": [],
                "results": [{"rc": 0, "executed": True, "target_exists_after": True,
                              "authorship": "producer"}]}
    monkeypatch.setitem(sys.modules, "flow_declared_producer_run",
                        types.SimpleNamespace(run_for_step=fake_declared))
    monkeypatch.setattr(backend_worker, "produce", backend_producers.produce)
    monkeypatch.setattr(backend_worker, "evaluate", observed_consumer)
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "source_sha": "fixture", "required_gates": []}))

    result = backend_worker.execute(
        inputs, outputs, step_id="15",
        params={"input_contract": [{"from": "external", "path": "fixture.sdc"}]})

    assert events == ["native", ("declared", "15"), "consumer"]
    assert result["verdict"] == "PASS"
    assert "reports/phase2/gates/stage2_compliance.json" in result["outputs"]


def test_declared_nonzero_rc_missing_target_is_incomplete(tmp_path, monkeypatch):
    row = {"step": "15", "program": "stage2_compliance", "target": "stage2.json"}
    monkeypatch.setattr(declared, "owed", lambda project, clauses: (clauses, []))
    monkeypatch.setattr(declared, "_run_one", lambda project, clause, timeout: {
        **clause, "rc": 1, "executed": True, "target_exists_after": False,
    })
    record = declared._run_clauses(tmp_path, [row])
    assert record["verdict"] == "INCOMPLETE"
    assert record["invalid_results"]
    assert record["documents_now_present"] == 0


def _reuse_clause():
    return {"step": "15", "program": "stage2_compliance",
            "command": "stage2_compliance . --json report.json",
            "target": "report.json", "siblings": ["native.def"]}


def _producer_report():
    return {"program": "flow_compliance_check", "invoked_as": "producer",
            "overall": "PASS", "scope": {"stage": "2"},
            "counts": {"PASS": 1}, "steps": [{"id": "12", "status": "PASS"}],
            "invocation": "prior-wall-clock-invocation"}


def test_current_step_reuses_content_and_input_bound_prior_producer(tmp_path, monkeypatch):
    clause = _reuse_clause()
    (tmp_path / "native.def").write_text("current native output\n")
    (tmp_path / "input.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    calls = []

    def successful_producer(project, row, timeout):
        calls.append(row["step"])
        (project / row["target"]).write_text(json.dumps(_producer_report()))
        return {**row, "rc": 0, "executed": True,
                "target_exists_after": True, "authorship": "producer"}

    monkeypatch.setattr(declared, "declared_producer_clauses", lambda: [clause])
    monkeypatch.setattr(declared, "_run_one", successful_producer)
    first = declared.run_for_step(tmp_path, "15")
    second = declared.run_for_step(tmp_path, "15")
    assert first["verdict"] == second["verdict"] == "PRODUCED"
    assert calls == ["15"]
    assert second["already_produced_by_the_run"] == 1
    assert second["skipped"][0]["current_input_identity_valid"] is True
    assert backend_producers._current_step_producer_authority(second)[0] is True


@pytest.mark.parametrize("mutation", ["garbage", "changed_target", "changed_input", "changed_source"])
def test_stale_producer_target_cannot_skip_current_step_failure(
        tmp_path, monkeypatch, mutation):
    clause = _reuse_clause()
    (tmp_path / "native.def").write_text("current native output\n")
    (tmp_path / "input.sdc").write_text("current constraints\n")

    def successful_producer(project, row, timeout):
        (project / row["target"]).write_text(json.dumps(_producer_report()))
        return {**row, "rc": 0, "executed": True,
                "target_exists_after": True, "authorship": "producer"}

    monkeypatch.setattr(declared, "declared_producer_clauses", lambda: [clause])
    monkeypatch.setattr(declared, "_run_one", successful_producer)
    assert declared.run_for_step(tmp_path, "15")["verdict"] == "PRODUCED"
    if mutation == "garbage":
        (tmp_path / "report.json").write_text(json.dumps({"invoked_as": "producer", "garbage": True}))
    elif mutation == "changed_target":
        doc = _producer_report()
        doc["counts"] = {"PASS": 999}
        (tmp_path / "report.json").write_text(json.dumps(doc))
    elif mutation == "changed_input":
        (tmp_path / "input.sdc").write_text("changed constraints\n")
    else:
        record_path = tmp_path / declared.REPORT_REL
        prior = json.loads(record_path.read_text())
        prior["input_identity"]["source_sha"] = "0" * 40
        record_path.write_text(json.dumps(prior))
    owed, skipped = declared.owed(tmp_path, [clause])
    if mutation == "garbage":
        assert [row["target"] for row in owed] == ["report.json"]
        assert skipped == []
    else:
        assert [row["target"] for row in skipped] == ["report.json"]
    calls = []
    monkeypatch.setattr(declared, "_run_one", lambda project, row, timeout:
                        calls.append(row["step"]) or {**row, "rc": 1,
                            "executed": True, "target_exists_after": True,
                            "authorship": "producer"})
    result = declared.run_for_step(tmp_path, "15")
    assert calls == ["15"]
    assert result["already_produced_by_the_run"] == 0
    assert result["verdict"] == "INCOMPLETE"
    assert backend_producers._current_step_producer_authority(result) == (
        False, "current-step producer execution failed", "FAIL")


@pytest.mark.parametrize('failure', ['audit', 'unstamped', 'exception', 'nonzero',
                                    'missing_target', 'zero_population'])
def test_audit_authored_current_step_blocks_backend_consumer(
        tmp_path, monkeypatch, failure):
    inputs = tmp_path / "inputs"
    project_input = inputs / "project"
    project_input.mkdir(parents=True)
    source = project_input / "fixture.sdc"
    source.write_text("create_clock -period 10 [get_ports clk]\n")
    calls = []

    def fake_native(project, params):
        calls.append("native")
        pnr = project / 'phase3/stage3/pnr'
        pnr.mkdir(parents=True)
        (pnr / 'floorplan.def').write_text('VERSION 5.8 ;\nEND DESIGN\n')
        (pnr / 'pdn.done').write_text('pdn complete\n')
        return {"verdict": "PASS", "detail": "native outputs retained"}

    def fake_declared(project, step_id):
        if failure == 'exception':
            raise RuntimeError('declared producer failed')
        report = project / "reports/phase2/gates/stage2_compliance.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"invoked_as": "audit", "verdict": "PASS"}) + "\n")
        row = {"rc": 1 if failure == 'nonzero' else 0, "executed": True,
               "target_exists_after": failure != 'missing_target',
               "authorship": 'audit' if failure == 'audit' else
                    None if failure == 'unstamped' else 'producer'}
        return {"scope": "current-step", "step_id": str(step_id),
                "verdict": "PRODUCED", "population": 0 if failure == 'zero_population' else 1,
                "executed": 1, "invalid_results": [], "unexecutable": [], "results": [row]}

    monkeypatch.setattr(backend_producers, "produce_pnr", fake_native)
    monkeypatch.setitem(sys.modules, "flow_declared_producer_run",
                        types.SimpleNamespace(run_for_step=fake_declared))
    monkeypatch.setattr(backend_worker, "produce", backend_producers.produce)
    monkeypatch.setattr(backend_worker, "evaluate",
                        lambda project, row: calls.append("consumer") or {
                            "status": "PASS", "ledger": []})
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "source_sha": "fixture", "required_gates": []}))
    manifest = {"declarations": [{"from": "external", "path": "fixture.sdc"}],
                "files": {"fixture.sdc": backend_worker.sha(source)}, "missing": []}
    result = backend_worker.execute(
        inputs, tmp_path / "outputs", step_id="15",
        params={"resolved_input_manifest": manifest})
    assert calls == ["native"]
    expected = 'FAIL' if failure == 'nonzero' else 'NOT_MEASURED'
    assert result["verdict"] == expected
    assert result["current_step_declared_producers"]["consumer_allowed"] is False
    assert result["current_step_declared_producers"]["authority_verdict"] == expected
    assert result['canonical_receipts'][0]['current_step_declared_producers'] == (
        result['current_step_declared_producers'])
