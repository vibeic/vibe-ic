"""Focused source controls for the canonical mixed Registry seam."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import execution_adapters_mixed as mixed
import execution_mixed_worker as worker
import vibe_ic_one_shot_runner as runner

from programs.tests import test_execution_modes as core_helpers
from programs.tests import test_execution_receipt_chain as live_issuer

isolated_transport = live_issuer.isolated_transport


def test_registry_has_one_runnable_ordinary_candidate_per_canonical_mixed_row():
    import execution_modes as em
    registry = mixed.register_mixed_adapters(em.Registry(), source_sha="ignored", project=Path.cwd(),
                                               parameters={"top_name": "chip_top"})
    flow_rows = {str(row["id"]): row for row in __import__("_flow_yaml").load()["steps"]}
    assert tuple(mixed.IDS) == ("M1", "M2", "M3", "M4")
    for sid in mixed.IDS:
        candidates = registry.adapters(sid)
        assert len(candidates) == 1
        assert candidates[0].arm_id == f"{sid}_ordinary_producer"
        assert candidates[0].qualified is True
        assert candidates[0].tool_id == "vibeic"
        assert candidates[0].role == "producer"
        assert set(candidates[0].output_contract) == set(flow_rows[sid]["required_outputs"])
    assert set(mixed.M2_SIDECAR_OUTPUTS) <= set(registry.adapters("M2")[0].required_outputs)


def test_shared_bootstrap_keeps_typed_step9_pdk_out_of_mixed_json():
    class Registry:
        def __init__(self):
            self.rows = []

        def register(self, adapter):
            self.rows.append(adapter)

        def adapters(self, step_id):
            return [row for row in self.rows if row.step_id == step_id]

    registry = mixed.register_mixed_adapters(
        Registry(), source_sha="ignored", project=Path.cwd(),
        parameters={"top": "top", "container": "LOCAL",
                    "pdk": SimpleNamespace(name="gf180mcuD"),
                    "pdk_name": "gf180mcuD"})
    argv = registry.adapters("M2")[0].components[0].argv
    params = json.loads(argv[argv.index("--params-json") + 1])
    assert params == {
        "container": "LOCAL", "pdk": "gf180mcuD",
        "project_subject": str(Path.cwd().resolve()), "top_name": "top"}


def test_m4_contract_binds_top_pv_declared_current_inputs(tmp_path):
    import execution_modes as em
    project = tmp_path / "project"
    (project / "input/mixed_signal").mkdir(parents=True)
    request = project / "input/mixed_signal/top_pv.json"
    request.write_text(json.dumps({"input_sha256": {
        "input/pdk/models/device.spice": "a" * 64,
        "phase3/analog/block/hardmacro.gds": "b" * 64,
        "../escape": "c" * 64,
        "/etc/passwd": "d" * 64}}))
    device = project / "input/pdk/models/device.spice"
    device.parent.mkdir(parents=True)
    device.write_text(".model device nmos\n")
    hardmacro = project / "phase3/analog/block/hardmacro.gds"
    hardmacro.parent.mkdir(parents=True)
    hardmacro.write_bytes(b"GDS fixture")
    candidate = mixed.register_mixed_adapters(
        em.Registry(), source_sha="ignored", project=project).adapters("M4")[0]
    assert "input/pdk/models/device.spice" in candidate.input_contract
    assert "phase3/analog/block/hardmacro.gds" in candidate.input_contract
    assert "phase3/librelane_switch.json" in candidate.input_contract
    assert "input/submission_template/tapeout_declaration.json" in candidate.input_contract
    assert "../escape" not in candidate.input_contract
    assert "/etc/passwd" not in candidate.input_contract


@pytest.mark.parametrize("sid", ("M1", "M2", "M3", "M4"))
def test_normal_fixed_caller_routes_each_row_through_shared_dispatch(sid):
    source = Path(runner.__file__).read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "_controller_mixed_step"
             and any(isinstance(arg, ast.Constant) and arg.value == sid for arg in node.args)]
    assert len(calls) == 1
    assert "dispatch_fixed_step(project, step_id)" in source
    assert "if dispatched is None:" in source
    assert "mixed_signal_" + {"M1": "top_lvs_run", "M2": "power_domain_run",
                             "M3": "m3_run", "M4": "signoff_run"}[sid] + ".py" in source


@pytest.mark.parametrize(("status", "expected_rc", "expected_verdict"), (
    ("ADOPTED", 0, "PASS"), ("FAIL", 1, "FAIL"), ("NOT_MEASURED", 2, "NOT_MEASURED"),
    ("AWAITING_AI_SELECTION", 2, "NOT_READY"),
))
def test_controller_result_preserves_status_in_fixed_runner(status, expected_rc, expected_verdict,
                                                             tmp_path):
    class Execution:
        def dispatch_fixed_step(self, project, step_id):
            assert project == tmp_path
            assert step_id == "M3"
            return {"status": status, "step_id": step_id, "selected": "M3_ordinary_producer"}

    path = tmp_path / "reports/audit.json"
    rc, report = runner._controller_mixed_step(Execution(), tmp_path, "M3", path)
    assert rc == expected_rc
    assert report["verdict"] == expected_verdict
    assert json.loads(path.read_text()) == report


def test_default_mode_keeps_direct_producer_fallback():
    class Execution:
        def dispatch_fixed_step(self, *_args):
            return None

    assert runner._controller_mixed_step(Execution(), Path("."), "M1", Path("unused")) is None


def test_normal_caller_shared_controller_adopts_and_rereads_current_bytes(tmp_path):
    """Exercise real Controller worker/choice/adoption using the neutral text fixture."""
    import execution_modes as em
    from execution_backend_snapshot import Journal
    from programs.tests import test_execution_modes as neutral

    project = tmp_path / "canonical-project"
    project.mkdir()
    context = neutral.context(project)
    controller = neutral.controller(neutral.adapter("a"))
    run_root = project / "controller-run"

    class Execution:
        def dispatch_fixed_step(self, current_project, step_id):
            assert current_project == project
            assert step_id == "M3"
            result = controller.run(context, run_root, "ultra-mode")
            assert result["status"] == "AWAITING_AI_SELECTION"
            result = controller.adopt(context, run_root, neutral.choice(context, run_root))
            result = controller.verify_adoption(context, run_root)
            generation = result["selected_generation"]
            journal = Journal(project)
            for name in ("value.txt", "measurement.json"):
                source = Path(generation["directory"]) / name
                journal.write(name, source.read_bytes())
            controller.verify_adoption(context, run_root)
            assert (project / "value.txt").read_text() == "ONE INPUT\n"
            assert em.digest(project / "value.txt") == result["selected_generation"]["outputs"]["value.txt"]
            return dict(status="ADOPTED", selected="a", current_reread=True)

    rc, report = runner._controller_mixed_step(Execution(), project, "M3",
                                                project / "reports/m3-controller.json")
    assert rc == 0
    assert report["controller_result"]["current_reread"] is True


def test_m3_measured_fail_survives_unmeasured_companion_and_output_edit(monkeypatch, tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    binding = {"step_id": "M3", "objective": {"top_name": "chip_top",
                "container": "vibeic-eda", "pdk": "auto", "project_subject": str(tmp_path.resolve())},
               "required_gates": ["mixed_signal_cosim_check", "mixed_signal_interface_si_check"],
               "inputs": {"phase3/mixed_signal/top_merged.gds": "a" * 64}}
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps(binding))

    def fake_run(program, _args, project):
        if program == mixed.PRODUCERS["M3"]:
            for rel in mixed.OUTPUTS["M3"]:
                path = project / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"verdict": "FAIL" if rel.endswith("m3_run.json")
                                            else "NOT_MEASURED"}))
            return {"program": program, "argv": [program], "rc": 1,
                    "verdict": "FAIL", "stdout_sha256": "b" * 64,
                    "stderr_sha256": "c" * 64}
        return {"program": program, "argv": [program], "rc": 2,
                "verdict": "NOT_MEASURED", "stdout_sha256": "d" * 64,
                "stderr_sha256": "e" * 64}

    monkeypatch.setattr(worker, "_run", fake_run)
    worker.execute(inputs, outputs, "M3", binding["objective"])
    evidence = mixed.validate(outputs, binding)
    assert evidence.verdict == "FAIL"
    (outputs / mixed.OUTPUTS["M3"][0]).write_text("edited")
    evidence = mixed.validate(outputs, binding)
    assert evidence.verdict == "FAIL"
    assert "OUTPUT_CHANGED" in evidence.detail


def test_wrong_step_binding_refuses_before_producer(monkeypatch, tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "step_id": "M2", "objective": {"top_name": "chip_top", "container": "vibeic-eda",
                                      "pdk": "auto", "project_subject": str(tmp_path.resolve())}}))
    called = []
    monkeypatch.setattr(worker, "_run", lambda *args: called.append(args))
    with pytest.raises(ValueError, match="MIXED_ISSUED_SUBJECT_MISMATCH"):
        worker.execute(inputs, outputs, "M3", {"top_name": "chip_top", "container": "vibeic-eda",
                                               "pdk": "auto", "project_subject": str(tmp_path.resolve())})
    assert not called


def test_issued_project_subject_survives_staging_and_current_m3_reread(tmp_path, monkeypatch):
    """The producer uses issued canonical identity; no receipt rewrite is needed."""
    import shutil
    import mixed_signal_m3_run as m3

    staged = tmp_path / "arm-inputs/project"
    canonical = tmp_path / "canonical-project"
    staged.mkdir(parents=True)
    canonical.mkdir()
    binding = {"step_id": "M3", "objective": {"project_subject": str(canonical.resolve())}}
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps(binding))
    m3.produce(staged, "chip_top")  # source-only fallback; no native execution
    for rel in (*m3.OUTPUTS.values(), m3.RECEIPT):
        target = canonical / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged / rel, target)
    with pytest.raises(m3.Refusal) as exc:
        m3.verify(canonical, "cosim")
    assert exc.value.rule == "EMPTY_SCENARIOS"


def test_direct_gate_run_captures_report_without_native_tools(tmp_path):
    project = tmp_path / "empty-project"
    project.mkdir()
    report = "reports/analog/mixed_signal/direct_cosim_audit.json"
    result = worker._run("mixed_signal_cosim_check", (report,), project)
    assert result["rc"] == 2
    assert result["verdict"] == "NOT_MEASURED"
    assert (project / report).is_file()


def test_nested_gate_expected_command_resolves_python_alias_and_binds_report(tmp_path,
                                                                            monkeypatch):
    from types import SimpleNamespace

    real_python = Path(worker.sys.executable).resolve()
    alias = tmp_path / "python-alias"
    alias.symlink_to(real_python)
    monkeypatch.setattr(mixed, "sys", SimpleNamespace(executable=str(alias)))
    project = str((tmp_path / "outputs/project").resolve())
    report = "reports/analog/mixed_signal/power_domain_native_audit.json"
    expected = [str(real_python), str(mixed.HERE / "mixed_signal_power_domain_run.py"),
                project, "--check-only", "--json", str(Path(project) / report)]
    actual = mixed._nested_gate_argv("mixed_signal_power_domain_run", project,
                                     report, ["--check-only"])
    assert actual == expected
    assert actual[0] != str(alias)


def test_m2_check_only_uses_consumer_argv_and_rejects_stale_pass(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    report = "reports/analog/mixed_signal/power_domain_native_audit.json"
    target = project / report
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"verdict": "PASS"}))
    observed = {}

    class Failed:
        returncode = 2
        stdout = ""
        stderr = "argument error"

    def run(argv, **kwargs):
        observed["argv"] = argv
        return Failed()

    monkeypatch.setattr(worker.subprocess, "run", run)
    result = worker._run("mixed_signal_power_domain_run",
                         ("--check-only", report), project)
    assert observed["argv"] == [sys.executable,
        str(worker.HERE / "mixed_signal_power_domain_run.py"), str(project),
        "--check-only", "--json", str(project / report)]
    assert "--top" not in observed["argv"] and "--container" not in observed["argv"]
    assert result["rc"] == 2 and result["verdict"] == "NOT_MEASURED"
    assert not target.exists()


def _m2_receipt_rebind_fixture(tmp_path):
    import hashlib

    staged = tmp_path / "worker/outputs/project"
    canonical = tmp_path / "canonical-project"
    relatives = (
        "input/pdk/liberty/neutral.lib",
        "phase2/stage2/constraints/boundary.upf",
        "phase3/mixed_signal/top_merged.gds",
        "phase3/stage3/pnr/boundary_pnr.v",
        "phase3/stage3/pnr/routed.def",
    )
    issued_relatives = relatives + ("input/step_0_5ic_answers.json",)
    issued = {}
    for index, relative in enumerate(issued_relatives):
        content = f"issued-input-{index}\n".encode()
        for root in (staged, canonical):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        issued[relative] = hashlib.sha256(content).hexdigest()
    receipt = {
        "schema": "vibeic.mixed_signal.m2.v1",
        "top": "boundary",
        "inputs": {str((staged / rel).resolve()): issued[rel]
                   for rel in relatives},
        "liberties": [str((staged / relatives[0]).resolve())],
    }
    return staged, canonical, issued, receipt


def test_m2_receipt_rebinds_staged_paths_to_exact_canonical_issued_bytes(tmp_path):
    staged, canonical, issued, receipt = _m2_receipt_rebind_fixture(tmp_path)
    rebound = worker.rebind_m2_receipt_inputs(
        receipt, staged, str(canonical.resolve()), str(canonical.resolve()), issued,
        "boundary")
    assert rebound["inputs"] == {
        str((canonical / relative).resolve()): issued[relative]
        for relative in (
            "input/pdk/liberty/neutral.lib",
            "phase2/stage2/constraints/boundary.upf",
            "phase3/mixed_signal/top_merged.gds",
            "phase3/stage3/pnr/boundary_pnr.v",
            "phase3/stage3/pnr/routed.def",
        )
    }
    assert str(canonical / "input/step_0_5ic_answers.json") not in rebound["inputs"]
    assert rebound["liberties"] == [
        str((canonical / "input/pdk/liberty/neutral.lib").resolve())
    ]
    assert all(str(staged.resolve()) in key for key in receipt["inputs"])


def test_m2_receipt_rebind_accepts_complete_issued_set(tmp_path):
    staged, canonical, issued, receipt = _m2_receipt_rebind_fixture(tmp_path)
    # The route/controller answer file is optional in the canonical M2
    # adapter.  With it absent from the issued set, the five producer inputs
    # are the complete issued set and must still rebind.
    issued.pop("input/step_0_5ic_answers.json")
    rebound = worker.rebind_m2_receipt_inputs(
        receipt, staged, str(canonical.resolve()), str(canonical.resolve()), issued,
        "boundary")
    assert rebound["inputs"] == {
        str((canonical / relative).resolve()): digest
        for relative, digest in issued.items()
    }
    assert rebound["liberties"] == [
        str((canonical / "input/pdk/liberty/neutral.lib").resolve())
    ]


@pytest.mark.parametrize("drift", ("outside_path", "digest"))
def test_m2_receipt_rebind_refuses_path_or_digest_drift(tmp_path, drift):
    staged, canonical, issued, receipt = _m2_receipt_rebind_fixture(tmp_path)
    key = next(iter(receipt["inputs"]))
    value = receipt["inputs"].pop(key)
    if drift == "outside_path":
        receipt["inputs"][str(tmp_path / "outside.lib")] = value
    else:
        receipt["inputs"][key] = "0" * 64
    with pytest.raises(ValueError, match="MIXED_M2_"):
        worker.rebind_m2_receipt_inputs(
            receipt, staged, str(canonical.resolve()), str(canonical.resolve()), issued,
            "boundary")


@pytest.mark.parametrize("drift", ("missing_key", "empty_inputs", "empty_issued_inputs",
                                   "unknown_receipt_key", "unsafe_key", "subject"))
def test_m2_receipt_rebind_refuses_incomplete_or_unbound_subject(tmp_path, drift):
    staged, canonical, issued, receipt = _m2_receipt_rebind_fixture(tmp_path)
    key = next(iter(receipt["inputs"]))
    value = receipt["inputs"].pop(key)
    subject = str(canonical.resolve())
    if drift == "missing_key":
        pass
    elif drift == "empty_inputs":
        receipt["inputs"].clear()
    elif drift == "empty_issued_inputs":
        receipt["inputs"][key] = value
        issued = {}
    elif drift == "unknown_receipt_key":
        receipt["inputs"][key] = value
        extra = staged / "extra/current.bin"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"unissued")
        import hashlib
        receipt["inputs"][str(extra.resolve())] = hashlib.sha256(b"unissued").hexdigest()
    elif drift == "unsafe_key":
        receipt["inputs"][str(staged / "../outside.bin")] = value
    else:
        receipt["inputs"][key] = value
        subject = str((tmp_path / "other-project").resolve())
        (tmp_path / "other-project").mkdir()
    expected = (r"^MIXED_M2_ISSUED_INPUTS_INVALID$"
                if drift == "empty_issued_inputs" else r"MIXED_M2_")
    with pytest.raises(ValueError, match=expected):
        worker.rebind_m2_receipt_inputs(receipt, staged, subject,
                                        str(canonical.resolve()), issued, "boundary")


def test_m2_receipt_loader_refuses_duplicate_json_keys(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text('{"inputs":{"/stage/a":"a","/stage/a":"b"}}')
    with pytest.raises(ValueError, match="MIXED_M2_RECEIPT_DUPLICATE_KEY"):
        worker._load_m2_receipt(path)


def _m2_producer_output_fixture(tmp_path):
    import hashlib
    import mixed_signal_power_domain_run as producer

    project = tmp_path / "project"
    expected = {f"{producer.DIR}/{name}" for name in producer.OUTPUTS}
    expected.update(mixed.M2_SIDECAR_OUTPUTS)
    receipt_outputs = {}
    for name in sorted(expected):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ("native-receipt-output:" + name + "\n").encode()
        path.write_bytes(content)
        receipt_outputs[name] = hashlib.sha256(content).hexdigest()
    receipt = {"schema": producer.SCHEMA, "verdict": "PASS", "top": "boundary",
               "outputs": receipt_outputs}
    return project, receipt


@pytest.mark.parametrize("drift", ("missing", "mutated", "extra", "unsafe", "symlink"))
def test_m2_producer_receipt_output_population_fails_closed(tmp_path, drift):
    project, receipt = _m2_producer_output_fixture(tmp_path)
    sidecar = mixed.M2_SIDECAR_OUTPUTS[0]
    if drift == "missing":
        receipt["outputs"].pop(sidecar)
    elif drift == "mutated":
        (project / sidecar).write_bytes(b"mutated-after-receipt")
    elif drift == "extra":
        receipt["outputs"]["reports/analog/mixed_signal/unowned.json"] = "a" * 64
    elif drift == "unsafe":
        receipt["outputs"]["../outside.json"] = "a" * 64
    else:
        target = project / sidecar
        target.unlink()
        outside = tmp_path / "outside.json"
        outside.write_bytes(b"outside")
        target.symlink_to(outside)
    with pytest.raises(ValueError, match="MIXED_M2_"):
        worker.validate_m2_producer_output_population(receipt, project)


def test_m2_worker_exports_complete_native_receipt_output_population(tmp_path, monkeypatch):
    import hashlib
    import mixed_signal_power_domain_run as producer

    canonical = tmp_path / "canonical"
    snapshot = tmp_path / "snapshot"
    inputs = (
        "input/pdk/liberty/neutral.lib",
        "phase2/stage2/constraints/boundary.upf",
        "phase3/mixed_signal/top_merged.gds",
        "phase3/stage3/pnr/boundary_pnr.v",
        "phase3/stage3/pnr/routed.def",
    )
    input_hashes = {}
    for index, name in enumerate(inputs):
        content = f"m2-input-{index}\n".encode()
        for root in (canonical, snapshot):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        input_hashes[name] = hashlib.sha256(content).hexdigest()
    params = {"top_name": "boundary", "container": "host", "pdk": "auto",
              "project_subject": str(canonical.resolve())}
    gate_names = [row[0] for row in worker.GATES["M2"]]
    binding = {"step_id": "M2", "objective": params,
               "required_gates": gate_names, "inputs": input_hashes}
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps(binding))

    def fake_run(program, args, project):
        if program == "mixed_signal_power_domain_run" and "--check-only" not in args:
            receipt_outputs = {}
            producer_paths = {f"{producer.DIR}/{name}" for name in producer.OUTPUTS}
            producer_paths.update(mixed.M2_SIDECAR_OUTPUTS)
            for name in sorted(producer_paths):
                path = project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("measured producer fixture: " + name + "\n")
                receipt_outputs[name] = worker.sha(path)
            native_receipt = {
                "schema": producer.SCHEMA, "verdict": "PASS", "top": "boundary",
                "inputs": {str((project / name).resolve()): digest
                           for name, digest in input_hashes.items()},
                "liberties": [str((project / inputs[0]).resolve())],
                "tool": {"name": "yosys", "exit_code": 0,
                         "creator": "Yosys bounded source fixture"},
                "outputs": receipt_outputs,
            }
            receipt_path = project / "reports/analog/mixed_signal/power_domain_run.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(native_receipt, sort_keys=True))
            return {"program": program, "argv": ["mocked-producer"], "rc": 0,
                    "verdict": "PASS", "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_sha256": hashlib.sha256(b"").hexdigest()}
        for name, report_path, *flags in worker.GATES["M2"]:
            if name == program:
                report = project / report_path
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text('{"verdict":"PASS"}\n')
                command = mixed._nested_gate_argv(name, str(project.resolve()),
                                                  report_path, flags)
                return {"program": name, "argv": command, "rc": 0,
                        "verdict": "PASS",
                        "stdout_sha256": hashlib.sha256(b"gate-out").hexdigest(),
                        "stderr_sha256": hashlib.sha256(b"gate-err").hexdigest()}
        raise AssertionError(f"unexpected worker program: {program} {args}")

    monkeypatch.setattr(worker, "_run", fake_run)
    arm_outputs = tmp_path / "arm-outputs"
    result = worker.execute(snapshot, arm_outputs, "M2", params)
    native_receipt = json.loads((arm_outputs / "project/reports/analog/mixed_signal/"
                                 "power_domain_run.json").read_text())
    native_population = set(native_receipt["outputs"])
    assert native_population == {
        *{f"{producer.DIR}/{name}" for name in producer.OUTPUTS},
        *mixed.M2_SIDECAR_OUTPUTS,
    }
    assert native_population <= set(result["outputs"])
    for name, digest in native_receipt["outputs"].items():
        exported = arm_outputs / name
        assert exported.is_file() and not exported.is_symlink()
        assert worker.sha(exported) == digest == result["outputs"][name]
    evidence = mixed.validate(arm_outputs, binding)
    assert evidence.verdict == "PASS"
    assert native_population <= set(evidence.outputs)


def test_actual_m2_worker_runs_checked_in_placed_fixture_and_existing_consumer(tmp_path,
                                                                               monkeypatch):
    """Exercise actual Registry worker source against the existing M2 fixture.

    The outcome follows the installed Yosys tool: without it, preserve the real
    producer's NOT_MEASURED result. No evidence or PASS is synthesized here.
    """
    import shutil
    from programs.tests.test_m2_native_producer import FIXTURE
    from programs.tests import test_m2_native_producer as native_m2

    project = tmp_path / "canonical-project"
    shutil.copytree(FIXTURE, project)
    source = project / "phase1/analog/analog_block_list.json"
    target = project / "phase3/analog/analog_block_list.json"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    params = {"top_name": "boundary", "container": "host", "pdk": "auto",
              "project_subject": str(project.resolve())}
    issued_input_paths = (
        "input/pdk/liberty/neutral.lib",
        "phase2/stage2/constraints/boundary.upf",
        "phase3/mixed_signal/top_merged.gds",
        "phase3/stage3/pnr/boundary_pnr.v",
        "phase3/stage3/pnr/routed.def",
    )
    binding = {"step_id": "M2", "objective": params,
               "required_gates": ["mixed_signal_power_domain_run",
                   "power_domain_crossing_check", "level_shifter_required_check",
                   "isolation_cell_required_check", "power_domain_signal_crossing_check"],
               # The worker rebinds a PASS receipt only against the exact
               # current bytes issued by the controller.  Empty and stale
               # bindings remain covered by the dedicated refusal controls.
               "inputs": {relative: worker.sha(project / relative)
                          for relative in issued_input_paths}}
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps(binding))
    inputs = tmp_path / "issued-inputs"
    shutil.copytree(project, inputs)
    outputs = tmp_path / "issued-outputs"
    receipt = worker.execute(inputs, outputs, "M2", params)
    assert receipt["producer"] == "mixed_signal_power_domain_run"
    assert receipt["producer_command"]["argv"]
    assert receipt["gate_records"]
    verdicts = {row["verdict"] for row in receipt["gate_records"]}
    if shutil.which("yosys"):
        assert receipt["producer_verdict"] == "PASS"
        # The rebound receipt names the canonical subject.  The obsolete
        # staged-root consumer must refuse that mismatch rather than silently
        # treating the worker snapshot as current.
        staged_consumer_report = "reports/analog/mixed_signal/power_domain_staged_consumer.json"
        assert native_m2.invoke(outputs / "project", "--check-only",
                                "--json", staged_consumer_report) == 1
        staged_report = json.loads(
            (outputs / "project" / native_m2.REPORTS /
             "power_domain_staged_consumer.json").read_text())
        assert staged_report["findings"][0]["rule"] == "STALE_INPUT"

        # Publish the worker's complete exported population to the canonical
        # subject, checking every declared digest before the existing consumer
        # reads it.  This is the same bounded adoption boundary the controller
        # uses; no receipt or output byte is synthesized here.
        for relative, expected in receipt["outputs"].items():
            exported = outputs / relative
            assert exported.is_file() and not exported.is_symlink()
            assert worker.sha(exported) == expected
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(exported, target)
            assert worker.sha(target) == expected
        assert native_m2.invoke(project, "--check-only") == 0
    else:
        assert "NOT_MEASURED" in verdicts or receipt["producer_verdict"] == "NOT_MEASURED"


@pytest.mark.parametrize("execution_mode", ["default", "ultra"])
def test_m2_real_adapter_controller_choice_adoption_journal_and_current_reread(tmp_path,
                                                                           monkeypatch,
                                                                           execution_mode):
    """Use the real issued route and actual registered M2 worker end to end."""
    import hashlib
    import shutil
    import execution_modes as em
    import execution_policy as policy
    from execution_backend_snapshot import Journal
    from programs.tests.test_m2_native_producer import FIXTURE
    import mixed_signal_power_domain_run as m2

    monkeypatch.setattr(policy, "_ordinary_runtime", None)
    journal_writes = []
    journal_write = Journal.write

    def capture_journal_write(journal, name, content):
        journal_writes.append((name, content))
        return journal_write(journal, name, content)

    monkeypatch.setattr(Journal, "write", capture_journal_write)
    project = (tmp_path / "canonical-project").resolve()
    shutil.copytree(FIXTURE, project)
    block_list = project / "phase1/analog/analog_block_list.json"
    staged_block_list = project / "phase3/analog/analog_block_list.json"
    staged_block_list.parent.mkdir(parents=True)
    shutil.copyfile(block_list, staged_block_list)

    issued = live_issuer.real_entry("IC", execution_mode, project)
    runtime = policy.bootstrap(project, parameters={
        "top_name": "boundary", "container": "host", "pdk": "auto"})
    assert runtime["route"] == issued["route"]
    assert runtime["controller"].registry is runtime["registry"]
    arms = runtime["registry"].adapters("M2")
    assert [arm.arm_id for arm in arms] == ["M2_ordinary_producer"]
    assert arms[0].components[0].argv[1].endswith("execution_mixed_worker.py")

    pending = policy.dispatch_fixed_step(project, "M2")
    assert pending["status"] == ("ADOPTED" if execution_mode == "default" else
                                  "AWAITING_AI_SELECTION"), pending
    run, first_result = runtime["runs"]["M2"]
    context = runtime["contexts"]["M2"]
    plan = json.loads((run / "plan.json").read_text())
    assert plan["arms"] == ["M2_ordinary_producer"]
    receipt_path = run / "M2_ordinary_producer/receipt.json"
    worker_receipt = json.loads((run / "M2_ordinary_producer/outputs/mixed-result.json").read_text())
    assert first_result["candidate_statuses"]["M2_ordinary_producer"] == "ELIGIBLE"
    assert worker_receipt["producer"] == "mixed_signal_power_domain_run"
    assert worker_receipt["producer_verdict"] == "PASS"
    assert worker_receipt["producer_command"]["rc"] == 0
    assert all(row["verdict"] == "PASS" for row in worker_receipt["gate_records"])
    producer_receipt = json.loads((run / "M2_ordinary_producer/outputs/project/"
                                   "reports/analog/mixed_signal/power_domain_run.json").read_text())
    actual_sidecars = {name for name in producer_receipt["outputs"]
                       if "/power_domain_tool/" in name}
    assert actual_sidecars == set(mixed.M2_SIDECAR_OUTPUTS)
    assert actual_sidecars <= set(worker_receipt["outputs"])
    assert all(worker_receipt["outputs"][name] == producer_receipt["outputs"][name]
               for name in actual_sidecars)

    legal_choice = core_helpers.choice(context, run, "M2_ordinary_producer")
    adopted = (pending if execution_mode == "default" else
               policy.dispatch_fixed_step(project, "M2", choice=legal_choice))
    assert adopted["status"] == "ADOPTED", adopted
    assert adopted["selected"] == "M2_ordinary_producer"
    verified = runtime["controller"].verify_adoption(context, run)
    assert verified["selected"] == adopted["selected"]
    generation = verified["selected_generation"]
    current_hashes = {}
    for name, expected in generation["outputs"].items():
        current = project / name
        assert current.is_file(), name
        actual = em.digest(current)
        assert actual == expected, name
        current_hashes[name] = actual
    assert {name for name, _content in journal_writes} == set(generation["outputs"])
    assert actual_sidecars <= set(generation["outputs"])
    assert actual_sidecars <= {name for name, _content in journal_writes}
    journal_contents = dict(journal_writes)
    assert all(hashlib.sha256(journal_contents[name]).hexdigest() ==
               current_hashes[name] == generation["outputs"][name] ==
               producer_receipt["outputs"][name] for name in actual_sidecars)
    assert current_hashes["reports/analog/mixed_signal/power_domain.json"] == \
        generation["outputs"]["reports/analog/mixed_signal/power_domain.json"]
    assert m2.main([str(project), "--check-only"]) == 0
    assert json.loads(receipt_path.read_text())["status"] == "ELIGIBLE"
    print(json.dumps({"selected_arm": adopted["selected"],
                      "generation": generation["generation"],
                      "current_power_domain_sha256": current_hashes[
                          "reports/analog/mixed_signal/power_domain.json"]}, sort_keys=True))


@pytest.mark.parametrize("sid", ("M1", "M2", "M3", "M4"))
def test_default_mixed_missing_current_receipt_is_named_not_measured(tmp_path, sid):
    binding = {"step_id": sid, "required_gates": [row[0] for row in worker.GATES[sid]]}
    evidence = mixed.validate(tmp_path, binding)
    assert (evidence.verdict, evidence.detail) == (
        "NOT_MEASURED", "MIXED_CURRENT_RECEIPT_ABSENT")
    assert all(status == "NOT_MEASURED" for status in evidence.gates.values())


def test_default_mixed_explicit_empty_population_is_inapplicable(tmp_path):
    import execution_modes as em
    project = tmp_path / "digital"
    declaration = project / "phase1/analog/analog_block_list.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_text('{"blocks":[],"block_count":0}\n')
    registry = mixed.register_mixed_adapters(em.Registry(), source_sha="ignored", project=project)
    observed = {sid: registry.adapters(sid)[0].applicability for sid in mixed.IDS}
    assert observed == dict.fromkeys(mixed.IDS, "inapplicable"), observed
