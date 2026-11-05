"""The parent can request a sub-review without manufacturing hygiene admission."""
import json
import os
from pathlib import Path
import sys

import pytest

_root = os.environ.get('CXARCH_SUBJECT_ROOT')
sys.path.insert(0, str(Path(_root)/'vibe-ic-marketplace/plugins/vibe-ic/programs'
                       if _root else Path(__file__).resolve().parents[1]))
import gatekeeper_review as R


@pytest.fixture
def bounded(monkeypatch, tmp_path):
    for name in list(vars(R)):
        if name.endswith('_gate') and callable(getattr(R, name)):
            monkeypatch.setattr(R, name, lambda *a, _name=name, **k:
                                R.GateResult(_name, 0, 'measured stub'))
    monkeypatch.setattr(R, 'role_scope_gate', lambda *a:
                        (R.GateResult('role_scope', 0, 'measured stub'), False))
    return dict(base='base', head='HEAD', repo=tmp_path, plugin_root=tmp_path,
                override_files=[], override_cur='1.0.2', override_prev='1.0.1')


def test_scope_preserves_every_other_gate_and_never_authorizes_standalone(bounded):
    full = R.review(**bounded)
    scoped = R.review(**bounded, scope='structural')
    assert full.verdict == 'MERGE_OK'
    assert scoped.verdict == 'SCOPED_REVIEW_OK'
    assert [(g.name, g.rc) for g in scoped.gates] == [
        (g.name, g.rc) for g in full.gates
        if g.name not in {'repo_hygiene_gate'}]
    report = R._verdict_to_dict(scoped)
    assert report['standalone_admission'] is False
    assert report['required_parent_units'] == ['full:repo-hygiene']
    assert not any('hygiene' in g.name for g in scoped.gates)


def test_standalone_default_executes_hygiene_once(bounded, monkeypatch):
    runs = []
    monkeypatch.setattr(R, 'repo_hygiene_gate', lambda *a, **k:
                        runs.append('hygiene') or R.GateResult('repo_hygiene_gates', 0, 'ran'))
    result = R.review(**bounded)
    assert runs == ['hygiene']
    assert result.verdict == 'MERGE_OK'
    assert R._verdict_to_dict(result)['standalone_admission'] is True


@pytest.mark.parametrize('rc', [1, 2])
def test_real_red_and_incomplete_hygiene_remain_blocking(bounded, monkeypatch, rc):
    monkeypatch.setattr(R, 'repo_hygiene_gate', lambda *a, **k:
                        R.GateResult('repo_hygiene_gates', rc, 'new red or incomplete'))
    result = R.review(**bounded)
    assert result.verdict == 'REQUEST_CHANGES'
    assert result.blocking




def test_scope_cannot_be_combined_with_substitute_evidence(bounded, tmp_path):
    with pytest.raises(RuntimeError, match='cannot accept'):
        R.review(**bounded, scope='structural', hygiene_record_in=tmp_path/'fake')






# ---------------------------------------------------------------------------
# The adjudicator may not be more certain than its producer.
#
# `repo_hygiene_gate` reports "this tree wires no hygiene set" as an honest SKIP
# that states its denominator (rc -1, "0 gate(s) consulted"), and writes no
# record because nothing ran. `gate_red_since_gate` read that deliberate absence
# and returned rc 2 BLOCKING -- "INCOMPLETE — debt evidence unavailable: [Errno
# 2] No such file or directory: '/tmp/gate_red_since_xxxxxxxx/hygiene.json'".
# MEASURED on 6883a9c93 that sentence was the SOLE blocker turning MERGE_OK into
# REQUEST_CHANGES for two reviews of trees that wire no hygiene set, and it names
# a temp path that never existed, so a reader learns nothing from it.
#
# The three tests below are the whole rule, and the second and third are why the
# first is safe: the blocking direction the original rule was written for is
# UNCHANGED. Only "the producer said it did not run, and there is indeed no
# record" is inherited.
# ---------------------------------------------------------------------------
