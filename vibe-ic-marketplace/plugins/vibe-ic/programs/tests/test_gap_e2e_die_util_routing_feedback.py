"""ORGANIC E2E (die-util ROUTING-FEEDBACK loop) — program-first, chip-AGNOSTIC
Phase-3 backend enhancement in phase3_one_shot_runner.py.

The over-util UPSIZE loop reacts to the HARD `[ERROR GPL-0301] … exceeds 100%`
placement error, and the over-sparse DOWNSIZE reacts to a sub-threshold tap/fill
skip. NEITHER reacts to the OTHER failure mode: a die that PLACES fine but whose
detailed route never CONVERGES — TritonRoute completes with a still-high /
non-decreasing `Number of violations` across its optimization iterations. The
empirically-clean routing util is design-dependent (a high-fanout crypto core
routes only at a very sparse util; a clean datapath converges much denser), so a
single fixed target cannot serve every design.

This loop LOOSENS an AUTO-sized die one strictly-looser ladder rung at a time
(0.25 → 0.18 → 0.12 target util → larger die) when — and ONLY when — detailed
route shows a genuine non-convergence signal, re-running bounded to the ladder
length. §4.05 (LOAD-BEARING) is exercised below:

  * fires ONLY when `--die-um auto` OWNS the geometry (explicit WxH exempt);
  * a CONVERGING route (0 violations, or a still-strictly-decreasing tail) NEVER
    triggers a loosen;
  * bounded + strictly monotone (each rung a lower util / larger die), never
    below the floor rung, never above the die cap;
  * every loosen step is DISCLOSED in resize_history (direction="loosen").

HONESTY: the loop is a DETERMINISTIC congestion-relief mechanism. It does NOT
prove a looser die converges any specific design — only a live PnR run can
confirm that. These tests pin the DECISION + the RESIZE + the guards on canned
OpenROAD-log text; none launches OpenROAD or a container.
"""
from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Ladder + budget constants
# ---------------------------------------------------------------------------
class TestLoosenLadderConstants:
    def test_floor_is_the_sparsest_target(self):
        assert mod._ROUTE_LOOSEN_UTIL_FLOOR == pytest.approx(0.12)

    def test_ladder_head_is_the_auto_die_target(self):
        # The ladder starts at the auto-die's own routing-headroom target so the
        # first loosen rung is strictly looser than what auto-die already sized.
        assert mod._ROUTE_LOOSEN_UTIL_LADDER[0] == mod._AUTO_DIE_TARGET_UTIL

    def test_ladder_is_strictly_decreasing_to_the_floor(self):
        lad = mod._ROUTE_LOOSEN_UTIL_LADDER
        assert len(lad) >= 2
        assert all(lad[i] > lad[i + 1] for i in range(len(lad) - 1))
        assert lad[-1] == mod._ROUTE_LOOSEN_UTIL_FLOOR

    def test_upsize_budget_preserved_at_three(self):
        # §4.05 regression guard — the historical over-util upsize budget stays 3.
        assert mod._PNR_UPSIZE_RETRIES == 3

    def test_retry_iters_covers_every_bounded_path(self):
        # initial + upsize budget + one downsize + the loosen ladder's own rung
        # bound. #914 — the ladder no longer terminates on the AUTHORED ladder's
        # length (that was a budget masquerading as a measurement), so the loop
        # budget is pinned to the ladder's bound rather than to the schedule.
        # The relationship, not the arithmetic, is the load-bearing part: the
        # loop guard is SHARED, so a budget below the ladder's own bound would
        # make the guard — not the ladder's criterion — decide the outcome.
        expected = (1 + mod._PNR_UPSIZE_RETRIES + 1
                    + mod._ROUTE_LOOSEN_MAX_RUNGS)
        assert mod._PNR_RETRY_ITERS == expected


# ---------------------------------------------------------------------------
# Trajectory parse
# ---------------------------------------------------------------------------
class TestDrtTrajectory:
    def test_per_iteration_drt_0199_sequence(self):
        log = (
            "[INFO DRT-0199] Number of violations = 312.\n"
            "[INFO DRT-0199] Number of violations = 297.\n"
            "[INFO DRT-0199] Number of violations = 297.\n"
        )
        assert mod._drt_violation_trajectory(log) == [312, 297, 297]

    def test_completing_fallback_when_no_drt_0199(self):
        log = (
            "Completing 100% with 40 violations.\n"
            "Completing 100% with 44 violations.\n"
        )
        assert mod._drt_violation_trajectory(log) == [40, 44]

    def test_empty_when_no_route(self):
        assert mod._drt_violation_trajectory("") == []
        assert mod._drt_violation_trajectory("GPL-0301 utilization 120%") == []

    def test_last_element_equals_final_violations(self):
        log = (
            "[INFO DRT-0199] Number of violations = 5.\n"
            "[INFO DRT-0199] Number of violations = 3.\n"
        )
        traj = mod._drt_violation_trajectory(log)
        assert traj[-1] == mod._drt_final_violations(log)

    def test_intra_iteration_progress_not_counted(self):
        # Only the 100% completion line of each iteration is a trajectory point;
        # the sub-100% progress lines are NOT.
        log = (
            "Completing 20% with 9 violations.\n"
            "Completing 60% with 6 violations.\n"
            "Completing 100% with 4 violations.\n"
        )
        assert mod._drt_violation_trajectory(log) == [4]


# ---------------------------------------------------------------------------
# Non-convergence detection
# ---------------------------------------------------------------------------
class TestNonConvergingDetection:
    def test_empty_is_not_non_converging(self):
        assert mod._drt_is_non_converging([]) is False

    def test_clean_finish_is_not_non_converging(self):
        assert mod._drt_is_non_converging([50, 20, 0]) is False
        assert mod._drt_is_non_converging([0]) is False

    def test_single_iteration_with_violations_is_non_converging(self):
        assert mod._drt_is_non_converging([7]) is True

    def test_plateau_tail_is_non_converging(self):
        assert mod._drt_is_non_converging([40, 42, 42]) is True

    def test_climbing_tail_is_non_converging(self):
        assert mod._drt_is_non_converging([8, 10, 12]) is True

    def test_still_decreasing_tail_is_not_non_converging(self):
        # §4.05 — a route still strictly reducing violations (decreasing-to-clean)
        # is a router-iteration knob, NOT a die knob: no loosen.
        assert mod._drt_is_non_converging([50, 40, 30, 20, 12]) is False


# ---------------------------------------------------------------------------
# Loosen geometry math
# ---------------------------------------------------------------------------
class TestComputeLoosenedDie:
    def test_loosen_grows_the_die(self):
        dims = mod._compute_loosened_die(100, 100, 0.25, 0.18)
        assert dims is not None
        new_w, new_h = dims
        assert new_w > 100 and new_h > 100
        # side *= sqrt(0.25/0.18) = 1.1785 → 118
        assert (new_w, new_h) == (118, 118)
        assert new_w / 100 == pytest.approx((0.25 / 0.18) ** 0.5, rel=0.01)

    def test_none_when_next_not_strictly_looser(self):
        assert mod._compute_loosened_die(100, 100, 0.25, 0.25) is None  # equal
        assert mod._compute_loosened_die(100, 100, 0.18, 0.25) is None  # tighter
        assert mod._compute_loosened_die(100, 100, 0.25, 0.0) is None   # invalid

    def test_none_when_would_breach_cap(self):
        # §4.05 — a loosen past the die cap is refused (never grow beyond cap).
        near_cap = mod._DEFAULT_DIE_MAX_UM - 10
        assert mod._compute_loosened_die(near_cap, near_cap, 0.25, 0.12) is None

    def test_returned_die_never_exceeds_cap(self):
        for side in (60, 400, 1200, 1700):
            dims = mod._compute_loosened_die(side, side, 0.25, 0.18)
            if dims is not None:
                assert max(dims) <= mod._DEFAULT_DIE_MAX_UM
                assert min(dims) > side   # strictly grew


# ---------------------------------------------------------------------------
# The routing-feedback DECISION (all §4.05 guards)
# ---------------------------------------------------------------------------
_NONCONV_LOG = ("[INFO DRT-0199] Number of violations = 40.\n"
                "[INFO DRT-0199] Number of violations = 42.\n")
_CONV_LOG = "[INFO DRT-0199] Number of violations = 0.\n"


class TestRouteFeedbackDecision:
    def _call(self, **kw):
        base = dict(die_w=95, die_h=95, log_text=_NONCONV_LOG, loosen_idx=0,
                    auto_die_requested=True, route_completed=True)
        base.update(kw)
        return mod._route_feedback_loosen(**base)

    def test_fires_on_auto_completed_nonconverging(self):
        res = self._call()
        assert res is not None
        new_w, new_h, rec = res
        assert new_w > 95 and new_h > 95           # die grew
        assert rec["direction"] == "loosen"
        assert rec["trigger"] == "route_not_converged"
        assert rec["from_die_um"] == "95x95"
        assert rec["to_die_um"] == f"{new_w}x{new_h}"
        assert rec["from_target_util"] == mod._ROUTE_LOOSEN_UTIL_LADDER[0]
        assert rec["to_target_util"] == mod._ROUTE_LOOSEN_UTIL_LADDER[1]
        assert rec["to_target_util"] < rec["from_target_util"]   # util dropped
        assert rec["final_violations"] == 42
        assert rec["violation_trajectory"] == [40, 42]

    def test_explicit_die_never_loosened(self):
        # §4.05 CRITICAL — an explicit WxH die (auto_die_requested=False) is the
        # caller's pinned choice and is NEVER resized, even on non-convergence.
        assert self._call(auto_die_requested=False) is None

    def test_incomplete_route_not_judged(self):
        # A route that did not complete (rc!=0 / no DEF) is not a loosen signal.
        assert self._call(route_completed=False) is None

    def test_converged_route_no_loosen(self):
        assert self._call(log_text=_CONV_LOG) is None

    def test_budget_exhausted_at_floor_rung(self):
        # §4.05 — once the ladder floor rung is reached, no further loosen.
        last = len(mod._ROUTE_LOOSEN_UTIL_LADDER) - 1
        assert self._call(loosen_idx=last) is None
        assert self._call(loosen_idx=last - 1) is not None   # one rung left

    def test_cap_blocks_loosen_returns_none(self):
        near_cap = mod._DEFAULT_DIE_MAX_UM - 5
        assert self._call(die_w=near_cap, die_h=near_cap,
                          loosen_idx=len(mod._ROUTE_LOOSEN_UTIL_LADDER) - 2) is None


# ---------------------------------------------------------------------------
# Shared floorplan-die rewrite helper
# ---------------------------------------------------------------------------
class TestRewriteFloorplanDie:
    _TCL = ('foo\n'
            'initialize_floorplan -die_area "0 0 95 95" \\\n'
            '                      -core_area "10 10 85 85" \\\n'
            '                      -site unithd\n'
            'make_tracks\n')

    def test_rewrites_die_and_core(self):
        out = mod._rewrite_pnr_floorplan_die(self._TCL, 130, 130, 10, 120, 120)
        assert '-die_area "0 0 130 130"' in out
        assert '-core_area "10 10 120 120"' in out
        assert '-die_area "0 0 95 95"' not in out

    def test_preserves_trailing_site_line(self):
        # The regex matches only the die/core lines — the `-site` continuation
        # and everything after are untouched.
        out = mod._rewrite_pnr_floorplan_die(self._TCL, 130, 130, 10, 120, 120)
        assert "-site unithd" in out
        assert "make_tracks" in out

    def test_matches_the_real_pnr_tcl_emit(self):
        # The rewrite regex must match what _build_pnr_tcl_text actually emits,
        # or a resize would silently no-op the tcl.
        #
        # This used to assert a LITERAL substring of the builder's source. FIX 1
        # made the die a rectangle rather than a size, so the emitted names
        # changed and the literal stopped matching — while the regex it exists
        # to protect still matched perfectly. A source-substring test cannot
        # tell "the shape drifted" from "the shape was parameterised", so it is
        # replaced by the property itself: format the builder's own template
        # with the unpinned geometry and require the regex to find it.
        src = inspect.getsource(mod._build_pnr_tcl_text)
        assert "initialize_floorplan -die_area" in src
        (d, c) = mod._die_core_rects(130, 130, 10, 120, 120)   # unpinned path
        emitted = (f'initialize_floorplan -die_area "{d[0]} {d[1]} {d[2]} {d[3]}" \\\n'
                   f'                      -core_area "{c[0]} {c[1]} {c[2]} {c[3]}" \\\n'
                   f'                      -site unithd\n')
        assert mod._RE_PNR_FLOORPLAN_DIE.search(emitted) is not None
        # ...and with a PINNED, non-origin rectangle too, which is the whole
        # point of the change: a resize must not silently no-op on a slot die.
        import phase3_one_shot_runner as _m
        _prev = _m._PINNED_DIE_RECT
        try:
            _m._PINNED_DIE_RECT = (442, 442, 1494, 2089)
            (d2, c2) = mod._die_core_rects(1052, 1647, 10, 1032, 1627)
            assert d2 == (442, 442, 1494, 2089)
            assert c2 == (452, 452, 1484, 2079)
            emitted2 = (f'initialize_floorplan -die_area '
                        f'"{d2[0]} {d2[1]} {d2[2]} {d2[3]}" \\\n'
                        f'                      -core_area '
                        f'"{c2[0]} {c2[1]} {c2[2]} {c2[3]}" \\\n'
                        f'                      -site unithd\n')
            assert mod._RE_PNR_FLOORPLAN_DIE.search(emitted2) is not None
        finally:
            _m._PINNED_DIE_RECT = _prev


# ---------------------------------------------------------------------------
# FUNCTIONAL — drive step_pnr with a monkeypatched _docker_exec (no OpenROAD)
# ---------------------------------------------------------------------------
def _sky130_pdk():
    return mod.PdkConfig(
        name="sky130A",
        liberty="/placeholder/sky130_fd_sc_hd__tt.lib",
        tech_lef="/placeholder/sky130_fd_sc_hd.tlef",
        cell_lef="/placeholder/sky130_fd_sc_hd.lef",
        cell_gds="/placeholder/sky130_fd_sc_hd.gds",
        site="unithd", drc_deck="/placeholder/x.drc", metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        tapcell_distance_um=14.0)


def _build_project(tmp_path: Path, top: str, n_cells: int) -> Path:
    project = tmp_path / "proj"
    synth = mod._pl.synth_dir(project)
    synth.mkdir(parents=True, exist_ok=True)
    lines = [f"module {top}(input clk, input a, output y);"]
    for i in range(n_cells):
        lines.append(f"sky130_fd_sc_hd__inv_1 u{i} (.A(n{i}), .Y(n{i + 1}));")
    lines.append("endmodule")
    (synth / f"{top}_synth.v").write_text("\n".join(lines))
    return project


def _drive_step_pnr(tmp_path, monkeypatch, die_um, responses,
                    top="widget", n_cells=300):
    """Run step_pnr with a stateful fake _docker_exec that returns
    `responses[i]` (an (rc, out, err) tuple) for the i-th OpenROAD call and
    (0,"","") for every other container command. Records the die carried by
    pnr.tcl at each OpenROAD call. Returns (StepResult, calls_dict)."""
    project = _build_project(tmp_path, top, n_cells)
    calls = {"n": 0, "dies": []}

    def fake_docker_exec(container, cmd, timeout=None, **_):
        if "openroad -no_init" in cmd:
            i = calls["n"]
            calls["n"] += 1
            tcl = (mod._pl.pnr_dir(project) / "pnr.tcl").read_text()
            m = re.search(r'-die_area "0 0 (\d+) (\d+)"', tcl)
            calls["dies"].append((int(m.group(1)), int(m.group(2))))
            defp = mod._pl.pnr_dir(project) / f"{top}.def"
            defp.parent.mkdir(parents=True, exist_ok=True)
            defp.write_text("VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
            return responses[min(i, len(responses) - 1)]
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod.step_pnr(project, top, _sky130_pdk(), "iic", die_um, 0.30)
    return res, calls


def _loosen_records(res):
    return [r for r in (res.extras or {}).get("resize_history", [])
            if r.get("direction") == "loosen"]


# Every simulated OpenROAD run carries the PG_NET_OWNERSHIP_AUDIT line a real
# one emits at the end of pnr.tcl. These fixtures exercise the ROUTE-convergence
# feedback loop, so they must not also trip the PG net-ownership gate — a routed
# design whose PG terminals were never counted is BLOCKED, by design.
#
# The marker was called PG_CONNECT_AUDIT (field `unconnected=`) through v1.9.62,
# a name that asserted connectivity its predicate never tested; see
# `_build_pg_reconnect_tcl`. Both spellings parse so a resumed run can still
# read its cached log; the fixture uses the current one so it stays a faithful
# stand-in for what the emitter actually writes today.
_PG_OK = "PG_NET_OWNERSHIP_AUDIT: total=600 no_net=0 masters=\n"

_R_NONCONV = (0, "[INFO DRT-0199] Number of violations = 40.\n"
                 "[INFO DRT-0199] Number of violations = 45.\n" + _PG_OK, "")
_R_CONV = (0, "[INFO DRT-0199] Number of violations = 0.\n" + _PG_OK, "")
_R_OVERUTIL = (1, "[ERROR GPL-0301] Utilization 150.0 % exceeds 100%.\n", "")


class TestStepPnrRoutingFeedbackFunctional:
    def test_nonconverging_auto_die_triggers_looser_retry(
            self, tmp_path, monkeypatch):
        # non-converging first, converges after one loosen.
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_R_NONCONV, _R_CONV])
        assert res.status == "PASS"
        assert calls["n"] == 2                      # one loosen retry
        lr = _loosen_records(res)
        assert len(lr) == 1
        rec = lr[0]
        # the die GREW and the target util DROPPED — bounded, disclosed.
        w0, h0 = calls["dies"][0]
        w1, h1 = calls["dies"][1]
        assert w1 > w0 and h1 > h0
        assert rec["to_target_util"] < rec["from_target_util"]
        assert rec["from_die_um"] == f"{w0}x{h0}"
        assert rec["to_die_um"] == f"{w1}x{h1}"

    def test_converging_route_no_retry(self, tmp_path, monkeypatch):
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_R_CONV])
        assert res.status == "PASS"
        assert calls["n"] == 1                      # NO retry
        assert _loosen_records(res) == []

    def test_explicit_die_never_resized_on_nonconvergence(
            self, tmp_path, monkeypatch):
        # §4.05 CRITICAL — an explicit WxH die is NEVER loosened; the step FAILs
        # honestly with ROUTE_NOT_CONVERGED and exactly one OpenROAD call.
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "480x480", [_R_NONCONV])
        assert res.status == "FAIL"
        assert res.extras.get("finding") == "ROUTE_NOT_CONVERGED"
        assert calls["n"] == 1
        assert calls["dies"] == [(480, 480)]        # die untouched
        assert _loosen_records(res) == []

    def test_persistent_nonconvergence_bounded_then_fails(
            self, tmp_path, monkeypatch):
        # never-converging auto die → loosen is bounded to (ladder-1) steps,
        # then the honest ROUTE_NOT_CONVERGED FAIL; the die never breaches cap.
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_R_NONCONV])
        assert res.status == "FAIL"
        assert res.extras.get("finding") == "ROUTE_NOT_CONVERGED"
        lr = _loosen_records(res)
        assert len(lr) == len(mod._ROUTE_LOOSEN_UTIL_LADDER) - 1
        # strictly monotone larger die / lower util, capped.
        sides = [d[0] for d in calls["dies"]]
        assert all(sides[i] < sides[i + 1] for i in range(len(sides) - 1))
        assert max(sides) <= mod._DEFAULT_DIE_MAX_UM
        utils = [r["to_target_util"] for r in lr]
        assert all(utils[i] > utils[i + 1] for i in range(len(utils) - 1))
        assert min(utils) >= mod._ROUTE_LOOSEN_UTIL_FLOOR

    def test_decreasing_tail_does_not_loosen(self, tmp_path, monkeypatch):
        # a still-improving route (decreasing-to-clean tail) is a router knob,
        # not a die knob → NO loosen, honest FAIL.
        decr = (0, "[INFO DRT-0199] Number of violations = 50.\n"
                   "[INFO DRT-0199] Number of violations = 12.\n", "")
        res, calls = _drive_step_pnr(tmp_path, monkeypatch, "auto", [decr])
        assert res.status == "FAIL"
        assert calls["n"] == 1
        assert _loosen_records(res) == []

    def test_over_util_upsize_path_still_fires(self, tmp_path, monkeypatch):
        # §4.05 regression guard — the pre-existing over-util UPSIZE path is
        # untouched: an over-util first run grows the die, then converges.
        res, calls = _drive_step_pnr(
            tmp_path, monkeypatch, "auto", [_R_OVERUTIL, _R_CONV])
        assert res.status == "PASS"
        assert calls["n"] == 2
        w0, _ = calls["dies"][0]
        w1, _ = calls["dies"][1]
        assert w1 > w0                              # upsized
        # the upsize is disclosed and is NOT a loosen record.
        rh = (res.extras or {}).get("resize_history", [])
        assert any(r.get("direction") not in ("loosen", "downsize") for r in rh)
        assert _loosen_records(res) == []


# ---------------------------------------------------------------------------
# Wiring contract — step_pnr uses the new helpers in the retry region
# ---------------------------------------------------------------------------
class TestStepPnrWiring:
    def test_step_pnr_wires_routing_feedback(self):
        src = inspect.getsource(mod.step_pnr)
        assert "_route_feedback_loosen" in src
        assert "_PNR_RETRY_ITERS" in src
        assert "_rewrite_pnr_floorplan_die" in src
        # the loosen decision precedes the over-sparse downsize in the branch.
        assert src.index("_route_feedback_loosen") < src.index("sparse_die_skip")

    def test_upsize_budget_guard_present(self):
        src = inspect.getsource(mod.step_pnr)
        assert "_upsize_tries" in src
        assert "_PNR_UPSIZE_RETRIES" in src
