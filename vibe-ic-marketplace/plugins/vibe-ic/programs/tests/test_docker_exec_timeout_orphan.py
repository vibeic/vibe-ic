#!/usr/bin/env python3
"""A host-side `docker exec` timeout must not ORPHAN the in-container tool.

Measured 2026-07-22 while driving a large design through Phase 2: a
`subprocess.run(['docker','exec',...], timeout=300)` raised TimeoutExpired,
the step was recorded as timed out and the runner moved on — and the yosys it
had launched was still running eighteen minutes later, holding 6 GB and a full
core inside a `--cpus=12 --memory=48g` container that the replacement step was
still sharing. Both invocations wrote the SAME output netlist path, so the
orphan was also free to overwrite the good artifact produced by the step that
replaced it.

Cause: killing `subprocess.run`'s child kills the `docker exec` CLIENT. Docker
does not propagate that to the process inside the container.

`phase3_one_shot_runner._docker_exec_raw` and
`_docker_watchdog.run_docker_supervised` already gave their commands a
container-side deadline (ORGANIC #570). The three other `_docker_exec_raw`
implementations — design_one_shot_runner (Phase 2 synth),
ppa_area_threshold_check, mixed_signal_top_lvs_run — never got it. The wrap is
now one shared helper and all of them use it.

chip/tool-AGNOSTIC: no chip, tool or PDK literal; the helper is a pure string
transform over whatever command it is handed.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _docker_watchdog as dw  # noqa: E402


def test_wrap_gives_the_command_its_own_earlier_deadline():
    w = dw.wrap_with_container_timeout("yosys -p 'synth'", 300)
    # Fires 5 s BEFORE the host, so the container side is already dead when
    # the caller's TimeoutExpired is raised.
    assert "timeout --kill-after=5 295 " in w
    assert shlex.quote("yosys -p 'synth'") in w


def test_wrap_escalates_term_to_kill():
    assert "--kill-after=5" in dw.wrap_with_container_timeout("x", 60)


def test_wrap_degrades_gracefully_without_a_timeout_binary():
    """A container with no `timeout` must behave exactly as before."""
    w = dw.wrap_with_container_timeout("x", 60)
    assert "command -v timeout" in w
    assert w.rstrip().endswith("fi")
    assert "else exec bash -lc x; fi" in w


def test_wrap_never_produces_a_non_positive_deadline():
    for t in (0, 1, 5, 6):
        w = dw.wrap_with_container_timeout("x", t)
        inner = int(w.split("--kill-after=5 ")[1].split(" ")[0])
        assert inner >= 1


def test_wrap_quotes_the_command_so_it_cannot_break_out():
    nasty = "echo hi'; rm -rf /tmp/nope; echo '"
    w = dw.wrap_with_container_timeout(nasty, 30)
    # The payload appears exactly once per branch, fully quoted.
    assert w.count(shlex.quote(nasty)) == 2


def test_supervisor_ceiling_wrap_is_unchanged_by_the_refactor():
    """`run_docker_supervised` built this string inline before; the shared
    helper must reproduce it byte-for-byte at the 24 h ceiling."""
    expected = (
        "if command -v timeout >/dev/null 2>&1; then "
        "exec timeout --kill-after=5 86395 bash -lc X; "
        "else exec bash -lc X; fi"
    )
    assert dw.wrap_with_container_timeout("X", 86400) == expected


@pytest.mark.parametrize("mod_name", [
    "design_one_shot_runner",
    "ppa_area_threshold_check",
    "mixed_signal_top_lvs_run",
])
def test_every_raw_exec_now_carries_a_container_side_deadline(mod_name):
    """Regression lock: the three runners that leaked must keep the wrap."""
    src = (PROGRAMS / f"{mod_name}.py").read_text()
    start = src.index("def _docker_exec_raw")
    body = src[start:start + 2500]
    assert "wrap_with_container_timeout" in body, (
        f"{mod_name}._docker_exec_raw lost its container-side deadline — a "
        "host timeout there orphans the in-container tool")
