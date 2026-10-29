"""Logical source bullets through the normal intent and plan consumers."""
import json
from pathlib import Path

import pytest
import phase1_doc_one_shot_runner as runner
from _hostpaths import require_repo


DISCLOSURE = (
    'Tool disclosure: IHP SG13G2 ships sectioned ngspice corner libraries for every device '
    'class (cornerMOShv.lib / cornerMOSlv.lib / cornerRES.lib / cornerCAP.lib, tt/ss/ff/sf/fs '
    'with _mismatch and _stat variants); corner sims bind those sections directly. Results are '
    'SIMULATED, not silicon sign-off, and say so — they are NOT LEVEL=1 standins. '
    'CORRECTED 2026-08-11 (vibe-ic#904).')
ORACLE = (
    'Golden cross-check (verify stage only): the fabricated UHEE628_S2024 GDS + KLayout-extracted '
    'SG13G2 netlist (chip-level; per-block sub-netlist is NOT published upstream → cross-check is '
    'spec-level + chip-GDS-DRC level, not per-block device-LVS).')


def source_fixture():
    return require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                        'fixtures', 'phase1_local', 'phase1_wrapped_verification_intent',
                        'L5_ANALOG_SPEC.md').read_text()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def normal_l7(project, text):
    result = runner.gen_l7_test_debug(project, {'L5_ANALOG_SPEC.md': text})
    return json.loads(result.path.read_text())


def methods(l7):
    return [r['method'] for r in l7['verification_strategy']
            if r.get('extraction_strategy') == 'verification_intent_bullet_v634']


def test_original_fixture_harvests_the_full_literal_disclosure():
    rows = runner._v634_harvest_verification_intent({'L5_ANALOG_SPEC.md': source_fixture()})
    observed = [r['description'] for r in rows]
    assert observed[2:] == [DISCLOSURE, ORACLE]


def test_normal_l7_preserves_complete_disclosure_and_separate_oracle(tmp_path):
    l7 = normal_l7(tmp_path, source_fixture())
    assert methods(l7)[2:] == [DISCLOSURE, ORACLE]
    (tmp_path / 'L7_OBSERVATION.json').write_text(json.dumps(l7, indent=2))


def test_normal_l22_transports_the_same_complete_method(tmp_path):
    # Neutral input records establish an analog-applicable frame, not native
    # design evidence. L7 and its transport are both the normal producers.
    gd = tmp_path / 'phase1/generated_docs'
    write_json(gd / 'L1_DATASHEET.json', {'doc_id': 'L1', 'class': 'data_converter'})
    write_json(gd / 'L5_ADI_SPEC.json', {
        'doc_id': 'L5', 'no_analog': False,
        'analog_blocks': [{'name': 'conversion_core', 'type': 'delta_sigma',
                           'spec': {'specs': []}}]})
    write_json(gd / 'L22_VERIFICATION_PLAN.json', {'doc_id': 'L22', 'fields': {}})
    normal_l7(tmp_path, source_fixture())
    assert runner._post_emit_l22_analog_verification_plan(tmp_path) == 1
    l22 = json.loads((gd / 'L22_VERIFICATION_PLAN.json').read_text())
    intent = l22['fields']['verification_plan']['unscoped_intent']
    # The existing L22 emitter splits semicolon clauses and retains their
    # full source method in clause_of; preserve that transport contract.
    for expected, prefix in ((DISCLOSURE, 'tool_disclosure_'),
                             (ORACLE, 'golden_cross_check_')):
        rows = [r for r in intent if r['phase'].startswith(prefix)]
        assert [r['method'] for r in rows] == [part.strip() for part in expected.split(';')]
        assert [r['clause_of'] for r in rows] == [expected] * len(rows)
    (tmp_path / 'L22_OBSERVATION.json').write_text(json.dumps(l22, indent=2))


def test_normal_l10_keeps_full_disclosure_and_oracle_as_refusals(tmp_path):
    result = runner.gen_l10_test_cases(tmp_path, {'L5_ANALOG_SPEC.md': source_fixture()}, {})
    l10 = json.loads(result.path.read_text())
    fields = l10.get('fields', l10)
    refusal = {r['reason_code']: r['sentence']
               for r in fields['verification_intent_refusals']}
    assert refusal == {'DISCLOSURE_OR_METHOD_NOTE': DISCLOSURE,
                       'ORACLE_CROSS_CHECK_4_05': ORACLE}
    assert not any(r.get('stimulus') in (DISCLOSURE, ORACLE)
                   for r in fields.get('test_cases', []))


@pytest.mark.parametrize('body,expected', [
    ('- Measure settling time\n  across all declared corners.\n- Check reset state.\n',
     ['Measure settling time across all declared corners.', 'Check reset state.']),
    ('- Measure settling time\n  across all declared corners.\n## Next section\n  unrelated details\n- Not intent.\n',
     ['Measure settling time across all declared corners.']),
    ('- Measure settling time\nUnindented unrelated prose.\n  Not a continuation.\n',
     ['Measure settling time']),
    ('1. Measure settling time\n   across all corners.\n2. Check reset state.\n',
     ['Measure settling time across all corners.', 'Check reset state.']),
    ('* Measure settling time\n  across all corners.\n\n  Preserve the declared limit.\n+ Check reset state.\n',
     ['Measure settling time across all corners. Preserve the declared limit.', 'Check reset state.']),
])
def test_logical_bullet_boundaries(body, expected):
    rows = runner._v634_harvest_verification_intent({'spec.md': '## Verification intent\n' + body})
    assert [r['description'] for r in rows] == expected


def test_wrapped_oracle_role_cannot_become_an_executable_test(tmp_path):
    text = ('## Verification intent\n- Cross-check:\n'
            '  against the golden reference netlist.\n')
    result = runner.gen_l10_test_cases(tmp_path, {'spec.md': text}, {})
    l10 = json.loads(result.path.read_text())
    fields = l10.get('fields', l10)
    assert [r['reason_code'] for r in fields.get('verification_intent_refusals', [])] == [
        'ORACLE_CROSS_CHECK_4_05']
    assert [r for r in fields.get('test_cases', [])
            if r.get('kind') == 'verification_intent'] == []


def test_single_line_and_absent_section_keep_existing_meaning():
    assert [r['description'] for r in runner._v634_harvest_verification_intent(
        {'spec.md': '## Verification intent\n- Check reset state.\n'})] == ['Check reset state.']
    assert runner._v634_harvest_verification_intent(
        {'spec.md': '## General notes\n- Check reset state.\n'}) == []


def normal_corner_plan(project, text):
    gd = project / 'phase1/generated_docs'
    write_json(gd / 'L1_DATASHEET.json', {'doc_id': 'L1', 'class': 'data_converter'})
    write_json(gd / 'L5_ADI_SPEC.json', {
        'doc_id': 'L5', 'no_analog': False,
        'analog_blocks': [{'name': 'conversion_core', 'type': 'delta_sigma',
                           'spec': {'specs': []}}]})
    write_json(gd / 'L22_VERIFICATION_PLAN.json', {'doc_id': 'L22', 'fields': {}})
    normal_l7(project, text)
    assert runner._post_emit_l22_analog_verification_plan(project) == 1
    return json.loads((gd / 'L22_VERIFICATION_PLAN.json').read_text())['fields']['verification_plan']


def test_original_campaign_cannot_gain_available_library_corners(tmp_path):
    plan = normal_corner_plan(tmp_path, source_fixture())
    actual = plan['corner_matrix']
    (tmp_path / 'CORNER_OBSERVATION.json').write_text(json.dumps(plan, indent=2))
    assert actual['process'] == ['TT', 'SS', 'FF'], actual
    assert actual['temperature_c'] == [-40, 27, 125], actual
    assert {r.get('clause_of', r['method']) for r in plan['unscoped_intent']
            if r['phase'].startswith('tool_disclosure_')} == {DISCLOSURE}


@pytest.mark.parametrize('metadata', [
    'Tool disclosure: available model sections include FS/SF at -20/90 C; results are SIMULATED.',
    'Method note: the model package supports FS/SF and -20/90 C.',
    'Golden cross-check: compare against the golden reference netlist at FS/SF and -20/90 C.',
])
def test_metadata_corner_axes_stay_out_of_declared_campaign(tmp_path, metadata):
    text = ('## Verification intent\n- Multi-corner: TT/SS/FF at -40/27/125 C.\n'
            '- ' + metadata + '\n')
    plan = normal_corner_plan(tmp_path, text)
    assert plan['corner_matrix']['process'] == ['TT', 'SS', 'FF']
    assert plan['corner_matrix']['temperature_c'] == [-40, 27, 125]
    assert any(r.get('clause_of', r['method']) == metadata
               for r in plan['unscoped_intent'])


def test_separately_required_extra_corners_still_propagate(tmp_path):
    text = (source_fixture() + '\n- Required extra corners: SF/FS at -20/90 C.\n')
    plan = normal_corner_plan(tmp_path, text)
    assert plan['corner_matrix']['process'] == ['TT', 'SS', 'FF', 'SF', 'FS']
    assert plan['corner_matrix']['temperature_c'] == [-40, 27, 125, -20, 90]


def test_metadata_alone_cannot_invent_a_required_matrix(tmp_path):
    text = ('## Verification intent\n- Tool disclosure: available corners FS/SF '
            'at -20/90 C; results remain SIMULATED.\n')
    plan = normal_corner_plan(tmp_path, text)
    assert plan.get('corner_matrix') is None
    assert {r.get('clause_of', r['method']) for r in plan['unscoped_intent']} == {
        'Tool disclosure: available corners FS/SF at -20/90 C; results remain SIMULATED.'}
