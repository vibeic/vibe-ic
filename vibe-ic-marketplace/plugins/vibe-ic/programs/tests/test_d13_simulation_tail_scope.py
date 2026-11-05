"""Simulation-only publication preserves accepted upstream evidence, not row credit."""
import ast
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.environ.get('VIBEIC_D13_TAIL_PROGRAMS', str(Path(__file__).resolve().parents[1])))
import design_one_shot_runner as design
import execution_policy as policy


@pytest.fixture(autouse=True)
def ordinary_default(monkeypatch):
    request = {**policy.request(), 'mode': 'default'}
    monkeypatch.setattr(policy, 'request', lambda: request)
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
















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
