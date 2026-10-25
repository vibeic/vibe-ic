"""Permanent R5 public-dispatch controls. No product/EDA runner is executed.

Runtime-pair facts and typed D1 outputs are explicit SOFTWARE_FIXTURE_ONLY
preconditions. The actual candidate dispatcher, anchors, receipt history,
invocation journal and admission code execute unmodified.
"""
import copy, hashlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import benchmark_dispatch as bd
import route_decision as rd
import task_nature_route as tnr
import test_ai_first_route_handoff as fixture
import _runtime_pair_fixture as runtime
import emit_attestation as ea
import _path_layout as pl
PRODUCTION_RUN = bd._RunnerBudget.run

@pytest.fixture(autouse=True)
def runtime_precondition(monkeypatch):
    runtime.assume_matching_runtime_pair(monkeypatch)

def record(name, value):
    # Captured by pytest/JUnit, never written into the repository.
    print(json.dumps({"control": name, **value}, sort_keys=True))

def _issue(tmp_path, monkeypatch, prompt="Design a pulse stretcher named top_module with two clock cycles of output.", typed=True):
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    dataset.mkdir()
    (dataset / "opaque_alpha_prompt.txt").write_text(prompt)
    calls = []
    monkeypatch.setattr(bd.subprocess, "run", fixture._typed_d1_runner(calls))
    assert bd.cmd_solve("verilogeval-human", str(dataset), str(run)) == 2
    assert calls == []
    task = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    answer = fixture._answer(task, "spec_generation")
    answer["prompt_evidence"] = [{"excerpt": prompt, "supports": "The visible INPUT describes spec_generation."}]
    return dataset, run, task, answer, calls

def _resume(dataset, run):
    return bd.cmd_resume("verilogeval-human", str(dataset), str(run))

def _stop_boundary(calls):
    def stop(_budget, argv):
        calls.append(list(argv))
        return bd._ProcessOutcome(rc=1, stdout="", stderr="", error="CONTROLLED_PROCESS_BOUNDARY_STOP")
    return stop

def _ready_backup(tmp_path, monkeypatch, prompt=None):
    kwargs = {"prompt": prompt} if prompt is not None else {}
    dataset, run, task, answer, calls = _issue(tmp_path, monkeypatch, **kwargs)
    fixture._write_answer(task, answer)
    _resume(dataset, run)
    backup = bd._read_jsonl(run / bd._BACKUP_WORKLIST)
    assert len(backup) == 1
    item = backup[0]
    project = Path(task["project"])
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top_module.v").write_text("module top_module(input a, output y); assign y=a; endmodule\n")
    body = {
        "schema": "vibeic.benchmark.ai_backup_record.v1", "id": item["id"],
        "task_sha256": item["task_sha256"], "prompt_sha256": item["prompt_sha256"],
        "source_sha256": item["public_original_input"]["source_sha256"],
        "output_manifest": bd._backup_output_manifest(project),
        "rtl_sha256": bd._sha256_text(bd._candidate_text(bd._rtl_files(project))),
        "author": {"kind": "AI", "model": "software-boundary-control"},
        "oracle_accessed": False, "disposition": "CHANGED",
        "rationale": "The output is derived only from the visible staged input.",
    }
    (project / "phase2/stage1/ai_backup_author.json").write_text(json.dumps(body))
    completion, reasons = bd._validate_backup_completion(item, run)
    assert completion is not None, reasons
    calls.clear()
    monkeypatch.setattr(bd._RunnerBudget, "run", _stop_boundary(calls))
    return dataset, run, task, calls

frozen = SimpleNamespace(issue=_issue, resume=_resume)
prior = SimpleNamespace(ready_backup=_ready_backup)


@pytest.mark.parametrize("mutate_route", [False, True])
def test_rtl_window_retains_the_issued_die_family_on_backup_reentry(
        tmp_path, monkeypatch, mutate_route):
    # A bounded RTL proof does not change the input's declared IC delivery
    # family. Exercise issuance, D1, backup completion and ordinary resume.
    prompt = ("Design a complete IC with module top_module, input a and "
              "output y wired directly to a. Supply the RTL implementation.")
    dataset, run, task, calls = prior.ready_backup(
        tmp_path, monkeypatch, prompt=prompt)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    row = solve["results"][0]
    assert task["prompt_delivery_requirements"]["route_family"] == "DIE"
    assert row["route_receipt"]["delivery_target"] == "rtl"
    assert row["delivery_route"] == "ic"
    if mutate_route:
        row["delivery_route"] = "ip"
        solve_path.write_text(json.dumps(solve))

    rc = frozen.resume(dataset, run)
    assert rc == 2
    if mutate_route:
        assert calls == []
        current = json.loads(solve_path.read_text())["results"][0]
        assert "ROUTE_REENTRY_ROUTE_MUTATION" in str(current)
    else:
        assert len(calls) == 1
        assert calls[0][calls[0].index("--route") + 1] == "ic"
        assert calls[0][calls[0].index("--exit-step") + 1] == "2"

IC_PROMPTS=[
    'Design a complete chip containing an IP hardmacro and deliver a shippable GDS.',
    'Build a complete IC that incorporates a hardmacro and deliver a GDS.',
    'Deliver a complete chip as GDS.\nComponents: an IP hardmacro and a digital controller.',
    'Integrate an IP hardmacro\ninto a complete chip and deliver a shippable GDS.',
    'Design a complete chip and deliver a shippable GDS. Integrate the vendor-supplied analog subsystem with its calibration controller, reset bridge, synchronization chain and IP hardmacro.',
    'Create a complete chip: (the subsystem contains (an IP hardmacro)). Deliver a shippable GDS.',
]

@pytest.mark.parametrize('prompt', IC_PROMPTS)
def test_complete_chip_words_do_not_authorize_ip_runner(tmp_path,monkeypatch,prompt):
    dataset,run,task,answer,calls=frozen.issue(tmp_path,monkeypatch,prompt,typed=True)
    answer['semantic_decision']={'nature':'spec_generation','delivery_target':'ip_hardmacro',
        'semantic_payload_sha256':task['semantic_payload_sha256']}
    fixture._write_answer(task,answer)
    decision,reasons=bd._validate_ai_route(task,run,benchmark='verilogeval-human',dataset=dataset)
    rc=frozen.resume(dataset,run)
    record('ic-'+task['prompt_sha256'][:12],{'prompt':prompt,'requirements':task['prompt_delivery_requirements'],
        'decision':decision,'reasons':reasons,'rc':rc,'runner_calls':calls})
    assert calls==[], f'complete-chip INPUT authorized IP argv: {calls}'

@pytest.mark.parametrize('prompt',[
    'Deliver a standalone IP hardmacro for use inside a customer chip; include GDS, LEF, Liberty and Verilog views.',
    'Deliver a standalone IP hardmacro to be integrated into a host IC; produce a GDS with LEF and Liberty views.',
    'Deliver a standalone IP hardmacro with GDS, LEF and Liberty views. Its embedded controller handles calibration.',
])
def test_standalone_ip_context_does_not_flip_to_die(prompt):
    req=tnr.prompt_delivery_requirements(prompt)
    resolution=tnr.resolve_prompt_delivery_target(req,'ip_hardmacro')
    record('standalone-'+hashlib.sha256(prompt.encode()).hexdigest()[:12],{'prompt':prompt,'requirements':req,'resolution':resolution})
    assert req['route_family']=='HARDMACRO' and resolution['ok'] is True

@pytest.mark.parametrize('prompt',[
    'Deliver a complete chip and a separate standalone IP hardmacro; produce a GDS and the LEF and Liberty views.',
    'The output is either a complete chip or a standalone IP hardmacro; the owner has not chosen. Deliver a GDS.',
])
def test_ambiguous_physical_object_does_not_authorize_runner(tmp_path,monkeypatch,prompt):
    dataset,run,task,answer,calls=frozen.issue(tmp_path,monkeypatch,prompt,typed=True)
    answer['semantic_decision']={'nature':'spec_generation','delivery_target':'ip_hardmacro',
        'semantic_payload_sha256':task['semantic_payload_sha256']}
    fixture._write_answer(task,answer)
    rc=frozen.resume(dataset,run)
    record('ambiguous-'+task['prompt_sha256'][:12],{'prompt':prompt,'requirements':task['prompt_delivery_requirements'],'rc':rc,'runner_calls':calls})
    assert calls==[]

def state(run,project):
    solve=json.loads((run/'solve_report.json').read_text())
    tasks=bd._read_jsonl(run/bd._ROUTE_WORKLIST)
    return bd._validated_route_reentry_state(bench='verilogeval-human',dataset=None,fmt=None,
        run_p=run,pid=tasks[0]['id'],result=solve['results'][0],route_worklist=tasks,allow_d1_only=False,supplied_rtl=True)

@pytest.mark.parametrize('mutation',[
    'none','entry','exit_deleted','route_deleted','prompt','report_deleted','report_duplicate',
    'ldoc_deleted','input_changed','dataset_changed','activation_rollback','duplicate_exit','duplicate_mode',
    'route_pointer_duplicate','ldoc_and_entry','route_removed_and_ldoc',
])
def test_public_backup_admission_current_and_strict(tmp_path,monkeypatch,mutation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); solve_path=run/'solve_report.json'
    solve=json.loads(solve_path.read_text()); row=solve['results'][0]
    docs=project/'phase1/generated_docs/L1.json'
    report=pl.report_path(project,'phase1_one_shot.json')
    if mutation=='entry': row['entry']='9'
    if mutation=='exit_deleted': row.pop('exit',None)
    if mutation=='route_deleted': row.pop('delivery_route',None)
    if mutation=='prompt': (project/'input/phase1_prompt.md').write_text('A changed design INPUT.')
    if mutation=='report_deleted': report.unlink()
    if mutation=='report_duplicate':
        raw=report.read_text(); report.write_text(raw.replace('"verdict": "PASS"','"verdict": "FAIL", "verdict": "PASS"'))
    if mutation=='ldoc_deleted': docs.unlink()
    if mutation=='input_changed':
        manifest = project / "input/public_original/manifest.json"
        value = json.loads(manifest.read_text())
        value["source_sha256"] = "f" * 64
        manifest.write_text(json.dumps(value))
    if mutation=='dataset_changed': (dataset/(task['id']+'_prompt.txt')).write_text('A changed external dataset, after immutable staging.')
    if mutation=='activation_rollback':
        pointer=bd._receipt_current_pointer(project,'d1_activation'); saved=pointer.read_bytes()
        activation=bd._read_current_receipt(project,'d1_activation')['receipt']
        bd._publish_current_receipt(project,'d1_activation',activation,digest_field='activation_sha256',run_id='review-repeat-activation')
        pointer.write_bytes(saved)
    if mutation in {'ldoc_and_entry','route_removed_and_ldoc'}:
        row['entry']='2'; docs.unlink()
        if mutation=='route_removed_and_ldoc': bd._receipt_current_pointer(project,'route_decision').unlink()
    solve_path.write_text(json.dumps(solve))
    if mutation=='duplicate_exit':
        raw=solve_path.read_text(); solve_path.write_text(raw.replace('"exit": "2"','"exit": "37.5ic", "exit": "2"',1))
    if mutation=='duplicate_mode':
        raw=solve_path.read_text(); solve_path.write_text(raw.replace('"authority": "PROGRAM_DEFAULT"','"authority": "USER_EXPLICIT_ULTRA", "authority": "PROGRAM_DEFAULT"',1))
    if mutation=='route_pointer_duplicate':
        p=bd._receipt_current_pointer(project,'route_decision'); raw=p.read_text()
        p.write_text(raw.replace('"kind": "route_decision"','"kind": "wrong", "kind": "route_decision"'))
    rc=frozen.resume(dataset,run)
    record('admission-'+mutation,{'rc':rc,'runner_calls':calls,'solve_report':json.loads(solve_path.read_text()),
        'ldoc_exists':docs.exists(),'report_exists':report.exists()})
    if mutation in {'none','exit_deleted','route_deleted','dataset_changed'}:
        assert len(calls)==1 and calls[0][calls[0].index('--exit-step')+1]=='2'
    else: assert calls==[], f'{mutation} passed into runner: {calls}'

@pytest.mark.parametrize('mutation',['none','report_delete','report_fail','ldoc_delete','ldoc_change','input_change'])
def test_downstream_changes_cannot_be_hidden_by_d1_restoration(tmp_path,monkeypatch,mutation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    if os.environ.get('R4_REVERSE')=='restore-disabled':
        monkeypatch.setattr(bd,'_restore_d1_evidence',lambda snapshot:None)
    project=Path(task['project']); docs=project/'phase1/generated_docs/L1.json'
    report=pl.report_path(project,'phase1_one_shot.json')
    before={'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'provenance':ea.phase1_provenance(project)}
    during={}
    def downstream(argv,*args,**kwargs):
        calls.append(list(argv))
        if mutation=='report_delete': report.unlink()
        if mutation=='report_fail':
            payload=json.loads(report.read_text()); payload['verdict']='FAIL'; report.write_text(json.dumps(payload))
        if mutation=='ldoc_delete': docs.unlink()
        if mutation=='ldoc_change': docs.write_text('{"requirement":"different during execution"}\n')
        if mutation=='input_change': (project/'input/phase1_prompt.md').write_text('A different prompt during execution.')
        during.update(report_exists=report.exists(),provenance=ea.phase1_provenance(project))
        if report.exists(): during['report_sha256']=hashlib.sha256(report.read_bytes()).hexdigest()
        return SimpleNamespace(returncode=1,stdout='',stderr='')
    # Keep genuine _RunnerBudget invocation/receipt production and diagnostics.
    monkeypatch.setattr(bd._RunnerBudget,'run',PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess,'run',downstream)
    rc=frozen.resume(dataset,run)
    after=state(run,project)
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    first_calls=copy.deepcopy(calls)
    if mutation not in {'none','input_change'}:
        calls.clear()
        monkeypatch.setattr(bd._RunnerBudget,'run',_stop_boundary(calls))
        subsequent_rc=frozen.resume(dataset,run)
        next_calls=copy.deepcopy(calls)
    else: subsequent_rc,next_calls=None,[]
    record('during-'+mutation,{'rc':rc,'calls':first_calls,'subsequent_rc':subsequent_rc,'subsequent_calls':next_calls,'before':before,'during':during,
        'after_admission':{k:v for k,v in after.items() if k not in {'project','task'}},
        'after_report_sha256':hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None,
        'after_provenance':ea.phase1_provenance(project),'result':result,
        'latest_invocation':json.loads((project/'reports/orchestrator/runner_invocations/latest.json').read_text())})
    assert len(first_calls)==1
    if mutation=='none': assert after['status']=='ACTIVE'
    else: assert after['status']=='REFUSED', f'{mutation} was hidden and old activation remains ACTIVE'

@pytest.mark.parametrize('seam',['fanout_route_delete','fanout_report_delete','capture_report_fail'])
def test_admission_is_rechecked_at_actual_runner_boundary(tmp_path,monkeypatch,seam):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); report=pl.report_path(project,'phase1_one_shot.json')
    if seam.startswith('fanout'):
        original=bd._runtime_pair_before_fan_out
        def mutate(plans,*args,**kwargs):
            if plans:
                if seam=='fanout_route_delete': bd._receipt_current_pointer(project,'route_decision').unlink()
                else: report.unlink()
            return original(plans,*args,**kwargs)
        monkeypatch.setattr(bd,'_runtime_pair_before_fan_out',mutate)
    else:
        original=bd._capture_d1_evidence
        def mutate(p):
            payload=json.loads(report.read_text()); payload['verdict']='FAIL'; report.write_text(json.dumps(payload))
            return original(p)
        monkeypatch.setattr(bd,'_capture_d1_evidence',mutate)
    rc=frozen.resume(dataset,run)
    record('seam-'+seam,{'rc':rc,'calls':calls,'result':json.loads((run/'solve_report.json').read_text())['results'][0]})
    assert calls==[]

@pytest.mark.parametrize('operation',['missing_report','missing_route','missing_activation'])
def test_refusal_persists_across_repeated_invocation(tmp_path,monkeypatch,operation):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project'])
    path=(pl.report_path(project,'phase1_one_shot.json') if operation=='missing_report' else
        bd._receipt_current_pointer(project,'route_decision' if operation=='missing_route' else 'd1_activation'))
    path.unlink()
    returns=[frozen.resume(dataset,run),frozen.resume(dataset,run)]
    record('repeat-'+operation,{'returns':returns,'calls':calls,'missing_path':str(path),'exists':path.exists()})
    assert calls==[] and not path.exists()

@pytest.mark.parametrize('exception',['runtime_error','signal_exit'])
def test_failed_subprocess_cannot_restore_a_deleted_d1_permit(tmp_path,monkeypatch,exception):
    dataset,run,task,calls=prior.ready_backup(tmp_path,monkeypatch)
    project=Path(task['project']); report=pl.report_path(project,'phase1_one_shot.json')
    def failed(argv,*args,**kwargs):
        calls.append(list(argv)); report.unlink()
        if exception=='runtime_error': raise RuntimeError('REVIEW_CONTROLLED_CHILD_FAILURE')
        return SimpleNamespace(returncode=-15,stdout='',stderr='')
    monkeypatch.setattr(bd._RunnerBudget,'run',PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess,'run',failed)
    rc=frozen.resume(dataset,run)
    admission=state(run,project)
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    record('exception-'+exception,{'rc':rc,'calls':calls,'report_exists':report.exists(),
        'admission':{k:v for k,v in admission.items() if k not in {'task','project'}},'result':result})
    assert len(calls)==1
    assert admission['status']=='REFUSED', 'failed child restored old deleted PASS into an ACTIVE launch permit'

@pytest.mark.parametrize('mutation',['target','mode'])
def test_co_mutated_run_root_cannot_replace_admitted_ai_route(tmp_path,monkeypatch,mutation,prompt=None):
    dataset,run,task,calls=_ready_backup(tmp_path,monkeypatch,prompt=prompt)
    project=Path(task['project'])
    external,capability=bd._route_anchor_paths(run)
    original_anchor=external.read_bytes()
    original_response=Path(task['response_path']).read_bytes()
    solve_path=run/'solve_report.json'; solve=json.loads(solve_path.read_text()); row=solve['results'][0]
    original=copy.deepcopy(row['route_receipt'])
    prompt=(project/'input/phase1_prompt.md').read_text()
    receipt=tnr.route_decision_receipt(prompt,nature=original['task_nature'],requested_evidence=original['requested_evidence'],
        delivery_target='ip_hardmacro' if mutation=='target' else original['delivery_target'],
        source_sha256=original['source_sha256'],
        explicit_user_evidence=rd.explicit_ultra_evidence('use ultra mode') if mutation=='mode' else None)
    activation=bd._read_current_receipt(project,'d1_activation')['receipt']
    gate=rd.make_d1_gate(verdict='PASS',route_receipt=receipt,provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'],
        ldoc_root_handle=activation['ldoc_root_handle'],invocation_id=activation['d1_gate']['invocation_id'],
        report_sha256=activation['d1_gate']['report_sha256'])
    pending=rd.write_d1_pending(project/'unused',route_receipt=receipt,source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'])
    replacement=rd.activate_d1(pending=pending,route_receipt=receipt,provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'],task_sha256=task['task_sha256'],
        ldoc_root_handle=activation['ldoc_root_handle'],d1_gate=gate)
    # Only run-root files change. No prompt, original AI response, dataset,
    # external owner anchor, capability or product source is rewritten.
    bd._publish_current_receipt(project,'route_decision',receipt,digest_field='receipt_sha256',run_id='review-co-mutation-route')
    bd._publish_current_receipt(project,'d1_pending',pending,digest_field='activation_sha256',run_id='review-co-mutation-pending')
    bd._publish_current_receipt(project,'d1_activation',replacement,digest_field='activation_sha256',run_id='review-co-mutation-activation')
    row.update(route_receipt=receipt,d1_activation=replacement,entry=receipt['entry_step'],exit=receipt['verify_through'],
        delivery_route=tnr.delivery_route_for_target(receipt['delivery_target']))
    solve_path.write_text(json.dumps(solve))
    rc=frozen.resume(dataset,run)
    record('co-mutation-'+mutation,{'rc':rc,'calls':calls,'original_receipt':original,'replacement_receipt':receipt,
        'external_anchor_unchanged':external.read_bytes()==original_anchor,
        'original_ai_response_unchanged':Path(task['response_path']).read_bytes()==original_response,
        'replacement_activation':replacement,'result':json.loads(solve_path.read_text())['results'][0]})
    assert calls==[], f'run-root rewrite replaced admitted AI {mutation} without changing the owner anchor: {calls}'

@pytest.mark.parametrize('prompt,target,route,terminal', [
    (IC_PROMPTS[0], 'shippable_gds', 'ic', '37.5ic'),
    (IC_PROMPTS[2], 'gds', 'ic', '37'),
    ('Deliver a standalone IP hardmacro to be integrated into a host IC; produce GDS, LEF and Liberty views.', 'ip_hardmacro', 'ip', '37.5ip'),
])
def test_compatible_object_enters_its_public_dispatch_span(tmp_path, monkeypatch, prompt, target, route, terminal):
    dataset, run, task, answer, calls = _issue(tmp_path, monkeypatch, prompt)
    answer['semantic_decision'] = {'nature': 'spec_generation', 'delivery_target': target,
                                   'semantic_payload_sha256': task['semantic_payload_sha256']}
    fixture._write_answer(task, answer)
    _resume(dataset, run)
    assert len(calls) == 2
    assert calls[0][calls[0].index('--exit-step') + 1] == 'D1'
    assert calls[1][calls[1].index('--exit-step') + 1] == terminal
    assert all(argv[argv.index('--route') + 1] == route for argv in calls)

@pytest.mark.parametrize('location', ['route_history', 'route_envelope', 'pending_pointer', 'activation_pointer', 'anchor', 'admission', 'config', 'response'])
@pytest.mark.parametrize('raw_kind', ['duplicate', 'overflow'])
def test_each_authority_reader_refuses_ambiguous_json(tmp_path, monkeypatch, location, raw_kind):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project'])
    if location == 'route_history': path = bd._receipt_history_head(project, 'route_decision')
    elif location == 'route_envelope': path = bd._read_current_receipt(project, 'route_decision')['path']
    elif location in {'pending_pointer', 'activation_pointer'}:
        path = bd._receipt_current_pointer(project, 'd1_pending' if location == 'pending_pointer' else 'd1_activation')
    elif location == 'anchor': path = bd._route_anchor_paths(run)[0]
    elif location == 'admission': path = bd._route_admission_path(run, task)
    elif location == 'config': path = run / 'solve_report.json'
    else: path = Path(task['response_path'])
    path = Path(path)
    value = json.loads(path.read_text())
    key = next(iter(value))
    raw = path.read_text()
    injected = (json.dumps(key) + ':"shadow",' if raw_kind == 'duplicate' else '"invalid_number":1e999,')
    path.write_text(raw.replace('{', '{' + injected, 1))
    _resume(dataset, run)
    assert calls == []

@pytest.mark.parametrize('mutation', ['restore_old_bytes', 'retype_current_route'])
def test_invalidated_d1_requires_new_typed_invocation(tmp_path, monkeypatch, mutation):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project']); report = pl.report_path(project, 'phase1_one_shot.json')
    original_bytes = report.read_bytes()
    old_activation = bd._read_current_receipt(project, 'd1_activation')['receipt']
    def corrupt(argv, *args, **kwargs):
        calls.append(list(argv))
        report.unlink()
        return SimpleNamespace(returncode=-15, stdout='', stderr='')
    monkeypatch.setattr(bd._RunnerBudget, 'run', PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess, 'run', corrupt)
    _resume(dataset, run)
    assert len(calls) == 1 and not report.exists()
    report.write_bytes(original_bytes)
    assert state(run, project)['status'] == 'REFUSED'
    if mutation == 'retype_current_route':
        receipt = bd._read_current_receipt(project, 'route_decision')['receipt']
        monkeypatch.setattr(bd.subprocess, 'run', fixture._typed_d1_runner(calls))
        _, _, fresh = bd._activate_route_d1(project, task, receipt,
            Path(bd.__file__).parent / 'vibe_ic_one_shot_runner.py', bd._RunnerBudget(1, 1, 1))
        assert fresh['d1_gate']['invocation_id'] != old_activation['d1_gate']['invocation_id']
        assert state(run, project)['status'] == 'ACTIVE'

@pytest.mark.parametrize('seam', ['capture_replace', 'native_replace', 'native_fail', 'native_route_delete', 'native_response_replace'])
def test_snapshot_generation_is_checked_through_native_submission(tmp_path, monkeypatch, seam):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project']); report = pl.report_path(project, 'phase1_one_shot.json')
    touched = []
    def replace():
        if seam == 'native_route_delete':
            bd._receipt_current_pointer(project, 'route_decision').unlink()
            touched.append(1)
            return
        if seam == 'native_response_replace':
            response = Path(task['response_path'])
            value = json.loads(response.read_text())
            value['author']['model'] = 'replacement-model'
            response.write_text(json.dumps(value))
            touched.append(1)
            return
        raw = report.read_bytes()
        if seam == 'native_fail':
            value = json.loads(raw); value['verdict'] = 'FAIL'; raw = json.dumps(value).encode()
        other = report.with_suffix('.replacement'); other.write_bytes(raw); other.replace(report)
        touched.append(1)
    if seam == 'capture_replace':
        original = bd._capture_d1_evidence
        def capture(p):
            snapshot = original(p)
            replace()
            return snapshot
        monkeypatch.setattr(bd, '_capture_d1_evidence', capture)
    else:
        original = bd._runner_material_snapshot
        def material(p):
            value = original(p)
            if getattr(bd._D1_LAUNCH_CONTEXT, 'snapshot', None) is not None and not touched:
                replace()
            return value
        monkeypatch.setattr(bd, '_runner_material_snapshot', material)
    def stop(argv, *args, **kwargs):
        calls.append(list(argv)); return SimpleNamespace(returncode=1, stdout='', stderr='')
    monkeypatch.setattr(bd._RunnerBudget, 'run', PRODUCTION_RUN)
    monkeypatch.setattr(bd.subprocess, 'run', stop)
    _resume(dataset, run)
    assert touched and calls == []


def test_finite_json_numbers_do_not_change_public_route_admission(tmp_path, monkeypatch):
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    path = run / 'solve_report.json'
    solve = json.loads(path.read_text())
    solve['measured_seconds'] = 0.125
    solve['bookkeeping_delta'] = -12.5
    path.write_text(json.dumps(solve))
    _resume(dataset, run)
    assert len(calls) == 1
    assert calls[0][calls[0].index('--exit-step') + 1] == '2'


def test_real_input_cannot_acquire_replacement_mode_authority(tmp_path, monkeypatch):
    from _hostpaths import require_repo
    prompt = require_repo(
        'vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
        'fixtures', 'real_benchmark', 'directional_bump_fall_moore_prompt.md').read_text()
    assert 'module TopModule' in prompt
    test_co_mutated_run_root_cannot_replace_admitted_ai_route(
        tmp_path, monkeypatch, 'mode', prompt=prompt)


def test_co_mutated_d1_must_come_from_a_fresh_typed_gate(tmp_path, monkeypatch):
    runtime.assume_matching_runtime_pair(monkeypatch)
    dataset, run, task, calls = _ready_backup(tmp_path, monkeypatch)
    project = Path(task['project'])
    receipt = bd._read_current_receipt(project, 'route_decision')['receipt']
    original = bd._read_current_receipt(project, 'd1_activation')['receipt']
    report = pl.report_path(project, 'phase1_one_shot.json')
    value = json.loads(report.read_text())
    value['runner_binding']['invocation_id'] = 'unissued-software-control-d1'
    report.write_text(json.dumps(value))
    gate = rd.make_d1_gate(verdict='PASS', route_receipt=receipt, provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'], task_sha256=task['task_sha256'],
        ldoc_root_handle=original['ldoc_root_handle'], invocation_id=value['runner_binding']['invocation_id'],
        report_sha256=hashlib.sha256(report.read_bytes()).hexdigest())
    pending = bd._read_current_receipt(project, 'd1_pending')['receipt']
    replacement = rd.activate_d1(pending=pending, route_receipt=receipt, provenance=ea.phase1_provenance(project),
        source_sha256=receipt['source_sha256'], task_sha256=task['task_sha256'],
        ldoc_root_handle=original['ldoc_root_handle'], d1_gate=gate)
    bd._publish_current_receipt(project, 'd1_activation', replacement,
        digest_field='activation_sha256', run_id='unissued-d1-control')
    _resume(dataset, run)
    print(json.dumps({'calls':calls,'original_activation':original,'replacement_activation':replacement}))
    assert calls == [], f'An unissued replacement D1 gate reached the child boundary: {calls}'
