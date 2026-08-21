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
import subprocess

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "design_one_shot_runner.py"


def _atpg_except_block() -> str:
    """The handler chain guarding the stuck-at ATPG subprocess call."""
    src = PROG.read_text(encoding="utf-8")
    i = src.index("except subprocess.TimeoutExpired as exc:")
    j = src.index("# ============ Step DT1", i)
    return src[i:j]


# ── the classification ───────────────────────────────────────────────────────
def test_a_timeout_is_handled_before_the_blanket_except():
    """Order is the whole fix: `except Exception` first would swallow it."""
    src = PROG.read_text(encoding="utf-8")
    t = src.index("except subprocess.TimeoutExpired as exc:")
    e = src.index("except Exception as exc:", t)
    assert t < e, "the blanket handler precedes the timeout handler"


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


def test_the_timeout_record_names_the_budget_it_blew():
    """A skip that does not say what limit it hit is not actionable."""
    timeout_arm = _atpg_except_block().split("except Exception as exc:", 1)[0]
    assert "budget_exceeded" in timeout_arm
    assert "wall_budget_s" in timeout_arm


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
    (subprocess.TimeoutExpired(cmd=["fault"], timeout=1800), "budget"),
    (RuntimeError("missing cell model"), "capability"),
    (FileNotFoundError("no such tool"), "capability"),
    (OSError("container gone"), "capability"),
])
def test_python_dispatches_the_two_arms_as_written(exc, expected):
    """Mirrors the handler chain and RUNS it.

    `subprocess.TimeoutExpired` subclasses `SubprocessError`, not `OSError`, and
    a reader checking the source alone would have to take the MRO on trust.
    """
    def dispatch(e):
        try:
            raise e
        except subprocess.TimeoutExpired:
            return "budget"
        except Exception:
            return "capability"

    assert dispatch(exc) == expected


def test_the_timeout_exception_carries_the_budget_value():
    """`exc.timeout` is what the record reports; if it were absent the message
    would name no number and the disclosure would be empty."""
    exc = subprocess.TimeoutExpired(cmd=["fault"], timeout=1800)
    assert getattr(exc, "timeout", None) == 1800


# ── the unscaled budget is disclosed as remaining, not silently accepted ─────
def test_the_constant_budget_is_still_there_and_is_acknowledged():
    """The other half of #581 is NOT fixed, and the code says so.

    Without this, a later reader sees a timeout arm that looks complete and has
    no way to know the budget itself was left as a size-independent constant on
    purpose. An unstated deferral is indistinguishable from an oversight.
    """
    src = PROG.read_text(encoding="utf-8")
    assert "timeout=1800" in src, (
        "the constant is gone — if it was scaled, this test should be replaced "
        "by one that measures the scaling, not deleted")
    timeout_arm = _atpg_except_block().split("except Exception as exc:", 1)[0]
    assert re.search(r"size-independent constant", timeout_arm), (
        "the deferral of the budget-scaling half is no longer recorded beside "
        "the code that works around it")
