import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner


HEAD = ('The block clock operates at 31.25 MHz.\n'
        'The auxiliary reference runs at 10 MHz.\n')
TABLE = ('| Instance | Clock port | Top clock pin |\n'
         '|---|---|---|\n'
         '| lane_a | clk | i_clk0 |\n'
         '| lane_b | clk | i_clk1 |\n')


def emit(project, text):
    source = project / 'input/docs/clock_contract.txt'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'pin_table': [
        {'name': 'i_clk0', 'mode': 'input'},
        {'name': 'i_clk1', 'mode': 'input'}]}))
    extracted = {source.name: text}
    runner.gen_l8_timing_waveform(project, extracted)
    runner.gen_l9_integration_spec(project, extracted, {})
    runner._post_emit_typed_clock_domains(project)
    runner._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    return json.loads((docs / 'L8_RTL_CONSTANTS.json').read_text())


@pytest.mark.parametrize('restatement', ['', 'The block clock operates at 31.25 MHz.\n'],
                         ids=['landing_probe', 'same_period_repeated'])
def test_bound_top_pins_keep_the_documented_block_period(tmp_path, restatement):
    l8 = emit(tmp_path, HEAD + restatement + TABLE)
    domains = {domain['source_pin']: domain for domain in l8['clock_domains']}
    assert 'clk' not in domains
    for pin in ('i_clk0', 'i_clk1'):
        domain = domains[pin]
        assert domain['freq_hz'] == pytest.approx(31_250_000)
        assert domain['freq_mhz'] == pytest.approx(31.25)
        assert domain['period_ns'] == pytest.approx(32)
        evidence = domain['evidence']
        assert evidence['file'] == 'input/docs/clock_contract.txt'
        assert evidence['line'] == 1
        assert '31.25 MHz' in evidence['matched_substring']
        assert evidence['matched_substring'] in HEAD.splitlines()[0]


@pytest.mark.parametrize('text', [
    HEAD + 'The block clock operates at 20 MHz.\n' + TABLE,
    'domain clk_fast 31.25 MHz\ndomain clk_slow 20 MHz\n'
    '| Instance | Clock port | Top clock pin |\n'
    '|---|---|---|\n'
    '| lane_a | clk_fast | i_clk0 |\n'
    '| lane_b | clk_slow | i_clk0 |\n',
    HEAD + 'domain i_clk0 20 MHz\n' + TABLE,
    'The block clock operates at 31.25 MHz and the block clock operates at 20 MHz.\n' + TABLE,
    'The block clock period is 32 ns and the block clock period is 50 ns.\n' + TABLE,
    'The block clock operates at 31.25 MHz or at 20 MHz.\n' + TABLE,
    'The block clock period is 32 ns or is 50 ns.\n' + TABLE,
], ids=['one_block_two_periods', 'one_pin_two_block_periods', 'bound_pin_period_conflict',
        'two_frequency_declarations_same_sentence', 'two_period_declarations_same_sentence',
        'frequency_alternative', 'period_alternative'])
def test_ambiguous_clock_binding_periods_refuse_by_name(tmp_path, text):
    with pytest.raises(ValueError, match='LL_CLOCK_BINDING_AMBIGUOUS'):
        emit(tmp_path, text)


@pytest.mark.parametrize('statement', [
    'The block clock has a setup time of 2 ns.\n',
    'The block clock does not operate at 20 MHz.\n',
], ids=['setup_is_not_period', 'negation_is_not_rate'])
def test_non_clock_timing_cannot_supply_bound_periods(tmp_path, statement):
    try:
        l8 = emit(tmp_path, statement + TABLE)
    except ValueError as exc:
        assert 'LL_CLOCK_BINDING_' in str(exc)
        return
    for domain in l8['clock_domains']:
        if domain.get('source_pin') in ('i_clk0', 'i_clk1'):
            assert domain.get('freq_hz') is None
            assert domain.get('period_ns') is None


@pytest.mark.parametrize('statement', [
    'The block clock period is 32 ns.\n',
    'The block clock period is 32 ns, with a setup time of 2 ns.\n',
    'The block clock operates at 31.25 MHz, with an auxiliary reference at 10 MHz.\n',
], ids=['period_literal', 'setup_is_separate', 'auxiliary_rate_is_separate'])
def test_bound_period_uses_only_the_clock_declaration(tmp_path, statement):
    l8 = emit(tmp_path, statement + TABLE)
    domains = {domain['source_pin']: domain for domain in l8['clock_domains']}
    for pin in ('i_clk0', 'i_clk1'):
        assert domains[pin]['period_ns'] == pytest.approx(32)
        assert domains[pin]['freq_hz'] == pytest.approx(31_250_000)
        assert domains[pin]['evidence']['matched_substring'] == statement.strip()


def test_repeating_post_emit_keeps_bound_period_provenance_stable(tmp_path):
    l8 = emit(tmp_path, HEAD + TABLE)
    runner._post_emit_typed_clock_domains(tmp_path)
    after = json.loads((tmp_path / 'phase1/generated_docs/L8_RTL_CONSTANTS.json').read_text())
    assert after['clock_domains'] == l8['clock_domains']
