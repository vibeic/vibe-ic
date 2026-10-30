"""D01 declaration owner/report/reader seam; not full Phase-1 acceptance.

Document extraction, packaging and expert analysis are out-of-scope edges.
The real main, declaration emitter, owner hook and routed report writer run;
no test constructs a successful D01 producer receipt.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

import _delivery_route as routes
import _path_layout as layout
import execution_policy
import fault_scan_chain_insert as scan
import flow109
import phase1_one_shot_runner as phase1
from test_flow109_selection import profile
from programs.tests.test_issue3444_l20_scan_reconciliation import _intent


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


def _produce(project, monkeypatch, *, route='ic', requires_scan=True, decisions=True):
    docs = project / 'input/docs'
    docs.mkdir(parents=True, exist_ok=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Neutral verification\nThe Plugin MUST declare `plugin_output/declaration.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    intent = _intent() if requires_scan else {'requires_scan': False, 'reason': 'neutral source excludes scan'}
    if decisions:
        _write(project / 'input/feature-decisions.json', {'dft': intent})
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(phase1, '_RUN', copy.deepcopy(phase1._RUN))
    monkeypatch.setattr(phase1, '_run_docs_mode', lambda *_a: 0)
    monkeypatch.setattr(phase1, '_run_step_0_5ic', lambda *_a, **_k: 0)
    monkeypatch.setattr(phase1, 'run_phase1_second_track', lambda *_a: 2)
    monkeypatch.setattr(sys, 'argv', [str(Path(phase1.__file__)), str(project),
                                    '--route', route, '--mode', 'docs', '--execution-mode', 'default'])
    phase1.main()
    report = layout.report_path(project, 'phase1_one_shot.json')
    body = json.loads(report.read_text())
    assert body['dft_intent_output'], body
    assert not (project / 'reports/phase1_one_shot.json').exists()
    features = profile('Small digital IC without DFT' if route == 'ic' else
                       'Mapped soft-IP with prestitched scan' if requires_scan else 'Digital soft-IP')
    features['requires_dft'] = features['requires_scan'] = requires_scan
    return {'features': features}, report, body


@pytest.mark.parametrize('route', ['ic', 'ip'])
@pytest.mark.parametrize('requires_scan', [False, True], ids=['no_scan', 'scan'])
def test_actual_d01_owner_output_is_read_on_both_routes(tmp_path, monkeypatch, route, requires_scan):
    context, report, body = _produce(tmp_path, monkeypatch, route=route, requires_scan=requires_scan)
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    observed = 'BOUND' if binding is not None and not problems else str(problems)
    assert observed == 'BOUND'
    result = flow109.dft_source_intent(tmp_path, context)
    assert result['requires_scan'] is requires_scan
    assert result['source_binding']['sha256'] == body['dft_intent_output']['sha256']
    assert result['source_evidence']['D01']['producer_result'] == {
        'path': report.relative_to(tmp_path).as_posix(),
        'sha256': hashlib.sha256(report.read_bytes()).hexdigest()}
    assert body['delivery_route'] == route.upper()
    assert report == tmp_path / 'reports/orchestrator/phase1_one_shot.json'


def test_current_decision_reemits_instead_of_retaining_old_schema(tmp_path, monkeypatch):
    import spec_declaration_emit as declaration
    _produce(tmp_path, monkeypatch)
    obsolete = _intent(); obsolete['scan_test'] = obsolete.pop('requires_scan')
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(obsolete)]) == 0
    before = (tmp_path / 'plugin_output/declaration.json').read_bytes()
    output = phase1._d01_emit_dft_intent(tmp_path)
    assert output is not None
    current = json.loads((tmp_path / output['path']).read_text())['dft']
    assert current == _intent() and 'scan_test' not in current
    assert (tmp_path / output['path']).read_bytes() != before


def test_missing_current_dft_approval_cannot_reseal_carried_declaration(tmp_path, monkeypatch):
    _produce(tmp_path, monkeypatch)
    _write(tmp_path / 'input/feature-decisions.json', {})
    declaration = tmp_path / 'plugin_output/declaration.json'
    before = declaration.read_bytes()
    result = phase1._d01_emit_dft_intent(tmp_path)
    observed = 'BOUND' if result is not None else 'REFUSED'
    assert observed == 'REFUSED'
    assert declaration.read_bytes() == before


@pytest.mark.parametrize('damage', ['producer', 'producer_source', 'declaration', 'approved_input',
                                    'missing_source', 'route', 'context_route', 'project', 'legacy_report_only'])
def test_actual_consumer_refuses_wrong_or_stale_source(tmp_path, monkeypatch, damage):
    context, report, body = _produce(tmp_path, monkeypatch)
    if damage == 'producer':
        body['dft_intent_output']['producer'] = 'D09'; _write(report, body)
    elif damage == 'producer_source':
        body['dft_intent_output']['producer_source_sha256'] = '0' * 64; _write(report, body)
    elif damage == 'declaration':
        path = tmp_path / body['dft_intent_output']['path']; path.write_text(path.read_text() + '\n')
    elif damage == 'approved_input':
        _write(tmp_path / 'input/feature-decisions.json', {'dft': {'requires_scan': False, 'reason': 'changed source'}})
    elif damage == 'missing_source':
        (tmp_path / 'input/feature-decisions.json').unlink()
    elif damage == 'route':
        body['delivery_route'] = 'IP'; body['deliverable'] = 'HARDMACRO'; _write(report, body)
    elif damage == 'context_route':
        context['features']['ic'] = False; context['features']['ip'] = True
    elif damage == 'project':
        body['project'] = '/different/source/project'; _write(report, body)
    else:
        _write(tmp_path / 'reports/phase1_one_shot.json', body); report.unlink()
    try:
        flow109.dft_source_intent(tmp_path, context)
        observed = 'BOUND'
    except flow109.Flow109Error:
        observed = 'REFUSED'
    assert observed == 'REFUSED'


def test_obsolete_author_input_is_not_converted(tmp_path, monkeypatch):
    _produce(tmp_path, monkeypatch)
    old = _intent(); old['scan_test'] = old.pop('requires_scan')
    _write(tmp_path / 'input/feature-decisions.json', {'dft': old})
    result = phase1._d01_emit_dft_intent(tmp_path)
    assert result is None
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding is None and problems


def _historical_dft_owner(project, monkeypatch):
    """Actual publisher writes its own source identity; no receipt is forged."""
    current_source = phase1.__file__
    old_source = project.parent / (project.name + '-previous-producer.py')
    old_source.write_bytes(Path(current_source).read_bytes() + b'\n# Earlier unrelated release metadata.\n')
    monkeypatch.setattr(phase1, '__file__', str(old_source))
    acquire = phase1._runner_lock.acquire_or_reenter
    held = []
    def capture(*a, **k):
        lock = acquire(*a, **k)
        if lock is not None:
            held.append(lock)
        return lock
    monkeypatch.setattr(phase1._runner_lock, 'acquire_or_reenter', capture)
    try:
        context, report, body = _produce(project, monkeypatch)
    finally:
        for lock in held:
            lock.release()
        monkeypatch.setattr(phase1._runner_lock, 'acquire_or_reenter', acquire)
    monkeypatch.setattr(phase1, '__file__', current_source)
    return context, report, body, old_source


def _refresh(project, old_source, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(Path(phase1.__file__)), str(project),
        '--refresh-dft-intent-from-producer', str(old_source), '--execution-mode', 'default'])
    return phase1.main()


def test_dft_continuation_runs_publisher_without_docs_and_reaches_d19(tmp_path, monkeypatch):
    import flow109_metric_acceptance as metrics
    context, report, body, old_source = _historical_dft_owner(tmp_path, monkeypatch)
    original = report.read_bytes()
    artifact = tmp_path / body['dft_intent_output']['path']
    declaration = artifact.read_bytes()
    unrelated = tmp_path / 'phase1/generated_docs/retained.json'
    _write(unrelated, {'scope': 'unrelated accepted fixture'})
    retained = unrelated.read_bytes()
    calls = []
    for name, rc in (('_run_docs_mode', 0), ('_run_step_0_5ic', 0), ('run_phase1_second_track', 2)):
        def record(*a, _name=name, _rc=rc, **k):
            calls.append(_name)
            return _rc
        monkeypatch.setattr(phase1, name, record)
    assert scan.load_d09_dft_contract(tmp_path)[0] is None
    assert _refresh(tmp_path, old_source, monkeypatch) == 0
    assert calls == []
    current = json.loads(report.read_text())
    assert current['verdict'] == body['verdict']  # no new Phase-1 credit
    assert artifact.read_bytes() == declaration and unrelated.read_bytes() == retained
    history = current['dft_intent_continuations'][-1]
    assert (tmp_path / history['previous_report']).read_bytes() == original
    assert history['previous_report_sha256'] == hashlib.sha256(original).hexdigest()
    assert flow109.dft_source_intent(tmp_path, context)['requires_scan'] is True
    # D19 now reads normal D01 authority and reaches the next actual missing input.
    with pytest.raises(metrics.MetricRefusal) as error:
        metrics.d19_admission(tmp_path, context, publish=False)
    assert 'D19_D01_AUTHORITY_UNAVAILABLE' not in str(error.value)
    assert 'MISSING' in str(error.value)
    claims = [json.loads(x) for x in (tmp_path / 'provenance.jsonl').read_text().splitlines()]
    assert len([x for x in claims if x.get('tool') == 'spec_declaration_emit']) == 2


@pytest.mark.parametrize('damage', ['changed_source', 'missing_source', 'declaration',
                                    'decision', 'historical_source'])
def test_dft_continuation_refuses_changed_authority_before_publication(tmp_path, monkeypatch, damage):
    _, report, body, old_source = _historical_dft_owner(tmp_path, monkeypatch)
    if damage == 'changed_source':
        (tmp_path / 'input/docs/L7_verification_plan.md').write_text('changed authority')
    elif damage == 'missing_source':
        (tmp_path / 'input/docs/L7_verification_plan.md').unlink()
    elif damage == 'declaration':
        path = tmp_path / body['dft_intent_output']['path']; path.write_text(path.read_text() + '\n')
    elif damage == 'decision':
        _write(tmp_path / 'input/feature-decisions.json', {'dft': {'requires_scan': True}})
    elif damage == 'historical_source':
        old_source.write_text('tampered source')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert _refresh(tmp_path, old_source, monkeypatch) == 2
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before


def _legacy_non_scan_owner(project, monkeypatch):
    """Real normal emitter/report, legacy table without a DFT column."""
    import spec_declaration_emit as declaration
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/declaration.json` before authoring:\n\n'
        '| Field | Required | Example |\n|---|---|---|\n| `bit_order` | Yes | LSB_first |\n')
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setattr(phase1, '_RUN', copy.deepcopy(phase1._RUN))
    def extract(*_a):
        assert declaration.main([str(project), '--set', 'bit_order=LSB_first']) == 0
        return 0
    monkeypatch.setattr(phase1, '_run_docs_mode', extract)
    monkeypatch.setattr(phase1, '_run_step_0_5ic', lambda *_a, **_k: 0)
    monkeypatch.setattr(phase1, 'run_phase1_second_track', lambda *_a: 2)
    monkeypatch.setattr(sys, 'argv', [str(Path(phase1.__file__)), str(project),
        '--route', 'ic', '--mode', 'docs', '--execution-mode', 'default'])
    acquire = phase1._runner_lock.acquire_or_reenter
    held = []
    def capture(*a, **k):
        lock = acquire(*a, **k)
        if lock is not None:
            held.append(lock)
        return lock
    monkeypatch.setattr(phase1._runner_lock, 'acquire_or_reenter', capture)
    try:
        phase1.main()
    finally:
        for lock in held:
            lock.release()
        monkeypatch.setattr(phase1._runner_lock, 'acquire_or_reenter', acquire)
    report = layout.report_path(project, 'phase1_one_shot.json')
    body = json.loads(report.read_text())
    assert body['dft_intent_output'] is None
    _write(project / 'input/feature-decisions.json', {
        'dft': {'requires_scan': False, 'reason': 'explicit assigned baseline excludes scan'}})
    return report, body


def _publish_initial(project, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(Path(phase1.__file__)), str(project),
        '--publish-dft-intent', '--execution-mode', 'default'])
    return phase1.main()


def test_legacy_explicit_non_scan_initial_publication_preserves_d01(tmp_path, monkeypatch):
    report, body = _legacy_non_scan_owner(tmp_path, monkeypatch)
    original = report.read_bytes()
    artifact = tmp_path / 'plugin_output/declaration.json'
    declaration = artifact.read_bytes()
    prior_provenance = (tmp_path / 'provenance.jsonl').read_bytes()
    for name in ('_run_docs_mode', '_run_step_0_5ic', 'run_phase1_second_track'):
        def forbidden(*_a, **_k):
            raise AssertionError('DFT-only publication must not run Phase1 tracks')
        monkeypatch.setattr(phase1, name, forbidden)
    assert _publish_initial(tmp_path, monkeypatch) == 0
    current = json.loads(report.read_text())
    assert {k: v for k, v in current.items() if k not in
            ('dft_intent_output', 'dft_intent_continuations')} == {
            k: v for k, v in body.items() if k not in ('dft_intent_output', 'dft_intent_continuations')}
    history = current['dft_intent_continuations'][-1]
    archive = (tmp_path / history['previous_report']).parent
    assert history['initial_publication'] is True
    assert (archive / report.name).read_bytes() == original
    assert (archive / artifact.name).read_bytes() == declaration
    assert (archive / 'provenance.jsonl').read_bytes() == prior_provenance
    assert json.loads(artifact.read_text()) == {'bit_order': 'LSB_first', 'dft': {
        'requires_scan': False, 'reason': 'explicit assigned baseline excludes scan'}}
    context = {'features': profile()}
    binding = flow109.dft_source_intent(tmp_path, context)
    assert binding['requires_scan'] is False
    assert binding['source_binding']['intent']['reason'] == 'explicit assigned baseline excludes scan'
    assert binding['source_evidence']['D01']['producer_result']['sha256'] == hashlib.sha256(report.read_bytes()).hexdigest()


@pytest.mark.parametrize('damage', ['missing_reason', 'legacy_key', 'missing_decision',
    'selection_conflict', 'wrong_producer', 'declaration_drift', 'source_drift', 'unverified_choice'])
def test_initial_non_scan_refuses_before_publication(tmp_path, monkeypatch, damage):
    report, body = _legacy_non_scan_owner(tmp_path, monkeypatch)
    decisions = tmp_path / 'input/feature-decisions.json'
    if damage == 'missing_reason':
        _write(decisions, {'dft': {'requires_scan': False}})
    elif damage == 'legacy_key':
        _write(decisions, {'dft': {'scan_test': False, 'reason': 'legacy'}})
    elif damage == 'missing_decision':
        decisions.unlink()
    elif damage == 'selection_conflict':
        _write(tmp_path / 'input/flow109-manifest.json', {'features': {'requires_scan': True}})
    elif damage == 'wrong_producer':
        body['canonical_producer']['runner'] = 'not_the_d01_owner'; _write(report, body)
    elif damage == 'declaration_drift':
        p = tmp_path / 'plugin_output/declaration.json'; p.write_text(p.read_text() + '\n')
    elif damage == 'unverified_choice':
        import spec_declaration_emit as declaration
        (tmp_path / 'plugin_output/declaration.provenance.json').unlink()
        assert declaration.main([str(tmp_path)]) == 0
    else:
        p = tmp_path / 'input/docs/L7_verification_plan.md'; p.write_text(p.read_text() + '\n')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert _publish_initial(tmp_path, monkeypatch) == 2
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('damage', ['producer', 'decision', 'outside_provenance'])
def test_legacy_non_scan_consumer_keeps_owner_and_provenance_guards(tmp_path, monkeypatch, damage):
    report, body = _legacy_non_scan_owner(tmp_path, monkeypatch)
    assert _publish_initial(tmp_path, monkeypatch) == 0
    if damage == 'producer':
        body = json.loads(report.read_text()); body['dft_intent_output']['producer'] = 'D09'; _write(report, body)
    elif damage == 'decision':
        _write(tmp_path / 'input/feature-decisions.json', {'dft': {'requires_scan': False, 'reason': 'changed reason'}})
    else:
        p = tmp_path / 'plugin_output/declaration.provenance.json'; d = json.loads(p.read_text())
        d['declared_outside_contract']['dft']['provenance'] = 'recovered_from_prose'; _write(p, d)
    binding, problems = scan.load_d09_dft_contract(tmp_path)
    assert binding is None and problems


@pytest.mark.parametrize('damage', ['claim_source_digest', 'wrong_source_implementation', 'unrelated_choice'])
def test_initial_publication_cannot_launder_prior_producer_or_other_choices(tmp_path, monkeypatch, capsys, damage):
    report, _ = _legacy_non_scan_owner(tmp_path, monkeypatch)
    if damage == 'unrelated_choice':
        path = tmp_path / 'input/feature-decisions.json'
        body = json.loads(path.read_text()); body['bit_order'] = 'MSB_first'; _write(path, body)
        expected = 'DFT-only input changes unrelated declaration choices'
    else:
        path = tmp_path / 'provenance.jsonl'
        claims = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        claim = [row for row in claims if row.get('tool') == 'spec_declaration_emit'][-1]
        if damage == 'claim_source_digest':
            claim['source_sha256'] = 'sha256:' + '0' * 64
            expected = 'prior declaration producer source identity differs'
        else:
            import spec_declaration_emit as declaration
            wrong = tmp_path / 'wrong-producer/spec_declaration_emit.py'; wrong.parent.mkdir()
            text = Path(declaration.__file__).read_text()
            assert '"tool": "spec_declaration_emit"' in text
            wrong.write_text(text.replace('"tool": "spec_declaration_emit"', '"tool": "forged_publisher"'))
            claim['argv'][1] = str(wrong)
            claim['source_sha256'] = 'sha256:' + hashlib.sha256(wrong.read_bytes()).hexdigest()
            expected = 'prior declaration producer implementation differs'
        path.write_text(''.join(json.dumps(row) + '\n' for row in claims))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert _publish_initial(tmp_path, monkeypatch) == 2
    assert expected in capsys.readouterr().err
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before



def test_initial_publication_rejects_changed_historical_input_resolver(tmp_path, monkeypatch, capsys):
    _legacy_non_scan_owner(tmp_path, monkeypatch)
    import spec_declaration_emit as declaration
    wrong = tmp_path / 'wrong-helper/spec_declaration_emit.py'; wrong.parent.mkdir()
    text = Path(declaration.__file__).read_text()
    # The real input resolver is used by select_contract/main, but was absent
    # from the former publication-function whitelist. Keep those ten intact.
    import ast
    module = ast.parse(text)
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_iter_doc_texts')
    original = ast.get_source_segment(text, node)
    changed = original.replace('    ', '    # altered historical resolver\n    ', 1)
    # A real semantic change, rather than a comment-only source difference.
    changed += '\n    raise RuntimeError("altered historical input resolver")'
    text = text.replace(original, changed, 1)
    before_functions = {n.name: ast.dump(n, include_attributes=False) for n in module.body
                        if isinstance(n, ast.FunctionDef) and n.name != '_iter_doc_texts'}
    after_functions = {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(text).body
                       if isinstance(n, ast.FunctionDef) and n.name != '_iter_doc_texts'}
    assert before_functions == after_functions  # includes all former ten
    wrong.write_text(text)
    path = tmp_path / 'provenance.jsonl'
    claims = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    claim = [row for row in claims if row.get('tool') == 'spec_declaration_emit'][-1]
    claim['argv'][1] = str(wrong)
    claim['source_sha256'] = 'sha256:' + hashlib.sha256(wrong.read_bytes()).hexdigest()
    path.write_text(''.join(json.dumps(row) + '\n' for row in claims))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert _publish_initial(tmp_path, monkeypatch) == 2
    assert 'prior declaration producer implementation differs' in capsys.readouterr().err
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before
