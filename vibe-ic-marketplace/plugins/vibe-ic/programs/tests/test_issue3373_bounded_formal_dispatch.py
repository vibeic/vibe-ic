"""#3373: frontend manifest emission obeys the selected Step 5 window."""
from __future__ import annotations

import ast
import sys
from pathlib import Path



PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


RUNNER_SOURCE = PROGRAMS / "design_one_shot_runner.py"


def _main_node():
    tree = ast.parse(RUNNER_SOURCE.read_text())
    return next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")






def test_main_passes_step5_ownership_to_the_manifest_emitter():
    calls = [node for node in ast.walk(_main_node())
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "_complete_phase2_frontend"]
    assert len(calls) == 1
    keyword = next((kw.value for kw in calls[0].keywords
                    if kw.arg == "emit_formal"), None)
    assert isinstance(keyword, ast.Call)
    assert isinstance(keyword.func, ast.Name)
    assert keyword.func.id == "_step_requested"
    assert len(keyword.args) == 1
    assert isinstance(keyword.args[0], ast.Constant)
    assert keyword.args[0].value == "5"
