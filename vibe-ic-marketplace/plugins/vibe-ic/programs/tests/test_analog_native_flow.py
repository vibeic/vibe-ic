"""Native analog entry, retained state and failure propagation controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import analog_native_flow as native
import flow109


@pytest.fixture(autouse=True)
def _restore_native_frontdoor_environment(monkeypatch):
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)


def project(tmp_path):
    (tmp_path / "input").mkdir()
    block = tmp_path / "phase3/analog/cell_alpha"
    block.mkdir(parents=True)
    (block.parent / "analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "cell_alpha", "type": "amplifier"}]}))
    (block / "cell_alpha.sp").write_text("* actual DUT\n.subckt cell_alpha p n\nr1 p n 1k\n.ends\n")
    (block / "tb_cell_alpha.sp").write_text(
        "* actual testbench\n.include cell_alpha.sp\nv1 in 0 1\n"
        "xdut in 0 cell_alpha\n.control\ntran 1n 10n\n"
        "meas tran peak max v(in) from=2n to=8n\n.endc\n.end\n")
    (block / "spec.json").write_text('{"specs": [{"name":"peak","min":0.9,"max":1.1}]}')
    return tmp_path


def args(entry="A06", exit_="A06"):
    return SimpleNamespace(entry_step=entry, exit_step=exit_, blocks="", container="", pdk="")


def test_native_analog_cli_runs_delivered_consumer_without_qualification_files(tmp_path):
    root = project(tmp_path)
    command = [sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
               "--flow", "109", "--entry-step", "A06", "--exit-step", "A06", "--container", ""]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((root / "reports/analog_native/status.json").read_text())
    assert [(row["step"], row["block"], row["status"]) for row in report["steps"]] == [
        ("A06", "cell_alpha", "PASS")]
    assert not list(root.rglob("*qualification*"))


def test_new_default_native_entry_refuses_an_unimplemented_mode_before_execution(tmp_path):
    root = project(tmp_path)
    completed = subprocess.run([
        sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
        "--flow", "109", "--entry-step", "A06", "--exit-step", "A06",
        "--execution-mode", "ultra"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "implements Default mode" in completed.stderr
    assert not (root / "reports/analog_native").exists()


def test_canonical_flow_frontdoor_dispatches_same_native_consumer(tmp_path):
    root = project(tmp_path)
    features = next(profile["features"] for profile in flow109.load_registry()["reference_profiles"]
                    if profile["name"] == "Analog model-IP")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    command = [sys.executable, str(native.HERE / "vibe_ic_one_shot_runner.py"), str(root),
               "--flow", "109", "--flow109-manifest", str(manifest),
               "--entry-step", "A06", "--exit-step", "A06", "--route", "ip",
               "--container", "", "--no-dashboard"]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads((root / "reports/flow109/components/A06.json").read_text())
    assert receipt["component_status"] == "PASS"
    assert receipt["flow109_acceptance"] == "NOT_MEASURED"
    assert receipt["native_results"]["steps"][0]["block"] == "cell_alpha"


def test_attested_canonical_frontdoor_keeps_actual_a07_producer_local(tmp_path, monkeypatch):
    root = project(tmp_path)
    features = next(profile["features"] for profile in flow109.load_registry()["reference_profiles"]
                    if profile["name"] == "Analog model-IP")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", "old-named-container")
    completed = subprocess.run([
        sys.executable, str(native.HERE / "vibe_ic_one_shot_runner.py"), str(root),
        "--flow", "109", "--flow109-manifest", str(manifest),
        "--entry-step", "A07", "--exit-step", "A07", "--route", "ip",
        "--no-dashboard"], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    receipt = json.loads((root / "reports/flow109/components/A07.json").read_text())
    native_report = receipt["native_results"]
    assert native_report["transport"] == "LOCAL"
    assert native_report["container"] == ""
    execution = native_report["steps"][0]["executions"][0]
    assert execution["returncode"] == 0
    assert execution["argv"][0] != "docker"
    assert native_report["steps"][0]["producer_context"]["transport"] == "LOCAL"


def test_all_nineteen_registry_rows_name_the_actual_native_owner():
    rows = [row for row in flow109.load_registry()["rows"] if row["id"].startswith("A")]
    assert [row["id"] for row in rows] == list(native.STEPS)
    assert [(row["profiles"][0]["dispatch"]["adapter"]) for row in rows] == [
        "analog_native_flow"] * 19


def _a18_options(root, output, evidence):
    return {"features": {"digital_physical": False}, "config": {"analog_top": {
        "implementation_script": str(root / "input/a18.tcl"),
        "outputs": [str(output), str(evidence)], "evidence": str(evidence)}}}


def test_a18_preserves_native_component_fail_and_reason(tmp_path):
    root = project(tmp_path)
    script = root / "input/a18.tcl"
    script.write_text("puts A18\n")
    output, evidence = root / "top.gds", root / "a18.json"
    output.write_bytes(b"native-gds")
    evidence.write_text(json.dumps({"component_status": "FAIL",
                                    "reason": "native LVS mismatch"}))
    options = _a18_options(root, output, evidence)
    run = lambda *a, **kw: {"returncode": 0, "missing_outputs": [], "outputs": {}}
    result = native._views("A18", root, {"name": "cell_alpha"}, options, run)
    assert result["status"] == "FAIL"
    assert result["detail"] == "native LVS mismatch"
    assert result["native_evidence"]["component_status"] == "FAIL"


def test_a18_accepts_native_component_pass_with_required_outputs(tmp_path):
    root = project(tmp_path)
    script = root / "input/a18.tcl"
    script.write_text("puts A18\n")
    output, evidence = root / "top.gds", root / "a18.json"
    output.write_bytes(b"native-gds")
    evidence.write_text(json.dumps({"component_status": "PASS"}))
    options = _a18_options(root, output, evidence)
    run = lambda *a, **kw: {"returncode": 0, "missing_outputs": [], "outputs": {}}
    result = native._views("A18", root, {"name": "cell_alpha"}, options, run)
    assert result["status"] == "PASS", result


def test_a18_rejects_pass_without_declared_outputs(tmp_path):
    root = project(tmp_path)
    script = root / "input/a18.tcl"
    script.write_text("puts A18\n")
    evidence = root / "a18.json"
    evidence.write_text(json.dumps({"component_status": "PASS"}))
    options = _a18_options(root, root / "top.gds", evidence)
    options["config"]["analog_top"]["outputs"] = []
    run = lambda *a, **kw: {"returncode": 0, "missing_outputs": [], "outputs": {}}
    result = native._views("A18", root, {"name": "cell_alpha"}, options, run)
    assert result["status"] == "FAIL"


def test_a18_non_object_receipt_is_not_measured(tmp_path):
    root = project(tmp_path)
    script = root / "input/a18.tcl"
    script.write_text("puts A18\n")
    output, evidence = root / "top.gds", root / "a18.json"
    output.write_bytes(b"native-gds")
    evidence.write_text("[]")
    options = _a18_options(root, output, evidence)
    run = lambda *a, **kw: {"returncode": 0, "missing_outputs": [], "outputs": {}}
    result = native._views("A18", root, {"name": "cell_alpha"}, options, run)
    assert result["status"] == "NOT_MEASURED"


def test_explicit_mixed_inventory_cannot_omit_selected_analog_use():
    context = {"resolved_rows": [
        {"profile": {"dispatch": {"adapter": "analog_native_flow"}},
         "tool_uses": [{"use_id": "analog.native", "qualification_required": False}]},
        {"profile": {"dispatch": {"adapter": "digital_native"}},
         "tool_uses": [{"use_id": "digital.native", "qualification_required": True}]}],
        "runtime_tool_uses": [{"use_id": "digital.native"}],
        "qualification_registry": "digital-qualified.json"}
    # Ordinary native execution needs no registry. An explicit qualification
    # claim must still cover every selected use; it cannot exempt analog.
    with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_USE_MISMATCH"):
        flow109._window_inventory(context)
    context["runtime_tool_uses"].append({"use_id": "analog.native"})
    flow109._window_inventory(context)
    context["runtime_tool_uses"] = []
    with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_USE_MISMATCH"):
        flow109._window_inventory(context)
    context["runtime_tool_uses"] = [{"use_id": "digital.native"}, {"use_id": "unknown.use"}]
    with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_USE_MISMATCH"):
        flow109._window_inventory(context)


def test_canonical_invalid_block_input_returns_unmeasured_without_traceback(tmp_path):
    root = project(tmp_path)
    (root / "phase3/analog/analog_block_list.json").write_text('{"blocks":[]}')
    features = next(profile["features"] for profile in flow109.load_registry()["reference_profiles"]
                    if profile["name"] == "Analog model-IP")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    completed = subprocess.run([
        sys.executable, str(native.HERE / "vibe_ic_one_shot_runner.py"), str(root),
        "--flow", "109", "--flow109-manifest", str(manifest),
        "--entry-step", "A06", "--exit-step", "A06", "--route", "ip",
        "--container", "", "--no-dashboard"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    receipt = json.loads((root / "reports/flow109/components/A06.json").read_text())
    assert receipt["component_status"] == "NOT_MEASURED"
    assert receipt["native_started"] is False
    assert "block list" in receipt["reason"]


def test_canonical_analog_window_keeps_independent_consumers_running_after_native_refusal(tmp_path):
    root = project(tmp_path)
    features = next(profile["features"] for profile in flow109.load_registry()["reference_profiles"]
                    if profile["name"] == "Analog model-IP")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    completed = subprocess.run([
        sys.executable, str(native.HERE / "vibe_ic_one_shot_runner.py"), str(root),
        "--flow", "109", "--flow109-manifest", str(manifest),
        "--entry-step", "A05", "--exit-step", "A06", "--route", "ip",
        "--container", "", "--no-dashboard"], capture_output=True, text=True)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    reports = root / "reports/flow109/components"
    a05 = json.loads((reports / "A05.json").read_text())
    a06 = json.loads((reports / "A06.json").read_text())
    assert a05["component_status"] == "FAIL"
    assert a06["component_status"] == "PASS"
    assert a06["flow109_acceptance"] == "NOT_MEASURED"
    assert not list(root.rglob("*qualification*"))


@pytest.mark.parametrize("state,expected", [("FAIL", "FAIL"), ("NOT_MEASURED", "NOT_MEASURED")])
def test_native_nonpass_reaches_run_verdict(tmp_path, monkeypatch, state, expected):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *arguments:
                        {"status": state, "detail": "actual native result", "outputs": []})
    result = native.run_window(root, args())
    assert result["verdict"] == expected
    assert result["steps"][0]["status"] == state


def test_bounded_native_pass_does_not_erase_or_inherit_an_unrelated_failure(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda step, *arguments: {
        "status": "FAIL" if step == "A06" else "PASS", "outputs": []})
    native.run_window(root, args("A06", "A06"))
    result = native.run_window(root, args("A11", "A11"))
    assert result["window_verdict"] == "PASS"
    assert result["verdict"] == "FAIL"


def test_block_subset_keeps_other_block_state_without_inheriting_its_failure(tmp_path, monkeypatch):
    root = project(tmp_path)
    (root / "phase3/analog/analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "cell_alpha"}, {"name": "cell_beta"}]}))
    beta = root / "phase3/analog/cell_beta"
    beta.mkdir()
    (beta / "cell_beta.sp").write_text("* retained beta input\n")
    monkeypatch.setattr(native, "_dispatch", lambda step, _p, block, *_args: {
        "status": "FAIL" if block["name"] == "cell_beta" else "PASS", "outputs": []})
    native.run_window(root, args())
    selected = args()
    selected.blocks = "cell_alpha"
    result = native.run_window(root, selected)
    assert result["window_verdict"] == "PASS"
    assert result["verdict"] == "FAIL"
    assert {row["block"]: row["status"] for row in result["steps"]} == {
        "cell_alpha": "PASS", "cell_beta": "FAIL"}


def test_measurement_study_declaration_invalidates_only_its_consuming_rows(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *a: {"status": "PASS", "outputs": []})
    native.run_window(root, args("A05", "A07"))
    (root / "phase3/analog/cell_alpha/measurement_studies.json").write_text("[]")
    observed = []
    def dispatch(step, _project, _block, options, _run):
        observed.append(set(options["previous_results"]))
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A08", "A08"))
    assert "A05" in observed[-1]
    assert "A06" not in observed[-1] and "A07" not in observed[-1]


def test_post_mc_execution_sample_override_reaches_native_dispatch_without_config_edit(tmp_path, monkeypatch):
    root = project(tmp_path)
    seen = []
    def dispatch(step, _project, _block, options, _run):
        seen.append(options["post_mc_samples"])
        return {"status": "NOT_MEASURED", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    request = args("A15", "A15")
    request.post_mc_samples = 2
    native.run_window(root, request)
    assert seen == [2]
    assert not (root / "input/analog_flow.json").exists()


@pytest.mark.parametrize("leaf", ["template.sp", "bindings.json", "native.log"])
def test_retained_study_changes_are_detected_outside_input_directory(tmp_path, monkeypatch, leaf):
    root = project(tmp_path)
    study = root / "continuations/study"
    study.mkdir(parents=True)
    for name in ("template.sp", "bindings.json", "native.log"):
        (study / name).write_text("{}" if name.endswith("json") else "native input\n")
    record = study / "result.json"
    record.write_text(json.dumps({"executions": [{"log": str(study / "native.log")}]}))
    (root / "phase3/analog/cell_alpha/measurement_studies.json").write_text(json.dumps([{
        "testbench": str(study / "template.sp"), "bindings": str(study / "bindings.json"),
        "result": str(record)}]))
    observed = []
    def dispatch(step, _project, _block, options, _run):
        observed.append(set(options["previous_results"]))
        return {"status": "NOT_MEASURED", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A07", "A07"))
    native.run_window(root, args("A08", "A08"))
    assert "A07" in observed[-1]
    (study / leaf).write_text('{"changed":true}' if leaf.endswith("json") else "changed\n")
    native.run_window(root, args("A09", "A09"))
    assert "A07" not in observed[-1]


def test_retained_result_keeps_original_image_attribution_across_execution_contexts(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *a: {"status": "PASS", "outputs": []})
    first = args("A06", "A06")
    first.image = "image-A"
    native.run_window(root, first)
    second = args("A07", "A07")
    second.image = "image-B"
    result = native.run_window(root, second)
    rows = {row["step"]: row for row in result["steps"]}
    assert result["image"] == "image-B"
    assert rows["A06"]["producer_context"]["image"] == "image-A"
    assert rows["A07"]["producer_context"]["image"] == "image-B"


def test_native_discovered_inputs_are_retained_only_while_their_bytes_match(tmp_path, monkeypatch):
    root = project(tmp_path)
    source = root / "matched-load.sp"
    source.write_text("* actual selected post-layout load context\n")
    observed = []
    def dispatch(step, _project, _block, options, _run):
        observed.append(set(options["previous_results"]))
        return {"status": "NOT_MEASURED", "outputs": [], "native_inputs": {
            "matched_template": {"path": str(source), "sha256": native._sha(source)}}}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A14", "A14"))
    native.run_window(root, args("A15", "A15"))
    assert "A14" in observed[-1]
    source.write_text("* different load context\n")
    native.run_window(root, args("A16", "A16"))
    assert "A14" not in observed[-1]


def test_successful_exit_without_promised_native_output_is_not_pass(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *arguments: {
        "status": "PASS", "outputs": [], "executions": [{"returncode": 0,
        "missing_outputs": [str(root / "missing.gds")]}]})
    result = native.run_window(root, args())
    assert result["verdict"] == "NOT_MEASURED"
    assert "missing.gds" in result["steps"][0]["detail"]


def test_checkpoint_reused_only_while_its_actual_views_match(tmp_path, monkeypatch):
    root = project(tmp_path)
    recorded = []
    def dispatch(step, _project, _block, options, _run):
        recorded.append(set(options["previous_results"]))
        return {"status": "PASS", "detail": "native result", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A06", "A06"))
    native.run_window(root, args("A07", "A07"))
    assert "A06" in recorded[-1]
    (root / "phase3/analog/cell_alpha/cell_alpha.sp").write_text("* changed circuit\n")
    native.run_window(root, args("A08", "A08"))
    assert "A06" not in recorded[-1]


def test_alternate_nominal_deck_change_invalidates_retained_measurement(tmp_path, monkeypatch):
    root = project(tmp_path)
    alternate = root / "phase3/alternate.sp"
    alternate.write_text("* source-selected nominal deck\n")
    (root / "input/analog_flow.json").write_text(json.dumps({
        "steps": {"A07": {"nominal_testbench": "phase3/alternate.sp"}}}))
    observed = []
    def dispatch(step, _project, _block, options, _run):
        observed.append(set(options["previous_results"]))
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A07", "A07"))
    native.run_window(root, args("A08", "A08"))
    assert "A07" in observed[-1]
    alternate.write_text("* changed source-selected nominal deck\n")
    native.run_window(root, args("A09", "A09"))
    assert "A07" not in observed[-1]


def test_independent_block_advances_while_another_native_step_is_waiting(tmp_path, monkeypatch):
    root = project(tmp_path)
    declared = root / "phase3/analog/analog_block_list.json"
    declared.write_text(json.dumps({"blocks": [{"name": "cell_alpha"}, {"name": "cell_beta"}]}))
    (root / "input/analog_flow.json").write_text('{"workers":2}')
    beta_advanced = threading.Event()
    observed = []
    def dispatch(step, _project, block, options, _run):
        if block["name"] == "cell_alpha" and step == "A06":
            observed.append(beta_advanced.wait(5))
        if block["name"] == "cell_beta" and step == "A07":
            assert options["previous_results"]["A06"]["cell_beta"]["status"] == "PASS"
            beta_advanced.set()
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    result = native.run_window(root, args("A06", "A07"))
    assert observed == [True]
    assert result["verdict"] == "PASS"


def test_actual_subprocess_error_and_output_are_retained(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "HERE", tmp_path)
    (tmp_path / "native_tool.py").write_text("print('native failure detail')\nraise SystemExit(7)\n")
    execution = native.NativeCommands(tmp_path, tmp_path, "")("native_tool.py", [])
    assert execution["returncode"] == 7
    assert Path(execution["log"]).read_text() == "native failure detail\n"


def test_changed_sizing_input_invalidates_its_actual_consumers_only(tmp_path, monkeypatch):
    root = project(tmp_path)
    directory = root / "phase3/analog/cell_alpha"
    declarations = directory / "sizing_inputs.json"
    declarations.write_text('{"knobs":{"divider_ratio":2.0}}')
    calls = []
    def dispatch(step, *arguments):
        calls.append(step)
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    native.run_window(root, args("A01", "A05"))
    declarations.write_text('{"knobs":{"divider_ratio":1.5}}')
    report = native.run_window(root, args("A06", "A06"))
    retained = {row["step"] for row in report["steps"]}
    assert {"A01", "A02", "A03", "A06"}.issubset(retained)
    assert not {"A04", "A05"} & retained
    assert calls == ["A01", "A02", "A03", "A04", "A05", "A06"]


def test_a17_selects_explicit_native_binary_without_changing_gds_producer(tmp_path):
    root = project(tmp_path)
    directory = root / "phase3/analog/cell_alpha"
    (directory / "layout.mag").write_text("magic\n")
    selected = root / "native-tools/ngspice"
    selected.parent.mkdir()
    selected.write_text("native binary identity")
    declaration = directory / "characterization_inputs.json"
    declaration.write_text(json.dumps({"ngspice_bin": str(selected)}))
    calls = []
    def run(program, argv):
        calls.append((program, argv))
        return {"returncode": 0 if len(calls) == 1 else 1}
    result = native._views("A17", root, {"name": "cell_alpha"}, {"container": "native"}, run)
    assert result["status"] == "FAIL"
    assert "--ngspice-bin" not in calls[0][1]
    assert calls[1][1][-2:] == ["--ngspice-bin", str(selected)]
    before = native._input_views(root, "cell_alpha", "A17")
    selected.write_text("changed native binary identity")
    after = native._input_views(root, "cell_alpha", "A17")
    assert before[str(selected)] != after[str(selected)]
    assert str(declaration) in after


def test_container_subprocess_loads_native_tool_environment_without_shell_interpolation(tmp_path, monkeypatch):
    seen = []
    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="native result\n", stderr="")
    monkeypatch.setattr(native.subprocess, "run", run)
    execution = native.NativeCommands(tmp_path, tmp_path, "native-box", "repo@sha256:fixed")(
        "@ngspice", ["-b", str(tmp_path / "deck with space.sp")])
    assert seen[0][0][-7:] == ["bash", "-lc", 'exec "$@"', "analog-native", "ngspice", "-b",
                             str(tmp_path / "deck with space.sp")]
    assert execution["returncode"] == 0


def test_attested_local_adapter_ignores_inherited_legacy_container(tmp_path, monkeypatch):
    import librelane_contract as contract
    root = project(tmp_path)
    seen = {}
    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", "old-named-container")
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner.py"])
    monkeypatch.setattr(contract, "local_image_attestation", lambda: {
        "image": "repo@sha256:" + "a" * 64})
    monkeypatch.setattr(native, "run_window", lambda project, args, **kwargs:
                        seen.update(container=args.container, image=args.image,
                                    transport=args.transport) or {"window_verdict": "PASS"})
    context = {"requested_step": "A01", "features": {}}
    monkeypatch.setattr(flow109, "validate_execution_context", lambda value: value)
    result = native.execute_window(root, context)
    assert result["window_verdict"] == "PASS"
    assert seen == {"container": "", "image": "repo@sha256:" + "a" * 64,
                    "transport": "LOCAL"}


def test_explicit_container_adapter_selection_is_preserved(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", "selected-container")
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner.py",
                                      "--container", "selected-container"])
    assert native._adapter_transport(root) == ("selected-container", "", "CONTAINER")
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner.py", "--container", ""])
    assert native._adapter_transport(root) == ("", "", "HOST")


def test_unattested_inherited_container_is_not_relabelled_local(tmp_path, monkeypatch):
    import librelane_contract as contract
    root = project(tmp_path)
    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", "legacy-container")
    monkeypatch.setattr(sys, "argv", ["vibe_ic_one_shot_runner.py"])
    monkeypatch.setattr(contract, "local_image_attestation", lambda: (_ for _ in ()).throw(
        contract.Refusal("LL_LOCAL_IMAGE_UNATTESTED", "negative control")))
    assert native._adapter_transport(root) == ("legacy-container", "", "CONTAINER")


def test_a19_cannot_sign_off_empty_delivery_even_with_green_step_words(tmp_path):
    root = project(tmp_path)
    previous = {step: {"cell_alpha": {"status": "PASS"}} for step in native.STEPS[:-1]}
    result = native._views("A19", root, {"name": "cell_alpha"},
                           {"previous_results": previous}, None)
    assert result["status"] == "FAIL"
    receipt = json.loads((root / "phase3/analog/cell_alpha/signoff.json").read_text())
    assert receipt["deliverables"] == {}


@pytest.mark.parametrize("rc", [130, 137, 143, -15])
def test_a17_interrupted_producer_without_terminal_measurement_is_unmeasured(tmp_path, rc):
    root = project(tmp_path)
    (root / "phase3/analog/cell_alpha/layout.mag").write_text("magic\n")
    result = native._views("A17", root, {"name": "cell_alpha"},
                           {"container": ""}, lambda *a, **kw: {"returncode": rc})
    assert result["status"] == "NOT_MEASURED"
    assert result["executions"][0]["returncode"] == rc


def test_all_native_analog_rows_use_existing_unqualified_default_admission():
    for spec in flow109.load_registry()["rows"]:
        if not spec["id"].startswith("A"):
            continue
        row = {**spec, "profile": spec["profiles"][0]}
        dispatch = flow109.source_owned_native_dispatch(row)
        assert dispatch["adapter"] == "analog_native_flow"
        assert dispatch["acceptance_scope"] == "existing_native_component_only"


@pytest.mark.parametrize("exit_step", ["A06", "A07"])
def test_explicit_empty_analog_qualification_claim_never_launches_native(
        tmp_path, monkeypatch, exit_step):
    from types import SimpleNamespace
    from flow109_admission import AdmissionRefusal
    from programs.tests._route_fixture import stage_owner_route
    root = project(tmp_path)
    stage_owner_route(root, "ip")
    features = next(profile["features"] for profile in flow109.load_registry()["reference_profiles"]
                    if profile["name"] == "Analog model-IP")
    manifest = root / "explicit-qualification.json"
    manifest.write_text(json.dumps({"features": features, "runtime_tool_uses": []}))
    monkeypatch.setattr(native, "execute", lambda *a: pytest.fail("native must not start"))
    monkeypatch.setattr(native, "execute_window", lambda *a: pytest.fail("native must not start"))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="A06", exit_step=exit_step)
    if exit_step == "A06":
        with pytest.raises(AdmissionRefusal, match="QUALIFICATION_RUNTIME_ABSENT"):
            flow109.prepare_front_door(args, root)
    else:
        with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_USE_MISMATCH"):
            flow109.prepare_front_door(args, root)
