"""SOFTWARE exception-plan bindings; opt-in native tests only use neutral SDC.

No native platform qualification, SPM authority, STA or timing result is authored.
"""
import copy
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import design_one_shot_runner as owner
from test_flow109_d19_metric_acceptance import _case, _write, _ref
from test_flow109_selection import _public_d09_entry


@pytest.mark.parametrize('suffix, expected', [
    ('', []),
    ('set_false_path -from [all_inputs] -to [all_outputs]\n',
     ['set_false_path -from [all_inputs] -to [all_outputs]']),
    ('if {1} {set_false_path -from [all_inputs] -to [all_outputs]}\n', None),
])
def test_static_design_constraints_keep_exception_census_strict(tmp_path, suffix, expected):
    sdc = tmp_path / 'functional.sdc'
    sdc.write_text('create_clock -name core_clock -period 24 [get_ports clk]\n'
                   'set_max_fanout 4 [current_design]\n'
                   'set_max_transition 3 [current_design]\n'
                   'set_max_capacitance 0.2 [current_design]\n'
                   'set_timing_derate -early 0.95\n' + suffix)
    if expected is None:
        with pytest.raises(metrics.MetricRefusal, match='D19_EXCEPTION_CENSUS_UNSUPPORTED'):
            metrics._d19_exception_commands(sdc)
    else:
        try:
            observed = metrics._d19_exception_commands(sdc)
        except metrics.MetricRefusal as exc:
            observed = {'refusal': exc.code}
        assert observed == expected


def exception_authority(project, context, fields, *, command=None, validated_absence=True):
    scenarios = fields['scenario_constraints']['required_items']
    items = [{**row, 'command': command, 'justification': 'Declared neutral asynchronous test path'}
             for row in scenarios] if command else []
    payload = {'required_items': items}
    if not items and validated_absence:
        evidence = _ref(project, 'input/no-exceptions.json', json.dumps({
            'scope': 'SOFTWARE_NEUTRAL_OWNER_FIXTURE', 'timing_exceptions': 'none',
            'sdc_inputs': [x['sdc'] for x in fields['mode_library_rc_mapping']['reference']]}))
        payload['validated_absence'] = {'status': 'VALIDATED', 'authority': 'requirements_owner',
                                       'source_reference': evidence}
    path = project / 'input/exception-plan.json'
    reference = _ref(project, str(path.relative_to(project)), json.dumps({'exception_justification': payload}))
    _write(project / 'requirements/base_10/exception_justification.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'approval': {'status': 'APPROVED',
        'authority': 'requirements_owner', 'source_reference': reference}, **payload})


def software_loads(project, context, current, top, pdk_name):
    """Explicit SOFTWARE native artifact stand-in, never reference qualification."""
    outputs = []
    for i, entry in enumerate(current['mapping']):
        work = project / 'reports/SOFTWARE_LOAD_FIXTURE' / str(i)
        target = work / (top + '.sdc')
        sdc = _ref(project, str(target.relative_to(project)), (project / entry['sdc']['path']).read_text())
        cfg = _ref(project, str((work/'config.json').relative_to(project)), json.dumps({
            'scope': 'SOFTWARE_NOT_NATIVE', 'meta': {'step': 'Misc.LoadBaseSDC'},
            'DESIGN_NAME': top, 'FALLBACK_SDC': str((project / entry['sdc']['path']).resolve())}))
        state = _ref(project, str((work/'state_out.json').relative_to(project)), json.dumps({
            'scope': 'SOFTWARE_NOT_NATIVE', 'sdc': str(target)}))
        outputs.append({'scenario': {k:entry[k] for k in ('mode','corner','check') if k in entry},
            'source_sdc': entry['sdc'], 'sdc': sdc, 'config': cfg, 'state': state,
            'native_module': metrics.d19_native_module()})
    return outputs


def software_qualified(project, context):
    """Normal per-use admission control; NOT genuine platform qualification."""
    spec = context['resolved_row']['tool_uses'][0]
    assert spec['tool_id'] == 'python3'
    config = _ref(project, 'input/qualification/D19/config.json', json.dumps({
        'purpose':metrics.D19_PURPOSE, 'native_steps':metrics.D19_STEPS,
        'model_sources':metrics.d19_model_sources(), 'native_module':metrics.d19_native_module()}))
    binary = Path(shutil.which('python3')).resolve()
    reference = _ref(project, 'input/qualification/D19/SOFTWARE.json',
        json.dumps({'scope':'SOFTWARE_ADMISSION_CONTROL_NOT_NATIVE_QUALIFICATION'}))
    identity = {'use_id':spec['use_id'],'tool_id':'python3','version':'SOFTWARE_ONLY',
        'executable':{'path':str(binary),'sha256':metrics._sha(binary.read_bytes())},
        'build_sha256':metrics._sha(binary.read_bytes()),'config':config,
        'pdk':{'applicable':False,'reason':'SDC copy purpose is PDK independent'},
        'deck':{'applicable':False,'reason':'no physical rule deck'},'corner':'constraint-plan',
        'semantics':{'purpose':'D19.default','native_steps':metrics.D19_STEPS}}
    entry={'use_id':spec['use_id'],'status':'QUALIFIED','identity':identity,'reference_evidence':[reference]}
    path='input/qualification/D19/registry.json'
    _write(project/path,{'schema':'vibeic.flow109.qualifications.v1','uses':[entry],
        'scope':'SOFTWARE_ADMISSION_CONTROL_NOT_NATIVE_QUALIFICATION'})
    return flow109.execution_context(flow109.resolve_plan(context['features']),'D19','D19',
        runtime_tool_uses=[{**identity,'qualification_sha256':admission.canonical_sha(entry)}], qualification_registry=path)


@pytest.mark.parametrize('command', [None, 'set_false_path -from [get_ports async_in] -to [get_ports q]'])
def test_actual_exception_consumer_positive_and_unqualified_scope(tmp_path, monkeypatch, command):
    context, fields = _case(tmp_path, monkeypatch, scan=False)
    if command:
        path=tmp_path/'input/constraints/functional.sdc';path.write_text(path.read_text()+command+'\n')
        for entry in fields['mode_library_rc_mapping']['reference']:
            entry['sdc']['sha256']=metrics._sha(path.read_bytes())
        # Re-approve this SOFTWARE input epoch rather than forge producer binding.
        from test_flow109_d19_metric_acceptance import _revise
        _revise(tmp_path, fields, 'mode_library_rc_mapping',
                lambda payload:payload.update(reference=copy.deepcopy(fields['mode_library_rc_mapping']['reference'])))
    exception_authority(tmp_path,context,fields,command=command)
    current=metrics.d19_admission(tmp_path,context,publish=True)
    component={'d19_plan_admission':current, 'native_sdc_outputs':software_loads(tmp_path,context,current,'neutral','neutral')}
    result=metrics.accept_d19(tmp_path,context,component)
    assert all(r['status']=='PASS' for r in result['obligations']),result
    assert result['metric_status']=='PASS' and result['qualification']==result['status']=='NOT_MEASURED'


@pytest.mark.parametrize('damage', ['none','empty_without_absence','unexpected_exception','missing_exception',
                                  'changed_output','wrong_input','wrong_library','changed_model','missing_qualification','dynamic_tcl'])
def test_qualified_constraint_plan_and_actual_input_negative_controls(tmp_path,monkeypatch,damage):
    context,fields=_case(tmp_path,monkeypatch,scan=False)
    exception_authority(tmp_path,context,fields,validated_absence=damage!='empty_without_absence')
    qualified=software_qualified(tmp_path,context)
    current=metrics.d19_admission(tmp_path,qualified,publish=True)
    loads=software_loads(tmp_path,qualified,current,'neutral','neutral')
    component={'d19_plan_admission':current,'native_sdc_outputs':loads}
    if damage=='changed_output':
        (tmp_path/loads[0]['sdc']['path']).write_text('unapproved copied bytes\n')
    elif damage=='wrong_input':loads[0]['source_sdc']=loads[1]['state']
    elif damage=='wrong_library':(tmp_path/'input/pdk/logic.lib').write_text('changed library')
    elif damage in ('unexpected_exception','dynamic_tcl'):
        # Coherently update input, approval and native SOFTWARE output bytes;
        # only actual exception census/unsupported Tcl may refuse the row.
        path=tmp_path/'input/constraints/functional.sdc'
        path.write_text('set_false_path -from [get_ports a] -to [get_ports q]\n' if damage=='unexpected_exception'
                        else 'if {1} {set_false_path -from [get_ports a] -to [get_ports q]}\n')
        for entry in fields['mode_library_rc_mapping']['reference']:
            entry['sdc']['sha256']=metrics._sha(path.read_bytes())
        from test_flow109_d19_metric_acceptance import _revise
        _revise(tmp_path,fields,'mode_library_rc_mapping',
                lambda payload:payload.update(reference=copy.deepcopy(fields['mode_library_rc_mapping']['reference'])))
        for name,relative in (('scenario_constraints','requirements/base_10/scenario_constraints.json'),
                              ('mode_library_rc_mapping','adopted/base_10/mode_library_rc_mapping.json')):
            _write(tmp_path/relative,fields[name])
        current=metrics.d19_admission(tmp_path,qualified,publish=True)
        component={'d19_plan_admission':current,'native_sdc_outputs':software_loads(tmp_path,qualified,current,'neutral','neutral')}
    elif damage=='missing_exception':
        exception_authority(tmp_path,context,fields,command='set_false_path -from [get_ports a] -to [get_ports q]')
    elif damage=='changed_model':
        use=qualified['runtime_tool_uses'][0];cfg=tmp_path/use['config']['path']
        body=json.loads(cfg.read_text());body['model_sources']['flow109_metric_acceptance.py:_d19_exception_commands']='a'*64
        _write(cfg,body);use['config']['sha256']=metrics._sha(cfg.read_bytes())
        reg=json.loads((tmp_path/qualified['qualification_registry']).read_text())
        reg['uses'][0]['identity']['config']=dict(use['config'])
        use['qualification_sha256']=admission.canonical_sha(reg['uses'][0]);_write(tmp_path/qualified['qualification_registry'],reg)
        qualified=flow109.execution_context(flow109.resolve_plan(context['features']),'D19','D19',runtime_tool_uses=qualified['runtime_tool_uses'],qualification_registry=qualified['qualification_registry'])
        # Refresh the normal plan binding for the new context only, not the model.
        component['d19_plan_admission']=metrics.d19_admission(tmp_path,qualified,publish=True)
        assert admission.require_admission(tmp_path,qualified)['status']=='PASS'
    elif damage=='missing_qualification':
        qualified=context;component['d19_plan_admission']=metrics.d19_admission(tmp_path,qualified,publish=True)
    answer=metrics.accept_d19(tmp_path,qualified,component)
    assert answer['status']==('PASS' if damage=='none' else 'NOT_MEASURED'),answer
    if damage=='changed_model':assert answer['reason']=='D19_MODEL_QUALIFICATION_STALE',answer
    if damage=='empty_without_absence':assert answer['obligations'][-1]['reason']=='METRIC_EMPTY_SET_UNVALIDATED'
    if damage=='none':assert answer['scope'].startswith('constraint plan')


@pytest.mark.parametrize('damage', ['none', 'missing_qualification', 'missing_exception', 'missing_sdc', 'missing_load', 'changed_source'])
def test_actual_public_d19_completes_only_qualified_constraint_plan(tmp_path, monkeypatch, damage):
    missing_qualification = damage == 'missing_qualification'
    context,fields=_case(tmp_path,monkeypatch,scan=False)
    rtl=tmp_path/'phase2/stage1/rtl/neutral.v';rtl.parent.mkdir(parents=True,exist_ok=True)
    rtl.write_text('module neutral(input clk,input d,output q); assign q=d; endmodule\n')
    _write(tmp_path/'phase1/generated_docs/L8_TIMING_WAVEFORM.json',{'clocks':[{'name':'clk','period_ns':20}]})
    source=tmp_path/'input/constraints/functional.sdc'
    source.write_text('create_clock -name core -period 20 [get_ports clk]\n'
        'set_input_delay -max 2 -clock core [get_ports d]\nset_input_delay -min 0 -clock core [get_ports d]\n'
        'set_output_delay -max 2 -clock core [get_ports q]\nset_output_delay -min 0 -clock core [get_ports q]\n')
    for entry in fields['mode_library_rc_mapping']['reference']:
        entry['sdc']['sha256']=metrics._sha(source.read_bytes())
    from test_flow109_d19_metric_acceptance import _revise
    _revise(tmp_path,fields,'mode_library_rc_mapping',
        lambda payload:payload.update(reference=copy.deepcopy(fields['mode_library_rc_mapping']['reference'])))
    exception_authority(tmp_path,context,fields)
    if not missing_qualification:
        context=software_qualified(tmp_path,context)
    public=_public_d09_entry(tmp_path,monkeypatch)
    _write(tmp_path/'manifest.json',{k:context[k] for k in ('features','runtime_tool_uses','qualification_registry')})
    argv=[a for a in sys.argv if a not in ('--skip-phase1','--skip-phase3','--skip-analog')]
    for flag in ('--entry-step','--exit-step'):argv[argv.index(flag)+1]='D19'
    monkeypatch.setattr(sys,'argv',argv)
    from _ppa import timing
    def emitter(_rt,project,top,_pdk,_container):
        return _ref(project,'phase2/stage2/constraints/neutral.sdc',
                    (project/'input/constraints/functional.sdc').read_text())
    def pvt(project,*args):
        path=project/'phase2/stage2/constraints/pvt_matrix.json'
        _write(path,{'corners':[{'label':'approved_slow'},{'label':'approved_fast'}],
                     'scope':'SOFTWARE declared neutral plan; not measured timing'})
        return path,2
    monkeypatch.setattr(timing,'emit_step7_asic_sdc',emitter)
    monkeypatch.setattr(owner,'_emit_step7_pvt_matrix',pvt)
    def load(project, context, current, top, pdk_name):
        outputs = software_loads(project, context, current, top, pdk_name)
        if damage == 'missing_load':
            return []
        if damage == 'changed_source':
            (project / outputs[0]['source_sdc']['path']).write_text('# changed after native load\n')
        return outputs
    monkeypatch.setattr(owner,'_d19_load_base_sdc',load)
    if damage == 'missing_exception':
        (tmp_path / 'requirements/base_10/exception_justification.json').unlink()
    elif damage == 'missing_sdc':
        source.unlink()
    monkeypatch.setattr(owner,'_phase2_pdk_config',lambda *a,**k: type('NeutralPDK',(),{'name':'SOFTWARE_NEUTRAL'})())
    import flow_compliance_check
    import formal_property_run
    def forbidden(*args,**kwargs):
        pytest.fail('bounded D19 must not dispatch full P0/STA/formal or unrequested validation')
    monkeypatch.setattr(flow_compliance_check,'main',forbidden)
    monkeypatch.setattr(formal_property_run,'run',forbidden)
    monkeypatch.setattr(formal_property_run,'run_reachability',forbidden)
    monkeypatch.setattr(owner,'step_sdc_validation',forbidden)
    calls=[]
    def child(command,*,env=None,**kwargs):
        assert command[command.index('--entry-step')+1]==command[command.index('--exit-step')+1]=='7'
        calls.append(command)
        with monkeypatch.context() as m:
            for k,v in env.items():m.setenv(k,v)
            m.setattr(sys,'argv',command[1:])
            m.setattr(owner,'_activate_runtime_program_tree',lambda _p:None)
            m.setattr(owner,'_bootstrap_execution_policy',lambda *a,**k:None)
            m.setattr(owner,'step_reused_ip_consume',lambda *a:owner.StepResult('reused_ip','NOT_APPLICABLE',detail='SOFTWARE supplied upstream',declared_by='SOFTWARE neutral upstream fixture'))
            site=next(name for name,span in owner._spf.RUNNER_PLANS['design_one_shot_runner'].sites if '7' in span)
            m.setattr(owner._spf,'entry_admission',lambda *a:{'admitted':True,'site':site})
            rc=owner.main()
        return type('Process',(),{'returncode':rc})()
    monkeypatch.setattr(public.subprocess,'run',child)
    rc=public._main()
    diagnostic=json.loads((tmp_path/'reports/orchestrator/vibe_ic_one_shot.json').read_text())
    _write(Path('/evidence/public-diagnostic-'+damage+'.json'),diagnostic)
    assert rc==(0 if damage == 'none' else 1),diagnostic
    assert len(calls)==1
    attempt=Path(os.environ[flow109.ATTEMPT_ENV])
    result=json.loads((attempt/'result.json').read_text())
    assert result['default_row_status']==('PASS' if damage == 'none' else 'NOT_MEASURED'),result
    assert result['components'][0]['completed'] is (damage == 'none')
    assert result['whole_flow_acceptance']=='NOT_MEASURED'


@pytest.mark.skipif(os.environ.get('VIBEIC_D19_NATIVE_CONTROL') != '1',
                    reason='bounded installed Misc.LoadBaseSDC purpose control is opt-in')
@pytest.mark.parametrize('dynamic', [False, True])
def test_native_load_base_sdc_copy_and_exception_boundary(tmp_path, monkeypatch, dynamic):
    """Real SDK copy output; no platform approval, Tcl validation or STA claim."""
    context, fields = _case(tmp_path, monkeypatch, scan=False)
    source = tmp_path / 'input/constraints/functional.sdc'
    source.write_text('if {1} {set_false_path -from [get_ports d] -to [get_ports q]}\n'
                      if dynamic else 'create_clock -name core -period 20 [get_ports clk]\n')
    for entry in fields['mode_library_rc_mapping']['reference']:
        entry['sdc']['sha256'] = metrics._sha(source.read_bytes())
    from test_flow109_d19_metric_acceptance import _revise
    _revise(tmp_path, fields, 'mode_library_rc_mapping',
            lambda payload: payload.update(reference=copy.deepcopy(fields['mode_library_rc_mapping']['reference'])))
    exception_authority(tmp_path, context, fields)
    current = metrics.d19_admission(tmp_path, context, publish=True)
    assert current['mapping'], current
    loads = owner._d19_load_base_sdc(tmp_path, context, current, 'neutral', 'gf180mcuD')
    answer = metrics.accept_d19(tmp_path, context,
        {'d19_plan_admission': current, 'native_sdc_outputs': loads})
    assert answer['metric_status'] == ('NOT_MEASURED' if dynamic else 'PASS'), answer
    assert answer['status'] == answer['qualification'] == 'NOT_MEASURED', answer
    if dynamic:
        assert answer['obligations'][-1]['reason'] == 'D19_EXCEPTION_CENSUS_UNSUPPORTED', answer
    for output in loads:
        assert (tmp_path / output['sdc']['path']).read_bytes() == source.read_bytes()
    _write(tmp_path / 'NATIVE_CONTROL_RESULT.json', {
        'scope': 'Misc.LoadBaseSDC actual copy only; not SDC validation, STA or platform approval',
        'dynamic_tcl': dynamic, 'module': metrics.d19_native_module(),
        'native_sdc_outputs': loads, 'consumer': answer})


def test_actual_qualified_consumer_rejects_late_sdc_change(tmp_path, monkeypatch):
    """B's real-readback counterexample, with genuine software per-use admission."""
    context, fields = _case(tmp_path, monkeypatch, scan=False)
    exception_authority(tmp_path, context, fields)
    context = software_qualified(tmp_path, context)
    current = metrics.d19_admission(tmp_path, context, publish=True)
    component = {'d19_plan_admission': current,
        'native_sdc_outputs': software_loads(tmp_path, context, current, 'neutral', 'neutral')}
    stable = metrics.accept_d19(tmp_path, context, component)
    assert stable['status'] == stable['metric_status'] == stable['qualification'] == 'PASS', stable
    assert stable['delivery_blocked'] is False
    qualify = metrics._d19_qualification
    def qualify_then_change(*args):
        accepted = qualify(*args)
        assert accepted['status'] == 'PASS', accepted
        source = tmp_path / 'input/constraints/functional.sdc'
        source.write_text(source.read_text() + '\n# changed after real qualification\n')
        return accepted
    monkeypatch.setattr(metrics, '_d19_qualification', qualify_then_change)
    answer = metrics.accept_d19(tmp_path, context, component)
    assert answer['status'] == answer['metric_status'] == answer['qualification'] == 'NOT_MEASURED', answer
    assert answer['delivery_blocked'] is True and answer['reason'] == 'D19_INPUT_STALE', answer
    assert answer['admission']['status'] == 'PASS'  # original observation retained
    assert answer['obligations'] == stable['obligations']
    _write(tmp_path / 'RACE_RESULT.json', {'stable': stable, 'late_change': answer})


def test_observed_failure_survives_late_input_refusal(tmp_path, monkeypatch):
    """Explicit SOFTWARE reducer control; no native failure is manufactured."""
    context, fields = _case(tmp_path, monkeypatch, scan=False)
    exception_authority(tmp_path, context, fields)
    context = software_qualified(tmp_path, context)
    current = metrics.d19_admission(tmp_path, context, publish=True)
    component = {'d19_plan_admission': current,
        'native_sdc_outputs': software_loads(tmp_path, context, current, 'neutral', 'neutral')}
    evaluate = metrics.evaluate_operator
    observed = []
    def measured_failure(operator, measured, authority):
        if not observed:
            measured.update(status='FAIL', reason='SOFTWARE_INDEPENDENT_FAILURE_CONTROL')
            result = evaluate(operator, measured, authority)
            assert result[0] == 'FAIL'
            observed.append(result)
            source = tmp_path / 'input/constraints/functional.sdc'
            source.write_text(source.read_text() + '\n# late invalidation after observed failure\n')
            return result
        return evaluate(operator, measured, authority)
    monkeypatch.setattr(metrics, 'evaluate_operator', measured_failure)
    answer = metrics.accept_d19(tmp_path, context, component)
    assert answer['reason'] == 'D19_INPUT_STALE', answer
    assert answer['status'] == answer['metric_status'] == 'FAIL', answer
    assert answer['qualification'] == 'NOT_MEASURED' and answer['delivery_blocked'] is True
    first = answer['obligations'][0]
    assert first['status'] == first['measurement']['status'] == 'FAIL'
    assert first['measurement']['reason'] == 'SOFTWARE_INDEPENDENT_FAILURE_CONTROL'
    assert first['detail'] == observed[0][1]
