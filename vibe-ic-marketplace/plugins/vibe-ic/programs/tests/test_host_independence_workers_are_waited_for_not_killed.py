#!/usr/bin/env python3
"""A parallel host-independence worker is WAITED FOR. It is never killed on a clock.

WHAT WENT WRONG
===============
``gate_host_independence_check.parallel_audit`` shards 144 driveable gates over
``--jobs 8`` (the shipped wiring in ``tools/ci/repo_hygiene_gates.sh``) and gave
each worker a WALL-CLOCK budget of ``max(600 * len(labels), 600)`` seconds, then
``proc.kill()``-ed the worker that crossed it.

``hygiene_shard_plan`` is Longest-Processing-Time-first, so it deliberately
isolates the single heaviest gate on a shard of its own. MEASURED on this tree
at ``2fbb2932a8a3``, from the repo's own ``hygiene_gate_profile.json``::

    worker 0:  1 label   budget= 600s   `an argued direction is pinned`, 646s
    worker 1:  1 label   budget= 600s   `gates disclose their denominator`, 208s
    worker 2: 15 labels  budget=9000s
    worker 3: 42 labels  budget=25200s

The shard the planner made SMALLEST in count carries the HEAVIEST gate and got
the SMALLEST budget, and the repo's own measured profile says that gate costs
646 s against a 600 s budget. The kill was 46 s below the cost of the work ON AN
IDLE HOST; whether it fired was a property of host load and of nothing in the
commit. ``test_shipped_gate_is_wired_register_holds_no_pending_shrink`` records
the same event from the other side -- that gate went 417 s -> 804 s in a hygiene
sweep and this program "fell from PASS to PARALLEL_INCOMPLETE, `worker 0 exceeded
its 600s process budget`, naming that gate".

And ``PARALLEL_INCOMPLETE`` exits 2 under ``run_tolerating_uncheckable``, whose
contract is that rc 2 is LOUD AND NON-FATAL. One killed worker therefore turned
the whole 144-gate audit into `could not check`: announced, blocking nothing, and
leaving the sweep with no verdict at all about host independence.

WHAT THIS FILE LOCKS
====================
1. ``await_workers`` WAITS. A worker that outlives any budget a caller might have
   guessed still returns its record and its own exit status.
2. It returns ONE ROW PER LAUNCHED WORKER. A wait that silently dropped a row
   would be a set of labels nobody reports.
3. THE NEGATIVE ARM IS THE DELETED CODE ITSELF. The pre-fix wait is rebuilt here
   and driven against the SAME children, and it must LOSE the record. Without it
   this file would pass just as happily against a wait that still killed, because
   a short-lived child never crosses a budget.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/\\
test_host_independence_workers_are_waited_for_not_killed.py -q
"""
from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import gate_host_independence_check as G                    # noqa: E402

#: Long enough that the pre-fix budget below is crossed determinately on any
#: host, short enough that this file costs a couple of seconds. It is a property
#: of THIS FIXTURE, never of a gate: the fix is that no such number decides
#: whether real work is kept.
_WORKER_SECONDS = 3.0

#: The pre-fix budget, in the negative arm only. Below `_WORKER_SECONDS`, so the
#: deleted code kills; the shipped code has no budget at all.
_PREFIX_BUDGET_S = 0.5

_WORKER = """
import json, sys, time
time.sleep(float(sys.argv[2]))
json.dump({"selected_labels": [sys.argv[3]], "gates_declared": 1}, open(sys.argv[1], "w"))
"""


def _launch(tmp_path: Path, n: int):
    """`n` real children, each writing its record only AFTER it has slept."""
    procs = []
    for i in range(n):
        rec = tmp_path / f"worker-{i}.json"
        procs.append((i, [f"label-{i}"], rec, subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(rec), str(_WORKER_SECONDS),
             f"label-{i}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
    return procs


def _reap(procs) -> None:
    """Kill what this test spawned, by RECORDED pid -- never a name pattern."""
    for _, _, _, proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:                                    # noqa: BLE001
            pass


def test_a_worker_that_outlives_any_guessed_budget_is_waited_for(tmp_path):
    """The property, on real processes: no clock decides whether work is kept."""
    procs = _launch(tmp_path, 3)
    try:
        started = time.monotonic()
        rows = G.await_workers(procs, jobs=3)
        elapsed = time.monotonic() - started
    finally:
        _reap(procs)

    assert elapsed >= _WORKER_SECONDS, (
        f"the wait returned after {elapsed:.2f}s, before children that sleep "
        f"{_WORKER_SECONDS}s could have finished — so it did not wait for them, "
        f"and this file is measuring nothing")
    assert [r[0] for r in rows] == [0, 1, 2], (
        f"await_workers returned rows {[r[0] for r in rows]} for 3 launched "
        f"workers. One row per worker is what makes the caller's completeness "
        f"check a MEMBERSHIP check; a dropped row is a label nobody reports.")
    for i, labels, rec, rc, _out, _err in rows:
        assert rc == 0, (
            f"worker {i} exited {rc}. A worker still doing its work must be "
            f"waited for, never signalled: killing unfinished work cannot turn "
            f"it green.")
        assert rec.is_file(), (
            f"worker {i} left no machine record, so its {len(labels)} label(s) "
            f"would be reported by nobody")
        assert json.loads(rec.read_text())["selected_labels"] == labels


def test_the_deleted_wall_clock_kill_would_lose_the_record(tmp_path):
    """THE NEGATIVE ARM: the pre-fix wait, on the same children, must lose it.

    This is the code that was removed from ``parallel_audit``, rebuilt verbatim
    in shape. If it does NOT lose the record, then the budget above never fires
    against these children and the positive test could not have failed either —
    a check that cannot fail is not a check.
    """
    procs = _launch(tmp_path, 3)

    def prefix_collect(row):
        i, labels, rec, proc = row
        try:
            out, err = proc.communicate(timeout=_PREFIX_BUDGET_S)
            return i, labels, rec, proc.returncode, out, err, None
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            out, err = proc.communicate()
            return i, labels, rec, proc.returncode, out, err, exc

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            rows = sorted(pool.map(prefix_collect, procs),
                          key=lambda r: r[0])
    finally:
        _reap(procs)

    killed = [r for r in rows if r[6] is not None]
    assert len(killed) == 3, (
        f"the pre-fix wait killed {len(killed)} of 3 workers at a "
        f"{_PREFIX_BUDGET_S}s budget against children sleeping "
        f"{_WORKER_SECONDS}s. It has to kill all three, or the arm above is "
        f"proving nothing.")
    for i, labels, rec, _rc, _out, _err, _exc in killed:
        assert not rec.is_file(), (
            f"worker {i} still wrote its record despite being killed; then the "
            f"kill was not destroying evidence and this arm is vacuous")


def test_the_shipped_wait_carries_no_wall_clock_at_all(tmp_path):
    """A budget of PROCESSES, never of seconds — asserted on the behaviour.

    Driven by making the children outlive `_PREFIX_BUDGET_S` by a wide margin
    while the caller passes NO budget of any kind: there is no parameter on
    ``await_workers`` through which one could be supplied.
    """
    import inspect
    params = set(inspect.signature(G.await_workers).parameters)
    assert params == {"procs", "jobs"}, (
        f"await_workers takes {sorted(params)}. `jobs` is a budget of "
        f"PROCESSES and is the only budget this wait may have; a seconds "
        f"parameter is the deadline this file exists to keep out.")
    procs = _launch(tmp_path, 1)
    try:
        rows = G.await_workers(procs, jobs=1)
    finally:
        _reap(procs)
    assert rows[0][3] == 0 and rows[0][2].is_file()


def test_no_wall_clock_kill_survives_in_the_parallel_wait(tmp_path):
    """Removing the kill did not remove the refusal it was standing in for.

    READ AS CODE, NOT AS TEXT. A grep for "process budget" matches the docstring
    that EXPLAINS the removed deadline, so the published sentence becomes its own
    input and the check goes red on its own prose. This walks the ``ast`` of the
    two functions that own the wait and asks the only two questions that matter:
    is any child signalled there, and is any wait given a number of seconds.
    """
    import ast
    src = (_PROGRAMS / "gate_host_independence_check.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    # WRITTEN SO THE PRE-FIX TREE CAN ANSWER IT. `parallel_audit` exists on both
    # sides and `ast.walk` descends into the nested `collect` the deadline used
    # to live in, so the control arm reports the KILL rather than an
    # AttributeError about a function it has never heard of. `await_workers` is
    # included when present and is not required to be.
    owners = {n.name: n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name in ("await_workers", "parallel_audit")}
    assert "parallel_audit" in owners, (
        f"the parallel driver is not in this file any more (found "
        f"{sorted(owners)}); a renamed owner is a wait this check stopped "
        f"looking at, which is indistinguishable from a clean one")

    signals, timed_waits = [], []
    for name, fn in owners.items():
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", None)
            if attr in ("kill", "terminate", "send_signal"):
                signals.append(f"{name}: .{attr}() at line {node.lineno}")
            if attr in ("communicate", "wait") and any(
                    kw.arg == "timeout" for kw in node.keywords):
                timed_waits.append(
                    f"{name}: .{attr}(timeout=...) at line {node.lineno}")

    assert not signals, (
        "a parallel worker is signalled here: " + "; ".join(signals) +
        ". A worker that has not finished is waited for, not killed — killing "
        "unfinished work cannot turn it green, and here it discarded all 144 "
        "gates as UNCHECKABLE.")
    assert not timed_waits, (
        "a wall-clock worker budget is back: " + "; ".join(timed_waits) +
        ". The gate completes, or it reports NOT_COMPLETED by name; it never "
        "reports a clock.")

    # And the refusal the kill was standing in for is still there, still by name.
    assert "NOT_COMPLETED without a machine" in src, (
        "the no-record refusal lost its NOT_COMPLETED wording; a worker that "
        "died has to reach a reader as work that did not complete, naming the "
        "labels it was carrying")


def test_the_ast_check_above_can_actually_see_a_reintroduced_deadline(tmp_path):
    """The negative arm for the check above, on a MUTATED COPY of the real file.

    An ast walk that matched nothing because it was looking in the wrong place
    reports exactly the same clean zero as a file with no deadline in it. This
    puts the deleted deadline back into a copy and requires both findings.
    """
    import ast
    src = (_PROGRAMS / "gate_host_independence_check.py").read_text(
        encoding="utf-8")
    mutated = src.replace(
        "        out, err = proc.communicate()\n"
        "        return i, labels, json_path, proc.returncode, out, err\n",
        "        try:\n"
        "            out, err = proc.communicate(timeout=600)\n"
        "        except subprocess.TimeoutExpired:\n"
        "            proc.kill()\n"
        "            out, err = proc.communicate()\n"
        "        return i, labels, json_path, proc.returncode, out, err\n",
        1)
    assert mutated != src, (
        "the mutation did not apply — the wait no longer has the shape this "
        "arm knows how to break, so it is proving nothing about the check")

    fn = next(n for n in ast.walk(ast.parse(mutated))
              if isinstance(n, ast.FunctionDef) and n.name == "await_workers")
    signals = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", None) in
               ("kill", "terminate", "send_signal")]
    timed = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) in ("communicate", "wait")
             and any(kw.arg == "timeout" for kw in n.keywords)]
    assert signals and timed, (
        f"the mutated copy reintroduces both a kill and a timed wait, but the "
        f"walk found {len(signals)} signal(s) and {len(timed)} timed wait(s). "
        f"The instrument cannot see the defect it is deployed against.")
