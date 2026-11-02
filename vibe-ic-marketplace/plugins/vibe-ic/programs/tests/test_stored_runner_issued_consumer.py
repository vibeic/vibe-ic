"""Historical measurements name their issuer, never a later auditor revision.

Use the existing actual native report writer and invocation seam. Different
auditor bytes do not reattribute the producer or make a new gate measurement.
"""
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import benchmark_dispatch as current
import test_runner_report_generation as report_fixture


def load_dispatch(path, suffix=""):
    path.write_bytes(Path(current.__file__).read_bytes() + suffix.encode())
    name = "test_issued_consumer_" + hashlib.sha256(str(path).encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def measured(tmp_path):
    issuer = load_dispatch(tmp_path / "issued_dispatch.py")
    auditor = load_dispatch(tmp_path / "auditor_dispatch.py", "\n# next neutral audit revision\n")
    project, runner = report_fixture._fixture(tmp_path)
    argv = [sys.executable, str(runner), str(project), "fresh"]
    process = issuer._RunnerBudget(1, 1, 1).run(argv)
    collected = issuer._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert process.rc == 1 and not process.error and collected["ok"], collected
    assert process.invocation["source_before"] == process.invocation["source_after"]
    return issuer, auditor, project, runner, argv, process


def test_different_auditor_revalidates_actual_issuer_without_rebinding(tmp_path):
    issuer, auditor, project, runner, argv, process = measured(tmp_path)
    old = Path(process.receipt_path).read_bytes()
    binding = json.loads((project / "reports/orchestrator/phase2_one_shot.json").read_text())["runner_binding"]
    diagnostic = auditor._stored_runner_diagnostics(process.invocation)
    (tmp_path / "stored-diagnostic.json").write_text(json.dumps(diagnostic, indent=2))
    assert diagnostic["status"] == "REPORTS_AVAILABLE", diagnostic
    assert not diagnostic.get("reason")
    assert binding["source"]["consumer"]["path"] == issuer.__file__
    assert Path(issuer.__file__).read_bytes() != Path(auditor.__file__).read_bytes()
    assert Path(process.receipt_path).read_bytes() == old
    # The same different auditor is NOT the issuer of this live process.
    live = auditor._runner_diagnostics(process, argv, project)
    assert live["status"] == "SOURCE_MISMATCH", live
    assert live["reason_class"] == "RUNNER_SOURCE_UNBOUND"


@pytest.mark.parametrize("damage", [
    "issuer_changed", "issuer_missing", "runner_changed", "runner_missing",
    "argv", "receipt", "report", "material", "issuer_path_missing",
])
def test_stored_issuer_selection_preserves_source_and_material_refusals(tmp_path, damage):
    issuer, auditor, project, runner, argv, process = measured(tmp_path)
    invocation = copy.deepcopy(process.invocation)
    if damage == "issuer_changed":
        path = Path(issuer.__file__)
        path.write_text(path.read_text() + "\n# issuer drift\n")
    elif damage == "issuer_missing":
        Path(issuer.__file__).unlink()
    elif damage == "runner_changed":
        runner.write_text(runner.read_text() + "\n# runner drift\n")
    elif damage == "runner_missing":
        runner.unlink()
    elif damage == "argv":
        invocation["argv"].append("--not-issued")
    elif damage == "receipt":
        path = Path(process.receipt_path)
        content = json.loads(path.read_text())
        content["rc"] = 0
        path.write_text(json.dumps(content))
    elif damage == "report":
        report = project / "reports/orchestrator/phase2_one_shot.json"
        report.write_text(report.read_text() + "\n")
    elif damage == "material":
        prompt = project / "input/phase1_prompt.md"
        prompt.write_text(prompt.read_text() + "Changed public requirement.\n")
    else:
        del invocation["source_before"]["consumer"]["path"]
        Path(process.receipt_path).write_text(json.dumps(invocation))
    try:
        diagnostic = auditor._stored_runner_diagnostics(invocation)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        assert damage in {"argv", "receipt", "issuer_path_missing"}, str(exc)
    else:
        assert diagnostic.get("reason"), diagnostic
        assert diagnostic["status"] in {
            "SOURCE_MISMATCH", "INVOCATION_MISMATCH", "MATERIAL_MISMATCH"}, diagnostic
        if damage in {"issuer_changed", "runner_changed"}:
            assert diagnostic["reason_class"] == "RUNNER_SOURCE_UNBOUND"
        if damage == "material":
            assert diagnostic["reason_class"] == "RUNNER_MATERIAL_UNBOUND"


@pytest.fixture(scope="module")
def ordinary_duplicate(tmp_path_factory):
    root = tmp_path_factory.mktemp("actual_duplicate")
    project = root / "project"
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Module name: straight_link\nInput a drives output y combinationally.\n")
    rtl = project / "phase2/stage1/rtl/straight_link.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module straight_link(input a,output y); assign y=a; endmodule\n")
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text('{"steps":{"2":"direct"}}')
    import source_manifest_md_emit
    assert source_manifest_md_emit.emit(project).is_file()
    argv = current._solver_argv(
        Path(current.__file__).parent / "vibe_ic_one_shot_runner.py", project,
        "2", "2", "ip", "original", "rtl")
    budget = current._RunnerBudget(1, 1, 1)
    measured = budget.run(argv)
    assert not measured.error, measured.stderr
    report = json.loads((project / "reports/orchestrator/phase2_one_shot.json").read_text())
    assert next(row for row in report["steps"] if row["name"] == "rtl_validate")["status"] == "PASS"
    assert current._stored_runner_diagnostics(measured.invocation)["status"] == "REPORTS_AVAILABLE"
    duplicate = budget.run(argv)
    assert duplicate.rc == 1 and not duplicate.error, duplicate.stderr
    assert "canonical Phase-2 admission: DUPLICATE_NO_NEW_EVIDENCE" in duplicate.stderr
    assert measured.invocation["material_after"] == duplicate.invocation["material_before"] == duplicate.invocation["material_after"]
    assert measured.invocation["reports_after"]["phase2_one_shot.json"] == duplicate.invocation["reports_after"]["phase2_one_shot.json"]
    return root, project, argv, measured, duplicate


def test_actual_ordinary_duplicate_wrapper_preserves_measured_phase2(ordinary_duplicate):
    root, project, argv, measured, duplicate = ordinary_duplicate
    before = Path(measured.receipt_path).read_bytes()
    refusal = Path(duplicate.receipt_path).read_bytes()
    diagnostic = current._stored_runner_diagnostics(measured.invocation)
    (root / "stored-after-duplicate.json").write_text(json.dumps(diagnostic, indent=2))
    assert diagnostic["status"] == "REPORTS_AVAILABLE", diagnostic
    assert not diagnostic.get("reason")
    assert diagnostic["retained_after_duplicate"]["invocation_id"] == duplicate.invocation_id
    assert diagnostic["invocation_id"] == measured.invocation_id
    assert Path(measured.receipt_path).read_bytes() == before
    assert Path(duplicate.receipt_path).read_bytes() == refusal
    # Live transport still reports the duplicate attempt's lack of a fresh P2.
    assert current._runner_diagnostics(duplicate, argv, project)["status"] == "STALE_RUNNER_REPORT"


def test_duplicate_wrapper_with_additional_phase2_failure_is_rejected(ordinary_duplicate):
    # Adversarial report fixture, not a claimed native failure measurement.
    # Keep the whole receipt/report binding consistent so the phase census,
    # rather than an unrelated hash mismatch, must reject the mixed account.
    root, project, argv, measured, duplicate = ordinary_duplicate
    assert not current._stored_runner_diagnostics(measured.invocation).get("reason")
    path = project / "reports/orchestrator/vibe_ic_one_shot.json"
    later_path = Path(duplicate.receipt_path)
    with restore_bytes([path, later_path]):
        wrapper = json.loads(path.read_text())
        wrapper["phases"].append({"name": "phase2", "verdict": "FAIL", "rc": 1})
        path.write_text(json.dumps(wrapper))
        later = json.loads(later_path.read_text())
        later["reports_after"] = current._runner_report_snapshot(project)
        later_path.write_text(json.dumps(later))
        diagnostic = current._stored_runner_diagnostics(measured.invocation)
        (root / "mixed-phase2-failure.json").write_text(json.dumps(diagnostic, indent=2))
        assert diagnostic.get("reason"), diagnostic


@contextmanager
def restore_bytes(paths):
    # Only private fixture inputs/receipts/source copies, never a source WT or RUN.
    originals = {Path(path): Path(path).read_bytes() for path in paths}
    try:
        yield
    finally:
        for path, data in originals.items():
            path.write_bytes(data)


@pytest.fixture(scope="module")
def retained_runtime():
    """Bind the real enclosing image before the child records its admission.

    An in-image panel supplies its host-inspected CID/image through the existing
    local attestation protocol. No native result or image identity is mocked.
    """
    from librelane_contract import local_image_attestation
    identity = local_image_attestation()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("VIBEIC_EDA_IMAGE", identity["image"])
        yield identity


@pytest.fixture(scope="module")
def retained_orphan(tmp_path_factory, retained_runtime):
    import benchmark_io_adapter as bio
    import test_benchmark_program_first_ai_review as envelope
    root = tmp_path_factory.mktemp("retained_orphan")
    run, project = root / "run", root / "run/projects/neutral"
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Design a module named neutral with input a and output y. "
                      "Output y must always equal input a.\n")
    public = bio._stage_public_original("neutral", prompt.read_text(), {}, project)
    routes = envelope._write_issued_run_envelope(run, {
        "id": "neutral", "project": str(project), "public_original_input": public})
    receipt = envelope._issue_pending_route_fixture(
        run, routes[0], requested_evidence="lint_validated")
    assert receipt["input_contract"] == "original"
    runner = Path(current.__file__).parent / "vibe_ic_one_shot_runner.py"
    argv = current._solver_argv(runner, project, receipt["entry_step"],
        receipt["verify_through"], "ip", "original", "rtl")
    budget = current._RunnerBudget(1, 1, 1)
    original = budget.run(argv)
    assert original.rc == 1 and not original.error, original.stderr
    assert current._rtl_gen_waive(project)["fallback_skill"] == "spec-to-rtl"
    duplicate = budget.run(argv)
    assert duplicate.rc == 1 and not duplicate.error, duplicate.stderr
    diagnostic = current._runner_diagnostics(duplicate, argv, project)
    assert diagnostic["status"] == "STALE_RUNNER_REPORT", diagnostic
    for name in (current._BACKUP_WORKLIST, current._REVIEW_WORKLIST,
                 current._REPAIR_WORKLIST, current._ENHANCEMENT_WORKLIST):
        current._write_jsonl(run / name, [])
    current._atomic_write_json(run / "solve_report.json", {
        "bench": "rtllm", "format": "rtllm", "dataset": "/unused", "total": 1,
        "solved": 0, "accepted": 0, "routing_phase": "COMPLETE",
        "acceptance_policy": {"required": True,
            "review_task_schema": current._REVIEW_TASK_SCHEMA,
            "review_schema": current._AI_REVIEW_SCHEMA},
        "results": [{"id": "neutral", "ok": False, "candidate_ready": False,
            "accepted": False, "candidate_origin": "NONE", "awaiting_ai": False,
            "entry": receipt["entry_step"], "exit": receipt["verify_through"],
            "evidence": receipt["requested_evidence"], "delivery_route": "ip",
            "routing_verdict": {"nature": "spec_generation", "route_receipt": receipt},
            "route_receipt": receipt, "public_original_input": public,
            "runner_invocation": duplicate.invocation, "runner_diagnostics": diagnostic}]})
    current._atomic_write_json(run / current._ACCEPTANCE_REPORT, {
        "schema": current._ACCEPTANCE_SCHEMA, "status": "PENDING", "accepted": 0,
        "accepted_ids": [], "total": 1})
    return run, project, original, duplicate


def _orphan_projection_paths(run):
    return [run / name for name in ("solve_report.json", current._ACCEPTANCE_REPORT,
        current._BACKUP_WORKLIST, current._REVIEW_WORKLIST,
        current._REPAIR_WORKLIST, current._ENHANCEMENT_WORKLIST)]


def test_normal_resume_recovers_native_waive_handoff_without_rerun(
        retained_orphan, monkeypatch):
    run, project, original, duplicate = retained_orphan
    def no_runner(*args, **kwargs):
        pytest.fail("retained handoff recovery must not rerun a native producer")
    monkeypatch.setattr(current._RunnerBudget, "run", no_runner)
    before = {p: p.read_bytes() for p in
              [Path(original.receipt_path), Path(duplicate.receipt_path)]}
    with restore_bytes(_orphan_projection_paths(run)):
        rc = current.cmd_resume("rtllm", "/unused", str(run))
        row = current._read_json_regular(run / "solve_report.json")["results"][0]
        assert row["candidate_origin"] == "AI_BACKUP_PENDING", row
        assert rc == 2
        assert row["accepted"] is False and row["candidate_ready"] is False
        assert row["runner_invocation"]["invocation_id"] == original.invocation_id
        assert row["retained_handoff_recovery"]["observed_runner_invocation"] == duplicate.invocation
        tasks = current._read_jsonl(run / current._BACKUP_WORKLIST)
        assert len(tasks) == 1 and tasks[0]["id"] == "neutral"
        assert tasks[0]["handoff_source"] == "rtl_gen_waive"
        assert tasks[0]["input_authority"] == "original"
        assert current.cmd_resume("rtllm", "/unused", str(run)) == 2
        assert current._read_jsonl(run / current._BACKUP_WORKLIST) == tasks
        assert current._read_jsonl(run / current._REVIEW_WORKLIST) == []
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("damage", ["input", "report", "hash", "route", "source",
                                   "ambiguous", "published", "late_admission", "missing_manifest", "config"])
def test_normal_resume_retained_handoff_mismatches_remain_blocked(
        retained_orphan, monkeypatch, damage):
    run, project, original, duplicate = retained_orphan
    monkeypatch.setattr(current._RunnerBudget, "run",
        lambda *args, **kwargs: pytest.fail("mismatched retained evidence must not launch"))
    report = project / "reports/orchestrator/phase2_one_shot.json"
    prompt = project / "input/phase1_prompt.md"
    producer = Path(original.invocation["reports_after"][report.name]["runner_binding"]["producer"]["path"])
    receipt = Path(original.receipt_path)
    manifest = project / "input/flow109-manifest.json"
    import canonical_run_admission as admission
    ledger = admission.ledger_path(project)
    extra = None
    with restore_bytes([*_orphan_projection_paths(run), prompt, report, producer,
                        receipt, manifest, ledger]):
        try:
            if damage == "input":
                prompt.write_text(prompt.read_text() + "A changed public requirement.\n")
            elif damage == "report":
                report.write_text(report.read_text() + "\n")
            elif damage == "hash":
                document = current._read_json_regular(receipt)
                document["reports_after"][report.name]["sha256"] = "0" * 64
                receipt.write_text(json.dumps(document))
            elif damage == "route":
                solve = current._read_json_regular(run / "solve_report.json")
                solve["results"][0]["exit"] = "8"
                current._atomic_write_json(run / "solve_report.json", solve)
            elif damage == "source":
                producer.write_bytes(producer.read_bytes() + b"\n# changed neutral producer\n")
            elif damage == "ambiguous":
                extra = receipt.with_name("ambiguous.json")
                extra.write_bytes(receipt.read_bytes())
            elif damage == "late_admission":
                from datetime import datetime, timezone
                rows = current._read_jsonl(ledger)
                for row in rows:
                    row["admitted_at"] = datetime.fromtimestamp(
                        original.invocation["finished_ns"] / 1e9 + 10,
                        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                current._write_jsonl(ledger, rows)
            elif damage == "missing_manifest":
                manifest.unlink()
            elif damage == "config":
                extra = project / "phase3/librelane_switch.json"
                assert not extra.exists()
                extra.parent.mkdir(exist_ok=True)
                extra.write_text('{"steps":{"2":"direct"}}')
            else:
                extra = run / "responses/neutral.json"
                extra.parent.mkdir(exist_ok=True)
                extra.write_text('{}')
            assert current.cmd_resume("rtllm", "/unused", str(run)) != 0
            row = current._read_json_regular(run / "solve_report.json")["results"][0]
            assert row["candidate_origin"] == "NONE", row
            assert row["retained_handoff_recovery"]["status"] == "BLOCKED", row
            assert row["accepted"] is False
            assert current._read_jsonl(run / current._BACKUP_WORKLIST) == []
            if damage == "missing_manifest":
                assert not manifest.exists(), "recovery must never recreate missing input"
        finally:
            if extra is not None:
                extra.unlink()


@pytest.mark.parametrize("damage", [
    "changed_producer", "material", "config", "wrong_reason", "argv",
    "source", "log", "wrapper_snapshot", "phase2_snapshot", "latest",
])
def test_duplicate_retention_reverse_guards(ordinary_duplicate, damage):
    root, project, argv, measured, duplicate = ordinary_duplicate
    assert not current._stored_runner_diagnostics(measured.invocation).get("reason")
    later_path = Path(duplicate.receipt_path)
    later = json.loads(later_path.read_text())
    latest = project / "reports/orchestrator/runner_invocations/latest.json"
    producer = Path(measured.invocation["reports_after"]["phase2_one_shot.json"]["runner_binding"]["producer"]["path"])
    assert producer.is_relative_to(root), "only the neutral retained producer may be mutated"
    prompt, config = project / "input/phase1_prompt.md", project / "phase3/librelane_switch.json"
    stderr_path = Path(later["stderr_path"])
    with restore_bytes([later_path, latest, producer, prompt, config, stderr_path]):
        if damage == "changed_producer":
            producer.write_bytes(producer.read_bytes() + b"\n# neutral retained source drift\n")
        elif damage == "material":
            prompt.write_text(prompt.read_text() + "Changed public input.\n")
        elif damage == "config":
            config.write_text('{"steps":{"2":"librelane"}}')
        elif damage == "wrong_reason":
            later["stderr"] = later["stderr"].replace("DUPLICATE_NO_NEW_EVIDENCE", "TOOL_UNAVAILABLE")
            stderr_path.write_text(later["stderr"])
            later["stderr_sha256"] = current._sha256_text(later["stderr"])
        elif damage == "argv":
            later["argv"].append("--other-window")
        elif damage == "source":
            later["source_after"]["runner"]["sha256"] = "0" * 64
        elif damage == "log":
            stderr_path.write_text(later["stderr"] + "unexpected transport failure\n")
        elif damage in {"wrapper_snapshot", "phase2_snapshot"}:
            name = "vibe_ic_one_shot.json" if damage == "wrapper_snapshot" else "phase2_one_shot.json"
            later["reports_after"][name]["sha256"] = "0" * 64
        else:
            value = json.loads(latest.read_text())
            value["invocation_id"] = "0" * 32
            latest.write_text(json.dumps(value))
        later_path.write_text(json.dumps(later))
        rejected = current._stored_runner_diagnostics(measured.invocation)
        assert rejected.get("reason"), (damage, rejected)
    assert not current._stored_runner_diagnostics(measured.invocation).get("reason")


@pytest.mark.parametrize("case", ["default_output", "wrong_hash", "input_and_output", "admitted_output"])
def test_duplicate_retention_preserves_existing_repair_delta_boundary(ordinary_duplicate, case):
    root, project, argv, measured, duplicate = ordinary_duplicate
    rtl, prompt = project / "phase2/stage1/rtl/straight_link.v", project / "input/phase1_prompt.md"
    with restore_bytes([rtl, prompt]):
        rtl.write_bytes(rtl.read_bytes() + b"\n// independently admitted neutral authored delta\n")
        new_hash = current._runner_material_snapshot(project)["output_rtl_sha256"]
        kwargs = {} if case == "default_output" else {
            "allow_repaired_output": True,
            "repaired_output_sha256": "0" * 64 if case == "wrong_hash" else new_hash}
        if case == "input_and_output":
            prompt.write_text(prompt.read_text() + "A new requirement was not admitted.\n")
        diagnostic = current._stored_runner_diagnostics(measured.invocation, **kwargs)
        if case == "admitted_output":
            assert diagnostic["status"] == "REPORTS_AVAILABLE", diagnostic
            assert diagnostic["invocation_id"] == measured.invocation_id
            assert measured.invocation["output_rtl_sha256"] != new_hash
        else:
            assert diagnostic.get("reason"), diagnostic


@pytest.mark.parametrize("case", ["unknown_image", "different_image"])
def test_duplicate_scene_requires_actual_known_image(ordinary_duplicate, case):
    root, project, argv, measured, duplicate = ordinary_duplicate
    wrapper = json.loads((project / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert current._stored_duplicate_scene(measured.invocation, duplicate.invocation, wrapper, project)
    image = wrapper["container_image"]
    if case == "unknown_image":
        image["image_ref"] = "IMAGE_UNAVAILABLE"
    else:
        image["image_ref"] = "neutral.invalid/tool@sha256:" + "0" * 64
    assert current._stored_duplicate_scene(measured.invocation, duplicate.invocation, wrapper, project) is None


def test_real_new_failing_measurement_cannot_be_replaced_by_old_pass(ordinary_duplicate):
    # Last consumer of this private project: a real new measurement supersedes
    # its old reports. It is deliberately left as FAIL, not restored to PASS.
    root, project, argv, measured, duplicate = ordinary_duplicate
    assert not current._stored_runner_diagnostics(measured.invocation).get("reason")
    old_report = project / "reports/orchestrator/phase2_one_shot.json"
    (root / "original-measured-phase2.json").write_bytes(old_report.read_bytes())
    rtl = project / "phase2/stage1/rtl/straight_link.v"
    rtl.write_text("module straight_link(input a,output y); endmodule\n")
    actual = current._RunnerBudget(1, 1, 1).run(argv)
    assert not actual.error, actual.stderr
    report = json.loads(old_report.read_text())
    assert next(row for row in report["steps"] if row["name"] == "rtl_validate")["status"] == "FAIL"
    import flow_phase_attribution as fpa
    ledger = current._required_gate_ledger({"exit": "2", "phases": {
        "phase3_verifying": fpa.phase3_verifying(report, None)}})
    assert ledger["eligibility"] == "INELIGIBLE", ledger
    new_hash = current._runner_material_snapshot(project)["output_rtl_sha256"]
    diagnostic = current._stored_runner_diagnostics(
        measured.invocation, allow_repaired_output=True, repaired_output_sha256=new_hash)
    assert diagnostic.get("reason"), diagnostic
    (root / "new-failing-measurement.json").write_text(json.dumps({
        "invocation_id": actual.invocation_id, "diagnostic": diagnostic,
        "required_gate_ledger": ledger}, indent=2))
