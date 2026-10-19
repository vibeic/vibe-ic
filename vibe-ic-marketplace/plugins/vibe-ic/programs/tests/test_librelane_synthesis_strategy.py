"""Declared strategy authority through real emitters and handoff consumers.

Native mapping/LEC measurements live in the separate neutral EDA campaign;
receipt-shaped software fixtures here make no native qualification claim.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
import librelane_contract as LC
import synth_handoff_netlist_check as H
import phase3_one_shot_runner as R
from _ppa.synthesis import STRATEGIES
from test_step14_report_producer_authorship import project_fixture, put, digest


def switch(project, declaration):
    return put(project / 'phase3/librelane_switch.json', {
        'steps': {'9': 'librelane'}, 'synthesis_levers': declaration})


def emitter_project(tmp_path):
    p = tmp_path / 'project'
    put(p / 'input/submission_template/tapeout_declaration.json', {
        'schema': 'vibe-ic/tapeout_declaration/1', 'answers': {}})
    put(p / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'role': 'primary', 'source_pin': 'clk', 'period_ns': 20}]})
    put(p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'top'})
    put(p / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': {'pdk_target': 'neutral'}})
    rtl = p / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a,output y); assign y=a; endmodule\n')
    return p, rtl


@pytest.mark.parametrize('strategy', STRATEGIES)
def test_declared_strategy_reaches_emitter_and_provenance(tmp_path, strategy):
    p, rtl = emitter_project(tmp_path)
    out = p / 'synth.json'
    before = LC.emit_synthesis_config(p, 'neutral', out, [rtl], [], False)
    assert 'SYNTH_STRATEGY' not in before
    switch(p, {'SYNTH_STRATEGY': strategy})
    emitted = LC.emit_synthesis_config(p, 'neutral', out, [rtl], [], False)
    assert emitted == {**before, 'SYNTH_STRATEGY': strategy}
    provenance = json.loads(out.with_suffix('.provenance.json').read_text())
    assert provenance['SYNTH_STRATEGY'] == (
        'phase3/librelane_switch.json synthesis_levers.SYNTH_STRATEGY')


@pytest.mark.parametrize('bad', [None, False, 1, 'DELAY 2', [],
    {'SYNTH_STRATEGY': None}, {'SYNTH_STRATEGY': True}, {'SYNTH_STRATEGY': 2},
    {'SYNTH_STRATEGY': ['DELAY 2']}, {'SYNTH_STRATEGY': 'DELAY 9'},
    {'SYNTH_STRATEGY': 'delay 2'}, {'SYNTH_STRATEGY': ' DELAY 2'},
    {'LIB': {'*': ['other.lib']}}, {'CLOCK_PERIOD': 40},
    {'SYNTH_CORNER': 'slow'}, {'SYNTH_ABC_DFF': True},
    {'SYNTH_STRATEGY': 'DELAY 2', 'arbitrary': 1}])
def test_invalid_overlay_cannot_reach_native_config(tmp_path, bad):
    p, rtl = emitter_project(tmp_path)
    switch(p, bad)
    with pytest.raises(LC.Refusal, match='LL_SYNTH_LEVER_'):
        LC.emit_synthesis_config(p, 'neutral', p / 'synth.json', [rtl], [], False)


def admit(project, declaration, strategy):
    """Publish a changed neutral receipt-shaped fixture through the real owner."""
    switch(project, declaration)
    folder = project / 'phase3/librelane/02-yosys-synthesis'
    resolved = project / 'phase3/librelane/synthesis_resolved.json'
    cfg = json.loads(resolved.read_text())
    cfg['SYNTH_STRATEGY'] = strategy
    put(resolved, cfg)
    put(folder / 'config.json', cfg)
    inp = json.loads((folder / 'input_fingerprint.json').read_text())
    inp['config'] = digest(resolved)
    inp['synthesis_levers'] = declaration
    put(folder / 'input_fingerprint.json', inp)
    receipt = {'input': inp, 'sha256': {
        str(q.relative_to(folder)): digest(q) for q in folder.rglob('*')
        if q.is_file() and q.name != 'vibeic_receipt.json'}}
    put(folder / 'vibeic_receipt.json', receipt)
    return H.publish_handoff(project, folder, project / 'phase2/stage2/synth/core_synth.v', 'core')


@pytest.mark.parametrize('declaration', [{}, {'SYNTH_STRATEGY': 'AREA 0'},
                                      {'SYNTH_STRATEGY': 'DELAY 2'}])
def test_raw_authority_change_or_removal_refuses_even_if_default_unchanged(tmp_path, declaration):
    p, _ = project_fixture(tmp_path)
    binding = admit(p, declaration, declaration.get('SYNTH_STRATEGY', 'AREA 0'))
    assert binding['synthesis_levers'] == declaration
    assert H.bound_handoff(p)['verdict'] == 'PASS'
    path = p / 'phase3/librelane_switch.json'
    original = path.read_bytes()
    for changed in ({'steps': {'9': 'librelane'}},
                    {'steps': {'9': 'librelane'}, 'synthesis_levers': {'SYNTH_STRATEGY': 'DELAY 4'}}):
        put(path, changed)
        assert H.bound_handoff(p)['verdict'] == 'FAIL'
        with pytest.raises(ValueError):
            R.pnr_input_netlist(p, 'core')
    path.write_bytes(original)
    assert H.bound_handoff(p)['verdict'] == 'PASS'
    assert R.pnr_input_netlist(p, 'core')[0].name == 'core_synth.v'


def test_old_default_receipt_cannot_adopt_new_explicit_area0_authority(tmp_path):
    p, _ = project_fixture(tmp_path)
    assert H.bound_handoff(p)['verdict'] == 'PASS'
    switch(p, {'SYNTH_STRATEGY': 'AREA 0'})
    assert H.bound_handoff(p)['verdict'] == 'FAIL'


def test_publisher_refuses_declared_strategy_not_carried_by_native_config(tmp_path):
    p, _ = project_fixture(tmp_path)
    switch(p, {'SYNTH_STRATEGY': 'DELAY 2'})
    with pytest.raises(ValueError, match='synthesis declaration differs'):
        H.publish_handoff(p, p / 'phase3/librelane/02-yosys-synthesis',
                          p / 'phase2/stage2/synth/core_synth.v', 'core')


def test_sidecar_cannot_backfill_new_area0_authority_into_old_native_receipt(tmp_path):
    p, _ = project_fixture(tmp_path)
    switch(p, {'SYNTH_STRATEGY': 'AREA 0'})
    sidecar = p / 'phase2/stage2/synth/synth_inputs.json'
    doc = json.loads(sidecar.read_text())
    doc['librelane_synthesis']['synthesis_levers'] = {'SYNTH_STRATEGY': 'AREA 0'}
    put(sidecar, doc)
    report = H.bound_handoff(p)
    assert report['verdict'] == 'FAIL'
    assert 'native producer synthesis declaration' in str(report)


@pytest.mark.parametrize('wrong_strategy', ['AREA 0', 'DELAY 4'])
def test_raw_receipt_does_not_excuse_wrong_effective_native_value(tmp_path, wrong_strategy):
    p, _ = project_fixture(tmp_path)
    with pytest.raises(ValueError, match='strategy differs'):
        admit(p, {'SYNTH_STRATEGY': 'DELAY 2'}, wrong_strategy)


@pytest.mark.parametrize('mode', ['direct', 'dual'])
def test_present_declaration_cannot_be_silently_ignored_by_other_route(tmp_path, monkeypatch, mode):
    import execution_production
    monkeypatch.setattr(execution_production, 'dispatch_site', lambda *a, **k: None)
    put(tmp_path / 'phase3/librelane_switch.json', {
        'steps': {'9': mode}, 'synthesis_levers': {'SYNTH_STRATEGY': 'DELAY 2'}})
    row = R.step_synth(tmp_path, 'core', SimpleNamespace(name='neutral'), 'container')
    assert row.status == 'FAIL'
    assert 'LL_SYNTH_LEVER_ROUTE_UNSUPPORTED' in row.detail
