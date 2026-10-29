"""Source geometry roles through normal L1/L19 and area-basis derivation."""
import json
from pathlib import Path
import pytest
import phase1_doc_one_shot_runner as runner
import floorplan_contract as floorplan
import area_budget_basis_gen as basis
import _tapeout_declaration as declaration
from _hostpaths import require_repo


def fixture_text():
    return require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                        'fixtures', 'phase1_local', 'core_die_role_preservation',
                        'L9_CONSTRAINTS.md').read_text()


def frame(project, text):
    source = project / 'input/docs/L9_CONSTRAINTS.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    answers = {'schema': 'vibe-ic/step_0_5ic_answers/1',
               'answers': {'deliverable': 'DIE'},
               'answer_provenance': {'deliverable': {
                   'answered_by': 'owner', 'citation': 'Neutral source fixture selects DIE delivery only.'}}}
    path = project / 'input/step_0_5ic_answers.json'
    path.write_text(json.dumps(answers))
    return path, answers


def normal_projection(project, text):
    path, answers = frame(project, text)
    result = runner.gen_l1_datasheet(project, {'L9_CONSTRAINTS.md': text})
    runner._post_emit_promote_pipe_tables_to_l1(project)
    l1 = json.loads(result.path.read_text())
    l19path = project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json'
    l19path.write_text(json.dumps({'doc_id': 'L19', 'fields': {
        'die_area_budget_um': None, 'floorplan_hints': [], 'constraints_present': False}}))
    runner._post_emit_floorplan_contract(project)
    l19 = json.loads(l19path.read_text())
    derived = basis.derive(project, answers)
    snapshot = {'l1_die': (l1.get('tapeout_metadata') or {}).get('die_size_um'),
                'l19_die': l19['fields']['die_area_budget_um'],
                'basis_status': derived['status'],
                'fixed': derived.get('basis', {}).get('die_fixed_by_the_input')}
    return snapshot, l1, derived


def test_original_core_and_seal_rows_are_not_an_outer_die_limit(tmp_path):
    text = fixture_text()
    actual, l1, derived = normal_projection(tmp_path, text)
    (tmp_path / 'OBSERVATION.json').write_text(json.dumps({'actual': actual, 'l1': l1, 'derived': derived}, indent=2))
    assert actual == {'l1_die': None, 'l19_die': None,
                      'basis_status': 'NOT_DETERMINED', 'fixed': None}
    rows = [row for table in l1['comparison_tables'] for row in table['rows']]
    assert {'Field': 'Core die (no seal ring)', 'Value': '1300 × 1300 µm'} in rows
    assert {'Field': 'With seal ring', 'Value': '~1480 × 1480 µm'} in rows


@pytest.mark.parametrize('text', [
    '| Core die (no seal ring) | 1170 x 960 um |\n',
    '| Pad die envelope | 1190 x 980 um |\n',
    '| Die target | approximately 1330 x 1110 um |\n',
    '| Die size | ~1360 x 1140 um |\n',
    'Core area is 1220 x 1010 um.\n',
    'The die size is 1260 x 1050 um (without seal ring).\n',
])
def test_qualified_targets_do_not_become_hard_bounds(tmp_path, text):
    actual, _, _ = normal_projection(tmp_path, text)
    assert actual == {'l1_die': None, 'l19_die': None,
                      'basis_status': 'NOT_DETERMINED', 'fixed': None}


@pytest.mark.parametrize('text,expected', [
    ('| Outer die maximum | 1510 x 1270 um |\n', [1510, 1270]),
    ('DIE_AREA = [0,0,1430,1190]\n', None),
    ('Core die: 1170 x 960 um, outer die hard limit: 1590 x 1310 um.\n', [1590, 1310]),
    ('Core die (no seal ring): 1170 x 960 um.\n\nOuter die hard limit: 1590 x 1310 um.\n', [1590, 1310]),
])
def test_explicit_outer_die_bounds_keep_exact_values(tmp_path, text, expected):
    actual, _, derived = normal_projection(tmp_path, text)
    assert derived['status'] == 'WRITE', derived
    budget = derived['budget']
    dims = expected or [1430, 1190]
    assert budget['status'] == 'LIMIT'
    assert budget['max_die_dimensions_um'] == dims
    assert actual['l19_die'] == 'x'.join(map(str, dims))
    if expected:
        assert actual['l1_die'] == expected


def test_generator_retracts_its_stale_false_limit_without_touching_owner_route(tmp_path):
    path, doc = frame(tmp_path, fixture_text())
    doc['answers']['synthesis_area_budget'] = {'status': 'LIMIT', 'max_die_dimensions_um': [1300, 1300]}
    doc['synthesis_area_budget'] = doc['answers']['synthesis_area_budget']
    doc['answer_provenance']['synthesis_area_budget'] = {'answered_by': 'program', 'producer': 'area_budget_basis_gen'}
    path.write_text(json.dumps(doc))
    rc = basis.main([str(tmp_path)])
    result = json.loads(path.read_text())
    assert (rc, declaration.answer(result, 'synthesis_area_budget')) == (2, 'NOT_DETERMINED')
    assert result['answers']['synthesis_area_budget'] == 'NOT_DETERMINED'
    assert result['answers']['deliverable'] == doc['answers']['deliverable']
    assert result['answer_provenance']['deliverable'] == doc['answer_provenance']['deliverable']
    before = path.read_bytes()
    assert basis.main([str(tmp_path)]) == 2
    assert path.read_bytes() == before


def test_explicit_owner_numeric_limit_is_never_retracted(tmp_path):
    path, doc = frame(tmp_path, fixture_text())
    doc['answers']['synthesis_area_budget'] = {'status': 'LIMIT', 'max_die_dimensions_um': [1560, 1320]}
    doc['answer_provenance']['synthesis_area_budget'] = {
        'answered_by': 'owner', 'citation': 'Neutral owner explicitly approves this outer DIE numeric limit.'}
    path.write_text(json.dumps(doc))
    before = path.read_bytes()
    assert basis.main([str(tmp_path)]) == 1
    assert path.read_bytes() == before


def test_exact_legacy_core_row_is_retained_without_becoming_die_authority(tmp_path):
    original = '| Core die (no seal ring) | 1300 x 1300 um |\n'
    frame(tmp_path / 'original', original)
    assert floorplan.extract_floorplan_contract(tmp_path / 'original')['die_area_budget_um'] is None
    start = original.index('1300')
    assert floorplan._die_statement_negated(original, start, start + len('1300 x 1300')) is False
    actual, l1, _ = normal_projection(tmp_path / 'table', '| Field | Value |\n|---|---|\n' + original)
    assert actual == {'l1_die': None, 'l19_die': None, 'basis_status': 'NOT_DETERMINED', 'fixed': None}
    assert l1['comparison_tables'][0]['rows'] == [
        {'Field': 'Core die (no seal ring)', 'Value': '1300 x 1300 um'}]


@pytest.mark.parametrize('deliverable', ['DIE', 'HARDMACRO'])
def test_original_budget_core_carrier_remains_a_source_target(tmp_path, deliverable):
    original = '# L9 Constraints\n\n### 9.2.3 Floorplan\n| Item | Value |\n|---|---|\n| Core die (no seal ring) | 300 × 200 µm |\n'
    path, doc = frame(tmp_path, original)
    doc['answers']['deliverable'] = deliverable
    path.write_text(json.dumps(doc))
    actual = basis.derive(tmp_path, doc)
    assert (actual['status'], actual.get('basis', {}).get('die_fixed_by_the_input')) == ('NOT_DETERMINED', None)
    runner.gen_l1_datasheet(tmp_path, {'L9_CONSTRAINTS.md': original})
    runner._post_emit_promote_pipe_tables_to_l1(tmp_path)
    l1 = json.loads((tmp_path / 'phase1/generated_docs/L1_DATASHEET.json').read_text())
    assert l1['comparison_tables'][0]['rows'] == [{'Item': 'Core die (no seal ring)', 'Value': '300 × 200 µm'}]


def test_approximate_dimension_cannot_assert_a_fixed_die_limit(tmp_path):
    actual, _, _ = normal_projection(tmp_path, '| Die size | approximate 1375 x 1185 um |\n')
    assert actual['basis_status'] == 'NOT_DETERMINED'


def test_a_exact_outer_components_input_reaches_normal_limit(tmp_path):
    text = '| Outer die hard limit (core + pads) | 1600 x 1500 um |\n'
    snapshot, _, derived = normal_projection(tmp_path, text)
    actual = floorplan.extract_floorplan_contract(tmp_path)
    (tmp_path / 'OUTER_COMPONENTS_OBSERVATION.json').write_text(json.dumps(
        {'input': text, 'actual': actual, 'normal_projection': snapshot, 'derived': derived}, indent=2))
    assert snapshot['basis_status'] == 'WRITE'
    # A's exact source input and floorplan assertion, with no historical-head
    # metadata relabelled as a new execution.
    assert actual['die_area_budget_um'] == '1600x1500'
    assert snapshot['l1_die'] == [1600, 1500]
    assert snapshot['l19_die'] == '1600x1500'
    assert derived['budget']['status'] == 'LIMIT'
    assert derived['budget']['max_die_dimensions_um'] == [1600, 1500]


@pytest.mark.parametrize('text', [
    '| Outer die target (core + pads) | 1600 x 1500 um |\n',
    '| Outer die hard limit (approximate core + pads) | 1600 x 1500 um |\n',
    '| (Core die) target | 1300 x 1300 um |\n',
    '| Core die (outer die hard limit) | 1300 x 1300 um |\n',
    '| Outer die hard limit (without seal ring) | 1300 x 1300 um |\n',
])
def test_component_qualifiers_cannot_erase_a_target_or_core_owner(tmp_path, text):
    snapshot, _, _ = normal_projection(tmp_path, text)
    assert snapshot['basis_status'] == 'NOT_DETERMINED'
    assert snapshot['l1_die'] is None and snapshot['l19_die'] is None
