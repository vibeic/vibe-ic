"""Explicit reset phase tables must reach the normal consuming layers."""
from __future__ import annotations

import json
import ast
import sys
import subprocess
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as D

FIXTURE = Path(__file__).parent / 'fixtures/phase1_local/neutral_reset_domain_phases/reset.md'


def _emit(project, text):
    source = project / 'input/docs/reset.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    sdc = project / 'input/constraints/clocks.sdc'
    sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -name main -period 20 [get_ports clk_i]\n'
                   'create_clock -name aux -period 32 [get_ports clk_aux_i]\n')
    extracted = {'reset.md': text}
    D.gen_l1_datasheet(project, extracted)
    D.gen_l8_timing_waveform(project, extracted)
    D.gen_l8_timing_waveform_doc(project, extracted)
    D.gen_l9_integration_spec(project, extracted, {})
    D._post_emit_typed_clock_domains(project)
    D._post_emit_sdc_constraints(project)
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    D._post_emit_l8_clock_reset_waveform(project)
    docs = {name: json.loads((project / 'phase1/generated_docs' / name).read_text())
            for name in ['L8_RTL_CONSTANTS.json', 'L8_TIMING_WAVEFORM.json',
                         'L9_INTEGRATION_SPEC.json']}
    print('RESET_DOMAIN_OBSERVATION ' + json.dumps(docs, sort_keys=True))
    return docs


def test_explicit_per_domain_assertion_and_release_reach_normal_consumers(tmp_path):
    docs = _emit(tmp_path, FIXTURE.read_text())
    l9 = docs['L9_INTEGRATION_SPEC.json']
    reset = next(r for r in l9['reset_domains'] if r['name'] == 'rst_n')
    assert reset['sync'] == 'asynchronous'
    assert reset['polarity'] == 'active_low'
    expected = {clock: {'clock': clock, 'assertion': 'asynchronous',
                       'release': 'synchronous', 'release_clock': clock,
                       'release_stages': 2, 'polarity': 'active_low'}
                for clock in ['clk_i', 'clk_aux_i']}
    actual = {row['clock']: row for row in reset['domain_bindings']}
    for clock, fields in expected.items():
        assert {key: actual[clock][key] for key in fields} == fields
        assert actual[clock]['basis'][0]['file'] == 'input/docs/reset.md'
        assert actual[clock]['basis'][0]['quote'] in FIXTURE.read_text().splitlines()
    for layer in docs.values():
        domains = {row['name']: row for row in layer.get('clock_domains', [])}
        for clock, fields in expected.items():
            assert domains[clock]['reset_strategy'] == 'asynchronous assertion; synchronous release'
            binding = domains[clock]['reset_bindings'][0]
            assert binding['reset'] == 'rst_n'
            assert {key: binding[key] for key in fields} == fields
    waveform = docs['L8_TIMING_WAVEFORM.json']['clock_and_reset_waveform']
    projected = next(row for row in waveform['resets'] if row['name'] == 'rst_n')
    assert projected['domain_bindings'] == reset['domain_bindings']


@pytest.mark.parametrize('change,field,expected', [
    ('missing_stages', 'release_stages', 'unknown'),
    ('missing_release_clock', 'release_clock', 'unknown'),
    ('conflicting_stages', 'release_stages', 'unknown'),
    ('different_domain_stages', 'release_stages', 3),
])
def test_phase_values_stay_bound_to_the_explicit_domain(tmp_path, change, field, expected):
    text = FIXTURE.read_text()
    row = '| clk_aux_i | rst_n | active-low | asynchronous | synchronous to clk_aux_i | 2 |'
    replacement = row
    if change == 'missing_stages':
        replacement = row.replace('| 2 |', '| unspecified |')
    elif change == 'missing_release_clock':
        replacement = row.replace('synchronous to clk_aux_i', 'synchronous')
    elif change == 'conflicting_stages':
        replacement = row + '\n' + row.replace('| 2 |', '| 3 |')
    elif change == 'different_domain_stages':
        replacement = row.replace('| 2 |', '| 3 |')
    docs = _emit(tmp_path, text.replace(row, replacement))
    reset = docs['L9_INTEGRATION_SPEC.json']['reset_domains'][0]
    rows = {binding['clock']: binding for binding in reset['domain_bindings']}
    assert rows['clk_aux_i'][field] == expected
    assert rows['clk_i']['release_stages'] == 2
    assert rows['clk_i']['release_clock'] == 'clk_i'
    if change == 'conflicting_stages':
        assert len(rows['clk_aux_i']['basis']) == 2


def test_table_for_another_reset_cannot_supply_this_reset_phases():
    import _reset_input_semantics as R
    text = FIXTURE.read_text().replace('| rst_n | active-low |', '| other_reset_n | active-low |')
    assert R.reset_domain_bindings('rst_n', {'reset.md': text}) == []
    assert R.reset_semantics('rst_n', text) == {'polarity': 'active_low'}


def test_historical_phase_row_does_not_replace_current_reset_declaration():
    import _reset_input_semantics as R
    text = ('| Clock | Reset | Polarity | Assertion | Release | Release synchronizer stages | Note |\n'
            '|---|---|---|---|---|---:|---|\n'
            '| clk_i | rst_n | active-low | asynchronous | synchronous to clk_i | 2 | Historical configuration only |\n'
            'rst_n is an active-high synchronous reset.\n')
    assert R.reset_semantics('rst_n', text) == {'sync': 'synchronous', 'polarity': 'active_high'}
    assert R.reset_domain_bindings('rst_n', {'reset.md': text}) == []


def _consume(project, docs):
    import professional_tb_gen as T
    cr = T._load_clock_reset(project, docs['L9_INTEGRATION_SPEC.json']['ports'])
    cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(project), '--force'],
                        capture_output=True, text=True)
    return cr, cp


@pytest.mark.parametrize('depth', [2, 3])
def test_current_source_phase_admission_positive(tmp_path, depth):
    text = FIXTURE.read_text().replace('| 2 |', f'| {depth} |')
    if depth == 3:
        text = text.replace('two rising clock edges', 'three rising clock edges')
    docs = _emit(tmp_path, text)
    cr, cp = _consume(tmp_path, docs)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert cr['sync'] is False
    assert cr['release_clock'] == 'clk_i'
    assert cr['release_stages'] == depth
    assert len(cr['domain_bindings']) == 2
    decks = list((tmp_path / 'phase2/stage1/fpga').glob('*.sdc'))
    assert decks
    for p in decks:
        text = p.read_text()
        assert 'set_false_path' not in text
        assert f'release=synchronous to clk_i stages={depth}' in text
        assert f'release=synchronous to clk_aux_i stages={depth}' in text
    # Exercise the real common-header consumer without a simulator, DUT or
    # reference TB: its selected-clock post-release wait must use this depth.
    import professional_tb_gen as T
    header = ast.parse(T._emit_common_header({'cr': cr, 'top': 'neutral_core',
                                            'ports': docs['L9_INTEGRATION_SPEC.json']['ports']}))
    reset = next(n for n in header.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_reset')
    assert isinstance(reset.body[-1], ast.For)
    assert reset.body[-1].iter.args[0].value == depth


@pytest.mark.parametrize('mutation', ['assertion', 'depth', 'missing', 'source', 'release_clock',
                                     'float_depth', 'projection_empty', 'basis', 'direction_and_missing'])
def test_current_source_phase_admission_refuses(tmp_path, mutation):
    import professional_tb_gen as T
    docs = _emit(tmp_path, FIXTURE.read_text())
    def visit(value):
        if isinstance(value, dict):
            if mutation == 'assertion':
                if 'assertion' in value: value['assertion'] = 'synchronous'
                if 'sync' in value: value['sync'] = 'synchronous'
            if mutation in ('depth', 'float_depth') and 'release_stages' in value:
                value['release_stages'] = 3 if mutation == 'depth' else 2.0
            if mutation in ('missing', 'direction_and_missing'):
                value.pop('domain_bindings', None); value.pop('reset_bindings', None)
            if mutation == 'direction_and_missing' and value.get('name') == 'rst_n':
                for key in ('direction', 'mode', 'io'):
                    if key in value: value[key] = 'output'
            if mutation == 'projection_empty' and 'reset_bindings' in value:
                value['reset_bindings'] = []
            if mutation == 'basis' and 'basis' in value:
                value['basis'][0]['quote'] = 'unrelated current input'
            if mutation == 'release_clock' and 'release_clock' in value:
                value['release_clock'] = 'clk_aux_i'
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    if mutation == 'source':
        path = tmp_path / 'input/docs/reset.md'
        path.write_text(path.read_text().replace('| asynchronous |', '| synchronous |'))
    else:
        for name, doc in docs.items():
            visit(doc)
            (tmp_path / 'phase1/generated_docs' / name).write_text(json.dumps(doc))
    before = {p: p.read_bytes() for p in (tmp_path / 'phase1/generated_docs').glob('*.json')}
    cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(tmp_path), '--force'],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr  # Base observes concrete rc0.
    assert 'RESET_PHASE_SOURCE_ADMISSION_REFUSED' in cp.stdout + cp.stderr
    with pytest.raises(ValueError, match='RESET_PHASE_SOURCE_ADMISSION_REFUSED'):
        T._load_clock_reset(tmp_path, docs['L9_INTEGRATION_SPEC.json']['ports'])
    assert all(p.read_bytes() == data for p, data in before.items())
