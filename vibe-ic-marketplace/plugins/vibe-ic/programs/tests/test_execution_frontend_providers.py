import json
from pathlib import Path
import json
import execution_frontend_providers as p
import execution_modes as em
from programs.tests._execution_source_fixture import register_source_fixture, issued_context
from programs.tests.test_execution_receipt_chain import isolated_transport

EXPECTED=('D1','0.5ic','1','2','3','4','5','6','7','8','10','11','FS1','DT1','12','13','DT2','DT3','P0')

def test_machine_readable_coverage_and_default():
    c=p.coverage(); assert tuple(c)==EXPECTED; assert all(c[r]['default_rank']==i for i,r in enumerate(EXPECTED)); assert c['0.5ic']['applicability']=='IC+IP route authority'

def test_missing_provider_is_typed_and_no_pass():
    for row in EXPECTED:
        result=p.produce(row, Path('/nonexistent/project'))
        assert result.state in ('NOT_IMPLEMENTED','NOT_MEASURED'); assert 'PASS' not in result.state
    assert p.produce('opaque', Path('.')).state=='NOT_IMPLEMENTED'

def test_factory_reachability_reverse_and_dedup():
    registry=em.Registry(); assert p.register_factories(registry) == EXPECTED
    assert all(len(registry.adapters(row)) == 1 for row in EXPECTED)
    assert all(a.components[0].argv[0]=='python3' and '--step' in a.components[0].argv for row in EXPECTED for a in registry.adapters(row))
    assert p.choose('7') is p.choose('7'); assert p.choose('7').factory is not p.choose('8').factory
    eight=registry.adapters('8')[0]
    assert any(x.endswith('sdc_syntax_check.py') for x in eight.source_files)
    assert any(x.endswith('sdc_validator_check.py') for x in eight.source_files)

def test_real_boundary_consumes_output_and_reverse_red(tmp_path):
    source=tmp_path/'input'/'docs'; source.mkdir(parents=True); (source/'L1.md').write_text('# doc\n')
    (tmp_path/'input'/'issued_manifest.json').write_text(json.dumps({'step_id':'D1','parameters':{},'files':{'input/docs/L1.md':__import__('hashlib').sha256((source/'L1.md').read_bytes()).hexdigest()}}))
    result=p.produce('D1', tmp_path); assert result.state in ('NOT_MEASURED','NOT_IMPLEMENTED')

def test_step6_explicitly_not_measured_without_fpga():
    result=p.produce('6', Path('/missing'), fpga=False)
    assert result.state=='NOT_IMPLEMENTED'

def test_controller_executes_worker_and_validator_reddens_on_output_mutation(tmp_path):
    # Incomplete input is a real expert handoff, not an eligible D1 positive.
    from dataclasses import replace
    import subprocess
    import pytest
    project=tmp_path/'project'; src=project/'input'/'docs'; src.mkdir(parents=True)
    f=src/'L1.md'; f.write_text('# design\n')
    registry=em.Registry(); p.register_factories(registry, step_ids=('D1',))
    portfolio=em.load_portfolio(); row=next(s for s in portfolio['steps'] if s['id']=='D1')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[2],text=True).strip()
    context=issued_context(em.Context('D1',sha,{'input/docs/L1.md':f},
                           {'metric':'source_boundary'},tuple(row['mandatory_gate_programs'])),
                           project, mode='ultra')
    route=project/'input/step_0_5ic_answers.json'
    context=replace(context, inputs={**context.inputs,
                    'input/step_0_5ic_answers.json':route})
    bound_inputs={name: em.digest(path) for name, path in context.inputs.items()}
    run=tmp_path/'run'; controller=em.Controller(registry,em.Budget(1,1024,1),portfolio)
    result=controller.run(context,run)
    receipt_path=run/'frontend_D1/receipt.json'; receipt_bytes=receipt_path.read_bytes()
    receipt=json.loads(receipt_bytes); output=Path(receipt['output_root'])
    process,=receipt['processes']
    assert process['component']=='frontend_worker' and process['rc']==0
    assert process['pid']>0 and process['ended_ns']>process['started_ns']
    assert 'MemoryError' not in ''.join(Path(process[key]).read_text()
                                      for key in ('stdout', 'stderr'))
    assert receipt['binding']['objective']=={'metric':'source_boundary'}
    assert receipt['binding']['inputs']==bound_inputs
    frozen=Path(receipt['input_root'])
    from _execution_manifest import issued_manifest_path
    assert {str(path.relative_to(frozen)):em.digest(path)
            for path in frozen.rglob('*') if path.is_file() and
            path != issued_manifest_path(frozen)}==bound_inputs
    assert not (frozen/'phase1').exists() and not (frozen/'reports').exists()
    staged=output/'project'
    docs=list((staged/'phase1/generated_docs').glob('L*.json'))
    assert len(docs)==28
    expert=json.loads((staged/'reports/audit/phase1/expert_parse_track.json').read_text())
    assert expert['ai_subtrack']['status']=='HANDOFF_EMITTED'
    assert expert['ai_subtrack']['expectations']==[]
    assert result['status']=='NOT_MEASURED'
    assert result['candidate_statuses']=={'frontend_D1':'NOT_MEASURED'}
    assert receipt['reason']=='GATE_EXECUTION_UNBOUND'
    assert receipt['evidence']['verdict']=='NOT_MEASURED'
    assert receipt['evidence']['gates']=={
        name:'NOT_MEASURED' for name in row['mandatory_gate_programs']}
    assert json.loads((run/'comparison.json').read_text())['eligible_arms']==[]
    assert not (run/'selected').exists() and not (run/'adoption.json').exists()
    canonical=output/'canonical.json'; original=canonical.read_bytes()
    record=json.loads(original)
    assert record['producer_result']['name']=='phase1'
    # These existing producer primitives return rc0 for an emitted handoff.
    # Their program result cannot qualify D1 without the canonical consumers.
    assert record['producer_result']['status']=='PASS'
    assert 'HANDOFF_EMITTED' in record['producer_steps'][1]['detail']
    assert receipt['evidence']['outputs']=={'canonical.json':em.digest(canonical)}
    arm,=registry.adapters('D1')
    # The real producer recorder stamped its own writes, not a copied claim.
    import _phase1_producer_identity as identity
    stamp=json.loads((identity.sidecar_dir(staged)/'step_identity.json').read_text())['phase1']
    assert len(stamp['outputs'])==28 and stamp['carried']=={}
    # A direct helper has no live Controller-child issuance, even with these
    # genuine frozen bytes and their manifest. It must write nothing.
    import execution_frontend_worker as worker
    with pytest.raises(em.Refusal, match='ISSUED_FRONTEND_UNAVAILABLE'):
        worker.produce_d1(frozen, output)
    assert canonical.read_bytes()==original
    manifest=issued_manifest_path(frozen); original_manifest=manifest.read_bytes()
    wrong_step=json.loads(original_manifest); wrong_step['step_id']='8'
    # Serialized negative input is not Controller authority. Keep the genuine
    # read-only frozen manifest intact while exercising the public route check.
    wrong_input=tmp_path/'wrong-step-input'; wrong_input.mkdir()
    issued_manifest_path(wrong_input).write_text(json.dumps(wrong_step))
    with pytest.raises(ValueError, match='D1: issued route mismatch'):
        worker.produce_d1(wrong_input, output)
    assert canonical.read_bytes()==original
    assert manifest.read_bytes()==original_manifest
    # Forged SDC successes cannot qualify any D1 gate.
    sdc=output/'reports/phase2/sdc_check.json'; sdc.parent.mkdir(parents=True)
    sdc.write_text(json.dumps({'program':'sdc_syntax_check','passed':True}))
    (output/'reports/sdc_validator.json').write_text(json.dumps(
        {'verdict':'PASS','exit_code':0,'issues':[]}))
    record['producer_result']['status']='FAIL'
    canonical.write_text(json.dumps(record))
    assert arm.validate(output,context.binding()).verdict=='FAIL'
    record['producer_result']['status']='PASS'
    record['producer_result']['detail']='forged qualification without AI evidence'
    canonical.write_text(json.dumps(record))
    assert em.digest(canonical)!=receipt['evidence']['outputs']['canonical.json']
    changed=arm.validate(output,context.binding())
    assert changed.verdict=='NOT_MEASURED'
    assert changed.gates==receipt['evidence']['gates']
    choice={'arm_id':'frontend_D1','receipt_sha256':em.digest(receipt_path),
            'rationale':'mutation refusal control','reviewer':'test','binding':context.binding()}
    with pytest.raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        controller.adopt(context,run,choice)
    assert not (run/'selected').exists()
    assert json.loads((run/'adoption.json').read_text())['status']!='ADOPTED'
    # Missing, unknown and malformed canonical records also cannot qualify.
    for invalid in (None, [], {'schema':'unknown'},
                    {**record, 'producer_result':'StepResult(status=PASS)'}):
        if invalid is None:
            canonical.unlink()
        else:
            canonical.write_text(json.dumps(invalid))
        rejected=arm.validate(output,context.binding())
        assert rejected.verdict=='NOT_MEASURED'
        assert rejected.gates==receipt['evidence']['gates']
    canonical.write_bytes(original)
    assert arm.validate(output,context.binding()).verdict=='NOT_MEASURED'
    assert receipt_path.read_bytes()==receipt_bytes

def test_step8_public_controller_eligible_and_adopted(tmp_path):
    import hashlib, subprocess
    project=tmp_path/'project'; sdc=project/'phase2/stage2/constraints/top.sdc'; sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -period 10 [get_ports clk]\nset_input_delay 1 -clock clk [all_inputs]\nset_output_delay 1 -clock clk [all_outputs]\n')
    l8=project/'phase1/generated_docs/L8_TIMING_WAVEFORM.json'; l8.parent.mkdir(parents=True)
    l8.write_text(json.dumps({'clocks': {'clk': {'period_ns': 10}}}))
    matrix=sdc.with_name('pvt_matrix.json'); matrix.write_text('{"corners":[]}\n')
    registry=em.Registry(); p.register_factories(registry); portfolio=em.load_portfolio()
    row=next(s for s in portfolio['steps'] if str(s['id'])=='8')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[2],text=True).strip()
    ctx=issued_context(em.Context('8',sha,{'phase2/stage2/constraints/top.sdc':sdc,'phase1/generated_docs/L8_TIMING_WAVEFORM.json':l8, 'phase2/stage2/constraints/pvt_matrix.json':matrix},{'metric':'source_boundary'},tuple(row['mandatory_gate_programs'])), project)
    run=tmp_path/'run'; controller=em.Controller(registry,em.Budget(1,512,1),portfolio); controller.run(ctx,run)
    receipt=json.loads((run/'frontend_8/receipt.json').read_text())
    assert receipt['status']=='ELIGIBLE'; assert set(receipt['evidence']['gates'])==set(row['mandatory_gate_programs'])
    assert receipt['evidence']['outputs']['reports/phase2/sdc_check.json']==em.digest(run/'frontend_8/outputs/reports/phase2/sdc_check.json')
    choice={'arm_id':'frontend_8','receipt_sha256':em.digest(run/'frontend_8/receipt.json'),'rationale':'step8 fixture','reviewer':'test','binding':ctx.binding()}
    assert controller.adopt(ctx,run,choice)['status']=='ADOPTED'
    sdc.write_text(sdc.read_text()+'\n# mutation\n')
    with __import__('pytest').raises(Exception): controller.adopt(ctx,run,choice)


def test_05ic_public_controller_eligible_and_adopted(tmp_path):
    import hashlib, subprocess
    project=tmp_path/'project'; (project/'input').mkdir(parents=True)
    fixture=Path(__file__).parent/'fixtures/r0929_dieid_basis_self_tapeout_die/input/step_0_5ic_answers.json'
    answers=json.loads(fixture.read_text())
    answers['answer_provenance']['synthesis_area_budget']={
        'answered_by':'owner', 'citation':'bounded frontend fixture owner declaration'}
    answers_path=project/'input/step_0_5ic_answers.json'
    answers_path.write_text(json.dumps(answers, sort_keys=True))
    template=project/'input/submission_template_source'; template.mkdir(parents=True)
    slot=template/'s1.yaml'
    slot.write_text('DIE_AREA: [0, 0, 1000, 2000]\n'
                    'CORE_AREA: [26, 26, 974, 1974]\n'
                    'SEAL_RING_WIDTH: 26\nFP_SIZING: absolute\n'
                    'pads: [pad_n0, pad_n1, pad_s0]\n')
    registry=em.Registry(); p.register_factories(registry); portfolio=em.load_portfolio()
    row=next(s for s in portfolio['steps'] if str(s['id'])=='0.5ic')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[2],text=True).strip()
    ctx=issued_context(em.Context('0.5ic',sha,
                   {'input/step_0_5ic_answers.json':answers_path,
                    'input/submission_template_source/s1.yaml':slot},
                   {'template':'input/submission_template_source','slot':'s1'},
                   tuple(row['mandatory_gate_programs'])), project)
    run=tmp_path/'run'; controller=em.Controller(registry,em.Budget(1,512,1),portfolio)
    result=controller.run(ctx,run)
    assert result['candidate_statuses']['frontend_0_5ic']=='ELIGIBLE'
    receipt=json.loads((run/'frontend_0_5ic/receipt.json').read_text())
    assert receipt['evidence']['verdict']=='PASS'
    assert receipt['evidence']['gates']=={
        'submission_template_check':'PASS','tapeout_declaration_check':'PASS'}
    assert set(receipt['evidence']['outputs'])=={
        'input/submission_template/slots/s1.yaml',
        'reports/phase1/submission_template.json',
        'input/submission_template/tapeout_declaration.json',
        'reports/phase1/tapeout_declaration.json'}
    choice={'arm_id':'frontend_0_5ic',
            'receipt_sha256':em.digest(run/'frontend_0_5ic/receipt.json'),
            'rationale':'both declared producers and mandatory gates passed',
            'reviewer':'test', 'binding':ctx.binding()}
    assert controller.adopt(ctx,run,choice)['status']=='ADOPTED'


@__import__('pytest').mark.parametrize('deliverable,marker', [
    ('DIE', 'SELF_TAPEOUT.txt'),
    ('HARDMACRO', 'NO_TEMPLATE.txt'),
])
def test_05ic_declared_absence_routes_public_production_and_refuses_na_gate(
        tmp_path, deliverable, marker):
    """Both canonical absence routes run both producers and retain NA semantics."""
    import hashlib, subprocess
    project=tmp_path/'project'; (project/'input').mkdir(parents=True)
    fixture=Path(__file__).parent/'fixtures/r0929_dieid_basis_self_tapeout_die/input/step_0_5ic_answers.json'
    answers=json.loads(fixture.read_text())
    answers['answers']['deliverable']=deliverable
    answers['answer_provenance']['synthesis_area_budget']={
        'answered_by':'owner', 'citation':'bounded frontend absence route fixture'}
    if deliverable == 'HARDMACRO':
        answers['answer_provenance']['deliverable']={
            'answered_by':'owner', 'citation':'bounded frontend IP route fixture'}
    answers_path=project/'input/step_0_5ic_answers.json'
    answers_path.write_text(json.dumps(answers, sort_keys=True))
    registry=em.Registry(); p.register_factories(registry); portfolio=em.load_portfolio()
    row=next(s for s in portfolio['steps'] if str(s['id'])=='0.5ic')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[2],text=True).strip()
    reason=answers['operator_template']['absent_reason']
    ctx=issued_context(em.Context('0.5ic',sha,{'input/step_0_5ic_answers.json':answers_path},
                   {'template':'input/submission_template_source',
                    'no_template_reason':reason},
                   tuple(row['mandatory_gate_programs'])), project)
    run=tmp_path/'run'; controller=em.Controller(registry,em.Budget(1,512,1),portfolio)
    result=controller.run(ctx,run)
    assert result['candidate_statuses']['frontend_0_5ic']=='NOT_MEASURED'
    receipt=json.loads((run/'frontend_0_5ic/receipt.json').read_text())
    assert receipt['reason']=='GATE_NOT_MEASURED'
    assert receipt['evidence']['gates']=={
        'submission_template_check':'NOT_MEASURED',
        'tapeout_declaration_check':'PASS'}
    assert f'input/submission_template/{marker}' in receipt['evidence']['outputs']
    choice={'arm_id':'frontend_0_5ic',
            'receipt_sha256':em.digest(run/'frontend_0_5ic/receipt.json'),
            'rationale':'declared absence was executed and retained as not applicable',
            'reviewer':'test', 'binding':ctx.binding()}
    with __import__('pytest').raises(em.Refusal, match='AI_CHOICE_INELIGIBLE'):
        controller.adopt(ctx,run,choice)

@__import__('pytest').mark.parametrize('row,required', [
    ('2', ('top','clock','timeout','baseline_rtl_dir','candidate_rtl_dir')),
    ('3', ('top',)), ('4', ('top','container')), ('5', ('top','container')),
])
def test_rows_2_to_5_missing_typed_params_call_nothing(tmp_path, monkeypatch, row, required):
    import execution_frontend_worker as w
    calls=[]
    monkeypatch.setattr(w.subprocess, 'run', lambda *a, **k: calls.append(('cli',a,k)) or type('R',(),{'returncode':0,'stdout':'','stderr':''})())
    kwargs={name:'x' for name in required}
    for missing in required:
        bad=dict(kwargs); bad.pop(missing)
        calls.clear()
        with __import__('pytest').raises(ValueError): w.run_row(row,tmp_path,tmp_path/'out',**bad)
        assert calls == [], (row, missing, calls)

def test_rows_2_to_5_spy_order_and_argv(tmp_path, monkeypatch):
    import execution_frontend_worker as w
    import design_one_shot_runner as d
    import p0_tool_frontend_check as p0
    import formal_harness_gen as fh, formal_property_run as fp
    calls=[]
    monkeypatch.setattr(p0, 'check', lambda project: calls.append(('p0.check', str(project))) or {'ok':True})
    monkeypatch.setattr(w.subprocess, 'run', lambda argv, **kw: calls.append(('cli', list(argv))) or type('R',(),{'returncode':0,'stdout':'','stderr':''})())
    for name in ('step_professional_tb_gen','step_reference_tb','step_l10_unit_tb_run','step_full_stack_functional_tb'):
        monkeypatch.setattr(d, name, lambda *a, _name=name, **k: calls.append((_name, a, k)) or {'ok':True})
    monkeypatch.setattr(fh, 'generate', lambda *a, **k: calls.append(('formal_harness_gen.generate', a, k)) or {'ok':True})
    monkeypatch.setattr(fp, 'run', lambda *a, **k: calls.append(('formal_property_run.run', a, k)) or {'ok':True})
    monkeypatch.setattr(w, '_write', lambda step,out,producer,**kw: calls.append(('write',step,producer,kw)) or (Path(out).mkdir(parents=True,exist_ok=True) or Path(out)/'report.json'))
    base={'top':'chip_top','clock':'clk','timeout':7,'baseline_rtl_dir':'base','candidate_rtl_dir':'cand','container':'img'}
    (tmp_path/'input').mkdir(exist_ok=True)
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'3','parameters':base,'files':{}}))
    w.produce_2(tmp_path,tmp_path/'o2',**base)
    assert [x[0] for x in calls[:2]] == ['p0.check','cli']
    assert '--baseline-rtl-dir' in calls[1][1] and '--candidate-rtl-dir' in calls[1][1] and '--timeout' in calls[1][1]
    calls.clear(); w.produce_3(tmp_path,tmp_path/'o3',top='chip_top')
    assert [x[0] for x in calls[:4]] == ['cli','cli','cli','cli']
    assert all('--json' in x[1] for x in calls if x[0]=='cli')
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'4','parameters':base,'files':{}}))
    calls.clear(); w.produce_4(tmp_path,tmp_path/'o4',top='chip_top',container='img')
    assert [x[0] for x in calls[:4]] == ['step_professional_tb_gen','step_reference_tb','step_l10_unit_tb_run','cli']
    (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'5','parameters':base,'files':{}}))
    calls.clear(); w.produce_5(tmp_path,tmp_path/'o5',top='chip_top',container='img')
    assert [x[0] for x in calls] == ['formal_harness_gen.generate','formal_property_run.run','step_full_stack_functional_tb','write']

def test_step8_nonzero_and_manifest_mutation_refuse(tmp_path, monkeypatch):
    import hashlib
    project=tmp_path/'p'; sdc=project/'phase2/stage2/constraints/top.sdc'; sdc.parent.mkdir(parents=True)
    sdc.write_text('create_clock -period 10 [get_ports clk]\nset_input_delay 1 -clock clk [all_inputs]\n')
    l8=project/'phase1/generated_docs/L8_TIMING_WAVEFORM.json'; l8.parent.mkdir(parents=True); l8.write_text(json.dumps({'clocks':{'clk':{'period_ns':11}}}))
    matrix=sdc.with_name('pvt_matrix.json'); matrix.write_text('{"corners":[]}\n')
    files={str(x.relative_to(project)):hashlib.sha256(x.read_bytes()).hexdigest() for x in (sdc,l8,matrix)}
    (project/'input').mkdir(); (project/'input/issued_manifest.json').write_text(json.dumps({'step_id':'8','parameters':{},'files':files}))
    import execution_frontend_worker as w
    # Producer-only unit invocation envelope: real input/manifest bytes and
    # hashes, not a claim of canonical Controller authority or adoption.
    manifest=project/'input/issued_manifest.json'
    manifest_hash=hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setenv(w.ISSUED_MANIFEST_ENV,str(manifest))
    monkeypatch.setenv('VIBEIC_MANIFEST_SHA256',manifest_hash)
    monkeypatch.setenv('VIBEIC_ISSUED_MANIFEST_SHA256',manifest_hash)
    with __import__('pytest').raises(RuntimeError): w.run_row('8',project,tmp_path/'out')
    (project/'input/issued_manifest.json').write_text(json.dumps({'step_id':'9','parameters':{},'files':files}))
    with __import__('pytest').raises(ValueError): w.run_row('8',project,tmp_path/'out2')

def test_05ic_parameter_exclusivity_precedes_tools(tmp_path, monkeypatch):
    import execution_frontend_worker as w
    calls=[]
    monkeypatch.setattr(w.subprocess, 'run', lambda *a, **k: calls.append(a) or None)
    (tmp_path/'input').mkdir(); (tmp_path/'input/issued_manifest.json').write_text(json.dumps({'step_id':'0.5ic','parameters':{},'files':{}}))
    for kwargs in ({}, {'no_template_reason':'R'}):
        calls.clear()
        with __import__('pytest').raises(ValueError): w.produce_05ic(tmp_path,tmp_path/'out',**kwargs)
        assert calls == []
    with __import__('pytest').raises(ValueError):
        w.produce_05ic(tmp_path, tmp_path/'out', template='P',
                       no_template_reason='a declared absence with a searched path')
    assert calls == []

def test_05ic_real_producers_order_and_outputs(tmp_path, monkeypatch):
    # Isolate producer ordering; live issuance is exercised by the Controller
    # and CLI authority controls, rather than by this subprocess spy.
    monkeypatch.setattr(em, 'require_issued_frontend', lambda *a: None)
    import execution_frontend_worker as w
    from _atomic_artefact import write_text as atomic_write_text, observe_writes
    def write_text(path, text):
        with observe_writes():
            return atomic_write_text(path, text)
    monkeypatch.setattr(em, 'issue_frontend_chain', lambda *a: None)
    monkeypatch.setattr(w, '_producer_writes', lambda result, root: {
        str(path.relative_to(root)): em._frontend_tree(root)[str(path.relative_to(root))] for path in root.rglob('*')
        if path.is_file() and (str(path.relative_to(root)).startswith('input/submission_template/')
                               or str(path.relative_to(root)).startswith('reports/'))
        and str(path.relative_to(root)) not in getattr(result, 'prior', {})})
    import hashlib
    project=tmp_path/'project'; answers=project/'input/step_0_5ic_answers.json'; answers.parent.mkdir(parents=True)
    answers.write_text(json.dumps({'route':'IP','answers':{}}))
    (project/'input/issued_manifest.json').write_text(json.dumps({'step_id':'0.5ic','parameters':{},'files':{'input/step_0_5ic_answers.json':hashlib.sha256(answers.read_bytes()).hexdigest()}}))
    calls=[]
    class Result:
        returncode=0; stdout=''; stderr=''
    def fake(argv, **kw):
        calls.append(list(argv));
        if 'submission_template_ingest.py' in argv[1]:
            p=Path(argv[2]); (p/'input/submission_template').mkdir(parents=True,exist_ok=True); write_text(p/'input/submission_template/NO_TEMPLATE.txt', 'NO_TEMPLATE\n')
            (p/'reports/phase1').mkdir(parents=True,exist_ok=True); write_text(p/'reports/phase1/submission_template.json', json.dumps({'schema':'submission_template/1','passed':True}))
        else:
            p=Path(argv[2]); (p/'input/submission_template').mkdir(parents=True,exist_ok=True); write_text(p/'input/submission_template/tapeout_declaration.json', json.dumps({'schema':'tapeout_declaration/1'})); (p/'reports/phase1').mkdir(parents=True,exist_ok=True); write_text(p/'reports/phase1/tapeout_declaration.json', json.dumps({'schema':'tapeout_declaration/1','passed':True}))
        result = Result()
        if 'tapeout_declaration_gen.py' in argv[1]:
            result.prior = {'input/submission_template/NO_TEMPLATE.txt': '',
                            'reports/phase1/submission_template.json': ''}
        return result
    monkeypatch.setattr(w.subprocess,'run',fake)
    out=tmp_path/'out'; w.produce_05ic(project,out,template='input/submission_template_source',
                                       no_template_reason='design-neutral IP delivery does not target a shuttle slot')
    assert ['submission_template_ingest.py' in x[1] for x in calls] == [True,False]
    assert '--template' in calls[0] and '--no-template-reason' in calls[0]
    assert (out/'reports/phase1/submission_template.json').is_file() and (out/'reports/phase1/tapeout_declaration.json').is_file()
    assert not (out/'canonical.json').exists()


@__import__('pytest').mark.parametrize('fail_at', [0, 1])
def test_05ic_each_real_producer_nonzero_stops_order(tmp_path, monkeypatch, fail_at):
    # This spy exercises nonzero producer precedence after authority admission.
    monkeypatch.setattr(em, 'require_issued_frontend', lambda *a: None)
    import hashlib
    import execution_frontend_worker as w
    from _atomic_artefact import write_text as atomic_write_text, observe_writes
    def write_text(path, text):
        with observe_writes():
            return atomic_write_text(path, text)
    monkeypatch.setattr(w, '_producer_writes', lambda result, root: {
        str(path.relative_to(root)): em._frontend_tree(root)[str(path.relative_to(root))] for path in root.rglob('*')
        if path.is_file() and (str(path.relative_to(root)).startswith('input/submission_template/')
                               or str(path.relative_to(root)).startswith('reports/'))})
    project=tmp_path/'project'; template=project/'input/template'; template.mkdir(parents=True)
    (template/'s1.yaml').write_text('fixture\n')
    answers=project/'input/step_0_5ic_answers.json'; answers.write_text('{}\n')
    files={str(x.relative_to(project)):hashlib.sha256(x.read_bytes()).hexdigest()
           for x in (answers, template/'s1.yaml')}
    (project/'input/issued_manifest.json').write_text(json.dumps({
        'step_id':'0.5ic','parameters':{'template':'input/template','slot':'s1'},
        'files':files}))
    calls=[]
    class Result:
        stdout=''; stderr=''
        def __init__(self, returncode): self.returncode=returncode
    def fake(argv, **kwargs):
        index=len(calls); calls.append(list(argv))
        if index == 0:
            staged=Path(argv[2]); (staged/'input/submission_template/slots').mkdir(parents=True,exist_ok=True)
            write_text(staged/'input/submission_template/slots/s1.yaml', 'slot\n')
            (staged/'reports/phase1').mkdir(parents=True,exist_ok=True)
            write_text(staged/'reports/phase1/submission_template.json', '{}\n')
        return Result(1 if index == fail_at else 0)
    monkeypatch.setattr(w.subprocess,'run',fake)
    with __import__('pytest').raises(RuntimeError):
        w.produce_05ic(project,tmp_path/'out',template='input/template',slot='s1')
    assert len(calls)==fail_at+1


def _authority_project(tmp_path, *, top_cell=None):
    """Read a repository owner input, then supply neutral shuttle geometry."""
    import subprocess
    from programs.tests._hostpaths import repo_path
    project = tmp_path / 'project'
    answers_path = project / 'input/step_0_5ic_answers.json'
    answers_path.parent.mkdir(parents=True)
    fixture = repo_path('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                        'tests', 'fixtures', 'r0929_dieid_basis_self_tapeout_die',
                        'input', 'step_0_5ic_answers.json')
    answers = json.loads(fixture.read_text())
    answers['answer_provenance']['synthesis_area_budget'] = {
        'answered_by': 'owner', 'citation': 'neutral authority control area limit'}
    if top_cell is not None:
        answers['answers']['top_cell'] = top_cell
    answers_path.write_text(json.dumps(answers, sort_keys=True) + '\n')
    slot = project / 'input/template/s1.yaml'
    slot.parent.mkdir()
    slot.write_text('DIE_AREA: [0, 0, 1000, 2000]\n'
                    'CORE_AREA: [26, 26, 974, 1974]\n'
                    'SEAL_RING_WIDTH: 26\nFP_SIZING: absolute\n'
                    'pads: [pad_n0, pad_n1, pad_s0]\n')
    inputs = {str(path.relative_to(project)): path for path in (answers_path, slot)}
    parameters = {'template': 'input/template', 'slot': 's1', 'metric': 'source_boundary'}
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                  cwd=Path(p.__file__).parent, text=True).strip()
    row = next(row for row in em.load_portfolio()['steps'] if row['id'] == '0.5ic')
    return project, issued_context(em.Context('0.5ic', sha, inputs, parameters,
                                tuple(row['mandatory_gate_programs'])), project)


def _authority_controller():
    registry = em.Registry()
    p.register_factories(registry, step_ids=('0.5ic',))
    return em.Controller(registry, em.Budget(1, 512, 1))


def _authority_cli(project, output, env):
    import subprocess, sys
    return subprocess.run(
        [sys.executable, str(Path(p.__file__).with_name('execution_frontend_worker.py')),
         '--step', '0.5ic', '--inputs', str(project), '--outputs', str(output)],
        env=env, capture_output=True, text=True, timeout=30)


@__import__('pytest').mark.parametrize('issuer', ['missing', 'self_digest'])
def test_05ic_unauthorized_cli_stops_before_both_producers(tmp_path, issuer):
    """The two R2 failures must be real production refusals, never rc0."""
    import os
    project, ctx = _authority_project(tmp_path)
    manifest = project / 'issued_manifest.json'
    manifest.write_text(json.dumps({'step_id': '0.5ic', 'parameters': dict(ctx.objective),
                                   'files': ctx.binding()['inputs']}, sort_keys=True) + '\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if issuer == 'self_digest':
        env.update(VIBEIC_ISSUED_MANIFEST_SHA256=em.digest(manifest),
                   VIBEIC_EXECUTION_BINDING=json.dumps(ctx.binding()),
                   VIBEIC_ARM_ID='frontend_0_5ic')
    output = tmp_path / 'unauthorized-outputs'
    result = _authority_cli(project, output, env)
    assert result.returncode != 0
    assert 'ISSUED_FRONTEND_UNAVAILABLE' in result.stderr
    assert not list(output.rglob('*')), 'refusal must precede staging and both producers'


def test_05ic_completed_plan_and_environment_cannot_replay_cli(tmp_path):
    import os, shutil
    project, ctx = _authority_project(tmp_path)
    run = tmp_path / 'run'
    assert _authority_controller().run(ctx, run)['candidate_statuses']['frontend_0_5ic'] == 'ELIGIBLE'
    inputs = run / 'frontend_0_5ic/inputs'
    for name in ('plan.json', 'issued-plan.json'):
        shutil.copyfile(run / name, inputs / name)
    shutil.copyfile(run / 'frontend_0_5ic/issued-completion.json', inputs / 'issued-completion.json')
    env = dict(os.environ, VIBEIC_ISSUED_MANIFEST_SHA256=em.digest(inputs / 'issued_manifest.json'),
               VIBEIC_EXECUTION_BINDING=json.dumps(ctx.binding()), VIBEIC_ARM_ID='frontend_0_5ic')
    output = tmp_path / 'replayed-outputs'
    result = _authority_cli(inputs, output, env)
    assert result.returncode != 0, result.stderr
    assert 'ISSUED_FRONTEND_UNAVAILABLE' in result.stderr
    assert not list(output.rglob('*'))


@__import__('pytest').mark.parametrize('variant,refusal', [
    ('missing_live_issuer', 'ISSUED_AUTHORITY_UNAVAILABLE'),
    ('stale_signature', 'ISSUED_AUTHORITY_INVALID'),
    ('resigned_plan_comutation', 'ISSUED_AUTHORITY_CHANGED'),
    ('input_manifest_plan_comutation', 'ISSUED_AUTHORITY_CHANGED'),
    ('manifest_substitution', 'ISSUED_FRONTEND_MANIFEST_MISMATCH'),
    ('input_substitution', 'FROZEN_INPUT_CHANGED'),
    ('extra_input', 'FROZEN_INPUT_CHANGED'),
    ('other_arm', 'ISSUED_FRONTEND_PLAN_MISMATCH'),
    ('other_run_plan', 'ISSUED_FRONTEND_INVOCATION_MISMATCH'),
    ('other_inputs', 'ISSUED_FRONTEND_INVOCATION_MISMATCH'),
    ('other_outputs', 'ISSUED_FRONTEND_INVOCATION_MISMATCH'),
    ('parameters_substitution', 'ISSUED_FRONTEND_MANIFEST_MISMATCH'),
    ('step_substitution', 'ISSUED_FRONTEND_PLAN_MISMATCH'),
    ('executable_substitution', 'ADAPTER_SOURCE_MISMATCH'),
    ('transitive_source_substitution', 'ADAPTER_SOURCE_MISMATCH'),
])
def test_05ic_live_issuance_rejects_substitution_before_producers(
        tmp_path, monkeypatch, variant, refusal):
    """Fault injection challenges the actual child boundary and real producers."""
    from dataclasses import replace
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller()
    if variant == 'other_run_plan':
        controller.run(ctx, tmp_path / 'prior-run')
    original = em._issued_frontend_child

    def inject(plan_path, arm, component, argv, cwd, out_fd, err_fd, env, cpuset, issuer_pid):
        argv = list(argv)
        inputs = plan_path.parent / arm.arm_id / 'inputs'
        manifest = inputs / 'issued_manifest.json'
        plan = json.loads((plan_path.parent / 'plan.json').read_text())
        if variant == 'missing_live_issuer':
            em._ISSUED_AUTHORITY.pop(str(plan_path))
        elif variant == 'stale_signature':
            doc = json.loads(plan_path.read_text())
            doc['signature'] = '0' * 64
            plan_path.write_text(json.dumps(doc))
        elif variant in ('resigned_plan_comutation', 'input_manifest_plan_comutation'):
            plan['run_id'] = 'caller-reissued-run'
            if variant == 'input_manifest_plan_comutation':
                answers = inputs / 'input/step_0_5ic_answers.json'
                doc = json.loads(answers.read_text())
                doc['answers']['deliverable'] = 'HARDMACRO'
                answers.chmod(0o644)
                answers.write_text(json.dumps(doc))
                plan['binding']['inputs'][str(answers.relative_to(inputs))] = em.digest(answers)
                plan['issued_manifest_payload']['files'] = dict(plan['binding']['inputs'])
                manifest.chmod(0o644)
                manifest.write_bytes(em._issued_manifest_bytes(plan['issued_manifest_payload']))
                plan['issued_manifest_sha256'] = em.digest(manifest)
                env['VIBEIC_ISSUED_MANIFEST_SHA256'] = em.digest(manifest)
            (plan_path.parent / 'plan.json').write_text(json.dumps(plan))
            # Even this interpreter's real signer cannot replace its immutable issuance.
            plan_path.write_text(json.dumps(em._seal(plan)))
        elif variant in ('manifest_substitution', 'parameters_substitution', 'step_substitution'):
            doc = json.loads(manifest.read_text())
            if variant == 'step_substitution':
                doc['step_id'] = '8'
                argv[3] = '8'
            else:
                doc['parameters']['slot'] = 'caller-slot'
            manifest.chmod(0o644)
            manifest.write_text(json.dumps(doc, sort_keys=True) + '\n')
            if variant != 'manifest_substitution':
                env['VIBEIC_ISSUED_MANIFEST_SHA256'] = em.digest(manifest)
        elif variant == 'input_substitution':
            answers = inputs / 'input/step_0_5ic_answers.json'
            answers.chmod(0o644)
            answers.write_text(answers.read_text() + '\n')
        elif variant == 'extra_input':
            (inputs / 'unissued.txt').write_text('unissued bytes\n')
        elif variant == 'other_arm':
            arm = replace(arm, arm_id='frontend_other')
        elif variant == 'other_run_plan':
            plan_path = tmp_path / 'prior-run/issued-plan.json'
        elif variant == 'other_inputs':
            import shutil
            other = inputs.parent / 'other-inputs'
            shutil.copytree(inputs, other)
            argv[5] = str(other)
        elif variant == 'other_outputs':
            argv[7] = str(inputs.parent / 'other-outputs')
        elif variant in ('executable_substitution', 'transitive_source_substitution'):
            original_digest = em.digest
            target = (argv[0] if variant == 'executable_substitution' else
                      str(Path(p.__file__).with_name('_tapeout_declaration.py')))
            em.digest = lambda path: 'f' * 64 if str(path) == target else original_digest(path)
        original(plan_path, arm, component, argv, cwd, out_fd, err_fd, env, cpuset, issuer_pid)

    monkeypatch.setattr(em, '_issued_frontend_child', inject)
    run = tmp_path / 'run'
    result = controller.run(ctx, run)
    receipt = json.loads((run / 'frontend_0_5ic/receipt.json').read_text())
    assert result['candidate_statuses']['frontend_0_5ic'] == 'NOT_MEASURED'
    assert receipt['reason'] == 'PROCESS_ERROR', receipt
    assert receipt['processes'][0]['rc'] != 0
    assert refusal in (run / 'frontend_0_5ic/frontend_worker.stderr').read_text()
    assert not list((run / 'frontend_0_5ic/outputs').rglob('*'))
    assert not (run / 'frontend_0_5ic/other-outputs').exists()


@__import__('pytest').mark.parametrize('mutation', ['manifest', 'input'])
def test_05ic_authority_rechecked_between_real_producers(tmp_path, monkeypatch, mutation):
    import subprocess
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller()
    original = em._issued_frontend_child

    def inject(plan_path, arm, component, argv, cwd, out_fd, err_fd, env, cpuset, issuer_pid):
        real_run = subprocess.run
        def run_and_mutate(command, **kwargs):
            result = real_run(command, **kwargs)
            if command[1].endswith('submission_template_ingest.py'):
                target = plan_path.parent / arm.arm_id / 'inputs'
                target /= ('issued_manifest.json' if mutation == 'manifest' else
                           'input/step_0_5ic_answers.json')
                target.chmod(0o644)
                target.write_text(target.read_text() + '\n')
            return result
        subprocess.run = run_and_mutate
        original(plan_path, arm, component, argv, cwd, out_fd, err_fd, env, cpuset, issuer_pid)

    monkeypatch.setattr(em, '_issued_frontend_child', inject)
    run = tmp_path / 'run'
    result = controller.run(ctx, run)
    assert result['candidate_statuses']['frontend_0_5ic'] == 'NOT_MEASURED'
    outputs = run / 'frontend_0_5ic/outputs'
    assert (outputs / 'project/reports/phase1/submission_template.json').is_file()
    assert not (outputs / 'project/reports/phase1/tapeout_declaration.json').exists()
    assert not (outputs / 'reports/phase1/tapeout_declaration.json').exists()


def test_05ic_ultra_live_path_adopts_only_with_both_typed_gates(tmp_path):
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller()
    run = tmp_path / 'ultra-run'
    assert controller.run(ctx, run, 'ultra-mode')['candidate_statuses'] == {
        'frontend_0_5ic': 'ELIGIBLE'}
    receipt_path = run / 'frontend_0_5ic/receipt.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['evidence']['gates'] == {
        'submission_template_check': 'PASS', 'tapeout_declaration_check': 'PASS'}
    assert controller.adopt(ctx, run, {
        'arm_id': 'frontend_0_5ic', 'receipt_sha256': em.digest(receipt_path),
        'binding': ctx.binding(), 'reviewer': 'test',
        'rationale': 'both real producer outputs and mandatory typed gates passed',
    })['status'] == 'ADOPTED'


def _snapshot_adoption(controller, ctx, run):
    path = run / 'frontend_0_5ic/receipt.json'
    try:
        return controller.adopt(ctx, run, {
            'arm_id': 'frontend_0_5ic', 'receipt_sha256': em.digest(path),
            'binding': ctx.binding(), 'reviewer': 'snapshot integrity control',
            'rationale': 'reconsume real producer snapshots and both mandatory gates',
        })['status']
    except em.Refusal:
        return 'REFUSED'


@__import__('pytest').mark.parametrize('mutation', [
    'owner_answer', 'template_slot', 'intermediate', 'replacement', 'symlink',
    'directory_swap', 'restore_replay', 'intermediate_replay', 'slot_add_restore',
])
def test_05ic_staged_writer_refuses_before_adoption(tmp_path, mutation):
    """An external same-user writer; real producers and Controller, no patches."""
    import os, threading
    # Owner input must be complete before the genuine route capability binds it.
    project, ctx = _authority_project(tmp_path, top_cell='issued_owner_top')
    binding = ctx.binding()
    controller = _authority_controller()
    run = tmp_path / 'run'
    staged = run / 'frontend_0_5ic/outputs/project'
    signal = staged / 'reports/phase1/submission_template.json'
    events = []; errors = []
    completed = threading.Event()

    def writer():
        try:
            # Wait for the real producer report, including source admission.
            # A terminal Controller result also wakes the observer on refusal.
            while not signal.is_file() and not completed.wait(.0005):
                pass
            if not signal.is_file():
                raise RuntimeError('producer 1 never published its real report')
            target = staged / 'input/step_0_5ic_answers.json'
            if mutation == 'template_slot':
                target = staged / 'input/template/s1.yaml'
            elif mutation in ('intermediate', 'intermediate_replay'):
                target = signal
            raw = target.read_bytes(); metadata = target.stat()
            if mutation == 'template_slot':
                changed = raw + b'\n# unissued slot bytes\n'
            else:
                changed_doc = json.loads(raw)
                if mutation in ('intermediate', 'intermediate_replay'):
                    changed_doc['unissued_intermediate'] = 'caller_bytes'
                else:
                    changed_doc['answers']['top_cell'] = 'caller_unissued_top'
                changed = (json.dumps(changed_doc, sort_keys=True) + '\n').encode()
            if mutation == 'directory_swap':
                import shutil
                directory = staged / 'input/template'
                replacement = tmp_path / 'replacement-template'
                shutil.copytree(directory, replacement)
                directory.rename(tmp_path / 'prior-template')
                replacement.rename(directory)
            elif mutation in ('replacement', 'intermediate_replay'):
                replacement = tmp_path / 'replacement-input'
                replacement.write_bytes(raw)
                os.replace(replacement, target)
            elif mutation == 'symlink':
                replacement = tmp_path / 'unissued-input'
                replacement.write_bytes(changed)
                target.unlink(); target.symlink_to(replacement)
            elif mutation == 'slot_add_restore':
                extra = staged / 'input/template/unissued-slot.yaml'
                extra.write_text('unissued transient slot\n'); extra.unlink()
            else:
                target.chmod(0o644); target.write_bytes(changed)
                if mutation == 'restore_replay':
                    target.write_bytes(raw)
                    os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            events.append({'mutation': mutation, 'before': em._hash(raw.hex()),
                           'after': em.digest(target), 'external_writer': True})
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        controller.run(ctx, run)
    finally:
        completed.set()
        thread.join(25)
    assert not thread.is_alive() and not errors, errors
    assert events and ctx.binding() == binding
    assert em.digest(run / 'frontend_0_5ic/inputs/input/step_0_5ic_answers.json') == binding['inputs']['input/step_0_5ic_answers.json']
    observed = _snapshot_adoption(controller, ctx, run)
    assert observed == 'REFUSED', {'adoption': observed, 'writer': events, 'mutation': mutation}


def test_05ic_positive_issued_snapshot_chain(tmp_path):
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller(); run = tmp_path / 'run'
    assert controller.run(ctx, run)['candidate_statuses']['frontend_0_5ic'] == 'ELIGIBLE'
    assert _snapshot_adoption(controller, ctx, run) == 'ADOPTED'
    receipt = json.loads((run / 'frontend_0_5ic/receipt.json').read_text())
    assert receipt['evidence']['gates'] == {
        'submission_template_check': 'PASS', 'tapeout_declaration_check': 'PASS'}
    chain = receipt['producer_chain']; first, second = chain['stages']
    assert first['inputs'] == ctx.binding()['inputs']
    assert second['inputs'] == {**first['inputs'], **first['outputs']}
    assert second['predecessor_sha256'] == em._hash(first)
    assert first['root'] != second['root']
    assert chain == receipt['evidence']['provenance']['producer_chain']
    assert chain['outputs'] == receipt['evidence']['outputs']


@__import__('pytest').mark.parametrize('mutation', [
    'first_intermediate', 'second_input', 'chain_comutation', 'chain_replay',
    'path_symlink', 'restore_after_completion',
])
def test_05ic_snapshot_chain_reconsumed_at_adoption(tmp_path, mutation):
    import os
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller(); run = tmp_path / 'run'
    assert controller.run(ctx, run)['candidate_statuses']['frontend_0_5ic'] == 'ELIGIBLE'
    output = run / 'frontend_0_5ic/outputs'
    receipt_path = output.parent / 'receipt.json'
    chain_path = output / 'issued-producer-chain.json'
    if mutation == 'chain_replay':
        prior = tmp_path / 'prior-run'
        assert controller.run(ctx, prior)['candidate_statuses']['frontend_0_5ic'] == 'ELIGIBLE'
        chain_path.write_bytes((prior / 'frontend_0_5ic/outputs/issued-producer-chain.json').read_bytes())
    elif mutation == 'chain_comutation':
        signed = json.loads(chain_path.read_text())
        signed['payload']['stages'][0]['argv'].append('--caller-change')
        chain_path.write_text(json.dumps(signed))
        receipt = json.loads(receipt_path.read_text())
        receipt['producer_chain'] = signed['payload']
        receipt['evidence']['provenance']['producer_chain'] = signed['payload']
        receipt_path.write_text(json.dumps(receipt))
    else:
        root = output / ('project' if mutation == 'first_intermediate' else 'producer2_project')
        target = root / ('reports/phase1/submission_template.json' if mutation == 'first_intermediate'
                         else 'input/step_0_5ic_answers.json')
        raw = target.read_bytes(); metadata = target.stat()
        if mutation == 'path_symlink':
            replacement = tmp_path / 'same-bytes'; replacement.write_bytes(raw)
            target.unlink(); target.symlink_to(replacement)
        else:
            target.write_bytes(raw + b'\n')
            if mutation == 'restore_after_completion':
                target.write_bytes(raw)
                os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    observed = _snapshot_adoption(controller, ctx, run)
    assert observed == 'REFUSED', {'adoption': observed, 'mutation': mutation}


def test_05ic_observation_preserves_atomic_writer_default_encoding(tmp_path):
    from _atomic_artefact import observe_writes, write_text
    ordinary = tmp_path / 'ordinary.txt'
    write_text(ordinary, 'neutral owner text', encoding=None)
    assert ordinary.read_text() == 'neutral owner text'
    observed = tmp_path / 'observed.txt'
    with observe_writes() as records:
        write_text(observed, 'neutral owner text', encoding=None)
    row = records[str(observed.absolute())]
    assert row['sha256'] == em.digest(observed)
    assert row['version'][1] == observed.stat().st_ino


def test_05ic_measured_gate_fail_precedes_changed_chain(tmp_path):
    from dataclasses import asdict
    project, ctx = _authority_project(tmp_path)
    controller = _authority_controller(); run = tmp_path / 'run'
    assert controller.run(ctx, run)['candidate_statuses']['frontend_0_5ic'] == 'ELIGIBLE'
    completion_path = run / 'frontend_0_5ic/issued-completion.json'
    completion_bytes = completion_path.read_bytes()
    output = run / 'frontend_0_5ic/outputs'
    report = output / 'reports/phase1/submission_template.json'
    document = json.loads(report.read_text())
    document['ingest']['slots'] = []
    report.write_text(json.dumps(document))
    adapter = controller.registry.adapters('0.5ic')[0]
    evidence = adapter.validate(output, ctx.binding())
    assert evidence.verdict == 'FAIL'
    assert evidence.gates['submission_template_check'] == 'FAIL'
    receipt_path = output.parent / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['evidence'] = asdict(evidence)
    receipt_path.write_text(json.dumps(receipt))
    assert _snapshot_adoption(controller, ctx, run) == 'REFUSED'
    # The fresh validator still reports measured FAIL above. It does not
    # authorize a caller to rewrite evidence in an already sealed completion.
    # That integrity boundary refuses before considering the edited receipt.
    adoption = json.loads((run / 'adoption.json').read_text())
    assert adoption['reason'] == 'EVIDENCE_CHANGED'
    assert adoption['status'] == 'REFUSED'
    assert adoption.get('selected') is None
    assert not adoption.get('selected_generation')
    assert completion_path.read_bytes() == completion_bytes
