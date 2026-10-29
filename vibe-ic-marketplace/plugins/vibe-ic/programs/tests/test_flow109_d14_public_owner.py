"""Actual public/child entry controls with explicit SOFTWARE retained proof data.

No simulator/solver/cover engine is executed and no platform qualification is
adopted. The real admission, consumers, report writer and row finisher run.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import flow109
import formal_property_run as producer
import design_one_shot_runner as owner
import librelane_contract as contract
from test_flow109_d14_metric_binding import case as base_case, put
from test_formal_required_reachability import reach_case, software_covers, software_qualified_binding
from test_flow109_selection import _public_d09_entry, _write_dft_intent


@pytest.mark.parametrize('damage', ['current', 'missing_report', 'forged_report', 'stale_report',
                                  'source', 'required_partition', 'missing_requirement', 'cover', 'missing_cover', 'owner_hash'])
def test_actual_public_d14_reopens_retained_qualified_evidence_without_native_replay(reach_case, monkeypatch, damage):
    project, context = reach_case
    _write_dft_intent(project, monkeypatch, scan=False)
    put(project / 'phase1/generated_docs/L10_TEST_CASES.json',
        {'scope':'SOFTWARE_NEUTRAL_UPSTREAM_INPUT', 'test_cases': []})
    put(project / 'phase1/generated_docs/L12_BEHAVIORAL_SEQUENCES.json',
        {'scope':'SOFTWARE_NEUTRAL_UPSTREAM_INPUT', 'behavioral_sequences': []})
    software_covers(project)
    context = software_qualified_binding(project, context)
    assert __import__('flow109_metric_acceptance').accept_d14(project, context)['status'] == 'PASS'
    formal = project / 'phase2/stage1/formal'
    if damage == 'source':
        path = project / 'phase2/stage1/rtl/neutral.v';path.write_text(path.read_text()+'\n// stale actual model\n')
    elif damage == 'required_partition':
        path = project / 'requirements/base_08/proof_partition_coverage.json'
        data = json.loads(path.read_text());data['required_items'] = [{'task': 'forged_required_task'}];put(path,data)
    elif damage == 'cover':
        path = formal / 'reachability/results.json';data=json.loads(path.read_text());data['tasks'][0]['property']='wrong_target';put(path,data)
    elif damage == 'missing_requirement':
        (project / 'requirements/base_08/proof_partition_coverage.json').unlink()
    elif damage == 'missing_cover':
        (formal / 'reachability/results.json').unlink()
    elif damage == 'owner_hash':
        path = formal / 'results.json';data=json.loads(path.read_text());data['program_owner_sha256']['formal_property_run.py']='a'*64;put(path,data)
    # Guard the entire supplied proof/cover epoch against writes during entry.
    original = {p: p.read_bytes() for p in formal.rglob('*') if p.is_file()}
    sim = project / 'phase2/stage1/sim_full_stack/results.json'
    put(sim, {'scope':'SOFTWARE_UPSTREAM_PRESERVED'});sim_before=sim.read_bytes(),sim.stat().st_mtime_ns
    public = _public_d09_entry(project, monkeypatch)
    put(project / 'manifest.json', {k:context[k] for k in ('features','runtime_tool_uses','qualification_registry')})
    argv = [a for a in sys.argv if a not in ('--skip-phase1','--skip-phase3','--skip-analog')]
    for flag in ('--entry-step','--exit-step'):argv[argv.index(flag)+1]='D14'
    monkeypatch.setattr(sys,'argv',argv)
    assert not set(argv).intersection({'--skip-phase1','--skip-phase3','--skip-analog'})
    monkeypatch.setattr(contract,'local_image_attestation',lambda: {'scope':'SOFTWARE_SOURCE_CONTROL_NOT_NATIVE'})
    calls=[]
    def forbidden(*args,**kwargs):
        pytest.fail('bounded D14 owner must never dispatch simulation/proof/cover/emitter')
    for name in ('step_full_stack_tb_gen','step_reference_tb','step_d13_simulation','step_asic_sdc'):
        monkeypatch.setattr(owner,name,forbidden)
    monkeypatch.setattr(producer,'run',forbidden)
    monkeypatch.setattr(producer,'run_reachability',forbidden)
    def child(command,*,env=None,**kwargs):
        assert command[command.index('--entry-step')+1]=='4'
        assert command[command.index('--exit-step')+1]=='5'
        calls.append(command)
        with monkeypatch.context() as m:
            for key,value in env.items():m.setenv(key,value)
            m.setattr(sys,'argv',command[1:])
            m.setattr(owner,'_activate_runtime_program_tree',lambda _p:None)
            m.setattr(owner,'_bootstrap_execution_policy',lambda *a,**k:None)
            m.setattr(owner,'step_reused_ip_consume',lambda *a:None)
            site=next(name for name,span in owner._spf.RUNNER_PLANS['design_one_shot_runner'].sites if '4' in span)
            m.setattr(owner._spf,'entry_admission',lambda *a:{'admitted':True,'site':site})
            rc=owner.main()
        report=Path(env[flow109.ATTEMPT_ENV])/'phase2_one_shot.json'
        if damage=='missing_report':report.unlink()
        elif damage in ('forged_report','stale_report'):
            data=json.loads(report.read_text())
            if damage=='forged_report':data['runner_binding']['invocation_id']='forged-invocation'
            else:data['runner_binding']['producer']['sha256']='a'*64
            put(report,data)
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(public.subprocess,'run',child)
    assert public._main()==(0 if damage=='current' else 1)
    assert len(calls)==1
    attempt=Path(os.environ[flow109.ATTEMPT_ENV])
    finished=json.loads((attempt/'result.json').read_bytes())
    summary=json.loads((project/'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    expected='PASS' if damage=='current' else 'NOT_MEASURED'
    assert finished['default_row_status']==expected,finished
    assert finished['components'][0]['completed'] is (damage=='current')
    assert summary['dispatched_verdict']==expected,summary
    assert finished['whole_flow_acceptance']==finished['flow109_acceptance']=='NOT_MEASURED'
    assert finished['delivery_accepted'] is False
    assert all(p.read_bytes()==raw for p,raw in original.items())
    assert (sim.read_bytes(),sim.stat().st_mtime_ns)==sim_before
    if damage=='current':
        report=json.loads((attempt/'phase2_one_shot.json').read_bytes())
        assert report['declared_window']['dispatched_step_ids']==['5']
        assert report['steps'][0]['name']=='formal_verification'
        assert report['steps'][0]['extras']['completed'] is False
        assert report['steps'][0]['extras']['metric_acceptance']['qualification']=='PASS'
