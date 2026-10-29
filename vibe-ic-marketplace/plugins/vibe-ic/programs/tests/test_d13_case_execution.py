"""Scoped producer/lineage SOFTWARE controls; no simulator or reset outcome fabricated.

Actual reset monitor outcomes are read separately from E's retained native controls.
"""
import json
import sys
from pathlib import Path

import pytest
import _l10_execution as records
import testbench_gen as producer
import flow109_metric_acceptance as metrics
from test_l10_execution_evidence import _project, _fake_sim
from test_flow109_d13_metric_binding import case, lint_case, put, ref, sha


@pytest.mark.parametrize('run_rc,expected',[(0,'PASS'),(1,'FAIL')])
def test_case_cli_captures_actual_writer_and_launch_without_global_writes(case,monkeypatch,run_rc,expected):
    p,_,source=case
    # Generic delivered binary fixture, never a generated/synthetic reset
    # outcome. Only simulator dispatch is isolated; emitter/writer are real.
    delivered=p/producer._DELIVERED_TB_DIRS[0]/'binary_case.v'
    put(delivered,'module binary_case; neutral dut(); initial #1 $finish; endmodule\n')
    protected=[p/source['execution'][key]['path'] for key in
        ('scenario_record','unit_junit','coverage_report','original_owner')]
    before={x:(x.read_bytes(),x.stat().st_mtime_ns) for x in protected}
    out=p/'reports/flow109/case-cli/binary'
    monkeypatch.setattr(producer,'default_dispatch',_fake_sim(run_rc=run_rc))
    monkeypatch.setattr(sys,'argv',[producer.__file__,str(p),'--top','neutral','--case','binary_case',
        '--output-dir',str(out),'--run'])
    assert producer.main()==run_rc
    owner=json.loads((out/'phase2_one_shot.json').read_bytes())
    assert owner['verdict']==expected and owner['selected_cases']==['binary_case']
    assert owner['subject']==source['subject']
    assert owner['runner_binding']['producer']['sha256']==sha(Path(producer.__file__))
    assert owner['runner_binding']['invocation_id']!=source['execution']['original_invocation']
    assert json.loads((out/'launch.json').read_bytes())['cid']
    assert (out/'host-launch.json').is_file()
    assert all((x.read_bytes(),x.stat().st_mtime_ns)==v for x,v in before.items())


def test_emitter_selects_exact_case_without_touching_original_tb(tmp_path):
    project,l10=_project(tmp_path,('vector_alpha','vector_beta'))
    put(project/'phase2/stage1/rtl/dut.v','module dut(input a,output y); assign y=a; endmodule\n')
    old=project/'phase2/stage1/sim/tb/tb_driver.v';before=(old.read_bytes(),old.stat().st_mtime_ns)
    out=project/'separate/tb';report={}
    assert producer.emit_unit_tbs(project,top='dut',out_dir=out,
        case_ids=['vector_alpha'],report=report)==1
    assert sorted(p.stem for p in out.glob('*.v'))==['vector_alpha']
    assert (old.read_bytes(),old.stat().st_mtime_ns)==before
    assert producer.emit_unit_tbs(project,top='dut',out_dir=out,
        case_ids=['unknown'],report={})==-2


@pytest.mark.parametrize('run_rc', [0, 1], ids=['pass', 'fail'])
def test_selected_execution_preserves_original_outputs(tmp_path, run_rc):
    project, l10 = _project(tmp_path, ('vector_alpha', 'vector_beta'))
    global_record = records.write_record(project, l10, [], producer='old native scope')
    old_junit = producer.sim_professional_dir(project) / producer.UNIT_TB_RESULT_DIR / 'results.xml'
    put(old_junit, 'old native JUnit bytes')
    old_isa = project / records.ISA_RECEIPT_REL;put(old_isa, 'old native ISA receipt')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (global_record, old_junit, old_isa)}
    out = project / 'reports/flow109/case-scope/only-alpha'
    for name in ('vector_alpha', 'vector_beta'):
        put(out / 'tb' / (name + '.v'), 'module '+name+'; dut u_dut(); initial #1 $finish; endmodule\n')
    commands = []
    delegate = _fake_sim(run_rc=run_rc)
    def dispatch(argv, *args):
        commands.append(argv)
        return delegate(argv, *args)
    report = {}
    assert producer.run_unit_tbs(project, report=report, dispatch=dispatch,
        case_ids=['vector_alpha'], output_dir=out) == 1
    assert all('vector_beta' not in ' '.join(argv) for argv in commands)
    actual = records.load_record(project, l10, path=out/'l10_execution.json')
    assert set(actual['rows']) == {'vector_alpha'}
    assert records.case_state('vector_alpha', actual)[0] == ('FAIL' if run_rc else 'PASS')
    assert report['tb_total'] == report['executed'] == 1
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) if p.exists() else (None, None) for p in before}
    assert after == before, 'original execution evidence changed during isolated case run'
    # Completed scoped evidence cannot be overwritten by a repeated dispatch.
    snapshot = (out/'l10_execution.json').read_bytes()
    assert producer.run_unit_tbs(project, report={}, dispatch=dispatch,
        case_ids=['vector_alpha'], output_dir=out) == -2
    assert (out/'l10_execution.json').read_bytes() == snapshot


def test_missing_selected_bench_refuses_without_clearing_original(tmp_path):
    project, l10 = _project(tmp_path)
    old = records.write_record(project,l10,[],producer='original')
    before = (old.read_bytes(),old.stat().st_mtime_ns)
    def forbidden(*a,**k):raise AssertionError('no native process permitted')
    report={}
    assert producer.run_unit_tbs(project, report=report, dispatch=forbidden,
        case_ids=['vector_alpha'],output_dir=project/'separate') == -2
    assert (old.read_bytes(),old.stat().st_mtime_ns)==before


def supplemental_fixture(c):
    """Only generic binary-case SOFTWARE owner/authority construction."""
    p,context,source=c;name='binary_case';out=p/'reports/flow109/separate-binary'
    old=p/source['execution']['scenario_record']['path']
    row=json.loads(old.read_bytes())['cases'][0]
    tb=out/'tb/binary_case.v';put(tb,Path(row['tb_file']).read_text());row['tb_file']=str(tb)
    log=out/'binary_case/run.log';put(log,Path(row['arithmetic_scenario']['transcript']).read_text())
    row['arithmetic_scenario']['transcript']=str(log)
    record=records.write_record(p,p/'phase1/generated_docs/L10_TEST_CASES.json',[row],
        producer='testbench_gen.run_unit_tbs',output=out/'l10_execution.json')
    junit=out/'results.xml';put(junit,'<testsuite tests="1" failures="0" errors="0"><testcase name="binary_case"/></testsuite>')
    runtime=p/'runtime/testbench_gen.py';put(runtime,Path(producer.__file__).read_text())
    owner=out/'phase2_one_shot.json';original=json.loads((p/source['execution']['original_owner']['path']).read_bytes())
    import benchmark_dispatch as dispatch
    consumer=p/'runtime/benchmark_dispatch.py';put(consumer,Path(dispatch.__file__).read_text())
    argv=[sys.executable,str(runtime),str(p),'--run','--case',name,'--output-dir',str(out)]
    binding=original['runner_binding'];binding.update(invocation_id='software-new-case-invocation',argv=argv,
        source=dispatch._runner_source_snapshot(argv,consumer=str(consumer)),
        report_name='phase2_one_shot.json',producer=ref(p,runtime))
    put(owner,{'runner_binding':binding,'subject':source['subject'],'selected_cases':[name],
        'verdict':'PASS','model_sources':metrics.d13_model_sources(),
        'execution':{'execution_record':str(record),'results_xml':str(junit),'tb_total':1}})
    launch=out/'launch.json';put(launch,{'scope':'SOFTWARE_ONLY','cid':'3'*64,'image_id':'sha256:'+'2'*64})
    terminal=out/'terminal.json';put(terminal,{'scope':'SOFTWARE_ONLY','host_exit_verified':True,
        'docker_cli_exit_code':0,'host_die_event_exit_code':0,'source_unchanged':True})
    execution={'project':str(p),'original_owner':ref(p,owner),'original_producer':ref(p,runtime),
        'original_invocation':'software-new-case-invocation','original_launch':ref(p,launch),
        'original_terminal':ref(p,terminal),'scenario_record':ref(p,record),'unit_junit':ref(p,junit)}
    execution['artifacts']=[ref(p,x) for x in p.rglob('*') if x.is_file()]
    authority,_,_=metrics._d13_authority(p,'required_function_scenarios')
    input_path=p/'input/flow109/D13/binary-case-execution.json'
    put(input_path,{'purpose':metrics.D13_PURPOSE,'project':str(p),'subject':source['subject'],
        'case':name,'source_authority':authority['source'],'execution':execution})
    adopted=p/'adopted/base_07/scenario_executions/binary_case.json'
    put(adopted,{'schema':'vibeic.flow109.adopted-reference.v1','approval':{
        'status':'APPROVED','authority':'requirements_owner','source_reference':ref(p,input_path)},
        'reference':execution})
    return p,source,execution,input_path,adopted


def test_separate_execution_reopens_own_normal_lineage(case):
    p,source,execution,_,_=supplemental_fixture(case)
    actual=metrics._d13_execution(p,source,case_name='binary_case')
    assert actual==execution
    assert actual['original_invocation']!=source['execution']['original_invocation']
    # A valid generic binary receipt does not authorize reset supplementation.
    rows=metrics._d13_functions(p,source,source['execution'])
    assert rows[0]['status']=='NOT_MEASURED'
    assert rows[0]['reason']=='D13_CASE_SUPPLEMENT_SCOPE_UNSUPPORTED'


@pytest.mark.parametrize('change',['missing','tampered','subject','invocation','producer','approval','case','cid',
    'record_scope','junit_scope','argv','image'])
def test_separate_execution_refuses_foreign_or_unbound_lineage(case,change):
    p,source,execution,input_path,adopted=supplemental_fixture(case)
    if change=='missing':(p/execution['scenario_record']['path']).unlink()
    elif change=='tampered':(p/execution['scenario_record']['path']).write_text('{}')
    elif change=='approval':
        doc=json.loads(adopted.read_bytes());doc['approval']['status']='NOT_MEASURED';put(adopted,doc)
    else:
        owner=p/execution['original_owner']['path'];doc=json.loads(owner.read_bytes())
        if change=='subject':doc['subject']={}
        elif change=='case':doc['selected_cases']=['other']
        elif change=='producer':doc['model_sources']['testbench_gen.py']='0'*64
        elif change=='argv':doc['runner_binding']['source']['argv']=['unissued-command']
        elif change=='record_scope':
            execution['scenario_record']=source['execution']['scenario_record']
            doc['execution']['execution_record']=str(p/execution['scenario_record']['path'])
        elif change=='junit_scope':
            execution['unit_junit']=source['execution']['unit_junit']
            doc['execution']['results_xml']=str(p/execution['unit_junit']['path'])
        elif change=='invocation':
            doc['runner_binding']['invocation_id']=source['execution']['original_invocation']
            execution['original_invocation']=source['execution']['original_invocation']
        elif change in ('cid','image'):
            launch=p/execution['original_launch']['path'];j=json.loads(launch.read_bytes())
            j['cid' if change=='cid' else 'image_id']=('1'*64 if change=='cid' else 'sha256:'+'4'*64);put(launch,j)
            execution['original_launch']=ref(p,launch)
        put(owner,doc);execution['original_owner']=ref(p,owner)
        # SOFTWARE authority construction binds the wrong content too, so these
        # controls reach the semantic lineage guard rather than only a hash gap.
        body=json.loads(input_path.read_bytes());body['execution']=execution;put(input_path,body)
        body=json.loads(adopted.read_bytes());body['reference']=execution
        body['approval']['source_reference']=ref(p,input_path);put(adopted,body)
    with pytest.raises(metrics.MetricRefusal):metrics._d13_execution(p,source,case_name='binary_case')
