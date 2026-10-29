"""Canonical Default lookup preserves absent and present operator evidence."""
import json
from pathlib import Path

import pytest
import execution_policy as policy
import phase1_one_shot_runner as phase1
from programs.tests.test_execution_receipt_chain import isolated_transport  # noqa: F401
from programs.tests._route_fixture import stage_owner_route
from programs.tests.test_default_d1_entry import _raw_docs_project


def test_derived_answer_documents_reach_the_real_gate_and_remain_bound(tmp_path):
    import area_budget_basis_gen as area
    import submission_template_check
    import tapeout_declaration_check
    from programs.tests.test_r0929_deliverable_consistency import _project
    from programs.tests._route_fixture import stage_owner_route

    project = _project(tmp_path)
    path = project / 'input/step_0_5ic_answers.json'
    answers = json.loads(path.read_text())
    answers['operator_template']['absent_reason'] = (
        'This neutral input specifies no operator, purchased slot or submission '
        'template; the owner explicitly requires an independent DIE delivery.')
    path.write_text(json.dumps(answers) + '\n')
    stage_owner_route(project, 'ic')
    assert area.main([str(project), '--answers', str(path), '--out', str(path)]) == 0
    docs = {str(p.relative_to(project)): p.read_bytes()
            for p in (project / 'input/docs').iterdir() if p.is_file()}
    stage_owner_route(project, 'ic')
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    assert phase1._run_step_0_5ic(project) == 0
    output = project / 'reports/phase1'
    assert all((output / name).is_file() for name in (
        'submission_template.json', 'submission_template_answers.json',
        'submission_template_fetch.json', 'tapeout_declaration.json'))
    # Default is the canonical producer path.  The flow gates consume those
    # reports directly; there is no Controller plan, worker receipt, or
    # adoption record to make a component look like a whole-flow result.
    gate_dir = project / 'reports/execution_gates'
    gate_dir.mkdir()
    assert submission_template_check.main([
        str(project), '--json', str(gate_dir / 'submission_template_check.json')]) == 0
    assert tapeout_declaration_check.main([
        str(project), '--json', str(gate_dir / 'tapeout_declaration_check.json')]) == 0
    assert json.loads((gate_dir / 'submission_template_check.json').read_text())[
        'check']['verdict'] == 'NOT_APPLICABLE'
    assert json.loads((gate_dir / 'tapeout_declaration_check.json').read_text())[
        'verdict'] == 'PASS'
    assert not list((project / 'reports/execution').glob('*/*/plan.json'))
    assert not list((project / 'reports/execution').glob('*/0.5ic/adoption.json'))
    # The direct producer reads the staged documents; it does not create a
    # second mutable copy whose hash would become a separate adoption claim.
    for name, content in docs.items():
        assert (project / name).read_bytes() == content


@pytest.mark.parametrize('present', [False, True], ids=['missing', 'present'])
def test_default_05ic_uses_canonical_search_and_real_gates(tmp_path, present):
    import submission_template_check
    import tapeout_declaration_check
    project = tmp_path / 'subject'
    if present:
        _raw_docs_project(project)
        answer_path = project / 'input/step_0_5ic_answers.json'
        answers = json.loads(answer_path.read_text())
        del answers['operator_template']['path']
        answer_path.write_text(json.dumps(answers) + '\n')
    else:
        # The real field input declared DIE, but supplied neither an operator
        # template nor a reason for its absence. Do not complete its answers.
        answer_path = project / 'input/step_0_5ic_answers.json'
        answer_path.parent.mkdir(parents=True)
        answer_path.write_text(json.dumps({
            'schema': 'vibe-ic/step_0_5ic_answers/1',
            'answers': {'deliverable': 'DIE'},
            'answer_provenance': {'deliverable': {
                'answered_by': 'owner', 'citation': 'Owner requested an IC delivery.'}}
        }) + '\n')
    stage_owner_route(project, 'ic')
    owner_bytes = answer_path.read_bytes()
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    rc = phase1._run_step_0_5ic(project)
    assert answer_path.read_bytes() == owner_bytes
    output = project / 'reports/phase1'
    assert all((output / name).is_file() for name in (
        'submission_template.json', 'submission_template_fetch.json'))
    if present:
        assert (output / 'submission_template_answers.json').is_file()
        assert (output / 'tapeout_declaration.json').is_file()
    else:
        assert not (output / 'submission_template_answers.json').exists()
        assert not (output / 'tapeout_declaration.json').exists()
    assert not list((project / 'reports/execution').glob('*/*/receipt.json'))
    assert not list((project / 'reports/execution').glob('*/0.5ic/adoption.json'))
    ingest = json.loads((output / 'submission_template.json').read_text())['ingest']
    declaration = (json.loads((output / 'tapeout_declaration.json').read_text())
                   if present else None)
    gate_dir = project / 'reports/execution_gates'
    gate_dir.mkdir()
    submission_rc = submission_template_check.main([
        str(project), '--json', str(gate_dir / 'submission_template_check.json')])
    tapeout_rc = tapeout_declaration_check.main([
        str(project), '--json', str(gate_dir / 'tapeout_declaration_check.json')])
    assert (output / 'submission_template.json').stat().st_size
    assert ingest['lookup']['attempted'] is True
    assert len(ingest['lookup']['searched']) == 1
    assert ingest['lookup']['searched'][0].endswith('/input/submission_template_source')
    if present:
        assert submission_rc == 0 and tapeout_rc == 0
        assert rc == 0
        assert ingest['status'] == 'INGESTED'
        assert json.loads((gate_dir / 'submission_template_check.json').read_text())[
            'check']['verdict'] == 'PASS'
        assert json.loads((gate_dir / 'tapeout_declaration_check.json').read_text())[
            'verdict'] == 'PASS'
        assert json.loads((output / 'submission_template.json').read_text())[
            'ingest']['slots'][0]['source_relpath'] == 's1.yaml'
        assert declaration['route'] == 'SHUTTLE'
        row = json.loads((project / phase1._ST_INPUT_REL).read_text())
        _retain_input_case(project, row['extras']['invoked_producers'], 'supplied-template')
    else:
        # The producer records the absence; the blocking verdict belongs to
        # the canonical gate that consumes its report.
        assert rc == 2
        assert ingest['status'] == 'ABSENT'
        assert ingest['no_template_reason'] is None
        assert ingest['path_selector']['declared'] is False
        assert submission_rc == 1
        gate = json.loads((gate_dir / 'submission_template_check.json').read_text())
        assert gate['check']['verdict'] == 'FAIL'
        assert 'NO_TEMPLATE_WITHOUT_REASON' in {row['rule'] for row in gate['check']['refusals']}
        # The flow evaluator stops at this first blocking clause.  Running the
        # second gate above is only a direct consumer check in this test; it
        # must not turn the first FAIL into a pass.
        assert tapeout_rc == 1  # dependent declaration was not produced
        assert not (project / 'input/submission_template/NO_TEMPLATE.txt').exists()
        # Missing owner input stops the dependent declaration producer.
        assert not (project / 'input/submission_template/SELF_TAPEOUT.txt').exists()
        assert not (project / 'input/submission_template_source').exists()


def _absence_subject(project, reason=None):
    """Only design-owned input; never derive a reason from route or markers."""
    path = project / 'input/step_0_5ic_answers.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'schema': 'vibe-ic/step_0_5ic_answers/1',
            'answers': {'deliverable': 'DIE'},
            'answer_provenance': {'deliverable': {
                'answered_by': 'owner', 'citation': 'Neutral owner requests a DIE.'}}}
    if reason is not None:
        data['operator_template'] = {'absent_reason': reason}
    path.write_text(json.dumps(data) + '\n')
    return path


def _retain_input_case(project, calls, name):
    import os
    import shutil
    import submission_template_check as checker
    evidence = os.environ.get('ISSUE3750_EVIDENCE')
    if evidence:
        target = Path(evidence) / name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'invoked-producers.json').write_text(json.dumps(calls, indent=2))
        for relative in (phase1._ST_INPUT_REL, 'reports/phase1/submission_template.json',
                         'reports/orchestrator/phase1_one_shot.json'):
            path = project / relative
            if path.is_file():
                shutil.copyfile(path, target / path.name)
        checker.main([str(project), '--json', str(target / 'canonical-consumer.json')])


@pytest.mark.parametrize('reason', [None, '', '   ', 'none'], ids=['missing', 'blank', 'whitespace', 'short'])
def test_confirmed_absence_blocks_dependent_producers_with_typed_input(tmp_path, monkeypatch, reason):
    import hashlib
    import submission_template_check as checker
    project = tmp_path / 'subject'
    source = _absence_subject(project, reason)
    # Generated claims and elapsed history cannot replace an answer.
    marker = project / 'input/submission_template/SELF_TAPEOUT.txt'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('Generated DIE/self-tapeout marker; not an owner reason.\n')
    stage_owner_route(project, 'ic')
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    calls = []
    original = phase1._wd.run_host_supervised
    def run(argv, **kwargs):
        calls.append(Path(argv[1]).name)
        return original(argv, **kwargs)
    monkeypatch.setattr(phase1._wd, 'run_host_supervised', run)
    assert phase1._run_step_0_5ic(project) == 2
    assert calls == ['submission_template_fetch.py', 'submission_template_ingest.py']
    row = json.loads((project / phase1._ST_INPUT_REL).read_text())
    assert row['status'] == 'NOT_MEASURED' and row['reason_class'] == 'input_absent'
    assert row['extras']['input_required'] is True
    assert row['extras']['answer_key'] == 'operator_template.absent_reason'
    assert row['extras']['source']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert row['extras']['lookup']['attempted'] is True
    assert row['extras']['lookup']['searched']
    assert row['extras']['blocked_producers'] == ['submission_template_answers.py', 'tapeout_declaration_gen.py']
    assert not (project / 'reports/phase1/submission_template_answers.json').exists()
    assert not (project / 'reports/phase1/tapeout_declaration.json').exists()
    assert checker.main([str(project), '--json', str(project / 'consumer.json')]) == 1
    assert 'NO_TEMPLATE_WITHOUT_REASON' in {r['rule'] for r in json.loads((project / 'consumer.json').read_text())['check']['refusals']}
    _retain_input_case(project, calls, 'blocked-' + ('missing' if reason is None else repr(reason)))


def test_absence_input_resume_reopens_source_and_never_reuses_old_success(tmp_path, monkeypatch):
    import hashlib
    import submission_template_check as checker
    project = tmp_path / 'subject'
    source = _absence_subject(project)
    stage_owner_route(project, 'ic')
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    calls = []
    original = phase1._wd.run_host_supervised
    def run(argv, **kwargs):
        calls.append(Path(argv[1]).name)
        return original(argv, **kwargs)
    monkeypatch.setattr(phase1._wd, 'run_host_supervised', run)
    assert phase1._run_step_0_5ic(project) == 2
    old = json.loads((project / phase1._ST_INPUT_REL).read_text())['extras']['source']['sha256']
    reason = 'The neutral design owner supplies no operator template because this delivery has no purchased shuttle slot.'
    data = json.loads(source.read_text());data['operator_template'] = {'absent_reason': reason}
    source.write_text(json.dumps(data))
    calls.clear()
    assert phase1._run_step_0_5ic(project) == 0
    assert calls == ['submission_template_fetch.py', 'submission_template_ingest.py',
                     'submission_template_answers.py', 'tapeout_declaration_gen.py',
                     'submission_template_check.py', 'tapeout_declaration_check.py']
    row = json.loads((project / phase1._ST_INPUT_REL).read_text())
    assert row['status'] == 'PASS' and row['extras']['input_required'] is False
    assert row['extras']['source']['sha256'] != old
    assert row['extras']['source']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert checker.main([str(project), '--json', str(project / 'consumer.json')]) == 0
    assert json.loads((project / 'consumer.json').read_text())['check']['not_applicable_reason'] == reason
    _retain_input_case(project, calls, 'resumed-valid-source')
    # A previous successful receipt remains on disk; current lookup must win.
    data.pop('operator_template');source.write_text(json.dumps(data))
    calls.clear()
    assert phase1._run_step_0_5ic(project) == 2
    assert calls == ['submission_template_fetch.py', 'submission_template_ingest.py']
    assert checker.main([str(project), '--json', str(project / 'consumer.json')]) == 1
    _retain_input_case(project, calls, 'resumed-retracted-source')


def test_phase1_entry_stops_before_extraction_for_template_input(tmp_path, monkeypatch):
    import sys
    project = tmp_path / 'subject'
    _absence_subject(project)
    stage_owner_route(project, 'ic')
    monkeypatch.setattr(sys, 'argv', [str(phase1.__file__), str(project), '--route', 'ic', '--mode', 'docs'])
    def forbidden(*args, **kwargs):
        pytest.fail('missing template input must stop before Phase1 extraction')
    monkeypatch.setattr(phase1, '_detect_input_mode', forbidden)
    assert phase1.main() == 2
    import _path_layout as layout
    report = json.loads(layout.report_path(project, 'phase1_one_shot.json').read_text())
    assert report['verdict'] == 'NOT_MEASURED' and report['reason_class'] == 'input_absent'
    assert report['input_obligation'] == phase1._ST_INPUT_REL
    assert report['steps'][0]['extras']['input_required'] is True
    _retain_input_case(project, report['steps'][0]['extras']['invoked_producers'], 'normal-phase1-entry')
