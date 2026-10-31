"""Simulation-only publication preserves accepted upstream evidence, not row credit."""
import ast
import inspect
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.environ.get('VIBEIC_D13_TAIL_PROGRAMS', str(Path(__file__).resolve().parents[1])))
import design_one_shot_runner as design
import execution_backend_gates as gates
import execution_policy as policy
import step_output_collector as versions


@pytest.fixture(autouse=True)
def ordinary_default(monkeypatch):
    request = {**policy.request(), 'mode': 'default'}
    monkeypatch.setattr(policy, 'request', lambda: request)
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def write(project, rel, content):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def publish(project, plan):
    # Execute the same existing completion on base as well as repaired source.
    kwargs = {'emit_formal': False}
    if 'simulation_only' in inspect.signature(design._complete_phase2_frontend).parameters:
        kwargs['simulation_only'] = True
    return design._complete_phase2_frontend(project, plan, 'top', **kwargs)


def refuse_consumer(monkeypatch):
    seen = []
    def consume(project, row):
        seen.append(str(row['id']))
        return {'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'}, 'ledger': []}
    monkeypatch.setattr(gates, 'evaluate', consume)
    return seen


def plan(project, status='PASS', log=True):
    write(project, 'phase2/stage1/rtl/top.v', 'module top(input clk); endmodule\n')
    if log:
        write(project, 'phase2/stage1/sim/reference/ref_tb.log', 'TEST multiplication PASS\n')
    return [design.StepResult('rtl_validate', 'PASS', 0, 'original input', extras={'input_contract': 'original'}),
            design.StepResult('reference_tb', status, 0, 'actual reference result')]


def test_simulation_tail_preserves_upstream_and_only_consumes_simulation(tmp_path, monkeypatch):
    rows = plan(tmp_path)
    upstream = ['reports/phase2/cdc/crossing.json', 'reports/phase2/cdc/reset_dep.json',
                'reports/phase2/lint/rtl_hygiene.json', 'reports/phase2/fpga/on_board_pass.json',
                'phase2/stage1/formal/results.json']
    before = {rel: write(tmp_path, rel, 'immutable accepted prior evidence\n').read_bytes() for rel in upstream}
    original = Path.write_text
    def protected_write(path, *args, **kwargs):
        if str(path.relative_to(tmp_path)) in upstream:
            raise OSError(30, 'read-only accepted upstream evidence', str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', protected_write)
    seen = refuse_consumer(monkeypatch)
    result = publish(tmp_path, rows)
    assert result.status == 'PASS'  # Manifest publication is separate from acceptance.
    assert seen == ['4']
    assert before == {rel: (tmp_path / rel).read_bytes() for rel in upstream}
    sim = json.loads((tmp_path / 'sim/results.xml').read_text())
    assert sim['verdict'] == 'PASS' and sim['evidence'].endswith('ref_tb.log')
    entry = next(r for r in versions._read_index(tmp_path)['steps'] if r['id'] == '4')
    record = json.loads((tmp_path / 'steps' / entry['folder'] / 'outputs.json').read_text())
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '4') is None


@pytest.mark.parametrize('status,log', [('FAIL', True), ('PASS', False)])
def test_simulation_tail_does_not_promote_failed_or_missing_native_evidence(tmp_path, monkeypatch, status, log):
    rows = plan(tmp_path, status, log)
    seen = refuse_consumer(monkeypatch)
    publish(tmp_path, rows)
    sim = json.loads((tmp_path / 'sim/results.xml').read_text())
    cov = json.loads((tmp_path / 'reports/phase2/coverage/coverage_actual.json').read_text())
    assert sim['verdict'] == 'SKIP'
    assert cov['verdict'] == 'SKIPPED-CONDITION'
    assert seen == ['4'] and versions.latest_pass(tmp_path, '4') is None


def test_simulation_tail_does_not_dispatch_other_producers(tmp_path, monkeypatch):
    rows = plan(tmp_path)
    import flow_declared_producer_run as declared
    def forbidden(*args, **kwargs):
        pytest.fail('simulation window cannot dispatch upstream/formal/FPGA producers')
    monkeypatch.setattr(design, 'step_emit_phase2_manifests', forbidden)
    monkeypatch.setattr(declared, 'run_for_step', forbidden)
    refuse_consumer(monkeypatch)
    publish(tmp_path, rows)


def test_normal_caller_derives_simulation_scope_from_existing_window():
    tree = ast.parse(Path(design.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    assignment = next(n for n in ast.walk(main) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == '_simulation_only_frontend' for t in n.targets))
    expression = ast.unparse(assignment.value)
    assert "_step_requested('4')" in expression
    assert "('2', '3')" in expression and 'not any' in expression
    call = next(n for n in ast.walk(main) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == '_complete_phase2_frontend')
    assert any(k.arg == 'simulation_only' and isinstance(k.value, ast.Name)
               and k.value.id == '_simulation_only_frontend' for k in call.keywords)
