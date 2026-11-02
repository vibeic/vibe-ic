"""Neutral historical material fixtures using real subprocess lineage, never native PASS."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import textwrap

import pytest
import benchmark_dispatch as d
import flow109 as f

PROGRAMS = Path(__file__).resolve().parents[1]


def _history_launch(root, *, generate=True, mutation=''):
    leaf_code = textwrap.dedent('''\
    import json, os, pathlib, sys
    sys.path.insert(0, %r)
    import benchmark_dispatch as d
    p=pathlib.Path(sys.argv[1])
    is_phase1=pathlib.Path(__file__).stem == 'phase1_one_shot_runner'
    name='phase1_one_shot.json' if is_phase1 else 'phase2_one_shot.json'
    if not is_phase1 and os.environ.get('LINEAGE_TEST_MUTATION') == 'input':
        (p/'input/phase1_prompt.md').write_text('Changed source input.\\n')
    if not is_phase1 and os.environ.get('LINEAGE_TEST_MUTATION') == 'source':
        source=pathlib.Path(__file__).with_name('phase1_one_shot_runner.py')
        source.write_text(source.read_text()+'\\n# Changed phase1 source.\\n')
    if not is_phase1 and os.environ.get('LINEAGE_TEST_GENERATE_OUTPUT') == '1':
        out=p/'phase2/stage1/rtl/neutral.v'
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text('// Neutral lineage inventory fixture; not a design answer.\\n')
    body={'project':str(p),'fixture_control':True,'verdict':'NOT_MEASURED',
          'declared_window':{'entry_step':sys.argv[sys.argv.index('--entry-step')+1], 'exit_step':sys.argv[sys.argv.index('--exit-step')+1]}}
    out=p/'reports/orchestrator'/name
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(d._bind_runner_report(body,p,__file__,name)))
    ''') % str(PROGRAMS)
    for phase in ('phase1','phase2'):
        (root/(phase+'_one_shot_runner.py')).write_text(leaf_code)
    front = root / 'vibe_ic_one_shot_runner.py'
    front.write_text(textwrap.dedent('''\
    import json, os, pathlib, sys
    sys.path.insert(0, %r)
    import benchmark_dispatch as d
    import flow109 as f
    import vibe_ic_one_shot_runner as real
    p=pathlib.Path(sys.argv[1])
    entry=sys.argv[sys.argv.index('--entry-step')+1]
    exit_=sys.argv[sys.argv.index('--exit-step')+1]
    selection=json.loads(pathlib.Path(os.environ[f.CONTEXT_ENV]).read_text())
    if entry != exit_:
        parent_attempt=f._new_attempt(p,selection)
        for row in selection['resolved_rows']:
            selected=f.component_context(selection,requested_step=row['id'])
            child_attempt=f._new_attempt(p,selected)
            req=parent_attempt/('owner-'+child_attempt.name+'.json')
            req.write_text(json.dumps({'schema':'vibeic.flow109.owner-launch.v1','parent_context':selection,
              'child_context':selected,'parent_attempt':str(parent_attempt),'child_attempt':str(child_attempt)}))
            env=dict(os.environ)
            env[f.OWNER_LAUNCH_ENV]=str(req)
            rc=real._run_phase('Fixture selected owner',pathlib.Path(__file__),[str(p),'--entry-step',row['id'],'--exit-step',row['id']],env=env,invocation={})
            assert rc == 0
        window={'entry_step':entry,'exit_step':exit_}
    else:
        selected=f.component_context(selection,requested_step=entry)
        owner=f._canonical_owner_dispatch(selected['resolved_row'])
        selection_path=p/'reports'/('fixture-'+entry+'-context.json')
        selection_path.parent.mkdir(parents=True,exist_ok=True)
        selection_path.write_text(json.dumps(selected))
        env=dict(os.environ)
        env[f.CONTEXT_ENV]=str(selection_path)
        runner='phase2_one_shot_runner' if owner['owner_runner']=='design_one_shot_runner' else owner['owner_runner']
        rc=real._run_phase('Fixture leaf',pathlib.Path(__file__).parent/(runner+'.py'),
           [str(p),'--entry-step',owner['owner_entry_step'],'--exit-step',owner['owner_exit_step']],env=env,invocation={})
        assert rc == 0
        window={'entry_step':owner['owner_entry_step'],'exit_step':owner['owner_exit_step']}
    body={'project':str(p),'fixture_control':True,'verdict':'NOT_MEASURED','declared_window':window}
    out=p/'reports/orchestrator/vibe_ic_one_shot.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(d._bind_runner_report(body,p,__file__,out.name)))
    ''') % str(PROGRAMS))
    features={n:False for n in set(f.load_registry()['predicate_names'])-set(f.load_registry()['predicate_definitions'])-{'always'}}
    features.update(rtl_only=True,has_digital=True)
    selection=f.execution_context(f.resolve_plan(features),'D01','D09')
    selection_path=root/'selection.json'
    selection_path.write_text(json.dumps(selection))
    project=root/'project'
    (project/'input').mkdir(parents=True)
    (project/'input/phase1_prompt.md').write_text('Neutral lineage fixture.\n')
    argv=[sys.executable,str(front),str(project),'--entry-step','D01','--exit-step','D09']
    budget=d._RunnerBudget(1,1,0)
    budget._env={k:v for k,v in os.environ.items() if not k.startswith(('VIBEIC_FLOW109','VIBEIC_RUNNER_','VIBEIC_PARENT_RUNNER_','VIBE_IC_RUNNER_LOCK'))}
    budget._env[f.CONTEXT_ENV]=str(selection_path)
    budget._env['LINEAGE_TEST_GENERATE_OUTPUT']='1' if generate else '0'
    budget._env['LINEAGE_TEST_MUTATION']=mutation
    result=budget.run(argv)
    assert result.error is None and result.rc == 0,(result.error,result.stdout,result.stderr)
    return project,result


@pytest.mark.parametrize('generate', [False, True])
def test_phase1_owning_completion_precedes_legitimate_phase2_output(tmp_path, generate):
    project, result = _history_launch(tmp_path, generate=generate)
    receipt = result.invocation
    p1 = receipt['reports_after']['phase1_one_shot.json']['runner_binding']
    p2 = receipt['reports_after']['phase2_one_shot.json']['runner_binding']
    assert p1['material']['input'] == receipt['material_after']['input']
    assert not p1['material']['output_rtl']
    assert p2['material'] == receipt['material_after']
    assert bool(receipt['material_after']['output_rtl']) == generate
    assert d._runner_report_binding_reason(receipt, require_phase2=True) is None
    assert d._runner_diagnostics(result, receipt['argv'], project)['status'] == 'REPORTS_AVAILABLE'
    if generate:
        assert d._runner_report_binding_reason(receipt, require_phase2=False).startswith('RUNNER_REPORT_UNBOUND:')


@pytest.mark.parametrize('mutation', ['input', 'source'])
def test_phase1_history_requires_current_input_and_source(tmp_path, mutation):
    _, result = _history_launch(tmp_path, mutation=mutation)
    assert d._runner_report_binding_reason(result.invocation, require_phase2=True).startswith('RUNNER_REPORT_UNBOUND:')


def _rewrite(path, document):
    path.write_text(json.dumps(document))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', [
    'owner_output', 'completion_output', 'owner_input', 'owner_window', 'selection',
    'phase2_output',
])
def test_rehashed_history_still_requires_exact_owning_completion(tmp_path, kind):
    project, result = _history_launch(tmp_path)
    receipt = copy.deepcopy(result.invocation)
    name = 'phase2_one_shot.json' if kind == 'phase2_output' else 'phase1_one_shot.json'
    original_record = copy.deepcopy(receipt['reports_after'][name])
    canonical = project / 'reports/orchestrator' / name
    report = json.loads(canonical.read_bytes())
    outer_path = project / 'reports/orchestrator/vibe_ic_one_shot.json'
    outer = json.loads(outer_path.read_bytes())

    def rewrite_descendant(publication):
        matches = []
        for reference in publication['runner_binding']['child_invocations']:
            completion_path = project / reference['path']
            completion = json.loads(completion_path.read_bytes())
            launch = json.loads((project / completion['launch']['path']).read_bytes())
            if (completion['reports_after'].get(name) == original_record
                    and name in d._runner_fresh_reports(
                        launch['reports_before'], completion['reports_after'])):
                matches.append((reference, completion_path, completion))
        assert len(matches) == 1
        reference, completion_path, completion = matches[0]
        direct = completion['child_invocation']['invocation_id'] == report['runner_binding']['invocation_id']
        owner_name = name if direct else 'vibe_ic_one_shot.json'
        owner_ref = completion['owner_reports'][owner_name]
        owner_path = project / owner_ref['path']
        owner = json.loads(owner_path.read_bytes())
        if direct:
            launch_path = project / completion['launch']['path']
            launch = json.loads(launch_path.read_bytes())
            if kind in ('owner_output', 'phase2_output'):
                owner['runner_binding']['material']['output_rtl'] = {'forged.v': {'sha256': '0' * 64, 'size': 0}}
            elif kind == 'completion_output':
                completion['material_after']['output_rtl'] = {'forged.v': {'sha256': '0' * 64, 'size': 0}}
            elif kind == 'owner_input':
                owner['runner_binding']['material']['input'] = {}
            elif kind == 'owner_window':
                owner['declared_window']['exit_step'] = '9'
            elif kind == 'selection':
                launch['selection'] = f.execution_context(f.resolve_plan(
                    launch['selection']['features']), 'D09', 'D09')
            completion['launch']['sha256'] = _rewrite(launch_path, launch)
            _rewrite(canonical, owner)
        else:
            rewrite_descendant(owner)
        owner_ref['sha256'] = _rewrite(owner_path, owner)
        completion['reports_after'][owner_name]['sha256'] = owner_ref['sha256']
        completion['reports_after'][owner_name]['runner_binding'] = owner['runner_binding']
        completion['reports_after'][name] = d._runner_report_snapshot(project)[name]
        reference['sha256'] = _rewrite(completion_path, completion)

    rewrite_descendant(outer)
    _rewrite(outer_path, outer)
    receipt['reports_after'] = d._runner_report_snapshot(project)
    assert d._runner_report_binding_reason(receipt, require_phase2=True).startswith('RUNNER_REPORT_UNBOUND:')
