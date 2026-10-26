"""Exercise source-owned selection through the canonical front door.

These are configuration/dispatch tests, not EDA qualification or IC PASS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow109
from programs.tests._hostpaths import require_repo


def profile(name="Small digital IC without DFT"):
    registry = flow109.load_registry()
    return copy.deepcopy(next(p["features"] for p in registry["reference_profiles"] if p["name"] == name))


def test_source_mapping_preserves_native_identity_and_unfiltered_position():
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "phase1_phase2_phase3.yaml")
    import yaml
    native = yaml.safe_load(source.read_text())["steps"]
    plan = flow109.resolve_plan(profile())
    cts = flow109.resolve_step(plan, "D38")
    assert cts["legacy70"] == [{"position": 34, "id": "19", "name": native[33]["name"]}]
    assert cts["position"] > 34
    assert cts["profile"]["dispatch"]["native_step_id"] == "19"
    assert cts["tool_uses"][0]["use_id"] == "flow109.D38.default.openroad"
    assert plan["runtime_verdict"] == plan["flow109_acceptance"] == "NOT_MEASURED"
    assert [g["id"] for g in plan["gate_layers"]] == [f"G{i}" for i in range(1, 10)]
    assert cts["gate_matrix_status"] == "NOT_MEASURED_FOR_109"


def test_reference_profiles_close_without_turning_unknown_into_false():
    for item in flow109.load_registry()["reference_profiles"]:
        plan = flow109.resolve_plan(item["features"])
        assert plan["selected_count"] > 0
        assert plan["status"] == "PLAN_RESOLVED_NOT_EXECUTED"
    features = profile()
    del features["has_digital"]
    with pytest.raises(flow109.Flow109Error, match="FEATURE_UNRESOLVED"):
        flow109.resolve_plan(features)


@pytest.mark.parametrize("mutation", ["derived", "endpoint", "fpga", "non_boolean"])
def test_invalid_feature_sets_refuse_before_dispatch(mutation):
    features = profile()
    if mutation == "derived":
        features["digital_physical"] = False
    elif mutation == "endpoint":
        features["soft_ip"] = True
    elif mutation == "fpga":
        features = profile("Analog model-IP")
        features["fpga_final"] = True
    else:
        features["has_digital"] = "false"
    with pytest.raises(flow109.Flow109Error):
        flow109.resolve_plan(features)


def test_boolean_grammar_visits_hidden_unknowns_and_rejects_code():
    with pytest.raises(flow109.Flow109Error, match="FEATURE_UNRESOLVED"):
        flow109.predicate("always or omitted", {"always": True})
    with pytest.raises(flow109.Flow109Error, match="PREDICATE_INVALID"):
        flow109.predicate("open('unsafe')", {})


def test_analog_profile_cannot_be_forced_into_digital_default():
    features = profile("Analog hard-IP")
    plan = flow109.resolve_plan(features)
    assert flow109.resolve_step(plan, "D69")["selected_profile"] == "analog_die"
    assert flow109.resolve_step(plan, "D69")["profile"]["tools"] == "Magic.RCX"
    assert flow109.resolve_step(plan, "D69")["profile"]["native_steps"] == ["Magic.RCX"]
    with pytest.raises(flow109.Flow109Error, match="PROFILE_INAPPLICABLE"):
        flow109.resolve_plan(features, {"D69": "default"})


def test_odb_fill_is_not_aliased_to_legacy_gds_fill_pass():
    plan = flow109.resolve_plan(profile())
    fill = flow109.resolve_step(plan, "D62")
    assert fill["profile"]["entrypoint"]["command"] == "density_fill"
    assert fill["profile"]["geometry_format"] == "ODB"
    assert fill["profile"]["native_steps"] == [
        "OpenROAD.DensityFill", "OpenROAD.CheckMetalDensity",
        "OpenROAD.CheckFillObstructions"]
    window = flow109.resolve_execution_window(plan, "D62", "D62")
    assert window["native_step_id"] == "flow109.D62"
    assert window["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_density_fill"
    assert window["resolved_row"]["profile"]["dispatch"]["flow109_metrics_status"] == "IMPLEMENTED_D62_RUNTIME"
    final_extract = flow109.resolve_execution_window(plan, "D69", "D69")
    assert final_extract["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_final_extract"
    final_electrical = flow109.resolve_execution_window(plan, "D70", "D70")
    assert final_electrical["resolved_row"]["profile"]["dispatch"]["adapter"] == "flow109_final_electrical"
    continuation = flow109.resolve_execution_window(plan, "D38", "D41")
    assert [row["id"] for row in continuation["resolved_rows"]] == ["D38", "D39", "D40", "D41"]
    assert continuation["native_entry_step"] == "19"
    assert continuation["native_exit_step"] == "32"


def test_context_rejects_changed_tool_identity_and_changed_selection():
    plan = flow109.resolve_plan(profile())
    original = flow109.execution_context(plan, "D38", "D38", runtime_tool_uses=[],
                                         qualification_registry="input/qualifications.json")
    assert flow109.validate_execution_context(original) == original
    changed = copy.deepcopy(original)
    changed["runtime_tool_uses"].append({"use_id": "unrelated"})
    with pytest.raises(flow109.Flow109Error, match="CONTEXT_STALE"):
        flow109.validate_execution_context(changed)
    changed = copy.deepcopy(original)
    changed["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "21"
    changed["context_sha256"] = flow109.digest(
        {k: v for k, v in changed.items() if k != "context_sha256"})
    with pytest.raises(flow109.Flow109Error, match="CONTEXT_STALE"):
        flow109.validate_execution_context(changed)


def test_completion_audit_writer_stamps_only_validated_flow109_identity(
        tmp_path, monkeypatch):
    """The audit producer binds current flow identity to source, not omission."""
    import flow_compliance_check

    context = flow109.execution_context(flow109.resolve_plan(profile()),
                                        "D09", "D09")
    path = tmp_path / "flow109-context.json"
    path.write_text(json.dumps(context))
    monkeypatch.setenv("VIBEIC_FLOW109_CONTEXT", str(path))
    identity = flow_compliance_check._resolved_flow_identity()
    assert identity == {
        "schema": "vibeic.resolved-flow-identity.v1",
        "status": "RESOLVED",
        "flow_id": "109",
        "source": "VALIDATED_FLOW109_EXECUTION_CONTEXT",
        "context_sha256": context["context_sha256"],
        "registry_sha256": context["registry_sha256"],
        "planner_sha256": context["planner_sha256"],
    }

    changed = copy.deepcopy(context)
    changed["requested_step"] = "D11"
    path.write_text(json.dumps(changed))
    invalid = flow_compliance_check._resolved_flow_identity()
    assert invalid["status"] == "INVALID"
    assert invalid["flow_id"] is None


def test_default_public_cli_runs_flow109_and_emits_current_identity(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "vibe_ic_one_shot_runner.py")
    manifest = tmp_path / "manifest.json"
    features = profile("Low-power secure scan SoC")
    features["requires_functional_safety"] = True
    manifest.write_text(json.dumps({"features": features}))
    old = tmp_path / "reports" / "phase3_one_shot.json"
    old.parent.mkdir()
    old.write_text('{"verdict":"PASS","native_identity":"preserve"}\n')
    before = old.read_bytes()
    # Omit --flow deliberately: 109 is the public runtime, not an opt-in label
    # over the older route.
    command = [sys.executable, str(runner), str(tmp_path),
               "--flow109-manifest", str(manifest), "--flow109-plan-only", "--route", "ic", "--no-dashboard"]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path / "reports" / "flow109" / "plan.json").read_text())
    assert plan["flow_id"] == "109"
    identity = {row["id"]: row["position"] for row in plan["rows"]}
    expected = {"D09": 17, "D11": 19, "D13": 21,
                "D22": 34, "D23": 35, "D30": 42, "D50": 72}
    assert {key: identity.get(key) for key in expected} == expected
    assert plan["flow109_acceptance"] == "NOT_MEASURED"
    assert old.read_bytes() == before
    assert not (tmp_path / "reports" / "flow109" / "admission.json").exists()
    # Select an optional unmapped safety row explicitly: this digital profile's
    # D06 now has a native owner, so it is no longer a refusal case.
    unmapped = next(row['id'] for row in plan['rows'] if not row['profile'].get('dispatch'))
    result = subprocess.run([x for x in command if x != "--flow109-plan-only"]
                            + ["--entry-step", unmapped, "--exit-step", unmapped],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert "FLOW109_PRODUCER_UNIMPLEMENTED" in result.stderr
    assert old.read_bytes() == before
    # The implemented fill component still cannot launch without qualification.
    result = subprocess.run([x for x in command if x != "--flow109-plan-only"]
                            + ["--entry-step", "D62", "--exit-step", "D62"],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert "QUALIFICATION_RUNTIME_ABSENT" in result.stderr
    refusal = json.loads((tmp_path / "reports/flow109/admission.json").read_text())
    assert refusal["native_started"] is False
    assert old.read_bytes() == before


def test_obsolete_explicit_public_flow_refuses_before_project_access(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "vibe_ic_one_shot_runner.py")
    absent = tmp_path / "does-not-exist"
    result = subprocess.run(
        [sys.executable, str(runner), str(absent), "--flow", "70"],
        text=True, capture_output=True)
    assert result.returncode == 2
    assert "invalid choice: '70'" in result.stderr
    assert not absent.exists()


def test_real_front_door_selection_translates_only_the_named_component(tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile(), "runtime_tool_uses": [],
                                    "qualification_registry": "input/qualifications.json"}))
    observed = []
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    # This control observes the selection/dispatch contract only. Qualification
    # behavior itself is covered by the admission module's native controls.
    monkeypatch.setitem(sys.modules, "flow109_admission", SimpleNamespace(
        require_admission=lambda project, context: observed.append(context) or {"status": "PASS", "test_scope": "selection_only"}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest, flow109_plan_only=False,
                           execution_mode="default", entry_step="D38", exit_step="D38")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert args.entry_step == args.exit_step == "19"
    assert observed[0]["requested_step"] == "D38"
    context = json.loads(Path(__import__("os").environ[flow109.CONTEXT_ENV]).read_text())
    assert flow109.validate_execution_context(context) == observed[0]


def test_frontend_rows_route_stable_ids_to_existing_default_owner_sites():
    plan = flow109.resolve_plan(profile())
    expected = {
        "D01": ("D1", "phase1_one_shot_runner", "D1", "D1"),
        "D02": ("0.5ic", "phase1_one_shot_runner", "D1", "D1"),
        "D09": ("1", "design_one_shot_runner", "1", "1"),
        "D10": ("P0", "design_one_shot_runner", "1", "1"),
        "D11": ("2", "design_one_shot_runner", "2", "2"),
        "D12": ("3", "design_one_shot_runner", "2", "3"),
        "D13": ("4", "design_one_shot_runner", "4", "4"),
        "D14": ("5", "design_one_shot_runner", "4", "5"),
        "D19": ("7", "design_one_shot_runner", "7", "7"),
        "D20": ("8", "design_one_shot_runner", "8", "8"),
        "D25": ("13", "design_one_shot_runner", "11", "13"),
        "D26": ("10", "design_one_shot_runner", "10", "10"),
        "D30": ("14", "design_one_shot_runner", "14", "14"),
    }
    for row_id, values in expected.items():
        row = flow109.resolve_step(plan, row_id)
        dispatch = row["profile"]["dispatch"]
        assert dispatch["kind"] == "canonical_owner_window"
        assert (dispatch["native_step_id"], dispatch["owner_runner"],
                dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == values
        assert dispatch["native_step_id"] == row["legacy70"][0]["id"]
        expected_status = ("NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED" if row_id == "D11"
                           else "NATIVE_COMPONENT_ONLY_NOT_109_ACCEPTED")
        assert row["profile"]["execution_status"] == expected_status
        assert dispatch["flow109_metrics_status"] == "UNIMPLEMENTED"


def test_d24_routes_to_existing_default_dft_producer_and_consumer(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    plan = flow109.resolve_plan(features)
    row = flow109.resolve_step(plan, "D24")
    dispatch = row["profile"]["dispatch"]
    assert dispatch["kind"] == "canonical_owner_window"
    assert (dispatch["native_step_id"], dispatch["owner_runner"],
            dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == (
                "12", "design_one_shot_runner", "12", "12")
    assert dispatch["producer"] == (
        "design_one_shot_runner.py:_step_post_dft_optimization")
    assert dispatch["consumer"] == (
        "design_one_shot_runner retained Step 12 canonical acceptance")
    assert row["profile"]["execution_status"] == (
        "NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED")
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D24", exit_step="D24", container="")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("12", "12")
    owner = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert owner["owner_runner"] == "design_one_shot_runner"
    assert owner["native_step_id"] == "12"


def test_d23_routes_to_existing_default_dft_producer_and_consumer(tmp_path, monkeypatch):
    features = profile("Mapped soft-IP with prestitched scan")
    plan = flow109.resolve_plan(features)
    row = flow109.resolve_step(plan, "D23")
    dispatch = row["profile"]["dispatch"]
    assert dispatch["kind"] == "canonical_owner_window"
    assert (dispatch["native_step_id"], dispatch["owner_runner"],
            dispatch["owner_entry_step"], dispatch["owner_exit_step"]) == (
                "11", "design_one_shot_runner", "11", "11")
    assert dispatch["producer"] == (
        "design_one_shot_runner.py:_step_dft_insertion")
    assert dispatch["consumer"] == (
        "design_one_shot_runner retained Step 11 canonical acceptance")
    assert row["profile"]["execution_status"] == (
        "NATIVE_OWNER_WIRED_NOT_CASE_QUALIFIED")
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D23", exit_step="D23", container="")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("11", "11")
    owner = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert owner["owner_runner"] == "design_one_shot_runner"
    assert owner["native_step_id"] == "11"


def _step9_native_state(tmp_path, monkeypatch):
    import hashlib
    import vibe_ic_one_shot_runner as runner

    netlist = tmp_path / "phase2/stage2/synth/netlist.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top(input clk); endmodule\n")
    sha = hashlib.sha256(netlist.read_bytes()).hexdigest()
    folder = "phase2/stage2/9_current"
    record = tmp_path / "steps" / folder / "outputs.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({
        "status": "NOT_MEASURED",
        "canonical_pass": False,
        "outputs": [{"rel": "phase2/stage2/synth/netlist.v", "sha256": sha}],
    }))
    versions = SimpleNamespace(
        _read_index=lambda _p: {"steps": [{"id": "9", "folder": folder}]},
        _versions_root=lambda _p: tmp_path / "steps",
        _sha=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    )
    handoff = SimpleNamespace(bound_handoff=lambda _p: {
        "verdict": "PASS", "canonical": str(netlist), "mapped": str(netlist),
        "netlist_sha256": sha, "findings": [],
    })
    monkeypatch.setitem(sys.modules, "step_output_collector", versions)
    monkeypatch.setitem(sys.modules, "synth_handoff_netlist_check", handoff)
    return runner, netlist


def test_d23_accepts_current_native_step9_handoff_without_area_budget(
        tmp_path, monkeypatch):
    runner, _ = _step9_native_state(tmp_path, monkeypatch)

    current, error = runner._current_step9_checkpoint(tmp_path)

    assert error is None
    assert current["step9_record"]["status"] == "NOT_MEASURED"
    assert current["native_handoff"]["verdict"] == "PASS"


def test_d23_rejects_step9_handoff_after_netlist_bytes_change(tmp_path, monkeypatch):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    netlist.write_text("module changed; endmodule\n")

    current, error = runner._current_step9_checkpoint(tmp_path)

    assert current is None
    assert "no longer matches" in error


@pytest.mark.parametrize("case", ["noncanonical", "missing", "stale", "foreign"])
def test_d26_refuses_unbound_step9_before_prelayout_producer(
        tmp_path, monkeypatch, case):
    """A native handoff alone is not the current canonical D22 checkpoint."""
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name("top_synth.v")
    netlist.rename(mapped)
    import hashlib
    sha = hashlib.sha256(mapped.read_bytes()).hexdigest()
    record = next((tmp_path / "steps").rglob("outputs.json"))
    body = json.loads(record.read_text())
    body["outputs"][0]["sha256"] = sha
    record.write_text(json.dumps(body))
    sys.modules["synth_handoff_netlist_check"].bound_handoff = lambda _p: {
        "verdict": "PASS", "canonical": str(mapped), "mapped": str(mapped),
        "netlist_sha256": sha, "findings": [],
    }
    versions = sys.modules["step_output_collector"]
    if case == "missing":
        versions._read_index = lambda _p: {"steps": []}
    elif case == "noncanonical":
        versions.latest_pass = lambda *_a: None
    else:
        current = {**body, "folder": "phase2/stage2/9_current",
                   "current_inputs": case != "stale", "canonical_pass": True,
                   "status": "PASS", "result": {"canonical_consumer": {
                       "status": "PASS", "outputs": {"netlist": "foreign"}}}}
        versions.latest_pass = lambda *_a: current
        monkeypatch.setitem(sys.modules, "_flow_yaml", SimpleNamespace(
            load=lambda: {"steps": [{"id": "9"}]}))
        monkeypatch.setitem(sys.modules, "execution_backend_gates", SimpleNamespace(
            contracts=lambda *_a: {"netlist": "current"}))
    launched = []
    versions.current_acceptance = lambda *_a: [{
        "id": "10", "folder": "phase3/prelayout/10_current",
        "status": "PASS", "canonical_pass": True,
        "result": {"canonical_consumer": {"status": "PASS", "step": {
            "reasons": []}}}}]
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", SimpleNamespace(
        _phase2_pdk_config=lambda *_a: "neutral-pdk"))
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", SimpleNamespace(
        step_prelayout_signoff=lambda *a, **_k: launched.append(a) or SimpleNamespace(
            status="PASS", detail=f"{case} producer ran")))

    result = runner._complete_step10_prelayout(tmp_path, "top", "neutral", "")

    assert result["verdict"] == "NOT_MEASURED"
    expected = ("current Step9 native synthesis record" if case == "missing"
                else "current canonical Step9 checkpoint")
    assert expected in result["detail"]
    assert launched == []


def test_d26_current_canonical_step9_launches_prelayout_producer(
        tmp_path, monkeypatch):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name("top_synth.v")
    netlist.rename(mapped)
    sha = __import__("hashlib").sha256(mapped.read_bytes()).hexdigest()
    record = next((tmp_path / "steps").rglob("outputs.json"))
    body = json.loads(record.read_text())
    outputs = {"netlist": {"path": str(mapped), "sha256": sha}}
    body.update({"status": "PASS", "canonical_pass": True,
                 "current_inputs": True,
                 "outputs": [{"rel": "phase2/stage2/synth/netlist.v",
                              "sha256": sha}],
                 "result": {"canonical_consumer": {
                     "status": "PASS", "outputs": outputs}}})
    record.write_text(json.dumps(body))
    current = {**body, "folder": "phase2/stage2/9_current"}
    versions = sys.modules["step_output_collector"]
    versions.latest_pass = lambda *_a: current
    versions.current_acceptance = lambda *_a: [{
        "id": "10", "folder": "phase3/prelayout/10_current",
        "status": "PASS", "canonical_pass": True,
        "result": {"canonical_consumer": {"status": "PASS", "step": {
            "reasons": []}}}}]
    sys.modules["synth_handoff_netlist_check"].bound_handoff = lambda _p: {
        "verdict": "PASS", "canonical": str(mapped), "mapped": str(mapped),
        "netlist_sha256": sha, "findings": []}
    monkeypatch.setitem(sys.modules, "_flow_yaml", SimpleNamespace(
        load=lambda: {"steps": [{"id": "9"}]}))
    monkeypatch.setitem(sys.modules, "execution_backend_gates", SimpleNamespace(
        contracts=lambda *_a: outputs))
    launched = []
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", SimpleNamespace(
        _phase2_pdk_config=lambda *_a: "neutral-pdk"))
    monkeypatch.setitem(sys.modules, "phase3_one_shot_runner", SimpleNamespace(
        step_prelayout_signoff=lambda *a, **_k: launched.append(a) or SimpleNamespace(
            status="PASS", detail="canonical Step10 consumer PASS")))

    result = runner._complete_step10_prelayout(tmp_path, "top", "neutral", "")

    assert result["verdict"] == "PASS"
    assert launched == [(tmp_path, "top", "neutral-pdk", "")]


def test_d23_rejects_wrong_l20_before_scan_or_atpg_launch(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner

    mapped = tmp_path / "phase2/stage2/synth/top_synth.v"
    mapped.parent.mkdir(parents=True)
    mapped.write_text("module top(input clk); endmodule\n")
    monkeypatch.setattr(runner, "_current_step9_checkpoint",
                        lambda _p: ({"native_handoff": {"verdict": "PASS"}}, None))
    design = SimpleNamespace(
        derive_dft_clock_reset=lambda _p: ("clk", "rst", False),
        _step_dft_insertion=lambda *a, **k: pytest.fail(
            "wrong L20 must refuse before the native producer"),
    )
    atpg = SimpleNamespace(resolve_mapped_netlist=lambda *_a, **_k: (
        "phase2/stage2/synth/top_synth.v", "test"))
    scan = SimpleNamespace(
        count_flops=lambda _text: 64,
        load_l20_scan_contract=lambda *_a, **_k: (
            None, ["L20 length=63 does not match mapped-netlist flop count 64"]),
    )
    monkeypatch.setitem(sys.modules, "design_one_shot_runner", design)
    monkeypatch.setitem(sys.modules, "fault_atpg_run", atpg)
    monkeypatch.setitem(sys.modules, "fault_scan_chain_insert", scan)

    result = runner._complete_step11_dft(tmp_path, "top", "unused")

    assert result["verdict"] == "NOT_MEASURED"
    assert "length=63" in result["detail"]


@pytest.mark.parametrize("step,native", [("D23", "11"), ("D24", "12")])
@pytest.mark.parametrize("status", ["PASS", "FAIL", "NOT_MEASURED"])
def test_bounded_dft_owner_publishes_its_actual_selected_step_verdict(
        tmp_path, monkeypatch, step, native, status):
    import _delivery_route
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.setenv(flow109.ATTEMPT_ENV, "")
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step=step, exit_step=step, container="")
    assert flow109.prepare_front_door(args, tmp_path) is None

    result = runner._finish_selected_native_owner(
        tmp_path, native, {"verdict": status})

    published = json.loads((tmp_path / "reports/flow109/default_rows" /
                            f"{step}.json").read_text())
    assert result["default_row_status"] == published["default_row_status"] == status
    assert published["step_id"] == step
    assert published["completed"] is (status == "PASS")
    assert published["whole_flow_acceptance"] == "NOT_MEASURED"
    assert published["delivery_accepted"] is False


def test_bounded_owner_finish_does_not_change_legacy_execution(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner

    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    assert runner._finish_selected_native_owner(
        tmp_path, "11", {"verdict": "PASS"}) is None
    assert not (tmp_path / "reports/flow109/default_rows").exists()


def _d09_report_body(tmp_path, *, lint="PASS", reference="PASS", cdc="PASS"):
    """Create only producer evidence; the product path must add its binding."""
    rtl = tmp_path / "phase2/stage1/rtl/chip_top.sv"
    rtl.parent.mkdir(parents=True, exist_ok=True)
    rtl.write_text("module chip_top(input logic clk); endmodule\n")
    source_input = tmp_path / "input/spec.md"
    source_input.parent.mkdir(parents=True, exist_ok=True)
    source_input.write_bytes(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "flow109.json").read_bytes())
    evidence = []
    for name in ("crossing", "async_input", "reset_dep"):
        path = tmp_path / f"reports/phase2/cdc/{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"verdict": cdc}) + "\n")
        evidence.append(str(path.relative_to(tmp_path)))
    return {
        "project": str(tmp_path.resolve()),
        "verdict": "PASS",
        "declared_window": {"entry_step": "1", "exit_step": "4",
                            "dispatched_step_ids": ["1", "2", "3", "4"]},
        "steps": [
            {"name": "rtl_gen", "status": "PASS_WITH_WAIVERS",
             "extras": {"preserved": True, "rtl_provenance": "AUTHORED"}},
            {"name": "rtl_lint_tool", "status": lint, "extras": {}},
            {"name": "phase2_manifests", "status": "PASS",
             "output_files": evidence, "extras": {}},
            {"name": "reference_tb", "status": reference, "extras": {}},
        ],
    }


def _d09_owner_report(tmp_path, monkeypatch, *, lint="PASS", reference="PASS",
                      cdc="PASS"):
    """Issue the real child identity and let the existing writer bind it."""
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design
    import vibe_ic_one_shot_runner as runner

    report = _d09_report_body(
        tmp_path, lint=lint, reference=reference, cdc=cdc)
    out = tmp_path / "reports/orchestrator/phase2_one_shot.json"

    def child(command, *, env=None, **_kwargs):
        context = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        design._write_phase2_report(
            out, report, tmp_path, invocation_context=context)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)
    invocation = {}
    assert runner._run_phase(
        "D09 focused child", runner.PROGRAMS_DIR / "phase2_one_shot_runner.py",
        [str(tmp_path), "--entry-step", "1", "--exit-step", "4"],
        env=dict(os.environ), invocation=invocation) == 0
    report = json.loads(out.read_text())
    context = flow109.execution_context(flow109.resolve_plan(profile()),
                                        "D09", "D09")
    request = tmp_path / "d09-request.json"
    request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,
                       str(flow109._new_attempt(tmp_path, context)))
    return (runner, report,
            tmp_path / "phase2/stage1/rtl/chip_top.sv",
            tmp_path / "input/spec.md", invocation)


def test_d09_completion_requires_full_bound_owner_report_and_preserves_rtl(
        tmp_path, monkeypatch):
    runner, report, rtl, _, invocation = _d09_owner_report(tmp_path, monkeypatch)
    before = rtl.read_bytes()

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == "PASS"
    assert rtl.read_bytes() == before
    terminal = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) /
                           "result.json").read_text())
    assert terminal["default_row_status"] == "PASS"
    assert terminal["whole_flow_acceptance"] == "NOT_MEASURED"
    assert terminal["delivery_accepted"] is False
    component = terminal["components"][0]
    assert component["step_id"] == "D09"
    assert component["completed"] is True
    assert answer["evidence"]["rtl_inventory"][0]["path"] == "chip_top.sv"


@pytest.mark.parametrize("case,expected", [
    ("missing_lint", "NOT_MEASURED"),
    ("missing_handoff", "NOT_MEASURED"),
    ("lint_fail", "FAIL"),
    ("reference_fail", "FAIL"),
    ("cdc_fail", "FAIL"),
    ("changed_rtl", "NOT_MEASURED"),
    ("changed_input", "NOT_MEASURED"),
    ("foreign_report", "NOT_MEASURED"),
    ("stale_invocation", "NOT_MEASURED"),
    ("foreign_runner", "NOT_MEASURED"),
    ("foreign_attempt", "NOT_MEASURED"),
    ("foreign_native", "NOT_MEASURED"),
])
def test_d09_completion_fails_closed_on_missing_failed_or_foreign_evidence(
        tmp_path, monkeypatch, case, expected):
    runner, report, rtl, source_input, invocation = _d09_owner_report(
        tmp_path, monkeypatch,
        lint="FAIL" if case == "lint_fail" else "PASS",
        reference="FAIL" if case == "reference_fail" else "PASS",
        cdc="FAIL" if case == "cdc_fail" else "PASS")
    if case == "missing_lint":
        report["steps"] = [row for row in report["steps"]
                           if row["name"] != "rtl_lint_tool"]
    elif case == "missing_handoff":
        report["steps"][0]["extras"]["preserved"] = False
    elif case == "changed_rtl":
        rtl.write_text("module changed; endmodule\n")
    elif case == "changed_input":
        source_input.write_text("changed input\n")
    elif case == "foreign_report":
        report["runner_binding"]["project"] = str(tmp_path / "foreign")
    elif case == "stale_invocation":
        report["runner_binding"]["invocation_id"] = "0" * 32
    elif case == "foreign_runner":
        report["runner_binding"]["argv"][1] = str(tmp_path / "foreign.py")
    elif case == "foreign_attempt":
        monkeypatch.setenv(flow109.ATTEMPT_ENV, str(tmp_path / "foreign"))
    elif case == "foreign_native":
        context_path = Path(os.environ[flow109.CONTEXT_ENV])
        context = json.loads(context_path.read_text())
        context["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "2"
        context["context_sha256"] = flow109.digest(
            {key: value for key, value in context.items()
             if key != "context_sha256"})
        context_path.write_text(json.dumps(context))
    (tmp_path / "reports/orchestrator/phase2_one_shot.json").write_text(
        json.dumps(report, indent=2) + "\n")

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == expected
    assert answer["whole_flow_verdict"] == "NOT_MEASURED"


def test_d09_completion_does_not_overwrite_existing_attempt_result(
        tmp_path, monkeypatch):
    runner, report, _, _, invocation = _d09_owner_report(tmp_path, monkeypatch)
    result = Path(os.environ[flow109.ATTEMPT_ENV]) / "result.json"
    retained = b'{"immutable":"existing"}\n'
    result.write_bytes(retained)

    answer = runner._finish_d09_selected_owner(
        tmp_path, report, invocation, published_current=True)

    assert answer["verdict"] == "NOT_MEASURED"
    assert "FLOW109_ATTEMPT_RESULT_EXISTS" in answer["detail"]
    assert result.read_bytes() == retained


def _public_d09_entry(tmp_path, monkeypatch):
    """Configure the real public D09 entry with its separately-owned 1..4 span."""
    import _delivery_route
    import vibe_ic_one_shot_runner as runner

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    real_prepare = flow109.prepare_front_door

    def prepare_with_owned_span(args, project):
        result = real_prepare(args, project)
        if result is None:
            context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
            if context.get("requested_step") == "D09":
                args.exit_step = "4"
        return result

    monkeypatch.setattr(flow109, "prepare_front_door", prepare_with_owned_span)
    monkeypatch.setattr(
        runner._canonical_admission, "admit_span",
        lambda *_a, **_k: SimpleNamespace(admitted=True,
                                           identity_sha256="a" * 64))
    monkeypatch.setattr(
        runner._canonical_admission, "child_env",
        lambda _identity, env: dict(env))
    monkeypatch.setattr(sys, "argv", [
        str(Path(runner.__file__)), str(tmp_path), "--flow", "109",
        "--flow109-manifest", str(manifest), "--entry-step", "D09",
        "--exit-step", "D09", "--route", "ic", "--skip-phase1",
        "--skip-phase3", "--skip-analog", "--no-dashboard",
    ])
    return runner


def test_public_d09_entry_issues_child_binding_and_observes_terminal_result(
        tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design

    runner = _public_d09_entry(tmp_path, monkeypatch)
    body = _d09_report_body(tmp_path)
    report_path = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    issued = []

    def child(command, *, env=None, **_kwargs):
        context = json.loads(env[dispatch._RUNNER_CONTEXT_ENV])
        issued.append(context)
        design._write_phase2_report(
            report_path, body, tmp_path, invocation_context=context)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)

    assert runner._main() == 0

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    terminal = json.loads((attempt / "result.json").read_text())
    report = json.loads(report_path.read_text())
    summary = json.loads(
        (tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert len(issued) == 1
    assert report["runner_binding"]["invocation_id"] == issued[0]["invocation_id"]
    assert report["runner_binding"]["argv"] == issued[0]["argv"]
    assert terminal["default_row_status"] == "PASS"
    assert terminal["components"][0]["step_id"] == "D09"
    assert summary["d09_finalization"]["verdict"] == "PASS"
    assert summary["whole_flow_verdict"] == "NOT_MEASURED"


def test_public_d09_entry_refuses_stale_retained_report_invocation(
        tmp_path, monkeypatch):
    import benchmark_dispatch as dispatch
    import design_one_shot_runner as design

    runner = _public_d09_entry(tmp_path, monkeypatch)
    body = _d09_report_body(tmp_path)
    report_path = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    old_argv = [sys.executable, str(Path(runner.PROGRAMS_DIR) /
                "design_one_shot_runner.py"), str(tmp_path),
                "--entry-step", "1", "--exit-step", "4"]
    old_context = {
        "invocation_id": "0" * 32, "argv": old_argv,
        "project": str(tmp_path.resolve()),
        "source": dispatch._runner_source_snapshot(old_argv),
    }
    design._write_phase2_report(
        report_path, body, tmp_path, invocation_context=old_context)
    os.utime(report_path, (1, 1))
    launched = []

    def child(_command, *, env=None, **_kwargs):
        raw = (env or {}).get(dispatch._RUNNER_CONTEXT_ENV)
        launched.append(json.loads(raw) if raw else None)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)

    assert runner._main() == 1

    attempts = sorted((tmp_path / "reports/flow109/attempts").glob("window-*"))
    terminal = json.loads((attempts[-1] / "result.json").read_text())
    summary = json.loads(
        (tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert len(launched) == 1
    assert terminal["default_row_status"] == "NOT_MEASURED"
    assert terminal["components"][0]["completed"] is False
    assert summary["d09_finalization"]["verdict"] == "NOT_MEASURED"
    assert "D09_REPORT_UNBOUND" in summary["d09_finalization"]["detail"]
    assert launched[0]["invocation_id"] != old_context["invocation_id"]


@pytest.mark.parametrize("case,status,rc", [
    ("pass", "PASS", 0),
    ("producer_fail", "FAIL", 1),
    ("postcheck_not_measured", "NOT_MEASURED", 2),
])
def test_public_d26_owner_finalizes_selected_attempt(
        tmp_path, monkeypatch, case, status, rc):
    import _delivery_route
    import flow109
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    calls = []
    producer = "FAIL" if case == "producer_fail" else "PASS"
    monkeypatch.setattr(runner, "_complete_step10_prelayout",
                        lambda *_a, **_k: calls.append("producer") or {
                            "verdict": producer, "detail": case})
    monkeypatch.setattr(runner, "_complete_step8_postcheck",
                        lambda *_a, **_k: calls.append("postcheck") or {
                            "verdict": ("NOT_MEASURED"
                                        if case == "postcheck_not_measured" else "PASS"),
                            "detail": case})
    monkeypatch.setattr(sys, "argv", [str(Path(runner.__file__)), str(tmp_path),
                        "--flow", "109", "--flow109-manifest", str(manifest),
                        "--entry-step", "D26", "--exit-step", "D26",
                        "--route", "ip", "--no-dashboard"])

    assert runner._main() == rc

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    result = json.loads((attempt / "result.json").read_text())
    summary = json.loads((tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert result["schema"] == "vibeic.flow109.window-attempt-result.v1"
    assert result["default_row_status"] == status
    assert result["components"][0]["step_id"] == "D26"
    assert result["components"][0]["completed"] is (status == "PASS")
    assert summary["d26_finalization"]["verdict"] == status
    assert calls == (["producer"] if case == "producer_fail"
                     else ["producer", "postcheck"])


def test_public_d26_preexisting_attempt_result_is_not_overwritten(
        tmp_path, monkeypatch):
    import _delivery_route
    import flow109
    import vibe_ic_one_shot_runner as runner

    features = profile("Mapped soft-IP with prestitched scan")
    assert _delivery_route.admit(tmp_path, "ip") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    monkeypatch.setattr(runner, "_activate_runtime_program_tree", lambda _p: None)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_a, **_k: {
        "verdict": "PASS"})
    monkeypatch.setattr(runner, "_complete_step10_prelayout",
                        lambda *_a, **_k: {"verdict": "FAIL", "detail": "producer failed"})
    finish = flow109.finish_native_window
    retained = '{"immutable":"existing"}\n'
    def preexisting(project, report):
        result = Path(os.environ[flow109.ATTEMPT_ENV]) / "result.json"
        result.write_text(retained)
        return finish(project, report)
    monkeypatch.setattr(flow109, "finish_native_window", preexisting)
    monkeypatch.setattr(sys, "argv", [str(Path(runner.__file__)), str(tmp_path),
                        "--flow", "109", "--flow109-manifest", str(manifest),
                        "--entry-step", "D26", "--exit-step", "D26",
                        "--route", "ip", "--no-dashboard"])

    assert runner._main() == 2

    attempt = next((tmp_path / "reports/flow109/attempts").glob("window-*"))
    assert (attempt / "result.json").read_text() == retained
    summary = json.loads((tmp_path / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert summary["d26_finalization"]["verdict"] == "NOT_MEASURED"
    assert summary["d26_finalization"]["detail"].startswith(
        "D26_FINALIZATION_REFUSED: FLOW109_ATTEMPT_RESULT_EXISTS:")


def test_owner_route_uses_native_span_without_generic_qualification_registry(
        tmp_path, monkeypatch):
    # prepare_front_door intentionally installs the active request; restore
    # that environment at this control's boundary, like the older control.
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    monkeypatch.setitem(sys.modules, "flow109_admission", SimpleNamespace(
        require_admission=lambda *a, **k: pytest.fail("generic qualification must not run")))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D12", exit_step="D12")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("2", "3")
    route = json.loads((tmp_path / "reports/flow109/owner_route.json").read_text())
    assert route["owner_runner"] == "design_one_shot_runner"
    assert route["native_step_id"] == "3"
    assert route["component_status"] == route["flow109_acceptance"] == "NOT_MEASURED"
    request = json.loads(Path(__import__("os").environ[flow109.CONTEXT_ENV]).read_text())
    assert request["requested_step"] == "D12"
    assert request["resolved_row"]["id"] == "D12"
    assert request["context_sha256"] == route["context_sha256"]
    attempt_value = __import__("os").environ.get(
        flow109.ATTEMPT_ENV, "ATTEMPT_ENV_UNSET")
    assert Path(attempt_value).parent.name == "attempts"
    attempt = Path(attempt_value)
    immutable = json.loads((attempt / "request.json").read_text())
    assert immutable["context_sha256"] == request["context_sha256"]
    assert immutable["registry_sha256"] == request["registry_sha256"]
    assert immutable["planner_sha256"] == request["planner_sha256"]


@pytest.mark.parametrize("step, adapter, component_scope", [
    ("D45", "flow109_netlist_cdc", None),
    ("D69", "flow109_final_extract", "native_final_gds_floating_fill_component"),
    ("D70", "flow109_final_electrical", "final_sta_native_component_only"),
    ("D71", "flow109_final_gls", "final_sdf_gls_component_only"),
])
def test_registered_native_component_route_does_not_claim_generic_qualification(
        step, adapter, component_scope):
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, step)
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["adapter"] == adapter
    assert dispatch.get("component_scope") == component_scope
    if step == "D69":
        assert dispatch['engine_families'] == ['magic']
        assert dispatch['engine_steps'] == {'magic': ['vibeic-final-fill-spef extract']}
    context = flow109.execution_context(plan, step, step)
    admission = flow109.source_owned_native_admission(context)
    assert admission["admitted"] is True
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"
    claimed = flow109.execution_context(plan, step, step, runtime_tool_uses=[],
                                        qualification_registry="input/qualifications.json")
    assert flow109.source_owned_native_admission(claimed) is None
    assert flow109.source_owned_native_dispatch(flow109.resolve_step(plan, "D62")) is None


def test_final_native_window_reaches_real_missing_input_refusal_without_generic_claim(
        tmp_path, monkeypatch):
    import _delivery_route
    import flow109_admission

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, __import__("os").environ.get(name, ""))
        monkeypatch.delenv(name)
    monkeypatch.setattr(
        flow109_admission, "require_admission",
        lambda *a, **k: pytest.fail("generic qualification must remain unclaimed"))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D69", exit_step="D71")

    assert flow109.prepare_front_door(args, tmp_path) == 2
    d69 = json.loads((tmp_path / "reports/flow109/components/D69.json").read_text())
    assert d69["component_status"] == "NOT_MEASURED"
    assert d69["reason"] == "D69_REQUIRED_INPUT_ABSENT"
    assert d69["native_started"] is False
    assert not (tmp_path / "reports/flow109/components/D70.json").exists()
    assert not (tmp_path / "reports/flow109/components/D71.json").exists()
    attempt = next((tmp_path / "reports/flow109/attempts").iterdir())
    terminal = json.loads((attempt / "result.json").read_text())
    assert terminal["component_status"] == "NOT_MEASURED"
    assert terminal["flow109_acceptance"] == "NOT_MEASURED"
    assert terminal["whole_flow_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("step, reason", [
    ("D69", "D69_REQUIRED_INPUT_ABSENT"),
    ("D70", "D70_REQUIRED_INPUT_ABSENT"),
    ("D71", "D71_INPUT_INVALID"),
])
def test_final_native_single_entry_reaches_own_missing_input_refusal(
        tmp_path, monkeypatch, step, reason):
    import _delivery_route
    import flow109_admission

    assert _delivery_route.admit(tmp_path, "ic") is None
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": profile()}))
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, __import__("os").environ.get(name, ""))
        monkeypatch.delenv(name)
    monkeypatch.setattr(
        flow109_admission, "require_admission",
        lambda *a, **k: pytest.fail("generic qualification must remain unclaimed"))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step=step, exit_step=step)

    assert flow109.prepare_front_door(args, tmp_path) == 2
    component = json.loads(
        (tmp_path / f"reports/flow109/components/{step}.json").read_text())
    assert component["component_status"] == "NOT_MEASURED"
    assert component["reason"] == reason
    assert component["native_started"] is False
    admission_record = json.loads(
        (tmp_path / "reports/flow109/admission.json").read_text())
    assert admission_record["status"] == "NOT_APPLICABLE"
    assert admission_record["qualification_status"] == "NOT_CLAIMED"
    assert admission_record["flow109_acceptance"] == "NOT_MEASURED"


def test_unregistered_adapter_cannot_select_existing_native_policy():
    row = flow109.resolve_step(flow109.resolve_plan(profile()), "D45")
    row["profile"]["dispatch"]["adapter"] = "caller_plugin"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_forged_backend_owner_cannot_select_existing_native_policy():
    row = flow109.resolve_step(flow109.resolve_plan(profile()), "D31")
    row["profile"]["dispatch"]["native_step_id"] = "caller-step"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d34_clock_planning_registers_real_special_owner_and_strict_claim_path():
    import flow109_clock_plan

    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D34")
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["native_step_id"] == "flow109.D34"
    assert dispatch["adapter"] == "flow109_clock_plan"
    assert dispatch["admission_policy"] == "source_owned_existing_native"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert flow109_clock_plan._consumer_row()["id"] == 16
    sources = flow109_clock_plan.operation_sources()
    assert "programs/phase3_one_shot_runner.py" in sources
    assert "programs/_physical_current.py" in sources
    assert "programs/clock_plan_check.py" in sources
    context = flow109.execution_context(plan, "D34", "D34")
    admission = flow109.source_owned_native_admission(context)
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"
    claimed = flow109.execution_context(
        plan, "D34", "D34", runtime_tool_uses=[],
        qualification_registry="input/qualifications.json")
    assert flow109.source_owned_native_admission(claimed) is None

    row["profile"]["dispatch"]["adapter"] = "flow109_missing_clock_owner"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d44_retained_lec_registers_only_existing_native_admission_fields():
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D44")
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch["adapter"] == "flow109_final_lec"
    assert dispatch["native_step_id"] == "flow109.D44"
    assert dispatch["admission_policy"] == "source_owned_existing_native"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    context = flow109.execution_context(plan, "D44", "D44")
    admission = flow109.source_owned_native_admission(context)
    assert admission["status"] == "NOT_APPLICABLE"
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"

    del row["profile"]["dispatch"]["acceptance_scope"]
    with pytest.raises(flow109.Flow109Error, match="FLOW109_NATIVE_OWNER_INVALID"):
        flow109.source_owned_native_dispatch(row)


def test_d63_routes_only_to_current_canonical_default35_owner():
    plan = flow109.resolve_plan(profile())
    row = flow109.resolve_step(plan, "D63")
    dispatch = flow109.source_owned_native_dispatch(row)

    assert row["profile"]["execution_status"] == "NATIVE_COMPONENT_ONLY_NOT_109_ACCEPTED"
    assert dispatch["kind"] == "canonical_backend_window"
    assert dispatch["native_step_id"] == "35"
    assert dispatch["producer"] == "execution_backend_producers.py:produce"
    assert dispatch["consumer"] == "execution_backend_gates.py:evaluate"
    assert dispatch["native_required_outputs"] == ["reports/phase3/dfm_screen.json"]
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert dispatch["flow109_metrics_status"] == "UNIMPLEMENTED"
    assert row["metric_acceptance_status"] == "UNIMPLEMENTED"
    assert row["gate_matrix_status"] == "NOT_MEASURED_FOR_109"

    context = flow109.execution_context(plan, "D63", "D63")
    admission = flow109.source_owned_native_admission(context)
    assert admission["admitted"] is True
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["flow109_acceptance"] == "NOT_MEASURED"

    context["resolved_row"]["profile"]["dispatch"]["native_step_id"] = "34"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_CONTEXT_STALE"):
        flow109.validate_execution_context(context)


def test_owner_route_refuses_wrong_owner_and_unknown_native_mapping():
    plan = flow109.resolve_plan(profile())
    row = next(item for item in plan["rows"] if item["id"] == "D12")
    row["profile"]["dispatch"]["owner_runner"] = "phase1_one_shot_runner"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_OWNER_MISMATCH"):
        flow109.resolve_execution_window(plan, "D12", "D12")
    plan = flow109.resolve_plan(profile())
    row = next(item for item in plan["rows"] if item["id"] == "D12")
    row["profile"]["dispatch"]["native_step_id"] = "12"
    with pytest.raises(flow109.Flow109Error, match="FLOW109_OWNER_NATIVE_MAPPING_UNKNOWN"):
        flow109.resolve_execution_window(plan, "D12", "D12")


def test_frontend_owner_window_preserves_existing_indivisible_spans():
    window = flow109.resolve_execution_window(flow109.resolve_plan(profile()), "D09", "D14")
    assert window["dispatch_kind"] == "canonical_owner_window"
    assert [row["id"] for row in window["resolved_rows"]] == [
        "D09", "D10", "D11", "D12", "D13", "D14"]
    assert (window["native_entry_step"], window["native_exit_step"]) == ("1", "5")

# Native completion is an owner answer, separate from whole-flow acceptance.
@pytest.mark.parametrize('component,status,completed,expected', [
    ('PASS','PASS',True,'PASS'), ('PASS','PASS',False,'NOT_MEASURED'),
    ('PASS',None,True,'NOT_MEASURED'), ('FAIL','PASS',True,'FAIL'),
    ('NOT_MEASURED','PASS',True,'NOT_MEASURED'), ('PASS','FAIL',False,'FAIL')])
def test_selected_native_completion_is_not_blanket_component_pass(
        tmp_path, component, status, completed, expected):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    result = {'step_id':'D11','context_sha256':context['context_sha256'],
              'component_status':component,'completed':completed}
    if status is not None: result['default_row_status'] = status
    answer = flow109._selected_step_result(tmp_path, context, result)
    assert answer['default_row_status'] == expected
    assert answer['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert answer['delivery_accepted'] is False


@pytest.mark.parametrize('field,value', [
    ('step_id','foreign'), ('context_sha256','foreign'),
    ('whole_flow_acceptance','PASS'), ('delivery_accepted',True)])
def test_selected_native_completion_rejects_foreign_identity_and_whole_claims(tmp_path,field,value):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    result = {'step_id':'D11','context_sha256':context['context_sha256'],
              'component_status':'PASS','default_row_status':'PASS','completed':True}
    result[field] = value
    with pytest.raises(flow109.Flow109Error, match='FLOW109_COMPONENT_RESULT_INVALID'):
        flow109._selected_step_result(tmp_path, context, result)
    assert not (tmp_path/'reports/flow109/default_rows/D11.json').exists()


def test_selected_native_completion_empty_is_not_a_result(tmp_path):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    with pytest.raises(flow109.Flow109Error, match='FLOW109_COMPONENT_RESULT_INVALID'):
        flow109._selected_step_result(tmp_path, context, {})


def test_selected_completion_consumer_is_not_limited_to_a_row_allowlist(tmp_path):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D11', 'D11')
    calls=[]
    def consume(project, request, component):
        calls.append(request['requested_step'])
        return {'step_id':'D11','context_sha256':request['context_sha256'],
                'default_row_status':'PASS','completed':True}
    answer=flow109._selected_step_result(tmp_path,context,
        {'step_id':'D11','context_sha256':context['context_sha256'],
         'component_status':'PASS','flow109_acceptance':'NOT_MEASURED'},
        SimpleNamespace(consume_default_row_completion=consume))
    assert calls==['D11'] and answer['default_row_status']=='PASS'


@pytest.mark.parametrize('native,status,completed,expected', [
    ('2','PASS',True,'PASS'), ('2','PASS',False,'NOT_MEASURED'),
    ('2','FAIL',False,'FAIL'), ('foreign','PASS',True,'NOT_MEASURED')])
def test_owner_finish_uses_only_selected_completed_native_result(
        tmp_path, monkeypatch, native,status,completed,expected):
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D11','D11')
    request=tmp_path/'request.json';request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    report={'steps':[{'status':status,'extras':{'step_id':native,
        'context_sha256':context['context_sha256'],
        'default_row_status':status,'completed':completed}}]}
    result=flow109.finish_native_window(tmp_path,report)
    assert result['default_row_status']==expected
    assert result['whole_flow_acceptance']=='NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_owner_finish_rejects_stale_context_and_empty_report(tmp_path,monkeypatch):
    context=flow109.execution_context(flow109.resolve_plan(profile()),'D11','D11')
    request=tmp_path/'request.json';request.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV,str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    report={'steps':[{'status':'PASS','extras':{'step_id':'2',
        'context_sha256':'foreign','default_row_status':'PASS','completed':True}}]}
    with pytest.raises(flow109.Flow109Error,match='FLOW109_CONTEXT_STALE'):
        flow109.finish_native_window(tmp_path,report)
    monkeypatch.setenv(flow109.ATTEMPT_ENV,str(flow109._new_attempt(tmp_path,context)))
    assert flow109.finish_native_window(tmp_path,{'steps':[]})['default_row_status']=='NOT_MEASURED'
    context['context_sha256']='stale';request.write_text(json.dumps(context))
    assert flow109.finish_native_window(tmp_path,report) is None


def test_selected_lint_window_stops_at_its_own_step():
    window=flow109.resolve_execution_window(flow109.resolve_plan(profile()),'D11','D11')
    assert window['resolved_row']['profile']['dispatch']['owner_exit_step']=='2'
