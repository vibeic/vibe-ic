#!/usr/bin/env python3
"""vibe-ic#914 — the auto-loosen ladder terminated on a RUNG COUNT.

`_route_feedback_loosen_ex` stopped at `loosen_idx + 1 >= len(ladder)` and
reported `loosen_ladder_exhausted`. Two opposite situations arrived at that one
word:

    the design stopped responding to a looser die   — nothing left to try
    the design was still responding and the ladder  — the remedy was NOT
      ran out of AUTHORED rungs                       exhausted

The verdict (`ROUTE_NOT_CONVERGED`) is correct either way — at the die it
stopped on, the route really had not converged. What was wrong is that a
recoverable design got a terminal-sounding verdict whose remedy text told the
operator to enlarge the die by hand: the exact thing the ladder had been doing
automatically and abandoned. `stalled` and `exhausted` mean opposite things to
whoever reads the log next.

THE FILED RUN'S OWN NUMBERS, and what they actually say. `resize_history`
records `final_violations` 5 then 2, and the gate message records 3 remaining
at the die it stopped on — so the residual series across rungs is

    5 -> 2 -> 3

i.e. one real gain and then a rung that came back WORSE, not a monotone
improvement. That is why the stall criterion here is (a) measured against the
BEST residual so far, not the previous rung, and (b) patient: two consecutive
non-improving rungs, not one. A residual count is a PROXY for routability and
it is noisy across a die change — the same netlist that went 2 -> 3 at
587x587 routed to 0 at 900x900. Terminating on the first wobble would read
noise as a verdict.

chip-AGNOSTIC: violation-count arithmetic and OpenROAD log grammar only. No
design, PDK or part number appears in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


def _log(*counts: int) -> str:
    """An OpenROAD detailed-route log whose per-iteration violation counts are
    `counts`. A PLATEAU at the tail is what makes the run a loosen candidate;
    a strictly-decreasing tail is a router-iteration knob, not a die knob."""
    return "".join(f"[INFO DRT-0199] Number of violations = {c}.\n"
                   for c in counts)


def _plateau_at(final: int) -> str:
    """A completed route that finished at `final` violations and was NOT still
    improving inside its own run — the only shape the ladder ever acts on."""
    return _log(final + 10, final, final)


def _ex(**kw):
    base = dict(die_w=200, die_h=200, log_text="", loosen_idx=0,
                auto_die_requested=True, route_completed=True)
    base.update(kw)
    return p3._route_feedback_loosen_ex(**base)


# ── 1. the stall arithmetic, on its own ────────────────────────────────────

def test_914_streak_is_zero_while_the_series_keeps_setting_a_new_best():
    assert p3._loosen_stall_streak(()) == 0
    assert p3._loosen_stall_streak((5,)) == 0
    assert p3._loosen_stall_streak((5, 2)) == 0
    assert p3._loosen_stall_streak((5, 2, 1)) == 0


def test_914_the_filed_run_series_is_one_wobble_not_a_stall():
    """5 -> 2 -> 3: the last rung failed to beat the best (2), but exactly
    once. One is a wobble; the ladder must not call it finished."""
    assert p3._loosen_stall_streak((5, 2, 3)) == 1
    assert p3._loosen_stall_streak((5, 2, 3)) < p3._ROUTE_LOOSEN_STALL_PATIENCE


def test_914_two_consecutive_non_improving_rungs_is_a_stall():
    assert p3._loosen_stall_streak((5, 2, 3, 3)) == 2
    assert p3._loosen_stall_streak((5, 5, 5)) == 2
    assert (p3._loosen_stall_streak((5, 2, 3, 4))
            >= p3._ROUTE_LOOSEN_STALL_PATIENCE)


def test_914_improvement_is_measured_against_the_best_not_the_previous_rung():
    """`5 -> 2 -> 3 -> 2` did not improve on the best (2) either — measuring
    against the PREVIOUS rung would score that last rung as progress and let
    the ladder run forever on a sawtooth."""
    assert p3._loosen_stall_streak((5, 2, 3, 2)) == 2


# ── 2. the four terminators, each naming the bound that fired ──────────────

def test_914_a_stalled_ladder_says_stalled_not_exhausted():
    """THE MUTATION TEST. Same call shape, opposite word: a ladder whose
    residual has stopped improving reports a STALL, which origin/main has no
    way to say — it only ever counted rungs."""
    # 5 -> 2 -> 3 -> 3: one rung came back worse than the best, the next beat
    # nothing either. That is the stall; the single wobble before it was not.
    decision, reason = _ex(loosen_idx=2, log_text=_plateau_at(3),
                           residual_history=(5, 2, 3))
    assert decision is None
    assert reason == "loosen_ladder_stalled"
    assert reason != "loosen_ladder_exhausted"
    # and the wobble ALONE (5 -> 2 -> 3, the filed run's own series) does not
    # stop the ladder — it proposes another rung.
    _d, _r = _ex(die_w=600, die_h=600, loosen_idx=2,
                 log_text=_plateau_at(3), residual_history=(5, 2))
    assert _r == "loosened", _r


def test_914_a_still_improving_ladder_is_not_stopped_by_the_authored_length():
    """THE OTHER HALF OF THE MUTATION. At the AUTHORED ladder's last rung with
    a residual that is still improving, origin/main returns
    `loosen_ladder_exhausted` and stops; the ladder must now propose a strictly
    looser rung instead."""
    last = len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1
    decision, reason = _ex(die_w=600, die_h=600, loosen_idx=last,
                           log_text=_plateau_at(2), residual_history=(5,))
    assert reason == "loosened", reason
    assert decision is not None
    new_w, new_h, record = decision
    assert new_w > 600 and new_h > 600                # strictly looser
    assert record["to_target_util"] < record["from_target_util"]
    assert record["beyond_authored_ladder"] is True
    assert record["residual_series"] == [5, 2]
    assert record["stall_streak"] == 0


def test_914_the_hard_rung_bound_reports_itself_and_is_not_the_stall_word():
    """A bound firing on a design that is STILL improving must be
    distinguishable from a ladder that ran out of things to try."""
    decision, reason = _ex(die_w=600, die_h=600,
                           loosen_idx=p3._ROUTE_LOOSEN_MAX_RUNGS - 1,
                           log_text=_plateau_at(2), residual_history=(5,))
    assert decision is None
    assert reason == "loosen_rung_budget_reached"
    assert reason not in ("loosen_ladder_stalled", "loosen_ladder_exhausted")


def test_914_the_die_cap_still_reports_itself(monkeypatch):
    """The geometric bound is unchanged and keeps its own name."""
    decision, reason = _ex(die_w=p3._DEFAULT_DIE_MAX_UM,
                           die_h=p3._DEFAULT_DIE_MAX_UM,
                           loosen_idx=0, log_text=_plateau_at(9))
    assert decision is None
    assert reason == "die_cap_reached"


def test_914_no_improvement_evidence_at_the_authored_end_is_still_exhausted():
    """Continuing past the authored ladder requires POSITIVE evidence. With no
    measured rungs there is none, so the historical word — and the historical
    behaviour — stand. This is what keeps #307's decline-naming test true."""
    last = len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1
    decision, reason = _ex(loosen_idx=last, log_text="")
    assert decision is None
    assert reason == "loosen_ladder_exhausted"


def test_914_every_terminator_is_a_distinct_word():
    """Four bounds, four names. Collapsing any two of them back into one word
    is the defect, not a tidy-up."""
    seen = {
        _ex(loosen_idx=2, log_text=_plateau_at(3),
            residual_history=(5, 2, 3))[1],
        _ex(loosen_idx=len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1,
            log_text="")[1],
        _ex(die_w=600, die_h=600,
            loosen_idx=p3._ROUTE_LOOSEN_MAX_RUNGS - 1,
            log_text=_plateau_at(2), residual_history=(5,))[1],
        _ex(die_w=p3._DEFAULT_DIE_MAX_UM, die_h=p3._DEFAULT_DIE_MAX_UM,
            log_text=_plateau_at(9))[1],
    }
    assert seen == {"loosen_ladder_stalled", "loosen_ladder_exhausted",
                    "loosen_rung_budget_reached", "die_cap_reached"}


# ── 3. the continuation ladder itself ──────────────────────────────────────

def test_914_authored_rungs_are_byte_identical():
    lad = p3._ROUTE_LOOSEN_UTIL_LADDER
    for i, want in enumerate(lad):
        assert p3._loosen_ladder_util(i) == want


def test_914_continuation_rungs_are_strictly_looser_and_bounded():
    lad = p3._ROUTE_LOOSEN_UTIL_LADDER
    utils = [p3._loosen_ladder_util(i)
             for i in range(p3._ROUTE_LOOSEN_MAX_RUNGS + 1)]
    assert all(utils[i] > utils[i + 1] for i in range(len(utils) - 1))
    assert utils[len(lad)] < p3._ROUTE_LOOSEN_UTIL_FLOOR
    # the thing that must not grow without bound is the DIE, and it is bounded
    # by the cap, not by the util floor.
    assert p3._compute_loosened_die(
        p3._DEFAULT_DIE_MAX_UM, p3._DEFAULT_DIE_MAX_UM,
        utils[len(lad)], utils[len(lad) + 1]) is None


def test_914_the_stall_can_never_stop_a_ladder_EARLIER_than_before():
    """THE BLAST-RADIUS FLOOR, as an invariant rather than a promise.

    A stall needs `patience` consecutive non-improving rungs, which needs
    `patience + 1` measured residuals, which is only reached at
    `loosen_idx >= patience`. So as long as the patience is at least the number
    of loosen steps the AUTHORED ladder ever had, the stall criterion cannot
    fire before the rung count already did — every run either stops exactly
    where it used to (with a truer word for why) or runs longer. Lower the
    patience below this and the change stops being monotone.
    """
    authored_loosen_steps = len(p3._ROUTE_LOOSEN_UTIL_LADDER) - 1
    assert p3._ROUTE_LOOSEN_STALL_PATIENCE >= authored_loosen_steps
    # the arithmetic the invariant rests on
    for n in range(1, p3._ROUTE_LOOSEN_STALL_PATIENCE + 1):
        flat = tuple([7] * n)
        assert p3._loosen_stall_streak(flat) < p3._ROUTE_LOOSEN_STALL_PATIENCE


def test_914_the_loop_budget_covers_the_rung_bound():
    """If the loop guard ran out before the rung bound, a rung count would be
    deciding the outcome again — one level up, where nothing reports it."""
    assert (p3._PNR_RETRY_ITERS
            >= 1 + p3._PNR_UPSIZE_RETRIES + 1 + p3._ROUTE_LOOSEN_MAX_RUNGS)


# ── 4. nothing that used to loosen stops loosening ─────────────────────────

def test_914_the_first_rung_is_unchanged_with_no_history():
    """A run reaching the ladder for the first time has no across-rung series
    at all, so nothing about the stall criterion can apply to it. This is the
    common case and it must be untouched."""
    decision, reason = _ex(log_text=_plateau_at(40))
    assert reason == "loosened"
    assert decision is not None
    assert decision[2]["residual_series"] == [40]
    assert decision[2]["stall_streak"] == 0
    assert decision[2]["beyond_authored_ladder"] is False


def test_914_a_converging_route_is_still_never_loosened():
    """§4.05 guard, unchanged: a route still descending toward clean is a
    router-iteration knob, not a die knob."""
    decision, reason = _ex(log_text=_log(880145, 670215),
                           residual_history=(900000,))
    assert decision is None
    assert reason == "route_still_converging"


def test_914_the_explicit_die_and_incomplete_route_guards_are_unchanged():
    assert _ex(auto_die_requested=False)[1] == "explicit_die_requested"
    assert _ex(route_completed=False)[1] == "route_did_not_complete"


def test_914_the_backward_compatible_wrapper_still_returns_a_bare_optional():
    assert p3._route_feedback_loosen(200, 200, "", 0, False, True) is None
