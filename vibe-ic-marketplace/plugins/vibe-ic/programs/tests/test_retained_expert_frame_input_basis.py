"""Read-only actual retained SPM reader and copied-artifact rejection controls.

No expert expectation authoring, comparison replay, L-doc generation, signing,
canonical row execution or EDA dispatch. Negative copies have explicit targets.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest
import phase1_expert_parse_track as track
import _phase1_producer_identity as identity
import ai_signed_judgement as judgement
import execution_backend_worker as worker


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


@pytest.fixture
def altered(tmp_path, monkeypatch):
    project, source = paths()
    target = tmp_path / 'expert_parse_track.json'
    shutil.copy2(source, target)
    shutil.copytree(source.parent / 'expert_parse_track_pack', tmp_path / 'expert_parse_track_pack')
    report_path = track._pl.report_path
    monkeypatch.setattr(track._pl, 'report_path', lambda p, name:
                        target if name == 'phase1/expert_parse_track.json' else report_path(p, name))
    return project, target


@pytest.mark.parametrize('damage', ['frame_member', 'mapping', 'schema', 'expert_context',
                                  'answer', 'missing_basis', 'foreign_basis',
                                  'refused_transition', 'unsigned_current_review',
                                  'changed_declared_input', 'new_declared_input'])
def test_real_reader_preserves_changed_or_unbound_refusals(altered, monkeypatch, damage):
    project, target = altered
    record = json.loads(target.read_text())
    frame = record['ai_subtrack']['handoff']['source_frame']
    out = target.parent / 'expert_parse_track_pack'
    if damage == 'frame_member':
        frame['members'][0]['semantic_text'] += '\nchanged authored design requirement'
        frame['semantic_text'] += '\nchanged authored design requirement'
    elif damage == 'mapping':
        frame['responsibility_mapping_sha256'] = '0' * 64
    elif damage == 'schema':
        actual = track.authoring_schema
        def changed(p):
            value = copy.deepcopy(actual(p))
            value['changed_schema_epoch'] = True
            return value
        monkeypatch.setattr(track, 'authoring_schema', changed)
    elif damage == 'expert_context':
        p = out / 'lessons.md'
        p.write_text(p.read_text() + '\nchanged expert instruction\n')
    elif damage == 'answer':
        p = out / 'l_doc_expectations.json'
        p.write_bytes(p.read_bytes() + b'\n')
    elif damage in ('missing_basis', 'foreign_basis'):
        if damage == 'missing_basis':
            monkeypatch.delenv('VIBEIC_PHASE1_INPUT_BASIS', raising=False)
        else:
            wrong = target.parent / 'foreign-basis.json'
            wrong.write_text('{}')
            monkeypatch.setenv('VIBEIC_PHASE1_INPUT_BASIS', str(wrong))
    elif damage == 'refused_transition':
        monkeypatch.setattr(identity, 'assess', lambda *a, **kw:
            {'state': identity.REGENERATE, 'reason': identity.DESIGN_INPUT_CHANGED})
    elif damage == 'unsigned_current_review':
        signature = project / 'reports/audit/ai_judgements/D1.json'
        negative = target.parent / 'negative-D1.json'
        signed = json.loads(signature.read_text())
        signed['signed_by'] = ''
        negative.write_text(json.dumps(signed))
        reader = judgement._json
        monkeypatch.setattr(judgement, '_json', lambda path:
            reader(negative) if Path(path) == signature else reader(path))
    else:
        # Explicit declared-readset boundary doubles, with actual changed file
        # hashes; never apply this source mutation to the original carrier.
        altered_input = target.parent / 'changed-authored-input.md'
        altered_input.write_text('A new authored design obligation.\n')
        digest = hashlib.sha256(altered_input.read_bytes()).hexdigest()
        resolver = worker._declared_input_files
        def changed_inputs(p, declarations):
            opened = resolver(p, declarations)
            name = (next(k for k in opened if k.startswith('input/docs/'))
                    if damage == 'changed_declared_input' else 'input/docs/new-author-input.md')
            return {**opened, name: digest}
        monkeypatch.setattr(worker, '_declared_input_files', changed_inputs)
    target.write_text(json.dumps(record))
    # Only copied control artifacts were mutated; real originals stay RO.
    assert track.check_report(project) == 1
