#!/usr/bin/env python3
"""vibe-ic #914 — the PnR auto-loosen ladder terminated on a RUNG COUNT and
reported that as `loosen_ladder_exhausted` / `proposed_util=None`.

WHAT WAS ACTUALLY MEASURED (reproduced through the real `step_pnr` before any
fix, with the fake-docker harness this file reuses):

    status   : FAIL
    finding  : ROUTE_NOT_CONVERGED
    detail   : ...congestion-limited at die 138x138um / util 0.3...
    calls    : 3            dies routed: [(95,95), (112,112), (138,138)]
    decline  : reason=loosen_ladder_exhausted loosen_idx=2 proposed_util=null
               die_max_um=2000

A CORRECTION TO THE ISSUE'S OWN READING, because it changes the fix. The issue
says the ladder terminated "while its violation trend was still strictly
decreasing (5 -> 2)". It was not. `resize_history[i]["final_violations"]` is the
residual of the run being loosened AWAY from, so the two rows carry the 1st and
2nd runs' residuals; the 3rd run's residual lives only in the gate message. The
across-rung series is therefore **5 -> 2 -> 3** — one gain, then a rung that came
back WORSE. A criterion that stopped on the first non-improving rung (what the
issue literally proposes) would have stopped that run in exactly the same place,
just with a different word, and the issue's own controlled re-run at a much
larger die reached 0 violations. So the criterion here is measured against the
BEST residual so far and is PATIENT (two consecutive misses), not against the
previous rung.

The defect that is real: the ladder's decision read NONE of that evidence. It
stopped because an authored list ran out, at a 138um die against a 2000um cap,
and it would have stopped in the identical place for 50 -> 20 -> 8 and for
9 -> 9 -> 9. A bound that cannot tell "more die area buys nothing" from "the
budget ran out" is reported to the operator as the former while being the
latter — and the manual remedy it then prints is the remedy it just abandoned.

TWO ARMS. `TestFixed` must FAIL against the unfixed program; `TestUnchanged` is
the paired guard — it must pass on BOTH sides, so the first arm cannot be
satisfied by breaking behaviour that was already correct. Nothing here
re-implements the ladder rule: every assertion reads a value the program
returned (StepResult.status / .detail / .extras, or a decision tuple).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import textwrap

mod = importlib.import_module("phase3_one_shot_runner")
from test_gap_e2e_die_util_routing_feedback import (  # noqa: E402
    _PG_OK, _R_OVERUTIL, _drive_step_pnr, _loosen_records)


def _nc(final: int):
    """A COMPLETED detailed route that PLATEAUS at `final` violations — the
    shape `_drt_is_non_converging` recognises as a genuine stuck signal."""
    return (0, f"[INFO DRT-0199] Number of violations = {final}.\n"
               f"[INFO DRT-0199] Number of violations = {final}.\n" + _PG_OK,
            "")


_CONV = (0, "[INFO DRT-0199] Number of violations = 0.\n" + _PG_OK, "")
# A plateau log used for the direct decision-function calls below.
_PLATEAU = "\n".join(f"[INFO DRT-0199] Number of violations = 40." for _ in range(3))


def _reasons_the_decision_can_return(fn) -> set:
    """DISCOVER the decline vocabulary from the decision function itself rather
    than re-typing it here — a hand-typed copy of a vocabulary is exactly how a
    7th member goes unnoticed. Walks the AST for `return <x>, "<reason>"`."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            elts = node.value.elts
            if (len(elts) == 2 and isinstance(elts[1], ast.Constant)
                    and isinstance(elts[1].value, str)):
                out.add(elts[1].value)
    return out


# ===========================================================================
# ARM 1 — must FAIL against the unfixed program
# ===========================================================================
class TestFixed:
    def test_914_the_filed_runs_series_reaches_the_rung_that_converges_it(
            self, tmp_path, monkeypatch):
        """THE FILED RUN. Residuals 5 -> 2 -> 3 (not monotone), then a rung that
        clears. The ladder used to stop at rung 2 with the 4th run never made;
        it must now take it, and the four downstream gates that are gated on a
        routed design become reachable."""
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_nc(5), _nc(2), _nc(3), _CONV])
        assert res.status == "PASS", res.detail
        assert calls["n"] == 4
        assert len(_loosen_records(res)) == 3
        sides = [d[0] for d in calls["dies"]]
        assert all(sides[i] < sides[i + 1] for i in range(len(sides) - 1))
        assert max(sides) <= mod._DEFAULT_DIE_MAX_UM

    def test_914_a_ladder_stopped_by_a_bound_says_CUT_SHORT_in_the_verdict(
            self, tmp_path, monkeypatch):
        """A residual that keeps setting new bests never stalls, so the rung
        bound is what fires — and a bound must present itself as a bound. The
        operator reading `ROUTE_NOT_CONVERGED` has to be able to tell that the
        automatic remedy still had somewhere to go."""
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto",
            [_nc(60), _nc(50), _nc(40), _nc(30), _nc(20), _nc(10), _nc(5)])
        x = res.extras or {}
        assert res.status == "FAIL"
        assert x.get("finding") == "ROUTE_NOT_CONVERGED"
        assert x.get("loosen_terminator") == "loosen_rung_budget_reached"
        assert x.get("loosen_terminator_kind") == "bound"
        assert x.get("loosen_was_cut_short") is True
        assert x.get("loosen_still_improving") is True
        assert x.get("loosen_rungs_taken") == mod._ROUTE_LOOSEN_MAX_RUNGS
        assert calls["n"] == mod._ROUTE_LOOSEN_MAX_RUNGS + 1
        assert "CUT SHORT, NOT EXHAUSTED" in res.detail

    def test_914_a_ladder_stopped_by_its_own_measurements_says_STALLED(
            self, tmp_path, monkeypatch):
        """The opposite verdict, and the reason this fix is not just "run more
        rungs": a residual that beats nothing must still stop the ladder, and
        must say the remedy is spent rather than merely budgeted out."""
        res, calls = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_nc(9)])
        x = res.extras or {}
        assert res.status == "FAIL"
        assert x.get("loosen_terminator") == "loosen_ladder_stalled"
        assert x.get("loosen_terminator_kind") == "evidence"
        assert x.get("loosen_was_cut_short") is False
        assert x.get("loosen_residual_series") == [9, 9, 9]
        assert "AUTO-LOOSEN STALLED" in res.detail
        assert "CUT SHORT" not in res.detail

    def test_914_the_decline_carries_the_series_it_was_decided_on(
            self, tmp_path, monkeypatch):
        """`ROUTE_LOOSEN_DECLINED` used to disclose the reason but none of the
        evidence, so a reader could not check the reason against anything."""
        res, _ = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_nc(9)])
        d = (res.extras or {})["loosen_declines"][-1]
        assert d["reason"] == "loosen_ladder_stalled"
        assert d["kind"] == mod._LOOSEN_TERMINATOR_KIND[d["reason"]]
        assert d["residual_series"] == [9, 9, 9]
        assert d["stall_streak"] == mod._ROUTE_LOOSEN_STALL_PATIENCE
        assert d["stall_patience"] == mod._ROUTE_LOOSEN_STALL_PATIENCE
        assert d["still_improving"] is False

    def test_914_proposed_util_stops_reading_None_when_a_proposal_exists(
            self, tmp_path, monkeypatch):
        """`proposed_util=None` said "no proposal exists" when what was true was
        "we chose not to make one" — the field the operator would use to judge
        whether the ladder had anywhere left to go."""
        res, _ = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_nc(9)])
        d = (res.extras or {})["loosen_declines"][-1]
        assert isinstance(d["proposed_util"], float)
        assert 0.0 < d["proposed_util"] < mod._ROUTE_LOOSEN_UTIL_LADDER[-1]

    def test_914_the_verdict_names_the_util_the_geometry_was_targeted_at(
            self, tmp_path, monkeypatch):
        """The message presented the REQUESTED util as "the condition the design
        is limited at" while the ladder had re-targeted the geometry to another
        one. Both numbers are true of different things; only one of them
        describes the die that was routed."""
        res, _ = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_nc(9)])
        x = res.extras or {}
        assert "requested util" in res.detail
        assert f"auto-loosen rung {x['loosen_rungs_taken']} targeted util" \
            in res.detail
        assert x["loosen_target_util"] == mod._ROUTE_LOOSEN_UTIL_LADDER[-1]
        assert x["util"] != x["loosen_target_util"]

    def test_914_the_ladder_continues_at_its_own_authored_ratio(self):
        """Past the authored floor the schedule continues at the ratio the
        AUTHORED ladder itself ends on. Derived from `_ROUTE_LOOSEN_UTIL_LADDER`
        here too — a second hand-typed schedule is a second thing to drift."""
        lad = mod._ROUTE_LOOSEN_UTIL_LADDER
        for i, u in enumerate(lad):
            assert mod._loosen_ladder_util(i) == u
        ratio = lad[-1] / lad[-2]
        assert mod._loosen_ladder_util(len(lad)) == lad[-1] * ratio
        rungs = [mod._loosen_ladder_util(i)
                 for i in range(mod._ROUTE_LOOSEN_MAX_RUNGS + 1)]
        assert all(r is not None and r > 0.0 for r in rungs)
        assert all(rungs[i] > rungs[i + 1] for i in range(len(rungs) - 1))

    def test_914_the_stall_is_measured_against_best_so_far_not_the_last_rung(
            self):
        """LOAD-BEARING. The filed series 5 -> 2 -> 3 must NOT read as a stall:
        the controlled re-run at a larger die reached 0, so a criterion that
        called that a stall would have been wrong about this exact design."""
        assert mod._loosen_stall_streak([5, 2, 3]) == 1
        assert (mod._loosen_stall_streak([5, 2, 3])
                < mod._ROUTE_LOOSEN_STALL_PATIENCE)
        assert mod._loosen_stall_streak([5, 2, 3, 3]) == 2
        assert mod._loosen_stall_streak([50, 20, 8, 3, 1]) == 0
        assert mod._loosen_stall_streak([9, 9, 9]) == 2
        assert mod._loosen_stall_streak([4, 6, 8, 10]) == 3
        assert mod._loosen_stall_streak([7]) == 0

    def test_914_the_shared_loop_guard_cannot_end_the_ladder_first(self):
        """A rung count deciding the outcome ONE LEVEL UP is the same defect
        wearing a different hat: if the shared retry budget were smaller than
        the ladder's own bound, the loop guard — not the criterion — would be
        what stopped it."""
        assert mod._PNR_RETRY_ITERS >= (1 + mod._PNR_UPSIZE_RETRIES + 1
                                        + mod._ROUTE_LOOSEN_MAX_RUNGS)

    def test_914_every_reason_the_decision_can_return_has_a_declared_kind(
            self):
        """DISCOVERED, not enumerated. Whatever set of reasons the decision
        function can actually return must be exactly the set the disclosure map
        classifies — otherwise a future 8th reason reaches an operator with no
        statement of whether it is a bound or a measurement."""
        returned = _reasons_the_decision_can_return(mod._route_feedback_loosen_ex)
        assert "loosened" in returned
        assert returned - {"loosened"} == set(mod._LOOSEN_TERMINATOR_KIND)
        assert set(mod._LOOSEN_TERMINATOR_KIND.values()) <= {
            "not_engaged", "evidence", "bound"}
        # The two facts that must never share a word.
        assert (mod._LOOSEN_TERMINATOR_KIND["loosen_ladder_stalled"]
                != mod._LOOSEN_TERMINATOR_KIND["loosen_rung_budget_reached"])


# ===========================================================================
# ARM 2 — PAIRED GUARD: must pass on BOTH the fixed and the unfixed program.
# These pin the behaviour that must NOT move, so arm 1 cannot be satisfied by
# loosening something that was already right. Every call here uses only the
# API the unfixed program already had.
# ===========================================================================
class TestUnchanged:
    def test_914_guard_a_flat_residual_design_gains_no_rungs(
            self, tmp_path, monkeypatch):
        """The direction of this change is "never FEWER rungs, sometimes more"
        — and for a design whose residual never improves, "sometimes more" must
        be ZERO more. A stall needs `patience` consecutive misses, hence
        `patience + 1` measured residuals, which the old rung count already
        allowed; so the criterion cannot fire earlier OR later here."""
        res, calls = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_nc(45)])
        assert res.status == "FAIL"
        assert (res.extras or {}).get("finding") == "ROUTE_NOT_CONVERGED"
        assert calls["n"] == 3
        assert len(_loosen_records(res)) == 2
        utils = [r["to_target_util"] for r in _loosen_records(res)]
        assert min(utils) >= mod._ROUTE_LOOSEN_UTIL_FLOOR
        assert max(d[0] for d in calls["dies"]) <= mod._DEFAULT_DIE_MAX_UM

    def test_914_guard_a_worsening_residual_design_gains_no_rungs(
            self, tmp_path, monkeypatch):
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_nc(4), _nc(6), _nc(8), _nc(10)])
        assert res.status == "FAIL"
        assert calls["n"] == 3
        assert len(_loosen_records(res)) == 2

    def test_914_guard_an_explicit_die_is_still_never_loosened(
            self, tmp_path, monkeypatch):
        """The caller's pinned geometry is not the ladder's to touch, at any
        rung count and on any evidence."""
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "480x480", [_nc(40)])
        assert res.status == "FAIL"
        assert (res.extras or {}).get("finding") == "ROUTE_NOT_CONVERGED"
        assert calls["n"] == 1
        assert calls["dies"] == [(480, 480)]
        assert _loosen_records(res) == []

    def test_914_guard_a_converged_route_still_takes_no_rung(
            self, tmp_path, monkeypatch):
        res, calls = _drive_step_pnr(tmp_path, monkeypatch, "auto", [_CONV])
        assert res.status == "PASS"
        assert calls["n"] == 1
        assert _loosen_records(res) == []

    def test_914_guard_a_still_decreasing_tail_is_still_a_router_knob(
            self, tmp_path, monkeypatch):
        """A route still improving inside its own iterations is out of ROUTER
        iterations, not out of die area. It must buy no loosening no matter
        what the across-rung series looks like."""
        decr = (0, "[INFO DRT-0199] Number of violations = 50.\n"
                   "[INFO DRT-0199] Number of violations = 12.\n" + _PG_OK, "")
        res, calls = _drive_step_pnr(tmp_path, monkeypatch, "auto", [decr])
        assert res.status == "FAIL"
        assert calls["n"] == 1
        assert _loosen_records(res) == []

    def test_914_guard_the_die_cap_still_refuses_and_still_names_itself(self):
        near_cap = mod._DEFAULT_DIE_MAX_UM - 5
        d, r = mod._route_feedback_loosen_ex(
            near_cap, near_cap, _PLATEAU,
            len(mod._ROUTE_LOOSEN_UTIL_LADDER) - 2, True, True)
        assert d is None and r == "die_cap_reached"

    def test_914_guard_a_route_that_did_not_complete_buys_no_loosening(self):
        d, r = mod._route_feedback_loosen_ex(200, 200, _PLATEAU, 0, True, False)
        assert d is None and r == "route_did_not_complete"
        d, r = mod._route_feedback_loosen_ex(200, 200, _PLATEAU, 0, False, True)
        assert d is None and r == "explicit_die_requested"

    def test_914_guard_the_no_evidence_call_still_stops_at_the_authored_floor(
            self):
        """Called WITHOUT a measured residual series there is nothing to apply a
        stall criterion to, so the authored ladder length is still the bound and
        still reports `loosen_ladder_exhausted`. This is the path every existing
        caller and test takes, and it must be unmoved."""
        lad = mod._ROUTE_LOOSEN_UTIL_LADDER
        d, r = mod._route_feedback_loosen_ex(
            200, 200, _PLATEAU, len(lad) - 1, True, True)
        assert d is None and r == "loosen_ladder_exhausted"
        d, r = mod._route_feedback_loosen_ex(
            200, 200, _PLATEAU, len(lad) - 2, True, True)
        assert d is not None and r == "loosened"

    def test_914_guard_the_backward_compatible_wrapper_still_bare_optional(
            self):
        assert mod._route_feedback_loosen(200, 200, "", 0, False, True) is None

    def test_914_guard_the_over_util_upsize_path_is_untouched(
            self, tmp_path, monkeypatch):
        """The ladder shares its retry loop with the over-util UPSIZE path, and
        raising the loop's budget must not hand the upsize path a bigger one."""
        assert mod._PNR_UPSIZE_RETRIES == 3
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_R_OVERUTIL, _CONV])
        assert res.status == "PASS"
        assert calls["n"] == 2
        assert calls["dies"][1][0] > calls["dies"][0][0]
        assert _loosen_records(res) == []

    def test_914_guard_the_authored_ladder_itself_did_not_move(self):
        """The fix changes when the ladder STOPS, not where it starts. The
        authored schedule, its head, its floor and its monotonicity are the
        calibration other parts of this file are pinned to."""
        lad = mod._ROUTE_LOOSEN_UTIL_LADDER
        assert lad[0] == mod._AUTO_DIE_TARGET_UTIL
        assert lad[-1] == mod._ROUTE_LOOSEN_UTIL_FLOOR
        assert all(lad[i] > lad[i + 1] for i in range(len(lad) - 1))
