"""Neutral software controls. No dataset, EDA, RTL answer or native PASS."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest
import benchmark_dispatch as dispatch
import flow109

PROGRAMS = Path(__file__).resolve().parents[1]


def public_handoff(tmp_path, exit_step="D09"):
    project = tmp_path / 'project'
    (project / 'input').mkdir(parents=True, exist_ok=True)
    (project / 'input/phase1_prompt.md').write_text(
        'Deliver only a soft-IP RTL module. Inputs a and b drive q as their '
        'bitwise conjunction. Request RTL authoring only; no analog, netlist, '
        'hardware or physical delivery.\n')
    features = {name: False for name in
                set(flow109.load_registry()['predicate_names'])
                - set(flow109.load_registry()['predicate_definitions']) - {'always'}}
    features.update(rtl_only=True, has_digital=True)
    manifest = project / 'input/flow109-manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    argv = [sys.executable, str(PROGRAMS / 'vibe_ic_one_shot_runner.py'), str(project),
            '--flow109-manifest', str(manifest), '--entry-step', 'D09', '--exit-step', exit_step,
            '--route', 'ip', '--rtl-input', 'original', '--execution-mode', 'default',
            '--skip-phase1', '--skip-phase3', '--skip-analog', '--skip-hardware', '--no-dashboard']
    budget = dispatch._RunnerBudget(1, 1, 0)
    budget._env = {k: v for k, v in os.environ.items() if not k.startswith((
        'VIBEIC_FLOW109', 'VIBEIC_RUNNER_', 'VIBEIC_PARENT_RUNNER_', 'VIBE_IC_RUNNER_LOCK'))}
    budget.timeout_s = 90
    process = budget.run(argv)
    return project, process, argv


@pytest.fixture(scope='module')
def measured_handoffs(tmp_path_factory):
    return {exit_step: public_handoff(tmp_path_factory.mktemp('public-' + exit_step), exit_step)
            for exit_step in ('D09', 'D11')}


@pytest.mark.parametrize("exit_step,depth", [("D09", 1), ("D11", 2)])
def test_actual_default_public_generation_handoff_is_collectable(measured_handoffs, exit_step, depth):
    project, process, argv = measured_handoffs[exit_step]
    assert process.error is None, process.stderr
    handoff = dispatch._rtl_gen_waive(project)
    assert handoff is not None, process.stdout + process.stderr
    assert handoff['fallback_skill'] == 'spec-to-rtl'
    assert process.invocation['source_before'] == process.invocation['source_after']
    phase2 = json.loads((project / 'reports/orchestrator/phase2_one_shot.json').read_bytes())
    outer = json.loads((project / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert phase2['runner_binding']['invocation_id'] != process.invocation_id
    assert outer['runner_binding']['invocation_id'] == process.invocation_id
    got = dispatch._collect_runner_result(process, argv, 'neutral', 'neutral', project)
    assert got['runner_diagnostics']['status'] == 'REPORTS_AVAILABLE', got
    assert got['ok'] is False and 'completion' not in got
    assert got['reason'].startswith('no RTL at ')
    publication = outer
    for level in range(depth):
        refs = publication['runner_binding']['child_invocations']
        assert len(refs) == 1
        completion = json.loads((project / refs[0]['path']).read_bytes())
        launch = json.loads((project / completion['launch']['path']).read_bytes())
        assert launch['parent_invocation']['invocation_id'] == publication['runner_binding']['invocation_id']
        if level < depth - 1:
            publication = json.loads((project / completion['owner_reports']['vibe_ic_one_shot.json']['path']).read_bytes())
        else:
            assert launch['child_invocation']['invocation_id'] == phase2['runner_binding']['invocation_id']
            assert launch['material_before'] == completion['material_after'] == process.invocation['material_after']
    assert publication['d09_finalization']['verdict'] == 'NOT_MEASURED'
    assert not process.invocation['material_after']['output_rtl']


def _rewrite(path, document):
    path.write_text(json.dumps(document))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('kind', [
    'intermediate_window', 'intermediate_project', 'intermediate_source',
    'intermediate_producer', 'intermediate_material', 'intermediate_parent',
    'descendant_selection', 'grandchild_parent', 'grandchild_window',
    'grandchild_argv', 'grandchild_time', 'grandchild_report_swap',
    'grandchild_report_path', 'detached_grandchild', 'cycle', 'owner_request',
    'owner_request_parent', 'owner_request_alias', 'owner_window',
])
def test_fixture_rehashed_nested_public_lineage_cannot_graft_another_owner(measured_handoffs, kind):
    project, process, _ = measured_handoffs['D11']
    outer_path = project / 'reports/orchestrator/vibe_ic_one_shot.json'
    outer = json.loads(outer_path.read_bytes())
    top_ref = outer['runner_binding']['child_invocations'][0]
    top_path = project / top_ref['path']
    top = json.loads(top_path.read_bytes())
    top_launch_path = project / top['launch']['path']
    top_launch = json.loads(top_launch_path.read_bytes())
    intermediate_ref = top['owner_reports']['vibe_ic_one_shot.json']
    intermediate_path = project / intermediate_ref['path']
    intermediate = json.loads(intermediate_path.read_bytes())
    leaf_ref = intermediate['runner_binding']['child_invocations'][0]
    leaf_path = project / leaf_ref['path']
    leaf = json.loads(leaf_path.read_bytes())
    leaf_launch_path = project / leaf['launch']['path']
    leaf_launch = json.loads(leaf_launch_path.read_bytes())
    owner_path = project / leaf['owner_reports']['phase2_one_shot.json']['path']
    owner = json.loads(owner_path.read_bytes())
    request_path = project / top_launch['owner_launch']['path']
    request = json.loads(request_path.read_bytes())
    originals = {path: path.read_bytes() for path in (
        outer_path, top_path, top_launch_path, intermediate_path, leaf_path,
        leaf_launch_path, owner_path, request_path)}
    try:
        owned = intermediate['runner_binding']
        if kind == 'intermediate_window':
            intermediate['declared_window'] = {'entry_step': 'D09', 'exit_step': 'D11'}
        elif kind == 'intermediate_project':
            intermediate['project'] = str(project.parent / 'foreign-project')
        elif kind == 'intermediate_source':
            owned['source']['consumer']['sha256'] = '0' * 64
        elif kind == 'intermediate_producer':
            path = Path(dispatch.__file__)
            owned['producer'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        elif kind == 'intermediate_material':
            owned['material']['input'] = {}
        elif kind == 'intermediate_parent':
            owned['parent_invocation']['invocation_id'] = '0' * 32
        elif kind == 'descendant_selection':
            features = dict(leaf_launch['selection']['features'], requires_security=True)
            leaf_launch['selection'] = flow109.execution_context(flow109.resolve_plan(features), 'D09', 'D09',
                rtl_scope=leaf_launch['selection'].get('rtl_scope'))
        elif kind == 'grandchild_parent':
            leaf_launch['parent_invocation'] = top_launch['parent_invocation']
        elif kind == 'grandchild_window':
            leaf_launch['selection'] = flow109.execution_context(flow109.resolve_plan(
                leaf_launch['selection']['features']), 'D11', 'D11',
                rtl_scope=leaf_launch['selection'].get('rtl_scope'))
        elif kind == 'grandchild_argv':
            leaf['child_invocation']['argv'].append('--fixture-replacement')
        elif kind == 'grandchild_time':
            leaf_launch['started_ns'] = top_launch['started_ns'] - 1
        elif kind == 'grandchild_report_swap':
            owner['fixture_control'] = 'Substituted immutable owner bytes.'
        elif kind == 'grandchild_report_path':
            leaf['owner_reports']['phase2_one_shot.json']['path'] = 'reports/orchestrator/phase2_one_shot.json'
        elif kind == 'detached_grandchild':
            owned['child_invocations'] = []
        elif kind == 'cycle':
            owned['child_invocations'] = [top_ref]
        elif kind == 'owner_request':
            request['child_context'] = flow109.component_context(request['parent_context'], requested_step='D11')
        elif kind == 'owner_request_alias':
            top_launch['owner_launch']['path'] = top_launch['owner_launch']['path'].replace('/owner-', '/./owner-')
        elif kind == 'owner_request_parent':
            request['parent_context']['requested_exit'] = 'D10'
        elif kind == 'owner_window':
            top_launch['selection'] = flow109.execution_context(flow109.resolve_plan(
                top_launch['selection']['features']), 'D09', 'D10',
                rtl_scope=top_launch['selection'].get('rtl_scope'))
        top_launch['owner_launch']['sha256'] = _rewrite(request_path, request)
        leaf['owner_reports']['phase2_one_shot.json']['sha256'] = _rewrite(owner_path, owner)
        leaf['launch']['sha256'] = _rewrite(leaf_launch_path, leaf_launch)
        leaf_ref['sha256'] = _rewrite(leaf_path, leaf)
        intermediate_ref['sha256'] = _rewrite(intermediate_path, intermediate)
        top['reports_after']['vibe_ic_one_shot.json']['sha256'] = intermediate_ref['sha256']
        top['reports_after']['vibe_ic_one_shot.json']['runner_binding'] = intermediate['runner_binding']
        top['launch']['sha256'] = _rewrite(top_launch_path, top_launch)
        top_ref['sha256'] = _rewrite(top_path, top)
        _rewrite(outer_path, outer)
        receipt = copy.deepcopy(process.invocation)
        receipt['reports_after'] = dispatch._runner_report_snapshot(project)
        assert dispatch._runner_report_binding_reason(receipt, require_phase2=True).startswith(
            'RUNNER_REPORT_UNBOUND:')
    finally:
        for path, raw in originals.items():
            path.write_bytes(raw)
