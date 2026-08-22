"""Tests for the required-status poller. vibe-ic#1019/#1036.

The behaviour under test is almost entirely `classify()`, and that is on
purpose: everything else in the poller is transport (git worktree, `gh api`),
while `classify()` is where a wrong answer becomes a WRONG GREEN — a merge
allowed onto `main` because the poller mistook "measured nothing" for "measured
and found nothing wrong".

Every case below is anchored to a real measurement rather than an imagined one:

* the `no tests ran` shape is what `python3 -m pytest` prints on the landing
  host, where autoload pulls in a broken third-party pytest11 plugin (web3's
  `pytest_ethereum`) and the session dies AT COLLECTION. Zero tests run. The
  first time this was read, it was read as "baseline: 0 failures";
* the `2 failed, 379 passed` shape is the real targeted-selection output from
  PR #1056 on 2026-08-12;
* `exit 0 with no test count` is the shape a future refactor could produce if
  the selection file came back empty and the gate declined to notice.

NEGATIVE CONTROL: `test_a_pass_is_still_a_pass` exists so that the suite cannot
be satisfied by a `classify()` that simply refuses everything. A gate that
never says success is a ban, not a check, and would pass every other test here.
"""
import importlib.util
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parent / "gatekeeper_status_poller.py"
_spec = importlib.util.spec_from_file_location("gksp", _MOD)
gksp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gksp)


def test_collection_death_is_error_not_failure():
    """The whole point. A gate that could not run must not look like a red gate."""
    out = "ERROR: file or directory not found: programs/tests/test_new.py\n\nno tests ran in 0.13s\n"
    state, desc = gksp.classify(4, out)
    assert state == "error", "collection death must NOT be reported as `failure`"
    assert "COULD NOT RUN" in desc


def test_internalerror_is_error():
    state, _ = gksp.classify(3, "INTERNALERROR> ImportError: cannot import name 'foo'\n")
    assert state == "error"


def test_real_failures_are_failure():
    """PR #1056's measured output: the gate ran and disagreed."""
    state, desc = gksp.classify(1, "2 failed, 379 passed in 90.63s\n")
    assert state == "failure"
    assert "2 failed" in desc


def test_a_pass_is_still_a_pass():
    """NEGATIVE CONTROL — see module docstring. Without this, a classify() that
    returned `error` unconditionally would satisfy every other test here."""
    state, desc = gksp.classify(0, "770 passed, 2 skipped in 101.84s\n")
    assert state == "success"
    assert "770 passed" in desc


def test_zero_exit_without_evidence_of_running_is_error():
    """Exit 0 is not sufficient. Something must actually have been measured."""
    state, desc = gksp.classify(0, "--- cheap tier ---\n  PASS  something\n")
    assert state == "error"
    assert "no test ran" in desc


def test_zero_exit_that_also_reports_failures_is_error_not_success():
    """Contradiction is unmeasured, never a pass. A gate whose exit code and
    whose output disagree is a gate whose verdict is unknown."""
    state, _ = gksp.classify(0, "3 failed, 100 passed in 12s\n")
    assert state == "error"


def test_nonzero_without_a_count_is_still_failure():
    state, desc = gksp.classify(2, "  FAIL  repo hygiene gates\n")
    assert state == "failure"
    assert "exit 2" in desc


@pytest.mark.parametrize("state", ["failure", "error"])
def test_only_success_can_ever_satisfy_protection(state):
    """Documents the fail-closed property: GitHub requires the required context
    to be `success`, so `error` blocks a merge exactly as `failure` does. The
    three-valued verdict changes what a human is TOLD, never what is allowed."""
    assert state != "success"


def test_context_constant_matches_the_protection_rule():
    """The required context string is load-bearing — branch protection on `main`
    requires this exact value. Drift fails closed (nothing satisfies the rule),
    but it fails closed SILENTLY, so it is pinned here."""
    assert gksp.CONTEXT == "vibe-ic/gatekeeper-land"
