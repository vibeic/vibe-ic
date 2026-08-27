#!/usr/bin/env python3
"""A `docker exec` timeout must stop the TOOL, not just the client.

MEASURED 2026-08-19 on a fleet host, with the shipped image:

    $ timeout 4 docker exec vibeic-eda bash -c 'sleep 90 & wait'; echo $?
    124
    $ docker exec vibeic-eda pgrep -cf '[s]leep 90'
    2            <-- still running

Killing a `docker exec` CLIENT does not stop the process it started in the
container. So every timeout this server has ever reported was a client-side
give-up: the caller was told "command timed out after 300000ms", the agent
moved on, and the tool kept running with nothing left watching it. That is how
a yosys reached 113 GB on a 125 GB host AFTER its caller had given up, and the
machine's desktop session was OOM-killed by the kernel.

Moving the timeout inside the container fixes it, measured the same way:

    $ docker exec vibeic-eda timeout -k 5 4 bash -c 'sleep 90 & wait'; echo $?
    124
    $ docker exec vibeic-eda pgrep -cf '[s]leep 90'
    0            <-- gone

The behavioural tests below execute the SHIPPED `dockerExec` body -- sliced out
of src/index.js, not retyped -- against a recording stub, so they check the
argv that is actually issued rather than a restatement of it.
"""
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
INDEX_JS = MCP_ROOT / "src" / "index.js"
SRC = INDEX_JS.read_text()

_NODE = shutil.which("node")
_DOCKER = shutil.which("docker")
_CONTAINER = "vibeic-eda"


def _slice_function(name: str) -> str:
    """The shipped source of one top-level function, brace-matched."""
    start = SRC.index(f"function {name}(")
    depth, i, seen = 0, start, False
    while i < len(SRC):
        if SRC[i] == "{":
            depth += 1
            seen = True
        elif SRC[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return SRC[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces slicing {name}")


_HARNESS = r"""
const CONTAINER = "vibeic-eda";
const _UNREACHABLE_HINTS = ["permission denied"];
const _INNER_TIMEOUT_GRACE_MS = 20000;
const SCENARIO = JSON.parse(process.argv[2]);

const calls = [];
let _now = 1_000_000;
const _realNow = Date.now;
Date.now = () => _now;

function _probeDocker() { return { ok: true }; }
function _invalidateDockerProbe() {}
function _containerHasTimeout() { return SCENARIO.hasTimeout; }
function _spawnSync(bin, argv, opts) {
  calls.push({ bin, argv, opts: { timeout: opts.timeout } });
  _now += SCENARIO.elapsedMs;          // simulate the wall clock advancing
  return {
    stdout: SCENARIO.stdout ?? "",
    stderr: SCENARIO.stderr ?? "",
    status: SCENARIO.status,
    signal: null,
    error: null,
  };
}

__DOCKER_EXEC__

const result = dockerExec(SCENARIO.cmd ?? "yosys -p synth", SCENARIO.timeoutMs ?? 300000);
Date.now = _realNow;
console.log(JSON.stringify({ calls, result }));
"""


def _drive(tmp_path, **scenario):
    scenario.setdefault("hasTimeout", True)
    scenario.setdefault("elapsedMs", 5)
    scenario.setdefault("status", 0)
    script = tmp_path / "drive.mjs"
    script.write_text(_HARNESS.replace("__DOCKER_EXEC__", _slice_function("dockerExec")))
    proc = subprocess.run(
        [_NODE, str(script), json.dumps(scenario)],
        capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ── behavioural: the argv that is actually issued ───────────────────────────

@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_the_timeout_is_handed_to_the_container_not_kept_on_the_client(tmp_path):
    got = _drive(tmp_path, timeoutMs=300_000)
    argv = got["calls"][0]["argv"]
    assert argv[:2] == ["exec", _CONTAINER]
    assert "timeout" in argv, (
        f"the exec carries no in-container timeout, so killing the client "
        f"leaves the tool running: {argv}")
    t = argv.index("timeout")
    assert argv[t + 1] == "-k", "no KILL escalation: a tool that ignores TERM never dies"
    assert argv[t + 3] == "300", "the in-container limit is not the caller's limit"
    # The command still reaches bash as ONE argv element -- the injection
    # hardening of v0.114.6 must survive this change.
    assert argv[-2:] == ["bash", "-c"] or argv[-3:-1] == ["bash", "-c"], argv
    assert argv[-1] == "yosys -p synth"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_the_host_side_timeout_is_only_a_backstop(tmp_path):
    """It must be LONGER than the inner one, or it wins the race and we are
    back to killing the client and orphaning the tool."""
    got = _drive(tmp_path, timeoutMs=300_000)
    assert got["calls"][0]["opts"]["timeout"] > 300_000


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_an_expired_command_is_reported_as_a_timeout(tmp_path):
    got = _drive(tmp_path, timeoutMs=10_000, status=124, elapsedMs=10_500,
                 stdout="partial log\n")
    res = got["result"]
    assert res["success"] is False
    assert "timed out" in res["error"]
    assert _CONTAINER in res["error"], (
        "the message must say WHERE the kill happened; the old one described a "
        "client-side give-up and read the same")
    assert "partial log" in res["output"], (
        "the tool's own output before the kill is the only diagnostic there is")


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_a_tool_that_merely_exits_124_is_not_relabelled_a_timeout(tmp_path):
    """124 is `timeout`'s code, but nothing stops a tool from using it. The
    elapsed clock is what tells them apart -- an exit-code-only rule would
    silently convert real tool failures into 'timed out'."""
    got = _drive(tmp_path, timeoutMs=300_000, status=124, elapsedMs=200,
                 stderr="ERROR: syntax error in foo.v\n")
    res = got["result"]
    assert res["success"] is False
    assert "timed out" not in (res["error"] or "")
    assert "syntax error" in res["error"]


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_sigkill_escalation_is_still_a_timeout(tmp_path):
    got = _drive(tmp_path, timeoutMs=10_000, status=137, elapsedMs=20_100)
    assert "timed out" in got["result"]["error"]
    assert "SIGKILL" in got["result"]["error"]


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_an_image_without_timeout_degrades_instead_of_failing_everything(tmp_path):
    """EDA_CONTAINER is user-overridable. An image with no coreutils `timeout`
    must fall back to the old exec, not fail every command with 127."""
    got = _drive(tmp_path, hasTimeout=False)
    argv = got["calls"][0]["argv"]
    assert "timeout" not in argv
    assert argv == ["exec", _CONTAINER, "bash", "-c", "yosys -p synth"]
    assert got["result"]["success"] is True


# ── the premise, on real docker ─────────────────────────────────────────────

def _container_up() -> bool:
    if _DOCKER is None:
        return False
    out = subprocess.run(
        [_DOCKER, "ps", "--filter", f"name=^/{_CONTAINER}$", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=30, check=False)
    return out.stdout.strip() == _CONTAINER


@pytest.mark.skipif(not _container_up(), reason=f"container '{_CONTAINER}' not running")
def test_on_real_docker_only_the_inner_timeout_leaves_nothing_behind():
    """The measurement the fix is built on, re-run rather than quoted.

    Both arms use the same token so a leaked process from either is visible to
    the other; each arm cleans up after itself.

    THE TOKEN IS PER-INVOCATION, and that is load-bearing. This probe runs
    inside `vibeic-eda` -- the SINGLE long-lived container every run on the
    host execs into -- and it used to select on the literal `sleep 91`, shared
    by every run of this test, with `pkill -f`. Two concurrent runs, or any
    tool that happened to sleep 91 seconds, reaped each other's processes; the
    pre-flight `assert alive() == 0` would then fail on a neighbour's noise, or
    worse, pass after killing a neighbour's work. That is the same defect class
    as the two watchdog reapers repaired in `_docker_watchdog` and
    `phase3_one_shot_runner` (rc=143 with zero test failures, 2026-08-27).

    Why not the identity stamp those two now use: the processes measured here
    are DELIBERATELY orphaned -- being orphaned is the property under test --
    so no supervisor survives to stamp `(pid, /proc starttime)` and nothing
    would read it back. The token is instead carried in argv[0] via `exec -a`,
    where no other run can produce it, and the reap resolves it to PIDs and
    signals those. A pattern that cannot collide is not the same thing as `-x`
    on a pattern that is shared by design.
    """
    token = "vibeicorphanprobe" + uuid.uuid4().hex[:12]
    # `[t]oken` keeps the probe from matching its own pgrep command line.
    bracketed = f"[{token[0]}]{token[1:]}"
    marker = f"exec -a {token} sleep 91"

    def alive() -> int:
        r = subprocess.run(
            [_DOCKER, "exec", _CONTAINER, "bash", "-c",
             f"pgrep -cf '{bracketed}' || true"],
            capture_output=True, text=True, timeout=30, check=False)
        return int((r.stdout.strip() or "0").splitlines()[0])

    def reap():
        # Resolve the token to PIDs, then signal those PIDs. Never a
        # pattern-matching killer, which cannot be told which run it is
        # serving. `unanchored_process_kill_check.py` pins this.
        subprocess.run(
            [_DOCKER, "exec", _CONTAINER, "bash", "-c",
             f"pids=$(pgrep -f '{bracketed}' || true); "
             f'[ -n "$pids" ] && kill -KILL $pids || true'],
            capture_output=True, timeout=30, check=False)

    reap()
    assert alive() == 0, "a previous run leaked; refusing to measure against noise"

    try:
        # old behaviour: kill the client
        subprocess.run([_DOCKER, "exec", _CONTAINER, "bash", "-c", f"{marker} & wait"],
                       capture_output=True, timeout=4, check=False)
    except subprocess.TimeoutExpired:
        pass
    orphaned = alive()
    reap()

    # new behaviour: the timeout is inside
    subprocess.run(
        [_DOCKER, "exec", _CONTAINER, "timeout", "-k", "5", "3",
         "bash", "-c", f"{marker} & wait"],
        capture_output=True, timeout=60, check=False)
    survived = alive()
    reap()

    assert orphaned > 0, (
        "the premise no longer holds on this docker: killing the exec client "
        "already stops the process, so the fix would be unnecessary here")
    assert survived == 0, (
        f"the in-container timeout left {survived} process(es) running")


# ── shape: the fix cannot be silently reverted in place ─────────────────────

def test_no_tool_reaches_the_container_around_dockerexec():
    """Every `docker exec` that runs a TOOL must go through dockerExec.

    A second call site is a second place a runaway can be orphaned, and it
    would inherit none of this file's guarantees. The capability probe is the
    one permitted exception: it runs a fixed `command -v timeout`, never
    caller-supplied work, and it cannot itself use the wrapper it is testing
    for.
    """
    body = _slice_function("dockerExec")
    assert '"timeout"' in body and '"-k"' in body

    direct = re.findall(
        r'_spawnSync\(\s*"docker",\s*\[\s*"exec",\s*CONTAINER,([^\]]*)\]', SRC)

    # What separates a safe direct exec from an unsafe one is not the count but
    # whether it runs CALLER-SUPPLIED work. A probe runs a fixed command whose
    # cost is bounded by construction; a tool run is unbounded and is exactly
    # what has to be reaped on a timeout.
    for site in direct:
        assert not re.search(r'\bcmd\b', site), (
            f"a direct container exec runs the caller's command outside "
            f"dockerExec, so its timeout would orphan the tool: {site}")

    # Both known probes are fixed commands: the coreutils capability check and
    # the file-visibility preflight (`test -e` over a path list).
    assert len(direct) == 2, (
        f"a new direct container exec appeared; confirm it is a bounded probe "
        f"and not a tool run, then update this test: {direct}")
    assert any('"command -v timeout"' in d for d in direct)
    assert any("-e " in d for d in direct)
