"""Default Steps 34/35/37: retained-byte source controls, not native proof."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import _plugin_tree  # noqa: F401
from _hostpaths import require_repo
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_fill_dfm as LF
import metal_fill_density_check as MFD
import dfm_screen_check as DFM
import phase3_one_shot_runner as R
import metal_layer_density_check as MLD
import pdk_metal_density_windows as WINDOWS
from test_metal_fill_config_gen import _LAYERMAP, _TECHLEF, _DECK

PROMOTION = 'phase3/librelane/37-default-promotion.json'
_DENSITY_DECK = ('chip_area = extent.sized(0.0).area\n' + _DECK).replace(
    'if (metal1.area', '# Rule M1.4: synthetic whole-die metal1\nif (metal1.area').replace(
    'if (metal2.area', '# Rule M2.4: synthetic whole-die metal2\nif (metal2.area')


@pytest.fixture(autouse=True)
def neutral_declared_windows(tmp_path, monkeypatch):
    # Source controls use the existing synthetic PDK input, never a foundry
    # threshold disguised as a design-specific production default.
    from _stated_eda_image import mock_docker_route
    mock_docker_route(monkeypatch)
    registry = BF.put(tmp_path / 'source-fixture-pdk-registry.json', {'pdks': [{
        'name': 'neutral', 'metal_density_windows': {
            'layers': {'metal1': [0.33, None], 'metal2': [0.33, None]},
            '_scope': 'WHOLE-DIE synthetic input deck',
            '_source': 'SOURCE_FIXTURE _DECK states 33 percent and no maximum'}}]})
    monkeypatch.setattr(WINDOWS, '_REGISTRY_PATH', registry)


def refresh_receipt(folder):
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    receipt['input'] = json.loads((folder / 'input_fingerprint.json').read_text())
    receipt['sha256'] = {str(f.relative_to(folder)): LC.digest(f)
                        for f in folder.rglob('*') if f.is_file() and f.name != 'vibeic_receipt.json'}
    BF.put(folder / 'vibeic_receipt.json', receipt)


def density_recipe(p, arm):
    root = p / 'fixture_pdk/neutral'
    for name, text in {'layers.map': _LAYERMAP, 'tech.lef': _TECHLEF,
                       'density.rb': _DENSITY_DECK}.items():
        (root / name).write_text(text)
    config = p / 'phase3/librelane/34-config/KLayout.Density.json'
    cfg = json.loads(config.read_text())
    cfg.update(KLAYOUT_DEF_LAYER_MAP='/pdk/neutral/layers.map',
               TECH_LEFS={'nominal': '/pdk/neutral/tech.lef'},
               KLAYOUT_DENSITY_RUNSET='/pdk/neutral/density.rb')
    BF.put(config, cfg)
    folder = Path(arm['state']).parent
    BF.put(folder / 'config.json', cfg)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(config), config_files=LC.config_file_hashes(
        cfg, [(root, '/pdk/neutral')]))
    BF.put(folder / 'input_fingerprint.json', fp)
    (folder / 'invocation.log').write_text('SOURCE_FIXTURE: substituted native process\n'
                                          'Executing rule M1.4\nExecuting rule M2.4\n')
    refresh_receipt(folder)
    specs = LF._density_ratio_specs(_DENSITY_DECK,
                                   LF.build_metal_fill_config(_LAYERMAP, _TECHLEF, _DECK))
    rows = {rule: dict(spec, ratio=0.40) for rule, spec in specs.items()}
    report = BF.put(p / 'phase3/librelane/34-fill-ratios/density_ratios.json', {
        'status': 'MEASURED', 'gds': arm['subject'], 'die_area_um2': 100.0,
        'die': [0, 0, 10, 10], 'extent_from_deck': True, 'layers': rows})
    arm['ratios'] = {'report': str(report), 'report_sha256': LC.digest(report),
                     'subject_sha256': arm['subject_sha256'], 'layers': rows}


def subject(tmp_path):
    p = tmp_path / 'project'
    pnr = p / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    artifact = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                            'calibration', 'pg_supply_owned_negative.def')
    for name in ('top.def', 'routed.def'):
        (pnr / name).write_bytes(artifact.read_bytes())
    odb = BF.fill_record(p)
    BF.consume_fill(p, odb)
    LF.update_record(p, 'odb', {'shipped': 'librelane', 'tool': odb,
                              'def_sha256': LC.digest(pnr / 'routed.def')})
    filled = pnr / 'filled.def'
    stream = p / 'phase3/librelane/37-default-stream/01-klayout-streamout/top.gds'
    stream.parent.mkdir(parents=True)
    stream.write_bytes(b'SOURCE_FIXTURE: real stream bytes are measured separately')
    folder, _ = BF.producer(p, 'KLayout.StreamOut', {'def': str(filled), 'metrics': {}},
        {'def': str(filled), 'klayout_gds': str(stream), 'metrics': {}},
        lane='37-default-stream/01-klayout-streamout', name=LC._def_design_name(filled))
    prefill = p / 'phase3/tool_arms/34/prefill.gds'
    prefill.write_bytes(stream.read_bytes())
    source = p / 'phase3/librelane/34-fill/01-klayout-filler/top.gds'
    source.parent.mkdir(parents=True)
    source.write_bytes(stream.read_bytes() + b' plus filler')
    ff, _ = BF.producer(p, 'KLayout.Filler', {'gds': str(prefill), 'metrics': {}},
        {'gds': str(source), 'metrics': {}}, lane='34-fill/01-klayout-filler')
    arm = BF.density_record(p, source, 0)
    density_recipe(p, arm)
    arm['filler'] = {'state': str(ff / 'state_out.json'),
        'state_sha256': LC.digest(ff / 'state_out.json'), 'gds_in': str(prefill),
        'gds_in_sha256': LC.digest(prefill), 'filled_gds': str(source),
        'filled_sha256': LC.digest(source)}
    canonical = p / 'phase3/stage4/gds/top.gds'
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(source.read_bytes())
    pnr_gds = pnr / 'top.gds'
    pnr_gds.write_bytes(source.read_bytes())
    record = {'file_top': 'top', 'design_name': LC._def_design_name(filled),
        'image': BF.IMAGE, 'pdk': 'neutral',
        'stream_state': str(folder / 'state_out.json'),
        'stream_state_sha256': LC.digest(folder / 'state_out.json')}
    for key, path in dict(filled_def=filled, stream=stream, prefill=prefill,
                          source=source, pnr_gds=pnr_gds, canonical=canonical).items():
        record[key], record[key + '_sha256'] = str(path), LC.digest(path)
    record['gates'] = {}
    for name in ('substance', 'port_labels'):
        report = BF.put(p / 'phase3/librelane' / f'37-default-{name}.json',
                        {'verdict': 'PASS', 'evidence_kind': 'SOURCE_FIXTURE'})
        record['gates'][name] = {'rc': 0, 'report': str(report), 'sha256': LC.digest(report)}
    LF.update_record(p, 'gds', {'shipped': 'librelane', 'librelane': arm,
                              'shipped_sha256': LC.digest(source)})
    BF.put(p / PROMOTION, record)
    LF.update_record(p, 'default_stream', record)
    BF.put(p / 'reports/phase3/density.json', {'filler_instances': 7, 'row_utilization_pct': 100})
    assert LF.publish_metal_density(p, arm['ratios'], canonical, 'neutral') is not None
    return p, record, arm


def test_current_finished_bytes_are_consumed_by_both_existing_rows(tmp_path):
    p, record, arm = subject(tmp_path)
    findings, stats = MFD.tool_arm_findings(p)
    assert findings == [] and stats['density_errors'] == 0
    assert stats['per_layer_density_verified'] is True and stats['layers_ok'] == 2
    ref = DFM.audit(p)['density_ref']
    assert ref['step34_pass'] is True
    assert ref.get('subject_sha256') == record['canonical_sha256']
    assert ref.get('measurement_verdict') == 'PASS'
    assert ref['per_layer_consumer']['consumer'] == 'metal_layer_density_check.check'
    assert ref['per_layer_consumer']['subject_sha256'] == record['canonical_sha256']


@pytest.mark.parametrize('mutation', ['stream_execution', 'filler_execution', 'filled_def',
    'stream_bytes', 'wrong_stage', 'wrong_design', 'wrong_tool', 'image', 'pdk',
    'canonical', 'pnr_copy', 'promotion_removed', 'consumer_record_removed',
    'filler_input', 'filler_output', 'filled_def_gds_mismatch'])
def test_existing_rows_refuse_a_broken_finishing_chain(tmp_path, mutation):
    p, record, arm = subject(tmp_path)
    assert MFD.tool_arm_findings(p)[0] == []
    state = Path(record['stream_state'])
    if mutation in ('stream_execution', 'filler_execution'):
        selected = state if mutation == 'stream_execution' else Path(arm['filler']['state'])
        (selected.parent / 'invocation.log').unlink()
    elif mutation in ('filled_def', 'stream_bytes', 'canonical', 'pnr_copy', 'filler_input', 'filler_output'):
        key = {'stream_bytes': 'stream', 'pnr_copy': 'pnr_gds',
               'filler_input': 'prefill', 'filler_output': 'source'}.get(mutation, mutation)
        Path(record[key]).write_bytes(b'changed current subject')
    elif mutation == 'wrong_stage':
        foreign = p / 'phase2/foreign/state_out.json'
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(state.read_bytes())
        record.update(stream_state=str(foreign), stream_state_sha256=LC.digest(foreign))
    elif mutation in ('wrong_design', 'wrong_tool'):
        step = 'KLayout.StreamOut' if mutation == 'wrong_design' else 'Yosys.Synthesis'
        BF.producer(p, step, json.loads((state.parent / 'state_in.json').read_text()),
            json.loads(state.read_text()), lane='37-default-stream/01-klayout-streamout',
            name='another' if mutation == 'wrong_design' else record['design_name'])
        record['stream_state_sha256'] = LC.digest(state)
    elif mutation in ('image', 'pdk'):
        switch = p / 'phase3/librelane_switch.json'
        doc = json.loads(switch.read_text())
        if mutation == 'image':
            doc['image'] = BF.IMAGE.replace('a' * 64, 'b' * 64)
        else:
            doc['pdk_root_host'] = str(p / 'another-pdk')
            (p / 'another-pdk/neutral').mkdir(parents=True)
        BF.put(switch, doc)
    elif mutation == 'promotion_removed':
        (p / PROMOTION).unlink()
    elif mutation == 'consumer_record_removed':
        doc = json.loads((p / LF.RECORD_REL).read_text())
        del doc['default_stream']
        BF.put(p / LF.RECORD_REL, doc)
    else:
        # A coherent stream packet reads the unfilled DEF instead. Density
        # and all GDS outputs still match; only adoption is wrong.
        before = json.loads((state.parent / 'state_in.json').read_text())
        before['def'] = str(p / 'phase3/stage3/pnr/top.def')
        BF.producer(p, 'KLayout.StreamOut', before, json.loads(state.read_text()),
            lane='37-default-stream/01-klayout-streamout', name=record['design_name'])
        record['stream_state_sha256'] = LC.digest(state)
    if mutation in ('wrong_stage', 'wrong_design', 'wrong_tool', 'filled_def_gds_mismatch'):
        BF.put(p / PROMOTION, record)
        LF.update_record(p, 'default_stream', record)
    findings, _ = MFD.tool_arm_findings(p)
    assert any(f.severity == 'ERROR' for f in findings), findings
    assert DFM.audit(p)['density_ref']['step34_pass'] is False


def test_real_density_failure_remains_explicit_in_the_dfm_reference(tmp_path):
    p, _, arm = subject(tmp_path)
    # This is a failed tool arm, so no successful finishing promotion exists.
    (p / PROMOTION).unlink()
    (p / 'phase3/librelane/34-config/KLayout.StreamOut.json').unlink()
    doc = json.loads((p / LF.RECORD_REL).read_text())
    del doc['default_stream']
    BF.put(p / LF.RECORD_REL, doc)
    bad = BF.density_record(p, Path(arm['subject']), 5)
    LF.update_record(p, 'gds', {'shipped': 'librelane', 'librelane': bad})
    assert MFD.tool_arm_findings(p)[1]['density_errors'] == 5
    ref = DFM.audit(p)['density_ref']
    assert ref['step34_pass'] is False and ref['errors'] == 5
    assert ref.get('measurement_verdict') == 'FAIL'


def test_default_ordinary_caller_uses_one_primary_without_a_mode_switch(tmp_path, monkeypatch):
    p, record, _ = subject(tmp_path)
    assert 'steps' not in json.loads((p / 'phase3/librelane_switch.json').read_text())
    monkeypatch.setattr(R, '_layout_basis', lambda *a: ('current', None))
    monkeypatch.setattr(R._ga, 'stream_refusal', lambda *a: None)
    monkeypatch.setattr(R, '_vacuous_on_unrouted', lambda *a: None)
    calls = []
    def primary(*args):
        calls.append('primary')
        return {'canonical': record['canonical'], 'receipt': str(p / PROMOTION)}
    monkeypatch.setattr(LF, 'default_stream', primary, raising=False)
    # Stop a legacy producer at its first concrete decision; count observed
    # dispatch values rather than a missing symbol or a collection error.
    monkeypatch.setattr(R, 'publish_database_unit_declaration', lambda *a: {'verdict': 'PASS', 'reason': 'SOURCE_FIXTURE'})
    monkeypatch.setattr(R, '_streamout_top', lambda *a: ('top', ''))
    monkeypatch.setattr(R, 'publish_tapeout_declarations', lambda *a: {'published': [], 'not_determined': [], 'already_answered': []})
    def legacy(*args):
        calls.append('legacy')
        raise LC.Refusal('SOURCE_FIXTURE_LEGACY_SELECTED', 'observed legacy producer')
    monkeypatch.setattr(R, '_magic_def_to_gds', legacy)
    pdk = R.PdkConfig('neutral', '', '', '', None, '', None)
    try:
        R.step_gds(p, 'top', pdk, '')
    except LC.Refusal:
        pass
    assert calls == ['primary']


def test_ordinary_primary_and_gate_invoke_existing_per_layer_consumer(tmp_path, monkeypatch):
    p, record, _ = subject(tmp_path)
    monkeypatch.setattr(R, '_layout_basis', lambda *a: ('current', None))
    monkeypatch.setattr(R._ga, 'stream_refusal', lambda *a: None)
    monkeypatch.setattr(R, '_vacuous_on_unrouted', lambda *a: None)
    # The retained current result must be adopted without another producer.
    monkeypatch.setattr(LF, 'run_chain', lambda *a, **k: pytest.fail('duplicate producer'))
    calls, original = [], MLD.check
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append((str(args[0]), result['verdict']))
        return result
    monkeypatch.setattr(MLD, 'check', observed)
    result = R.step_gds(p, 'top', R.PdkConfig('neutral', '', '', '', None, '', None), '')
    assert result.status == 'PASS'
    assert MFD.main([str(p), '--json', str(p / 'step34.json')]) == 0
    report = json.loads((p / 'step34.json').read_text())
    assert report['summary']['per_layer_density_verified'] is True
    assert report['summary']['layers_ok'] == 2
    assert report['summary']['filled_gds_density'] == 'PASS'
    categories = [f['category'] for f in report['findings']]
    assert 'PER_LAYER_DENSITY_NOT_VERIFIED_HERE' not in categories
    assert 'PER_LAYER_DENSITY_CONSUMED' in categories
    consumer = report['tool_per_layer_density']
    assert 'PDK-stated minimum 0.33' in consumer['window_note']
    assert 'measured absence of maximum' in consumer['window_note']
    assert 'generic' not in consumer['window_note'] and '[None,None]' not in consumer['window_note']
    assert all(row['window'] == [0.33, None] and 'PDK-measured-absence' in row['window_source']
               for row in consumer['per_layer'].values())
    ref = DFM.audit(p)['density_ref']
    assert ref['step34_pass'] is True
    assert ref['per_layer_consumer']['subject_sha256'] == record['canonical_sha256']
    assert calls == [(str(p / LF.METAL_DENSITY_REL), 'PASS')] * 3


def test_unverified_tool_path_retains_disclosure_and_refusal(tmp_path):
    p, _, _ = subject(tmp_path)
    (p / LF.METAL_DENSITY_REL).unlink()
    output = p / 'step34-unverified.json'
    assert MFD.main([str(p), '--json', str(output)]) == 1
    report = json.loads(output.read_text())
    assert report['summary']['pass'] is False
    assert report['summary']['per_layer_density_verified'] is False
    categories = [f['category'] for f in report['findings']]
    assert 'PER_LAYER_DENSITY_NOT_VERIFIED_HERE' in categories
    assert 'PER_LAYER_DENSITY_CONSUMED' not in categories


@pytest.mark.parametrize('mutation', ['missing_report', 'empty_layers', 'missing_layer',
    'prefill_subject', 'wrong_ratio_source', 'unexecuted_rules', 'below_floor',
    'wrong_denominator', 'invented_window', 'unknown_windows', 'changed_output_gate'])
def test_zero_errors_cannot_replace_the_current_per_layer_consumer(tmp_path, mutation):
    p, record, arm = subject(tmp_path)
    path = p / LF.METAL_DENSITY_REL
    doc = json.loads(path.read_text())
    if mutation == 'missing_report':
        path.unlink()
    elif mutation in ('empty_layers', 'missing_layer'):
        doc['layers'] = {} if mutation == 'empty_layers' else {'metal1': doc['layers']['metal1']}
    elif mutation == 'prefill_subject':
        doc.update(gds=record['prefill'], gds_sha256=record['prefill_sha256'])
    elif mutation == 'wrong_ratio_source':
        doc['source']['report_sha256'] = '0' * 64
    elif mutation == 'invented_window':
        doc['windows'] = {'metal1': [0, 1], 'metal2': [0, 1]}
    elif mutation == 'unexecuted_rules':
        folder = Path(arm['state']).parent
        (folder / 'invocation.log').write_text('SOURCE_FIXTURE: 0 errors, no executed rules\n')
        refresh_receipt(folder)
    elif mutation == 'unknown_windows':
        BF.put(WINDOWS._REGISTRY_PATH, {'pdks': []})
    elif mutation == 'changed_output_gate':
        Path(record['gates']['substance']['report']).write_text('{"verdict":"FAIL"}')
    else:
        raw_path = Path(arm['ratios']['report'])
        raw = json.loads(raw_path.read_text())
        if mutation == 'below_floor':
            raw['layers']['M2.4']['ratio'] = 0.10
            arm['ratios']['layers'] = raw['layers']
            doc['layers']['metal2'] = 0.10
        else:
            raw['die_area_um2'] = 50.0
            doc['die_area_um2'] = 50.0
        BF.put(raw_path, raw)
        arm['ratios']['report_sha256'] = LC.digest(raw_path)
        doc['source']['report_sha256'] = LC.digest(raw_path)
        LF.update_record(p, 'gds', {'shipped': 'librelane', 'librelane': arm,
                                  'shipped_sha256': arm['subject_sha256']})
    if mutation != 'missing_report':
        BF.put(path, doc)
    findings, stats = MFD.tool_arm_findings(p)
    ref = DFM.audit(p)['density_ref']
    assert ref['step34_pass'] is False
    assert any(f.severity == 'ERROR' for f in findings), findings
    assert ref['measurement_verdict'] != 'PASS'
    if mutation == 'below_floor':
        assert stats['density_errors'] == 0
        assert ref['measurement_verdict'] == 'FAIL'
        assert ref['per_layer_consumer']['per_layer']['metal2']['status'] == 'FAIL'
