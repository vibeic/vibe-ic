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
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
INDEX_JS = HERE.parent / "src" / "index.js"

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
    run = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         timeout=60)
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
