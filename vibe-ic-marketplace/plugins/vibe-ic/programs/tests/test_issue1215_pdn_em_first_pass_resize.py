#!/usr/bin/env python3
"""A single end-to-end run must be able to size its own PDN.

THE DEFECT. `_pdn_em_width_floor` derives the strap width from I_total = P/V,
and the only producer of that number is the EM analysis at canonical step 25 --
which runs AFTER the PnR that draws the straps. On a tree built from `input/`
alone there is no prior run, so the floor returned its documented first-pass
None, the PDN was drawn un-sized, and step 25 then honestly failed the grid it
had just measured. MEASURED on a keeper end-to-end run of spm at v1.14.26:
pdn_em_sizing.json absent, pnr.tcl `-layer Metal4 -width 1.6`,
em_current_authority FAIL with 26 offenders at worst utilization 2.4916, all of
it on Metal4 -- the exact layer the floor targets -- while the follow-pin Metal1
rail sat at 0.53.

`_pdn_em_first_pass_resize` is the decision that closes that loop once. These
tests pin the three properties that make it safe:

  * THE BOUND IS STRUCTURAL. A sentinel in the pnr dir, written by the caller
    BEFORE the re-dispatch, makes a second resize impossible -- including after
    a crash, and including when the second pass is STILL short.
  * THE TRIGGER IS NOT A VERDICT. It fires on `drawn DEF width < derived w_em`,
    a comparison of two widths. No gate's PASS/FAIL is read.
  * IT NEVER WIDENS WHAT IT SHOULD NOT. A strap already at or above its floor
    does not trigger, and a layer the floor does not name -- the follow-pin
    rails -- is never named in the decision.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


#: The PDN script the flow itself emits: ONE follow-pin rail plus two straps.
#: The rail line is what tells the decision which layer is not a strap, and it
#: is why this fixture carries a real pnr.tcl rather than a stub.
_PNR_TCL = (
    "  add_pdn_stripe -grid grid -layer Metal1 -width 0.6 -pitch 5.44"
    " -offset 0 -followpins\n"
    "  add_pdn_stripe -grid grid -layer Metal4 -width 1.6 -pitch 153.6"
    " -offset 16.32 -extend_to_core_ring\n"
    "  add_pdn_stripe -grid grid -layer Metal5 -width 1.6 -pitch 153.18"
    " -offset 16.65 -extend_to_core_ring\n")


def _tree(tmp_path: Path, top: str = "spm", *, pnr_tcl: str = _PNR_TCL) -> Path:
    """A project whose pnr dir holds a non-empty routed DEF and the PDN script
    the run emitted."""
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / f"{top}.def").write_text("DESIGN spm ;\nEND DESIGN\n")
    if pnr_tcl is not None:
        (pnr / "pnr.tcl").write_text(pnr_tcl)
    R._pl.reports_phase3_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _arm(monkeypatch, *, floor: dict | None, drawn: dict):
    """Make the two measurements deterministic, and make the EM emit a no-op
    that leaves a fresh em.rpt so the staleness branch is satisfied."""
    monkeypatch.setattr(R, "_pdn_em_width_floor",
                        lambda *a, **k: floor, raising=True)

    def _emit(project, top, pdk, container, ir_rpt, em_rpt, notes):
        em_rpt.parent.mkdir(parents=True, exist_ok=True)
        em_rpt.write_text("Total power 0.0216\nSupply voltage 5.0\n")
        return True, True
    monkeypatch.setattr(R, "_emit_ir_em_reports", _emit, raising=True)

    import em_current_density_check as _emcd
    monkeypatch.setattr(_emcd, "_def_pg_widths_of",
                        lambda p: dict(drawn), raising=True)


#: THE REAL SHAPE. `_pdn_em_width_floor` emits a bound for EVERY routing layer,
#: the follow-pin rail's layer included -- metal1..metal4 all land on the same
#: w_em because they share a Jmax. An earlier version of this fixture listed
#: only the strap layers, and that omission made the follow-pin test VACUOUS:
#: it could not fail against the shape the program actually produces, and a
#: real defect (Metal1 reported "0.6 -> 7.24 um, 12.07x short") shipped past it.
_FLOOR = {"per_layer": {
    "metal1": {"orig_name": "Metal1", "w_em_um": 7.27},
    "metal2": {"orig_name": "Metal2", "w_em_um": 7.27},
    "metal3": {"orig_name": "Metal3", "w_em_um": 7.27},
    "metal4": {"orig_name": "Metal4", "w_em_um": 7.27},
    "metal5": {"orig_name": "Metal5", "w_em_um": 3.25},
}}


# --------------------------------------------------------------------------
# it fires when the run drew narrower than its own measured current requires
# --------------------------------------------------------------------------
def test_a_strap_drawn_narrower_than_its_own_floor_triggers_one_resize(
        tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR,
         drawn={"metal4": 1.6, "metal5": 1.6, "metal1": 0.6})
    out = R._pdn_em_first_pass_resize(_tree(tmp_path), "spm", object(), "c")
    assert out is not None
    layers = {d["layer"]: d for d in out["short"]}
    assert set(layers) == {"Metal4", "Metal5"}
    assert layers["Metal4"]["drawn_um"] == 1.6
    assert layers["Metal4"]["w_em_um"] == 7.27
    # 7.27 / 1.6 -- the shortfall the keeper run actually exhibited
    assert layers["Metal4"]["shortfall_x"] == round(7.27 / 1.6, 4)


def test_the_follow_pin_rail_is_never_named_in_the_decision(
        tmp_path, monkeypatch):
    # The floor DOES bound metal1 (7.27) and the DEF DOES state its drawn 0.6,
    # so a naive comparison calls the rail "12x short". It is not short: it is
    # a rail, and `_build_pdn_tcl` will never widen it. The decision must read
    # the `-followpins` marker in the run's own pnr.tcl and skip it.
    _arm(monkeypatch, floor=_FLOOR,
         drawn={"metal4": 1.6, "metal5": 1.6, "metal1": 0.6})
    out = R._pdn_em_first_pass_resize(_tree(tmp_path), "spm", object(), "c")
    assert {d["layer"] for d in out["short"]} == {"Metal4", "Metal5"}


def test_a_rail_short_on_its_own_must_not_order_a_wasted_repnr(
        tmp_path, monkeypatch):
    # THE REGRESSION THIS FILE EXISTS TO PREVENT. Straps already meet their
    # floor; only the rail is "short", and it always will be -- 0.6 um is the
    # cell architecture's and can never reach a multi-micron bound. Triggering
    # here would order a re-PnR that changes the PDN not at all, on every such
    # run, forever.
    _arm(monkeypatch, floor=_FLOOR,
         drawn={"metal4": 18.71, "metal5": 8.36, "metal1": 0.6})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path), "spm", object(), "c") is None


def test_without_the_pdn_script_the_decision_refuses_rather_than_guesses(
        tmp_path, monkeypatch):
    # No pnr.tcl means the strap/rail split cannot be established. Guessing it
    # is how the false trigger comes back, so the answer is None.
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 1.6, "metal1": 0.6})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path, pnr_tcl=None), "spm", object(), "c") is None


# --------------------------------------------------------------------------
# it does NOT fire when it should not
# --------------------------------------------------------------------------
def test_a_strap_already_at_its_floor_does_not_trigger(tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 7.27, "metal5": 3.25})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path), "spm", object(), "c") is None


def test_a_strap_wider_than_its_floor_does_not_trigger(tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 18.71, "metal5": 8.36})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path), "spm", object(), "c") is None


def test_no_floor_derivable_means_no_resize(tmp_path, monkeypatch):
    # e.g. a tech LEF that states no per-layer Jmax. Behaviour unchanged.
    _arm(monkeypatch, floor=None, drawn={"metal4": 1.6})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path), "spm", object(), "c") is None


def test_no_routed_def_means_no_resize(tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 1.6})
    R._pl.pnr_dir(tmp_path).mkdir(parents=True, exist_ok=True)   # no DEF
    R._pl.reports_phase3_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    assert R._pdn_em_first_pass_resize(
        tmp_path, "spm", object(), "c") is None


def test_a_def_stating_no_pg_widths_means_no_resize(tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={})
    assert R._pdn_em_first_pass_resize(
        _tree(tmp_path), "spm", object(), "c") is None


# --------------------------------------------------------------------------
# THE BOUND -- structural, and it holds in the cases a counter would miss
# --------------------------------------------------------------------------
def test_the_sentinel_bounds_the_resize_at_exactly_one_pass(
        tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 1.6, "metal5": 1.6})
    proj = _tree(tmp_path)
    first = R._pdn_em_first_pass_resize(proj, "spm", object(), "c")
    assert first is not None, "the first pass must be offered"
    # The caller writes the sentinel BEFORE re-dispatching. Simulate that.
    first["sentinel"].write_text("{}")
    assert first["sentinel"].name == R._PDN_EM_RESIZE_SENTINEL
    # Same still-short widths -- a counter-free bound must still refuse.
    assert R._pdn_em_first_pass_resize(proj, "spm", object(), "c") is None


def test_the_bound_holds_even_when_the_second_pass_is_still_short(
        tmp_path, monkeypatch):
    # pdngen can refuse a width; the second pass may still be under the floor.
    # That must NOT buy a third pass -- it must be reported, not retried.
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 2.0, "metal5": 1.8})
    proj = _tree(tmp_path)
    (R._pl.pnr_dir(proj) / R._PDN_EM_RESIZE_SENTINEL).write_text("{}")
    assert R._pdn_em_first_pass_resize(proj, "spm", object(), "c") is None


def test_the_sentinel_lives_in_the_pnr_dir_so_a_crash_cannot_reset_it(
        tmp_path, monkeypatch):
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 1.6})
    proj = _tree(tmp_path)
    out = R._pdn_em_first_pass_resize(proj, "spm", object(), "c")
    assert out["sentinel"].parent == R._pl.pnr_dir(proj)


# --------------------------------------------------------------------------
# the trigger is a width comparison, not a verdict
# --------------------------------------------------------------------------
def test_the_decision_never_reads_a_gate_verdict(tmp_path, monkeypatch):
    # An em_current_authority.json saying PASS must not suppress a real
    # shortfall, and one saying FAIL must not manufacture one. The decision is
    # a function of widths alone.
    import json
    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 1.6})
    proj = _tree(tmp_path)
    auth = R._pl.reports_phase3_dir(proj) / "em_current_authority.json"
    auth.write_text(json.dumps({"verdict": "PASS"}))
    assert R._pdn_em_first_pass_resize(proj, "spm", object(), "c") is not None

    _arm(monkeypatch, floor=_FLOOR, drawn={"metal4": 18.71})
    proj2 = _tree(tmp_path / "b")
    auth2 = R._pl.reports_phase3_dir(proj2) / "em_current_authority.json"
    auth2.write_text(json.dumps({"verdict": "FAIL"}))
    assert R._pdn_em_first_pass_resize(proj2, "spm", object(), "c") is None
