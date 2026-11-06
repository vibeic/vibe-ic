"""Regression tests for the Phase-2 Step-7 producer seam."""
from __future__ import annotations

import ast
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))























def test_phase3_step9_consumes_default_fallback_marker():
    """Phase-3 synth must have an explicit one-shot producer bypass."""
    import phase3_one_shot_runner as P3
    source = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(source)
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "step_synth")
    segment = ast.get_source_segment(source, fn)
    assert segment is not None
    assert "_fallback_handoff" in segment
    assert P3.step_synth.__name__ == "step_synth"
    retry = [node for node in ast.walk(fn)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "step_synth"]
    assert any(any(kw.arg == "_fallback_handoff" for kw in call.keywords)
               for call in retry)
