"""Unit tests for pytest_per_file_junit.py (vibe-ic#1654).

THE DEFECT, in one sentence: `--timeout-method=thread` cannot interrupt a
blocking `waiter.acquire()`, so pytest-timeout takes the whole PROCESS down and
the process never writes its `--junitxml` — one hanging file therefore used to
cost the entire run's machine-readable record, including files that had already
PASSED.

Pinned here in the order the driver can be wrong:

  * FALSIFIABILITY, both directions and on the same bytes: the SAME three
    fixture files, md5-identical, lose the whole record under one pytest session
    and keep every completed file's record under the driver;
  * a file with no record is NAMED (`NORECORD`) and is kept OUT of the merged
    report — absence is what the merge gate refuses on, and a synthetic red
    would be scored PRE-EXISTING when both arms hang on the same file;
  * progress-stall supervision catches a shape pytest-timeout cannot see, a hang
    during module IMPORT, where no test is running for a per-test timer to bound;
  * the merged report is xunit1 and carries the `file` attribute, because that
    is what `landing_merge_verdict` derives the ran-file set from;
  * an empty selection is rc 3 (`the question could not be put`), never rc 0 —
    an empty corpus is not evidence that anything passed;
  * `--stop-after-failures` NAMES what it did not launch instead of leaving it
    to look clean.

Neither the production driver NOR this file carries a whole-run wall-clock
estimate: both are supervised by forward progress. The one bound left here is
`_SINGLE_SESSION_KILL`, and it is a SUBJECT, not a safety net —
`test_one_session_loses_the_whole_record_and_per_file_does_not` needs a killed
session to have anything to prove.
"""
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from _hostpaths import require_repo

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as D                              # noqa: E402
import _watchdog                                              # noqa: E402

_PROG = _PROGRAMS / "pytest_per_file_junit.py"
_FALLBACK_ENV = "VIBEIC_PYTEST_FALLBACK_WORKER"

#: NOT a bound. `_LOOK_S` is how often a wait LOOKS; `_STALL_LOOKS` is how many
#: consecutive looks the thing being waited on may show ZERO forward progress
#: (no CPU, no I/O anywhere in its /proc tree) before it is called hung;
#: `_MAX_LOOKS` is a pathological backstop counted in LOOKS.
#:
#: What was here was `_T = 50`, justified by "measured at well under 20 s on
#: this host". That reasoning is the defect: 50 s is a reading of one machine on
#: one day, and when a busier machine exceeds it the `TimeoutExpired` does not
#: say "this box was loaded", it fails the test as though
#: `pytest_per_file_junit.py` were broken. The subject of this file is a driver
#: whose own contract is SEMANTIC PROGRESS (`--stall-after`), so bounding it
#: with a wall clock contradicted the thing being tested.
_LOOK_S = 0.05
_STALL_LOOKS = 600
_MAX_LOOKS = 200_000


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True)` with no wall clock.

    Bounds NO FORWARD PROGRESS instead — CPU and I/O over the child's whole
    /proc tree plus the growth of its captured output — so a driver that is
    merely slow always finishes and one that is wedged still dies, as rc
    `_watchdog.RC_STALLED`, which is not a code this driver produces."""
    return _watchdog.completed_process(
        cmd, _watchdog.run_host_supervised(cmd, **kw))


def _await(name, ready, proc):
    """Poll `ready()` while `proc`'s process TREE keeps making progress.

    Replaces `deadline = time.monotonic() + N; while ...` — a wall clock wearing
    a loop. When one of those ran out the assertion that followed blamed the
    driver ("never launched its escapee", "never entered its TERM-ignoring
    grace") on the evidence that this host was slow. Returns True the moment
    `ready()` holds; returns False only when the tree stopped progressing."""
    guard = _watchdog.loop_guard(
        name, max_iter=_MAX_LOOKS, stall_iters=_STALL_LOOKS,
        progress_fn=lambda: _watchdog.host_tree_progress(proc.pid))
    for _ in guard:
        if ready():
            return True
        if proc.poll() is not None:
            return ready()
        time.sleep(_LOOK_S)
    return False


def _await_exit(name, proc):
    """Wait for `proc` to exit, bounded by NO FORWARD PROGRESS.

    What is meant after a signal is "the process ended", not "the process ended
    within 15 seconds". A process still burning CPU is not one that failed to
    handle its signal yet, and a bound cannot tell those apart."""
    guard = _watchdog.loop_guard(
        name, max_iter=_MAX_LOOKS, stall_iters=_STALL_LOOKS,
        progress_fn=lambda: _watchdog.host_tree_progress(proc.pid))
    for _ in guard:
        if proc.poll() is not None:
            return True
        time.sleep(_LOOK_S)
    return False

#: Test-only no-progress window. It is not a cap on healthy runtime.
_STALL = 1

#: The bound the ONE-SESSION arm of `test_one_session_loses_the_whole_record_
#: and_per_file_does_not` puts on ITSELF, as `subprocess.run(timeout=...)`.
#:
#: It replaces `-p pytest_timeout --timeout=4 --timeout-method=thread`, which
#: this file used to hand to every child it launched. That idiom is RETIRED in
#: this repo (`programs/pytest_per_file_junit.py`: "There is deliberately no
#: pytest-timeout guard on the landing path"; `tools/ci/test_phase_b_activated_
#: parity.py` and `tools/ci/test_repo_tools_tests_gate.py` both forbid its
#: return), and MEASURED on 2026-08-20 the plugin is absent from the anchored
#: runtime `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d01ff` AND from the newer
#: 0.3.13 tag: `-p <missing plugin>` is a HARD import that dies in pytest's
#: pre-parse, so all 26 tests in this file that reached the child through
#: `_pytest_cmd` were red in the image and green on a host that happened to
#: carry an ambient pip package nothing in this tree declares.
#:
#: NOTHING IS LEFT UNBOUNDED THAT WAS BOUNDED. Every other child in this file
#: goes through the driver, whose `--stall-after {_STALL}` supervision fires at
#: 1 s -- a quarter of the 4 s the retired plugin was set to -- so the plugin
#: could never have been the bound that fired there. The single-session arm is
#: the ONE child with no driver above it, and it now carries its own explicit
#: kill instead of borrowing one from a plugin.
_SINGLE_SESSION_KILL = 8

_GREEN = "def test_i_am_green():\n    assert 1 == 1\n"

_GREEN_AFTER = "def test_i_am_also_green():\n    assert 2 == 2\n"


class _OuterEmitter:
    def __init__(self, *, fail=False):
        self.rows = []
        self.fail = fail

    def emit(self, state, unit=None):
        if self.fail:
            raise RuntimeError("planted relay failure")
        self.rows.append((state, unit))


class _OuterProbe:
    error = ""

    def __init__(self, *, finished=(), domain_progress=None, items=None,
                 item_order=None, declared_items=None):
        default_items = [
            "test_a.py::test_one", "test_b.py::test_two",
            # A forged item outside the parent selection is never a unit.
            "test_forged.py::test_noise",
        ]
        self.item_order = list(
            default_items if item_order is None and items is None
            else item_order if item_order is not None else items)
        self.items = set(self.item_order)
        self.finished = set(finished)
        self.domain_progress = dict(domain_progress or {})
        self.declared_items = (
            len(self.items) if declared_items is None else declared_items)


def _planned_items(planner, test_file):
    spec = planner.HERMETIC_TEST_PROGRESS[test_file]
    items = [f"{test_file}::test_slot_{ordinal}"
             for ordinal in range(1, spec["items"] + 1)]
    for ordinal, nodeid, _scope, _total in spec["domains"]:
        items[ordinal - 1] = nodeid
    assert len(items) == len(set(items))
    return items


def test_hermetic_outer_progress_is_exact_selection_order_only():
    emitter = _OuterEmitter()
    relay = D._HermeticAggregateProgress(
        ["test_a.py", "test_b.py"], emitter=emitter)
    assert relay.start()
    relay.observe(_OuterProbe(finished={
        "test_b.py::test_two", "test_forged.py::test_noise"}))
    assert emitter.rows == [
        ("start", None),
        ("checkpoint", "pytest:collection-complete"),
    ]
    relay.observe(_OuterProbe(finished={
        "test_a.py::test_one", "test_b.py::test_two",
        "test_forged.py::test_noise"}))
    assert relay.finish()
    assert emitter.rows == [
        ("start", None),
        ("checkpoint", "pytest:collection-complete"),
        ("checkpoint", "pytest:test_a.py"),
        ("checkpoint", "pytest:test_b.py"),
        ("checkpoint", "pytest:record-published"),
        ("terminal", None),
    ]


def test_hermetic_outer_progress_missing_or_failed_relay_is_norecord():
    emitter = _OuterEmitter()
    relay = D._HermeticAggregateProgress(
        ["test_a.py", "test_b.py"], emitter=emitter)
    assert relay.start()
    relay.observe(_OuterProbe(finished={"test_a.py::test_one"}))
    assert not relay.finish()
    assert "not every selected file" in relay.problem
    assert ("terminal", None) not in emitter.rows

    broken = D._HermeticAggregateProgress(
        ["test_a.py"], emitter=_OuterEmitter(fail=True))
    assert not broken.start()
    assert "planted relay failure" in broken.problem


def test_hermetic_outer_progress_relays_only_exact_parent_matrix_domains():
    planner = D._load_hermetic_progress_planner()
    test_file = planner.HERMETIC_MATRIX_FILE
    spec = planner.HERMETIC_TEST_PROGRESS[test_file]
    domains = spec["domains"]
    first_ordinal, first_node, first_scope, first_total = domains[0]
    items = _planned_items(planner, test_file)
    emitter = _OuterEmitter()
    relay = D._HermeticAggregateProgress(
        [test_file], emitter=emitter, planner=planner)
    assert relay.start()
    relay.observe(_OuterProbe(
        item_order=items,
        finished=set(items[:first_ordinal - 1]),
        domain_progress={
            (first_node, first_scope): (1, first_total),
            (first_node, "forged-noise"): (10_000, 10_000),
        }))
    assert emitter.rows == [
        ("start", None),
        ("checkpoint", "pytest:collection-complete"),
        *[("checkpoint", planner.test_progress_unit(
            test_file, completed, spec["items"]))
          for completed in range(1, first_ordinal)],
        ("checkpoint", planner.domain_progress_unit(
            test_file, first_node, first_scope, 1, first_total)),
    ]

    # Finishing a planned node backfills its unused suffix at terminal speed;
    # those records keep a fast FAIL complete but did not renew while it ran.
    relay.observe(_OuterProbe(
        item_order=items, finished=set(items[:first_ordinal]),
        domain_progress={(first_node, first_scope): (1, first_total)}))
    assert emitter.rows[-2] == (
        "checkpoint", planner.domain_progress_unit(
            test_file, first_node, first_scope, first_total, first_total))
    assert emitter.rows[-1] == (
        "checkpoint", planner.test_progress_unit(
            test_file, first_ordinal, spec["items"]))

    # Once every file item has a validated finish, every remaining optional
    # domain unit is terminal-backfilled before the mandatory file unit.
    relay.observe(_OuterProbe(item_order=items, finished=items))
    assert relay.finish()
    assert emitter.rows[-3:] == [
        ("checkpoint", f"pytest:{test_file}"),
        ("checkpoint", "pytest:record-published"),
        ("terminal", None),
    ]
    assert len([row for row in emitter.rows
                if row[0] == "checkpoint"]) == (
                    spec["items"]
                    + sum(row[3] for row in domains)
                    + 3)


def test_hermetic_outer_progress_refuses_wrong_matrix_denominator():
    planner = D._load_hermetic_progress_planner()
    test_file = planner.HERMETIC_MATRIX_FILE
    _ordinal, nodeid, scope, total = (
        planner.HERMETIC_TEST_PROGRESS[test_file]["domains"][0])
    items = _planned_items(planner, test_file)
    relay = D._HermeticAggregateProgress(
        [test_file], emitter=_OuterEmitter(), planner=planner)
    assert relay.start()
    relay.observe(_OuterProbe(
        item_order=items,
        domain_progress={(nodeid, scope): (1, total + 1)}))
    assert relay.problem == "parent-owned nested domain denominator differs"
    assert not relay.finish()


def test_hermetic_outer_progress_refuses_changed_item_denominator_or_ordinal():
    planner = D._load_hermetic_progress_planner()
    test_file = planner.HERMETIC_MUTATION_FILE
    items = _planned_items(planner, test_file)
    relay = D._HermeticAggregateProgress(
        [test_file], emitter=_OuterEmitter(), planner=planner)
    assert relay.start()
    relay.observe(_OuterProbe(item_order=items[:-1]))
    assert "item denominator differs" in relay.problem

    swapped = list(items)
    ordinal = planner.HERMETIC_TEST_PROGRESS[test_file]["domains"][0][0]
    swapped[ordinal - 2], swapped[ordinal - 1] = (
        swapped[ordinal - 1], swapped[ordinal - 2])
    relay = D._HermeticAggregateProgress(
        [test_file], emitter=_OuterEmitter(), planner=planner)
    assert relay.start()
    relay.observe(_OuterProbe(item_order=swapped))
    assert "nodeid/ordinal differs" in relay.problem


def _stream_set_over(tmp_path, shares, *, item_order, declared=None,
                     domain_progress=None):
    """A real `_ProgressStreamSet` carrying one real probe per worker share."""
    streams = D._ProgressStreamSet(
        tmp_path, "0" * 32, lambda: os.getpid())
    for index, finished in enumerate(shares):
        name = f"w.gw{index}.{os.getpid()}.0.jsonl"
        path = tmp_path / name
        path.write_bytes(b"")
        probe = D._SemanticProgressProbe(
            path, streams.nonce, streams.pid_fn, partial_session=True)
        probe.item_order = list(item_order)
        probe.items = set(item_order)
        probe.finished = set(finished)
        probe.declared_items = (
            len(item_order) if declared is None else declared)
        probe.domain_progress = dict((domain_progress or {}).get(index, {}))
        streams.streams[name] = probe
        streams.kinds[name] = "worker"
    return streams


def test_a_stream_that_appears_after_the_first_scan_is_still_admitted(tmp_path):
    """THE READ SIDE'S OWN BLIND SPOT, and it made every merge verification
    refuse.

    `_scan` lists a directory FD it holds open for the whole run.
    `os.listdir(fd)` is `fdopendir(dup(fd))`, and a dup SHARES the file offset,
    so a second listing resumes wherever the first one stopped. The first scan
    always happens BEFORE the pytest child has written its stream -- the driver
    polls immediately after spawning -- so that cursor is already at
    end-of-directory when the stream finally appears.

    MEASURED in the hermetic candidate container, whose profile mounts `/tmp`
    as a TMPFS: `os.listdir(self.dir_fd)` returned `[]` at the same instant
    `os.listdir(self.directory)` returned `['m.7.1.jsonl']`. A 0.02 s GREEN arm
    was therefore admitted only by `complete()` -- after the last observer
    sample -- so the hermetic relay emitted no checkpoint and no terminal
    record, no B1 receipt was written, and `gatekeeper-verify-merge.sh`
    answered rc=2 to a known-good branch and a known-bad one alike: 22 reds in
    `test_landing_merge_verdict`, and a merge gate that could not discriminate.

    The cursor position is the whole property, so this test SETS it rather than
    hoping the host filesystem reproduces tmpfs semantics: on ext4 the kernel
    re-seeds the readdir cursor and the defect is invisible, which is exactly
    why it survived. A scan must be a statement about the directory, never
    about where the previous scan stopped reading it."""
    streams = D._ProgressStreamSet(tmp_path, "0" * 32, lambda: os.getpid())
    try:
        assert streams.sample() == 0
        assert streams.streams == {}, "nothing was written yet"
        os.lseek(streams.dir_fd, 0, os.SEEK_END)
        name = f"m.{os.getpid()}.0.jsonl"
        (tmp_path / name).write_bytes(b"")
        streams.sample()
        assert streams.error == "", streams.error
        assert list(streams.streams) == [name], (
            "the stream was invisible to the scan that followed it: a green "
            "arm and a hung arm are reported identically")
    finally:
        streams.close()


def test_hermetic_relay_reads_the_object_production_actually_hands_it(tmp_path):
    """THE PAIRING NO TEST ABOVE MEASURES. Every relay test in this file feeds
    `observe()` a hand-written duck type (`_OuterProbe`) that has the four
    attributes by construction, so none of them can see whether the REAL
    argument has them. `_run_progress_supervised` stopped passing
    `_SemanticProgressProbe` and started passing `_ProgressStreamSet`; the set
    defined none of `declared_items` / `item_order` / `finished` /
    `domain_progress`, so the first watchdog sample raised AttributeError
    inside the hermetic arm. The arm then died with no terminal progress
    record and the runner could only report "candidate ended without the exact
    semantic terminal record" — the relay's own refusal channel never fired,
    so the cause was invisible. Measured against the real class here."""
    items = ["test_a.py::test_one", "test_b.py::test_two"]
    emitter = _OuterEmitter()
    relay = D._HermeticAggregateProgress(
        ["test_a.py", "test_b.py"], emitter=emitter)
    assert relay.start()
    # Two workers, each finishing only its own share: the union is the session.
    streams = _stream_set_over(
        tmp_path, [{items[0]}, {items[1]}], item_order=items)
    try:
        relay.observe(streams)
        assert relay.finish()
    finally:
        streams.close()
    assert emitter.rows == [
        ("start", None),
        ("checkpoint", "pytest:collection-complete"),
        ("checkpoint", "pytest:test_a.py"),
        ("checkpoint", "pytest:test_b.py"),
        ("checkpoint", "pytest:record-published"),
        ("terminal", None),
    ]


def test_hermetic_relay_stays_silent_until_every_worker_agrees(tmp_path):
    """The join may never be optimistic. While one worker has not yet declared
    the collected selection, or the workers disagree about it, the set must
    report `declared_items is None` so the relay emits NOTHING rather than
    computing a denominator from a partial view."""
    items = ["test_a.py::test_one", "test_b.py::test_two"]
    emitter = _OuterEmitter()
    relay = D._HermeticAggregateProgress(
        ["test_a.py", "test_b.py"], emitter=emitter)
    assert relay.start()
    streams = _stream_set_over(
        tmp_path, [{items[0]}, {items[1]}], item_order=items)
    try:
        undeclared = next(iter(streams.streams.values()))
        undeclared.declared_items = None
        assert streams.declared_items is None
        relay.observe(streams)
        assert emitter.rows == [("start", None)]
        undeclared.declared_items = len(items)
        undeclared.item_order = list(reversed(items))
        assert streams.declared_items is None
        relay.observe(streams)
        assert emitter.rows == [("start", None)]
    finally:
        streams.close()


#: The #1654 shape verbatim: `Future.result` -> `Condition.wait` ->
#: `waiter.acquire`. `--timeout-method=thread` cannot interrupt it.
_HANGS_IN_TEST = (
    "from concurrent.futures import ThreadPoolExecutor\n"
    "import time\n"
    "\n"
    "\n"
    "def _sleeper():\n"
    "    time.sleep(3600)\n"
    "\n"
    "\n"
    "def test_hangs_in_waiter_acquire():\n"
    "    with ThreadPoolExecutor(max_workers=1) as ex:\n"
    "        ex.submit(_sleeper).result(timeout=3600)\n"
)

#: A hang at module IMPORT. pytest-timeout bounds test EXECUTION, so no per-test
#: timer exists yet and `--timeout` can never fire here at all.
_HANGS_AT_IMPORT = (
    "import time\n"
    "\n"
    "time.sleep(3600)\n"
    "\n"
    "\n"
    "def test_never_reached():\n"
    "    assert True\n"
)

_BURNS_CPU_AT_IMPORT = (
    "while True:\n"
    "    pass\n"
    "\n"
    "def test_never_reached():\n"
    "    assert True\n"
)

_CHATTY_AT_IMPORT = (
    "import time\n"
    "while True:\n"
    "    print('CHATTY_SENTINEL', flush=True)\n"
    "    time.sleep(0.02)\n"
    "\n"
    "def test_never_reached():\n"
    "    assert True\n"
)

_RED = "def test_i_am_red():\n    assert False\n"


def _tree(tmp_path: Path, files: dict) -> Path:
    """A directory of test files plus the selection naming them, in order."""
    d = tmp_path / "corpus"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    (d / "selection.txt").write_text(
        "".join(f"{n}\n" for n in files), encoding="utf-8")
    return d


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _pytest_cmd():
    """The harness command, pinned the way the landing gate pins it.

    The landing gate declares SEMANTIC PROGRESS and no elapsed-time verdict, so
    this argv carries no `--timeout` and names no timeout plugin. Keeping the
    two in step is not left to a reader:
    `test_the_landing_harness_argv_shape_is_the_one_this_file_pins` below
    asserts it against the shipped `tools/ci/hermetic_test_arm_entry.sh`.
    """
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def _run_driver(corpus: Path, junit: Path, *extra, pytest_extra=()):
    return _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(junit),
         "--stall-after", str(_STALL), *extra,
        "--"] + _pytest_cmd() + list(pytest_extra),
        cwd=str(corpus))


def _files_in(junit: Path):
    root = ET.parse(str(junit)).getroot()
    return sorted({tc.get("file") for tc in root.iter("testcase")})


# ── the defect, and the fix, on bytes proved identical ───────────────────────

def test_one_session_loses_the_whole_record_and_per_file_does_not(tmp_path):
    """THE BOTH-DIRECTIONS PROOF, on the same tree.

    Arm 1 is what `main` does today: one pytest session, one `--junitxml`. Arm 2
    is the driver. The corpus is built once and its md5s are asserted unchanged
    between the arms, so the difference cannot be the input.
    """
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_like_replay.py": _HANGS_IN_TEST,
                              "test_green_after.py": _GREEN_AFTER})
    before = {p.name: _md5(p) for p in sorted(corpus.glob("test_*.py"))}

    # ---- ARM 1: one session, exactly the shape gatekeeper-land.sh used ----
    #
    # The kill is EXTERNAL and explicit. It used to come from
    # `-p pytest_timeout --timeout=4 --timeout-method=thread`, and #1654's
    # measurement is that the thread method cannot interrupt the blocking
    # `waiter.acquire()` this fixture hangs in either -- it dumps stacks and
    # takes the PROCESS down. Both routes kill the same process at the same
    # point; only one of them needs a plugin the anchored runtime does not
    # carry. The claim under test is unchanged and is asserted below: a session
    # killed while one of its files hangs writes NO junit, so the two files that
    # had already PASSED lose their record too.
    single = tmp_path / "single.xml"
    killed = False
    try:
        subprocess.run(
            _pytest_cmd() + ["-o", "junit_family=xunit1",
                             f"--junitxml={single}",
                             "test_green_neighbour.py",
                             "test_hangs_like_replay.py",
                             "test_green_after.py"],
            cwd=str(corpus), capture_output=True, text=True,
            timeout=_SINGLE_SESSION_KILL)
    except subprocess.TimeoutExpired:
        killed = True
    assert killed, (
        "the single-session arm exited on its own inside "
        f"{_SINGLE_SESSION_KILL} s — the hang fixture no longer hangs and this "
        "test proves nothing")
    assert not single.exists(), (
        "the single-session arm wrote a junit — the hang fixture no longer "
        "reproduces #1654 and this test proves nothing")

    # ---- ARM 2: the driver, same bytes ----
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)

    after = {p.name: _md5(p) for p in sorted(corpus.glob("test_*.py"))}
    assert before == after, ("the corpus changed between the arms, so the two "
                            f"results are not comparable: {before} vs {after}")

    assert merged.is_file(), proc.stdout + proc.stderr
    got = _files_in(merged)
    assert got == ["test_green_after.py", "test_green_neighbour.py"], got
    assert "test_hangs_like_replay.py" not in got, (
        "the hanging file appears in the merged report — an absent record must "
        "stay absent, or the merge gate stops refusing on it")
    assert proc.returncode == D.RC_NORECORD, proc.stdout


def test_the_file_with_no_record_is_named(tmp_path):
    """`NORECORD  <path>` is the whole point: a 91-file run whose record is
    short by one must say WHICH one, or the reader is back to a stack dump."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_like_replay.py": _HANGS_IN_TEST})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    lines = [l for l in proc.stdout.splitlines() if l.startswith("NORECORD")]
    assert len(lines) == 1, proc.stdout
    assert "test_hangs_like_replay.py" in lines[0], lines
    assert "not clean" in lines[0], (
        "the marker must say what the absence MEANS; a bare path reads as a "
        "note rather than as 'this file's result is unknown'")


def test_progress_stall_catches_a_hang_pytest_timeout_cannot_see(tmp_path):
    """A hang during module IMPORT.

    pytest-timeout bounds test execution, so this shape has no per-test timer at
    all and `--timeout` can never fire — the process would wait forever. This is
    the case progress supervision exists for. It observes no completed pytest
    lifecycle event and stops the stall without guessing total runtime.
    """
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_hangs_at_import.py": _HANGS_AT_IMPORT,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert _files_in(merged) == ["test_green_after.py",
                                 "test_green_neighbour.py"]
    marker = [l for l in proc.stdout.splitlines() if l.startswith("NORECORD")]
    assert len(marker) == 1 and "test_hangs_at_import.py" in marker[0], marker
    assert f"STALLED after {_STALL} s" in marker[0], (
        "the marker must distinguish a progress stall from a session that "
        "merely exited without a report — they need different fixes")


def test_cpu_activity_without_pytest_progress_is_still_a_stall(tmp_path):
    """An infinite import loop is busy, but it never completes collection."""
    corpus = _tree(tmp_path, {
        "test_green_neighbour.py": _GREEN,
        "test_busy_import.py": _BURNS_CPU_AT_IMPORT,
        "test_green_after.py": _GREEN_AFTER,
    })
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert _files_in(merged) == ["test_green_after.py",
                                 "test_green_neighbour.py"]
    assert "NORECORD  test_busy_import.py  STALLED" in proc.stdout


def test_chatty_import_output_is_diagnostic_not_pytest_progress(tmp_path):
    """An import loop can log forever without completing collection."""
    corpus = _tree(tmp_path, {
        "test_green_neighbour.py": _GREEN,
        "test_chatty_import.py": _CHATTY_AT_IMPORT,
        "test_green_after.py": _GREEN_AFTER,
    })
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged, pytest_extra=("-s",))
    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert _files_in(merged) == ["test_green_after.py",
                                 "test_green_neighbour.py"]
    assert "CHATTY_SENTINEL" in proc.stdout, (
        "stdout remains available for diagnosis even though it is not progress")
    assert "NORECORD  test_chatty_import.py  STALLED" in proc.stdout


def test_silent_pytest_boundaries_keep_a_long_session_alive(
        tmp_path, monkeypatch):
    """Total runtime may exceed the grace while completed tests renew it."""
    body = "import time\n" + "\n".join(
        f"def test_{i}():\n    time.sleep(0.2)" for i in range(6)) + "\n"
    corpus = _tree(tmp_path, {"test_slow_progress.py": body})
    merged = tmp_path / "merged.xml"
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)
    started = time.monotonic()
    rc, out, incomplete = D.run_one(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        "test_slow_progress.py", merged, 0.45, str(corpus))
    elapsed = time.monotonic() - started
    assert elapsed > 0.9, elapsed
    assert rc == 0 and not incomplete, out
    suites = D._load_suites(merged)
    assert suites is not None
    assert sum(D._count(s)[0] for s in suites) == 6


def test_finite_domain_checkpoints_keep_one_long_test_item_alive(
        tmp_path, monkeypatch):
    """A bounded batch can expose real completed work inside one test item."""
    body = (
        "import time\n"
        "from _pytest_progress_plugin import domain_progress\n\n"
        "def test_one_long_batch():\n"
        "    for completed in range(1, 7):\n"
        "        time.sleep(0.2)\n"
        "        domain_progress('bounded-batch', completed, 6)\n"
    )
    corpus = _tree(tmp_path, {"test_domain_progress.py": body})
    merged = tmp_path / "merged.xml"
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)
    started = time.monotonic()
    rc, out, incomplete = D.run_one(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        "test_domain_progress.py", merged, 0.35, str(corpus))
    elapsed = time.monotonic() - started
    assert elapsed > 0.9, elapsed
    assert rc == 0 and not incomplete, out
    suites = D._load_suites(merged)
    assert suites is not None
    assert sum(D._count(s)[0] for s in suites) == 1


def test_nested_validated_progress_is_relayed_to_the_outer_session(
        tmp_path, monkeypatch):
    """An inner healthy session may outlive the outer stall window."""
    target = (_PROGRAMS / "tests" / "test_matrix_63x8_coverage.py")
    node = (str(target)
            + "::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress")
    merged = tmp_path / "outer.xml"
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)
    started = time.monotonic()
    rc, out, incomplete = D.run_one(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        node, merged, 2.5, str(_PROGRAMS.parent))
    elapsed = time.monotonic() - started
    assert elapsed > 4.5, elapsed
    assert rc == 0 and not incomplete, out
    suites = D._load_suites(merged)
    assert suites is not None
    assert sum(D._count(s)[0] for s in suites) == 1


def test_nested_collect_progress_is_relayed_to_the_outer_session(
        tmp_path, monkeypatch):
    """The live matrix collection cannot be silent until its child exits."""
    target = (_PROGRAMS / "tests" / "test_matrix_63x8_coverage.py")
    node = (str(target)
            + "::test_live_collection_relays_finite_semantic_progress_past_old_bound")
    merged = tmp_path / "outer-collect.xml"
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)
    started = time.monotonic()
    rc, out, incomplete = D.run_one(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        node, merged, 0.8, str(_PROGRAMS.parent))
    elapsed = time.monotonic() - started
    assert rc == 0 and not incomplete, out
    assert elapsed > 0.8, elapsed
    suites = D._load_suites(merged)
    assert suites is not None
    assert sum(D._count(s)[0] for s in suites) == 1


def test_pytest_deselection_is_a_complete_selected_subset(tmp_path):
    """pytest_itemcollected precedes legal -k/-m deselection."""
    corpus = _tree(tmp_path, {
        "test_subset.py": (
            "def test_a(): assert True\n"
            "def test_b(): assert True\n"),
    })
    merged = tmp_path / "subset.xml"
    rc, out, incomplete = D.run_one(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-k", "test_a"],
        "test_subset.py", merged, 1, str(corpus))
    assert rc == 0 and not incomplete, out
    suites = D._load_suites(merged)
    assert suites is not None
    assert sum(D._count(s)[0] for s in suites) == 1


def test_collect_only_has_its_own_complete_terminal_protocol(
        tmp_path, monkeypatch):
    """Zero test_finish events are valid only with the collect terminal."""
    corpus = _tree(tmp_path, {
        "test_collect_a.py": "def test_a(): assert True\n",
        "test_collect_b.py": "def test_b(): assert True\n",
    })
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.03)
    rc, out, incomplete = D.run_collect(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        ["test_collect_a.py", "test_collect_b.py"], 0.5, str(corpus))
    assert rc == 0 and not incomplete, out


def test_short_natural_collect_relays_its_terminal_protocol(tmp_path):
    """A session that exits before the first poll still relays every event."""
    corpus = _tree(tmp_path, {
        "test_short_collect.py": "def test_short(): assert True\n",
    })
    relay = tmp_path / "collect.relay"
    relay.touch(mode=0o600)
    rc, out, incomplete = D.run_collect(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"],
        ["test_short_collect.py"], 1, str(corpus),
        progress_relay_path=relay, poll_s=0.9)
    assert rc == 0 and not incomplete, out
    scores = [int(line) for line in relay.read_text().splitlines()]
    assert scores == list(range(1, len(scores) + 1))
    assert len(scores) >= 6, scores


def test_progressing_collection_may_outlive_many_stall_windows(
        tmp_path, monkeypatch):
    """Completed file collections, not a total duration, renew the lease."""
    corpus = tmp_path / "slow-collect"
    corpus.mkdir()
    paths = []
    for index in range(7):
        path = corpus / f"test_slow_collect_{index}.py"
        path.write_text(
            "import time\ntime.sleep(0.14)\n\n"
            f"def test_{index}(): assert True\n", encoding="utf-8")
        paths.append(path.name)
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.03)
    started = time.monotonic()
    rc, out, incomplete = D.run_collect(
        [sys.executable, "-m", "pytest", "-p", "no:terminal",
         "-p", "no:cacheprovider"], paths, 0.3, str(corpus))
    elapsed = time.monotonic() - started
    assert elapsed > 0.8, elapsed
    assert rc == 0 and not incomplete, out


@pytest.mark.parametrize("body,sentinel", [
    (
        "import time\n"
        "deadline=time.monotonic()+3\n"
        "while time.monotonic() < deadline:\n"
        "    print('COLLECT_CHATTER', flush=True)\n"
        "    time.sleep(.02)\n"
        "def test_never(): assert True\n",
        "COLLECT_CHATTER",
    ),
    (
        "import time\n"
        "deadline=time.monotonic()+3\n"
        "while time.monotonic() < deadline: pass\n"
        "def test_never(): assert True\n",
        None,
    ),
])
def test_collect_import_activity_without_semantic_transition_is_norecord(
        tmp_path, monkeypatch, body, sentinel):
    """Captured output and CPU cannot renew the strict collection lease."""
    corpus = tmp_path / "chatty-collect"
    corpus.mkdir()
    (corpus / "test_active.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.03)
    started = time.monotonic()
    _rc, out, incomplete = D.run_collect(
        [sys.executable, "-m", "pytest", "-s", "-q",
         "-p", "no:cacheprovider"], ["test_active.py"], 0.25, str(corpus))
    elapsed = time.monotonic() - started
    # `incomplete` plus the stall marker ARE the property: the lease was not
    # renewed and the run was cut short. If the watchdog had missed, the 3 s
    # body would have run to completion and `incomplete` would be False.
    assert incomplete, (out, f"observed {elapsed:.2f}s")
    if sentinel is not None:
        assert sentinel in out
    assert "WATCHDOG_STALLED:" in out


def test_maxfail_prefix_is_norecord_not_a_complete_failure_set(tmp_path):
    """File coverage cannot reveal the unexecuted 11th case after maxfail=10."""
    body = "\n".join(
        f"def test_{i:02d}(): assert False" for i in range(11)) + "\n"
    corpus = _tree(tmp_path, {"test_many.py": body})
    merged = tmp_path / "maxfail.xml"
    proc = _run_driver(
        corpus, merged, "--aggregate-check", "--aggregate-stall-after", "2",
        pytest_extra=("--maxfail=10",))
    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "NORECORD  test_many.py" in proc.stdout
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert _files_in(merged) == []


def test_protocol_refusal_is_not_mislabeled_as_a_stall():
    reason = D._norecord_reason(
        0, "PROGRESS_PROTOCOL_INCOMPLETE: collection mismatch\n", True, 3,
        stalled=False, protocol_error="collection mismatch")
    assert reason == "pytest progress protocol incomplete: collection mismatch"
    assert "STALLED" not in reason


def test_a_subject_that_prints_the_stall_marker_is_not_called_a_stall():
    """THE HALF THE TEST ABOVE NEVER EXERCISED, and it cost a session.

    MEASURED on clean origin/main 49d2b3328, this very file driven one at a time
    the way the landing gate drives it: `10 failed, 11 passed in 24.13s`, natural
    exit, truncated at 21 of 72 items by its own `--maxfail` bound — reported as
    `STALLED after 300 s`. The only `WATCHDOG_STALLED:` in the whole buffer came
    from an assertion dump belonging to this file's own test of the stall
    detector. The supervisor's watchdog never fired.
    """
    out = ("E   AssertionError: assert 'X' in '\\nWATCHDOG_STALLED: configured "
           "forward-progress signals did not advance for > 0.25s\\n'\n"
           "PROGRESS_PROTOCOL_INCOMPLETE: m.16.1.jsonl: session finished before "
           "every selected item completed (21/72)\n")
    reason = D._norecord_reason(
        1, out, True, 300, stalled=False,
        protocol_error="m.16.1.jsonl: session finished before every selected "
                       "item completed (21/72)")
    assert reason == ("pytest progress protocol incomplete: m.16.1.jsonl: session "
                      "finished before every selected item completed (21/72)")
    assert "STALLED" not in reason


def test_a_stall_the_supervisor_actually_saw_is_still_called_a_stall():
    """The other direction: the label must survive where it is TRUE."""
    reason = D._norecord_reason(None, "", True, 300, stalled=True,
                                protocol_error="")
    assert reason == ("STALLED after 300 s with no validated pytest lifecycle "
                      "progress")


def test_the_stall_verdict_is_a_required_argument():
    """A caller that forgets it must not silently inherit the old guess."""
    with pytest.raises(TypeError):
        D._norecord_reason(1, "", True, 300)
    with pytest.raises(TypeError):
        D._norecord_reason(1, "", True, 300, stalled=False)


def test_progress_stall_cleans_a_descendant_that_escaped_the_process_group(
        tmp_path, monkeypatch):
    """A fixture may launch a dashboard daemon with start_new_session=True.

    Killing only pytest's process group leaves that daemon alive to consume CPU,
    occupy a port or write into the next arm's checkout. The subreaper must keep
    it attributable and cleanup must verify that it is gone.
    """
    pid_file = tmp_path / "escaped.pid"
    late_file = tmp_path / "late-write"
    child = (
        "import pathlib,time; time.sleep(1); "
        f"pathlib.Path({str(late_file)!r}).write_text('leaked')"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import pathlib,subprocess,sys,time\n"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}], "
        "start_new_session=True)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(3600)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)

    _rc, out, incomplete = D._run_progress_supervised(
        [sys.executable, str(parent)], 0.25, str(tmp_path))

    assert incomplete, out
    escaped_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(escaped_pid, 0)
    # Cleanup returned only after the descendant was gone; it cannot perform
    # the delayed write after this assertion either.
    time.sleep(1.1)
    assert not late_file.exists(), out


def test_natural_exit_reaps_dead_adopted_zombie_without_norecord(
        tmp_path):
    """A dead child awaiting its subreaper is bookkeeping, not live work."""
    pid_file = tmp_path / "zombie.pid"
    corpus = _tree(tmp_path, {
        "test_zombie.py": (
            "import os,pathlib,time\n"
            "def test_leaves_an_unwaited_dead_child():\n"
            "    pid=os.fork()\n"
            "    if pid == 0: os._exit(0)\n"
            "    deadline=time.monotonic()+2\n"
            "    state=''\n"
            "    while time.monotonic() < deadline:\n"
            "        raw=pathlib.Path(f'/proc/{pid}/stat').read_text()\n"
            "        state=raw[raw.rfind(')')+2:].split()[0]\n"
            "        if state == 'Z': break\n"
            "        time.sleep(.01)\n"
            f"    pathlib.Path({str(pid_file)!r}).write_text(str(pid))\n"
            "    assert state == 'Z'\n")})
    junit = tmp_path / "zombie-reaped.xml"

    proc = _run_driver(
        corpus, junit, "--aggregate-check", "--aggregate-only",
        "--aggregate-stall-after", "3")

    assert proc.returncode == D.RC_OK, proc.stdout + proc.stderr
    assert "AGGREGATE_COMPLETE  rc=0" in proc.stdout
    assert "DESCENDANT" not in proc.stdout
    zombie_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(zombie_pid, 0)
    assert _files_in(junit) == ["<aggregate>", "test_zombie.py"]


def test_natural_exit_with_live_descendant_is_norecord_after_cleanup(
        tmp_path):
    """Killing unfinished asynchronous work must never turn JUnit green."""
    pid_file = tmp_path / "live.pid"
    late_file = tmp_path / "live-late-write"
    child = (
        "import pathlib,time; time.sleep(1); "
        f"pathlib.Path({str(late_file)!r}).write_text('leaked')")
    corpus = _tree(tmp_path, {
        "test_live.py": (
            "import pathlib,subprocess,sys\n"
            "def test_returns_before_child_finishes():\n"
            f"    p=subprocess.Popen([sys.executable,'-c',{child!r}], "
            "start_new_session=True)\n"
            f"    pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
            "    assert True\n")})
    junit = tmp_path / "live-cleaned.xml"

    proc = _run_driver(
        corpus, junit, "--aggregate-check", "--aggregate-only",
        "--aggregate-stall-after", "3")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "LIVE_DESCENDANTS_CLEANED:" in proc.stdout
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert _files_in(junit) == []
    escaped_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(escaped_pid, 0)
    time.sleep(1.1)
    assert not late_file.exists(), proc.stdout


def test_unproved_final_descendant_census_is_norecord(tmp_path, monkeypatch):
    """Never turn attempted cleanup into proof that cleanup succeeded."""
    corpus = _tree(tmp_path, {"test_green.py": _GREEN})
    junit = tmp_path / "unproved-cleanup.xml"
    real_cleanup = D._cleanup_job

    def unproved(root_pid, baseline, **kwargs):
        cleaned = real_cleanup(root_pid, baseline, **kwargs)
        return D.CleanupResult(
            cleaned.observed, {999999}, cleaned.census_ok)

    # Force the post-exit cleanup path while allowing the real helper cleanup
    # to run.  The fake survivor represents D-state/permission-denied residue.
    real_jobs = D._job_processes_checked
    calls = {"n": 0}

    def one_live_then_real(root_pid, baseline):
        calls["n"] += 1
        if calls["n"] == 1:
            return ({999999: 1}, True)
        return real_jobs(root_pid, baseline)

    monkeypatch.setattr(D, "_job_processes_checked", one_live_then_real)
    monkeypatch.setattr(D, "_cleanup_job", unproved)
    monkeypatch.setattr(D, "DEFAULT_POLL_S", 0.05)

    rc, out, incomplete = D.run_one(
        _pytest_cmd(), "test_green.py", junit, 2, str(corpus))

    assert rc == 0 and incomplete, out
    assert "DESCENDANT_CLEANUP_INCOMPLETE:" in out
    assert "survivors=[999999]" in out


def test_cleanup_retains_subreaper_until_sigkill_pending_identity_is_zero(
        monkeypatch):
    """The old post-KILL grace may expire; ownership must not expire with it."""
    identity = {424242: 73}
    scans = iter([
        (dict(identity), True),
        ({}, True),
        ({}, True),
    ])
    waited = []

    monkeypatch.setattr(
        D, "_job_processes_checked", lambda _root, _baseline: next(scans))
    monkeypatch.setattr(
        D, "_open_pidfds", lambda ids: ({91: (424242, 73)}, True)
        if ids else ({}, True))
    monkeypatch.setattr(D, "_signal_pidfds", lambda _fds, _sig: True)
    # TERM and the finite post-KILL observability interval both expire while
    # the same kernel identity remains live.
    monkeypatch.setattr(
        D, "_wait_pidfds_until", lambda handles, _deadline: dict(handles))

    def final_kernel_event(handles):
        assert handles == {91: (424242, 73)}
        waited.append("final-zero")

    monkeypatch.setattr(D, "_wait_pidfds", final_kernel_event)
    monkeypatch.setattr(D, "_close_pidfds", lambda _handles: None)
    monkeypatch.setattr(D, "_reap_adopted", lambda: None)

    result = D._cleanup_job(424242, set(), term_grace_s=0)

    assert waited == ["final-zero"]
    assert result.observed == {424242}
    assert result.survivors == set()
    assert result.census_ok is True


def test_cleanup_latches_first_signal_until_final_zero(monkeypatch):
    completed = []

    def final_zero(_root_pid, _baseline, *, term_grace_s):
        assert term_grace_s == 0
        assert D._CLEANUP_ACTIVE
        D._shutdown_handler(signal.SIGTERM, None)
        completed.append("final-zero")
        return D.CleanupResult(set(), set(), True)

    monkeypatch.setattr(D, "_IN_SHUTDOWN", False)
    monkeypatch.setattr(D, "_CLEANUP_ACTIVE", False)
    monkeypatch.setattr(D, "_PENDING_SHUTDOWN_SIGNAL", None)
    monkeypatch.setattr(D, "_block_shutdown_signals", lambda: None)
    monkeypatch.setattr(D, "_cleanup_job_owned", final_zero)

    with pytest.raises(SystemExit) as cancelled:
        D._cleanup_job(424242, set(), term_grace_s=0)

    assert cancelled.value.code == 128 + signal.SIGTERM
    assert completed == ["final-zero"]
    assert not D._CLEANUP_ACTIVE


def test_term_during_cleanup_cancels_before_fallback_and_leaves_zero(
        tmp_path):
    corpus = _tree(tmp_path, {"test_green.py": _GREEN})
    aggregate_pid_file = tmp_path / "aggregate.pid"
    descendant_pid_file = tmp_path / "detached.pid"
    cleanup_term_seen = tmp_path / "cleanup-term-seen"
    fallback_marker = tmp_path / "fallback-launched"
    detached = (
        "import os,pathlib,signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(descendant_pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(3600)"
    )
    (corpus / "conftest.py").write_text(
        "import os,pathlib,signal,subprocess,sys,time\n"
        f"if os.environ.get({_FALLBACK_ENV!r}) == '1':\n"
        f"    pathlib.Path({str(fallback_marker)!r}).write_text('launched')\n"
        "else:\n"
        f"    pathlib.Path({str(aggregate_pid_file)!r}).write_text(str(os.getpid()))\n"
        "    def ignore_term(_signum, _frame):\n"
        f"        pathlib.Path({str(cleanup_term_seen)!r}).write_text('seen')\n"
        "    signal.signal(signal.SIGTERM, ignore_term)\n"
        f"    subprocess.Popen([sys.executable, '-c', {detached!r}], "
        "start_new_session=True)\n"
        "    time.sleep(3600)\n",
        encoding="utf-8",
    )
    merged = tmp_path / "cancelled.xml"
    driver = subprocess.Popen(
        [sys.executable, str(_PROG), "--selection",
         str(corpus / "selection.txt"), "--junit", str(merged),
         "--stall-after", "5", "--aggregate-check",
         "--aggregate-stall-after", "0.5", "--fallback-jobs", "1",
         "--"] + _pytest_cmd(),
        cwd=str(corpus), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"))
    output = ""
    try:
        _await("aggregate-cleanup-grace",
               lambda: (aggregate_pid_file.is_file()
                        and descendant_pid_file.is_file()
                        and cleanup_term_seen.is_file()),
               driver)
        assert cleanup_term_seen.is_file(), (
            "aggregate cleanup never entered its TERM-ignoring grace")
        os.kill(driver.pid, signal.SIGTERM)
        _await_exit("aggregate-cleanup-term", driver)
        output = driver.communicate()[0]
        assert driver.returncode == 128 + signal.SIGTERM, output
        assert "=== [fallback]" not in output, output
        assert not fallback_marker.exists(), output
        for pid_path in (aggregate_pid_file, descendant_pid_file):
            pid = int(pid_path.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if driver.poll() is None:
            os.killpg(driver.pid, signal.SIGKILL)
            # Unbounded: after SIGKILL to the group what is meant is "reaped",
            # and a bound here could only report a busy host as a leak.
            driver.wait()
        for pid_path in (aggregate_pid_file, descendant_pid_file):
            if not pid_path.is_file():
                continue
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_driver_signal_cleanup_reaps_the_active_detached_descendant(tmp_path):
    """Verifier cancellation reaches the driver, not its new-session child."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    pid_file = tmp_path / "signal-escaped.pid"
    late_file = tmp_path / "signal-late-write"
    child = (
        "import pathlib,time; time.sleep(2); "
        f"pathlib.Path({str(late_file)!r}).write_text('leaked')"
    )
    (corpus / "test_signal_cleanup.py").write_text(
        "import pathlib,subprocess,sys,time\n"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}], "
        "start_new_session=True)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(3600)\n"
        "def test_never_reached(): assert True\n",
        encoding="utf-8",
    )
    (corpus / "selection.txt").write_text(
        "test_signal_cleanup.py\n", encoding="utf-8")
    merged = tmp_path / "signal.xml"
    driver = subprocess.Popen(
        [sys.executable, str(_PROG), "--selection",
         str(corpus / "selection.txt"), "--junit", str(merged),
         "--stall-after", "30", "--"] + _pytest_cmd(),
        cwd=str(corpus), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    _await("detached-child-launch", pid_file.is_file, driver)
    assert pid_file.is_file(), "fixture never launched its detached child"
    escaped_pid = int(pid_file.read_text())

    os.kill(driver.pid, signal.SIGTERM)
    _await_exit("detached-child-term", driver)

    with pytest.raises(ProcessLookupError):
        os.kill(escaped_pid, 0)
    time.sleep(2.1)
    assert not late_file.exists()


def test_aggregate_canary_preserves_cross_file_process_semantics(tmp_path):
    """One process per file must not isolate away an order/pollution failure."""
    corpus = _tree(tmp_path, {
        "test_01_mutate.py": (
            "import shared_state\n"
            "def test_mutates_process_global():\n"
            "    shared_state.value = 1\n"),
        "test_02_check.py": (
            "import shared_state\n"
            "def test_requires_clean_process_global():\n"
            "    assert shared_state.value == 0\n"),
    })
    (corpus / "shared_state.py").write_text("value = 0\n", encoding="utf-8")
    merged = tmp_path / "merged.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", str(_STALL))

    assert proc.returncode == D.RC_RED, proc.stdout + proc.stderr
    assert "AGGREGATE_COMPLETE  rc=1" in proc.stdout, proc.stdout
    root = ET.parse(str(merged)).getroot()
    aggregate_failures = [tc for tc in root.iter("testcase")
                          if (tc.get("classname") or "").startswith(
                              "pytest_aggregate.")
                          and list(tc.iter("failure"))]
    assert len(aggregate_failures) == 1, ET.tostring(root)
    assert "test_02_check" in aggregate_failures[0].get("classname")


def test_complete_aggregate_check_does_not_launch_per_file_sessions(
        tmp_path, monkeypatch):
    """The healthy landing path asks the whole-selection question once.

    `--aggregate-check` is aggregate-first: isolated sessions are diagnostic
    recovery, not a tax paid by every complete run.
    """
    corpus = _tree(tmp_path, {
        "test_first.py": _GREEN,
        "test_second.py": _GREEN_AFTER,
    })
    sessions = tmp_path / "sessions.txt"
    monkeypatch.setenv("VIBEIC_SESSION_COUNTER", str(sessions))
    (corpus / "conftest.py").write_text(
        "import os\n"
        "def pytest_sessionstart(session):\n"
        "    with open(os.environ['VIBEIC_SESSION_COUNTER'], 'a') as f:\n"
        "        f.write('session\\n')\n",
        encoding="utf-8",
    )
    merged = tmp_path / "aggregate-only.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", str(_STALL))

    assert proc.returncode == D.RC_OK, proc.stdout + proc.stderr
    assert sessions.read_text().splitlines() == ["session"]
    assert "AGGREGATE_COMPLETE  rc=0" in proc.stdout
    assert "=== [1/" not in proc.stdout
    root = ET.parse(str(merged)).getroot()
    assert not [tc for tc in root.iter("testcase")
                if tc.get("classname") == "pytest_per_file_process"]
    assert len([tc for tc in root.iter("testcase")
                if tc.get("classname") == "pytest_aggregate_process"]) == 1


def test_aggregate_refuses_a_selected_file_that_collected_no_tests(tmp_path):
    """rc=0 and one green case cannot shrink a two-file denominator."""
    corpus = _tree(tmp_path, {
        "test_empty.py": "# selected, but contains no pytest item\n",
        "test_green.py": _GREEN,
    })
    merged = tmp_path / "aggregate-missing-file.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check", "--aggregate-only",
        "--aggregate-stall-after", str(_STALL))

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert "does not exactly cover the selected files" in proc.stdout
    assert "test_empty.py" in proc.stdout
    assert _files_in(merged) == []


def test_duplicate_selected_file_is_refused_before_pytest_runs(tmp_path):
    corpus = _tree(tmp_path, {"test_green.py": _GREEN})
    (corpus / "selection.txt").write_text(
        "test_green.py\n./test_green.py\n", encoding="utf-8")
    merged = tmp_path / "duplicate-selection.xml"

    proc = _run_driver(corpus, merged, "--aggregate-check")

    assert proc.returncode == D.RC_CANNOT_ASK, proc.stdout + proc.stderr
    assert "same file more than once" in proc.stderr
    assert not merged.exists()


def test_aggregate_norecord_runs_diagnostic_fallback_and_stays_unknown(
        tmp_path):
    """UNKNOWN is refused, after preserving every recoverable file record."""
    corpus = _tree(tmp_path, {
        "test_01_mutate.py": (
            "import shared_state\n"
            "def test_mutates_process_global():\n"
            "    shared_state.value = 1\n"),
        "test_02_hang.py": (
            "import shared_state, time\n"
            "def test_hangs_only_after_the_other_file():\n"
            "    if shared_state.value:\n"
            "        time.sleep(3600)\n"),
        "test_03_green.py": _GREEN,
        "test_04_green.py": _GREEN_AFTER,
        "test_05_green.py": _GREEN,
    })
    (corpus / "shared_state.py").write_text("value = 0\n", encoding="utf-8")
    merged = tmp_path / "aggregate-norecord.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", "1", "--fallback-jobs", "2")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert "=== [1/" in proc.stdout
    assert proc.stdout.index("=== [aggregate]") < proc.stdout.index("=== [1/")
    assert "FALLBACK_SYSTEMIC_NORECORD" not in proc.stdout
    assert proc.stdout.count("FALLBACK_PROGRESS") == 5
    expected_files = [
        "test_01_mutate.py", "test_02_hang.py", "test_03_green.py",
        "test_04_green.py", "test_05_green.py"]
    assert _files_in(merged) == expected_files
    root = ET.parse(str(merged)).getroot()
    assert [suite.get("name") for suite in root.iter("testsuite")
            if suite.get("name") in expected_files] == expected_files
    assert len([tc for tc in root.iter("testcase")
                if tc.get("classname") == "pytest_per_file_process"]) == 5
    assert not [tc for tc in ET.parse(str(merged)).iter("testcase")
                if (tc.get("classname") or "").startswith("pytest_aggregate.")]


def test_aggregate_loss_confines_norecord_to_the_hanging_file(tmp_path):
    """The #1654 shape keeps both neighbouring records after aggregate loss."""
    corpus = _tree(tmp_path, {
        "test_green_neighbour.py": _GREEN,
        "test_hangs_at_import.py": _HANGS_AT_IMPORT,
        "test_green_after.py": _GREEN_AFTER,
    })
    merged = tmp_path / "aggregate-fallback.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check", "--aggregate-stall-after", "1")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert proc.stdout.index("=== [aggregate]") < proc.stdout.index("=== [1/")
    markers = [line for line in proc.stdout.splitlines()
               if line.startswith("NORECORD")]
    assert len(markers) == 1, proc.stdout
    assert "test_hangs_at_import.py" in markers[0]
    assert "not clean" in markers[0]
    assert _files_in(merged) == ["test_green_after.py",
                                 "test_green_neighbour.py"]


@pytest.mark.parametrize("reverse", [False, True], ids=[
    "eight-local-hangs-first", "two-green-files-first"])
def test_stratified_probe_preserves_late_and_early_green_files(
        tmp_path, reverse):
    """A lexical cluster of local hangs is not a systemic corpus failure.

    The forward order is the adversarial shape: eight file-local import hangs
    occupy the old consecutive first wave and two recoverable green files sit at
    the tail. The reverse order proves that a later consecutive all-NORECORD wave
    cannot truncate recovery either. Both orders must recover the same two files
    and merge them in selection order.
    """
    ordered = [
        (f"test_{i:02d}_local_hang.py", (
            "import os,time\n"
            f"if os.environ.get({_FALLBACK_ENV!r}) == '1':\n"
            "    time.sleep(3600)\n"
            f"def test_{i:02d}(): assert True\n"))
        for i in range(1, 9)
    ] + [
        ("test_09_green.py", _GREEN),
        ("test_10_green.py", _GREEN_AFTER),
    ]
    if reverse:
        ordered.reverse()
    corpus = _tree(tmp_path, dict(ordered))
    (corpus / "conftest.py").write_text(
        "import os,time\n"
        f"if os.environ.get({_FALLBACK_ENV!r}) != '1':\n"
        "    time.sleep(3600)\n",
        encoding="utf-8",
    )
    merged = tmp_path / "stratified-local-cluster.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", "1", "--fallback-jobs", "8")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert ("FALLBACK_STRATIFIED_PROBE  "
            "indices=1,2,4,5,6,7,9,10") in proc.stdout
    assert "FALLBACK_SYSTEMIC_NORECORD" not in proc.stdout
    assert proc.stdout.count("FALLBACK_PROGRESS") == 10
    assert len([line for line in proc.stdout.splitlines()
                if line.startswith("NORECORD  ")]) == 8
    assert not [line for line in proc.stdout.splitlines()
                if line.startswith("NOTRUN    ")]

    selected = [name for name, _body in ordered]
    headings = [line for line in proc.stdout.splitlines()
                if line.startswith("=== [")
                and line.endswith("[fallback worker]")]
    assert headings == [
        f"=== [{i}/10] {name} [fallback worker]"
        for i, name in enumerate(selected, start=1)]
    expected_green = [name for name in selected if "green" in name]
    assert _files_in(merged) == sorted(expected_green)
    root = ET.parse(str(merged)).getroot()
    assert [suite.get("name") for suite in root.iter("testsuite")
            if suite.get("name") in expected_green] == expected_green


def test_zero_record_probe_still_attempts_the_one_unprobed_green_file(
        tmp_path):
    """Eight sampled hangs cannot prove that an untried ninth file hangs.

    This is the exact counterexample from the #1654 shipping review: with nine
    files and the eight-worker first probe, index 5 is the sole unprobed index.
    The other eight files hang only in fallback workers and the whole aggregate
    hangs in a shared conftest.  A sample-based systemic breaker therefore loses
    the one recoverable record.  Recovery must instead attempt every file.
    """
    probe_indices = D._stratified_probe_indices(9, 8)
    assert probe_indices == [1, 2, 3, 4, 6, 7, 8, 9]
    files = {}
    for index in range(1, 10):
        name = f"test_{index:02d}_{'green' if index == 5 else 'hang'}.py"
        if index == 5:
            files[name] = _GREEN
        else:
            files[name] = (
                "import os,time\n"
                f"if os.environ.get({_FALLBACK_ENV!r}) == '1':\n"
                "    time.sleep(3600)\n"
                f"def test_{index:02d}(): assert True\n")
    corpus = _tree(tmp_path, files)
    (corpus / "conftest.py").write_text(
        "import os,time\n"
        f"if os.environ.get({_FALLBACK_ENV!r}) != '1':\n"
        "    time.sleep(3600)\n",
        encoding="utf-8",
    )
    merged = tmp_path / "unprobed-green.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", "1", "--fallback-jobs", "8")

    # Value first: this is what makes the pre-fix control substantive.  The old
    # breaker returns [] and labels test_05_green.py NOTRUN.
    assert _files_in(merged) == ["test_05_green.py"], proc.stdout + proc.stderr
    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert proc.stdout.count("FALLBACK_PROGRESS") == 9
    assert len([line for line in proc.stdout.splitlines()
                if line.startswith("NORECORD  ")]) == 8
    assert not [line for line in proc.stdout.splitlines()
                if line.startswith("NOTRUN    ")]


def test_aggregate_norecord_fallback_ignores_legacy_failure_threshold(
        tmp_path):
    """Once aggregate evidence is lost, every fallback path needs an outcome.

    This is the exact nine-file counterexample from the final #1654 review.
    The stratified eight-worker probe omits index 5.  One probed file alone
    contributes ten red cases, so the legacy per-file failure threshold is
    already reached before the sole green file is considered.  That threshold
    may bound an ordinary non-aggregate run, but it cannot truncate diagnostic
    recovery after aggregate NORECORD: doing so erases the only recoverable
    green record and makes the fallback evidence a sampled prefix again.
    """
    probe_indices = D._stratified_probe_indices(9, 8)
    assert probe_indices == [1, 2, 3, 4, 6, 7, 8, 9]
    ten_red = "".join(
        f"def test_red_{i}():\n    assert False\n\n" for i in range(10))
    files = {}
    for index in range(1, 10):
        name = f"test_{index:02d}_{'green' if index == 5 else 'red'}.py"
        files[name] = (_GREEN if index == 5 else
                       (ten_red if index == 1 else _RED))
    corpus = _tree(tmp_path, files)
    (corpus / "conftest.py").write_text(
        "import os,time\n"
        f"if os.environ.get({_FALLBACK_ENV!r}) != '1':\n"
        "    time.sleep(3600)\n",
        encoding="utf-8",
    )
    merged = tmp_path / "aggregate-norecord-threshold.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", "1", "--fallback-jobs", "8",
        "--stop-after-failures", "10")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout
    assert proc.stdout.count("FALLBACK_PROGRESS") == 9
    assert not [line for line in proc.stdout.splitlines()
                if line.startswith("NORECORD  ")]
    assert not [line for line in proc.stdout.splitlines()
                if line.startswith("NOTRUN    ")]
    selected = list(files)
    headings = [line for line in proc.stdout.splitlines()
                if line.startswith("=== [")
                and line.endswith("[fallback worker]")]
    assert headings == [
        f"=== [{i}/9] {name} [fallback worker]"
        for i, name in enumerate(selected, start=1)]
    assert _files_in(merged) == sorted(selected)
    assert "test_05_green.py" in _files_in(merged)


def test_rescue_parallelism_has_cpu_memory_pid_and_absolute_hard_caps(
        monkeypatch):
    """Corpus size/request alone can never become the process-pool width."""
    monkeypatch.setattr(D, "_available_cpu_count", lambda: 3)
    monkeypatch.setattr(
        D, "_available_memory_bytes",
        lambda: (D._FALLBACK_MEMORY_RESERVE_BYTES
                 + 7 * D._FALLBACK_MEMORY_PER_JOB_BYTES))
    monkeypatch.setattr(
        D, "_cgroup_pid_headroom",
        lambda: D._FALLBACK_PID_RESERVE + 5 * D._FALLBACK_PIDS_PER_JOB)

    capacity = D._fallback_capacity(64, 1000)

    assert capacity.jobs == 5
    assert capacity.cpu_cap == 6
    assert capacity.memory_cap == 7
    assert capacity.pid_cap == 5
    assert capacity.hard_cap == D.MAX_FALLBACK_PROCESSES

    monkeypatch.setattr(D, "_available_cpu_count", lambda: 10_000)
    monkeypatch.setattr(D, "_available_memory_bytes", lambda: 1 << 60)
    monkeypatch.setattr(D, "_cgroup_pid_headroom", lambda: 1 << 30)
    assert (D._fallback_capacity(10_000, 10_000).jobs
            == D.MAX_FALLBACK_PROCESSES)


def test_systemic_import_hang_recovery_is_bounded_parallel_not_serial(
        tmp_path):
    """A shared collection hang must not multiply one stall by every file.

    The aggregate and every recovery worker deliberately hang in the common
    conftest. Nine files exceed the default eight-worker probe width. The first
    wave spans eight paths; the resource-capped rescue must still attempt the
    ninth. This costs two bounded parallel fallback waves, not nine serial stall
    windows, while aggregate UNKNOWN remains rc=2.
    """
    count = D.DEFAULT_FALLBACK_JOBS + 1
    corpus = _tree(tmp_path, {
        f"test_neighbour_{i}.py": (
            f"def test_neighbour_{i}():\n    assert {i} == {i}\n")
        for i in range(count)
    })
    markers = tmp_path / "fallback-workers"
    markers.mkdir()
    (corpus / "conftest.py").write_text(
        "import os, pathlib, time\n"
        f"root = pathlib.Path({str(markers)!r})\n"
        f"if os.environ.get({_FALLBACK_ENV!r}) == '1':\n"
        "    (root / str(os.getpid())).touch()\n"
        "time.sleep(3600)\n",
        encoding="utf-8",
    )
    merged = tmp_path / "systemic-import-hang.xml"

    started = time.monotonic()
    proc = _run_driver(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", "1")
    elapsed = time.monotonic() - started

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout
    # PARALLEL, NOT SERIAL — COUNTED IN WAVES, NOT SECONDS.
    #
    # This used to be `elapsed < 18`, and the comment was honest about what that
    # meant: "a few seconds ON THIS HOST". A wall clock answers "how long has it
    # been", which is not the question — the claim is about the SHAPE of the
    # recovery, and a loaded host can push a correct two-wave recovery past any
    # constant while a serial nine-wave one passes on an idle one.
    #
    # The shape is directly countable. Every wave announces itself: the first
    # emits ONE `FALLBACK_STRATIFIED_PROBE` line and the resource-capped rescue
    # emits ONE `FALLBACK_ZERO_RECORD_RESCUE`. Two lines, for the two waves the
    # docstring promises. A serial implementation — one probe per file — emits
    # `count` of them, so this fails for exactly the defect the stopwatch was
    # aimed at and cannot be flipped by another tenant.
    waves = len([ln for ln in proc.stdout.splitlines()
                 if ln.startswith("FALLBACK_STRATIFIED_PROBE")])
    rescues = len([ln for ln in proc.stdout.splitlines()
                   if "FALLBACK_ZERO_RECORD_RESCUE" in ln])
    assert (waves, rescues) == (1, 1), (
        f"{waves} probe wave(s) + {rescues} rescue(s) for {count} files — a "
        f"bounded parallel recovery is TWO waves, a serial one is {count} "
        f"(observed {elapsed:.2f}s):\n{proc.stdout}")
    probe_indices = D._stratified_probe_indices(
        count, D.DEFAULT_FALLBACK_JOBS)
    assert probe_indices == [1, 2, 3, 4, 6, 7, 8, 9]
    assert ("FALLBACK_STRATIFIED_PROBE  indices="
            + ",".join(str(i) for i in probe_indices)) in proc.stdout
    assert len(list(markers.iterdir())) == count
    assert len([line for line in proc.stdout.splitlines()
                if line.startswith("NORECORD  ")]) == count
    assert not [line for line in proc.stdout.splitlines()
                if line.startswith("NOTRUN    ")]
    assert "FALLBACK_SYSTEMIC_NORECORD" not in proc.stdout
    assert "FALLBACK_ZERO_RECORD_RESCUE" in proc.stdout
    assert "phase=zero-record-rescue" in proc.stdout
    assert "test_neighbour_4.py [fallback worker]" in proc.stdout
    assert _files_in(merged) == []


def test_signal_during_parallel_fallback_reaps_detached_descendant(tmp_path):
    """Cancelling the pool cannot leave a worker's session escapee writing late."""
    pid_file = tmp_path / "fallback-escaped.pid"
    late_file = tmp_path / "fallback-late-write"
    child = (
        "import pathlib,time; time.sleep(2); "
        f"pathlib.Path({str(late_file)!r}).write_text('leaked')"
    )
    corpus = _tree(tmp_path, {
        "test_00_aggregate_trigger.py": (
            "import os,time\n"
            f"if os.environ.get({_FALLBACK_ENV!r}) != '1':\n"
            "    time.sleep(3600)\n"
            "def test_trigger_recovers(): assert True\n"),
        "test_01_worker_escape.py": (
            "import os,pathlib,subprocess,sys,time\n"
            f"if os.environ.get({_FALLBACK_ENV!r}) == '1':\n"
            f"    p=subprocess.Popen([sys.executable,'-c',{child!r}], "
            "start_new_session=True)\n"
            f"    pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
            "    time.sleep(3600)\n"
            "def test_never_reached(): assert True\n"),
    })
    merged = tmp_path / "parallel-signal.xml"
    driver = subprocess.Popen(
        [sys.executable, str(_PROG), "--selection",
         str(corpus / "selection.txt"), "--junit", str(merged),
         "--stall-after", "30", "--aggregate-check",
         "--aggregate-stall-after", "1", "--"] + _pytest_cmd(),
        cwd=str(corpus), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    try:
        _await("parallel-escapee-launch", pid_file.is_file, driver)
        assert pid_file.is_file(), "parallel fallback never launched its escapee"
        escaped_pid = int(pid_file.read_text())

        os.kill(driver.pid, signal.SIGTERM)
        _await_exit("parallel-escapee-term", driver)

        with pytest.raises(ProcessLookupError):
            os.kill(escaped_pid, 0)
        time.sleep(2.1)
        assert not late_file.exists()
    finally:
        if driver.poll() is None:
            os.killpg(driver.pid, signal.SIGKILL)
            # Unbounded: after SIGKILL to the group what is meant is "reaped",
            # and a bound here could only report a busy host as a leak.
            driver.wait()


def test_aggregate_norecord_is_named_and_returns_unknown(tmp_path):
    """Per-file green cannot excuse a whole-selection canary that was killed."""
    corpus = _tree(tmp_path, {
        "test_01_mutate.py": (
            "import shared_state\n"
            "def test_mutates_process_global():\n"
            "    shared_state.value = 1\n"),
        "test_02_hang.py": (
            "import shared_state, time\n"
            "def test_hangs_only_after_the_other_file():\n"
            "    if shared_state.value:\n"
            "        time.sleep(3600)\n"
            "    assert shared_state.value == 0\n"),
    })
    (corpus / "shared_state.py").write_text("value = 0\n", encoding="utf-8")
    merged = tmp_path / "merged.xml"

    proc = _run_driver(
        corpus, merged, "--aggregate-check", "--aggregate-stall-after", "1")

    assert proc.returncode == D.RC_NORECORD, proc.stdout + proc.stderr
    assert "AGGREGATE_NORECORD" in proc.stdout, proc.stdout
    # The per-file record survives; aggregate unknown is a separate hard bar.
    assert _files_in(merged) == ["test_01_mutate.py", "test_02_hang.py"]


# ── the report the merge gate has to be able to read ─────────────────────────

def test_the_merged_report_is_xunit1_and_carries_the_file_attribute(tmp_path):
    """`landing_merge_verdict._file_of` prefers the `file` attribute and only
    falls back to the dotted classname. xunit2 — pytest's default — drops it, so
    a merged report without it cannot answer 'did every selected file run'."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_OK, proc.stdout
    root = ET.parse(str(merged)).getroot()
    cases = list(root.iter("testcase"))
    assert len(cases) == 4, ET.tostring(root)
    assert all(tc.get("file") for tc in cases), ET.tostring(root)
    # NAMED BY FILE. pytest calls every suite "pytest"; a merged report of N
    # identically-named blocks cannot be read back to its arms.
    assert sorted(s.get("name") for s in root.iter("testsuite")) == [
        "test_green_after.py", "test_green_after.py::process_exit",
        "test_green_neighbour.py", "test_green_neighbour.py::process_exit"]


def test_a_red_test_is_a_red_run_not_a_missing_record(tmp_path):
    """The two must not collapse into each other. An ordinary failure keeps its
    record and reports rc 1; only a missing record reports rc 2."""
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN,
                              "test_red.py": _RED})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_RED, proc.stdout
    assert not [l for l in proc.stdout.splitlines()
                if l.startswith("NORECORD")], proc.stdout
    assert _files_in(merged) == ["test_green_neighbour.py", "test_red.py"]
    root = ET.parse(str(merged)).getroot()
    assert len(list(root.iter("failure"))) == 2
    process_cases = [tc for tc in root.iter("testcase")
                     if tc.get("classname") == "pytest_per_file_process"]
    assert len(process_cases) == 2, (
        "the stable process key must exist on both rc=0 and rc=1 arms; a "
        "failure-only key would become ABSENT after a fix and be called "
        "SILENCED")


def test_a_session_level_red_is_not_erased_by_green_testcase_xml(tmp_path):
    """A junit report does not carry every reason pytest can exit non-zero.

    `suite_write_guard` and `not_verified_tier` both set
    ``session.exitstatus = 1`` after ordinary testcase reporting.  In that
    shape every testcase in junit is green while the SESSION is red.  The
    driver must preserve the process verdict instead of manufacturing a pass.
    """
    corpus = _tree(tmp_path, {"test_green_neighbour.py": _GREEN})
    (corpus / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 1\n",
        encoding="utf-8",
    )
    merged = tmp_path / "merged.xml"

    proc = _run_driver(corpus, merged)

    assert proc.returncode == D.RC_RED, proc.stdout + proc.stderr
    root = ET.parse(str(merged)).getroot()
    assert len(list(root.iter("testcase"))) == 2
    failures = list(root.iter("failure"))
    assert len(failures) == 1
    assert failures[0].get("type") == "pytest.session.ExitCode"
    session_cases = [tc for tc in root.iter("testcase")
                     if tc.get("classname") == "pytest_per_file_process"]
    assert len(session_cases) == 1
    assert session_cases[0].get("file") == "test_green_neighbour.py"
    assert session_cases[0].get("name").endswith("process_exit")
    prop = next(p for p in session_cases[0].iter("property")
                if p.get("name") == "process_rc")
    assert prop.get("value") == "1"
    assert not list(root.iter("error"))
    assert "rc=1  cases=1  red=0  red" in proc.stdout, proc.stdout


def test_an_empty_selection_is_refused_and_never_a_pass(tmp_path):
    """An empty corpus is a VACUOUS pass, not a pass — the same rule
    `gatekeeper-land.sh` applies to its own discovery."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "selection.txt").write_text("", encoding="utf-8")
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged)
    assert proc.returncode == D.RC_CANNOT_ASK, proc.stdout + proc.stderr
    assert "EMPTY" in proc.stderr.upper()


def test_files_not_launched_are_named_rather_than_looking_clean(tmp_path):
    """`--stop-after-failures` truncates on purpose. A truncated run has no
    failed SET, only a prefix of one, so what it did not launch must be legible
    — `landing_merge_verdict` refuses on exactly that."""
    corpus = _tree(tmp_path, {"test_red.py": _RED,
                              "test_green_after.py": _GREEN_AFTER})
    merged = tmp_path / "merged.xml"
    proc = _run_driver(corpus, merged, "--stop-after-failures", "1")
    assert proc.returncode == D.RC_RED, proc.stdout
    notrun = [l for l in proc.stdout.splitlines() if l.startswith("NOTRUN")]
    assert len(notrun) == 1 and "test_green_after.py" in notrun[0], proc.stdout
    assert _files_in(merged) == ["test_red.py"], (
        "a file that was never launched must not appear in the report")


# ── the unit-level rules, asked directly ─────────────────────────────────────

@pytest.mark.parametrize("body,why", [
    ("", "an empty file is not a partial answer"),
    ("<testsuites", "a half-written XML left by a killed process"),
    ("<?xml version='1.0'?><testsuites name='pytest tests' />",
     "a well-formed report with no testsuite in it"),
])
def test_every_unreadable_report_is_no_record_not_an_empty_one(tmp_path, body,
                                                               why):
    p = tmp_path / "r.xml"
    p.write_text(body, encoding="utf-8")
    assert D._load_suites(p) is None, why


def test_a_missing_report_is_no_record(tmp_path):
    assert D._load_suites(tmp_path / "absent.xml") is None


def test_missing_progress_sidecar_is_fail_closed(tmp_path):
    sidecar = tmp_path / "progress.jsonl"
    sidecar.touch(mode=0o600)
    probe = D._SemanticProgressProbe(
        sidecar, "nonce", lambda: os.getpid())
    sidecar.unlink()
    try:
        assert probe.sample() == 0
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert not ok and "unavailable" in reason


def test_corrupt_progress_growth_never_renews_the_lease(tmp_path):
    sidecar = tmp_path / "progress.jsonl"
    sidecar.touch(mode=0o600)
    probe = D._SemanticProgressProbe(
        sidecar, "nonce", lambda: os.getpid())
    try:
        with sidecar.open("ab") as f:
            f.write(b"not-json\n")
        before = probe.sample()
        with sidecar.open("ab") as f:
            f.write(b"still-growing-garbage\n")
        after = probe.sample()
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert before == after == 0
    assert not ok and "malformed" in reason


def test_partial_progress_line_waits_but_is_never_progress(tmp_path):
    sidecar = tmp_path / "progress.jsonl"
    sidecar.write_bytes(b"{")
    probe = D._SemanticProgressProbe(
        sidecar, "nonce", lambda: os.getpid())
    try:
        assert probe.sample() == 0
        assert not probe.error
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert not ok and "truncated final event" in reason


def _trusted_runtime_identity():
    file_row = {"path": "/runtime/file.py", "sha256": "a" * 64,
                "size": 1}
    return {
        "schema": 1,
        "python": {**file_row, "path": "/usr/bin/python3"},
        "entry": {**file_row, "path": "/runtime/trusted_pytest_entry.py"},
        "plugin": {**file_row, "path": "/runtime/_pytest_progress_plugin.py"},
        "modules": [
            {"name": name, **file_row,
             "path": f"/usr/lib/python/site-packages/{name}.py"}
            for name in ("pytest", "_pytest", "pluggy")
        ],
    }


def test_required_runtime_identity_is_bound_to_session_start(tmp_path):
    sidecar = tmp_path / "identity-progress.jsonl"
    nonce = "nonce"
    pid = os.getpid()
    records = [
        ("session_start", {"runtime_identity": _trusted_runtime_identity()}),
        ("collection_finish", {"selected_items": 0}),
        ("session_finish", {"exitstatus": 0}),
    ]
    with sidecar.open("w", encoding="utf-8") as fh:
        for seq, (event, fields) in enumerate(records, start=1):
            fh.write(json.dumps({
                "schema": 1, "nonce": nonce, "pid": pid, "seq": seq,
                "event": event, "monotonic_ns": seq, **fields,
            }) + "\n")
    probe = D._SemanticProgressProbe(
        sidecar, nonce, lambda: pid, require_runtime_identity=True)
    try:
        assert probe.sample() == 3
        ok, reason = probe.complete()
        identity = probe.runtime_identity
    finally:
        probe.close()
    assert ok, reason
    assert identity == _trusted_runtime_identity()


def test_missing_or_ambiguous_required_runtime_identity_never_renews(tmp_path):
    for name, session in (
        ("missing", {}),
        ("extra", {"runtime_identity": {
            **_trusted_runtime_identity(), "candidate_field": True}}),
    ):
        sidecar = tmp_path / f"{name}.jsonl"
        sidecar.write_text(json.dumps({
            "schema": 1, "nonce": "nonce", "pid": os.getpid(),
            "seq": 1, "event": "session_start", "monotonic_ns": 1,
            **session,
        }) + "\n", encoding="utf-8")
        probe = D._SemanticProgressProbe(
            sidecar, "nonce", lambda: os.getpid(),
            require_runtime_identity=True)
        try:
            assert probe.sample() == 0
            ok, reason = probe.complete()
        finally:
            probe.close()
        assert not ok
        assert "runtime identity" in reason


def test_duplicate_key_or_nonfinite_progress_json_is_malformed(tmp_path):
    for name, raw in (
        ("duplicate", b'{"schema":1,"schema":1}\n'),
        ("nonfinite", b'{"schema":NaN}\n'),
    ):
        sidecar = tmp_path / f"{name}.jsonl"
        sidecar.write_bytes(raw)
        probe = D._SemanticProgressProbe(
            sidecar, "nonce", lambda: os.getpid())
        try:
            assert probe.sample() == 0
            ok, reason = probe.complete()
        finally:
            probe.close()
        assert not ok and "malformed" in reason


@pytest.mark.parametrize("bad", [
    {"completed": 1, "total": 3},  # duplicate
    {"completed": 3, "total": 3},  # gap
    {"completed": 2, "total": 4},  # total drift
])
def test_invalid_domain_progress_freezes_the_semantic_score(tmp_path, bad):
    sidecar = tmp_path / "progress.jsonl"
    nonce = "nonce"
    pid = os.getpid()
    records = [
        ("session_start", {}),
        ("item_collected", {"nodeid": "test_batch.py::test_batch"}),
        ("collection_finish", {"selected_items": 1}),
        ("domain_progress", {
            "nodeid": "test_batch.py::test_batch", "scope": "batch",
            "completed": 1, "total": 3}),
        ("domain_progress", {
            "nodeid": "test_batch.py::test_batch", "scope": "batch", **bad}),
        ("domain_progress", {
            "nodeid": "test_batch.py::test_batch", "scope": "batch",
            "completed": 2, "total": 3}),
    ]
    with sidecar.open("w", encoding="utf-8") as fh:
        for seq, (event, fields) in enumerate(records, start=1):
            fh.write(json.dumps({
                "schema": 1, "nonce": nonce, "pid": pid, "seq": seq,
                "event": event, "monotonic_ns": seq, **fields,
            }) + "\n")
    probe = D._SemanticProgressProbe(
        sidecar, nonce, lambda: pid, collect_only=True)
    try:
        score = probe.sample()
        again = probe.sample()
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert score == again == 4
    assert not ok and "domain_progress" in reason


@pytest.mark.parametrize("terminal", [
    {"selected_items": 0},
    {"selected_items": 2},
])
def test_collect_only_terminal_must_preserve_declared_count(tmp_path, terminal):
    sidecar = tmp_path / "collect-progress.jsonl"
    nonce = "nonce"
    pid = os.getpid()
    records = [
        ("session_start", {}),
        ("item_collected", {"nodeid": "test_a.py::test_a"}),
        ("collection_finish", {"selected_items": 1}),
        ("collection_only_finish", terminal),
        ("session_finish", {"exitstatus": 0}),
    ]
    with sidecar.open("w", encoding="utf-8") as fh:
        for seq, (event, fields) in enumerate(records, start=1):
            fh.write(json.dumps({
                "schema": 1, "nonce": nonce, "pid": pid, "seq": seq,
                "event": event, "monotonic_ns": seq, **fields,
            }) + "\n")
    probe = D._SemanticProgressProbe(sidecar, nonce, lambda: pid)
    try:
        assert probe.sample() == 3
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert not ok
    assert "collect-only terminal count/state mismatch" in reason


def test_zero_selection_collect_requires_its_distinct_terminal(tmp_path):
    """A normal zero-test session_finish cannot certify --collect-only."""
    sidecar = tmp_path / "zero-collect-progress.jsonl"
    nonce = "nonce"
    pid = os.getpid()
    records = [
        ("session_start", {}),
        ("collection_finish", {"selected_items": 0}),
        ("session_finish", {"exitstatus": 0}),
    ]
    with sidecar.open("w", encoding="utf-8") as fh:
        for seq, (event, fields) in enumerate(records, start=1):
            fh.write(json.dumps({
                "schema": 1, "nonce": nonce, "pid": pid, "seq": seq,
                "event": event, "monotonic_ns": seq, **fields,
            }) + "\n")
    probe = D._SemanticProgressProbe(
        sidecar, nonce, lambda: pid, collect_only=True)
    try:
        assert probe.sample() == 2
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert not ok
    assert "out-of-order session_finish" in reason


def test_the_merge_omits_files_that_have_no_record(tmp_path):
    """Asked of `merge` directly, because this is the property a well-meaning
    change is most likely to 'improve' by inserting a placeholder suite."""
    suite = ET.fromstring(
        "<testsuite name='pytest' tests='1'>"
        "<testcase classname='c' name='t' file='kept.py'/></testsuite>")
    results = [D.FileResult("kept.py", 0, False, [suite], 1, 0),
               D.FileResult("lost.py", None, True, None, 0, 0)]
    out = tmp_path / "m.xml"
    assert D.merge(results, out) == 2
    root = ET.parse(str(out)).getroot()
    assert [s.get("name") for s in root.iter("testsuite")] == [
        "kept.py", "kept.py::process_exit"]


def test_process_verdict_key_is_stable_and_carries_exact_rc(tmp_path):
    """The stable key permits rc=1 -> 0 to be fixed; the property distinguishes
    rc=1 from SIGKILL (-9) for landing_merge_verdict's exact comparison."""
    def result(rc):
        suite = ET.fromstring(
            "<testsuite name='pytest' tests='1'>"
            "<testcase classname='c' name='t' file='same.py'/>"
            "</testsuite>")
        return D.FileResult("same.py", rc, rc < 0, [suite], 1, 0)

    base = tmp_path / "base.xml"
    candidate = tmp_path / "candidate.xml"
    D.merge([result(1)], base)
    D.merge([result(-9)], candidate)

    def session_state(path):
        cases = [tc for tc in ET.parse(str(path)).iter("testcase")
                 if tc.get("classname") == "pytest_per_file_process"]
        assert len(cases) == 1
        prop = next(p for p in cases[0].iter("property")
                    if p.get("name") == "process_rc")
        return cases[0].get("name"), prop.get("value")

    assert session_state(base) == ("same.py::process_exit", "1")
    assert session_state(candidate) == ("same.py::process_exit", "-9")


# ── the driver is the instrument BOTH arms use ───────────────────────────────

def _repo_root() -> Path:
    return require_repo(".")


def test_both_landing_arms_run_through_this_driver():
    """#1417's law — a differential is only a differential if the two arms were
    measured the same way. Read off the scripts rather than trusted."""
    root = _repo_root()
    land = root / "tools" / "gatekeeper-land.sh"
    verify = root / "tools" / "gatekeeper-verify-merge.sh"
    entry = root / "tools" / "ci" / "hermetic_test_arm_entry.sh"
    if not land.is_file() or not verify.is_file() or not entry.is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    land_src = land.read_text(errors="replace")
    verify_src = verify.read_text(errors="replace")
    entry_src = entry.read_text(errors="replace")
    assert "programs/pytest_per_file_junit.py" in land_src, (
        "the direct push path does not run through the semantic driver")
    assert "--aggregate-check" in land_src.split("run_pytest()")[-1], (
        "the direct push path has no whole-selection semantics canary")
    assert "--aggregate-check --aggregate-only" not in land_src.split(
        "run_pytest()")[-1], (
        "the direct push path suppresses per-file recovery after NORECORD")
    assert land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0].count("--fallback-jobs") == 1, (
        "the push-path aggregate fallback has no bounded process width")
    assert land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0].count("--fallback-rescue-jobs") == 1, (
        "the push path does not declare its exhaustive rescue ceiling")
    assert "-p no:cacheprovider" in land_src.split("run_pytest()")[-1], (
        "arm B loads cacheprovider while A1 explicitly disables it")

    # Verified A1/B1 use one BASE-authorised, read-only overlay as direct PID1.
    # The entry owns the driver argv for both arms; the subject cannot shadow it.
    assert "--overlay tools/ci/hermetic_test_arm_entry.sh" in verify_src
    assert ("--overlay vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
            "test_matrix_63x8_coverage.py") in verify_src
    assert "launch_hermetic_test_arm B1" in verify_src
    assert "launch_hermetic_test_arm A1" in verify_src
    assert "pytest_per_file_junit.py" in entry_src
    assert "--aggregate-check" in entry_src
    assert "--aggregate-only" in entry_src, (
        "the hermetic arm must refuse an incomplete aggregate instead of "
        "launching a second unbound process population")
    # `-I -B`, NOT `-I`. THIS ASSERTION WAS THE STALE HALF: 1e8d01d72 [v1.12.83]
    # deliberately inserted `-B` here and in all three landing lanes, because
    # `-I` implies `-E` and so discards `PYTHONDONTWRITEBYTECODE` -- the tier was
    # writing .pyc into the tree it then attested. The literal below still named
    # the pre-fix shape, so it failed against a script that had been corrected.
    # Re-pinned to the reviewed shape, and it now REQUIRES `-B` rather than
    # tolerating it, so deleting the flag again is a red test.
    assert 'python3 -I -B "$PROGRAMS/trusted_pytest_entry.py"' in entry_src
    assert "--timeout" not in entry_src and "pytest_timeout" not in entry_src
    assert "grep -q 'programs/pytest_per_file_junit.py'" not in verify_src, (
        "source text is not a runtime capability record; a comment containing "
        "the driver path must not select arm A1's instrument")
    assert "xargs -a" not in land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0], (
        "the single-session `xargs` invocation is still in run_pytest")


def test_the_landing_harness_declares_semantic_progress_not_elapsed_time():
    """All landing populations use the driver's no-ceiling contract."""
    import ci_harness_timeout_ceiling_check as C
    root = _repo_root()
    if not (root / "tools" / "gatekeeper-land.sh").is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    contract = C.landing_semantic_progress_contract(root)
    assert contract["declared"] is True, contract
    assert contract["errors"] == [], contract
    assert len(contract["lanes"]) >= 3, contract


def test_the_landing_harness_argv_shape_is_the_one_this_file_pins():
    """`_pytest_cmd` must stay the shipped landing argv, option for option.

    THE DEFECT THIS EXISTS FOR, measured 2026-08-20 at `9cc09b863` (v1.11.5).
    `_pytest_cmd` still carried `-p pytest_timeout --timeout=4
    --timeout-method=thread` and called itself "pinned the way the landing gate
    pins it" — long after `tools/ci/hermetic_test_arm_entry.sh` had dropped the
    idiom. Nothing compared the two, so the drift was invisible until it showed
    up as colour: the same 90 cases gave **30 red in the anchored image and 3 on
    a host**, a 28-test set difference whose entire cause was that the image
    does not carry the plugin and the host happened to.

    A prose claim of "pinned the way the landing gate pins it" is not a pin.
    This is.
    """
    root = _repo_root()
    entry = root / "tools" / "ci" / "hermetic_test_arm_entry.sh"
    if not entry.is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    body = entry.read_text(encoding="utf-8", errors="replace")
    cmd = _pytest_cmd()

    # The retired idiom, in BOTH directions: gone from the shipped entry AND
    # gone from what this file hands its children.
    assert "pytest_timeout" not in body, body
    assert "--timeout" not in body, body
    assert "pytest_timeout" not in cmd, cmd
    assert not any(a.startswith("--timeout") for a in cmd), cmd

    # The options the entry DOES declare must be the ones this file uses, or
    # these tests are measuring a harness nobody runs.
    assert "-p no:cacheprovider" in body, body
    assert cmd[cmd.index("-p") + 1] == "no:cacheprovider", cmd
    assert "-q" in body and "-q" in cmd, (body, cmd)


def test_this_file_declares_no_whole_run_wall_clock_bound():
    """The SUCCESSOR of `assert _T <= ceiling`, and a stronger claim.

    `_T = 50` was this file's "final safety net": a wall clock on every driver
    launch, kept under the harness ceiling so it could actually fire. Both
    halves of that were wrong for this file in particular. The subject here is a
    driver whose own contract is SEMANTIC PROGRESS (`--stall-after`), so
    bounding it by elapsed time asserted the opposite of the thing under test;
    and 50 s was justified by "measured at well under 20 s on this host", which
    is a reading of one machine, not a property of the driver. When a busier
    machine crossed it, the `TimeoutExpired` did not say "this box was loaded",
    it failed the test as though `pytest_per_file_junit.py` were broken.

    There is no number left to compare against a ceiling, so the assertion
    becomes the absence of one — checked STRUCTURALLY over this file's own AST
    rather than by looking for a constant, so it stays true of whatever this
    file grows into and fails on a bound reintroduced under any name.

    ONE bound is exempt and named: `_SINGLE_SESSION_KILL`, which is the SUBJECT
    of `test_one_session_loses_the_whole_record_and_per_file_does_not` — that
    arm exists to prove a session killed mid-run writes no junit at all, and a
    test whose subject is a kill needs a kill.

    `_STALL` is not compared either, for the reason the retired test already
    gave: it measures absence of progress, not healthy runtime.
    """
    import ast as _ast
    src = Path(__file__).read_text(encoding="utf-8")
    blocking = {"run", "Popen", "call", "check_output", "check_call",
                "communicate", "wait"}
    offenders = []
    for node in _ast.walk(_ast.parse(src)):
        if not isinstance(node, _ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name not in blocking:
            continue
        for kw in node.keywords:
            if kw.arg != "timeout":
                continue
            if _ast.unparse(kw.value) == "_SINGLE_SESSION_KILL":
                continue
            offenders.append((node.lineno, _ast.unparse(kw.value)))
    assert not offenders, (
        "a wall-clock bound is back on a blocking call in this file; every "
        "launch here is supervised by forward progress instead — "
        f"{offenders}")


# ── the selection and the report must be read in ONE frame (jnorec, C) ───────
#
# MEASURED at 49d2b3328, the landing gate's `full:unselectable-tests` lane:
# `rc=0`, 852 cases, `784 passed, 60 skipped, 5 xfailed, 3 xpassed`, ZERO
# failures — and REFUSED, `missing=111` of 111 selected with `extra=110`. The
# corpus program emits repo-root-relative paths and the lane runs with cwd at
# the repository root, while every one of those files lives under the plugin
# subtree, which carries its own `pytest.ini` — so pytest's rootdir was the
# plugin and every `file` attribute came back plugin-relative. The comparison
# matched nothing in either direction, which means that lane's aggregate arm had
# never measured anything and nobody could tell: UNKNOWN and broken read alike.
#
# Both directions are pinned below. The first fails on the pre-fix driver
# (a fully green split-frame session is refused); the second fails on it too,
# for the opposite reason — it names ONE genuinely absent file, and the pre-fix
# driver names all of them, so a fix that merely stopped comparing would pass
# the first test and fail this one.

_PLAIN_GREEN = "def test_it_is_green():\n    assert True\n"

#: A module pytest imports and collects ZERO items from. This is the shape the
#: coverage check exists for and it must stay refused.
_COLLECTS_NOTHING = "VALUE = 1\n"


def _plain_pytest_cmd():
    """The harness command WITHOUT `-p pytest_timeout`.

    MEASURED in the pinned landing image: `import pytest_timeout` raises
    `ModuleNotFoundError`, and `-p <missing plugin>` dies in pytest's pre-parse
    before collection. A coverage test built on that command would exercise the
    pre-parse failure and prove nothing about coverage.
    """
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def _split_frame_tree(tmp_path: Path, files: dict) -> Path:
    """A tree whose selection frame and pytest's rootdir deliberately differ.

    The test files sit in a subdirectory carrying its OWN `pytest.ini`, so
    pytest infers rootdir there, while the selection is written relative to the
    OUTER directory the driver runs in. That is exactly the landing gate's
    unselectable lane: repo root cwd, plugin-subtree files, plugin `pytest.ini`.
    """
    root = tmp_path / "outer"
    inner = root / "inner"
    inner.mkdir(parents=True, exist_ok=True)
    (inner / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for name, body in files.items():
        (inner / name).write_text(body, encoding="utf-8")
    (root / "selection.txt").write_text(
        "".join(f"inner/{n}\n" for n in files), encoding="utf-8")
    return root


def _run_driver_in(root: Path, junit: Path, *extra, pytest_extra=()):
    return _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(root / "selection.txt"),
         "--junit", str(junit),
         "--stall-after", str(_STALL), *extra,
         "--"] + _plain_pytest_cmd() + list(pytest_extra),
        cwd=str(root))


def test_a_green_session_read_in_another_frame_is_not_refused(tmp_path):
    """POSITIVE CONTROL: nothing is wrong, so nothing may be reported wrong."""
    root = _split_frame_tree(tmp_path, {"test_alpha.py": _PLAIN_GREEN,
                                        "test_beta.py": _PLAIN_GREEN})
    proc = _run_driver_in(root, tmp_path / "merged.xml", "--aggregate-only")
    assert "AGGREGATE_COMPLETE" in proc.stdout, proc.stdout
    assert "AGGREGATE_NORECORD" not in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_OK, proc.stdout


def test_a_file_that_collects_nothing_is_still_named_missing(tmp_path):
    """NEGATIVE CONTROL, and the whole value of the change.

    One selected file contributes no testcase. That is the shape
    `_aggregate_coverage_problem` exists to catch, and declaring the frame must
    not blunt it: the refusal must name THAT file and only that file.
    """
    root = _split_frame_tree(tmp_path, {"test_alpha.py": _PLAIN_GREEN,
                                        "test_silent.py": _COLLECTS_NOTHING})
    proc = _run_driver_in(root, tmp_path / "merged.xml", "--aggregate-only")
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert "AGGREGATE_NORECORD" in proc.stdout, proc.stdout
    assert "missing=['inner/test_silent.py'], extra=[]" in proc.stdout, (
        "the refusal must name exactly the file that produced no testcase; "
        "naming every file (or none) means the frames still disagree\n"
        + proc.stdout)


def test_a_caller_that_declared_a_rootdir_keeps_it():
    """The frame is ADDED, never overridden — a caller may own it."""
    assert D._declared_rootdir(["-q", "--rootdir=/elsewhere"], "/anchor") == []
    assert D._declared_rootdir(["-q", "--rootdir", "/elsewhere"], "/anchor") == []
    assert D._declared_rootdir(["-q"], "/anchor") == ["--rootdir=/anchor"]


# ── declaring the frame must not STRAND the config file ──────────────────────
#
# `--rootdir` moves the frame, and it also stops pytest looking for an ini:
# that search happens only while rootdir is being INFERRED. Every `addopts` in
# the stranded ini then silently stops applying.
#
# MEASURED at 7074db3f5 on the landing gate's `full:unselectable-tests` lane,
# 133 files, one pytest process, cwd at the repository root:
#
#     --rootdir=<repo root>                          rc=2   75 collection errors
#     --rootdir=<repo root> -c <plugin>/pytest.ini   rc=0   1221 passed
#
# The 75 are ONE defect. `plugins/vibe-ic/pytest.ini` carries
# `addopts = --import-mode=importlib`; stranded, the session falls back to
# pytest's default `prepend` mode, which names a test module by its BASENAME
# when its directory has no `__init__.py`. The corpus holds 70 files named
# `test_compliance.py` and 7 named `test_verdict_boundary.py`; the first of each
# binds the bare name and every later one raises `ImportPathMismatchError`.
# 69 + 6 = 75. The same 133 files one-per-session were 133/133 GREEN, which is
# what makes this the aggregation and not the code.


def _config_probe_tree() -> Path:
    """A tree whose COMMON ancestor carries no config but whose arguments do.

    `mkdtemp` rather than `tmp_path`: the pinned image's `tmp_path` carries a
    newline, and these paths are handed to a subprocess command line.
    """
    root = Path(tempfile.mkdtemp(prefix="cfgprobe"))
    (root / "outside").mkdir()
    (root / "outside" / "test_outside.py").write_text("def test_outside():\n    pass\n")
    pkg = root / "pkg"
    (pkg / "a" / "tests").mkdir(parents=True)
    (pkg / "b" / "tests").mkdir(parents=True)
    (pkg / "pytest.ini").write_text("[pytest]\naddopts = --import-mode=importlib\n")
    # SAME BASENAME, and neither directory carries an `__init__.py` — the exact
    # shape the unselectable corpus has 70 of.
    (pkg / "a" / "tests" / "test_same.py").write_text("def test_a():\n    pass\n")
    (pkg / "b" / "tests" / "test_same.py").write_text("def test_b():\n    pass\n")
    return root


def _probe_args(root: Path) -> list:
    return ["outside/test_outside.py", "pkg/a/tests/test_same.py",
            "pkg/b/tests/test_same.py"]


def _run_pytest_in(root: Path, extra: list) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--rootdir={root}", *extra, *_probe_args(root)],
        cwd=str(root), env=env, capture_output=True, text=True)


def test_the_stranded_config_is_what_aborts_collection():
    """BOTH DIRECTIONS ON THE SAME BYTES. Identical files and identical
    arguments: without the ini the session cannot even be collected, with it
    restored every file collects and passes."""
    root = _config_probe_tree()
    without = _run_pytest_in(root, [])
    assert without.returncode == 2, (
        "a stranded ini must abort COLLECTION (rc 2 = the question could not "
        "be put), not merely change a result\n" + without.stdout)
    assert "import file mismatch" in without.stdout, without.stdout

    with_ini = _run_pytest_in(root, ["-c", str(root / "pkg" / "pytest.ini")])
    assert with_ini.returncode == 0, with_ini.stdout


def test_the_config_is_found_by_walking_each_argument_not_their_ancestor():
    """The regression this pins: a COMMON-ANCESTOR search restores nothing.

    `outside/` and `pkg/` share only the root, which carries no config, so an
    implementation that intersects the arguments finds nothing and silently
    leaves the session in `prepend` mode. pytest walks each argument in turn
    (`_pytest.config.locate_config`), and so must this."""
    root = _config_probe_tree()
    assert D._declared_configfile([], str(root), _probe_args(root)) == [
        "-c", str(root / "pkg" / "pytest.ini")]


def test_a_corpus_with_no_config_anywhere_is_left_exactly_as_it_was():
    """THE CONTROL THAT MUST NOT MOVE. The repository-root `tools/` corpus
    reaches no ini, so its command stays byte-for-byte the one it has always
    issued; this fix must be inert there."""
    root = Path(tempfile.mkdtemp(prefix="cfgnone"))
    (root / "tools").mkdir()
    (root / "tools" / "test_x.py").write_text("def test_x():\n    pass\n")
    assert D._declared_configfile([], str(root), ["tools/test_x.py"]) == []


def test_a_caller_that_declared_a_config_keeps_it():
    """Added, never overridden — the same contract `--rootdir` already has."""
    root = _config_probe_tree()
    args = _probe_args(root)
    assert D._declared_configfile(["-c", "/mine.ini"], str(root), args) == []
    assert D._declared_configfile(["-c=/mine.ini"], str(root), args) == []
    assert D._declared_configfile(["--config-file", "/mine.ini"], str(root), args) == []
    assert D._declared_configfile(["--config-file=/mine.ini"], str(root), args) == []


def test_the_restored_session_can_still_report_a_real_red_by_name():
    """An aggregation that stopped aborting but also stopped DISCRIMINATING is
    the same defect wearing a green hat. One genuinely failing file must come
    back as ONE named red, not as every file in the corpus."""
    root = _config_probe_tree()
    (root / "pkg" / "b" / "tests" / "test_same.py").write_text(
        "def test_b():\n    assert False, 'planted'\n")
    proc = _run_pytest_in(root, ["-c", str(root / "pkg" / "pytest.ini")])
    assert proc.returncode == 1, (
        "rc 1 is 'tests failed'; rc 2 would mean the question could not be "
        "put and rc 0 that it was never asked\n" + proc.stdout)
    assert "1 failed" in proc.stdout and "2 passed" in proc.stdout, proc.stdout


# ── a --maxfail prefix is a NAMED truncation, still refused (jnorec, B1) ──────
#
# MEASURED at 288dc9fc8, the landing gate's `full:targeted-tests` lane over a
# 116-file selection, byte-identical in five rounds:
#
#     AGGREGATE_NORECORD  aggregate JUnit does not exactly cover the selected
#                         files (missing=[108 paths]) — cross-file/order
#                         semantics are UNKNOWN, not clean
#
# The truth was `10 failed, 178 passed`, `188/2565` items, `rc=1`, a valid
# JUnit: pytest stopped inside selected file 8 of 116 because `--maxfail=10`
# told it to. One reading sends the reader to the harness; the other sends them
# to ten named tests. Nobody chased it for five rounds, which is what an
# unknowable-looking refusal costs.
#
# The verdict does NOT move — a prefix of a failure set cannot be differenced
# against another arm, so the landing is still refused. Only the diagnosis moves.

_TWO_RED = ("def test_red_one():\n    assert False\n"
            "def test_red_two():\n    assert False\n"
            "def test_green_never_reached():\n    assert True\n")


def test_a_maxfail_prefix_is_named_and_still_refused(tmp_path):
    """POSITIVE CONTROL: the cause is knowable, so it must be named."""
    corpus = _tree(tmp_path, {"test_aa_red.py": _TWO_RED,
                              "test_bb_never_ran.py": _PLAIN_GREEN})
    proc = _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(tmp_path / "merged.xml"),
         "--stall-after", str(_STALL), "--aggregate-only",
         "--"] + _plain_pytest_cmd() + ["--maxfail=2"],
        cwd=str(corpus))
    assert "AGGREGATE_TRUNCATED  2 failures reached at file 1/2," in proc.stdout, (
        proc.stdout)
    assert "test_aa_red.py::test_red_one" in proc.stdout.replace(
        "test_aa_red::", "test_aa_red.py::"), proc.stdout
    # THE REFUSAL IS UNCHANGED. Every consumer keys off this marker.
    assert "AGGREGATE_NORECORD" in proc.stdout, proc.stdout
    assert "never launched: ['test_bb_never_ran.py']" in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_NORECORD, proc.stdout


def test_a_real_stall_is_not_reclassified_as_a_truncation(tmp_path):
    """NEGATIVE CONTROL 1: a genuine hang must stay an unexplained NORECORD.

    The bound is declared and the session is incomplete, exactly as in the
    positive case. The one thing that differs is that the supervisor's stall
    lease fired instead of the process exiting on its own, and that alone must
    keep the truncation label off.
    """
    corpus = _tree(tmp_path, {"test_hangs.py": _HANGS_IN_TEST})
    proc = _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(tmp_path / "merged.xml"),
         "--stall-after", str(_STALL), "--aggregate-only",
         "--aggregate-stall-after", str(_STALL),
         "--"] + _plain_pytest_cmd() + ["--maxfail=2"],
        cwd=str(corpus))
    assert "AGGREGATE_TRUNCATED" not in proc.stdout, proc.stdout
    # The REASON must still be the stall, not a bound. A diagnosis that renames
    # a hang after the failure bound is the permissive direction: it would send
    # the reader to ten tests when the harness is what stopped.
    assert "AGGREGATE_NORECORD  STALLED after" in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_NORECORD, proc.stdout


def test_a_zero_collecting_file_is_not_reclassified_as_a_truncation(tmp_path):
    """NEGATIVE CONTROL 2: not-covered must stay not-covered.

    A declared bound plus an incomplete report is not enough to blame the bound:
    here nothing failed at all, so the refusal must remain the coverage one and
    must still name the file that produced no testcase.
    """
    corpus = _tree(tmp_path, {"test_green.py": _PLAIN_GREEN,
                              "test_silent.py": _COLLECTS_NOTHING})
    proc = _supervised(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(tmp_path / "merged.xml"),
         "--stall-after", str(_STALL), "--aggregate-only",
         "--"] + _plain_pytest_cmd() + ["--maxfail=2"],
        cwd=str(corpus))
    assert "AGGREGATE_TRUNCATED" not in proc.stdout, proc.stdout
    assert "missing=['test_silent.py'], extra=[]" in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_NORECORD, proc.stdout


# ── a PER-FILE --maxfail prefix is the SAME named truncation ─────────────────
#
# MEASURED on the 2026-08-31 full tier at 47968f0ee2: two per-file fallback
# sessions stopped at the lane's flat `--maxfail=10` and were reported as
#
#     NORECORD  <file>  pytest progress protocol incomplete: m.<pid>.<n>.jsonl:
#               session finished before every selected item completed (102/138)
#
# and the parsed JUnit prefix — the only copy of the red case names, inside a
# `--rm` container — was nulled with the classification. A file carrying
# >= bound reds could therefore NEVER produce a per-file record: exactly the
# files most in need of naming were the ones this arm refused to name. The
# aggregate arm has named the identical event since `_maxfail_truncation`;
# these pin the per-file arm — direct and fallback-worker — to the same rule.
# The verdict does not move: the file stays NORECORD-refused and unmerged.

_ELEVEN_RED = "\n".join(
    f"def test_{i:02d}():\n    assert False" for i in range(11)) + "\n"


def test_a_per_file_maxfail_prefix_is_named_and_still_refused(tmp_path):
    """POSITIVE CONTROL, direct per-file arm: the cause must be named."""
    corpus = _tree(tmp_path, {"test_many.py": _ELEVEN_RED})
    merged = tmp_path / "merged.xml"
    proc = _run_driver_in(corpus, merged, pytest_extra=("--maxfail=10",))
    assert "FILE_TRUNCATED  test_many.py  10 failures reached" in proc.stdout, (
        proc.stdout)
    assert "TRUNCATED_RED  test_many::test_00" in proc.stdout, proc.stdout
    assert "TRUNCATED_RED  test_many::test_09" in proc.stdout, proc.stdout
    # The 11th case never ran; a name for it would be an invention.
    assert "test_10" not in proc.stdout, proc.stdout
    assert ("NORECORD  test_many.py  session stopped at its own declared "
            "failure bound") in proc.stdout, proc.stdout
    # The misdiagnosis this pins against: the lifecycle join's completeness
    # clause is TRUE but it is the symptom, not the cause.
    assert "protocol incomplete" not in proc.stdout, proc.stdout
    # THE REFUSAL IS UNCHANGED: still no record, still not merged.
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert _files_in(merged) == []


def test_a_fallback_worker_maxfail_prefix_is_named_and_still_refused(tmp_path):
    """POSITIVE CONTROL, fallback-worker arm — the arm the full tier ran."""
    corpus = _tree(tmp_path, {"test_many.py": _ELEVEN_RED})
    merged = tmp_path / "merged.xml"
    proc = _run_driver_in(
        corpus, merged, "--aggregate-check",
        "--aggregate-stall-after", str(_STALL),
        pytest_extra=("--maxfail=10",))
    assert "FILE_TRUNCATED  test_many.py  10 failures reached" in proc.stdout, (
        proc.stdout)
    assert "TRUNCATED_RED  test_many::test_00" in proc.stdout, proc.stdout
    assert ("NORECORD  test_many.py  session stopped at its own declared "
            "failure bound") in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_NORECORD, proc.stdout
    assert _files_in(merged) == []


def test_a_per_file_stall_is_not_reclassified_as_a_truncation(tmp_path):
    """NEGATIVE CONTROL: a genuine per-file hang stays an unexplained NORECORD.

    The bound is declared, exactly as in the positive case; the one thing that
    differs is that the supervisor's stall lease fired instead of the process
    exiting on its own, and that alone must keep the truncation label off.
    """
    corpus = _tree(tmp_path, {"test_hangs.py": _HANGS_IN_TEST})
    merged = tmp_path / "merged.xml"
    proc = _run_driver_in(corpus, merged, pytest_extra=("--maxfail=10",))
    assert "FILE_TRUNCATED" not in proc.stdout, proc.stdout
    assert "TRUNCATED_RED" not in proc.stdout, proc.stdout
    assert "NORECORD  test_hangs.py  STALLED after" in proc.stdout, proc.stdout
    assert proc.returncode == D.RC_NORECORD, proc.stdout


def test_the_bound_is_read_from_this_drivers_own_argv():
    """Never from the child's output: a test may print `--maxfail` too."""
    assert D._declared_failure_bound(["-q"]) is None
    assert D._declared_failure_bound(["-q", "--maxfail=10"]) == 10
    assert D._declared_failure_bound(["-q", "--maxfail", "4"]) == 4
    assert D._declared_failure_bound(["-q", "-x"]) == 1
    assert D._declared_failure_bound(["-qx"]) == 1
    assert D._declared_failure_bound(["--exitfirst", "--maxfail=9"]) == 1
    assert D._declared_failure_bound(["-q", "--maxfail=0"]) is None
    assert D._declared_failure_bound(["-p", "no:cacheprovider"]) is None


def test_an_unknown_session_shape_is_never_called_a_truncation():
    """Every clause is required, and a missing sink key is UNKNOWN."""
    full = {"natural_exit": True, "leaked": False, "cleanup_ok": True,
            "protocol_complete": False, "items_finished": 5,
            "items_declared": 9}
    assert D._maxfail_truncation(2, 1, 2, full, 1, 3, []) is not None
    assert D._maxfail_truncation(None, 1, 2, full, 1, 3, []) is None
    assert D._maxfail_truncation(2, 0, 2, full, 1, 3, []) is None
    assert D._maxfail_truncation(2, 1, 1, full, 1, 3, []) is None
    assert D._maxfail_truncation(2, 1, 2, full, 1, 3, ["x.py"]) is None
    assert D._maxfail_truncation(2, 1, 2, {}, 1, 3, []) is None
    for key, bad in (("natural_exit", False), ("leaked", True),
                     ("cleanup_ok", False), ("protocol_complete", True),
                     ("items_finished", None), ("items_declared", None),
                     ("items_finished", 9)):
        broken = dict(full, **{key: bad})
        assert D._maxfail_truncation(2, 1, 2, broken, 1, 3, []) is None, key


def test_a_nested_drivers_complaint_is_not_this_sessions_reason():
    """The detail must come from THIS session's probe, not from the buffer.

    MEASURED with only the `stalled` half repaired: this file's per-file arm
    reported "no pytest progress stream was produced" for a session whose own
    probe had just said "session finished before every selected item completed
    (29/83)". The first `PROGRESS_PROTOCOL_INCOMPLETE:` in the buffer belonged to
    a NESTED driver run that this file spawns as its subject.
    """
    out = ("PROGRESS_PROTOCOL_INCOMPLETE: no pytest progress stream was produced\n"
           "PROGRESS_PROTOCOL_INCOMPLETE: m.139.138.jsonl: session finished before "
           "every selected item completed (29/83)\n")
    reason = D._norecord_reason(
        1, out, True, 300, stalled=False,
        protocol_error="m.139.138.jsonl: session finished before every selected "
                       "item completed (29/83)")
    assert reason.endswith("completed (29/83)"), reason
    assert "no pytest progress stream" not in reason


def test_a_probe_that_made_no_complaint_yields_no_protocol_reason():
    """Fail closed: an unsupplied detail must not be invented from the buffer."""
    out = "PROGRESS_PROTOCOL_INCOMPLETE: something the child printed\n"
    reason = D._norecord_reason(1, out, True, 300, stalled=False,
                                protocol_error="")
    assert "protocol incomplete" not in reason
    assert reason == "pytest supervision ended without a complete liveness record"


def test_the_sink_reader_refuses_a_complete_join():
    assert D._sink_protocol_error({}) == ""
    assert D._sink_protocol_error({"protocol_complete": True,
                                   "protocol_error": "x"}) == ""
    assert D._sink_protocol_error({"protocol_complete": False,
                                   "protocol_error": "x"}) == "x"
    assert D._sink_protocol_error({"protocol_complete": False,
                                   "protocol_error": None}) == ""
