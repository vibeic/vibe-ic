"""D44 actual LibreLane EQY controls on an independent tiny mapped design.

Qualification references here are developer contract controls, not PDK/signoff
qualification. No existing IC input, native run, pre-layout PASS or GLS is used.
"""
from __future__ import annotations

import copy
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
    assert {item['id']: item['status'] for item in accepted['obligations']} == {
        'final_lec.final_lec_unproved': 'PASS',
        'final_lec.sta_lvs_release_netlist_mapping': 'FAIL'}


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
