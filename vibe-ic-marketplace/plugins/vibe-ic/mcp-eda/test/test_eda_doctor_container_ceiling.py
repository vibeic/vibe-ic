#!/usr/bin/env python3
"""eda_doctor must notice a container running with no memory ceiling.

A ceiling is set at CREATE time and nowhere else. `docker rm -f` + `docker run`
on a newer image — exactly how the documented upgrade path moves the MCP — starts
from nothing but its own flags, so it drops the ceiling the operator had been
running with. Nothing fails at that moment. The host simply becomes killable by
the next runaway synthesis run, and killing a timed-out `docker exec` does NOT
kill the tool still running inside, so the ceiling has to be on the container.

A document can be skipped; a check cannot. This is that check.

The helper is EXECUTED here rather than grepped for: these tests stub the docker
inspect call and run `_containerMemoryCeiling` under node, so they assert what it
DOES. The registration test below is the only static one, because the wiring into
the tool is a shape, not a behaviour.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
INDEX_JS = HERE.parent / "src" / "index.js"

# THIS FILE'S ONE LAUNCH IS ON THE HOST, NOT IN THE CONTAINER. `_run` below
# execs `node -e` over a STUB `_spawnSync` — no docker is involved at all, so
# there is no container-level kill here to confuse with an in-tool one; the only
# thing that could stop the child was the `timeout=60` this replaces.
sys.path.insert(0, str(HERE.parents[1] / "programs"))
import _watchdog                                              # noqa: E402

#: How long the node child may be COMPLETELY FLAT — no output, no CPU, no I/O
#: anywhere in its tree — before it is called hung. NOT a runtime budget. The
#: helper under test is a pure function over a stubbed spawn and returns in
#: milliseconds; what the old `timeout=60` actually bounded was the HOST, and on
#: a loaded one it raised `TimeoutExpired`, which pytest recorded as this file
#: FAILING — an assertion about `_containerMemoryCeiling` that no measurement
#: supported.
_STALL_GRACE_S = 60

GIB = 1024 * 1024 * 1024


def _helper_source() -> str:
    """The shipped helper itself. A copy in this file would pass while the
    server did something else, which is the failure this test exists to catch."""
    src = INDEX_JS.read_text(encoding="utf-8")
    start = src.index("const _BYTES_PER_GIB =")
    end = src.index("// ─── Tool: eda_doctor", start)
    body = src[start:end]
    assert "_containerMemoryCeiling" in body, body[:200]
    return body


def _run(stdout: str, status: int = 0) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available; the helper under test is JavaScript")
    script = textwrap.dedent(f"""
        const CONTAINER = "vibeic-eda";
        const _spawnSync = () => ({json.dumps({"status": status, "stdout": stdout})});
        {_helper_source()}
        console.log(JSON.stringify(_containerMemoryCeiling()));
    """)
    argv = [node, "-e", script]
    res = _watchdog.run_host_supervised(argv, stall_grace_s=_STALL_GRACE_S)
    assert res.outcome not in ("stalled", "ceiling"), (
        f"the node child made NO forward progress for {_STALL_GRACE_S}s — "
        f"nothing in its process tree advanced, so it was stopped as hung. "
        f"Nothing about the ceiling helper was measured.\n{res.out}{res.err}")
    run = _watchdog.completed_process(argv, res)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_a_capped_container_with_swap_disabled_passes():
    out = _run(f"{64 * GIB} {64 * GIB}")
    assert out["ok"] is True
    assert "64 GiB" in out["detail"]
    assert "swap disabled" in out["detail"]


def test_an_uncapped_container_is_reported():
    """THE CASE THIS EXISTS FOR. `docker run` with no --memory reports 0."""
    out = _run("0 0")
    assert out["ok"] is False
    assert "NO memory ceiling" in out["detail"]
    assert "--memory-swap" in out["detail"], "the fix must be in the message"


def test_the_message_names_why_an_upgrade_loses_the_ceiling():
    """The operator has to know that recreating drops it, or they will lose it
    again on the next upgrade and this check will just fire again."""
    out = _run("0 0")
    assert "recreate" in out["detail"].lower()


@pytest.mark.parametrize("swap,shown", [
    (-1, "unlimited"),
    (128 * GIB, "128 GiB"),
])
def test_a_ceiling_with_swap_still_enabled_is_reported(swap, shown):
    """A cap with swap left on does not fail fast — it thrashes the disk for
    hours, which is the failure mode that looks like a hang."""
    out = _run(f"{64 * GIB} {swap}")
    assert out["ok"] is False
    assert "swap is NOT disabled" in out["detail"]
    assert shown in out["detail"]


def test_an_unreadable_container_is_not_reported_as_capped():
    """NOT-KNOWN IS NOT CAPPED. A failed inspect must warn, never hand a clean
    bill of health to a container nobody measured."""
    assert _run("", status=1)["ok"] is False
    assert _run("garbage")["ok"] is False


def test_the_check_is_soft_and_wired_after_the_docker_probe():
    """Registration shape. SOFT deliberately: an uncapped container runs every
    flow correctly, so failing eda_doctor hard would block users over a host
    risk they may have accepted. `if (!ok && !soft) allOk = false;` is what
    makes `soft` mean that."""
    src = INDEX_JS.read_text(encoding="utf-8")
    i = src.index('check: "container_memory_ceiling"')
    block = src[i - 400:i + 400]
    assert "_containerMemoryCeiling()" in block
    assert "soft: ceiling.ok ? undefined : true" in block
    assert src.index('check: "docker_reachable"') < i, (
        "the ceiling check must run after docker is known reachable")
