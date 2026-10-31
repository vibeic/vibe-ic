"""Only explicit same-carrier terminal geometry can resolve a port-only net.

Neutral source controls, not native extraction or signoff qualification.
"""
import hashlib
import json
from pathlib import Path

import pytest
import drv_signoff_annotation as annotation


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _subject(tmp_path, case):
    name = 'unloaded[3]'
    pins = {name: {'kind': 'port', 'cell_class': 'port', 'cell': None,
                   'cell_pin': None, 'liberty': None, 'driver_pin': name,
                   'driver_cell': None, 'net': name}}
    (tmp_path/'annotation.rpt').write_text('Found 1 unannotated drivers.\n'+name+'\n\nFound 0 partially unannotated drivers.\n')
    lef = tmp_path/'pins.lef'
    lef.write_text('MACRO logic\n CLASS CORE ;\n PIN Y\n USE SIGNAL ;\n PORT\n LAYER M1 ;\n RECT 0 0 1 1 ;\n END\n END Y\nEND logic\n')
    lib = tmp_path/'pins.lib'
    lib.write_text('library (unit) { time_unit : "1ns"; capacitive_load_unit (1,pf); cell (logic) { pin (Y) { direction : output; max_transition : 1; } } }')
    body = 'VERSION 5.8 ;\nDESIGN unit ;\nUNITS DISTANCE MICRONS 1000 ;\nPINS 1 ;\n- '+name+' + NET '+name+' + DIRECTION INPUT + USE SIGNAL + PORT + LAYER M1 ( -2 -1 ) ( 2 1 ) + PLACED ( 10 20 ) N ;\nEND PINS\nNETS 1 ;\n- '+name+' ( PIN '+name+' ) + USE SIGNAL ;\nEND NETS\nEND DESIGN\n'
    if case == 'routed': body = body.replace(' + USE SIGNAL ;\nEND NETS', ' + ROUTED M1 ( 0 0 ) ( 10 0 ) + USE SIGNAL ;\nEND NETS')
    elif case == 'missing_def_net': body = body.replace('- '+name+' ( PIN '+name+' ) + USE SIGNAL ;', '')
    elif case == 'wrong_pin_net': body = body.replace('+ NET '+name, '+ NET foreign')
    elif case == 'missing_geometry': body = body.replace(' + PORT + LAYER M1 ( -2 -1 ) ( 2 1 ) + PLACED ( 10 20 ) N', '')
    elif case == 'foreign_design': body = body.replace('DESIGN unit ;', 'DESIGN foreign ;')
    elif case == 'extra_def_endpoint': body = body.replace('( PIN '+name+' )', '( PIN '+name+' ) ( core A )')
    definition = tmp_path/'routed.def'; definition.write_text(body)
    spef = tmp_path/'route.spef'
    spef.write_text('*SPEF "ieee 1481-1999"\n*DESIGN "unit"\n*DIVIDER /\n*DELIMITER :\n*NAME_MAP\n*1 '+name+'\n*PORTS\n*1 I\n')
    if case == 'missing_spef_port': spef.write_text(spef.read_text().replace('*1 I\n',''))
    if case == 'foreign_spef_net': spef.write_text(spef.read_text()+'*D_NET other 0\n*CONN\n*P *1 I\n*END\n')
    cap = ' Wire capacitance: 0\n'
    if case == 'missing_wire_cap': cap = ''
    if case == 'nonzero_wire_cap': cap = ' Wire capacitance: 0.1\n'
    (tmp_path/'net_census.rpt').write_text('Net '+name+'\n'+cap+' Total capacitance: 0.19\n Number of drivers: 1\n Number of loads: 0\n Number of pins: 1\n\nDriver pins\n '+name+' input port\n\n')
    receipt = {'schema':'vibeic.spef_extraction_receipt.v1',
               'routed_def_sha256':_sha(definition),'spef_sha256':_sha(spef)}
    if case == 'foreign_receipt': receipt['routed_def_sha256'] = '0'*64
    if case != 'missing_receipt': (tmp_path/'spef_extraction_receipt.json').write_text(json.dumps(receipt))
    return pins, [{'path':str(lib)}], [{'path':str(lef)}], definition, spef


@pytest.mark.parametrize('case', ['same_net', 'routed', 'missing_def_net', 'wrong_pin_net',
    'missing_geometry', 'foreign_design', 'extra_def_endpoint', 'missing_spef_port',
    'foreign_spef_net', 'missing_wire_cap', 'nonzero_wire_cap', 'foreign_receipt',
    'missing_receipt'])
def test_port_terminal_annotation_requires_all_bound_proofs(tmp_path, case):
    args = _subject(tmp_path, case)
    result = annotation.derive(tmp_path, *args)
    (tmp_path/'OBSERVATION.json').write_text(json.dumps(result,indent=2)+'\n')
    if case == 'same_net':
        assert result['unresolved'] == []
        assert len(result['resolved']) == 1
        assert result['resolved'][0]['reason'] == 'port_terminal_zero_interconnect'
        assert result['resolved'][0]['net'] == 'unloaded[3]'
        assert result['resolved'][0]['wire_cap_pf'] == 0
    else:
        assert result['resolved'] == []
        assert result['unresolved'] == [{'pin':'unloaded[3]','net':'unloaded[3]',
                                        'reason':'missing_parasitic_or_geometry_proof'}]
