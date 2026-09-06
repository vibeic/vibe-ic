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

AND "NOTHING" IS NOT THE REPLACEMENT. Deleting the clock and waiting forever
trades a worker killed while working for a worker nobody stops when it has
genuinely wedged. The replacement is the repo's own primitive: the watchdog kills
only a job that has STOPPED — every readable forward-progress signal (captured
output, the process tree's CPU, its block I/O) flat for a COUNT of consecutive
looks, never a duration.

WHAT THIS FILE LOCKS
====================
1. ``run_workers_supervised`` WAITS for a worker that is still moving. One that
   outlives any budget a caller might have guessed still returns its record and
   its own exit status.
2. A WEDGED worker IS stopped, and the reason is NAMED. Silent, no CPU, no I/O
   across the looks -> ``Stalled``, quoting which signals were readable.
3. THE TWO ARE PROVED IN ONE CALL, at one cadence, against one supervisor. A
   wedged child and a slow-but-progressing child handed to the same pool must
   come back with opposite verdicts, or the discrimination is asserted rather
   than measured.
4. It returns ONE ROW PER LAUNCHED WORKER. A wait that silently dropped a row
   would be a set of labels nobody reports.
5. THE NEGATIVE ARM IS THE DELETED CODE ITSELF. The pre-fix wait is rebuilt here
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
import _progress_run as _pr                                 # noqa: E402

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


#: The OBSERVATION CADENCE this file drives the real supervisor at. Production
#: looks 12 times at its own measured cadence — about six minutes of total
#: stillness — and waiting that out per arm would make this file unrunnable.
#: `_progress_run` is explicit that this direction is safe: "sampling more often
#: never kills a working job sooner". So the cadence is fast and the SUPERVISOR
#: is the real one; nothing here is stubbed.
_LOOKS = 3
_POLL_S = 0.4
_STALL_WINDOW_S = _LOOKS * _POLL_S            # 1.2 s of total stillness

#: The progressing arm runs for many multiples of that window, so a red here is
#: a real discrimination failure and never a race with it.
_PROGRESSING_S = 8.0

#: A child that BURNS CPU and says nothing: no output, no block I/O, no writes
#: until the very end. It is the shape a real gate has — `an argued direction is
#: pinned` produces no output for the 646 s it is inside its own drive — and it
#: is the shape a naive "did it print lately?" supervisor would murder.
_PROGRESSING = """
import json, sys, time
t = time.monotonic(); x = 0
while time.monotonic() - t < float(sys.argv[2]):
    x = (x * x + 1) % 1000003
json.dump({"selected_labels": [sys.argv[3]], "gates_declared": 1, "x": x},
          open(sys.argv[1], "w"))
"""

#: A child that has STOPPED: asleep, silent, no CPU, no I/O, forever.
_WEDGED = "import time\ntime.sleep(36000)\n"


def _fast(argv, progress_path):
    """The REAL configuration point, sampled fast — `supervise_one_worker`.

    Not a paraphrase of it: the progress channel, the env var, the log-path
    watch and the `Stalled` conversion are all the shipped ones. Only the
    OBSERVATION CADENCE moves, and `_progress_run` is explicit that sampling
    more often never kills a working job sooner.
    """
    return G.supervise_one_worker(argv, progress_path,
                                  stall_grace_s=_STALL_WINDOW_S,
                                  poll_s=_POLL_S)


def _launch(tmp_path: Path, n: int):
    """`n` worker SPECS, each writing its record only AFTER it has slept.

    Specs, not live processes: `run_workers_supervised` owns the launch, which
    is what makes the pool width a budget of PROCESSES rather than a count of
    things already started.
    """
    return [(i, [f"label-{i}"], tmp_path / f"worker-{i}.json",
             [sys.executable, "-c", _WORKER,
              str(tmp_path / f"worker-{i}.json"), str(_WORKER_SECONDS),
              f"label-{i}"])
            for i in range(n)]



def _reap(procs) -> None:
    """Kill what THIS TEST spawned, by RECORDED pid -- never a name pattern.

    Used only by the negative arm below, which Popens its own children in order
    to drive the DELETED wait against them.
    """
    for _, _, _, proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:                                    # noqa: BLE001
            pass



def test_a_worker_that_outlives_any_guessed_budget_is_waited_for(tmp_path):
    """At the PRODUCTION cadence, on real processes: no clock cuts them short.

    Deliberately NOT `_fast`. This arm is about the shipped configuration —
    twelve looks at the supervisor's own measured cadence — and three children
    that sleep past any per-worker budget a caller might once have guessed.
    """
    procs = _launch(tmp_path, 3)
    started = time.monotonic()
    rows = G.run_workers_supervised(procs, jobs=3)
    elapsed = time.monotonic() - started

    assert elapsed >= _WORKER_SECONDS, (
        f"the pool returned after {elapsed:.2f}s, before children that sleep "
        f"{_WORKER_SECONDS}s could have finished — so it did not wait for them, "
        f"and this file is measuring nothing")
    assert [r[0] for r in rows] == [0, 1, 2], (
        f"run_workers_supervised returned rows {[r[0] for r in rows]} for 3 "
        f"launched workers. One row per worker is what makes the caller's "
        f"completeness check a MEMBERSHIP check; a dropped row is a set of "
        f"labels nobody reports.")
    for i, labels, rec, rc, _out, _err, stall in rows:
        assert not stall, (
            f"worker {i} was stopped: {stall}. It was sleeping, which is the "
            f"one thing a wall clock and a progress supervisor disagree about — "
            f"and at {_WORKER_SECONDS}s it is nowhere near twelve looks.")
        assert rc == 0, (
            f"worker {i} exited {rc}. A worker still doing its work must be "
            f"waited for, never signalled.")
        assert rec.is_file(), (
            f"worker {i} left no machine record, so its {len(labels)} label(s) "
            f"would be reported by nobody")
        assert json.loads(rec.read_text())["selected_labels"] == labels



def test_a_wedged_worker_is_stopped_and_the_reason_is_named(tmp_path):
    """A job that has STOPPED is reaped, and the refusal says how that was seen.

    Not "it took too long" — every readable signal sat still, `_LOOKS` times
    running. The distinction is the whole of vibe-ic#2051 and it has to survive
    into the message a reader gets.
    """
    rec = tmp_path / "wedged.json"
    specs = [(0, ["a planted gate that sleeps forever"], rec,
              [sys.executable, "-c", _WEDGED])]
    started = time.monotonic()
    rows = G.run_workers_supervised(specs, 1, run_fn=_fast)
    elapsed = time.monotonic() - started

    assert len(rows) == 1
    i, labels, json_path, rc, _out, _err, stall = rows[0]
    assert rc is None and stall, (
        f"the wedged worker came back rc={rc!r} with stall={stall!r}; a child "
        f"asleep for ten hours has stopped, and a supervisor that did not "
        f"notice is not supervising")
    assert "STALLED" in stall and "signals" in stall, (
        f"the refusal does not say WHAT was seen: {stall}")
    assert "idle" in stall and "grace" in stall, (
        f"the refusal does not say how long the job had shown nothing, of what "
        f"grace: {stall}")
    assert "across 0 consecutive looks" not in stall, (
        f"the refusal describes an observation nobody made: {stall}")
    assert not json_path.is_file(), (
        "a stopped worker wrote a machine record, so it was not wedged and "
        "this arm is measuring something else")
    assert elapsed >= _STALL_WINDOW_S, (
        f"the supervisor returned after {elapsed:.2f}s, inside its own "
        f"{_STALL_WINDOW_S:.2f}s window — it did not spend the looks it claims")


def test_a_slow_but_progressing_worker_is_never_stopped(tmp_path):
    """The 646 s gate, in miniature: quiet, CPU-bound, far past the window.

    THIS IS THE ARM THE OLD DEADLINE FAILED. It produces no output at all until
    it is finished, so only the CPU signal keeps it alive — which is exactly the
    signal `_watchdog`'s own docstring says a "CPU-bound-but-quiet phase" needs.
    """
    rec = tmp_path / "slow.json"
    specs = [(0, ["a slow but progressing gate"], rec,
              [sys.executable, "-c", _PROGRESSING, str(rec),
               str(_PROGRESSING_S), "a slow but progressing gate"])]
    started = time.monotonic()
    rows = G.run_workers_supervised(specs, 1, run_fn=_fast)
    elapsed = time.monotonic() - started

    i, labels, json_path, rc, _out, _err, stall = rows[0]
    assert not stall, (
        f"a worker that burned CPU for {_PROGRESSING_S}s — "
        f"{_PROGRESSING_S / _STALL_WINDOW_S:.0f}x the {_STALL_WINDOW_S:.2f}s "
        f"stall window — was stopped anyway: {stall}. That is the deadline "
        f"back under another name.")
    assert rc == 0, f"the progressing worker exited {rc}"
    assert json_path.is_file()
    assert json.loads(json_path.read_text())["selected_labels"] == labels
    assert elapsed >= _PROGRESSING_S, (
        f"the arm returned in {elapsed:.2f}s but the child was asked for "
        f"{_PROGRESSING_S}s of work; it did not run, so nothing was proved")


def test_the_same_supervisor_at_one_cadence_tells_the_two_apart(tmp_path):
    """BOTH DIRECTIONS IN ONE CALL — the arm that makes the two above evidence.

    Separately, each is consistent with a supervisor that always stops, or one
    that never does, plus a coincidence. Handed to ONE pool at ONE cadence, a
    supervisor that cannot discriminate must get one of them wrong.
    """
    wedged_rec = tmp_path / "w.json"
    slow_rec = tmp_path / "s.json"
    specs = [
        (0, ["a planted gate that sleeps forever"], wedged_rec,
         [sys.executable, "-c", _WEDGED]),
        (1, ["a slow but progressing gate"], slow_rec,
         [sys.executable, "-c", _PROGRESSING, str(slow_rec),
          str(_PROGRESSING_S), "a slow but progressing gate"]),
    ]
    rows = G.run_workers_supervised(specs, 2, run_fn=_fast)

    assert [r[0] for r in rows] == [0, 1], (
        f"rows came back as {[r[0] for r in rows]}; one row per spec, in index "
        f"order, is what makes the caller's completeness check a membership "
        f"check")
    wedged, slow = rows
    assert wedged[6] and wedged[3] is None, (
        f"the wedged worker survived: rc={wedged[3]!r} stall={wedged[6]!r}")
    assert not slow[6] and slow[3] == 0, (
        f"the progressing worker was stopped: rc={slow[3]!r} "
        f"stall={slow[6]!r}")
    assert not wedged_rec.is_file() and slow_rec.is_file(), (
        "the two arms did not leave opposite records, so the pool did not "
        "actually run them differently")


#: A child that is silent, burns no measurable CPU and does no block I/O — the
#: shape of a worker QUEUED on the single-holder checkout claim — but which
#: appends one earned line to the progress channel while it waits.
_QUEUED_BUT_TALKING = """
import os, sys, time
ch = os.environ.get("VIBEIC_HOSTINDEP_WORKER_PROGRESS", "")
t = time.monotonic()
while time.monotonic() - t < float(sys.argv[1]):
    time.sleep(0.3)
    if ch:
        open(ch, "a").write("claim: still queued\\n")
"""

#: The same child with the channel taken away: it does nothing observable at all.
_QUEUED_AND_SILENT = """
import sys, time
t = time.monotonic()
while time.monotonic() - t < float(sys.argv[1]):
    time.sleep(0.3)
"""


def test_a_worker_queued_on_the_claim_is_not_mistaken_for_a_wedged_one(tmp_path):
    """THE REGRESSION THIS CHANNEL EXISTS FOR, both directions in one file.

    MEASURED on 8hd-3 at f3e5bd985, the real gate at `--jobs 8`, supervised on
    the GENERIC signals alone: three of eight workers were reaped as stalled and
    every one of them was working correctly — worker 0 at 645.1 s carrying the
    646 s gate, worker 2 at 810.1 s, worker 5 at 210.0 s, all three with
    `signals readable: cpu,io,output`. The checkout claim is a single-holder
    `flock` polled every 0.25 s, so seven of eight workers are queued at any
    moment: silent, no block I/O, and four syscalls a second is under one clock
    tick. A process correctly waiting on a lock and a wedged one are the same
    picture to every generic signal there is.

    So the two arms here differ in ONE thing — whether the child says it is
    still queued — and they must come back with opposite verdicts.
    """
    idle_s = _STALL_WINDOW_S * 5

    talking = tmp_path / "talking.json"
    rows = G.run_workers_supervised(
        [(0, ["queued but reporting"], talking,
          [sys.executable, "-c", _QUEUED_BUT_TALKING, str(idle_s)])],
        1, run_fn=_fast)
    assert not rows[0][6], (
        f"a worker that was queued for {idle_s:.1f}s — "
        f"{idle_s / _STALL_WINDOW_S:.0f}x the window — and SAID SO on the "
        f"progress channel was still reaped: {rows[0][6]}. That is the "
        f"measured regression, unfixed.")

    silent = tmp_path / "silent.json"
    rows = G.run_workers_supervised(
        [(0, ["queued and silent"], silent,
          [sys.executable, "-c", _QUEUED_AND_SILENT, str(idle_s)])],
        1, run_fn=_fast)
    assert rows[0][6], (
        "the SAME shape with the channel taken away was NOT reaped, so the "
        "channel is not what kept the first arm alive and this test proves "
        "nothing about it")


def test_the_deleted_wall_clock_kill_would_lose_the_record(tmp_path):
    """THE NEGATIVE ARM: the pre-fix wait, on the same children, must lose it.

    This is the code that was removed from ``parallel_audit``, rebuilt verbatim
    in shape. If it does NOT lose the record, then the budget above never fires
    against these children and the positive test could not have failed either —
    a check that cannot fail is not a check.
    """
    procs = [(i, [f"label-{i}"], tmp_path / f"worker-{i}.json",
              subprocess.Popen(
                  [sys.executable, "-c", _WORKER,
                   str(tmp_path / f"worker-{i}.json"), str(_WORKER_SECONDS),
                   f"label-{i}"],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
             for i in range(3)]

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


def test_the_shipped_wait_carries_no_seconds_parameter_at_all(tmp_path):
    """A budget of PROCESSES, never of seconds — asserted on the interface.

    `jobs` is a pool width. `run_fn` is an observation CADENCE seam and
    `_progress_run` is explicit that it is safe in the only direction that
    matters: "sampling more often never kills a working job sooner". Neither is
    a duration a worker's life depends on, and there is no third parameter.
    """
    import inspect
    params = set(inspect.signature(G.run_workers_supervised).parameters)
    assert params == {"specs", "jobs", "run_fn"}, (
        f"run_workers_supervised takes {sorted(params)}. `jobs` is a budget of "
        f"PROCESSES and is the only budget this launcher may have; a seconds "
        f"parameter is the deadline this file exists to keep out.")
    procs = _launch(tmp_path, 1)
    rows = G.run_workers_supervised(procs, jobs=1)
    assert rows[0][3] == 0 and rows[0][2].is_file() and not rows[0][6]


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
    # AttributeError about a function it has never heard of.
    # `run_workers_supervised` is included when present and is not required.
    owners = {n.name: n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name in ("run_workers_supervised", "parallel_audit")}
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
        "            cp = launch(argv, progress_path)\n",
        "            proc = subprocess.Popen(argv)\n"
        "            try:\n"
        "                out, err = proc.communicate(timeout=600)\n"
        "            except subprocess.TimeoutExpired:\n"
        "                proc.kill()\n"
        "                out, err = proc.communicate()\n"
        "            cp = subprocess.CompletedProcess(argv, proc.returncode,\n"
        "                                             out, err)\n",
        1)
    assert mutated != src, (
        "the mutation did not apply — the launch no longer has the shape this "
        "arm knows how to break, so it is proving nothing about the check")

    fn = next(n for n in ast.walk(ast.parse(mutated))
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_workers_supervised")
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
