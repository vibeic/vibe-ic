"""Native corner selection follows the PDK's include and library references."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import path_spice_tool as pst


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_corner_includes_are_resolved_from_each_including_file(tmp_path):
    tech = tmp_path / 'libs.tech/ngspice'
    library = put(tech / 'process.lib.spice',
                  '.lib tt\n.include "corners/tt.spice"\n.endl tt\n'
                  '.lib ss\n.include "corners/ss.spice"\n.endl ss\n'
                  '.lib ss_mm\n.include "corners/ss.spice"\n.endl ss_mm\n')
    for corner in ('tt', 'ss'):
        put(tech / f'corners/{corner}.spice',
            f'.include "../../../libs.ref/devices/{corner}.spice"\n')
        put(tmp_path / f'libs.ref/devices/{corner}.spice',
            '.subckt native_fet d g s b\n.ends\n.model native_diode d\n')
    result = pst.model_file(tech, '/pdk/libs.tech/ngspice', 'ngspice',
                            'cells__ss_125C.lib', {'native_fet', 'native_diode'},
                            125, tmp_path / 'models.sp')
    assert result['sections'] == [[str(library), 'ss']]
    assert '.lib /pdk/libs.tech/ngspice/process.lib.spice ss' in Path(result['path']).read_text()


def test_library_reference_keeps_its_path_and_section(tmp_path):
    library = put(tmp_path / 'm.ngspice',
                  '.lib ss\n.lib "nested/m.ngspice" slow\n.endl ss\n'
                  '.lib tt\n.lib "nested/m.ngspice" typical\n.endl tt\n')
    put(tmp_path / 'nested/m.ngspice',
        '.lib slow\n.subckt slow_fet d g s b\n.ends\n.endl slow\n'
        '.lib typical\n.subckt typical_fet d g s b\n.ends\n.endl typical\n')
    sections = pst.model_sections(tmp_path, 'ngspice')
    assert sections[str(library), 'ss'] == {'slow_fet'}
    assert sections[str(library), 'tt'] == {'typical_fet'}


def test_include_cycles_do_not_supply_an_absent_device(tmp_path):
    put(tmp_path / 'm.ngspice', '.lib ss\n.include "a.spice"\n.endl ss\n')
    put(tmp_path / 'a.spice', '.include "b.spice"\n.model present d\n')
    put(tmp_path / 'b.spice', '.include "a.spice"\n')
    with pytest.raises(pst.Refusal, match='absent'):
        pst.model_file(tmp_path, '/pdk', 'ngspice', 'cells__ss.lib',
                       {'absent'}, None, tmp_path / 'out.sp')


def test_library_closure_preludes_are_not_included_twice(tmp_path):
    put(tmp_path / 'models.ngspice', '.lib ss\n.include "corners/ss.spice"\n.endl ss\n')
    put(tmp_path / 'corners/ss.spice', '.include "../devices.ngspice"\n')
    put(tmp_path / 'devices.ngspice', '.param native_scale=1\n'
        '.subckt native_fet d g s b\n.ends\n')
    put(tmp_path / 'design.ngspice', '.param independent_switch=0\n')
    result = pst.model_file(tmp_path, '/pdk', 'ngspice', 'cells__ss.lib',
                            {'native_fet'}, None, tmp_path / 'out.sp')
    text = Path(result['path']).read_text()
    assert '.include /pdk/devices.ngspice' not in text
    assert '.include /pdk/design.ngspice' in text


def test_native_multiline_subcircuit_ports_and_calls_are_folded_together(tmp_path):
    source = put(tmp_path / 'pads.cdl',
                 '.SUBCKT pad\n+ A Y VDD\n+ VSS VNW\n'
                 'Xdevice Y A VSS\n+ VNW native_fet\n+ w=1 l=0.5\n.ENDS\n')
    result = pst.fold_subckts([source], {'VDD': 3.3, 'VSS': 0, 'VNW': 3.3},
                              'VDD', 'VSS', tmp_path / 'folded.spice')
    text = Path(result['path']).read_text()
    assert '.subckt pad A Y VDD VSS' in text
    assert ' Xdevice Y A VSS VDD native_fet w=1 l=0.5' in text
    assert pst.device_names(text) == {'native_fet'}


def test_nested_calls_keep_the_folded_child_terminal_order(tmp_path):
    source = put(tmp_path / 'pads.spice',
                 '.subckt wrapper A Y VDD VSS\n'
                 'Xnested A Y VDD VSS VSS child\n.ends\n'
                 '.subckt child A Y VP VSSA VSS\n'
                 'Xfet Y A VSSA VSS native_fet w=1 l=0.5\n.ends\n')
    result = pst.fold_subckts([source], {'VDD': 3.3, 'VSS': 0, 'VP': 3.3, 'VSSA': 0},
                              'VDD', 'VSS', tmp_path / 'folded.spice')
    text = Path(result['path']).read_text()
    assert '.subckt child A Y VSS VDD' in text
    assert 'Xnested A Y VSS VDD child' in text
