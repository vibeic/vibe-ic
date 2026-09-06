"""#581 — an ATPG timeout was bookkept against a capability the engine HAS.

The wall-budget expiry fell into a blanket `except Exception` and was recorded
as

    {"verdict": "SKIPPED-CONDITION",
     "reason": "Fault ATPG execution error: Command '[...]' timed out after 1800 seconds",
     "capability_flag": "cap:atpg_signoff_coverage"}

The `reason` string is honest. The machine-readable flag is not: it asserts the
ENGINE cannot measure this design, when the engine measured it fine and ran out
of OUR wall clock.

MEASURED, a controlled A/B on one design (sha256 x sky130A) whose only variable
is netlist size:

     8 730 comb cells   finished, `Stuck-at % : 95.05` published
    11 627 comb cells   timed out, recorded as a capability gap

Nothing about the engine's ability changed between the arms. A reader of the
second record cannot tell "raise the budget" from "the tool cannot do this",
and the flag actively points at the wrong one.

The distinction already existed one branch up: a signal death is recorded as
`engine_crash` rather than against a capability, with the comment *"a crash must
not be bookkept against a capability the engine HAS"*. A timeout is the same
argument.

SCOPE. This pins the CLASSIFICATION. The budget is still a size-independent
constant — that is the other half of #581, and scaling it needs a measured
cells-per-second rather than an invented formula, so it is not done here.
"""
from __future__ import annotations

import pathlib
import re
import subprocess  # noqa: F401
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "design_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))
import _progress_run as _pr  # noqa: E402


def _atpg_except_block() -> str:
    """The handler chain guarding the stuck-at ATPG subprocess call."""
    src = PROG.read_text(encoding="utf-8")
    # CZT-10 — the arm is now `except _pr.Stalled`. The wall clock this file
    # was written about is GONE, so `subprocess.TimeoutExpired` can no longer
    # be raised here at all; the classification #581 fought for is what this
    # file still pins, on the mechanism that replaced it.
    # ANCHORED BACKWARDS FROM THE STEP BANNER, on purpose: `_pr.Stalled` is
    # now handled in several places in this runner, and a forward `index` from
    # the top of the file found the FIRST one (a phase-1 regen arm) and
    # asserted this file's properties against a completely different handler.
    # Measured while writing this: every assertion here "failed" against code
    # that was correct.
    j = src.index("# ============ Step DT1")
    i = src.rindex("except _pr.Stalled as exc:", 0, j)
    return src[i:j]


# ── the classification ───────────────────────────────────────────────────────
def test_a_timeout_is_handled_before_the_blanket_except():
    """Order is the whole fix: `except Exception` first would swallow it.

    MORE load-bearing now, not less: `_progress_run.Stalled` is a
    `RuntimeError`, so the blanket arm would catch it just as readily as it
    caught `TimeoutExpired`, and re-apply the capability flag.
    """
    src = PROG.read_text(encoding="utf-8")
    j = src.index("# ============ Step DT1")
    t = src.rindex("except _pr.Stalled as exc:", 0, j)
    e = src.index("except Exception as exc:", t)
    assert t < e < j, "the blanket handler precedes the stall handler"


def test_the_timeout_record_carries_no_capability_flag():
    """The defect, stated as a property of the emitted record.

    `capability_flag` says the engine cannot do this. A budget expiry says
    nothing of the sort, and the two must not share a field.
    """
    block = _atpg_except_block()
    timeout_arm = block.split("except Exception as exc:", 1)[0]
    # COMMENTS STRIPPED. The arm's own comment must NAME the flag in order to
    # explain why it does not set it, and the disclosure message says "not a
    # capability gap" in prose. A scan that cannot tell documentation from code
    # has to be weakened the first time someone documents something — the same
    # mistake `test_dont_use_ordering` produced in v1.9.6.
    code = "\n".join(ln for ln in timeout_arm.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "capability_flag" not in code, (
        "the timeout arm still RECORDS a capability flag — a reader cannot tell "
        "'raise the budget' from 'the tool cannot do this'")
    assert "capability_flag" in timeout_arm, (
        "the arm no longer explains why it withholds the flag; without that, the "
        "next reader adds it back as an obvious omission")


def test_the_record_names_what_it_OBSERVED_now_that_there_is_no_limit():
    """A skip that does not say what it saw is not actionable.

    #581's version of this asked for `budget_exceeded` / `wall_budget_s`: the
    limit that was hit. There is no limit any more, so naming one would be a
    lie, and the actionable facts are what the supervisor watched and for how
    long it saw nothing move. Same purpose, honest content.
    """
    arm = _atpg_except_block().split("except Exception as exc:", 1)[0]
    for field in ("stopped_as", "stall_looks", "stall_elapsed_s",
                  "stall_signals"):
        assert field in arm, field
    code = "\n".join(ln for ln in arm.splitlines()
                      if not ln.lstrip().startswith("#"))
    assert "budget_exceeded" not in code, (
        "the record still claims a budget was exceeded; there is no budget")
    assert "wall_budget_s" not in code, (
        "the record still names a wall budget that does not exist")


def test_a_non_timeout_error_still_records_the_capability_flag():
    """The accept case, and the reason this is a split rather than a deletion.

    A missing cell model or an absent binary IS a capability gap, and dropping
    the flag for those would trade one mislabel for another.
    """
    block = _atpg_except_block()
    blanket = block.split("except Exception as exc:", 1)[1]
    assert "cap:atpg_signoff_coverage" in blanket, (
        "the genuine capability-gap path lost its flag")


# ── the dispatch actually separates them, executed rather than read ──────────
@pytest.mark.parametrize("exc,expected", [
    (_pr.Stalled(["fault"], looks=12, poll_s=30.0, elapsed_s=361.0,
                 signals={"output": True, "cpu": True, "io": True}), "stall"),
    (RuntimeError("missing cell model"), "capability"),
    (FileNotFoundError("no such tool"), "capability"),
    (OSError("container gone"), "capability"),
])
def test_python_dispatches_the_two_arms_as_written(exc, expected):
    """Mirrors the handler chain and RUNS it.

    THE MRO IS THE WHOLE RISK AND IT GOT SHARPER. `Stalled` IS a `RuntimeError`
    — so a plain `RuntimeError` (a genuine capability gap) and a stall now sit
    on the same branch of the hierarchy, one a subclass of the other, and only
    handler ORDER separates them. A reader checking the source alone would have
    to take that on trust; this runs it, including the RuntimeError case that
    must still reach the capability arm.
    """
    def dispatch(e):
        try:
            raise e
        except _pr.Stalled:
            return "stall"
        except Exception:
            return "capability"

    assert dispatch(exc) == expected


def test_the_stall_exception_carries_what_the_supervisor_SAW():
    """The record reports these; if they were absent the disclosure would name
    no observation and a reader could not tell a stall from an assertion."""
    exc = _pr.Stalled(["fault"], looks=12, poll_s=30.0, elapsed_s=361.0,
                      signals={"output": True, "cpu": True, "io": False})
    assert exc.looks == 12
    assert exc.elapsed_s == 361.0
    assert exc.signals == {"output": True, "cpu": True, "io": False}
    # DEGRADE LOUDLY: the message names which signals were readable, so a stall
    # observed with a degraded probe set is tellable from a full one.
    assert "cpu,output" in str(exc), str(exc)   # the primitive sorts them


# ── the unscaled budget is disclosed as remaining, not silently accepted ─────
def test_the_other_half_of_581_is_now_CLOSED_and_the_code_says_how():
    """This test is the successor of `test_the_constant_budget_is_still_there
    _and_is_acknowledged`, which asserted the deferral rather than the fix.

    #581 deferred the second half in these words: *"scaling it needs a measured
    cells-per-second, and inventing a formula would replace a wrong constant
    with an unmeasured one."* That reasoning is correct and its conclusion is
    that the constant should not be SCALED but REMOVED — a budget a correct run
    can exhaust is a wrong answer at every value.

    The predecessor's own instruction was to REPLACE it rather than delete it if
    the constant ever went away, and this is that replacement: it asserts the
    constant is gone AND that the arm records why, so the closure is as visible
    as the deferral was.
    """
    # NOT A GREP FOR THE STRING. `_run(cmd, timeout=1800)` is still in this
    # file and is CORRECT: `_run` reads its argument as an IDLE TOLERANCE, so
    # 1800 there means "killed only if NOTHING moved for 30 minutes" -- the
    # mechanism this lane installs, not the one it removes. Written as a grep
    # first, and it failed on exactly that line: the claim is about the ATPG
    # DISPATCH, so it is asserted there.
    src = PROG.read_text(encoding="utf-8")
    for anchor in ("r = _pr.run(cmd, capture_output=True, text=True)",
                   "_tdf_p = _pr.run(tdf_cmd, capture_output=True, text=True)"):
        assert anchor in src, (
            f"the ATPG dispatch is no longer {anchor!r} — either it moved back "
            f"onto a clock or this anchor is stale; both need a reader")
    arm = _atpg_except_block().split("except Exception as exc:", 1)[0]
    assert re.search(r"size-independent constant", arm), (
        "the arm no longer quotes the deferral it closes, so a reader cannot "
        "tell this from a constant that was simply dropped")
    assert re.search(r"should not be\s+# SCALED, it should be GONE", arm) \
        or re.search(r"should\s*# not be SCALED", arm) \
        or "it should be GONE" in arm, (
        "the reason the constant was removed rather than scaled is not recorded")
