"""Source-only dispatch controls: no native proof/result/identity is fabricated."""
import json
from pathlib import Path

import pytest
import flow109
import design_one_shot_runner as D
import librelane_contract as LC
import librelane_eqy as EQY
from test_default_frontend_r2 import _produce, put
from programs.tests.test_flow109_selection import profile, _publish_dft_intent


class ReachedEQY(Exception):
    pass


@pytest.fixture
def subject(tmp_path, monkeypatch):
    project, rtl, _ = _produce(tmp_path, monkeypatch)
    features = profile()
    assert features['requires_scan'] is features['requires_dft'] is False
    _publish_dft_intent(project, {'requires_scan': False,
        'reason': 'Source fixture explicitly selects functional equivalence without DFT.'})
    context = flow109.execution_context(flow109.resolve_plan(features), 'D25', 'D25')
    put(project / 'context.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(project / 'context.json'))
    put(project / 'input/flow109/D22.json', {'top': 'top', 'pdk': 'pdkA'})
    put(project / 'reports/flow109/default_rows/D22.json', {
        'step_id': 'D22', 'default_row_status': 'PASS', 'completed': True})
    calls = []
    original = D.subprocess.run
    def no_legacy(argv, *args, **kwargs):
        if len(argv) > 1 and str(argv[1]).endswith('lec_run.py'):
            raise RuntimeError('source control: legacy equiv_* was selected instead of required EQY')
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(D.subprocess, 'run', no_legacy)
    # Stop at actual run_eqy's existing native dispatch, after real config,
    # original RTL, mapped State and EQY script have been produced.
    lib = next((tmp_path / 'pdkroot').rglob('*.lib'))
    def config(project, image, source, output, **kw):
        cfg = json.loads(source.read_text())
        cfg.update({'CELL_LIBS': {'*': [str(lib)]}, 'DEFAULT_CORNER': 'neutral'})
        put(output, cfg)
        return output
    monkeypatch.setattr(EQY, 'resolve_step_config', config)
    def reached(project, image, steps, **kwargs):
        calls.append((project, image, steps, kwargs))
        raise ReachedEQY
    monkeypatch.setattr(EQY, 'run_chain', reached)
    return project, rtl, context, calls


def test_nondft_actual_owner_reaches_eqy_with_original_rtl_and_adopted_mapped(subject):
    project, rtl, context, calls = subject
    # Unselected post-DFT leftovers must not become either proof side.
    put(project / 'phase2/stage2/synth/post_dft_not_run.json', {'verdict': 'NOT_APPLICABLE'})
    with pytest.raises(ReachedEQY):
        D.step_lec_equivalence(project, 'top', 'unused')
    assert len(calls) == 1
    sid, config, state = calls[0][2][0]
    assert sid == 'Yosys.EQY'
    assert json.loads(state.read_text())['nl'] == str(project / 'phase2/stage2/synth/top_synth.v')
    cfg = json.loads(config.read_text())
    assert cfg['VERILOG_FILES'] == [str(rtl)]
    script = Path(cfg['EQY_SCRIPT']).read_text()
    gold = script.split('[gold]', 1)[1].split('[gate]', 1)[0]
    gate = script.split('[gate]', 1)[1].split('[script]', 1)[0]
    assert str(rtl) in gold and 'top_synth.v' not in gold
    assert 'top_synth.v' in gate and 'post_dft_netlist.v' not in gate
    assert not (project / 'reports/lec.json').exists()
    assert not (project / 'reports/lec_eqy.json').exists()


@pytest.mark.parametrize('damage', ['missing_mapped', 'stale_mapped', 'stale_rtl',
    'missing_D01', 'stale_D01', 'unaccepted_D22', 'foreign_top'])
def test_selected_inputs_refuse_before_native_dispatch(subject, damage):
    project, rtl, context, calls = subject
    mapped = project / 'phase2/stage2/synth/top_synth.v'
    if damage == 'missing_mapped': mapped.unlink()
    elif damage == 'stale_mapped': mapped.write_text(mapped.read_text() + '\n// changed')
    elif damage == 'stale_rtl': rtl.write_text(rtl.read_text() + '\n// changed')
    elif damage == 'missing_D01':
        import _path_layout as layout
        layout.report_path(project, 'phase1_one_shot.json').unlink()
    elif damage == 'stale_D01':
        path = project / 'input/feature-decisions.json'
        path.write_text(path.read_text() + ' ')
    elif damage == 'unaccepted_D22':
        put(project / 'reports/flow109/default_rows/D22.json', {
            'step_id': 'D22', 'default_row_status': 'NOT_MEASURED', 'completed': False})
    else: put(project / 'input/flow109/D22.json', {'top': 'foreign', 'pdk': 'pdkA'})
    rows = D.step_lec_equivalence(project, 'top', 'unused')
    assert calls == []
    assert rows[-1].status in ('FAIL', 'NOT_MEASURED')
    assert 'legacy equiv_*' not in rows[-1].detail


@pytest.mark.parametrize('scan,mbist', [(False, False), (False, True), (True, False)])
def test_dft_scan_and_mbist_keep_existing_population(tmp_path, monkeypatch, scan, mbist):
    from test_f1_lec_subject_is_pnr_input import _tree
    project = _tree(tmp_path, scan='authorized' if scan else '')
    features = profile('Mapped soft-IP with prestitched scan') if scan else profile()
    features.update(requires_dft=True, requires_scan=scan)
    if scan:
        # Admit the authored fixture's current L20 + mode-constraint contract.
        # This is a legacy nonphysical scan transport, never a native result.
        import fault_scan_chain_insert as scan_owner
        import scan_mode_constraint as mode
        path = project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json'
        doc = json.loads(path.read_text())
        doc['fields']['scan_chains'][0]['frequency_mhz'] = 10.0
        put(path, doc)
        meta_path = project / 'reports/phase2/dft/scan_chain.json'
        meta = json.loads(meta_path.read_text())
        binding, problems = scan_owner.load_l20_scan_contract(project, 'clk', 1)
        assert not problems
        constraint, problems = mode.emit(project, binding)
        assert not problems
        meta.update(l20_contract=binding, scan_mode_constraint=constraint)
        meta['l20_reconciliation'] = scan_owner.reconcile_l20_scan_contract(binding, meta)
        put(meta_path, meta)
        current, why = scan_owner.l20_binding_is_current(project, meta)
        assert current, why
    if mbist:
        put(project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json', {
            'doc_id': 'L20', 'applicability': 'APPLICABLE', 'extraction_status': 'EXTRACTED',
            'fields': {'dft_present': True, 'scan_chains': [],
                       'bist_mbist': [{'name': 'memory_selftest', 'type': 'MBIST'}]}})
    context = flow109.execution_context(flow109.resolve_plan(features), 'D25', 'D25')
    put(project / 'context.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(project / 'context.json'))
    seen = []
    original = D.subprocess.run
    def stop(argv, *args, **kwargs):
        if len(argv) > 1 and str(argv[1]).endswith('lec_run.py'):
            seen.append(argv)
            raise RuntimeError('source-only stop before existing DFT producer')
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(D.subprocess, 'run', stop)
    D.step_lec_equivalence(project, 'tiny', 'unused')
    assert len(seen) == 1
    argv = seen[0]
    gate = argv[argv.index('--gate-netlist') + 1]
    assert gate.endswith('post_dft_netlist.v' if scan else 'tiny_synth.v')
    assert ('--scan-meta' in argv) is scan


def test_empty_eqy_output_cannot_fall_back_to_legacy_identity(subject):
    import flow109_metric_acceptance as metrics
    project, rtl, context, calls = subject
    folder = project / 'phase3/librelane/lec_eqy/01-yosys-eqy'
    folder.mkdir(parents=True)
    report = EQY.judge_eqy(folder, project / 'reports/lec_eqy.json')
    assert report['verdict'] == 'NOT_MEASURED'
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['component_status'] == 'NOT_MEASURED'
    assert observed['reason'] == 'D25_NATIVE_EXECUTION_ABSENT', observed
    assert not (project / 'reports/lec.json').exists()


@pytest.mark.parametrize('damage', ['none', 'stale_receipt', 'foreign_state', 'stale_script'])
def test_consumer_reopens_empty_transport_without_claiming_proof(subject, damage):
    """Model run_chain transport only; no status/partition/proof is authored."""
    import flow109_metric_acceptance as metrics
    project, rtl, context, calls = subject
    with pytest.raises(ReachedEQY):
        D.step_lec_equivalence(project, 'top', 'unused')
    _, image, steps, kwargs = calls[0]
    sid, config, state = steps[0]
    cfg = json.loads(config.read_text())
    # The synthesis fixture used /pdk guest paths. Bind its existing selected
    # source file via the same config-file mapper before modelling transport.
    synthesis_dir = project / 'phase3/librelane/02-yosys-synthesis'
    synthesis = json.loads((synthesis_dir / 'config.json').read_text())
    assert len({p for group in synthesis['LIB'].values() for p in group}) == 1
    selected = next(iter(synthesis['LIB'].values()))[0]
    if selected.startswith('/pdk/'):
        root = Path(LC.pdk_root_resolution(project, 'pdkA')['path'])
        # Generic EQY must be bound to the same actual model; only this neutral
        # transport fixture has a host/guest split, no PDK aliases are created.
        cfg['CELL_LIBS'] = {'*': [selected]}
        Path(cfg['EQY_SCRIPT']).write_text(EQY.eqy_script('top', [rtl],
            project / 'phase2/stage2/synth/top_synth.v', selected))
        put(config, cfg)
    folder = project / 'phase3/librelane/lec_eqy/01-yosys-eqy'
    folder.mkdir(parents=True)
    put(folder / 'config.json', cfg)
    put(folder / 'state_out.json', json.loads(state.read_text()))
    (folder / 'invocation.log').write_text('SOURCE_FIXTURE transport only; no EQY executed\n')
    mounts = [(Path(LC.pdk_root_resolution(project, 'pdkA')['path']), '/pdk')]
    fingerprint = {'image': str(image), 'step': sid, 'config': LC.digest(config),
        'state': LC.digest(state), 'state_files': {
            str(project / 'phase2/stage2/synth/top_synth.v'):
                LC.digest(project / 'phase2/stage2/synth/top_synth.v')},
        'config_files': LC.config_file_hashes(cfg, mounts),
        'local_image': LC.local_image_attestation()}
    put(folder / 'input_fingerprint.json', fingerprint)
    put(folder / 'pdk_root.json', {'cli_pdk_root': '/pdk',
        'mounts_under_it': [[str(mounts[0][0]), '/pdk']], 'stated_by': 'run_chain(pdk_root=...)'})
    put(folder / 'vibeic_receipt.json', {'input': fingerprint, 'sha256': {
        str(p.relative_to(folder)): LC.digest(p) for p in folder.rglob('*') if p.is_file()}})
    EQY.judge_eqy(folder, project / 'reports/lec_eqy.json')
    if damage == 'stale_receipt': (folder / 'invocation.log').write_text('changed')
    elif damage == 'foreign_state': put(state, {'nl': str(rtl)})
    elif damage == 'stale_script': Path(cfg['EQY_SCRIPT']).write_text('changed')
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['component_status'] == 'NOT_MEASURED', observed
    if damage == 'none':
        assert observed['reason'] == 'D25_NATIVE_TOOL_PURPOSE_UNQUALIFIED', observed
        assert observed['native_consumer']['compared_points'] == 0
    else:
        assert observed['reason'] in ('D25_NATIVE_INPUT_STALE', 'D25_NATIVE_SUBJECT_UNBOUND'), observed



@pytest.mark.parametrize('schema,relocated,damage', [
    ('CELL_LIBS', False, None), ('CELL_LIBS', True, None),
    ('LIB', False, None), ('LIB', True, None),
    ('LIB', True, 'same_bytes_foreign_asset'), ('LIB', True, 'different_library_bytes'),
])
def test_generic_eqy_library_binding_uses_verified_consumed_paths(
        subject, schema, relocated, damage):
    """Existing empty transport only; no native PASS or approval is authored."""
    import flow109_metric_acceptance as metrics
    test_consumer_reopens_empty_transport_without_claiming_proof(subject, 'none')
    project, rtl, context, _ = subject
    root = project / 'phase3/librelane/lec-eqy-config'
    config = root / 'eqy.resolved.json'
    cfg = json.loads(config.read_text())
    selected = next(iter(cfg['CELL_LIBS'].values()))[0]
    proof = selected
    host_root = Path(LC.pdk_root_resolution(project, 'pdkA')['path'])
    if relocated:
        proof = str(host_root / Path(selected).relative_to('/pdk'))
    if damage:
        foreign = project / 'input/foreign.lib'
        foreign.write_bytes(Path(proof).read_bytes())
        if damage == 'different_library_bytes':
            foreign.write_text(foreign.read_text().replace('area : 1', 'area : 2'))
        proof = str(foreign)
    cfg.pop('CELL_LIBS')
    cfg[schema] = {'*': [proof]}
    Path(cfg['EQY_SCRIPT']).write_text(EQY.eqy_script('top', [rtl],
        project / 'phase2/stage2/synth/top_synth.v', proof))
    put(config, cfg)
    folder = project / 'phase3/librelane/lec_eqy/01-yosys-eqy'
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['input']['config'] = LC.digest(config)
    receipt['input']['config_files'] = LC.config_file_hashes(cfg, [(host_root, '/pdk')])
    put(folder / 'config.json', cfg)
    receipt['sha256']['config.json'] = LC.digest(folder / 'config.json')
    put(folder / 'input_fingerprint.json', receipt['input'])
    receipt['sha256']['input_fingerprint.json'] = LC.digest(folder / 'input_fingerprint.json')
    put(receipt_path, receipt)
    observed = metrics.accept_d25(project, context)
    assert observed['status'] == observed['qualification'] == 'NOT_MEASURED', observed
    if damage:
        assert observed['reason'] == 'D25_MODEL_NOT_QUALIFIED', observed
        assert 'library_binding' not in observed
    else:
        assert observed['reason'] == 'D25_NATIVE_TOOL_PURPOSE_UNQUALIFIED', observed
        if schema != 'CELL_LIBS' or relocated:
            actual = (host_root / Path(proof).relative_to('/pdk')
                      if proof.startswith('/pdk/') else Path(proof))
            assert observed['library_binding']['consumed_path'] == str(actual.resolve())
            assert observed['library_binding']['sha256'] == LC.digest(actual)
        assert observed['native_consumer']['compared_points'] == 0


def test_named_fresh_caller_dispatches_existing_producer(subject, monkeypatch):
    """Caller transport only; qualification remains inside unchanged d25_run."""
    project, rtl, context, calls = subject
    put(project / 'input/flow109/D25.json', {'purpose': 'functional_after_observed_reset'})
    entered = []
    def stop(p, top, gold, gate):
        entered.append((p, top, gold, gate))
        raise ReachedEQY
    monkeypatch.setattr(EQY, 'd25_run', stop)
    with pytest.raises(ReachedEQY):
        D.step_lec_equivalence(project, 'top', 'unused')
    assert entered == [(project, 'top', [rtl], project / 'phase2/stage2/synth/top_synth.v')]
    assert not (project / 'reports/lec_eqy_execution.json').exists()


def test_named_fresh_invalid_authority_refuses_in_real_producer(subject, monkeypatch):
    """Actual producer/input reader must reject before any native command."""
    import copy
    import sys
    project, rtl, context, calls = subject
    put(project / 'input/flow109/D25.json', {'purpose': 'functional_after_observed_reset'})
    put(project / 'requirements/base_16/required_lec_partitions.json', {
        'schema': 'vibeic.flow109.requirement-authority.v1',
        'approval': {'status': 'UNAPPROVED', 'authority': 'requirements_owner'}})
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    entered = []
    native_commands = []
    original_run = D.subprocess.run
    def no_native(argv, *args, **kwargs):
        if Path(str(argv[0])).name in ('yosys', 'eqy', 'iverilog', 'sby'):
            native_commands.append(argv)
            raise AssertionError('native tool dispatched before authority admission')
        return original_run(argv, *args, **kwargs)
    monkeypatch.setattr(D.subprocess, 'run', no_native)
    previous = sys.getprofile()
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code.co_filename.endswith('librelane_eqy.py') and frame.f_code.co_name == 'd25_run':
            entered.append(True)
    sys.setprofile(observe)
    try:
        row = D.step_lec_equivalence(project, 'top', 'unused')[-1]
    finally:
        sys.setprofile(previous)
    assert entered == [True]
    assert row.status == 'NOT_MEASURED' and 'METRIC_AUTHORITY_UNAPPROVED' in row.detail
    assert not native_commands
    assert not (project / 'reports/lec_eqy_execution.json').exists()


def test_named_fresh_foreign_execution_symlink_still_refuses(subject, monkeypatch, tmp_path):
    project, rtl, context, calls = subject
    put(project / 'input/flow109/D25.json', {'purpose': 'functional_after_observed_reset'})
    foreign = tmp_path / 'foreign-execution.json'
    foreign.write_text('{}')
    target = project / 'reports/lec_eqy_execution.json'
    target.symlink_to(foreign)
    entered = []
    def stop(*args):
        entered.append(True)
        raise ReachedEQY
    monkeypatch.setattr(EQY, 'd25_run', stop)
    row = D.step_lec_equivalence(project, 'top', 'unused')[-1]
    assert row.status == 'NOT_MEASURED' and 'D25_NATIVE_EXECUTION_ABSENT' in row.detail
    assert not entered


def _fresh_source_handoff(project, reference):
    """Synthetic handoff envelope over unchanged native reference bytes, not proof."""
    import synth_handoff_netlist_check as handoff
    sidecar = project / 'phase2/stage2/synth/synth_inputs.json'
    binding = json.loads(sidecar.read_text())['librelane_synthesis']
    original = reference / binding['folder']
    receipt = json.loads((original / 'vibeic_receipt.json').read_text())
    state = json.loads((original / 'state_out.json').read_text())
    resolver = handoff._project_path_resolver(reference, original, state)
    raw = resolver(state['nl'])
    assert LC.digest(raw) == binding['netlist_sha256']
    assert LC.digest(project / binding['mapped']) == binding['netlist_sha256']
    # Like the existing synthesis factory, author a transport envelope at the
    # current fixture paths. Never re-sign the original native receipt/PASS.
    folder = project / 'phase3/librelane/source-fixture-synthesis'
    folder.mkdir()
    for name in (str(raw.relative_to(original)), 'reports/stat.json',
                 'reports/pre_synth_chk.rpt', 'reports/chk.rpt'):
        source = original / name
        assert LC.digest(source) == receipt['sha256'][name], name
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    original_config = json.loads((original / 'config.json').read_text())
    assert LC.digest(original / 'config.json') == receipt['sha256']['config.json']
    assert LC.digest(original / 'state_out.json') == receipt['sha256']['state_out.json']
    config = {key: original_config[key] for key in (
        'meta', 'DESIGN_NAME', 'PDK', 'SYNTH_TIEHI_CELL', 'SYNTH_TIELO_CELL',
        'TRISTATE_CELLS', 'SYNTH_CHECKS_ALLOW_TRISTATE', 'SYNTH_STRATEGY') if key in original_config}
    manifest = json.loads((project / 'input/flow109/D25.json').read_text())
    config['VERILOG_FILES'] = [str(project / ref['path']) for ref in manifest['rtl']]
    config['CELL_LIBS'] = {'*': [manifest['liberty']['path']]}
    assert LC.digest(Path(manifest['liberty']['path'])) == manifest['liberty']['sha256']
    put(project / 'phase3/librelane/synthesis_resolved.json', config)
    put(folder / 'config.json', config)
    state['nl'] = str(folder / raw.relative_to(original))
    put(folder / 'state_out.json', state)
    # The fixture imports the already-produced mapped artifact; it does not
    # replay synthesis or pretend to consume an unstaged old JsonHeader.
    state_files = {str(project / binding['mapped']): binding['netlist_sha256']}
    fingerprint = {'step': 'Yosys.Synthesis', 'image': 'SOFTWARE_FIXTURE_NOT_NATIVE',
        'config': LC.digest(folder / 'config.json'), 'state_files': state_files,
        'config_files': LC.config_file_hashes(config, [])}
    put(folder / 'input_fingerprint.json', fingerprint)
    put(folder / 'pdk_root.json', {'cli_pdk_root': '/foss/pdks',
        'mounts_under_it': [], 'stated_by': 'run_chain(pdk_root=...)'})
    put(folder / 'vibeic_receipt.json', {'input': fingerprint,
        'source_fixture_only': True, 'original_native_receipt_sha256': LC.digest(
            original / 'vibeic_receipt.json'),
        'sha256': {str(p.relative_to(folder)): LC.digest(p)
                   for p in folder.rglob('*') if p.is_file()}})
    handoff.publish_handoff(project, folder, project / binding['mapped'], binding['top'])
    current = handoff.bound_handoff(project)
    assert current is not None and current['verdict'] == 'PASS', current


@pytest.mark.skipif(not __import__('os').environ.get('FLOW109_D25_FRESH_REFERENCE'),
                    reason='requires the matching cached old qualified runtime and immutable reference')
@pytest.mark.parametrize('invalid_authority', [False, True])
def test_fully_admitted_named_fresh_actual_producer(tmp_path, monkeypatch, invalid_authority):
    """Root7 old-runtime source control; never starts or forges native proof."""
    import os
    import shutil
    reference = Path(os.environ['FLOW109_D25_FRESH_REFERENCE'])
    project = Path('/out/canonical/projects/good')
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    assert any(row[4] == str(project) and 'rw' in row[5].split(',') for row in mounts)
    assert project.resolve() != reference.resolve()
    for child in project.iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(reference, project, dirs_exist_ok=True)
    # Only the disposable copy is fresh; retained original proof stays read-only.
    (project / 'reports/lec_eqy_execution.json').unlink()
    # This clone is an authored source fixture, not a new IC qualification.
    # The old reference's unextracted L20 is not a no-DFT declaration.
    _publish_dft_intent(project, {'requires_scan': False,
        'reason': 'Synthetic fresh-dispatch fixture selects functional equivalence without DFT.'})
    put(project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json', {
        'doc_id': 'L20', 'applicability': 'NOT_APPLICABLE',
        'fields': {'dft_present': False, 'scan_chains': [],
                   'jtag_tap': None, 'compression': None, 'bist_mbist': []}})
    _fresh_source_handoff(project, reference)
    features = profile()
    assert features['requires_scan'] is features['requires_dft'] is False
    context = flow109.execution_context(flow109.resolve_plan(features), 'D25', 'D25')
    context_file = tmp_path / 'context.json'
    put(context_file, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_file))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(project, context)))
    assert flow109.dft_source_intent(project, context)['requires_scan'] is False
    if invalid_authority:
        path = project / 'requirements/base_16/required_lec_partitions.json'
        doc = json.loads(path.read_text())
        doc['approval']['status'] = 'UNAPPROVED'
        put(path, doc)
    reached = []
    # d25_sources is first called AFTER the actual _d25_inputs/admission,
    # exact subject and fresh launch checks, BEFORE any census/tool process.
    def stop_after_admission():
        reached.append(True)
        raise ReachedEQY
    monkeypatch.setattr(EQY, 'd25_sources', stop_after_admission)
    original_run = D.subprocess.run
    commands = []
    def no_native(argv, *args, **kwargs):
        if Path(str(argv[0])).name in ('yosys', 'eqy', 'iverilog', 'sby'):
            commands.append(argv)
            raise AssertionError('source control must stop before native proof')
        return original_run(argv, *args, **kwargs)
    monkeypatch.setattr(D.subprocess, 'run', no_native)
    if invalid_authority:
        row = D.step_lec_equivalence(project, 'test_counter', '')[-1]
        assert row.status == 'NOT_MEASURED' and 'METRIC_AUTHORITY_UNAPPROVED' in row.detail, (row.status, row.detail)
        assert not reached, (row.status, row.detail)
    else:
        try:
            rows = D.step_lec_equivalence(project, 'test_counter', '')
        except ReachedEQY:
            pass
        else:
            pytest.fail(f'producer sentinel not reached: {[(r.status, r.detail) for r in rows]}')
        assert reached == [True]
    assert not commands
    assert not (project / 'reports/lec_eqy_execution.json').exists()
