"""Issue #3444: Step 11 consumes and reconciles the exact current L20."""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as D  # noqa: E402
import fault_scan_chain_insert as S  # noqa: E402


def _project(tmp_path: Path, chains: list[dict]) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({
        "doc_id": "L20", "applicability": "APPLICABLE",
        "extraction_status": "EXTRACTED",
        "fields": {"dft_present": True, "scan_chains": chains,
                   "test_compression": None, "bist_mbist": [],
                   "jtag_tap": None},
    }, indent=2) + "\n")
    return tmp_path


def _chain(**overrides):
    row = {"name": "core_scan", "length": 2, "scan_in": "sin",
           "scan_out": "sout", "clock": "clk"}
    row.update(overrides)
    return row


def _report(binding: dict) -> dict:
    report = {
        "clock": "clk", "input_flop_count": 2,
        "internal_chain_length": 2,
        "dft_ports": ["sin", "shift", "test", "tck", "sout"],
        "l20_contract": binding,
    }
    report["l20_reconciliation"] = S.reconcile_l20_scan_contract(binding, report)
    return report


def test_positive_current_one_chain_contract_reconciles(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, problems = S.load_l20_scan_contract(
        project, expected_clock="clk", expected_length=2)
    assert problems == [] and binding is not None
    assert binding["path"].endswith("L20_DFT_SCAN_TOPOLOGY.json")
    assert len(binding["sha256"]) == 64
    report = _report(binding)
    assert report["l20_reconciliation"]["ok"] is True
    assert S.l20_binding_is_current(project, report)[0] is True
    assert D.dft_scan_insertion_contract(project)[0] is True


def test_stale_l20_bytes_invalidate_the_receipt(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    report = _report(binding)
    path = project / binding["path"]
    path.write_text(path.read_text().replace('"core_scan"', '"renamed"'))
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "differs" in reason


def test_saved_pass_cannot_hide_changed_measurements(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    report = _report(binding)
    report["internal_chain_length"] = 1
    # The saved reconciliation still says PASS; the consumer must re-derive it.
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "reconciliation" in reason


def test_multi_chain_is_refused_before_native_execution(tmp_path, monkeypatch):
    project = _project(tmp_path, [_chain(), _chain(name="second")])
    netlist = project / "phase2" / "stage2" / "synth" / "mapped.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text(
        "module top(input clk, input d, output q);\n"
        "sky130_fd_sc_hd__dfxtp_1 u0 (.CLK(clk), .D(d), .Q(q));\n"
        "endmodule\n")
    monkeypatch.setattr(S._fatpg, "_run_docker", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("native tool must not run"))))
    rc, report = S.run_chain(
        project, "phase2/stage2/synth/mapped.v", "clk", "sky130",
        require_l20_contract=True)
    assert rc == 1
    assert report["stage"] == "l20_contract"
    assert "exactly one" in "; ".join(report["problems"])


def test_declared_length_must_equal_the_mapped_flop_count(tmp_path):
    project = _project(tmp_path, [_chain(length=3)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert binding is None
    assert any("flop count 2" in problem for problem in problems)


def test_fixed_scan_ports_are_enforced(tmp_path):
    for key, value, expected in (("scan_in", "custom_si", "fixed port 'sin'"),
                                 ("scan_out", "custom_so", "fixed port 'sout'")):
        project = _project(tmp_path / key, [_chain(**{key: value})])
        binding, problems = S.load_l20_scan_contract(project, "clk", 2)
        assert binding is None
        assert expected in "; ".join(problems)


def test_declared_clock_must_equal_step11_clock(tmp_path):
    project = _project(tmp_path, [_chain(clock="other_clk")])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert binding is None
    assert "does not match Step 11 clock" in "; ".join(problems)


def test_declared_shift_frequency_is_canonicalized_for_the_actuator(tmp_path):
    project = _project(tmp_path, [_chain(frequency_mhz=4)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert problems == []
    assert binding["chain"]["frequency_mhz"] == "4.0"


def test_reconciliation_rejects_measured_length_port_and_clock_mutations(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    base = _report(binding)
    mutations = [
        {"internal_chain_length": 1},
        {"dft_ports": ["shift", "test", "tck", "sout"]},
        {"dft_ports": ["sin", "shift", "test", "tck"]},
        {"clock": "other_clk"},
    ]
    for mutation in mutations:
        report = {**base, **mutation}
        assert S.reconcile_l20_scan_contract(binding, report)["ok"] is False


# D09 planned intent -> the EXISTING run_chain consumer. Native I/O is a
# neutral payload replay, never a claimed new native D23 acceptance result.
import pytest
import hashlib
import spec_declaration_emit as DECL
import librelane_contract as LL


def _intent():
    return {'requires_scan': True,
            'test_port_def': {
                'scan_enable': {'public': 'scan_enable', 'native': 'shift'},
                'scan_in': {'public': 'scan_in', 'native': 'sin'},
                'scan_out': {'public': 'scan_out', 'native': 'sout'},
                'test': {'public': 'test_mode', 'native': 'test'},
                'tck': {'public': 'scan_clock', 'native': 'tck'}},
            'test_mode': {'clock': 'clk', 'clock_domains': ['clk'], 'edge': 'rising',
                          'scan_clock': 'tck', 'scan_clock_domains': ['tck'], 'scan_edge': 'rising',
                          'clock_select': {'native': 'test', 'functional_value': 0, 'scan_value': 1},
                          'reset': {'signal': 'rst', 'style': 'synchronous',
                                    'active_level': 1, 'shift_value': 0}}}


def _mapped(count=2, scan=False):
    ports = 'clk, rst, d, q' + (', sin, sout, shift, test, tck' if scan else '')
    declarations = ('input sin, shift, test, tck; output sout; assign sout=q;\n'
                    if scan else '')
    cells = ''.join(f'  sky130_fd_sc_hd__dfxtp_1 u{i} (.CLK(clk), .D(d), .Q(q));\n'
                    for i in range(count))
    return f'module unit({ports});\ninput clk; input rst; input d; output q;\n{declarations}{cells}endmodule\n'


def _planned(project, intent=None):
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    # The existing D09 declaration artifact, not a separate DFT-intent file.
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nDFT remains planned and unmeasured.\n'
        'The Plugin MUST declare `plugin_output/declaration.json` before authoring:\n\n'
        '| Field | Required | Example |\n|---|---|---|\n| `dft` | Yes | object |\n')
    gd = project / 'phase1/generated_docs'
    gd.mkdir(parents=True)
    from programs.tests._hostpaths import require_repo
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'l20_applicable_unextracted_retained.json')
    (gd / 'L20_DFT_SCAN_TOPOLOGY.json').write_bytes(fixture.read_bytes())
    import l20_dft_intent_emit
    assert l20_dft_intent_emit.run(project)['status'] == 'OK'
    (project / 'input/feature-decisions.json').write_text(json.dumps({'dft': intent or _intent()}))
    assert DECL.main([str(project), '--set', 'dft=' + json.dumps(intent or _intent())]) == 0
    import phase1_one_shot_runner as phase1
    output = phase1._d01_emit_dft_intent(project)
    if output is not None:
        report = project / 'reports/phase1_one_shot.json'; report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'dft_intent_output': output}))
    net = project / 'phase2/stage2/synth/netlist.v'
    net.parent.mkdir(parents=True)
    net.write_text(_mapped())
    return project


def _native_payload(project, monkeypatch, *, actual=2):
    calls = []
    retained = Path(__file__).parent / 'fixtures' / 'd23_native_controls'
    monkeypatch.setattr(S, 'resolve_liberty', lambda pdk, override: (
        str(retained / 'semantic.lib'), 'function-only unit fixture; native integration sealed separately'))
    if actual == 2:
        (project / 'phase2/stage2/synth/netlist.v').write_bytes(
            (retained / 'input_mapped.v').read_bytes())
    def native(project, argv, **kwargs):
        assert argv[:2] == ['fault', 'chain']  # no new native/tool path
        calls.append(argv)
        metadata = {'sin': 'sin', 'sout': 'sout', 'shift': 'shift',
                    'internalCount': 2, 'boundaryCount': 0,
                    'order': [{'name': 'u0', 'kind': 'dff', 'width': 1},
                              {'name': 'u1', 'kind': 'dff', 'width': 1}]}
        artifact = ('/* FAULT METADATA: \'' + json.dumps(metadata)
                    + '\' END FAULT METADATA */\n' + _mapped(actual, scan=True))
        path = project / 'phase2/stage2/dft/scan_chain_work/chained.v'
        if actual == 2:
            path.write_bytes((retained / 'chained.v').read_bytes())
            log = (retained / 'native_chain.log').read_text()
            # Preserve the exact combined native log bytes used by run_chain.
            out, separator, err = log.rpartition('\n')
            assert separator
            return 0, out, err
        path.write_text(artifact)
        return 0, ('Internal scan chain successfully constructed. Length: 2\n'
                   'Boundary scan cells successfully chained. Length: 0\n'
                   'Total scan-chain length: 2\n'), ''
    monkeypatch.setattr(S._fatpg, '_run_docker', native)
    return calls


def test_d09_planned_authority_reaches_existing_native_boundary(tmp_path, monkeypatch):
    project = _planned(tmp_path)
    # This assertion is the substantive reverse: old caller returns False
    # despite real owner declaration, before it can reach the native producer.
    assert D.dft_scan_insertion_contract(project)[0] is True
    calls = []
    def refused_native(project, argv, **kwargs):
        calls.append(argv)
        return 1, '', 'intentional native-boundary refusal in source control'
    monkeypatch.setattr(S._fatpg, '_run_docker', refused_native)
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', require_l20_contract=True)
    assert rc == 1 and report['stage'] == 'chain'
    assert len(calls) == 1 and calls[0][:2] == ['fault', 'chain']
    assert '--l20-contract' not in calls[0]  # no guessed native length argument
    assert not (project / S.SCAN_NETLIST_REL).exists()


def test_d09_native_measurement_publishes_existing_l20_receipt(tmp_path, monkeypatch):
    project = _planned(tmp_path)
    calls = _native_payload(project, monkeypatch)
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', skip_boundary='on', top_module='neutral_unit',
                             require_l20_contract=True)
    assert rc == 0 and report['published'] is True and len(calls) == 1
    assert report['internal_chain_length'] == 2
    assert report['l20_reconciliation']['ok'] is True
    assert S.l20_binding_is_current(project, report)[0] is True
    assert report['functional_clock'] == 'clk' and report['clock'] == 'tck'
    proof = report['native_clock_controls']
    assert proof['mux']['instance'] == '_4_' and len(proof['flop_clocks']) == 2
    assert set(proof['flop_clocks'].values()) == {'__clk_source__'}
    assert report['test_port_def'] == _intent()['test_port_def']
    l20 = json.loads((project / report['l20_contract']['path']).read_text())
    assert l20['fields']['scan_chains'][0]['length'] == 2
    assert l20['fields']['scan_chains'][0]['clock'] == 'tck'
    assert l20['fields']['scan_chains'][0]['functional_clock'] == 'clk'
    assert l20['extraction_evidence']['d09_contract'] == report['d09_contract']
    assert set(report['dft_ports']) == set(S.DFT_PORTS)  # explicit native binding, no renaming
    (project / S.SCAN_NETLIST_REL).write_text(_mapped())
    assert S.l20_binding_is_current(project, report)[0] is False
    # Rehashing a native log/artifact cannot restore an unrelated authority.
    (project / 'input/docs/L7_verification_plan.md').write_text('foreign replacement')
    assert S.l20_binding_is_current(project, report)[0] is False


@pytest.mark.parametrize('damage', ['declaration', 'sidecar', 'publication', 'source'])
def test_d09_forged_authority_cannot_dispatch(tmp_path, monkeypatch, damage):
    project = _planned(tmp_path)
    paths = {'declaration': 'plugin_output/declaration.json',
             'sidecar': 'plugin_output/declaration.provenance.json',
             'publication': 'provenance.jsonl', 'source': 'input/docs/L7_verification_plan.md'}
    path = project / paths[damage]
    path.write_text(path.read_text() + ' altered')
    monkeypatch.setattr(S._fatpg, '_run_docker', lambda *a, **k: pytest.fail('native started'))
    with pytest.raises(LL.Refusal, match='D09_DFT_AUTHORITY_INVALID'):
        D.dft_scan_insertion_contract(project)
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', require_l20_contract=True)
    assert rc == 1 and report['stage'] == 'd09_contract'


@pytest.mark.parametrize('wrong', ['length', 'clock', 'reset', 'polarity', 'domains'])
def test_d09_guessed_or_unsupported_intent_refuses(tmp_path, monkeypatch, wrong):
    intent = _intent()
    if wrong == 'length': intent['chain_length'] = 64
    if wrong == 'clock': intent['test_mode']['clock'] = 'other_clk'
    if wrong == 'reset': intent['test_mode']['reset']['signal'] = 'other_rst'
    if wrong == 'polarity': intent['test_mode']['reset'].update(active_level=0, shift_value=1)
    if wrong == 'domains': intent['test_mode']['clock_domains'].append('other_clk')
    project = _planned(tmp_path, intent)
    monkeypatch.setattr(S._fatpg, '_run_docker', lambda *a, **k: pytest.fail('native started'))
    with pytest.raises(LL.Refusal, match='D09_DFT_AUTHORITY_INVALID'):
        D.dft_scan_insertion_contract(project)


def test_d09_missing_authority_is_named_refusal(tmp_path):
    project = _project(tmp_path, [])
    with pytest.raises(LL.Refusal, match='D09_DFT_AUTHORITY_REQUIRED'):
        D.dft_scan_insertion_contract(project)


def test_d09_explicit_no_scan_is_scan_only_and_composable(tmp_path, monkeypatch):
    intent = {'requires_scan': False, 'reason': 'test declares scan not required', 'bist': {'required': True}, 'compression': {'required': True}}
    project = _planned(tmp_path, intent)
    enabled, reason = D.dft_scan_insertion_contract(project)
    assert enabled is False and 'D09_REQUIRES_SCAN_DISABLED' in reason
    binding, problems = S.load_d09_dft_contract(project)
    assert problems == [] and binding['intent']['bist']['required'] is True
    monkeypatch.setattr(S._fatpg, '_run_docker', lambda *a, **k: pytest.fail('native started'))
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             require_l20_contract=True)
    assert rc == 0 and report['verdict'] == 'NOT_APPLICABLE'
    assert report['reason_code'] == 'D09_REQUIRES_SCAN_DISABLED' and not report['published']


def test_d09_incomplete_native_mapping_does_not_publish(tmp_path, monkeypatch):
    project = _planned(tmp_path)
    _native_payload(project, monkeypatch, actual=1)
    before = (project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').read_bytes()
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', require_l20_contract=True)
    assert rc == 1 and report['published'] is False
    assert any('D23_INCOMPLETE_MAPPING' in p for p in report['problems'])
    assert (project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').read_bytes() == before
    assert not (project / S.SCAN_NETLIST_REL).exists()


# Return1: complete clock-control authority, consuming the exact retained native
# two-DFF artifact. No Fault invocation is executed by these source controls.
def test_d09_old_three_role_intent_must_refuse(tmp_path, monkeypatch):
    intent = _intent()
    for role in ('test', 'tck'):
        intent['test_port_def'].pop(role)
    for key in ('scan_clock', 'scan_clock_domains', 'scan_edge', 'clock_select'):
        intent['test_mode'].pop(key)
    project = _planned(tmp_path, intent)
    monkeypatch.setattr(S._fatpg, '_run_docker', lambda *a, **k: pytest.fail('native started'))
    refused = False
    try:
        allowed, _ = D.dft_scan_insertion_contract(project)
    except LL.Refusal:
        refused, allowed = True, False
    assert allowed is False  # parent returns True: substantive observed VALUE
    assert refused is True  # unknown/incomplete is not a scan-test:false skip


@pytest.mark.parametrize('damage', [
    'missing_test', 'missing_tck', 'changed_test', 'changed_tck',
    'aliased_public_control', 'aliased_public_clock', 'missing_scan_clock',
    'changed_scan_clock', 'aliased_clock_domain', 'missing_select',
    'changed_select', 'swapped_mode_values',
])
def test_d09_complete_control_authority_rejects_damage(tmp_path, monkeypatch, damage):
    intent = _intent()
    defs, mode = intent['test_port_def'], intent['test_mode']
    if damage == 'missing_test': defs.pop('test')
    if damage == 'missing_tck': defs.pop('tck')
    if damage == 'changed_test': defs['test']['native'] = 'shift'
    if damage == 'changed_tck': defs['tck']['native'] = 'clk'
    if damage == 'aliased_public_control': defs['test']['public'] = defs['scan_enable']['public']
    if damage == 'aliased_public_clock': defs['tck']['public'] = 'clk'
    if damage == 'missing_scan_clock': mode.pop('scan_clock')
    if damage == 'changed_scan_clock': mode['scan_clock'] = 'clk'
    if damage == 'aliased_clock_domain': mode['scan_clock_domains'] = ['clk']
    if damage == 'missing_select': mode.pop('clock_select')
    if damage == 'changed_select': mode['clock_select']['native'] = 'shift'
    if damage == 'swapped_mode_values': mode['clock_select'].update(functional_value=1, scan_value=0)
    project = _planned(tmp_path, intent)
    monkeypatch.setattr(S._fatpg, '_run_docker', lambda *a, **k: pytest.fail('native started'))
    binding, problems = S.load_d09_dft_contract(project)
    assert binding is None and problems[0].startswith('D09_DFT_AUTHORITY_INVALID:')
    with pytest.raises(LL.Refusal, match='D09_DFT_AUTHORITY_INVALID'):
        D.dft_scan_insertion_contract(project)


def _wrong_control(text, mutation):
    if mutation == 'mux_scan_input': return text.replace('.A1(tck)', '.A1(clk)')
    if mutation == 'mux_select': return text.replace('.S(test)', '.S(shift)')
    if mutation == 'flop_clock': return text.replace('.CLK(__clk_source__)', '.CLK(clk)', 1)
    raise AssertionError(mutation)


@pytest.mark.parametrize('mutation', ['mux_scan_input', 'mux_select', 'flop_clock'])
def test_d09_actual_native_clock_wiring_blocks_publication(tmp_path, monkeypatch, mutation):
    project = _planned(tmp_path)
    _native_payload(project, monkeypatch)
    replay = S._fatpg._run_docker
    def corrupt(project, argv, **kwargs):
        result = replay(project, argv, **kwargs)
        path = project / 'phase2/stage2/dft/scan_chain_work/chained.v'
        before = path.read_text()
        after = _wrong_control(before, mutation)
        assert after != before
        path.write_text(after)
        return result
    monkeypatch.setattr(S._fatpg, '_run_docker', corrupt)
    before = (project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').read_bytes()
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', skip_boundary='on', top_module='neutral_unit',
                             require_l20_contract=True)
    assert rc == 1 and report['published'] is False
    assert report['problems'][0].startswith('D23_NATIVE_CONTROL_AUTHORITY:')
    assert (project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').read_bytes() == before
    assert not (project / S.SCAN_NETLIST_REL).exists()


@pytest.mark.parametrize('mutation', ['mux_scan_input', 'mux_select', 'flop_clock'])
def test_d09_native_currentness_rederives_controls_after_rehash(tmp_path, monkeypatch, mutation):
    project = _planned(tmp_path)
    _native_payload(project, monkeypatch)
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', 'clk', 'sky130',
                             reset='rst', skip_boundary='on', top_module='neutral_unit',
                             require_l20_contract=True)
    assert rc == 0 and report['published'] and S.l20_binding_is_current(project, report)[0]
    path = project / 'phase2/stage2/dft/scan_chain_work/chained.v'
    changed = _wrong_control(path.read_text(), mutation)
    path.write_text(changed)
    (project / S.SCAN_NETLIST_REL).write_text(changed)
    # A fresh digest/old passing label is insufficient: semantics are re-read.
    report['measured_artifacts'][str(path.relative_to(project))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert S.l20_binding_is_current(project, report)[0] is False


@pytest.mark.parametrize('damage', [None, 'internal_clock', 'boundary_clock',
                                   'unknown_cell', 'unknown_order', 'boundary_reset',
                                   'internal_reset', 'boundary_test', 'mux_select'])
def test_d09_internal_and_boundary_native_control_authority(damage):
    # Actual neutral 2DFF Fault output: internal2 + boundary2, auto boundary.
    retained = Path(__file__).parent / 'fixtures' / 'd23_native_controls'
    text = original = (retained / 'boundary_chained.v').read_text()
    library = (retained / 'semantic.lib').read_text()
    if damage == 'internal_clock':
        text = text.replace('.CLK(\\__uuf__.__clk_source__ )', '.CLK(clk)', 1)
    if damage == 'boundary_clock':
        text = text.replace('.CLK(tck)', '.CLK(clk)', 1)
    if damage == 'unknown_cell':
        text = text.replace('sky130_fd_sc_hd__dfrtp_1 _12_', 'unknown_storage _12_')
    if damage == 'unknown_order':
        text = text.replace('"kind":"input"', '"kind":"unknown"')
    if damage == 'boundary_reset':
        text = text.replace('.RESET_B(_01_)', ".RESET_B(1'b1)", 1)
    if damage == 'internal_reset':
        text = text.replace('.S(rst)', '.S(data)', 1)
    if damage == 'boundary_test':
        text = text.replace('.S(test)', '.S(shift)', 1)
    if damage == 'mux_select':
        text = text.replace('.S(test),\n    .X(\\__uuf__.__clk_source__ )',
                            '.S(shift),\n    .X(\\__uuf__.__clk_source__ )')
    if damage:
        assert text != original
        with pytest.raises(ValueError):
            S._native_clock_controls(text, library, _intent())
    else:
        proof = S._native_clock_controls(text, library, _intent())
        assert [v['kind'] for v in proof['flop_roles'].values()] == ['input', 'dff', 'dff', 'output']
        assert {v['clock'] for v in proof['flop_roles'].values() if v['kind'] == 'dff'} == {'__uuf__.__clk_source__'}
        assert {v['clock'] for v in proof['flop_roles'].values() if v['kind'] != 'dff'} == {'tck'}
        assert proof['functional_value'] == 0 and proof['scan_value'] == 1


def test_d09_boundary_native_measurement_publishes_current_receipt(tmp_path, monkeypatch):
    project = _planned(tmp_path)
    _native_payload(project, monkeypatch)
    replay = S._fatpg._run_docker
    retained = Path(__file__).parent / 'fixtures' / 'd23_native_controls'
    def boundary(project, argv, **kwargs):
        rc, out, err = replay(project, argv, **kwargs)
        (project / 'phase2/stage2/dft/scan_chain_work/chained.v').write_bytes(
            (retained / 'boundary_chained.v').read_bytes())
        return rc, out.replace('chained. Length: 0', 'chained. Length: 2').replace(
            'Total scan-chain length: 2', 'Total scan-chain length: 4'), err
    monkeypatch.setattr(S._fatpg, '_run_docker', boundary)
    rc, report = S.run_chain(project, 'phase2/stage2/synth/netlist.v', pdk='sky130',
                             clock='clk', reset='rst', reset_active_low=False,
                             require_l20_contract=True, top_module='neutral_unit')
    assert rc == 0 and report['published'] is True, report
    assert report['internal_chain_length'] == 2 and report['boundary_chain_length'] == 2
    assert S.l20_binding_is_current(project, report)[0] is True
