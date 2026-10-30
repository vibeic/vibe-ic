"""Conditional verification substitution is document intent, not execution credit."""
import json
import pytest
import phase1_doc_one_shot_runner as runner
from phase1_expert_parse_track import converge_ai_expectation

CONDITION = ('Hardware-in-the-loop is WAIVED (no physical die on the bench) — '
             'substitute with a real mixed-signal cosim and state it.')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def produce(project, extracted):
    gd = project / 'phase1/generated_docs'
    if not (gd / 'L1_DATASHEET.json').exists():
        write(gd / 'L1_DATASHEET.json', {'doc_id': 'L1', 'class': 'data_converter'})
        write(gd / 'L5_ADI_SPEC.json', {'doc_id': 'L5', 'no_analog': False,
            'analog_blocks': [{'name': 'conversion_core', 'type': 'delta_sigma',
                              'spec': {'specs': []}}]})
        write(gd / 'L22_VERIFICATION_PLAN.json', {'doc_id': 'L22', 'fields': {}})
    l7 = runner.gen_l7_test_debug(project, extracted)
    assert runner._post_emit_l22_analog_verification_plan(project) == 1
    return json.loads(l7.path.read_text()), json.loads((gd / 'L22_VERIFICATION_PLAN.json').read_text())


def demand():
    return {'id': 'neutral.hil_substitution', 'layer': 'L7_TEST_DEBUG',
        'field_path': 'verification_strategy',
        'requirement': 'Preserve the explicit conditional HIL-to-cosim method, not its execution.',
        'evidence': ['source.md: explicit condition and substitute'],
        'expected_tokens': ['hardware-in-the-loop', 'WAIVED', 'mixed-signal', 'cosim']}


@pytest.mark.parametrize('earlier', [False, True])
def test_normal_l7_and_l22_keep_conditional_substitution(tmp_path, earlier):
    extracted = {'earlier.md': '## Verification intent\n- Check reset state.\n'} if earlier else {}
    extracted['source.md'] = ('## Tool / data disclosures\n- Hardware-in-the-loop is WAIVED '
        '(no physical die on the bench) — substitute with a\n'
        '  real mixed-signal cosim and state it.\n## Next section\n- Unrelated metadata.\n')
    l7, l22 = produce(tmp_path, extracted)
    decided = converge_ai_expectation(tmp_path, demand())
    assert decided['met'] == True, decided
    matching = [r for r in l7['verification_strategy'] if r['method'] == CONDITION]
    assert len(matching) == 1
    assert matching[0]['evidence'].startswith('input/docs/source.md')
    plan = l22['fields']['verification_plan']
    assert any(r.get('clause_of', r['method']) == CONDITION for r in plan['unscoped_intent'])
    assert not any(k in matching[0] for k in ['waived', 'native_pass', 'executed'])


@pytest.mark.parametrize('text', [
    'Hardware-in-the-loop is WAIVED; no substitute has been declared.',
    'Hardware-in-the-loop is WAIVED; do not substitute with a real mixed-signal cosim.',
    'Tool disclosure: hardware-in-the-loop is WAIVED; substitute with a real mixed-signal cosim.',
    'Golden cross-check: hardware-in-the-loop is WAIVED; substitute with a real mixed-signal cosim against the golden reference netlist.',
])
def test_other_notes_are_not_promoted_to_substitution_intent(tmp_path, text):
    l7, _ = produce(tmp_path, {'notes.md': '## General notes\n- ' + text + '\n'})
    assert [r for r in l7['verification_strategy'] if r['method'] == text] == []


def test_conditional_substitute_is_not_a_runnable_l10_test(tmp_path):
    extracted = {'source.md': '## Verification intent\n- '+CONDITION+'\n'}
    result = runner.gen_l10_test_cases(tmp_path, extracted, {})
    l10 = json.loads(result.path.read_text());fields=l10.get('fields',l10)
    assert [r for r in fields.get('test_cases', []) if r.get('kind') == 'verification_intent'] == []
    assert any(r['sentence'] == CONDITION and r['reason_code'] == 'DISCLOSURE_OR_METHOD_NOTE'
               for r in fields.get('verification_intent_refusals', []))
