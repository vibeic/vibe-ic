#!/usr/bin/env python3
"""Focused public-consumer tests for ``eda_phase23_completion_audit``.

The wrapped program is a retained legacy diagnostic.  It must still execute
and report its own outcome, but the public MCP result must refuse to promote
that outcome to current Flow109 acceptance because this tool accepts neither a
current Flow109 manifest nor an execution window.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "src" / "index.js"
GATE_NAME = "phase23_completion_self_audit_check.py"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"eda_phase23_completion_audit"')
    assert idx > 0
    return src[idx: idx + 4000]


def test_tool_registered():
    assert '"eda_phase23_completion_audit"' in INDEX_JS.read_text()


def test_project_dir_is_required():
    """Negative: project_dir must be required (no default). A default
    would let an agent forget to pass it and silently audit the wrong
    tree — exactly the failure mode CLAUDE.md rule #11 forbids."""
    w = _slice()
    i = w.find("project_dir")
    line = w[i: i + 250]
    assert ".default(" not in line, "project_dir must be required"


def test_dispatches_to_canonical_gate_script():
    """Positive: must run the canonical phase23_completion_self_audit_check.py
    via a subprocess — NOT a re-implementation. The hardening switched the runner
    from execSync(string) to _spawnSync(argv) so project_dir is never
    shell-parsed; either subprocess primitive satisfies the delegation
    contract."""
    w = _slice()
    assert "phase23_completion_self_audit_check.py" in w, (
        "tool must delegate to the canonical gate, not re-implement"
    )
    assert "_spawnSync" in w or "execSync" in w


def test_uses_json_output_mode():
    """Edge: must invoke gate with --json - so structured Overall/PASS/
    FAIL data round-trips back to the agent."""
    w = _slice()
    assert "--json" in w


def test_legacy_phase23_complete_field_derived_from_exit_code():
    """The retained legacy diagnostic still derives its own result from rc."""
    w = _slice()
    assert "legacy_phase23_complete" in w
    assert "exitCode === 0" in w or "exitCode == 0" in w


def test_description_refuses_current_flow_authority():
    """The inventory-facing description must not present the legacy gate as current."""
    w = _slice()
    assert "legacy diagnostic" in w.lower()
    assert "not current flow109 authority" in w.lower()
    assert "sole phase 2+3 acceptance criterion" not in w.lower()
