"""Current MMIO declarations join only their explicitly named source ports."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import known_answer_vector as kav


PROGRAMS = Path(__file__).resolve().parents[1]
PORT_TEXT = """# External Interface
The top module is neutral_unit.
| Signal | Width | Direction | Description |
|---|---|---|---|
| tick_i | 1 | input | rising-edge clock |
| select_i | 1 | input | register selection |
| write_i | 1 | input | write selection |
| index_i | 6 | input | register index |
| value_o | 16 | output | read value |
"""
PORTS = [dict(name=name, direction=direction, width=width,
              evidence='input/docs/ports.md') for name, direction, width in [
    ('tick_i', 'input', 1), ('select_i', 'input', 1), ('write_i', 'input', 1),
    ('index_i', 'input', 6), ('value_o', 'output', 16)]]
BINDING = 'Software accesses registers through select_i/write_i/index_i.'
DECLARATION = 'The peripheral adopts a **memory-mapped register file**.'


def transport(documents, ports=PORTS, owner=None):
    record = (kav.declared_mmio_interface(documents, ports) if owner is None else
              kav.declared_mmio_interface(documents, ports, owner=owner))
    l9 = {'interface_type': record['name'] if record else None,
          'interface_types': [record] if record else []}
    return kav.resolve_transport(l9, {})


@pytest.mark.parametrize('declaration', [
    DECLARATION,
    'The peripheral exposes a `memory-mapped register interface`.',
    '本裝置採用 **memory-mapped register file** 作為對外 command protocol。',
    '本装置使用 **memory mapped register interface**。',
])
def test_affirmative_markdown_and_bilingual_split_sources(declaration):
    documents = {'protocol.md': declaration + '\n' + BINDING,
                 'ports.md': PORT_TEXT}
    actual = transport(documents)
    assert actual['kind'] == 'memory_mapped_register', actual
    assert actual['ports'] == PORTS
    assert actual['citation'] == {'source': 'input/docs/protocol.md', 'line': 1,
                                  'quote': declaration}
    assert actual['author_handoff_required'] is True
    assert not {'driver', 'status', 'verdict', 'measured'} & set(actual)


@pytest.mark.parametrize('protocol', [
    'The guide discusses a memory-mapped register file.\n' + BINDING,
    'The peripheral does not adopt a memory-mapped register file.\n' + BINDING,
    '本裝置不採用 **memory-mapped register file**。\n' + BINDING,
    'Previously, the peripheral used a memory-mapped register file.\n' + BINDING,
    '舊版本採用 **memory-mapped register file**。\n' + BINDING,
    'For comparison, another device uses a memory-mapped register file.\n' + BINDING,
    '# Example\nThe peripheral uses a memory-mapped register file.\n' + BINDING,
    'For example, a peripheral uses a memory-mapped register file.\n' + BINDING,
    'The peripheral may use a memory-mapped register file.\n' + BINDING,
    'The old peripheral uses a memory-mapped register file.\n' + BINDING,
    'The peripheral used a memory-mapped register file.\n' + BINDING,
    DECLARATION,
    DECLARATION + '\nSoftware accesses registers through missing_i/write_i/index_i.',
    DECLARATION + '\nSoftware does not access registers through select_i/write_i/index_i.',
    DECLARATION + '\n' + BINDING + '\nThe peripheral has no memory-mapped register interface.',
], ids=['mention', 'denied', 'denied_bilingual', 'historical', 'historical_bilingual',
        'comparison', 'example_heading', 'example_clause', 'proposed', 'old', 'past_tense', 'no_named_binding',
        'missing_named_port', 'denied_named_binding', 'contradictory_declaration'])
def test_non_declarations_and_unbound_ports_keep_transport_undeclared(protocol):
    actual = transport({'protocol.md': protocol, 'ports.md': PORT_TEXT})
    assert actual['kind'] == 'undeclared', actual


@pytest.mark.parametrize('ports,source_text', [
    ([{**p, 'evidence': 'input/docs/foreign.md'} for p in PORTS], PORT_TEXT),
    (PORTS, PORT_TEXT.replace('| index_i | 6 | input |', '| other_i | 6 | input |')),
    (PORTS, PORT_TEXT.replace('| index_i | 6 | input |', '| index_i | 7 | input |')),
    (PORTS, PORT_TEXT + '| index_i | 7 | input | conflicting register index |\n'),
    (PORTS, '# Historical\n' + PORT_TEXT.replace('# External Interface', '## External Interface')),
    (PORTS, '# Example\n' + PORT_TEXT.replace('# External Interface', '## External Interface')),
])
def test_cross_source_join_requires_owning_typed_port_declarations(ports, source_text):
    actual = transport({'protocol.md': DECLARATION + '\n' + BINDING,
                        'ports.md': source_text}, ports)
    assert actual['kind'] == 'undeclared', actual


def test_explicit_wrong_port_binding_is_refused_even_in_the_declaration_source():
    actual = transport({'ports.md': DECLARATION + '\nUsing missing_i.\n\n' + PORT_TEXT})
    assert actual['kind'] == 'undeclared', actual


def test_conflicting_explicit_port_bindings_do_not_select_a_neighbor():
    ports = PORTS + [{**p, 'evidence': 'input/docs/other_ports.md'} for p in PORTS]
    actual = transport({'protocol.md': DECLARATION + '\n' + BINDING,
                        'ports.md': PORT_TEXT, 'other_ports.md': PORT_TEXT}, ports)
    assert actual['kind'] == 'undeclared', actual


@pytest.mark.parametrize('clause', [
    '本裝置未採用', '本裝置尚未採用', '本裝置曾採用', '本裝置原先採用',
    '本裝置可能採用', '本裝置可使用', '作為比較，其他裝置採用', '建議本裝置採用',
    '本裝置計畫採用', '本装置将采用', '本裝置考慮使用',
])
def test_mandarin_noncurrent_authority_does_not_declare_mmio(clause):
    actual = transport({'protocol.md': clause + ' **memory-mapped register file**。\n' + BINDING,
                        'ports.md': PORT_TEXT})
    assert actual['kind'] == 'undeclared', actual


@pytest.mark.parametrize('source_text', [
    PORT_TEXT.replace('Description', 'Reset value').replace(
        '| index_i | 6 | input | register index |', '| index_i | 7 | input | 6 |'),
    PORT_TEXT.replace('Description', 'Other domain').replace(
        '| index_i | 6 | input | register index |', '| index_i | 6 | output | input |'),
    PORT_TEXT.replace('Description', 'Bits'),
    '\n'.join(line for line in PORT_TEXT.splitlines() if not line.startswith(('| Signal', '|---'))),
])
def test_table_authority_cannot_come_from_unrelated_or_ambiguous_columns(source_text):
    actual = transport({'protocol.md': DECLARATION + '\n' + BINDING,
                        'ports.md': source_text})
    assert actual['kind'] == 'undeclared', actual


@pytest.mark.parametrize('shape', ['range', 'nbit', 'mixed_case_direction', 'reordered',
                                 'mandarin_header', 'type_and_direction'])
def test_explicit_typed_port_table_representations_keep_the_same_transport(shape):
    lines = []
    for raw in PORT_TEXT.splitlines():
        if not raw.startswith('|'):
            lines.append(raw)
            continue
        cells = [cell.strip() for cell in raw.strip('|').split('|')]
        if cells[0] in {p['name'] for p in PORTS}:
            if shape == 'range':
                cells[1] = '[' + str(int(cells[1]) - 1) + ':0]'
            elif shape == 'nbit':
                cells[1] += '-bit'
            elif shape == 'mixed_case_direction':
                cells[2] = cells[2].title()
        if shape == 'reordered':
            cells = [cells[3], cells[2], cells[0], cells[1]]
        elif shape == 'mandarin_header' and cells[0] == 'Signal':
            cells = ['訊號', '寬度', '方向', '描述']
        elif shape == 'type_and_direction':
            cells.append('Type' if cells[0] == 'Signal' else 'logic')
        lines.append('| ' + ' | '.join(cells) + ' |')
    actual = transport({'protocol.md': DECLARATION + '\n' + BINDING,
                        'ports.md': '\n'.join(lines)})
    assert actual['kind'] == 'memory_mapped_register', actual
    assert actual['ports'] == PORTS


@pytest.mark.parametrize('declaration', [
    'neutral_unit uses a memory-mapped register file.',
    '`neutral_unit` 採用 memory-mapped register file。',
    'The neutral_unit module implements a memory-mapped register interface.',
    'This peripheral exposes a memory-mapped register interface.',
    '本裝置採用 memory-mapped register file。',
    'A register peripheral with a memory-mapped register interface.',
])
def test_exact_owner_and_generic_current_subjects_keep_declared_transport(declaration):
    actual = transport({'protocol.md': declaration + '\n' + BINDING,
                        'ports.md': PORT_TEXT}, owner='neutral_unit')
    assert actual['kind'] == 'memory_mapped_register', actual


@pytest.mark.parametrize('declaration', [
    'neighbor_unit uses a memory-mapped register file.',
    'neighbor_unit 採用 memory-mapped register file。',
    'Neutral_unit uses a memory-mapped register file.',
    'neutral_unit compares its serial port with a memory-mapped register file.',
    'The peripheral has a helper with a memory-mapped register file.',
])
def test_named_foreign_or_indirect_subjects_cannot_supply_current_transport(declaration):
    actual = transport({'protocol.md': declaration + '\n' + BINDING,
                        'ports.md': PORT_TEXT}, owner='neutral_unit')
    assert actual['kind'] == 'undeclared', actual


@pytest.mark.parametrize('verb', ['have', 'use', 'implement', 'adopt', 'provide', 'expose'])
def test_current_owner_denials_block_an_affirmative_declaration(verb):
    denial = 'The peripheral does not ' + verb + ' a memory-mapped register interface.'
    actual = transport({'protocol.md': DECLARATION + '\n' + BINDING + '\n' + denial,
                        'ports.md': PORT_TEXT}, owner='neutral_unit')
    assert actual['kind'] == 'undeclared', actual


def run_phase1(tmp_path, protocol):
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'ports.md').write_text(PORT_TEXT)
    (docs / 'protocol.md').write_text(protocol)
    argv = [sys.executable, str(PROGRAMS / 'phase1_doc_one_shot_runner.py'),
            str(tmp_path), '--strict', '--ic-name', 'neutral_unit', '--pdk', 'sky130A']
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    (tmp_path / 'cli.stdout').write_text(result.stdout)
    (tmp_path / 'cli.stderr').write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    generated = tmp_path / 'phase1/generated_docs'
    l9 = json.loads((generated / 'L9_INTEGRATION_SPEC.json').read_text())
    l10 = json.loads((generated / 'L10_TEST_CASES.json').read_text())
    return l9, l10


@pytest.mark.parametrize('declaration', [
    'Another device uses a memory-mapped register file.',
    '其他裝置採用 memory-mapped register file。',
    'The peripheral compares its serial port with a memory-mapped register file.',
], ids=['foreign_en', 'foreign_zh', 'comparison_verb'])
def test_foreign_subject_or_comparison_does_not_reach_normal_l10(tmp_path, declaration):
    l9, l10 = run_phase1(tmp_path, declaration + '\n' + BINDING)
    actual = l10['known_answer_vector_census']['transport']
    assert actual['kind'] == 'undeclared', actual
    assert not l9['interface_types'], l9['interface_types']


@pytest.mark.parametrize('subject,expected', [
    ('The peripheral', 'undeclared'),
    ('neutral_unit', 'undeclared'),
    ('Another device', 'memory_mapped_register'),
    ('neighbor_unit', 'memory_mapped_register'),
])
def test_owner_denial_census_preserves_both_polarities_through_normal_l10(tmp_path, subject, expected):
    protocol = (DECLARATION + '\n' + BINDING + '\n' + subject
                + ' does not have a memory-mapped register interface.')
    l9, l10 = run_phase1(tmp_path, protocol)
    actual = l10['known_answer_vector_census']['transport']
    assert actual['kind'] == expected, actual
    assert (l9['interface_type'] == 'memory_mapped_register') == (expected == 'memory_mapped_register')


def test_normal_phase1_l9_to_l10_consumes_split_source_declaration(tmp_path):
    l9, l10 = run_phase1(tmp_path, DECLARATION + '\n' + BINDING)
    actual = l10['known_answer_vector_census']['transport']
    assert actual['kind'] == 'memory_mapped_register', actual
    assert l9['interface_type'] == actual['kind']
    assert actual['ports'] == l9['interface_types'][0]['ports']
    assert {p['name'] for p in actual['ports']} == {p['name'] for p in PORTS}
    assert {p['evidence'] for p in actual['ports']} == {'input/docs/ports.md'}
    assert actual['author_handoff_required'] is True
