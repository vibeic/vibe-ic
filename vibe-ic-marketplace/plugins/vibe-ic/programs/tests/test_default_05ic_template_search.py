"""Canonical Default lookup preserves absent and present operator evidence."""
import hashlib
import json
from pathlib import Path

import pytest
import execution_policy as policy
import phase1_one_shot_runner as phase1
from programs.tests.test_execution_receipt_chain import isolated_transport, real_entry
from programs.tests.test_default_d1_entry import _raw_docs_project


def test_derived_answer_documents_reach_the_real_gate_and_remain_bound(tmp_path):
    import area_budget_basis_gen as area
    import execution_modes as modes
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
    real_entry('IC', 'default', project)
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    assert phase1._run_step_0_5ic(project) == 0
    receipt_path, = (project / 'reports/execution').glob(
        '*/0.5ic/frontend_0_5ic/receipt.json')
    receipt = json.loads(receipt_path.read_text())
    output = Path(receipt['output_root'])
    assert all(row['rc'] == 0 for row in receipt['processes'])
    gate = json.loads((output / 'reports/execution_gates/tapeout_declaration_check.json').read_text())
    assert gate['verdict'] == 'PASS' and gate['refusals'] == []
    assert receipt['evidence']['gates']['submission_template_check'] == 'NOT_APPLICABLE'
    adoption = json.loads((receipt_path.parent.parent / 'adoption.json').read_text())
    assert adoption['status'] == 'ADOPTED'
    assert not modes.required_gate_satisfied('0.5ic', 'tapeout_declaration_check', 'NOT_APPLICABLE')
    assert not modes.required_gate_satisfied('32', 'submission_template_check', 'NOT_APPLICABLE')
    for name, content in docs.items():
        assert receipt['binding']['inputs'][name] == hashlib.sha256(content).hexdigest()
        assert (output / name).read_bytes() == content
    modes.consume_frontend_chain(output, receipt['binding'])
    changed = output / next(iter(docs))
    changed.write_bytes(changed.read_bytes() + b'\nchanged after staging\n')
    with pytest.raises(modes.Refusal, match='STAGED_INPUT_COPY_CHANGED'):
        modes.consume_frontend_chain(output, receipt['binding'])


@pytest.mark.parametrize('present', [False, True], ids=['missing', 'present'])
def test_default_05ic_uses_canonical_search_and_real_gates(tmp_path, present):
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
    real_entry('IC', 'default', project)
    owner_bytes = answer_path.read_bytes()
    policy.bootstrap(project, parameters={'skip_analog': True}, phase1_only=True)
    rc = phase1._run_step_0_5ic(project)
    assert answer_path.read_bytes() == owner_bytes
    receipts = list((project / 'reports/execution').glob('*/0.5ic/frontend_0_5ic/receipt.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    worker, *gates = receipt['processes']
    assert worker['component'] == 'frontend_worker' and worker['rc'] == 0, receipt
    assert receipt['binding']['objective']['template'] == 'input/submission_template_source'
    output = Path(receipt['output_root'])
    chain = json.loads((output / 'issued-producer-chain.json').read_text())['payload']
    assert [Path(stage['argv'][1]).name for stage in chain['stages']] == [
        'submission_template_ingest.py', 'tapeout_declaration_gen.py']
    assert all(stage['rc'] == 0 for stage in chain['stages'])
    for name in ('submission_template', 'tapeout_declaration'):
        rel = 'reports/phase1/' + name + '.json'
        assert hashlib.sha256((output / rel).read_bytes()).hexdigest() == chain['outputs'][rel]
        assert (output / rel).stat().st_ctime_ns == chain['output_ctimes'][rel]
    ingest = json.loads((output / 'reports/phase1/submission_template.json').read_text())['ingest']
    assert ingest['lookup']['attempted'] is True
    assert len(ingest['lookup']['searched']) == 1
    assert ingest['lookup']['searched'][0].endswith('/input/submission_template_source')
    if present:
        assert len(gates) == 2 and all(gate['rc'] == 0 for gate in gates)
        assert rc == 0
        assert ingest['status'] == 'INGESTED'
        assert receipt['evidence']['gates'] == {
            'submission_template_check': 'PASS', 'tapeout_declaration_check': 'PASS'}
        assert json.loads((receipts[0].parent.parent / 'adoption.json').read_text())['status'] == 'ADOPTED'
        assert 'input/submission_template_source/s1.yaml' in receipt['binding']['inputs']
    else:
        assert rc == 1
        assert ingest['status'] == 'ABSENT'
        assert ingest['no_template_reason'] is None
        assert ingest['path_selector']['declared'] is False
        assert len(gates) == 1
        assert gates[0]['component'] == 'submission_template_check' and gates[0]['rc'] == 1
        gate = json.loads((output / 'reports/execution_gates/submission_template_check.json').read_text())
        assert gate['check']['verdict'] == 'FAIL'
        assert 'NO_TEMPLATE_WITHOUT_REASON' in {row['rule'] for row in gate['check']['refusals']}
        # Existing component execution stops at the first nonzero gate. Keep
        # that refusal and its unmeasured remainder; it cannot be adopted.
        assert receipt['status'] == 'NOT_MEASURED'
        assert receipt['reason'] == 'PROCESS_ERROR'
        assert receipt['detail'] == 'PROCESS_ERROR: submission_template_check: rc=1'
        assert not (output / 'reports/execution_gates/tapeout_declaration_check.json').exists()
        assert not (receipts[0].parent.parent / 'selected').exists()
        for marker in ('NO_TEMPLATE.txt', 'SELF_TAPEOUT.txt'):
            assert not (project / 'input/submission_template' / marker).exists()
        assert not (output / 'input/submission_template/NO_TEMPLATE.txt').exists()
        assert not (project / 'input/submission_template_source').exists()
