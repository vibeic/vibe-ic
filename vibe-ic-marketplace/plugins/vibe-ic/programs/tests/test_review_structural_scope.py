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
        if g.name not in {'repo_hygiene_gate', 'gate_red_since_gate'}]
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


def test_expired_debt_is_visible_advisory_and_other_ledger_errors_block(tmp_path, monkeypatch):
    G = R._load_module('gate_red_since_check')
    monkeypatch.setattr(R, '_load_module', lambda name: G)
    rec = tmp_path/'hygiene.json'
    rec.write_text(json.dumps({'declared':1, 'gates':[{'label':'old', 'state':'FAIL'}]}))
    monkeypatch.setattr(G, 'load_ledger_from_ref', lambda *a: [{
        'gate':'old', 'since':'a'*40, 'since_date':'2026-01-01T00:00:00+00:00', 'max_days':2}])
    monkeypatch.setattr(G, 'git_age_days', lambda *a: lambda ref: 4)
    monkeypatch.setattr(G, 'git_commit_date', lambda *a: lambda ref:'2026-01-01T00:00:00+00:00')
    result = R.gate_red_since_gate(tmp_path, rec, base='base')
    assert result.green and result.rc == 1 and result.advisory
    assert 'expired' in result.summary and 'old' in result.summary
    monkeypatch.setattr(G, 'git_commit_date', lambda *a: lambda ref:'2026-01-02T00:00:00+00:00')
    result = R.gate_red_since_gate(tmp_path, rec, base='base')
    assert not result.green
    assert 'misdated' in result.summary


def test_missing_debt_evidence_is_incomplete_not_a_skip(tmp_path):
    result = R.gate_red_since_gate(tmp_path, tmp_path/'missing', base='base')
    assert result.rc == 2 and not result.green
    assert 'INCOMPLETE' in result.summary


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
def test_a_skipped_hygiene_producer_is_inherited_as_a_skip(tmp_path):
    """The producer's zero denominator is the consumer's zero denominator."""
    producer = R.GateResult(
        'repo_hygiene_gates', -1,
        'skipped — 0 gate(s) consulted: tools/ci/repo_hygiene_gates.sh '
        f'not present under {tmp_path}')
    result = R.gate_red_since_gate(tmp_path, tmp_path / 'missing', base='base',
                                   producer=producer)
    assert result.rc == -1 and result.green
    # and it SAYS whose zero it inherited, so the cascade is legible.
    assert '0 hygiene record(s) produced' in result.summary
    assert 'repo_hygiene_gates' in result.summary
    assert '0 gate(s) consulted' in result.summary


def test_a_producer_that_RAN_and_left_no_record_still_BLOCKS(tmp_path):
    """The case the INCOMPLETE rule was written for, unchanged.

    A hygiene run that happened and produced nothing readable is exactly the
    evidence failure this gate must refuse; only a run that never happened is
    inherited as a skip. rc 0 here, and rc 1/2 are the same: any rc but -1 means
    the set ran.
    """
    for rc in (0, 1, 2):
        producer = R.GateResult('repo_hygiene_gates', rc, 'the set ran')
        result = R.gate_red_since_gate(tmp_path, tmp_path / 'missing',
                                       base='base', producer=producer)
        assert result.rc == 2 and not result.green, rc
        assert 'INCOMPLETE' in result.summary, rc


def test_a_skipped_producer_does_not_excuse_a_record_that_IS_there(tmp_path):
    """The skip is granted on ABSENCE, never on the producer's rc alone.

    Without this arm a -1 producer would be a blanket amnesty: a record present
    and vacuous would be waived unread, which is the shape `record_is_vacuous`
    exists to refuse.
    """
    rec = tmp_path / 'hygiene.json'
    rec.write_text(json.dumps({'declared': 0, 'gates': []}))
    producer = R.GateResult('repo_hygiene_gates', -1, 'skipped — 0 gate(s)')
    result = R.gate_red_since_gate(tmp_path, rec, base='base',
                                   producer=producer)
    assert result.rc == 2 and not result.green
    assert '0 hygiene record(s) produced' not in result.summary
