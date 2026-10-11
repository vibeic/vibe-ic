"""Existing producer calls retain old bytes and their actual canonical verdict."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_CANONICAL_RETENTION_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import execution_backend_gates as gates
import execution_policy as policy
import phase1_one_shot_runner as phase1
import phase3_one_shot_runner as phase3
import step_output_collector as versions


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def saved(project, sid):
    row = next((r for r in versions._read_index(project)['steps'] if r['id'] == sid), None)
    assert row is not None, f'Step {sid} did not retain its invocation'
    folder = project / 'steps' / row['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


@pytest.mark.parametrize('name,sid', [
    ('foundry_handoff', '38'), ('tapeout_checklist', '36'), ('gds_xor', '37.3')])
def test_real_pre_audit_refusal_preserves_the_file_it_invalidates(tmp_path, monkeypatch, name, sid):
    entry = next(e for e in phase3._PRE_AUDIT_PRODUCERS if e[0] == name)
    original = tmp_path / entry[2]
    original.parent.mkdir(parents=True)
    original.write_bytes(b'{"evidence":"previous producer bytes"}')
    def refuse(project, actual_name, *_args):
        assert actual_name == name
        assert not original.exists(), 'a failed retry must not consume the old working copy'
        return phase3._signoff_not_checked(name, 0.0, 'producer cannot run')
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', refuse)
    rows = phase3.run_pre_audit_producers(tmp_path, only_names=[name])
    assert rows[0].status == 'NOT_MEASURED'
    folder, record = saved(tmp_path, sid)
    before = json.loads((folder / 'before/outputs.json').read_text())
    kept = next(r for r in before['outputs'] if r['rel'] == entry[2])
    assert (folder / 'before' / kept['snapshot']).read_bytes() == b'{"evidence":"previous producer bytes"}'
    assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
    assert versions.latest_pass(tmp_path, sid) is None
    assert [r['id'] for r in versions._read_index(tmp_path)['steps']] == [sid]


def test_producer_success_is_not_a_canonical_pass(tmp_path, monkeypatch):
    output = tmp_path / 'reports/audit/tapeout_checklist.json'
    def produce(project, name, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"producer":"current bytes"}')
        return phase3.StepResult(name, 'PASS', 0.0, 'producer completed', [str(output)])
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', produce)
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'},
        'ledger': [{'gate': 'tapeout_signoff_check', 'rc': 1, 'verdict': 'FAIL'}]})
    assert phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])[0].status == 'PASS'
    _, record = saved(tmp_path, '36')
    assert record['status'] == 'FAIL'
    assert record['result']['canonical_consumer']['ledger'][0]['rc'] == 1
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '36') is None


def test_consumer_acceptance_and_failed_retry_keep_distinct_versions(tmp_path, monkeypatch):
    output = tmp_path / 'reports/audit/tapeout_checklist.json'
    content = [b'{"attempt":1}', b'{"attempt":2}']
    def produce(project, name, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content.pop(0))
        return phase3.StepResult(name, 'PASS', 0.0, 'producer completed', [str(output)])
    outcomes = iter(['PASS', 'FAIL'])
    def consume(project, row):
        assert output.read_bytes() in (b'{"attempt":1}', b'{"attempt":2}')
        status = next(outcomes)
        return {'status': status, 'step': {'id': row['id'], 'status': status}, 'ledger': []}
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', produce)
    monkeypatch.setattr(gates, 'evaluate', consume)
    phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])
    folder, record = saved(tmp_path, '36')
    assert record['canonical_pass'] is True
    relative = str(output.relative_to(tmp_path))
    assert record['result']['canonical_consumer']['outputs'] == {
        relative: {relative: hashlib.sha256(b'{"attempt":1}').hexdigest()}}
    accepted = versions.latest_pass(tmp_path, '36')
    assert accepted['folder'] == str(folder.relative_to(tmp_path / 'steps'))
    phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])
    newer, failed = saved(tmp_path, '36')
    assert newer != folder and failed['status'] == 'FAIL' and not failed['canonical_pass']
    assert (folder / 'files/reports/audit/tapeout_checklist.json').read_bytes() == b'{"attempt":1}'
    assert (newer / 'files/reports/audit/tapeout_checklist.json').read_bytes() == b'{"attempt":2}'
    assert versions.latest_pass(tmp_path, '36')['folder'] == accepted['folder']


def test_unknown_input_identity_does_not_claim_current_pass(tmp_path):
    attempt = versions.begin_step(tmp_path, '1')
    versions.finish_step(tmp_path, attempt, verdict='PASS', canonical_pass=True)
    historical = versions.latest_pass(tmp_path, '1')
    assert historical['status'] == 'PASS'
    assert historical['current_inputs'] is False


def test_step05_producer_completion_reaches_the_real_refusing_consumer(tmp_path):
    assert phase1._run_step_0_5ic(tmp_path) == 0
    _, record = saved(tmp_path, '0.5ic')
    assert record['status'] != 'PASS'
    assert record['result']['canonical_consumer']['status'] != 'PASS'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '0.5ic') is None


def test_step05_current_declared_die_reaches_the_real_accepting_consumer(tmp_path):
    import area_budget_basis_gen as area
    from programs.tests.test_r0929_deliverable_consistency import _project
    from programs.tests._route_fixture import stage_owner_route
    project = _project(tmp_path)
    path = project / 'input/step_0_5ic_answers.json'
    answers = json.loads(path.read_text())
    answers['operator_template']['absent_reason'] = (
        'The fixture owner requested independent DIE delivery without an operator or purchased slot.')
    path.write_text(json.dumps(answers))
    stage_owner_route(project, 'ic')
    assert area.main([str(project), '--answers', str(path), '--out', str(path)]) == 0
    assert phase1._run_step_0_5ic(project) == 0
    folder, record = saved(project, '0.5ic')
    assert record['status'] == 'PASS' and record['canonical_pass'] is True
    consumer = record['result']['canonical_consumer']
    assert consumer['status'] == 'PASS'
    assert {r['gate'] for r in consumer['ledger']} >= {
        'submission_template_check', 'tapeout_declaration_check'}
    assert versions.latest_pass(project, '0.5ic')['folder'] == str(folder.relative_to(project / 'steps'))


def test_real_derived_refusal_retains_deleted_flag_and_returned_reason(tmp_path, monkeypatch):
    flag = phase3._pl.postroute_timing_repair_dir(tmp_path) / 'no_repair_needed.flag'
    flag.parent.mkdir(parents=True)
    flag.write_bytes(b'previous repair evidence')
    def refuse(*_args, **_kwargs):
        flag.unlink()
        return SimpleNamespace(returncode=2, stdout='', stderr='current basis absent')
    monkeypatch.setattr(phase3.subprocess, 'run', refuse)
    outcome = phase3._run_derived_artefact_generators(tmp_path, None, skip_names=[
        'foundry_handoff_pack_gen.py', 'tapeout_checklist_gen.py'])
    assert outcome[0]['rc'] == 2
    folder, record = saved(tmp_path, '32')
    before = json.loads((folder / 'before/outputs.json').read_text())
    retained = next(r for r in before['outputs'] if r['rel'] == str(flag.relative_to(tmp_path)))
    assert (folder / 'before' / retained['snapshot']).read_bytes() == b'previous repair evidence'
    assert record['result']['producer_return']['message'] == 'current basis absent'
    assert not record['canonical_pass']
