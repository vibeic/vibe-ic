import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_bound_measurements as bound


@pytest.fixture
def circuit():
    text = ('* delivered\n.subckt ota vdd vss in out\n'
            'xinput n1 sum tail vss nmos w=48u l=1u ng=5\n'
            'xtail tail bias vss vss nmos w=8u l=1u\n'
            'xcc nz out cmim w=10u l=27.99u\n'
            'xrz n1 nz vss rppd w=0.5u l=5.77u\n.ends ota\n')
    declaration = {'kind':'split_gate','source_sha256':hashlib.sha256(text.encode()).hexdigest(),
                   'instance':'xdut','gates':[{'device':'xinput','terminal':'G','terminal_index':1,
                                              'model':'nmos','source_node':'sum','probe_node':'probe_g'}],
                   'ports':[{'node':'probe_g','top_node':'g'},{'node':'sum','top_node':'s'}]}
    return text, declaration


def test_reconnection_preserves_every_device_terminal_model_and_value(circuit):
    original, declaration = circuit
    view, audit = bound.instrument_split_gate_view(original, declaration)
    assert audit['device_count'] == 4
    assert audit['reconnection'] == 'EXACT_ALL_DELIVERED_DEVICE_CARDS'
    assert bound.validate_split_gate_reconnection(original, view, declaration) == audit
    assert next(m for m in audit['all_device_mapping'] if m['device']=='xrz')['original_pins'] == ['n1','nz','vss']
    assert next(m for m in audit['all_device_mapping'] if m['device']=='xcc')['original_pins'] == ['nz','out']
    assert view.replace('vdd vss in out probe_g sum','vdd vss in out').replace('n1 probe_g tail','n1 sum tail') == original


@pytest.mark.parametrize('replacement', [
    ('l=5.77u','l=5.78u'), ('n1 nz vss rppd','n1 nz vdd rppd'),
    ('xtail tail bias','xtail tail sum'), ('xcc nz out','xcc n1 out')])
def test_additional_changes_are_refused(circuit, replacement):
    original, declaration = circuit
    view, _ = bound.instrument_split_gate_view(original, declaration)
    with pytest.raises(ValueError, match='wrong or additional changes'):
        bound.validate_split_gate_reconnection(original, view.replace(*replacement), declaration)


@pytest.mark.parametrize('field,value', [('terminal','D'),('terminal_index',0),('source_node','bias'),('model','pmos')])
def test_wrong_original_pin_or_model_is_refused(circuit, field, value):
    original, declaration = circuit
    declaration['gates'][0][field] = value
    with pytest.raises(ValueError):
        bound.instrument_split_gate_view(original, declaration)


def test_actual_consumer_refuses_wrong_source_before_native(tmp_path, circuit):
    original, declaration = circuit
    netlist, template = tmp_path/'ota.sp', tmp_path/'tb.sp'
    netlist.write_text(original)
    template.write_text('* test\n.include ota.sp\nxdut vdd 0 in out ota\n.end\n')
    declaration = copy.deepcopy(declaration)
    declaration['source_sha256'] = '0'*64
    def forbidden(*args, **kwargs):
        pytest.fail('invalid source reached native execution')
    report = bound.run_measurements(tmp_path, netlist, template,
                                    {'instrumentation':declaration}, tmp_path/'result', forbidden)
    assert report['status'] == 'NOT_MEASURED'
    assert 'source hash' in report['detail']
    assert report['executions'] == []


def test_actual_consumer_refuses_unknown_physical_port_before_native(tmp_path, circuit):
    original, declaration = circuit
    netlist, template = tmp_path/'ota.sp', tmp_path/'tb.sp'
    netlist.write_text(original)
    template.write_text('* test\n.include ota.sp\nxdut vdd 0 in out ota\n.end\n')
    declaration['ports'].append({'node':'unknown','top_node':'extra'})
    def forbidden(*args, **kwargs):
        pytest.fail('invalid port reached native execution')
    report = bound.run_measurements(tmp_path, netlist, template,
                                    {'instrumentation':declaration}, tmp_path/'result', forbidden)
    assert report['status'] == 'NOT_MEASURED'
    assert 'undeclared new physical node' in report['detail']
    assert report['executions'] == []


def test_model_includes_resolve_from_original_delivered_directory(tmp_path, circuit):
    original, declaration = circuit
    original = '.lib ../../../input/pdk/models/corner.lib tt\n' + original
    declaration['source_sha256'] = hashlib.sha256(original.encode()).hexdigest()
    source = tmp_path/'case/phase3/analog/ota'
    view, audit = bound.instrument_split_gate_view(original, declaration, source)
    assert str(tmp_path/'case/input/pdk/models/corner.lib') in view
    assert audit['source_sha256'] == declaration['source_sha256']
    bound.validate_split_gate_reconnection(original, view, declaration, source)
