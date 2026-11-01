"""Native LEF roles bound the tap-spacing population on the fallback path."""
import json
from pathlib import Path
import pytest
import latchup_esd_spacing_check as L


@pytest.mark.parametrize('corner_class', ['ENDCAP BOTTOMLEFT', 'PAD', 'PAD AREAIO'])
def test_native_io_classes_are_excluded(tmp_path, corner_class):
    p = scene(tmp_path, corner_class)
    r = L._latchup_tap_spacing_check(p)
    assert r['n_std'] == 60
    assert r['lef_noncore_masters'] == ['edge']
    assert r['status'] == 'SPACING_OK_NECESSARY_NOT_SUFFICIENT'


def test_unknown_master_is_undecided(tmp_path):
    r = L._latchup_tap_spacing_check(scene(tmp_path, None))
    assert r['status'] == 'UNDECIDED'
    assert r['reason'] == 'LEF_CLASS_UNDETERMINED'
    assert r['unknown_masters'] == ['edge']


def test_genuine_far_core_still_fails(tmp_path):
    r = L._latchup_tap_spacing_check(scene(tmp_path, 'CORE'))
    assert r['status'] == 'WELLTAP_SPACING_GAP'
    assert r['reason'] == 'UNTAPPED_REGION'
    assert r['n_std'] == 61


def test_real_corner_fixture_declares_the_excluded_class():
    from _pad_ring import parse_lef_macro_classes
    data = (Path(__file__).parent / 'fixtures/perc_native_corner.lef').read_text()
    assert list(parse_lef_macro_classes(data).values()) == ['ENDCAP BOTTOMLEFT']


def scene(tmp_path, cls):
    routed = tmp_path / 'phase3/stage3/pnr/top.def'
    routed.parent.mkdir(parents=True)
    rows = [f'- i{i} logic + PLACED ( {i*100} 0 ) N ;' for i in range(60)]
    rows += ['- t tap + PLACED ( 0 0 ) N ;', '- e edge + PLACED ( 100000 100000 ) N ;']
    routed.write_text('UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 400000 400000 ) ;\nCOMPONENTS 62 ;\n'+'\n'.join(rows)+'\nEND COMPONENTS\nEND DESIGN\n')
    lef = tmp_path / 'native.lef'
    lef.write_text('MACRO logic\n CLASS CORE ;\nEND logic\nMACRO tap\n CLASS CORE WELLTAP ;\nEND tap\n'+('MACRO edge\n CLASS '+cls+' ;\nEND edge\n' if cls else 'MACRO edge\nEND edge\n'))
    report = tmp_path / 'reports/phase3/io_pad_chip_top.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'verdict':'WROTE','io_library_lefs':[str(lef)]}))
    return routed
