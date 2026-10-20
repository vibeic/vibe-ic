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


def _emit(project, text, clocks=('clk_i', 'clk_aux_i')):
    source = project / 'input/docs/reset.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    sdc = project / 'input/constraints/clocks.sdc'
    sdc.parent.mkdir(parents=True)
    sdc.write_text(''.join(f'create_clock -name {clock} -period {20 + i * 12} '
                           f'[get_ports {clock}]\n' for i, clock in enumerate(clocks)))
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


_NONCURRENT_PHASE_INPUTS = {'denied_note': '# NeutralCore\n\nThe module **`reset_bridge`** has the following hardware interfaces defined.\n\n| Signal | Direction | Type | Width | Description |\n|---|---|---|---:|---|\n| clk_i | input | logic | 1 | Main rising-edge clock, period 20 ns. |\n| clk_aux_i | input | logic | 1 | Auxiliary rising-edge clock, period 32 ns. |\n| rst_n | input | logic | 1 | System-supplied active-low global reset for both clock domains. |\n| ready_o | output | logic | 1 | Ready output. |\n\n## Current legacy reset contract\n\nrst_n is an active-low asynchronous reset. Separate release stages are not specified.\n\n## Non-binding comparison table\n\n| Clock | Reset | Polarity | Assertion | Release | Release synchronizer stages | Note |\n|---|---|---|---|---|---:|---|\n| clk_i | rst_n | active-low | asynchronous | synchronous to clk_i | 2 | Not a current implementation requirement |\n| clk_aux_i | rst_n | active-low | asynchronous | synchronous to clk_aux_i | 2 | Not a current implementation requirement |\n', 'historical_heading': '# NeutralCore\n\nThe module **`reset_bridge`** has the following hardware interfaces defined.\n\n| Signal | Direction | Type | Width | Description |\n|---|---|---|---:|---|\n| clk_i | input | logic | 1 | Main rising-edge clock, period 20 ns. |\n| clk_aux_i | input | logic | 1 | Auxiliary rising-edge clock, period 32 ns. |\n| rst_n | input | logic | 1 | System-supplied active-low global reset for both clock domains. |\n| ready_o | output | logic | 1 | Ready output. |\n\n## Current legacy reset contract\n\nrst_n is an active-high synchronous reset. Separate release stages are not specified.\n\n## Historical comparison\n\nThe following obsolete alternative is not the current implementation.\n\n| Clock | Reset | Polarity | Assertion | Release | Release synchronizer stages | Note |\n|---|---|---|---|---|---:|---|\n| clk_i | rst_n | active-low | asynchronous | synchronous to clk_i | 2 | Alternative only |\n| clk_aux_i | rst_n | active-low | asynchronous | synchronous to clk_aux_i | 2 | Alternative only |\n'}


@pytest.mark.parametrize('scope', ['denied_note', 'historical_heading'])
def test_noncurrent_phase_table_preserves_legacy_and_is_not_admission_authority(tmp_path, scope):
    import professional_tb_gen as T
    import _reset_input_semantics as R
    text = _NONCURRENT_PHASE_INPUTS[scope]
    project = tmp_path / 'legacy'
    docs = _emit(project, text)
    reset = next(r for r in docs['L9_INTEGRATION_SPEC.json']['reset_domains'] if r['name'] == 'rst_n')
    assert reset.get('domain_bindings', []) == [], reset
    expected = 'synchronous' if scope == 'historical_heading' else 'asynchronous'
    assert reset['sync'] == expected, reset
    assert R.reset_semantics('rst_n', text)['sync'] == expected
    cr, cp = _consume(project, docs)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert cr['sync'] is (expected == 'synchronous')
    assert 'release_stages' not in cr

    # A stale typed projection cannot legitimize the denied table merely by
    # citing its actual line and quote. Both normal consumers must refuse it.
    stale = tmp_path / 'stale'
    stale_docs = _emit(stale, FIXTURE.read_text())
    (stale / 'input/docs/reset.md').write_text(text)
    table_rows = {clock: (number, line) for number, line in enumerate(text.splitlines(), 1)
                  for clock in ('clk_i', 'clk_aux_i') if line.startswith('| ' + clock + ' |')}
    def retarget_basis(value):
        if isinstance(value, dict):
            if 'basis' in value and value.get('clock') in table_rows:
                number, line = table_rows[value['clock']]
                value['basis'] = [{'file': 'input/docs/reset.md', 'line': number, 'quote': line}]
            for child in value.values():
                retarget_basis(child)
        elif isinstance(value, list):
            for child in value:
                retarget_basis(child)
    for name, doc in stale_docs.items():
        retarget_basis(doc)
        (stale / 'phase1/generated_docs' / name).write_text(json.dumps(doc))
    before = {p: p.read_bytes() for p in (stale / 'phase1/generated_docs').glob('*.json')}
    cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(stale), '--force'],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert 'RESET_PHASE_SOURCE_ADMISSION_REFUSED' in cp.stdout + cp.stderr
    with pytest.raises(ValueError, match='RESET_PHASE_SOURCE_ADMISSION_REFUSED'):
        T._load_clock_reset(stale, stale_docs['L9_INTEGRATION_SPEC.json']['ports'])
    assert all(p.read_bytes() == data for p, data in before.items())


def test_current_phase_no_enable_note_keeps_the_declared_release(tmp_path):
    text = (FIXTURE.read_text()
            .replace('Release synchronizer stages |', 'Release synchronizer stages | Note |')
            .replace('|---:|', '|---:|---|')
            .replace('| 2 |', '| 2 | No enable signal is required |'))
    docs = _emit(tmp_path, text)
    cr, cp = _consume(tmp_path, docs)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert cr['release_stages'] == 2
    assert cr['sync'] is False
    assert len(cr['domain_bindings']) == 2


_PHASE_SENTENCE = ('rst_n remains the same active-low system reset for both domains, '
                   'with asynchronous assertion and separate two-stage synchronous release.')
_PHASE_PROSE = [
    ('verbatim', _PHASE_SENTENCE, True),
    ('table_only', '', True),
    ('numeric_prefix', 'rst_n has asynchronous assertion and 2-stage synchronous release.', True),
    ('suffix_with_word', 'rst_n has synchronous release with two stages.', True),
    ('suffix_through_number', 'rst_n has synchronous release through 2 stages.', True),
    ('phase_first', 'rst_n assertion is asynchronous and release is synchronous.', True),
    ('release_first', 'rst_n has two-stage synchronous release and asynchronous assertion.', True),
    ('explicit_clock', 'rst_n has synchronous release to core_clock through 2 stages.', True),
    ('explicit_both_clocks', 'rst_n has synchronous release to core_clock and entropy_clock.', True),
    ('targets_mixed_or', 'rst_n has asynchronous assertion and synchronous release to core_clock or absent_clock.', False),
    ('targets_mixed_slash', 'rst_n has asynchronous assertion and synchronous release to core_clock / absent_clock.', False),
    ('targets_mixed_on_or', 'rst_n has asynchronous assertion and synchronous release on core_clock or absent_clock.', False),
    ('targets_no_space_slash', 'rst_n has synchronous release to core_clock/absent_clock.', False),
    ('targets_upper_or', 'rst_n has synchronous release to core_clock OR absent_clock.', False),
    ('targets_ambiguous_admitted_or', 'rst_n has synchronous release to core_clock or entropy_clock.', False),
    ('targets_ambiguous_admitted_slash', 'rst_n has synchronous release to core_clock/entropy_clock.', False),
    ('targets_oxford_absent', 'rst_n has synchronous release to core_clock, and absent_clock.', False),
    ('targets_and_then_or_absent', 'rst_n has synchronous release to core_clock and entropy_clock or absent_clock.', False),
    ('targets_pipe_absent', 'rst_n has synchronous release to core_clock | absent_clock.', False),
    ('targets_ampersand_absent', 'rst_n has synchronous release to core_clock & absent_clock.', False),
    ('targets_dangling_and', 'rst_n has synchronous release to core_clock and.', False),
    ('targets_dangling_comma', 'rst_n has synchronous release to core_clock,.', False),
    ('targets_valid_single', 'rst_n has asynchronous assertion and synchronous release to core_clock.', True),
    ('targets_valid_and', 'rst_n has asynchronous assertion and synchronous release to core_clock and entropy_clock.', True),
    ('targets_valid_comma', 'rst_n has asynchronous assertion and synchronous release to core_clock, entropy_clock.', True),
    ('targets_valid_oxford', 'rst_n has asynchronous assertion and synchronous release to core_clock, and entropy_clock.', True),
    ('targets_valid_backticks', 'rst_n has synchronous release to `core_clock`, and `entropy_clock`.', True),
    ('targets_valid_repeated', 'rst_n has synchronous release to core_clock and to entropy_clock.', True),
    ('targets_valid_before_depth', 'rst_n has synchronous release to core_clock and entropy_clock through 2 stages.', True),
    ('after_depth_valid_multiclock', 'rst_n has asynchronous assertion and synchronous release through 2 stages to core_clock and entropy_clock.', True),
    ('after_depth_wrong_clock', 'rst_n has asynchronous assertion and synchronous release through 2 stages to absent_clock.', False),
    ('after_depth_valid_on_multiclock', 'rst_n has synchronous release through 2 stages on core_clock and entropy_clock.', True),
    ('after_depth_wrong_on_clock', 'rst_n has synchronous release through 2 stages on absent_clock.', False),
    ('after_depth_mixed_multiclock', 'rst_n has synchronous release through 2 stages to core_clock and absent_clock.', False),
    ('after_depth_repeated_target', 'rst_n has synchronous release to core_clock through 2 stages to absent_clock.', False),
    ('after_depth_valid_repeated_target', 'rst_n has synchronous release to core_clock through 2 stages to entropy_clock.', True),
    ('after_depth_before_invalid_target', 'rst_n has synchronous release to absent_clock through 2 stages to core_clock and entropy_clock.', False),
    ('another_reset', 'other_reset has asynchronous release.\n' + _PHASE_SENTENCE, True),
    ('wrong_assertion', 'rst_n has synchronous assertion and synchronous release.', False),
    ('wrong_release', 'rst_n has asynchronous assertion and asynchronous release.', False),
    ('wrong_polarity', _PHASE_SENTENCE.replace('active-low', 'active-high'), False),
    ('wrong_clock', 'rst_n has synchronous release to absent_clock.', False),
    ('additional_wrong_clock', 'rst_n has synchronous release to core_clock and absent_clock.', False),
    ('wrong_prefix_word', 'rst_n has three-stage synchronous release.', False),
    ('wrong_prefix_number', 'rst_n has 3-stage synchronous release.', False),
    ('wrong_suffix_with_word', 'rst_n has synchronous release with three stages.', False),
    ('wrong_suffix_through_number', 'rst_n has synchronous release through 3 stages.', False),
    ('wrong_clock_depth', 'rst_n has synchronous release to core_clock through 3 stages.', False),
    ('unknown_depth', 'rst_n has synchronous release with unspecified stages.', False),
    ('fractional_depth', 'rst_n has synchronous release through 2.2 stages.', False),
    ('compound_depth', 'rst_n has twenty-two-stage synchronous release.', False),
    ('alternative_depth', 'rst_n has synchronous release through 3 or 2 stages.', False),
    ('bounded_depth', 'rst_n has synchronous release through at least 2 stages.', False),
    ('conflicting_depth', 'rst_n has two-stage synchronous release through 3 stages.', False),
    ('denied_assertion', 'rst_n does not have asynchronous assertion.', False),
    ('denied_release', 'rst_n does not have synchronous release.', False),
    ('legacy_ambiguity', 'rst_n is an active-low synchronous/asynchronous reset.', False),
    ('phase_ambiguity', 'rst_n has asynchronous/synchronous release.', False),
    ('unphased_conflict', _PHASE_SENTENCE + '\nrst_n is synchronous.', False),
    ('residual_conflict', 'rst_n has asynchronous assertion and synchronous release and synchronous reset.', False),
]


@pytest.mark.parametrize('case,prose,accepted', _PHASE_PROSE, ids=[row[0] for row in _PHASE_PROSE])
def test_phase_prose_reaches_ordinary_reset_consumers(tmp_path, case, prose, accepted):
    from programs.tests._hostpaths import require_repo
    import professional_tb_gen as T
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'phase1_local', 'neutral_reset_phase_prose',
                           'neutral_reset_phase_prose.md')
    text = fixture.read_text().replace(_PHASE_SENTENCE, prose)
    docs = _emit(tmp_path, text, clocks=('core_clock', 'entropy_clock'))
    before = {p: p.read_bytes() for p in (tmp_path / 'phase1/generated_docs').glob('*.json')}
    cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(tmp_path), '--force'],
                        capture_output=True, text=True)
    assert cp.returncode == (0 if accepted else 1), cp.stdout + cp.stderr
    if accepted:
        cr = T._load_clock_reset(tmp_path, docs['L9_INTEGRATION_SPEC.json']['ports'])
        assert cr['sync'] is False
        assert cr['active_high'] is False
        bindings = cr['domain_bindings']
        assert {row['clock'] for row in bindings} == {'core_clock', 'entropy_clock'}
        for row in bindings:
            assert (row['assertion'], row['release'], row['release_clock'],
                    row['release_stages'], row['polarity']) == (
                        'asynchronous', 'synchronous', row['clock'], 2, 'active_low')
        decks = list((tmp_path / 'phase2/stage1/fpga').glob('*.sdc'))
        assert decks
        for deck in decks:
            emitted = deck.read_text()
            assert 'release=synchronous to core_clock stages=2' in emitted
            assert 'release=synchronous to entropy_clock stages=2' in emitted
            assert 'set_false_path' not in emitted
    else:
        assert 'RESET_PHASE_SOURCE_ADMISSION_REFUSED' in cp.stdout + cp.stderr
        with pytest.raises(ValueError, match='RESET_PHASE_SOURCE_ADMISSION_REFUSED'):
            T._load_clock_reset(tmp_path, docs['L9_INTEGRATION_SPEC.json']['ports'])
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('prose,accepted', [
    ('rst_n has two-stage synchronous release.', False),
    ('rst_n has two-stage synchronous release to core_clock.', True),
    ('rst_n has synchronous release to entropy_clock through 3 stages.', True),
], ids=['shared_depth_conflict', 'core_depth_matches', 'entropy_depth_matches'])
def test_prose_depth_is_checked_against_its_own_domain(tmp_path, prose, accepted):
    text = FIXTURE.read_text().replace('clk_aux_i', 'entropy_clock').replace('clk_i', 'core_clock')
    text = text.replace('| synchronous to entropy_clock | 2 |', '| synchronous to entropy_clock | 3 |')
    docs = _emit(tmp_path, text + '\n' + prose, clocks=('core_clock', 'entropy_clock'))
    if accepted:
        cr, cp = _consume(tmp_path, docs)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert {row['clock']: row['release_stages'] for row in cr['domain_bindings']} == {
            'core_clock': 2, 'entropy_clock': 3}
    else:
        import professional_tb_gen as T
        cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(tmp_path), '--force'],
                            capture_output=True, text=True)
        assert cp.returncode == 1, cp.stdout + cp.stderr
        with pytest.raises(ValueError, match='RESET_PHASE_SOURCE_ADMISSION_REFUSED'):
            T._load_clock_reset(tmp_path, docs['L9_INTEGRATION_SPEC.json']['ports'])


def test_current_prose_change_refuses_stale_generated_phase_values(tmp_path):
    import professional_tb_gen as T
    text = FIXTURE.read_text() + '\nrst_n has synchronous release through 2 stages.\n'
    docs = _emit(tmp_path, text)
    _, cp = _consume(tmp_path, docs)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    before = {p: p.read_bytes() for p in (tmp_path / 'phase1/generated_docs').glob('*.json')}
    source = tmp_path / 'input/docs/reset.md'
    source.write_text(text.replace('through 2 stages', 'through 3 stages'))
    cp = subprocess.run([sys.executable, str(PROGRAMS / 'sdc_gen.py'), str(tmp_path), '--force'],
                        capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert 'RESET_PHASE_SOURCE_ADMISSION_REFUSED' in cp.stdout + cp.stderr
    with pytest.raises(ValueError, match='RESET_PHASE_SOURCE_ADMISSION_REFUSED'):
        T._load_clock_reset(tmp_path, docs['L9_INTEGRATION_SPEC.json']['ports'])
    assert all(p.read_bytes() == data for p, data in before.items())
