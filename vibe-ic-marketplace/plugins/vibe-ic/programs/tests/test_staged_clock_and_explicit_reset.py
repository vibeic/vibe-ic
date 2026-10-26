"""Public tiny documents exercise the ordinary Phase1 CLI, not an IC flow."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / 'fixtures/phase1_local'
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as D
import librelane_contract as LC


def _public_cli(tmp_path, fixture, source_name, *, sdc_override=None, source_override=None):
    root = FIXTURES / fixture
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    shutil.copyfile(root / source_name, docs / source_name)
    if source_override is not None:
        (docs / source_name).write_text(source_override)
    shutil.copyfile(root / 'context/physical_inputs.md', docs / 'physical_inputs.md')
    constraints = tmp_path / 'input/constraints'
    constraints.mkdir()
    target = constraints / 'constraints.sdc'
    shutil.copyfile(root / 'context/constraints.sdc', target)
    if sdc_override is not None:
        target.write_text(sdc_override)
    command = [sys.executable, str(PROGRAMS / 'phase1_doc_one_shot_runner.py'),
               str(tmp_path), '--ic-name', 'neutral_reset_control']
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    (tmp_path / 'cli.stdout').write_text(run.stdout)
    (tmp_path / 'cli.stderr').write_text(run.stderr)
    print('PUBLIC_CLI_PROCESS ' + json.dumps({'argv': command, 'returncode': run.returncode}))
    assert run.returncode == 0, run.stdout + run.stderr
    result = {name: json.loads((tmp_path / 'phase1/generated_docs' / (name + '.json')).read_text())
              for name in ['L1_DATASHEET', 'L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM',
                           'L9_INTEGRATION_SPEC']}
    print('PUBLIC_CLI_TYPED_OBSERVATION ' + json.dumps(result, sort_keys=True))
    return result


def test_public_cli_initializes_both_empty_l8_clock_domain_records(tmp_path):
    result = _public_cli(tmp_path, 'neutral_clock_sdc_bootstrap', '01-current-mixed-stages.md')
    expected = {'clk_fast_i': 16, 'clk_aux_i': 31}
    for layer in ['L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM', 'L9_INTEGRATION_SPEC']:
        rows = {row['name']: row for row in result[layer].get('clock_domains', [])}
        assert len(rows) == 2, rows
        assert set(rows) == set(expected)
        for clock, period in expected.items():
            assert rows[clock]['source_pin'] == clock
            assert rows[clock]['period_ns'] == period
            assert rows[clock]['evidence'] == 'input/constraints/constraints.sdc'
    waveform = result['L8_TIMING_WAVEFORM']['clock_and_reset_waveform']
    assert {row['name']: row['period_ns'] for row in waveform['clocks']} == expected
    reset = next(row for row in waveform['resets'] if row['name'] == 'sys_reset_n')
    bindings = {row['clock']: row for row in reset['domain_bindings']}
    assert bindings['clk_fast_i']['release_stages'] == 2
    assert bindings['clk_aux_i']['release_stages'] == 3


def test_public_cli_keeps_explicit_scalar_current_reset_without_inventing_release(tmp_path):
    result = _public_cli(tmp_path, 'neutral_named_legacy_reset', '02-current-legacy-with-history.md')
    resets = result['L9_INTEGRATION_SPEC'].get('reset_domains', [])
    assert len(resets) == 1, resets
    assert resets[0]['name'] == 'sys_reset_n'
    assert resets[0]['polarity'] == 'active_low'
    assert resets[0]['sync'] == 'asynchronous'
    assert not resets[0].get('domain_bindings')
    waveform = result['L8_TIMING_WAVEFORM']['clock_and_reset_waveform']
    assert [row['name'] for row in waveform['resets']] == ['sys_reset_n']
    assert not waveform['resets'][0].get('domain_bindings')


def test_public_cli_sdc_labels_do_not_become_physical_clock_pins(tmp_path):
    result = _public_cli(
        tmp_path, 'neutral_clock_sdc_bootstrap', '01-current-mixed-stages.md',
        sdc_override='create_clock -name fast_label -period 16 [get_ports {clk_fast_i}]\n'
                     'create_clock -name aux_label -period 31 [get_ports {clk_aux_i}]\n')
    for layer in ['L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM', 'L9_INTEGRATION_SPEC']:
        rows = result[layer]['clock_domains']
        assert {row['name']: row['source_pin'] for row in rows} == {
            'clk_fast_i': 'clk_fast_i', 'clk_aux_i': 'clk_aux_i'}
        assert {row['name']: row['period_ns'] for row in rows} == {
            'clk_fast_i': 16, 'clk_aux_i': 31}


def test_empty_clock_bootstrap_requires_a_declared_scalar_input(tmp_path):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    source = tmp_path / 'input/constraints/clocks.sdc'
    source.parent.mkdir(parents=True)
    source.write_text('create_clock -name absent -period 10 [get_ports missing_i]\n'
                      'create_clock -name bus -period 11 [get_ports bus_i]\n'
                      'create_clock -name out -period 12 [get_ports out_o]\n'
                      'create_clock -name valid_label -period 19 [get_ports actual_i]\n')
    ports = [{'name': name, 'direction': direction, 'width': width}
             for name, direction, width in [('bus_i', 'input', 2),
                                            ('out_o', 'output', 1),
                                            ('actual_i', 'input', 1)]]
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_ports': ports}))
    for layer in ['L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM']:
        (docs / (layer + '.json')).write_text(json.dumps({'clock_domains': []}))
    D._post_emit_sdc_constraints(tmp_path)
    for layer in ['L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM']:
        rows = json.loads((docs / (layer + '.json')).read_text())['clock_domains']
        assert len(rows) == 1
        assert (rows[0]['name'], rows[0]['source_pin'], rows[0]['period_ns']) == (
            'actual_i', 'actual_i', 19)


def _empty_l8_sdc_project(tmp_path, prose, sdc):
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'contract.md').write_text(prose)
    constraints = tmp_path / 'input/constraints'
    constraints.mkdir()
    (constraints / 'constraints.sdc').write_text(sdc)
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    (generated / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'neutral_counter', 'top_ports': [], 'ports': []}))
    (generated / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {}}))
    for name in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        (generated / f'{name}.json').write_text(json.dumps({'clock_domains': []}))
    return generated


def test_explicit_sole_clock_and_unique_sdc_bootstrap_empty_l8(tmp_path):
    generated = _empty_l8_sdc_project(
        tmp_path,
        '# Current contract\n\n`clk` is the sole clock, with a 10 ns period.\n',
        'create_clock -name clk -period 10 [get_ports clk]\n')
    D._post_emit_sdc_constraints(tmp_path)
    for name in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        rows = json.loads((generated / f'{name}.json').read_text())['clock_domains']
        assert rows == [{
            'name': 'clk', 'source_pin': 'clk',
            'domain_kind': 'primary', 'role': 'master',
            'freq_hz': 100_000_000, 'freq_mhz': 100.0, 'period_ns': 10.0,
            'source': 'input/constraints/*.sdc',
            'evidence': 'input/constraints/constraints.sdc',
            'subject_evidence': 'input/docs/contract.md',
            'reset_strategy': 'unspecified'}]
    emitted = LC.emit_config(
        tmp_path, 'neutral', tmp_path / 'phase3/librelane/config.json',
        synthesis_only=True)
    assert (emitted['CLOCK_PORT'], emitted['CLOCK_PERIOD']) == ('clk', 10.0)


@pytest.mark.parametrize(('prose', 'sdc'), [
    ('`clk` is the sole clock, with a 10 ns period.\n',
     'create_clock -name clk -period 12 [get_ports clk]\n'),
    ('`other_clk` is the sole clock, with a 10 ns period.\n',
     'create_clock -name clk -period 10 [get_ports clk]\n'),
    ('`clk` is the sole clock, with a 10 ns period.\n',
     'create_clock -name clk -period 10 [get_ports clk]\n'
     'create_clock -name aux -period 20 [get_ports aux]\n'),
], ids=['period_mismatch', 'name_mismatch', 'multiple_sdc_clocks'])
def test_explicit_sole_clock_does_not_override_ambiguous_or_mismatched_sdc(
        tmp_path, prose, sdc):
    generated = _empty_l8_sdc_project(tmp_path, prose, sdc)
    D._post_emit_sdc_constraints(tmp_path)
    for name in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        assert json.loads((generated / f'{name}.json').read_text())['clock_domains'] == []
    with pytest.raises(LC.Refusal, match='LL_CLOCK_AMBIGUOUS: 0 primary clocks'):
        LC.emit_config(
            tmp_path, 'neutral', tmp_path / 'phase3/librelane/config.json',
            synthesis_only=True)


@pytest.mark.parametrize('prose', [
    'If debug mode is disabled, `clk` is the sole clock, with a 10 ns period.\n',
    'It is not true that `clk` is the sole clock, with a 10 ns period.\n',
    ('`clk` is the sole clock, with a 10 ns period, or `aux` is the sole '
     'clock, with a 20 ns period.\n'),
], ids=['reviewer_conditional', 'outer_negated', 'alternative'])
def test_qualified_or_alternative_sole_clock_clause_is_not_authority(
        tmp_path, prose):
    generated = _empty_l8_sdc_project(
        tmp_path, prose,
        'create_clock -name clk -period 10 [get_ports clk]\n')
    D._post_emit_sdc_constraints(tmp_path)
    observed = {}
    for name in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        observed[name] = json.loads(
            (generated / f'{name}.json').read_text())['clock_domains']
        assert observed[name] == []
    with pytest.raises(
            LC.Refusal, match='LL_CLOCK_AMBIGUOUS: 0 primary clocks') as refusal:
        LC.emit_config(
            tmp_path, 'neutral', tmp_path / 'phase3/librelane/config.json',
            synthesis_only=True)
    print('CLOCK_AUTHORITY_REFUSAL_OBSERVATION ' + json.dumps({
        'prose': prose.strip(), 'clock_domains': observed,
        'consumer_refusal': str(refusal.value)}, sort_keys=True))


@pytest.mark.parametrize('prose', [
    ('If debug mode is disabled:\n'
     '- `clk` is the sole clock, with a 10 ns period.\n'),
    ('- Clock mode:\n'
     '  - `clk` is the sole clock, with a 10 ns period.\n'),
    ('If debug mode is disabled:\n\n'
     '- `clk` is the sole clock, with a 10 ns period.\n'),
    ('**If debug mode is disabled:**\n\n'
     '- `clk` is the sole clock, with a 10 ns period.\n'),
], ids=['reviewer_multiline_conditional', 'nested_list',
        'reviewer_blankline_parent', 'reviewer_emphasized_parent'])
def test_nonflat_structural_block_cannot_detach_clock_authority(
        tmp_path, prose):
    generated = _empty_l8_sdc_project(
        tmp_path, prose,
        'create_clock -name clk -period 10 [get_ports clk]\n')
    D._post_emit_sdc_constraints(tmp_path)
    observed = {}
    for name in ('L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        observed[name] = json.loads(
            (generated / f'{name}.json').read_text())['clock_domains']
        assert observed[name] == []
    with pytest.raises(
            LC.Refusal, match='LL_CLOCK_AMBIGUOUS: 0 primary clocks') as refusal:
        LC.emit_config(
            tmp_path, 'neutral', tmp_path / 'phase3/librelane/config.json',
            synthesis_only=True)
    print('CLOCK_AUTHORITY_STRUCTURAL_REFUSAL ' + json.dumps({
        'prose': prose.strip(), 'clock_domains': observed,
        'consumer_refusal': str(refusal.value)}, sort_keys=True))


def test_colon_heading_does_not_become_a_list_parent_qualifier(tmp_path):
    generated = _empty_l8_sdc_project(
        tmp_path,
        '# Clock configuration:\n\n'
        '- `clk` is the sole clock, with a 10 ns period.\n',
        'create_clock -name clk -period 10 [get_ports clk]\n')
    D._post_emit_sdc_constraints(tmp_path)
    rows = json.loads(
        (generated / 'L8_TIMING_WAVEFORM.json').read_text())['clock_domains']
    assert [(row['source_pin'], row['period_ns']) for row in rows] == [
        ('clk', 10.0)]
    emitted = LC.emit_config(
        tmp_path, 'neutral', tmp_path / 'phase3/librelane/config.json',
        synthesis_only=True)
    assert (emitted['CLOCK_PORT'], emitted['CLOCK_PERIOD']) == ('clk', 10.0)


def test_explicit_reset_role_without_timing_does_not_invent_semantics():
    doc = {'ports': [{'name': 'clear_i', 'direction': 'input', 'width': 1}]}
    D._v1_6_369_emit_reset_domains(doc, {'current.md': 'The current reset is clear_i.'})
    row = doc['reset_domains'][0]
    assert row['name'] == 'clear_i'
    assert row['polarity'] == row['sync'] == 'unknown'
    assert not row.get('domain_bindings')


@pytest.mark.parametrize('text', [
    'other_i is an asynchronous active-low reset.',
    'clear_i is not a reset; it is asynchronous active-low data.',
    'Previously clear_i was an asynchronous active-low reset.',
    'clear_i is active-low asynchronous data sampled during reset.',
], ids=['other_port', 'negated_role', 'historical', 'data_during_reset'])
def test_reset_role_is_exact_current_and_not_borrowed(text):
    doc = {'ports': [{'name': 'clear_i', 'direction': 'input', 'width': 1}]}
    D._v1_6_369_emit_reset_domains(doc, {'current.md': text})
    assert not doc.get('reset_domains')


def test_noncanonical_reset_role_requires_a_scalar_input():
    for direction, width in [('output', 1), ('input', 2), ('input', None)]:
        doc = {'ports': [{'name': 'clear_i', 'direction': direction, 'width': width}]}
        D._v1_6_369_emit_reset_domains(doc, {
            'current.md': 'clear_i is an asynchronous active-low reset.'})
        assert not doc.get('reset_domains')


def test_public_cli_explicitly_denied_reset_role_stays_data(tmp_path):
    result = _public_cli(
        tmp_path, 'neutral_named_legacy_reset', '02-current-legacy-with-history.md',
        source_override='# Current contract\n'
                        'Clock clk_control_i has period 27 ns.\n'
                        'No reset is sys_reset_n.\n'
                        'sys_reset_n is an asynchronous active-low data input.\n')
    assert 'sys_reset_n' not in {
        row['name'] for row in result['L9_INTEGRATION_SPEC'].get('reset_domains', [])}
