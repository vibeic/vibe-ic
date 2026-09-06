#!/usr/bin/env python3
"""vibe-ic#2051 — `hard_ceiling_s` records a budget; it never stops a job.

THE MEASUREMENT THAT FORCED THE RULING. 2026-09-06 on 8HD-9, two sha256 LEC
yosys runs were live under `timeout --kill-after=5 86395`, wrapped there by
`run_docker_supervised` at `DEFAULT_HARD_CEILING_S`. One of them was 5360 s into
a post-layout proof with 1374 points proved, 0 failed, 99.9 % CPU and still
advancing. Had the clock reached it, the tool would have been SIGKILLed inside
the container and the run booked `RC_CEILING` / `status: "hard_ceiling"` — a
statement about elapsed time, recorded in the field a reader consults for a
statement about the design. The owner ruled: the 24 h ceiling RECORDS and
NOTIFIES, and only the progress-stall watchdog may kill.

This file drives the docker-side half of that: the record, the notice, the
absence of a kill, and — the control that makes the rest mean anything — that a
run which never reaches the budget grows none of it.

`_watchdog`'s own half (the supervision loop, the once-only notice, and the
stall still firing AFTER a crossing) is in `test_watchdog.py`; the shape of the
command sent into the container, and the process-group teardown that used to
ride on the removed `timeout`, are in `test_docker_exec_timeout_orphan.py`.

chip/tool-AGNOSTIC: a `sleep`/`echo` child and a stub raw-exec. No IC, PDK or
vendor anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _docker_watchdog as DW  # noqa: E402
import _watchdog as W  # noqa: E402


def _raw(_container, _cmd, timeout=15):
    """A raw exec that can answer nothing. Deliberate: with no CPU reading the
    supervision rests on captured output alone, so a test that keeps a child
    alive has kept it alive on a signal it can name."""
    return 1, "", ""


def _run(tmp_path, *, cmd, ceiling, sidecar=True, notice_sink=None):
    side = (tmp_path / "telemetry.json") if sidecar else None
    kw = {}
    if notice_sink is not None:
        kw["ceiling_notice"] = notice_sink.append
    rc, out, err = DW.run_docker_supervised(
        "host", cmd, "marker-unused",
        docker_exec_raw=_raw, telemetry_path=side,
        telemetry_context={"invocation_id": "inv", "attempt": 1},
        stall_grace_s=30.0, poll_s=0.2, hard_ceiling_s=ceiling, **kw)
    doc = json.loads(side.read_text(encoding="utf-8")) if side else None
    return rc, out, err, doc


# ---------------------------------------------------------------------------
# THE RULING
# ---------------------------------------------------------------------------

def test_a_progressing_job_crosses_the_budget_and_finishes(tmp_path, capfd):
    """A REAL child that runs ~2.5 s against a 0.5 s budget, printing as it
    goes. Before #2051 this was `timeout --kill-after=5` at the budget and the
    child died with no verdict; it must now run to its own natural exit.
    """
    notices = []
    child = ("for i in 1 2 3 4 5; do echo tick $i; sleep 0.5; done; "
             "echo DONE; exit 0")
    rc, out, err, doc = _run(tmp_path, cmd=child, ceiling=0.5,
                             notice_sink=notices)

    assert rc == 0, (rc, err)
    assert "DONE" in out, out
    # NOT stopped, and not relabelled as stopped.
    assert rc != W.RC_CEILING and rc != W.RC_STALLED
    assert doc["status"] == "complete", doc["status"]
    assert "WATCHDOG_CEILING" not in err, err

    # RECORDED — in the sidecar, beside the run's own numbers.
    assert doc["hard_ceiling_exceeded"] is True, doc
    events = [e for e in doc.get("events", [])
              if e.get("event") == "hard_ceiling"]
    assert len(events) == 1, doc.get("events")
    assert events[0]["budget_sec"] == 0.5
    assert events[0]["action"] == "recorded_and_continued"
    assert events[0]["elapsed_sec"] >= 0.5
    assert doc["attempts"][-1]["budget_exceeded_sec"] >= 0.5

    # NOTIFIED — on the caller's hook, and on stderr for a caller with no hook.
    assert len(notices) == 1, notices
    assert notices[0]["event"] == "hard_ceiling"
    assert "WATCHDOG_HARD_CEILING" in capfd.readouterr().err


def test_a_run_inside_its_budget_records_nothing(tmp_path, capfd):
    """THE CONTROL. Every assertion above would also hold on an implementation
    that stamped the crossing unconditionally and had never read the clock."""
    notices = []
    rc, out, err, doc = _run(tmp_path, cmd="echo quick; exit 0",
                             ceiling=3600.0, notice_sink=notices)
    assert rc == 0 and "quick" in out
    assert doc["status"] == "complete"
    assert "hard_ceiling_exceeded" not in doc, doc
    assert doc.get("events", []) == []
    assert "budget_exceeded_sec" not in doc["attempts"][-1]
    assert notices == []
    assert "WATCHDOG_HARD_CEILING" not in capfd.readouterr().err


def test_a_tool_that_exits_124_itself_is_not_relabelled_as_a_ceiling(tmp_path):
    """`status` says what WE did to a run, so it may not put our vocabulary on
    the tool's own verdict.

    rc 124 used to mean "our ceiling killed it", and `run_docker_supervised`
    mapped it to `status: "hard_ceiling"`. Nothing here kills on a clock any
    more, so a 124 can now only be the tool's own exit — from a `timeout` the
    USER wrote, or a program that simply returns 124 — and calling that a
    hard_ceiling would manufacture a stop that never happened.
    """
    rc, _out, _err, doc = _run(tmp_path, cmd="echo bye; exit 124",
                               ceiling=3600.0)
    assert rc == 124
    assert doc["status"] == "complete", doc["status"]
    assert doc["returncode"] == 124
    assert "hard_ceiling_exceeded" not in doc


def test_a_broken_notifier_cannot_take_the_job_down(tmp_path):
    """A notification that could kill the run it reports on would be this whole
    defect wearing new clothes."""
    def explode(_record):
        raise RuntimeError("the dashboard is down")

    rc, out, _err = DW.run_docker_supervised(
        "host", "echo alive; sleep 1.2; echo DONE; exit 0", "marker-unused",
        docker_exec_raw=_raw, telemetry_path=(tmp_path / "t.json"),
        telemetry_context={"invocation_id": "inv", "attempt": 1},
        stall_grace_s=30.0, poll_s=0.2, hard_ceiling_s=0.4,
        ceiling_notice=explode)
    assert rc == 0, out
    assert "DONE" in out
    side = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert side["hard_ceiling_exceeded"] is True
    assert side["status"] == "complete"


def test_a_run_with_no_sidecar_still_says_it_went_over(tmp_path, capfd):
    """`telemetry_path=None` is the common case for most callers. The crossing
    must not become an unmeasured thing that reads as a measured zero just
    because nobody wired a sidecar — stderr is the second channel for exactly
    that reason."""
    rc, _out, _err = DW.run_docker_supervised(
        "host", "echo a; sleep 1.0; exit 0", "marker-unused",
        docker_exec_raw=_raw, stall_grace_s=30.0, poll_s=0.2,
        hard_ceiling_s=0.3)
    assert rc == 0
    assert "WATCHDOG_HARD_CEILING" in capfd.readouterr().err


# ---------------------------------------------------------------------------
# THE OTHER KILL IS UNTOUCHED — this landing removed one, not both
# ---------------------------------------------------------------------------

def test_a_silent_idle_job_is_still_reaped_by_the_stall(tmp_path):
    """The stall path must be byte-identical in BEHAVIOUR. A child that emits
    one line and then goes silent and idle is killed as hung, at the grace and
    not at any budget — the budget here is an hour and never reached.
    """
    killed = []
    real_kill = DW.kill_supervised_job

    def spy(*a, **kw):
        killed.append(a)
        return real_kill(*a, **kw)

    DW.kill_supervised_job = spy
    try:
        rc, _out, err = DW.run_docker_supervised(
            "host", "echo start; sleep 30", "marker-unused",
            docker_exec_raw=_raw, stall_grace_s=1.0, poll_s=0.25,
            hard_ceiling_s=3600.0)
    finally:
        DW.kill_supervised_job = real_kill

    assert rc == W.RC_STALLED, (rc, err)
    assert "WATCHDOG_STALLED" in err, err
    assert killed, "the stall did not reach the identity-anchored reap"


def test_an_unbounded_budget_is_now_expressible_at_all(tmp_path):
    """A LATENT CRASH the wrap removal takes with it, pinned so it stays gone.

    `wrap_with_container_timeout` computes `max(1, int(timeout_s) - margin_s)`,
    and `int(float("inf"))` raises OverflowError. The supervised path fed
    `hard_ceiling_s` straight into that call, so
    `run_docker_supervised(..., hard_ceiling_s=float("inf"))` — the spelling
    three other callers of `run_supervised` already use to say "no budget
    claimed" — could not be written here at all. MEASURED on both trees
    2026-09-07: the base raises `OverflowError: cannot convert float infinity
    to integer`; this branch runs.

    It matters beyond tidiness. `float("inf")` is the honest way to say a job's
    length is not knowable in advance, and a primitive that crashed on it
    pushed callers toward writing a finite number they did not mean — which is
    how a budget nobody believed in became a kill.
    """
    rc, out, _err = DW.run_docker_supervised(
        "host", "echo unbounded; exit 0", "marker-unused",
        docker_exec_raw=_raw, stall_grace_s=30.0, poll_s=0.2,
        hard_ceiling_s=float("inf"))
    assert rc == 0, out
    assert "unbounded" in out

    # The wrap itself is UNCHANGED and still cannot take an infinite deadline —
    # which is correct there: it exists to fire BEFORE a finite host bound, so
    # an infinite one is not a thing it can express. The supervised path simply
    # no longer asks it to.
    with pytest.raises(OverflowError):
        DW.wrap_with_container_timeout("x", float("inf"))
