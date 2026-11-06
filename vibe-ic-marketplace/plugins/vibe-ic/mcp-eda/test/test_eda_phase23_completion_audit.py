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
