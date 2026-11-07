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
