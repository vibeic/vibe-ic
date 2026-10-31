"""SOURCE_ONLY new 51/52/56 controls; no prior CTS/placement tests replayed.

Native receipts and requirement APIs are explicit in-memory doubles. Disk
sentinels are deliberately invalid; neutral DEF/LEF/log bytes drive real
semantic readers. Unit qualification fixtures are not runtime qualification.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import execution_backend_producers as producer
import execution_backend_worker as worker
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import step_output_collector as versions
import test_flow109_window_continuation as windows

REAL_DOCUMENT = metrics._approved_document
REAL_RECEIPT = ll.validate_step_receipt


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def neutral_def(*, overlap=False, outside=False, missing=False):
    insts = [('m0', 'BLOCK0', 40000, 40000), ('m1', 'BLOCK0', 45000 if overlap else 60000, 40000),
             ('io0', 'PAD0', 0, 0), ('io1', 'PAD0', 20000, 0), ('esd', 'ESD0', 80000, 80000),
             ('pv', 'PAD0', 0, 80000), ('pg', 'PAD0', 20000, 80000)]
    if missing:
        insts = [i for i in insts if i[0] != 'esd']
    lines = ['VERSION 5.8 ;', 'DESIGN neutral ;', 'UNITS DISTANCE MICRONS 1000 ;',
             'DIEAREA ( 0 0 ) ( 100000 100000 ) ;', f'COMPONENTS {len(insts)} ;']
    lines += [f'- {n} {m} + FIXED ( {x} {y} ) N ;' for n, m, x, y in insts]
    lines += ['END COMPONENTS', 'PINS 2 ;',
        '- a + NET a + DIRECTION INPUT + USE SIGNAL + LAYER M1 ( 0 0 ) ( 2000 2000 ) + FIXED ( 0 0 ) N ;',
        f'- y + NET y + DIRECTION OUTPUT + USE SIGNAL + LAYER M1 ( 0 0 ) ( 2000 2000 ) + FIXED ( {110000 if outside else 20000} 0 ) N ;',
        'END PINS', 'NETS 2 ;', '- a ( PIN a ) ( io0 PAD ) ;', '- y ( PIN y ) ( io1 PAD ) ;',
        'END NETS', 'SPECIALNETS 2 ;', '- VDD ( pv VDD ) + USE POWER ;', '- VSS ( pg VSS ) + USE GROUND ;', 'END SPECIALNETS', 'END DESIGN', '']
    return '\n'.join(lines)


def neutral_lef():
    text = 'VERSION 5.8 ;\nLAYER M1\n TYPE ROUTING ;\n DIRECTION HORIZONTAL ;\n WIDTH 0.1 ;\nEND M1\n'
    for name, kind in [('BLOCK0', 'BLOCK'), ('PAD0', 'PAD'), ('ESD0', 'CORE')]:
        text += f'MACRO {name}\n CLASS {kind} ;\n ORIGIN 0 0 ;\n SIZE 10 BY 10 ;\n'
        text += ' PIN PAD\n DIRECTION INOUT ;\n USE SIGNAL ;\n PORT\n LAYER M1 ;\n RECT 0 0 2 2 ;\n END\n END PAD\n'
        for pin, use in [('VDD', 'POWER'), ('VSS', 'GROUND')]:
            text += f' PIN {pin}\n DIRECTION INOUT ;\n USE {use} ;\n PORT\n LAYER M1 ;\n RECT 0 0 1 1 ;\n END\n END {pin}\n'
        text += f'END {name}\n'
    return text + 'END LIBRARY\n'


@pytest.fixture
def digital(tmp_path, monkeypatch):
    project = tmp_path / 'SOURCE_ONLY_DIGITAL'
    project.mkdir()
    def put(path, body):
        p = project / path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body) if isinstance(body, (dict, list)) else body)
        return p
    c = SimpleNamespace(project=project, put=put, bodies={}, row='D31')
    c.nl = put('input/neutral.v', 'module neutral(input a, output y); assign y=a; endmodule\n')
    c.sdc = put('phase3/stage3/pnr/constraint.sdc', 'create_clock -period 24 [get_ports a]\n')
    c.lef = put('input/neutral.lef', neutral_lef())
    c.definition = put('native-geometry/neutral.def', neutral_def())
    c.odb = put('native-geometry/neutral.odb', 'SOURCE_ONLY_INVALID_ODB_SENTINEL\n')
    c.header = put('native-geometry/neutral.h.json', {'modules': {'neutral': {'ports': {'a': {'bits': [1]}, 'y': {'bits': [2]}}}}})
    c.initial = put('phase3/librelane/15-config/bridge/state_in.json', {'nl': str(c.nl), 'sdc': str(c.sdc)})
    c.steps = ['Yosys.JsonHeader', 'OpenROAD.Floorplan', 'OpenROAD.PadRing', 'OpenROAD.GeneratePDN']
    c.receipts, c.configs, c.folders = {}, {}, {}
    previous = c.initial
    for index, step in enumerate(c.steps, 1):
        folder = project / 'phase3/librelane/15-floorplan' / (f'{index:02d}-' + step.lower().replace('.', '-'))
        config = put('phase3/librelane/15-config/' + step + '.cell-policy.json', {'meta': {'step': step},
            'DESIGN_NAME': 'neutral', 'CELL_LEFS': [str(c.lef)], 'VDD_NETS': ['VDD'], 'GND_NETS': ['VSS']})
        state = put(folder / 'state_out.json', {'nl': str(c.nl), 'sdc': str(c.sdc), 'def': str(c.definition),
            'odb': str(c.odb), 'json_h': str(c.header), 'metrics': {'design__power_grid_violation__count': 0,
                'design__power_grid_violation__count__net:VDD': 0, 'design__power_grid_violation__count__net:VSS': 0}})
        log = put(folder / 'invocation.log', '[INFO PSM-0040] All shapes on net VDD are connected.\n[INFO PSM-0040] All shapes on net VSS are connected.\n')
        put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT\n')
        put(folder / 'pdk_root.json', {'mounts_under_it': []})
        fp = {'image': 'SOURCE_ONLY_DOUBLE', 'step': step, 'state': sha(previous), 'config': sha(config),
            'state_files': {str(p): sha(p) for p in ll._walk_paths({k: v for k, v in json.loads(previous.read_text()).items() if k != 'metrics'})},
            'config_files': {str(c.lef): sha(c.lef)}}
        c.receipts[str(folder)] = {'input': fp, 'sha256': {'state_out.json': sha(state), 'invocation.log': sha(log)}}
        c.configs[step], c.folders[step] = config, folder
        previous = state
    for net in ['VDD', 'VSS']:
        report = put(c.folders[c.steps[-1]] / (net + '-grid-errors.rpt'), '')
        c.receipts[str(report.parent)]['sha256'][report.name] = sha(report)
    c.handoff = {'state': str(previous), 'state_sha256': sha(previous), 'views': {}}
    for view, src, name in [('def', c.definition, 'floorplan.def'), ('odb', c.odb, 'librelane_floorplan.odb')]:
        dest = put('phase3/stage3/pnr/' + name, src.read_text())
        c.handoff['views'][view] = {'source': str(src), 'source_sha256': sha(src), 'dest': str(dest), 'dest_sha256': sha(dest)}
    c.handoff_path = put('reports/phase3/librelane_floorplan_handoff.json', c.handoff)
    pad = c.folders['OpenROAD.PadRing'] / 'state_out.json'
    put('reports/phase3/librelane_padring_handoff.json', {'state': str(pad), 'state_sha256': sha(pad)})
    monkeypatch.setattr(ll, 'validate_step_receipt', lambda folder, step: c.receipts[str(folder)])
    c.extras = {'bounded_state': True, 'native_state': str(previous), 'pdn_state': str(previous), 'handoff': str(c.handoff_path),
        'floorplan': str(project / producer.PNR / 'floorplan.def'), 'odb': str(project / producer.PNR / 'librelane_floorplan.odb'),
        'librelane_steps': c.steps}
    def publish():
        producer._publish_step15_bounded_state(project, SimpleNamespace(extras=c.extras))
        publisher = getattr(producer, '_publish_digital_floorplan_metrics', None)
        if publisher:
            publisher(project, {'image_id': 'SOURCE_ONLY_DOUBLE'}, c.extras)
    c.publish = publish
    c.publish()
    def select(row):
        c.row = row
        plan = flow109.resolve_plan(windows._profile())
        c.context = flow109.execution_context(plan, row, row)
        path = put('context.json', c.context)
        monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
        return c.context
    c.select = select; c.select('D31')
    def observe():
        judge = getattr(metrics, 'accept_' + c.row.lower() + '_digital', None)
        assert callable(judge), 'digital metric consumer absent'
        result = judge(project, c.context, {'native_image': 'SOURCE_ONLY_DOUBLE', 'verdict': 'PASS'})
        put('SOURCE_ONLY_OBSERVATION.json', result)
        return result
    c.observe = observe
    def bounds(relative, body):
        source = put('input/bounds-source.txt', 'SOURCE_ONLY_INDEPENDENT_REQUIREMENTS_METHOD_DOUBLE\n')
        sentinel = put(relative, 'SOURCE_ONLY_INVALID_REQUIREMENT_SENTINEL\n')
        auth = {'status': 'SOURCE_ONLY_API_DOUBLE', 'path': relative, 'sha256': sha(sentinel),
            'source': {'path': str(source.relative_to(project)), 'sha256': sha(source)}}
        c.bodies[relative] = (auth, body)
    c.bounds = bounds
    def document(project, relative, **kwargs):
        return c.bodies[relative] if relative in c.bodies else REAL_DOCUMENT(project, relative, **kwargs)
    monkeypatch.setattr(metrics, '_approved_document', document)
    c.bounds('requirements/base_20/floorplan_boundary_pin_feasibility.json', {
        'limits': {'die_width_um': {'min': 100, 'max': 100}, 'die_height_um': {'min': 100, 'max': 100},
            **{k: {'max': 0} for k in ['macro_boundary_errors', 'unplaced_macros', 'pin_boundary_errors', 'unplaced_pins', 'pin_population_errors']}},
        'units': {'die_width_um': 'um', 'die_height_um': 'um', **{k: 'count' for k in ['macro_boundary_errors', 'unplaced_macros', 'pin_boundary_errors', 'unplaced_pins', 'pin_population_errors']}}})
    c.bounds('requirements/base_21/pad_io_esd_pg_inventory.json', {'required_items': [
        {'kind': kind, 'instance': inst, 'master': master, **({'pin': 'VDD' if kind == 'power' else 'VSS', 'net': 'VDD' if kind == 'power' else 'VSS'} if kind in ('power', 'ground') else {})} for kind, inst, master in [
            ('io', 'io0', 'PAD0'), ('io', 'io1', 'PAD0'), ('esd', 'esd', 'ESD0'), ('power', 'pv', 'PAD0'), ('ground', 'pg', 'PAD0')]]})
    c.bounds('requirements/base_21/pad_access_spacing.json', {'limits': {
        'min_pad_spacing_um': {'min': 5}, 'min_pin_access_spacing_um': {'min': 5}, 'pin_access_errors': {'max': 0}},
        'units': {'min_pad_spacing_um': 'um', 'min_pin_access_spacing_um': 'um', 'pin_access_errors': 'count'}})
    # Coherent new native population, distinct from tampering a consumed file.
    def geometry(**kwargs):
        c.definition.write_text(neutral_def(**kwargs))
        (project / producer.PNR / 'floorplan.def').write_text(c.definition.read_text())
        c.handoff['views']['def'].update(source_sha256=sha(c.definition), dest_sha256=sha(c.definition))
        c.handoff_path.write_text(json.dumps(c.handoff))
        for rec in c.receipts.values():
            if str(c.definition) in rec['input']['state_files']:
                rec['input']['state_files'][str(c.definition)] = sha(c.definition)
        c.publish()
    c.geometry = geometry
    def pg(value):
        state = c.folders[c.steps[-1]] / 'state_out.json'
        body = json.loads(state.read_text());body['metrics']['design__power_grid_violation__count'] = value
        body['metrics']['design__power_grid_violation__count__net:VDD'] = value
        state.write_text(json.dumps(body))
        c.receipts[str(state.parent)]['sha256']['state_out.json'] = sha(state)
        c.handoff['state_sha256'] = sha(state);c.handoff_path.write_text(json.dumps(c.handoff));c.publish()
    c.pg = pg
    return c


def test_floorplan_measures_def_not_cell_area_and_reuses_config_snapshot(digital):
    result = digital.observe()
    assert result['metric_status'] == 'PASS', json.dumps(result, indent=2)
    assert result['status'] == result['qualification'] == 'NOT_MEASURED'
    chain = json.loads((digital.project / 'reports/phase3/execution-backend-15.json').read_text())
    assert all(ref['config_sha256'] == sha(digital.configs[ref['step']]) for ref in chain['states'])
    values = {m['field']: m['measurement']['value'] for o in result['obligations'] for m in o.get('measurements', [])}
    assert values['die_width_um'] == values['die_height_um'] == 100


@pytest.mark.parametrize('bad', ['overlap', 'outside'])
def test_real_floorplan_geometry_violation_blocks(digital, bad):
    digital.geometry(**{bad: True})
    result = digital.observe()
    assert result['metric_status'] == result['status'] == 'FAIL', json.dumps(result, indent=2)


def test_overlap_survives_late_missing_requirements(digital):
    digital.geometry(overlap=True)
    digital.bodies.clear()
    result = digital.observe()
    assert result['status'] == 'FAIL', json.dumps(result, indent=2)
    assert any(o['status'] == 'NOT_MEASURED' for o in result['obligations'])


@pytest.mark.parametrize('damage', ['netlist', 'def', 'odb', 'library', 'config', 'source_population', 'requirements', 'foreign', 'truncated', 'missing_authority'])
def test_wrong_missing_or_stale_floorplan_source_refuses(digital, damage):
    if damage in ('netlist', 'def', 'odb', 'library'):
        p = {'netlist': digital.nl, 'def': digital.definition, 'odb': digital.odb, 'library': digital.lef}[damage]
        p.write_text(p.read_text() + '\nCHANGED\n')
    elif damage == 'config':
        p = digital.project / 'reports/phase3/floorplan-native-configs/01-Yosys.JsonHeader.json'
        p.write_text('{}')
    elif damage == 'source_population':
        digital.receipts[str(digital.folders['OpenROAD.Floorplan'])]['input']['state_files'] = {}
    elif damage == 'requirements':
        digital.put('input/bounds-source.txt', 'CHANGED SOURCE')
    elif damage == 'missing_authority':
        digital.bodies.clear()
    elif damage == 'foreign':
        p = digital.project / 'reports/phase3/execution-backend-15.json'
        body = json.loads(p.read_text());body['states'][0]['state'] = str(digital.initial);p.write_text(json.dumps(body))
    elif damage == 'truncated':
        digital.geometry();digital.definition.write_text(neutral_def().replace('COMPONENTS 7', 'COMPONENTS 8'))
        # Exercise actual strict semantic parser independently of stale hash refusal.
        with pytest.raises(Exception, match='DIGITAL_DEF_POPULATION_INVALID'):
            metrics._digital_def_geometry(digital.definition.read_text(), [digital.lef])
    result = digital.observe()
    assert result['status'] == result['metric_status'] == 'NOT_MEASURED', json.dumps(result, indent=2)


def test_real_receipt_and_requirement_apis_reject_disk_sentinels(digital, monkeypatch):
    monkeypatch.setattr(ll, 'validate_step_receipt', REAL_RECEIPT)
    assert digital.observe()['metric_status'] == 'NOT_MEASURED'
    monkeypatch.setattr(metrics, '_approved_document', REAL_DOCUMENT)
    with pytest.raises(metrics.MetricRefusal):
        REAL_DOCUMENT(digital.project, 'requirements/base_20/floorplan_boundary_pin_feasibility.json', authority='requirements_owner', schema=metrics.AUTHORITY_SCHEMA)


def test_pad_inventory_physical_grid_and_access_are_read_together(digital):
    digital.select('D32')
    result = digital.observe()
    assert result['metric_status'] == 'PASS', json.dumps(result, indent=2)
    assert result['status'] == 'NOT_MEASURED'
    assert result['obligations'][1]['measurement']['value'] == 0


@pytest.mark.parametrize('bad', ['missing_esd', 'pg_errors', 'spacing'])
def test_real_pad_population_connectivity_or_spacing_violation_blocks(digital, bad):
    digital.select('D32')
    if bad == 'missing_esd':
        digital.geometry(missing=True)
    elif bad == 'pg_errors':
        digital.pg(2)
    else:
        digital.bodies['requirements/base_21/pad_access_spacing.json'][1]['limits']['min_pad_spacing_um']['min'] = 11
    result = digital.observe()
    assert result['status'] == 'FAIL', json.dumps(result, indent=2)


@pytest.mark.parametrize('bad', ['psm_absent', 'net_absent', 'policy_absent', 'unapproved_zero'])
def test_pad_zero_without_native_physical_and_independent_authority_is_nm(digital, bad):
    digital.select('D32')
    if bad == 'psm_absent':
        p = digital.folders['OpenROAD.GeneratePDN'] / 'invocation.log';p.write_text('PG_NET_OWNERSHIP_AUDIT: total=100 NULL=0\n')
        digital.receipts[str(p.parent)]['sha256']['invocation.log'] = sha(p)
    elif bad == 'net_absent':
        (digital.folders['OpenROAD.GeneratePDN'] / 'VSS-grid-errors.rpt').unlink()
    elif bad == 'unapproved_zero':
        digital.bodies.pop('requirements/base_21/pad_access_spacing.json')
    else:
        digital.bodies.pop('requirements/base_21/pad_io_esd_pg_inventory.json')
    assert digital.observe()['status'] == 'NOT_MEASURED'


def test_native_pg_failure_survives_later_missing_spacing(digital):
    digital.select('D32');digital.pg(2)
    digital.bodies.pop('requirements/base_21/pad_access_spacing.json')
    assert digital.observe()['status'] == 'FAIL'


@pytest.fixture
def placement(digital, monkeypatch):
    import placement_legality_check as legality
    c = digital
    c.select('D35');c.netlist = c.nl
    c.model = c.put('input/library.lib', 'SOURCE_ONLY_LIBERTY_SENTINEL')
    steps = ['OpenROAD.GlobalPlacement', 'OpenROAD.RepairDesignPostGPL',
             'Vibeic.PostGPLFanoutClosure', 'OpenROAD.DetailedPlacement']
    states = [];previous = c.initial
    for index, step in enumerate(steps, 1):
        folder = c.project / 'phase3/librelane/execution-backend-17' / (f'{index:02d}-' + step.lower().replace('.', '-'))
        cfg = c.put('phase3/librelane/execution-backend-17-config/' + step + '.cell-policy.json',
            {'meta': {'step': step}, 'LIB': str(c.model)})
        state = c.put(folder / 'state_out.json', {'nl': str(c.nl), 'def': str(c.definition), 'odb': str(c.odb),
            'metrics': {'timing__setup__ws': 1.0}})
        log = c.put(folder / 'invocation.log', 'SOURCE_ONLY_LOG_SENTINEL')
        c.put(folder / 'vibeic_receipt.json', 'SOURCE_ONLY_INVALID_NATIVE_RECEIPT')
        c.put(folder / 'pdk_root.json', {'mounts_under_it': []})
        fp = {'image': 'SOURCE_ONLY_DOUBLE', 'step': step, 'state': sha(previous), 'config': sha(cfg),
            'state_files': {str(p): sha(p) for p in ll._walk_paths({k:v for k,v in json.loads(previous.read_text()).items() if k != 'metrics'})},
            'config_files': {str(c.model): sha(c.model)}}
        if step.startswith(ll.PLUGIN_STEP_PREFIX):fp['plugin'] = ll._plugin_digests(step)
        c.receipts[str(folder)] = {'input': fp, 'sha256': {'state_out.json': sha(state), 'invocation.log': sha(log)}}
        states.append({'step': step, 'state': str(state), 'sha256': sha(state),
            'config': str(cfg.relative_to(c.project)), 'config_sha256': sha(cfg)})
        previous = state
    c.chain = {'ordered_steps': steps, 'initial_state': str(c.initial), 'initial_sha256': sha(c.initial), 'states': states}
    c.chain_path = c.put('reports/phase3/execution-backend-17.json', c.chain)
    c.handoff = {'state': str(previous), 'state_sha256': sha(previous), 'views': {}}
    for view, src, name in [('def', c.definition, 'placed.def'), ('odb', c.odb, 'librelane_placed.odb')]:
        dest = c.put('phase3/stage3/pnr/' + name, src.read_text())
        c.handoff['views'][view] = {'source': str(src), 'source_sha256': sha(src), 'dest': str(dest), 'dest_sha256': sha(dest)}
    c.put('reports/phase3/librelane_placement_handoff.json', c.handoff)
    monkeypatch.setattr(legality, '_librelane_placement', lambda project: {
        'bound': True, 'detailed_placement': 'COMPLETED', 'receipt': 'SOURCE_ONLY_DOUBLE',
        'detailed_placement_dir': str(previous.parent)})
    c.bounds('requirements/base_23/pre_cts_setup_drv_targets.json', {
        'limits': {'timing__setup__ws': {'min': 0}}, 'units': {'timing__setup__ws': 'ns'}})
    c.bounds('requirements/base_23/congestion_targets.json', {
        'limits': {'route.congestion.weighted': {'max': 1.5}}, 'units': {'route.congestion.weighted': '1'}})
    c.log = Path(states[0]['state']).parent / 'invocation.log'
    def transcript(text):
        c.log.write_text(text);c.receipts[str(c.log.parent)]['sha256']['invocation.log'] = sha(c.log)
    c.transcript = transcript
    transcript('[INFO GPL-0040] Routability pass 1: weighted congestion 1.2500 (target 1.0100), 1 of 10 actionable tiles overflowed (10.0%).\n')
    def observe():
        result = metrics.accept_d35(c.project, c.context, {'native_image': 'SOURCE_ONLY_DOUBLE', 'verdict': 'PASS'})
        c.put('NEW_D35_OBSERVATION.json', result)
        return result
    c.observe = observe
    return c


def test_placement_actual_derived_config_and_normal_gpl_field(placement):
    result = placement.observe()
    assert result['metric_status'] == 'PASS', json.dumps(result, indent=2)
    assert result['obligations'][2]['measurements'][0]['measurement']['value'] == 1.25
    assert result['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('bad', ['bound', 'unit', 'absent', 'config', 'population', 'library', 'setup_corner'])
def test_placement_current_selected_source_bounds_and_units(placement, monkeypatch, bad):
    if bad == 'bound':
        placement.transcript('[INFO GPL-0040] Routability pass 1: weighted congestion 2.0000 (target 1.0100), 2 of 10 actionable tiles overflowed (20.0%).\n')
    elif bad == 'absent':
        placement.transcript('[INFO] routability not executed\n')
    elif bad == 'unit':
        document = metrics._approved_document
        def wrong(project, relative, **kw):
            auth, body = document(project, relative, **kw)
            if 'congestion_targets' in relative:body['units']['route.congestion.weighted'] = '%'
            return auth, body
        monkeypatch.setattr(metrics, '_approved_document', wrong)
    elif bad == 'config':
        (placement.project / placement.chain['states'][0]['config']).write_text('{}')
    elif bad == 'population':
        placement.receipts[str(placement.log.parent)]['input']['state_files'] = {}
    elif bad == 'library':
        placement.model.write_text('CHANGED LIBERTY')
    else:
        document = metrics._approved_document
        def corner(project, relative, **kw):
            auth, body = document(project, relative, **kw)
            if 'pre_cts_setup' in relative:
                body = {'limits': {'timing__setup__ws__corner:slow': {'min': 0}}, 'units': {'timing__setup__ws__corner:slow': 'ns'}}
            return auth, body
        monkeypatch.setattr(metrics, '_approved_document', corner)
    result = placement.observe()
    assert result['metric_status'] == ('FAIL' if bad == 'bound' else 'NOT_MEASURED'), json.dumps(result, indent=2)


def test_gpl_revert_selects_native_pass_and_never_uses_grt_stage():
    parser = getattr(metrics, '_d35_selected_congestion', None)
    assert callable(parser)
    text = ('[INFO GPL-0040] Routability pass 1: weighted congestion 1.2500 (target 1.0100), 1 of 10 actionable tiles overflowed (10.0%).\n'
            '[INFO GPL-0040] Routability pass 2: weighted congestion 2.0000 (target 1.0100), 2 of 10 actionable tiles overflowed (20.0%).\n'
            '[INFO GPL-0055] Reverting inflation and target density to the pass with the minimum observed routing congestion (1.2500), target density 0.7000.\n')
    result = parser(text)
    assert result['route.congestion.weighted']['value'] == 1.25
    assert result['route.congestion.overflowed_tiles.count']['value'] == 1
    assert parser('[INFO GRT-0096] Final congestion report\n') == {}


@pytest.mark.parametrize('row', ['D31', 'D32'])
def test_digital_metric_propagates_into_existing_producer_result(digital, row):
    digital.select(row)
    helper = getattr(producer, '_digital_floorplan_metric_result', None)
    assert callable(helper)
    result = helper(digital.project, {'image_id': 'SOURCE_ONLY_DOUBLE'}, {'verdict': 'PASS'}, row)
    assert result['metric_acceptance_status'] == 'PASS', json.dumps(result, indent=2)
    assert result['default_row_status'] == 'NOT_MEASURED'
    digital.geometry(overlap=True) if row == 'D31' else digital.pg(1)
    result = helper(digital.project, {'image_id': 'SOURCE_ONLY_DOUBLE'}, {'verdict': 'PASS'}, row)
    assert result['verdict'] == 'FAIL', json.dumps(result, indent=2)


@pytest.fixture(params=['D31', 'D32', 'D35'])
def scene(request, monkeypatch):
    row = request.param
    c = request.getfixturevalue('placement' if row == 'D35' else 'digital')
    plan, context, _ = windows._window_fixture(c.project, monkeypatch, row, row)
    c.context = context;c.row = row
    path = c.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(c.project, context)))
    native = {'D31': '15', 'D32': '15.5ic', 'D35': '17'}[row]
    for spec in worker.ROWS[native]['canonical_row']['required_outputs']:
        choices = spec.split(' OR ')
        if not any(any(c.project.glob(choice)) for choice in choices):
            assert '*' not in choices[0]
            c.put(choices[0], 'SOURCE_ONLY_GATE_OUTPUT_SENTINEL')
    def produced(project, params):
        if row != 'D35':
            return producer._digital_floorplan_metric_result(project, params, {'verdict': 'PASS'}, row)
        measured = c.observe()
        return {'verdict': 'FAIL' if measured['metric_status'] == 'FAIL' else 'PASS',
            'metric_acceptance': measured, 'metric_acceptance_status': measured['metric_status'],
            'default_row_status': measured['status']}
    monkeypatch.setattr(producer, 'produce_pnr', produced)
    monkeypatch.setattr(producer, '_native_current_step_output_snapshot', lambda *a: {})
    monkeypatch.setattr(producer, '_native_current_step_producer', lambda *a: 'SOURCE_ONLY_PRODUCER_DOUBLE')
    monkeypatch.setattr(producer, '_native_current_step_receipt', lambda *a: {'scope': 'SOURCE_ONLY_PRODUCER_DOUBLE'})
    monkeypatch.setattr(producer, '_current_step_producer_authority', lambda *a, **kw: (True, 'SOURCE_ONLY', 'PASS'))
    monkeypatch.setattr(producer, '_runner_context', lambda: SimpleNamespace(_DECLARED_SIGNOFF_GATES=[], _PRESTREAM_GATES=[]))
    inputs = {str(path.relative_to(c.project)): sha(path)}
    attempt = versions.begin_step(c.project, native, inputs=inputs)
    produced = producer.produce(c.project, {'step_id': native, 'top': 'neutral', 'image_id': 'SOURCE_ONLY_DOUBLE', 'stop_on_producer_failure': True})
    assert produced['metric_acceptance']['status'] == 'PASS', json.dumps(produced, indent=2)
    assert produced['canonical_receipts'][0]['metric_acceptance'] == produced['metric_acceptance']
    monkeypatch.setattr(worker, '_current_step_producer_authority', lambda *a, **kw: (True, 'SOURCE_ONLY', 'PASS'))
    monkeypatch.setattr(worker, 'evaluate', lambda *a: {'status': 'PASS', 'step': {'id': native, 'status': 'PASS'}, 'ledger': []})
    backend = worker.execute_current_step(c.project, step_id=native, producer=produced)
    assert backend['verdict'] == 'PASS', json.dumps(backend, indent=2)
    receipt = c.put('reports/phase3/default_steps/' + native + '/backend_result.json', backend)
    version = versions.finish_step(c.project, attempt, verdict='PASS', result=backend, canonical_pass=True)
    selected = {r['id'] for r in plan['rows']}
    dependencies = (set(context['resolved_row']['acceptance_deps']) | {d['step'] for d in context['resolved_row']['data_deps']}) & selected
    for dep in dependencies:
        original = flow109.execution_context(plan, dep, dep)
        c.put('reports/flow109/requests/' + original['context_sha256'] + '.json', original)
        c.put('reports/flow109/default_rows/' + dep + '.json', {'step_id': dep, 'default_row_status': 'PASS', 'completed': True,
            'context_sha256': original['context_sha256'], 'scope': 'SOURCE_ONLY_DEPENDENCY_FIXTURE'})
    report = {'bounded': True, 'steps': [{'extras': {'canonical_steps': [{'status': 'PASS', 'detail': 'SOURCE_ONLY',
        'extras': {'step_id': native, 'output_version': version['folder']}}]}}]}
    def consume():
        result = flow109.finish_native_window(c.project, report)
        c.put('SOURCE_ONLY_FINALIZER_OBSERVATION.json', result)
        return result
    def fail():
        if row == 'D31':c.geometry(overlap=True)
        elif row == 'D32':c.pg(2)
        else:c.transcript('[INFO GPL-0040] Routability pass 1: weighted congestion 2.0000 (target 1.0100), 2 of 10 actionable tiles overflowed (20.0%).\n')
    return SimpleNamespace(case=c, project=c.project, consume=consume, fail=fail, dependencies=dependencies, receipt=receipt)


def test_finalizer_reads_owner_again_and_reuses_valid_unit_admission(scene):
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', json.dumps(result, indent=2)
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED' and result['delivery_accepted'] is False


def test_finalizer_missing_qualification_cannot_inherit_prior_pass(scene):
    (scene.project / 'qualifications.json').unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', json.dumps(result, indent=2)
    assert result['components'][0]['metric_acceptance']['metric_status'] == 'PASS'


@pytest.mark.parametrize('late', ['admission', 'dependency', 'version'])
def test_finalizer_fresh_actual_failure_survives_late_missing_input(scene, late):
    scene.fail()
    if late == 'admission':(scene.project / 'qualifications.json').unlink()
    elif late == 'dependency':(scene.project / 'reports/flow109/default_rows' / (sorted(scene.dependencies)[0] + '.json')).unlink()
    else:
        for path in versions._versions_root(scene.project).glob('**/outputs.json'):path.unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', json.dumps(result, indent=2)


def test_finalizer_foreign_receipt_cannot_inherit_prior_pass(scene):
    body = json.loads(scene.receipt.read_text());body['source_sha'] = 'FOREIGN'
    scene.receipt.write_text(json.dumps(body))
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', json.dumps(result, indent=2)


def test_psm_clean_core_cannot_offset_disconnected_supply_pad(digital):
    digital.select('D32')
    # A coherently produced DEF, not a stale-file refusal. Core PSM logs and
    # counts remain clean; the independent required IO supply is disconnected.
    digital.definition.write_text(neutral_def().replace('( pv VDD )', '( io0 VDD )'))
    (digital.project / producer.PNR / 'floorplan.def').write_text(digital.definition.read_text())
    digital.handoff['views']['def'].update(source_sha256=sha(digital.definition), dest_sha256=sha(digital.definition))
    digital.handoff_path.write_text(json.dumps(digital.handoff))
    for rec in digital.receipts.values():
        if str(digital.definition) in rec['input']['state_files']:
            rec['input']['state_files'][str(digital.definition)] = sha(digital.definition)
    digital.publish()
    result = digital.observe()
    assert result['status'] == 'FAIL', json.dumps(result, indent=2)
    assert result['obligations'][0]['status'] == 'FAIL'
    assert result['obligations'][1]['status'] == 'PASS'


def test_native_pg_positive_survives_missing_physical_report(digital):
    digital.select('D32');digital.pg(2)
    digital.receipts[str(digital.folders['OpenROAD.GeneratePDN'])]['sha256'].pop('VSS-grid-errors.rpt')
    (digital.folders['OpenROAD.GeneratePDN'] / 'VSS-grid-errors.rpt').unlink()
    assert digital.observe()['status'] == 'FAIL'


def test_real_normal_gpl_bound_failure_survives_later_missing_authority(placement):
    # The first native setup obligation is a measured failure; congestion
    # authority then disappears. No invented pre-CTS hold metric is used.
    placement.bodies['requirements/base_23/pre_cts_setup_drv_targets.json'][1]['limits']['timing__setup__ws']['min'] = 2
    placement.bodies.pop('requirements/base_23/congestion_targets.json')
    result = placement.observe()
    assert result['status'] == 'FAIL', json.dumps(result, indent=2)
    assert result['obligations'][2]['status'] == 'NOT_MEASURED'


def test_unbound_late_added_grid_report_cannot_certify_zero(digital):
    digital.select('D32')
    digital.receipts[str(digital.folders['OpenROAD.GeneratePDN'])]['sha256'].pop('VSS-grid-errors.rpt')
    assert digital.observe()['status'] == 'NOT_MEASURED'
