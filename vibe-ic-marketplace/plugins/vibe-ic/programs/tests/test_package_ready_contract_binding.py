"""Neutral producer-observation controls, never native/platform/IC evidence.

Only the already-observed native boundary is a fixture. Context, source/input
identity, provider policy, normal INPUT authority readers and metric/completion
consumers run unchanged. No native EDA producer is launched.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import flow109
import flow109_package_ready as d75
import flow109_metric_acceptance as metrics

if os.environ.get('PKG103_BASE_SOURCE'):
    spec = importlib.util.spec_from_file_location('d75_base_control',
        Path(os.environ['PKG103_BASE_SOURCE']) / 'flow109_package_ready.py')
    d75 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d75)

NAMES = ['pad_bump_package_layout_agreement', 'escape_bond_feasibility',
         'package_feedback_unresolved', 'test_access_ready', 'package_electrical_feedback_coverage']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, sort_keys=True))


def authority(project, name, payload, *, adopted=False):
    # Independent design/requirements input, not an observation or a producer self-list.
    source = project / 'input' / 'package_contracts' / (name + '.json')
    write(source, {name: payload})
    reference = {'path': source.relative_to(project).as_posix(),
                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    body = {'schema': 'vibeic.flow109.adopted-reference.v1' if adopted else metrics.AUTHORITY_SCHEMA,
            'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
                         'source_reference': reference}, **payload}
    # Absence source points to this input; remove its own hash from the input to
    # avoid a recursive hash. Keep reasoned absence in a separate normal INPUT.
    if payload.get('required_items') == []:
        decision = project / 'input/package_contracts/absence.json'
        if not decision.exists():
            write(decision, {'reason': 'Neutral source explicitly selects no DFT or specific package model.'})
        body['validated_absence'] = {'status': 'VALIDATED', 'authority': 'requirements_owner',
            'reason': 'Neutral source explicitly selects no DFT or specific package model.',
            'source_reference': {'path': decision.relative_to(project).as_posix(),
                                 'sha256': hashlib.sha256(decision.read_bytes()).hexdigest()}}
        write(source, {name: {k: v for k, v in body.items() if k not in ('schema', 'approval')}})
        body['approval']['source_reference']['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = project / ('adopted' if adopted else 'requirements') / 'package_ready' / (name + '.json')
    write(path, body)
    return path


def rebind(project, component):
    component['inputs'] = [d75._record(project, p) for p in sorted(project.rglob('*'))
                           if p.is_file() and not p.is_relative_to(project / 'requirements')
                           and not p.is_relative_to(project / 'adopted')
                           and not p.is_relative_to(project / 'input/package_contracts')]


def context(project, **features):
    registry = flow109.load_registry()
    selected = dict(next(p['features'] for p in registry['reference_profiles']
                         if p['name'] == 'Small digital IC without DFT'))
    selected.update(package_model_required=False, requires_dft=False, requires_scan=False, requires_perc=False)
    selected.update(features)
    ctx = flow109.execution_context(flow109.resolve_plan(selected), 'D75', 'D75')
    write(project / d75.CONTEXT_REQUESTS / (ctx['context_sha256'] + '.json'), ctx)
    return ctx


@pytest.fixture
def sample(tmp_path):
    project = tmp_path / 'neutral-observations'
    ctx = context(project)
    write(project / d75.DECLARATION, {'fixture': 'neutral owner-selected bare DIE'})
    write(project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
          {'layer': 'L20', 'applicability': 'NOT_APPLICABLE', 'fields': {},
           'reason': 'Neutral design uses functional pad access; no DFT.'})
    write(project / d75.IO_REPORT, {'program': 'io_pad_chip_top_gen', 'verdict': 'WROTE',
        'chip_top_module': 'neutral_top', 'io_library_lefs': ['input/pdk/io.lef']})
    write(project / 'input/pdk/io.lef', '''MACRO NEUTRAL_PAD
  CLASS PAD ;
  SIZE 10 BY 10 ;
  PIN TERMINAL
    PORT
      LAYER RouteX ;
      RECT 0 0 10 10 ;
    END
  END TERMINAL
END NEUTRAL_PAD
''')
    write(project / 'input/pdk/tech.tlef', '''UNITS
 DATABASE MICRONS 1000 ;
END UNITS
LAYER RouteX
 TYPE ROUTING ;
 WIDTH 1 ;
END RouteX
''')
    write(project / d75.PAD_DEF, '''VERSION 5.8 ;
DESIGN neutral_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
COMPONENTS 1 ;
- pad_signal NEUTRAL_PAD + PLACED ( 10000 10000 ) N ;
END COMPONENTS
PINS 1 ;
- signal + NET signal + DIRECTION INPUT + USE SIGNAL
 + LAYER RouteX ( 0 0 ) ( 10000 10000 )
 + PLACED ( 10000 10000 ) N ;
END PINS
NETS 1 ;
- signal ( PIN signal ) ( pad_signal TERMINAL ) ;
END NETS
END DESIGN
''')
    write(project / 'phase3/stage4/gds/final.gds', 'NEUTRAL OBSERVED LAYOUT BOUNDARY FIXTURE; not a native GDS result')
    write(project / 'input/pdk/layers.lyp', '<neutral-opening-source/>')
    write(project / d75.PROVIDER_TARGET, {'provider': 'neutral_requirements_owner',
        'technical_target': {'dimensions_um': [100, 100]},
        'bond_pad_edge_distance': {'max_distance_um': 90}})
    layout = d75._record(project, Path('phase3/stage4/gds/final.gds'))
    # Adopted reference authored from the normal design requirements, before
    # producing observations. No copying a report/value from the consumer.
    row = {'pin': 'signal', 'net': 'signal', 'instance': 'pad_signal', 'terminal': 'TERMINAL',
        'master': 'NEUTRAL_PAD', 'orient': 'N', 'pin_layer': 'RouteX',
        'pin_rect': [10000, 10000, 20000, 20000], 'terminal_rect': [10000, 10000, 20000, 20000],
        'overlap': [10000, 10000, 20000, 20000], 'verdict': 'CONNECTED',
        'reason': "the pin and the pad terminal share 10000x10000 of RouteX, at or above that layer's minimum width 1000"}
    reference = {'top': 'neutral_top', 'units': 1000, 'layout': layout,
        'bterms': {'signal': {'net': 'signal', 'layer': 'RouteX', 'rect': [10000, 10000, 20000, 20000],
                              'placement': [10000, 10000, 'N']}},
        'pad_instances': [{'instance': 'pad_signal', 'master': 'NEUTRAL_PAD', 'status': 'PLACED',
                           'x': 10000, 'y': 10000, 'orient': 'N'}],
        'pad_bterms': [{k: v for k, v in row.items() if k not in ('verdict', 'reason')}]}
    reference_identity = {'producer': 'independent_layout_authority', 'checker': 'requirements_owner',
        'tool_execution': 'independent_normal_INPUT', 'consumed_inputs': {'layout': layout},
        'requirements': 'neutral_die_interface', 'configuration': 'neutral_contract'}
    authority(project, NAMES[0], {'reference': reference, 'reference_identity': reference_identity}, adopted=True)
    authority(project, NAMES[1], {'rule_source': d75._record(project, d75.PROVIDER_TARGET),
        'rule_field': 'bond_pad_edge_distance.max_distance_um', 'required_opening_count': 1, 'required_pad_masters': ['NEUTRAL_PAD'],
        'limits': {side: {'min': 0, 'max': 90} for side in ('left', 'bottom', 'right', 'top')},
        'units': {side: 'um' for side in ('left', 'bottom', 'right', 'top')}})
    required = ['tapeout_declaration_check', 'declared_delivery_form', 'pad_side_constraint_check',
                'pad_bterm_coincidence_check', 'provider_bond_pad_edge', 'test_access_applicability',
                'perc_signoff_check', 'package_electrical_feedback']
    authority(project, NAMES[2], {'required_items': [{'check': name} for name in required]})
    authority(project, NAMES[3], {'required_items': []})
    authority(project, NAMES[4], {'required_items': [], 'when': {'package_model_required': False}})
    rc, pads = d75.pad_bterm_coincidence_check.run((project / d75.PAD_DEF).read_text(),
        (project / 'input/pdk/tech.tlef').read_text(), [project / 'input/pdk/io.lef'])
    assert rc == 0 and pads['nets'] == [row]
    def release(path):
        rec = d75._record(project, Path(path))
        return {'path': str((project / rec['path']).resolve()), 'sha256': rec['sha256']}
    edge = {'verdict': 'PASS', 'input': release(layout['path']), 'profile': release(d75.PROVIDER_TARGET),
        'top': 'neutral_top', 'master_sources': [release('input/pdk/io.lef')],
        'opening_layer': {'source': release('input/pdk/layers.lyp')},
        'pad_masters': ['NEUTRAL_PAD'], 'opening_count': 1, 'opening_bbox_um': [10, 10, 20, 20],
        'distances_um': {'left': 10, 'bottom': 10, 'right': 80, 'top': 80},
        'declared_max_distance_um': 90, 'tool_version': 'NEUTRAL_OBSERVATION_FIXTURE'}
    checks = [d75._check(name, 'PASS', {'fixture': 'neutral_observed_component'}) for name in required[:3]]
    checks += [d75._check('pad_bterm_coincidence_check', 'PASS', pads),
        d75._check('provider_bond_pad_edge', 'PASS', edge),
        d75._check('test_access_applicability', 'NOT_APPLICABLE', d75.dft_atpg_coverage_check.l20_dft_applicability(project)),
        d75._check('perc_signoff_check', 'NOT_APPLICABLE', 'requires_perc is false'),
        d75._check('package_electrical_feedback', 'NOT_APPLICABLE', 'package_model_required is false')]
    component = {'schema': d75.SCHEMA, 'step_id': 'D75', 'program': 'flow109_package_ready',
        'context_sha256': ctx['context_sha256'], 'component_status': 'PASS', 'checks': checks,
        'reason': 'NEUTRAL_PRODUCER_OBSERVATIONS_NOT_NATIVE_QUALIFICATION',
        'consumer_load_identity': d75.operation_sources(),
        'provider_identity': d75._provider_identity(project, edge), 'inputs': []}
    rebind(project, component)
    d75.validate(project, component)
    return project, ctx, component


def consume(sample):
    result = d75.consume_default_row_completion(*sample)
    # Retain the actual consumer result and original observation for the lander.
    with (sample[0].parent / 'D75-consumer-observations.jsonl').open('a') as stream:
        stream.write(json.dumps({'scope': 'NEUTRAL_SOURCE_CONTROL_ONLY',
            'original_component': sample[2], 'consumed': result}, sort_keys=True) + '\n')
    return result['metric_acceptance']


def item(result, name):
    return next(row for row in result['obligations'] if row['id'] == 'package_ready.' + name)


def check(sample, name):
    return next(row for row in sample[2]['checks'] if row['check'] == name)


def test_positive_bare_die(sample):
    result = consume(sample)
    states = {row['id']: row['status'] for row in result['obligations']}
    assert states == {'package_ready.' + name: ('PASS' if index < 3 else 'NOT_APPLICABLE')
                      for index, name in enumerate(NAMES)}
    assert result['metric_status'] == 'PASS'
    assert sample[1]['features']['package_interface'] is True
    assert result['status'] == 'PASS'
    assert result['qualification'] == 'NOT_CLAIMED'
    assert result['acceptance_scope'] == 'existing_native_component_only'
    completed = d75.consume_default_row_completion(*sample)
    assert completed['completed'] is True and completed['delivery_accepted'] is False
    assert completed['whole_flow_acceptance'] == 'NOT_MEASURED'


def _self_tapeout_absence(sample):
    project, _, component = sample
    (project / d75.PROVIDER_TARGET).unlink()
    decl = d75.declaration.blank_declaration()
    decl['answers']['deliverable'] = d75.declaration.DELIVERABLE_DIE
    decl[d75.declaration.PROVENANCE_KEY] = {'deliverable': {
        'answered_by': d75.declaration.ANSWERED_BY_OWNER_VALUE,
        'citation': 'Neutral owner explicitly selects an independent bare DIE.'}}
    own = copy.deepcopy(decl)
    own['operator_template'] = {'path': None, 'slot': None,
                               'absent_reason': 'Owner selected independent bare-die tapeout.'}
    write(project / d75.DECLARATION, decl)
    write(project / d75.DESIGN_ANSWERS, own)
    write(project / d75.OPERATOR_ANSWERS, own)
    write(project / d75.declaration.SELF_TAPEOUT_REL,
          d75.declaration.SELF_TAPEOUT_MARKER + '\n')
    owed, scope = d75._provider_scope(project, decl, [])
    assert owed is False
    check(sample, 'provider_bond_pad_edge').update(status='NOT_APPLICABLE', detail=scope)
    component['provider_identity'] = None
    reason = 'Owner-certified independent bare DIE needs no provider bond-pad limit.'
    absence = project / 'input/package_contracts/self_tapeout_absence.json'
    write(absence, {'reason': reason})
    payload = {'required_items': [], 'when': {'route': 'SELF_TAPEOUT', 'deliverable': 'DIE'},
        'validated_absence': {'status': 'VALIDATED', 'authority': 'requirements_owner',
            'reason': reason, 'source_reference': {
                'path': absence.relative_to(project).as_posix(),
                'sha256': hashlib.sha256(absence.read_bytes()).hexdigest()}}}
    source = project / 'input/package_contracts/escape_bond_feasibility.json'
    write(source, {NAMES[1]: payload})
    path = project / 'requirements/package_ready/escape_bond_feasibility.json'
    write(path, {'schema': metrics.AUTHORITY_SCHEMA, **payload,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner', 'approver': 'neutral-requirements-reviewer',
            'source_reference': {'path': source.relative_to(project).as_posix(),
                                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}})
    rebind(project, component)
    return path


def test_self_tapeout_escape_bond_accepts_approved_reasoned_absence(sample):
    path = _self_tapeout_absence(sample)
    result = item(consume(sample), NAMES[1])
    assert result['status'] == 'NOT_APPLICABLE'
    assert result['skip_reason'] == json.loads(path.read_text())['validated_absence']['reason']
    assert len(result['authority']['bound_inputs']) == 3


@pytest.mark.parametrize('damage,code', [
    ('missing', 'METRIC_AUTHORITY_ABSENT'),
    ('unapproved', 'METRIC_AUTHORITY_UNAPPROVED'),
    ('empty_reason', 'D75_REASONED_ABSENCE_REQUIRED'),
    ('different_reason', 'D75_REASONED_ABSENCE_REQUIRED'),
    ('stale_reason', 'METRIC_EMPTY_SET_UNVALIDATED'),
    ('wrong_when', 'D75_SELF_TAPEOUT_ABSENCE_UNPROVEN'),
    ('unbound_owner', 'D75_OBSERVATION_INPUT_UNBOUND'),
])
def test_self_tapeout_escape_bond_refuses_missing_or_unbound_authority(sample, damage, code):
    path = _self_tapeout_absence(sample)
    project = sample[0]
    body = json.loads(path.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'unbound_owner':
        sample[2]['inputs'] = [r for r in sample[2]['inputs']
                               if r['path'] != str(d75.DESIGN_ANSWERS)]
    elif damage == 'stale_reason':
        write(project / body['validated_absence']['source_reference']['path'],
              {'reason': 'Changed after approval.'})
    else:
        if damage == 'unapproved':
            body['approval']['status'] = 'PENDING'
        elif damage in ('empty_reason', 'different_reason'):
            body['validated_absence']['reason'] = '' if damage == 'empty_reason' else 'Different reason.'
        else:
            body['when']['deliverable'] = 'HARDMACRO'
        source = project / body['approval']['source_reference']['path']
        write(source, {NAMES[1]: {k: v for k, v in body.items() if k not in ('schema', 'approval')}})
        body['approval']['source_reference']['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        write(path, body)
    result = item(consume(sample), NAMES[1])
    assert result['status'] == 'NOT_MEASURED'
    assert code in (result.get('reason', '') + result.get('detail', ''))


@pytest.mark.parametrize('damage,code', [
    ('provider_present', 'D75_PROVIDER_IDENTITY_MISMATCH'),
    ('missing_marker', '[Errno 2]'),
    ('unattested', '[Errno 2]'),
    ('forged_detail', 'D75_PROVIDER_SCOPE_MISMATCH'),
])
def test_provider_na_without_current_self_tapeout_proof_is_refused(sample, damage, code):
    _self_tapeout_absence(sample)
    project = sample[0]
    if damage == 'provider_present':
        write(project / d75.PROVIDER_TARGET, {'provider': 'neutral_selected_provider'})
    elif damage == 'missing_marker':
        (project / d75.declaration.SELF_TAPEOUT_REL).unlink()
    elif damage == 'unattested':
        path = project / d75.DESIGN_ANSWERS
        doc = json.loads(path.read_text())
        doc[d75.declaration.PROVENANCE_KEY] = {}
        write(path, doc)
    else:
        check(sample, 'provider_bond_pad_edge')['detail']['owner_self_tapeout'] = False
    rebind(project, sample[2])
    result = item(consume(sample), NAMES[1])
    assert result['status'] == 'NOT_MEASURED'
    assert code in result['reason']


def test_provider_pass_escape_bond_retains_all_four_declared_bounds(sample):
    result = item(consume(sample), NAMES[1])
    assert result['status'] == 'PASS'
    assert {r['side'] for r in result['comparisons']} == {'left', 'bottom', 'right', 'top'}
    assert all(r['status'] == 'PASS' for r in result['comparisons'])


def test_wildcard_connectivity_keeps_the_native_pad_identity(sample):
    project = sample[0]
    path = project / d75.PAD_DEF
    write(path, path.read_text().replace('( pad_signal TERMINAL )', '( * TERMINAL )'))
    rebind(project, sample[2])
    result = consume(sample)
    assert result['metric_status'] == 'PASS'
    assert item(result, NAMES[0])['status'] == 'PASS'


def test_adopted_reference_missing_pad(sample):
    p = sample[0]
    path = p / 'adopted/package_ready' / (NAMES[0] + '.json')
    body = json.loads(path.read_text())
    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
    payload['reference']['pad_bterms'] = []
    authority(p, NAMES[0], payload, adopted=True)
    result = consume(sample)
    assert item(result, NAMES[0])['status'] == 'FAIL'
    assert result['status'] == 'FAIL'


def test_actual_pad_population_removed(sample):
    check(sample, 'pad_bterm_coincidence_check')['detail']['nets'] = []
    result = consume(sample)
    assert item(result, NAMES[0])['status'] == 'NOT_MEASURED'
    assert 'D75_PAD_BTERM_POPULATION_INCOMPLETE' in result['reason']


@pytest.mark.parametrize('name', NAMES[:2], ids=['adopted', 'bounds'])
@pytest.mark.parametrize('damage', ['missing', 'tampered', 'foreign', 'unrelated_approved', 'self_observation'])
def test_authority_refuses(sample, name, damage):
    p = sample[0]
    path = p / ('adopted' if name == NAMES[0] else 'requirements') / 'package_ready' / (name + '.json')
    body = json.loads(path.read_text())
    if damage == 'missing':
        path.unlink()
    elif damage == 'tampered':
        write(p / body['approval']['source_reference']['path'], {'tampered': True})
    else:
        if damage == 'foreign':
            source = p.parent / 'foreign.json'
        elif damage == 'self_observation':
            source = p / 'reports/self_approved.json'
        else:
            source = p / 'input/unrelated.json'
        write(source, {'unrelated': 'APPROVED'})
        body['approval']['source_reference'] = {'path': str(source) if damage == 'foreign' else source.relative_to(p).as_posix(),
                                               'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        write(path, body)
    result = consume(sample)
    refused = item(result, name)
    assert refused['status'] == 'NOT_MEASURED'
    expected = {'missing': 'METRIC_AUTHORITY_ABSENT', 'tampered': 'METRIC_AUTHORITY_STALE',
                'foreign': 'METRIC_FOREIGN_INPUT', 'unrelated_approved': 'D75_APPROVED_FIELDS_DIFFER',
                'self_observation': 'D75_INDEPENDENT_INPUT_REQUIRED'}[damage]
    assert expected in str(refused), refused
    assert result['metric_status'] != 'PASS'


@pytest.mark.parametrize('damage', ['source', 'context', 'input', 'missing_component', 'duplicate_component', 'component_status'])
def test_original_binding_refuses(sample, damage):
    p, ctx, component = sample
    if damage == 'source':
        component['consumer_load_identity']['programs/provider_bond_pad_edge.py'] = '0' * 64
    elif damage == 'context':
        component['context_sha256'] = '0' * 64
    elif damage == 'input':
        write(p / d75.PAD_DEF, (p / d75.PAD_DEF).read_text() + '\n# stale\n')
    elif damage == 'missing_component':
        component['checks'].pop(0)
    elif damage == 'component_status':
        component['component_status'] = 'NOT_MEASURED'
    else:
        component['checks'].append(copy.deepcopy(component['checks'][0]))
    result = consume(sample)
    assert result['metric_status'] == 'NOT_MEASURED'
    assert all(row['status'] == 'NOT_MEASURED' for row in result['obligations'])


def test_empty_test_set_without_absence_refuses(sample):
    p = sample[0]
    path = p / 'requirements/package_ready/test_access_ready.json'
    body = json.loads(path.read_text()); body.pop('validated_absence'); write(path, body)
    assert item(consume(sample), NAMES[3])['reason'] == 'METRIC_EMPTY_SET_UNVALIDATED'


def test_missing_l20_is_not_no_dft(sample):
    p, _, component = sample
    (p / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').unlink()
    rebind(p, component)
    assert item(consume(sample), NAMES[3])['status'] == 'NOT_MEASURED'


def test_empty_test_set_conflicting_dft_intent_refuses(sample):
    p, _, component = sample
    write(p / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
          {'layer': 'L20', 'applicability': 'APPLICABLE', 'fields': {'scan_required': True}})
    rebind(p, component)
    assert item(consume(sample), NAMES[3])['status'] == 'NOT_MEASURED'


def test_required_test_access_uses_actual_coverage_and_pad_set(sample):
    p, _, component = sample
    ctx = context(p, requires_dft=True)
    component['context_sha256'] = ctx['context_sha256']
    write(p / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
          {'layer': 'L20', 'applicability': 'APPLICABLE', 'fields': {'scan_required': True}})
    write(p / 'reports/phase2/dft/coverage.json', {'coverage_pct': 100.0, 'target_pct': 100.0})
    required = [{'pin': 'signal', 'net': 'signal', 'instance': 'pad_signal', 'terminal': 'TERMINAL'}]
    authority(p, NAMES[3], {'required_items': required})
    access = check(sample, 'test_access_applicability')
    access.update(check='dft_atpg_coverage_check', status='PASS', detail=d75.dft_atpg_coverage_check.audit(p))
    rebind(p, component)
    changed = (p, ctx, component)
    assert item(consume(changed), NAMES[3])['status'] == 'PASS'
    required[0]['pin'] = 'missing_test_pin'
    authority(p, NAMES[3], {'required_items': required})
    assert item(consume(changed), NAMES[3])['status'] == 'FAIL'


def test_model_true_missing_feedback_refuses(sample):
    p, _, component = sample
    ctx = context(p, package_model_required=True)
    component['context_sha256'] = ctx['context_sha256']
    component['component_status'] = 'NOT_MEASURED'
    check(sample, 'package_electrical_feedback').update(status='NOT_MEASURED', detail='missing required D67')
    rebind(p, component)
    authority(p, NAMES[4], {'required_items': [{'case': 'case_a', 'corner': 'nominal',
        'mission_mode': 'functional', 'metric': 'voltage'}]})
    result = consume((p, ctx, component))
    assert item(result, NAMES[4])['status'] == 'NOT_MEASURED'
    assert item(result, NAMES[2])['measurement']['unresolved_required'] == ['package_electrical_feedback']
    assert item(result, NAMES[2])['measurement']['value'] == 1
    assert item(result, NAMES[2])['status'] == 'FAIL'


def test_native_failure_survives_missing_authority(sample):
    p, _, component = sample
    component['component_status'] = 'FAIL'
    check(sample, 'provider_bond_pad_edge')['status'] = 'FAIL'
    for path in (p / 'requirements').rglob('*.json'):
        path.unlink()
    result = consume(sample)
    assert result['status'] == 'FAIL'
    assert item(result, NAMES[1])['failed_checks'] == ['provider_bond_pad_edge']
    assert item(result, NAMES[1])['status'] == 'FAIL'


def test_failed_d67_survives_later_missing_authority(sample):
    p, _, component = sample
    ctx = context(p, package_model_required=True)
    component['context_sha256'] = ctx['context_sha256']; component['component_status'] = 'FAIL'
    check(sample, 'package_electrical_feedback').update(status='FAIL', detail={'native_failure': 'neutral_failed_feedback'})
    rebind(p, component)
    (p / 'requirements/package_ready/package_electrical_feedback_coverage.json').unlink()
    result = consume((p, ctx, component))
    assert result['status'] == 'FAIL'
    assert item(result, NAMES[4])['status'] == 'FAIL'
    assert item(result, NAMES[4])['failed_checks'] == ['package_electrical_feedback']


def test_prior_failed_id_is_preserved(sample):
    sample[2]['metric_acceptance'] = {'status': 'FAIL', 'obligations': [
        {'id': 'package_ready.' + NAMES[0], 'status': 'FAIL'}]}
    result = consume(sample)
    assert result['status'] == 'FAIL'
    assert item(result, NAMES[0])['reason'] == 'D75_PRIOR_MEASURED_FAILURE'


def test_source_bound_bond_bounds_cannot_be_relaxed(sample):
    p = sample[0]
    path = p / 'requirements/package_ready/escape_bond_feasibility.json'
    body = json.loads(path.read_text())
    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
    payload['limits']['left']['max'] = 999
    authority(p, NAMES[1], payload)
    result = consume(sample)
    assert item(result, NAMES[1])['status'] == 'NOT_MEASURED'
    assert 'D75_BOND_SOURCE_RULE_MISMATCH' in item(result, NAMES[1])['detail']


def test_bare_die_missing_conditional_absence_refuses(sample):
    p = sample[0]
    (p / 'requirements/package_ready/package_electrical_feedback_coverage.json').unlink()
    result = consume(sample)
    assert item(result, NAMES[4])['status'] == 'NOT_MEASURED'
    assert item(result, NAMES[4])['reason'] == 'METRIC_AUTHORITY_ABSENT'


def test_required_feedback_list_cannot_omit_check(sample):
    authority(sample[0], NAMES[2], {'required_items': [{'check': 'pad_bterm_coincidence_check'}]})
    result = consume(sample)
    assert item(result, NAMES[2])['status'] == 'NOT_MEASURED'
    assert 'D75_REQUIRED_FEEDBACK_POPULATION_MISMATCH' in item(result, NAMES[2])['detail']


def test_bond_opening_population_must_match_independent_requirement(sample):
    check(sample, 'provider_bond_pad_edge')['detail']['opening_count'] = 2
    result = consume(sample)
    assert item(result, NAMES[1])['status'] == 'NOT_MEASURED'
    assert 'D75_BOND_RULE_OR_POPULATION_UNBOUND' in item(result, NAMES[1])['detail']


def test_full_pad_reference_retains_unbonded_corner(sample):
    p, _, component = sample
    lef = p / 'input/pdk/io.lef'
    write(lef, lef.read_text() + '\nMACRO NEUTRAL_CORNER\n CLASS PAD ;\n SIZE 10 BY 10 ;\nEND NEUTRAL_CORNER\n')
    def_path = p / d75.PAD_DEF
    write(def_path, def_path.read_text().replace('COMPONENTS 1 ;', 'COMPONENTS 2 ;').replace(
        'END COMPONENTS', '- corner NEUTRAL_CORNER + PLACED ( 0 0 ) N ;\nEND COMPONENTS'))
    edge = check(sample, 'provider_bond_pad_edge')['detail']
    edge['master_sources'][0]['sha256'] = hashlib.sha256(lef.read_bytes()).hexdigest()
    ref_path = p / 'adopted/package_ready/pad_bump_package_layout_agreement.json'
    body = json.loads(ref_path.read_text())
    payload = {k: v for k, v in body.items() if k not in ('schema', 'approval')}
    payload['reference']['pad_instances'].insert(0, {'instance': 'corner', 'master': 'NEUTRAL_CORNER',
        'status': 'PLACED', 'x': 0, 'y': 0, 'orient': 'N'})
    authority(p, NAMES[0], payload, adopted=True)
    rebind(p, component)
    result = consume(sample)
    assert item(result, NAMES[0])['status'] == 'PASS'
    assert item(result, NAMES[1])['status'] == 'PASS'


# Incremental existing-admission controls. The original 32 test IDs above are
# sealed evidence and are not selected by this follow-up's runner.
@pytest.fixture
def existing_admission_calls(sample, monkeypatch):
    import flow109_admission as admission
    actual = admission.require_admission
    calls = []

    def trace(project, current):
        record = {'context_sha256': current['context_sha256']}
        calls.append(record)
        try:
            result = actual(project, current)
        except admission.AdmissionRefusal as exc:
            record['refusal'] = exc.report
            raise
        record['receipt'] = result
        return result

    # This observer delegates to the unchanged implementation on every call.
    monkeypatch.setattr(admission, 'require_admission', trace)
    yield calls
    write(sample[0].parent / 'existing-admission-calls.json',
          {'scope': 'NEUTRAL_SOFTWARE_ADMISSION_CONTROL_ONLY', 'calls': calls})


def _existing_admission_context(sample, runtime, registry):
    project, previous, component = sample
    plan = flow109.resolve_plan(previous['features'], previous['step_profiles'])
    current = flow109.execution_context(plan, 'D75', 'D75',
        runtime_tool_uses=runtime, qualification_registry=registry)
    flow109.validate_execution_context(current)
    path = project / d75.CONTEXT_REQUESTS / (current['context_sha256'] + '.json')
    write(path, current)
    previous_path = str(d75.CONTEXT_REQUESTS / (previous['context_sha256'] + '.json'))
    component['inputs'] = [r for r in component['inputs'] if r['path'] != previous_path]
    component['inputs'].append(d75._record(project, path))
    component['context_sha256'] = current['context_sha256']
    return project, current, component


@pytest.fixture
def existing_admission_sample(sample):
    """Existing qualification schema, expressly synthetic reference evidence.

    Like the admission module's own neutral fixture, these QUALIFIED records
    test only binding behavior. They exist in the temporary control project;
    they grant no production authority. Installed executables are hashed and
    resolved by the real reader without running them or replacing which().
    """
    import shutil
    import flow109_admission as admission
    project, ctx, _ = sample
    runtime, records = [], []

    def artifact(name, value):
        path = project / 'neutral-software-admission' / name
        write(path, value)
        return {'path': path.relative_to(project).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    for index, use in enumerate(ctx['resolved_row']['tool_uses']):
        executable = shutil.which(use['executable_name'])
        assert executable, 'official runtime missing required executable: ' + use['executable_name']
        path = Path(executable).resolve()
        executable_ref = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        label = 'NEUTRAL_SOFTWARE_BINDING_CONTROL_NOT_NATIVE_QUALIFICATION'
        identity = {'use_id': use['use_id'], 'tool_id': use['tool_id'], 'version': label,
            'build_sha256': executable_ref['sha256'], 'executable': executable_ref,
            'config': artifact(str(index) + '-config.json', {'fixture': label, 'kind': 'config'}),
            'pdk': artifact(str(index) + '-pdk.json', {'fixture': label, 'kind': 'pdk'}),
            'deck': artifact(str(index) + '-deck.json', {'fixture': label, 'kind': 'deck'}),
            'corner': 'neutral_software_control_corner',
            'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']}}
        record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
            'reference_evidence': [artifact(str(index) + '-reference.json',
                {'fixture': label, 'native_qualification': 'NOT_MEASURED'})]}
        records.append(record)
        runtime.append({**identity, 'qualification_sha256': admission.canonical_sha(record)})
    registry = 'neutral-software-admission/qualifications.json'
    write(project / registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': records,
        'scope': 'NEUTRAL_SOFTWARE_ADMISSION_CONTROL_ONLY'})
    return _existing_admission_context(sample, runtime, registry)


def test_existing_admission_matching_receipt_completes_row(existing_admission_sample, existing_admission_calls):
    sample = existing_admission_sample
    accepted = consume(sample)
    assert accepted['metric_status'] == 'PASS'
    assert accepted['status'] == accepted['qualification'] == 'PASS'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_BINDINGS_CURRENT'
    assert len(existing_admission_calls) == 1
    assert accepted['qualification_receipt'] == existing_admission_calls[0]['receipt']
    # Row completion preserves the separate whole-flow/delivery boundary.
    row = d75.consume_default_row_completion(*sample)
    assert row['default_row_status'] == row['flow109_acceptance'] == 'PASS'
    assert row['completed'] is True and row['delivery_accepted'] is False
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('runtime,registry', [
    (None, 'explicit-missing-qualifications.json'), ([], None), (None, '')],
    ids=['registry_only', 'empty_runtime', 'empty_registry'])
def test_existing_admission_explicit_generic_missing_runtime_refuses(sample, existing_admission_calls, runtime, registry):
    sample = _existing_admission_context(sample, runtime, registry)
    accepted = consume(sample)
    assert accepted['metric_status'] == 'PASS'
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_RUNTIME_ABSENT'
    assert len(existing_admission_calls) == 1


def test_existing_admission_missing_registry_refuses(existing_admission_sample, existing_admission_calls):
    project, current, _ = existing_admission_sample
    (project / current['qualification_registry']).unlink()
    accepted = consume(existing_admission_sample)
    assert accepted['metric_status'] == 'PASS'
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_INPUT_ABSENT'
    assert len(existing_admission_calls) == 1


def test_existing_admission_runtime_identity_mismatch_refuses(existing_admission_sample, existing_admission_calls):
    project, current, component = existing_admission_sample
    runtime = copy.deepcopy(current['runtime_tool_uses'])
    runtime[0]['corner'] = 'different_neutral_corner'
    sample = _existing_admission_context(existing_admission_sample, runtime, current['qualification_registry'])
    accepted = consume(sample)
    assert accepted['metric_status'] == 'PASS'
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_IDENTITY_MISMATCH'
    assert len(existing_admission_calls) == 1


@pytest.mark.parametrize('artifact', ['registry', 'config', 'pdk', 'deck', 'reference'])
def test_existing_admission_stale_artifact_refuses(existing_admission_sample, existing_admission_calls, artifact):
    project, current, _ = existing_admission_sample
    registry = project / current['qualification_registry']
    body = json.loads(registry.read_text())
    record = body['uses'][0]
    if artifact == 'registry':
        record['control_revision'] = 'changed_after_binding'
        write(registry, body)
    else:
        reference = record['reference_evidence'][0] if artifact == 'reference' else record['identity'][artifact]
        write(project / reference['path'], {'fixture': 'changed after qualification binding'})
    accepted = consume(existing_admission_sample)
    assert accepted['metric_status'] == 'PASS'
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_STALE'
    assert len(existing_admission_calls) == 1


def test_existing_admission_current_runtime_executable_required(existing_admission_sample, existing_admission_calls):
    import flow109_admission as admission
    project, current, _ = existing_admission_sample
    registry_path = project / current['qualification_registry']
    body = json.loads(registry_path.read_text())
    record = body['uses'][0]
    # A matching hashed reference to a different executable still must refuse.
    foreign = record['identity']['config']
    record['identity']['executable'] = {**foreign, 'path': str(project / foreign['path'])}
    record['identity']['build_sha256'] = foreign['sha256']
    write(registry_path, body)
    runtime = copy.deepcopy(current['runtime_tool_uses'])
    runtime[0] = {**record['identity'], 'qualification_sha256': admission.canonical_sha(record)}
    sample = _existing_admission_context(existing_admission_sample, runtime, current['qualification_registry'])
    accepted = consume(sample)
    assert accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['qualification_receipt']['reason'] == 'QUALIFICATION_RUNTIME_UNSUPPORTED'
    assert len(existing_admission_calls) == 1


def test_existing_admission_measured_failure_precedes_qualification(existing_admission_sample, existing_admission_calls):
    sample = existing_admission_sample
    sample[2]['component_status'] = 'FAIL'
    check(sample, 'provider_bond_pad_edge')['status'] = 'FAIL'
    accepted = consume(sample)
    assert accepted['status'] == accepted['metric_status'] == 'FAIL'
    assert accepted['qualification'] == 'NOT_MEASURED'
    assert item(accepted, NAMES[1])['failed_checks'] == ['provider_bond_pad_edge']
    assert existing_admission_calls == []


def test_existing_admission_prior_failed_id_precedes_qualification(existing_admission_sample, existing_admission_calls):
    sample = existing_admission_sample
    oid = 'package_ready.' + NAMES[0]
    sample[2]['metric_acceptance'] = {'status': 'FAIL', 'obligations': [{'id': oid, 'status': 'FAIL'}]}
    accepted = consume(sample)
    assert accepted['status'] == accepted['metric_status'] == 'FAIL'
    assert accepted['qualification'] == 'NOT_MEASURED'
    assert accepted['prior_failed_obligation_ids'] == [oid]
    assert item(accepted, NAMES[0])['reason'] == 'D75_PRIOR_MEASURED_FAILURE'
    assert existing_admission_calls == []


def test_existing_admission_incomplete_metrics_cannot_borrow_qualification(existing_admission_sample, existing_admission_calls):
    sample = existing_admission_sample
    (sample[0] / 'requirements/package_ready/escape_bond_feasibility.json').unlink()
    accepted = consume(sample)
    assert accepted['metric_status'] == accepted['status'] == accepted['qualification'] == 'NOT_MEASURED'
    assert item(accepted, NAMES[1])['reason'] == 'METRIC_AUTHORITY_ABSENT'
    assert existing_admission_calls == []


def test_existing_admission_partial_native_observation_cannot_qualify(existing_admission_sample, existing_admission_calls):
    sample = existing_admission_sample
    sample[2]['component_status'] = 'NOT_MEASURED'
    check(sample, 'pad_side_constraint_check')['status'] = 'NOT_MEASURED'
    accepted = consume(sample)
    assert accepted['status'] == accepted['metric_status'] == 'FAIL'
    assert accepted['qualification'] == 'NOT_MEASURED'
    feedback = item(accepted, NAMES[2])
    assert feedback['measurement']['value'] == 1
    assert feedback['measurement']['unresolved_required'] == ['pad_side_constraint_check']
    assert existing_admission_calls == []


@pytest.fixture
def existing_launch_admission_calls(sample, monkeypatch, request):
    import flow109_admission as admission
    actual = admission.require_launch_admission
    calls = []

    def trace(project, step_id, params=None):
        record = {'step_id': step_id, 'context_sha256': params['flow109_context']['context_sha256']}
        calls.append(record)
        try:
            receipt = actual(project, step_id, params)
        except admission.AdmissionRefusal as exc:
            record['refusal'] = exc.report
            raise
        record['receipt'] = receipt
        return receipt

    monkeypatch.setattr(admission, 'require_launch_admission', trace)
    yield calls
    write(sample[0].parent / 'existing-launch-admission-calls.json',
          {'scope': 'NEUTRAL_SOFTWARE_POLICY_CONTROL_ONLY', 'test_id': request.node.nodeid, 'calls': calls})


def _source_owned_canonical(sample):
    project, current, component = sample
    row = flow109._selected_step_result(project, current, component, adapter=d75)
    with (project.parent / 'D75-canonical-policy-observations.jsonl').open('a') as stream:
        stream.write(json.dumps({'scope': 'NEUTRAL_SOFTWARE_POLICY_CONTROL_ONLY',
            'context': current, 'original_component': component, 'canonical_result': row}, sort_keys=True) + '\n')
    return row


def test_existing_admission_source_owned_normal_scope(sample, existing_launch_admission_calls, existing_admission_calls):
    # No synthetic qualification record is needed for this actual normal policy.
    context = sample[1]
    dispatch = context['resolved_row']['profile']['dispatch']
    assert dispatch['admission_policy'] == 'source_owned_existing_native'
    assert dispatch['acceptance_scope'] == 'existing_native_component_only'
    assert context['runtime_tool_uses'] is None and context['qualification_registry'] is None
    row = _source_owned_canonical(sample)
    accepted = row['metric_acceptance']
    assert accepted['metric_status'] == accepted['status'] == 'PASS'
    assert accepted['qualification'] == 'NOT_CLAIMED'
    receipt = accepted['qualification_receipt']
    assert receipt['admitted'] is True
    assert receipt['qualification_status'] == 'NOT_CLAIMED'
    assert receipt['reason'] == 'SOURCE_OWNED_EXISTING_NATIVE_COMPONENT'
    assert receipt['acceptance_scope'] == accepted['acceptance_scope'] == dispatch['acceptance_scope']
    assert receipt['native_step_id'] == 'flow109.D75'
    assert receipt['context_sha256'] == context['context_sha256']
    assert row['default_row_status'] == row['flow109_acceptance'] == 'PASS'
    assert row['completed'] is True
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and row['delivery_accepted'] is False
    assert len(existing_launch_admission_calls) == 1
    assert existing_admission_calls == []


@pytest.mark.parametrize('damage', ['measured_failure', 'prior_failure', 'incomplete_metrics', 'partial_native'])
def test_existing_admission_source_owned_failure_priority(sample, existing_launch_admission_calls, existing_admission_calls, damage):
    if damage == 'measured_failure':
        sample[2]['component_status'] = 'FAIL'
        check(sample, 'provider_bond_pad_edge')['status'] = 'FAIL'
    elif damage == 'prior_failure':
        sample[2]['metric_acceptance'] = {'status': 'FAIL', 'obligations': [
            {'id': 'package_ready.' + NAMES[0], 'status': 'FAIL'}]}
    elif damage == 'incomplete_metrics':
        (sample[0] / 'requirements/package_ready/escape_bond_feasibility.json').unlink()
    else:
        sample[2]['component_status'] = 'NOT_MEASURED'
        check(sample, 'pad_side_constraint_check')['status'] = 'NOT_MEASURED'
    row = _source_owned_canonical(sample)
    expected = 'NOT_MEASURED' if damage == 'incomplete_metrics' else 'FAIL'
    assert row['default_row_status'] == row['flow109_acceptance'] == expected
    assert row['completed'] is False
    assert row['metric_acceptance']['qualification'] == 'NOT_MEASURED'
    assert row['whole_flow_acceptance'] == 'NOT_MEASURED' and row['delivery_accepted'] is False
    assert existing_launch_admission_calls == existing_admission_calls == []
