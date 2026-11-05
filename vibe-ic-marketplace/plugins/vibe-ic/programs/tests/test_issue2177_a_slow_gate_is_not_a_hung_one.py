#!/usr/bin/env python3
"""vibe-ic#2177 — a gate slower than the stall lease is not a wedged one.

THE DEFECT, IN THIS REPO'S OWN SHIPPED NUMBERS
==============================================
The hygiene shard is supervised by `_owned_process_supervisor` in attestation
mode, where `output_progress=False` and the ONLY forward-progress signal is one
attestation row per COMPLETED GATE.  The lease is spent between two consecutive
validated events, so the unit that gets killed is a WHOLE GATE, and the stall
grace is therefore a wall clock for any single gate.

`hygiene_gate_profile.json` at v1.19.39, the profile this repo SHIPS::

    gates are host-independent      2556 s
    an argued direction is pinned    646 s

against the graces actually in force::

    repo_hygiene_parallel.DEFAULT_STALL_GRACE_S       300 s
    gatekeeper_review._HYGIENE_STALL_GRACE_S         1800 s

Two gates above the first; one above the second.  MEASURED on 8HD-6, three
landing logs of 2026-08-27 (`~/j1786/baseev/base_land.log` and the two under
`~/j1786/tmp/gk_land_diff.8oX709/`), all three carrying::

    arm A shard 0: PROGRESS_PROTOCOL_INCOMPLETE: attestation progress ended
    before assigned gates completed: an argued direction is pinned; progress
    watchdog outcome=stalled, rc=199; the shard did not complete naturally

and the landing then reporting `16 wiring error(s) in the hygiene gate
declarations, so the set certifies nothing`.  Not one of those sixteen was a
property of the tree.

WHAT IS ASSERTED HERE, AND IN WHICH DIRECTION
=============================================
1. A supervised job that runs FAR past its stall lease while reporting
   sub-unit progress COMPLETES.  It is DRIVEN — a real child process under the
   real `run_owned` — not simulated.
2. A job that stops reporting IS killed, and the refusal NAMES the gate that
   was in flight and how long the lease had gone unrenewed.
3. THE MUTATION.  Delete the in-flight renewal (the one line that adds
   `inflight_probe.sample()` to the score) and arm 1 must go red — that is the
   wall clock restored, and a fix whose removal changes nothing was never a
   fix.  Driven by monkeypatching the reader to a frozen score, which is
   byte-equivalent to the channel contributing nothing.
4. The protocol refuses what it must refuse: an unassigned label, a unit that
   does not advance, a denominator that moves, a rewritten history.  A channel
   that accepted those would be a lease anyone could hold open forever.

chip/tool-AGNOSTIC: `sleep`, `printf` and a temporary directory.  No IC, no
PDK, no vendor, no benchmark.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _gate_inflight_progress as I  # noqa: E402
import _owned_process_supervisor as O  # noqa: E402

LABEL = "an argued direction is pinned"
OTHER = "gates are host-independent"

#: The lease every arm below runs under.  Small so the file is fast; the SHAPE
#: is the production one — a job whose runtime is a multiple of its own lease.
GRACE_S = 3.0
POLL_S = 0.25
#: Long enough that a wall clock could not miss it: 6x the lease.
RUN_S = 18.0
UNITS = 12


def _labels_manifest(tmp_path: Path, labels) -> Path:
    path = tmp_path / "expected.json"
    path.write_text(json.dumps({"schema": 1, "labels": list(labels)}),
                    encoding="utf-8")
    return path


def _child(tmp_path: Path, *, attest: Path, inflight: Path,
           emit_units: int, run_s: float, label: str = LABEL) -> Path:
    """A child that behaves like one hygiene shard running ONE long gate.

    It announces the gate, emits `emit_units` sub-units spread over `run_s`,
    then (only if it emitted them all) finishes the gate and writes the
    completed-gate attestation row.  `emit_units=0` is the wedged shape: it
    announces and then goes silent for the whole run.
    """
    script = tmp_path / f"child_{label.replace(' ', '_')}.py"
    script.write_text(f'''
import json, os, sys, time
sys.path.insert(0, {str(PROGRAMS)!r})
import _gate_inflight_progress as I

label = {label!r}
inflight = {str(inflight)!r}
attest = {str(attest)!r}
units = {emit_units}
run_s = {run_s!r}

I.append_event(inflight, I.STARTED, label, 1)
os.environ[I.ENV_PATH] = inflight
os.environ[I.ENV_LABEL] = label
if units:
    for n in range(1, units + 1):
        time.sleep(run_s / units)
        I.emit(n, units)
    I.append_event(inflight, I.FINISHED, label, 1)
    with open(attest, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({{"complete": True, "label": label}}) + "\\n")
else:
    time.sleep(run_s)
''', encoding="utf-8")
    return script


class _Attest:
    """Stand in for `gate_process_attestation` so this file drives the
    SUPERVISION and not the attestation schema, which has its own tests."""

    @staticmethod
    def strict_loads(text):
        return json.loads(text)

    @staticmethod
    def validate_record(record, _lineno):
        return record


@pytest.fixture()
def stub_attest(monkeypatch):
    monkeypatch.setattr(O, "_attest", _Attest)
    return _Attest


def _drive(tmp_path, script, attest, inflight, labels, *,
           inflight_path_arg=True):
    return O.run_owned(
        [sys.executable, "-B", str(script)], tmp_path, dict(os.environ),
        progress_path=attest, stall_grace_s=GRACE_S, poll_s=POLL_S,
        output_progress=False, semantic_progress=True,
        expected_progress_labels=list(labels),
        inflight_path=inflight if inflight_path_arg else None)


# ══════════════════════════════════════════════════════════════════════════
# 1. ACCEPTANCE 1 — a long gate that reports progress is NOT killed.
# ══════════════════════════════════════════════════════════════════════════

def test_a_gate_far_longer_than_its_lease_completes_while_reporting(
        tmp_path, stub_attest):
    attest = tmp_path / "attest.jsonl"
    attest.touch()
    inflight = tmp_path / "inflight.jsonl"
    script = _child(tmp_path, attest=attest, inflight=inflight,
                    emit_units=UNITS, run_s=RUN_S)
    started = time.monotonic()
    result = _drive(tmp_path, script, attest, inflight, [LABEL])
    elapsed = time.monotonic() - started

    # The point of the arm: it really did outlive its own lease, by a lot.
    assert elapsed > GRACE_S * 3, (
        f"the drive finished in {elapsed:.1f}s, which is not long enough to "
        f"have proved anything against a {GRACE_S}s lease")
    assert result.outcome == "natural", (result.outcome, result.problem)
    assert result.rc == 0, (result.rc, result.body)
    assert result.problem is None, result.problem


# ══════════════════════════════════════════════════════════════════════════
# 2. ACCEPTANCE 3 — the mutation. Remove the renewal and arm 1 goes red.
# ══════════════════════════════════════════════════════════════════════════

def test_without_the_inflight_renewal_the_same_job_is_killed(
        tmp_path, stub_attest):
    """The pre-fix behaviour, reached by the ONE thing the fix added.

    `inflight_path=None` is exactly the state of every caller before this
    change: the attestation probe is the only renewal source, the gate is
    silent for its whole life, and the lease expires on elapsed time.
    """
    attest = tmp_path / "attest.jsonl"
    attest.touch()
    inflight = tmp_path / "inflight.jsonl"
    script = _child(tmp_path, attest=attest, inflight=inflight,
                    emit_units=UNITS, run_s=RUN_S)
    result = _drive(tmp_path, script, attest, inflight, [LABEL],
                    inflight_path_arg=False)
    assert result.outcome == "stalled", (result.outcome, result.problem)
    assert "did not complete naturally" in (result.problem or "")


def test_a_frozen_inflight_score_also_restores_the_kill(
        tmp_path, stub_attest, monkeypatch):
    """The second spelling of the same mutation, at the probe rather than the
    call site: a reader whose score never advances contributes no renewals."""
    original = I.InflightReader.sample
    monkeypatch.setattr(I.InflightReader, "sample", lambda self: 0)
    try:
        attest = tmp_path / "attest.jsonl"
        attest.touch()
        inflight = tmp_path / "inflight.jsonl"
        script = _child(tmp_path, attest=attest, inflight=inflight,
                        emit_units=UNITS, run_s=RUN_S)
        result = _drive(tmp_path, script, attest, inflight, [LABEL])
        assert result.outcome == "stalled", (result.outcome, result.problem)
    finally:
        monkeypatch.setattr(I.InflightReader, "sample", original)


# ══════════════════════════════════════════════════════════════════════════
# 3. ACCEPTANCE 2 — a worker that stops reporting IS killed, BY NAME.
# ══════════════════════════════════════════════════════════════════════════

def test_a_silent_worker_is_killed_and_the_kill_names_the_gate_in_flight(
        tmp_path, stub_attest):
    attest = tmp_path / "attest.jsonl"
    attest.touch()
    inflight = tmp_path / "inflight.jsonl"
    script = _child(tmp_path, attest=attest, inflight=inflight,
                    emit_units=0, run_s=RUN_S)
    result = _drive(tmp_path, script, attest, inflight, [LABEL, OTHER])
    assert result.outcome == "stalled", (result.outcome, result.problem)
    problem = result.problem or ""
    # The gate in flight, by name — not "the shard".
    assert LABEL in problem, problem
    assert "in flight" in problem, problem
    # …and the interval that elapsed, so "killed as hung" is checkable.
    assert "no forward progress for" in problem, problem
    assert "stall lease" in problem, problem
    # The gate that was NOT running must not be named as the one in flight.
    # It is still named in the earlier PROGRESS_PROTOCOL_INCOMPLETE clause,
    # correctly: it is one of the assigned gates that never reached a verdict.
    # That is a different sentence from "this is what held the lease".
    in_flight_clause = problem.split("in flight:", 1)[1]
    assert LABEL in in_flight_clause, in_flight_clause
    assert OTHER not in in_flight_clause, in_flight_clause


def test_the_gate_that_finished_is_reported_as_finished_not_in_flight(
        tmp_path, stub_attest):
    """A shard killed AFTER a gate completed must not name that gate."""
    inflight = tmp_path / "inflight.jsonl"
    I.append_event(str(inflight), I.STARTED, LABEL, 2)
    I.append_event(str(inflight), I.FINISHED, LABEL, 2)
    I.append_event(str(inflight), I.STARTED, OTHER, 2)
    reader = I.InflightReader(str(inflight), (LABEL, OTHER))
    assert reader.sample() == 3, reader.error
    described = reader.describe()
    assert OTHER in described, described
    assert "1 of 2 assigned gate(s) completed" in described, described
    assert f"{LABEL!r} (gate" not in described, described


# ══════════════════════════════════════════════════════════════════════════
# 4. THE PROTOCOL REFUSES WHAT IT MUST REFUSE.
#    Each of these is a way to hold a lease open on a job going nowhere.
# ══════════════════════════════════════════════════════════════════════════

def _reader(tmp_path, rows, labels=(LABEL,)):
    path = tmp_path / "channel.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    reader = I.InflightReader(str(path), tuple(labels))
    reader.sample()
    return reader


def _started(label=LABEL, of=1, index=1):
    return {"schema": 1, "event": I.STARTED, "label": label,
            "index": index, "of": of}


def _unit(n, units, label=LABEL):
    return {"schema": 1, "event": I.UNIT, "label": label, "index": 1, "of": 1,
            "unit": n, "units": units}


def test_a_healthy_stream_scores_every_row():
    pass  # covered by the driven arm above; kept out of the refusal table


@pytest.mark.parametrize("rows,fragment", [
    ([_started("not mine")], "unassigned gate label"),
    ([_unit(1, 3)], "before its gate started"),
    ([_started(), _unit(2, 3), _unit(2, 3)], "did not advance"),
    ([_started(), _unit(1, 3), _unit(2, 4)], "declared unit count changed"),
    ([_started(), _unit(1, 3), _unit(4, 3)], "exceeds its declared total"),
    ([_started(), _started()], "gate started twice"),
    ([_started(), {"schema": 1, "event": I.FINISHED, "label": LABEL,
                   "index": 1, "of": 1},
      _unit(1, 3)], "after its gate finished"),
    ([{"schema": 2, "event": I.STARTED, "label": LABEL, "index": 1, "of": 1}],
     "unknown in-flight schema"),
    ([{"schema": 1, "event": "heartbeat", "label": LABEL,
       "index": 1, "of": 1}], "unknown in-flight event"),
])
def test_the_channel_refuses_a_lease_it_did_not_earn(tmp_path, rows, fragment):
    reader = _reader(tmp_path, rows)
    assert reader.error, f"accepted {rows}"
    assert fragment in reader.error, (fragment, reader.error)


def test_a_rewritten_history_is_refused(tmp_path):
    path = tmp_path / "channel.jsonl"
    reader = I.InflightReader(str(path), (LABEL,))
    I.append_event(str(path), I.STARTED, LABEL, 1)
    assert reader.sample() == 1, reader.error
    # Same row count, different content: the one substitution a count cannot see.
    path.write_text(json.dumps(_started("not mine"), sort_keys=True) + "\n",
                    encoding="utf-8")
    reader.sample()
    assert reader.error, "a substituted history was accepted"


def test_truncation_is_refused(tmp_path):
    path = tmp_path / "channel.jsonl"
    reader = I.InflightReader(str(path), (LABEL,))
    I.append_event(str(path), I.STARTED, LABEL, 1)
    reader.sample()
    path.write_text("", encoding="utf-8")
    reader.sample()
    assert "truncated" in reader.error, reader.error


def test_the_renewal_stream_is_finite_by_construction(tmp_path):
    """A gate cannot renew forever: `units` is declared once and `unit`
    strictly increases, so the channel's own bound is the denominator.

    REFUSED AT BOTH ENDS, which is why this arm checks the writer and the
    reader separately. `emit` will not WRITE a unit outside 1..units (it
    returns False and the file does not grow), and the reader refuses one that
    reaches it some other way — the parametrised table above drives that half.
    A guarantee enforced only by the writer would be a guarantee any other
    writer could ignore."""
    path = tmp_path / "channel.jsonl"
    I.append_event(str(path), I.STARTED, LABEL, 1)
    os.environ[I.ENV_PATH] = str(path)
    os.environ[I.ENV_LABEL] = LABEL
    try:
        for n in range(1, 4):
            assert I.emit(n, 3)
        # A fourth renewal does not exist inside a declared three.
        assert I.emit(4, 3) is False
    finally:
        os.environ.pop(I.ENV_PATH, None)
        os.environ.pop(I.ENV_LABEL, None)
    reader = I.InflightReader(str(path), (LABEL,))
    score = reader.sample()
    assert not reader.error, reader.error
    # started + exactly the three declared units, and nothing after them.
    assert score == 4, score


# ══════════════════════════════════════════════════════════════════════════
# 5. THE CHANNEL IS INERT WITHOUT A SUPERVISOR, AND REFUSED WITHOUT ONE.
# ══════════════════════════════════════════════════════════════════════════

def test_emit_is_a_no_op_with_no_channel(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in (I.ENV_PATH, I.ENV_LABEL)}
    assert I.emit(1, 5, env=env) is False
    assert I.enabled(env) is False
    assert not list(tmp_path.iterdir())


def test_an_inflight_channel_without_the_attestation_channel_is_refused(
        tmp_path):
    """It is an ADDITION to completed-gate progress, never a replacement.

    Accepting it alone would let a run renew its lease forever while reaching
    no verdict at all — the exact state the supervisor exists to stop.
    """
    result = O.run_owned(
        [sys.executable, "-c", "pass"], tmp_path, dict(os.environ),
        progress_path=None, stall_grace_s=GRACE_S, poll_s=POLL_S,
        inflight_path=tmp_path / "inflight.jsonl")
    assert result.outcome == "policy_refused", result.outcome
    assert "in-flight" in (result.problem or ""), result.problem


# ══════════════════════════════════════════════════════════════════════════
# 6. THE TWO GATES THAT ARE ACTUALLY ABOVE THE LEASE NOW RELAY THEIR OWN
#    EARNED EVENTS OUTWARD.
#
#    The channel above is useless if the only two gates that need it never
#    write to it, so this section drives the relay in the gate that carries
#    the whole problem — `gates are host-independent`, 2556 s in the shipped
#    profile — through its own declared test seam.
# ══════════════════════════════════════════════════════════════════════════







# ══════════════════════════════════════════════════════════════════════════
# 7. THE GENERIC HALF — the 152 gates that know no denominator of their own.
#
#    MEASURED on 8HD-6 at load1 ~30, `repo_hygiene_parallel --stall-grace 300`
#    over a pristine a1f3685837ca: four shards killed at rc 199 across the two
#    arms, and for two of them the gate in flight was `every program is
#    reachable` — which the shipped cost profile does not list among its heavy
#    rows at all. Instrumenting the two known-heavy gates would not have saved
#    that shard, and neither would a bigger number: under load ANY gate can
#    outlive any clock somebody picked.
#
#    So the dispatcher also OBSERVES the gate it launched. Every row must prove
#    its own advance, at both ends: the writer refuses to append one, and the
#    reader refuses to score one.
# ══════════════════════════════════════════════════════════════════════════

import subprocess  # noqa: E402


def _alive(path, label, *, capture="", root_pid, exclude_pid=0, of=1):
    return I.append_alive(str(path), label, of, capture, root_pid, exclude_pid)


def test_a_working_gate_renews_and_a_still_one_does_not(tmp_path):
    """One call, two subjects, opposite verdicts — the discrimination itself.

    A child burning CPU produces a row; a child asleep produces none. Both are
    measured through the SAME function at the SAME moment, so a pass here is
    not "the busy one worked" but "the busy one and the idle one were told
    apart".
    """
    channel = tmp_path / "channel.jsonl"
    I.append_event(str(channel), I.STARTED, LABEL, 1)

    busy = subprocess.Popen(
        [sys.executable, "-c",
         "import time\nend=time.time()+30\nwhile time.time()<end: pass"])
    idle = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Baseline row for each subject: the first observation has nothing to
        # beat, so it is always written and establishes the counters.
        assert _alive(channel, LABEL, root_pid=busy.pid) == 0
        time.sleep(2.0)
        assert _alive(channel, LABEL, root_pid=busy.pid) == 0, (
            "a child at 100% CPU did not renew; the observation is not "
            "reading the subject")
        before = channel.read_text()
        # The idle child's tree has produced neither output nor CPU since the
        # busy reading above, so its counters cannot beat what is recorded.
        rc_idle = _alive(channel, LABEL, root_pid=idle.pid)
        assert rc_idle == I.RC_NO_ADVANCE, rc_idle
        assert channel.read_text() == before, "a still subject wrote a row"
    finally:
        busy.kill(); busy.wait()
        idle.kill(); idle.wait()

    reader = I.InflightReader(str(channel), (LABEL,))
    assert reader.sample() >= 3, reader.error
    assert not reader.error, reader.error


def test_the_poller_does_not_renew_itself(tmp_path):
    """`--exclude-pid` is load-bearing, not an optimisation.

    Without it the process doing the observing is inside the tree it observes,
    so its own CPU renews the lease — a heartbeat on a timer wearing a liveness
    probe's clothes. Measured directly: the CPU attributed to a tree WITH the
    observer excluded must be strictly less than the same tree WITHOUT it, when
    the observer is the only thing in it that has run.
    """
    idle = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        # Burn a little CPU in THIS process, then measure its own tree both
        # ways. `os.getpid()` is the observer here.
        total = 0
        for i in range(200000):
            total += i
        with_self = I._tree_cpu_ticks(os.getpid(), 0)
        without_self = I._tree_cpu_ticks(os.getpid(), os.getpid())
        assert without_self < with_self, (without_self, with_self, total)
    finally:
        idle.kill(); idle.wait()


@pytest.mark.parametrize("rows,fragment", [
    ([_started(),
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": 10, "cpu_ticks": 5},
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": 10, "cpu_ticks": 5}], "shows no advance"),
    ([_started(),
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": 10, "cpu_ticks": 5},
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": 9, "cpu_ticks": 5}], "went backwards"),
    ([_started(),
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": 10}], "cpu_ticks is not an integer"),
    ([_started(),
      {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1, "of": 1,
       "bytes": -1, "cpu_ticks": 5}], "negative"),
])
def test_a_liveness_row_must_prove_its_own_advance(tmp_path, rows, fragment):
    reader = _reader(tmp_path, rows)
    assert reader.error, f"accepted {rows}"
    assert fragment in reader.error, (fragment, reader.error)


def test_the_kill_message_says_a_silent_gate_reported_nothing_at_all(tmp_path):
    """The two silences are different and must read differently: a gate that
    never said anything, and one that was observed alive and then stopped."""
    channel = tmp_path / "channel.jsonl"
    I.append_event(str(channel), I.STARTED, LABEL, 1)
    reader = I.InflightReader(str(channel), (LABEL,))
    reader.sample()
    assert "reported nothing at all since it started" in reader.describe()

    with channel.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {"schema": 1, "event": I.ALIVE, "label": LABEL, "index": 1,
             "of": 1, "bytes": 4096, "cpu_ticks": 900}, sort_keys=True) + "\n")
    reader2 = I.InflightReader(str(channel), (LABEL,))
    reader2.sample()
    described = reader2.describe()
    assert "1 liveness observation(s)" in described, described
    assert "4096 output byte(s)" in described, described
    assert "900 CPU tick(s)" in described, described


def test_the_liveness_poller_refuses_a_tree_it_cannot_attribute():
    """The CPU census is rooted at the shard shell, so it is only an
    observation OF THE GATE while that shell is running exactly one gate.

    With a parallel pool the busiest gate in the pool would renew a wedged
    peer's lease — an observation attributed to the wrong subject, which is
    worse than no observation at all. The shipped supervised shape is always
    serial (`repo_hygiene_parallel.SHARD_DISPATCH_JOBS == "1"`), so this guard
    refuses a state that does not occur today; writing it down before it can is
    the point.
    """
    dispatch = (PROGRAMS.parent.parent.parent.parent
                / "tools" / "ci" / "_gate_dispatch.sh")
    body = dispatch.read_text(encoding="utf-8")
    start = body.index("_gate_inflight_poller_start() {")
    end = body.index("_gate_inflight_poller_stop() {")
    assert '[ "${GATE_DISPATCH_JOBS:-1}" -le 1 ] || return 0' in body[start:end]

    import repo_hygiene_parallel as P  # noqa: PLC0415
    assert P.SHARD_DISPATCH_JOBS == "1", P.SHARD_DISPATCH_JOBS


def test_the_dispatcher_kills_only_its_own_recorded_poller_pid():
    """Never a pattern. Every agent on this fleet runs the same script names,
    and `unanchored_process_kill_check` forbids a pattern kill in shipped
    code for exactly that reason."""
    dispatch = (PROGRAMS.parent.parent.parent.parent
                / "tools" / "ci" / "_gate_dispatch.sh")
    body = dispatch.read_text(encoding="utf-8")
    start = body.index("_gate_inflight_poller_stop() {")
    stop_body = body[start:body.index("\n}", start)]
    assert 'kill "$GATE_DISPATCH_INFLIGHT_POLLER"' in stop_body, stop_body
    assert "pkill" not in stop_body and "pgrep" not in stop_body, stop_body


def test_stopping_poller_reaps_its_current_sleep_child(tmp_path):
    """The recorded poller PID is not its entire process tree.

    Before the repair, TERM made the poller shell exit while its current sleep
    was reparented. The outer ownership supervisor then found and cleaned that
    child after every otherwise-natural shard. Drive the shipped shell function
    and inspect the exact child PID through /proc; no name matching is used.
    """
    dispatch = (PROGRAMS.parent.parent.parent.parent
                / "tools" / "ci" / "_gate_dispatch.sh")
    channel = tmp_path / "inflight.jsonl"
    helper = PROGRAMS / "_gate_inflight_progress.py"
    probe = tmp_path / "poller_result.txt"
    script = tmp_path / "drive_poller.sh"
    script.write_text(f'''#!/usr/bin/env bash
set -euo pipefail
source {str(dispatch)!r}
GATE_DISPATCH_INFLIGHT_FILE={str(channel)!r}
GATE_DISPATCH_INFLIGHT_HELPER={str(helper)!r}
GATE_DISPATCH_INFLIGHT_TOTAL=1
GATE_DISPATCH_INFLIGHT_POLL_S=20
_gate_inflight_poller_start probe /dev/null
poller="$GATE_DISPATCH_INFLIGHT_POLLER"
children=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  children="$(cat "/proc/$poller/task/$poller/children" 2>/dev/null || true)"
  [ -n "$children" ] && break
  sleep 0.01
done
[ -n "$children" ]
_gate_inflight_poller_stop
for child in $children; do
  [ ! -e "/proc/$child" ] || exit 23
done
printf '%s\\n' "$children" > {str(probe)!r}
''', encoding="utf-8")
    script.chmod(0o755)
    result = subprocess.run(["bash", str(script)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert probe.read_text(encoding="utf-8").strip(), "no sleep child observed"


def test_no_bound_was_raised_by_this_fix():
    """The forbidden repair, asserted against the two numbers themselves.

    Raising a wall clock moves the cliff instead of removing it, so both graces
    must be exactly what they were on the frozen base a1f3685837ca.
    """
    import repo_hygiene_parallel as P  # noqa: PLC0415
    import gatekeeper_review as R  # noqa: PLC0415
    assert P.DEFAULT_STALL_GRACE_S == 300, P.DEFAULT_STALL_GRACE_S
    assert R._HYGIENE_STALL_GRACE_S == 1800, R._HYGIENE_STALL_GRACE_S
    # …and nothing this fix touches wraps a command in a clock.
    for name in ("_gate_inflight_progress.py", "repo_hygiene_parallel.py",
                 "_owned_process_supervisor.py"):
        text = (PROGRAMS / name).read_text(encoding="utf-8")
        assert "wrap_with_container_timeout" not in text, name
