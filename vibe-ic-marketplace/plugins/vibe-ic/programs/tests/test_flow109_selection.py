"""Exercise source-owned selection through the canonical front door.

These are configuration/dispatch tests, not EDA qualification or IC PASS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import _path_layout as layout
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










def _publish_dft_intent(project, intent, *, route='ic'):
    import _delivery_route
    assert _delivery_route.admit(project, route) is None
    import spec_declaration_emit as declaration
    docs = project / "input/docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L7_verification_plan.md").write_text(
        "# Verification\nThe Plugin MUST declare `plugin_output/declaration.json` "
        "before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n"
        "| `dft` | Yes | object |\n")
    (project / 'input/feature-decisions.json').write_text(json.dumps({'dft': intent}))
    assert declaration.main(
        [str(project), "--set", "dft=" + json.dumps(intent)]) == 0
    import phase1_one_shot_runner as phase1
    output = phase1._d01_emit_dft_intent(project)
    if output is not None:
        report = layout.report_path(project, 'phase1_one_shot.json')
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'project': str(project.resolve()), **__import__('_delivery_route').report_label(project), 'dft_intent_output': output}))
































































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


class NativePrelayoutReached(Exception):
    pass


def test_d26_native_handoff_without_area_budget_reaches_original_timing_owner(tmp_path, monkeypatch):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name('top_synth.v')
    netlist.rename(mapped)
    sha = hashlib.sha256(mapped.read_bytes()).hexdigest()
    sys.modules['synth_handoff_netlist_check'].bound_handoff = lambda _p: {
        'verdict':'PASS', 'canonical':str(mapped), 'mapped':str(mapped),
        'netlist_sha256':sha, 'findings':[]}
    versions = sys.modules['step_output_collector']
    versions.latest_pass = lambda *_a: None
    monkeypatch.setitem(sys.modules, 'design_one_shot_runner', SimpleNamespace(
        _phase2_pdk_config=lambda *_a: 'neutral-pdk'))
    def native(project, top, pdk, container):
        assert (project,top,pdk,container) == (tmp_path,'top','neutral-pdk','')
        raise NativePrelayoutReached
    monkeypatch.setitem(sys.modules, 'phase3_one_shot_runner', SimpleNamespace(
        step_prelayout_signoff=native))
    with pytest.raises(NativePrelayoutReached):
        runner._complete_step10_prelayout(tmp_path, 'top', 'neutral', '')


@pytest.mark.parametrize('case', ['missing', 'stale', 'native_failure'])
def test_d26_refuses_unbound_step9_before_prelayout_producer(tmp_path, monkeypatch, case):
    runner, netlist = _step9_native_state(tmp_path, monkeypatch)
    mapped = netlist.with_name('top_synth.v')
    netlist.rename(mapped)
    sha = hashlib.sha256(mapped.read_bytes()).hexdigest()
    handoff = {'verdict':'PASS', 'canonical':str(mapped), 'mapped':str(mapped),
        'netlist_sha256':sha, 'findings':[]}
    sys.modules['synth_handoff_netlist_check'].bound_handoff = lambda _p: handoff
    versions = sys.modules['step_output_collector']
    versions.latest_pass = lambda *_a: None
    if case == 'missing':
        versions._read_index = lambda _p: {'steps':[]}
    elif case == 'stale':
        mapped.write_text('module changed; endmodule\n')
    else:
        handoff.update(verdict='FAIL', findings=['native mapped handoff failed'])
    monkeypatch.setitem(sys.modules, 'design_one_shot_runner', SimpleNamespace(
        _phase2_pdk_config=lambda *_a: 'neutral-pdk'))
    monkeypatch.setitem(sys.modules, 'phase3_one_shot_runner', SimpleNamespace(
        step_prelayout_signoff=lambda *a, **kw: pytest.fail('bad native handoff reached timing')))
    result = runner._complete_step10_prelayout(tmp_path, 'top', 'neutral', '')
    assert result['verdict'] == 'NOT_MEASURED'


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
    # This directly exercises the retained pre-stitched owner, without a
    # selected physical D23 context leaked from another test.
    monkeypatch.setattr(runner, '_flow109_selected_row', lambda _row: False)

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
    import design_one_shot_runner as design
    from test_flow109_d09_owned_metrics import d01_precondition
    monkeypatch.setattr(design, '_serial_d01_state', d01_precondition)
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







































# Native completion is an owner answer, separate from whole-flow acceptance.


























def test_d10_yosys_observation_requires_matching_current_native_binding(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'attributes': {}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['status'] == 'OBSERVED'
    assert observation['elaboration_errors'] == 0
    assert observation['unexpected_blackboxes'] == 0
    assert observation['qualification'] == 'NOT_MEASURED'
    path.write_text(json.dumps({'modules': {'top': {'cells': {'u': {'type': 'foreign'}}}}}))
    assert runner._d10_yosys_observation(tmp_path)['status'] == 'NOT_MEASURED'


def test_d10_yosys_observation_does_not_approve_nonzero_blackboxes(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'cells': {'u': {'type': 'macro'}}},
                         'macro': {'attributes': {'blackbox': '1'}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['observed_blackbox_instances'] == ['u']
    assert observation['unexpected_blackboxes'] is None
    assert observation['qualification'] == 'NOT_MEASURED'


def test_d10_yosys_observation_follows_hierarchy_and_refuses_unknown_cells(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import vibe_ic_one_shot_runner as runner
    path = tmp_path / native.NETLIST_REL
    path.parent.mkdir(parents=True)
    graph = {'modules': {'top': {'cells': {'u': {'type': 'child'}}},
                         'child': {'cells': {'m': {'type': 'macro'}}},
                         'macro': {'attributes': {'blackbox': '1'}, 'cells': {}}}}
    path.write_text(json.dumps(graph))
    bound = {'sha256': {'netlist.json': hashlib.sha256(path.read_bytes()).hexdigest()},
             'input': {'fingerprint': 'current-input'}}
    monkeypatch.setattr(native, 'load', lambda _: SimpleNamespace(top='top'))
    monkeypatch.setattr(native, 'require_binding', lambda *_: bound)
    observation = runner._d10_yosys_observation(tmp_path)
    assert observation['observed_blackbox_instances'] == ['u/m']
    assert observation['unexpected_blackboxes'] is None
    graph['modules']['child']['cells']['m']['type'] = 'undefined'
    path.write_text(json.dumps(graph))
    bound['sha256']['netlist.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert runner._d10_yosys_observation(tmp_path)['status'] == 'NOT_MEASURED'









def test_d10_single_gate_dry_run_real_frontend_positive_negative_and_no_project_writes(tmp_path, monkeypatch, capsys):
    import hashlib
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    argv = [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10', '--only',
            'p0_tool_frontend_check', '--dry-run']
    monkeypatch.setattr(sys, 'argv', argv)
    def snapshot():
        return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob('*') if p.is_file()}
    before = snapshot()
    assert runner._main() == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['gate_status'] == 'PASS'
    assert result['row_status'] == 'NOT_MEASURED'
    assert result['tool_qualification'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert snapshot() == before
    rtl.write_text('module top(input a, output y); missing_cell x(.a(a),.y(y)); endmodule\n')
    before = snapshot()
    assert runner._main() == 1
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['gate_status'] == 'FAIL'
    assert result['row_status'] == 'NOT_MEASURED'
    assert snapshot() == before




def test_d10_single_gate_dry_run_refuses_changed_inputs_and_untrusted_runtime(tmp_path, monkeypatch, capsys):
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10',
                                     '--only', 'p0_tool_frontend_check', '--dry-run'])
    def changed(_project, *, output_project):
        output = output_project / frontend.RTL_ELAB_REL
        output.parent.mkdir(parents=True)
        output.write_text('{"modules":{"top":{}}}')
        rtl.write_text(rtl.read_text() + '// changed\n')
        return {'passed': True, 'findings': [], 'tools': {
            'Yosys.JsonHeader': {'exit_code': 0}, 'Verilator.Lint': {'exit_code': 0}}}
    monkeypatch.setattr(frontend, 'check', changed)
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == answer['row_status'] == 'NOT_MEASURED'
    assert 'changed' in answer['detail']
    monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', str(tmp_path / 'missing.json'))
    monkeypatch.setattr(frontend, 'check', lambda *_a, **_k: pytest.fail('untrusted runtime must not run'))
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == 'NOT_MEASURED'


def test_d10_single_gate_dry_run_never_classifies_tool_crash_as_design_fail(tmp_path, monkeypatch, capsys):
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output y); assign y = a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10',
                                     '--only', 'p0_tool_frontend_check', '--dry-run'])
    monkeypatch.setattr(frontend, 'check', lambda *_a, **_k: {'passed': False,
        'findings': ['tool crashed'], 'tools': {'Yosys.JsonHeader': {'exit_code': -9},
                                               'Verilator.Lint': {'exit_code': 0}}})
    assert runner._main() == 2
    answer = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert answer['gate_status'] == 'NOT_MEASURED'
    assert answer['reason'] == 'NATIVE_FRONTEND_ABNORMAL_TERMINATION'
    assert answer['row_status'] == 'NOT_MEASURED'








def test_dft_vocabulary_canonical_named_intent_rejects_legacy_key(tmp_path):
    import spec_declaration_emit as declaration
    import fault_scan_chain_insert as producer
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    intent = {'scan_test': False, 'requires_scan': False, 'reason': 'no scan required'}
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(intent)]) == 0
    assert (tmp_path / 'plugin_output/dft_intent.json').is_file()
    binding, problems = producer.load_d09_dft_contract(tmp_path)
    assert binding is None and 'DFT_INTENT_SCHEMA_INVALID' in str(problems)




def test_d10_dft_ports_dry_run_real_frontend_positive_and_missing_port(tmp_path, monkeypatch, capsys):
    import hashlib
    import vibe_ic_one_shot_runner as runner
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    rtl.write_text('module top(input scan_enable, scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_enable ^ scan_in ^ test_mode ^ scan_clock; endmodule\n')
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(Path(runner.__file__)), str(tmp_path), '--step', 'D10', '--only', 'dft_port_consistency', '--dry-run'])
    snapshot = lambda: {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    before = snapshot()
    assert runner._main() == 0
    good = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert good['gate_status'] == 'PASS' and good['row_status'] == 'NOT_MEASURED'
    assert snapshot() == before
    rtl.write_text('module top(input scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_in ^ test_mode ^ scan_clock; endmodule\n')
    before = snapshot()
    assert runner._main() == 1
    bad = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert bad['gate_status'] == 'FAIL' and bad['reason'] == 'DFT_PORT_MISMATCH'
    assert bad['port_evidence']['mismatches'][0]['role'] == 'scan_enable'
    assert bad['row_status'] == 'NOT_MEASURED' and snapshot() == before


def test_d10_dft_owner_consumes_current_native_elaboration(tmp_path, monkeypatch):
    import hashlib
    import _cdc_netlist as native
    import _specrtl_common
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input scan_in, test_mode, scan_clock, output scan_out); assign scan_out = scan_in ^ test_mode ^ scan_clock; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    result = frontend.check(tmp_path, output_project=tmp_path)
    assert result['passed'] is True
    path = tmp_path / frontend.RTL_ELAB_REL
    p0 = {'status': 'PASS', 'top': 'top', 'elaboration_path': frontend.RTL_ELAB_REL,
          'elaboration_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
          'input_fingerprint': native.source_binding(tmp_path, 'top', _specrtl_common.rtl_source_files(tmp_path))['fingerprint']}
    # This test isolates the DFT-port comparison; the P0 identity is tested
    # independently through its consumer and actual-source refusal controls.
    monkeypatch.setattr(runner, '_validate_d10_p0_consumer', lambda *_: {'status': 'PASS'})
    observed = runner._d10_dft_ports(tmp_path, p0)
    assert observed['status'] == 'FAIL' and observed['reason'] == 'DFT_PORT_MISMATCH'
    assert observed['mismatches'][0]['role'] == 'scan_enable'
    rtl.write_text(rtl.read_text() + '// changed after elaboration\n')
    assert runner._d10_dft_ports(tmp_path, p0)['status'] == 'NOT_MEASURED'


def test_d10_p0_consumer_binds_actual_argv_and_rejects_stale_inputs(tmp_path, monkeypatch):
    import hashlib
    import shutil
    import _cdc_netlist as native
    import _specrtl_common
    import librelane_contract as contract
    import p0_tool_frontend_check as frontend
    import vibe_ic_one_shot_runner as runner
    rtl = tmp_path / 'phase2/stage1/rtl/top.v'; rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a, output b); assign b=a; endmodule\n')
    spec = tmp_path / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'; spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({'top_module': 'top'}))
    result = frontend.check(tmp_path, output_project=tmp_path)
    assert result['passed'] is True
    receipt = tmp_path / 'p0_result.json'; receipt.write_text(json.dumps(result))
    authority = {'image': 'image-ref', 'image_id': 'image-id', 'cid': 'cid', 'attestation_sha256': 'launch'}
    monkeypatch.setattr(contract, 'local_image_attestation', lambda: dict(authority))
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    p0 = {'status':'PASS', 'top':'top',
        'elaboration_path':frontend.RTL_ELAB_REL,
        'elaboration_sha256':digest(tmp_path / frontend.RTL_ELAB_REL),
        'producer_result': {'path':'p0_result.json', 'sha256':digest(receipt)},
        'input_fingerprint':native.source_binding(tmp_path, 'top', _specrtl_common.rtl_source_files(tmp_path))['fingerprint'],
        'producer_source_sha256':digest(frontend.__file__), 'runner_source_sha256':digest(runner.__file__),
        'tool_sha256':{name:digest(shutil.which(name)) for name in ('yosys','verilator')}, **authority}
    assert runner._validate_d10_p0_consumer(tmp_path, p0)['argv_validation'] == 'MATCH'
    bad = json.loads(receipt.read_text())
    bad['tools']['Yosys.JsonHeader']['argv'][4] = bad['tools']['Yosys.JsonHeader']['argv'][4].replace('read_slang', 'read_verilog', 1)
    receipt.write_text(json.dumps(bad)); p0['producer_result']['sha256'] = digest(receipt)
    with pytest.raises(ValueError, match='Yosys command'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    receipt.write_text(json.dumps(result)); p0['producer_result']['sha256'] = digest(receipt)
    wrong_image = dict(p0, image_id='foreign')
    with pytest.raises(ValueError, match='launch identity'):
        runner._validate_d10_p0_consumer(tmp_path, wrong_image)
    elab = tmp_path / frontend.RTL_ELAB_REL
    original_elab = elab.read_bytes(); elab.write_bytes(original_elab + b' ')
    with pytest.raises(ValueError, match='elaboration is missing or stale'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    elab.write_bytes(original_elab)
    rtl.write_text(rtl.read_text() + '// stale source\n')
    with pytest.raises(ValueError, match='source, producer or runner'):
        runner._validate_d10_p0_consumer(tmp_path, p0)
    assert p0['status'] == 'PASS'  # P0 only; this test does not claim D10.










def test_d09_dft_consumer_refuses_wrong_owner_without_reemission(tmp_path, monkeypatch):
    import design_one_shot_runner as design
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    _publish_dft_intent(tmp_path, _intent())
    report = layout.report_path(tmp_path, 'phase1_one_shot.json')
    body = json.loads(report.read_text()); body['dft_intent_output']['producer'] = 'D09'
    report.write_text(json.dumps(body))
    artifact = tmp_path / body['dft_intent_output']['path']
    before = artifact.read_bytes()
    monkeypatch.setattr(design.subprocess, 'run', lambda *_a, **_kw: pytest.fail('D09 must not re-emit DFT intent'))
    result = design.declaration_before_step4(tmp_path)
    assert result['producer'] == 'D01' and result['emitted'] is False
    assert 'UNPROVEN_ADAPTER_BINDING' in result['reason']
    assert artifact.read_bytes() == before


def test_d01_fresh_author_decisions_produce_bound_intent(tmp_path):
    assert __import__('_delivery_route').admit(tmp_path, 'ic') is None
    import phase1_one_shot_runner as phase1
    import fault_scan_chain_insert as scan
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    docs = tmp_path / 'input/docs'; docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    decisions = tmp_path / 'input/feature-decisions.json'
    decisions.write_text(json.dumps({'dft': _intent()}))
    assert not (tmp_path / 'plugin_output/dft_intent.json').exists()
    assert phase1._as_the_producer(lambda _p: 0)(tmp_path) == 0
    output = phase1._RUN['dft_intent_output']
    assert output and output['producer'] == 'D01'
    assert output['path'] == 'plugin_output/dft_intent.json'
    assert 'input/feature-decisions.json' in output['sources']
    report = layout.report_path(tmp_path, 'phase1_one_shot.json'); report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'project': str(tmp_path.resolve()), **__import__('_delivery_route').report_label(tmp_path), 'dft_intent_output': output}))
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding and not problems
    decisions.write_text(json.dumps({'dft': {'requires_scan': False, 'reason': 'changed'}}))
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding is None and problems


def test_d01_does_not_relabel_old_d09_decision_without_d01_source(tmp_path):
    import phase1_one_shot_runner as phase1
    import spec_declaration_emit as declaration
    from programs.tests.test_issue3444_l20_scan_reconciliation import _intent
    docs = tmp_path / 'input/docs'; docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(_intent())]) == 0
    old = (tmp_path / 'plugin_output/dft_intent.json').read_bytes()
    assert phase1._d01_emit_dft_intent(tmp_path) is None
    assert (tmp_path / 'plugin_output/dft_intent.json').read_bytes() == old
