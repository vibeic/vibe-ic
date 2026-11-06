"""Current native Step37.3 artefacts and substantive refusal controls."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _physical_current as pc
import librelane_contract as lc
from test_librelane_contract import local_image  # existing attested-image fixture


def retained_local_receipt(tmp_path, local_image, *, change=None):
    """Neutral immutable producer receipt with a distinct 32 GiB frame."""
    project = tmp_path / 'retained-project'
    folder = project / 'phase3/librelane/37.3-compare/02-klayout-xor'
    folder.mkdir(parents=True)
    current = lc.local_image_attestation(local_image.image)
    original = {**current, 'memory': 32 * 1024**3,
                'memory_swap': 32 * 1024**3}
    if change == 'image':
        original['image'] = 'registry.invalid/changed@sha256:' + '1' * 64
    elif change == 'frame':
        original['memory'] = 0
    fingerprint = {'step': 'KLayout.XOR', 'local_image': original}
    files = {
        'state_out.json': {'metrics': {}},
        'input_fingerprint.json': fingerprint,
        'pdk_root.json': {'execution_route': 'LOCAL'},
    }
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value))
    (folder / 'invocation.log').write_text('SOURCE_CONTROL retained rc0 producer\n')
    names = [*files, 'invocation.log']
    (folder / 'vibeic_receipt.json').write_text(json.dumps({
        'input': fingerprint,
        'sha256': {name: pc.digest(folder / name) for name in names}}))
    return project, folder, original






@pytest.fixture
def project():
    declared = os.environ.get("VIBEIC_XOR373_NATIVE_PROJECT")
    if not declared:
        pytest.skip("native producer artefacts not supplied: NOT_VERIFIED")
    path = Path(declared)
    assert path.is_dir()
    return path






@pytest.mark.parametrize("scenario", ["current", "changed", "missing"])
def test_material_bytes_and_mount_are_read(tmp_path, scenario):
    root = tmp_path / "real_mount"
    root.mkdir()
    deck = root / "declared.deck"
    deck.write_text("declared fixture material\n")
    config = {"deck": "/pdk/declared.deck"}
    mounts = [(root, "/pdk")]
    first = lc._current_config_material(config, mounts)
    assert first == {str(deck): pc.digest(deck)}
    if scenario == "changed":
        deck.write_text("changed declared fixture material\n")
        assert lc._current_config_material(config, mounts) != first
    elif scenario == "missing":
        deck.unlink()
        with pytest.raises(lc.Refusal, match="LL_CONFIG_MATERIAL_MISSING"):
            lc._current_config_material(config, mounts)
