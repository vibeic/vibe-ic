"""General Shape-D dispatcher scope and synthetic named-AI lifecycle controls.

The static controls preserve the prohibition on benchmark-name branches and
require the registry to match the general extractor entry. Executable controls
prove the public entry, hidden boundary, shared route validation, fixed product
windows and complete-population barrier using synthetic rows only.
"""
import json
import re
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
DISPATCH = PROGRAMS / "benchmark_dispatch.py"
REGISTRY = PROGRAMS.parent / "benchmark" / "BENCHMARK_REGISTRY.json"
_GENERAL_EXTRACTOR = "agentic_jsonl_to_shape_d.py"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _dispatcher_routes_shape_d() -> bool:
    """Does the dispatcher name the general Shape-D extractor at all?"""
    return _GENERAL_EXTRACTOR in DISPATCH.read_text()


def _bench_format() -> dict:
    """`_BENCH_FORMAT` read from the source, without importing the module."""
    import ast
    tree = ast.parse(DISPATCH.read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "_BENCH_FORMAT"
                        for t in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError("_BENCH_FORMAT is gone from benchmark_dispatch.py")


def test_dispatch_setup_has_no_bench_name_branch():
    """The cmd_setup() function must not contain `bench == "cvdp"` (or similar
    benchmark-name string comparisons). The Shape-D path must be schema-driven."""
    src = DISPATCH.read_text()
    forbidden = [
        re.compile(r'bench\s*==\s*["\']cvdp["\']'),
        re.compile(r'bench\s*==\s*["\']rtllm["\']'),
        re.compile(r'bench\s*==\s*["\']verilogeval[-_]?v2["\']'),
        re.compile(r'bench\s*==\s*["\']verilogeval[-_]?human["\']'),
        re.compile(r'bench\s*==\s*["\']pyhdl[-_]?eval["\']'),
    ]
    for pat in forbidden:
        m = pat.search(src)
        assert m is None, (
            f"Found bench-name branch {m.group()!r} in benchmark_dispatch.py — "
            f"setup logic must be schema-driven, not keyword-driven.")


def test_dispatch_routes_jsonl_datasets_through_general_extractor():
    """A JSONL Shape-D dataset is routed through the GENERAL extractor, or it
    is not routed at all — never through a bench-named one.

    The negative half is unconditional: `cvdp_jsonl_extract.py` is the
    bench-specific extractor this file exists to keep out, and no scope
    decision licenses it back.

    The positive half is a DISJUNCTION with an exclusive-or, not a text pin:
    either the dispatcher names the general extractor (it has a Shape-D path,
    and that path is general), or the registry declares Shape D out of the
    dispatcher's scope. Both true is a contradiction — a live Shape-D path
    while the registry says there is none — and it fails here.
    """
    src = DISPATCH.read_text()
    assert "cvdp_jsonl_extract.py" not in src, (
        "a bench-named JSONL extractor is back in the dispatcher")
    for stem in ("cvdp", "rtllm", "verilogeval", "pyhdl"):
        assert f"{stem}_jsonl_extract" not in src, (
            f"bench-named extractor {stem}_jsonl_extract in the dispatcher")

    routes = _dispatcher_routes_shape_d()
    scope = _registry().get("_dispatcher_scope")
    declared_out = (isinstance(scope, dict)
                    and "D" not in (scope.get("implements_shapes") or []))
    assert routes or declared_out, (
        f"the dispatcher names no Shape-D extractor and the registry does not "
        f"declare Shape D out of scope — {_GENERAL_EXTRACTOR} is orphaned and "
        f"nothing says so; decide and record it in "
        f"BENCHMARK_REGISTRY.json:_dispatcher_scope")
    assert not (routes and declared_out), (
        f"the dispatcher routes Shape D through {_GENERAL_EXTRACTOR} while the "
        f"registry still declares Shape D out of its scope — the declaration "
        f"outlived the code; update _dispatcher_scope.implements_shapes")


def test_dispatch_falls_back_to_subdir_discovery_for_shape_d():
    """Dataset LAYOUT knowledge stays out of the dispatcher, and the shapes it
    accepts stay the shapes it implements.

    The original pin (`'work/PROMPT.txt' in src`) asserted the presence of the
    general subdir-discovery rglob. With no Shape-D verb there is no discovery
    to pin, and re-adding the string would pin a comment. What the pin was
    PROTECTING is still checkable and is checked here: a dataset laid out as
    per-problem directories must never be reached by a per-benchmark layout
    literal, and a benchmark whose registry shape the dispatcher does not
    implement must not be dispatchable.

    Fails if someone adds a Shape-D (or any unimplemented-shape) benchmark to
    `_BENCH_FORMAT` without either wiring the general path or moving the shape
    into `_dispatcher_scope.implements_shapes` — which the previous test then
    holds to the general extractor.

    A per-benchmark LAYOUT-literal scan was written here and REMOVED after
    measuring it: substring-matching every registry `layout` value against the
    dispatcher source reported three hits, and all three were artefacts of the
    instrument. `cvdp.layout.harness_subdir='score'` matches 77 unrelated
    occurrences of the word, and `module_name_strategy='always_TopModule'`
    matches `benchmark_dispatch.py:1908`, which READS that declared strategy
    from the registry and compares — the general pattern, not a leak. A check
    whose every finding is its own false positive is worse than no check.
    """
    reg = _registry()
    scope = reg.get("_dispatcher_scope")
    assert isinstance(scope, dict), (
        "BENCHMARK_REGISTRY.json no longer declares _dispatcher_scope — the "
        "set of shapes the dispatcher implements must be written down, not "
        "inferred from which verbs happen to exist")
    implemented = set(scope.get("implements_shapes") or [])
    assert implemented, "_dispatcher_scope.implements_shapes is empty"

    benchmarks = reg["benchmarks"]
    offenders = []
    for bench in _bench_format():
        entry = benchmarks.get(bench)
        assert entry is not None, (
            f"the dispatcher accepts {bench!r}, which the registry does not "
            f"describe at all")
        shapes = {s.strip() for s in str(entry.get("shape", "")).split("/")
                  if s.strip()}
        if not shapes & implemented:
            offenders.append((bench, entry.get("shape")))
    assert not offenders, (
        f"the dispatcher accepts benchmarks whose registry shape it does not "
        f"implement {offenders}; implemented={sorted(implemented)}")


# Executable Shape-D controls use the same public coordinator as Shapes B/C.
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(PROGRAMS));sys.path.insert(0, str(PROGRAMS / 'tests'))
import benchmark_dispatch as bd
import task_nature_route as tnr
import _runtime_pair_fixture as runtime_pair
import emit_attestation
import test_ai_first_route_handoff as ai_route_fixtures

_HIDDEN = 'SYNTHETIC_HIDDEN_HARNESS_SENTINEL'
_METADATA = 'SYNTHETIC_SCORER_METADATA_SENTINEL'
_RTL = 'module unit(input wire a, output wire y); assign y = a; endmodule\n'
_PROMPTS = {
    'spec_generation': 'Design a combinational module from this visible specification.',
    'completion': 'Complete the partial RTL module by filling the missing TODO implementation.',
    'functional_modification': 'Modify the supplied module to add an enable input.',
    'optimization': 'Optimize the supplied module to reduce logic area.',
    'debug': 'Fix the incorrect output inversion in the supplied module.',
}

def _current_d1_boundary(calls, d1_calls):
    """Reuse the v1.27.7 bound D1 producer in explicit subprocess mock scope.

    The real dispatcher still writes invocation receipts and validates the
    current report, source/material hashes, activation and launch snapshot.
    Product calls remain separate so their count and argv are asserted exactly.
    """
    typed_d1 = ai_route_fixtures._typed_d1_runner(d1_calls)

    def boundary(argv, *args, **kwargs):
        if argv[argv.index('--exit-step') + 1] == 'D1':
            return typed_d1(argv, *args, **kwargs)
        calls.append(list(argv))
        return SimpleNamespace(returncode=1, stdout='', stderr='')

    return boundary


def _shape_d_issue(tmp_path, monkeypatch, *, nature='spec_generation', count=1, bench='cvdp-open', supplied_rtl=_RTL, d1_calls=None):
    runtime_pair.assume_matching_runtime_pair(monkeypatch)
    dataset = tmp_path / 'dataset';dataset.mkdir();run = tmp_path / 'run'
    rows = []
    for i in range(count):
        context = {'docs/spec.md': 'Visible requirement: output y must equal input a.'}
        if nature != 'spec_generation':context['rtl/unit.sv'] = supplied_rtl
        rows.append({'id':f'neutral_{i}', 'prompt':_PROMPTS[nature], 'context':context,
            'harness':{'src/hidden.py':_HIDDEN}, 'score':_METADATA,
            'output':{'reference.sv':_METADATA}, 'categories':['optimization',_METADATA]})
    (dataset / 'synthetic.jsonl').write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
    calls = []
    if d1_calls is None:
        d1_calls = []
    monkeypatch.setattr(bd.subprocess, 'run', _current_d1_boundary(calls, d1_calls))
    assert bd.cmd_solve(bench,str(dataset),str(run),shape='D') == 2
    tasks = bd._read_jsonl(run / bd._ROUTE_WORKLIST)
    assert len(tasks) == count and calls == []
    return dataset,run,tasks,calls

def _shape_d_answer(task, *, nature=None, disposition='CONFIRM'):
    return {'schema':bd._AI_ROUTE_SCHEMA, 'id':task['id'], 'task_sha256':task['task_sha256'],
        'prompt_sha256':task['prompt_sha256'], 'source_sha256':task['public_original_input']['source_sha256'],
        'routing_contract_sha256':task['routing_contract_sha256'], 'disposition':disposition,
        'ai_nature':nature or task['program_proposal']['entry_nature'],
        'author':{'kind':'AI','model':'named-synthetic-route-reviewer'},
        'blind':{'oracle_accessed':False}, 'rationale':'The visible input determines this existing product task nature.',
        'prompt_evidence':[{'excerpt':Path(task['prompt_path']).read_text(),
            'supports':'The visible task selects '+(nature or task['program_proposal']['entry_nature'])+' as its product nature.'}]}

def _shape_d_write(task, answer):
    path=Path(task['response_path']);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(answer))

def test_shape_d_public_frontdoor_emits_pending_route(tmp_path,monkeypatch):
    """SHAPED-FRONTDOOR-RED / SHAPED-ROUTE-PENDING: exact public entry."""
    runtime_pair.assume_matching_runtime_pair(monkeypatch)
    dataset=tmp_path/'dataset';dataset.mkdir();run=tmp_path/'run'
    (dataset/'synthetic.jsonl').write_text(json.dumps({'id':'neutral_one',
        'prompt':'Design a combinational module from this visible specification.',
        'context':{'docs/spec.md':'Output y must equal input a.'},
        'harness':{'src/hidden.py':'SYNTHETIC_HIDDEN_SENTINEL'}})+'\n')
    calls=[]
    monkeypatch.setattr(bd._RunnerBudget,'run',lambda *_a:calls.append(1))
    monkeypatch.setattr(sys,'argv',['benchmark_dispatch.py','cvdp-open','--shape','D','--solve','--dataset',str(dataset),'--run',str(run)])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code==2
    tasks=bd._read_jsonl(run/bd._ROUTE_WORKLIST)
    assert calls==[]
    assert len(tasks)==1, f'SHAPED-FRONTDOOR-RED: public entry emitted {len(tasks)} pending routes; expected one'
    assert tasks[0]['allowed_natures']==['completion','debug','functional_modification','optimization','spec_generation']

def test_shape_d_hidden_boundary(tmp_path,monkeypatch):
    """SHAPED-HIDDEN-BOUNDARY: only public files reach task/project/argv."""
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch)
    task=tasks[0];project=Path(task['project']);scorer=run.parent/(run.name+'.shape_d_scorer')
    assert scorer.is_dir() and not scorer.is_relative_to(run)
    assert (scorer/task['id']/'score/src/hidden.py').read_text()==_HIDDEN
    assert _METADATA in (scorer/task['id']/'.row_meta.json').read_text()
    exposed=json.dumps(task)+'\n'+'\n'.join(str(p.relative_to(project))+':'+p.read_text() for p in project.rglob('*') if p.is_file())
    assert _HIDDEN not in exposed and _METADATA not in exposed and str(scorer) not in exposed
    assert not (project/'score').exists() and not (project/'.row_meta.json').exists()
    _shape_d_write(task,_shape_d_answer(task))
    bd.cmd_resume('cvdp-open',str(dataset),str(run))
    assert len(calls)==1
    assert calls[0][2]==str(project)
    assert str(scorer) not in json.dumps(calls) and str(dataset) not in json.dumps(calls)
    assert all(_HIDDEN not in p.read_text() and _METADATA not in p.read_text() for p in project.rglob('*') if p.is_file())

@pytest.mark.parametrize('mutation',['missing','prompt_hash','source_hash','contract_hash','nature','unattributed','oracle','ungrounded_override','clarification','prompt_bytes','source_bytes','contract_drift'])
def test_shape_d_route_refusals(tmp_path,monkeypatch,mutation):
    """SHAPED-ROUTE-REFUSALS: each invalid route launches zero runners."""
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch)
    task=tasks[0];answer=_shape_d_answer(task)
    if mutation.endswith('_hash'):answer[{'prompt_hash':'prompt_sha256','source_hash':'source_sha256','contract_hash':'routing_contract_sha256'}[mutation]]='0'*64
    if mutation=='nature':answer['ai_nature']='invented_product_class'
    if mutation=='unattributed':answer['author']['model']='unknown'
    if mutation=='oracle':answer['blind']['oracle_accessed']=True
    if mutation=='ungrounded_override':
        answer.update(disposition='OVERRIDE',ai_nature='debug',prompt_evidence=[],rationale='Ungrounded filler rationale. '*10)
    if mutation=='clarification':answer['disposition']='NEEDS_CLARIFICATION'
    if mutation!='missing':_shape_d_write(task,answer)
    if mutation=='prompt_bytes':Path(task['prompt_path']).write_text('Changed visible request.')
    if mutation=='source_bytes':
        (Path(task['project'])/'input/public_original/files/docs/spec.md').write_text('Changed public source bytes.')
    if mutation=='contract_drift':monkeypatch.setitem(tnr.NATURE_ENTRY['spec_generation'],'entry_step','2')
    assert bd.cmd_resume('cvdp-open',str(dataset),str(run))==2
    assert calls==[]
    assert json.loads((run/'solve_report.json').read_text())['routing_phase']=='PENDING'

@pytest.mark.parametrize('nature',list(_PROMPTS))
def test_shape_d_confirm_entry(tmp_path,monkeypatch,nature):
    """SHAPED-CONFIRM-ENTRY: selector never substitutes for task nature."""
    d1_calls = []
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch,nature=nature,d1_calls=d1_calls)
    task=tasks[0];project=Path(task['project'])
    assert task['program_proposal']['entry_nature']==nature
    assert task['allowed_natures']==sorted(tnr.NATURE_ENTRY)
    entry=tnr.NATURE_ENTRY[nature]['entry_step']
    if entry!='D1':
        # Historical provenance cannot authorize a fresh mid-flow launch.
        # This remains a software fixture, not a native Phase-1 measurement.
        docs=project/'phase1/generated_docs';docs.mkdir(parents=True)
        (docs/'L1.json').write_text('{"earlier_canonical_D1_fixture":true}\n')
        before=emit_attestation.phase1_provenance(project)
    _shape_d_write(task,_shape_d_answer(task))
    bd.cmd_resume('cvdp-open',str(dataset),str(run))
    assert len(calls)==1
    assert len(d1_calls)==1
    assert d1_calls[0] == bd._solver_argv(
        PROGRAMS/'vibe_ic_one_shot_runner.py',project,'D1','D1') + ['--no-dashboard']
    product_entry = tnr.NATURE_ENTRY[nature]['then'][0] if entry=='D1' else entry
    expected=bd._solver_argv(PROGRAMS/'vibe_ic_one_shot_runner.py',project,product_entry,tnr.EVIDENCE_EXIT[tnr.NATURE_ENTRY[nature]['default_evidence']]['exit_step'])
    assert calls[0]==expected
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    assert result['routing_verdict']['source']=='ai_confirmed' and result['accepted'] is False
    assert emit_attestation.phase1_provenance(project)['ran'] is True
    current = emit_attestation.phase1_provenance(project)
    assert result['phase1_frontdoor']['provenance']==current and result['phase1_frontdoor']['status']=='GENERATED'
    gate = result['phase1_frontdoor']['d1_gate']
    assert gate['current_call'] is True and gate['d1_provenance_sha256']==current['digest']
    assert result['phase1_frontdoor']['runner_invocation']['invocation_id']==gate['invocation_id']
    if entry!='D1':
        assert result['phase1_frontdoor']['provenance']!=before and result['phase1_frontdoor']['status']=='GENERATED'
        assert emit_attestation.phase1_provenance(project)==current and current!=before
    with pytest.raises(SystemExit):bd._require_program_first_ai_acceptance(run)

@pytest.mark.parametrize('nature',['debug','optimization'])
def test_shape_d_override_midflow(tmp_path,monkeypatch,nature):
    """SHAPED-OVERRIDE-MIDFLOW: grounded AI selects fixed existing steps."""
    original=tnr.classify_task_nature
    monkeypatch.setattr(tnr,'classify_task_nature',lambda *_a:{**original(_PROMPTS['spec_generation'],False,None),'source':'synthetic_misroute_control'})
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch,nature=nature)
    task=tasks[0];project=Path(task['project'])
    docs=project/'phase1/generated_docs';docs.mkdir(parents=True)
    (docs/'L1.json').write_text('{"earlier_canonical_D1_fixture":true}\n')
    before=emit_attestation.phase1_provenance(project)
    answer=_shape_d_answer(task,nature=nature,disposition='OVERRIDE')
    answer['entry_step']='37';answer['exit_step']='39' # AI cannot invent steps.
    _shape_d_write(task,answer)
    bd.cmd_resume('cvdp-open',str(dataset),str(run))
    assert len(calls)==1 and calls[0][calls[0].index('--entry-step')+1]=={'debug':'4','optimization':'2'}[nature]
    assert calls[0][calls[0].index('--exit-step')+1]=={'debug':'4','optimization':'9'}[nature]
    result=json.loads((run/'solve_report.json').read_text())['results'][0]
    assert result['routing_verdict']['source']=='ai_override'
    current=emit_attestation.phase1_provenance(project)
    assert result['phase1_frontdoor']['status']=='GENERATED'
    assert result['phase1_frontdoor']['provenance']==current and current!=before
    gate=result['phase1_frontdoor']['d1_gate']
    assert gate['current_call'] is True and gate['d1_provenance_sha256']==current['digest']
    assert result['phase1_frontdoor']['runner_invocation']['invocation_id']==gate['invocation_id']

@pytest.mark.parametrize('invalid',['missing','invalid'])
def test_shape_d_multirow_barrier(tmp_path,monkeypatch,invalid):
    """SHAPED-MULTIROW-BARRIER: one ready row cannot launch early."""
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch,count=2)
    _shape_d_write(tasks[0],_shape_d_answer(tasks[0]))
    if invalid=='invalid':
        bad=_shape_d_answer(tasks[1]);bad['source_sha256']='0'*64;_shape_d_write(tasks[1],bad)
    assert bd.cmd_resume('cvdp-open',str(dataset),str(run))==2 and calls==[]
    _shape_d_write(tasks[1],_shape_d_answer(tasks[1]))
    bd.cmd_resume('cvdp-open',str(dataset),str(run))
    assert len(calls)==2
    assert json.loads((run/'solve_report.json').read_text())['route_confirmed']==2

@pytest.mark.parametrize('bench',list(bd._BENCH_FORMAT))
def test_shape_d_selector_is_protocol_only(tmp_path,monkeypatch,bench):
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch,bench=bench)
    assert tasks[0]['program_proposal']['entry_nature']=='spec_generation'
    assert calls==[]
    assert json.loads((run/'.bench_config.json').read_text())['format']=='agentic'
    collected=[]
    collect=bd._collect_runner_result
    def observe(*args,**kwargs):
        collected.append(kwargs['required_top'])
        return collect(*args,**kwargs)
    monkeypatch.setattr(bd,'_collect_runner_result',observe)
    _shape_d_write(tasks[0],_shape_d_answer(tasks[0]))
    bd.cmd_resume(bench,str(dataset),str(run))
    assert len(calls)==1 and collected==[None]

def test_shape_d_score_refuses_nonagentic_fallthrough(tmp_path,monkeypatch):
    dataset,run,tasks,calls=_shape_d_issue(tmp_path,monkeypatch)
    assert bd._BENCH_FORMAT['cvdp-open']=='cvdp'
    with pytest.raises(SystemExit,match='SHAPED_SCORE_REFUSED'):
        bd.cmd_score('cvdp-open',str(run),str(dataset))
    assert calls==[]


def test_issued_format_valid_agentic_completion(tmp_path, monkeypatch):
    partial = 'module unit(input wire a, output wire y);\n// TODO: implement output\nendmodule\n'
    d1_calls = []
    dataset, run, tasks, calls = _shape_d_issue(
        tmp_path, monkeypatch, nature='completion', bench='verilogeval-human',
        supplied_rtl=partial, d1_calls=d1_calls)
    task = tasks[0]
    assert task['io_format'] == 'agentic'
    assert task['program_proposal']['entry_nature'] == 'completion'
    assert (Path(task['project']) / 'input/rtl/unit.sv').read_text() == partial
    collected = []
    collect = bd._collect_runner_result

    def observe(*args, **kwargs):
        collected.append((args[2], kwargs['required_top']))
        return collect(*args, **kwargs)

    monkeypatch.setattr(bd, '_collect_runner_result', observe)
    _shape_d_write(task, _shape_d_answer(task))
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    assert len(calls) == 1 and collected == [('agentic', None)]
    assert len(d1_calls) == 1
    assert json.loads((run / 'solve_report.json').read_text())['format'] == 'agentic'


def test_issued_format_valid_nonagentic_continuation(tmp_path, monkeypatch):
    runtime_pair.assume_matching_runtime_pair(monkeypatch)
    dataset = tmp_path / 'dataset'
    dataset.mkdir()
    (dataset / 'neutral_prompt.txt').write_text('Design a combinational output buffer named TopModule.')
    run = tmp_path / 'run'
    calls = []
    d1_calls = []
    monkeypatch.setattr(bd.subprocess, 'run', _current_d1_boundary(calls, d1_calls))
    assert bd.cmd_solve('verilogeval-human', str(dataset), str(run)) == 2
    task = bd._read_jsonl(run / bd._ROUTE_WORKLIST)[0]
    assert task['io_format'] == 'verilogeval' and calls == []
    collected = []
    collect = bd._collect_runner_result

    def observe(*args, **kwargs):
        collected.append((args[2], kwargs['required_top']))
        return collect(*args, **kwargs)

    monkeypatch.setattr(bd, '_collect_runner_result', observe)
    _shape_d_write(task, _shape_d_answer(task))
    assert bd.cmd_resume('verilogeval-human', str(dataset), str(run)) == 2
    assert len(calls) == 1 and collected == [('verilogeval', 'TopModule')]
    assert len(d1_calls) == 1
    assert json.loads((run / 'solve_report.json').read_text())['format'] == 'verilogeval'


@pytest.mark.parametrize('record', [
    'config_missing', 'solve_changed', 'solve_missing', 'task_changed',
    'task_missing', 'issue_changed', 'issue_missing', 'config_and_solve_changed',
])
def test_issued_format_binding_refuses_record_mutation(tmp_path, monkeypatch, record, capsys):
    dataset, run, tasks, calls = _shape_d_issue(tmp_path, monkeypatch, nature='completion')
    task = tasks[0]
    _shape_d_write(task, _shape_d_answer(task))
    if record.startswith('config') or record.startswith('solve'):
        names = (['.bench_config.json', 'solve_report.json']
                 if record == 'config_and_solve_changed' else
                 ['.bench_config.json' if record.startswith('config') else 'solve_report.json'])
        for name in names:
            path = run / name
            value = json.loads(path.read_text())
            if record.endswith('missing'):
                value.pop('format')
            else:
                value['format'] = 'cvdp'
            path.write_text(json.dumps(value))
    elif record.startswith('task'):
        if record.endswith('missing'):
            task.pop('io_format')
        else:
            task['io_format'] = 'cvdp'
        # A self-rehashed worklist/AI answer still cannot replace the issue.
        body = {k: v for k, v in task.items() if k != 'task_sha256'}
        task['task_sha256'] = bd._sha256_text(json.dumps(body, sort_keys=True))
        bd._write_jsonl(run / bd._ROUTE_WORKLIST, [task])
        _shape_d_write(task, _shape_d_answer(task))
    else:
        path = run / 'ai_route_tasks' / (task['task_sha256'] + '.json')
        if record.endswith('missing'):
            path.unlink()
        else:
            value = json.loads(path.read_text())
            value['io_format'] = 'cvdp'
            path.write_text(json.dumps(value))
    assert bd.cmd_resume('cvdp-open', str(dataset), str(run)) == 2
    assert calls == []
    assert 'IO_FORMAT_BINDING_REFUSED' in capsys.readouterr().err
    assert json.loads((run / 'solve_report.json').read_text())['routing_phase'] == 'PENDING'
