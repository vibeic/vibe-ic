"""Finite public event prose through ordinary L9 and its L8 consumers."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
import ic_class_profile as C
import l8_clock_reset_waveform_emit as W

FIXTURES = Path(__file__).parent / 'fixtures/phase1_local/typed_event_provenance'


def _ordinary(project, body, clock='clk', reset='rst'):
    text = ('Module name:\nneutral_control\nInput ports:\n'
            f'{clock}: Clock signal.\n{reset}: Reset signal.\n'
            'data_i: 1-bit input data.\nOutput ports:\n'
            'data_o: 1-bit output data.\nImplementation:\n' + body + '\n')
    source = project / 'input/docs/contract.txt'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    extracted = {'contract.txt': text}
    D.gen_l1_datasheet(project, extracted)
    D.gen_l8_timing_waveform(project, extracted)
    D.gen_l9_integration_spec(project, extracted, {})
    D.gen_l8_timing_waveform_doc(project, extracted)
    D._post_emit_typed_clock_domains(project)
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    D._post_emit_derive_l9_clocks_v1_6_323(project)
    D._post_emit_seed_l8b_clocks_from_l1_v1_6_571(project)
    D._post_emit_mirror_clock_resets_to_l9_v1_6_311(project)
    D._post_emit_l8_clock_reset_waveform(project)
    docs = project / 'phase1/generated_docs'
    return text, {name: json.loads((docs / (name + '.json')).read_text())
                  for name in ('L1_DATASHEET', 'L8_RTL_CONSTANTS',
                               'L8_TIMING_WAVEFORM', 'L9_INTEGRATION_SPEC')}


@pytest.mark.parametrize('fixture,clock,reset,polarity', [
    ('positive_reset.txt', 'CLK', 'RST', 'active_high'),
    ('falling_reset.txt', 'clk', 'rst_n', 'active_low'),
    ('unnamed_reset.txt', 'clk', 'rst_n', 'active_low'),
])
def test_public_event_list_reaches_typed_l9_and_l8(tmp_path, fixture, clock, reset, polarity):
    body = (FIXTURES / fixture).read_text().strip()
    text, docs = _ordinary(tmp_path, body, clock, reset)
    l9 = docs['L9_INTEGRATION_SPEC']
    row = next(r for r in l9['reset_domains'] if r['name'] == reset)
    assert (row['sync'], row['polarity']) == ('asynchronous', polarity), row
    assert row['semantic_provenance']['sync']['kind'] == 'explicit'
    basis = row['semantic_provenance']['sync']['basis']
    assert any(b['quote'] == body and b['sha256'] == hashlib.sha256(text.encode()).hexdigest()
               and b['file'] == 'input/docs/contract.txt' for b in basis), basis
    assert not row.get('domain_bindings'), row  # no invented release/guard/frequency
    for name in ('L9_INTEGRATION_SPEC', 'L8_RTL_CONSTANTS', 'L8_TIMING_WAVEFORM'):
        clocks = docs[name]['clocks'] if name == 'L9_INTEGRATION_SPEC' else docs[name]['clock_domains']
        record = next(r for r in clocks if r['name'] == clock)
        assert record['edge'] == 'posedge', record
        assert record['semantic_provenance']['edge']['kind'] == 'explicit', record
    waveform = docs['L8_TIMING_WAVEFORM']['clock_and_reset_waveform']
    assert waveform['resets'][0]['sync'] == 'asynchronous'
    assert waveform['resets'][0]['semantic_provenance'] == row['semantic_provenance']
    assert waveform['clocks'][0]['semantic_provenance']['edge']['kind'] == 'explicit'


def test_clock_only_event_does_not_invent_async_reset(tmp_path):
    _, docs = _ordinary(tmp_path, 'always @(negedge clk) data_o <= data_i;')
    row = docs['L9_INTEGRATION_SPEC']['reset_domains'][0]
    assert row['sync'] == 'unknown', row
    assert row['semantic_provenance']['sync']['kind'] == 'unspecified'
    waveform = docs['L8_TIMING_WAVEFORM']['clock_and_reset_waveform']
    assert waveform['clocks'][0]['edge'] == 'negedge', waveform
    assert waveform['clocks'][0]['semantic_provenance']['edge']['kind'] == 'explicit'


def test_unstated_defaults_keep_convention_provenance_through_l8(tmp_path):
    _, docs = _ordinary(tmp_path, 'The output follows the input.')
    row = docs['L9_INTEGRATION_SPEC']['reset_domains'][0]
    assert (row['polarity'], row['sync']) == ('active_high', 'unknown'), row
    assert row['semantic_provenance']['polarity']['kind'] == 'convention'
    assert row['semantic_provenance']['sync']['kind'] == 'unspecified'
    waveform = docs['L8_TIMING_WAVEFORM']['clock_and_reset_waveform']
    assert waveform['resets'][0]['semantic_provenance'] == row['semantic_provenance']
    assert waveform['clocks'][0]['edge'] == 'posedge'
    assert waveform['clocks'][0]['semantic_provenance']['edge']['kind'] == 'convention'
    assert not waveform['clocks'][0].get('period_ns')


def test_event_denial_history_conflict_and_other_reset_are_not_borrowed():
    from _reset_input_semantics import reset_semantics
    assert reset_semantics('rst', 'clk: Clock signal.\nrst: Reset signal.\n'
                           'Previously always @(posedge clk or posedge rst).') == {}
    assert reset_semantics('rst', 'clk: Clock signal.\nrst: Reset signal.\n'
                           'Do not use always @(posedge clk or posedge rst).') == {}
    assert reset_semantics('rst', 'clk: Clock signal.\nrst: Reset signal.\n'
                           'always @(posedge clk or negedge other_rst).') == {}
    values = reset_semantics('rst', 'clk: Clock signal.\nrst: Reset signal.\n'
                             'rst is synchronous active-high.\n'
                             'always @(posedge clk or negedge rst).')
    assert values == {'sync': 'unknown', 'polarity': 'unknown'}, values


def test_unnamed_events_do_not_borrow_roles_from_another_document():
    l9 = {'ports': [{'name': 'rst', 'direction': 'input', 'width': 1}]}
    D._v1_6_369_emit_reset_domains(l9, {
        'interface.txt': 'clk: Clock signal.\nrst: Reset signal.\n',
        'independent.txt': 'On the positive edge of the clock or the negative edge of the reset signal, update data.\n'})
    row = l9['reset_domains'][0]
    assert row['sync'] == 'unknown', row
    assert row['semantic_provenance']['sync']['kind'] == 'unspecified', row


def test_temporal_location_in_is_not_an_inch_but_units_survive(tmp_path):
    body = ('For shift counts greater than 0 and less than 17, if the bit at position i-1 in the multiplicand register (areg) is high, the product register (yout_r) accumulates the shifted value of the multiplier register (breg) by shifting it left by i-1 positions and appending zeros at the least significant bit positions.\n'
            'The ring counter follows a cyclic pattern where exactly one bit is set to 1 in the output at any given time, and the 1 shifts to the next bit with each clock pulse.\n'
            'A package measures 2 in wide and 4 mm high; use a 3 inch enclosure.\n')
    D.gen_l1_datasheet(tmp_path, {'contract.txt': body})
    D._harvest_vendor_short_literals(tmp_path, {'contract.txt': body})
    doc = json.loads((tmp_path / 'phase1/generated_docs/L1_DATASHEET.json').read_text())
    dimensions = {r['literal'] for r in doc['vendor_short_literals'] if r['kind'] == 'dimension'}
    assert dimensions == {'2in', '4mm', '3inch'}, dimensions


@pytest.mark.parametrize('description,expected', [
    ('Implement an ALU for a 32-bit MIPS-ISA CPU.', 'digital_arithmetic_primitive'),
    ('Implement a RISC-V CPU with an ALU, instruction fetch and program counter.', 'processor_cpu'),
])
def test_actual_l1_identifier_harvest_cannot_launder_host_context(tmp_path, description, expected):
    extracted = {'contract.txt': '# Overview\n' + description + '\n'}
    D.gen_l1_datasheet(tmp_path, extracted)
    D.gen_l2_frs(tmp_path, extracted)
    D._backfill_auto_literals_into_typed(tmp_path, extracted)
    assert C.infer_ic_class_uncached(tmp_path)['ic_class'] == expected
    # The supported refresh persists the ordinary reader's answer; no input
    # owner declaration or layer is rewritten to manufacture classification.
    assert C.detect_ic_class(tmp_path, refresh=True)['ic_class'] == expected


def test_explicit_layer_class_path_is_never_refreshed_as_generated(tmp_path):
    gd = tmp_path / 'phase1/generated_docs'
    gd.mkdir(parents=True)
    (gd / 'L1_DATASHEET.json').write_text(json.dumps({'class_path': 'owner_selected_class'}))
    D._post_emit_ic_class_into_L9_L1(tmp_path, 'digital_arithmetic_primitive')
    assert json.loads((gd / 'L1_DATASHEET.json').read_text())['class_path'] == 'owner_selected_class'
