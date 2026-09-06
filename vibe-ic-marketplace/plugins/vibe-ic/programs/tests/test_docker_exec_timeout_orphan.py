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

AND THE SUPERVISED PATH NO LONGER USES IT AT ALL (vibe-ic#2051, 2026-09-07).
There the wrap was doing two jobs, and only one of them was legitimate: it tore
a spawned tree down whole, AND it SIGKILLed the tool at `hard_ceiling_s`
whatever the job was doing. The owner ruled the second out — only a progress
stall may stop a job — so the wrap came off that path, and the teardown is now
proved to come from the identity-anchored reap instead of from GNU `timeout`.
The last three tests in this file are that proof, and they are the ones that
keep the 2026-07-22 hazard caught.

chip/tool-AGNOSTIC: no chip, tool or PDK literal; the helper is a pure string
transform over whatever command it is handed.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

from _source_pin import func_src

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


def test_the_wrap_helper_is_unchanged_for_the_callers_that_still_need_it():
    """The helper's exact output, pinned.

    `run_docker_supervised` no longer calls this (vibe-ic#2051 — see
    `test_the_supervised_path_carries_no_outer_clock` below), but four callers
    still do, and they still need to: each drives a RAW `docker exec` under a
    host-side `subprocess.run(timeout=)`, where the bound kills the docker
    CLIENT and leaves the tool inside the container running. This assertion
    keeps that string byte-for-byte, so removing the clock from the supervised
    path cannot quietly change what the orphan guard emits everywhere else.
    """
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
    body = func_src(src, "_docker_exec_raw")
    assert "wrap_with_container_timeout" in body, (
        f"{mod_name}._docker_exec_raw lost its container-side deadline — a "
        "host timeout there orphans the in-container tool")


# ---------------------------------------------------------------------------
# The path that ACTUALLY leaked: a full docker-exec argv handed to the generic
# `_run` subprocess helper, bypassing `_docker_exec_raw` entirely.
# ---------------------------------------------------------------------------
import design_one_shot_runner as dosr  # noqa: E402


def test_docker_exec_argv_gets_a_container_side_deadline():
    """`docker exec -w <dir> <c> bash -lc "<tool>"` — the Phase-2 generic-synth
    dispatch shape, and the one measured leaking."""
    argv = ["docker", "exec", "-w", "/w", "c", "bash", "-lc",
            "yosys -p 'synth'"]
    out = dosr._docker_exec_argv_with_deadline(argv, 300)
    assert out[:-1] == argv[:-1]                       # only the script changes
    assert "timeout --kill-after=5 295 " in out[-1]
    assert shlex.quote("yosys -p 'synth'") in out[-1]


@pytest.mark.parametrize("argv", [
    ["docker", "cp", "src", "c:/dst"],                 # not an exec
    ["yosys", "-p", "synth"],                          # not docker at all
    ["docker", "exec", "c", "ls"],                      # no bash -lc payload
    ["docker", "exec", "c"],                            # too short
])
def test_non_exec_argvs_are_returned_untouched(argv):
    assert dosr._docker_exec_argv_with_deadline(list(argv), 60) == argv


def test_sh_lc_is_also_covered():
    out = dosr._docker_exec_argv_with_deadline(
        ["docker", "exec", "c", "sh", "-lc", "tool"], 60)
    assert "timeout --kill-after=5 55 " in out[-1]


def test_run_helper_applies_the_wrap():
    """Regression lock on the call path, not just the helper."""
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    body = func_src(src, "_run")
    assert "_docker_exec_argv_with_deadline" in body, (
        "_run stopped hardening docker-exec argvs — a host timeout there "
        "orphans the in-container tool")


def test_lec_run_docker_helper_carries_a_container_side_deadline():
    """Fourth instance of the same shape: `lec_run._docker` is a bare
    `subprocess.run(["docker","exec",...])` whose own `except TimeoutExpired`
    handler proves a timeout is an expected outcome — so the leak was an
    expected outcome too. Fixed by pattern from the measured Phase-2 leak."""
    src = (PROGRAMS / "lec_run.py").read_text()
    body = func_src(src, "_docker")
    assert "wrap_with_container_timeout" in body, (
        "lec_run._docker lost its container-side deadline — a host timeout "
        "there orphans a yosys equivalence run inside the container")


# ===========================================================================
# vibe-ic#2051 — THE SUPERVISED PATH HAS NO OUTER CLOCK, AND STILL TEARS AN
# ORPHAN DOWN WHOLE.
#
# The wrap was introduced here because GNU `timeout` "puts the command in its
# own process group", so a tool that spawns children (yosys -> abc) is killed
# as a group rather than left overwriting the good netlist. Taking the wrap off
# the supervised path is therefore only safe if the grouping was never the
# wrap's to give. MEASURED 2026-09-07 in the pinned image: it was not. `docker
# exec` starts each exec in its OWN session, so the stamping shell already
# reports pid == pgid == sid with no `timeout` anywhere, and `exec` hands that
# pid — and that group — straight to the tool.
#
# These three tests hold the two halves apart: the shape (no clock, still a
# group-signalling reap) and the mechanism (the reap selects by the STAMP, so
# an unstamped job is left alone — which is what makes a torn-down tree the
# reap's doing and not the shell's).
# ===========================================================================

def test_the_supervised_path_carries_no_outer_clock():
    """The command `run_docker_supervised` sends into the container.

    A `timeout` here is a wall clock on every long tool run in the plugin, which
    is the defect #2051 removed. The assertion is on the STRING the supervised
    path builds, not on the source of the function, so a reintroduction through
    a differently-spelled helper is caught too.
    """
    built = dw.supervised_container_command("yosys -p 'synth'", "/tmp/x.pid")
    assert "timeout" not in built, built
    assert "--kill-after" not in built, built
    # It is still an `exec`, so the stamped pid IS the tool's pid.
    assert built.rstrip().endswith(
        "exec bash -lc " + shlex.quote("yosys -p 'synth'")), built
    # ...and it is still stamped, which is what the reap selects on.
    assert "/tmp/x.pid" in built, built

    body = func_src((PROGRAMS / "_docker_watchdog.py").read_text(),
                    "run_docker_supervised")
    assert "wrap_with_container_timeout" not in body, (
        "the supervised path took its outer wall clock back")
    assert "supervised_container_command" in body, body


def test_the_stall_reap_signals_the_whole_process_group():
    """THE 2026-07-22 HAZARD, still caught — by the reap rather than by a clock.

    The reap must (a) signal the process GROUP when the stamped root leads one,
    which is what tears a `yosys -> abc` tree down atomically, and (b) also name
    the ppid-walked descendants, which catches a child that called `setpgid` and
    left the group. Losing either would let an orphan survive to overwrite the
    artifact of the step that replaced it.
    """
    reap = dw.reap_command("/tmp/job.pid", "TERM")
    # (a) the GROUP, guarded by "the root actually leads one"
    assert 'VPG=$(ps -o pgid= -p "$VPID"' in reap, reap
    assert 'kill -TERM -- "-$VPID"' in reap, reap
    # (b) the ppid walk, so nothing that left the group is missed
    assert "ps -eo pid=,ppid=" in reap, reap
    assert 'kill -TERM "$VPID" $VKIDS' in reap, reap


def test_the_reap_selects_by_the_stamp_and_never_by_a_pattern():
    """Why the teardown above is the REAP's doing.

    Identity is `(pid, /proc starttime)` read from the stamp and re-validated;
    with no stamp, or a recycled pid, the reap does NOTHING and says which. A
    fallback to matching a command line would put back the defect that
    SIGTERMed another run's healthy tool in the shared container (2026-08-27),
    and it is exactly on the paths where the stamp failed that it would fire.
    """
    reap = dw.reap_command("/tmp/job.pid", "KILL")
    for why in ("no_stamp", "unreadable", "bad_pid", "bad_starttime",
                "already_gone", "pid_reused"):
        assert f"VIBEIC_REAP_SKIP {why}" in reap, why
    assert "pkill" not in reap, reap
    assert "pgrep" not in reap, reap
