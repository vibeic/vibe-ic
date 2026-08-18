#!/usr/bin/env python3
"""Unit tests for pdk_dielectric_fit — the PDK cap → dielectric-stack inverter.

Covers: the parallel-plate area inversion round-trip, the exact fringe-anchored
(area,edge)->(h,eps) round-trip (the inversion ALGEBRA), the fringe-coefficient
least-squares fit, LEF parsing, and a real-shaped LEF whose area caps are
reproduced exactly with a physically-ascending, monotonic stack.
"""
from __future__ import annotations

import math

import pdk_dielectric_fit as P


# ── area inversion round-trip (grounded, exact) ───────────────────────────────
def test_area_roundtrip_exact():
    for eps_r in (3.9, 4.0, 4.2):
        for h in (0.5, 1.0, 2.5, 8.0):
            a = P.area_cap_from_stack(h, eps_r)
            h_back = P.height_from_area_cap(a, eps_r)
            assert math.isclose(h_back, h, rel_tol=1e-12)


def test_height_ratio_is_assumption_free():
    # h_i / h_j == area_j / area_i regardless of eps_r
    a1 = P.area_cap_from_stack(1.0, 4.0)
    a2 = P.area_cap_from_stack(3.0, 4.0)
    h1 = P.height_from_area_cap(a1, 4.0)
    h2 = P.height_from_area_cap(a2, 4.0)
    assert math.isclose(h1 / h2, a2 / a1, rel_tol=1e-12)


# ── fringe-anchored EXACT 2-unknown inversion round-trip (the algebra) ─────────
def test_fringe_anchored_roundtrip_recovers_h_and_eps():
    c_fr, p_fr = 1.40, 0.222
    for eps_true in (3.9, 4.1):
        for h_true in (0.6, 1.2, 4.0):
            for T in (0.3, 0.53, 3.08):
                area = P.area_cap_from_stack(h_true, eps_true)
                edge = P.edge_cap_from_stack(T, h_true, eps_true, c_fr, p_fr)
                h_rec, eps_rec = P.invert_fringe_anchored(area, edge, T, c_fr, p_fr)
                assert math.isclose(h_rec, h_true, rel_tol=1e-9), (h_rec, h_true)
                assert math.isclose(eps_rec, eps_true, rel_tol=1e-9)


def test_fringe_anchored_reproduces_inputs():
    # the recovered (h,eps) must regenerate the SAME area+edge under the model
    c_fr, p_fr = 1.40, 0.222
    area, edge, T = 3.058e-5, 8.17e-6, 0.53
    h, eps = P.invert_fringe_anchored(area, edge, T, c_fr, p_fr)
    assert math.isclose(P.area_cap_from_stack(h, eps), area, rel_tol=1e-9)
    assert math.isclose(P.edge_cap_from_stack(T, h, eps, c_fr, p_fr), edge,
                        rel_tol=1e-9)


def test_fringe_anchored_degenerate_guards():
    assert P.invert_fringe_anchored(0.0, 1.0, 0.5) == (0.0, 0.0)
    assert P.invert_fringe_anchored(1.0, 0.0, 0.5) == (0.0, 0.0)
    assert P.invert_fringe_anchored(1e-5, 1e-6, 0.5, p_fr=1.0) == (0.0, 0.0)


# ── fringe-coefficient least-squares fit ──────────────────────────────────────
def test_fit_fringe_coefficient_recovers_known():
    eps_r, p_fr, c_true = 4.0, 0.222, 0.37
    layers = []
    for name, area, T in (("A", 3.0e-5, 0.53), ("B", 1.4e-5, 0.53),
                          ("C", 6.0e-6, 0.53)):
        h = P.height_from_area_cap(area, eps_r)
        edge = P.edge_cap_from_stack(T, h, eps_r, c_true, p_fr)
        layers.append(P.CapLayer(name, area, edge, T, 0.28, 0.5, "HORIZONTAL"))
    c_fit = P.fit_fringe_coefficient(layers, eps_r, p_fr)
    assert math.isclose(c_fit, c_true, rel_tol=1e-9)


def test_fit_fringe_coefficient_empty_is_default():
    assert P.fit_fringe_coefficient([], 4.0) == P.DEFAULT_C_FRINGE


# ── LEF parsing ───────────────────────────────────────────────────────────────
_LEF = """
VERSION 5.6 ;
LAYER MET1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.56 ;
  WIDTH 0.23 ;
  SPACING 0.23 ;
  RESISTANCE RPERSQ 0.082 ;
  CAPACITANCE   CPERSQDIST 0.03058e-3 ;
  EDGECAPACITANCE   0.00817e-3 ;
  THICKNESS 0.53 ;
END MET1
LAYER VIA1
  TYPE CUT ;
END VIA1
LAYER MET2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.66 ;
  WIDTH 0.28 ;
  CAPACITANCE   CPERSQDIST 0.01406e-3 ;
  EDGECAPACITANCE   0.00684e-3 ;
  THICKNESS 0.53 ;
END MET2
LAYER MET_NOCAP
  TYPE ROUTING ;
  WIDTH 0.28 ;
  THICKNESS 0.53 ;
END MET_NOCAP
END LIBRARY
"""


def test_parse_lef_cap_layers():
    layers = P.parse_lef_cap_layers(_LEF)
    assert set(layers) == {"MET1", "MET2"}          # MET_NOCAP skipped (no caps)
    m1 = layers["MET1"]
    assert math.isclose(m1.area_cap, 3.058e-5, rel_tol=1e-9)
    assert math.isclose(m1.edge_cap, 8.17e-6, rel_tol=1e-9)
    assert m1.thickness == 0.53 and m1.width == 0.23
    assert m1.direction == "HORIZONTAL" and m1.pitch == 0.56


# ── full-stack fit on real-shaped data ────────────────────────────────────────
def _six_layer_lef():
    rows = [
        ("MET1", "0.03058e-3", "0.00817e-3", "0.53", "HORIZONTAL"),
        ("MET2", "0.01406e-3", "0.00684e-3", "0.53", "VERTICAL"),
        ("MET3", "0.00913e-3", "0.00607e-3", "0.53", "HORIZONTAL"),
        ("MET4", "0.00676e-3", "0.00536e-3", "0.53", "VERTICAL"),
        ("MET5", "0.00537e-3", "0.00505e-3", "0.53", "HORIZONTAL"),
        ("MET6", "0.00445e-3", "0.00478e-3", "3.08", "VERTICAL"),
    ]
    body = ["VERSION 5.6 ;"]
    for name, a, e, t, d in rows:
        body.append(f"""LAYER {name}
  TYPE ROUTING ;
  DIRECTION {d} ;
  WIDTH 0.28 ;
  CAPACITANCE   CPERSQDIST {a} ;
  EDGECAPACITANCE   {e} ;
  THICKNESS {t} ;
END {name}""")
    body.append("END LIBRARY")
    return "\n".join(body)


def test_fit_stack_reproduces_area_exactly_and_monotonic():
    stack = P.fit_stack(_six_layer_lef(), eps_r_phys=4.0)
    assert stack["n_layers"] == 6
    assert stack["eps_r_eff"] == 4.0
    # AREA cap reproduced exactly for every layer
    assert stack["area_max_rel_err"] < 1e-9
    for L in stack["layers"]:
        # area_rel_err is 0 on the unrounded h; recompute from the 6-decimal
        # stored h_eff carries only that rounding (<1e-4 rel).
        assert L["area_rel_err"] < 1e-9
        repro = P.area_cap_from_stack(L["h_eff_um"], L["eps_r_eff"])
        assert math.isclose(repro, L["area_cap_pf_per_um2"], rel_tol=1e-4)
    # heights are physical and monotonically ascending (lowest metal first)
    hs = [L["h_eff_um"] for L in stack["layers"]]
    assert hs == sorted(hs)
    assert all(0.1 < h < 50.0 for h in hs)
    # z-stack strictly ascending, non-overlapping bottoms
    zbots = [L["z_bottom_um"] for L in stack["layers"]]
    assert zbots == sorted(zbots)


def test_fit_stack_fringe_calibrated_and_diagnostic_disclosed():
    stack = P.fit_stack(_six_layer_lef(), eps_r_phys=4.0)
    # PDK-calibrated fringe coefficient is far below the generic literature 1.40
    # (this IS the disclosed finding — the PDK fringe convention differs)
    assert 0.0 < stack["c_fringe_fitted"] < 1.40
    # calibrated model reproduces the PDK fringe within a modest band
    assert stack["fringe_median_abs_err"] < 0.30
    # the exact fringe-anchored diagnostic eps_r is UNPHYSICAL (< 1) — disclosed
    for L in stack["layers"]:
        assert L["eps_r_fringe_solve"] < 1.5
    assert any("not uniquely invertible" in d.lower() for d in stack["disclosure"])


def test_fit_stack_eps_r_scales_heights():
    s40 = P.fit_stack(_six_layer_lef(), eps_r_phys=4.0)
    s42 = P.fit_stack(_six_layer_lef(), eps_r_phys=4.2)
    for a, b in zip(s40["layers"], s42["layers"]):
        assert math.isclose(b["h_eff_um"] / a["h_eff_um"], 4.2 / 4.0, rel_tol=1e-6)
