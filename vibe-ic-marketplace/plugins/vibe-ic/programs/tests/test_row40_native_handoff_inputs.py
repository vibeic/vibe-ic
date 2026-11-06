"""Source-only adapter transport controls. No physical geometry credit."""

import pytest
from test_pdk_registry_resolves_inside_the_eda_container import _fake_pdk, _p3








def test_in_image_registry_uses_the_attested_selected_pdk_root(in_image, tmp_path, monkeypatch):
    m = _p3()
    tree = _fake_pdk(tmp_path)
    monkeypatch.setenv('PDK_ROOT', str(tree.parent))
    registry = {'name': tree.name, 'container_path': '/absent/legacy/pdks/' + tree.name,
                'liberty_glob': 'libs.ref/scl/lib/*tt*.lib',
                'tech_lef_glob': 'libs.ref/scl/techlef/*.tlef',
                'cell_lef_glob': 'libs.ref/scl/lef/*.lef', 'tapcell_master': None}
    resolved = m._pdk_config_from_registry(tmp_path, registry)
    assert resolved is not None, 'selected PDK exists under the attested image root, legacy alias does not'
    assert resolved.liberty == str(tree / 'libs.ref/scl/lib/scl__tt_025C_1v80.lib')
    assert resolved.tech_lef == str(tree / 'libs.ref/scl/techlef/scl__nom.tlef')




@pytest.mark.parametrize('layout', ['paired', 'split', 'foreign', 'escaped_asset', 'broken', 'cycle'])
def test_in_image_composed_pdk_keeps_one_selected_family_root(in_image, tmp_path, monkeypatch, layout):
    m = _p3()
    installed = _fake_pdk(tmp_path / 'installed')
    (installed / 'libs.tech').mkdir()
    root = tmp_path / 'composed' / installed.name
    root.mkdir(parents=True)
    refs = installed / 'libs.ref'
    tech = installed / 'libs.tech'
    if layout == 'split':
        tech = tmp_path / 'other' / installed.name / 'libs.tech'
        tech.mkdir(parents=True)
    elif layout == 'foreign':
        foreign = tmp_path / 'other' / 'foreignFamily'
        foreign.mkdir(parents=True)
        (foreign / 'libs.tech').mkdir()
        (foreign / 'libs.ref').mkdir()
        refs, tech = foreign / 'libs.ref', foreign / 'libs.tech'
    elif layout == 'escaped_asset':
        liberty = installed / 'libs.ref/scl/lib/scl__tt_025C_1v80.lib'
        outside = tmp_path / 'foreign.lib'
        outside.write_text('library (foreign) {}\n')
        liberty.unlink()
        liberty.symlink_to(outside)
    (root / 'libs.ref').symlink_to(refs)
    (root / 'libs.tech').symlink_to(tech)
    if layout in ('broken', 'cycle'):
        (root / 'libs.tech').unlink()
        (root / 'libs.tech').symlink_to(root / ('missing-tech' if layout == 'broken' else 'libs.tech'))
    monkeypatch.setenv('PDK_ROOT', str(root.parent))
    registry = {'name': installed.name, 'container_path': '/absent/legacy/pdks/' + installed.name,
                'liberty_glob': 'libs.ref/scl/lib/*tt*.lib',
                'tech_lef_glob': 'libs.ref/scl/techlef/*.tlef',
                'cell_lef_glob': 'libs.ref/scl/lef/*.lef', 'tapcell_master': None}
    if layout in ('split', 'foreign', 'broken', 'cycle'):
        with pytest.raises(SystemExit, match='PDK.*COMPOSITION'):
            m._pdk_config_from_registry(tmp_path, registry)
    else:
        resolved = m._pdk_config_from_registry(tmp_path, registry)
        if layout == 'escaped_asset':
            assert resolved is None
        else:
            assert resolved is not None, 'paired installed PDK views must resolve under their common selected-family root'
            assert resolved.liberty == str(installed / 'libs.ref/scl/lib/scl__tt_025C_1v80.lib')
