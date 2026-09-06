"""Item 2 — phase 3's supervised dispatch is the SHARED one, and carries no clock.

`phase3_one_shot_runner._docker_exec` kept its own copy of the supervised
dispatch AND wrapped the in-container command in a GNU `timeout` at the
ceiling. Two defects in one: the wrap is an outer WALL CLOCK, which vibe-ic#2051
removed after a still-converging proof was SIGKILLed at 86395 s and the flow
recorded a design it had never finished comparing; and a private copy of a
supervised dispatch is how two files come to disagree about what stops a job.

These tests drive REAL children — a slow one that must survive its budget, and
a hung one that must be reaped whole — rather than asserting on source alone,
because a source guard cannot see reachability (measured: an earlier guard in
this lane passed a mutation that merely made a branch unreachable).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]


def _load(name):
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _raw(_container, _cmd, timeout=15):
    """A raw exec that answers nothing, so supervision rests on captured
    output alone and a surviving child survived on a signal we can name."""
    return 1, "", ""


# ---------------------------------------------------------------------------
# NO CLOCK
# ---------------------------------------------------------------------------

def test_a_slow_but_progressing_job_outlives_its_budget():
    """The shape the wrap used to kill: still working, past the ceiling."""
    DW = _load("_docker_watchdog")
    notices = []
    child = ("for i in 1 2 3 4 5; do echo tick $i; sleep 0.4; done; "
             "echo DONE; exit 0")
    rc, out, err = DW.run_docker_supervised(
        "host", child, "marker", docker_exec_raw=_raw,
        stall_grace_s=30.0, poll_s=0.2, hard_ceiling_s=0.5,
        ceiling_notice=notices.append)
    assert rc == 0, (rc, err)
    assert "DONE" in out, out
    assert notices, "the budget crossing must be RECORDED, not silent"


def test_the_dispatch_carries_no_gnu_timeout():
    """The wrap is gone from the supervised branch — asserted on CODE with the
    docstring stripped, so the guard cannot match its own explanation."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "_docker_exec"]
    assert len(fn) == 1
    body = list(fn[0].body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)):
        body = body[1:]
    code = "\n".join(ast.unparse(n) for n in body)
    assert "wrap_with_container_timeout" not in code, code[:400]
    assert "run_docker_supervised" in code, code[:400]
    # and the private dispatch is gone with it
    assert "_wd.run_supervised" not in code, code[:400]
    assert "new_job_pidfile" not in code, code[:400]


# ---------------------------------------------------------------------------
# THE CAPABILITY THAT MUST SURVIVE THE MOVE
# ---------------------------------------------------------------------------

def test_abort_probe_survives_the_move_to_the_shared_path():
    """`abort_probe` is the caller's OWN read of "progressing but going
    NOWHERE" — a measurement over the job's own output, not a clock. Two
    phase-3 sites pass one. Moving onto the shared path must not drop it."""
    DW = _load("_docker_watchdog")
    seen = {"n": 0}

    def going_nowhere():
        seen["n"] += 1
        return "produced nothing" if seen["n"] > 2 else None

    rc, _out, err = DW.run_docker_supervised(
        "host", "for i in $(seq 1 50); do echo x; sleep 0.2; done",
        "marker", docker_exec_raw=_raw,
        stall_grace_s=3600.0, poll_s=0.2, hard_ceiling_s=3600.0,
        abort_probe=going_nowhere)
    assert rc == DW._wd.RC_ABORTED, (rc, err)
    assert "produced nothing" in err, err


def test_phase3_still_hands_its_probe_through():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "_docker_exec"][0]
    code = "\n".join(ast.unparse(n) for n in fn.body[1:])
    assert "abort_probe=abort_probe" in code, code[:400]


# ---------------------------------------------------------------------------
# THE REAP IS THE ONLY THING THAT STOPS A JOB
# ---------------------------------------------------------------------------

def _host_raw(_container, cmd, timeout=15):
    """A REAL host exec, so the identity reap can actually run.

    The reap is dispatched THROUGH `docker_exec_raw`; handing it a stub that
    answers nothing means the reap never executes and only the direct child
    dies. Measured here first: with a stub, two backgrounded grandchildren
    survived — which said nothing about the reap and everything about the
    stub."""
    cp = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                        timeout=timeout)
    return cp.returncode, cp.stdout, cp.stderr


def test_a_hung_child_is_reaped_whole_with_no_survivors():
    """A job that emits NOTHING is stopped by the progress-stall reap, and the
    children it spawned go with it — the wrap's other purpose, without the
    wrap. Survivors are counted by asking the OS, not by trusting the return."""
    DW = _load("_docker_watchdog")
    tag = "vibeic-reap-proof-%d" % os.getpid()
    child = (f"sh -c 'sleep 300 # {tag}' & sh -c 'sleep 300 # {tag}' & "
             f"sleep 300 # {tag}")
    t0 = time.monotonic()
    rc, _out, err = DW.run_docker_supervised(
        "host", child, "marker", docker_exec_raw=_host_raw,
        stall_grace_s=2.0, poll_s=0.2, hard_ceiling_s=3600.0)
    elapsed = time.monotonic() - t0
    assert rc == DW._wd.RC_STALLED, (rc, err)
    assert elapsed < 60, f"stopped on the STALL ({elapsed:.1f}s), never a clock"
    time.sleep(1.5)
    survivors = subprocess.run(["pgrep", "-f", tag],
                               capture_output=True, text=True).stdout.split()
    for pid in survivors:                       # never leave strays behind
        try:
            os.kill(int(pid), 9)
        except Exception:
            pass
    assert survivors == [], f"ZERO survivors required, found {survivors}"


def test_the_reap_selects_by_identity_not_by_command_line():
    """The reap must signal the stamped (pid, starttime) and NOT a stranger
    sharing the tool's argv — the defect that made a marker `pkill -f` unsafe
    on a shared host."""
    DW = _load("_docker_watchdog")
    pf = DW.new_job_pidfile()
    prelude = DW.identity_stamp_prelude(pf)
    reap = DW.reap_command(pf, "TERM")
    assert pf in prelude and pf in reap
    assert "pkill" not in reap, reap
    assert "VIBEIC_REAP" in reap, reap


# ---------------------------------------------------------------------------
# THE GATE MUST BE ABLE TO GO RED
# ---------------------------------------------------------------------------

def test_the_residual_class_is_blocking():
    """Reported-forever is how a known defect becomes permanent: the count was
    printed and the exit code still said PASS."""
    src = (PROGRAMS / "watchdog_ceiling_semantics_check.py").read_text()
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "main"][0]
    code = "\n".join(ast.unparse(n) for n in fn.body)
    assert "if offenders or residual:" in code, code[-800:]
    assert "(BLOCKING)" in src


def test_the_gate_is_green_on_this_tree():
    """The population is empty, so the promoted class costs nothing here."""
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "watchdog_ceiling_semantics_check.py"),
         str(PROGRAMS)], capture_output=True, text=True, timeout=600)
    assert cp.returncode == 0, cp.stdout[-2000:]
    assert "RESIDUAL 0" in cp.stdout, cp.stdout[-2000:]
