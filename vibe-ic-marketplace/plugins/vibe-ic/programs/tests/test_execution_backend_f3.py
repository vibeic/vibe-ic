from __future__ import annotations

import json
from contextlib import contextmanager
import os
import shutil
import uuid
from pathlib import Path
import subprocess
import sys
from dataclasses import asdict, replace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_modes as em
from programs.tests._execution_source_fixture import register_source_fixture, issued_context
from programs.tests.test_execution_receipt_chain import isolated_transport
from execution_adapters_backend import (
    _step30_simulators,
    _step37_route_specs,
    _site_path,
    register_backend_adapters,
    _backend_input_contract,
    backend_project_input_contract,
    validate,
    validate_streamout_receipt,
)
from execution_backend_worker import resolve_input_contract
from synth_handoff_netlist_check import _project_path_resolver
import execution_backend_consumer
from execution_provider_catalog import BACKEND_IDS, coverage_rows, coverage_table, current_source_identity

BASE = current_source_identity()
PRE_FIX_BASE = "59cd75606885b71ca7d11bbe34baf2541671be68"


def test_pre_fix_base_could_not_reach_backend_factory(tmp_path):
    path = "vibe-ic-marketplace/plugins/vibe-ic/programs/execution_adapters_backend.py"
    assert subprocess.run(["git", "cat-file", "-e", f"{PRE_FIX_BASE}:{path}"]).returncode != 0
    proc = subprocess.run([sys.executable, "-c", "import execution_adapters_backend"],
                          cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
                          text=True, capture_output=True)
    assert proc.returncode != 0
    assert "ModuleNotFoundError" in proc.stderr


def test_all_backend_rows_register_one_reachable_provider():
    registry = register_backend_adapters(source_sha=BASE, available=True)
    assert tuple(a.step_id for a in registry._adapters.values()) == BACKEND_IDS
    assert all(len(registry.adapters(step)) == 1 for step in BACKEND_IDS)
    assert all(a.role == "producer" for a in registry._adapters.values())
    assert all(a.qualification_evidence.endswith(".py") or "producer site=" in a.qualification_evidence
               for a in registry._adapters.values())


def test_machine_readable_owned_coverage_has_exact_dispositions():
    table = coverage_table()
    assert table["row_count"] == 37
    assert table["backend_row_count"] == 23
    assert table["release_row_count"] == 14
    assert sum(row["disposition"] == "implemented" for row in table["rows"]) == 31
    assert sum(row["disposition"] == "unavailable" for row in table["rows"]) == 1
    assert sum(row["disposition"] == "external" for row in table["rows"]) == 5
    assert {row["step_id"] for row in table["rows"]} == set(BACKEND_IDS) | {
        "14", "16", "35", "36", "37.4", "37.5ip", "37.5ic", "38", "39",
        "40", "41", "42", "43", "44"}


def test_default_call_path_is_source_only_and_unmeasured():
    registry = register_backend_adapters(source_sha=BASE, available=False)
    adapter = registry.adapters("15")[0]
    assert adapter.available is False
    assert adapter.availability_reason == "NATIVE_EXECUTION_NOT_MEASURED"
    assert adapter.tool_id == "backend-worker"
    assert adapter.engine_families == ("openroad",)


def test_backend_argv_binds_complete_typed_parameter_envelope():
    registry = register_backend_adapters(
        source_sha=BASE, available=False,
        parameters={"pdk_name": "gf180mcuD", "image_id": "vibeic-eda:review",
                    "pdk_root": "/pdk", "top": "chip_top", "die_um": [100, 100],
                    "util": 0.55})
    argv = registry.adapters("15")[0].components[0].argv
    params = json.loads(argv[argv.index("--params-json") + 1])
    assert params["pdk_name"] == "gf180mcuD"
    assert params["image_id"] == "vibeic-eda:review"
    assert params["pdk_root"] == "/pdk"
    assert params["top"] == "chip_top"
    assert params["die_um"] == [100, 100] and params["util"] == 0.55
    assert "input_contract" in params and "source_sha" in params
    assert len(params["source_sha"]) == len(params["source_tree_sha"]) == 40


def test_backend_component_calls_real_worker_and_records_gate_boundary(tmp_path):
    source = tmp_path / "seed.txt"
    source.write_text("source-only\n")
    row = next(r for r in coverage_rows() if r["step_id"] == "15")
    context = issued_context(em.Context("15", BASE, {"project/input/seed.txt": source},
                         {"metric": "canonical_evidence", "direction": "max"},
                         tuple(_required_gates("15")), "librelane"), tmp_path, mode="default")
    registry = register_backend_adapters(em.Registry(), source_sha=BASE, available=True)
    controller = em.Controller(registry, em.Budget(cpus=1, ram_mb=512, workers=1))
    plan = controller.plan(context, "default-mode")
    root = tmp_path / "run"
    assert plan["arms"] == ["backend_15"]
    summary = controller.run(context, root, "default-mode")
    assert summary["candidate_statuses"]["backend_15"] in {"NOT_MEASURED", "FAIL"}
    adapter = registry.adapters("15")[0]
    result = json.loads((root / adapter.arm_id / "outputs" / "backend_result.json").read_text())
    assert result["step_id"] == "15"
    assert "gate_ledger" in result and result["verdict"] in {"NOT_MEASURED", "FAIL"}
    assert result["canonical_receipts"][0]["producer"] == "execution_backend_producers.produce"


def test_required_input_zero_byte_is_missing_but_nonempty_or_alternate_is_valid(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    zero = project / "empty.v"
    zero.write_bytes(b"")
    assert resolve_input_contract(project, [{"path": "empty.v"}]) == ["empty.v"]
    alternate = project / "real.sv"
    alternate.write_text("module top; endmodule\n")
    assert resolve_input_contract(project, [{"path": "empty.v OR real.sv"}]) == []


def test_backend_handoff_resolves_only_receipt_project_namespace(tmp_path):
    """A staged backend may rebase receipt project paths, never read ambient originals."""
    staged = tmp_path / "staged"
    folder = staged / "phase3/librelane/02-yosys-synthesis"
    folder.mkdir(parents=True)
    (staged / "phase3/stage1/rtl").mkdir(parents=True)
    source = staged / "phase3/librelane/02-yosys-synthesis/spm.nl.v"
    source.write_text("module spm; endmodule\n")
    original = Path("/original/project/phase3/librelane/02-yosys-synthesis/spm.nl.v")
    resolver = _project_path_resolver(
        staged, folder, {"nl": str(original)})
    assert resolver(original) == source.resolve()
    with pytest.raises(ValueError, match="absent"):
        resolver(Path("/original/project/phase3/librelane/02-yosys-synthesis/missing.v"))
    # A PDK path is external and stays external; it is subsequently checked
    # by the receipt's PDK mount validator rather than mapped to the project.
    assert resolver(Path("/pdk/gf180mcuD/config.tcl")) == Path("/pdk/gf180mcuD/config.tcl")


def test_backend_project_contract_uses_published_synthesis_folder_only(tmp_path):
    project = tmp_path / "project"
    sidecar = project / "phase2/stage2/synth/synth_inputs.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(json.dumps({"librelane_synthesis": {
        "folder": "phase3/librelane/02-yosys-synthesis",
        "mapped": "phase2/stage2/synth/top_synth.v"}}))
    resolved = project / "phase3/librelane/synthesis_resolved.json"
    resolved.parent.mkdir(parents=True)
    resolved.write_text("{}")
    folder = project / "phase3/librelane/02-yosys-synthesis"
    folder.mkdir(parents=True)
    (folder / "vibeic_receipt.json").write_text(json.dumps({"input": {
        "state_files": {
            str(project / "phase3/librelane/01-yosys-jsonheader/top.h.json"): "a",
            "/foreign/project/state.json": "b"}}}))
    contract = backend_project_input_contract(project, "37")
    assert "phase3/librelane/02-yosys-synthesis" in contract
    assert "phase2/stage2/synth/top_synth.v" in contract
    assert "phase3/librelane" not in contract
    assert "phase3/librelane/01-yosys-jsonheader/top.h.json" in contract
    assert "/foreign/project/state.json" not in contract
    from execution_provider_catalog import BACKEND_ROWS
    static = _backend_input_contract("37", BACKEND_ROWS["37"])
    assert "reports/pdk_via_patch_legalization.json" in static


def test_source_identity_binds_worker_runner_and_librelane_contract():
    adapter = register_backend_adapters(source_sha=BASE, available=False).adapters("19")[0]
    names = {Path(path).name for path in adapter.source_files}
    assert {"execution_backend_worker.py", "execution_backend_producers.py",
            "phase3_one_shot_runner.py", "librelane_contract.py",
            "librelane_cts_hold.py"}.issubset(names)


def _required_gates(step_id):
    return next(row['mandatory_gate_programs'] for row in em.load_portfolio()['steps']
                if row['id'] == step_id)


def test_controller_adoption_calls_selected_backend_consumer(tmp_path, monkeypatch):
    # A finite source fixture gives the public controller a real eligible arm;
    # the consumer spy proves adoption passes the immutable selected generation
    # rather than the mutable run root.
    script = tmp_path / "backend_fixture.py"
    script.write_text(
        "import json, os, pathlib, sys\n"
        "inputs, outputs = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])\n"
        "binding = json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])\n"
        "result = {'binding': binding, 'step_id': '15', 'producer_verdict': 'PASS',\n"
        " 'gates': {g: 'PASS' for g in binding['required_gates']},\n"
        " 'canonical_receipts': [{'producer': 'backend_fixture'}],\n"
        " 'outputs': {}, 'verdict': 'PASS'}\n"
        "(outputs / 'backend_result.json').write_text(json.dumps(result))\n")
    source = tmp_path / "seed.txt"
    source.write_text("fixture\n")
    row = next(r for r in coverage_rows() if r["step_id"] == "15")
    context = issued_context(em.Context("15", BASE, {"project/input/seed.txt": source},
                         {"metric": "canonical_evidence", "direction": "max"},
                         tuple(_required_gates("15")), "librelane"), tmp_path)

    def validator(outputs, binding):
        result = json.loads((outputs / "backend_result.json").read_text())
        return em.Evidence(binding, result["verdict"], result["gates"],
                           {"backend_result.json": em.digest(outputs / "backend_result.json")})

    adapter = em.Adapter(
        "backend_consumer_fixture", "fixture", "15", BASE,
        {str(Path(sys.executable).resolve()): em.digest(Path(sys.executable)),
         str(script.resolve()): em.digest(script), str(Path(__file__).resolve()): em.digest(Path(__file__))},
        sys.version, ("fixture",),
        (em.Component("producer", (str(Path(sys.executable).resolve()), str(script),
                                    "{inputs}", "{outputs}"), 5),), validator,
        ("backend_result.json",), {"metric": "canonical_evidence", "direction": "max"},
        output_contract={name: ("backend_result.json",) for name in row["canonical_outputs"]},
        qualification_evidence="R2 finite producer fixture", available=True)
    adapter = replace(adapter, source_files={**adapter.source_files,
        **{str(p): em.digest(p) for p in em._source_closure(adapter.source_files)}})
    registry = em.Registry(); register_source_fixture(registry, adapter, fixture_root=tmp_path)
    controller = em.Controller(registry, em.Budget(cpus=1, ram_mb=512, workers=1))
    seen = {}

    def consume(selected, ctx, ctl, run, adopted):
        seen.update(selected=Path(selected), run=Path(run), status=adopted["status"])
        return {"status": "CONSUMED"}

    monkeypatch.setattr(execution_backend_consumer, "import_selected", consume)
    root = tmp_path / "consumer-run"
    assert controller.run(context, root)["candidate_statuses"][adapter.arm_id] == "ELIGIBLE"
    receipt_path = root / adapter.arm_id / "receipt.json"
    choice = {"arm_id": adapter.arm_id, "binding": context.binding(),
              "receipt_sha256": em.digest(receipt_path), "reviewer": "R2 test",
              "rationale": "selected-generation consumer control"}
    assert controller.adopt(context, root, choice)["status"] == "ADOPTED"
    assert seen["status"] == "PROVISIONAL"
    assert seen["selected"].parent == root / "selected"
    assert seen["selected"] != root / adapter.arm_id / "outputs"


def test_public_controller_refuses_changed_actual_producer_call(tmp_path):
    source = tmp_path / "seed.txt"
    source.write_text("source-only\n")
    row = next(r for r in coverage_rows() if r["step_id"] == "15")
    context = issued_context(em.Context("15", BASE, {"project/input/seed.txt": source},
                         {"metric": "canonical_evidence", "direction": "max"},
                         tuple(_required_gates("15")), "librelane"), tmp_path, mode="default")
    original_registry = register_backend_adapters(source_sha=BASE, available=True)
    original_adapter = original_registry.adapters("15")[0]
    producer = next(Path(name) for name in original_adapter.source_files
                    if Path(name).name == "execution_backend_worker.py")
    original = producer.read_text()
    mutated = original.replace("producer = produce(project, params)",
                               "producer = {'verdict': 'PASS', 'canonical_receipts': []}", 1)
    assert mutated != original
    mutant = tmp_path / "execution_backend_worker.py"
    mutant.write_text(mutated.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\nimport sys\nsys.path.insert(0, " + repr(str(PROGRAMS)) + ")", 1))
    mutant_adapter = replace(
        original_adapter,
        source_files={**{k: v for k, v in original_adapter.source_files.items() if k != str(producer)},
                      str(mutant.resolve()): em.digest(mutant)},
        components=(replace(original_adapter.components[0],
                            argv=tuple(str(mutant.resolve()) if x == str(producer) else x
                                       for x in original_adapter.components[0].argv)),))
    registry = em.Registry()
    register_source_fixture(registry, mutant_adapter, fixture_root=tmp_path)
    root = tmp_path / "mutated-run"
    summary = em.Controller(registry, em.Budget(cpus=1, ram_mb=512, workers=1)).run(
        context, root, "default-mode")
    assert summary["candidate_statuses"]["backend_15"] in {"NOT_MEASURED", "FAIL"}
    result = json.loads((root / mutant_adapter.arm_id / "outputs" / "backend_result.json").read_text())
    assert result["producer_verdict"] == "PASS"
    assert result["canonical_receipts"] == []


def test_step30_default_and_explicit_xyce_are_parameters_of_one_provider():
    assert _step30_simulators() == ("ngspice",)
    assert _step30_simulators({"simulators": "xyce"}) == ("xyce",)
    with pytest.raises(em.Refusal):
        _step30_simulators({"simulators": ["ngspice", "ngspice"]})
    assert len([r for r in coverage_rows() if r["step_id"] == "30"]) == 1


def test_step37_has_one_engine_family_and_refuses_direct_magic_fallback():
    assert len(_step37_route_specs()) == 1
    with pytest.raises(em.Refusal):
        validate_streamout_receipt({}, route="direct_magic")
    assert validate_streamout_receipt({"status": "FAIL"}, route="direct_magic") == "FAIL"


def test_step37_receipt_requires_actual_streamout_engine():
    receipt = {"schema": "vibeic/step37-streamout-engine/1", "step_id": "37",
               "arm_id": "backend_37_librelane", "route": "librelane",
               "allowed_streamout_engines": ["magic", "klayout"],
               "streamout_engine": "magic", "status": "PASS"}
    assert validate_streamout_receipt(receipt) == "PASS"
    broken = dict(receipt, streamout_engine="toy")
    with pytest.raises(em.Refusal):
        validate_streamout_receipt(broken)


def test_reverse_mutations_refuse_missing_producer_symbol_and_output(tmp_path):
    with pytest.raises(em.Refusal):
        _site_path("execution_backend_producers.py:missing_row_producer")
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("mutated\n")
    binding = {"required_gates": ["canonical"]}
    receipt = {"binding": binding, "producer_verdict": "PASS",
               "gates": {"canonical": "PASS"}, "native_receipts": [{"tool": "native"}],
               "outputs": {"artifact.txt": "0" * 64}}
    (tmp_path / "backend_result.json").write_text(json.dumps(receipt))
    assert validate(tmp_path, binding).verdict == "NOT_MEASURED"
    receipt["producer_verdict"] = "FAIL"
    (tmp_path / "backend_result.json").write_text(json.dumps(receipt))
    assert validate(tmp_path, binding).verdict == "FAIL"


# Production API controls for BR2-001..006; fixtures never qualify native EDA.
from programs.tests import test_execution_modes as H
from programs.tests._hostpaths import require_repo
import execution_adapters_backend as backend
import execution_adapters_release as release
import execution_backend_consumer as consumer
import execution_backend_producers as producers
import execution_release_worker as worker
from execution_provider_catalog import coverage_rows, current_source_identity

em = H.em


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@contextmanager
def environment(values):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def observed(fn):
    try:
        value = fn()
        return value.get('status') if isinstance(value, dict) else value
    except em.Refusal as exc:
        return 'REFUSED:' + exc.code


@pytest.fixture(scope='module')
def release_arm():
    row = next(r for r in coverage_rows() if r['step_id'] == '16')
    return release._adapter(row, current_source_identity(),
                            {'metric': 'canonical_evidence', 'direction': 'max'},
                            path='IC', available=True, route_receipt=None, declaration=None)


def context16(tmp_path, *, native_clock=False):
    floorplan, clock = tmp_path / 'floorplan.def', tmp_path / 'clock.sdc'
    floorplan.write_text('VERSION 5.8 ;\n')
    clock.write_text('create_clock -name clk -period 10 [get_ports clk]\n')
    inputs = {
        'project/phase3/stage3/pnr/floorplan.def': floorplan,
        'project/phase2/stage2/constraints/clock.sdc': clock,
    }
    if native_clock:
        # This positive needs the genuine Step-16 producer, not a successful
        # placeholder plan. The negative fixture deliberately omits the PDK.
        floorplan.write_text('VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
            'DESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            'DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n'
            'PINS 1 ;\n- clk + NET clk + DIRECTION INPUT + USE CLOCK\n'
            '  + PORT + LAYER met1 ( -100 -100 ) ( 100 100 ) + FIXED ( 0 50000 ) N ;\n'
            'END PINS\nNETS 1 ;\n- clk ( PIN clk ) ;\nEND NETS\nEND DESIGN\n')
        pdk = tmp_path / 'declared_pdk.json'
        pdk.write_text(json.dumps({'fields': {'pdk_target': 'sky130A'}}))
        inputs['project/phase1/generated_docs/L19_CONSTRAINTS_PDK.json'] = pdk
    return issued_context(em.Context('16', current_source_identity(), inputs,
        {'metric': 'canonical_evidence', 'direction': 'max'}, ('clock_plan_check',), 'librelane'), tmp_path)



def ctl(arm, budget=None, *, fixture_root=None):
    registry = em.Registry()
    if fixture_root is None:
        registry.register(arm)
    else:
        register_source_fixture(registry, arm, fixture_root=fixture_root)
    return em.Controller(registry, budget or em.Budget(1, max(512, arm.ram_mb), workers=1))


def forged_first_write(controller, ctx, arm, root):
    """The R2 attack executes a real worker but invents supervisor facts."""
    inputs, outputs = root / arm.arm_id / 'inputs', root / arm.arm_id / 'outputs'
    inputs.mkdir(parents=True); outputs.mkdir()
    for name, path in ctx.inputs.items():
        target = inputs / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target); target.chmod(0o444)
    with environment({'VIBEIC_EXECUTION_BINDING': json.dumps(ctx.binding()), 'VIBEIC_ARM_ID': arm.arm_id}):
        report = worker.execute(inputs, outputs, step_id='16', params=json.loads(arm.components[0].argv[-1]))
    assert report['qualification'] == 'PASS'
    plan = controller.plan(ctx)
    plan.update(run_id=uuid.uuid4().hex, run_root=str(root), superiority=None,
                budget=asdict(controller.budget), public_portfolio=controller.portfolio,
                public_portfolio_sha256=em._hash(controller.portfolio))
    processes = []
    for component in arm.components:
        stdout, stderr = root / arm.arm_id / (component.name + '.stdout'), root / arm.arm_id / (component.name + '.stderr')
        stdout.write_bytes(b''); stderr.write_bytes(b'')
        processes.append(dict(component=component.name,
            argv=[x.replace('{inputs}', str(inputs)).replace('{outputs}', str(outputs)) for x in component.argv],
            rc=0, stop_reason=None, pid=999999999, started_ns=1, ended_ns=2,
            stdout=str(stdout), stderr=str(stderr), stdout_sha256=em.digest(stdout), stderr_sha256=em.digest(stderr)))
    receipt = dict(run_id=plan['run_id'], arm_id=arm.arm_id, binding=ctx.binding(),
        adapter=arm.identity(), processes=processes, input_root=str(inputs), output_root=str(outputs),
        status='ELIGIBLE', reason='ADAPTER_EVIDENCE', evidence=asdict(arm.validate(outputs, ctx.binding())), ended_ns=3)
    completion = {k: receipt[k] for k in ('run_id', 'arm_id', 'binding', 'adapter', 'processes', 'input_root', 'output_root')}
    completion.update(actual_status='ELIGIBLE', actual_reason=receipt['reason'], evidence=receipt['evidence'], ended_ns=3, run_root=str(root))
    dump(root / 'plan.json', plan); dump(root / arm.arm_id / 'receipt.json', receipt)
    for path, payload in ((root / 'issued-plan.json', plan), (root / arm.arm_id / 'issued-completion.json', completion)):
        em._record_authority(path, json.dumps(payload)); dump(path, em._seal(payload))
    return controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id))


def test_br2_001_first_write_cannot_mint_adoption(tmp_path, release_arm):
    ctx = context16(tmp_path, native_clock=True)
    actual = observed(lambda: forged_first_write(ctl(release_arm), ctx, release_arm, tmp_path / 'forged'))
    assert actual == 'REFUSED:ISSUED_AUTHORITY_UNAVAILABLE'


def test_br2_001_real_controller_and_issued_mutation_control(tmp_path, release_arm):
    ctx = context16(tmp_path, native_clock=True)
    assert release_arm.ram_mb == 4096
    controller = ctl(release_arm, budget=em.Budget(1, 4096, workers=1)); root = tmp_path / 'real'
    assert controller.run(ctx, root)['candidate_statuses'][release_arm.arm_id] == 'ELIGIBLE'
    from programs.tests._composite_gate_controls import assert_current_composite_refusals
    assert_current_composite_refusals(controller, ctx, root, release_arm.arm_id)
    assert controller.adopt(ctx, root, H.choice(ctx, root, release_arm.arm_id))['status'] == 'ADOPTED'
    receipt = root / release_arm.arm_id / 'receipt.json'
    payload = json.loads(receipt.read_text()); payload['reason'] = 'mutated'; dump(receipt, payload)
    # The immutable existing adoption chain checks its original arm digest
    # before the completion consumer. Both checks retain the issued bytes.
    assert observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root, release_arm.arm_id))) == 'REFUSED:ARM_RECEIPT_DIGEST_MISMATCH'


def test_br2_001_direct_arm_and_injected_issuer_refused(tmp_path):
    import threading
    ctx = H.context(tmp_path); arm = H.adapter(); controller = H.controller(arm)
    actual = observed(lambda: controller._run_arm(arm, ctx, controller.plan(ctx), tmp_path / 'direct', threading.Event()))
    assert actual == 'REFUSED:ISSUED_AUTHORITY_UNAVAILABLE'
    actual = observed(lambda: controller.run(ctx, tmp_path / 'injected', _issue=lambda *a: None))
    assert actual == 'REFUSED:ISSUED_AUTHORITY_UNAVAILABLE'


def test_br2_002_irrelevant_source_and_labels_cannot_split_implementation(tmp_path, release_arm):
    ctx = context16(tmp_path, native_clock=True); extra = tmp_path / 'unexecuted.txt'; extra.write_text('unexecuted\n')
    first = replace(release_arm, tool_id='first')
    duplicate = replace(first, arm_id='relabelled', tool_id='second', engine_families=('invented',),
                        source_files={**first.source_files, str(extra): em.digest(extra)})
    registry = em.Registry(); register_source_fixture(registry, first, fixture_root=tmp_path); register_source_fixture(registry, duplicate, fixture_root=tmp_path)
    controller = em.Controller(registry, em.Budget(2, 2 * first.ram_mb, workers=2))
    plan = controller.plan(ctx, 'ultra-mode')
    assert len(plan['arms']) == 1
    assert controller.run(ctx, tmp_path / 'deduped', 'ultra-mode')['candidate_statuses'] == {plan['arms'][0]: 'ELIGIBLE'}


def test_br2_002_real_components_stay_distinct_and_claims_have_source_evidence(tmp_path):
    # This real checked-in tool is consumed through the repository resolver.
    assert require_repo() / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/execution_modes_tool.py' == H.TOOL
    ctx = H.context(tmp_path); controller = H.controller(H.adapter('a'), H.adapter('b'))
    plan = controller.plan(ctx, 'ultra-mode')
    assert plan['arms'] == ['a', 'b']
    assert all(v['scope'] == 'SOURCE_COMPONENT_CLOSURE' and v['native_independence'] == 'NOT_MEASURED'
               for v in plan['independence'].values())
    assert len({v['sha256'] for v in plan['independence'].values()}) == 2


def finite_backend(tmp_path):
    row = next(r for r in coverage_rows() if r['step_id'] == '15')
    arm = backend._adapter(row, current_source_identity(), {'metric': 'canonical_evidence', 'direction': 'max'}, path='IC', available=True)
    script = tmp_path / 'finite.py'
    script.write_text("import json,os,pathlib,sys\n"
        "out=pathlib.Path(sys.argv[2]);binding=json.loads(os.environ['VIBEIC_EXECUTION_BINDING'])\n"
        "r={'binding':binding,'step_id':'15','producer_verdict':'PASS','verdict':'PASS',"
        "'gates':{g:'PASS' for g in binding['required_gates']},'outputs':{},'canonical_receipts':[{'scope':'SOFTWARE_FIXTURE_ONLY'}]}\n"
        "(out/'backend_result.json').write_text(json.dumps(r))\n")
    arm = replace(arm, arm_id='finite', tool_id='finite', components=(em.Component('finite',
        (str(Path(sys.executable).resolve()), str(script), '{inputs}', '{outputs}'), 5),),
        source_files={**arm.source_files, str(script): em.digest(script)})
    seed = tmp_path / 'seed.txt'; seed.write_text('seed\n')
    ctx = issued_context(em.Context('15', current_source_identity(), {'project/input/seed.txt': seed}, arm.objective,
                      tuple(_required_gates('15')), 'librelane'), tmp_path)
    return ctl(arm, fixture_root=tmp_path), ctx, arm


def test_br2_003_real_consumer_refusal_clears_persisted_selection(tmp_path):
    controller, ctx, arm = finite_backend(tmp_path); root = tmp_path / 'fault'
    assert controller.run(ctx, root)['candidate_statuses'][arm.arm_id] == 'ELIGIBLE'
    actual = observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id)))
    assert actual == 'REFUSED:GATE_FAIL'
    persisted = json.loads((root / 'adoption.json').read_text())
    assert (persisted['status'], persisted['selected']) == ('REFUSED', None)
    assert 'selected_generation' not in persisted


@pytest.mark.parametrize('answer', [{'status':'CONSUMED'}, {'status':'REFUSED'}, None, 'ERROR'])
def test_br2_003_consumer_commit_is_provisional_until_success(tmp_path, monkeypatch, answer):
    controller, ctx, arm = finite_backend(tmp_path); root = tmp_path / 'consumer'
    seen = []
    def consume(project, context, ctl, run, adoption):
        seen.append(adoption['status'])
        if answer == 'ERROR':
            raise RuntimeError('consumer fault')
        return answer
    monkeypatch.setattr(consumer, 'import_selected', consume)
    controller.run(ctx, root)
    actual = observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id)))
    persisted = json.loads((root / 'adoption.json').read_text())
    assert seen == ['PROVISIONAL']
    if answer == {'status':'CONSUMED'}:
        assert actual == persisted['status'] == 'ADOPTED'
        assert persisted['selected'] == arm.arm_id
    else:
        assert actual.startswith('REFUSED:')
        assert (persisted['status'], persisted['selected']) == ('REFUSED', None)


def test_br2_004_factory_supervisor_worker_route_roundtrip(tmp_path, monkeypatch):
    row = next(r for r in coverage_rows() if r['step_id'] == '37')
    arm = backend._adapter(row, current_source_identity(), {'metric':'canonical_evidence','direction':'max'}, path='IC', available=True)
    seed = tmp_path / 'seed'; seed.write_text('source-only\n')
    ctx = issued_context(em.Context('37', current_source_identity(), {'project/input/seed': seed}, arm.objective,
                      tuple(dict.fromkeys(row['consumer_gates'])), 'librelane'), tmp_path)
    actual_env = {}; popen = em.subprocess.Popen
    def launch(*args, **kwargs):
        if 'VIBEIC_ARM_ID' in kwargs.get('env', {}):
            actual_env.update(kwargs['env'])
        return popen(*args, **kwargs)
    monkeypatch.setattr(em.subprocess, 'Popen', launch)
    monkeypatch.setenv('VIBEIC_STEP37_ROUTE', 'caller-forged-route')
    controller = ctl(arm); controller.run(ctx, tmp_path / 'route')
    receipt = json.loads((tmp_path / 'route' / arm.arm_id / 'receipt.json').read_text())
    params = json.loads(arm.components[0].argv[-1])
    with environment({k:actual_env.get(k) for k in ('VIBEIC_ARM_ID','VIBEIC_STEP37_ROUTE')}):
        actual = observed(lambda: producers._step37_route(params))
    assert actual == 'librelane'
    assert receipt['processes'][0]['issued_environment'] == {
        k:actual_env[k] for k in ('VIBEIC_ARM_ID', 'VIBEIC_STEP37_ROUTE',
                                 'PYTHONPYCACHEPREFIX', 'PYTHONDONTWRITEBYTECODE')}
    assert arm.arm_id == 'backend_37_librelane'
    assert params['route'] == params['streamout_route'] == 'librelane'
    result = producers._step37_streamout_result(tmp_path, actual,
        type('SoftwareRow', (), {'extras':{'streamout_engine':'magic'}, 'status':'PASS', 'detail':'SOFTWARE_FIXTURE_ONLY'})())
    assert result['verdict'] == 'PASS'
    receipt = json.loads((tmp_path / 'reports/phase3/step37_streamout/vibeic_receipt.json').read_text())
    assert backend.validate_streamout_receipt(receipt, route=actual) == 'PASS'


@pytest.mark.parametrize('mutation', ['params', 'arm', 'environment', 'engine', 'direct'])
def test_br2_004_mismatched_route_and_engine_refused(monkeypatch, mutation):
    params = {'route':'librelane', 'streamout_route':'librelane'}
    monkeypatch.setenv('VIBEIC_ARM_ID', 'backend_37_librelane'); monkeypatch.setenv('VIBEIC_STEP37_ROUTE', 'librelane')
    if mutation == 'params': params['streamout_route'] = 'direct'
    if mutation == 'arm': monkeypatch.setenv('VIBEIC_ARM_ID', 'backend_37')
    if mutation == 'environment': monkeypatch.setenv('VIBEIC_STEP37_ROUTE', 'direct')
    if mutation in ('engine','direct'):
        receipt = {'schema':'vibeic/step37-streamout-engine/1','step_id':'37','arm_id':'backend_37_librelane',
            'route':'librelane','allowed_streamout_engines':['magic','klayout'],'streamout_engine':'other','status':'PASS'}
        assert observed(lambda: backend.validate_streamout_receipt(receipt, route='direct_magic' if mutation == 'direct' else 'librelane')).startswith('REFUSED:')
    else:
        assert observed(lambda: producers._step37_route(params)) == 'REFUSED:BACKEND_STEP37_ROUTE_UNBOUND'


def hardmacro_report(tmp_path, native):
    binding = {'step_id':'37.5ip','required_gates':['digital_hardmacro_check','release_docs_check']}
    report = {'step_id':'37.5ip','binding':binding,'qualification':'PASS','producer_verdict':'PASS','design_verdict':'PASS',
        'outputs':{},'missing_outputs':[], 'gate_records':[{'gate':g,'verdict':'PASS','blocking':True} for g in binding['required_gates']],
        'native_receipts':native}
    dump(tmp_path / 'release-evidence.json', report)
    return release.validate(tmp_path, binding).verdict


def test_br2_005_native_checker_fail_has_precedence(tmp_path):
    assert hardmacro_report(tmp_path, [{'status':'FAIL','processes':[]}]) == 'FAIL'


@pytest.mark.parametrize('native', [[], [{}], [None], ['invalid'], [None, {'status':'FAIL'}], [{'status':'FAIL'}, None]])
def test_br2_005_absent_invalid_and_mixed_evidence(tmp_path, native):
    expected = 'FAIL' if any(isinstance(x,dict) and x.get('status') == 'FAIL' for x in native) else 'NOT_MEASURED'
    assert hardmacro_report(tmp_path, native) == expected


def test_br2_005_valid_checker_positive_is_only_software_fixture(tmp_path):
    processes = [{'binary':name,'rc':0,'version':'fixture','argv':[name],'output_sha256':'a'*64} for name in ('magic','sta')]
    assert hardmacro_report(tmp_path, [{'status':'PRODUCED','processes':processes}]) == 'PASS'


@pytest.mark.parametrize('qualified', [False, True])
@pytest.mark.parametrize('resource', ['ram','cpu','license'])
def test_br2_006_feasibility_precedes_ready(tmp_path, release_arm, qualified, resource):
    ctx = context16(tmp_path)
    arm = replace(release_arm, qualified=qualified, cpus=2 if resource == 'cpu' else 1,
                  license_id='finite_license' if resource == 'license' else None)
    budget = em.Budget(1, 128 if resource == 'ram' else 512, workers=1)
    controller = ctl(arm, budget); root = tmp_path / 'underbudget'
    plan = controller.plan(ctx)
    assert plan['arms'] == []
    assert plan['portfolio'][0]['admission'] == ('LICENSE_UNAVAILABLE' if resource == 'license' else 'BUDGET_UNAVAILABLE')
    assert controller.run(ctx, root)['status'] == 'NOT_MEASURED'
    assert not (root / arm.arm_id).exists()


def test_br2_006_fitting_unqualified_arm_runs(tmp_path, release_arm):
    ctx = context16(tmp_path, native_clock=True); controller = ctl(release_arm)
    assert controller.plan(ctx)['portfolio'][0]['admission'] == 'READY_SOURCE_BOUND'
    assert controller.run(ctx, tmp_path / 'fitting')['candidate_statuses'][release_arm.arm_id] == 'ELIGIBLE'


@pytest.mark.parametrize('native', [[{'status':'FAIL'}], []])
def test_br2_005_fail_precedence_survives_missing_output(tmp_path, native):
    hardmacro_report(tmp_path, native)
    report_path = tmp_path / 'release-evidence.json'
    report = json.loads(report_path.read_text())
    report['outputs'] = {'missing.lib': 'a' * 64}
    dump(report_path, report)
    assert release.validate(tmp_path, report['binding']).verdict == ('FAIL' if native else 'NOT_MEASURED')


def test_br2_006_kernel_capacity_change_has_bounded_wait(tmp_path, monkeypatch):
    ctx = H.context(tmp_path)
    arm = H.adapter()
    arm = replace(arm, components=tuple(replace(c, timeout_s=.02) for c in arm.components))
    controller = H.controller(arm)
    affinity = set(os.sched_getaffinity(0))
    calls = 0
    def kernel_affinity(pid):
        nonlocal calls
        calls += 1
        # Resource admission is feasible. The supervisor's allocation snapshot
        # loses its CPU before dispatch, while the admission view stays feasible.
        return set() if calls == 2 else affinity
    monkeypatch.setattr(em.os, 'sched_getaffinity', kernel_affinity)
    root = tmp_path / 'capacity-change'
    summary = controller.run(ctx, root)
    receipt = H.read(root)
    assert summary['candidate_statuses'][arm.arm_id] == 'NOT_MEASURED'
    assert receipt['reason'] == 'RESOURCE_WAIT_DEADLINE'
    assert receipt['processes'] == []


def test_r3_coverage_census_matches_registered_streamout_identity():
    table = json.loads((PROGRAMS / 'data/ultra_provider_coverage.json').read_text())
    assert table == coverage_table()
    row = next(r for r in table['rows'] if r['step_id'] == '37')
    arm = backend._adapter(row, current_source_identity(), {'metric':'canonical_evidence','direction':'max'}, path='IC', available=False)
    assert row['arm_id'] == arm.arm_id == 'backend_37_librelane'


# R4 controls extend the reviewed test module without changing earlier cases.
@pytest.mark.parametrize('style', ['direct', 'alias'])
def test_r4_transparent_wrapper_has_one_real_producer(tmp_path, release_arm, style):
    ctx = context16(tmp_path, native_clock=True)
    release_arm = replace(release_arm, tool_id='source_worker_16')
    wrapper = tmp_path / 'transparent.py'
    symbol = 'main as invoke' if style == 'alias' else 'main'
    invocation = 'invoke' if style == 'alias' else 'main'
    wrapper.write_text('import sys\nsys.path.insert(0, ' + repr(str(PROGRAMS)) + ')\n'
                       'from execution_release_worker import ' + symbol + '\n'
                       'raise SystemExit(' + invocation + '())\n')
    component = release_arm.components[0]
    sources = {**release_arm.source_files, str(wrapper): em.digest(wrapper)}
    wrapped = replace(release_arm, arm_id='wrapped_release_16', tool_id='wrapper_label',
        engine_families=('caller_distinct_label',), source_files=sources,
        components=(replace(component, argv=(component.argv[0], str(wrapper), *component.argv[2:])),))
    registry = em.Registry(); register_source_fixture(registry, release_arm, fixture_root=tmp_path); register_source_fixture(registry, wrapped, fixture_root=tmp_path)
    controller = em.Controller(registry, em.Budget(2, 2 * release_arm.ram_mb, workers=2))
    plan = controller.plan(ctx, 'ultra-mode')
    assert len(plan['arms']) == 1
    assert controller.run(ctx, tmp_path / 'wrapper-run', 'ultra-mode')['candidate_statuses'] == {
        plan['arms'][0]: 'ELIGIBLE'}


@pytest.mark.parametrize('label', ['16', '39', None])
def test_r4_native_fail_survives_report_step_relabel(tmp_path, label):
    hardmacro_report(tmp_path, [{'status':'FAIL','processes':[]}])
    report = json.loads((tmp_path / 'release-evidence.json').read_text())
    binding = report['binding']
    before = release.validate(tmp_path, binding)
    report['step_id'] = label
    dump(tmp_path / 'release-evidence.json', report)
    after = release.validate(tmp_path, binding)
    assert (before.verdict, after.verdict) == ('FAIL', 'FAIL')
    assert after.detail == 'RELEASE_STEP_IDENTITY_MISMATCH'


@pytest.mark.parametrize('native', [None, {}, {'status':'PASS','processes':[]}])
def test_r4_relabel_cannot_drop_native_requirement(tmp_path, native):
    hardmacro_report(tmp_path, [] if native is None else [native])
    report = json.loads((tmp_path / 'release-evidence.json').read_text())
    binding = report['binding']
    report['step_id'] = '16'
    dump(tmp_path / 'release-evidence.json', report)
    evidence = release.validate(tmp_path, binding)
    assert evidence.verdict == 'NOT_MEASURED'
    assert evidence.detail == 'RELEASE_STEP_IDENTITY_MISMATCH'


def test_r4_refused_generation_is_removed_and_revoked(tmp_path, monkeypatch):
    controller, ctx, arm = finite_backend(tmp_path); root = tmp_path / 'refused'
    original = consumer.import_selected
    captured = {}
    def consume(project, context, ctl, run, adoption):
        captured.update(generation=dict(adoption['selected_generation']), adoption=dict(adoption),
                        manifest=(Path(project) / 'manifest.json').read_bytes())
        return original(project, context, ctl, run, adoption)
    monkeypatch.setattr(consumer, 'import_selected', consume)
    assert controller.run(ctx, root)['candidate_statuses'][arm.arm_id] == 'ELIGIBLE'
    assert observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id))) == 'REFUSED:GATE_FAIL'
    assert len(list((root / 'selected').iterdir())) == 0
    generation = captured['generation']; directory = Path(generation['directory'])
    # Restoring a saved valid signature must not restore revoked issuance.
    directory.mkdir()
    (directory / 'manifest.json').write_bytes(captured['manifest'])
    assert observed(lambda: em._issued(directory / 'manifest.json')) == 'REFUSED:ISSUED_AUTHORITY_UNAVAILABLE'
    assert observed(lambda: original(directory, ctx, controller, root, captured['adoption'])) == 'REFUSED:BACKEND_SELECTED_MANIFEST_UNBOUND'
    refusal = json.loads((root / 'adoption.json').read_text())
    assert refusal['discarded_generation']['status'] == 'INVALIDATED'


@pytest.mark.parametrize('answer', [None, {'status':'REFUSED'}, 'ERROR'])
def test_r4_consumer_failure_cleans_only_new_generation(tmp_path, monkeypatch, answer):
    controller, ctx, arm = finite_backend(tmp_path); root = tmp_path / 'rollback'
    controller.run(ctx, root)
    monkeypatch.setattr(consumer, 'import_selected', lambda *args: {'status':'CONSUMED'})
    accepted = controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id))
    previous = Path(accepted['selected_generation']['directory'])
    snapshot = {str(p.relative_to(previous)): (p.read_bytes(), p.stat().st_mode & 0o777)
                for p in previous.rglob('*') if p.is_file()}
    def refuse(*args):
        if answer == 'ERROR':
            raise RuntimeError('consumer failure after provisional selection')
        return answer
    monkeypatch.setattr(consumer, 'import_selected', refuse)
    assert observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id))).startswith('REFUSED:')
    assert list((root / 'selected').iterdir()) == [previous]
    assert snapshot == {str(p.relative_to(previous)): (p.read_bytes(), p.stat().st_mode & 0o777)
                        for p in previous.rglob('*') if p.is_file()}
    controller._generation_current(accepted['selected_generation'])


def test_r4_partial_generation_copy_rolls_back(tmp_path, monkeypatch):
    ctx = H.context(tmp_path); controller = H.controller(H.adapter()); root = tmp_path / 'partial'
    assert controller.run(ctx, root, 'ultra-mode')['status'] == 'AWAITING_AI_SELECTION'
    assert not (root / 'selected').exists()
    # Inject a real publication error at the filesystem boundary. Source-bound
    # call sites can retain their original write_bytes reference.
    original = os.replace; count = []
    def fail_second(source, target, *args, **kwargs):
        if Path(target).is_relative_to(root / 'selected'):
            count.append(Path(target))
            if len(count) == 2:
                raise OSError('selected copy fault')
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(os, 'replace', fail_second)
    assert observed(lambda: controller.adopt(ctx, root, H.choice(ctx, root))) == 'REFUSED:INVALID_ADOPTION_EVIDENCE'
    assert len(count) == 2
    assert len(list((root / 'selected').iterdir())) == 0


def test_r4_manifest_is_provisional_until_consumer_success(tmp_path, monkeypatch):
    controller, ctx, arm = finite_backend(tmp_path); root = tmp_path / 'commit'
    controller.run(ctx, root); captured = []
    def consume(project, context, ctl, run, adoption):
        captured.append(em._issued(Path(project) / 'manifest.json')['status'])
        return {'status':'CONSUMED'}
    monkeypatch.setattr(consumer, 'import_selected', consume)
    accepted = controller.adopt(ctx, root, H.choice(ctx, root, arm.arm_id))
    assert captured == ['PROVISIONAL']
    generation = accepted['selected_generation']
    assert generation['status'] == em._issued(Path(generation['directory']) / 'manifest.json')['status'] == 'ADOPTED'


# Current canonical backend receipt projection; software controls only.
def _backend_projection_current_fixture():
    import shlex
    step = "15"
    row = backend.ROWS[step]
    gates = list(row["portfolio_policy"]["mandatory_gate_programs"])
    commands = []
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero", "optional_program_exit_zero"):
                    command = value.get("command") if isinstance(value, dict) else value
                    if isinstance(command, str): commands.append(command)
                else: walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    walk(row["canonical_row"].get("gate", {}))
    ledger = [{"gate": Path(shlex.split(cmd)[0]).stem, "cmd": cmd, "rc": 0,
               "exit_code": 0, "verdict": "PASS"} for cmd in commands]
    binding = {"step_id": step, "source_sha": "SOFTWARE_PROJECTION_FIXTURE_ONLY", "required_gates": gates}
    report = {"schema": "vibeic/backend-result/2", "step_id": step,
        "source_sha": binding["source_sha"], "binding": binding,
        "producer_verdict": "PASS", "verdict": "PASS", "gates": {**{g: "PASS" for g in gates},
          "backend_canonical": "PASS", "backend_native_substance": "PASS"},
        "gate_ledger": ledger, "outputs": {}, "missing_outputs": [], "missing_inputs": [],
        "canonical_receipts": [{"schema": "vibeic/backend-producer-receipt/1",
          "producer": "execution_backend_producers.produce", "step_id": step, "verdict": "PASS",
          "detail": "SOFTWARE_PROJECTION_FIXTURE_ONLY"}]}
    return binding, report


def _backend_projection_value(tmp_path, binding, report):
    (tmp_path / "backend_result.json").write_text(json.dumps(report))
    return backend.validate(tmp_path, binding)


def test_backend_current_projection_is_descriptive_only(tmp_path):
    binding, report = _backend_projection_current_fixture()
    value = _backend_projection_value(tmp_path, binding, report)
    projected = value.provenance["composite_gate_execution"]
    assert set(projected["gate_records"]) == set(binding["required_gates"])
    assert projected["receipt_sha256"] == value.outputs["backend_result.json"]
    assert projected["worker_component"] == "producer"
    assert projected["worker_source"] == str(backend.HERE / "execution_backend_worker.py")
    assert projected["gate_sources"]
    # No Controller, observed process, sealed issuance, adoption or native tool
    # exists in this fixture. Projection alone does not authorize any of them.


@pytest.mark.parametrize("fault", ["missing_ledger", "gate_cmd", "gate_rc", "source", "producer", "required_set"])
def test_backend_incomplete_or_forged_projection_is_absent(tmp_path, fault):
    binding, report = _backend_projection_current_fixture()
    real = next(row for row in report["gate_ledger"] if row["gate"] in binding["required_gates"])
    if fault == "missing_ledger": report["gate_ledger"] = []
    elif fault == "gate_cmd": real["cmd"] += " --forged"
    elif fault == "gate_rc": real["rc"] = True
    elif fault == "source": report["source_sha"] = "STALE"
    elif fault == "producer": report["canonical_receipts"][0]["producer"] = "caller_written"
    elif fault == "required_set": binding["required_gates"] = []
    value = _backend_projection_value(tmp_path, binding, report)
    assert not value.provenance
    assert value.metrics.get("canonical_evidence", 0) == 0


def test_backend_measured_fail_survives_forged_projection(tmp_path):
    binding, report = _backend_projection_current_fixture()
    report["gate_ledger"] = []
    report["producer_verdict"] = "FAIL"
    value = _backend_projection_value(tmp_path, binding, report)
    assert value.verdict == "FAIL"
    assert not value.provenance


@pytest.mark.parametrize("state", ["PASS", "FAIL", "NOT_MEASURED"])
def test_backend_summary_states_keep_exact_gate_census_and_fail_precedence(tmp_path, state):
    binding, report = _backend_projection_current_fixture()
    report["gates"]["backend_canonical"] = state
    value = _backend_projection_value(tmp_path, binding, report)
    assert set(value.gates) == set(binding["required_gates"])
    if state == "FAIL":
        assert value.verdict == "FAIL"
    if state != "PASS":
        assert not value.provenance
        assert value.metrics.get("canonical_evidence", 0) == 0
    else:
        assert value.provenance["composite_gate_execution"]
