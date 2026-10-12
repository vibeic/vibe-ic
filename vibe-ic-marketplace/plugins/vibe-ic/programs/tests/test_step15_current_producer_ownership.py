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
    # The producer writes its stamped report, and the deliberately tiny
    # project makes the explicitly advisory stage2_compliance return rc=1.
    # The finding stays in the receipt but does not deny producer completeness.
    assert record["documents_now_present"] == 1
    assert record["verdict"] == "PRODUCED"
    assert record["results"][0]["target_exists_after"] is True
    assert record["results"][0]["authorship"] == "producer"
    assert record["results"][0]["enforcement"] == "advisory"
    assert not record["invalid_results"]
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


def test_audit_gate_json_is_not_a_step_sibling_or_input_closure(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    gate_json = project / "reports/lec_equivalence_check.json"
    gate_json.parent.mkdir(parents=True)
    gate_json.write_text(json.dumps({"invoked_as": "audit", "verdict": "PASS"}) + "\n")
    producer_json = project / "reports/real_producer.json"
    producer_json.write_text(json.dumps({
        "invoked_as": "producer", "program": "real_producer",
    }) + "\n")

    clauses = [{"step": "15", "program": "stage2_compliance",
                "target": "reports/phase2/gates/stage2_compliance.json",
                "siblings": ["reports/lec_equivalence_check.json"]}]
    to_run, skipped = declared.owed(project, clauses)
    assert not to_run
    assert skipped and "did not perform" in skipped[0]["why"]

    identity = declared._current_input_identity(project, clauses)
    assert "reports/lec_equivalence_check.json" not in identity["files"]
    assert "reports/real_producer.json" in identity["files"]


def test_audit_role_gate_output_is_excluded_but_producer_role_survives(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    audit_json = project / "reports/analog/a1_spec.json"
    audit_json.parent.mkdir(parents=True)
    audit_json.write_text(json.dumps({"invoked_as": "audit", "verdict": "PASS"}) + "\n")
    producer_json = project / "reports/analog/a1_spec_produced.json"
    producer_json.write_text(json.dumps({
        "invoked_as": "producer", "program": "analog_a1_spec_extract_check",
    }) + "\n")
    identity = declared._current_input_identity(project, [{
        "step": "A1", "program": "analog_a1_spec_extract_check",
        "target": "reports/analog/a1_spec.json",
    }])
    assert "reports/analog/a1_spec.json" not in identity["files"]
    assert "reports/analog/a1_spec_produced.json" in identity["files"]


def test_canonical_local_input_alias_binds_actual_phase_output(tmp_path):
    target = tmp_path / "phase1/generated_docs/L1_DATASHEET.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"spec": "first"}\n')
    alias = tmp_path / "steps/phase1/D1/L1_DATASHEET.json"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(target)
    first = declared._current_input_identity(tmp_path, [])
    assert "phase1/generated_docs/L1_DATASHEET.json" in first["files"]
    assert "steps/phase1/D1/L1_DATASHEET.json" not in first["files"]
    target.write_text('{"spec": "changed"}\n')
    second = declared._current_input_identity(tmp_path, [])
    assert first != second


def test_local_alias_cannot_bind_a_file_outside_this_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "other.json"
    outside.write_text('{}\n')
    (project / "alias.json").symlink_to(outside)
    with pytest.raises(ValueError, match="leaves project"):
        declared._current_input_identity(project, [])


def test_installed_package_input_identity_uses_actual_source_bytes(tmp_path, monkeypatch):
    source = tmp_path / "installed_programs"
    source.mkdir()
    writer = source / "stage2_compliance.py"
    writer.write_text("print('first source')\n")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(declared, "PROGRAMS_DIR", source)
    monkeypatch.setattr(declared.subprocess, "check_output", lambda *_a, **_k:
                        pytest.fail("installed package has no Git metadata"))
    clauses = [{"program": "stage2_compliance", "target": "report.json"}]
    first = declared._current_input_identity(project, clauses)
    assert first["source_sha"].startswith("sha256:")
    writer.write_text("print('changed source')\n")
    second = declared._current_input_identity(project, clauses)
    assert first["source_sha"] != second["source_sha"]


def test_future_output_alias_does_not_block_current_step_producer(tmp_path, monkeypatch):
    clause = _reuse_clause()
    (tmp_path / "native.def").write_text("current native output\n")
    future = tmp_path / "steps/phase3/future/corner_test_vectors.json"
    future.parent.mkdir(parents=True)
    future.symlink_to(tmp_path / "phase3/stage4/foundry_handoff/corner_test_vectors.json")

    def producer(project, row, timeout):
        (project / row["target"]).write_text(json.dumps(_producer_report()))
        return {**row, "rc": 0, "executed": True,
                "target_exists_after": True, "authorship": "producer"}

    monkeypatch.setattr(declared, "declared_producer_clauses", lambda: [clause])
    monkeypatch.setattr(declared, "_run_one", producer)
    result = declared.run_for_step(tmp_path, "15")
    assert result["verdict"] == "PRODUCED"
    assert result["executed"] == 1
    assert not result["invalid_results"]
    assert not future.exists()


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


@pytest.mark.parametrize("rc,enforcement", [(0, None), (1, "advisory")],
                         ids=["clean", "advisory-finding"])
def test_real_backend_worker_runs_declared_producer_before_consumer(
        tmp_path, monkeypatch, rc, enforcement):
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
        (pnr / "constraint.sdc").write_text((project_input / "fixture.sdc").read_text())
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
        result = {"scope": "current-step", "step_id": str(step_id),
                "verdict": "PRODUCED", "executed": 1, "population": 1,
                "invalid_results": [], "unexecutable": [],
                "results": [{"rc": rc, "executed": True,
                              "target_exists_after": True,
                              "target_content_valid": True,
                              "authorship": "producer"}]}
        if enforcement:
            result["results"][0]["enforcement"] = enforcement
        return result
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
    assert result["current_step_declared_producers"]["results"][0]["rc"] == rc
    assert result["current_step_declared_producers"]["consumer_allowed"] is True


@pytest.mark.parametrize("rc,target_exists", [(1, False), (2, True)],
                         ids=["missing-output", "advisory-rc2"])
def test_advisory_finding_does_not_hide_missing_output_or_rc2(
        tmp_path, monkeypatch, rc, target_exists):
    row = {"step": "15", "program": "stage2_compliance",
           "target": "stage2.json", "enforcement": "advisory"}
    monkeypatch.setattr(declared, "owed", lambda project, clauses: (clauses, []))
    monkeypatch.setattr(declared, "_run_one", lambda project, clause, timeout: {
        **clause, "rc": rc, "executed": True,
        "target_exists_after": target_exists,
        "target_content_valid": target_exists,
        "authorship": "producer",
    })
    record = declared._run_clauses(tmp_path, [row])
    assert record["verdict"] == "INCOMPLETE"
    assert record["invalid_results"]
    assert record["documents_now_present"] == 0


def test_blocking_consumer_failure_still_fails_after_advisory_producer(
        tmp_path, monkeypatch):
    project = _step15_project(tmp_path)
    current = {
        "schema": "vibeic/current-step-producer-census/1",
        "step_id": "15", "scope": "current-step", "verdict": "PRODUCED",
        "population": 1, "executed": 1, "invalid_results": [],
        "unexecutable": [], "already_produced_by_the_run": 0,
        "results": [{"rc": 1, "enforcement": "advisory", "executed": True,
                     "target_exists_after": True,
                     "target_content_valid": True, "authorship": "producer"}],
    }
    monkeypatch.setattr(backend_worker, "evaluate",
                        lambda _project, _row: {
                            "status": "FAIL",
                            "ledger": [{"gate": "blocking", "verdict": "FAIL"}],
                        })
    result = backend_worker.execute_current_step(
        project, step_id="15", producer={
            "verdict": "PASS",
            "current_step_declared_producers": current,
        })
    assert result["verdict"] == "FAIL"
    assert result["gate_ledger"][0]["verdict"] == "FAIL"


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
