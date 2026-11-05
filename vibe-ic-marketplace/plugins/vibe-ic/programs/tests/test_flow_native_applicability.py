"""Design and delivery applicability through the real editable step table."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
import flow_steps_generate as generator


def row(name):
    return next(item for item in engine.read_json(engine.TABLE)['steps'] if item['name'] == name)


@pytest.mark.parametrize('target,safety,expected', [
    ('rtl', False, []),
    ('ip_hardmacro', False, ['submission_and_implementation_interface', 'pdk_library_deck_and_tool_use_qualification']),
    ('shippable_gds', True, ['submission_and_implementation_interface', 'pdk_library_deck_and_tool_use_qualification', 'functional_safety_plan_and_tool_confidence']),
])
def test_early_rows_follow_design_scope(tmp_path, target, safety, expected):
    table = engine.read_json(engine.TABLE)
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'requires_functional_safety': safety}))
    route = {'entry_step': 'requirements_and_delivery_route', 'verify_through': 'functional_safety_plan_and_tool_confidence', 'delivery_target': target}
    features = engine.design_features(tmp_path, route, table)
    chosen = engine.select_steps(table, route, features, 'submission_and_implementation_interface', None)
    assert [item['name'] for item in chosen] == expected


def test_selected_safety_without_tool_is_visible(tmp_path):
    safety = row('functional_safety_plan_and_tool_confidence')
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'requires_functional_safety': True}))
    table = engine.read_json(engine.TABLE)
    route = {'entry_step': 'requirements_and_delivery_route', 'verify_through': safety['name'], 'delivery_target': 'ip_hardmacro'}
    result = engine.run(tmp_path, table=table, route=route, from_name=safety['name'])
    assert result['selected'] == 1
    assert result['steps'][0]['status'] == 'NOT_MEASURED'
    assert 'not available' in result['steps'][0]['detail'] or 'adapted' in result['steps'][0]['detail']
    omitted = next(item for item in result['not_selected'] if item['name'] == 'mixed_signal_signoff')
    assert omitted['condition'] == 'mixed'
    assert omitted['features'] == {'mixed': False}


@pytest.mark.parametrize('target', ['ip_hardmacro', 'shippable_gds'])
def test_document_only_physical_delivery_needs_no_absence_answer(tmp_path, target):
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'physical_declarations'}, {'delivery_target': target})
    assert engine.evaluate(engine.ToolResult(**result), []) == 'PASS'
    if target == 'ip_hardmacro':
        assert result['metrics'] == {'slot_owed': False, 'pad_ring_owed': False, 'die_outputs_owed': False}
    else:
        assert result['metrics']['operator_template_present'] is False


def test_bought_slot_hard_ip_still_fails(tmp_path):
    path = tmp_path / 'input/step_0_5ic_answers.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'answers': {'deliverable': 'HARDMACRO'},
        'answer_provenance': {'deliverable': {'answered_by': 'owner', 'citation': 'Deliver a hard macro IP.'}},
        'operator_template': {'slot': 'neutral_slot'}}))
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'physical_declarations'}, {'delivery_target': 'ip_hardmacro'})
    assert engine.evaluate(engine.ToolResult(**result), []) == 'FAIL'
    assert 'bought shuttle slot' in result['detail']


def test_generator_does_not_infer_deletion_from_metric_words():
    registry = {'rows': [{'id': 'neutral', 'name': 'Neutral row', 'when': 'always',
        'profiles': [{'select_when': 'otherwise'}], 'obligations': [
            {'metric': name, 'expectation': {'operator': 'eq', 'value': 0}}
            for name in ('binding_errors', 'qualification_errors', 'approval_errors', 'stale_adopted_evidence')]}],
        'predicate_definitions': {}, 'feature_implications': {}, 'feature_exclusions': {}}
    native = {'steps': {}, 'runs': {}, 'deleted_metrics': {'stale_adopted_evidence': 'Explicit owner deletion.'}}
    table, dropped, _ = generator.generate(registry, native)
    assert [item['metric'] for item in table['steps'][0]['checks']] == ['binding_errors', 'qualification_errors', 'approval_errors']
    assert [item['metric'] for item in dropped] == ['stale_adopted_evidence']


def test_native_technology_conflict_is_a_failure_without_context_or_image(tmp_path, monkeypatch):
    import flow109_technology_qualification as technology
    root = tmp_path / 'pdk'
    root.mkdir()
    monkeypatch.setenv('PDK_ROOT', str(root))
    monkeypatch.delenv('VIBEIC_EDA_IMAGE', raising=False)
    config = tmp_path / 'phase3/librelane/config.json'
    config.parent.mkdir(parents=True)
    config.write_text('{}')
    with patch.object(technology, 'declared_distribution', return_value=('neutral_pdk', [])), patch.object(
            technology, '_resolve', side_effect=technology.D03Refusal('D03_PDK_DECLARATION_CONFLICT', 'config differs')):
        result = technology.execute(tmp_path, tmp_path / 'step')
    assert engine.evaluate(engine.ToolResult(**result), []) == 'FAIL'
    assert 'D03_PDK_DECLARATION_CONFLICT' in result['detail']


def test_document_operator_template_runs_both_existing_producers(tmp_path):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    template = tmp_path / 'operator'
    template.mkdir()
    (template / 'neutral.json').write_text(json.dumps({'name': 'neutral_slot',
        'DIE_AREA': [0, 0, 600, 700], 'PAD_NORTH': ['signal_a']}))
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'operator_template': {
        'path': str(template), 'slot': 'neutral_slot'}}))
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'physical_declarations'}, {'delivery_target': 'shippable_gds'})
    assert engine.evaluate(engine.ToolResult(**result), []) == 'PASS', result
    report = engine.read_json(tmp_path / 'reports/phase1/submission_template.json')
    assert report['ingest']['declared_slot'] == 'neutral_slot'
    assert list((tmp_path / 'input/submission_template/slots').glob('*.yaml'))
    assert (tmp_path / 'input/submission_template/tapeout_declaration.json').is_file()


def test_document_bought_slot_conflicts_with_hard_ip(tmp_path):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'fields': {'operator_template': {'slot': 'neutral_slot'}}}))
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'physical_declarations'}, {'delivery_target': 'ip_hardmacro'})
    assert engine.evaluate(engine.ToolResult(**result), []) == 'FAIL'
    assert 'bought shuttle slot' in result['detail']


@pytest.mark.parametrize('name,feature', [
    ('macro_logical_and_timing_views', 'uses_macros'),
    ('mixed_signal_signoff', 'has_analog'),
])
@pytest.mark.parametrize('declared', [False, True])
def test_restored_conditional_rows_remain_visible_without_inputs(tmp_path, name, feature, declared):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({feature: declared}))
    table = engine.read_json(engine.TABLE)
    route = {'entry_step': name, 'verify_through': name, 'delivery_target': 'ip_hardmacro'}
    report = engine.run(tmp_path, table=table, route=route)
    assert report['selected'] == int(declared)
    if declared:
        assert report['steps'][0]['status'] == 'NOT_MEASURED'
        assert report['steps'][0]['detail']
    else:
        omitted = next(item for item in report['not_selected'] if item['name'] == name)
        assert list(omitted['features'].values()) == [False]


@pytest.mark.parametrize('complete,status', [(True, 'PASS'), (False, 'FAIL')])
def test_existing_macro_producer_retains_its_own_view_set_verdict(tmp_path, complete, status):
    macro = tmp_path / 'input/pdk_local/neutral/block'
    macro.mkdir(parents=True)
    (macro / 'block.lef').write_text('MACRO block\n CLASS BLOCK ;\n SIZE 10 BY 10 ;\nEND block\n')
    (macro / 'block.gds').write_bytes(b'neutral view-set fixture')
    if complete:
        (macro / 'block.lib').write_text('library(neutral) { cell(block) { area: 100; } }\n')
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'macro_views'}, {'delivery_target': 'ip_hardmacro'})
    assert engine.evaluate(engine.ToolResult(**result), []) == status
    assert result['metrics']['macro_count'] == 1


def test_physical_declaration_refusal_cannot_reuse_an_earlier_pass(tmp_path):
    physical = row('submission_and_implementation_interface')
    table = {'steps': [physical], 'predicates': {'physical': 'hard_ip'}}
    route = {'entry_step': physical['name'], 'verify_through': physical['name'], 'delivery_target': 'ip_hardmacro'}
    assert engine.run(tmp_path, table=table, route=route)['steps'][0]['status'] == 'PASS'
    path = tmp_path / 'input/step_0_5ic_answers.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'answers': {'deliverable': 'HARDMACRO'},
        'answer_provenance': {'deliverable': {'answered_by': 'owner', 'citation': 'Deliver a hard macro IP.'}},
        'operator_template': {'slot': 'neutral_slot'}}))
    report = engine.run(tmp_path, table=table, route=route)
    assert report['steps'][0]['status'] == 'FAIL'
    assert report['steps'][0]['retained'] is False


def test_only_actual_merged_rows_are_unconditionally_unselected():
    table = engine.read_json(engine.TABLE)
    assert {item['name'] for item in table['steps'] if item['when'] == 'False'} == {
        'constraint_validation', 'netlist_handoff'}
    reason = row('netlist_handoff')['applicability_reason']
    assert all(name in reason for name in ('LibreLane State', 'Synthesis', 'Netlist equivalence', 'Pre-layout timing'))
