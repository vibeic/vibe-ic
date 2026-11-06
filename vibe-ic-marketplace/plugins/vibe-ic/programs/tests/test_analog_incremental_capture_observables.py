"""Append-only normal capture observability, without native performance claims."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_incremental_capture as capture
from test_analog_incremental_capture import _template, _dump, _declaration


def _inputs(tmp_path):
    template, spec, topology = _template(tmp_path)
    text = template.read_text()
    begin, end = text.index('.subckt'), text.index('.ends conv') + len('.ends conv')
    netlist = tmp_path / 'delivered.sp'
    netlist.write_text(text[begin:end] + '\n')
    template.write_text(text[:begin] + '.include delivered.sp' + text[end:])
    settings = {'reset_node': 'xdut.reset_b', 'held_input_v': .8,
                'extra_node_voltages': {'nodes': ['vcm', 'n1', 'n2', 'vrefp', 'vrefn']}}
    return template, spec, topology, settings, netlist


def _prepare(inputs, destination):
    template, spec, topology, settings, netlist = inputs
    return capture.prepare_deck(template, spec, topology, settings, destination, netlist=netlist)


def test_default_deck_and_declaration_keep_exact_base_bytes(tmp_path):
    template, spec, topology, settings, _ = _inputs(tmp_path)
    settings.pop('extra_node_voltages')
    text, clock, declaration = capture.prepare_deck(template, spec, topology, settings, tmp_path)
    normalized = text.replace(str(tmp_path), '<TMP>')
    assert hashlib.sha256(normalized.encode()).hexdigest() == 'ee9f09dd6c6a0f751d1aea0ffab970b4dbffb721550da8a28369c7c673510c97'
    assert 'extra_node_voltages' not in declaration
    assert clock == pytest.approx((0, 1e-6, 1.8))


def test_source_bound_nodes_append_after_unchanged_prefix(tmp_path):
    inputs = _inputs(tmp_path)
    settings = inputs[3]
    text, _, declaration = _prepare(inputs, tmp_path)
    old = copy.deepcopy(settings)
    old.pop('extra_node_voltages')
    default, _, original = capture.prepare_deck(*inputs[:3], old, tmp_path)
    extra = declaration['extra_node_voltages']
    assert extra['nodes'] == settings['extra_node_voltages']['nodes']
    assert extra['netlist'] == {'path': str(inputs[4].resolve())}
    assert extra['columns'] == ['v(xdut.vcm)', 'v(xdut.n1)', 'v(xdut.n2)', 'v(vrefp)', 'v(vrefn)']
    assert declaration['native_timing'] == original['native_timing']
    suffix = ' ' + ' '.join(extra['columns'])
    assert text.replace(suffix, '') == default


@pytest.mark.parametrize('nodes', [[], ['unknown'], ['vcm', 'VCM'], ['vcm) .control'],
                                  ['vcm;quit'], ['vcm\nquit'], ['v(vcm)'], ['vcm+1'], ['ain']])
def test_invalid_or_duplicate_nodes_refuse_before_native(tmp_path, nodes):
    inputs = _inputs(tmp_path)
    inputs[3]['extra_node_voltages']['nodes'] = nodes
    with pytest.raises(ValueError, match='observable'):
        _prepare(inputs, tmp_path)


@pytest.mark.parametrize('fault', ['missing_netlist', 'unused_source', 'duplicate_instance',
                                  'wrong_subcircuit', 'duplicate_source_subcircuit'])
def test_source_or_declaration_mismatch_refuses(tmp_path, fault):
    inputs = list(_inputs(tmp_path))
    template, _, _, settings, netlist = inputs
    if fault == 'missing_netlist':
        inputs[4] = None
    elif fault == 'unused_source':
        template.write_text(template.read_text().replace('.include delivered.sp', ''))
    elif fault == 'duplicate_instance':
        template.write_text(template.read_text() + '\nxdut vdd 0 ain vrefp vrefn clk dout conv\n')
    elif fault == 'wrong_subcircuit':
        template.write_text(template.read_text().replace('dout conv', 'dout wrong'))
    elif fault == 'duplicate_source_subcircuit':
        netlist.write_text(netlist.read_text() * 2)
    with pytest.raises(ValueError, match='observable|DUPLICATE'):
        _prepare(inputs, tmp_path)


def _extended_dump(tmp_path, declaration, settings):
    path = _dump(tmp_path / 'extended.dat')
    original = path.read_text().splitlines()
    prefix = ['output', 'reset', 'input', *declaration['native_timing']['columns']]
    extra = {'netlist': {'path': '/synthetic/delivered.sp'},
             'nodes': ['vcm'], 'columns': ['v(xdut.vcm)'], 'prefix_columns': prefix}
    declaration['extra_node_voltages'] = extra
    settings['extra_node_voltages'] = {'nodes': ['vcm']}
    path.write_text(' '.join(['time', *prefix, *extra['columns']]) + '\n' +
                    '\n'.join(line + ' .61' for line in original[1:]))
    return path


def test_appended_finite_observables_leave_decode_exactly_unchanged(tmp_path):
    declaration, settings = _declaration(), {}
    original = capture.decode_capture(_dump(tmp_path / 'default.dat'), (1, 1, 1.2), declaration, settings)
    path = _extended_dump(tmp_path, declaration, settings)
    assert capture.decode_capture(path, (1, 1, 1.2), declaration, settings) == original


@pytest.mark.parametrize('fault', ['unknown_header', 'missing_header_column', 'reordered_header',
                                  'missing_row_column', 'undeclared_row_column', 'nonfinite',
                                  'settings_nodes', 'undeclared_capture'])
def test_appended_capture_or_declaration_mismatch_refuses(tmp_path, fault):
    declaration, settings = _declaration(), {}
    path = _extended_dump(tmp_path, declaration, settings)
    lines = path.read_text().splitlines()
    if fault == 'unknown_header':
        lines[0] = lines[0].replace('v(xdut.vcm)', 'v(xdut.other)')
    elif fault == 'missing_header_column':
        lines[0] = ' '.join(lines[0].split()[:-1])
    elif fault == 'reordered_header':
        fields = lines[0].split(); fields[-1], fields[-2] = fields[-2], fields[-1]
        lines[0] = ' '.join(fields)
    elif fault == 'missing_row_column':
        lines[2] = ' '.join(lines[2].split()[:-1])
    elif fault == 'undeclared_row_column':
        lines[2] += ' .9'
    elif fault == 'nonfinite':
        lines[2] = ' '.join(lines[2].split()[:-1] + ['nan'])
    elif fault == 'settings_nodes':
        settings['extra_node_voltages']['nodes'] = ['other']
    else:
        settings.pop('extra_node_voltages'); declaration.pop('extra_node_voltages')
    path.write_text('\n'.join(lines))
    with pytest.raises(ValueError, match='observable|header|columns|non-finite'):
        capture.decode_capture(path, (1, 1, 1.2), declaration, settings)
