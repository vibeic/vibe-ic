"""Transport identity and real RTL publisher controls in a fresh process.

The existing admission fixture isolates image/upstream D01 I/O only. Actual
admission, duplicate ledger and RTL snapshot/publication remain in use.
"""
from pathlib import Path
import os
import pytest
from test_canonical_native_owner_identity import admission_case


def _transport_subject(project, monkeypatch):
    """Neutral actual publisher; only upstream D01 is software-isolated."""
    import json
    import design_one_shot_runner as runner
    import ai_signed_judgement as judgement
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs/'L2_FRS.json').write_text(json.dumps({'content':
        'serial-parallel multiplier; synchronous active-high reset'}))
    (docs/'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module':project.name, 'top_ports':[
        {'name':'clk','direction':'input','width':1},
        {'name':'rst','direction':'input','width':1},
        {'name':'parallel_i','direction':'input','width':8},
        {'name':'serial_i','direction':'input','width':1},
        {'name':'serial_o','direction':'output','width':1}]}))
    monkeypatch.setattr(runner, '_serial_d01_state', lambda root: {
        'current':True, 'detail':'SOFTWARE_CONTROL upstream only',
        'evidence_sha256':judgement.evidence_sha256(root,'D1')})
    return runner


def test_transport_materialization_actual_publisher_reopens_once(admission_case, tmp_path, monkeypatch):
    import json
    module, project, programs = admission_case
    runner = _transport_subject(project, monkeypatch)
    original = tmp_path/'original-native.json'
    original.write_text('{"retained":"same bytes"}\n')
    report = project/'reports/native.json';report.parent.mkdir();report.symlink_to(original)
    config = {'pdk':'fixture-pdk','entry_step':'1','exit_step':'1'}
    admit = lambda: module.admit_span(project,'phase2',programs,'fixture-container',config)
    first = admit()
    blocked = runner.step_rtl_gen(project,'digital_arithmetic_primitive')
    assert first.admitted and blocked.status == 'NOT_MEASURED', blocked
    assert blocked.extras['output_refusal']['reason'] == 'PROJECT_SYMLINK_NOT_ISOLATABLE'
    assert not (project/'phase2/stage1/rtl').exists()
    unchanged = admit()
    report.unlink();report.write_bytes(original.read_bytes())
    changed = admit()
    repeated = admit()
    observed = {'scope':'SOURCE_CONTROL actual canonical admission + actual normal RTL publisher; upstream D01 isolated',
                'before':first.reason,'unchanged':unchanged.reason,'after_materialization':changed.reason,
                'repeat':repeated.reason,'before_identity':first.identity,'after_identity':changed.identity,
                'payload_equal':report.read_bytes()==original.read_bytes()}
    (tmp_path/'transport-observation.json').write_text(json.dumps(observed,indent=2)+'\n')
    assert changed.reason == 'ADMITTED', observed
    assert first.identity['source_input_sha256'] == changed.identity['source_input_sha256']
    assert not unchanged.admitted and unchanged.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    progress_globals = runner._pr.run.__globals__
    retained = progress_globals.get('_RUNTIME_PROGRAM_TREE')
    observed['runtime_context'] = {
        'publisher_module':runner.__name__,
        'publisher_retained_root':str(runner._RUNTIME_PROGRAM_TREE.plugin_root) if runner._RUNTIME_PROGRAM_TREE else None,
        'progress_wrapper_module':progress_globals.get('__name__'),
        'progress_wrapper_retained_root':str(retained.plugin_root) if retained else None}
    try:
        produced = runner.step_rtl_gen(project,'digital_arithmetic_primitive')
        observed['publisher_status'] = produced.status
        observed['publisher_detail'] = produced.detail
        (tmp_path/'transport-observation.json').write_text(json.dumps(observed,indent=2)+'\n')
        assert produced.status == 'PASS', {'detail':produced.detail, 'context':observed['runtime_context']}
        assert (project/'phase2/stage1/rtl'/f'{project.name}.v').is_file()
    finally:
        runner._finalize_rtl_provenance();runner._RTL_SESSION_OWNED=False;runner._RTL_SESSION_PROJECT=None


def test_transport_identity_ignores_output_noise_and_unsafe_retargeting(admission_case, tmp_path):
    module, project, programs = admission_case
    external = tmp_path/'outside.json';external.write_text('same native bytes\n')
    other = tmp_path/'different-outside.json';other.write_text('different native bytes\n')
    report = project/'reports/native.json';report.parent.mkdir();report.symlink_to(external)
    cfg = {'entry_step':'1','exit_step':'1'}
    admit = lambda:module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    unsafe = admit();assert unsafe.admitted
    report.unlink();report.symlink_to(other)
    retargeted = admit()
    assert not retargeted.admitted and retargeted.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert retargeted.identity == unsafe.identity
    report.unlink();report.write_bytes(external.read_bytes())
    safe = admit();assert safe.admitted
    report.write_text('arbitrary output payload churn\n')
    (project/'reports/config.json').write_text('{"changed":true}\n')
    (project/'phase3').mkdir();(project/'phase3/operator-notes.txt').write_text('noise\n')
    noise = admit()
    assert not noise.admitted and noise.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert noise.identity == safe.identity
    report.unlink();report.symlink_to(external)
    reverted = admit()
    assert not reverted.admitted and reverted.identity == unsafe.identity


@pytest.mark.parametrize('target_kind', ['absolute_file','relative_escape','directory'])
def test_unsafe_transport_still_refuses_actual_publisher(admission_case, tmp_path, monkeypatch, target_kind):
    module, project, programs = admission_case
    runner = _transport_subject(project, monkeypatch)
    outside = tmp_path/'outside'
    if target_kind == 'directory':outside.mkdir()
    else:outside.write_text('foreign payload must never grant publication\n')
    link = project/'reports/external';link.parent.mkdir()
    link.symlink_to(os.path.relpath(outside,link.parent) if target_kind=='relative_escape' else outside)
    cfg = {'entry_step':'1','exit_step':'1'}
    first = module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    assert first.admitted
    result = runner.step_rtl_gen(project,'digital_arithmetic_primitive')
    assert result.status == 'NOT_MEASURED'
    assert result.extras['output_refusal']['reason'] == 'PROJECT_SYMLINK_NOT_ISOLATABLE'
    assert not (project/'phase2/stage1/rtl').exists()
    repeated = module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    assert not repeated.admitted and repeated.reason == 'DUPLICATE_NO_NEW_EVIDENCE'


def test_isolation_change_after_admission_cannot_publish_rtl(admission_case, tmp_path, monkeypatch):
    module, project, programs = admission_case
    runner = _transport_subject(project, monkeypatch)
    cfg = {'entry_step':'1','exit_step':'1'}
    first = module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    assert first.admitted
    foreign = tmp_path/'foreign';foreign.write_text('outside the isolated snapshot')
    link = project/'reports/late-link';link.parent.mkdir();link.symlink_to(foreign)
    result = runner.step_rtl_gen(project,'digital_arithmetic_primitive')
    assert result.status == 'NOT_MEASURED'
    assert result.extras['output_refusal']['reason'] == 'PROJECT_SYMLINK_NOT_ISOLATABLE'
    assert not (project/'phase2/stage1/rtl').exists()


def test_later_span_does_not_bind_unconsumed_rtl_snapshot_condition(admission_case, tmp_path):
    module, project, programs = admission_case
    foreign = tmp_path/'native';foreign.write_text('unchanged payload\n')
    link = project/'reports/native';link.parent.mkdir();link.symlink_to(foreign)
    cfg = {'entry_step':'2','exit_step':'2'}
    first = module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    link.unlink();link.write_bytes(foreign.read_bytes())
    later = module.admit_span(project,'phase2',programs,'fixture-container',cfg)
    assert first.admitted
    assert not later.admitted and later.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
    assert later.identity == first.identity
