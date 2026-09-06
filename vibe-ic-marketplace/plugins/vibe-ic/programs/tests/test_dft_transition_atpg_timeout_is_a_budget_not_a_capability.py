"""DT1 (#581, extended to the AT-SPEED path) — a transition-ATPG timeout was
bookkept against a capability the engine HAS.

#581 split the STUCK-AT dispatch's wall-clock expiry out of its blanket
`except Exception` so a timeout records `budget_exceeded` instead of
`capability_flag: cap:atpg_signoff_coverage`. The TRANSITION / at-speed
dispatch in the SAME function (`step_dft_lec_chain`, the DT1 producer call)
was left with only `except Exception`, so a wall-clock expiry there still
lands in `_TDF_CAP` and is recorded as

    {"verdict": "SKIPPED-CONDITION",
     "reason": "transition ATPG execution error: Command '[...]' timed out ...",
     "capability_flag": "cap:at_speed_timing_graded_atpg",
     "not_run_stage": "producer_execution_error"}

The flag asserts the ENGINE cannot do at-speed TDF ATPG. MEASURED on
opentitan_aes x sky130A (fault 0.9.4, vibeic/yosys `sat`): the LOC miter
builds and the SAT solver returns real per-fault STR/STF verdicts
(cal_run.log: "VIBEICTDF _42764__A2 STR", 617 620 cells imported, model
FOUND). The engine ran fine — ~57 s of kissat per fault x --max-faults 400 on
a 2922-flop flattened AES simply cannot finish in the wall budget. The remedy
is "raise the budget / lower --max-faults", which the capability flag hides.

This pins the CLASSIFICATION of the transition arm, exactly as #581 pinned it
for stuck-at. The budget itself is still a size-independent constant (the other
half of #581) and is deliberately not scaled here.
"""
from __future__ import annotations

import pathlib
import subprocess  # noqa: F401
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "design_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))
import _progress_run as _pr  # noqa: E402


def _transition_dispatch() -> str:
    """The transition/at-speed ATPG subprocess dispatch — from where the
    producer command is assembled to the end of its handler chain (the next
    step's banner). This isolates the DT1 arm from the stuck-at arm above."""
    src = PROG.read_text(encoding="utf-8")
    i = src.index("tdf_cmd = [sys.executable,")
    j = src.index("# ================= Step 12", i)
    return src[i:j]


def _transition_timeout_arm() -> str:
    # CZT-10 — the arm is now `except _pr.Stalled`. The outer wall this file
    # was written about is GONE (see
    # `test_tdf_atpg_outer_wall_covers_producer.py` for the measurement that
    # removing it does not move the producer's fault sample), so
    # `subprocess.TimeoutExpired` can no longer be raised here at all. What this
    # file still pins is the CLASSIFICATION, on the mechanism that replaced it.
    block = _transition_dispatch()
    t = block.index("except _pr.Stalled as exc:")
    e = block.index("except Exception as exc:", t)
    return block[t:e]


# ── the classification ───────────────────────────────────────────────────────
def test_transition_timeout_handled_before_the_blanket_except():
    """Order is the whole fix: `except Exception` first would swallow the
    TimeoutExpired (it is an Exception subclass) and re-apply the capability
    flag."""
    block = _transition_dispatch()
    t = block.index("except _pr.Stalled as exc:")
    e = block.index("except Exception as exc:", t)
    assert t < e, "the blanket handler precedes the transition stall handler"


def test_transition_timeout_record_carries_no_capability_flag():
    """A budget expiry must not share a field with `capability_flag`.

    COMMENTS STRIPPED before the scan: the arm's own comment NAMES the flag to
    explain why it withholds it, and the disclosure prose says "not a capability
    gap". A scan that cannot tell documentation from code would fire on those.
    """
    arm = _transition_timeout_arm()
    code = "\n".join(ln for ln in arm.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "capability_flag" not in code, (
        "the transition timeout arm still RECORDS a capability flag — a reader "
        "cannot tell 'raise the budget' from 'the tool cannot do this'")
    assert "_TDF_CAP" not in code, (
        "the timeout arm reuses _TDF_CAP, which carries "
        "capability_flag: cap:at_speed_timing_graded_atpg")
    assert "capability" in arm, (
        "the arm no longer explains why it withholds the flag; the next reader "
        "adds it back as an obvious omission")


def test_transition_record_names_what_it_OBSERVED_now_that_there_is_no_limit():
    """The predecessor asked for `budget_exceeded` / `wall_budget_s`: the limit
    that was hit. There is no limit any more, so naming one would be a lie. The
    actionable facts are what the supervisor watched and for how long it saw
    nothing move -- same purpose, honest content."""
    arm = _transition_timeout_arm()
    for field in ("stopped_as", "stall_looks", "stall_elapsed_s",
                  "stall_signals"):
        assert field in arm, field
    code = "\n".join(ln for ln in arm.splitlines()
                      if not ln.lstrip().startswith("#"))
    assert "budget_exceeded" not in code
    assert "wall_budget_s" not in code


def test_transition_non_timeout_error_still_records_the_capability_flag():
    """The accept case: a crash / missing binary IS a capability gap and keeps
    the flag on the blanket arm. This is a split, not a deletion."""
    block = _transition_dispatch()
    blanket = block.split("except Exception as exc:", 1)[1]
    assert "_TDF_CAP" in blanket, (
        "the genuine capability-gap path lost its _TDF_CAP flag")


# ── the dispatch actually separates them, executed rather than read ──────────
@pytest.mark.parametrize("exc,expected", [
    (_pr.Stalled(["transition_fault_atpg_run"], looks=12, poll_s=30.0,
                 elapsed_s=361.0,
                 signals={"output": True, "cpu": True, "io": True}), "stall"),
    (RuntimeError("producer crashed"), "capability"),
    (FileNotFoundError("no python"), "capability"),
    (OSError("container gone"), "capability"),
])
def test_python_dispatches_the_two_transition_arms_as_written(exc, expected):
    """THE MRO GOT SHARPER, NOT SAFER. `_progress_run.Stalled` IS a
    `RuntimeError`, so a genuine capability gap (a crashed producer, raising
    RuntimeError) and a stall now sit on the same branch of the hierarchy, one
    a subclass of the other, and ONLY handler order separates them. Run it."""
    def dispatch(e):
        try:
            raise e
        except _pr.Stalled:
            return "stall"
        except Exception:
            return "capability"

    assert dispatch(exc) == expected


def test_transition_records_the_same_required_output_path():
    """The budget record must still name the artefact DT1's gate reads, so the
    step reaches BLOCKED-with-reason and does not silently vanish."""
    arm = _transition_timeout_arm()
    assert "reports/phase2/dft/transition_coverage.json" in arm
