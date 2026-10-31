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
