"""RUNNER-LEVEL bidirectional test for the tapless-cell-PDK latch-up false FAIL.

THE DEFECT
==========
Step 28 PERC/Reliability FAILed with

  "Latch-up tap spacing (geometry): N placed std cell(s) but 0 rated
   well/substrate-tap cell(s) - every logic transistor is infinitely far from
   any tap = categorical latch-up exposure. CONCLUSIVE structural GAP"

on a PDK that ships NO tapcell master at all — the well/substrate ties are
INSIDE every std cell, so 0 tap COMPONENTS in the DEF is the EXPECTED value and
nothing was "skipped". The same report contradicted itself: the tap-PRESENCE
category already returned a tapless INDETERMINATE while the tap-SPACING category
called the identical measurement a CONCLUSIVE FAIL.

`_latchup_tap_spacing_check` could not tell "the PDK declares no tapcell" from
"the caller passed nothing" — both arrive as `rated_tap_masters=None` — so the
ZERO_TAPS branch had no way to be correct. The explicit `tapless_pdk` signal
(`pdk.tapcell_master is None`) gives it one.

WHY A RUNNER-LEVEL TEST
=======================
The runner ALREADY had a tapless reclassification, but it fires ONLY when the
sign-off GDS tap-diffusion measurement succeeds — i.e. only for a PDK whose
`tap_geom_layers` are declared. The FIRST PDK of a family gets that data from an
agent recovery; the NEXT one does not, and the conclusive false FAIL comes back.
This file pins BOTH halves at the level the defect was observed at:

  * DEFECT direction   — tapless PDK, measurement unavailable  -> not a FAIL
  * NO-REGRESSION      — tapless PDK, measurement available    -> still upgrades
                         to TAPLESS_CELL_INTERNAL_TIES with its positive
                         geometry evidence (the richer path must NOT be lost as
                         a side effect of the new sub-status)
  * DEFECT direction   — tapcell-methodology PDK, 0 taps       -> still a
                         CONCLUSIVE AUTOMATED FAIL (a genuinely skipped tapcell
                         step is a real break and must keep failing)

chip-AGNOSTIC: keyed on `pdk.tapcell_master is None`, a registry SHAPE, not on
any PDK / vendor / chip name. The PDK strings below are fixture data only.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

runner = importlib.import_module("phase3_one_shot_runner")
geo_mod = importlib.import_module("latchup_esd_spacing_check")

_SPACING_CAT = "Latch-up tap spacing (geometry)"


def _routed_def(n_std: int, units: int = 1000, die_um: int = 100000) -> str:
    """A routed DEF with `n_std` std cells on a 10 um grid and ZERO tap cells."""
    lines = ["VERSION 5.8 ;", "DESIGN chip_top ;",
             f"UNITS DISTANCE MICRONS {units} ;",
             f"DIEAREA ( 0 0 {die_um} {die_um} ) ;",
             f"COMPONENTS {n_std} ;"]
    side = int(n_std ** 0.5) + 1
    k = 0
    for i in range(side):
        for j in range(side):
            if k >= n_std:
                break
            lines.append("- c%d sky130_fd_sc_hd__nor3_1 + PLACED ( %d %d ) N ;"
                         % (k, (5 + i * 10) * units, (5 + j * 10) * units))
            k += 1
    lines.append("END COMPONENTS")
    lines.append("SPECIALNETS 2 ;")
    lines.append("    - VGND ( c0 VNB ) + USE GROUND ;")
    lines.append("    - VPWR ( c0 VPB ) + USE POWER ;")
    lines.append("END SPECIALNETS")
    lines.append("END DESIGN")
    return "\n".join(lines) + "\n"


def _pdk(tapcell_master):
    """A minimal PdkConfig differing ONLY in whether a tapcell master exists."""
    return runner.PdkConfig(
        name="fixture_pdk",
        liberty="/foss/pdks/fixture_pdk/lib.lib",
        tech_lef="/foss/pdks/fixture_pdk/tech.tlef",
        cell_lef="/foss/pdks/fixture_pdk/cells.lef",
        cell_gds=None,
        site="unit",
        drc_deck=None,
        metal_prefix="met",
        tapcell_master=tapcell_master,
    )


def _mk_project(tmp_path: Path) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text(_routed_def(120))
    rpt3 = runner._pl.reports_phase3_dir(tmp_path)
    rpt3.mkdir(parents=True, exist_ok=True)
    for name in ("antenna", "ir_drop", "em", "erc"):
        (rpt3 / (name + ".json")).write_text(json.dumps({"verdict": "PASS"}) + "\n")
    return tmp_path


def _spacing_category(tmp_path, pdk, monkeypatch, *, tap_geometry=None):
    """Drive `_emit_perc_equivalent` and return its tap-spacing category."""
    project = _mk_project(tmp_path)
    monkeypatch.setattr(
        runner, "_measure_tap_geometry",
        lambda *a, **k: (tap_geometry if tap_geometry is not None
                         else {"ok": False, "reason": "NO_TAP_GEOM_LAYERS"}))
    assert runner._emit_perc_equivalent(project, "chip_top", pdk, "x", [])
    data = json.loads(
        (runner._pl.reports_phase3_dir(project) / "perc_equivalent.json").read_text())
    return data, next(c for c in data["categories"]
                      if c["category"] == _SPACING_CAT)


# ── DEFECT DIRECTION: the false FAIL ────────────────────────────────────
def test_tapless_pdk_without_geometry_data_is_not_a_conclusive_fail(tmp_path,
                                                                    monkeypatch):
    """A tapless PDK whose tap geometry cannot be measured must NOT read as a
    skipped tapcell step. Honest INCOMPLETE — never a fabricated PASS."""
    data, sp = _spacing_category(tmp_path, _pdk(None), monkeypatch)
    assert sp["geometry_status"] not in geo_mod.GAP_STATUSES, sp
    assert sp["result"] != "FAIL", sp
    assert _SPACING_CAT not in data["automated_failed"], data["automated_failed"]
    # ... and it must not be laundered into a PASS either.
    assert _SPACING_CAT not in data["automated_pass"], data["automated_pass"]


# ── NO-REGRESSION: the richer positive-evidence path must survive ───────
def test_tapless_pdk_with_measured_ties_still_upgrades_to_positive_evidence(
        tmp_path, monkeypatch):
    """The pre-existing GDS tap-diffusion upgrade must STILL fire for a tapless
    PDK — the new sub-status must not silently skip the measurement."""
    _data, sp = _spacing_category(
        tmp_path, _pdk(None), monkeypatch,
        tap_geometry={"ok": True, "ntap_polys": 21, "ntap_area_um2": 987.72,
                      "ptap_polys": 394, "ptap_area_um2": 1195.04})
    assert sp["geometry_status"] == "TAPLESS_CELL_INTERNAL_TIES", sp
    assert "21 N-well" in sp["note"] and "394 P-substrate" in sp["note"]
    assert sp["result"] != "FAIL"


# ── DEFECT DIRECTION: a genuine skipped-tapcell break must still FAIL ───
def test_tapcell_pdk_with_zero_taps_still_conclusively_fails(tmp_path,
                                                             monkeypatch):
    """The guard is keyed on the PDK declaring NO tapcell master. A PDK that
    DOES declare one, with 0 taps in the DEF, is the real v0.1.45 silent break
    and must keep hard-FAILing."""
    data, sp = _spacing_category(
        tmp_path, _pdk("sky130_fd_sc_hd__tapvpwrvgnd_1"), monkeypatch)
    assert sp["geometry_status"] in geo_mod.GAP_STATUSES, sp
    assert sp["status"] == "AUTOMATED" and sp["result"] == "FAIL", sp
    assert _SPACING_CAT in data["automated_failed"]
    assert data["verdict"] == "PERC_EQUIV_FAIL"
