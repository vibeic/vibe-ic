"""The landing review has a budget, and running out of it BLOCKS.

Owner ruling, 2026-08-21: a landing may spend up to four minutes on
`gatekeeper_review`, and "if the review cannot decide inside that, it must
return rc=2 UNDETERMINED and BLOCK, never rc=0".

THE NUMBER MOVED AND THE RULE DID NOT. The four minutes was chosen for a
review that was going to be HANDED this run's hygiene record. That handover was
a command-line flag on the one gate that may not be skipped, it is gone, and
the review now runs the set — so the script's default is 1800 s,
`repo_hygiene_gate._HYGIENE_STALL_GRACE_S`. Nothing here asserts 240; the
budget is a parameter of `_drive`, and every case below drives the RULE: a
review that did not decide arrives as rc 2 and BLOCKS, never rc 0.

The function is EXTRACTED FROM THE REAL SCRIPT rather than restated here. A
copy of the case statement in a test would go on passing after the script's own
copy was edited, which is the drift this repo removes from gates one at a time;
`_extract` fails loudly if the function is renamed or reshaped.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDER = ROOT / "tools" / "gatekeeper-land.sh"

sys.path.insert(
    0, str(ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"))
import _watchdog                                              # noqa: E402

#: How long a driver may be COMPLETELY IDLE before it is called hung.
#:
#: This replaces the `subprocess.run(..., timeout=60)` the three drivers below
#: carried. Their comment already conceded what the number was -- "this is a
#: backstop and not a runtime" -- but `subprocess.run` cannot express that
#: distinction: it counts ELAPSED seconds, so a bash driver that was working
#: and merely slow (a loaded host, 32 lanes on the box) raised
#: `TimeoutExpired`, and pytest recorded that as a RED test about the LANDER.
#: It is not one. Nothing about `run_gatekeeper_review` is established by a
#: driver the clock ran out on.
#:
#: `stall_grace_s` is the tolerance for SILENCE, not for duration: the whole
#: process tree -- output bytes, CPU seconds, I/O bytes -- must be flat across
#: the window before the kill fires. A driver that is genuinely working runs to
#: completion however long that legitimately takes; one that has stopped moving
#: is still stopped, so the hang these drivers can produce is still caught.
#:
#: 60 remains `ci_harness_timeout_ceiling_check.inner_timeout_ceiling` for this
#: tree, and the number is kept so no bound in this file rose. The stubs here
#: are killed by the script's own `GK_REVIEW_BUDGET_S`, which is the budget
#: under test and is untouched.
_STALL_GRACE_S = 60


def _bash(script: Path) -> subprocess.CompletedProcess:
    """Run a driver script under progress-stall supervision.

    A stall is raised rather than returned: a driver that never finished has no
    `RC=` line, and letting the caller parse one out of a truncated stdout
    would invent a verdict. The raised message says the run made NO PROGRESS,
    which is a statement about the driver -- never that the lander was slow.
    """
    # stdout and stderr stay SEPARATE, as `subprocess.run` left them: two
    # callers below read only `.stdout` and merging would change what they
    # parse, which a supervision change has no business doing.
    res = _watchdog.run_host_supervised(
        ["bash", str(script)], stall_grace_s=_STALL_GRACE_S)
    if res.outcome in ("stalled", "ceiling"):
        raise AssertionError(
            f"the driver made NO forward progress for {_STALL_GRACE_S}s -- "
            f"nothing in its process tree (output, CPU or I/O) advanced, so it "
            f"was stopped as hung. This is NOT a statement that the lander is "
            f"slow, and no verdict about `run_gatekeeper_review` was reached."
            f"\n{(res.out + res.err)[-2000:]}")
    return _watchdog.completed_process(["bash", str(script)], res)


def _extract(name: str) -> str:
    src = LANDER.read_text(encoding="utf-8")
    # `{` may carry a trailing comment — most of these helpers document their
    # argument list right there — so the line is matched up to its newline
    # rather than assuming the brace ends it.
    m = re.search(rf"^{re.escape(name)}\(\) \{{[^\n]*\n(.*?)^\}}\n",
                  src, re.S | re.M)
    assert m, f"{name}() is not in {LANDER.name} in the shape this test drives"
    return f"{name}() {{\n{m.group(1)}}}\n"


def _drive(tmp_path, stub_body: str, budget: str = "240"):
    """Run the REAL function against a stub `gatekeeper_review.py`."""
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "gatekeeper_review.py").write_text(
        textwrap.dedent(stub_body), encoding="utf-8")
    script = tmp_path / "drive.sh"
    script.write_text(
        "set -u\n"
        f'PROGRAMS="{programs}"\nROOT="{tmp_path}"\nBASE="origin/main"\n'
        f'GK_REVIEW_RECORD="{tmp_path}/review-hygiene.json"\n'
        f'GK_REVIEW_BUDGET_S="{budget}"\n'
        + _extract("run_gatekeeper_review")
        + 'run_gatekeeper_review; echo "RC=$?"\n',
        encoding="utf-8")
    r = _bash(script)
    rc = int(re.search(r"RC=(-?\d+)", r.stdout).group(1))
    return rc, r.stdout


def test_a_review_that_says_merge_ok_passes(tmp_path):
    rc, out = _drive(tmp_path, """
        import sys
        print("VERDICT: MERGE_OK")
        sys.exit(0)
        """)
    assert rc == 0, out


def test_a_review_that_requests_changes_blocks(tmp_path):
    rc, out = _drive(tmp_path, """
        import sys
        print("VERDICT: REQUEST_CHANGES")
        sys.exit(1)
        """)
    assert rc == 1, out


def test_a_review_that_runs_out_of_budget_is_rc_2_and_blocks(tmp_path):
    """THE RULING'S CASE. Not rc 0, and not the 124 `timeout` really returns —
    a landing must be able to tell 'undecided' from 'decided nothing is wrong',
    and 124 reaching a caller that only special-cases 0 and 1 is how the first
    becomes the second."""
    rc, out = _drive(tmp_path, """
        import time
        time.sleep(30)
        """, budget="1")
    assert rc == 2, out
    assert "UNDETERMINED" in out
    assert "did not decide within 1s" in out


def test_an_unexpected_exit_status_is_rc_2_and_blocks(tmp_path):
    """A crash, an import error, a python that is not there. None of them are
    MERGE_OK and none of them are REQUEST_CHANGES, so none of them may be
    resolved by guessing which one they resemble."""
    rc, out = _drive(tmp_path, """
        raise SystemExit(9)
        """)
    assert rc == 2, out
    assert "UNDETERMINED" in out and "exited 9" in out


def test_a_review_killed_outright_is_rc_2_and_blocks(tmp_path):
    rc, out = _drive(tmp_path, """
        import os, signal
        os.kill(os.getpid(), signal.SIGKILL)
        """)
    assert rc == 2, out
    assert "UNDETERMINED" in out


@pytest.mark.parametrize("stub,expect", [
    ("import sys; sys.exit(0)", 0),
    ("import sys; sys.exit(1)", 1),
    ("import sys; sys.exit(2)", 2),
    ("import sys; sys.exit(3)", 2),
])
def test_no_status_other_than_zero_reaches_a_caller_as_a_pass(
        tmp_path, stub, expect):
    rc, out = _drive(tmp_path, stub)
    assert rc == expect, out
    if expect != 0:
        assert rc != 0


# --- the wiring itself, so it cannot quietly come undone -------------------

def test_the_lander_actually_calls_the_review():
    src = LANDER.read_text(encoding="utf-8")
    assert 'run "full:gatekeeper-review"' in src, (
        "the review is defined but never invoked — which is the exact state "
        "this wiring exists to end")


def test_the_review_is_a_declared_landing_unit():
    """`landing_completion_record.finish` refuses unless the emitted labels
    equal the complete tuple, so a unit the lander emits and the tuple does not
    declare would refuse every landing — and one the tuple declares and the
    lander never emits would do the same."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lcr", ROOT / "tools" / "ci" / "landing_completion_record.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    units = list(mod.LANDING_PROGRESS_UNITS)
    assert "full:gatekeeper-review" in units
    # AFTER the hygiene run whose record it reads, and BEFORE the closing tree
    # gates, which is the only position where its input exists and its own
    # writes are still covered.
    assert units.index("full:repo-hygiene") < units.index("full:gatekeeper-review")
    assert units.index("full:gatekeeper-review") < units.index("full:write-guard-final")


def test_the_hygiene_record_is_written_unconditionally():
    """With no record the review can only report `skipped — 0 gate state(s)
    examined`, which is a deadline that never comes due."""
    src = LANDER.read_text(encoding="utf-8")
    assert 'GK_HYG=(--summary-json "$GK_HYG_RECORD")' in src
    assert re.search(r'GK_HYG_RECORD="\$\{GATEKEEPER_HYGIENE_REPORT:-', src)


# --- THE SEAM NOTHING HAD EXERCISED: `run` GIVEN A SHELL FUNCTION ----------
#
# Every other `run` / `run_capture` call in the lander passes `python3`.
# `run_gatekeeper_review` is the first shell FUNCTION handed to it, and the file
# has a separate `fn_capture` wrapper precisely because functions are not always
# interchangeable with commands here — `fn_capture` exists for stages that print
# their own PASS/FAIL line and signal through `FAILED` rather than through an
# exit status, which this one does not. So `run` is the right pairing, and that
# is a reasoned choice that was worth executing rather than trusting: if
# `run_capture`'s `out="$("$@" 2>&1)"` did not invoke a function, every landing
# would break at this unit.
_CHAIN = ("landing_output_sha", "landing_record", "lane_write",
          "lane_reported", "lane_resolve", "run_capture", "run_emit", "run")


def _drive_through_run(tmp_path, stub_body: str, budget: str = "240"):
    """Drive the REAL `run` -> `run_capture` -> `run_emit` chain."""
    programs = tmp_path / "programs"
    programs.mkdir(exist_ok=True)
    (programs / "gatekeeper_review.py").write_text(
        textwrap.dedent(stub_body), encoding="utf-8")
    lanes = tmp_path / "lanes"
    lanes.mkdir(exist_ok=True)
    script = tmp_path / "drive_run.sh"
    script.write_text(
        "set -u\n"
        f'PROGRAMS="{programs}"\nROOT="{tmp_path}"\nBASE="origin/main"\n'
        f'GK_REVIEW_RECORD="{tmp_path}/review-hygiene.json"\n'
        f'GK_REVIEW_BUDGET_S="{budget}"\nLANE_DIR="{lanes}"\n'
        'LANE_BROKEN=0\nLANE_WAIT_RC=0\nLANDING_RECORD_ENABLED=0\nFAILED=0\n'
        'EMIT_OUT=""\nEMIT_RC=0\n'
        + "".join(_extract(fn) for fn in _CHAIN)
        + _extract("run_gatekeeper_review")
        + 'run "full:gatekeeper-review" "gatekeeper review" '
          'run_gatekeeper_review\n'
          'echo "FAILED=$FAILED"\n',
        encoding="utf-8")
    r = _bash(script)
    failed = re.search(r"FAILED=(\d+)", r.stdout)
    return (int(failed.group(1)) if failed else None), r.stdout + r.stderr


def test_run_invokes_the_function_and_reports_a_pass(tmp_path):
    failed, out = _drive_through_run(tmp_path, """
        import sys
        print("VERDICT: MERGE_OK")
        sys.exit(0)
        """)
    assert "  PASS  gatekeeper review" in out, out
    assert failed == 0, out


def test_run_invokes_the_function_and_reports_a_failure(tmp_path):
    failed, out = _drive_through_run(tmp_path, """
        import sys
        print("VERDICT: REQUEST_CHANGES")
        sys.exit(1)
        """)
    assert "  FAIL  gatekeeper review" in out, out
    assert failed == 1, out


def test_an_undetermined_review_reaches_the_landing_as_a_failure(tmp_path):
    """THE WHOLE POINT, end to end rather than at the function boundary: the
    rc 2 the budget mapping produces must arrive at the landing as FAILED=1,
    not merely as a non-zero somebody still has to interpret."""
    failed, out = _drive_through_run(tmp_path, """
        import time
        time.sleep(30)
        """, budget="1")
    assert "  FAIL  gatekeeper review" in out, out
    assert "UNDETERMINED" in out, out
    assert failed == 1, out


def test_the_function_is_not_silently_treated_as_a_missing_command(tmp_path):
    """The failure mode this whole section exists for. If `run_capture` could
    not invoke a function it would report 127 command-not-found — which is
    non-zero, so the landing would still refuse, but it would refuse EVERY time
    and name the wrong cause. A red that is always red teaches nobody anything.
    """
    failed, out = _drive_through_run(tmp_path, """
        import sys
        sys.exit(0)
        """)
    assert "command not found" not in out, out
    assert "127" not in out, out
    assert failed == 0, out


# --- THE SHAPE THE REVIEW IS TOLD ABOUT ------------------------------------
#
# `cheap:landing-shape` counts the range into `GK_RANGE_N` and, above one, runs
# `landing_is_one_commit_check.py --batch` and passes. The review runs that
# SAME checker again through `gatekeeper_review.one_commit_gate`. While this
# invocation forwarded nothing, one caller called the tree a valid batch and
# the other called it an illegal landing, in one gate run about one tree.
#
# A protected-path ceremony landing is structurally at least three commits, so
# the un-forwarded form had no passing case: it refused every batch, always.
#
# Driven through the REAL extracted function against a stub that records the
# argv it was handed, so what is asserted is the WIRING and not the presence of
# a string somewhere in the file.

def _review_argv(tmp_path, range_n=None):
    """Return the argv the real function hands `gatekeeper_review.py`."""
    programs = tmp_path / "programs"
    programs.mkdir(exist_ok=True)
    argv_file = tmp_path / "argv.txt"
    (programs / "gatekeeper_review.py").write_text(textwrap.dedent(f"""
        import sys
        open({str(argv_file)!r}, "w").write("\\n".join(sys.argv[1:]))
        print("VERDICT: MERGE_OK")
        sys.exit(0)
        """), encoding="utf-8")
    script = tmp_path / "drive_argv.sh"
    # Unset rather than empty when `range_n is None`: that is the state the
    # other drivers in this file leave it in, and `set -u` is the point.
    range_line = "" if range_n is None else f'GK_RANGE_N="{range_n}"\n'
    script.write_text(
        "set -u\n"
        f'PROGRAMS="{programs}"\nROOT="{tmp_path}"\nBASE="origin/main"\n'
        f'GK_REVIEW_RECORD="{tmp_path}/review-hygiene.json"\n'
        'GK_REVIEW_BUDGET_S="240"\n'
        + range_line
        + _extract("run_gatekeeper_review")
        + 'run_gatekeeper_review; echo "RC=$?"\n',
        encoding="utf-8")
    r = _bash(script)
    m = re.search(r"RC=(-?\d+)", r.stdout)
    rc = int(m.group(1)) if m else None
    argv = (argv_file.read_text(encoding="utf-8").splitlines()
            if argv_file.exists() else [])
    return rc, argv, r.stdout + r.stderr


def test_a_batch_range_forwards_the_batch_flag_to_the_review(tmp_path):
    """THE DEFECT, at the seam where it lived."""
    rc, argv, out = _review_argv(tmp_path, range_n=3)
    assert rc == 0, out
    assert "--batch" in argv, (
        "the landing-shape gate already counted this range as a batch and "
        "passed it that way; the review runs the same checker and was told "
        f"nothing, so it can only ever refuse. argv={argv}\n{out}")


def test_a_one_commit_range_does_not_claim_to_be_a_batch(tmp_path):
    """The flag is OPT-IN and asks a different, stronger question. A single
    landing that opted into it would be asserting a shape nobody checked."""
    rc, argv, out = _review_argv(tmp_path, range_n=1)
    assert rc == 0, out
    assert "--batch" not in argv, f"argv={argv}\n{out}"


def test_an_uncounted_range_claims_nothing_and_does_not_die_under_set_u(
        tmp_path):
    """`GK_RANGE_N` unset is the shape every other driver in this file leaves,
    and a bare dereference under `set -u` kills the function before the case
    statement — the failure `${LANE_DIR:-}` was already fixed for once."""
    rc, argv, out = _review_argv(tmp_path, range_n=None)
    assert rc == 0, out
    assert "--batch" not in argv, f"argv={argv}\n{out}"
