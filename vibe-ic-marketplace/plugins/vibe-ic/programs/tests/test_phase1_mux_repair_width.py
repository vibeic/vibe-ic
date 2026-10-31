"""Functional repair intent versus an explicitly buggy interface declaration."""
from pathlib import Path
import json

import pytest

import phase1_port_extract as ports
import phase1_doc_one_shot_runner as docs


def request(width=16, count=4, *, action='Repair the buggy implementation.',
            purpose=None, extra='', output='output result'):
    purpose = purpose or f'The following implementation is a {width}-bit {count}-to-1 multiplexer.'
    sw = (count - 1).bit_length()
    selector = 'input choose' if sw == 1 else f'input [{sw-1}:0] choose'
    inputs = ',\n'.join(f'input [{width-1}:0] source_{index}' for index in range(count))
    return (f'{purpose}\n{action}\n{extra}\n'
            f'module SelectWord(\n{selector},\n{inputs},\n{output}\n);\n'
            'assign result = source_0;\nendmodule\n')


def _widths(text):
    return {row['name']: row['width'] for row in ports.extract_code_block_ports(text)}


@pytest.mark.parametrize('width,count', [(16, 4), (12, 2), (7, 3)])
def test_debug_mux_recovers_the_declared_functional_data_width(width, count):
    found = _widths(request(width, count))
    assert found['result'] == width
    assert found['choose'] == (count-1).bit_length()
    assert all(found[f'source_{index}'] == width for index in range(count))


@pytest.mark.parametrize('kwargs', [
    {'action': 'Document this current implementation.'},
    {'extra': 'The scalar output is valid. The result must remain one bit.'},
    {'extra': 'The output must remain scalar.'},
    {'extra': 'Keep the existing interface unchanged.'},
    {'extra': 'The output reports the parity of the selected word.'},
    {'output': 'output [0:0] result'},
    {'purpose': 'This buggy module computes parity of a 16-bit data input.'},
])
def test_valid_scalar_and_non_mux_outputs_are_not_reinterpreted(kwargs):
    assert _widths(request(**kwargs))['result'] == 1


def test_ambiguous_sibling_module_cannot_supply_an_output_width():
    text = request() + '\nmodule OtherBlock(input [63:0] sibling, output [63:0] result); endmodule\n'
    assert _widths(text)['result'] == 1


def test_inconsistent_data_inputs_do_not_confirm_a_repair_dimension():
    text = request().replace('input [15:0] source_3', 'input [31:0] source_3')
    assert _widths(text)['result'] == 1


def test_recovered_width_retains_both_authorities():
    row = next(p for p in ports.extract_code_block_ports(request()) if p['name'] == 'result')
    assert row['declared_width'] == 1
    assert row['source_line'] == 'output result'
    assert row['width_recovery']['functional_intent'] == '16-bit 4-to-1 multiplexer'
    assert row['width_recovery']['module'] == 'SelectWord'


def test_l1_to_all_l9_port_consumers_receive_the_repaired_dimension(tmp_path):
    extracted = {'repair.md': request()}
    generated = tmp_path / 'phase1/generated_docs'
    generated.mkdir(parents=True)
    docs.gen_l1_datasheet(tmp_path, extracted)
    docs.gen_l9_integration_spec(tmp_path, extracted, {})
    l1 = json.loads((generated / 'L1_DATASHEET.json').read_text())
    l9 = json.loads((generated / 'L9_INTEGRATION_SPEC.json').read_text())
    target = next(row for row in l1['pin_table'] if row['name'] == 'result')
    assert target['width'] == 16
    for key in ('top_ports', 'ports', 'top_module_pins'):
        by_name = {row['name']: row for row in l9[key]}
        assert by_name['result']['width'] == 16
        assert by_name['result']['declared_width'] == 1
        assert by_name['result']['width_recovery'] == target['width_recovery']
        assert by_name['choose']['width'] == 2
    import phase2_scaffold_gen as consumer
    signals = {row['name']: row for row in consumer.derive_signals({}, l9)}
    assert signals['result']['width'] == 16
    assert signals['choose']['width'] == 2


def test_table_evidence_cannot_be_borrowed_as_the_buggy_header_shape():
    table = '| Name | Direction | Width |\n|---|---|---|\n| source_0 | input | 16 |\n| source_1 | input | 16 |\n'
    text = request(16, 2).replace('[15:0]', '[31:0]') + table
    assert _widths(text)['result'] == 1


def test_compact_header_preserves_the_same_repair_authority():
    text = request(12, 2)
    prose, code = text.split('module ', 1)
    compact = prose + 'module ' + ' '.join(code.splitlines())
    assert _widths(compact)['result'] == 12
