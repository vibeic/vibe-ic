"""M01 inherited-producer/consumer adapter controls; no product qualification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import flow109
import flow109_admission as admission
import flow109_mixed_m01 as mixed
from _hostpaths import require_repo


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _basis(source, line, quote):
    return [{'source': source, 'line': line, 'quote': quote}]


def _bound(value, source, line, quote):
    return {'status': 'BOUND', 'value': value, 'basis': _basis(source, line, quote)}


def _case(project):
    lines = {
        'analog': ('Analog input pins AIN1..AIN2 use analog domain ANA and rail VDDA; '
                   'direction input; unit V.'),
        'digital': ('Digital output pins DOUT1..DOUT2 use digital domain DIG and rail VDDD; '
                    'direction output; unit bit.'),
        'clock': ('Clock input pins CLK1..CLK2 use clock signal type in digital domain DIG and '
                  'rail VDDD; direction input; unit Hz.'),
        'relationship': ('Converter clocks CLK1..CLK2 drive outputs DOUT1..DOUT2 for owner '
                         'converter.'),
        'budget': 'Interface latency budget is 2 cycles.',
    }
    l1 = _put(project, 'input/docs/L1_DATASHEET.md', '\n'.join(lines.values()) + '\n')
    l5_text = ('A 12-bit ADC converter has 2 channels and accepts AIN1..AIN2.\n'
               + lines['relationship'] + '\n' + lines['budget'] + '\n')
    l5 = _put(project, 'input/docs/L5_ANALOG_SPEC.md', l5_text)
    l9_text = ('## Supply domains\n| Rail | Voltage |\n|---|---|\n'
               '| VDDA | 1.8 V |\n| VDDD | 1.2 V |\n')
    l9 = _put(project, 'input/docs/L9_CONSTRAINTS.md', l9_text)

    domains = [
        {'name': 'ANA', 'rail': _bound('VDDA', 'L1', 1, lines['analog']),
         'voltage': _bound('1.8 V', 'L9', 4, '| VDDA | 1.8 V |'),
         'basis': _basis('L1', 1, lines['analog'])},
        {'name': 'DIG', 'rail': _bound('VDDD', 'L1', 2, lines['digital']),
         'voltage': _bound('1.2 V', 'L9', 5, '| VDDD | 1.2 V |'),
         'basis': _basis('L1', 2, lines['digital'])},
    ]
    pins = []
    for names, line, direction, signal_type, domain, rail, unit in (
            (('AIN1', 'AIN2'), lines['analog'], 'input', 'analog', 'ANA', 'VDDA', 'V'),
            (('DOUT1', 'DOUT2'), lines['digital'], 'output', 'digital', 'DIG', 'VDDD', 'bit'),
            (('CLK1', 'CLK2'), lines['clock'], 'input', 'clock', 'DIG', 'VDDD', 'Hz')):
        line_no = list(lines).index({'analog': 'analog', 'digital': 'digital',
                                    'clock': 'clock'}[signal_type]) + 1
        for name in names:
            pins.append({'name': name, 'basis': _basis('L1', line_no, line),
                         'direction': _bound(direction, 'L1', line_no, line),
                         'signal_type': _bound(signal_type, 'L1', line_no, line),
                         'domain': _bound(domain, 'L1', line_no, line),
                         'rail': _bound(rail, 'L1', line_no, line),
                         'unit': _bound(unit, 'L1', line_no, line)})
    requirements = _put(project, 'input/flow109/M01-requirements.json', {
        'schema': mixed.SCHEMA,
        'source_authority': {'status': 'SOURCE_BOUND', 'authority': 'fixture_source_owner',
                             'source_reference': 'neutral component control'},
        'domains': domains, 'pins': pins,
        'relationships': [{'id': 'clock_to_serial', 'kind': 'clock_output',
                           'inputs': ['CLK1', 'CLK2'], 'outputs': ['DOUT1', 'DOUT2'],
                           'owner': 'converter', 'status': 'BOUND',
                           'basis': _basis('L5', 2, lines['relationship'])}],
        'budgets': [{'name': 'interface_latency',
                     'value': _bound('2 cycles', 'L5', 3, lines['budget'])}],
    })

    topology = _put(project, 'phase3/analog/converter/topology.json',
                    {'block': 'converter', 'block_type': 'converter'})
    freeze = _put(project, 'adopted/analog_topology/topology_freeze.json',
                  {'step_id': 'A04', 'status': 'PASS'})
    a04 = _put(project, 'reports/flow109/components/A04.json', {
        'schema': 'vibeic.flow109.analog-topology.v1', 'step_id': 'A04',
        'component_status': 'PASS', 'flow109_acceptance': 'NOT_MEASURED',
        'freeze': freeze, 'blocks': [{'block': 'converter', 'component_status': 'PASS',
                                      'topology': topology}]})
    config = _put(project, mixed.INPUT, {
        'schema': mixed.SCHEMA, 'basis': 'source_bound_interface_facts',
        'sources': {'L1': l1, 'L5': l5, 'L9': l9},
        'requirements': requirements, 'a04_receipt': a04})

    features = next(row['features'] for row in flow109.load_registry()['reference_profiles']
                    if row['name'] == 'Mixed hard-IP')
    plan = flow109.resolve_plan(features)
    use = flow109.resolve_step(plan, 'M01')['tool_uses'][0]
    binary = Path(shutil.which('python3')).resolve()
    executable = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    identity = {'use_id': use['use_id'], 'tool_id': 'python3', 'version': sys.version,
                'build_sha256': executable['sha256'], 'executable': executable,
                'config': config,
                'pdk': {'applicable': False,
                        'reason': 'source interface contract is PDK-independent'},
                'deck': requirements, 'corner': ['source'],
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                              'operation_sources': mixed.operation_sources()}}
    evidence = _put(project, 'input/flow109/M01-reference.json',
                    {'scope': 'developer component control; not design signoff'})
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [evidence]}
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]}
    manifest = {'features': features, 'qualification_registry': 'qualifications.json',
                'runtime_tool_uses': [{**identity,
                    'qualification_sha256': admission.canonical_sha(record)}]}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))
    context = flow109.execution_context(plan, 'M01', 'M01',
                                        runtime_tool_uses=manifest['runtime_tool_uses'],
                                        qualification_registry='qualifications.json')
    return {'requirements': requirements, 'config': config, 'registry': registry,
            'manifest': manifest, 'context': context, 'lines': lines}


def _sync(project, case, *, requirements_changed=False, config_changed=False):
    identity = case['registry']['uses'][0]['identity']
    if requirements_changed:
        path = project / case['requirements']['path']
        case['requirements']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        identity['deck'] = case['requirements']
        body = json.loads((project / case['config']['path']).read_text())
        body['requirements'] = case['requirements']
        (project / case['config']['path']).write_text(json.dumps(body, indent=2))
        config_changed = True
    if config_changed:
        path = project / case['config']['path']
        case['config']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        identity['config'] = case['config']
    record = case['registry']['uses'][0]
    case['manifest']['runtime_tool_uses'][0] = {
        **identity, 'qualification_sha256': admission.canonical_sha(record)}
    (project / 'qualifications.json').write_text(json.dumps(case['registry']))
    (project / 'manifest.json').write_text(json.dumps(case['manifest']))


def _run(project):
    return subprocess.run([
        sys.executable, str(mixed.HERE / 'vibe_ic_one_shot_runner.py'), str(project),
        '--flow', '109', '--flow109-manifest', str(project / 'manifest.json'),
        '--entry-step', 'M01', '--exit-step', 'M01', '--route', 'ip', '--no-dashboard'],
        capture_output=True, text=True)


def test_m01_adapter_loads_by_path_with_sibling_imports():
    path = mixed.HERE / 'flow109_mixed_m01.py'
    spec = importlib.util.spec_from_file_location('flow109_mixed_m01_path_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCHEMA == mixed.SCHEMA


def test_m01_normal_entry_uses_inherited_producers_and_consumer(tmp_path):
    _case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/M01.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['consumer']['verdict'] == 'PASS'
    assert report['a04_binding']['status'] == 'BOUND_COMPONENT_ONLY'
    assert report['a04_binding']['independent_review'] == 'PENDING'
    assert report['metric_acceptance_status'] == 'UNIMPLEMENTED'
    assert set(report['gate_layers'].values()) == {'NOT_MEASURED'}
    assert (tmp_path / mixed.FREEZE).is_file()


@pytest.mark.parametrize('damage,token', [
    ('rail_absent', 'M01_SOURCE_RAILS_ABSENT'),
    ('rail_domain_contradiction', 'M01_PIN_DOMAIN_RAIL_CONTRADICTION'),
    ('pin_absent', 'M01_PIN_NOT_SOURCE_BOUND'),
    ('a04_owner', 'M01_A04_OWNER_MISMATCH'),
    ('clock_semantics', 'M01_RELATIONSHIP_KIND_UNSUPPORTED'),
])
def test_m01_refuses_absent_or_contradictory_source_contract(tmp_path, damage, token):
    case = _case(tmp_path)
    if damage == 'rail_absent':
        path = tmp_path / 'input/docs/L9_CONSTRAINTS.md'
        path.write_text('# Constraints\nNo supply table is source-stated.\n')
        body = json.loads((tmp_path / case['config']['path']).read_text())
        body['sources']['L9']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (tmp_path / case['config']['path']).write_text(json.dumps(body, indent=2))
        _sync(tmp_path, case, config_changed=True)
    else:
        path = tmp_path / case['requirements']['path']
        body = json.loads(path.read_text())
        if damage == 'rail_domain_contradiction':
            body['pins'][0]['rail'] = _bound('VDDD', 'L9', 5, '| VDDD | 1.2 V |')
        elif damage == 'pin_absent':
            body['pins'][0]['name'] = 'ABSENT_PIN'
        elif damage == 'clock_semantics':
            body['relationships'][0]['kind'] = 'phase_magic'
        else:
            body['relationships'][0]['owner'] = 'unowned_converter'
            body['relationships'][0]['basis'] = _basis(
                'L5', 2, case['lines']['relationship'].replace('converter', 'unowned_converter'))
            l5 = tmp_path / 'input/docs/L5_ANALOG_SPEC.md'
            l5.write_text(l5.read_text().replace('owner converter', 'owner unowned_converter'))
            config_body = json.loads((tmp_path / case['config']['path']).read_text())
            config_body['sources']['L5']['sha256'] = hashlib.sha256(l5.read_bytes()).hexdigest()
            (tmp_path / case['config']['path']).write_text(json.dumps(config_body, indent=2))
        path.write_text(json.dumps(body, indent=2))
        _sync(tmp_path, case, requirements_changed=True, config_changed=damage == 'a04_owner')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert token in result.stdout + result.stderr
    assert not (tmp_path / mixed.FREEZE).exists()


def test_m01_retains_unresolved_budget_as_not_measured(tmp_path):
    case = _case(tmp_path)
    path = tmp_path / case['requirements']['path']
    body = json.loads(path.read_text())
    body['budgets'][0]['value'] = {
        'status': 'NOT_MEASURED', 'reason': 'source states no accepted latency budget',
        'basis': _basis('L5', 3, case['lines']['budget'])}
    body['relationships'][0]['status'] = 'NOT_MEASURED'
    body['relationships'][0]['reason'] = 'source names clocks and outputs but no crossing policy'
    path.write_text(json.dumps(body, indent=2))
    _sync(tmp_path, case, requirements_changed=True)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/M01.json').read_text())
    assert report['component_status'] == 'NOT_MEASURED'
    assert report['consumer']['reason'] == 'M01_SOURCE_FACTS_UNRESOLVED'
    assert report['budgets'][0]['value']['status'] == 'NOT_MEASURED'
    assert report['relationships'][0]['status'] == 'NOT_MEASURED'


def test_m01_refuses_source_changed_after_prepare(tmp_path):
    case = _case(tmp_path)
    prepared = mixed.prepare(tmp_path, case['context'])
    (tmp_path / 'input/docs/L1_DATASHEET.md').write_text('changed after prepare\n')
    with pytest.raises(admission.AdmissionRefusal, match='M01_STALE_OR_MISSING_INPUT'):
        mixed._before(tmp_path, case['context'], prepared)


def test_m01_source_producer_reverse_and_restored(tmp_path, monkeypatch):
    case = _case(tmp_path)
    original = mixed.rail_source.derive
    monkeypatch.setattr(mixed.rail_source, 'derive', lambda *_args, **_kwargs: {'rails': []})
    with pytest.raises(admission.AdmissionRefusal, match='M01_SOURCE_RAILS_ABSENT'):
        mixed.prepare(tmp_path, case['context'])
    monkeypatch.setattr(mixed.rail_source, 'derive', original)
    assert mixed.prepare(tmp_path, case['context'])['rails']


def test_m01_inherited_rail_producer_reads_checked_in_interface_source():
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'tests', 'fixtures', 'a9_cosim_scenarios', 'input', 'docs',
                          'L9_CONSTRAINTS.md')
    derived = mixed.rail_source.derive(source.parents[3], [str(source.relative_to(source.parents[3]))])
    assert derived['docs_read'] == 1
    assert derived['rails']
    assert all(row['evidence']['file'] == str(source.relative_to(source.parents[3]))
               for row in derived['rails'])
