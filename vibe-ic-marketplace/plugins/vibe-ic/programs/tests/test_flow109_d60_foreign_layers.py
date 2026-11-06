"""Native D60 stream regressions with neutral source-GDS cells and real tools."""
import hashlib
import json

import analog_hardmacro_gds_emit as stream














def test_foreign_view_identity_comes_from_shipped_gds_bytes(tmp_path, monkeypatch):
    from _hostpaths import require_repo
    fixture = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                           'fixtures', 'density_fill', 'filled.gds')
    content = fixture.read_bytes()
    pdk = tmp_path / 'pdk'; pdk.mkdir()
    # The library name differs from the adopted copy; an equal-sized native
    # view and a symlink cycle must not change the classification.
    (pdk / 'library.gds').write_bytes(content)
    (pdk / 'cycle').symlink_to(pdk, target_is_directory=True)
    adopted = tmp_path / 'adopted.gds'; adopted.write_bytes(content)
    generated = tmp_path / 'generated.gds'; generated.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    magic = pdk / 'libs.tech/magic'; magic.mkdir(parents=True)
    for suffix in ['tech', 'magicrc']:
        (magic / ('neutral.' + suffix)).write_text('neutral test technology\n')
    inputs = tmp_path / 'input'; inputs.mkdir()
    (inputs / 'flow109').mkdir()
    def ref(path):
        return {'path': str(path.relative_to(tmp_path)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    top = tmp_path / 'neutral_top.mag'
    top.write_text('magic\ntech neutral\nuse foreign foreign_0\nuse native native_0\n<< end >>\n')
    for name in ['foreign', 'native']:
        (tmp_path / (name + '.mag')).write_text('magic\ntech neutral\n<< metal1 >>\nrect 0 0 1 1\n<< end >>\n')
    inventory = inputs / 'inventory.json'
    inventory.write_text(json.dumps({'instances': {'foreign_0': {'master': 'foreign', 'gds': ref(adopted)},
                                                'native_0': {'master': 'native', 'gds': ref(generated)}}}))
    (inputs / 'project.json').write_text('{}')
    (inputs / 'flow109/D31.json').write_text(json.dumps({'macro_inventory': ref(inventory)}))
    (inputs / 'flow109/D60.json').write_text(json.dumps({'top': top.stem, 'layout': ref(top)}))
    import analog_pdk_availability, declared_pdk_is_the_pdk_used_check
    monkeypatch.setattr(declared_pdk_is_the_pdk_used_check, 'declared_target', lambda p: ('neutral', 'input/project.json:pdk'))
    monkeypatch.setattr(analog_pdk_availability, 'families_agree', lambda *a: True)
    monkeypatch.setattr(analog_pdk_availability, 'resolve_pdk', lambda *a, **k:
                        {'source': 'container_installed', 'available': True, 'pdk_root': str(pdk)})
    actual = stream._d60_inputs(tmp_path)
    assert actual.get('foreign_views', actual['views']) == {'foreign': str(adopted)}
