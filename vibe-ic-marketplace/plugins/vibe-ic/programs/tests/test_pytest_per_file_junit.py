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

`_T` is only the test suite's final safety net. The production driver uses
forward-progress supervision and has no whole-run wall-clock estimate.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from _hostpaths import require_repo

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import pytest_per_file_junit as D                              # noqa: E402

_PROG = _PROGRAMS / "pytest_per_file_junit.py"
_FALLBACK_ENV = "VIBEIC_PYTEST_FALLBACK_WORKER"

#: Inner bound for every subprocess this file launches. Each one runs at most
#: three trivial pytest sessions plus one deliberately-killed one, measured at
#: well under 20 s on this host, so 50 s is generous and inside the 60 s ceiling
#: the harness gate publishes for a 180 s lane.
_T = 50

#: Test-only no-progress window. It is not a cap on healthy runtime.
_STALL = 1

#: pytest-timeout's per-test bound inside these tests. Must be BELOW `_KILL` for
#: the "pytest-timeout fires first" fixture and ABOVE it for the import-hang
#: fixture, which is the whole distinction the two shapes exist to draw.
_INNER_TIMEOUT = 4

_GREEN = "def test_i_am_green():\n    assert 1 == 1\n"

_GREEN_AFTER = "def test_i_am_also_green():\n    assert 2 == 2\n"

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
    """The harness command, pinned the way the landing gate pins it."""
    return [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
            f"--timeout={_INNER_TIMEOUT}", "--timeout-method=thread",
            "-p", "no:cacheprovider"]


def _run_driver(corpus: Path, junit: Path, *extra, pytest_extra=()):
    return subprocess.run(
        [sys.executable, str(_PROG),
         "--selection", str(corpus / "selection.txt"),
         "--junit", str(junit),
         "--stall-after", str(_STALL), *extra,
        "--"] + _pytest_cmd() + list(pytest_extra),
        cwd=str(corpus), capture_output=True, text=True, timeout=_T)


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
    single = tmp_path / "single.xml"
    subprocess.run(
        _pytest_cmd() + ["-o", "junit_family=xunit1", f"--junitxml={single}",
                         "test_green_neighbour.py", "test_hangs_like_replay.py",
                         "test_green_after.py"],
        cwd=str(corpus), capture_output=True, text=True, timeout=_T)
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
        0, "PROGRESS_PROTOCOL_INCOMPLETE: collection mismatch\n", True, 3)
    assert reason == "pytest progress protocol incomplete: collection mismatch"
    assert "STALLED" not in reason


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
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not pid_file.is_file():
        time.sleep(0.05)
    assert pid_file.is_file(), "fixture never launched its detached child"
    escaped_pid = int(pid_file.read_text())

    os.kill(driver.pid, signal.SIGTERM)
    driver.wait(timeout=15)

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
    # The 2 s watchdog poll makes one 1 s stall a few seconds on this host. The
    # aggregate plus TWO parallel fallback waves stays far below nine serial
    # stalls. Keep this observed-value assertion before structural markers so a
    # serial implementation is behaviourally rejected.
    assert elapsed < 18, (
        f"parallel recovery took {elapsed:.2f}s; output:\n{proc.stdout}")
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
    deadline = time.monotonic() + 12
    try:
        while time.monotonic() < deadline and not pid_file.is_file():
            time.sleep(0.05)
        assert pid_file.is_file(), "parallel fallback never launched its escapee"
        escaped_pid = int(pid_file.read_text())

        os.kill(driver.pid, signal.SIGTERM)
        driver.wait(timeout=15)

        with pytest.raises(ProcessLookupError):
            os.kill(escaped_pid, 0)
        time.sleep(2.1)
        assert not late_file.exists()
    finally:
        if driver.poll() is None:
            os.killpg(driver.pid, signal.SIGKILL)
            driver.wait(timeout=5)


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
    probe = D._SemanticProgressProbe(sidecar, nonce, lambda: pid)
    try:
        score = probe.sample()
        again = probe.sample()
        ok, reason = probe.complete()
    finally:
        probe.close()
    assert score == again == 4
    assert not ok and "domain_progress" in reason


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
    if not land.is_file() or not verify.is_file():
        pytest.skip("the landing scripts are not shipped in this tree")
    land_src = land.read_text(errors="replace")
    verify_src = verify.read_text(errors="replace")
    assert "programs/pytest_per_file_junit.py" in land_src, (
        "arm B does not run through the per-file driver, so one hanging file "
        "still costs the candidate's whole record")
    assert "programs/pytest_per_file_junit.py" in verify_src, (
        "arm A1 does not run through the per-file driver; an unmeasurable base "
        "arm is the permissive direction — see vibe-ic#1443")
    assert "--aggregate-check" in land_src.split("run_pytest()")[-1], (
        "arm B isolates every file without the whole-selection semantics canary")
    assert "--aggregate-check" in verify_src, (
        "arm A1 and arm B do not share the aggregate semantics canary")
    assert "--aggregate-check --aggregate-only" not in land_src.split(
        "run_pytest()")[-1], (
        "arm B suppresses per-file recovery after aggregate NORECORD")
    assert "--aggregate-check --aggregate-only" not in verify_src, (
        "arm A1/B1 suppress per-file recovery after aggregate NORECORD")
    assert land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0].count("--fallback-jobs") == 1, (
        "the push-path aggregate fallback has no bounded process width")
    assert verify_src.count("--fallback-jobs") == 2, (
        "arm A1 and arm B1 do not both declare the bounded fallback width")
    assert land_src.split("run_pytest()")[-1].split(
        "run_repo_tools_pytest")[0].count("--fallback-rescue-jobs") == 1, (
        "the push path does not declare its exhaustive rescue ceiling")
    assert verify_src.count("--fallback-rescue-jobs") == 2, (
        "arm A1 and arm B1 do not both declare the exhaustive rescue ceiling")
    assert "contract=aggregate-first-exhaustive-process-rescue" in verify_src, (
        "the base-test cache key does not name the process-isolated contract")
    assert "fallback_jobs=" in verify_src, (
        "the base-test cache fingerprint omits the fallback pool width")
    assert "fallback_rescue_jobs=" in verify_src, (
        "the base-test cache fingerprint omits the rescue pool width")
    assert "-p no:cacheprovider" in land_src.split("run_pytest()")[-1], (
        "arm B loads cacheprovider while A1 explicitly disables it")
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


def test_this_files_final_test_safety_bound_is_inside_the_ceiling():
    import ci_harness_timeout_ceiling_check as C
    root = C.find_repo_root()
    if root is None:
        pytest.skip("no repo root in reach")
    ceiling = C.inner_timeout_ceiling(root)
    if ceiling is None:
        pytest.skip("no harness bound in reach")
    assert _T <= ceiling, (_T, ceiling)
    # `_STALL` is deliberately not compared: it measures absence of progress,
    # not healthy runtime, and therefore is not a wall-clock harness bound.
