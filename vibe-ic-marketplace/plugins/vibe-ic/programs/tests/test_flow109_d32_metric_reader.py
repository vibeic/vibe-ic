"""SOURCE_ONLY D32 reader controls: no native, qualification or row PASS credit.

The existing pad producer writes the neutral placement fixture. Database/cell
views below are explicitly synthetic function inputs, never canonical native
receipts. Completion tests inject that observation at the reader seam, then
exercise the actual adapter and Flow109 consumer. Native owner replay remains
required independently.
"""
import copy
import json
from pathlib import Path
import hashlib
import shutil
import subprocess
import ast

import pytest
import flow109
import pad_ring_gen as owner
import _pad_ring as ring
import test_pad_ring as existing
from _hostpaths import require_repo


@pytest.fixture
def population(tmp_path):
    project = existing._project(tmp_path)
    assert existing._gen(project) == 0
    placed = json.loads((project / ring.REPORT_REL).read_text())
    logical = project / 'logical.spice'
    logical.write_text('.subckt core ' + ' '.join(existing.ALL_SIGNALS) + '\n.ends core\n')
    data = {'top': 'core', 'logical': str(logical),
            'floorplan': str(project / ring.FLOORPLAN_DEF_REL),
            'assignment': str(project / ring.ASSIGNMENT_REL)}
    # SOURCE_ONLY native-edge values; these are not serialized as receipts.
    db = {'top': 'core',
          'ports': {name: name for name in existing.ALL_SIGNALS},
          'instances': {pad['instance']: {'master': pad['master'], 'placed': True}
                        for pad in placed['pads']},
          'nets': {name: {'iterms': [existing.PADS[name] + '/terminal']}
                   for name in existing.ALL_SIGNALS}}
    views = {'pad_bidir': {'present': True, 'nonempty': True}}
    return project, data, placed, db, views


def observe(population):
    if not hasattr(owner, '_d32_native_population'):
        pytest.skip('exact-main has no D32 population reader; canonical controls below still execute')
    _, data, placement, db, views = population
    return owner._d32_native_population(data, placement, db, views)


def context():
    # Read the real in-repo registry, through its canonical resolver.
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'flow109.json')
    registry = json.loads(source.read_text())
    for profile in registry['reference_profiles']:
        plan = flow109.resolve_plan(profile['features'])
        row = next((r for r in plan['rows'] if r['id'] == 'D32'), None)
        if row and row['profile']['id'] == 'analog_die':
            return flow109.execution_context(plan, 'D32', 'D32')
    raise AssertionError('real registry has no selected analog D32 reference profile')


def consume(project, monkeypatch, observation, *, component_status='PASS', unavailable=False, prior_metric_fail=False):
    current = context()
    if hasattr(owner, '_d32_metric_observation'):
        def reader(*args):
            if unavailable:
                raise ValueError('SOURCE_ONLY_STALE_INPUT_CONTROL')
            return copy.deepcopy(observation)
        monkeypatch.setattr(owner, '_d32_metric_observation', reader)
    component = {'step_id': 'D32', 'context_sha256': current['context_sha256'],
        'component_status': component_status, 'completed': False,
        'default_row_status': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
        'delivery_accepted': False, 'scope': 'SOURCE_ONLY_FUNCTION_EDGE_CONTROL'}
    # The ordinary consumer publishes only its normal diagnostic result. No
    # qualification, native launch, or accepted predecessor is manufactured.
    if prior_metric_fail:
        component.update(metric_acceptance_status='FAIL', default_row_status='FAIL',
            metric_acceptance={'status': 'FAIL', 'reason': 'SOURCE_ONLY_PRIOR_MEASURED_FAILURE',
                'obligations': [{'id': current['resolved_row']['obligations'][0]['id'], 'status': 'FAIL'}]})
    return flow109._selected_step_result(project, current, component, adapter=owner)


def test_complete_source_io_population_retains_all_physical_gaps(population):
    result = observe(population)
    assert result['status'] == 'PASS' and result['failures'] == []
    assert len(result['required_io']) == len(existing.ALL_SIGNALS)
    assert set(result['required_ports']) == set(existing.ALL_SIGNALS)
    assert 'ESD_protection_inventory' in result['unmeasured']
    assert 'physical_PG_rail_conduction' in result['unmeasured']


@pytest.mark.parametrize('damage', ['truncated', 'disconnected', 'missing_view', 'wrong_master',
                                     'duplicate', 'unplaced', 'missing_port'])
def test_observed_set_cannot_approve_its_own_population(population, damage):
    _, _, placement, db, views = population
    pad = placement['pads'][0]
    if damage == 'truncated':
        placement['pads'].pop()
    elif damage == 'disconnected':
        db['nets'][pad['signal']]['iterms'] = []
    elif damage == 'missing_view':
        views['pad_bidir']['nonempty'] = False
    elif damage == 'wrong_master':
        db['instances'][pad['instance']]['master'] = 'foreign_pad'
    elif damage == 'duplicate':
        placement['pads'][-1] = copy.deepcopy(pad)
    elif damage == 'unplaced':
        db['instances'][pad['instance']]['placed'] = False
    else:
        del db['ports'][pad['signal']]
    result = observe(population)
    assert result['status'] == 'FAIL' and result['failures']
    assert len(result['required_io']) == len(existing.ALL_SIGNALS)


def test_missing_independent_source_population_refuses(population):
    _, data, *_ = population
    Path(data['assignment']).write_text('{}')
    if not hasattr(owner, '_d32_native_population'):
        pytest.skip('reader absent on exact main')
    with pytest.raises(ValueError, match='D32_REQUIRED_IO_POPULATION_UNAVAILABLE'):
        observe(population)


def test_actual_consumer_never_promotes_complete_io_census_to_row_PASS(population, monkeypatch):
    project, *_ = population
    result = consume(project, monkeypatch,
                     {'status': 'PASS', 'failures': [], 'scope': 'SOURCE_ONLY'})
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False and result['delivery_accepted'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('failure', ['D32_DECLARED_PAD_POPULATION_MISMATCH',
                                  'D32_REQUIRED_NATIVE_PAD_DISCONNECTED: pad_a',
                                  'D32_REQUIRED_NATIVE_PAD_VIEW_MISSING: pad_a'])
def test_actual_consumer_blocks_measured_inventory_failure(population, monkeypatch, failure):
    project, *_ = population
    result = consume(project, monkeypatch,
                     {'status': 'FAIL', 'failures': [failure], 'scope': 'SOURCE_ONLY'})
    # Value-based pre-fix control: exact main returns NOT_MEASURED here.
    assert result['default_row_status'] == 'FAIL', result
    assert result['completed'] is False and result['delivery_accepted'] is False


def test_later_unmeasured_reader_never_erases_existing_FAIL(population, monkeypatch):
    project, *_ = population
    result = consume(project, monkeypatch, {}, component_status='FAIL', unavailable=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False


def test_stale_or_missing_reader_remains_unmeasured(population, monkeypatch):
    project, *_ = population
    result = consume(project, monkeypatch, {}, unavailable=True)
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False


def test_reader_refuses_unrecorded_source_without_trusting_component_PASS(population):
    if not hasattr(owner, 'accept_d32'):
        pytest.skip('reader absent on exact main')
    project, *_ = population
    current = context()
    result = owner.accept_d32(project, current, {'step_id': 'D32',
        'context_sha256': current['context_sha256'], 'component_status': 'PASS'})
    assert result['status'] == 'NOT_MEASURED'
    assert 'D32_CONSUMED_SOURCE_CHANGED_OR_UNRECORDED' in result['detail']
    assert result['delivery_blocked'] is True


def test_existing_native_readers_reopen_neutral_geometry_without_any_qualification(population):
    """Actual tiny OpenDB/KLayout reads; no native launch or canonical receipt issued."""
    if not hasattr(owner, '_d32_metric_readback'):
        pytest.skip('reader absent on exact main')
    project, data, placed, *_ = population
    # Extend the existing neutral source fixture with explicit terminal nets.
    lef = project / 'native.lef'
    text = existing._io_lef()
    text = text.replace('SITE io_site', 'LAYER met2\n TYPE ROUTING ;\n DIRECTION HORIZONTAL ;\n'
        ' PITCH 1 ;\n WIDTH 0.1 ;\n SPACING 0.1 ;\nEND met2\nSITE io_site', 1)
    text = text.replace('END pad_bidir', ' PIN terminal\n  DIRECTION INOUT ;\n  USE SIGNAL ;\n'
        '  PORT\n   LAYER met2 ;\n   RECT 1 1 2 2 ;\n  END\n END terminal\nEND pad_bidir')
    text = text.replace('END LIBRARY', 'MACRO CORE_MACRO\n CLASS BLOCK ;\n SIZE 10 BY 10 ;\n'
                        'END CORE_MACRO\nEND LIBRARY')
    lef.write_text(text)
    work = project / 'source_only_native_readback'
    generated = work / 'case' / ring.PADRING_DEF_REL
    generated.parent.mkdir(parents=True)
    def_text = (project / ring.PADRING_DEF_REL).read_text()
    nets = [f'- {name} ( PIN {name} ) ( {existing.PADS[name]} terminal ) ;'
            for name in existing.ALL_SIGNALS]
    def_text = def_text.replace('END DESIGN', f'NETS {len(nets)} ;\n' + '\n'.join(nets) +
                                '\nEND NETS\nEND DESIGN')
    generated.write_text(def_text)
    gds = project / 'source_only_cells.gds'
    script = project / 'source_only_gds.py'
    masters = sorted({p['master'] for key in ('pads', 'corners', 'fillers') for p in placed[key]})
    script.write_text('import pya\nl=pya.Layout();l.dbu=0.001\nlayer=l.layer(1,0)\n' +
        '\n'.join(f'l.create_cell({name!r}).shapes(layer).insert(pya.Box(0,0,1000,1000))'
                  for name in masters) + f'\nl.write({str(gds)!r})\n')
    tools = {name: {'path': shutil.which(name)} for name in ('openroad', 'klayout')}
    assert all(row['path'] for row in tools.values()), 'run in the installed official EDA image'
    proc = subprocess.run([tools['klayout']['path'], '-b', '-r', str(script)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data.update(lefs=[str(lef)], gds=[str(gds)])
    (work / 'gds-request.json').write_text(json.dumps({'masters': masters}))
    for row in tools.values():
        row['sha256'] = hashlib.sha256(Path(row['path']).resolve().read_bytes()).hexdigest()
    readback = owner._d32_metric_readback(project, data, work, tools)
    assert set(readback['native_db']['ports']) == set(existing.ALL_SIGNALS)
    assert set(readback['native_gds']) == set(masters)
    assert all(v['present'] and v['nonempty'] for v in readback['native_gds'].values())
    for name in existing.ALL_SIGNALS:
        assert existing.PADS[name] + '/terminal' in readback['native_db']['nets'][name]['iterms']
    assert all(e['returncode'] == 0 for e in readback['executions'])
    assert not list((project / 'reports/flow109/D32').glob('*/component.json'))
    assert not (project / 'qualifications.json').exists()


@pytest.mark.parametrize('damage', ['current', 'declaration_bytes', 'stale_logical',
                                     'foreign_view', 'missing_floorplan'])
def test_actual_input_reader_binds_source_declaration_and_selected_views(population, monkeypatch, damage):
    """SOURCE_ONLY PDK-discovery edge; actual input reader, no launch or receipts."""
    if not hasattr(owner, 'accept_d32'):
        pytest.skip('D32 metric reader absent on exact main')
    import analog_pdk_availability as resolver
    project, data, *_ = population
    tree = project / 'pdk/proc'
    gds = tree / 'libs.ref/proc_io/gds/io.gds'
    gds.parent.mkdir(parents=True)
    gds.write_text('SOURCE_ONLY view identity, never supplied to a native tool\n')
    tech = tree / 'libs.ref/proc_tech/lef/proc_tech.lef'
    tech.parent.mkdir(parents=True)
    tech.write_text('SOURCE_ONLY technology identity\n')
    declaration = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    declaration.parent.mkdir(parents=True)
    declaration.write_text('{"fields":{"pdk_target":"neutralprocess"}}\n')
    monkeypatch.setattr(resolver, 'resolve_pdk', lambda *a, **k:
        {'source': 'container_installed', 'available': True, 'pdk_root': str(tree),
         'scope': 'SOURCE_ONLY_DISCOVERY_EDGE'})
    def ref(path, absolute=False):
        path = Path(path)
        return {'path': str(path if absolute else path.relative_to(project)),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    lefs = ring.discover_io_lefs(str(tree.parent), tree.name)
    assert lefs, 'existing neutral pad fixture must contain its IO LEF'
    config = {'top': 'core', 'floorplan_def': ref(data['floorplan']),
              'pad_assignment': ref(data['assignment']), 'logical_netlist': ref(data['logical']),
              'io_lefs': [ref(p, True) for p in lefs], 'io_gds': [ref(gds, True)],
              'technology_lef': ref(tech, True)}
    path = project / 'input/flow109/D32.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    before = owner._d32_inputs(project)
    assert before['inputs'][str(declaration)] == hashlib.sha256(declaration.read_bytes()).hexdigest()
    if damage == 'current':
        assert owner._d32_inputs(project) == before
        assert set(before['ports']) == set(existing.ALL_SIGNALS)
        assert not (project / 'reports/flow109/D32').exists()
        return
    if damage == 'declaration_bytes':
        declaration.write_text(declaration.read_text() + ' ')
    elif damage == 'stale_logical':
        Path(data['logical']).write_text(Path(data['logical']).read_text() + '* changed\n')
    elif damage == 'foreign_view':
        config['io_gds'][0]['path'] = str(project / 'foreign.gds')
        path.write_text(json.dumps(config))
    else:
        Path(data['floorplan']).unlink()
    current = context()
    result = owner.accept_d32(project, current, {'step_id': 'D32',
        'context_sha256': current['context_sha256'], 'component_status': 'PASS',
        'metric_sources': owner._d32_metric_sources(), 'inputs': before['inputs']})
    assert result['status'] == 'NOT_MEASURED'
    assert result['delivery_blocked'] is True
    assert 'observation' not in result
    assert not (project / 'reports/flow109/D32').exists()


def test_placement_implementation_is_part_of_consumed_source_identity(tmp_path, monkeypatch):
    """SOURCE_ONLY copy: changing existing placement code must change the fingerprint."""
    if not hasattr(owner, '_d32_metric_sources'):
        pytest.skip('metric reader absent on exact main')
    original = Path(owner.__file__)
    before = owner._d32_metric_sources()
    tree = ast.parse(original.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    main.body.insert(0, ast.Pass())
    for sibling in before:
        if sibling.endswith('.py') and sibling != original.name:
            shutil.copyfile(original.parent / sibling, tmp_path / sibling)
    for name in ('_pad_ring.py', 'pad_ring_check.py', 'analog_lvs_comparison_prep.py',
                 'declared_pdk_is_the_pdk_used_check.py', 'l_doc_consumer_contract.py',
                 'analog_pdk_availability.py'):
        if not (tmp_path / name).exists():
            shutil.copyfile(original.parent / name, tmp_path / name)
    copied = tmp_path / original.name
    copied.write_text(ast.unparse(tree))
    monkeypatch.setattr(owner, '__file__', str(copied))
    after = owner._d32_metric_sources()
    assert before != after, 'the actually consumed existing placement implementation was omitted'


def test_prior_metric_FAIL_survives_later_unmeasured_reader(population, monkeypatch):
    project, *_ = population
    result = consume(project, monkeypatch, {}, unavailable=True, prior_metric_fail=True)
    assert result['default_row_status'] == 'FAIL'
    assert result['completed'] is False
    if hasattr(owner, 'accept_d32'):
        assert result['metric_acceptance']['metric_status'] == 'FAIL'
        assert result['metric_acceptance']['obligations'][0]['status'] == 'FAIL'
        assert result['metric_acceptance']['prior_failed_obligation_ids']
