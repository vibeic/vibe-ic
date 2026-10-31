"""The real D1 contract follows complete native source projection, never file absence."""
from pathlib import Path
import json,sys,os
from argparse import Namespace
import pytest
PROGRAMS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROGRAMS));sys.path.insert(0,str(PROGRAMS/'tests'))
from test_phase1_converged_fact_graph import staged
import phase1_one_shot_runner as runner
import phase1_all_l_docs_present_check as layers
import phase1_coverage_report_present_check as coverage
import execution_backend_gates as gates
import execution_modes as em
import _flow_yaml
import flow109
import flow_compliance_check as compliance


@pytest.fixture(autouse=True)
def current_request_environment(monkeypatch):
    monkeypatch.setenv(flow109.CONTEXT_ENV, '')
    monkeypatch.setenv(flow109.ATTEMPT_ENV, '')


def current_nonphysical_request(tmp_path, graph):
    manifest = tmp_path / 'input/current-scope.json'
    manifest.write_text(json.dumps(graph.metadata['flow109_manifest']))
    args = Namespace(flow='109', flow109_manifest=manifest, flow109_plan_only=False,
                     execution_mode='default', entry_step='D01', exit_step='D01',
                     delivery_target='rtl', route=None)
    assert flow109.prepare_front_door(args, tmp_path) is None
    return manifest


def project(tmp_path):
    graph,path,data=staged(tmp_path)
    assert runner.step_ingest_render(tmp_path,'neutral_top').status=='PASS'
    report=tmp_path/'reports/audit/phase1/expert_parse_track.json';report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'verdict':'NOT_MEASURED','test_only':'contract fixture; no review/row acceptance'}))
    current_nonphysical_request(tmp_path, graph)
    return graph,path,data


def row():return next(r for r in _flow_yaml.load()['steps'] if str(r['id'])=='D1')


def contract(project):
    try:return 'BOUND',gates.contracts(project,row())
    except (ValueError,em.Refusal):return 'REFUSED',{}


def test_normal_contract_binds_every_declared_native_layer(tmp_path):
    project(tmp_path)
    state,bound=contract(tmp_path)
    assert state=='BOUND'
    assert 'phase1/generated_docs/L22_VERIFICATION_PLAN.json' in bound
    assert 'phase1/generated_docs/L3_CMD_PROTOCOL.json' not in bound
    assert len([k for k in bound if k.startswith('phase1/generated_docs/')])==10


def test_existing_layer_and_coverage_consumers_measure_native_facts(tmp_path):
    project(tmp_path)
    assert layers._check(tmp_path)[0]==0
    assert coverage._check(tmp_path)[0]==0


@pytest.mark.parametrize('damage',['missing_layer','extra_port','changed_requirement','missing_required_fact','duplicate_key','invalid_selection'])
def test_incomplete_or_changed_source_projection_is_still_refused(tmp_path,damage):
    graph,path,_=project(tmp_path)
    assert contract(tmp_path)[0]=='BOUND'
    generated=tmp_path/'phase1/generated_docs'
    if damage=='missing_layer':(generated/'L22_VERIFICATION_PLAN.json').unlink()
    elif damage in ('extra_port','duplicate_key'):
        p=generated/'L9_INTEGRATION_SPEC.json';doc=json.loads(p.read_text())
        if damage=='extra_port':
            doc['top_ports'].append({'name':'foreign','direction':'output','width':1});p.write_text(json.dumps(doc))
        else:p.write_text('{"top_ports":[],"top_ports":'+json.dumps(doc['top_ports'])+'}')
    elif damage=='changed_requirement':
        p=generated/'L2_FRS.json';doc=json.loads(p.read_text());doc['requirements'][0]['text']='different behavior';p.write_text(json.dumps(doc))
    elif damage=='missing_required_fact':
        graph.facts.remove(graph.by_path('L2.functional_description'));graph.save(path)
    else:
        graph.metadata['flow109_manifest']['features']={'physical':False};graph.save(path)
    assert contract(tmp_path)[0]=='REFUSED'
    assert layers._check(tmp_path)[0]==1
    assert coverage._check(tmp_path)[0]==1


@pytest.mark.parametrize('selection',['physical','unknown','raw'])
def test_nonselected_inputs_retain_legacy_full_contract(tmp_path,selection):
    graph,path,_=project(tmp_path)
    registry=json.loads((PROGRAMS.parent/'flow/flow109.json').read_text())
    if selection=='physical':
        graph.metadata['flow109_manifest']={'features':next(r['features'] for r in registry['reference_profiles'] if r['features']['physical'])};graph.save(path)
    elif selection=='unknown':graph.metadata={};graph.save(path)
    else:path.unlink()
    assert contract(tmp_path)[0]=='REFUSED'


def test_matching_current_nonphysical_scope_keeps_native_projection(tmp_path):
    project(tmp_path)
    assert flow109.active_rtl_scope(tmp_path)['project'] == str(tmp_path.resolve())
    assert contract(tmp_path)[0] == 'BOUND'
    assert layers._check(tmp_path)[0] == 0
    assert coverage._check(tmp_path)[0] == 0
    assert compliance._output_not_owed(
        tmp_path, row(), 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json')


def test_current_physical_request_cannot_excuse_old_nonphysical_projection(tmp_path):
    graph, _, _ = project(tmp_path)
    assert graph.metadata['flow109_manifest']['features']['physical'] is False
    features = next(r['features'] for r in flow109.load_registry()['reference_profiles']
                    if r['features']['physical'])
    context = flow109.execution_context(flow109.resolve_plan(features), 'D01', 'D01')
    request = tmp_path / 'reports/flow109/requests' / (context['context_sha256'] + '.json')
    request.write_text(json.dumps(context))
    os.environ[flow109.CONTEXT_ENV] = str(request)
    assert context['features']['physical'] is True
    assert contract(tmp_path)[0] == 'REFUSED'
    assert layers._check(tmp_path)[0] == 1
    assert coverage._check(tmp_path)[0] == 1
    assert compliance._output_not_owed(
        tmp_path, row(), 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json') is None


@pytest.mark.parametrize('damage', ['missing_context', 'unbound_context', 'foreign_request',
                                   'changed_manifest', 'changed_original', 'changed_issuer'])
def test_unproven_current_scope_retains_strict_outputs(tmp_path, damage):
    project(tmp_path)
    request = Path(os.environ[flow109.CONTEXT_ENV])
    context = json.loads(request.read_text())
    if damage == 'missing_context':
        os.environ.pop(flow109.CONTEXT_ENV)
    elif damage == 'foreign_request':
        foreign = tmp_path / 'input/foreign-request.json'
        foreign.write_bytes(request.read_bytes())
        os.environ[flow109.CONTEXT_ENV] = str(foreign)
    elif damage == 'changed_manifest':
        p = tmp_path / 'input/current-scope.json'
        p.write_text(p.read_text() + '\n')
    elif damage == 'changed_original':
        p = tmp_path / 'input/docs/design.sv'
        p.write_text(p.read_text() + '// original bytes changed\n')
    else:
        if damage == 'unbound_context':
            context.pop('rtl_scope')
        else:
            context['rtl_scope']['issuer_sources']['phase1_one_shot_runner.py'] = '0' * 64
        context['context_sha256'] = flow109.digest(
            {k: v for k, v in context.items() if k != 'context_sha256'})
        request = request.parent / (context['context_sha256'] + '.json')
        request.write_text(json.dumps(context))
        os.environ[flow109.CONTEXT_ENV] = str(request)
    assert contract(tmp_path)[0] == 'REFUSED'
    assert layers._check(tmp_path)[0] == 1
    assert coverage._check(tmp_path)[0] == 1
    assert compliance._output_not_owed(
        tmp_path, row(), 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json') is None
