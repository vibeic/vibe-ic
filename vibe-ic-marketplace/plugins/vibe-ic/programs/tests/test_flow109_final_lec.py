"""D44 actual LibreLane EQY controls on an independent tiny mapped design.

Qualification references here are developer contract controls, not PDK/signoff
qualification. No existing IC input, native run, pre-layout PASS or GLS is used.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

import flow109
import flow109_admission as admission
import flow109_final_lec as lec
import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return lec._record(project, path)


def _case(project, *, bad_logic=False, blackbox=False):
    from librelane.config import Config
    from librelane.steps.yosys import EQY
    pdk = {'PDK': 'gf180mcuD', 'STD_CELL_LIBRARY': 'gf180mcu_fd_sc_mcu7t5v0', 'pdk_root': '/foss/pdks'}
    config, _ = Config.load({'DESIGN_NAME': 'proof_alpha', 'PDK': pdk['PDK'],
        'STD_CELL_LIBRARY': pdk['STD_CELL_LIBRARY'], 'VERILOG_FILES': []},
        EQY.get_all_config_variables(), design_dir=str(project), pdk_root=pdk['pdk_root'])
    import fnmatch
    libraries = [p for pattern, group in config['CELL_LIBS'].items()
                 if fnmatch.fnmatch(config['DEFAULT_CORNER'], pattern) for p in group]
    assert len(libraries) == 1
    library = Path(libraries[0])
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                          'fixtures', 'flow109_final_lec', 'rtl.v')
    rtl = _put(project, 'inputs/reference.v', source.read_text())
    text = source.read_text().replace('(a & b) ^ c', '(a | b) ^ c') if bad_logic else source.read_text()
    _put(project, 'inputs/revised.v', text)
    script = project / 'map.ys'
    script.write_text('read_verilog inputs/revised.v\nsynth -top proof_alpha\n'
                      f'abc -liberty {library}\nclean\nwrite_verilog -noattr inputs/adopted.v\n')
    mapped = subprocess.run(['yosys', '-Q', '-T', '-s', str(script)], cwd=project,
                            capture_output=True, text=True)
    assert mapped.returncode == 0, mapped.stdout + mapped.stderr
    if blackbox:
        (project / 'inputs/adopted.v').write_text('''
(* blackbox *) module unknown_gate(input a, output y); endmodule
module proof_alpha(input a,b,c, output y,z);
unknown_gate u(.a(a),.y(y)); assign z=~c;
endmodule
''')
    netlist = lec._record(project, project / 'inputs/adopted.v')
    liberty = lec._record(project, library)
    manifest = {'schema': lec.SCHEMA, 'top': 'proof_alpha', 'rtl': [rtl],
        'adopted_netlist': netlist, 'liberty': liberty, 'librelane': pdk, 'transformations': [],
        'consumer_netlists': {r: copy.deepcopy(netlist) for r in ('sta', 'lvs_reference', 'release')}}
    _put(project, lec.INPUT, manifest)
    operation = _put(project, 'input/flow109/D44-operation.json',
                      {'schema': lec.SCHEMA, 'operation': 'Yosys.EQY', 'transformations': []})
    pdk_record = _put(project, 'input/flow109/D44-pdk.json', {'librelane': pdk, 'liberty': liberty})
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(features)
    references = [_put(project, 'input/qualification-control.json',
                       {'scope': 'developer contract control; not production qualification'})]
    uses, records = [], []
    for use in flow109.resolve_step(plan, 'D44')['tool_uses']:
        binary = Path(shutil.which(use['executable_name'])).resolve()
        executable = lec._record(project, binary)
        identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'],
            'version': 'native developer control (executable hash bound)', 'build_sha256': executable['sha256'],
            'executable': executable, 'config': operation, 'pdk': pdk_record, 'deck': liberty,
            'corner': config['DEFAULT_CORNER'],
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                          'operation_sources': lec.operation_sources()}}
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                  'reference_evidence': references}
        records.append(record)
        uses.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
    _put(project, 'qualifications.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records})
    selection = {'features': features, 'runtime_tool_uses': uses, 'qualification_registry': 'qualifications.json'}
    _put(project, 'manifest.json', selection)
    context = flow109.execution_context(plan, 'D44', 'D44', runtime_tool_uses=uses,
                                        qualification_registry='qualifications.json')
    return context


def test_registry_registers_only_the_two_D44_runtime_bindings():
    registry = flow109.load_registry()
    features = next(p['features'] for p in registry['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    row = flow109.resolve_step(flow109.resolve_plan(features), 'D44')
    assert row['profile']['dispatch']['flow109_metrics_status'] == 'IMPLEMENTED_D44_RUNTIME'
    assert row['metric_acceptance_status'] == 'IMPLEMENTED_D44_RUNTIME'
    assert {item['id']: item['status'] for item in row['obligations']} == {
        'final_lec.final_lec_unproved': 'IMPLEMENTED_D44_RUNTIME_BINDING',
        'final_lec.sta_lvs_release_netlist_mapping': 'IMPLEMENTED_D44_RUNTIME_BINDING'}
    assert set(metrics.D44_BINDINGS) == {
        'final_lec.final_lec_unproved',
        'final_lec.sta_lvs_release_netlist_mapping'}


def test_actual_general_entry_proves_final_mapped_netlist_and_publishes_common_source_chain(tmp_path):
    _case(tmp_path)
    legacy = tmp_path / 'reports/lec.json'
    legacy.parent.mkdir(exist_ok=True)
    legacy.write_text('{"verdict":"PASS","scope":"prelayout-only"}')
    old = legacy.read_bytes()
    main = lec.HERE / 'vibe_ic_one_shot_runner.py'
    result = subprocess.run([sys.executable, str(main), str(tmp_path), '--flow', '109',
        '--flow109-manifest', str(tmp_path / 'manifest.json'), '--entry-step', 'D44', '--exit-step', 'D44',
        '--route', 'ic', '--no-dashboard'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads((tmp_path / 'reports/flow109/components/D44.json').read_text())
    assert record['component_status'] == 'PASS'
    assert record['flow109_acceptance'] == record['baseline_adoption'] == 'NOT_MEASURED'
    assert record['proof']['verdict'] == 'PASS'
    assert record['proof']['compared_points'] > 0
    assert set(record['proof']['declared_partitions']) == set(record['proof']['partitions'])
    metrics = record['metric_bindings']
    assert metrics['status'] == 'PASS'
    assert metrics['metrics']['final_lec_unproved']['value'] == 0
    mapping = metrics['metrics']['sta_lvs_release_netlist_mapping']
    assert mapping['status'] == 'PASS'
    assert mapping['consumer_adoption'] == 'NOT_MEASURED'
    acceptance = record['metric_acceptance']
    assert record['metric_acceptance_status'] == acceptance['status'] == 'PASS'
    assert acceptance['delivery_blocked'] is False
    assert {item['id']: item['status'] for item in acceptance['obligations']} == {
        'final_lec.final_lec_unproved': 'PASS',
        'final_lec.sta_lvs_release_netlist_mapping': 'PASS'}
    assert record['flow109_acceptance'] == 'NOT_MEASURED'
    baseline = json.loads((tmp_path / lec.BASELINE).read_text())
    assert baseline['consumer_adoption'] == 'NOT_MEASURED'
    assert all(r['sha256'] == baseline['adopted_netlist']['sha256']
               for r in baseline['consumer_netlists'].values())
    assert baseline['transformations'] == []
    assert legacy.read_bytes() == old


@pytest.mark.parametrize('damage, expected', [('logic', 'FAIL'), ('blackbox', 'NOT_MEASURED')])
def test_native_logic_change_or_functionless_cell_never_passes(tmp_path, damage, expected):
    context = _case(tmp_path, bad_logic=damage == 'logic', blackbox=damage == 'blackbox')
    record = lec.execute(tmp_path, context)
    assert record['component_status'] == expected, record
    assert not (tmp_path / lec.BASELINE).exists()
    if damage == 'logic':
        assert record['proof']['non_equivalent_points']
        assert record['metric_bindings']['metrics']['final_lec_unproved']['status'] == 'FAIL'
        assert record['metric_bindings']['metrics']['final_lec_unproved']['value'] > 0
        assert record['metric_bindings']['metrics']['sta_lvs_release_netlist_mapping']['status'] == 'NOT_MEASURED'
        assert record['metric_acceptance_status'] == 'FAIL'
        assert record['metric_acceptance']['delivery_blocked'] is True
    else:
        assert record['reason'] == 'D44_FUNCTIONAL_MODEL_UNSUPPORTED'
        assert record['metric_bindings']['status'] == 'NOT_MEASURED'
        assert record['metric_acceptance_status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['consumer', 'transformation', 'source', 'unsupported'])
def test_unqualified_or_unbound_subject_stops_before_model_or_proof_launch(tmp_path, monkeypatch, damage):
    context = _case(tmp_path)
    if damage in ('consumer', 'transformation'):
        path = tmp_path / lec.INPUT
        manifest = json.loads(path.read_text())
        if damage == 'consumer':
            manifest['consumer_netlists']['release'] = _put(tmp_path, 'inputs/another.v', 'module unrelated; endmodule')
        else:
            manifest['transformations'] = [{'drop_cells': ['any_cell']}]
        path.write_text(json.dumps(manifest))
    elif damage == 'source':
        monkeypatch.setattr(lec, 'operation_sources', lambda: {'changed': 'source'})
    else:
        registry = json.loads((tmp_path / 'qualifications.json').read_text())
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    calls = []
    monkeypatch.setattr(lec, '_model_census', lambda *a: calls.append('native'))
    record = lec.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED', record
    assert record['native_started'] is False and calls == []
    assert not (tmp_path / lec.BASELINE).exists()


def test_checked_in_native_eqy_sample_cannot_lose_a_required_partition(tmp_path):
    context = _case(tmp_path)
    sample = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'calibration',
                          'eqy_defined_init_negative.tar')
    scratch = tmp_path / 'native/scratch'
    scratch.mkdir(parents=True)
    with tarfile.open(sample) as archive:
        archive.extractall(scratch, filter='data')
    output = tmp_path / 'proof.json'
    complete = lec.consume_eqy(tmp_path / 'native', output)
    assert complete['verdict'] == 'PASS', complete
    partition = complete['declared_partitions'][0]
    shutil.rmtree(scratch / 'strategies' / partition)
    incomplete = lec.consume_eqy(tmp_path / 'native', output)
    assert incomplete['verdict'] == 'NOT_MEASURED'
    assert incomplete['explanation'] == 'D44_PARTITION_COVERAGE_INCOMPLETE'
    binding = lec._proof_binding(incomplete)
    assert binding == {'status': 'NOT_MEASURED', 'reason': 'D44_PARTITION_COVERAGE_INCOMPLETE'}
    forged = copy.deepcopy(complete)
    forged['partitions'].pop(partition)
    forged.update(verdict='PASS', compared_points=len(forged['partitions']),
                  proven_points=len(forged['partitions']), non_equivalent_points=[],
                  unproven_points=[], xbits_partitions=[])
    assert lec._proof_binding(forged) == {
        'status': 'NOT_MEASURED', 'reason': 'D44_PARTITION_COVERAGE_INCOMPLETE'}
    component = {'component_status': 'NOT_MEASURED', 'proof': incomplete,
                 'flow109_acceptance': 'NOT_MEASURED'}
    accepted = metrics.accept_d44(tmp_path, context, component)
    assert accepted['status'] == 'NOT_MEASURED'
    assert accepted['delivery_blocked'] is True
    assert {item['id']: item['status'] for item in accepted['obligations']} == {
        'final_lec.final_lec_unproved': 'NOT_MEASURED',
        'final_lec.sta_lvs_release_netlist_mapping': 'NOT_MEASURED'}


@pytest.mark.parametrize('damage', ['swapped_baseline', 'stale_proof', 'stale_netlist'])
def test_metric_binding_refuses_swapped_or_stale_common_source_chain(tmp_path, damage):
    context = _case(tmp_path)
    record = lec.execute(tmp_path, context)
    assert record['metric_bindings']['status'] == 'PASS'
    baseline_path = tmp_path / lec.BASELINE
    baseline = json.loads(baseline_path.read_text())
    if damage == 'swapped_baseline':
        other = _put(tmp_path, 'inputs/swapped.v', 'module proof_alpha(input a,b,c, output y,z); assign y=a; assign z=b; endmodule')
        baseline['adopted_netlist'] = other
        baseline_path.write_text(json.dumps(baseline))
    elif damage == 'stale_proof':
        proof = tmp_path / baseline['proof']['path']
        proof.write_text(proof.read_text() + '\n')
    else:
        netlist = tmp_path / baseline['adopted_netlist']['path']
        netlist.write_text(netlist.read_text() + '\n')
    rebound = lec.bind_metrics(tmp_path, context, record)
    assert rebound['status'] == 'FAIL'
    assert rebound['metrics']['final_lec_unproved']['status'] == 'PASS'
    assert rebound['metrics']['sta_lvs_release_netlist_mapping']['status'] == 'FAIL'
    accepted = metrics.accept_d44(tmp_path, context, record)
    assert accepted['status'] == 'FAIL'
    assert accepted['delivery_blocked'] is True
    # Once the adopted netlist changes, the retained proof cannot receive
    # current-input credit.  The measured mapping failure must still win.
    proof_status = 'NOT_MEASURED' if damage == 'stale_netlist' else 'PASS'
    assert {item['id']: item['status'] for item in accepted['obligations']} == {
        'final_lec.final_lec_unproved': proof_status,
        'final_lec.sta_lvs_release_netlist_mapping': 'FAIL'}
    if damage == 'stale_netlist':
        proof_metric = next(item for item in accepted['obligations']
                            if item['id'] == 'final_lec.final_lec_unproved')
        assert proof_metric['measurement']['reason'] == 'METRIC_EXECUTION_EVIDENCE_STALE'


def test_actual_model_launch_rechecks_qualification_after_preparation(tmp_path, monkeypatch):
    context = _case(tmp_path)
    prepare = lec.prepare
    def invalidate_before_launch(project, selection):
        prepared = prepare(project, selection)
        path = project / 'qualifications.json'
        registry = json.loads(path.read_text())
        registry['uses'][0]['status'] = 'UNSUPPORTED'
        path.write_text(json.dumps(registry))
        return prepared
    monkeypatch.setattr(lec, 'prepare', invalidate_before_launch)
    record = lec.execute(tmp_path, context)
    assert record['component_status'] == 'NOT_MEASURED'
    assert record['reason'] == 'QUALIFICATION_UNSUPPORTED'
    assert record['native_started'] is False
    assert not list(tmp_path.rglob('gold.model.log'))
    assert not list(tmp_path.rglob('*.eqy'))


def _retained_case(project, monkeypatch):
    gold = _put(project, 'evidence/gold.v', 'module chip_top(input a, output p); assign p=a; endmodule\n')
    gate = _put(project, 'evidence/gate.v', 'module chip_top(input a, output p); assign p=a; endmodule\n')
    rtl = _put(project, 'inputs/rtl.v', 'module source(input a, output p); assign p=a; endmodule\n')
    netlist = _put(project, 'inputs/adopted.v', 'module source(input a, output p); assign p=a; endmodule\n')
    listing = _put(project, 'evidence/scratch/partition.list', 'partition chip_top.p: p\n')
    pdr = _put(project, 'evidence/scratch/strategies/chip_top.p/pdr/status', 'PASS\n')
    sat = _put(project, 'evidence/scratch/strategies/chip_top.p/sat/status', 'UNKNOWN\n')
    proof_value = {'verdict': 'PASS', 'explanation': 'all 1 partition(s) proven',
        'compared_points': 1, 'proven_points': 1, 'non_equivalent_points': [],
        'unproven_points': [], 'xbits_partitions': [], 'declared_partitions': ['chip_top.p'],
        'partitions': {'chip_top.p': {'pdr': 'PASS', 'sat': 'UNKNOWN'}},
        'evidence_sha256': {'scratch/partition.list': listing['sha256'],
            'scratch/strategies/chip_top.p/pdr/status': pdr['sha256'],
            'scratch/strategies/chip_top.p/sat/status': sat['sha256']}}
    proof = _put(project, 'evidence/proof.json', proof_value)
    prep_value = {'schema': lec.physical.SCHEMA, 'producer': 'flow109_final_lec_physical',
        'status': 'PREPARED_NOT_EQUIVALENCE_PROVEN', 'kind': lec.physical.KIND,
        'top': 'chip_top', 'inputs': {}, 'raw_adopted_netlist': netlist,
        'powered_mode': {'VDD': 1, 'VSS': 0},
        'projected_supply_ports': {'gold': ['VDD', 'VSS'], 'gate': []},
        'functional_interfaces': {'gold': {'a': ['input', 1], 'p': ['output', 1]},
                                  'gate': {'a': ['input', 1], 'p': ['output', 1]}},
        'outputs': {'gold': gold, 'gate': gate}}
    old_prep = _put(project, 'evidence/preparation.json', prep_value)
    current_prep = _put(project, 'reports/current-preparation.json', prep_value)
    sources_value = {'programs/librelane_eqy.py': 'a',
                     'programs/lec_post_layout_check.py': 'b',
                     'native/librelane/steps/yosys.py': 'c'}
    monkeypatch.setattr(lec, 'operation_sources', lambda: sources_value)
    sources = _put(project, 'evidence/operation-sources.json', sources_value)
    model = _put(project, 'evidence/model.v', 'module cell(input a, output y); assign y=a; endmodule\n')
    model_path = str(project / model['path'])
    config_value = {'DESIGN_NAME': 'chip_top', 'PDK': 'gf180mcuD',
                    'STD_CELL_LIBRARY': 'gf180mcu_fd_sc_mcu7t5v0',
                    'VERILOG_FILES': ['/e/gold'], 'CELL_VERILOG_MODELS': [model_path],
                    'EQY_SCRIPT': '/e/chip_top.eqy'}
    config = _put(project, 'evidence/config.json', config_value)
    proof_value['config_sha256'] = config['sha256']
    (project / proof['path']).write_text(json.dumps(proof_value))
    proof = lec._record(project, project / proof['path'])
    state = _put(project, 'evidence/state.json', {'nl': '/e/gate'})
    script = lec.eqy.eqy_script('chip_top', [Path('/e/gold')], Path('/e/gate'),
                                'inputs/lib.lib')
    cid = '1' * 64
    local_image = {'image': lec.EDA_IMAGE, 'image_id': 'sha256:' + '2' * 64,
                   'cid': cid, 'network_mode': 'none'}
    fingerprint_value = {'image': lec.EDA_IMAGE, 'state_files': {'/e/gate': gate['sha256']},
                         'config_files': {'/e/gold': gold['sha256'],
                             model_path: model['sha256'], '/e/chip_top.eqy':
                             hashlib.sha256(script.encode()).hexdigest()},
                         'local_image': local_image}
    fingerprint = _put(project, 'evidence/fingerprint.json', fingerprint_value)
    step = _put(project, 'evidence/native-step.json', {'input': fingerprint_value})
    method = _put(project, 'evidence/method.py', '# retained native method\n')
    run = _put(project, 'evidence/run.sh', '# retained native invocation\n')
    argv = _put(project, 'evidence/argv.json',
                ["docker", "run", lec.EDA_IMAGE, "--skip", "bash", "/evidence/run.sh"])
    native_value = {'component_status': 'PASS', 'native_status': 'PASS',
        'image': lec.EDA_IMAGE, 'image_id': local_image['image_id'], 'cid': cid, 'exit_code': 0,
        'argv': {'sha256': argv['sha256']},
        'source_closure': {'sha256': sources['sha256']},
        'positive': {'proof': {'sha256': proof['sha256']}},
        'physical_preparation': {'sha256': old_prep['sha256']},
        'raw_adopted_netlist': {'sha256': netlist['sha256']},
        'reference_rtl': {'sha256': rtl['sha256']}}
    native = _put(project, 'evidence/native.json', native_value)
    retained_value = {'schema': lec.RETAINED_SCHEMA, 'status': 'PASS',
        'image': lec.EDA_IMAGE, 'scope': 'powered single-domain functional subset',
        'native_receipt': native, 'operation_sources': sources, 'preparation': old_prep,
        'proof': proof, 'reference_view': gold, 'gate_view': gate, 'config': config,
        'state_in': state, 'input_fingerprint': fingerprint, 'native_step_receipt': step,
        'partition_list': listing, 'strategy_statuses': [pdr, sat],
        'method_source': method, 'run_script': run, 'argv': argv}
    retained = _put(project, 'input/flow109/D44-retained-native.json', retained_value)
    prepared = {'retained_native': project / retained['path'],
        'transformation_receipt': current_prep,
        'proof_paths': {'rtl': [project / gold['path']],
                        'adopted_netlist': project / gate['path']},
        'paths': {'rtl': [project / rtl['path']],
                  'adopted_netlist': project / netlist['path']},
        'manifest': {'top': 'chip_top', 'liberty': {'path': 'inputs/lib.lib'}, 'librelane': {
            'PDK': 'gf180mcuD', 'STD_CELL_LIBRARY': 'gf180mcu_fd_sc_mcu7t5v0'}}}
    return prepared, retained_value


def test_retained_native_proof_is_reopened_only_for_exact_current_views(tmp_path, monkeypatch):
    prepared, _ = _retained_case(tmp_path, monkeypatch)
    proof, adoption = lec._consume_retained_native(tmp_path, prepared)
    assert proof['verdict'] == 'PASS'
    assert adoption['mode'] == 'current_views_exactly_match_retained_native_EQY_subject'


def test_current_retained_physical_views_are_consumed_without_producer_rerun(tmp_path,
                                                                             monkeypatch):
    prepared, retained = _retained_case(tmp_path, monkeypatch)
    retained['current_preparation'] = prepared['transformation_receipt']
    Path(prepared['retained_native']).write_text(json.dumps(retained))
    views, receipt = lec._retained_physical_views(tmp_path, prepared)
    assert views['status'] == 'PREPARED_NOT_EQUIVALENCE_PROVEN'
    assert receipt == prepared['transformation_receipt']


def _source_owned_identity_case(project, monkeypatch):
    prepared, retained = _retained_case(project, monkeypatch)
    argv = retained.pop('argv')
    retained['current_preparation'] = prepared['transformation_receipt']
    Path(prepared['retained_native']).write_text(json.dumps(retained))
    proof, adoption = lec._consume_retained_native(project, prepared)
    retained['argv'] = argv
    Path(prepared['retained_native']).write_text(json.dumps(retained))
    adoption['receipt'] = lec._record(project, Path(prepared['retained_native']))
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D44', 'D44')
    component = {'component_status': 'PASS', 'proof': proof,
        'proof_receipt': retained['proof'], 'transformation_receipt': retained['current_preparation'],
        'retained_native': adoption, 'inputs': {'inputs/rtl.v': lec._sha(project / 'inputs/rtl.v')},
        'source_sha256': lec.operation_sources(),
        'model_census': {'gold': {'modules': ['chip_top'], 'ports': {'p': {'direction': 'output'}}},
                         'gate': {'modules': ['chip_top'], 'ports': {'p': {'direction': 'output'}}}},
        'metric_bindings': {'schema': lec.METRICS_SCHEMA}}
    obligation = context['resolved_row']['obligations'][0]
    return context, component, obligation, retained


def test_source_owned_D44_identity_reopens_actual_retained_execution(tmp_path, monkeypatch):
    context, component, obligation, _ = _source_owned_identity_case(tmp_path, monkeypatch)
    try:
        if len(inspect.signature(metrics._d44_identity).parameters) == 3:
            identity = metrics._d44_identity(component, context, obligation)
        else:
            identity = metrics._d44_identity(tmp_path, component, context, obligation)
    except metrics.MetricRefusal as exc:
        identity = {'refusal': exc.code}
    assert 'tool_execution' in identity, identity
    execution = identity['tool_execution']['source_owned']
    assert execution['policy']['reason'] == 'SOURCE_OWNED_EXISTING_NATIVE_COMPONENT'
    assert execution['native_receipt']['sha256']
    assert execution['model_census'] == component['model_census']


@pytest.mark.parametrize('damage', ['explicit_empty_claim', 'missing_proof', 'proof',
                                    'partition', 'input', 'source', 'config', 'tool',
                                    'forged_context'])
def test_source_owned_D44_identity_refuses_missing_stale_or_forged_evidence(
        tmp_path, monkeypatch, damage):
    context, component, obligation, retained = _source_owned_identity_case(tmp_path, monkeypatch)
    if damage == 'explicit_empty_claim':
        context['runtime_tool_uses'] = []
    elif damage == 'missing_proof':
        component.pop('proof_receipt')
    elif damage == 'proof':
        (tmp_path / retained['proof']['path']).write_text('{}')
    elif damage == 'partition':
        (tmp_path / retained['strategy_statuses'][0]['path']).write_text('FAIL\n')
    elif damage == 'input':
        (tmp_path / 'inputs/rtl.v').write_text('module changed; endmodule\n')
    elif damage == 'source':
        component['source_sha256'] = {'changed': 'source'}
    elif damage == 'config':
        (tmp_path / retained['config']['path']).write_text('{}')
    elif damage == 'tool':
        native_path = tmp_path / retained['native_receipt']['path']
        native = json.loads(native_path.read_text())
        native['image_id'] = 'sha256:' + 'f' * 64
        native_path.write_text(json.dumps(native))
        retained['native_receipt'] = lec._record(tmp_path, native_path)
        manifest = tmp_path / 'input/flow109/D44-retained-native.json'
        manifest.write_text(json.dumps(retained))
        component['retained_native']['receipt'] = lec._record(tmp_path, manifest)
    else:
        context['resolved_row']['profile']['dispatch'].pop('admission_policy')
    with pytest.raises(metrics.MetricRefusal):
        metrics._d44_identity(tmp_path, component, context, obligation)


@pytest.mark.parametrize('damage, reason', [
    ('partition', 'D44_INPUT_STALE_OR_MISSING'),
    ('view', 'D44_INPUT_STALE_OR_MISSING'),
    ('source', 'D44_RETAINED_PROOF_SOURCE_CHANGED')])
def test_retained_native_proof_refuses_missing_or_stale_evidence(tmp_path, monkeypatch,
                                                                damage, reason):
    prepared, retained = _retained_case(tmp_path, monkeypatch)
    if damage == 'partition':
        (tmp_path / retained['strategy_statuses'][0]['path']).write_text('FAIL\n')
    elif damage == 'view':
        (tmp_path / retained['gate_view']['path']).write_text('stale\n')
    else:
        monkeypatch.setattr(lec, 'operation_sources', lambda: {
            'programs/librelane_eqy.py': 'changed',
            'programs/lec_post_layout_check.py': 'b',
            'native/librelane/steps/yosys.py': 'c'})
    with pytest.raises(admission.AdmissionRefusal, match=reason):
        lec._consume_retained_native(tmp_path, prepared)
