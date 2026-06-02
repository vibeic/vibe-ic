"""Tests for emitter_failure_mode_check (v1.6.38 anti-fabrication gate)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs.emitter_failure_mode_check import audit


def _mk_plugin(tmp_path: Path, code: str) -> Path:
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "module.py").write_text(textwrap.dedent(code))
    return root


def test_emit_with_pass_then_failure_branch_fails(tmp_path: Path) -> None:
    """The v1.6.37 escape pattern: tool failure ⇒ silent PASS."""
    root = _mk_plugin(tmp_path, """
        def emit_drc_signoff(project, gds, container):
            try:
                rc, out, err = run_klayout(gds)
            except OSError:
                out = ""
            viol_count = 0
            verdict = "PASS"
            return verdict, viol_count
    """)
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.function == "emit_drc_signoff" for f in findings)


def test_emit_with_explicit_fail_branch_still_flagged_without_annotation(tmp_path: Path) -> None:
    """The heuristic is intentionally conservative: a function with
    both `verdict = "PASS"` and an except / failure branch is flagged
    regardless of whether they're on different paths. Reviewer
    suppresses with the explicit annotation after auditing."""
    root = _mk_plugin(tmp_path, """
        def emit_drc_signoff(project, gds, container):
            try:
                rc, out, err = run_klayout(gds)
            except OSError:
                return "TOOL_FAILED", 0
            verdict = "PASS"
            return verdict, 0
    """)
    v, findings = audit(root)
    assert v == "FAIL", "conservative heuristic must flag without annotation"
    # With reviewed annotation it passes:
    annotated = _mk_plugin(tmp_path / "annotated", """
        # emitter-failure-mode: reviewed
        def emit_drc_signoff(project, gds, container):
            try:
                rc, out, err = run_klayout(gds)
            except OSError:
                return "TOOL_FAILED", 0
            verdict = "PASS"
            return verdict, 0
    """)
    v2, _ = audit(annotated)
    assert v2 == "PASS"


def test_reviewed_annotation_suppresses_finding(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, """
        # emitter-failure-mode: reviewed
        def emit_thing(project):
            try:
                run_tool()
            except Exception:
                pass
            verdict = "PASS"
            return verdict
    """)
    v, _ = audit(root, allow_annotation=True)
    assert v == "PASS"
    v_strict, findings_strict = audit(root, allow_annotation=False)
    assert v_strict == "FAIL"


def test_annotation_in_docstring_also_suppresses(tmp_path: Path) -> None:
    root = _mk_plugin(tmp_path, '''
        def emit_widget(project):
            """Build the widget. emitter-failure-mode: reviewed."""
            try:
                go()
            except OSError:
                pass
            verdict = "PASS"
            return verdict
    ''')
    v, _ = audit(root)
    assert v == "PASS"


def test_non_emitter_function_not_audited(tmp_path: Path) -> None:
    """Helper functions whose names don't start with `emit_` are
    out of scope — only emit_* / _emit_* are audited."""
    root = _mk_plugin(tmp_path, """
        def helper(project):
            try:
                go()
            except Exception:
                pass
            verdict = "PASS"
            return verdict
    """)
    v, findings = audit(root)
    assert v == "PASS"
    assert findings == []


def test_no_programs_dir_is_vacuous(tmp_path: Path) -> None:
    v, findings = audit(tmp_path / "empty")
    assert v == "VACUOUS_PASS"
    assert findings == []


def test_emit_dict_pattern_caught(tmp_path: Path) -> None:
    """Dict literal `{"verdict": "PASS", ...}` is also flagged."""
    root = _mk_plugin(tmp_path, """
        import json
        def emit_em_report(project):
            try:
                p = read_power()
            except OSError:
                p = None
            data = {"verdict": "PASS", "j_max": 2.0}
            return data
    """)
    v, findings = audit(root)
    assert v == "FAIL"
    assert any(f.function == "emit_em_report" for f in findings)
