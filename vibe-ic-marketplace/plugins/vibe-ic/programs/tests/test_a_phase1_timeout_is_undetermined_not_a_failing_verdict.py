#!/usr/bin/env python3
"""test_a_phase1_producer_is_bounded_by_progress_not_by_a_clock.py (kept at its
original filename so the nodeids in the census do not move).

THE DEFECT. `phase1_one_shot_runner` dispatched its expert track and its two
step-0.5ic producers under `subprocess.run(..., timeout=600)` and, when the
bound fired, printed the right diagnosis —

    "a timeout is not a verdict, and an unevaluated track cannot pass"

— and returned a failure. The first attempt at this fixed the SENTENCE, moving
the exit code to the repo's rc 2 UNDETERMINED. THAT WAS THE WRONG FIX AND IT IS
RETRACTED: a timeout that returns NOT_MEASURED still kills a track that was one
second from finishing. It stops lying about why and leaves the behaviour just as
broken. Ending work because a clock expired does not make sense at any label.

THE KILL WAS THE DEFECT. These sites now run under `_watchdog.run_host_supervised`,
which bounds NO PROGRESS and never runtime: CPU (`utime+stime`) and I/O
(`read_bytes+write_bytes`) are read out of `/proc` across the whole process tree,
and the captured output is watched for growth. Any signal moving resets the
grace. So:

  * a producer that is WORKING runs to completion however long that takes, and a
    fast host and a loaded host give the same answer about the same design;
  * a producer whose entire tree is idle across the grace is STALLED — which is
    a MEASURED finding about the producer, with evidence, and therefore a real
    verdict rather than a shrug.

600 is now the STALL GRACE, not a runtime. It can only ever kill LESS than the
old bound: every job the old bound let through, this lets through, plus every
job that was still working at 600 s.

No design, PDK, vendor or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_phase1_timeout_is_undetermined_not_a_failing_verdict.py -q
"""
from __future__ import annotations

import subprocess
import sys
import time
import unittest.mock as mock
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_one_shot_runner as R              # noqa: E402
import _watchdog as W                           # noqa: E402


def _project(tmp_path: Path, name: str = "proj") -> Path:
    p = tmp_path / name
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "reports").mkdir(parents=True)
    return p


def _programs_dir_running(tmp_path: Path, body: str) -> Path:
    """A PROGRAMS_DIR whose expert track is a real program with `body`."""
    d = tmp_path / "programs"
    d.mkdir()
    (d / R._EXPERT_TRACK).write_text(body, encoding="utf-8")
    return d


# ── direction 1: a slow-but-working producer is no longer killed ────────────

def test_a_track_that_is_working_outlives_its_old_bound(tmp_path, monkeypatch):
    """THE FIX, and the half the retracted version did not deliver.

    The subject runs far past the grace it is given and is NEVER stopped,
    because it is burning CPU and writing the whole time. Under
    `subprocess.run(timeout=N)` — and equally under a version of that which
    merely relabels the kill — it is dead at N with Phase 1 reporting a failure
    about a design nothing examined.
    """
    monkeypatch.setattr(R, "_TRACK_STALL_GRACE_S", 1)
    p = _project(tmp_path)
    report = R._pl.report_path(p, "phase1/expert_parse_track.json")
    body = (
        "import json, pathlib, sys, time\n"
        "end = time.monotonic() + 3.0\n"
        "x = 0\n"
        "while time.monotonic() < end:\n"
        "    x += 1\n"                       # CPU: the tree is progressing
        "    if x % 200000 == 0:\n"
        "        print('still working', flush=True)\n"   # and so is the output
        f"p = pathlib.Path({str(report)!r})\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text(json.dumps({'verdict': 'PASS', 'findings': []}))\n"
        "sys.exit(0)\n")
    started = time.monotonic()
    with mock.patch.object(R, "PROGRAMS_DIR", _programs_dir_running(tmp_path, body)):
        rc = R._run_expert_track(p)
    took = time.monotonic() - started
    assert rc == 0, "a track that finished cleanly was not credited"
    # NON-VACUITY: it really did outlive the grace it was given, so this is not
    # passing because the subject happened to be fast.
    assert took > 2.0, (
        f"the track finished in {took:.1f}s against a 1s grace — it never "
        f"outlived the bound, so this proves nothing")


# ── direction 2: a genuinely wedged producer is still caught ───────────────

def test_a_track_that_is_doing_nothing_is_still_stopped(tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE. Idle and silent across the whole grace,
    process still alive: STALLED, stopped, and Phase 1 still refuses. A guard
    that stopped refusing would be a deletion, not a fix."""
    monkeypatch.setattr(R, "_TRACK_STALL_GRACE_S", 1)
    p = _project(tmp_path)
    body = "import time\ntime.sleep(600)\n"
    started = time.monotonic()
    with mock.patch.object(R, "PROGRAMS_DIR", _programs_dir_running(tmp_path, body)):
        rc = R._run_expert_track(p)
    took = time.monotonic() - started
    assert rc != 0, "a wedged track reported a clean run"
    assert took < 60, (
        f"the wedged track took {took:.0f}s to be noticed — the watchdog is "
        f"not sampling inside its own grace")


def test_the_stall_is_reported_as_a_measurement_not_as_a_clock(
        tmp_path, monkeypatch, capsys):
    """A real verdict, with evidence. "timed out after 600s" is equally
    reachable by a correct track on a busy host; "no CPU, no I/O and no output
    across the grace" is not."""
    monkeypatch.setattr(R, "_TRACK_STALL_GRACE_S", 1)
    p = _project(tmp_path)
    with mock.patch.object(R, "PROGRAMS_DIR",
                           _programs_dir_running(tmp_path, "import time\ntime.sleep(600)\n")):
        R._run_expert_track(p)
    err = capsys.readouterr().err
    assert "STALLED" in err, err
    assert "no forward progress" in err, err
    assert "It was not slow; it was doing nothing." in err, err
    assert "timed out" not in err, (
        "the clock sentence is still being published as the reason")


def test_the_step_0_5ic_producers_get_the_same_supervision(tmp_path, monkeypatch):
    """The second site, asserted separately — the fix was applied twice and a
    correct handler in an unreached branch is not a fix."""
    monkeypatch.setattr(R, "_TRACK_STALL_GRACE_S", 1)
    p = _project(tmp_path)
    calls = []

    def _stalled(argv, **kw):
        calls.append(argv)
        return W.SupervisedResult(
            rc=W.RC_STALLED, out="", err="WATCHDOG_STALLED", outcome="stalled",
            elapsed_s=1.0)

    monkeypatch.setattr(R._wd, "run_host_supervised", _stalled)
    rc = R._run_step_0_5ic(p)
    assert rc != 0, "an undispatched route producer reported a clean run"
    assert calls, "the producer was never dispatched through the supervisor"


# ── the shape of the change, asserted so it cannot quietly regress ──────────

def test_no_runtime_bound_remains_at_either_dispatch_site():
    """Both sites must be supervised, and neither may carry a `timeout=`.

    Read from source rather than behaviour because the failure mode being
    guarded is a future edit putting one back — a `subprocess.run(timeout=N)`
    added beside the supervisor would pass every behavioural test above while
    reintroducing exactly the defect.
    """
    import ast
    src = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # AST, NOT grep. The first draft of this check searched the source text for
    # `timeout=600` and matched the COMMENT above the grace constant, which
    # quotes the call it replaced — a published selector matching its own
    # published copy. The question is whether a CALL passes a runtime bound, and
    # only the tree can answer it.
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = (f.attr if isinstance(f, ast.Attribute) else
                getattr(f, "id", ""))
        if name not in ("run", "check_output", "call", "Popen"):
            continue
        if any(k.arg == "timeout" for k in node.keywords):
            offenders.append(getattr(node, "lineno", "?"))
    assert offenders == [], (
        f"a runtime bound is back on a subprocess call at line(s) {offenders} "
        f"— the kill is the defect, and a bigger constant is the same defect "
        f"restated")
    assert src.count("run_host_supervised") >= 2, (
        "one of the two dispatch sites is not supervised")
    assert "_TRACK_STALL_GRACE_S" in src


def test_the_grace_can_only_kill_less_than_the_bound_it_replaced():
    """The safety argument for reusing 600, stated as a test.

    A stall grace of N kills a strict subset of what a runtime bound of N kills:
    both stop a job idle for N, and only the runtime bound stops a job that is
    working at N. So no job that used to complete can start failing.
    """
    assert R._TRACK_STALL_GRACE_S == 600, (
        "the grace moved; re-check that it is still >= the runtime bound it "
        "replaced, or this argument no longer holds")


# ── the retraction itself ──────────────────────────────────────────────────

def test_the_not_measured_relabel_is_gone(tmp_path):
    """THE RETRACTION, pinned.

    An earlier version of this fix converted the expiry to rc 2 UNDETERMINED and
    left the 600 s kill in place. That is the last-resort shape, used as a first
    resort, and it destroys work that was progressing while reporting honestly
    that it did so. Nothing here may reintroduce it.
    """
    assert not hasattr(R, "RC_UNDETERMINED"), (
        "the relabel machinery is back; the kill is the defect, not the label")
    assert not hasattr(R, "_delegated_verdict")
    src = Path(R.__file__).read_text(encoding="utf-8")
    assert "NOT MEASURED" not in src, (
        "a NOT_MEASURED verdict is being produced by a bound firing again")
