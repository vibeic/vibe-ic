"""POST protocol software controls; these fixtures are not native qualification."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import analog_incremental_post_layout as post
import analog_incremental_capture as capture
import analog_incremental_pvt as pvt
from test_analog_incremental_statistics import method as statistical_method, pvt_method, _write_probe
from test_analog_incremental_pvt import _native_fixture_series as _fixture_series
from test_analog_incremental_capture import _dump


def _timed_dump(path, common, topology):
    """Synthetic phase values under the actual prepared observation names."""
    timing = capture._transfer_timing(topology, common['reset_node'], common.get('transfer_gate_nodes'))
    path = _dump(path)
    n_columns = {group['n_gate'] for group in timing['groups']}
    p_columns = {group['p_gate'] for group in timing['groups']}
    assert not n_columns & p_columns
    lines = path.read_text().splitlines()
    lines[0] = 'time output reset input ' + ' '.join(timing['columns'])
    for index in range(1, len(lines)):
        fields = lines[index].split()
        phase = [fields[4] if column in n_columns else fields[5] for column in timing['columns']]
        lines[index] = ' '.join([*fields[:4], *phase])
    path.write_text('\n'.join(lines))
    return path


def _native_fixture_series(context, limit=None):
    project = Path(context['project'])
    common = post._read(context['settings']['path'])
    topology = post._read(project / 'phase3/analog/converter/topology.json')
    with patch.dict(_fixture_series.__globals__,
                    {'_dump': lambda path: _timed_dump(path, common, topology)}):
        return _fixture_series(context, limit)


@pytest.fixture
def source(statistical_method, tmp_path):
    project, settings, library, _model = statistical_method
    directory = project / 'phase3/analog/converter'
    net = directory / 'converter.sp'
    net.write_text(net.read_text().replace('.subckt conv ', '.param source_header=0.75\n.subckt converter ').replace('.ends conv',
        'r_reset reset_b 0 1k\n.ends converter'))
    tb = directory / 'tb_converter.sp'
    tb.write_text(tb.read_text().replace('dout conv', 'dout converter'))
    library.write_text(library.read_text() +
        '\n.lib device_ss\n.param ss=1\n.endl device_ss\n.lib device_ff\n.param ff=1\n.endl device_ff\n')
    plan = pvt.prepare(project, 'converter', settings, tmp_path / 'PRE-pvt', library,
        ['device_tt', 'device_ss', 'device_ff'], image='fixture-image', reference_ports=['ref_hi', 'ref_lo'])
    plan_path = tmp_path / 'PRE-pvt-manifest.json'; capture.write_json(plan_path, plan)
    gds = net.with_suffix('.gds'); gds.write_bytes(b'software layout identity fixture')
    tech = tmp_path / 'native-tech.flat'
    tech.write_text('extract\nstyle ngspice variants (), (fast)\nend\n')
    rows = []
    body = net.read_text()[net.read_text().index('.subckt converter'):]
    for style in ('ngspice()', 'ngspice(fast)'):
        raw = tmp_path / (post.a7._style_slug(style) + '.spice')
        raw.write_text(body.replace('.ends converter', 'rpex ain split 5\ncpex split 0 1f\n.ends converter'))
        rows.append({'style': style, 'extracted_netlist': str(raw), 'sha256': capture.bound.sha(raw)})
    extraction = tmp_path / 'A13.json'
    capture.write_json(extraction, {'status': 'PASS', 'metrics': {'netlist_sha256': capture.bound.sha(net),
        'layout_sha256': capture.bound.sha(gds), 'magic_tech': str(tech), 'corners': rows}})
    return {'project': project, 'settings': settings, 'pre_plan': plan_path, 'pre_score': tmp_path / 'PRE-score/score.json',
            'extraction': extraction, 'technology': tech}


def prepared(source, root, **kwargs):
    return post.prepare(source['project'], 'converter', source['settings'], source['extraction'],
        source['pre_plan'], source['pre_score'], root, 'fixture-image', **kwargs)


def nominal(source):
    paths = pvt._paths(source['project'], 'converter')
    _native_fixture_series({'project': str(source['project']), 'settings': post._view(source['settings']),
        'native_inputs': {role: post._view(path) for role, path in paths.items()},
        'score': str(source['pre_score']), 'temperature_c': 27})


def test_prepare_uses_actual_wrapper_reset_and_whole_pre_pvt_matrix(source, tmp_path):
    original = {str(path): path.read_bytes() for path in source['project'].rglob('*') if path.is_file()}
    manifest = prepared(source, tmp_path / 'POST', samples=2)
    assert manifest['kind'] == post.KIND and manifest['stage'] == 'POST'
    assert manifest['expected_styles'] == ['ngspice()', 'ngspice(fast)']
    assert post._validate(manifest)['kind'] == 'incremental_capture_pvt'
    configuration, probes = post._validate_statistics(manifest, 2)
    assert configuration['samples'] == 2 and len(probes) == 10
    for style in manifest['styles']:
        plan = post._read(style['pvt_manifest']['path'])
        assert len(plan['contexts']) == 9
        assert plan['common_settings']['reset_node'] == 'xdut.xrcx.reset_b'
        wrapper = Path(style['native_inputs']['netlist']['path']).read_text()
        assert wrapper.count('.subckt ') == 1 and '.include "' in wrapper and 'xrcx ' in wrapper
        assert '.param source_header=0.75' in wrapper
        assert 'rpex ain split 5' in Path(style['extracted_body']['path']).read_text()
    assert all(Path(path).read_bytes() == value for path, value in original.items())


def test_transfer_gate_exposed_as_extra_native_port_uses_wrapper_forwarding(source, tmp_path):
    extraction = post._read(source['extraction'])
    for corner in extraction['metrics']['corners']:
        path = Path(corner['extracted_netlist'])
        lines = path.read_text().splitlines()
        lines = [line + ' transfer_n transfer_p' if line.startswith('.subckt converter ') else line
                 for line in lines]
        path.write_text('\n'.join(lines) + '\n')
        corner['sha256'] = capture.bound.sha(path)
    capture.write_json(source['extraction'], extraction)
    manifest = prepared(source, tmp_path / 'POST-forwarded-gates')
    for style in manifest['styles']:
        mapping = style['probe_mapping']['transfer_gates']
        assert len(mapping['nodes']) == 8
        assert all(node.startswith('xdut.rcx_int_') for node in mapping['nodes'].values())
        assert post._read(style['settings']['path'])['transfer_gate_nodes'] == mapping['nodes']
    assert post._validate(manifest)['kind'] == 'incremental_capture_pvt'


def test_altered_transfer_map_refuses_before_any_spice(source, tmp_path, monkeypatch):
    manifest = prepared(source, tmp_path / 'POST')
    style = manifest['styles'][0]
    settings = Path(style['settings']['path']); common = post._read(settings)
    first = next(iter(common['transfer_gate_nodes']))
    common['transfer_gate_nodes'][first] = 'xdut.unrelated_native_node'
    capture.write_json(settings, common)
    style['settings'] = post._view(settings)  # Resealing one view cannot replace the reconstructed mapping.
    monkeypatch.setattr(pvt, 'run', lambda *a, **k: pytest.fail('wrong map must refuse before SPICE'))
    monkeypatch.setattr(post, '_run_probes', lambda *a, **k: pytest.fail('wrong map must refuse before probes'))
    result = post.run(manifest, 'fixture-container', 'fixture-image')
    assert result['status'] == 'NOT_MEASURED'
    assert 'POST inputs differ' in result['detail']


def test_missing_pre_score_never_launches_post_native_or_credits_input_readiness(source, tmp_path, monkeypatch):
    manifest = prepared(source, tmp_path / 'POST', samples=2)
    monkeypatch.setattr(pvt, 'run', lambda *a, **k: pytest.fail('PRE incomplete: no POST native run'))
    monkeypatch.setattr(post, '_run_probes', lambda *a, **k: pytest.fail('PRE incomplete: no POST native probes'))
    for operation in ('resim', 'statistics'):
        result = post.run(manifest, 'fixture-container', 'fixture-image', 2, 2, operation, 2)
        assert result['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('mutation', ['project', 'body', 'style_omission', 'reset', 'sample_count'])
def test_wrong_source_or_incomplete_style_hardware_cannot_pass(source, tmp_path, mutation):
    manifest = prepared(source, tmp_path / 'POST', samples=2)
    if mutation == 'project':
        manifest['project'] = str(tmp_path / 'another-project')
    elif mutation == 'body':
        path = Path(manifest['styles'][0]['extracted_body']['path'])
        path.write_text(path.read_text().replace('w=2u', 'w=3u'))
    elif mutation == 'style_omission':
        manifest['styles'].pop(); manifest['statistics']['styles'].pop()
    elif mutation == 'reset':
        item = manifest['styles'][0]; path = Path(item['settings']['path'])
        common = post._read(path); common['reset_node'] = 'xdut.reset_b'
        path.write_text(json.dumps(common)); item['settings'] = post._view(path)
    if mutation == 'sample_count':
        result = post.collect(manifest, 'statistics', 3)
        assert 'sample count' in result['detail']
    else:
        result = post.collect(manifest, 'resim')
    assert result['status'] == 'NOT_MEASURED'


def test_absent_extracted_reset_refuses_instead_of_fabricating_a_probe(source, tmp_path):
    record = post._read(source['extraction'])
    for row in record['metrics']['corners']:
        path = Path(row['extracted_netlist']); path.write_text(path.read_text().replace('reset_b', 'removed_reset'))
        row['sha256'] = capture.bound.sha(path)
    source['extraction'].write_text(json.dumps(record))
    with pytest.raises(ValueError, match='reset node is absent'):
        prepared(source, tmp_path / 'POST')


def test_nominal_only_post_styles_cannot_replace_nine_corner_pvt(source, tmp_path):
    manifest = prepared(source, tmp_path / 'POST')
    nominal(source)
    for style in manifest['styles']:
        plan = post._read(style['pvt_manifest']['path'])
        context = next(row for row in plan['contexts'] if row['process_label'] == 'tt' and row['temperature_c'] == 27)
        _native_fixture_series(context)
    result = post.collect(manifest, 'resim')
    assert result['status'] == 'NOT_MEASURED'
    assert all(row['result']['metrics']['corners_executed'] == 1 for row in result['metrics']['corners'])


def populate_statistics(source, manifest):
    nominal(source)
    for group in manifest['statistics']['styles']:
        fake = {'image': manifest['image'], 'fingerprint_bindings': group['fingerprint_bindings']}
        assert all('.xdut.xrcx.' in field['expression'] for field in group['fingerprint_bindings'])
        for probe in [group['disabled_control']['probe']] + [probe for chip in group['chips'] for probe in chip['probes']]:
            _write_probe(fake, probe)
        for chip in group['chips']:
            _native_fixture_series({**chip, 'temperature_c': 27})
    return manifest


def test_statistics_uses_real_capture_replay_and_one_hardware_seed_across_styles(source, tmp_path):
    manifest = populate_statistics(source, prepared(source, tmp_path / 'POST', samples=2))
    result = post.collect(manifest, 'statistics', 2)
    assert result['status'] == 'PASS', result
    assert result['metrics']['mc_runs'] == 2 and result['metrics']['mc_yield_pct'] == 100
    assert result['metrics']['native_activation_proven'] is True
    for group in result['metrics']['corners']:
        assert all(chip['measurements']['enob'] < 99 for chip in group['chips'])


def test_same_seed_but_different_realized_hardware_between_styles_is_unmeasured(source, tmp_path):
    manifest = populate_statistics(source, prepared(source, tmp_path / 'POST', samples=2))
    group = manifest['statistics']['styles'][1]
    fake = {'image': manifest['image'], 'fingerprint_bindings': group['fingerprint_bindings']}
    fields = {field['key']: 1.01 for field in group['fingerprint_bindings']}
    fields[next(iter(fields))] = 1.011
    for probe in group['chips'][0]['probes']:
        _write_probe(fake, probe, values=fields)
    result = post.collect(manifest, 'statistics', 2)
    assert result['status'] == 'NOT_MEASURED'
    assert any('differs between extraction styles' in gap for gap in result['metrics']['gaps'])


def test_complete_post_pvt_uses_every_native_corner_and_raw_pre_comparison(source, tmp_path):
    record = post._read(source['extraction']); record['metrics']['corners'] = record['metrics']['corners'][:1]
    source['extraction'].write_text(json.dumps(record))
    source['technology'].write_text('extract\nstyle ngspice variants ()\nend\n')
    manifest = prepared(source, tmp_path / 'POST')
    nominal(source)
    pre = post._read(source['pre_plan'])
    for context in pre['contexts']:
        _native_fixture_series(context)
    plan = post._read(manifest['styles'][0]['pvt_manifest']['path'])
    for context in plan['contexts']:
        _native_fixture_series(context)
    result = post.collect(manifest, 'resim')
    assert result['status'] == 'PASS', result
    assert result['metrics']['corners'][0]['result']['metrics']['corners_executed'] == 9
    assert len(result['metrics']['comparisons']) == 27
    assert {row['metric'] for row in result['metrics']['comparisons']} == {'enob', 'vref', 'sndr_db'}
    assert all(row['delta_pct'] == 0 for row in result['metrics']['comparisons'])


def test_selected_native_binary_reaches_actual_point_callback_and_cannot_be_relabelled(source, tmp_path, monkeypatch):
    from analog_native_flow import NativeCommands
    binary = tmp_path / 'selected-native'
    binary.write_bytes(b'owned executable software control'); binary.chmod(0o755)
    manifest = prepared(source, tmp_path / 'POST', native_binary=binary)
    style = manifest['styles'][0]; common = post._read(style['settings']['path'])
    target = tmp_path / 'native-point'; target.mkdir()
    settings = target / 'settings.json'; capture.write_json(settings, capture.phase_settings(common, 0))
    seen = []
    def native(_self, program, argv, **kwargs):
        seen.append((program, argv))
        assert program == '@env' and str(binary) in argv and 'OMP_WAIT_POLICY=PASSIVE' in argv
        raw = _timed_dump(target / 'conversion.dat', common,
                          post._read(style['native_inputs']['topology']['path']))
        raw.write_text('\n'.join(' '.join([f'{float(line.split()[0]) * 1e-6:.17g}', *line.split()[1:]])
            if line and line[0].isdigit() else line for line in raw.read_text().splitlines()))
        log = target / 'native.log'; log.write_text('Doing analysis at TEMP = 27\n')
        return {'returncode': 0, 'argv': ['env', *argv], 'log': str(log), 'log_sha256': capture.bound.sha(log)}
    monkeypatch.setattr(NativeCommands, '__call__', native)
    code = post._point_launch([style['project'], '--block', 'converter', '--settings', str(settings),
        '--out', str(target), '--container', 'fixture-container', '--image', 'fixture-image'])
    assert code == 0 and len(seen) == 1
    row = post._read(target / 'result.json')
    assert row['native_inputs']['native_binary'] == post._view(binary)
    assert capture.validate_point(row)[0]
    post._binary_check(row, post._view(binary))
    row['executions'][0]['argv'] = ['ngspice', '-b', row['native_inputs']['deck']['path']]
    with pytest.raises(ValueError, match='selected binary'):
        post._binary_check(row, post._view(binary))


def test_invalid_api_operation_or_delta_never_launches_even_with_measured_pre(source, tmp_path, monkeypatch):
    manifest = prepared(source, tmp_path / 'POST')
    nominal(source)
    monkeypatch.setattr(pvt, 'run', lambda *a, **kw: pytest.fail('invalid API input cannot launch native'))
    result = post.run(manifest, 'fixture-container', 'fixture-image', operation='unknown')
    assert result['status'] == 'NOT_MEASURED' and 'operation' in result['detail']
    manifest['max_delta_pct'] = float('nan')
    result = post.run(manifest, 'fixture-container', 'fixture-image')
    assert result['status'] == 'NOT_MEASURED' and 'max_delta_pct' in result['detail']


@pytest.fixture
def distributed_reset(tmp_path):
    from _analog_producer_common import content_digest
    root = tmp_path / 'actual-source'; root.mkdir()
    model = root / 'devices.lib'
    model.write_text('.subckt fixture_fet d g s b\n.ends fixture_fet\n')
    net = root / 'converter.sp'
    net.write_text('.include "devices.lib"\n.subckt converter ain dout vdd vss\n'
        'xone dout reset_b ain vss fixture_fet w=2u l=1u\n'
        'xtwo ain reset_b dout vss fixture_fet w=2u l=1u\n.ends converter\n')
    tb = root / 'tb_converter.sp'
    tb.write_text('* real source context\n.include "converter.sp"\n'
        'xdut ain dout vdd 0 converter\n.save v(xdut.reset_b)\n.end\n')
    mag = root / 'layout.mag'; mag.write_text('magic\nuse fixture_fet_A d0\nuse fixture_fet_B d1\n')
    capture.write_json(root / 'layout_provenance.json', {'producer':'analog_a5_layout_emit', 'result':'OK',
        'netlist_content_sha256':content_digest(net.read_text()), 'layout_mag':str(mag)})
    step = tmp_path / 'native-extraction'; (step / 'extraction_full').mkdir(parents=True)
    ext = step / 'extraction_full/converter.ext'
    ext.write_text('node "d0.G" 0 0 0\nequiv "d0.G" "d1.G"\n')
    raw = ('.subckt converter ain dout vdd vss\n'
        'xone dout d0.G.t0 ain vss fixture_fet w=2u l=1u\n'
        'xtwo ain d0.G.t1 dout vss fixture_fet w=2u l=1u\n'
        'r_gate0 d0.G d0.G.t0 15\nr_gate1 d0.G d0.G.t1 207.7\n.ends converter\n')
    return net, tb, raw, {'step_dir':str(step), 'extracted_netlist':str(step / 'raw.spice')}, ext, mag


def test_actual_source_labeled_reset_observation_preserves_distributed_resistors(distributed_reset, tmp_path):
    net, tb, raw, corner, ext, mag = distributed_reset
    wrapper, body, mapping = post._wrapped_body('converter', net, raw, tmp_path)
    proof = {}
    text, reset, dropped = post._post_template('converter', net, tb, tmp_path / 'post.sp', raw, mapping,
        'xdut.reset_b', corner=corner, observation=proof)
    assert reset == 'xdut.xrcx.d0.G'
    assert proof['kind'] == 'source_labeled_conductor' and proof['source_device'] == 'one'
    assert proof['native_node'] == 'd0.G' and proof['logical_reset'] == 'xdut.reset_b'
    assert proof['supporting_inputs']['native_ext'] == post._view(ext)
    assert 'r_gate0 d0.G d0.G.t0 15' in body and 'r_gate1 d0.G d0.G.t1 207.7' in body
    assert 'not declared equipotential' in proof['scope']


@pytest.mark.parametrize('mutation', ['wrong_source_net', 'wrong_layout_model', 'missing_equiv', 'resistor_only_alias'])
def test_reset_conductor_mapping_requires_actual_source_layout_and_ext_identity(distributed_reset, mutation):
    net, tb, raw, corner, ext, mag = distributed_reset
    if mutation == 'wrong_source_net':
        net.write_text(net.read_text().replace('reset_b', 'unrelated'))
    elif mutation == 'wrong_layout_model':
        mag.write_text(mag.read_text().replace('fixture_fet_A', 'other_model_A'))
    elif mutation == 'missing_equiv':
        ext.write_text('node "d0.G" 0 0 0\nnode "d1.G" 0 0 0\n')
    else:
        ext.write_text('node "d0.G" 0 0 0\nnode "d1.G" 0 0 0\nresist "d0.G" "d1.G" 15\n')
    with pytest.raises(ValueError):
        post._source_reset_observation('converter', net, tb, raw, corner, 'xdut.reset_b', None)


def test_technology_override_cannot_omit_actual_a13_style_inventory(source, tmp_path):
    weaker = tmp_path / 'weaker-tech.flat'
    weaker.write_text('extract\nstyle ngspice variants ()\nend\n')
    with pytest.raises(ValueError, match='actual A13 technology'):
        prepared(source, tmp_path / 'POST', technology=weaker)


def test_known_native_failure_keeps_precedence_over_incomplete_runtime_receipt(source, tmp_path, monkeypatch):
    manifest = prepared(source, tmp_path / 'POST', samples=2)
    monkeypatch.setattr(pvt, 'collect', lambda plan: {'status':'FAIL', 'detail':'actual native residual failure',
        'native_inputs':{}, 'outputs':[], 'metrics':{'contexts':[]}})
    monkeypatch.setattr(post, '_pvt_binary_gaps', lambda plan: [{'detail':'selected binary receipt missing'}])
    result = post._resim_collect(manifest, post._read(source['pre_plan']))
    assert result['status'] == 'FAIL'
    assert all(row['status'] == 'FAIL' for row in result['metrics']['corners'])
    group = manifest['statistics']['styles'][0]
    probe = group['chips'][0]['probes'][0]
    _write_probe({'image':manifest['image'], 'fingerprint_bindings':group['fingerprint_bindings']}, probe, code=1)
    state, _, _ = post._probe_state(probe, group['fingerprint_bindings'], manifest['image'],
        {'path':str(tmp_path / 'unbound-selected-binary'), 'sha256':'0'*64})
    assert state == 'FAIL'


@pytest.fixture
def physical_gate(tmp_path):
    """Source/A5/native-ext identity with a real gate beyond positive R."""
    from _analog_producer_common import content_digest
    root = tmp_path / 'gate-source'; root.mkdir()
    model = root / 'device.lib'
    model.write_text('.subckt fixture_fet d g s b\n.ends fixture_fet\n')
    net = root / 'converter.sp'
    net.write_text('.include "device.lib"\n.subckt converter ain dout vdd vss\n'
        'xsw dout control ain vss fixture_fet w=2u l=1u\n.ends converter\n')
    tb = root / 'tb_converter.sp'
    tb.write_text('.include "converter.sp"\nxdut ain dout vdd 0 converter\n.end\n')
    mag = root / 'layout.mag'; mag.write_text('magic\nuse fixture_fet_UNIT d0\n')
    provenance = root / 'layout_provenance.json'
    capture.write_json(provenance, {'producer': 'analog_a5_layout_emit', 'result': 'OK',
        'netlist_content_sha256': content_digest(net.read_text()), 'layout_mag': str(mag)})
    step = tmp_path / 'gate-extraction'; (step / 'extraction_full').mkdir(parents=True)
    ext = step / 'extraction_full/converter.ext'
    ext.write_text('node "d0.D" 0 0 0\nequiv "d0.D" "dout"\n'
        'node "d0.G" 0 0 0\nequiv "d0.G" "gate_bus"\n'
        'node "d0.S" 0 0 0\nequiv "d0.S" "ain"\n'
        'node "d0.B" 0 0 0\nequiv "d0.B" "vss"\n')
    raw = ('.subckt converter ain dout vdd vss\n'
        'xnative drain_terminal gate_terminal source_terminal bulk_terminal fixture_fet w=2u l=1u\n'
        'r_d dout drain_terminal 12\nr_g gate_bus gate_terminal 207.7\n'
        'r_s ain source_terminal 21\nr_b vss bulk_terminal 4\n.ends converter\n')
    return {'net': net, 'tb': tb, 'raw': raw, 'model': model, 'mag': mag, 'ext': ext,
        'provenance': provenance, 'corner': {'step_dir': str(step), 'extracted_netlist': str(step / 'raw.spice')},
        'device': {'name': 'sw', 'role': 'nmos', 'nets': ['dout', 'control', 'ain', 'vss']}}


def _physical_gate(case, **overrides):
    data = {**case, **overrides}
    return post._physical_transfer_gate('converter', data['net'], data['tb'], data['raw'],
        data['corner'], data['device'], data.get('logical', 'xdut.control'))


def test_native_gate_is_selected_beyond_positive_resistor_without_voltage_collapse(physical_gate):
    case = physical_gate
    original = case['raw']
    node, proof = _physical_gate(case)
    assert node == 'xdut.gate_terminal' and node != 'xdut.gate_bus'
    assert proof['kind'] == 'source_physical_device_terminal'
    assert proof['source_device'] == 'sw' and proof['layout_instance'] == 'd0'
    assert proof['native_instance'] == 'xnative'
    assert post._current(proof['supporting_inputs'])
    assert case['raw'] == original and 'r_g gate_bus gate_terminal 207.7' in original


def test_retained_instance_also_observes_actual_gate_beyond_resistor(physical_gate):
    raw = ('.subckt converter ain dout vdd vss\n'
        'xsw dout gate_terminal ain vss fixture_fet w=2u l=1u\n'
        'r_gate control gate_terminal 207.7\n.ends converter\n')
    node, proof = _physical_gate(physical_gate, raw=raw, corner=None)
    assert node == 'xdut.gate_terminal'
    assert proof['kind'] == 'retained_native_device_terminal'


def test_wrapper_parameters_do_not_become_extra_mos_terminals(physical_gate):
    physical_gate['model'].write_text('.subckt fixture_fet d g s b params: w=2u l=1u\n.ends fixture_fet\n')
    node, _proof = _physical_gate(physical_gate)
    assert node == 'xdut.gate_terminal'


def test_mixed_case_spice_identity_preserves_the_actual_gate_spelling(physical_gate):
    from _analog_producer_common import content_digest
    case = physical_gate
    case['net'].write_text(case['net'].read_text().replace(
        'xsw dout control ain vss fixture_fet', 'XSW DOUT CONTROL AIN VSS FIXTURE_FET'))
    record = post._read(case['provenance'])
    record['netlist_content_sha256'] = content_digest(case['net'].read_text())
    capture.write_json(case['provenance'], record)
    case['raw'] = case['raw'].replace('gate_terminal', 'Gate_TERMINAL').replace('fixture_fet w=', 'FIXTURE_FET w=')
    node, _proof = _physical_gate(case)
    assert node == 'xdut.Gate_TERMINAL'


@pytest.mark.parametrize('mutation', ['source', 'layout', 'model', 'missing_ext', 'wrong_ext',
                                     'ambiguous_ext', 'foreign_model', 'ambiguous_mos', 'foreign_instance'])
def test_physical_gate_requires_unambiguous_source_layout_model_and_native_ext(physical_gate, mutation):
    case = physical_gate
    if mutation == 'source':
        case['net'].write_text(case['net'].read_text().replace('control', 'foreign_control'))
        case['device'] = {**case['device'], 'nets': ['dout', 'foreign_control', 'ain', 'vss']}
    elif mutation == 'layout':
        case['mag'].write_text('magic\nuse unrelated_fet_UNIT d0\n')
    elif mutation == 'model':
        case['model'].write_text('.subckt fixture_fet d s g b\n.ends fixture_fet\n')
    elif mutation == 'missing_ext':
        case['ext'].unlink()
    elif mutation == 'wrong_ext':
        case['ext'].write_text(case['ext'].read_text().replace('"gate_bus"', '"dout"'))
    elif mutation == 'ambiguous_ext':
        case['ext'].write_text(case['ext'].read_text() + 'equiv "d0.G" "unjoined_anchor"\n')
        case['raw'] = case['raw'].replace('.ends converter', 'r_other unjoined_anchor unrelated 2\n.ends converter')
    elif mutation == 'foreign_model':
        case['raw'] = case['raw'].replace('fixture_fet w=', 'unrelated_fet w=')
    elif mutation == 'ambiguous_mos':
        case['raw'] = case['raw'].replace('.ends converter',
            'xsecond drain_terminal gate_terminal source_terminal bulk_terminal fixture_fet w=2u l=1u\n.ends converter')
    elif mutation == 'foreign_instance':
        case['logical'] = 'unrelated_dut.control'
    with pytest.raises(ValueError):
        _physical_gate(case)


def test_retained_instance_cannot_bypass_actual_wrapper_terminal_order(tmp_path):
    # Executed review counterexample against7edb038b: the old direct branch
    # returnedxdut.source even thoughG was the third actual wrapper terminal.
    net = tmp_path / 'converter.sp'; tb = tmp_path / 'tb.sp'
    net.write_text('.subckt odd_fet D S G B\nMcore D G S B native_n w=1u l=1u\n.ends odd_fet\n'
        '.subckt converter drain source actual_gate bulk\n'
        'xsw drain source actual_gate bulk odd_fet w=1u l=1u\n.ends converter\n')
    tb.write_text('xdut drain source actual_gate bulk converter\n.end\n')
    raw = ('.subckt converter drain source actual_gate bulk\n'
        'xsw drain source actual_gate bulk odd_fet w=1u l=1u\n.ends converter\n')
    with pytest.raises(ValueError, match='d/g/s/b terminal order'):
        post._physical_transfer_gate('converter', net, tb, raw, None,
            {'name': 'sw', 'role': 'nmos', 'nets': ['drain', 'source', 'actual_gate', 'bulk']}, 'xdut.actual_gate')


@pytest.mark.parametrize('header', ['d g s b extra', 'd g s b\n.ends fixture_fet\n.subckt fixture_fet d s g b'])
def test_extra_or_conflicting_wrapper_ports_refuse_even_on_retained_route(physical_gate, header):
    physical_gate['model'].write_text('.subckt fixture_fet ' + header + '\n.ends fixture_fet\n')
    raw = ('.subckt converter ain dout vdd vss\nxsw dout control ain vss fixture_fet w=2u l=1u\n.ends converter\n')
    with pytest.raises(ValueError, match='d/g/s/b terminal order'):
        _physical_gate(physical_gate, raw=raw, corner=None)
