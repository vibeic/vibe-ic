"""The four causes that left eight files with NO verdict, each pinned both ways.

MEASURED TWICE BY THE OWNER before any of this was written: a 3191-file census
left 8 files with no result, and re-running those 8 alone under LOW LOAD (5 and
7 at a time) reproduced all 8 identically. Load was never the cause; four
distinct driver-side causes were.

    rc=5, no complete junit           test_arith_declaration_emit_equals_separator
                                      test_atpg_exit_code_not_signal
    unfinished live descendants       test_full_suite_run_check
                                      test_issue1283_probe_timeout_is_not_absence
    progress protocol: empty/over-    test_gds_substance_check
      sized event
    STALLED after 300 s               test_flow_matrix_coverage
                                      test_issue1129_gatekeeper_prepare_landing
                                      test_flow_matrix_census_freshness

"UNKNOWN" IS THE STATE THIS FILE EXISTS TO REMOVE, and the way to remove it is
never to widen a bound until the complaint stops. Every arm below therefore has
the direction that must STILL refuse next to the direction that must now
answer; the fourth class has ONLY the refusing direction, because nothing about
the stall detector was changed and the proof of that is that it still fires.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import _pytest_progress_plugin as PP                           # noqa: E402
import _watchdog                                               # noqa: E402
import pytest_per_file_junit as D                              # noqa: E402

_PROG = _PROGRAMS / "pytest_per_file_junit.py"
_TESTS = Path(__file__).resolve().parent


def _tree(tmp_path: Path, files: dict) -> Path:
    d = tmp_path / "corpus"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    (d / "selection.txt").write_text(
        "".join(f"{n}\n" for n in files), encoding="utf-8")
    return d


def _drive(corpus: Path, junit: Path, *extra):
    """The driver, run the way the landing lane runs it: one file per process.

    Supervised by FORWARD PROGRESS rather than a wall clock, so a loaded host
    (load average 22 was measured on this host while these causes were being
    diagnosed) finishes late instead of reporting a hang that is not there.
    """
    cmd = [sys.executable, str(_PROG),
           "--selection", str(corpus / "selection.txt"),
           "--junit", str(junit),
           "--stall-after", "20", *extra,
           "--", sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return _watchdog.completed_process(
        cmd, _watchdog.run_host_supervised(cmd, cwd=str(corpus)))


# ===========================================================================
# CAUSE 1 — rc=5 was nulled with the abnormal exits
# ===========================================================================
_NO_TESTS = (
    '"""A CLI parameterised by a path, named test_*.py. Collects nothing."""\n'
    "def main():\n"
    "    return 0\n"
)
_BROKEN_IMPORT = "import a_module_that_is_not_installed_anywhere\n"


def test_a_clean_zero_collect_session_gets_a_verdict(tmp_path):
    """THE FIX. rc=5 is `EXIT_NO_TESTS_COLLECTED` — a session that ran end to
    end and determinately contained nothing. It is a KNOWN zero, so the file is
    recorded and named `EMPTY`, never left UNKNOWN."""
    corpus = _tree(tmp_path, {"test_collects_nothing.py": _NO_TESTS})
    p = _drive(corpus, tmp_path / "j.xml")
    out = p.stdout + p.stderr
    assert "NORECORD" not in out.replace("  NORECORD   0", ""), out[-3000:]
    assert "EMPTY     test_collects_nothing.py" in out, out[-3000:]
    assert "  NORECORD   0" in out, out[-3000:]
    assert p.returncode == D.RC_OK, out[-3000:]


def test_a_session_that_could_not_collect_is_still_UNKNOWN(tmp_path):
    """THE NEGATIVE CONTROL, and the reason the arm above is not a licence.

    A file whose import fails collects zero tests too — and it must NOT come
    out `EMPTY`. pytest reports a collection ERROR, which is not rc 5, so the
    admission rule never sees it. If this ever passes as EMPTY, the widening
    has become 'call every failure to collect an empty file'.
    """
    corpus = _tree(tmp_path, {"test_cannot_import.py": _BROKEN_IMPORT})
    p = _drive(corpus, tmp_path / "j.xml")
    out = p.stdout + p.stderr
    assert "EMPTY     test_cannot_import.py" not in out, out[-3000:]
    assert p.returncode != D.RC_OK, (
        "a file that could not even be imported was accepted as a clean "
        "measurement\n" + out[-3000:])


def test_zero_collect_is_read_from_three_facts_not_from_the_rc_alone():
    """`_zero_collect`'s own can-say-no. rc 5 with cases or reds in the report
    is a CONTRADICTION, and a contradiction is not a verdict."""
    assert D._zero_collect(5, 0, 0) is True
    assert D._zero_collect(5, 3, 0) is False, "cases and rc 5 disagree"
    assert D._zero_collect(5, 3, 1) is False
    assert D._zero_collect(0, 0, 0) is False, "rc 0 is an ordinary green"
    assert D._zero_collect(1, 0, 0) is False
    assert D._zero_collect(2, 0, 0) is False
    assert D._zero_collect(None, 0, 0) is False


# ===========================================================================
# CAUSE 2 — the supervisor reached the head of the tree and no further
# ===========================================================================
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return state.rsplit(")", 1)[-1].split()[0] != "Z"


def _wait_gone(pid: int, looks: int = 100) -> bool:
    for _ in range(looks):
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _grandchild_of(script: Path, pidf: Path):
    """A script whose GRANDCHILD is the thing that must die, and which names it.

    `$!` AND NOT `$$`. `$$` is the SHELL's own pid — the direct child, which
    every kill reaches, including the pre-fix one. Recording it made both arms
    below assert something trivially true: measured, the negative control
    "failed" because the pid it watched was the shell it had just killed, while
    the real orphan (`sleep 600`, reparented to init) was a DIFFERENT pid that
    nothing was looking at. The backgrounded `sleep` is the process the whole
    class is about, so it is the process whose pid is written down.
    """
    script.write_text(
        f"#!/bin/sh\nsleep 600 &\necho $! > {pidf}\nwait\n",
        encoding="utf-8")
    script.chmod(0o755)


def _read_pid(pidf: Path, proc) -> int:
    for _ in range(300):
        if pidf.is_file():
            txt = pidf.read_text().strip()
            if txt.isdigit():
                return int(txt)
        if proc is not None and proc.poll() is not None and pidf.is_file():
            break
        time.sleep(0.05)
    raise AssertionError("the fixture never recorded its grandchild pid")


def test_the_supervisor_deadline_reaches_what_the_script_launched(tmp_path):
    """THE FIX. `run_supervised` puts the child in its own session and
    `_default_kill` signals that GROUP, so `sh -> sleep 600` dies whole.

    Before this, the deadline killed `sh` and left `sleep 600` reparented to
    init. Under the per-file landing driver that leftover is a live descendant
    of the pytest session and the file's WHOLE result was UNKNOWN — measured on
    `test_full_suite_run_check.py`, every one of whose 23 tests passes.
    """
    script = tmp_path / "hangs.sh"
    pidf = tmp_path / "gc.pid"
    _grandchild_of(script, pidf)

    started = time.monotonic()
    res = _watchdog.run_supervised(
        ["bash", str(script)], stall_grace_s=3, hard_ceiling_s=3, poll_s=1)
    elapsed = time.monotonic() - started
    assert res.rc != 0, "the deadline did not fire at all"
    assert elapsed < 120, f"the deadline did not fire: {elapsed:.1f}s"

    gc = int(pidf.read_text().strip())
    assert _wait_gone(gc), (
        f"grandchild {gc} outlived the supervised deadline — the driver will "
        "call the enclosing file's result UNKNOWN however green its tests are")


def test_a_head_only_kill_still_orphans_the_grandchild(tmp_path):
    """THE NEGATIVE CONTROL. The pre-fix idiom — launch in the caller's own
    session, kill the direct child — must STILL leak, or the arm above is
    indistinguishable from doing nothing.

    It CLEANS UP THE ORPHAN IT CREATES: leaving a `sleep 600` behind would make
    THIS file the next NORECORD, which would be a fine joke and a bad test.
    """
    script = tmp_path / "hangs.sh"
    pidf = tmp_path / "gc.pid"
    _grandchild_of(script, pidf)

    proc = subprocess.Popen(["bash", str(script)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    gc = _read_pid(pidf, proc)
    try:
        proc.kill()                      # the pre-fix idiom: the head only
        proc.wait()
        time.sleep(0.5)
        assert _alive(gc), (
            "a head-only kill did not orphan the grandchild, so the group kill "
            "above proves nothing")
    finally:
        try:
            os.kill(gc, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        assert _wait_gone(gc), f"failed to clean up orphan {gc}"


def test_the_kill_never_signals_a_group_the_child_does_not_lead():
    """The safety half of the same clause, asserted rather than assumed.

    `os.getpgid(pid)` of a child that is NOT its own session leader returns
    THIS process's group. Signalling it would kill the supervisor — so
    `_default_kill` asks first, and this is the asking.
    """
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)     # OUR group
    try:
        assert os.getpgid(proc.pid) != proc.pid, (
            "the fixture is already its own group leader, so this test cannot "
            "exercise the guard it exists for")
        _watchdog._default_kill(proc, "test")
        proc.wait(timeout=30)
        assert _alive(os.getpid()), "the supervisor signalled its own group"
    finally:
        if proc.poll() is None:                            # pragma: no cover
            proc.kill()
            proc.wait()


def test_the_repaired_call_sites_carry_the_idiom_that_repairs_them():
    """Anchored to the operation, not to a line number."""
    wd = (_PROGRAMS / "_watchdog.py").read_text(encoding="utf-8")
    assert "start_new_session=True" in wd and "killpg" in wd, (
        "the supervisor no longer owns the tree it launches")
    nvt = (_PROGRAMS / "not_verified_tier.py").read_text(encoding="utf-8")
    assert "start_new_session=True" in nvt and "killpg" in nvt, (
        "a timed-out probe no longer reaps what it probed")


# ===========================================================================
# CAUSE 3 — a node id the subject chose was longer than the channel
# ===========================================================================
def test_a_long_node_id_cannot_blind_the_supervisor():
    """THE FIX. MEASURED at b309595f06: `pytest --collect-only -q
    programs/tests/test_gds_substance_check.py` emits node ids of 614505,
    607419 and 438868 characters, because its parameters are 150 KB `bytes`
    blobs and pytest ascii-escapes a parameter into the id. Every progress
    event naming one was over the reader's 64 KiB line limit, the stream was
    refused, and the file had no result."""
    long_id = "programs/tests/test_x.py::test_y[" + ("A" * 600_000) + "]"
    bounded = PP._bounded_nodeid(long_id)
    assert len(bounded) < 64 * 1024, len(bounded)
    assert len(bounded.encode("utf-8")) < D._MAX_PROGRESS_LINE


def test_the_bound_is_injective_so_two_long_ids_stay_two():
    """The clause that keeps the fix from being a different UNKNOWN.

    The reader uses the node id as an identity key: a `test_finish` must name
    an id `item_collected` announced, and a REPEAT is a refusal. A bare prefix
    would fold two 600 KB siblings into one and buy "oversized event" back as
    "duplicate item_collected".
    """
    head = "programs/tests/test_x.py::test_y[" + ("A" * 600_000)
    a = PP._bounded_nodeid(head + "1]")
    b = PP._bounded_nodeid(head + "2]")
    assert a != b, "two distinct long node ids collapsed into one"


def test_a_short_node_id_is_passed_through_byte_for_byte():
    plain = "programs/tests/test_x.py::test_y[case-3]"
    assert PP._bounded_nodeid(plain) == plain


def test_the_readers_line_limit_is_unchanged():
    """THE NEGATIVE CONTROL for this class. The bound above is on what an
    HONEST emitter writes. The reader's refusal is untouched: a genuinely
    oversized line in the stream is still a refusal, not a longer read."""
    assert D._MAX_PROGRESS_LINE == 64 * 1024


# ===========================================================================
# CAUSE 4 — a grace shorter than a budget the subject itself declares
# ===========================================================================
_LONG = "VIBEIC_SILENCE_BUDGET_S = 1800\n\ndef test_ok():\n    assert True\n"
_OVER = ("VIBEIC_SILENCE_BUDGET_S = 99999\n\n"
         "def test_ok():\n    assert True\n")
_COMPUTED = ("import os\n"
             "VIBEIC_SILENCE_BUDGET_S = int(os.environ.get('X', '900'))\n\n"
             "def test_ok():\n    assert True\n")


def test_a_file_may_declare_that_its_own_work_is_legitimately_silent(tmp_path):
    """THE FIX for the three STALLED files, and the shape it deliberately is
    NOT: `--stall-after` is not raised for anybody. The declaration is per file
    and lives in the file, so the diff that adds one is the review of it."""
    f = tmp_path / "test_declares.py"
    f.write_text(_LONG, encoding="utf-8")
    budget, problem = D._declared_silence_budget(f)
    assert (budget, problem) == (1800.0, "")


def test_a_file_that_declares_nothing_keeps_the_base_grace(tmp_path):
    f = tmp_path / "test_plain.py"
    f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert D._declared_silence_budget(f) == (None, "")


def test_a_declaration_past_the_ceiling_is_REFUSED_not_clamped(tmp_path):
    """The direction that stops the declaration from becoming an off switch.

    A clamp would let a file ask for no supervision at all and be quietly given
    an hour instead — a number nobody would ever read again. The file is
    refused by name, which is a thing a reader has to answer.
    """
    f = tmp_path / "test_over.py"
    f.write_text(_OVER, encoding="utf-8")
    budget, problem = D._declared_silence_budget(f)
    assert budget is None
    assert "exceeds the" in problem and "ceiling" in problem, problem


def test_a_negative_declaration_is_refused_for_the_reason_it_is_wrong(tmp_path):
    """A minus sign is not "this has to be run". `-5` parses as a UnaryOp over
    a Constant, and reporting it as an unreadable expression would send a
    reader hunting the wrong defect."""
    f = tmp_path / "test_neg.py"
    f.write_text("VIBEIC_SILENCE_BUDGET_S = -5\n", encoding="utf-8")
    budget, problem = D._declared_silence_budget(f)
    assert budget is None
    assert "not a positive grace" in problem, problem


def test_a_declaration_that_has_to_be_RUN_is_refused(tmp_path):
    """The file is parsed, never imported. A computed budget cannot be read
    without executing the subject, so it is refused rather than guessed at."""
    f = tmp_path / "test_computed.py"
    f.write_text(_COMPUTED, encoding="utf-8")
    budget, problem = D._declared_silence_budget(f)
    assert budget is None
    assert "not a plain number literal" in problem, problem


def test_the_declaration_reaches_the_run_and_is_disclosed(tmp_path):
    """END TO END: the driver prints the grace it actually used, so a reader of
    the log never has to infer which number supervised which file."""
    corpus = _tree(tmp_path, {"test_declares.py": _LONG})
    p = _drive(corpus, tmp_path / "j.xml")
    out = p.stdout + p.stderr
    assert "SILENCE_BUDGET  test_declares.py  1800s declared in the file" in out, \
        out[-3000:]
    assert p.returncode == D.RC_OK, out[-3000:]


def test_an_over_ceiling_declaration_stops_the_file_at_the_driver(tmp_path):
    corpus = _tree(tmp_path, {"test_over.py": _OVER})
    p = _drive(corpus, tmp_path / "j.xml")
    out = p.stdout + p.stderr
    assert "NORECORD  test_over.py" in out, out[-3000:]
    assert p.returncode == D.RC_NORECORD, out[-3000:]


def test_the_aggregate_lane_inherits_the_widest_declaration(tmp_path):
    """The lane the landing gate actually uses. The aggregate is ONE session
    over the whole selection, so a file whose test is legitimately silent for
    1800 s silences the aggregate for 1800 s. A per-file-only repair would have
    left the same UNKNOWN exactly where it costs most."""
    corpus = _tree(tmp_path, {"test_plain.py": "def test_ok():\n    assert True\n",
                              "test_declares.py": _LONG})
    p = _drive(corpus, tmp_path / "j.xml", "--aggregate-check")
    out = p.stdout + p.stderr
    assert "SILENCE_BUDGET  [aggregate]  1800s" in out, out[-3000:]
    assert p.returncode == D.RC_OK, out[-3000:]


def test_the_three_declaring_files_carry_their_measurement(tmp_path):
    """A number without the run that produced it is a guess with a decimal
    point. Each declaration must cite seconds measured on a real run."""
    for name in ("test_flow_matrix_coverage.py",
                 "test_flow_matrix_census_freshness.py",
                 "test_issue1129_gatekeeper_prepare_landing.py"):
        src = (_TESTS / name).read_text(encoding="utf-8")
        assert D._SILENCE_BUDGET_NAME in src, f"{name} lost its declaration"
        budget, problem = D._declared_silence_budget(_TESTS / name)
        assert problem == "", f"{name}: {problem}"
        assert budget is not None and budget > D.DEFAULT_STALL_AFTER, (
            f"{name} declares {budget}, which is not larger than the base "
            f"grace — the declaration does nothing")
        head = src[:src.index(D._SILENCE_BUDGET_NAME)]
        assert "MEASURED" in head, (
            f"{name} declares a silence budget with no measurement above it")


# ===========================================================================
# CAUSE 4b — nothing about the stall detector changed, and it still fires
# ===========================================================================
_WEDGED = (
    "import threading\n"
    "def test_wedged():\n"
    "    threading.Event().wait()\n"
)


def test_a_genuinely_wedged_session_is_still_NORECORD(tmp_path):
    """THE REVERSE CONTROL THE WHOLE CHANGE RESTS ON.

    Three of the eight files were reported STALLED. Not one line of the stall
    detector was touched — the remedy for a slow file is never a bigger number
    — and this is how that is proved rather than asserted: a session that makes
    no lifecycle progress at all must STILL be refused as UNKNOWN, by name,
    with the stall named as the cause.
    """
    corpus = _tree(tmp_path, {"test_wedged.py": _WEDGED})
    p = _drive(corpus, tmp_path / "j.xml")
    out = p.stdout + p.stderr
    assert "NORECORD  test_wedged.py" in out, out[-4000:]
    assert "STALLED after" in out, out[-4000:]
    assert "UNKNOWN, not clean" in out, out[-4000:]
    assert p.returncode == D.RC_NORECORD, out[-4000:]


_WEDGED_DECLARING = (
    "VIBEIC_SILENCE_BUDGET_S = 30\n"
    "import threading\n"
    "def test_wedged():\n"
    "    threading.Event().wait()\n"
)


def test_a_declaring_file_that_wedges_is_STILL_killed_at_its_own_number(
        tmp_path):
    """THE CONTROL ON THE NEW MECHANISM ITSELF — the one that decides whether
    it is a supervision policy or an off switch.

    A declaration WIDENS a grace; it does not remove one. This file asks for 30
    s and then wedges forever. It must be killed, it must be NORECORD, and the
    refusal must quote 30 — not the base 20 it was driven with, which would mean
    the declaration was never honoured, and not silence, which would mean it was
    honoured as an exemption.

    30 s is the smallest number that is BOTH larger than the base grace this
    helper drives with (20 s) and therefore actually exercises the widening.
    """
    corpus = _tree(tmp_path, {"test_wedged_declaring.py": _WEDGED_DECLARING})
    started = time.monotonic()
    p = _drive(corpus, tmp_path / "j.xml")
    elapsed = time.monotonic() - started
    out = p.stdout + p.stderr
    assert "SILENCE_BUDGET  test_wedged_declaring.py  30s" in out, out[-4000:]
    assert "NORECORD  test_wedged_declaring.py" in out, out[-4000:]
    assert "STALLED after 30 s" in out, (
        "the refusal did not quote the grace the file declared, so the "
        f"declaration reached the log and not the supervisor\n{out[-4000:]}")
    assert p.returncode == D.RC_NORECORD, out[-4000:]
    # It waited for the DECLARED number rather than the base one. Load can only
    # make this larger, so the lower bound is the safe direction to assert.
    assert elapsed >= 25, (
        f"the run ended after {elapsed:.1f}s, before the 30 s it declared — "
        "the base grace fired and the declaration did nothing")
