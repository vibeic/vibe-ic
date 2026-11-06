"""Read-only actual retained SPM reader and copied-artifact rejection controls.

No expert expectation authoring, comparison replay, L-doc generation, signing,
canonical row execution or EDA dispatch. Negative copies have explicit targets.
"""
import hashlib
import os
from pathlib import Path

import pytest
import phase1_expert_parse_track as track


@pytest.fixture(autouse=True)
def no_dispatch(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('No generation/review/native/control dispatch belongs in frame reopening')

    monkeypatch.setattr('subprocess.Popen', refuse)
PROJECT = os.environ.get('RETAINED_EXPERT_FRAME_PROJECT')
pytestmark = pytest.mark.skipif(not PROJECT, reason='actual root-adopted retained frame required')


def paths():
    project = Path(PROJECT)
    target = track._pl.report_path(project, 'phase1/expert_parse_track.json')
    return project, target


def test_actual_check_report_reuses_original_frame_without_writes():
    project, target = paths()
    before = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
              for p in [target, project / 'phase1/step_identity.json',
                        project / 'reports/audit/ai_judgements/D1.json']
              + list((target.parent / 'expert_parse_track_pack').iterdir()) if p.is_file()}
    assert track.check_report(project) == 0
    assert before == {p: (hashlib.sha256(Path(p).read_bytes()).hexdigest(), Path(p).stat().st_mtime_ns)
                      for p in before}
