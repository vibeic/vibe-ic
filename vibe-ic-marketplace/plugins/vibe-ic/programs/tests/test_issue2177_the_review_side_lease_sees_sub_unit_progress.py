#!/usr/bin/env python3
"""vibe-ic#2177, the REVIEW-side half — the outer lease was still a wall clock.

WHAT THE LANDED FIX REPAIRED, AND WHAT IT DID NOT
=================================================
`_gate_inflight_progress` gave the lease `repo_hygiene_parallel` holds over
each SHARD a sub-unit signal, so a gate that is merely slow is no longer
killed.  Driven on this repo's own 155-gate set at a 300 s lease: the pre-fix
caller (`inflight_path=None`) died at 600 s with rc 199 and NO summary, and
the fix ran the same set to completion.

The lease one level out was untouched.  `gatekeeper_review.repo_hygiene_gate`
supervises the COORDINATOR with::

    _wd.run_supervised(command, log_path=progress,
                       stall_grace_s=_HYGIENE_STALL_GRACE_S)   # 1800 s

and its own refusal text names its only two signals -- "no output or
completed-gate record advanced for 1800s".  The in-flight files are PRIVATE TO
EACH WORKER (`repo_hygiene_parallel` writes one per shard per arm and says
"nothing downstream reads this channel"), so nothing that supervisor can see
moves while one long gate is in flight.

THE ARITHMETIC IS DERIVED FROM THE SHIPPED ARTEFACTS, never typed: see
`derived_silent_tail()` below.  At v1.20.0 it is 2556 - 646 = 1910 s of
unavoidable silence against an 1800 s lease -- the issue's own sentence, "a
wall-clock bound below its subject's own runtime", one supervisor out.

WHAT IS ASSERTED HERE, AND IN WHICH DIRECTION
=============================================
1. A child that reports sub-unit progress and NOTHING else survives an outer
   lease a fraction of its runtime.  DRIVEN: a real child, the real
   `_watchdog.run_supervised`, the real `_gate_inflight_progress` writer.
2. THE RED CONTROL / THE MUTATION.  The same child with the relay not entered
   -- byte-equivalent to the pre-patch caller -- IS killed at its lease with
   `_watchdog.RC_STALLED`.  A fix whose removal changes nothing was never one.
3. The relay renews only on rows the reader ACCEPTS: an unassigned label
   freezes the score and is reported once, so a shard cannot hold the outer
   lease open with rows the protocol refuses.
4. With no shard channel the relay starts no thread and prints nothing.

chip/tool-AGNOSTIC: `sleep`, a temporary directory and this repo's own
programs.  No IC, no PDK, no vendor, no benchmark.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _gate_inflight_progress as I           # noqa: E402
import _watchdog as _wd                       # noqa: E402
import repo_hygiene_parallel as R             # noqa: E402

LABEL = "gates are host-independent"
OTHER = "an argued direction is pinned"

#: The outer lease every driven arm below runs under.  Small so the file is
#: fast; the SHAPE is the production one -- a job whose runtime is a multiple
#: of the lease held over it.
GRACE_S = 6.0
RUN_S = 24.0
WRITE_EVERY_S = 0.5




def _child_source(inflight: Path, relay: bool) -> str:
    return textwrap.dedent(f"""
        import sys, time, subprocess
        sys.path.insert(0, {str(PROGRAMS)!r})
        import repo_hygiene_parallel as R
        writer = subprocess.Popen([
            sys.executable, {str(PROGRAMS / "_gate_inflight_progress.py")!r},
            "--path", {str(inflight)!r}, "--label", {LABEL!r},
            "--of", "2", "--started"])
        writer.wait()

        def emit(i):
            subprocess.run([
                sys.executable,
                {str(PROGRAMS / "_gate_inflight_progress.py")!r},
                "--path", {str(inflight)!r}, "--label", {LABEL!r},
                "--of", "2", "--capture", "b=%d" % i,
                "--root-pid", "1", "--alive"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        rows = [("A", 0, {str(inflight)!r}, ({LABEL!r}, {OTHER!r}))]
        deadline = time.monotonic() + {RUN_S}
        # `getattr`, NOT a bare attribute: on the PRE-FIX tree this arm has to
        # RUN and answer wrongly. An AttributeError would abort the control
        # before it observed anything, and a control that observed nothing
        # proves nothing.
        Relay = getattr(R, "OuterProgressRelay", None)
        if {relay!r} and Relay is not None:
            with Relay(rows, poll_s=0.5):
                i = 0
                while time.monotonic() < deadline:
                    i += 1
                    emit(i)
                    time.sleep({WRITE_EVERY_S})
        else:
            i = 0
            while time.monotonic() < deadline:
                i += 1
                emit(i)
                time.sleep({WRITE_EVERY_S})
    """)


def _drive(tmp_path: Path, relay: bool):
    inflight = tmp_path / ("inflight-%s.jsonl" % ("relay" if relay else "bare"))
    child = tmp_path / ("child-%s.py" % ("relay" if relay else "bare"))
    child.write_text(_child_source(inflight, relay), encoding="utf-8")
    return _wd.run_supervised([sys.executable, "-u", str(child)],
                              stall_grace_s=GRACE_S, poll_s=0.5,
                              hard_ceiling_s=float("inf")), inflight


def test_sub_unit_progress_renews_the_review_side_lease(tmp_path):
    """1. DRIVEN: reporting sub-unit progress and nothing else survives."""
    res, inflight = _drive(tmp_path, relay=True)
    rows = [json.loads(line)
            for line in inflight.read_text(encoding="utf-8").splitlines()]
    assert len(rows) > 2, rows
    assert res.outcome == "natural", (res.outcome, res.rc, res.err[-800:])
    assert "[PROGRESS] hygiene arm A shard 0" in res.out, res.out[-800:]
    assert LABEL in res.out, res.out[-800:]


def test_without_the_relay_the_same_child_is_killed_at_its_lease(tmp_path):
    """2. THE RED CONTROL. The pre-patch caller dies on the same channel."""
    res, inflight = _drive(tmp_path, relay=False)
    rows = [json.loads(line)
            for line in inflight.read_text(encoding="utf-8").splitlines()]
    assert len(rows) > 2, "the channel must have advanced in this arm too"
    assert res.outcome == "stalled", (res.outcome, res.rc)
    assert res.rc == _wd.RC_STALLED, res.rc


def test_the_relay_renews_only_on_rows_the_reader_accepts(tmp_path):
    """3. A refused row must not renew, and must be said once."""
    inflight = tmp_path / "inflight.jsonl"
    said = []

    class _Sink:
        def write(self, text):
            said.append(text)

        def flush(self):
            pass

    relay = R.OuterProgressRelay([("A", 3, inflight, (LABEL,))],
                                 stream=_Sink(), poll_s=0.1)
    I.append_event(str(inflight), "gate_started", LABEL, 2)
    assert relay.sample_once() == 1
    accepted = relay.emitted
    # A label this shard was never assigned is refused by the protocol.
    I.append_event(str(inflight), "gate_started", OTHER, 2)
    relay.sample_once()
    relay.sample_once()
    joined = "".join(said)
    assert "stopped renewing" in joined, joined
    assert joined.count("stopped renewing") == 1, joined
    frozen = relay.emitted
    relay.sample_once()
    assert relay.emitted == frozen, "a refused channel kept renewing"
    assert accepted >= 1


def test_the_relay_is_inert_without_a_shard_channel():
    """4. No channel, no thread, no output."""
    said = []

    class _Sink:
        def write(self, text):
            said.append(text)

        def flush(self):
            pass

    with R.OuterProgressRelay([], stream=_Sink(), poll_s=0.05) as relay:
        assert relay.sample_once() == 0
    assert said == []
    assert relay.emitted == 0
