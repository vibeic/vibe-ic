#!/usr/bin/env python3
"""Focused public-consumer tests for ``eda_phase23_completion_audit``.

The wrapped program is a retained legacy diagnostic.  It must still execute
and report its own outcome, but the public MCP result must refuse to promote
that outcome to current Flow109 acceptance because this tool accepts neither a
current Flow109 manifest nor an execution window.
"""
import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest

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


def _call_actual_tool(tmp_path, *, programs_dir=None):
    env = {k: v for k, v in os.environ.items() if k != "VIBE_IC_PROGRAMS_DIR"}
    if programs_dir is not None:
        env["VIBE_IC_PROGRAMS_DIR"] = str(programs_dir)
    env["TMPDIR"] = str(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "eda_phase23_completion_audit",
                    "arguments": {"project_dir": str(proj)}}},
    ]
    p = subprocess.Popen(["node", str(INDEX_JS)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env, cwd=str(tmp_path))
    try:
        for m in msgs:
            p.stdin.write(json.dumps(m) + "\n")
        p.stdin.flush()
        reply, end = None, time.time() + 600
        while reply is None and time.time() < end:
            if not select.select([p.stdout], [], [], 1)[0]:
                continue
            line = p.stdout.readline()
            if not line:
                break
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == 2:
                reply = m
    finally:
        p.kill()
        p.wait()
    assert reply is not None, "the tool never answered"
    res = reply["result"]
    return json.loads("".join(c.get("text", "") for c in res["content"]))


@pytest.mark.skipif(
    shutil.which("node") is None
    or not (ROOT / "node_modules" / "@modelcontextprotocol" / "sdk").is_dir(),
    reason="NOT_MEASURED: node or mcp-eda/node_modules absent (run `npm ci`)",
)
def test_actual_consumer_runs_legacy_gate_but_refuses_current_flow109(tmp_path):
    """Ask the actual MCP TOOL for both its positive and refusal values.

    Positive control: the retained diagnostic really runs and names the
    canonical program.  Refusal control: without a current manifest/window,
    its measured legacy result cannot become current Flow109 acceptance.
    """
    out = _call_actual_tool(tmp_path)
    assert out.get("flow_id") == "109", out
    assert out.get("flow109_manifest") is None, out
    assert out.get("execution_window") is None, out
    assert out.get("status") == "NOT_MEASURED", out
    assert out.get("flow109_manifest") is None, out
    assert out.get("execution_window") is None, out
    assert out.get("flow109_acceptance") == "NOT_MEASURED", out
    assert out.get("current_flow_authority") is False, out
    assert out.get("audit_ran") is False, out
    assert out.get("phase23_complete") is False, out
    assert out.get("not_measured_class") == "FLOW109_MANIFEST_WINDOW_UNBOUND", out
    legacy = out.get("legacy_diagnostic")
    assert isinstance(legacy, dict), out
    assert legacy.get("status") == "MEASURED" and legacy.get("audit_ran") is True, out
    assert isinstance(legacy.get("legacy_phase23_complete"), bool), out
    gate = legacy.get("gate")
    assert gate, f"the diagnostic did not report its resolved gate: {out}"
    gate = Path(gate)
    assert gate.name == GATE_NAME and gate.is_file(), gate
    assert gate.resolve() == (ROOT.parent / "programs" / GATE_NAME).resolve(), (
        f"the tool resolved {gate}, not the plugin's own programs/ gate")


@pytest.mark.skipif(
    shutil.which("node") is None
    or not (ROOT / "node_modules" / "@modelcontextprotocol" / "sdk").is_dir(),
    reason="NOT_MEASURED: node or mcp-eda/node_modules absent (run `npm ci`)",
)
def test_actual_consumer_does_not_promote_legacy_pass(tmp_path):
    """A measured positive legacy result is still not current authority."""
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / GATE_NAME).write_text(
        "import json\n"
        "print(json.dumps({'summary': {'overall': 'PASS', 'certified': True}}))\n",
        encoding="utf-8",
    )
    out = _call_actual_tool(tmp_path, programs_dir=programs)
    assert out.get("status") == "NOT_MEASURED", out
    assert out.get("flow109_acceptance") == "NOT_MEASURED", out
    assert out.get("current_flow_authority") is False, out
    assert out.get("phase23_complete") is False, out
    legacy = out.get("legacy_diagnostic")
    assert legacy.get("status") == "MEASURED", out
    assert legacy.get("legacy_phase23_complete") is True, out
