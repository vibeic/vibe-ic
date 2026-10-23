"""A copied real-run layout retains its native placement identity."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import placement_legality_check as placement


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def copied(tmp_path):
    original = tmp_path / 'original'
    placed = original / 'phase3/stage3/pnr/placed.def'
    placed.parent.mkdir(parents=True)
    placed.write_text('DESIGN unit ;\nEND DESIGN\n')
    folder = original / 'phase3/librelane/placement/01-detailedplacement'
    folder.mkdir(parents=True)
    state = folder / 'state_out.json'
    state.write_text(json.dumps({'def': str(placed)}))
    (folder / 'vibeic_receipt.json').write_text(json.dumps({
        'input': {'step': 'OpenROAD.DetailedPlacement'}}))
    receipt = original / 'reports/phase3/librelane_placement_handoff.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'state': str(state), 'state_sha256': sha(state),
        'views': {'def': {'dest': str(placed), 'dest_sha256': sha(placed)}}}))
    target = tmp_path / 'retained'
    shutil.copytree(original, target)
    shutil.rmtree(original)
    return target


def test_copied_native_placement_remains_bound(copied):
    result = placement._librelane_placement(copied)
    assert result['bound'] is True
    assert result['detailed_placement'] == 'COMPLETED'
    assert Path(result['detailed_placement_dir']).is_relative_to(copied)


@pytest.mark.parametrize('relative', [
    'phase3/stage3/pnr/placed.def',
    'phase3/librelane/placement/01-detailedplacement/state_out.json',
])
def test_copied_artifact_mutation_still_refuses(copied, relative):
    path = copied / relative
    path.write_text(path.read_text() + '\nchanged\n')
    assert placement._librelane_placement(copied)['bound'] is False


def test_another_destination_is_not_reinterpreted_as_placement(copied):
    path = copied / 'reports/phase3/librelane_placement_handoff.json'
    doc = json.loads(path.read_text())
    doc['views']['def']['dest'] = '/other/phase3/stage3/pnr/routed.def'
    path.write_text(json.dumps(doc))
    assert placement._librelane_placement(copied)['bound'] is False
