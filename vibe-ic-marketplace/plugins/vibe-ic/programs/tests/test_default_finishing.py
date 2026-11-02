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
    # The historical fixture includes the same raw -> separate sealed ->
    # prefill chain as the Default owner. No native execution is claimed here.
    sealed = p / 'phase3/tool_arms/26.5ic/default-stream/sealed.gds'
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_bytes(stream.read_bytes())
    finishing = BF.put(p / 'reports/phase3/die_finishing.json', {
        'producer': 'die_finishing_gen',
        'seal_ring': {'state': 'PASS', 'consumed_into': str(sealed.relative_to(p)),
                      'staged_sha256': LC.digest(sealed)},
        'evidence_kind': 'SOURCE_FIXTURE'})
    recipe = pnr / 'stream_out.py'
    recipe.write_text('# SOURCE_FIXTURE native stream recipe\n')
    material = p / 'fixture_pdk/neutral/stream.lef'
    material.write_text('SOURCE_FIXTURE native material\n')
    cfg = json.loads((folder / 'config.json').read_text())
    cfg['TECH_LEFS'] = ['/pdk/neutral/stream.lef']
    BF.put(folder / 'config.json', cfg)
    BF.put(p / 'phase3/librelane/34-config/KLayout.StreamOut.json', cfg)
    fp = json.loads((folder / 'input_fingerprint.json').read_text())
    fp.update(config=LC.digest(folder / 'config.json'),
              config_files={'/pdk/neutral/stream.lef': LC.digest(material)})
    BF.put(folder / 'input_fingerprint.json', fp)
    argv = ['python3', '/native/stream_out.py', str(filled), '--input-lef', '/pdk/neutral/stream.lef']
    import shlex
    (folder / 'COMMANDS').write_text(shlex.join(argv) + '\n')
    refresh_receipt(folder)
    import _stream_input_record as sir
    readset = sir.build(engine='klayout', output=stream, top='top', project=p,
        project_c=str(p), recipe=recipe, def_file=filled, files={}, scalars={}, rcfile=None, hashes={})
    readset['native_cli'] = {'argv': argv, 'commands': str(folder / 'COMMANDS'),
        'commands_sha256': LC.digest(folder / 'COMMANDS'),
        'inputs': [{'path': '/pdk/neutral/stream.lef', 'project_rel': None,
                    'sha256': LC.digest(material), 'argv_index': 4}]}
    readset_path = sir.write(pnr_gds, readset)
    record.update(finishing_status='PASS', sealed=str(sealed), sealed_sha256=LC.digest(sealed),
        finishing_report=str(finishing), finishing_report_sha256=LC.digest(finishing),
        finishing_stream_sha256=LC.digest(stream), stream_inputs_sha256=LC.digest(readset_path))
    record['stream_state_sha256'] = LC.digest(folder / 'state_out.json')
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
    LF.validate_default_stream(p)
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


def test_relative_project_cli_consumes_the_current_default_density(tmp_path):
    """Actual child CLI and validators; retained native processes are neutral."""
    import subprocess
    import sys
    import os
    p, record, _ = subject(tmp_path)
    output = p / 'relative-step34.json'
    # Carry only this fixture's declared transport and PDK data into the
    # child; no producer/receipt/density validator is replaced.
    bootstrap = '''import runpy, sys
from pathlib import Path
import _container_exec as transport
import pdk_metal_density_windows as windows
import librelane_fill_dfm as finishing
transport.no_container_route = lambda: False
windows._REGISTRY_PATH = Path(sys.argv.pop(1))
try:
    finishing.validate_default_stream(Path('.'))
except ValueError as exc:
    print('SOURCE_CONTROL_RELATIVE_VALIDATOR_EXCEPTION: ' + repr(exc), file=sys.stderr)
script = sys.argv.pop(1)
sys.argv[0] = script
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', bootstrap, str(WINDOWS._REGISTRY_PATH),
        str(Path(MFD.__file__).resolve()), '.', '--json', str(output)],
        cwd=p, capture_output=True, text=True, check=False,
        env=dict(os.environ,
                 PYTHONPATH=str(Path(MFD.__file__).resolve().parent)))
    (p / 'relative-step34.stdout').write_text(result.stdout)
    (p / 'relative-step34.stderr').write_text(result.stderr)
    report = json.loads(output.read_text())
    assert result.returncode == 0, report
    assert report['project_dir'] == '.' and report['summary']['pass'] is True
    assert report['summary']['odb_fill_consumed'] is True
    assert report['summary']['tool_density_errors'] == 0
    assert report['summary']['filled_gds_density'] == 'PASS'
    assert report['tool_per_layer_density']['subject_sha256'] == record['canonical_sha256']


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


def without_switch(project, monkeypatch):
    """Declare the same process/image through the ordinary non-switch inputs."""
    from tapeout_precheck import RUN_PDK_RECORD_REL
    switch = project / 'phase3/librelane_switch.json'
    declared = json.loads(switch.read_text())
    monkeypatch.setenv('VIBEIC_LIBRELANE_IMAGE', declared['image'])
    monkeypatch.delenv('VIBEIC_LIBRELANE_PDK_ROOT', raising=False)
    BF.put(project / RUN_PDK_RECORD_REL,
           {'pdk': declared['pdk'], 'pdk_source': '--pdk'})
    switch.unlink()


@pytest.mark.parametrize('switch_present', [True, False])
def test_ordinary_primary_and_gate_invoke_existing_per_layer_consumer(
        tmp_path, monkeypatch, switch_present):
    p, record, arm = subject(tmp_path)
    if not switch_present:
        without_switch(p, monkeypatch)
    monkeypatch.setattr(R, '_layout_basis', lambda *a: ('current', None))
    monkeypatch.setattr(R._ga, 'stream_refusal', lambda *a: None)
    monkeypatch.setattr(R, '_vacuous_on_unrouted', lambda *a: None)
    # Ruling #101: every D60 invocation streams anew. Real native StreamOut is
    # covered by test_default_stream_epoch_order; this row owns the consumer.
    streams = []

    def fresh_stream(project, top, pdk, container):
        streams.append(top)
        prior = LF.validate_default_stream(project)
        assert LF.current_metal_density(project, arm, prior)['verdict'] == 'PASS'
        return dict(prior, receipt=str(project / LF.DEFAULT_STREAM_REL))

    monkeypatch.setattr(LF, 'default_stream', fresh_stream)
    calls, original = [], MLD.check
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append((str(args[0]), result['verdict']))
        return result
    monkeypatch.setattr(MLD, 'check', observed)
    result = R.step_gds(p, 'top', R.PdkConfig('neutral', '', '', '', None, '', None), '')
    assert result.status == 'PASS', result.detail
    assert streams == ['top']
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
    # step_gds, the Step-34 report, its DFM reference and this explicit audit
    # each invoke the same existing consumer on the same retained bytes.
    assert calls == [(str(p / LF.METAL_DENSITY_REL), 'PASS')] * 4
    assert (p / 'phase3/librelane_switch.json').exists() is switch_present


@pytest.mark.parametrize('mutation,reason', [
    ('malformed_switch', 'Expecting property name'),
    ('conflicting_process', 'LL_PDK_DECLARATION_MISMATCH'),
    ('changed_root', 'LL_PDK_ROOT_CHANGED'),
])
def test_optional_switch_does_not_hide_invalid_declared_material(
        tmp_path, monkeypatch, mutation, reason):
    p, record, arm = subject(tmp_path)
    without_switch(p, monkeypatch)
    assert LF.current_metal_density(p, arm, record)['verdict'] == 'PASS'
    switch = p / 'phase3/librelane_switch.json'
    if mutation == 'malformed_switch':
        switch.write_text('{invalid')
    elif mutation == 'conflicting_process':
        BF.put(switch, {'pdk': 'another-process'})
    else:
        root = p / 'changed-pdk-root'
        root.mkdir()
        monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(root))
    with pytest.raises((ValueError, LC.Refusal), match=reason):
        LF.current_metal_density(p, arm, record)


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


@pytest.mark.parametrize('switch_present', [True, False])
@pytest.mark.parametrize('mutation', ['missing_report', 'empty_layers', 'missing_layer',
    'prefill_subject', 'wrong_ratio_source', 'unexecuted_rules', 'below_floor',
    'wrong_denominator', 'invented_window', 'unknown_windows', 'changed_output_gate'])
def test_zero_errors_cannot_replace_the_current_per_layer_consumer(
        tmp_path, monkeypatch, mutation, switch_present):
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
    if not switch_present:
        without_switch(p, monkeypatch)
    findings, stats = MFD.tool_arm_findings(p)
    ref = DFM.audit(p)['density_ref']
    assert ref['step34_pass'] is False
    assert any(f.severity == 'ERROR' for f in findings), findings
    assert ref['measurement_verdict'] != 'PASS'
    if mutation == 'below_floor':
        assert stats['density_errors'] == 0
        assert ref['measurement_verdict'] == 'FAIL'
        assert ref['per_layer_consumer']['per_layer']['metal2']['status'] == 'FAIL'


def _typed_local_finishing(tmp_path, monkeypatch):
    """Actual run_chain receipts; only the external EDA process writes are neutral."""
    import subprocess
    p, record, arm = subject(tmp_path)
    root = p / 'fixture_pdk'
    source = tmp_path / 'local-librelane'
    (source / 'librelane').mkdir(parents=True)
    (source / 'librelane/__init__.py').write_text('# neutral provider source\n')
    executable = tmp_path / 'local-python'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    switch = p / 'phase3/librelane_switch.json'
    cfg = json.loads(switch.read_text())
    cfg.update(execution_route='LOCAL', local_network_mode='host',
               librelane_root_host=str(source), librelane_executable=str(executable))
    BF.put(switch, cfg)
    namespace = ['net:[1001]']
    monkeypatch.setattr(LC, '_local_network_namespace', lambda: namespace[0])
    image = LC.resolve_image(p)
    LC.pdk_root_resolution(p, 'neutral', image=image)
    doc = json.loads((p / LF.RECORD_REL).read_text())
    tool = doc['odb']['tool']
    stages = [(LF.ODB_FILL_STEP, Path(tool['state'])),
              ('KLayout.StreamOut', Path(record['stream_state'])),
              ('KLayout.Filler', Path(arm['filler']['state'])),
              ('KLayout.Density', Path(arm['state']))]
    payloads, initial, configs = {}, {}, {}
    common = {}
    for view in ('odb', 'nl', 'sdc'):
        path = p / 'phase3/librelane/neutral-inputs' / ('input.' + view)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('neutral ' + view + ' input\n')
        common[view] = str(path)
    for step, state in stages:
        folder = state.parent
        after = json.loads(state.read_text())
        outputs = {path: path.read_bytes() for path in LC._walk_paths(after)
                   if path.is_relative_to(folder)}
        commands = folder / 'COMMANDS'
        payloads[step] = (after, outputs, commands.read_bytes() if commands.exists() else None,
                          (folder / 'invocation.log').read_text())
        before = json.loads((folder / 'state_in.json').read_text())
        if step in (LF.ODB_FILL_STEP, 'KLayout.StreamOut'):
            before.update(common)
        initial[step] = BF.put(p / 'phase3/librelane/neutral-inputs' / (step + '.state.json'), before)
        configs[step] = p / 'phase3/librelane/34-config' / (step + '.json')
    calls = []

    def process_edge(argv, **kwargs):
        step = argv[argv.index('--id') + 1]
        folder = Path(argv[argv.index('-o') + 1])
        after, outputs, commands, log = payloads[step]
        BF.put(folder / 'state_in.json', json.loads(Path(argv[argv.index('-i') + 1]).read_text()))
        BF.put(folder / 'config.json', json.loads(Path(argv[argv.index('-c') + 1]).read_text()))
        for path, data in outputs.items():
            path.write_bytes(data)
        BF.put(folder / 'state_out.json', after)
        if commands is not None:
            (folder / 'COMMANDS').write_bytes(commands)
        calls.append(step)
        return subprocess.CompletedProcess(argv, 0, log, '')

    monkeypatch.setattr(LC, 'run_container', process_edge)
    mounts = [(root, '/pdk')]
    for lane, steps in [('34', [LF.ODB_FILL_STEP]),
                        ('37-default-stream', ['KLayout.StreamOut']),
                        ('34-fill', ['KLayout.Filler', 'KLayout.Density'])]:
        LC.run_chain(p, image, [(step, configs[step], initial[step]) for step in steps],
                     lane=lane, mounts=mounts, pdk_root='/pdk')
    tool['binding'].update(image=str(image), mounts=[[str(root), '/pdk']],
        input_state=str(initial[LF.ODB_FILL_STEP]),
        receipt_sha256=LC.digest(Path(tool['state']).parent / 'vibeic_receipt.json'))
    record['image'] = str(image)
    doc.update(default_stream=record)
    BF.put(p / LF.RECORD_REL, doc)
    BF.put(p / LF.DEFAULT_STREAM_REL, record)
    assert LF.validate_default_stream(p) == record
    receipts = {str(path.parent / name): (path.parent / name).read_bytes()
                for _, path in stages for name in ('vibeic_receipt.json', 'input_fingerprint.json')}
    assert len(calls) == 4
    return p, record, namespace, receipts, source, executable, calls


def test_retained_local_finishing_accepts_a_new_namespace_without_rewriting_receipts(
        tmp_path, monkeypatch):
    p, record, namespace, receipts, _, _, calls = _typed_local_finishing(tmp_path, monkeypatch)
    namespace[0] = 'net:[1002]'
    current = LC.resolve_image(p).as_record()
    previous = json.loads(next(data for path, data in receipts.items()
                               if path.endswith('vibeic_receipt.json')))['input']['local_provider']
    assert {key for key in previous if previous[key] != current[key]} == {'reference', 'network_namespace'}
    observation = {'previous': previous, 'current': current, 'calls': calls}
    try:
        assert LF.validate_default_stream(p) == record
        assert LF.validate_default_stream(p) == record
        assert all(Path(path).read_bytes() == data for path, data in receipts.items())
        assert len(calls) == 4
        observation['accepted'] = True
    except Exception as exc:
        observation['refusal'] = str(exc)
        raise
    finally:
        BF.put(tmp_path / 'LOCAL_FINISHING_OBSERVATION.json', observation)


def test_retained_local_finishing_still_refuses_true_material_and_input_changes(
        tmp_path, monkeypatch):
    observations = []
    for changed in ('source', 'pdk', 'executable', 'policy', 'config', 'state', 'input', 'promotion'):
        with monkeypatch.context() as patch:
            p, record, namespace, _, source, executable, calls = _typed_local_finishing(tmp_path / changed, patch)
            namespace[0] = 'net:[1002]'
            tool = json.loads((p / LF.RECORD_REL).read_text())['odb']['tool']
            if changed == 'source':
                (source / 'librelane/__init__.py').write_text('# changed real source bytes\n')
            elif changed == 'pdk':
                (p / 'fixture_pdk/neutral/stream.lef').write_text('changed real PDK bytes\n')
            elif changed == 'executable':
                executable.write_text('#!/bin/sh\nexit 1\n')
            elif changed == 'policy':
                path = p / 'phase3/librelane_switch.json'
                cfg = json.loads(path.read_text()); cfg['local_network_mode'] = 'none'
                BF.put(path, cfg)
            elif changed == 'config':
                Path(tool['binding']['config']).write_text('{}')
            elif changed == 'state':
                Path(tool['binding']['input_state']).write_text('{}')
            elif changed == 'input':
                subject = Path(tool['subject'])
                subject.write_text(subject.read_text() + '\n# changed real input bytes\n')
            else:
                record['image'] = 'local://librelane@sha256:' + '0' * 64
                BF.put(p / LF.DEFAULT_STREAM_REL, record)
                LF.update_record(p, 'default_stream', record)
            with pytest.raises(LC.Refusal) as refused:
                LF.validate_default_stream(p)
            assert len(calls) == 4
            observations.append({'changed': changed, 'refusal': str(refused.value)})
    BF.put(tmp_path / 'LOCAL_FINISHING_NEGATIVES.json', observations)
    print(json.dumps(observations, indent=2))


def test_retained_density_consumers_leave_readonly_project_unchanged(tmp_path,monkeypatch):
    p,record,_namespace,_receipts,_source,_executable,_calls=_typed_local_finishing(tmp_path,monkeypatch)
    arm=json.loads((p/LF.RECORD_REL).read_text())['gds']['librelane']
    material=[path for path in p.rglob('*') if path.is_file()]
    directories=[p,*[path for path in p.rglob('*') if path.is_dir()]]
    before={str(path.relative_to(p)):LC.digest(path) for path in material}
    modes={path:path.stat().st_mode & 0o777 for path in material+directories}
    try:
        for path in material:path.chmod(0o444)
        for path in directories:path.chmod(0o555)
        current=LF.validate_density_result(p,arm,layout=Path(record['canonical']))
        (tmp_path/'READONLY_DENSITY_OBSERVATION.json').write_text(json.dumps(current,indent=2)+'\n')
        assert current['value']==0,current
        measured=LF.current_metal_density(p,arm,record)
        assert measured['verdict']=='PASS',measured
        assert before=={str(path.relative_to(p)):LC.digest(path) for path in material}
    finally:
        for path,mode in modes.items():path.chmod(mode)
