"""Source-only controls for the Phase-2 installed-PDK caller binding."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import design_one_shot_runner as D
import librelane_contract as LC
import phase3_one_shot_runner as P3


@pytest.fixture
def native(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True)
    (project / 'input/project.json').write_text(json.dumps({'pdk': 'gf180mcuD'}))
    root = tmp_path / 'nix/store/content-pdks'
    root.mkdir(parents=True)
    monkeypatch.setenv('PDK_ROOT', str(root))
    # Image identity is an external I/O boundary; provider, declaration, registry
    # resolution and asset probes below all execute their production code.
    monkeypatch.setattr(LC, 'local_image_attestation', lambda *_: {'image_id': 'fixture-image'})
    monkeypatch.setattr(LC, 'resolve_image', lambda *_: 'fixture-image')
    monkeypatch.setattr(LC._ce, 'no_container_route', lambda: True)
    monkeypatch.setattr(P3, '_LOCAL_EXEC_MODE', None)
    return project, root


def install(root, name='gf180mcuD', library='gf180mcu_fd_sc_mcu7t5v0'):
    tree = root.parent / 'backing-pdks' / name
    tree.mkdir(parents=True, exist_ok=True)
    (tree / 'libs.tech').mkdir(exist_ok=True)
    exposed = root / name
    exposed.mkdir(parents=True, exist_ok=True)
    (exposed / 'libs.ref').symlink_to(tree / 'libs.ref', target_is_directory=True)
    (exposed / 'libs.tech').symlink_to(tree / 'libs.tech', target_is_directory=True)
    base = tree / 'libs.ref' / library
    for rel, data in {
        'lib/cells__tt_025C_5v00.lib': 'library(test) {}',
        'techlef/cells__nom.tlef': 'LAYER Metal1\n TYPE ROUTING ;\nEND Metal1\n',
        'lef/cells.lef': 'SITE GF018hv5v_mcu_sc7\nEND GF018hv5v_mcu_sc7\n',
    }.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    return base


def test_nix_only_caller_uses_installed_root(native, monkeypatch):
    project, root = native
    base = install(root)
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', '/stale/host/projection')
    before = copy.deepcopy(P3._pdk_registry_entry('gf180mcuD'))
    pdk = D._phase2_pdk_config(project, 'gf180mcuD')
    assert pdk.name == 'gf180mcuD'
    assert Path(pdk.liberty) == base / 'lib/cells__tt_025C_5v00.lib'
    assert Path(pdk.tech_lef) == base / 'techlef/cells__nom.tlef'
    assert Path(pdk.cell_lef) == base / 'lef/cells.lef'
    assert P3._pdk_registry_entry('gf180mcuD') == before


@pytest.mark.parametrize('installed', ['absent', 'sky130A', 'gf180mcuC'])
def test_absent_or_foreign_distribution_refuses(native, installed):
    project, root = native
    if installed != 'absent':
        install(root, installed)
    with pytest.raises(LC.Refusal, match='LL_IMAGE_PDK_ABSENT'):
        D._phase2_pdk_config(project, 'gf180mcuD')


def test_wrong_library_refuses(native):
    project, root = native
    install(root, library='gf180mcu_fd_sc_mcu9t5v0')
    with pytest.raises(LC.Refusal, match='LL_PHASE2_PDK_UNRESOLVED'):
        D._phase2_pdk_config(project, 'gf180mcuD')


def test_undeclared_foreign_selection_refuses(native):
    project, root = native
    install(root, 'sky130A')
    with pytest.raises(LC.Refusal, match='LL_PHASE2_PDK_CONFLICT'):
        D._phase2_pdk_config(project, 'sky130A')


def test_declared_family_variant_selects_exact_distribution(native):
    project, root = native
    (project / 'input/project.json').write_text(json.dumps({'pdk': 'gf180mcu'}))
    base = install(root)
    pdk = D._phase2_pdk_config(project, 'gf180mcuD')
    assert pdk.name == 'gf180mcuD'
    assert Path(pdk.liberty).is_relative_to(base)


def test_container_foss_resolution_is_preserved(tmp_path, monkeypatch):
    from test_issue211_registry_driven_pdk_refuse import _FakeContainer
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True)
    (project / 'input/project.json').write_text(json.dumps({'pdk': 'gf180mcuD'}))
    root = '/foss/pdks/ciel/gf180mcu/versions/fixture/gf180mcuD'
    base = root + '/libs.ref/gf180mcu_fd_sc_mcu7t5v0'
    paths = {root, base + '/lib/cells__tt_025C_5v00.lib',
             base + '/techlef/cells__nom.tlef', base + '/lef/cells.lef'}
    monkeypatch.setattr(P3, '_LOCAL_EXEC_MODE', False)
    monkeypatch.setattr(P3, '_docker_exec_raw', _FakeContainer(paths))
    pdk = D._phase2_pdk_config(project, 'gf180mcuD')
    assert pdk.name == 'gf180mcuD'
    assert pdk.liberty == base + '/lib/cells__tt_025C_5v00.lib'


@pytest.mark.parametrize('damage', ['split_tree', 'foreign_variant'])
def test_composed_distribution_must_bind_one_same_variant_tree(native, damage):
    project, root = native
    install(root)
    exposed = root / 'gf180mcuD'
    if damage == 'split_tree':
        alternate = root.parent / 'other' / 'gf180mcuD' / 'libs.tech'
        alternate.mkdir(parents=True)
        (exposed / 'libs.tech').unlink()
        (exposed / 'libs.tech').symlink_to(alternate, target_is_directory=True)
    else:
        install(root, 'gf180mcuC')
        for name in ('libs.ref', 'libs.tech'):
            (exposed / name).unlink()
            (exposed / name).symlink_to(root / 'gf180mcuC' / name, target_is_directory=True)
    with pytest.raises(LC.Refusal, match='installed PDK asset trees disagree'):
        D._phase2_pdk_config(project, 'gf180mcuD')


@pytest.mark.skipif(not os.environ.get('VIBEIC_TEST_LOCAL_CIEL_ROOT'),
                    reason='requires a mounted Ciel-only fixture and live image attestation')
def test_local_ciel_only_existing_caller_preserved():
    import tempfile
    root = Path(os.environ['PDK_ROOT'])
    assert root == Path(os.environ['VIBEIC_TEST_LOCAL_CIEL_ROOT'])
    assert not (root / 'gf180mcuD').exists()
    reg = P3._pdk_registry_entry('gf180mcuD')
    matches = list(root.glob(str(Path(reg['container_path_glob']).relative_to(root))))
    assert len(matches) == 1
    LC.local_image_attestation(LC.resolve_image())
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        (project / 'input').mkdir()
        (project / 'input/project.json').write_text(json.dumps({'pdk': 'gf180mcuD'}))
        pdk = D._phase2_pdk_config(project, 'gf180mcuD')
    assert pdk.name == 'gf180mcuD'
    assert Path(pdk.liberty) == matches[0] / 'libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/cells__tt_025C_5v00.lib'
    assert Path(pdk.tech_lef).is_relative_to(matches[0])
    assert Path(pdk.cell_lef).is_relative_to(matches[0])


@pytest.mark.skipif(not os.environ.get('VIBEIC_TEST_LOCAL_CIEL_ROOT'),
                    reason='requires a mounted Ciel-only fixture and live image attestation')
def test_foreign_attested_root_cannot_borrow_ciel_tree(tmp_path, monkeypatch):
    root = tmp_path / 'foreign-provider'
    root.mkdir()
    monkeypatch.setenv('PDK_ROOT', str(root))
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True)
    (project / 'input/project.json').write_text(json.dumps({'pdk': 'gf180mcuD'}))
    with pytest.raises(LC.Refusal, match='LL_IMAGE_PDK_ABSENT'):
        D._phase2_pdk_config(project, 'gf180mcuD')
