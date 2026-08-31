"""The common router/runner cannot branch on benchmark or problem identity."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "benchmark"))

import benchmark_entry_surface_check as surface  # noqa: E402


def test_shipped_general_core_has_no_benchmark_selector():
    report = surface.audit(PLUGIN)
    assert report["verdict"] == "PASS", report


def test_selector_audit_recognizes_the_forbidden_shape():
    tree = ast.parse("if bench == 'cvdp-open':\n    solve_special()\n")
    test = next(node.test for node in ast.walk(tree) if isinstance(node, ast.If))
    assert surface._selector_literals(test) == ["cvdp-open"]
