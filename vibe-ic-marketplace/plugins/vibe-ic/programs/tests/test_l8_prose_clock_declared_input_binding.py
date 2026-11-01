"""The prose clock producer must bind one declared input, not invent its pin."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as runner


def emit(tmp_path, pins, text="| Target clock period | 32 ns (31.25 MHz) |\n"):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'pin_table': pins}))
    runner.gen_l8_timing_waveform(tmp_path, {'product_overview.md': text})
    runner._post_emit_typed_clock_domains(tmp_path)
    return json.loads((docs / 'L8_RTL_CONSTANTS.json').read_text())


@pytest.mark.parametrize('name', ['i_clk', 'clk_i', 'in_clock', 'clk'])
def test_prose_target_binds_the_single_declared_input_clock(tmp_path, name):
    doc = emit(tmp_path, [{'name': name, 'mode': 'input'}])
    domains = doc['clock_domains']
    assert len(domains) == 1
    assert domains[0]['name'] == name
    assert domains[0]['source_pin'] == name
    assert domains[0]['period_ns'] == pytest.approx(32)


def test_output_clock_does_not_displace_the_declared_input(tmp_path):
    doc = emit(tmp_path, [{'name': 'o_clk', 'mode': 'output'},
                          {'name': 'i_clk', 'mode': 'input'}])
    assert doc['clock_domains'][0]['source_pin'] == 'i_clk'


def test_multiple_declared_inputs_do_not_guess_the_prose_target(tmp_path):
    doc = emit(tmp_path, [{'name': 'i_clk0', 'mode': 'input'},
                          {'name': 'i_clk1', 'mode': 'input'}])
    assert doc['clock_domains'][0]['source_pin'] == 'clk'


def test_no_declared_input_keeps_the_existing_unbound_prose_record(tmp_path):
    doc = emit(tmp_path, [{'name': 'data', 'mode': 'input'}])
    assert doc['clock_domains'][0]['source_pin'] == 'clk'


def test_explicit_domain_name_keeps_its_own_identity(tmp_path):
    doc = emit(tmp_path, [{'name': 'i_clk', 'mode': 'input'}],
               'domain clk_aux 31.25 MHz\n')
    assert doc['clock_domains'][0]['name'] == 'clk_aux'
    assert doc['clock_domains'][0]['source_pin'] == 'clk_aux'


def _emit_block_clock_bindings(project, text, pins):
    source = project / 'input/docs/clock_contract.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    if pins is None:
        runner.gen_l1_datasheet(project, {source.name: text})
    else:
        (docs / 'L1_DATASHEET.json').write_text(json.dumps({'pin_table': pins}))
    extracted = {source.name: text}
    runner.gen_l8_timing_waveform(project, extracted)
    runner.gen_l9_integration_spec(project, extracted, {})
    runner._post_emit_typed_clock_domains(project)
    runner._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    return tuple(json.loads((docs / (name + '.json')).read_text())
                 for name in ('L8_RTL_CONSTANTS', 'L9_INTEGRATION_SPEC'))


_BLOCK_CLOCK_TABLE = (
    'The block clock operates at 31.25 MHz.\n'
    '| Instance | Clock port | Top clock pin |\n'
    '|---|---|---|\n'
    '| lane_a | clk | i_clk0 |\n'
    '| lane_b | clk | i_clk1 |\n')


def test_block_clock_bindings_do_not_create_an_extra_top_clock(tmp_path):
    l8, l9 = _emit_block_clock_bindings(tmp_path, _BLOCK_CLOCK_TABLE, [
        {'name': 'i_clk0', 'mode': 'input'},
        {'name': 'i_clk1', 'mode': 'input'}])
    assert l9.get('clock_binding', {}) == {'lane_a': 'i_clk0', 'lane_b': 'i_clk1'}
    assert {d['source_pin'] for d in l8['clock_domains']} == {'i_clk0', 'i_clk1'}
    assert {d['source_pin'] for d in l9['clock_domains']} == {'i_clk0', 'i_clk1'}
    evidence = l9['extraction_evidence']['clock_binding']
    assert {e['block_clock_port'] for e in evidence} == {'clk'}
    assert all(e['file'] == 'input/docs/clock_contract.md' for e in evidence)


@pytest.mark.parametrize('rows,problem', [
    ('| lane_a | clk | i_clk1 |\n', 'conflicting clock binding'),
    ('| lane_c | clk | absent_clock |\n', 'undeclared top input'),
])
def test_block_clock_bindings_refuse_invalid_connections(tmp_path, rows, problem):
    with pytest.raises(ValueError, match=problem):
        _emit_block_clock_bindings(tmp_path, _BLOCK_CLOCK_TABLE + rows, [
            {'name': 'i_clk0', 'mode': 'input'},
            {'name': 'i_clk1', 'mode': 'input'}])


def test_block_clock_bindings_keep_a_real_top_pin_named_clk(tmp_path):
    text = _BLOCK_CLOCK_TABLE.replace('i_clk0', 'clk')
    l8, l9 = _emit_block_clock_bindings(tmp_path, text, [
        {'name': 'clk', 'mode': 'input'},
        {'name': 'i_clk1', 'mode': 'input'}])
    assert l9.get('clock_binding', {}) == {'lane_a': 'clk', 'lane_b': 'i_clk1'}
    assert {d['source_pin'] for d in l8['clock_domains']} == {'clk', 'i_clk1'}


def test_block_clock_bindings_use_the_checked_in_interface(tmp_path):
    from programs.tests._hostpaths import require_repo
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                           'tests', 'fixtures', 'phase1_local',
                           'neutral_clock_sdc_bootstrap', 'context', 'physical_inputs.md')
    text = fixture.read_text() + '\n' + _BLOCK_CLOCK_TABLE.replace(
        'i_clk0', 'clk_fast_i').replace('i_clk1', 'clk_aux_i')
    l8, l9 = _emit_block_clock_bindings(tmp_path, text, None)
    assert l9.get('clock_binding', {}) == {'lane_a': 'clk_fast_i', 'lane_b': 'clk_aux_i'}
    assert {d['source_pin'] for d in l8['clock_domains']} == {'clk_fast_i', 'clk_aux_i'}
