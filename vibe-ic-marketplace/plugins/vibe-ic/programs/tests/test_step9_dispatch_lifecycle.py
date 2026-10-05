"""Step9 input lifetime: real staging and installed-tool admission, no synthesis."""
import json
import os
import time
from pathlib import Path

import pytest
import execution_modes as em
import execution_policy as policy
import execution_production as production
from programs.tests import test_execution_receipt_chain as R
from programs.tests.test_execution_ordinary_composition import clean_runtime

isolated_transport = R.isolated_transport


@pytest.mark.parametrize('prior_rtl', [False, True], ids=['absent', 'replaced'])
def test_step9_binds_after_real_staging(tmp_path, monkeypatch, prior_rtl):
    image = os.environ.get('VIBEIC_STEP9_INSTALLATION_TEST_IMAGE')
    if not image:
        pytest.skip('requires an installed pinned image for the real version probe')
    started = time.monotonic()
    print('STEP9_LIFECYCLE_START', prior_rtl, flush=True)
    import librelane_contract as ll
    import phase3_one_shot_runner as phase3
    import reused_ip_rtl_consume as consume
    from test_librelane_contract_production_defaults import _chip
    project = _chip(tmp_path / 'project')
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text('{"top_module":"top"}')
    source = project / 'input/vendor_rtl/top.v'
    source.parent.mkdir(parents=True)
    source.write_text('module top(input a, output z); assign z = a; endmodule\n')
    rtl = project / 'phase2/stage1/rtl/top.v'
    if prior_rtl:
        rtl.parent.mkdir(parents=True)
        rtl.write_text('module top(input a, output z); assign z = ~a; endmodule\n')
    root = tmp_path / 'pdk'
    lib = root / 'libs.ref/cells.lib'
    lib.parent.mkdir(parents=True)
    lib.write_text('library (cells) { cell (buf) { area : 1; } }\n')
    config = root / 'libs.tech/librelane/config.tcl'
    config.parent.mkdir(parents=True)
    config.write_text('set ::env(PDK) lifecycle_fixture\n')
    pdk = {'name': 'lifecycle_fixture', 'pdk_root_host': str(root), 'liberty': str(lib)}
    monkeypatch.setattr(ll, 'resolve_image', lambda *_: image)
    issued = R.real_entry('IC', 'default', project)
    installation_calls = []
    staged_current_inputs = False
    original = production._step9_installation
    def observed_installation(*args, **kwargs):
        assert staged_current_inputs, 'bootstrap bound future producer inputs'
        installation_calls.append(em.digest(rtl) if rtl.exists() else None)
        return original(*args, **kwargs)
    monkeypatch.setattr(production, '_step9_installation', observed_installation)
    runtime = policy.bootstrap(project, parameters={
        'top': 'top', 'pdk': pdk, 'skip_analog': True, 'container': 'unused'})
    print('STEP9_BOOTSTRAP_COMPLETE', round(time.monotonic() - started, 2), flush=True)
    assert installation_calls == [], 'bootstrap bound future producer inputs'
    others = {a.arm_id: a for key in runtime['registry']._adapters
              for a in [runtime['registry']._adapters[key]] if a.step_id != '9'}
    controller = runtime['controller']
    registry = runtime['registry']
    assert registry.adapters('9')[0].availability_reason == 'STEP9_DISPATCH_PREPARATION_PENDING'
    if prior_rtl:
        # The next real staging transaction replaces a retired prior output.
        rtl.unlink()
    staged = consume.consume_reused_ip_rtl(project)
    assert staged['reused_ip'] and 'top.v' in staged['staged'], staged
    assert rtl.read_bytes() == source.read_bytes()
    current_digest = em.digest(rtl)
    staged_current_inputs = True
    print('STEP9_STAGING_COMPLETE', current_digest, flush=True)
    captured = {}
    class AdmissionReached(Exception):
        pass
    def stop_after_admission(context, run, mode):
        captured['context'] = context
        captured['plan'] = controller.plan(context, mode, execution_root=run)
        raise AdmissionReached
    monkeypatch.setattr(controller, 'run', stop_after_admission)
    with pytest.raises(AdmissionReached):
        phase3.step_synth(project, 'top', pdk, 'unused')
    print('STEP9_ADMISSION_COMPLETE', round(time.monotonic() - started, 2), flush=True)
    assert runtime['controller'] is controller and controller.registry is registry
    assert all(registry._adapters[key] is value for key, value in others.items())
    arm = registry.adapters('9')[0]
    assert arm.available and arm.qualified, arm.availability_reason
    plan = captured['plan']
    assert any(row['arm_id'] == arm.arm_id and row['admission'] == 'READY'
               for row in plan['portfolio']), plan
    receipt = json.loads(arm.qualification_evidence)['native_installation_receipt']
    assert receipt['status'] == 'MEASURED'
    assert receipt['source_sha'] == issued['route']['source_sha']
    assert receipt['input_hashes']['project/phase2/stage1/rtl/top.v'] == current_digest
    assert installation_calls == [current_digest]
    policy._prepare_step9(runtime, {})  # AI selection polls omit producer args.
    with pytest.raises(em.Refusal, match='STEP9_DISPATCH_PARAMETERS_CHANGED'):
        policy._prepare_step9(runtime, {'top': 'changed_top'})
    assert installation_calls == [current_digest]
    with pytest.raises(em.Refusal, match='REGISTRY_FINALIZED'):
        registry.register(arm)
    with pytest.raises(em.Refusal, match='STEP9_BINDING_CLOSED'):
        registry.bind_step9(project=project, parameters={})
    empty = em.Registry()
    empty.finalize()
    with pytest.raises(em.Refusal, match='STEP9_RESERVATION_UNBOUND'):
        empty.bind_step9(project=project, parameters={})
    rtl.write_text(rtl.read_text() + '// changed after binding\n')
    with pytest.raises(em.Refusal, match='STEP9_BOOTSTRAP_INPUT_CHANGED'):
        phase3.step_synth(project, 'top', pdk, 'unused')
    assert installation_calls == [current_digest], 'input changes must not rebind'
    evidence = tmp_path / 'lifecycle-evidence.json'
    evidence.write_text(json.dumps({
        'lifecycle': 'replaced' if prior_rtl else 'absent',
        'source_sha': receipt['source_sha'], 'project': str(project),
        'staging': staged, 'receipt': receipt,
        'plan_admission': [{key: row[key] for key in (
            'arm_id', 'admission', 'available', 'qualified', 'source_sha', 'tool_version')}
            for row in plan['portfolio'] if row['arm_id'] == arm.arm_id],
        'post_binding_mutation_refused': True, 'selection_poll_reuses_binding': True,
    }, sort_keys=True, indent=2) + '\n')
    print('STEP9_EVIDENCE', str(evidence), flush=True)



def test_step9_binding_rechecks_source_and_closes_after_plan(tmp_path, monkeypatch):
    from execution_source_snapshot import SourceSnapshot, using
    worker = tmp_path / 'registration-helper.py'
    worker.write_text('value = 1\n')
    source, _ = production.source_identity()
    snapshot = SourceSnapshot(em._REPO_ROOT, source)
    with using(snapshot):
        reserved = em.Registry(snapshot=snapshot)
        production.register_synthesis_adapter(reserved, deferred=True)
        reserved.finalize()
    original = worker.read_bytes()
    register = production.register_synthesis_adapter
    def change_after_registration(*args, **kwargs):
        register(*args, **kwargs)
        # A registration-time source read belongs to the fresh snapshot. Its
        # final verification must run before the reserved slot can be bound.
        em._active_source_snapshot().read_bytes(worker)
        worker.write_bytes(original + b'value = 2\n')
    with monkeypatch.context() as patch:
        patch.setattr(production, 'register_synthesis_adapter', change_after_registration)
        try:
            with pytest.raises(em.Refusal, match='SOURCE_AUTHORITY_DIRTY'):
                reserved.bind_step9(project=tmp_path, parameters={})
        finally:
            worker.write_bytes(original)
    assert reserved._step9_reserved is not None
    # Even an unsuccessful first plan closes preparation; it cannot be rebound
    # after a caller has begun using the immutable Step9 plan identity.
    controller = em.Controller(reserved, em.Budget(1, 4096))
    context = em.Context('9', source, {}, {'metric': 'mapped_area_um2'}, production.REQUIRED_GATES)
    with pytest.raises(em.Refusal):
        controller.plan(context)
    with pytest.raises(em.Refusal, match='STEP9_BINDING_CLOSED'):
        reserved.bind_step9(project=tmp_path, parameters={})
