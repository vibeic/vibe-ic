#!/usr/bin/env python3
"""Wave 75 — tests for mcp_server_health_check (v0.113 tool).

The health probe MUST stay cheap (no docker, no execSync, no FS I/O)
so an agent can call it inside a tight loop to detect MCP liveness.

Positive: returns alive + uptime fields.
Negative: takes no required arguments (empty schema).
Edge   : node version + server PID present so disconnects are diagnosable.
SKIP   : never skips — must always answer; that's the whole point.
"""
from pathlib import Path

INDEX_JS = Path(__file__).resolve().parent.parent / "src" / "index.js"


def _slice():
    src = INDEX_JS.read_text()
    idx = src.find('"mcp_server_health_check"')
    assert idx > 0
    return src[idx: idx + 2000]


def test_tool_registered():
    assert '"mcp_server_health_check"' in INDEX_JS.read_text()


def test_empty_input_schema():
    """Negative: schema must be {} — agents shouldn't have to pass
    anything to ping the server."""
    w = _slice()
    # The tool registers with `{}` between description and async handler.
    # Look for the canonical '"...",\n  {},\n  async' pattern.
    assert "{}" in w[:600], "health check input schema must be empty {}"


def test_returns_alive_status():
    """Positive: response payload must include status:'alive'."""
    w = _slice()
    assert '"alive"' in w, "must report status:'alive'"


def test_returns_diagnostic_fields():
    """Edge: uptime + node version + PID so a stuck or wrong-version
    server is diagnosable without restarting."""
    w = _slice()
    for field in ("uptime_ms", "node_version", "server_pid", "probe_timestamp"):
        assert field in w, f"diagnostic field {field} missing"


def test_no_docker_or_execsync_in_health_check():
    """SKIP-equivalent: this must never block on docker / execSync /
    fs (would defeat the purpose). A regression that adds them turns
    the health check into a heavyweight probe."""
    w = _slice()
    assert "dockerExec" not in w, "health check must not call docker"
    assert "execSync" not in w, "health check must not call execSync"
    assert "readFileSync" not in w, "health check must not touch FS"


def test_uptime_computed_from_start_constant():
    """Positive: uptime is computed from a module-scope _mcpStartTime,
    not Date.now() - Date.now() which would always be 0."""
    src = INDEX_JS.read_text()
    assert "const _mcpStartTime" in src
    w = _slice()
    assert "Date.now() - _mcpStartTime" in w
