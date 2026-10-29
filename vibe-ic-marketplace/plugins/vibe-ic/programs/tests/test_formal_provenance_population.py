"""Citation repetition is not a new temporal requirement; source gaps stay open."""
import copy
import json
from pathlib import Path

import formal_harness_gen as generator


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def case(tmp_path):
    docs = tmp_path / 'phase1/generated_docs'
    put(docs / 'L3_PROTOCOL.json', {'no_opcodes_in_input': True})
    put(docs / 'L6_FSM.json', {'no_fsm_in_input': True})
    data = {'clock_and_reset_waveform': {
        'clocks': [{'name': 'clk', 'edge': 'posedge', 'semantic_provenance': {
            'edge': {'kind': 'convention', 'rule': 'default_positive_clock_edge'}}}],
        'resets': [{'name': 'rst', 'polarity': 'active_high', 'sync': 'synchronous',
                    'port_description': 'synchronous active-high',
                    'semantic_provenance': {
                        'sync': {'kind': 'explicit', 'basis': [{'quote': 'reset startup behavior not mapped'}]},
                        'polarity': {'kind': 'explicit', 'basis': [{'quote': 'reset startup behavior not mapped'}]}}}]}}
    path = docs / 'L8_TIMING_WAVEFORM.json'
    put(path, data)
    return path, data


def ids(declared):
    return {row['id'] for row in declared['obligations']}


def test_repeated_changed_citations_do_not_change_canonical_behavior_population(tmp_path):
    path, data = case(tmp_path)
    before = generator.declaration_obligations(tmp_path)
    changed = copy.deepcopy(data)
    reset = changed['clock_and_reset_waveform']['resets'][0]
    for field in ('sync', 'polarity'):
        reset['semantic_provenance'][field]['basis'] *= 5
        reset['semantic_provenance'][field]['basis'].append({'quote': 'scan shift uses a different clock and reset mode'})
    put(path, changed)
    after = generator.declaration_obligations(tmp_path)
    assert ids(before) == ids(after)
    assert not any('.semantic_provenance.' in oid for oid in ids(after))
    for name in ('name', 'polarity', 'sync', 'port_description'):
        assert 'L8.clock_and_reset_waveform.resets.0.' + name in ids(after)
    assert 'L8.clock_and_reset_waveform.clocks.0.edge' in ids(after)
    assert before['provenance_evidence'] != after['provenance_evidence']
    assert {r['id'] for r in before['provenance_gaps']} == {r['id'] for r in after['provenance_gaps']}
    assert all(r['status'] == 'NOT_DETERMINED' for r in after['provenance_gaps'])
    assert generator._unresolved_declaration_rows(after) == after['provenance_gaps']
    readback = generator._declaration_read_state(after)
    assert readback['provenance_evidence'] == after['provenance_evidence']
    assert readback['provenance_gaps'] == after['provenance_gaps']


def test_canonical_polarity_change_remains_a_different_required_claim(tmp_path):
    path, data = case(tmp_path)
    before = generator.declaration_obligations(tmp_path)
    data['clock_and_reset_waveform']['resets'][0]['polarity'] = 'active_low'
    put(path, data)
    after = generator.declaration_obligations(tmp_path)
    oid = 'L8.clock_and_reset_waveform.resets.0.polarity'
    a = next(r for r in before['obligations'] if r['id'] == oid)
    b = next(r for r in after['obligations'] if r['id'] == oid)
    assert a['program_rule']['claims'] != b['program_rule']['claims']
    assert b['program_rule']['claims'][0]['value'] == 'active_low'
    # The contradictory active-high port description is still a separate,
    # unchanged requirement; provenance cannot erase either source fact.
    desc = next(r for r in after['obligations'] if r['id'].endswith('.port_description'))
    assert desc['program_rule']['claims'][1]['value'] == 'active_high'


def test_changed_structured_reset_value_is_not_filtered_as_metadata(tmp_path):
    path, data = case(tmp_path)
    reset = data['clock_and_reset_waveform']['resets'][0]
    reset['reset_value'] = 0
    put(path, data)
    before = generator.declaration_obligations(tmp_path)
    reset['reset_value'] = 1
    put(path, data)
    after = generator.declaration_obligations(tmp_path)
    a = next(r for r in before['obligations'] if r['id'].endswith('.reset_value'))
    b = next(r for r in after['obligations'] if r['id'].endswith('.reset_value'))
    assert a['description'] != b['description']
    assert 'program_rule' not in b  # unsupported value requires author input, never implicit PASS


def test_real_new_output_alias_retains_its_reset_assertion_and_changed_value():
    rtl = '''module neutral(input clk, input rst, output p, output scan_out);
reg pr;
always @(posedge clk) if (rst) pr <= 1'b0; else pr <= ~pr;
assign p = pr;
assign scan_out = pr;
endmodule'''
    iface = generator.parse_module(rtl, 'neutral')
    props = generator.derive_reset_props(iface, 'rst', False)
    assert {p.output for p in props} == {'p', 'scan_out'}
    harness = generator.emit_harness(iface, 'clk', 'rst', False, props)
    assert "(p == '0)" in harness and "(scan_out == '0)" in harness
    mutated = generator.parse_module(rtl.replace("pr <= 1'b0", "pr <= 1'b1"), 'neutral')
    changed = generator.derive_reset_props(mutated, 'rst', False)
    assert {p.output: p.value for p in changed} == {'p': "1'b1", 'scan_out': "1'b1"}
    emitted = generator.emit_harness(mutated, 'clk', 'rst', False, changed)
    assert "(scan_out == 1'b1)" in emitted
