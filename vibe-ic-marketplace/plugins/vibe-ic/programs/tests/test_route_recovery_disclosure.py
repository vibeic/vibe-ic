"""ROUTE-RECOVERY DISCLOSURE — a non-converged route must SAY whether any
automated congestion remedy actually ran (chip/PDK-AGNOSTIC).

PROVE-FIRST floor (measured against the shipped v1.5.78 runner, 2026-07-25,
edge-LLM GEMM convergence campaign):

  * `_route_feedback_loosen` returns None for SIX distinct reasons and the
    call site cannot tell them apart. Probing the SHIPPED function directly:

        _drt_is_non_converging([409554,332073,312639,129304,116677]) -> False
        _route_feedback_loosen(2000,2000, <that log>, 0, True, True) -> None
        _route_feedback_loosen(2000,2000, <plateau log>, 0, True, True) -> None

    Both a still-improving route AND a genuine plateau produced the SAME
    `None`, i.e. "no remedy", for two completely different reasons.

  * `_DEFAULT_DIE_MAX_UM` is a hardcoded 2000 with no CLI/env override, and
    `_compute_loosened_die` refuses any growth past it. Measured on the
    shipped function, a clear plateau signal yields:

        die  800x800  -> grow to  943x943
        die 1200x1200 -> grow to 1415x1415
        die 1600x1600 -> grow to 1886x1886
        die 1900x1900 -> NO RECOVERY
        die 2000x2000 -> NO RECOVERY
        die 2400x2400 -> NO RECOVERY

    So EVERY design whose die is at/near the cap silently gets zero
    congestion recovery — while the ROUTE_NOT_CONVERGED FAIL still tells the
    operator to "increase --die-um ... or raise the router's end iteration",
    as though the automation had nothing to report.

  * The second dead end is the router BUDGET case: when the trajectory tail
    is still strictly decreasing, `_drt_is_non_converging` correctly declines
    to resize (the die is not the problem) and its docstring names the right
    knob as "router end-iteration" — but the main `detailed_route` call emits
    no `-droute_end_iter` and no flag exposes it. The named remedy does not
    exist, and nothing said so.

Fix under test: `_route_recovery_disclosure` — a PURE classifier that names
which remedy was available and, when none was, exactly why. It mutates
nothing, never converts a FAIL into a PASS, and is recorded on
`resize_history` so it reaches the step extras and the FAIL text.

These tests pin the classifier's decisions AND guard that the disclosure is
inert with respect to flow control (`_route_feedback_loosen` must keep
returning byte-identical decisions).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import phase3_one_shot_runner as p3


def _log(traj):
    """Synthesize an OpenROAD detailed-route log carrying a trajectory."""
    return "".join(
        f"[INFO DRT-0199] Number of violations = {v}\n" for v in traj)


# Trajectory shapes, all synthetic and chip-agnostic.
TRAJ_DECREASING = [409554, 332073, 312639, 129304, 116677]
TRAJ_PLATEAU = [409554, 332073, 312639, 129304, 129304]
TRAJ_CLIMB = [409554, 332073, 312639, 129304, 131000]
TRAJ_CONVERGED = [409554, 332073, 1200, 0]


# ---------------------------------------------------------------------------
# The two silent dead ends — the whole point of the fix.
# ---------------------------------------------------------------------------
def test_router_budget_dead_end_is_disclosed():
    """Tail still FALLING => not a geometry problem; the die ladder correctly
    does not fire, and the named remedy (router end-iteration) is absent."""
    rec = p3._route_recovery_disclosure(
        1200, 1200, _log(TRAJ_DECREASING), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_ROUTER_BUDGET
    d = rec["disclosure"]
    assert "FALLING" in d
    assert "droute_end_iter" in d
    assert "NO automated remedy" in d
    # The measured tail must be quoted so the claim is checkable.
    assert "129304" in d and "116677" in d
    # And the loosen path must indeed have declined.
    assert p3._route_feedback_loosen(
        1200, 1200, _log(TRAJ_DECREASING), 0, True, True) is None


def test_die_cap_dead_end_is_disclosed():
    """Genuine plateau at/above the cap => the ONLY remedy is refused,
    silently in the shipped code. The disclosure must name the cap and the
    shortfall."""
    rec = p3._route_recovery_disclosure(
        2000, 2000, _log(TRAJ_PLATEAU), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_DIE_CAP
    assert rec["die_max_um"] == p3._DEFAULT_DIE_MAX_UM
    # ceil-rounded exactly as _compute_loosened_die does it:
    # 2000 * sqrt(0.25/0.18) = 2357.02 -> 2358
    assert rec["would_need_die_um"] == "2358x2358"
    d = rec["disclosure"]
    assert "REFUSED" in d
    assert str(p3._DEFAULT_DIE_MAX_UM) in d
    assert "NO automated remedy ran" in d
    assert p3._route_feedback_loosen(
        2000, 2000, _log(TRAJ_PLATEAU), 0, True, True) is None


@pytest.mark.parametrize("side", [1900, 2000, 2400, 5000])
def test_every_die_at_or_above_cap_gets_no_recovery(side):
    """The cap makes recovery unavailable for ALL large dies, not just one."""
    rec = p3._route_recovery_disclosure(
        side, side, _log(TRAJ_PLATEAU), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_DIE_CAP
    assert p3._route_feedback_loosen(
        side, side, _log(TRAJ_PLATEAU), 0, True, True) is None


# ---------------------------------------------------------------------------
# The cases where the existing machinery IS doing the right thing.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("side", [800, 1200, 1600])
def test_small_die_plateau_still_reports_remedy_available(side):
    rec = p3._route_recovery_disclosure(
        side, side, _log(TRAJ_PLATEAU), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_AVAILABLE
    assert p3._route_feedback_loosen(
        side, side, _log(TRAJ_PLATEAU), 0, True, True) is not None


def test_climbing_tail_is_a_plateau_class_signal():
    rec = p3._route_recovery_disclosure(
        1200, 1200, _log(TRAJ_CLIMB), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_AVAILABLE


def test_converged_route_needs_no_remedy():
    rec = p3._route_recovery_disclosure(
        2000, 2000, _log(TRAJ_CONVERGED), 0, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_CONVERGED
    assert rec["final_violations"] == 0


def test_explicit_die_is_an_exemption_not_a_dead_end():
    rec = p3._route_recovery_disclosure(
        2000, 2000, _log(TRAJ_PLATEAU), 0, False, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_EXPLICIT_DIE
    assert "--die-um" in rec["disclosure"]


def test_incomplete_route_is_reported_as_such():
    rec = p3._route_recovery_disclosure(
        1200, 1200, _log(TRAJ_PLATEAU), 0, True, False)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_INCOMPLETE


def test_ladder_exhaustion_is_reported_as_such():
    last = len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1
    rec = p3._route_recovery_disclosure(
        1200, 1200, _log(TRAJ_PLATEAU), last, True, True)
    assert rec["remedy"] == p3._ROUTE_RECOVERY_LADDER_DONE


# ---------------------------------------------------------------------------
# REGRESSION GUARD — the disclosure must not change flow control.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("traj", [TRAJ_DECREASING, TRAJ_PLATEAU,
                                  TRAJ_CLIMB, TRAJ_CONVERGED])
@pytest.mark.parametrize("side", [800, 1200, 1600, 1900, 2000, 2400])
@pytest.mark.parametrize("auto,done", [(True, True), (True, False),
                                       (False, True), (False, False)])
def test_loosen_decision_is_unchanged_by_the_disclosure(traj, side, auto, done):
    """`_route_feedback_loosen` is the ONLY function that moves geometry.
    Calling the classifier must never perturb it, and the classifier's own
    verdict must agree with it on whether a remedy exists."""
    lg = _log(traj)
    before = p3._route_feedback_loosen(side, side, lg, 0, auto, done)
    rec = p3._route_recovery_disclosure(side, side, lg, 0, auto, done)
    after = p3._route_feedback_loosen(side, side, lg, 0, auto, done)
    assert before == after, "classifier perturbed the loosen decision"
    if rec["remedy"] == p3._ROUTE_RECOVERY_AVAILABLE:
        assert after is not None
    else:
        assert after is None


def test_disclosure_never_yields_a_pass_or_waiver_token():
    """A disclosure explains; it must never read as an excuse. No verdict
    vocabulary that a downstream reader could mistake for absolution."""
    banned = re.compile(r"\b(pass|waiv\w*|accept\w*|floor|ok|clean|benign)\b",
                        re.IGNORECASE)
    for traj in (TRAJ_DECREASING, TRAJ_PLATEAU, TRAJ_CLIMB):
        for side in (1200, 2000, 2400):
            for auto in (True, False):
                rec = p3._route_recovery_disclosure(
                    side, side, _log(traj), 0, auto, True)
                hit = banned.search(rec["disclosure"])
                assert hit is None, (
                    f"disclosure carries verdict vocabulary "
                    f"{hit.group(0)!r}: {rec['disclosure']}")


def test_classifier_is_pure():
    """No file IO, no mutation of inputs, deterministic across calls."""
    lg = _log(TRAJ_PLATEAU)
    a = p3._route_recovery_disclosure(2000, 2000, lg, 0, True, True)
    b = p3._route_recovery_disclosure(2000, 2000, lg, 0, True, True)
    assert a == b
    assert lg == _log(TRAJ_PLATEAU), "input log text was mutated"


def test_no_trajectory_at_all_is_not_a_converged_claim():
    """An empty log must never be read as 'converged' — that would be a
    vacuous pass (the classic false-clean)."""
    rec = p3._route_recovery_disclosure(2000, 2000, "", 0, True, True)
    assert rec["remedy"] != p3._ROUTE_RECOVERY_CONVERGED
    assert rec["final_violations"] is None


# ---------------------------------------------------------------------------
# chip-AGNOSTIC guard on the new code itself.
# ---------------------------------------------------------------------------
def test_new_code_is_chip_agnostic():
    """The classifier must not name a vendor, SKU, PDK or design."""
    src = Path(p3.__file__).read_text()
    start = src.index("def _route_recovery_disclosure")
    end = src.index("def _route_feedback_loosen")
    body = src[start:end]
    banned = re.compile(
        r"\b(sky130\w*|gf180\w*|nangate\w*|freepdk\w*|asap7|ihp[-_]?sg13\w*|"
        r"skywater|globalfoundries|tsmc|samsung|intel|edge_llm\w*|"
        r"riscv|ibex|sha256|spm)\b", re.IGNORECASE)
    hit = banned.search(body)
    assert hit is None, f"chip-specific literal in new code: {hit.group(0)!r}"
