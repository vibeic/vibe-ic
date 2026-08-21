#!/usr/bin/env python3
"""Fit a self-consistent dielectric stack from a PDK's OWN shipped cap numbers.

WHY (the gap this closes)
-------------------------
A real field-solved extraction (Calibre-xRC / StarRC / QRC) needs the foundry's
process dielectric profile (``rules.C`` / ``.nxtgrd``) — a multi-dielectric ILD
stack with the true per-layer heights and permittivities.  That file is NOT in
a commercial 180nm PDK's (or most vendor) LEF/.tf snapshot, which ships only, per routing
layer:

    * CPERSQDIST      — area capacitance over the substrate ground plane (pF/um^2)
    * EDGECAPACITANCE — fringe capacitance per unit edge length          (pF/um)
    * THICKNESS       — metal thickness                                  (um)

The *previous* coupling pass assumed a bare generic ``eps_r=4.0`` with NO stack
geometry.  This module does strictly better: it INVERTS the PDK's own two cap
numbers per layer into a **fitted dielectric stack** — a per-layer effective ILD
height ``h_eff`` and a disclosed effective permittivity ``eps_r_eff`` — that a
real 3D field solver (FasterCap) can then run on the routed geometry.

THE INVERSION (grounded in the PDK's own numbers)
-------------------------------------------------
For a wide plate at height ``h`` over a ground plane in a medium ``eps_r``:

    area_cap = eps_r * eps0 / h                         (I)  parallel plate

``eps0 = 8.854e-6 pF/um``.  Equation (I) reproduces the PDK's CPERSQDIST EXACTLY
and ties ``h`` to ``eps_r``.  So the per-layer height is fully GROUNDED in the
PDK area cap once ``eps_r`` is fixed:

    h_eff = eps_r_eff * eps0 / area_cap                 (grounded, exact area)

The relative heights are assumption-free: ``h_i / h_j = area_j / area_i``.

The fringe gives a SECOND relation.  A documented per-edge fringe model
(Sakurai-Tamaru thickness-fringe term, per single edge):

    edge_cap = eps_r * eps0 * c_fr * (T / h) ** p_fr    (II) fringe, c_fr,p_fr disclosed

Two equations (I)+(II), two unknowns (h, eps_r) → an EXACT closed-form solve
(``invert_fringe_anchored``):

    h    = ( (edge/area) / (c_fr * T**p_fr) ) ** (1/(1-p_fr))
    eps_r = area * h / eps0

HONEST FINDING (disclosed, not hidden)
--------------------------------------
The fringe-anchored EXACT solve on a REAL vendor PDK yields an UNPHYSICAL eps_r
(<1) because the foundry's per-layer EDGECAPACITANCE was produced by their OWN
calibrated 2D solver, whose fringe convention differs from any single generic
literature coefficient by several x.  Therefore ``eps_r`` is NOT uniquely
recoverable from (area, fringe) alone — this is a genuine information limit, and
we DISCLOSE it (the exact solve is reported as a diagnostic, ``eps_r_fringe_solve``).

The stack we hand to the field solver instead:
    * ANCHORS eps_r_eff to the physical SiO2 IMD value (default 4.0, disclosed),
    * DERIVES per-layer h_eff from the PDK area cap (grounded, reproduces area
      exactly),
    * CALIBRATES the fringe coefficient c_fr to the PDK's EDGECAPACITANCE at that
      eps_r (1-parameter least-squares), so the model reproduces the PDK fringe
      too, and reports the per-layer residual ratio.

Result: a fitted stack that reproduces the PDK's AREA cap exactly and its FRINGE
cap via a PDK-calibrated coefficient, with a PHYSICAL permittivity a field solver
can use — DISCLOSED as FITTED, not the foundry's true multi-dielectric rules.C.

All functions here are PURE (text/number in, data out) — unit-testable and
chip/PDK-AGNOSTIC (no vendor/SKU/IC literal drives any branch).
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

# Vacuum permittivity in pF/um : 8.854e-12 F/m -> 8.854e-6 pF/um.
EPS0_PF_PER_UM = 8.854e-6
# Physical inter-metal-dielectric permittivity anchor (SiO2-based IMD, ~3.9-4.2).
# DISCLOSED assumption — eps_r is NOT uniquely invertible from area+fringe alone.
DEFAULT_EPS_R_PHYS = 4.0
# Sakurai-Tamaru thickness-fringe term.  The classic single-line ST model is
# C/L = eps*[1.15*(w/h) + 2.80*(t/h)^0.222]; the fringe (thickness) term carries
# coefficient 2.80 over BOTH edges, so per SINGLE edge the default is 1.40.
# p_fr=0.222 is the ST thickness exponent.  Both DISCLOSED; c_fr is re-fitted to
# the PDK's own EDGECAPACITANCE in fit_stack().
DEFAULT_C_FRINGE = 1.40
DEFAULT_P_FRINGE = 0.222


# ── PDK cap layer ─────────────────────────────────────────────────────────────
class CapLayer:
    """Per-routing-layer capacitance + geometry read from the tech LEF."""

    __slots__ = ("name", "area_cap", "edge_cap", "thickness", "width",
                 "pitch", "direction")

    def __init__(self, name: str, area_cap: float, edge_cap: float,
                 thickness: float, width: float, pitch: Optional[float],
                 direction: str):
        self.name = name
        self.area_cap = area_cap        # pF/um^2  (CPERSQDIST)
        self.edge_cap = edge_cap        # pF/um    (EDGECAPACITANCE)
        self.thickness = thickness      # um       (THICKNESS)
        self.width = width              # um       (WIDTH)
        self.pitch = pitch              # um       (PITCH), may be None
        self.direction = direction      # HORIZONTAL / VERTICAL / ""

    def __repr__(self):
        return (f"CapLayer({self.name}, area={self.area_cap:g}, "
                f"edge={self.edge_cap:g}, T={self.thickness}, W={self.width})")


def _num(s: str) -> float:
    """Parse a LEF number incl. '0.03058e-3' scientific form."""
    return float(s)


def parse_lef_cap_layers(lef_text: str) -> Dict[str, CapLayer]:
    """Return {layer: CapLayer} for every TYPE ROUTING layer that ships BOTH a
    CPERSQDIST (area cap) and an EDGECAPACITANCE (fringe).  Layers without both
    are skipped (they cannot be inverted)."""
    out: Dict[str, CapLayer] = {}
    for m in re.finditer(r"\bLAYER\s+(\S+)\s(.*?)\bEND\s+\1\b", lef_text,
                         re.DOTALL):
        name, body = m.group(1), m.group(2)
        if not re.search(r"TYPE\s+ROUTING", body):
            continue

        def g(pat: str) -> Optional[str]:
            mm = re.search(pat, body)
            return mm.group(1) if mm else None

        num_re = r"([\d.]+(?:[eE][+-]?\d+)?)"
        area = g(r"\bCAPACITANCE\s+CPERSQDIST\s+" + num_re)
        edge = g(r"\bEDGECAPACITANCE\s+" + num_re)
        th = g(r"\bTHICKNESS\s+" + num_re)
        w = g(r"\bWIDTH\s+" + num_re)
        pitch = g(r"\bPITCH\s+" + num_re)
        drc = g(r"\bDIRECTION\s+(\w+)")
        if area is None or edge is None or th is None or w is None:
            continue
        out[name] = CapLayer(
            name=name,
            area_cap=_num(area),
            edge_cap=_num(edge),
            thickness=_num(th),
            width=_num(w),
            pitch=_num(pitch) if pitch else None,
            direction=(drc or "").upper(),
        )
    return out


# ── forward + inverse cap algebra (PURE) ──────────────────────────────────────
def area_cap_from_stack(h_um: float, eps_r: float) -> float:
    """Parallel-plate area cap (pF/um^2) for a plate at height h in medium eps_r."""
    if h_um <= 0:
        return 0.0
    return eps_r * EPS0_PF_PER_UM / h_um


def height_from_area_cap(area_cap: float, eps_r: float) -> float:
    """Invert the parallel-plate area cap → effective ILD height h (um).

    GROUNDED: reproduces ``area_cap_from_stack(h, eps_r) == area_cap`` exactly."""
    if area_cap <= 0:
        return 0.0
    return eps_r * EPS0_PF_PER_UM / area_cap


def edge_cap_from_stack(thickness_um: float, h_um: float, eps_r: float,
                        c_fr: float = DEFAULT_C_FRINGE,
                        p_fr: float = DEFAULT_P_FRINGE) -> float:
    """Per-edge fringe cap (pF/um) from the disclosed power-law fringe model."""
    if thickness_um <= 0 or h_um <= 0:
        return 0.0
    return eps_r * EPS0_PF_PER_UM * c_fr * (thickness_um / h_um) ** p_fr


def invert_fringe_anchored(area_cap: float, edge_cap: float, thickness_um: float,
                           c_fr: float = DEFAULT_C_FRINGE,
                           p_fr: float = DEFAULT_P_FRINGE
                           ) -> Tuple[float, float]:
    """EXACT 2-unknown solve: (area, edge, T) → (h, eps_r) that reproduce BOTH.

    From (I) area = eps_r*eps0/h and (II) edge = eps_r*eps0*c_fr*(T/h)^p_fr:
        edge/area = h * c_fr*(T/h)^p_fr = c_fr*T^p_fr * h^(1-p_fr)
        h = ( (edge/area)/(c_fr*T^p_fr) ) ^ (1/(1-p_fr))
        eps_r = area * h / eps0

    Round-trips exactly (the unit test drives this both directions).  On a real
    PDK the recovered eps_r is UNPHYSICAL — reported as a diagnostic only."""
    if area_cap <= 0 or edge_cap <= 0 or thickness_um <= 0:
        return 0.0, 0.0
    if p_fr == 1.0:  # degenerate: ratio no longer depends on h
        return 0.0, 0.0
    ratio = edge_cap / area_cap                       # um
    base = ratio / (c_fr * thickness_um ** p_fr)
    if base <= 0:
        return 0.0, 0.0
    h = base ** (1.0 / (1.0 - p_fr))
    eps_r = area_cap * h / EPS0_PF_PER_UM
    return h, eps_r


def fit_fringe_coefficient(layers: List[CapLayer], eps_r: float,
                           p_fr: float = DEFAULT_P_FRINGE) -> float:
    """Least-squares fit of the fringe coefficient c_fr at a FIXED physical eps_r,
    given each layer's area-anchored height, so the model best reproduces the
    PDK's EDGECAPACITANCE across all layers.

    With h_i = eps_r*eps0/area_i, the model edge_i = c_fr * k_i where
    k_i = eps_r*eps0*(T_i/h_i)^p_fr.  LS solution: c_fr = sum(edge_i*k_i)/sum(k_i^2).
    Returns DEFAULT_C_FRINGE if the layer set is empty/degenerate."""
    num = den = 0.0
    for L in layers:
        h = height_from_area_cap(L.area_cap, eps_r)
        if h <= 0 or L.thickness <= 0:
            continue
        k = eps_r * EPS0_PF_PER_UM * (L.thickness / h) ** p_fr
        num += L.edge_cap * k
        den += k * k
    if den <= 0:
        return DEFAULT_C_FRINGE
    return num / den


# ── per-layer + full-stack fit ────────────────────────────────────────────────
def fit_layer(layer: CapLayer, eps_r_phys: float, c_fr: float,
              p_fr: float = DEFAULT_P_FRINGE) -> Dict:
    """Fit one layer.  Area-anchored physical stack + fringe cross-check +
    fringe-anchored exact diagnostic."""
    h_eff = height_from_area_cap(layer.area_cap, eps_r_phys)
    area_repro = area_cap_from_stack(h_eff, eps_r_phys)
    edge_pred = edge_cap_from_stack(layer.thickness, h_eff, eps_r_phys, c_fr, p_fr)
    edge_ratio = (edge_pred / layer.edge_cap) if layer.edge_cap else 0.0
    # diagnostic exact fringe-anchored solve (unphysical eps_r on real PDKs)
    h_fr, eps_fr = invert_fringe_anchored(layer.area_cap, layer.edge_cap,
                                          layer.thickness, DEFAULT_C_FRINGE, p_fr)
    return {
        "layer": layer.name,
        "direction": layer.direction,
        "thickness_um": round(layer.thickness, 6),
        "width_um": round(layer.width, 6),
        "pitch_um": round(layer.pitch, 6) if layer.pitch else None,
        "area_cap_pf_per_um2": layer.area_cap,
        "edge_cap_pf_per_um": layer.edge_cap,
        # fitted physical stack (fed to the field solver):
        "eps_r_eff": round(eps_r_phys, 4),
        "h_eff_um": round(h_eff, 6),
        "area_cap_reproduced_pf_per_um2": area_repro,
        "area_rel_err": round(abs(area_repro - layer.area_cap)
                              / layer.area_cap, 8) if layer.area_cap else 0.0,
        # fringe cross-check with the PDK-calibrated coefficient:
        "edge_cap_predicted_pf_per_um": round(edge_pred, 10),
        "edge_ratio_pred_over_pdk": round(edge_ratio, 4),
        # honest diagnostic — exact (area,edge) inversion:
        "eps_r_fringe_solve": round(eps_fr, 4),
        "h_fringe_solve_um": round(h_fr, 6),
    }


def fit_stack(lef_text: str, eps_r_phys: float = DEFAULT_EPS_R_PHYS,
              p_fr: float = DEFAULT_P_FRINGE,
              calibrate_fringe: bool = True) -> Dict:
    """Fit the full dielectric stack from the tech LEF.

    Returns a dict ready to serialize (``dielectric_stack.json``) with the fitted
    physical stack (per-layer h_eff + z-heights + eps_r_eff), the PDK-calibrated
    fringe coefficient, per-layer area/fringe reproduction, and the disclosure."""
    layers_map = parse_lef_cap_layers(lef_text)
    # order by descending area cap == ascending height (lowest metal first)
    layers = sorted(layers_map.values(), key=lambda L: -L.area_cap)
    c_fr = (fit_fringe_coefficient(layers, eps_r_phys, p_fr)
            if (calibrate_fringe and layers) else DEFAULT_C_FRINGE)

    fits = [fit_layer(L, eps_r_phys, c_fr, p_fr) for L in layers]
    # assign z-heights: metal bottom at h_eff above the substrate ground plane,
    # top at h_eff + thickness.  Gives a physically-ascending, PDK-derived stack.
    for f in fits:
        z_bot = f["h_eff_um"]
        f["z_bottom_um"] = round(z_bot, 6)
        f["z_top_um"] = round(z_bot + f["thickness_um"], 6)

    # fringe reproduction quality (median |1-ratio|):
    ratios = [f["edge_ratio_pred_over_pdk"] for f in fits if f["edge_ratio_pred_over_pdk"]]
    fringe_med_abs_err = (sorted(abs(1.0 - r) for r in ratios)[len(ratios) // 2]
                          if ratios else None)
    area_max_err = max((f["area_rel_err"] for f in fits), default=0.0)

    return {
        "tool": "pdk_dielectric_fit",
        "method": "PDK-inverted fitted dielectric stack (area-anchored h_eff, "
                  "physical eps_r, PDK-calibrated fringe)",
        "eps0_pf_per_um": EPS0_PF_PER_UM,
        "eps_r_eff": round(eps_r_phys, 4),
        "fringe_model": "Sakurai-Tamaru thickness-fringe (per edge): "
                        "edge = eps_r*eps0*c_fr*(T/h)^p_fr",
        "c_fringe_fitted": round(c_fr, 6),
        "p_fringe": p_fr,
        "n_layers": len(fits),
        "area_max_rel_err": area_max_err,
        "fringe_median_abs_err": (round(fringe_med_abs_err, 4)
                                  if fringe_med_abs_err is not None else None),
        "layers": fits,
        "disclosure": [
            "FITTED stack, NOT the foundry's true rules.C/.nxtgrd multi-dielectric "
            "profile.",
            "eps_r_eff is ANCHORED to the physical SiO2-IMD value (default 4.0) — "
            "it is NOT uniquely invertible from area+fringe alone (see "
            "eps_r_fringe_solve: the exact (area,edge) solve gives an unphysical "
            "eps_r because the PDK's calibrated fringe convention differs from a "
            "generic literature coefficient).",
            "h_eff is GROUNDED in the PDK's own CPERSQDIST and reproduces the area "
            "cap EXACTLY (area_rel_err ~ 0).",
            "c_fringe is LEAST-SQUARES-fitted to the PDK's own EDGECAPACITANCE at "
            "the physical eps_r, so the model reproduces the PDK fringe too.",
            "Single uniform dielectric per solve (not the true multi-layer ILD "
            "profile) — a disclosed simplification, strictly better than a bare "
            "eps_r assumption with no stack geometry.",
            "NOT crosstalk-SI-signoff-grade; NOT silicon-proven.",
        ],
    }


def emit_stack_json(lef_path: str, out_path: str,
                    eps_r_phys: float = DEFAULT_EPS_R_PHYS,
                    p_fr: float = DEFAULT_P_FRINGE) -> Dict:
    """Read the tech LEF, fit the stack, write ``dielectric_stack.json``."""
    with open(lef_path) as f:
        lef_text = f.read()
    stack = fit_stack(lef_text, eps_r_phys, p_fr)
    stack["lef_path"] = lef_path
    with atomic_writing(out_path) as f:
        json.dump(stack, f, indent=2)
    stack["out_path"] = out_path
    return stack


def summarize(stack: Dict) -> str:
    return ("fitted dielectric stack (PDK-inverted, DISCLOSED not foundry rules.C): "
            f"{stack['n_layers']} layers, eps_r_eff={stack['eps_r_eff']}, "
            f"c_fringe_fit={stack['c_fringe_fitted']}, "
            f"area_max_rel_err={stack['area_max_rel_err']:.2e}, "
            f"fringe_median_abs_err={stack['fringe_median_abs_err']}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Invert a PDK's per-layer area+fringe caps into a fitted "
                    "dielectric stack (DISCLOSED, not foundry rules.C).")
    ap.add_argument("--lef", dest="lef_path", required=True)
    ap.add_argument("--out", dest="out_path", default="dielectric_stack.json")
    ap.add_argument("--eps-r", type=float, default=DEFAULT_EPS_R_PHYS)
    ap.add_argument("--p-fringe", type=float, default=DEFAULT_P_FRINGE)
    a = ap.parse_args(argv)
    stack = emit_stack_json(a.lef_path, a.out_path, a.eps_r, a.p_fringe)
    print(json.dumps({k: v for k, v in stack.items() if k != "layers"}, indent=2))
    print(summarize(stack))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
