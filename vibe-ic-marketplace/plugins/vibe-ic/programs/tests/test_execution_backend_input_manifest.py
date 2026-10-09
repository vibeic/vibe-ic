from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_backend_worker as worker
from execution_adapters_backend import (
    ROWS,
    _backend_input_contract,
    backend_project_input_contract as policy_backend_contract,
)
import execution_policy as policy
import _flow_yaml


def test_resolve_input_contract_aggregates_all_missing_declarations(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    declarations = [
        {"path": "phase2/stage2/synth/missing_a.v"},
        {"path": "reports/phase2/gates/missing_b.json"},
    ]

    assert worker.resolve_input_contract(project, declarations) == [
        "phase2/stage2/synth/missing_a.v",
        "reports/phase2/gates/missing_b.json",
    ]


def test_execute_missing_manifest_inputs_does_not_call_native_producer(
        tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    (inputs / "project").mkdir(parents=True)
    outputs = tmp_path / "outputs"
    declarations = [
        {"path": "phase2/stage2/synth/missing_a.v"},
        {"path": "reports/phase2/gates/missing_b.json"},
    ]
    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, params: calls.append("produce"))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))

    result = worker.execute(
        inputs, outputs, step_id="15",
        params={"resolved_input_manifest": {
            "declarations": declarations, "files": {}, "missing": []}})

    assert set(result["missing_inputs"]) == {
        "phase2/stage2/synth/missing_a.v",
        "reports/phase2/gates/missing_b.json",
    }
    assert calls == []


def test_manifest_hash_mismatch_is_fail_closed(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    project = inputs / "project"
    project.mkdir(parents=True)
    artifact = project / "phase2/stage2/synth/netlist.v"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("module top; endmodule\n")
    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, params: calls.append("produce"))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))

    result = worker.execute(
        inputs, tmp_path / "outputs", step_id="15",
        params={"resolved_input_manifest": {
            "declarations": [{"path": "phase2/stage2/synth/netlist.v"}],
            "files": {"phase2/stage2/synth/netlist.v": "0" * 64},
            "missing": [],
        }})

    assert "phase2/stage2/synth/netlist.v" in result["missing_inputs"]
    assert result["verdict"] == "NOT_MEASURED"
    assert calls == []


def test_malformed_manifest_schema_does_not_call_producer_or_consumer(
        tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    (inputs / "project").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, params: calls.append("produce"))
    monkeypatch.setattr(worker, "evaluate",
                        lambda project, row: calls.append("evaluate"))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))

    result = worker.execute(
        inputs, tmp_path / "outputs", step_id="15",
        params={"resolved_input_manifest": {
            "declarations": None, "files": {}, "missing": []}})

    assert result["missing_inputs"] == ["resolved_input_manifest"]
    assert result["verdict"] == "NOT_MEASURED"
    assert calls == []


def test_manifest_accepts_pathless_external_check_none_declaration():
    assert worker._valid_resolved_manifest({
        "declarations": [{
            "from": "external", "check": "none",
            "what": "the PDK device models / tech decks",
        }],
        "files": {}, "missing": [],
    })


def test_manifest_accepts_numeric_upstream_step_declaration():
    assert worker._valid_resolved_manifest({
        "declarations": [{
            "from": 12, "path": "phase2/stage2/synth/netlist.v",
        }],
        "files": {}, "missing": [],
    })


@pytest.mark.parametrize("forged", [
    {"declarations": [], "files": {}, "missing": []},
    {"declarations": [{"path": "missing.v", "required": False}],
     "files": {}, "missing": []},
])
def test_public_registration_never_transports_caller_manifest(
        tmp_path, monkeypatch, forged):
    """Only the issuer dispatch seam may bind a worker manifest."""
    from execution_adapters_backend import register_backend_adapters
    from execution_provider_catalog import current_source_identity

    registry = register_backend_adapters(
        source_sha=current_source_identity(), available=False,
        parameters={"resolved_input_manifest": forged})
    argv = registry.adapters("15")[0].components[0].argv
    params = json.loads(argv[argv.index("--params-json") + 1])
    assert params["resolved_input_manifest"] is None

    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, value: calls.append("produce"))
    monkeypatch.setattr(worker, "evaluate",
                        lambda project, row: calls.append("evaluate"))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))
    inputs = tmp_path / "inputs"
    (inputs / "project").mkdir(parents=True)
    result = worker.execute(inputs, tmp_path / "outputs", step_id="15", params=params)
    assert result["missing_inputs"] == ["resolved_input_manifest"]
    assert result["verdict"] == "NOT_MEASURED"
    assert calls == []


def test_backend_manifest_transport_rebinds_and_restores_component_argv():
    @dataclass(frozen=True)
    class FakeComponent:
        argv: tuple[str, ...]

    @dataclass(frozen=True)
    class FakeArm:
        arm_id: str
        components: tuple[FakeComponent, ...]

    original_argv = (
        "/usr/bin/python3", "execution_backend_worker.py", "{inputs}",
        "{outputs}", "--step-id", "15", "--params-json",
        json.dumps({"pdk_name": "gf180mcuD"}, sort_keys=True),
    )
    arm = FakeArm("backend_15", (FakeComponent(original_argv),))

    class FakeRegistry:
        def __init__(self):
            self._adapters = {arm.arm_id: arm}

        def adapters(self, step_id):
            return [self._adapters[arm.arm_id]] if str(step_id) == "15" else []

    registry = FakeRegistry()
    runtime = {"registry": registry}
    manifest = {
        "declarations": [{"from": 12, "path": "phase2/stage2/synth/netlist.v"}],
        "files": {"phase2/stage2/synth/netlist.v": "a" * 64},
        "missing": [],
    }

    with policy._backend_manifest_parameters(runtime, "15", manifest):
        current = registry.adapters("15")[0].components[0].argv
        encoded = json.loads(current[current.index("--params-json") + 1])
        assert encoded["resolved_input_manifest"] == manifest
        assert encoded["resolved_input_manifest"]["declarations"][0]["from"] == 12

    assert registry.adapters("15")[0].components[0].argv == original_argv


def test_directory_declaration_requires_nonempty_contained_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    template = project / "input/submission_template"
    template.mkdir(parents=True)
    (template / "README.md").write_text("template\n")
    assert worker.resolve_input_contract(
        project, ["input/submission_template"]) == []

    empty = project / "input/empty_template"
    empty.mkdir()
    assert worker.resolve_input_contract(
        project, ["input/empty_template"]) == ["input/empty_template"]


def test_issuer_manifest_aggregates_missing_row_inputs_before_dispatch(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()

    class EmptyRegistry:
        def adapters(self, step_id):
            return []

    monkeypatch.setattr(_flow_yaml, "load", lambda: {"steps": [{
        "id": "15",
        "required_inputs": [
            {"from": "external", "path": "phase2/stage2/synth/missing_a.v"},
            {"from": "external", "path": "reports/phase2/gates/missing_b.json"},
        ],
    }]})
    parameters = {}
    files = policy._fixed_inputs(
        {"project": project, "registry": EmptyRegistry()}, "15",
        parameters=parameters)

    assert files == {}
    assert set(parameters["resolved_input_manifest"]["missing"]) >= {
        "phase2/stage2/synth/missing_a.v",
        "reports/phase2/gates/missing_b.json",
        "input/submission_template",
    }


def test_optional_backend_consumer_edges_preserve_present_files_and_empty_waivers(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    optional = {
        "phase3/librelane_switch.json": b'{"mode":"librelane"}\n',
        "waivers.json": b'{"waived_steps":[]}\n',
        "input/pdk/liberty/sky.lib": b"library sky {}\n",
    }
    monkeypatch.setattr(_flow_yaml, "load", lambda: {"steps": [{
        "id": "15", "required_inputs": [],
    }]})
    static_contract = _backend_input_contract("15", ROWS["15"])

    class Registry:
        def adapters(self, step_id):
            return [SimpleNamespace(input_contract=static_contract)]

    absent = policy_backend_contract(project, "15")
    assert not (set(optional) & set(absent))
    (project / "waivers.json").write_bytes(b"")
    # An existing empty waiver file is malformed input.  Keep it in the
    # consumer population so flow_compliance_check's schema gate rejects it;
    # treating it as absent would synthesize a different waiver set.
    assert "waivers.json" in policy_backend_contract(project, "15")
    from flow_compliance_check import _load_waivers
    with pytest.raises(SystemExit):
        _load_waivers(project)
    (project / "waivers.json").unlink()
    absent_parameters = {}
    policy._fixed_inputs(
        {"project": project, "registry": Registry()}, "15",
        parameters=absent_parameters)
    absent_manifest = absent_parameters["resolved_input_manifest"]
    absent_strings = {item for item in absent_manifest["declarations"]
                      if isinstance(item, str)}
    assert not (set(optional) & absent_strings)
    assert not (set(optional) & set(absent_manifest["missing"]))

    for raw, data in optional.items():
        path = project / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    present = policy_backend_contract(project, "15")
    present_paths = {
        item if isinstance(item, str) else item.get("path")
        for item in present
    }
    assert set(optional) <= present_paths
    present_parameters = {}
    present_files = policy._fixed_inputs(
        {"project": project, "registry": Registry()}, "15",
        parameters=present_parameters)
    assert set(optional) <= set(present_files)
    present_declaration_paths = {
        item if isinstance(item, str) else item.get("path")
        for item in present_parameters["resolved_input_manifest"]["declarations"]
    }
    assert set(optional) <= present_declaration_paths

    inputs = tmp_path / "inputs/project"
    outputs = tmp_path / "outputs"
    for raw in optional:
        target = inputs / raw
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / raw, target)
    manifest = {
        "declarations": [{"path": raw} for raw in optional],
        "files": {raw: worker.sha(inputs / raw) for raw in optional},
        "missing": [],
    }
    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, params: calls.append("produce") or {
                            "verdict": "NOT_MEASURED",
                            "current_step_declared_producers": {
                                "verdict": "PRODUCED", "population": 1,
                                "results": [{"rc": 0, "executed": True,
                                             "target_exists_after": True,
                                             "authorship": "producer"}]}})
    monkeypatch.setattr(worker, "evaluate",
                        lambda project, row: calls.append("evaluate") or {
                            "status": "NOT_MEASURED", "ledger": []})
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))
    result = worker.execute(
        tmp_path / "inputs", outputs, step_id="15",
        params={"resolved_input_manifest": manifest})
    assert result["missing_inputs"] == []
    assert set(result["resolved_input_manifest"]["files"]) == set(optional)
    assert calls == ["produce", "evaluate"]


def test_issuer_and_worker_share_zero_byte_missing_contract(tmp_path, monkeypatch):
    """Issuer and worker agree on ordinary zero bytes but preserve waivers."""
    project = tmp_path / "project"
    project.mkdir()
    ordinary = project / "phase2/stage2/synth/fsm_encoding.enc"
    ordinary.parent.mkdir(parents=True)
    ordinary.write_bytes(b"")
    (project / "waivers.json").write_bytes(b"")
    monkeypatch.setattr(_flow_yaml, "load", lambda: {"steps": [{
        "id": "15", "required_inputs": [],
    }]})

    class Registry:
        def adapters(self, step_id):
            return [SimpleNamespace(input_contract=(str(ordinary.relative_to(project)),))]

    parameters = {}
    files = policy._fixed_inputs(
        {"project": project, "registry": Registry()}, "15",
        parameters=parameters)
    manifest = parameters["resolved_input_manifest"]
    ordinary_raw = str(ordinary.relative_to(project))
    assert ordinary_raw in files and ordinary_raw in manifest["files"]
    assert "waivers.json" in files and "waivers.json" in manifest["files"]
    assert ordinary_raw in manifest["missing"]
    assert "waivers.json" not in manifest["missing"]

    inputs = tmp_path / "inputs/project"
    outputs = tmp_path / "outputs"
    for raw, source in files.items():
        target = inputs / raw
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    calls = []
    monkeypatch.setattr(worker, "produce",
                        lambda project, params: calls.append("produce"))
    monkeypatch.setattr(worker, "evaluate",
                        lambda project, row: calls.append("evaluate"))
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [],
    }))
    result = worker.execute(
        tmp_path / "inputs", outputs, step_id="15",
        params={"resolved_input_manifest": manifest})
    assert result["missing_inputs"] == manifest["missing"]
    assert ordinary_raw in result["missing_inputs"]
    assert "waivers.json" not in result["missing_inputs"]
    assert calls == []


@pytest.mark.parametrize("omitted, empty", [
    ((), None),
    (("required_a.v", "required_b.v"), None),
    (("required_b.v",), "required_a.v"),
], ids=["complete", "two_missing", "zero_byte_and_missing"])
def test_explicit_backend_dispatch_uses_exact_population_and_blocks_missing(
        tmp_path, monkeypatch, omitted, empty):
    """Explicit inputs use the issuer contract before the Controller seam."""
    import execution_modes as em

    project = tmp_path / "project"
    project.mkdir()
    present_a = project / "required_a.v"
    present_b = project / "required_b.v"
    present_a.write_text("module a; endmodule\n")
    present_b.write_text("module b; endmodule\n")
    for name in ("input/step_0_5ic_answers.json",
                 "input/submission_template/README.md", "reports/prior.json"):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    monkeypatch.setattr(_flow_yaml, "load", lambda: {"steps": [
        {"id": 12, "required_outputs": ["required_a.v", "required_b.v"]},
        {"id": "15", "required_inputs": [{"from": 12, "outputs": "all"}]},
    ]})
    monkeypatch.setattr(em, "_verify_route_authority", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(em, "_git_source_authority", lambda *_args: ("commit", "tree"))
    producer_calls, consumer_calls = [], []

    def produce(project, params):
        producer_calls.append(project)
        return {"verdict": "NOT_MEASURED", "detail": "mock producer boundary",
                'current_step_declared_producers': {
                    'verdict': 'PRODUCED', 'population': 1, 'results': [{
                        'rc': 0, 'executed': True, 'target_exists_after': True,
                        'authorship': 'producer'}]}}

    def evaluate(project, row):
        consumer_calls.append(project)
        return {"status": "NOT_MEASURED", "ledger": []}

    monkeypatch.setattr(worker, "produce", produce)
    monkeypatch.setattr(worker, "evaluate", evaluate)
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({"required_gates": []}))

    @dataclass(frozen=True)
    class FakeComponent:
        argv: tuple[str, ...]

    @dataclass(frozen=True)
    class FakeArm:
        arm_id: str
        tool_id: str
        applicability: str
        objective: dict
        input_contract: tuple
        components: tuple[FakeComponent, ...]

    original_argv = (
        "python3", "execution_backend_worker.py", "--params-json",
        json.dumps({"resolved_input_manifest": None}, sort_keys=True),
    )
    arm = FakeArm("backend_15", "backend-worker", "applicable",
                  {"metric": "source_boundary"}, ("reports/prior.json",),
                  (FakeComponent(original_argv),))

    class FakeRegistry:
        def __init__(self):
            self._adapters = {arm.arm_id: arm}

        def adapters(self, step_id):
            return [self._adapters[arm.arm_id]] if str(step_id) == "15" else []

    class FakeController:
        def __init__(self, registry):
            self.registry = registry
            self.calls = []
            self.seen_manifests = []
            self.worker_results = []
            self.portfolio = {"steps": [{
                "id": "15", "mandatory_gate_programs": ("manifest_gate",),
            }]}

        def run(self, context, run, mode):
            self.calls.append((context, run, mode))
            argv = self.registry.adapters("15")[0].components[0].argv
            params = json.loads(argv[argv.index("--params-json") + 1])
            self.seen_manifests.append(params.get("resolved_input_manifest"))
            staged = run / "inputs"
            for name, source in context.inputs.items():
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            self.worker_results.append(worker.execute(
                staged, run / "outputs", step_id="15", params=params))
            return {"status": "NOT_MEASURED", "candidate_statuses": {}}

    registry = FakeRegistry()
    controller = FakeController(registry)
    route = {
        "kind": "issued-route", "schema": 1, "ic_ip_path": "IC",
        "source_sha": "a" * 40, "project_digest": "b" * 64,
        "request_digest": "c" * 64, "intent_label": "PROGRAM_DEFAULT",
        "mode_intent": "default",
    }
    route["route_digest"] = em._hash(route)
    monkeypatch.setattr(policy, "controller_fields", lambda **_kwargs: {
        "ic_ip_path": "IC", "route_receipt": route,
        "intent_label": "PROGRAM_DEFAULT", "request_digest": route["request_digest"],
    })
    runtime = {
        "project": project.resolve(), "registry": registry,
        "controller": controller, "route": route,
        "policy": {"mode": "default", "mode_label": "default-mode",
                    "request_receipt": {"invocation_id": "manifest-test"}},
        "parameters": {}, "contexts": {}, "bindings": {}, "runs": {},
    }
    monkeypatch.setattr(policy, "_ordinary_runtime", runtime)
    issued_params = {}
    complete = policy._fixed_inputs(runtime, "15", parameters=issued_params)
    assert issued_params["resolved_input_manifest"]["missing"] == []
    assert {"required_a.v", "required_b.v"} <= set(complete)
    supplied = {name: path for name, path in complete.items() if name not in omitted}
    expected_missing = set(omitted)
    if empty:
        supplied[empty].write_bytes(b"")
        expected_missing.add(empty)
        explicit_params = {}
        assert policy._manifest_for_explicit_inputs(
            runtime, "15", explicit_params, supplied) == supplied
        manifest = explicit_params["resolved_input_manifest"]
        assert manifest["files"][empty] == worker.sha(supplied[empty])
        assert set(manifest["missing"]) == expected_missing
    result = policy.dispatch_fixed_step(
        project, "15", inputs=supplied, parameters={"resolved_input_manifest": None})
    assert result["status"] == "NOT_MEASURED"
    if expected_missing:
        # Ambient project files still exist: only the supplied population counts.
        assert present_a.is_file() and present_b.is_file()
        assert controller.calls == []
        assert producer_calls == consumer_calls == []
        assert result["reason"] == "ORDINARY_INPUT_ABSENT"
        assert set(result["missing_inputs"]) == expected_missing
        assert runtime["contexts"] == runtime["runs"] == {}
    else:
        assert len(controller.calls) == len(producer_calls) == len(consumer_calls) == 1
        assert controller.calls[0][0].inputs == supplied
        assert controller.seen_manifests == [issued_params["resolved_input_manifest"]]
        assert controller.worker_results[0]["missing_inputs"] == []
        assert controller.worker_results[0]["resolved_input_manifest"] == (
            issued_params["resolved_input_manifest"])
    assert registry.adapters("15")[0].components[0].argv == original_argv
