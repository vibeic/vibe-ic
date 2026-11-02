"""Delivery applicability requires complete-source review, never scanner silence."""
from pathlib import Path
import json
import pytest
import flow109


@pytest.mark.parametrize('prompt', [
    'Implement a module that computes the XOR of two inputs.',
    'Implement a module. Ship the packaged units.',
    'Implement a module. Build it.',
])
def test_unreviewed_prose_cannot_select_source_profile(tmp_path, prompt):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input/phase1_prompt.md').write_text(prompt)
    try:
        selected = flow109.resolve_task_manifest(tmp_path, '1', '2', 'rtl', 'ip')
    except flow109.Flow109Error as exc:
        assert exc.code == 'DELIVERY_OWNERSHIP_UNRESOLVED'
        selected = None
    observed = 'SOURCE_PROFILE_SELECTED' if selected is not None else 'REFUSED'
    assert observed == 'REFUSED'


def test_second_source_obligation_blocks_profile(tmp_path):
    (tmp_path / 'input/docs').mkdir(parents=True)
    (tmp_path / 'input/phase1_prompt.md').write_text('Implement a Verilog module.')
    (tmp_path / 'input/docs/delivery.md').write_text('Deliver GDS for tapeout.')
    assert flow109.resolve_task_manifest(tmp_path, '1', '2', 'rtl', 'ip') is None


def test_explicit_manifest_bytes_are_preserved(tmp_path):
    (tmp_path / 'input').mkdir()
    path = tmp_path / 'input/flow109-manifest.json'
    raw = b'{"features": {"owner_selected": true}}\n'
    path.write_bytes(raw)
    assert flow109.resolve_task_manifest(tmp_path, '1', '2', 'rtl', 'ip') is None
    assert path.read_bytes() == raw


import delivery_intent as di
from _delivery_review_fixture import accept_review, review_files


@pytest.fixture(autouse=True)
def isolated_authority(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_IC_DELIVERY_AUTHORITY_ROOT', str(tmp_path.parent / (tmp_path.name + '-authority')))


def _project(tmp_path, prompt='Implement a synthesizable module with an XOR output.'):
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True)
    (project / 'input/phase1_prompt.md').write_text(prompt)
    return project


@pytest.mark.parametrize('prompt', [
    'Implement a controller for a chip with a ready signal.',
    'Implement a module for a to-be-delivered chip.',
    'Implement a module for a to-be-built chip.',
    'Implement a module for a deliverable chip.',
    'Implement a module for a deployment-ready chip.',
    'Implement a module that controls a chip and build the device.',
    'Implement a module for a chip which must be built.',
    'Implement a module for a chip which must be packaged.',
    'Implement a module. Build it.',
    'Implement a module. Ship the packaged units.',
])
def test_unknown_ownership_never_defaults_to_source_or_ip(tmp_path, prompt):
    decision = di.resolve_project_delivery(_project(tmp_path, prompt))
    assert decision.outcome == 'unresolved'
    with pytest.raises(di.DeliveryRefusal, match='UNRESOLVED'):
        di.require_compatible_target(decision, None)


@pytest.mark.parametrize(('prompt', 'family', 'minimum', 'route'), [
    ('Build a complete chip.', 'DIE', None, 'ic'),
    ('Deliver GDS.', 'DIE', 'gds', 'ic'),
    ('Provide foundry handoff.', 'DIE', 'foundry_handoff', 'ic'),
    ('Build a chip for tapeout.', 'DIE', 'shippable_gds', 'ic'),
    ('Deliver a standalone hardmacro.', 'HARDMACRO', 'ip_hardmacro', 'ip'),
])
def test_recognized_physical_floors_survive_source_review(tmp_path, prompt, family, minimum, route):
    project = _project(tmp_path, prompt)
    decision = di.resolve_project_delivery(project)
    assert decision.outcome == 'physical'
    target = di.require_compatible_target(decision, None)
    assert (target.family, target.minimum_target, target.route) == (family, minimum, route)
    paths = review_files(project)
    response = json.loads(paths['response_path'].read_text())
    response['outcome'] = 'source'
    response['requested_source'] = response['candidate_dispositions'][0]['supports']
    for row in response['candidate_dispositions']:
        row['role'] = 'external_reference'
    task = json.loads(Path(di.issue_review(project)['task_path']).read_text())
    with pytest.raises(di.DeliveryRefusal, match='contradicts retained obligations'):
        di._validate_response(response, task, decision.bundle, decision.evidence)


def test_second_file_conflict_cannot_be_dropped(tmp_path):
    project = _project(tmp_path, 'Build a chip.')
    (project / 'input/docs').mkdir()
    (project / 'input/docs/delivery.md').write_text('Deliver a standalone hardmacro.')
    decision = di.resolve_project_delivery(project)
    assert decision.outcome == 'conflict'
    with pytest.raises(di.DeliveryRefusal, match='CONFLICT'):
        di.require_compatible_target(decision, 'rtl')


def test_fixture_review_admits_current_source_and_preserves_staged_copy(tmp_path):
    project = _project(tmp_path)
    binding = accept_review(project)
    selected = flow109.resolve_task_manifest(project, '1', '2', 'rtl', 'ip')
    assert selected.is_file()
    assert di.require_compatible_target(di.resolve_project_delivery(project), None).route == 'ip'
    (project / 'input/docs').mkdir()
    (project / 'input/docs/design_description.md').write_bytes((project / 'input/phase1_prompt.md').read_bytes())
    di.validate_current_delivery_binding(project, binding)


@pytest.mark.parametrize('change', ['modified', 'added', 'deleted', 'policy', 'action', 'observation', 'dispatch'])
def test_accepted_review_is_not_rehashed_into_fresh_authority(tmp_path, monkeypatch, change):
    project = _project(tmp_path)
    binding = accept_review(project)
    issued = di.issue_review(project)
    authority = di._authority_dir(project) / 'issued' / issued['issuance_id']
    if change == 'modified':
        (project / 'input/phase1_prompt.md').write_text('Implement a different module.')
    elif change == 'added':
        (project / 'input/docs').mkdir()
        (project / 'input/docs/extra.md').write_text('Deliver GDS.')
    elif change == 'deleted':
        (project / 'input/phase1_prompt.md').unlink()
    elif change == 'policy':
        monkeypatch.setattr(di, 'policy_sha256', lambda: '0' * 64)
    else:
        name = {'action': 'action.jsonl', 'observation': 'observation.json', 'dispatch': 'dispatch.txt'}[change]
        with (authority / name).open('ab') as stream:
            stream.write(b'\n')
    with pytest.raises(di.DeliveryRefusal):
        di.validate_current_delivery_binding(project, binding)


@pytest.mark.parametrize('change', ['foreign_parent', 'foreign_thread', 'missing_completion',
                                    'wrong_model', 'swapped_response', 'missing_dispatch', 'unissued',
                                    'stale_source', 'invalid_span', 'duplicate_candidate'])
def test_importer_rejects_bad_observed_actions(tmp_path, change):
    project = _project(tmp_path)
    paths = review_files(project)
    rows = [json.loads(line) for line in paths['runtime_path'].read_text().splitlines()]
    if change == 'foreign_parent':
        rows[0]['payload']['parent_thread_id'] = 'foreign'
    elif change == 'foreign_thread':
        rows[0]['payload']['id'] = 'foreign'
    elif change == 'missing_completion':
        rows.pop()
    elif change == 'wrong_model':
        rows[2]['payload']['model'] = 'other-model'
    elif change == 'swapped_response':
        paths['response_path'].write_text('{}')
    elif change == 'missing_dispatch':
        paths['dispatch_prompt_path'].unlink()
    elif change == 'unissued':
        (di._authority_dir(project) / 'current.json').unlink()
    elif change == 'stale_source':
        (project / 'input/phase1_prompt.md').write_text('Deliver GDS.')
    else:
        response = json.loads(paths['response_path'].read_text())
        if change == 'invalid_span':
            response['requested_source'][0]['excerpt'] = 'invented evidence'
        else:
            response['candidate_dispositions'] *= 2
        paths['response_path'].write_text(json.dumps(response))
        import hashlib
        final = json.loads(rows[-1]['payload']['last_agent_message'])
        final['task_responses'][0]['response_sha256'] = hashlib.sha256(paths['response_path'].read_bytes()).hexdigest()
        rows[-1]['payload']['last_agent_message'] = json.dumps(final)
        rows[-2]['payload']['content'][0]['text'] = json.dumps(final)
    paths['runtime_path'].write_text('\n'.join(json.dumps(row) for row in rows))
    with pytest.raises(di.DeliveryRefusal):
        di.collect_review(project, **paths)


def test_unissued_worker_answer_has_no_authority(tmp_path):
    project = _project(tmp_path)
    (project / 'reports/delivery-ownership').mkdir(parents=True)
    (project / 'reports/delivery-ownership/accepted.json').write_text('{"outcome":"source"}')
    assert di.resolve_project_delivery(project).outcome == 'unresolved'


def test_old_route_schema_cannot_be_upgraded_by_rehash(tmp_path):
    import route_decision as rd
    import task_nature_route as tnr
    project = _project(tmp_path)
    accept_review(project)
    receipt = tnr.route_decision_receipt('Implement a module.', nature='spec_generation',
                                       delivery_binding=di.resolve_project_delivery(project).binding)
    assert rd.validate_route_receipt(receipt, project=project) == []
    receipt['schema'] = 'vibeic.route_decision_receipt.v1'
    receipt['receipt_sha256'] = rd.sha256_json({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
    assert 'ROUTE_RECEIPT_SCHEMA' in rd.validate_route_receipt(receipt, project=project)


def test_coordinator_nature_only_response_cannot_authorize_delivery(tmp_path, monkeypatch):
    import test_ai_first_route_handoff as helper
    import benchmark_dispatch as bd
    import _runtime_pair_fixture as runtime_pair
    runtime_pair.assume_matching_runtime_pair(monkeypatch)
    dataset, run, calls, task = helper._route_response_run(tmp_path, monkeypatch)
    helper._write_raw_answer(task, json.dumps(helper._answer(task, 'spec_generation')))
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any('DELIVERY_OWNERSHIP_UNRESOLVED' in reason for reason in reasons)
    assert calls == []
    assert Path(task['delivery_review']['task_path']).is_file()
    accept_review(Path(task['project']))
    decision, reasons = bd._validate_ai_route(task, run)
    assert reasons == []
    assert decision['delivery_route'] == 'ip'
    assert decision['delivery_target'] == 'rtl'
    receipt = decision['route_receipt']
    bd._seal_route_admission(run, task, decision)
    bd._require_route_admission(run, task, receipt, require_d1=False)
    argv = bd._solver_argv(Path(bd.__file__).parent / 'vibe_ic_one_shot_runner.py',
                          Path(task['project']), receipt['entry_step'], receipt['verify_through'],
                          'ip', receipt['input_contract'], 'rtl')
    assert argv[argv.index('--delivery-target') + 1] == 'rtl'
    # Worker changes both its task and route hashes. The external authority
    # still binds the complete original source and independently accepted action.
    source = Path(task['project']) / 'input/docs/additional.md'
    source.parent.mkdir(exist_ok=True)
    source.write_text('Deliver GDS.')
    import route_decision as rd
    receipt['receipt_sha256'] = rd.sha256_json({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
    with pytest.raises(ValueError, match='DELIVERY_'):
        bd._require_route_admission(run, task, receipt, require_d1=False)
    with pytest.raises(ValueError, match='DELIVERY_'):
        bd._solver_argv(Path('unused-runner'), Path(task['project']), '1', '2', 'ip', 'original', 'rtl')


def test_shipped_profile_selection_uses_real_registry(tmp_path):
    from _hostpaths import require_repo
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'flow109.json')
    registry = json.loads(path.read_text())
    shipped = next(row for row in registry['reference_profiles'] if row['name'] == 'RTL-only')
    project = _project(tmp_path)
    accept_review(project)
    manifest = flow109.resolve_task_manifest(project, '1', '2', 'rtl', 'ip')
    assert json.loads(manifest.read_text()) == {'features': shipped['features']}


@pytest.mark.parametrize('prompt_present', [False, True])
def test_independent_canonical_document_is_included_at_profile_boundary(tmp_path, prompt_present):
    project = _project(tmp_path)
    if not prompt_present:
        (project / 'input/phase1_prompt.md').unlink()
    (project / 'input/docs').mkdir()
    (project / 'input/docs/spec.md').write_text('Implement a synthesizable Verilog module.')
    (project / 'phase1/input_doc').mkdir(parents=True)
    (project / 'phase1/input_doc/delivery.md').write_text('Deliver GDS for tapeout.')
    accept_review(project)
    selected = flow109.resolve_task_manifest(project, '1', '2', 'rtl', 'ip')
    observed = 'SOURCE_PROFILE_SELECTED' if selected is not None else 'REFUSED'
    assert observed == 'REFUSED'


def test_canonical_materialized_copy_and_generated_layers_do_not_add_authority(tmp_path):
    project = _project(tmp_path)
    binding = accept_review(project)
    (project / 'phase1/input_doc').mkdir(parents=True)
    (project / 'phase1/input_doc/prompt.md').write_bytes((project / 'input/phase1_prompt.md').read_bytes())
    (project / 'phase1/generated_docs').mkdir()
    (project / 'phase1/generated_docs/L1.json').write_text('{"content":"Deliver GDS for tapeout."}')
    di.validate_current_delivery_binding(project, binding)
    assert flow109.resolve_task_manifest(project, '1', '2', 'rtl', 'ip').is_file()


@pytest.mark.parametrize('change', ['changed', 'deleted'])
def test_worker_task_copy_cannot_replace_issued_contract(tmp_path, change):
    project = _project(tmp_path)
    binding = accept_review(project)
    path = Path(di.issue_review(project)['task_path'])
    if change == 'deleted':
        path.unlink()
    else:
        raw = json.loads(path.read_text())
        raw['sources'][0]['text'] = 'Different source'
        path.write_text(json.dumps(raw))
    with pytest.raises(di.DeliveryRefusal, match='DELIVERY_REVIEW_TASK_CHANGED'):
        di.validate_current_delivery_binding(project, binding)


def test_coordinator_rechecks_canonical_original_documents(tmp_path, monkeypatch):
    import test_ai_first_route_handoff as helper
    import benchmark_dispatch as bd
    import _runtime_pair_fixture as runtime_pair
    runtime_pair.assume_matching_runtime_pair(monkeypatch)
    _, run, calls, task = helper._route_response_run(tmp_path, monkeypatch)
    helper._write_answer(task, helper._answer(task, 'spec_generation'))
    decision, reasons = bd._validate_ai_route(task, run)
    assert reasons == [] and decision['delivery_route'] == 'ip'
    source = Path(task['project']) / 'phase1/input_doc/delivery.md'
    source.parent.mkdir(parents=True)
    source.write_text('Deliver GDS for tapeout.')
    decision, reasons = bd._validate_ai_route(task, run)
    assert decision is None
    assert any('DELIVERY_REVIEW_STALE' in reason for reason in reasons)
    assert calls == []


def test_malformed_controller_pointer_has_a_named_refusal(tmp_path):
    project = _project(tmp_path)
    di.issue_review(project)
    (di._authority_dir(project) / 'current.json').write_text('{}')
    with pytest.raises(di.DeliveryRefusal, match='DELIVERY_REVIEW_ISSUANCE_INVALID'):
        di.issue_review(project)
    assert di.main(['issue', '--project', str(project)]) == 2


@pytest.mark.parametrize('entry', ['receipt', 'coordinator'])
def test_die_family_without_target_floor_retains_structured_admission(tmp_path, monkeypatch, entry):
    import task_nature_route as tnr
    import route_decision as rd
    prompt = 'Build a complete chip.'
    if entry == 'receipt':
        project = _project(tmp_path, prompt)
        selection = di.require_compatible_target(di.resolve_project_delivery(project), None)
        receipt = tnr.route_decision_receipt(prompt, nature='spec_generation',
                    delivery_target=selection.target, delivery_binding=selection.binding)
    else:
        import test_ai_first_route_handoff as helper
        import benchmark_dispatch as bd
        import _runtime_pair_fixture as runtime_pair
        runtime_pair.assume_matching_runtime_pair(monkeypatch)
        _, run, _, task = helper._route_response_run(tmp_path, monkeypatch, prompt=prompt)
        response = helper._answer(task, 'spec_generation')
        response['prompt_evidence'] = [{'excerpt': prompt, 'supports': 'Build a new chip.'}]
        helper._write_answer(task, response)
        decision, reasons = bd._validate_ai_route(task, run)
        assert reasons == []
        assert decision['delivery_route'] == 'ic'
        receipt = decision['route_receipt']
        project = Path(task['project'])
    assert receipt['delivery_binding']['outcome'] == 'physical'
    assert receipt['input_contract'] == 'structured'
    assert 'D1' in receipt['verify_closed_steps']
    assert rd.validate_route_receipt(receipt, project=project) == []
    assert rd.is_rtl_only_route_receipt(receipt) is False
