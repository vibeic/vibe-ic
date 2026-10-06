"""Focused controls for the ordinary A1-A5/A9 Registry producer lane."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent))
import execution_modes as em
import execution_policy as policy
import execution_adapters_analog_front as front
import execution_analog_front_worker as worker
import analog_one_shot_runner as runner
from programs.tests._analog_producer_fixture import block, make_project, stage_custom_pdk
from programs.tests._route_fixture import stage_owner_route


def _project(root: Path, names=("alpha", "beta")) -> Path:
    blocks = [block(name, "amplifier", specs=[{
        "name": "vout", "target": 1.0, "units": "V", "source": "doc_alpha.md"}])
        for name in names]
    make_project(root, blocks)
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"electrical_specs": []}))
    return root


def test_front_registry_census_is_exactly_six_single_source_rows(tmp_path):
    project = _project(tmp_path / "project")
    registry = em.Registry()
    front.register_front_adapters(registry, project=project,
                                  source_sha=em._git_source_authority(
                                      __import__("subprocess").check_output(
                                          ["git", "-C", str(PROGRAMS.parents[3]), "rev-parse", "HEAD"],
                                          text=True).strip())[0])
    assert tuple(front.FRONT_IDS) == ("A1", "A2", "A3", "A4", "A5", "A9")
    assert {step: len(registry.adapters(step)) for step in front.FRONT_IDS} == {
        step: 1 for step in front.FRONT_IDS}
    for step in front.FRONT_IDS:
        arm = registry.adapters(step)[0]
        assert arm.arm_id == "analog-front-" + step.lower()
        assert arm.tool_id == "analog-front-worker"
        assert "native readiness not implied" in arm.qualification_evidence
    assert "phase3/analog/*/hw_measurements.json" in \
        registry.adapters("A9")[0].input_contract
    assert all(not registry.adapters(step) for step in ("M1", "M2", "M3", "M4"))


def test_explicit_skip_analog_omits_registration_without_declaration(tmp_path):
    """The routed digital-only path must not invent an empty declaration."""
    project = tmp_path / "digital"
    project.mkdir()
    registry = em.Registry()
    policy._register_analog_adapters(
        registry, project, "not-consumed-on-explicit-skip",
        {"skip_analog": True})
    assert all(not registry.adapters(step) for step in
               (*front.FRONT_IDS, *front.analog.STEP_IDS))
    assert not (project / "phase1/analog/analog_block_list.json").exists()


def test_missing_declaration_without_explicit_skip_remains_refused(tmp_path):
    """Missing Phase-1 evidence cannot silently become a digital-only route."""
    project = tmp_path / "unknown"
    project.mkdir()
    with pytest.raises(em.Refusal, match="ANALOG_DECLARATION_REQUIRED"):
        front.register_front_adapters(
            em.Registry(), project=project,
            source_sha="not-reached-before-declaration-refusal")


@pytest.mark.parametrize("mode", ["default", "ultra"])
@pytest.mark.parametrize("window", [("15", "22"), ("37", "37")])
def test_phase3_backend_binding_carries_current_image_and_pdk_root(
        tmp_path, monkeypatch, mode, window):
    """Exercise CLI-to-producer parameters, including automatic PDK selection."""
    import phase3_one_shot_runner as backend
    import execution_backend_producers as producers
    import librelane_contract as contract

    project = tmp_path / "backend"
    project.mkdir()
    pdk = SimpleNamespace(name="synthetic_process")
    image = "registry.invalid/eda@sha256:" + "a" * 64
    root = str(tmp_path / "pdks")
    resolved = []
    observed = {}

    class Bound(Exception):
        pass

    def resolve_root(subject, name, *, image):
        resolved.append((subject, name, image))
        return {"path": root}

    def bootstrap(subject, *, parameters):
        # Invoke the real first backend consumer. Before the repair it refuses
        # image_id,pdk_root, so the value below is REFUSED rather than BOUND.
        try:
            producers._parameters(subject, parameters)
        except em.Refusal as exc:
            observed.update(status="REFUSED", detail=str(exc))
        else:
            observed.update(status="BOUND", parameters=parameters)
        raise Bound

    monkeypatch.setattr(policy, "configure", lambda args: None)
    monkeypatch.setattr(policy, "request", lambda: {"mode": mode})
    monkeypatch.setenv(policy._CAPABILITY_FD_ENV, "test-bootstrap-intercepted")
    monkeypatch.setattr(policy, "bootstrap", bootstrap)
    monkeypatch.setattr(backend, "_delivery_admission_refusal", lambda p: None)
    monkeypatch.setattr(backend, "_librelane_admission_facts", lambda p: {})
    monkeypatch.setattr(backend._canonical_admission, "admit_span",
                        lambda *args: SimpleNamespace(admitted=True))
    monkeypatch.setattr(backend, "_detect_pdk", lambda *args: pdk)
    monkeypatch.setattr(contract, "resolve_image", lambda subject: image)
    monkeypatch.setattr(contract, "pdk_root_resolution", resolve_root)
    monkeypatch.setattr(sys, "argv", ["phase3_one_shot_runner.py", str(project),
        "--execution-mode", mode, "--pdk", "auto", "--top-name", "unit_top",
        "--entry-step", window[0], "--exit-step", window[1]])
    with pytest.raises(Bound):
        backend.main()
    assert observed["status"] == "BOUND", observed
    assert observed["parameters"]["image_id"] == image
    assert observed["parameters"]["pdk_root"] == root
    assert observed["parameters"]["pdk_name"] == pdk.name
    assert resolved == [(project, pdk.name, image)]


@pytest.mark.parametrize("cause", ["image", "pdk_root"])
def test_phase3_backend_binding_preserves_runtime_refusal(tmp_path, monkeypatch, cause):
    import phase3_one_shot_runner as backend
    import librelane_contract as contract

    def refused(*args, **kwargs):
        raise contract.Refusal("LL_RUNTIME_UNAVAILABLE", cause)

    monkeypatch.setattr(contract, "resolve_image",
                        refused if cause == "image" else lambda p: "test-image")
    monkeypatch.setattr(contract, "pdk_root_resolution", refused)
    with pytest.raises(contract.Refusal, match="LL_RUNTIME_UNAVAILABLE"):
        backend._backend_parameter_values(tmp_path, SimpleNamespace(name="synthetic_process"))


@pytest.mark.parametrize("mode", ["default", "ultra"])
@pytest.mark.parametrize("window", [None, ("15", "22"), ("37", "37")])
def test_backend_entry_does_not_register_an_analog_frontend(
        tmp_path, monkeypatch, mode, window):
    """Exercise main's registration call without running an unrelated A-track."""
    import phase3_one_shot_runner as backend

    project = tmp_path / "backend"
    project.mkdir()
    registry = em.Registry()
    called = []

    def bootstrap(subject, *, parameters):
        policy._register_analog_adapters(
            registry, subject, "no-analog-source-needed", parameters)
        called.append(subject)

    # This control owns only entry/registration. Admission is already granted;
    # no PDK prevents any synthesis, stream-out or physical verdict afterwards.
    monkeypatch.setattr(policy, "configure", lambda args: None)
    monkeypatch.setattr(policy, "bootstrap", bootstrap)
    monkeypatch.setattr(backend, "_delivery_admission_refusal", lambda p: None)
    monkeypatch.setattr(backend, "_librelane_admission_facts", lambda p: {})
    monkeypatch.setattr(backend._canonical_admission, "admit_span",
                        lambda *args: SimpleNamespace(admitted=True))
    monkeypatch.setattr(backend, "_detect_pdk", lambda *args: None)
    argv = ["phase3_one_shot_runner.py", str(project),
            "--execution-mode", mode]
    if window:
        argv += ["--entry-step", window[0], "--exit-step", window[1]]
    monkeypatch.setattr(sys, "argv", argv)
    assert backend.main() == 0
    assert called == [project]
    assert all(not registry.adapters(step) for step in
               (*front.FRONT_IDS, *front.analog.STEP_IDS))
    assert not (project / "phase1/analog/analog_block_list.json").exists()


def test_two_block_worker_runs_existing_a1_producer_in_declared_order(tmp_path):
    project = tmp_path / "project"
    blocks = [block(name, "ldo", specs=[{
        "name": "Vout", "target": 1.8, "unit": "V", "source": "doc_alpha.md"}, {
        "name": "Vref", "target": 0.9, "unit": "V", "source": "doc_alpha.md"}])
        for name in ("vreg_alpha", "vreg_beta")]
    make_project(project, blocks)
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"electrical_specs": []}))
    stage_custom_pdk(project, "synthetic-test-family")
    stage_owner_route(project, "ic")
    from programs.tests import test_execution_receipt_chain as live
    live_count = len(live._launchers)
    saved = {name: os.environ.get(name) for name in
             (policy.ENV, policy._CAPABILITY_FD_ENV, "VIBEIC_EXECUTION_AUTH_SOCKET")}
    previous_runtime = policy._ordinary_runtime
    policy._ordinary_runtime = None
    try:
        live.real_entry(path="IC", execution_mode="ultra", project=project)
        args = SimpleNamespace(execution_mode="ultra", execution_cpus=None,
            execution_ram_mb=None, execution_workers=None, execution_licenses=None,
            execution_choice=None, execution_choice_wait_s=None,
            execution_request_digest=None, execution_request_receipt=None)
        policy.configure(args)
        runtime = policy.bootstrap(project)
        assert runtime is not None
        expected = {
            "A1": ("analog_a1_spec_emit.py", "spec.json"),
            "A2": ("analog_a2_topology_emit.py", "topology.md"),
            "A3": ("analog_a3_netlist_emit.py", "vreg_alpha.sp"),
        }
        for step, (producer, artifact) in expected.items():
            pending = policy.dispatch_fixed_step(project, step)
            context = runtime["contexts"][step]
            bound_inputs = set(context.binding()["inputs"])
            if step in ("A2", "A3"):
                assert {f"phase3/analog/{name}/spec.json"
                        for name in ("vreg_alpha", "vreg_beta")} <= bound_inputs
            if step == "A3":
                assert {f"phase3/analog/{name}/topology.json"
                        for name in ("vreg_alpha", "vreg_beta")} <= bound_inputs
            if pending["status"] != "AWAITING_AI_SELECTION":
                run, _ = runtime["runs"][step]
                arm_id = "analog-front-" + step.lower()
                arm_root = run / arm_id
                diagnostics = {"result": pending}
                for path in (arm_root / "receipt.json",
                             arm_root / "outputs/front-producer.json"):
                    if path.is_file():
                        diagnostics[path.name] = json.loads(path.read_text())
                diagnostics["observed_gates"] = {
                    path.name: json.loads(path.read_text())
                    for path in (arm_root / "outputs/observed-gates").glob("*.json")
                    if path.is_file()}
                pytest.fail(f"{step} did not produce selectable current evidence: " +
                            json.dumps(diagnostics, sort_keys=True))
            run, _ = runtime["runs"][step]
            arm_id = "analog-front-" + step.lower()
            receipt = json.loads((run / arm_id / "outputs/front-producer.json").read_text())
            assert receipt["blocks"] == ["vreg_alpha", "vreg_beta"]
            assert receipt["verdict"] == "PASS"
            assert [row["status"] for row in receipt["rows"]] == ["PASS", "PASS"]
            assert [row["producer"] for row in receipt["rows"]] == [producer, producer]
            assert receipt["producer_pid"] > 0
            choice = {"arm_id": arm_id,
                "binding": context.binding(),
                "receipt_sha256": em.digest(run / arm_id / "receipt.json"),
                "reviewer": "test AI decision consumer",
                "rationale": "Current producer and gate evidence for the ordered declared blocks."}
            adopted = policy.dispatch_fixed_step(project, step, choice=choice)
            assert adopted["status"] == "ADOPTED", (step, adopted)
            verified = runtime["controller"].verify_adoption(context, run)
            generation = verified["selected_generation"]
            assert generation["outputs"]
            for relative, digest in generation["outputs"].items():
                current = project / relative
                assert current.is_file() and em.digest(current) == digest
            output_name = f"phase3/analog/vreg_alpha/{artifact}"
            assert output_name in generation["outputs"]
    finally:
        policy._ordinary_runtime = previous_runtime
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for proc, fd, channel in live._launchers[live_count:]:
            channel.close()
            proc.wait(timeout=10)
            if proc.stderr:
                proc.stderr.close()
            try:
                os.close(fd)
            except OSError:
                pass
        del live._launchers[live_count:]


def test_measured_fail_precedes_missing_sibling_and_missing_outputs_stay_nm(tmp_path, monkeypatch):
    project = _project(tmp_path / "input")
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({"step_id": "A4"}))
    calls = []

    def fail_then_missing(root, row, name, args=None):
        calls.append(row["name"])
        if row["name"] == "alpha":
            target = root / "phase3/analog/alpha/corner_results.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"verdict":"FAIL"}\n')
            return SimpleNamespace(status="FAIL", detail="measured corner failure",
                                    reason_class="", output_files=[str(target.relative_to(root))])
        return SimpleNamespace(status="NOT_MEASURED", detail="simulator absent",
                               reason_class="", output_files=[])

    monkeypatch.setattr(runner, "step_for_block", fail_then_missing)
    result = worker.execute("A4", project, tmp_path / "fail-output")
    assert calls == ["alpha", "beta"]
    assert result["verdict"] == "FAIL"
    assert result["block_outputs"]["beta"] == []

    monkeypatch.setattr(runner, "step_for_block", lambda *a, **k:
                        SimpleNamespace(status="NOT_MEASURED", detail="tool absent",
                                        reason_class="", output_files=[]))
    absent = worker.execute("A4", project, tmp_path / "nm-output")
    assert absent["verdict"] == "NOT_MEASURED"
    assert not absent["outputs"]


def test_default_bootstrap_still_returns_without_front_registry(monkeypatch, tmp_path):
    monkeypatch.delenv(policy.ENV, raising=False)
    assert policy.bootstrap(tmp_path) is None


def test_validator_refuses_other_block_replay_and_edited_output(tmp_path):
    root = tmp_path / "arm"
    root.mkdir()
    binding = {"step_id": "A1", "required_gates": [],
               "objective": {"blocks": ["alpha", "beta"]}}
    alpha = root / "phase3/analog/alpha/spec.json"
    alpha.parent.mkdir(parents=True)
    alpha.write_text("alpha current\n")
    beta = root / "phase3/analog/beta/spec.json"
    beta.parent.mkdir(parents=True)
    beta.write_text("beta current\n")
    outputs = {str(path.relative_to(root)): em.digest(path) for path in (alpha, beta)}
    receipt = dict(binding=binding, step_id="A1", blocks=["alpha", "beta"],
        rows=[{"block": "alpha"}, {"block": "beta"}], outputs=outputs,
        block_outputs={"alpha": ["phase3/analog/alpha/spec.json"],
                       "beta": ["phase3/analog/beta/spec.json"]},
        verdict="PASS", detail="")
    (root / "front-producer.json").write_text(json.dumps(receipt))
    evidence = front.validate(root, binding)
    assert evidence.verdict == "PASS"
    beta.write_text("edited\n")
    assert front.validate(root, binding).verdict == "NOT_MEASURED"
    receipt["block_outputs"]["beta"] = ["phase3/analog/alpha/spec.json"]
    beta.write_text("beta current\n")
    receipt["outputs"]["phase3/analog/beta/spec.json"] = em.digest(beta)
    (root / "front-producer.json").write_text(json.dumps(receipt))
    assert front.validate(root, binding).verdict == "NOT_MEASURED"


def _a9_gate_evidence(root: Path, *, hardware: bool, optional_status: str):
    root.mkdir(parents=True, exist_ok=True)
    inputs = {}
    if hardware:
        measurement = root / "current-input/phase3/analog/alpha/hw_measurements.json"
        measurement.parent.mkdir(parents=True)
        measurement.write_text('{"measurement":"current"}\n')
        inputs["phase3/analog/alpha/hw_measurements.json"] = em.digest(measurement)
    gate_names = [row["command"].split()[0] for row in front.analog.gate_specs("A9")
                  if row["kind"] != "advisory_program_exit_zero"]
    binding = {"step_id": "A9", "required_gates": gate_names,
        "objective": {"blocks": ["alpha"]}, "inputs": inputs}
    product = root / "phase3/analog/alpha/a9_result.json"
    product.parent.mkdir(parents=True)
    product.write_text('{"result":"current"}\n')
    relative = str(product.relative_to(root))
    receipt = {"binding": binding, "step_id": "A9", "blocks": ["alpha"],
        "rows": [{"block": "alpha"}], "outputs": {relative: em.digest(product)},
        "block_outputs": {"alpha": [relative]}, "verdict": "PASS", "detail": ""}
    (root / "front-producer.json").write_text(json.dumps(receipt))
    gate_dir = root / "observed-gates"
    gate_dir.mkdir()
    for gate in gate_names:
        status = optional_status if gate == "analog_hw_spice_correlation_check" else "PASS"
        report = {"verdict": status}
        rc = 0 if status == "PASS" else 1 if status == "FAIL" else 2
        (gate_dir / f"{gate}.json").write_text(json.dumps({
            "binding": binding, "argv": [f"{gate}.py"], "rc": rc, "report": report}))
    return binding, gate_dir


def test_a9_optional_hardware_gate_absent_allows_simulation_only_qualification(tmp_path):
    binding, _ = _a9_gate_evidence(tmp_path / "arm", hardware=False,
                                   optional_status="NOT_MEASURED")
    evidence = front.validate(tmp_path / "arm", binding)
    assert evidence.verdict == "PASS"
    assert evidence.gates["analog_hw_spice_correlation_check"] == "NOT_APPLICABLE"


def test_a9_optional_hardware_gate_present_requires_current_pass(tmp_path):
    binding, _ = _a9_gate_evidence(tmp_path / "arm", hardware=True,
                                   optional_status="PASS")
    evidence = front.validate(tmp_path / "arm", binding)
    assert evidence.verdict == "PASS"
    assert evidence.gates["analog_hw_spice_correlation_check"] == "PASS"


def test_a9_optional_hardware_gate_present_fail_dominates_and_missing_record_is_nm(tmp_path):
    root = tmp_path / "arm"
    binding, gate_dir = _a9_gate_evidence(root, hardware=True, optional_status="FAIL")
    failed = front.validate(root, binding)
    assert failed.verdict == "FAIL"
    assert failed.gates["analog_hw_spice_correlation_check"] == "FAIL"
    (gate_dir / "analog_hw_spice_correlation_check.json").unlink()
    missing = front.validate(root, binding)
    assert missing.verdict == "NOT_MEASURED"
    assert missing.gates["analog_hw_spice_correlation_check"] == "NOT_MEASURED"
