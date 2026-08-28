"""tests/test_progress_run.py — the drop-in that judges PROGRESS, not duration.

The owner's ruling, on a failure in a file nobody had touched:

    你怎麼知道它 60 秒這次過了，換一臺機器會不會跑得更久或跑得更快？你不知道嘛。

So the acceptance bar for `_progress_run` is BIDIRECTIONAL, and neither half is
worth anything alone:

  1. a slow-but-PROGRESSING child is NO LONGER FAILED — the defect being fixed;
  2. a genuinely STALLED child is STILL CAUGHT — because a guard that stopped
     refusing is a deletion, not a fix.

Each pair below is written as an explicit A/B against the shape it replaces:
the SAME child is driven through `subprocess.run(timeout=...)` and through
`_progress_run.run(...)`, and the two are asserted to DISAGREE. Testing only the
new call would pass just as well if the new call never refused anything at all.

All timing is compressed by injecting the cadence (`poll_s`/`stall_looks`), never
by waiting out the shipped six-minute default.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _progress_run as R  # noqa: E402

# A compressed cadence: 3 looks 0.2s apart = 0.6s of stillness ⇒ STALLED.
FAST = dict(poll_s=0.2, stall_looks=3)

# Children, as argv. Neither names a tool, a PDK or a design: `sys.executable`
# is the interpreter already running this test.
BUSY_QUIET = "t=__import__('time').monotonic()+2.0\nx=0\nwhile __import__('time').monotonic()<t: x+=1\n"
SLEEP_FOREVER = "__import__('time').sleep(600)\n"
CHATTY_SLOW = ("import sys,time\n"
               "for _ in range(10):\n"
               "    sys.stdout.write('tick\\n'); sys.stdout.flush(); time.sleep(0.2)\n")


def _py(src):
    return [sys.executable, "-c", src]


# ── 1. THE DEFECT: a slow-but-progressing child must no longer be failed ─────
def test_a_quiet_cpu_bound_child_is_failed_by_the_clock_and_not_by_progress():
    """The owner's exact scenario: it computes, it says nothing, it runs long.

    This is the A/B that carries the whole change. The SAME child is refused by
    a wall-clock bound and accepted by progress supervision, so the assertion
    cannot be satisfied by a primitive that simply never refuses.
    """
    argv = _py(BUSY_QUIET)          # burns CPU for 2s, emits NOTHING

    # A: the shape being replaced. A bound shorter than the work = a verdict.
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(argv, capture_output=True, text=True, timeout=0.6)

    # B: the replacement. The stall window (0.6s) is the SAME number, and is
    # deliberately far shorter than the child's 2s runtime — proving the child
    # survives because it is PROGRESSING, not because the window was widened.
    cp = R.run(argv, **FAST)
    assert cp.returncode == 0


def test_a_chatty_child_outliving_its_window_is_kept_alive_by_output():
    """Output is the second progress signal, and it alone must suffice."""
    argv = _py(CHATTY_SLOW)         # ~2s, a line every 0.2s
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(argv, capture_output=True, text=True, timeout=0.6)
    cp = R.run(argv, **FAST)
    assert cp.returncode == 0
    assert cp.stdout.count("tick") == 10


def test_the_child_is_never_killed_for_running_long_however_long_it_runs():
    """The property a wall-clock bound cannot have.

    The stall window is held FIXED while the child's runtime is tripled. If any
    part of the decision scaled with elapsed time, the longer child would die.
    """
    for seconds in (0.5, 1.5):
        src = (f"t=__import__('time').monotonic()+{seconds}\nx=0\n"
               f"while __import__('time').monotonic()<t: x+=1\n")
        cp = R.run(_py(src), **FAST)
        assert cp.returncode == 0, f"a {seconds}s progressing child was killed"


# ── 2. THE GUARD: a genuinely stalled child must still be caught ─────────────
def test_a_motionless_child_is_still_caught():
    """No CPU, no I/O, no output — the guard must still refuse it.

    Without this half, every assertion above is satisfied by deleting the guard.
    """
    t0 = time.monotonic()
    with pytest.raises(R.Stalled) as exc:
        R.run(_py(SLEEP_FOREVER), **FAST)
    elapsed = time.monotonic() - t0
    assert elapsed < 30, "the stall was detected, but not promptly"
    assert "STALLED" in str(exc.value)
    assert exc.value.looks == 3


def test_the_stall_report_names_which_signals_it_could_actually_read():
    """flow-change-acceptance §6 — degrade LOUDLY.

    A stall observed with a degraded probe set is a weaker claim than one
    observed with all three, so the result must say which it was rather than
    presenting both the same way.
    """
    with pytest.raises(R.Stalled) as exc:
        R.run(_py(SLEEP_FOREVER), **FAST)
    assert isinstance(exc.value.signals, dict)
    assert set(exc.value.signals) == {"output", "cpu", "io"}
    assert "signals readable:" in str(exc.value)


def test_a_stall_is_a_distinct_outcome_not_a_returncode():
    """A stall must not be able to impersonate a child that exited non-zero.

    If a stall were reported as an rc, every existing `if rc != 0: fail` in the
    repo would silently convert it straight back into a verdict about the
    subject — the defect, restored through the back door.
    """
    with pytest.raises(R.Stalled):
        R.run(_py(SLEEP_FOREVER), **FAST)
    cp = R.run(_py("import sys; sys.exit(3)"), **FAST)
    assert cp.returncode == 3          # a real non-zero exit is still an rc


# ── 3. THE GATE FACE: a stall reaches the stamp as UNDETERMINED ──────────────
def test_run_or_undetermined_separates_a_stall_from_a_verdict():
    """The landing gate's own rule: a review that could not decide must never
    reach the stamp as a review that decided nothing was wrong — and equally,
    must never reach it as one that decided something WAS."""
    cp, reason = R.run_or_undetermined(_py("import sys; sys.exit(1)"), **FAST)
    assert reason is None and cp.returncode == 1   # a real failing verdict

    cp, reason = R.run_or_undetermined(_py(SLEEP_FOREVER), **FAST)
    assert cp is None and reason and "STALLED" in reason
    assert R.RC_UNDETERMINED == 2


# ── 4. THE MEASUREMENT: the session floor can only add patience ──────────────
def test_a_measured_slow_host_makes_the_primitive_more_patient_never_less():
    """Where a number is unavoidable it is measured in-session — but a
    measurement that could SHORTEN the window would be a new way to fail a
    slow host, which is the defect wearing a lab coat."""
    R._spawn_floor_cache = None
    try:
        R.spawn_floor_s(_probe=lambda: 0.0)      # an impossibly fast host
        fast_host = R._poll_interval()
        R._spawn_floor_cache = None
        R.spawn_floor_s(_probe=lambda: 5.0)      # a very slow host
        slow_host = R._poll_interval()
    finally:
        R._spawn_floor_cache = None
    assert fast_host == R.DEFAULT_POLL_S, "a fast host must not shorten the window"
    assert slow_host > fast_host, "a slow host must widen the window"


def test_the_shipped_defaults_are_a_count_of_looks_not_a_duration():
    """The shipped configuration must not contain a runtime estimate."""
    assert isinstance(R.DEFAULT_STALL_LOOKS, int)
    assert R.DEFAULT_STALL_LOOKS >= 3


# ── 5. DEGRADE LOUDLY on the shapes this primitive does not serve ────────────
def test_unsupported_shapes_refuse_out_loud_rather_than_hanging():
    """Bytes mode would hand back str; a stdout REDIRECT would take the output
    away from the progress meter without saying so; a decode policy other than
    the one `_watchdog` applies would be accepted and then not honoured.

    All three refuse. None hangs, and none accepts-then-ignores — which is the
    failure mode that matters here, because a converted call site that silently
    changed meaning is worse than the timeout it replaced.
    """
    with pytest.raises(NotImplementedError):
        R.run(_py("pass"), text=False, errors="replace", **FAST)
    with pytest.raises(NotImplementedError):
        R.run(_py("pass"), stdout=subprocess.DEVNULL, **FAST)
    with pytest.raises(NotImplementedError):
        R.run(_py("pass"), errors="strict", **FAST)


# ── 6. THE WIDENED SURFACE — each shape is one a call site in this repo uses ──
# Every case below asserts the argument was HONOURED, not merely accepted. An
# `input=` that reached no child, or a `stderr=STDOUT` that quietly dropped the
# second stream, would leave the converted gate reading an empty answer and
# calling it a clean one.
def test_input_is_actually_delivered_to_the_child():
    """`_published_tree` feeds `git cat-file --batch` its sha list this way."""
    src_ = "import sys; sys.stdout.write(sys.stdin.read().upper())"
    cp = R.run(_py(src_), input="hello\n", **FAST)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "HELLO", cp.stdout


def test_a_devnull_stdin_child_reads_eof_rather_than_inheriting_the_terminal():
    """The landing gates pass `stdin=DEVNULL` so a child cannot block on a
    terminal that is not there. Inheriting instead would hang a landing."""
    src_ = "import sys; sys.stdout.write(repr(sys.stdin.read()))"
    cp = R.run(_py(src_), stdin=subprocess.DEVNULL, **FAST)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "''", cp.stdout


def test_input_and_stdin_together_are_a_caller_error_not_a_silent_winner():
    with pytest.raises(ValueError):
        R.run(_py("pass"), input="x", stdin=subprocess.DEVNULL, **FAST)


def test_the_combined_stream_preserves_the_order_a_human_observes():
    """`gate_host_independence_check` compares two arms' OUTPUT, and separately
    captured stdout-then-stderr is not the order `2>&1 | tee` shows. The
    interleaving is the thing under test, so assert the order, not the bytes."""
    src_ = ("import sys\n"
            "sys.stderr.write('E1\\n'); sys.stderr.flush()\n"
            "sys.stdout.write('O1\\n'); sys.stdout.flush()\n"
            "sys.stderr.write('E2\\n'); sys.stderr.flush()\n")
    cp = R.run(_py(src_), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
               **FAST)
    assert cp.returncode == 0
    assert cp.stdout.split() == ["E1", "O1", "E2"], cp.stdout
    # There was no second stream, so there is nothing to report on one.
    assert cp.stderr == "", cp.stderr


def test_errors_replace_is_accepted_because_it_is_what_already_happens():
    """A call site that spelled the decode policy out gets what it asked for —
    including on a child that emits bytes no UTF-8 decoder accepts."""
    src_ = ("import sys; sys.stdout.buffer.write(b'ok\\xff\\n')")
    cp = R.run(_py(src_), errors="replace", **FAST)
    assert cp.returncode == 0
    assert cp.stdout.startswith("ok"), cp.stdout


def test_shell_true_still_runs_through_the_supervisor():
    cp = R.run("printf 'a\\n'", shell=True, **FAST)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "a", cp.stdout


# ── 7. THE WIDENED SURFACE IS STILL SUPERVISED, IN BOTH DIRECTIONS ───────────
# A new argument that quietly bypassed the watchdog would be the same defect
# wearing the fix's name, so each direction is asserted THROUGH the new shape.
def test_a_stalled_child_is_still_caught_through_the_combined_stream():
    """A guard that stopped refusing is a deletion, not a fix."""
    with pytest.raises(R.Stalled):
        R.run(_py(SLEEP_FOREVER), stdout=subprocess.PIPE,
              stderr=subprocess.STDOUT, **FAST)


def test_a_progressing_child_survives_the_combined_stream_far_past_a_bound():
    """The same shape, the other direction: output on the COMBINED stream is
    still read as progress, so a chatty child outliving the window lives."""
    argv = _py(CHATTY_SLOW)                      # ~2s of output, 0.6s window
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(argv, capture_output=True, text=True, timeout=0.6)
    cp = R.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **FAST)
    assert cp.returncode == 0
    assert cp.stdout.count("tick") == 10, cp.stdout


def test_a_child_fed_by_input_is_still_killed_when_it_stops_moving():
    """`input=` hands over a file and returns; it must not hand the child a
    licence to hang. Same child, same payload, and it is still caught."""
    src_ = "import sys,time; sys.stdin.read(); time.sleep(600)"
    with pytest.raises(R.Stalled):
        R.run(_py(src_), input="x\n", **FAST)


# ── 8. BYTES MODE — because decode-then-re-encode is not the same bytes ──────
def test_bytes_mode_returns_exactly_what_the_child_wrote():
    """`git ls-files -z` and `git cat-file --batch` are read as BYTES by the
    gates that call them. A decoded-and-re-encoded stream would hand them
    plausible bytes that are not the ones the child wrote — so assert the
    payload survives EXACTLY, including a sequence no UTF-8 decoder accepts."""
    payload = b"a\x00b\xff\xfe\x00c"
    src_ = ("import sys; sys.stdout.buffer.write(%r)" % payload)
    cp = R.run(_py(src_), text=False, **FAST)
    assert cp.returncode == 0
    assert cp.stdout == payload, cp.stdout
    assert isinstance(cp.stderr, bytes)
    # And the lossy alternative really would have destroyed it — this is the
    # negative control for the sentence above, not a restatement of it.
    assert payload.decode("utf-8", "replace").encode("utf-8") != payload


def test_bytes_mode_is_still_supervised_in_both_directions():
    """Skipping the decode must not skip the watchdog."""
    with pytest.raises(R.Stalled):
        R.run(_py(SLEEP_FOREVER), text=False, **FAST)
    argv = _py(CHATTY_SLOW)
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(argv, capture_output=True, timeout=0.6)
    assert R.run(argv, text=False, **FAST).stdout.count(b"tick") == 10


def test_a_bytes_mode_stall_reports_its_reason_in_bytes_not_str():
    """`run_best_effort` puts the reason on `.stderr`; a caller in bytes mode
    would crash concatenating a str there, which is the silent-breakage shape
    this module exists to avoid."""
    cp = R.run_best_effort(_py(SLEEP_FOREVER), text=False, **FAST)
    assert cp.returncode == R.RC_STALLED
    assert isinstance(cp.stderr, bytes)
    assert b"STALLED" in cp.stderr


# ── 9. THE EXCEPTION CONTRACT — a drop-in may not quietly change it ──────────
def test_a_missing_executable_raises_exactly_as_subprocess_does():
    """`subprocess.run` raises `FileNotFoundError` for an executable that is not
    there, and call sites across this repo catch it to say "the tool is not
    installed". The supervisor reports that as rc 127, which is right for a
    supervisor and wrong for a drop-in: every one of those handlers would go
    silent and 127 would be read as the tool's own verdict.

    Asserted as an A/B against the call being replaced, so it cannot pass by
    both sides merely doing something."""
    argv = ["/nonexistent/definitely-not-a-tool-here", "--version"]
    with pytest.raises(FileNotFoundError):
        subprocess.run(argv, capture_output=True, text=True, timeout=5)
    with pytest.raises(FileNotFoundError):
        R.run(argv, **FAST)
    # and the best-effort face must not swallow it into a plain rc either
    with pytest.raises(FileNotFoundError):
        R.run_best_effort(argv, **FAST)
