from pathlib import Path
import json

import pytest

import execution_backend_gates as gates
import execution_backend_producers as producers
import execution_backend_worker as worker
import execution_policy
import flow_compliance_check as fcc
import step_required_inputs_check as required
import step_write_ledger as ledger
from test_native_backend_current_receipts import _retained_default_stream

SPEC = 'phase3/stage4/gds/*.gds'
OWNED = 'phase3/stage4/gds/logical.gds'
FOREIGN = 'phase3/stage4/gds/physical_cell.gds'


def _runtime(monkeypatch, project, top='logical'):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', {
        'project': project, 'policy': {'mode': 'default'},
        'parameters': {'top': top}})


@pytest.fixture
def layout(tmp_path, monkeypatch):
    import klayout.db as db
    for relative, width in ((OWNED, 10), (FOREIGN, 20)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        geometry = db.Layout()
        cell = geometry.create_cell('physical_cell')
        cell.shapes(geometry.layer(1, 0)).insert(db.Box(0, 0, width, 10))
        geometry.write(str(path))
    _runtime(monkeypatch, tmp_path)
    return tmp_path


@pytest.mark.parametrize('consumer', ['snapshot', 'receipt_contract', 'worker',
                                    'fcc', 'ledger', 'input_files', 'input_check'])
def test_every_consumer_selects_only_logical_file_top(layout, consumer):
    before = producers._native_output_identity(layout / FOREIGN)
    if consumer == 'snapshot':
        paths = producers._native_current_step_output_snapshot(layout, '37')
    elif consumer == 'receipt_contract':
        paths = gates.contracts(layout, {'id': 37, 'required_outputs': [SPEC]})[SPEC]
    elif consumer == 'worker':
        paths, missing = worker.resolve_contract(layout, [SPEC])
        assert missing == []
    elif consumer == 'fcc':
        binding = {'available': True, 'rows': {'37': {
            SPEC: {'produced': [FOREIGN, OWNED], 'rejected': []}}}}
        satisfied, paths, *_ = fcc._resolve_required_output(layout, 37, SPEC, binding)
        assert satisfied
    elif consumer == 'ledger':
        paths = ledger._spec_candidates(layout, SPEC)
    elif consumer == 'input_files':
        paths = worker._declared_input_files(layout, [{'from': 37, 'path': SPEC}])
    else:
        row = {'id': 'consumer', 'required_inputs': [{'from': 37, 'path': SPEC}]}
        result = required.check_one(layout, row, {'37': {'required_outputs': [SPEC]}}, {}, None)
        assert result['verdict'] == 'READY'
        paths = [result['inputs'][0]['evidence']]
    assert set(paths) == {OWNED}
    assert producers._native_output_identity(layout / FOREIGN) == before


@pytest.mark.parametrize('token', [SPEC, '--output=' + SPEC])
def test_gate_argv_selects_one_owned_path_including_leaf_glob(layout, token):
    assert fcc._expand_globs([token], layout) == [token.replace(SPEC, OWNED)]


def test_foreign_sibling_cannot_satisfy_missing_logical_output(layout):
    (layout / OWNED).unlink()
    paths, missing = worker.resolve_contract(layout, [SPEC])
    assert paths == {}
    assert missing == [SPEC]
    assert worker.resolve_input_contract(layout, [{'from': 37, 'path': SPEC}]) == [SPEC]
    assert not fcc._resolve_required_output(layout, 37, SPEC, {
        'available': True, 'rows': {'37': {SPEC: {'produced': [FOREIGN]}}}})[0]


@pytest.mark.parametrize('top', [None, '', '../physical_cell', 'a/b', '*', 'wrong'])
def test_unbound_unsafe_or_wrong_top_cannot_credit_sibling(layout, monkeypatch, top):
    _runtime(monkeypatch, layout, top)
    try:
        paths, missing = worker.resolve_contract(layout, [SPEC])
    except (ValueError, worker.em.Refusal) as exc:
        assert 'OUTPUT_TOP' in str(exc)
    else:
        assert paths == {}
        if top == 'wrong':
            assert missing == [SPEC]
        else:
            assert 'OUTPUT_TOP_UNBOUND' in missing[0]


def test_retained_owner_does_not_adopt_foreign_physical_cell(tmp_path, monkeypatch):
    import klayout.db as db
    import phase3_one_shot_runner as runner
    import step_output_collector as versions
    project, params, first, calls = _retained_default_stream(tmp_path, monkeypatch)
    _runtime(monkeypatch, project, params['top'])
    monkeypatch.setattr(runner._ga, 'admitted_gds', lambda *_: True)
    canonical = Path(first['canonical'])
    sibling = canonical.with_name('physical_cell.gds')
    geometry = db.Layout()
    geometry.read(str(canonical))
    geometry.top_cell().shapes(geometry.layer(99, 0)).insert(db.Box(1, 2, 30, 40))
    geometry.write(str(sibling))
    before = producers._native_output_identity(sibling)
    owned_before = producers._native_output_identity(canonical)
    result = producers.produce(project, params)
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'PASS', current
    assert str(sibling.relative_to(project)) not in current['outputs']
    assert str(canonical.relative_to(project)) in current['outputs']
    assert str(canonical.relative_to(project)) not in current.get('retained_outputs', {}).get('outputs', {})
    assert producers._native_output_identity(canonical)['sha256'] != owned_before['sha256']
    assert calls == ['primary', 'seal', 'filler-density'] * 2
    attempt = versions.begin_step(project, '37', params['resolved_input_manifest']['files'])
    published = versions.publish_producer_outputs(project, attempt)
    consumed = worker.execute_current_step(project, step_id='37', producer=result)
    assert consumed['verdict'] == 'PASS', consumed
    canonical_rel = str(canonical.relative_to(project))
    foreign_rel = str(sibling.relative_to(project))
    assert canonical_rel in consumed['outputs'] and foreign_rel not in consumed['outputs']
    row = next(row for row in ledger.build(project)['steps'] if str(row['id']) == '37')
    gds = [entry for entry in row['produced'] if entry['spec'] == SPEC]
    assert [entry['rel'] for entry in gds] == [canonical_rel]
    assert foreign_rel not in json.dumps(published)
    for name in ('gds_substance.json', 'gds_port_labels.json', 'gds_size.json'):
        report = (project / 'reports/phase3' / name).read_text()
        assert canonical_rel in report and foreign_rel not in report
    assert producers._native_output_identity(sibling) == before


def test_new_native_writer_changes_owned_identity_and_is_credited(tmp_path, monkeypatch):
    import _default_backend_fixtures as fixture
    import librelane_contract as contract
    import librelane_fill_dfm as fill
    import phase3_one_shot_runner as runner
    from test_native_backend_current_receipts import _manifest
    project, params, first, calls = _retained_default_stream(tmp_path, monkeypatch)
    _runtime(monkeypatch, project, params['top'])
    canonical = Path(first['canonical'])
    sibling = canonical.with_name('physical_cell.gds')
    import klayout.db as db
    geometry = db.Layout()
    geometry.read(str(canonical))
    geometry.top_cell().shapes(geometry.layer(99, 0)).insert(db.Box(0, 0, 17, 18))
    geometry.write(str(sibling))
    before = producers._native_output_identity(canonical)
    foreign_before = producers._native_output_identity(sibling)
    routed = project / 'phase3/stage3/pnr/routed.def'
    routed.write_text(routed.read_text() + '\n# SOURCE_FIXTURE new route epoch\n')

    def refill(project, top, pdk, container, target, notes):
        record = fixture.fill_record(project, subject=routed)
        fixture.consume_fill(project, record)
        fill.update_record(project, 'odb', {'shipped': 'librelane', 'tool': record,
                                          'def_sha256': contract.digest(routed)})
        return True

    monkeypatch.setattr(runner, '_emit_metal_fill', refill)
    monkeypatch.setattr(runner._ga, 'admitted_gds', lambda *_: False)
    params['resolved_input_manifest'] = _manifest(project, str(routed.relative_to(project)))
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    result = producers.produce(project, params)
    current = result['current_step_declared_producers']
    after = producers._native_output_identity(canonical)
    assert calls == ['primary', 'seal', 'filler-density'] * 2
    assert before.keys() == {'sha256', 'size', 'mtime_ns', 'st_dev', 'st_ino'}
    assert after != before and after['sha256'] != before['sha256']
    assert result['verdict'] == 'PASS', result
    assert str(canonical.relative_to(project)) in current['outputs']
    assert str(sibling.relative_to(project)) not in current['outputs']
    assert str(canonical.relative_to(project)) not in current.get('retained_outputs', {}).get('outputs', {})
    assert producers._native_output_identity(sibling) == foreign_before
    (project / 'd60_writer_observation.json').write_text(json.dumps({
        'scope': 'SOURCE_FIXTURE real KLayout geometry with controlled native process edges',
        'native_calls': calls, 'owned_before': before, 'owned_after': after,
        'foreign_before': foreign_before, 'foreign_after': producers._native_output_identity(sibling),
        'current_receipt': current}, indent=2))


def test_noop_with_valid_promotion_remains_not_measured(tmp_path, monkeypatch):
    project, params, first, calls = _retained_default_stream(tmp_path, monkeypatch)
    _runtime(monkeypatch, project, params['top'])
    producers._step37_retained_output_sources(project, first['receipt'])
    before = producers._native_output_identity(Path(first['canonical']))
    monkeypatch.setattr(producers, 'produce_signoff', lambda *_: {
        'verdict': 'PASS', 'finishing_receipt': first['receipt']})
    result = producers.produce(project, params)
    assert result['verdict'] == 'NOT_MEASURED'
    assert 'NATIVE_CURRENT_OUTPUT_UNCHANGED' in result['current_step_declared_producers']['reason']
    assert calls == ['primary', 'seal', 'filler-density']
    assert producers._native_output_identity(Path(first['canonical'])) == before


def test_true_noop_without_retained_owner_remains_not_measured(layout, monkeypatch):
    from test_native_backend_current_receipts import _manifest
    row = dict(worker.ROWS['37']['canonical_row'], required_outputs=[SPEC])
    monkeypatch.setitem(worker.ROWS['37'], 'canonical_row', row)
    calls = []

    def noop(project, params):
        calls.append('no-op')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_signoff', noop)
    params = {'step_id': '37', 'top': 'logical', 'execution_mode': 'default',
              'resolved_input_manifest': _manifest(layout, FOREIGN)}
    before = producers._native_output_identity(layout / OWNED)
    result = producers.produce(layout, params)
    assert calls == ['no-op']
    assert result['verdict'] == 'NOT_MEASURED'
    assert 'NATIVE_CURRENT_OUTPUT_UNCHANGED' in result['current_step_declared_producers']['reason']
    assert producers._native_output_identity(layout / OWNED) == before


def test_conflicting_explicit_top_refuses_before_native(layout, monkeypatch):
    monkeypatch.setattr(producers, 'produce_signoff', lambda *_: pytest.fail('native started'))
    with pytest.raises(ValueError, match='OUTPUT_TOP_CONFLICT'):
        producers.produce(layout, {'step_id': '37', 'top': 'physical_cell'})


def test_isolated_worker_uses_its_typed_top_and_copies_only_owned_output(layout, monkeypatch):
    row = dict(worker.ROWS['37']['canonical_row'], required_outputs=[SPEC], required_inputs=[])
    monkeypatch.setitem(worker.ROWS['37'], 'canonical_row', row)
    monkeypatch.setattr(worker, 'produce', lambda *_: {'verdict': 'NOT_MEASURED'})
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING', json.dumps({'required_gates': []}))
    result = worker.execute(layout, layout.parent / 'isolated-output',
                            step_id='37', params={'top': 'logical'})
    assert result['verdict'] == 'NOT_MEASURED'
    assert set(result['outputs']) == {OWNED}
    assert not (layout.parent / 'isolated-output' / FOREIGN).exists()


def test_other_project_runtime_does_not_supply_an_unbound_top(layout, monkeypatch):
    _runtime(monkeypatch, layout.parent / 'different-project')
    paths, missing = worker.resolve_contract(layout, [SPEC])
    assert paths == {} and 'OUTPUT_TOP_UNBOUND' in missing[0]


def test_fcc_cannot_credit_selected_file_using_a_foreign_only_ledger(layout):
    binding = {'available': True, 'rows': {'37': {SPEC: {'produced': [FOREIGN]}}}}
    assert not fcc._resolve_required_output(layout, 37, SPEC, binding)[0]


def test_required_input_reports_missing_top_as_named_refusal(layout, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    row = {'id': 'consumer', 'required_inputs': [{'from': 37, 'path': SPEC}]}
    result = required.check_one(layout, row, {'37': {'required_outputs': [SPEC]}}, {}, None)
    assert result['verdict'] == 'BLOCKED'
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in result['reasons'])


def test_selected_gds_keeps_existing_physical_def_pairing(layout):
    import gds_port_label_check as labels
    pnr = layout / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    body = 'VERSION 5.8 ;\nDESIGN physical_cell ;\nPINS 0 ;\nEND PINS\nEND DESIGN\n'
    (pnr / 'routed.def').write_text(body)
    physical = pnr / 'physical_cell.def'
    physical.write_text(body)
    _, all_records = labels.audit(layout, None, None)
    expected = next(record for record in all_records if record['gds_file'] == str(layout / OWNED))
    _, selected = labels.audit(layout, layout / OWNED, None)
    assert selected == [expected]
    assert selected[0]['def_file'] == str(physical)


@pytest.mark.parametrize('consumer', ['dashboard', 'finish_step', 'materialize'])
def test_final_step_retention_keeps_only_the_owned_gds(layout, consumer):
    import flow_dashboard_data as dashboard
    import step_output_collector as versions
    before = producers._native_output_identity(layout / FOREIGN)
    if consumer == 'dashboard':
        data = dashboard.collect(layout, live=False)
        row = next(row for phase in data['phases'] for row in phase['steps'] if str(row['id']) == '37')
        outputs = row['retention_outputs']
    elif consumer == 'finish_step':
        attempt = versions.begin_step(layout, '37')
        outputs = versions.finish_step(layout, attempt, verdict='NOT_MEASURED')['outputs']
    else:
        versions.materialize(layout, only_steps={'37'})
        entry = next(row for row in versions._read_index(layout)['steps'] if str(row['id']) == '37')
        outputs = json.loads((layout / 'steps' / entry['folder'] / 'outputs.json').read_text())['outputs']
    assert {row['rel'] for row in outputs if row['rel'].endswith('.gds')} == {OWNED}
    assert producers._native_output_identity(layout / FOREIGN) == before


def test_nested_gate_keeps_the_same_invocation_top(layout, monkeypatch):
    import flow_artifact_paths as paths
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)

    @fcc._with_child_gate_step
    def nested(project, step):
        return fcc._glob_first(project, SPEC)

    with paths.gate_parameters(layout, {'top': 'logical'}):
        assert nested(layout, {'id': '37'}) == [OWNED]
    with pytest.raises(ValueError, match='OUTPUT_TOP_UNBOUND'):
        paths.resolve(layout, SPEC)


def test_private_full_gate_audit_carries_the_invocation_top(layout, monkeypatch):
    import phase3_one_shot_runner as runner
    import yaml
    flow = layout.parent / 'audit-flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [{
        'id': 37, 'name': 'GDS output', 'stage': 'stage4',
        'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}}]}))
    monkeypatch.setattr(fcc, 'DEFAULT_FLOW_DEF', flow)
    result = runner._phase3_window_full_gate_audit(layout, {'37'})['37']
    assert result['evidence'] == [OWNED], result
    assert not any('OUTPUT_TOP_UNBOUND' in reason for reason in result['reasons'])


def test_unbound_top_cannot_advance_a_retained_pass(layout, monkeypatch):
    import step_output_collector as versions
    attempt = versions.begin_step(layout, '37')
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    record = versions.finish_step(layout, attempt, verdict='PASS', canonical_pass=True)
    assert record['canonical_pass'] is False
    assert record['outputs'] == []
    assert any('OUTPUT_TOP_UNBOUND' in error for error in record['capture_errors'])


def test_steps_view_subprocess_transports_the_typed_top(layout):
    import _path_layout
    import step_output_collector as versions
    result = _path_layout.emit_steps_view(layout, only_steps={'37'})
    assert result['status'] == 'OK', result
    entry = next(row for row in versions._read_index(layout)['steps'] if str(row['id']) == '37')
    record = json.loads((layout / 'steps' / entry['folder'] / 'outputs.json').read_text())
    assert {row['rel'] for row in record['outputs'] if row['rel'].endswith('.gds')} == {OWNED}


@pytest.mark.parametrize('read_only', [False, True])
@pytest.mark.parametrize('workers', ['1', '2'])
def test_fcc_cli_transports_top_through_readonly_clone_and_threadpool(layout, read_only, workers):
    import os
    import subprocess
    import sys
    import yaml
    flow = layout.parent / 'cli-flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [
        {'id': 37, 'name': 'GDS output', 'stage': 'stage4',
         'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}},
        {'id': 38, 'name': 'Other output', 'stage': 'stage4',
         'required_outputs': ['other.txt'], 'gate': {'files_exist': ['other.txt']}}
    ]}))
    (layout / 'other.txt').write_text('source fixture\n')
    report = layout.parent / 'cli-audit.json'
    command = [sys.executable, fcc.__file__, str(layout), '--top', 'logical',
               '--flow-def', str(flow), '--json', str(report)]
    if read_only:
        command.append('--read-only')
    result = subprocess.run(command, capture_output=True, text=True,
                            env={**os.environ, 'VIBE_IC_COMPLIANCE_WORKERS': workers})
    assert report.is_file(), result.stderr
    row = next(row for row in json.loads(report.read_text())['steps'] if str(row['id']) == '37')
    assert OWNED in row['evidence'], row
    assert FOREIGN not in row['evidence']
    assert not any('OUTPUT_TOP_UNBOUND' in reason for reason in row['reasons'])


def test_fcc_cli_scope_resets_after_a_judgement_exception(layout, monkeypatch):
    import flow_artifact_paths as paths
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)

    def refused(args, project):
        assert paths.resolve(project, SPEC) == OWNED
        raise RuntimeError('source fixture judgement failure')

    monkeypatch.setattr(fcc, '_audit_project', refused)
    with pytest.raises(RuntimeError, match='judgement failure'):
        fcc.main([str(layout), '--top', 'logical'])
    with pytest.raises(ValueError, match='OUTPUT_TOP_UNBOUND'):
        paths.resolve(layout, SPEC)


def test_nested_invocation_cannot_replace_the_bound_top(layout):
    import flow_artifact_paths as paths
    with paths.gate_parameters(layout, {'top': 'logical'}):
        with pytest.raises(ValueError, match='OUTPUT_TOP_CONFLICT'):
            with paths.gate_parameters(layout, {'top': 'physical_cell'}):
                pytest.fail('conflicting invocation entered')
        assert paths.resolve(layout, SPEC) == OWNED


@pytest.mark.parametrize('consumer', ['summary', 'summary_audit', 'dashboard_audit'])
def test_existing_audit_launchers_forward_typed_top(layout, monkeypatch, consumer):
    import _path_layout
    import final_report_generate as summary
    import flow_dashboard_data as dashboard
    from types import SimpleNamespace
    seen = []

    def transport(command, **kwargs):
        seen.append(command)
        if '--json' in command:
            Path(command[command.index('--json') + 1]).write_text('{"steps": []}')
        return SimpleNamespace(returncode=0, rc=0, stdout='', stderr='', out='', err='',
                               outcome='natural', stalled=False)

    if consumer == 'summary':
        monkeypatch.setattr(_path_layout._pr, 'run', transport)
        _path_layout.emit_final_summary(layout)
    elif consumer == 'summary_audit':
        monkeypatch.setattr(summary._wd, 'run_host_supervised', transport)
        summary._run_audit(layout)
    else:
        import subprocess
        monkeypatch.setattr(subprocess, 'run', transport)
        dashboard._run_compliance(layout)
    assert len(seen) == 1
    assert seen[0][seen[0].index('--top') + 1] == 'logical'


def test_other_rows_keep_their_existing_parameter_contract(layout, monkeypatch):
    from test_native_backend_current_receipts import _manifest, _native_outputs
    seed = layout / 'seed.txt'
    seed.write_text('source fixture input\n')

    def native(project, params):
        _native_outputs(project, '18')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_pnr', native)
    result = producers.produce(layout, {'step_id': '18',
                                        'resolved_input_manifest': _manifest(layout, 'seed.txt')})
    assert result['verdict'] == 'PASS', result


def test_nested_stage_wrapper_transports_top_to_real_fcc_child(layout):
    import shlex
    import subprocess
    import yaml
    flow = layout.parent / 'stage-flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [{
        'id': 37, 'name': 'GDS output', 'stage': 'stage4',
        'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}}]}))
    report = layout.parent / 'stage-audit.json'
    command = shlex.join(['stage4_compliance', str(layout), '--flow-def', str(flow), '--json', str(report)])
    argv = fcc._resolve_program_cmd(command, layout)
    result = subprocess.run(argv, capture_output=True, text=True)
    assert report.is_file(), result.stderr
    row = next(row for row in json.loads(report.read_text())['steps'] if str(row['id']) == '37')
    assert OWNED in row['evidence'], row
    assert FOREIGN not in row['evidence']


def test_stage_wrapper_does_not_guess_an_unbound_top(layout, monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    assert '--top' not in fcc._resolve_program_cmd('stage4_compliance .', layout)


def test_legacy_window_carries_top_to_collection_and_private_audit(layout, monkeypatch):
    from types import SimpleNamespace
    import flow_artifact_paths as paths
    import phase3_one_shot_runner as runner
    import yaml
    flow = layout.parent / 'window-flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [{
        'id': 37, 'name': 'GDS output', 'stage': 'stage4',
        'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}}]}))
    monkeypatch.setattr(fcc, 'DEFAULT_FLOW_DEF', flow)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(execution_policy, 'dispatch_ordinary_rows', lambda *a, **k: None)
    monkeypatch.setattr(runner, '_restore_recorded_physical_views', lambda *a: {
        'tech_lef': None, 'macro_lefs': [], 'macro_gds': [], 'notes': []})
    monkeypatch.setattr(runner, '_direct_flow_window', lambda *a: runner.StepResult(
        'gds', 'NOT_MEASURED', 0.0, 'source fixture: producer not executed',
        reason_class=runner._V.ReasonClass.NOT_EXECUTED))
    monkeypatch.setenv('VIBEIC_PHASE3_WINDOW_RUN_ID', 'logical-contract')
    args = SimpleNamespace(entry_step='37', exit_step='37', container=None)
    runner._run_phase3_window(layout, 'logical', object(), args, ['gds'])
    audit = json.loads((layout / 'reports/audit/windows/logical-contract/phase23_completion_audit.json').read_text())
    assert audit['declared_gate_checks']['37']['evidence'] == [OWNED]
    assert audit['declared_output_checks']['37']['status'] == 'PRESENT'
    report = json.loads((layout / 'reports/orchestrator/windows/logical-contract/phase3_one_shot.json').read_text())
    assert report['steps_view']['status'] == 'OK'
    with pytest.raises(ValueError, match='OUTPUT_TOP_UNBOUND'):
        paths.resolve(layout, SPEC)


def _topless_cli_audit(layout, *extra):
    import subprocess
    import sys
    import yaml
    flow = layout.parent / 'topless-flow.yaml'
    flow.write_text(yaml.safe_dump({'steps': [
        {'id': 37, 'name': 'GDS output', 'stage': 'stage4',
         'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}},
        {'id': 38, 'name': 'Other output', 'stage': 'stage4',
         'required_outputs': ['other.txt'], 'gate': {'files_exist': ['other.txt']}},
        {'id': 39, 'name': 'GDS gate only', 'stage': 'stage4',
         'gate': {'files_exist': [SPEC]}},
    ]}))
    (layout / 'other.txt').write_text('source fixture\n')
    report = layout.parent / 'topless-audit.json'
    result = subprocess.run(
        [sys.executable, fcc.__file__, str(layout), '--flow-def', str(flow),
         '--json', str(report), *extra], capture_output=True, text=True)
    rows = {str(row['id']): row for row in json.loads(report.read_text())['steps']}
    return result, rows


def test_topless_audit_finishes_and_names_only_the_gds_step_not_measured(layout):
    result, rows = _topless_cli_audit(layout, '--strict')
    assert 'Traceback' not in result.stderr, result.stderr
    assert result.returncode != 0
    assert rows['37']['status'] == 'NOT_MEASURED'
    assert rows['37']['reason_class']
    assert any('OUTPUT_TOP_UNBOUND' in reason for reason in rows['37']['reasons'])
    assert FOREIGN not in rows['37']['evidence'] and OWNED not in rows['37']['evidence']
    assert rows['39']['status'] == 'NOT_MEASURED'
    assert rows['38']['status'] != 'NOT_MEASURED'


def test_topless_audit_refusal_does_not_leak_into_a_top_bound_step(layout, monkeypatch):
    row = {'id': 37, 'name': 'GDS output', 'stage': 'stage4',
           'required_outputs': [SPEC], 'gate': {'files_exist': [SPEC]}}
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    assert fcc.check_step(layout, row, {}).status == 'NOT_MEASURED'
    bound = fcc.check_step(layout, row, {}, parameters={'top': 'logical'})
    assert bound.status != 'NOT_MEASURED'
    assert OWNED in bound.evidence and FOREIGN not in bound.evidence


def test_explicit_conflicting_top_still_raises_instead_of_a_step_row(layout):
    with pytest.raises(ValueError, match='OUTPUT_TOP_CONFLICT'):
        fcc.check_step(layout, {'id': 37, 'name': 'GDS', 'stage': 'stage4',
                                'gate': {'files_exist': [SPEC]}}, {},
                       parameters={'top': 'other'})
