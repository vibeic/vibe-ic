import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phase1_doc_one_shot_runner import (
    _harvest_test_cases_from_input_tables as harvest,
    gen_l10_test_cases,
)
import cpu_functional_oracle_waiver_check as coverage_consumer
import l10_coverage_goal_classify as coverage_classify
import l10_test_case_oracle_anchor_check as oracle_consumer
from _hostpaths import require_repo

_GOALS=['random_message_functional_equivalence_vs_nist_go',
        'message_length','protocol','mode_switch']

def test_original_coverage_goals_are_not_vectors():
 text=(Path(__file__).resolve().parent/'fixtures/phase1_local/coverage_goal_table_local/verification_plan.md').read_text()
 rows=harvest({'verification_plan.md':text})
 # The count is DERIVED from the pinned member list below, not a second literal
 # that could agree with any four rows.
 assert len(rows)==len(_GOALS)
 # H5 -- the MEMBERS, not only how many. A count-only pin cannot tell four
 # distinct coverage goals from four copies of one, and the row this fixture
 # was filed for (LOCAL:SHA2055, `mode_switch`) could disappear without moving
 # the number. Pinned by NAME because the stimulus column of this captured
 # input is not English and does not belong in test source.
 assert [r['name'] for r in rows]==_GOALS
 assert all(r['kind']=='coverage_goal' for r in rows)
 assert all('100%' in r['expected'] and r['stimulus'] for r in rows)

def test_neutral_acceptance_scope_table():
 text='| Test category | Pass criterion | Scope |\n|---|---|---|\n| Random lengths | 99% PASS | 500 independent lengths |\n'
 rows=harvest({'verification_plan.md':text});assert len(rows)==1
 assert rows[0]['kind']=='coverage_goal' and rows[0]['expected']=='99% PASS'

def test_concrete_input_and_result_remain_vector():
 text='| Test | Input | Expected |\n|---|---|---|\n| Arithmetic example | 0x01 | 0x02 |\n'
 row=harvest({'verification_plan.md':text})[0]
 assert row['kind']=='functional_vector' and row['stimulus']=='0x01' and row['expected']=='0x02'

def test_percent_output_is_not_coverage_goal():
 text='| Test | Input | Expected |\n|---|---|---|\n| Duty output | control=1 | 100% PASS |\n'
 row=harvest({'verification_plan.md':text})[0];assert row['kind']=='functional_vector'


_ISSUE3473_IDS = [
    'random_multiplication_functional_equivalence',
    'corner_operand',
    'case_3',
    'reset',
    'toggle_branch_coverage',
]


def _issue3473_plan_text():
    return require_repo(
        'vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
        'fixtures', 'issue3473_retained_replay', 'input', 'docs',
        'L7_verification_plan.md').read_text()


def _emit_l10(tmp_path, text):
    project = tmp_path / 'project'
    source = project / 'input/docs/L7_verification_plan.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    result = gen_l10_test_cases(
        project, {'L7_verification_plan.md': text}, {})
    return project, result.path, json.loads(result.path.read_text())


def _single_case_chain(tmp_path, name, expected):
    text = f'''| Test | Input | Expected |
| --- | --- | --- |
| {name} | x=1 | {expected} |
'''
    project, l10_path, emitted = _emit_l10(tmp_path, text)
    row = emitted['test_cases'][0]
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    coverage = coverage_consumer._coverage_goal_summary(project)
    goal = next((item for item in coverage['rows']
                 if item['case'] == name), None)
    return row, oracle, goal


def test_native_measurement_row_reaches_oracle_and_coverage_consumers(tmp_path):
    project, l10_path, emitted = _emit_l10(tmp_path, _issue3473_plan_text())
    rows = emitted['test_cases'][:5]
    measurement = rows[-1]
    functional, delegated = coverage_classify.execution_partition(rows)
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    coverage = coverage_consumer._coverage_goal_summary(project)
    measured = next((row for row in coverage['rows']
                     if row['case'] == 'toggle_branch_coverage'), None)
    observed = {
        'ids': [row['name'] for row in rows],
        'kinds': [row['kind'] for row in rows],
        'functional': [row['name'] for row in functional],
        'delegated_coverage': [row['name'] for row in delegated],
        'threshold_field_present': 'target_pct' in measurement,
        'threshold_pct': coverage_classify.stated_acceptance_percentage(
            measurement)[0],
        'oracle_denominator': oracle['summary']['cases_executable'],
        'oracle_findings': [finding['category']
                            for finding in oracle['findings']],
        'coverage_consumer': None if measured is None else {
            'stated_pct': measured['stated_pct'],
            'achieved_pct': measured['achieved_pct'],
            'verdict': measured['verdict'],
        },
    }
    assert observed['ids'] == _ISSUE3473_IDS
    assert observed['kinds'] == [
        'functional_vector', 'functional_vector', 'functional_vector',
        'functional_vector', 'coverage_goal']
    assert observed['functional'] == _ISSUE3473_IDS[:4]
    assert observed['delegated_coverage'] == _ISSUE3473_IDS[4:]
    assert observed['threshold_field_present'] is False
    assert observed['threshold_pct'] is None
    assert observed['oracle_denominator'] == 4
    assert observed['oracle_findings'] == []
    assert observed['coverage_consumer'] == {
        'stated_pct': None,
        'achieved_pct': None,
        'verdict': 'NOT_MEASURED',
    }


def test_native_measurement_actual_consumer_values(tmp_path):
    project, l10_path, emitted = _emit_l10(tmp_path, _issue3473_plan_text())
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    coverage = coverage_consumer._coverage_goal_summary(project)
    measured = next((row for row in coverage['rows']
                     if row['case'] == 'toggle_branch_coverage'), None)
    actual = [
        oracle['summary']['cases_executable'],
        [finding['category'] for finding in oracle['findings']],
        None if measured is None else measured['verdict'],
    ]
    assert actual == [4, [], 'NOT_MEASURED']


def test_coverage_like_functional_prose_without_measurement_stays_strict(
        tmp_path):
    text = '''| Test case | Stimulus | Expected result |
| --- | --- | --- |
| ordinary_transaction | Enable coverage collection, then drive request. | Coverage status behaves correctly. |
'''
    _project, l10_path, emitted = _emit_l10(tmp_path, text)
    row = emitted['test_cases'][0]
    assert row['kind'] == 'functional_vector'
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    assert oracle['summary']['cases_executable'] == 1
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']


def test_coverage_shaped_name_without_measurement_semantics_stays_strict(
        tmp_path):
    text = '''| Test case | Stimulus | Expected result |
| --- | --- | --- |
| toggle_branch_coverage | Drive deterministic operands. | Behavior follows the verification plan. |
'''
    _project, l10_path, emitted = _emit_l10(tmp_path, text)
    row = emitted['test_cases'][0]
    assert row['name'] == 'toggle_branch_coverage'
    assert row['kind'] == 'functional_vector'
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']


def test_negated_native_measurement_is_not_an_affirmative_obligation(tmp_path):
    text = '''| Test case | Stimulus | Expected result |
| --- | --- | --- |
| diagnostic_mode | Drive deterministic operands. | Native line, branch, and toggle coverage must not be measured and reported. |
'''
    _project, l10_path, emitted = _emit_l10(tmp_path, text)
    assert emitted['test_cases'][0]['kind'] == 'functional_vector'
    oracle = oracle_consumer.audit(l10_path, l10_path.parent)
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']


def test_mixed_functional_and_coverage_expected_stays_functional(tmp_path):
    expected = ('Output p must equal 1; native line, branch and toggle '
                'coverage must be measured and reported.')
    row, oracle, goal = _single_case_chain(tmp_path, 'mixed', expected)
    assert [row['kind'], row['expected']] == ['functional_vector', expected]
    assert oracle['summary']['cases_executable'] == 1
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']
    assert goal is None, 'mixed reporting prose must never manufacture PASS'


def test_outer_negation_does_not_become_affirmative_measurement(tmp_path):
    expected = ('It is not true that native line, branch and toggle coverage '
                'are measured and reported.')
    row, oracle, goal = _single_case_chain(
        tmp_path, 'outer_negation', expected)
    assert row['kind'] == 'functional_vector'
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']
    assert goal is None


def test_conditional_measurement_clause_stays_functional(tmp_path):
    expected = ('If coverage mode is enabled, native line, branch and toggle '
                'coverage must be measured and reported.')
    row, oracle, goal = _single_case_chain(tmp_path, 'conditional', expected)
    assert row['kind'] == 'functional_vector'
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']
    assert goal is None


def test_malformed_modal_measurement_clause_stays_functional(tmp_path):
    expected = ('Native line, branch, and toggle coverage must measured and '
                'reported.')
    row, oracle, goal = _single_case_chain(
        tmp_path, 'malformed_modal', expected)
    assert [row['kind'], row['expected']] == ['functional_vector', expected]
    assert oracle['summary']['cases_executable'] == 1
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']
    assert goal is None


def test_malformed_copular_measurement_clause_stays_functional(tmp_path):
    expected = ('Native line, branch, and toggle coverage is be measured and '
                'reported.')
    row, oracle, goal = _single_case_chain(
        tmp_path, 'malformed_copular', expected)
    assert [row['kind'], row['expected']] == ['functional_vector', expected]
    assert oracle['summary']['cases_executable'] == 1
    assert [finding['category'] for finding in oracle['findings']] == [
        'NO_ORACLE_ANCHOR']
    assert goal is None
