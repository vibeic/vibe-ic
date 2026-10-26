"""Receipt-bound library containment; neutral owner fixtures plus current input.

Neutral fixtures isolate this owner with a declared upstream handoff stub.
The current-input case uses the real ordinary handoff and image filesystem.
No proof result or native synthesis receipt is manufactured for the current case.
"""
import json
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_LIBRARY_TEST_PROGRAMS',
                               str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import lec_run as L
import librelane_contract as LC
import pdk_revision_resolve as P
import synth_handoff_netlist_check as H


def resolution_outcome(project):
    """Observe success or the actual named refusal through the public consumer."""
    try:
        return L.resolve_liberty(project, L.DEFAULT_LIBERTY,
                                 lambda path: Path(path).is_file())
    except ValueError as exc:
        return None, str(exc)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    folder = project / 'phase3/librelane/synthesis'
    folder.mkdir(parents=True)
    roots = tmp_path / 'roots'
    selected = roots / 'store/versions' / ('ab' * 20) / 'process'
    library = selected / 'libs.ref/cells/typical.lib'
    library.parent.mkdir(parents=True)
    library.write_text('library (neutral) { }\n')
    (roots / 'process').symlink_to(selected, target_is_directory=True)
    config = {'PDK_ROOT': '/pdk', 'CELL_LIBS': {
        '*': ['/pdk/process/libs.ref/cells/typical.lib']}}
    root_record = {'cli_pdk_root': '/pdk',
                   'mounts_under_it': [[str(roots), '/pdk']]}
    receipt = {'sha256': {}, 'input': {'config_files': {}}}
    def refresh():
        (folder / 'config.json').write_text(json.dumps(config))
        (folder / 'pdk_root.json').write_text(json.dumps(root_record))
        receipt['sha256']['pdk_root.json'] = LC.digest(folder / 'pdk_root.json')
        receipt['input']['config_files'] = LC.config_file_hashes(
            {'files': config['CELL_LIBS']}, root_record['mounts_under_it'])
        (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))
    binding = project / 'phase2/stage2/synth/synth_inputs.json'
    binding.parent.mkdir(parents=True)
    binding.write_text(json.dumps({'librelane_synthesis': {
        'folder': str(folder.relative_to(project))}}))
    monkeypatch.setattr(H, 'bound_handoff', lambda _: {'verdict': 'PASS'})
    monkeypatch.setattr(LC, 'phase2_pdk', lambda _, *, selected=None: ('process', 'neutral fixture'))
    refresh()
    return project, folder, roots, selected, library, config, root_record, receipt, refresh


def test_resolved_install_path_binds_selected_symlink(fixture):
    project, _, roots, _, library, config, _, _, refresh = fixture
    config['CELL_LIBS']['*'] = ['/pdk/' + str(library.relative_to(roots))]
    refresh()
    got, source = resolution_outcome(project)
    assert source == 'run_synth'
    assert got == str(library.resolve())


def test_direct_selected_path_still_binds(fixture):
    project, _, _, _, library, _, _, _, _ = fixture
    got, source = resolution_outcome(project)
    assert source == 'run_synth'
    assert got == str(library.resolve())


@pytest.mark.parametrize('damage', ['foreign_symlink', 'changed', 'missing',
                                  'missing_hash', 'ambiguous_mount', 'sibling_root',
                                  'mount_escape', 'traversal'])
def test_foreign_changed_missing_or_ambiguous_library_refuses(fixture, damage):
    project, folder, roots, _, library, _, root_record, receipt, refresh = fixture
    if damage == 'foreign_symlink':
        foreign = roots / 'other/libs.ref/cells/typical.lib'
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(library.read_bytes())
        library.unlink()
        library.symlink_to(foreign)
        refresh()
    elif damage in ('sibling_root', 'mount_escape'):
        destination = ((library.parents[2].with_name('process-sibling'))
                       if damage == 'sibling_root' else roots.parent / 'outside')
        foreign = destination / 'libs.ref/cells/typical.lib'
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(library.read_bytes())
        library.unlink()
        library.symlink_to(foreign)
        refresh()
    elif damage == 'traversal':
        config = json.loads((folder / 'config.json').read_text())
        config['CELL_LIBS']['*'] = ['/pdk/process/../process/libs.ref/cells/typical.lib']
        (folder / 'config.json').write_text(json.dumps(config))
    elif damage == 'changed':
        library.write_text('library (changed) { }\n')
    elif damage == 'missing':
        library.unlink()
    elif damage == 'missing_hash':
        receipt['input']['config_files'] = {}
        (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))
    else:
        root_record['mounts_under_it'].append([str(roots), '/pdk'])
        refresh()
    with pytest.raises(ValueError, match='LL_LEC_LIB_UNBOUND'):
        L.resolve_liberty(project, L.DEFAULT_LIBERTY,
                          lambda path: Path(path).is_file())


def test_current_native_receipt_selects_exact_library():
    value = os.environ.get('VIBEIC_LIBRARY_CURRENT_PROJECT')
    if not value:
        pytest.skip('current-input native packet not supplied')
    project = Path(value)
    bound = H.bound_handoff(project)
    assert bound and bound['verdict'] == 'PASS', bound
    binding = json.loads((project / 'phase2/stage2/synth/synth_inputs.json').read_text())
    folder = project / binding['librelane_synthesis']['folder']
    config = json.loads((folder / 'config.json').read_text())
    recorded = next(iter(config['CELL_LIBS'].values()))[0]
    expected = P.Fs(None).realpath(recorded)
    got, source = resolution_outcome(project)
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    assert source == 'run_synth'
    assert got == expected
    assert LC.digest(Path(got)) == receipt['input']['config_files'][recorded]
