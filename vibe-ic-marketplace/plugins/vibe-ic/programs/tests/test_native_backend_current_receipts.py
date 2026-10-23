"""Native Default producer/consumer boundaries for backend rows 18--20."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import execution_backend_producers as producers  # noqa: E402
import execution_backend_worker as worker  # noqa: E402
from execution_provider_catalog import BACKEND_SITES  # noqa: E402


def _write(project: Path, relative: str, text: str) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _native_outputs(project: Path, step: str) -> None:
    if step == "18":
        _write(project, "phase3/stage3/pnr/post_spare.def",
               "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
        _write(project, "phase3/stage3/pnr/spare_cells.json",
               json.dumps({"spare_count": 4, "target_density": 0.01}))
        _write(project, "reports/spare_cell_coverage.json",
               json.dumps({"verdict": "PASS", "spare_count": 4}))
    elif step == "19":
        _write(project, "phase3/stage3/pnr/post_cts.def",
               "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
        _write(project, "phase3/stage3/cts/clock_tree.rpt",
               "clock latency 1.0 skew 0.1 buffers 2\n")
        # _cts_split publishes this canonical Step19 output as well as the
        # DEF/report. This fixture exercises receipt transport, not native CTS.
        views = {}
        for name, relative in (
                ('post_cts_def', 'phase3/stage3/pnr/post_cts.def'),
                ('cts_rpt', 'phase3/stage3/cts/clock_tree.rpt')):
            views[name] = {'dest': relative, 'dest_sha256': hashlib.sha256(
                (project / relative).read_bytes()).hexdigest()}
        _write(project, "reports/phase3/librelane_cts_handoff.json",
               json.dumps({'scope': 'SOURCE_FIXTURE receipt transport',
                           'views': views}))
    else:
        _write(project, "phase3/stage3/pnr/post_hold.def",
               "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")


def _manifest(project: Path, relative: str) -> dict:
    path = project / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"declarations": [{"from": "external", "path": relative}],
            "files": {relative: digest}, "missing": []}


def _registry_outputs(project: Path, step: str) -> list[str]:
    from execution_adapters_backend import ROWS
    paths = []
    for spec in ROWS[step]['canonical_row']['required_outputs']:
        raw = str(spec).split(' OR ')[0]
        if '*' in raw:
            raw = raw.replace('*', 'fixture')
        path = _write(project, raw, '{}\n' if raw.endswith('.json') else 'fixture\n')
        paths.append(str(path.relative_to(project)))
    return paths


def test_native_rows_create_current_receipt_after_producer(tmp_path, monkeypatch):
    for step, predecessor in (("18", "placed.def"),
                              ("19", "placed.def"),
                              ("20", "post_cts.def")):
        project = tmp_path / step
        _write(project, f"phase3/stage3/pnr/{predecessor}", "input\n")
        events = []

        def native(current_project, _params, *, _events=events, _step=step):
            _events.append("producer")
            _native_outputs(current_project, _step)
            return {"verdict": "PASS", "detail": "native fixture"}

        monkeypatch.setattr(producers, "produce_pnr", native)
        result = producers.produce(
            project, {"step_id": step,
                      "resolved_input_manifest": _manifest(
                          project, f"phase3/stage3/pnr/{predecessor}")})
        current = result["current_step_declared_producers"]
        assert events == ["producer"]
        assert current["schema"] == "vibeic/native-current-step-receipt/1"
        assert current["verdict"] == "PRODUCED", current
        assert current["step_id"] == step
        assert producers._current_step_producer_authority(
            current, project=project) == (True, "", "PASS")
        if step == '19':
            handoff = 'reports/phase3/librelane_cts_handoff.json'
            assert handoff in current['outputs']
            (project / handoff).unlink()
            assert producers._current_step_producer_authority(
                current, project=project) == (
                    False, 'native current producer output changed: ' + handoff,
                    'NOT_MEASURED')


def test_native_receipt_mutation_blocks_consumer(tmp_path, monkeypatch):
    project = tmp_path / "project"
    predecessor = "phase3/stage3/pnr/placed.def"
    _write(project, predecessor, "input\n")
    events = []

    def native(current_project, _params):
        events.append("producer")
        _native_outputs(current_project, "18")
        return {"verdict": "PASS", "detail": "native fixture"}

    monkeypatch.setattr(producers, "produce_pnr", native)
    result = producers.produce(
        project, {"step_id": "18",
                  "resolved_input_manifest": _manifest(project, predecessor)})
    current = result["current_step_declared_producers"]
    output = project / "phase3/stage3/pnr/spare_cells.json"
    output.write_text(output.read_text() + "mutated\n")
    assert producers._current_step_producer_authority(
        current, project=project) == (
            False, "native current producer output changed: "
            "phase3/stage3/pnr/spare_cells.json", "NOT_MEASURED")


def test_worker_calls_consumer_only_after_native_receipt(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs" / "project"
    predecessor = inputs / "phase3/stage3/pnr/placed.def"
    predecessor.parent.mkdir(parents=True)
    predecessor.write_text("input\n")
    outputs = tmp_path / "outputs"
    events = []

    def native(project, _params):
        events.append("producer")
        _native_outputs(project, "18")
        return {"verdict": "PASS", "detail": "native fixture"}

    monkeypatch.setattr(producers, "produce_pnr", native)
    monkeypatch.setattr(worker, "evaluate",
                        lambda _project, _row: events.append("consumer") or
                        {"status": "PASS", "ledger": []})
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({
        "required_gates": [], "source_sha": "fixture"}))
    result = worker.execute(inputs.parent, outputs, step_id="18", params={})
    assert events == ["producer", "consumer"]
    assert result["verdict"] == "PASS"
    assert result["canonical_receipts"][0]["schema"] == \
        "vibeic/backend-producer-receipt/1"


def test_registry_rows_create_receipts_from_catalog_sites(tmp_path, monkeypatch):
    for step in ('27', '32'):
        project = tmp_path / step
        input_path = _write(project, 'inputs/current.txt', 'current\n')
        outputs = _registry_outputs(project, step)

        def native(current_project, _params, _outputs=outputs):
            for raw in _outputs:
                _write(current_project, raw,
                       '{"fresh": 1}\n' if raw.endswith('.json') else 'fresh\n')
            return {'verdict': 'PASS', 'detail': 'registry fixture'}

        monkeypatch.setattr(producers, 'produce_signoff', native)
        result = producers.produce(
            project, {'step_id': step,
                      'resolved_input_manifest': _manifest(
                          project, str(input_path.relative_to(project)))})
        current = result['current_step_declared_producers']
        assert result['verdict'] == 'PASS'
        assert current['verdict'] == 'PRODUCED'
        assert current['producer'] == list(BACKEND_SITES[step])
        assert set(current['preexisting_outputs']) == set(outputs)
        assert producers._current_step_producer_authority(
            current, project=project) == (True, '', 'PASS')


def test_registry_receipt_rejects_unchanged_preexisting_output(tmp_path, monkeypatch):
    project = tmp_path / 'stale'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    _registry_outputs(project, '27')

    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {'verdict': 'PASS'})
    result = producers.produce(
        project, {'step_id': '27',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'NOT_MEASURED'
    assert current['reason'].startswith('NATIVE_CURRENT_OUTPUT_UNCHANGED:')


def test_registry_receipt_rejects_missing_output(tmp_path, monkeypatch):
    project = tmp_path / 'missing'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {'verdict': 'PASS'})
    result = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    current = result['current_step_declared_producers']
    assert result['verdict'] == 'NOT_MEASURED'
    assert current['reason'].startswith('NATIVE_CURRENT_OUTPUT_CONTRACT_UNAVAILABLE:')


def test_registry_measured_fail_survives_missing_outputs(tmp_path, monkeypatch):
    project = tmp_path / 'fail'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    monkeypatch.setattr(producers, 'produce_signoff',
                        lambda _project, _params: {
                            'verdict': 'FAIL', 'detail': 'native failure'})
    result = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})
    assert result['verdict'] == 'FAIL'


def test_registry_receipt_rejects_wrong_identity_and_mutated_input(tmp_path, monkeypatch):
    project = tmp_path / 'mutation'
    input_path = _write(project, 'inputs/current.txt', 'current\n')
    outputs = _registry_outputs(project, '32')

    def native(current_project, _params):
        for raw in outputs:
            _write(current_project, raw, 'fresh\n')
        return {'verdict': 'PASS'}

    monkeypatch.setattr(producers, 'produce_signoff', native)
    current = producers.produce(
        project, {'step_id': '32',
                  'resolved_input_manifest': _manifest(
                      project, str(input_path.relative_to(project)))})[
                          'current_step_declared_producers']
    wrong = dict(current, producer=['wrong-site'])
    assert producers._current_step_producer_authority(
        wrong, project=project) == (
            False, 'native current producer identity is invalid', 'NOT_MEASURED')
    input_path.write_text('mutated\n')
    assert producers._current_step_producer_authority(
        current, project=project) == (
            False, 'native current producer input changed: inputs/current.txt',
            'NOT_MEASURED')


def test_worker_does_not_promote_entire_tree_to_producer_inputs(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs' / 'project'
    inputs.mkdir(parents=True)
    _write(inputs, 'unrelated.txt', 'must not enter receipt\n')
    outputs = tmp_path / 'outputs'
    seen = {}

    def fake_produce(_project, params):
        seen['files'] = params['resolved_input_manifest']['files']
        return {'verdict': 'NOT_MEASURED', 'current_step_declared_producers': None}

    monkeypatch.setattr(worker, 'produce', fake_produce)
    monkeypatch.setenv('VIBEIC_EXECUTION_BINDING',
                       json.dumps({'required_gates': []}))
    worker.execute(inputs.parent, outputs, step_id='32', params={})
    assert seen['files'] == {}


def _retained_default_stream(tmp_path, monkeypatch, *, native_only_provenance=False):
    """Original owner/validators; only native process edges are neutral data."""
    import klayout.db as db
    import librelane_contract as LC
    import librelane_fill_dfm as LF
    import phase3_one_shot_runner as R
    import _runner_measurement
    import test_default_stream_epoch_order as transport
    geometry = transport._geometry

    def substantive_geometry(path, number=0):
        geometry(path, number)
        layout = db.Layout(); layout.read(str(path))
        top = layout.cell('cal_pg')
        # Real neutral geometry, not padding or a relaxed size threshold.
        for index in range(2000):
            top.shapes(layout.layer(1, 0)).insert(
                db.Box(index * 2, 10, index * 2 + 1, 11))
        layout.write(str(path))
    monkeypatch.setattr(transport, '_geometry', substantive_geometry)
    project, pdk, calls, _ = transport._transport(
        tmp_path, monkeypatch, finished_geometry=native_only_provenance)
    if native_only_provenance:
        stream_process = LF.run_chain

        def declared_native_stream(*args, **kwargs):
            folders = stream_process(*args, **kwargs)
            state = json.loads((folders[0] / 'state_out.json').read_text())
            relative = str(Path(state['klayout_gds']).relative_to(project))
            entry = {'record': 'invocation', 'tool': 'klayout', 'exit_code': 0,
                     'scope': 'SOURCE_FIXTURE controlled native process',
                     'outputs': {relative: 'sha256:' + LC.digest(project / relative)},
                     'measurement': _runner_measurement.derive(project, relative, 'klayout')}
            with (project / 'provenance.jsonl').open('a') as stream:
                stream.write(json.dumps(entry) + '\n')
            return folders
        monkeypatch.setattr(LF, 'run_chain', declared_native_stream)
    first = LF.default_stream(project, 'top', pdk, '')
    assert calls == ['primary', 'seal', 'filler-density']
    # A core-only delivery does not owe the independent pad-ring report.
    (project / 'input/submission_template/slots/neutral.yaml').unlink()
    _write(project, 'input/submission_template/tapeout_declaration.json',
           json.dumps({'answers': {'deliverable': 'HARDMACRO'}}))
    _write(project, 'FINAL_REPORT.md', '# SOURCE_FIXTURE\nNo completion claims.\n')
    _write(project, 'plugin_output/declaration.json', '{}\n')
    _write(project, 'reports/phase3/pad_ring_route_evidence.json', json.dumps({
        'verdict': 'NOT_APPLICABLE', 'reason': 'SOURCE_FIXTURE core-only delivery'}))
    canonical = Path(first['canonical'])
    relative = str(canonical.relative_to(project))
    if not native_only_provenance:
        _write(project, 'provenance.jsonl', json.dumps({
            'record': 'invocation', 'tool': 'klayout', 'exit_code': 0,
            'scope': 'SOURCE_FIXTURE controlled native process',
            'outputs': {relative: 'sha256:' + LC.digest(canonical)},
            'measurement': _runner_measurement.derive(project, relative, 'klayout'),
        }) + '\n')
    monkeypatch.setattr(producers, '_parameters', lambda *_: (R, LC, pdk, ''))
    monkeypatch.setattr(R, 'step_prestream_gate', lambda *_: R.StepResult(
        'prestream', 'PASS', 0.0, 'SOURCE_FIXTURE upstream admission',
        extras={'layout_digest': LC.digest(project / 'phase3/stage3/pnr/routed.def')}))
    monkeypatch.setattr(R, '_layout_basis', lambda *_: ('fixture-layout', None))
    monkeypatch.setattr(R, '_vacuous_on_unrouted', lambda *_: None)
    monkeypatch.setattr(R._ga, 'stream_refusal', lambda *_: None)
    monkeypatch.setattr(R._ga, 'admit_gds', lambda *_: None)
    monkeypatch.setattr(R, '_layout_basis_paths', lambda *_: [])
    monkeypatch.setattr(R, '_chip_path_requests_pad_ring', lambda *_: False)
    monkeypatch.setattr(R, '_librelane_antenna_gds', lambda *_: None)
    # Only the optional native antenna tool edge is neutral. The actual full
    # consumer, size/substance/port/provenance programs and LF/LC readers run.
    import flow_compliance_check as fcc
    gate_process = fcc._watchdog.run_host_supervised

    def native_gate_edge(argv, **kwargs):
        if len(argv) > 1 and Path(argv[1]).name == 'gds_antenna_deck_check.py':
            report = project / argv[argv.index('--json') + 1]
            _write(project, str(report.relative_to(project)), json.dumps({
                'verdict': 'PASS', 'evidence_kind': 'SOURCE_FIXTURE native process',
                'gds_sha256': LC.digest(canonical)}))
            return fcc._watchdog.SupervisedResult(
                0, 'SOURCE_FIXTURE optional native antenna process\n', '', 'natural')
        return gate_process(argv, **kwargs)
    monkeypatch.setattr(fcc._watchdog, 'run_host_supervised', native_gate_edge)
    params = {'step_id': '37', 'top': 'top', 'pdk_name': pdk.name,
              'pdk_root': str(project / 'fixture_pdk'), 'image_id': first['image'],
              'execution_mode': 'default',
              'resolved_input_manifest': _manifest(
                  project, 'phase3/stage3/pnr/routed.def')}
    return project, params, first, calls


@pytest.mark.parametrize('scenario', ['current', 'changed_final_gds', 'missing_native_proof'])
def test_default_step37_finishing_publishes_measured_provenance(
        tmp_path, monkeypatch, scenario):
    import librelane_fill_dfm as LF
    import librelane_contract as LC
    import phase3_one_shot_runner as R
    import provenance_check
    import step_output_collector as versions
    project, params, first, calls = _retained_default_stream(
        tmp_path, monkeypatch, native_only_provenance=True)
    canonical = Path(first['canonical'])
    ledger = project / 'provenance.jsonl'
    entries = [json.loads(line) for line in ledger.read_text().splitlines()]
    native = [entry for entry in entries if entry.get('record') == 'invocation']
    assert len(native) == 1
    assert set(native[0]['outputs']) == {str(Path(first['stream']).relative_to(project))}
    assert first['stream_sha256'] != first['source_sha256'], 'finishing changed real neutral geometry'
    argv = [str(project), '--output=phase3/stage4/gds/*.gds',
            '--tool=klayout,magic,openroad', '--require-measured']
    assert provenance_check.main(argv) == 0, 'fresh normal LF publication must declare final material'
    artefacts = [entry for entry in entries if entry.get('record') == 'artefact']
    retained = [entry for entry in artefacts if entry.get('produced_by') ==
                'librelane_default_finishing_retention']
    assert len(retained) == 1
    [(retained_relative, retained_sha)] = retained[0]['outputs'].items()
    assert Path(retained_relative).parent == Path('phase3/stage3/pnr/streamout')
    assert retained_relative != str(Path(first['source']).relative_to(project))
    assert retained_sha == 'sha256:' + first['source_sha256']
    assert LC.digest(project / retained_relative) == first['source_sha256']
    assert retained[0]['reconstructed'] is True
    assert retained[0]['measurement']['measured'] is True
    assert retained[0]['measurement']['wrote'] == [retained_relative]
    # The native lane is reusable; both delivery aliases must derive from the
    # independently retained finished bytes, not a newly asserted invocation.
    publications = [entry for entry in entries if entry.get('record') ==
                    'declared_transform' and entry.get('producing_step') ==
                    'step37_default_finishing_publication']
    assert len(publications) == 2
    assert {relative for entry in publications for relative in entry['outputs']} == {
        str(Path(first[name]).relative_to(project)) for name in ('pnr_gds', 'canonical')}
    for entry in publications:
        assert entry['inputs'] == {retained_relative: retained_sha}
        assert list(entry['outputs'].values()) == [retained_sha]
        assert entry['reconstructed'] is True
        assert entry['tool'] == 'klayout' and entry['exit_code'] == 0
        assert entry['measurement']['measured'] is True
        assert entry['measurement']['wrote'] == list(entry['outputs'])
    assert all(entry.get('duration_ms') is None for entry in entries if entry not in native)
    # Resume the actual historical case: only native-path provenance survived;
    # none declares the different final bytes or either delivery alias.
    ledger.write_text(''.join(json.dumps(entry) + '\n' for entry in native))
    assert provenance_check.main(argv) != 0
    identities = {name: (LC.digest(Path(first[name])), Path(first[name]).stat().st_mtime_ns)
                  for name in ('source', 'pnr_gds', 'canonical')}
    if scenario == 'changed_final_gds':
        canonical.write_bytes(canonical.read_bytes() + b'changed')
    elif scenario == 'missing_native_proof':
        (Path(first['stream_state']).parent / 'vibeic_receipt.json').unlink()
    if scenario != 'current':
        with pytest.raises((LF.Refusal, ValueError, KeyError)):
            R._step37_declare_streamout_gds_provenance(project, 'top', default_finishing=True)
        assert ledger.read_text() == ''.join(json.dumps(entry) + '\n' for entry in native)
        assert provenance_check.main(argv) != 0
        return
    result = producers.produce(project, params)
    assert result['verdict'] == 'PASS', result
    attempt = versions.begin_step(project, '37', params['resolved_input_manifest']['files'])
    versions.publish_producer_outputs(project, attempt)
    consumed = worker.execute_current_step(project, step_id='37', producer=result)
    assert consumed['verdict'] == 'PASS', consumed
    assert consumed['canonical_step_result']['status'] == 'PASS'
    assert any(row.get('gate') == 'provenance_check' and row.get('rc') == 0
               for row in consumed['gate_ledger'])
    assert provenance_check.main(argv) == 0
    assert calls == ['primary', 'seal', 'filler-density'], 'retained publication runs no native epoch'
    assert {name: LC.digest(Path(first[name])) for name in identities} == {
        name: identity[0] for name, identity in identities.items()}
    # The existing outer producer always copies the stage4 alias. The source
    # and pnr stream remain untouched; publication itself is ledger-only.
    assert {name: Path(first[name]).stat().st_mtime_ns for name in ('source', 'pnr_gds')} == {
        name: identities[name][1] for name in ('source', 'pnr_gds')}


@pytest.mark.parametrize('scenario', [
    'current_reuse', 'changed_log', 'changed_gds', 'changed_readset',
    'changed_recipe', 'missing_native_proof', 'density_not_current'])
def test_default_step37_whole_reuse_reaches_current_consumer(
        tmp_path, monkeypatch, scenario):
    import librelane_fill_dfm as LF
    import phase3_one_shot_runner as R
    import step_output_collector as versions
    project, params, first, calls = _retained_default_stream(tmp_path, monkeypatch)
    log = project / 'phase3/stage3/pnr/stream_out.log'
    before = log.read_bytes(), log.stat().st_mtime_ns

    def after_stream(*_):
        # Mutate one actual retained artefact after the normal owner returned,
        # before the native-current collector. Do not stub its validators.
        targets = {
            'changed_log': log, 'changed_gds': Path(first['canonical']),
            'changed_readset': project / 'phase3/stage3/pnr/top.stream_inputs.json',
            'changed_recipe': project / 'phase3/stage3/pnr/stream_out.py',
            'missing_native_proof': Path(first['stream_state']).parent / 'vibeic_receipt.json',
            'density_not_current': project / 'reports/phase3/metal_density.json'}
        if scenario == 'missing_native_proof':
            targets[scenario].unlink()
        elif scenario in targets:
            targets[scenario].write_bytes(targets[scenario].read_bytes() + b'\nchanged\n')
    monkeypatch.setattr(R, '_librelane_antenna_gds', after_stream)
    # Real produce_signoff -> real step_gds -> existing whole-reuse owner;
    # omitting finishing_receipt at that return site must break the positive.
    result = producers.produce(project, params)
    current = result['current_step_declared_producers']
    if result['verdict'] == 'PASS':
        # The retained leaf has closed its invocation. Publish the ordinary
        # current consumer's existing attribution, backed by its producer receipt.
        attempt = versions.begin_step(project, '37', params['resolved_input_manifest']['files'])
        versions.publish_producer_outputs(project, attempt)
    consumed = worker.execute_current_step(project, step_id='37', producer=result)
    assert calls == ['primary', 'seal', 'filler-density'], 'no second native epoch'
    if scenario != 'current_reuse':
        assert result['verdict'] == 'NOT_MEASURED'
        assert 'NATIVE_CURRENT_OUTPUT_UNCHANGED' in current['reason']
        assert consumed['verdict'] == 'NOT_MEASURED'
        return
    assert result['verdict'] == 'PASS', result
    assert result['finishing_receipt'] == str(project / LF.DEFAULT_STREAM_REL)
    assert (log.read_bytes(), log.stat().st_mtime_ns) == before
    adopted = current['retained_outputs']['outputs']
    assert str(log.relative_to(project)) in adopted
    assert set(adopted) <= set(current['outputs'])
    assert consumed['verdict'] == 'PASS', consumed
    assert consumed['canonical_step_result']['status'] == 'PASS'
    assert any(row.get('gate') == 'gds_substance_check'
               and row.get('rc') == 0 for row in consumed['gate_ledger'])
    # Consumer re-derives promotion/density proof, not just the output hashes.
    promotion = project / LF.DEFAULT_STREAM_REL
    promotion.unlink()
    refused = worker.execute_current_step(project, step_id='37', producer=result)
    assert refused['verdict'] == 'NOT_MEASURED'
    assert 'native retained stream refused' in refused['gate_ledger'][0]['reason']


@pytest.mark.parametrize('scenario', [
    'current_fill', 'changed_filled_def', 'changed_density_json',
    'changed_density_rpt', 'changed_fill_marker', 'missing_native_proof'])
def test_default_step34_retained_fill_reaches_current_consumer(
        tmp_path, monkeypatch, scenario):
    import librelane_contract as LC
    import librelane_fill_dfm as LF
    import phase3_one_shot_runner as R
    import step_output_collector as versions
    project, params, promotion, calls = _retained_default_stream(tmp_path, monkeypatch)
    # The neutral retained packets use the existing synthetic image route.
    # Run this exact checker CLI in-process so that route fixture also applies
    # to its real LF/LC readers; never replace the checker/validator verdict.
    import contextlib
    import io
    import flow_compliance_check as fcc
    import metal_fill_density_check as density_check
    gate_process = fcc._watchdog.run_host_supervised

    def density_consumer_transport(argv, **kwargs):
        if len(argv) > 1 and Path(argv[1]).name == 'metal_fill_density_check.py':
            report = project / argv[argv.index('--json') + 1]
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = density_check.main([str(project), '--json', str(report)])
            return fcc._watchdog.SupervisedResult(
                rc, stdout.getvalue(), stderr.getvalue(), 'natural')
        return gate_process(argv, **kwargs)
    monkeypatch.setattr(fcc._watchdog, 'run_host_supervised', density_consumer_transport)
    tool = LF._load(project / LF.RECORD_REL)['odb']['tool']
    pnr = project / 'phase3/stage3/pnr'
    subject = R._measured_subject(
        project, promotion['file_top'], [Path(tool['subject']), pnr / 'filled.def'],
        tool_log=Path(tool['state']).parent / 'openroad-fillinsertion.log')
    LF.write_direct_schema_reports(project, tool, subject, R._measured_subject_lines(subject))
    # Replace only the earlier neutral transport's minimal density placeholder
    # with the original writer's document, keeping both declared aliases equal.
    phase3_json = project / 'reports/phase3/density.json'
    phase3_json.write_bytes((project / 'reports/density.json').read_bytes())
    params['step_id'] = '34'
    params['resolved_input_manifest'] = _manifest(project, 'phase3/stage4/gds/top.gds')
    paths = [pnr / 'filled.def', pnr / 'metal_fill.done',
             project / 'reports/density.json', phase3_json,
             project / 'reports/density.rpt']
    unchanged = {str(p.relative_to(project)): producers._native_output_identity(p) for p in paths}
    targets = {'changed_filled_def': pnr / 'filled.def',
               'changed_density_json': phase3_json,
               'changed_density_rpt': project / 'reports/density.rpt',
               'changed_fill_marker': pnr / 'metal_fill.done',
               'missing_native_proof': Path(tool['state']).parent / 'vibeic_receipt.json'}
    if scenario == 'missing_native_proof':
        targets[scenario].unlink()
    elif scenario in targets:
        target = targets[scenario]
        if scenario == 'changed_density_json':
            doc = json.loads(target.read_text()); doc['filler_instances'] += 1
            target.write_text(json.dumps(doc))
        else:
            target.write_bytes(target.read_bytes() + b'\nchanged\n')
    if scenario in ('changed_filled_def', 'missing_native_proof'):
        with pytest.raises(LC.Refusal, match='LL_FILL_(HANDOFF_UNBOUND|NOT_CONSUMED)'):
            producers.produce(project, params)
        return
    result = producers.produce(project, params)
    if result['verdict'] == 'PASS':
        attempt = versions.begin_step(project, '34', params['resolved_input_manifest']['files'])
        versions.publish_producer_outputs(project, attempt)
    consumed = worker.execute_current_step(project, step_id='34', producer=result)
    assert calls == ['primary', 'seal', 'filler-density'], 'no second fill or native epoch'
    if scenario != 'current_fill':
        assert result['verdict'] == 'NOT_MEASURED'
        assert 'NATIVE_CURRENT_OUTPUT_UNCHANGED' in result['current_step_declared_producers']['reason']
        assert consumed['verdict'] == 'NOT_MEASURED'
        return
    assert result['verdict'] == 'PASS', result
    assert consumed['verdict'] == 'PASS', consumed
    assert consumed['canonical_step_result']['status'] == 'PASS'
    assert any(row.get('gate') == 'metal_fill_density_check' and row.get('rc') == 0
               for row in consumed['gate_ledger'])
    assert {str(p.relative_to(project)): producers._native_output_identity(p) for p in paths} == unchanged
    current = result['current_step_declared_producers']
    assert set(current['retained_outputs']['outputs']) == set(unchanged)
    (project / 'STEP34_CURRENT_CONSUMER_OBSERVATION.json').write_text(json.dumps(consumed, indent=2))
    # Intact alias hashes alone do not preserve authority after native proof loss.
    (Path(tool['state']).parent / 'vibeic_receipt.json').unlink()
    refused = worker.execute_current_step(project, step_id='34', producer=result)
    assert refused['verdict'] == 'NOT_MEASURED'
    assert 'native retained stream refused' in refused['gate_ledger'][0]['reason']


@pytest.mark.parametrize('mutation', ['current', 'changed_final_gds', 'missing_native_proof'])
def test_admitted_default_stream_rechecks_owner_without_restarting_native_producers(
        tmp_path, monkeypatch, mutation):
    import phase3_one_shot_runner as R
    import librelane_contract as LC
    project, params, first, calls = _retained_default_stream(
        tmp_path, monkeypatch, native_only_provenance=True)
    monkeypatch.setattr(R._ga, 'admitted_gds', lambda *_: True)
    restarted = []
    def prestream(*args, **kwargs):
        restarted.append('prestream')
        return R.StepResult('prestream', 'PASS', 0.0, 'SOURCE_FIXTURE transport',
                            extras={'layout_digest': 'fixture-layout'})
    def stream(*args, **kwargs):
        restarted.append('stream')
        return R.StepResult('gds', 'PASS', 0.0, 'SOURCE_FIXTURE transport',
                            extras={'finishing_receipt': first['receipt']})
    monkeypatch.setattr(R, 'step_prestream_gate', prestream)
    monkeypatch.setattr(R, 'step_gds', stream)
    if mutation == 'changed_final_gds':
        with Path(first['canonical']).open('ab') as output:
            output.write(b'changed native output')
    elif mutation == 'missing_native_proof':
        Path(first['stream_state']).with_name('vibeic_receipt.json').unlink()
    result = None
    try:
        result = producers.produce_signoff(project, params)
    except LC.Refusal:
        pass
    assert len(restarted) == 0, restarted
    if mutation == 'current':
        assert result['verdict'] == 'PASS', result
        assert result['finishing_receipt'] == first['receipt']
        assert calls == ['primary', 'seal', 'filler-density']
    else:
        assert result is None, result
