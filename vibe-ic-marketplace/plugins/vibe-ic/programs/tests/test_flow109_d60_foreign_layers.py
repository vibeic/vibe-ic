"""Native D60 stream regressions with neutral source-GDS cells and real tools."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import analog_hardmacro_gds_emit as stream


def native(argv, **kwargs):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60, **kwargs)
    assert done.returncode == 0, done.stdout + done.stderr
    return done


@pytest.fixture(params=[False, True], ids=['flat', 'hierarchical'])
def foreign_stream(tmp_path, monkeypatch, request):
    pya = pytest.importorskip('klayout.db')
    magic, klayout = shutil.which('magic'), shutil.which('klayout')
    if not magic or not klayout or not os.environ.get('D60_TEST_MAGICRC'):
        pytest.skip('native Magic/KLayout and D60_TEST_MAGICRC required')
    tech = os.environ['D60_TEST_TECH']
    rcfile = os.environ['D60_TEST_MAGICRC']
    project = tmp_path / 'project'; project.mkdir()
    inputs = project / 'input'; inputs.mkdir()
    def mag(name, body):
        path = inputs / (name + '.mag')
        path.write_text(f'magic\ntech {tech}\nmagscale 1 2\ntimestamp 0\n' + body + '<< end >>\n')
        return path
    native_mag = mag('neutral_native', '<< metal1 >>\nrect 0 0 200 100\n')
    foreign_mag = mag('neutral_foreign', '<< metal1 >>\nrect 0 0 200 100\n')
    cells = {p.stem: str(p) for p in (native_mag, foreign_mag)}
    hierarchy = {'neutral_native': {}, 'neutral_foreign': {}}
    if request.param:
        leaf = mag('neutral_leaf', '<< metal1 >>\nrect 0 0 20 10\n')
        cells[leaf.stem] = str(leaf)
        foreign_mag.write_text(foreign_mag.read_text().replace('<< end >>',
            'use neutral_leaf leaf_0\ntimestamp 0\ntransform 0 -1 400 1 0 300\nbox 0 0 20 10\n<< end >>'))
        hierarchy['neutral_foreign'] = {'neutral_leaf': 1}
        hierarchy['neutral_leaf'] = {}
    top = mag('neutral_top', '<< metal1 >>\nrect 1000 1000 1200 1200\n'
        'use neutral_foreign foreign_0\ntimestamp 0\ntransform 0 -1 800 1 0 600\nbox 0 0 200 100\n'
        'use neutral_native native_0\ntimestamp 0\ntransform 1 0 0 0 1 0\nbox 0 0 200 100\n')
    cells[top.stem] = str(top)
    hierarchy[top.stem] = {'neutral_foreign': 1, 'neutral_native': 1}
    recipe = inputs / 'native.tcl'
    recipe.write_text(stream.build_gds_write_tcl(native_mag.stem, native_mag.stem, 'native.gds'))
    env = {**os.environ, 'PDK': tech, 'PDK_ROOT': os.environ['D60_TEST_PDK_ROOT']}
    native([magic, '-noconsole', '-dnull', '-rcfile', rcfile, str(recipe)], cwd=inputs, env=env)
    native_gds = inputs / 'native.gds'
    native_layout = pya.Layout(); native_layout.read(str(native_gds))
    source = pya.Layout(); source.dbu = native_layout.dbu
    master = source.create_cell('neutral_foreign')
    # This layer/datatype has no mapping in the selected Magic techfile.
    master.shapes(source.layer(32123, 7)).insert(pya.Box(0, 0, 17001, 9003))
    master.shapes(source.layer(32123, 9)).insert(pya.Path([pya.Point(1, 2), pya.Point(2000, 3000)], 100))
    master.shapes(source.layer(32123, 11)).insert(pya.Text('neutral label', pya.Trans(19, 23)))
    if request.param:
        leaf = source.create_cell('neutral_leaf')
        leaf.shapes(source.layer(32124, 8)).insert(pya.Box(5, 7, 701, 1103))
        master.insert(pya.CellInstArray(leaf.cell_index(), pya.Trans(1, True, 400, 300)))
    # Unreferenced cells in a PDK library must not become extra stream tops.
    source.create_cell('neutral_unused').shapes(source.layer(32125, 0)).insert(pya.Box(0, 0, 1, 1))
    foreign_gds = inputs / 'foreign.gds'; source.write(str(foreign_gds))
    data = dict(top=top.stem, tech=tech, pdk_root=env['PDK_ROOT'], rcfile=rcfile,
        cells=cells, hierarchy=hierarchy, foreign_views={'neutral_foreign': str(foreign_gds)}, views={'neutral_foreign': str(foreign_gds),
        'neutral_native': str(native_gds)}, instances={'foreign_0': 'neutral_foreign', 'native_0': 'neutral_native'},
        inputs={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*map(Path, cells.values()), native_gds, foreign_gds]})
    # Only admission/input discovery is supplied by the neutral fixture. The
    # actual D60 producer, Magic, KLayout merge and strict reader all execute.
    monkeypatch.setattr(stream, '_d60_inputs', lambda project: data)
    import flow109_admission, librelane_contract
    monkeypatch.setattr(flow109_admission, 'require_launch_admission', lambda *a: {'scope': 'TEST_ONLY'})
    monkeypatch.setattr(librelane_contract, 'local_image_attestation', lambda: {'scope': 'TEST_ONLY'})
    context = {'requested_step': 'D60', 'native_step_id': 'flow109.D60',
               'resolved_row': {'profile': {'id': 'analog_die'}}}
    return project, data, context, pya, klayout


def test_foreign_layers_survive_native_stream_with_zero_xor(foreign_stream, monkeypatch):
    project, data, context, pya, _ = foreign_stream
    magic_stream = pya.Layout()
    original = stream.Stage.sh
    def capture(stage, *args, **kwargs):
        result = original(stage, *args, **kwargs)
        magic_stream.read(str(Path(stage.path) / (data['top'] + '.gds')))
        return result
    monkeypatch.setattr(stream.Stage, 'sh', capture)
    result = stream.execute(project, context)
    assert result['component_status'] == 'PASS', result
    output = project / result['outputs'][0]['path']
    actual = pya.Layout(); actual.read(str(output))
    for master, path in data['views'].items():
        source = pya.Layout(); source.read(path)
        for index in source.layer_indexes():
            info = source.get_info(index)
            a = pya.Region(source.cell(master).begin_shapes_rec(index))
            b = pya.Region(actual.cell(master).begin_shapes_rec(actual.layer(info)))
            assert (a ^ b).is_empty(), (master, str(info), (a ^ b).area())
    # The Magic-generated native cell and die geometry stay unchanged.
    for name in ['neutral_top', 'neutral_native']:
        for index in magic_stream.layer_indexes():
            a = pya.Region(magic_stream.cell(name).shapes(index))
            b = pya.Region(actual.cell(name).shapes(actual.layer(magic_stream.get_info(index))))
            assert (a ^ b).is_empty(), name
    text = actual.cell('neutral_foreign').shapes(actual.layer(32123, 11))
    assert [s.text.string for s in text.each() if s.is_text()] == ['neutral label']
    assert 'neutral_unused' not in result['measurements']['cells']


@pytest.mark.parametrize('master', ['neutral_foreign', 'neutral_native'])
def test_changed_stream_is_still_rejected(foreign_stream, master):
    project, data, context, pya, klayout = foreign_stream
    result = stream.execute(project, context)
    # On the predecessor the lossy stream is still available for the control.
    gds = next((project / 'reports/flow109/D60').glob('*/work/neutral_top.gds'))
    changed = pya.Layout(); changed.read(str(gds))
    changed.cell(master).shapes(changed.layer(32126, 13)).insert(pya.Box(0, 0, 123, 456))
    changed.write(str(gds))
    data['views'] = {master: data['views'][master]}
    observed = stream._d60_metric_readback(project, data, gds, {'path': klayout})['measurement']
    assert observed['status'] == 'FAIL', (result, observed)
    assert observed['reason'] == 'D60_ADOPTED_VIEW_GEOMETRY_MISMATCH: ' + master, observed


def test_changed_magic_generated_cell_is_not_replaced_from_old_gds(foreign_stream):
    project, data, context, _, _ = foreign_stream
    data['views'] = {'neutral_native': data['views']['neutral_native']}
    data['foreign_views'] = {}
    path = Path(data['cells']['neutral_native'])
    path.write_text(path.read_text().replace('200 100', '400 100'))
    result = stream.execute(project, context)
    assert result['component_status'] == 'FAIL', result
    assert result['reason'] == 'D60_ADOPTED_VIEW_GEOMETRY_MISMATCH: neutral_native', result


def test_stream_bytes_cannot_change_during_readback(foreign_stream, monkeypatch):
    project, data, context, _, _ = foreign_stream
    data['views'] = {'neutral_native': data['views']['neutral_native']}
    data['foreign_views'] = {}
    # Change a library timestamp, leaving geometry intact. Both the old Magic
    # stream and the merged stream must bind the bytes the checker consumed.
    mutation = ("import json,pathlib\n"
        "p=pathlib.Path(json.loads(pathlib.Path(D60_REQUEST).read_text())['gds'])\n"
        "b=bytearray(p.read_bytes());b[10:12]=(1999).to_bytes(2,'big');p.write_bytes(b)\n")
    monkeypatch.setattr(stream, '_D60_READBACK', mutation + stream._D60_READBACK)
    result = stream.execute(project, context)
    assert result['reason'] == 'D60_STREAM_CHANGED_DURING_READBACK', result
    assert result['component_status'] != 'PASS'


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
