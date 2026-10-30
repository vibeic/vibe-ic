"""SOFTWARE controls over the shipped dispatcher/public manifest boundary.

Neutral visible task only; no dataset, RTL answer, hidden harness, native
qualification, score or fabricated semantic route approval.
"""
import json
import sys
from pathlib import Path

import pytest
import benchmark_dispatch as dispatch
import flow109
import task_nature_route as routing
import vibe_ic_one_shot_runner as public


@pytest.fixture
def subject(tmp_path):
    prompt = ('Deliver only a soft-IP RTL module. Inputs a and b drive q as their '
              'bitwise conjunction. Request lint validation only; no analog, '
              'netlist, hardware, physical delivery or other optional work.')
    # Explicit operator declarations for this SOFTWARE task, not defaults in
    # the implementation. The current registry still validates every field.
    features = {name: False for name in
                set(flow109.load_registry()['predicate_names'])
                - set(flow109.load_registry()['predicate_definitions']) - {'always'}}
    features.update(rtl_only=True, has_digital=True)
    project = tmp_path / 'subject'
    (project / 'input').mkdir(parents=True)
    (project / 'input/phase1_prompt.md').write_text(prompt)
    manifest = {'features': features}
    (project / 'input/flow109-manifest.json').write_text(json.dumps(manifest))
    return project, manifest


def observe_public(argv, monkeypatch, capsys):
    """Real parser/delivery/manifest/planner/owner route, stop before authoring.

    The trap is after prepare_front_door, never a mock PASS or fake child result.
    Old behavior returns the actual MANIFEST_REQUIRED refusal instead.
    """
    class OwnerBoundary(Exception):
        pass
    observed = {}
    def owner_boundary(args):
        record = json.loads((args.project / 'reports/flow109/owner_route.json').read_text())
        import _path_layout
        _path_layout.select_rtl_input(args.project,args.rtl_input,args.entry_step,args.exit_step)
        observed.update(outcome='OWNER_REACHED', owner=record['owner_runner'],
                        entry=args.entry_step, exit=args.exit_step)
        raise OwnerBoundary
    monkeypatch.setattr(public, '_configure_execution_policy', owner_boundary)
    monkeypatch.setattr(sys, 'argv', argv[1:])
    for key in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):monkeypatch.delenv(key, raising=False)
    try:
        rc = public.main()
        observed.update(outcome='REFUSED', rc=rc)
    except OwnerBoundary:
        pass
    output = capsys.readouterr()
    observed['stderr'] = output.err
    return observed


@pytest.mark.parametrize('nature,entry,terminal,supplied,owner,native_entry,native_exit', [
    ('generation','1','2',False,'design_one_shot_runner','1','4'),
    ('completion_phase1','D1','D1',False,'phase1_one_shot_runner','D1','D1'),
    ('completion_validation','1','2',True,'design_one_shot_runner','2','2'),
    ('debug','2','2',True,'design_one_shot_runner','2','2'),
])
def test_dispatcher_reaches_actual_current_product_owner(subject, monkeypatch, capsys,
        nature, entry, terminal, supplied, owner, native_entry, native_exit):
    project, _ = subject
    runner = Path(public.__file__)
    if supplied:
        argv = dispatch._resume_solver_argv(runner, project, True, entry, terminal, 'ip', 'original')
    else:
        argv = dispatch._solver_argv(runner, project, entry, terminal, 'ip',
            'structured' if nature=='completion_phase1' else 'original')
    observed = observe_public(argv, monkeypatch, capsys)
    (project.parent / ('OBSERVATION-'+nature+'.json')).write_text(json.dumps(
        {'argv':argv,'observed':observed,'scope':'SOFTWARE_OWNER_BOUNDARY_ONLY'},indent=2))
    assert {k:v for k,v in observed.items() if k!='stderr'} == {
        'outcome':'OWNER_REACHED','owner':owner,'entry':native_entry,'exit':native_exit}
    assert argv[argv.index('--flow')+1]=='109'
    assert argv[argv.index('--flow109-manifest')+1]==str(project/'input/flow109-manifest.json')
    plan=json.loads((project/'reports/flow109/plan.json').read_text())
    assert plan['features']['physical'] is False
    context=json.loads(Path(__import__('os').environ[flow109.CONTEXT_ENV]).read_text())
    rows=context.get('resolved_rows') or [context['resolved_row']]
    assert all(r['position']<30 for r in rows)


def test_missing_manifest_still_refuses_before_authoring(subject,monkeypatch,capsys):
    project,_=subject;(project/'input/flow109-manifest.json').unlink()
    argv=dispatch._solver_argv(Path(public.__file__),project,'1','2','ip','original')
    observed=observe_public(argv,monkeypatch,capsys)
    assert observed['outcome']=='REFUSED' and observed['rc']==2
    assert 'FLOW109_MANIFEST_REQUIRED' in observed['stderr']
    assert not (project/'reports/flow109/owner_route.json').exists()


@pytest.mark.parametrize('damage',['non_boolean','unresolved','route_conflict'])
def test_bad_explicit_features_cannot_reach_authoring(subject,monkeypatch,capsys,damage):
    project,manifest=subject
    if damage=='non_boolean':manifest['features']['has_digital']='yes'
    elif damage=='unresolved':del manifest['features']['has_digital']
    else:manifest['features'].update(soft_ip=False,rtl_only=False,ic=True)
    (project/'input/flow109-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        dispatch._solver_argv(Path(public.__file__),project,'1','2','ip','original')
    assert not (project/'reports/flow109/owner_route.json').exists()


def test_operator_input_is_immutable_across_normal_forwarding(subject,tmp_path):
    project,manifest=subject
    source=tmp_path/'explicit-features.json';source.write_text(json.dumps(manifest))
    run=tmp_path/'run';dispatch._stage_product_manifest(run,source)
    target=tmp_path/'other';dispatch._forward_product_manifest(run,target)
    assert (target/'input/flow109-manifest.json').read_bytes()==source.read_bytes()
    before=(run/'input/flow109-manifest.json').read_bytes()
    manifest['features']['requires_security']=True;source.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='immutable'):
        dispatch._stage_product_manifest(run,source)
    assert (run/'input/flow109-manifest.json').read_bytes()==before


def test_unapproved_route_still_refuses_before_any_runner(tmp_path):
    with pytest.raises(ValueError):
        dispatch._require_route_admission(tmp_path,{}, {},require_d1=False)
    assert not (tmp_path/'runner_invocation.json').exists()


@pytest.mark.parametrize('name_clause', ['named LogicBlock', 'called LogicBlock', 'named chip'])
def test_named_module_background_reaches_soft_ip_owner(subject, monkeypatch, capsys, name_clause):
    project, manifest = subject
    prompt = (f'Implement a Verilog module {name_clause} with two inputs and one output. '
              'The RefUnit is a chip with a logic gate. '
              'The module should implement the same functionality as the RefUnit chip.')
    (project / 'input/phase1_prompt.md').write_text(prompt)
    requirements = routing.prompt_delivery_requirements(prompt)
    resolved = routing.resolve_prompt_delivery_target(requirements, 'rtl')
    assert resolved['ok'] is True
    delivery = routing.delivery_route_for_target(resolved['target'], resolved['route_family'])
    assert delivery == 'ip', requirements
    assert routing.flow109_product_window(manifest, '1', '2', delivery) == ('D09', 'D11')
    argv = dispatch._solver_argv(Path(public.__file__), project, '1', '2', delivery, 'original')
    observed = observe_public(argv, monkeypatch, capsys)
    assert observed['outcome'] == 'OWNER_REACHED', observed
    assert observed['owner'] == 'design_one_shot_runner'
    assert observed['entry'] == '1' and observed['exit'] == '4'


@pytest.mark.parametrize('obligation', [
    'Deliver the final chip.',
    'Deliver GDS for fabrication.',
    'Deliver the modeled device in a physical package.',
])
def test_named_module_cannot_erase_independent_physical_delivery(subject, obligation):
    project, manifest = subject
    prompt = ('Implement a Verilog module named LogicBlock that models a chip. '
              + obligation)
    requirements = routing.prompt_delivery_requirements(prompt)
    resolved = routing.resolve_prompt_delivery_target(requirements, None)
    assert resolved['ok'] is True
    delivery = routing.delivery_route_for_target(resolved['target'], resolved['route_family'])
    assert delivery == 'ic', requirements
    with pytest.raises(ValueError, match='FLOW109_ROUTE_CONFLICT'):
        routing.flow109_product_window(manifest, '1', '2', delivery)
    assert not (project / 'reports/flow109/owner_route.json').exists()


@pytest.mark.parametrize('mode',['solve','resume'])
def test_cli_forwards_explicit_operator_input(subject,monkeypatch,mode):
    project,_=subject;seen=[]
    def coordinator(*args,**kwargs):
        seen.append(kwargs['flow109_manifest']);return 2
    monkeypatch.setattr(dispatch,'cmd_'+mode,coordinator)
    monkeypatch.setattr(dispatch,'_install_orphan_guard',lambda:None)
    monkeypatch.setattr(sys,'argv',[str(Path(dispatch.__file__)),'neutral-source-control',
        '--'+mode,'--dataset',str(project/'visible-only'),'--run',str(project/'run'),
        '--flow109-manifest',str(project/'input/flow109-manifest.json')])
    with pytest.raises(SystemExit) as result:dispatch.main()
    assert result.value.code==2
    assert seen==[str(project/'input/flow109-manifest.json')]


@pytest.mark.parametrize('terminal,expected', [('1',['D09']),('2',['D09','D10','D11']),('4',['D09','D10','D11','D12','D13'])])
def test_authoring_purpose_and_requested_evidence_keep_owner_closure(subject,terminal,expected):
    project,manifest=subject
    first,last=routing.flow109_product_window(manifest,'1',terminal,'ip')
    context=flow109.resolve_execution_window(flow109.resolve_plan(manifest['features']),first,last)
    rows=context.get('resolved_rows') or [context['resolved_row']]
    observed={'rows':[r['id'] for r in rows],
              'producer':rows[0]['profile']['dispatch']['producer'],
              'native_exit':context.get('native_exit_step') or rows[0]['profile']['dispatch']['owner_exit_step']}
    assert observed=={'rows':expected,'producer':'design_one_shot_runner.py:step_rtl_gen','native_exit':'4'}


def test_actual_solve_initializes_fresh_run_then_resume_keeps_unapproved_route_pending(subject,tmp_path,monkeypatch):
    project,manifest=subject
    dataset=tmp_path/'visible.jsonl';dataset.write_text(json.dumps({'id':'neutral_unit', 'input':{
        'prompt':'Write an RTL-only conjunction module; lint evidence only.', 'context':{}}})+'\n')
    run=tmp_path/'fresh-run'
    # Explicit SOURCE_ONLY runtime/preflight fixture. Real clean-room creation,
    # public adapter, route worklist issuance, input binding and resume remain.
    monkeypatch.setattr(dispatch,'_runtime_pair_gate',lambda *a,**k:(None,{'scope':'SOFTWARE_PREFLIGHT_NOT_QUALIFICATION'}))
    monkeypatch.setattr(dispatch,'_dispatch_format',lambda *a,**k:'cvdp')
    monkeypatch.setattr(dispatch,'_render_lesson_digest',lambda *a:None)
    source=project/'input/flow109-manifest.json'
    monkeypatch.setattr(dispatch,'_install_orphan_guard',lambda:None)
    monkeypatch.setattr(sys,'argv',[str(Path(dispatch.__file__)),'neutral-source-control',
        '--solve','--dataset',str(dataset),'--run',str(run),'--limit','1',
        '--flow109-manifest',str(source)])
    with pytest.raises(SystemExit) as solved:dispatch.main()
    observed={'rc':solved.value.code,'config':(run/'.bench_config.json').is_file(),
              'manifest':(run/'input/flow109-manifest.json').is_file()}
    assert observed=={'rc':2,'config':True,'manifest':True}
    report=json.loads((run/'solve_report.json').read_text())
    assert report['routing_phase']=='PENDING' and report['solved']==report['accepted']==0
    before=(run/'input/flow109-manifest.json').read_bytes()
    monkeypatch.setattr(sys,'argv',[str(Path(dispatch.__file__)),'neutral-source-control',
        '--resume','--dataset',str(dataset),'--run',str(run)])
    with pytest.raises(SystemExit) as resumed:dispatch.main()
    assert resumed.value.code==2
    assert (run/'input/flow109-manifest.json').read_bytes()==before
    assert not list(run.glob('projects/**/phase2/stage1/rtl/*'))


def test_original_owner_closure_does_not_authorize_a_broad_raw_request(subject,monkeypatch,capsys):
    import _path_layout as layout
    project,manifest=subject
    monkeypatch.delenv(flow109.CONTEXT_ENV,raising=False)
    with pytest.raises(ValueError,match='bounded Step 1/2'):
        layout.select_rtl_input(project,'original','1','4')
    argv=dispatch._solver_argv(Path(public.__file__),project,'1','4','ip','original')
    with pytest.raises(ValueError,match='bounded Step 1/2'):
        observe_public(argv,monkeypatch,capsys)
    assert layout._original_author_owner_closure(project,'1','4') is False


def test_unreadable_explicit_feature_input_is_named_refusal(tmp_path):
    with pytest.raises(ValueError,match='FLOW109_MANIFEST_INVALID'):
        dispatch._stage_product_manifest(tmp_path/'run',tmp_path/'missing.json')
    assert not (tmp_path/'run/input/flow109-manifest.json').exists()
