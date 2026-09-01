#!/usr/bin/env python3
"""pdk_analog_characterize.py — measure a PDK's analog device constants ONCE,
from that PDK's OWN models, and publish them as
`analog_device_params.measured`.

WHAT WAS BROKEN
===============
Clearing an analog block's STRUCTURE_ONLY state needs numbers no document
states: the process transconductance parameters, the threshold the square-law
model actually fits, the resistor sheet, the MiM capacitance density, and the
gate drive a given current buys. `pdk_registry.json` carried three hand-typed
constants per family (two thresholds and a supply) and none of those, so every
analog-sizing invocation on every PDK re-derived them in the session from
throwaway ngspice decks — same four measurements, per design, per PDK, with no
provenance and no way for a later reader to tell a measured number from a
remembered one (vibe-ic#1962).

WHAT THIS PROGRAM IS
====================
The deterministic half of that work, and only that half. It

  1. resolves the target family's model libs, corner sections and per-ROLE
     device primitives through the resolvers the analog flow ALREADY uses, so
     every number it publishes describes the device A3 actually instantiates;
  2. emits four tiny decks — one per device class — in the geometry-unit idiom
     the resolved family declares for itself;
  3. runs them under the pinned EDA container's ngspice;
  4. extracts the constants, each by a stated method, each with the witness
     that says how well that method describes this device;
  5. writes the record with its full provenance, either into the shipped
     registry (open PDKs only) or into the project that staged the PDK.

WHAT IT DELIBERATELY DOES **NOT** DO
====================================
The sizing JUDGMENT stays where it belongs. Which spec binds which device, what
overdrive to spend, how to split a current budget, which corner a block must
close at — none of that has a unique correct answer derivable from a model
card, so none of it is here. This program measures; `analog-sizing` decides.
A measured constant that arrives with its bias conditions and its fit residual
lets that decision be made once, out loud, instead of re-derived silently.

It also never INVENTS. A metric whose deck did not run, or whose extraction is
not physical (a slope that is not positive, an extracted threshold above the
gate voltage it was extracted at, a resistance that does not increase with
length), is ABSENT from `params` and NAMED in `not_measured` together with the
simulator's own words. An absent key means not measured — never zero, never a
neighbouring family's number, never a default.

THE FOUR MEASUREMENTS
=====================
* TWO-POINT SQUARE LAW (per MOS role). Three gate biases at fractions of the
  supply, drain at the supply so the device is saturated. `sqrt(Id)` is linear
  in `Vgs` for the square law, so the OUTER two points give

      m    = (sqrt(Id_hi) - sqrt(Id_lo)) / (Vgs_hi - Vgs_lo)
      Vth  = Vgs_lo - sqrt(Id_lo) / m
      k'   = 2 m^2 / (W/L)

  and the INTERIOR point is spent on the honesty: it is not used by the fit, it
  is PREDICTED from it, and the relative error is published as `fit`. Real
  short-channel devices leave the square law as the overdrive grows, and a k'
  quoted with no residual cannot be told apart from one that fits.

* DIODE-CONNECTED GATE DRIVE (per MOS role). The gate voltage a stated current
  buys in a stated geometry. This is the number a bias chain is built from, and
  it is a measurement rather than an inversion of the square-law fit precisely
  because the fit is imperfect.

* TWO-LENGTH SHEET RESISTANCE. One resistor is not a sheet: a two-terminal
  measurement carries the end/contact resistance into the number. Two LENGTHS
  at one width cancel it exactly,

      Rs = (R(L2) - R(L1)) * W / (L2 - L1)      R_end = R(L1) - Rs * L1 / W

  and both halves are published, because a short resistor is dominated by the
  end term the single-device method silently folds into its "sheet".
  A THIRD instance at twice the width says whether the primitive honours `w` at
  all — a fixed-width flavour returns the same current for both, and for such a
  device the per-micron resistance is published and the sheet is NOT, because a
  sheet derived from a width the device ignored would be a fabricated number.

* TWO-AREA CAPACITANCE DENSITY. Same argument on the other axis: C(A) is an
  area term plus a perimeter fringe term, so one plate cannot separate them.
  Two square plates solve both exactly, and both are published, because a small
  MiM is dominated by the fringe the single-plate method folds into its
  "density".

chip-AGNOSTIC. No PDK family, foundry, vendor, SKU or device name appears in
this file. Every family-specific fact is resolved at run time from the target
PDK's own libs through the shared resolvers, or read from `pdk_registry.json`
as DATA.

NDA. The record carries derived SCALARS and the PATHS they were measured
through, never model content. Publishing into the shipped registry is refused
for any family the registry does not mark `open_source`: measuring a PDK is
reading it, and a proprietary process's constants are not the plugin's to
distribute. Such a family's record is written into the PROJECT that staged the
PDK, which is the shape vibe-ic#1962 was reported on.
"""
from __future__ import annotations

import argparse
import base64
import posixpath
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analog_pdk_availability as _apa           # noqa: E402
import analog_pdk_deck_context as _apdc          # noqa: E402
import analog_a3_netlist_emit as _a3             # noqa: E402
import analog_real_corner_sweep as _ars          # noqa: E402
import pdk_analog_device_params as _pdp          # noqa: E402
import pdk_analog_layout_minima as _minima       # noqa: E402
import _atomic_artefact as _aa                   # noqa: E402

PRODUCER = "programs/pdk_analog_characterize.py"
REGISTRY = Path(__file__).resolve().parent / "pdk_registry.json"

# The device ROLES a characterization asks the resolvers to bind. Generic role
# tokens, the same four the analog IR uses.
ROLES = ("nmos", "pmos", "res", "cap")

# ── the testbench CONDITIONS ──────────────────────────────────────────────
# Every constant below is a testbench CONDITION, not a spec and not a tuning
# knob: it is published verbatim in the record's `conditions` block so the
# measurement is reproducible, and any consumer can see the bias a number was
# taken at. The geometries are long/wide enough to keep the extraction in the
# regime the model it fits was written for.
MOS_W_UM = 10.0
MOS_L_UM = 1.0
DIODE_W_UM = 4.0
DIODE_L_UM = 2.0
DIODE_I_A = 10e-6
# THE BIAS GRID IS FOUND IN TWO PASSES, AND IT HAS TO BE.
#
# Pass 1 biases the gate at fractions OF THE SUPPLY. That is the only grid
# available before anything is known about the device, and on a family whose
# threshold sits high it lands the low point at or below threshold: measured on
# a shipped open PDK, the p-role`s low point drew 0.17 uA against the high
# point`s 41 uA, the fit was anchored in subthreshold, and the interior point
# came out 90% away from the model. A k` extracted there is not a process
# constant, it is an artefact of where the grid happened to fall.
#
# So pass 1`s only product is a PRELIMINARY threshold, and pass 2 re-biases at
# fractions of the GATE SWING THAT REMAINS above it (Vdd - Vth), which is the
# quantity a designer actually reasons in. The published numbers are pass 2`s,
# the grid used is published with them, and the residual still reports what the
# square law does or does not describe.
VGS_FRACTIONS = (0.50, 0.625, 0.75)
VOV_FRACTIONS = (0.25, 0.375, 0.50)
# Never drive the gate past this fraction of the rail, whatever the seed says:
# a bias above the supply is not a measurement of anything the design can bias.
VGS_CEILING_FRACTION = 0.95
RES_W_UM = 0.5
RES_L1_UM = 20.0
RES_L2_UM = 40.0
CAP_S1_UM = 10.0
CAP_S2_UM = 20.0
CAP_PROBE_HZ = 1000.0
DEFAULT_TEMP_C = 27.0
DEFAULT_CONTAINER = "vibeic-eda"
DECK_DEADLINE_S = 300

# A width the resolved primitive ignores cannot carry a sheet resistance. The
# probe doubles the width; anything under this relative change is "ignored".
WIDTH_SENSITIVITY_FLOOR = 0.05

# How far the interior point may sit from the square-law fit before the record
# says the model describes this device POORLY. The value is still published —
# it is the best square-law fit of a device that is not square-law — but a
# reader must not have to re-derive that from the residual.
FIT_POOR_ABOVE = 0.25

ROLE_NODES = {
    "nmos": ("d", "g", "s", "b"),
    "pmos": ("d", "g", "s", "b"),
    "res": ("a", "b", "bulk"),
    "cap": ("p", "n"),
}
ROLE_TERMINALS_DEFAULT = {"nmos": 4, "pmos": 4, "res": 3, "cap": 2}

_MEAS_RE = re.compile(
    r"MEAS\s+(\w+)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)")
# ngspice diagnostics that mean the deck did not produce a usable operating
# point. Generic simulator strings, not any family's content.
_FATAL_MARKERS = (
    "could not find a valid modelname",
    "unable to find definition of model",
    "too few parameters for subcircuit",
    "unknown subckt",
    "simulation interrupted due to error",
    "no simulations run",
    "singular matrix",
    "iteration limit reached",
)


# ═══════════════════════════════════════════════════════════════════════════
# EXTRACTION — pure arithmetic, no simulator, no container, no PDK
# ═══════════════════════════════════════════════════════════════════════════
def _finite_positive(*vals: Any) -> bool:
    for v in vals:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
        if not math.isfinite(float(v)) or float(v) <= 0.0:
            return False
    return True


def extract_square_law(vgs_lo: float, id_lo: float,
                       vgs_hi: float, id_hi: float,
                       w_over_l: float
                       ) -> Tuple[Optional[float], Optional[float], str]:
    """`(k_prime_A_per_V2, vth_V, reason)` from two saturated points.

    `reason` is empty on success and states the refusal otherwise. The two
    refusals are physical, not stylistic: a slope that is not positive means
    the device did not turn on harder at the higher gate bias, and a threshold
    at or above the lower gate bias means the fit puts the device off at a
    point it was measured conducting. Either way there is no square-law device
    here to quote a k' for, and quoting one anyway is the defect this program
    removes."""
    if not _finite_positive(id_lo, id_hi, w_over_l):
        return None, None, ("a measured drain current is not a finite "
                            "positive number, so no square-law fit exists")
    if vgs_hi <= vgs_lo:
        return None, None, "the two gate biases are not ordered"
    m = (math.sqrt(id_hi) - math.sqrt(id_lo)) / (vgs_hi - vgs_lo)
    if not math.isfinite(m) or m <= 0.0:
        return None, None, (f"sqrt(Id) does not increase with Vgs "
                            f"(slope {m:.6g}), so the device is not in the "
                            f"square-law regime at this bias")
    vth = vgs_lo - math.sqrt(id_lo) / m
    if vth >= vgs_lo:
        return None, None, (f"the extracted threshold {vth:.4g} V is not "
                            f"below the {vgs_lo:.4g} V bias it was extracted "
                            f"at")
    return 2.0 * m * m / float(w_over_l), vth, ""


def square_law_id(k_prime: float, w_over_l: float, vgs: float,
                  vth: float) -> float:
    """The fitted model's own prediction, used ONLY to score itself."""
    vov = vgs - vth
    return 0.5 * k_prime * w_over_l * vov * vov if vov > 0 else 0.0


def fit_residual(k_prime: float, vth: float, w_over_l: float,
                 vgs: float, id_measured: float) -> Optional[float]:
    """Relative error of the fit at a point the fit did not use."""
    if not _finite_positive(id_measured):
        return None
    pred = square_law_id(k_prime, w_over_l, vgs, vth)
    return abs(pred - id_measured) / id_measured


def extract_sheet_resistance(r_l1: float, r_l2: float, w_um: float,
                             l1_um: float, l2_um: float
                             ) -> Tuple[Optional[float], Optional[float],
                                        Optional[float], str]:
    """`(rsheet_ohm_per_sq, r_end_ohm, r_per_um_ohm, reason)`.

    The length differential cancels the end/contact resistance exactly; the
    intercept is that end term, published rather than folded away."""
    if not _finite_positive(r_l1, r_l2, w_um) or l2_um <= l1_um:
        return None, None, None, ("the two-length resistance measurement is "
                                  "not a pair of finite positive resistances "
                                  "at ordered lengths")
    per_um = (r_l2 - r_l1) / (l2_um - l1_um)
    if per_um <= 0.0:
        return None, None, None, (f"resistance does not increase with length "
                                  f"({per_um:.6g} ohm/um), so the primitive "
                                  f"does not scale with the drawn geometry")
    rsheet = per_um * w_um
    r_end = r_l1 - per_um * l1_um
    return rsheet, r_end, per_um, ""


def width_is_honoured(r_w: float, r_2w: float) -> bool:
    """Does the primitive's resistance respond to the drawn WIDTH at all?

    A fixed-width resistor flavour returns the same resistance for both, and a
    sheet derived from a width it ignored would be a fabricated number."""
    if not _finite_positive(r_w, r_2w):
        return False
    return abs(r_2w - r_w) / r_w >= WIDTH_SENSITIVITY_FLOOR


def extract_cap_density(c1_f: float, c2_f: float, s1_um: float, s2_um: float
                        ) -> Tuple[Optional[float], Optional[float], str]:
    """`(c_area_F_per_um2, c_perim_F_per_um, reason)` from two SQUARE plates.

    C(s) = c_area * s^2 + c_perim * 4s is two equations in two unknowns; one
    plate can only report their sum divided by its own area, which is the
    fringe-contaminated number the single-plate method calls a density."""
    if not _finite_positive(c1_f, c2_f, s1_um, s2_um) or s2_um <= s1_um:
        return None, None, ("the two-area capacitance measurement is not a "
                            "pair of finite positive capacitances at ordered "
                            "plate sizes")
    det = (s1_um * s1_um) * (4 * s2_um) - (4 * s1_um) * (s2_um * s2_um)
    if det == 0:
        return None, None, ("the two plate sizes do not separate area from "
                            "fringe")
    c_area = (c1_f * (4 * s2_um) - (4 * s1_um) * c2_f) / det
    c_perim = ((s1_um * s1_um) * c2_f - c1_f * (s2_um * s2_um)) / det
    if not math.isfinite(c_area) or c_area <= 0.0:
        return None, None, (f"the separated area density {c_area:.6g} F/um^2 "
                            f"is not positive")
    return c_area, c_perim, ""


# ═══════════════════════════════════════════════════════════════════════════
# DECK EMISSION — pure text, no simulator
# ═══════════════════════════════════════════════════════════════════════════
def _num(v: float) -> str:
    return f"{v:.10g}"


def _geom(w_um: float, l_um: float, metric: bool) -> str:
    """Geometry in the idiom the RESOLVED family declares for this device.

    Measured, and not a preference: a family whose subckt declares METRIC
    defaults computes its own junction geometry from the caller's `w` mixed
    with metric constants, so a bare number arrives ~1e6x too large there; a
    family
    whose libs set `.option scale` puts an explicit-metre number ~1e6x too
    SMALL, outside every model bin. Same rule, same reason, as
    `analog_real_corner_sweep._emit_metric_geometry`."""
    if metric:
        return f"w={_num(w_um)}u l={_num(l_um)}u"
    return f"w={_num(w_um)} l={_num(l_um)}"


def _instance(name: str, role: str, nodes: Sequence[str], device: str,
              terminals: Optional[int], geom: str) -> str:
    """One subckt instantiation, padded to the RESOLVED terminal count.

    A foundry primitive may carry terminals beyond the ones this role needs
    (a substrate tie, a well tie). ngspice aborts `Too few parameters for
    subcircuit` unless they are supplied; the extra ties go to global ground,
    the most-negative reference node. Keyed on the resolved COUNT, so a
    primitive with exactly the natural terminals is untouched."""
    want = terminals if isinstance(terminals, int) and terminals > 0 else \
        ROLE_TERMINALS_DEFAULT.get(role, len(nodes))
    nl = list(nodes)
    while len(nl) < want:
        nl.append("0")
    return f"x{name} {' '.join(nl[:want])} {device} {geom}"


def _deck_head(title: str, loads: Sequence[Tuple[str, str]], metric: bool,
               ) -> List[str]:
    L = [f"* {title} — {PRODUCER}"]
    if not metric:
        # The bare-micron idiom. Emitted only for a family that does not
        # declare metric geometry; converting the geometry and leaving it, or
        # dropping it and leaving the geometry, are the two ways to be off by
        # a million.
        L.append(".option scale=1u")
    for lib, section in loads:
        L.append(f".lib {lib} {section}" if section else f".include {lib}")
    return L


def bias_grid(supply_v: float, vth_seed: Optional[float]
              ) -> Tuple[List[float], str]:
    """`(the three gate biases, the basis that chose them)`.

    With no threshold known yet the grid is fractions of the SUPPLY — the only
    thing known before the first measurement. With a preliminary threshold in
    hand it is fractions of the gate swing that REMAINS above that threshold,
    so every point sits in strong inversion on a high-threshold device and on a
    low-threshold one alike, and the low point stops landing in subthreshold on
    whichever family happens to have the higher threshold."""
    if vth_seed is None:
        return ([supply_v * f for f in VGS_FRACTIONS],
                "fractions of the supply "
                f"{list(VGS_FRACTIONS)} (no threshold known yet)")
    swing = supply_v - float(vth_seed)
    ceiling = supply_v * VGS_CEILING_FRACTION
    grid = [min(float(vth_seed) + swing * f, ceiling) for f in VOV_FRACTIONS]
    return (grid,
            f"threshold-referred: Vth_seed {vth_seed:.4g} V + "
            f"{list(VOV_FRACTIONS)} of the remaining gate swing "
            f"{swing:.4g} V, capped at {VGS_CEILING_FRACTION} of the rail")


def render_mos_deck(role: str, device: str, terminals: Optional[int],
                    metric: bool, loads: Sequence[Tuple[str, str]],
                    supply_v: float, temp_c: float,
                    vgs_points: Sequence[float],
                    with_diode: bool = True) -> str:
    """Three saturated gate biases plus (optionally) one diode-connected
    instance.

    The PMOS is the same circuit referred to the top rail: source and bulk at
    the supply, drain at ground, gate at `supply - Vgs`, so `Vgs` below means
    the same |Vgs| for both roles and one extraction serves both."""
    p = (role == "pmos")
    vg = list(vgs_points)
    L = _deck_head(f"{role} two-point square law"
                   + (" + diode-connected gate drive" if with_diode else ""),
                   loads, metric)
    if p:
        L.append(f"vsup vsup 0 {_num(supply_v)}")
    rail = "vsup" if p else "0"
    for i, v in enumerate(vg, start=1):
        d, g = f"d{i}", f"g{i}"
        L.append(_instance(f"m{i}", role, (d, g, rail, rail), device,
                           terminals, _geom(MOS_W_UM, MOS_L_UM, metric)))
        L.append(f"vg{i} {g} 0 {_num(supply_v - v if p else v)}")
        L.append(f"vd{i} {d} 0 {_num(0.0 if p else supply_v)}")
    if with_diode:
        L.append(_instance("md", role, ("nd", "nd", rail, rail), device,
                           terminals, _geom(DIODE_W_UM, DIODE_L_UM, metric)))
        # The current source is oriented so the diode-connected device SOURCES
        # it from its own rail in both roles.
        L.append(f"idio {'nd 0' if p else '0 nd'} {_num(DIODE_I_A)}")
    L.append(f".temp {_num(temp_c)}")
    L.append(".control")
    L.append("op")
    for i in range(1, len(vg) + 1):
        L.append(f"let i{i} = {'' if p else '-'}i(vd{i})")
        L.append(f'echo "MEAS id{i}=" $&i{i}')
    if with_diode:
        L.append(f"let vdio = {f'{_num(supply_v)} - v(nd)' if p else 'v(nd)'}")
        L.append('echo "MEAS vdio=" $&vdio')
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n"


def render_res_deck(device: str, terminals: Optional[int], metric: bool,
                    loads: Sequence[Tuple[str, str]], w_um: float,
                    temp_c: float) -> str:
    """Two lengths at one width (the sheet), plus twice the width at the first
    length (does this primitive honour `w` at all)."""
    L = _deck_head("resistor: two-length sheet + width-sensitivity probe",
                   loads, metric)
    plan = (("1", w_um, RES_L1_UM), ("2", w_um, RES_L2_UM),
            ("3", 2.0 * w_um, RES_L1_UM))
    for tag, w, ln in plan:
        L.append(_instance(f"r{tag}", "res", (f"r{tag}", "0", "0"), device,
                           terminals, _geom(w, ln, metric)))
        L.append(f"vr{tag} r{tag} 0 1.0")
    L.append(f".temp {_num(temp_c)}")
    L.append(".control")
    L.append("op")
    for tag, _w, _l in plan:
        L.append(f"let ir{tag} = -i(vr{tag})")
        L.append(f'echo "MEAS ir{tag}=" $&ir{tag}')
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n"


def render_cap_deck(device: str, terminals: Optional[int], metric: bool,
                    loads: Sequence[Tuple[str, str]], temp_c: float) -> str:
    """Two square plates, measured as the small-signal current a 1 V AC probe
    drives at a low frequency: C = |I| / (2*pi*f*V)."""
    L = _deck_head("capacitor: two-area density + fringe separation",
                   loads, metric)
    for tag, s in (("1", CAP_S1_UM), ("2", CAP_S2_UM)):
        L.append(_instance(f"c{tag}", "cap", (f"c{tag}", "0"), device,
                           terminals, _geom(s, s, metric)))
        L.append(f"vc{tag} c{tag} 0 AC 1")
    L.append(f".temp {_num(temp_c)}")
    L.append(".control")
    L.append("op")
    L.append(f"ac lin 1 {_num(CAP_PROBE_HZ)} {_num(CAP_PROBE_HZ)}")
    for tag in ("1", "2"):
        L.append(f"let cm{tag} = abs(i(vc{tag}))/(2*pi*{_num(CAP_PROBE_HZ)})")
        L.append(f'echo "MEAS c{tag}=" $&cm{tag}')
    L.append(".endc")
    L.append(".end")
    return "\n".join(L) + "\n"


def parse_measurements(log: str) -> Dict[str, float]:
    """Every `MEAS <key>= <value>` the deck echoed."""
    out: Dict[str, float] = {}
    for m in _MEAS_RE.finditer(log or ""):
        try:
            out[m.group(1)] = float(m.group(2))
        except ValueError:
            continue
    return out


def deck_failed(log: str) -> Optional[str]:
    """The simulator's OWN first fatal line, or None when the deck ran.

    Returned verbatim (trimmed) so a gap is reported in the simulator's words
    rather than in this program's paraphrase of them."""
    low = (log or "").lower()
    for marker in _FATAL_MARKERS:
        idx = low.find(marker)
        if idx < 0:
            continue
        start = low.rfind("\n", 0, idx) + 1
        end = low.find("\n", idx)
        line = (log[start:end] if end > 0 else log[start:]).strip()
        return line[:400] or marker
    return None


# ═══════════════════════════════════════════════════════════════════════════
# RESOLUTION — through the resolvers the analog flow already uses
# ═══════════════════════════════════════════════════════════════════════════
def resolve_target(selector: str, container: str,
                   project: Optional[Path] = None) -> Dict[str, Any]:
    """Model libs, corner sections and the per-ROLE primitive, for `selector`.

    Deliberately NOT a second resolver. `analog_a3_netlist_emit
    .resolve_pdk_context` is the one the flow binds its NETLIST devices with
    (deck-context election -> the registry's curated `device_map` -> its
    declared `device_models`); measuring k' on a device A3 does not instantiate
    would publish a constant that describes something the design never builds.

    What this adds is the PDK RESOLUTION ITSELF. That function discovers the
    target from the PROJECT's L19 document, because its callers are per-block
    producers. A characterization is asked for a PDK, not for a design, and a
    caller with no project silently fell all the way through to the fallback
    family — measured: a request naming one family came back carrying ANOTHER
    family's model lib AND its device names. So the resolver result is
    produced here, from the selector (and from the project when one is given,
    which is what finds a PDK STAGED INTO the project), and passed in."""
    res = None
    try:
        res = _apa.resolve_pdk(selector, project=project, container=container)
    except Exception as exc:                                # pragma: no cover
        return {"status": "UNRESOLVED",
                "work_items": [f"PDK resolver unavailable: {exc}"]}
    if not (isinstance(res, dict) and res.get("available")):
        return {"status": "UNRESOLVED", "resolution": res or {},
                "work_items": [
                    f"no model libs resolve for PDK selector {selector!r}; "
                    f"nothing can be measured from a PDK that is not present"]}
    ctx = _a3.resolve_pdk_context(Path(project) if project else Path("."),
                                  selector, container, list(ROLES),
                                  resolution=res)
    ctx["resolution_source"] = res.get("source")
    ctx["pdk_root"] = res.get("pdk_root")
    ctx["resolved_libs"] = list(res.get("spice_libs") or [])
    return ctx


def _under(path: str, root: str) -> bool:
    r = posixpath.normpath(str(root)).rstrip("/") + "/"
    return posixpath.normpath(str(path)).startswith(r)


def context_describes_target(ctx: Dict[str, Any],
                             loads: Sequence[Tuple[str, str]]
                             ) -> Tuple[bool, str]:
    """Do the libs this context would load actually BELONG to the PDK that was
    asked for?

    THIS GUARD EXISTS BECAUSE THE ANSWER WAS NO, AND NOTHING SAID SO. The deck
    resolver has an authored fast-path table for a couple of open families;
    a selector that is not a key of that table falls back to another family's
    entry while still reporting the name that was ASKED FOR.
    `analog_pdk_deck_context.known_family_context` documents this exactly, and
    its own disclosure string says the context "does NOT describe" the
    requested PDK — it calls itself "a LATENT trap for the next consumer that
    reads ctx.device_map / ctx.model_lib at face value".

    This program was that next consumer. MEASURED, before this guard: a request
    for one shipped open family came back carrying ANOTHER family's model lib
    and ANOTHER family's device names, the MOS decks ran happily against the
    wrong process, and a full record — k', threshold, gate drive — was
    published under the requested family's name. Only the passive roles failed
    loudly ("unknown subckt"), and only because that family's passive names are
    not the other one's.

    So the check is STRUCTURAL and does not trust any name: every `(lib,
    section)` the decks would load must live under the PDK ROOT the resolver
    matched for this selector, or be one of the libs it resolved. A lib from
    anywhere else means the context is describing a different process, and the
    honest answer is to measure nothing.
    """
    root = ctx.get("pdk_root")
    resolved = set(ctx.get("resolved_libs") or [])
    if not root and not resolved:
        # nothing to check against; do not invent a check
        return True, ""
    foreign = [lib for lib, _s in loads
               if lib not in resolved and not (root and _under(lib, root))]
    if not foreign:
        return True, ""
    dc = ctx.get("deck_context") or {}
    tmpl = dc.get("template_family")
    corroboration = (f" The resolver reports it is carrying the `{tmpl}` "
                     f"template." if tmpl and tmpl != dc.get("family") else "")
    return False, (
        f"the resolved context would load model lib(s) that do not belong to "
        f"this PDK: {foreign}. The PDK resolved to `{root}`, so these "
        f"describe a DIFFERENT process, and measuring here would publish one "
        f"process's "
        f"constants under another's name.{corroboration}")


def registry_family_for(selector: str, ctx: Dict[str, Any]) -> Optional[str]:
    """The registry entry this characterization reads from and publishes under.

    THREE candidates, resolved through the ONE shared matcher, first hit wins:
    the family the netlist binder already resolved, the selector the caller
    ASKED for, and the family name the lib PARSE derived. The middle rung is
    not redundant — measured: a family whose libs parse to a name with the
    punctuation dropped resolved to no registry entry at all, so its declared
    supply could not be read and the whole characterization refused with
    NO_SUPPLY on a family whose supply the registry states plainly. The
    selector is the thing the caller and the registry agree on."""
    for cand in (ctx.get("registry_family"), selector, ctx.get("family")):
        if not cand:
            continue
        name, _ent = _minima.resolve_family(str(cand))
        if name:
            return name
    return None


def resolve_supply(selector: str, ctx: Dict[str, Any],
                   override: Optional[float],
                   registry: Optional[Path] = None
                   ) -> Tuple[Optional[float], str]:
    """`(supply_volts, basis)` — the rail every gate bias is a fraction of.

    A bias point is a testbench CONDITION, so it must be stated, not guessed.
    The ladder, in order, and the first rung that answers wins:

      1. the caller said so (`--supply`);
      2. the registry's DECLARED `nominal_supply_v` for the resolved family —
         the same constant `analog_a3_netlist_emit` already seeds every
         testbench supply expression from, so a characterization is biased at
         the rail the flow's own decks run at;
      3. the voltage the elected NMOS primitive's NAME spells, for a family the
         registry has no entry for at all.

    No rung four. A family that states no rail anywhere is reported unmeasured
    rather than characterized at a number this program picked."""
    if override is not None:
        return float(override), "caller (--supply)"
    fam = registry_family_for(selector, ctx) or selector
    _f, declared = _pdp.declared_params(str(fam), registry)
    v = declared.get("nominal_supply_v")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v), (f"pdk_registry.json {fam}."
                          f"analog_device_params.nominal_supply_v")
    dev = (ctx.get("role_models") or {}).get("nmos")
    if dev:
        rating = _apdc.name_voltage_rating(dev)
        if rating > 0:
            return float(rating), (f"the voltage rating the elected device "
                                   f"name spells ({dev})")
    return None, ("no supply is declared for this family and no elected "
                  "device name spells one")


def deck_loads_for(ctx: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Every `(lib, section)` the decks must load, in order.

    A family that splits its devices across several corner libs reports each
    with its OWN section name, because split libs do not share a corner
    vocabulary. A single-lib family reports none, and the single elected
    `model_lib` + nominal section is still the whole load."""
    loads = [(str(a), str(b)) for a, b in (ctx.get("deck_loads") or [])]
    if loads:
        return loads
    lib, sec = ctx.get("model_lib"), ctx.get("typ_section")
    return [(str(lib), str(sec or ""))] if lib else []


def corner_loads(loads: Sequence[Tuple[str, str]], corner: str,
                 reader) -> Tuple[List[Tuple[str, str]], Dict[str, str]]:
    """Re-elect EACH lib's own section for the requested process corner.

    "Per corner lib" is the whole point: a family that keeps its actives, its
    resistors and its capacitors in three libs states three separate corner
    vocabularies, and switching only the primary one would publish a
    slow-corner k' beside a typical-corner sheet resistance under one corner's
    name. A lib
    that states no section for the requested corner KEEPS the one it was
    elected at and SAYS SO in the returned notes, which the record publishes —
    a partially-cornered record must not read like a fully-cornered one."""
    out: List[Tuple[str, str]] = []
    notes: Dict[str, str] = {}
    for lib, section in loads:
        txt = None
        try:
            txt = reader(lib) if reader else None
        except Exception:                                   # pragma: no cover
            txt = None
        if txt is None:
            out.append((lib, section))
            notes[lib] = ("lib not readable; kept the section it was elected "
                          f"at ({section})")
            continue
        typ, process = _apdc.map_corner_sections(_apdc.parse_sections(txt))
        by_role: Dict[str, str] = {}
        for sec, off in process:
            role = "slow" if off < 0 else ("fast" if off > 0 else "typ")
            by_role[role] = sec
        if typ and "typ" not in by_role:
            by_role["typ"] = typ
        pick = by_role.get(corner)
        if pick:
            out.append((lib, pick))
            continue
        out.append((lib, section))
        notes[lib] = (f"states no `{corner}` corner section; kept "
                      f"`{section}`, so this lib's contribution to the "
                      f"`{corner}` record is at its nominal corner")
    return out, notes


# ═══════════════════════════════════════════════════════════════════════════
# THE SIMULATOR — the only part that needs a container
# ═══════════════════════════════════════════════════════════════════════════
def _sh_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def run_deck(container: str, ngspice: str, stage: str, name: str,
             text: str, deadline_s: int = DECK_DEADLINE_S) -> Dict[str, Any]:
    """Stage one deck INSIDE the container and run it.

    The deck is carried in base64 through the same exec the simulator runs
    under, so no host path has to be reachable from inside the container and no
    bind-mount layout is assumed. Nothing here reads or copies PDK content."""
    path = f"{stage}/{name}.sp"
    blob = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cp = _ars._docker(
        container,
        f"mkdir -p {_sh_quote(stage)} && printf %s {_sh_quote(blob)} "
        f"| base64 -d > {_sh_quote(path)}", timeout=120)
    if cp.returncode != 0:
        return {"ok": False, "deck": text, "meas": {},
                "log": (cp.stdout or "") + (cp.stderr or ""),
                "fatal": "the deck could not be staged in the container"}
    cp = _ars._docker(container,
                      f"{_sh_quote(ngspice)} -b {_sh_quote(path)} 2>&1",
                      timeout=deadline_s)
    log = cp.stdout or ""
    meas = parse_measurements(log)
    fatal = deck_failed(log)
    if not fatal and not meas:
        fatal = "the deck produced no MEAS line"
    return {"ok": fatal is None, "deck": text, "log": log, "meas": meas,
            "fatal": fatal, "rc": cp.returncode}


def simulator_provenance(container: str, ngspice: str) -> Dict[str, Any]:
    """Which simulator, in which image, said all of this."""
    out: Dict[str, Any] = {"tool": "ngspice", "binary": ngspice,
                           "container": container}
    try:
        cp = _ars._docker(container, f"{_sh_quote(ngspice)} -v 2>&1 | head -5",
                          timeout=60)
        m = re.search(r"ngspice[-\s]*([0-9][0-9.a-z]*)", cp.stdout or "",
                      re.I)
        if m:
            out["version"] = m.group(1)
    except Exception:                                       # pragma: no cover
        pass
    for fmt, key in (("{{.Config.Image}}", "container_image"),
                     ("{{.Image}}", "container_image_id")):
        try:
            cp = subprocess.run(["docker", "inspect", "--format", fmt,
                                 container], capture_output=True, text=True,
                                timeout=60)
            if cp.returncode == 0 and cp.stdout.strip():
                out[key] = cp.stdout.strip()
        except (OSError, subprocess.SubprocessError):       # pragma: no cover
            pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
# THE MEASUREMENT — one corner, four decks, every gap named
# ═══════════════════════════════════════════════════════════════════════════
METHOD = (
    "k' and the threshold: two-point square-law fit of sqrt(Id) vs Vgs at "
    "saturation, from the OUTER two of three gate biases; the interior point "
    "is not used by the fit and its relative error is published as `fit`. "
    "Gate drive: the gate voltage a diode-connected instance settles at for a "
    "stated current in a stated geometry. Sheet resistance: two LENGTHS at "
    "one width, which cancels the end/contact resistance exactly and "
    "publishes it separately; a third instance at twice the width says "
    "whether the primitive honours `w` at all, and the sheet is withheld when "
    "it does not. "
    "Capacitance: two SQUARE plates, which separate the area density from the "
    "perimeter fringe exactly and publish both.")

_MOS_ROLE_KEYS = {
    "nmos": ("k_prime_n_ua_per_v2", "vth_n_extracted_v", "vgs_at_id_n_v",
             "n_fit_residual_rel"),
    "pmos": ("k_prime_p_ua_per_v2", "vth_p_extracted_v", "vgs_at_id_p_v",
             "p_fit_residual_rel"),
}


def _resistance(current: Any, volts: float = 1.0) -> Optional[float]:
    if not _finite_positive(current):
        return None
    return volts / float(current)


def measure_corner(container: str, ngspice: str, stage: str,
                   ctx: Dict[str, Any], corner: str,
                   loads: Sequence[Tuple[str, str]], supply_v: float,
                   temp_c: float, res_w_um: float,
                   deck_sink=None) -> Dict[str, Any]:
    """One corner's whole record. Never raises for a PDK's shortcoming: a role
    that does not resolve, a deck that does not run and an extraction that is
    not physical each land in `not_measured` with the reason, and the corner
    still publishes whatever the other three decks did measure."""
    devices: Dict[str, str] = dict(ctx.get("role_models") or {})
    terminals: Dict[str, int] = dict(ctx.get("device_terminals") or {})
    units: Dict[str, str] = dict(ctx.get("geometry_units") or {})
    params: Dict[str, float] = {}
    fit: Dict[str, Any] = {}
    not_measured: Dict[str, str] = {}
    # HOW each role's deck was emitted. Recorded because a record that states
    # its bias and its device but not the geometry idiom or the terminal count
    # cannot be re-run from itself — and a measurement nobody can reproduce
    # from its own record is back to being a number somebody remembers.
    idiom = {r: {"geometry_units": ("metric" if units.get(r) == "metric"
                                    else "scaled_micron"),
                 "terminals": terminals.get(r) or ROLE_TERMINALS_DEFAULT[r]}
             for r in ROLES if devices.get(r)}

    def _emit(name: str, text: str) -> Dict[str, Any]:
        if deck_sink is not None:
            deck_sink[f"{corner}.{name}"] = text
        return run_deck(container, ngspice, stage, f"{corner}_{name}", text)

    # ── the two MOS roles, in two passes ─────────────────────────────────
    w_over_l = MOS_W_UM / MOS_L_UM
    bias: Dict[str, Any] = {}
    for role in ("nmos", "pmos"):
        k_key, vth_key, vgs_key, fit_key = _MOS_ROLE_KEYS[role]
        dev = devices.get(role)
        if not dev:
            not_measured[role] = ("no primitive resolves for this device role "
                                  "in the target PDK's own libs")
            continue
        metric = units.get(role) == "metric"
        term = terminals.get(role)

        def _pass(tag: str, vgs: Sequence[float], with_diode: bool):
            r = _emit(f"{role}{tag}",
                      render_mos_deck(role, dev, term, metric, loads,
                                      supply_v, temp_c, vgs, with_diode))
            if not r["ok"]:
                return None, str(r["fatal"])
            return r["meas"], ""

        # PASS 1 — supply-referred, and its only product is a seed threshold
        # (plus the diode-connected gate drive, which no bias grid affects).
        seed_grid, _seed_basis = bias_grid(supply_v, None)
        m1, why1 = _pass("_seed", seed_grid, True)
        if m1 is None:
            not_measured[role] = why1
            continue
        vdio = m1.get("vdio")
        if _finite_positive(vdio) and float(vdio) < supply_v:
            params[vgs_key] = float(vdio)
        else:
            not_measured[vgs_key] = (
                "the diode-connected instance did not settle at a gate drive "
                "between ground and the supply")
        _k0, vth0, why0 = extract_square_law(seed_grid[0], m1.get("id1"),
                                             seed_grid[2], m1.get("id3"),
                                             w_over_l)

        # PASS 2 — threshold-referred, and its product is what gets published.
        vgs, basis = bias_grid(supply_v, vth0)
        meas, why = (m1, "") if vth0 is None else _pass("", vgs, False)
        if vth0 is None:
            vgs, basis = seed_grid, ("fractions of the supply; the seed pass "
                                     "yielded no threshold to refer a second "
                                     "grid to")
        if meas is None:
            not_measured[k_key] = why
            continue
        # The bias is recorded at FULL precision, not rounded for looks: this
        # is the grid the deck was actually emitted at, and a record rounded to
        # six places re-runs at a different bias and reproduces a different k'
        # in the sixth digit. A record that cannot reproduce itself exactly is
        # not provenance, it is a summary of one.
        bias[role] = {"vgs_v": [float(v) for v in vgs], "basis": basis,
                      "seed_vth_v": vth0}
        k, vth, why = extract_square_law(vgs[0], meas.get("id1"),
                                         vgs[2], meas.get("id3"), w_over_l)
        if k is None or vth is None:
            not_measured[k_key] = why
            continue
        params[k_key] = k * 1e6
        params[vth_key] = vth
        resid = fit_residual(k, vth, w_over_l, vgs[1], meas.get("id2"))
        if resid is not None:
            fit[fit_key] = resid
            if resid > FIT_POOR_ABOVE:
                fit[f"{fit_key}_verdict"] = (
                    "POOR — the square law is the wrong model for this "
                    "device at this overdrive; the value is the best "
                    "square-law fit of it, not a law it obeys")

    # ── the resistor ─────────────────────────────────────────────────────
    dev = devices.get("res")
    if not dev:
        not_measured["res"] = ("no resistor primitive resolves for this role "
                               "in the target PDK's own libs")
    else:
        r = _emit("res", render_res_deck(dev, terminals.get("res"),
                                         units.get("res") == "metric", loads,
                                         res_w_um, temp_c))
        if not r["ok"]:
            not_measured["res"] = str(r["fatal"])
        else:
            m = r["meas"]
            r1 = _resistance(m.get("ir1"))
            r2 = _resistance(m.get("ir2"))
            r3 = _resistance(m.get("ir3"))
            if r1 is None or r2 is None:
                rs = r_end = per_um = None
                why = ("the resistor deck produced no usable current at one "
                       "of the two lengths")
            else:
                rs, r_end, per_um, why = extract_sheet_resistance(
                    r1, r2, res_w_um, RES_L1_UM, RES_L2_UM)
            if per_um is None:
                not_measured["rsheet_ohm_per_sq"] = why
            else:
                params["r_per_um_ohm"] = per_um
                if r_end is not None:
                    params["r_end_ohm"] = r_end
                if r1 is not None and r3 is not None and \
                        width_is_honoured(r1, r3):
                    params["rsheet_ohm_per_sq"] = rs
                else:
                    not_measured["rsheet_ohm_per_sq"] = (
                        f"the resolved primitive `{dev}` returns the same "
                        f"resistance at w and at 2w, so it does not honour "
                        f"the drawn width; a sheet resistance derived from a "
                        f"width the device ignored would be fabricated. The "
                        f"per-micron resistance at this primitive's OWN fixed "
                        f"width is published instead.")

    # ── the capacitor ────────────────────────────────────────────────────
    dev = devices.get("cap")
    if not dev:
        not_measured["cap"] = ("no capacitor primitive resolves for this role "
                               "in the target PDK's own libs")
    else:
        r = _emit("cap", render_cap_deck(dev, terminals.get("cap"),
                                         units.get("cap") == "metric", loads,
                                         temp_c))
        if not r["ok"]:
            not_measured["cap"] = str(r["fatal"])
        else:
            m = r["meas"]
            c_area, c_perim, why = extract_cap_density(
                m.get("c1"), m.get("c2"), CAP_S1_UM, CAP_S2_UM)
            if c_area is None:
                not_measured["cap_area_ff_per_um2"] = why
            else:
                params["cap_area_ff_per_um2"] = c_area * 1e15
                if c_perim is not None:
                    params["cap_perim_ff_per_um"] = c_perim * 1e15

    return {
        "sections": [list(x) for x in loads],
        "devices": {r: devices[r] for r in ROLES if devices.get(r)},
        "temp_c": temp_c,
        "supply_v": supply_v,
        # The grid each MOS role was actually measured on. It is per-role and
        # per-corner because it is referred to that role's own threshold at
        # that corner, so it cannot live in the shared `conditions` block.
        "bias": bias,
        "deck_idiom": idiom,
        "params": {k: params[k] for k in sorted(params)},
        "fit": fit,
        "not_measured": {k: not_measured[k] for k in sorted(not_measured)},
    }


def build_record(ctx: Dict[str, Any], corners: Dict[str, Dict[str, Any]],
                 nominal: str, supply_basis: str, res_w_um: float,
                 simulator: Dict[str, Any],
                 corner_notes: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """The whole `analog_device_params.measured` record."""
    return {
        "_schema": _pdp.RECORD_SCHEMA,
        "_generated_by": PRODUCER,
        "_method": METHOD,
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "nominal_corner": nominal,
        "simulator": simulator,
        "conditions": {
            "supply_basis": supply_basis,
            "bias_strategy": (
                "two passes: a supply-referred seed grid whose only product "
                "is a preliminary threshold, then a threshold-referred grid "
                "at fractions of the remaining gate swing, which is what is "
                "published. Each corner's `bias` block states the volts each "
                "role was actually measured at."),
            "seed_vgs_fractions_of_supply": list(VGS_FRACTIONS),
            "vov_fractions_of_remaining_swing": list(VOV_FRACTIONS),
            "vgs_ceiling_fraction_of_supply": VGS_CEILING_FRACTION,
            "fit_points": "the outer two of the three; the interior point is "
                          "the residual witness and is not used by the fit",
            "mos_w_um": MOS_W_UM, "mos_l_um": MOS_L_UM,
            "diode_w_um": DIODE_W_UM, "diode_l_um": DIODE_L_UM,
            "diode_i_a": DIODE_I_A,
            "res_w_um": res_w_um,
            "res_l1_um": RES_L1_UM, "res_l2_um": RES_L2_UM,
            "res_width_probe_um": 2.0 * res_w_um,
            "cap_s1_um": CAP_S1_UM, "cap_s2_um": CAP_S2_UM,
            "cap_probe_hz": CAP_PROBE_HZ,
        },
        "resolution": {
            "family": ctx.get("family"),
            "registry_family": ctx.get("registry_family"),
            "source": ctx.get("resolution_source"),
            "status": ctx.get("status"),
            "model_lib": ctx.get("model_lib"),
            "role_binding": (ctx.get("role_model_election") or {}).get(
                "bound_by") or {},
            "unresolved_roles": list(ctx.get("unresolved_roles") or []),
        },
        "corner_section_notes": corner_notes,
        "corners": corners,
    }


# ── writing the registry back WITHOUT churning it ─────────────────────────
# `pdk_registry.json` is a hand-maintained file: it carries `\uXXXX`-escaped
# prose, hand-compacted arrays, and a key order somebody chose. Re-dumping it
# with `json.dumps` reproduces NONE of that — measured, a run that added one
# key rewrote 63 unrelated lines, which is how a data edit stops being
# reviewable. So the record is SPLICED into the exact byte span of the member
# it replaces, and every other byte of the file is left alone.
def _scan_spans(text: str, start: int, depth_wanted: int = 0):
    """Yield `(start, end)` of each `{...}` at `depth_wanted` from `start`,
    stopping at the matching `]`. String-aware, so a brace inside PDK prose
    does not move the parse."""
    depth = 0
    in_str = False
    esc = False
    open_at = None
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == depth_wanted:
                open_at = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == depth_wanted and open_at is not None:
                yield open_at, i + 1
                open_at = None
        elif ch == "]" and depth == depth_wanted:
            return
        i += 1


def _member_span(obj: str, key: str):
    """`(member_start, value_end)` of `"key": <value>` at THIS object's own
    level, or None. Nested objects are skipped by depth, so a key of the same
    name one level down is never mistaken for this one."""
    depth = 0
    in_str = False
    esc = False
    i = 0
    tok_start = None
    while i < len(obj):
        ch = obj[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                if depth == 1 and obj[tok_start + 1:i] == key:
                    j = i + 1
                    while j < len(obj) and obj[j] in " \t\r\n":
                        j += 1
                    if j < len(obj) and obj[j] == ":":
                        j += 1
                        while j < len(obj) and obj[j] in " \t\r\n":
                            j += 1
                        if obj[j] == "{":
                            for a, b in _scan_spans(obj, j, 0):
                                return tok_start, b
                        return None
        elif ch == '"':
            in_str = True
            tok_start = i
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return None


def _indent_of(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos] if not text[line_start:pos].strip() else ""


def splice_registry_text(text: str, family: str, record: Dict[str, Any],
                         params_key: str = _pdp.PARAMS_KEY,
                         measured_key: str = _pdp.MEASURED_KEY
                         ) -> Tuple[Optional[str], str]:
    """`(new_text, "")` with `record` written under
    `<family>.<params_key>.<measured_key>`, or `(None, reason)`.

    Byte-exact everywhere else: the ONLY bytes that move are the ones inside
    the member being written."""
    try:
        arr = text.index('"pdks"')
        arr = text.index("[", arr)
    except ValueError:
        return None, "the registry declares no `pdks` array"
    for e_start, e_end in _scan_spans(text, arr + 1, 0):
        entry_text = text[e_start:e_end]
        try:
            if json.loads(entry_text).get("name") != family:
                continue
        except ValueError:
            continue
        span = _member_span(entry_text, params_key)
        if span is None:
            return None, (f"`{family}` declares no `{params_key}` object to "
                          f"write into")
        p_start, p_end = span
        params_text = entry_text[p_start:p_end]
        v_start = params_text.index("{")
        body = params_text[v_start:]
        pad = _indent_of(text, e_start + p_start) + "  "
        blob = json.dumps(record, indent=2, ensure_ascii=True)
        blob = ("\n" + pad).join(blob.splitlines())
        member = f'"{measured_key}": {blob}'
        inner = _member_span(body, measured_key)
        if inner is not None:
            m_start, m_end = inner
            new_body = body[:m_start] + member + body[m_end:]
        else:
            close = len(body) - 1                       # the object's own `}`
            head = body[:close].rstrip()
            sep = "," if head.rstrip().endswith(('"', "}", "]", "e")) or \
                head.rstrip()[-1:].isdigit() else ""
            if head.rstrip().endswith("{"):
                sep = ""
            new_body = (head + sep + "\n" + pad + member + "\n"
                        + _indent_of(text, e_start + p_start) + "}")
        new_params = params_text[:v_start] + new_body
        new_entry = entry_text[:p_start] + new_params + entry_text[p_end:]
        return text[:e_start] + new_entry + text[e_end:], ""
    return None, f"`{family}` has no entry in the registry"


def upsert_registry(registry: Dict[str, Any], family: str,
                    record: Dict[str, Any]) -> bool:
    """Put `record` under `<family>.analog_device_params.measured`, in place.

    The DECLARED constants beside it are left untouched: a family that has been
    characterized must still answer every question it answered before, with the
    same numbers, or characterizing it would be a silent retune of everything
    that already read the field."""
    for ent in registry.get("pdks") or []:
        if isinstance(ent, dict) and str(ent.get("name") or "") == family:
            params = ent.get(_pdp.PARAMS_KEY)
            if not isinstance(params, dict):
                params = {}
                ent[_pdp.PARAMS_KEY] = params
            params[_pdp.MEASURED_KEY] = record
            return True
    return False


def registry_publishable(registry: Dict[str, Any], family: str
                         ) -> Tuple[bool, str]:
    """May this family's constants be published into the SHIPPED registry?

    Only when the registry itself marks the family `open_source`. Measuring a
    PDK is reading it, and a proprietary process's device constants are not the
    plugin's to distribute — they belong in the project that is entitled to the
    PDK, which is what `--project` writes."""
    for ent in registry.get("pdks") or []:
        if isinstance(ent, dict) and str(ent.get("name") or "") == family:
            if ent.get("open_source") is True:
                return True, ""
            return False, (f"`{family}` is not marked `open_source` in the "
                           f"registry; its measured constants may not be "
                           f"published into the shipped plugin. Re-run with "
                           f"`--project <dir>` to write them into the design "
                           f"that stages the PDK.")
    return False, (f"`{family}` has no entry in the registry, so there is "
                   f"nothing to refresh; use `--project` or `--out`.")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════
def resolve_res_width(selector: str, nominal: float = RES_W_UM) -> float:
    """The resistor width the decks draw, FLOORED to the target process's own
    drawn minimum (vibe-ic#1952's record, through its reader).

    Measuring the sheet at a width the process will not let you draw would put
    the constant outside the geometry any layout can realise. A family whose
    minimum sits below the nominal draws the nominal, unchanged."""
    _fam, roles = _minima.layout_minima(selector)
    lo = _minima.min_width_um(roles, "res")
    w, _raised = _minima.floor_width(nominal, lo)
    return float(w)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Measure a PDK's analog device constants from its own "
                     "models and publish them as "
                     "analog_device_params.measured"))
    ap.add_argument("--pdk", required=True,
                    help="PDK selector to characterize")
    ap.add_argument("--container", default=DEFAULT_CONTAINER,
                    help="EDA container holding ngspice and the PDK")
    ap.add_argument("--project", default=None,
                    help=("design root. Enables resolution of a PDK STAGED "
                          "into the project, and is where the record is "
                          "written for a family that may not be published"))
    ap.add_argument("--corners", default="typ",
                    help="comma-separated process corners: typ,slow,fast")
    ap.add_argument("--temp-c", type=float, default=DEFAULT_TEMP_C)
    ap.add_argument("--supply", type=float, default=None,
                    help="rail every gate bias is a fraction of")
    ap.add_argument("--out", default=None,
                    help="write the record JSON here")
    ap.add_argument("--deck-dir", default=None,
                    help="write every emitted deck here, for audit")
    ap.add_argument("--write-registry", action="store_true",
                    help="refresh programs/pdk_registry.json (open PDKs only)")
    ap.add_argument("--registry", default=None,
                    help=("registry path to read/refresh "
                          "(default: the shipped one)"))
    ap.add_argument("--json", action="store_true",
                    help="print the record on stdout")
    a = ap.parse_args(argv)

    project = Path(a.project).resolve() if a.project else None
    registry_path = Path(a.registry) if a.registry else REGISTRY
    report: Dict[str, Any] = {"producer": PRODUCER, "pdk": a.pdk}

    wanted = [c.strip() for c in str(a.corners).split(",") if c.strip()]
    allowed_corners = {"typ", "slow", "fast"}
    invalid_corners = [c for c in wanted if c not in allowed_corners]
    if not wanted or invalid_corners:
        report["status"] = "INVALID_CORNERS"
        detail = ("no process corner was requested" if not wanted else
                  "unsupported process corner(s): " +
                  ", ".join(invalid_corners))
        report["work_items"] = [
            f"{detail}; --corners accepts only typ, slow, fast"]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    ctx = resolve_target(a.pdk, a.container, project)
    if ctx.get("status") == "UNRESOLVED":
        report["status"] = "UNRESOLVED"
        report["work_items"] = ctx.get("work_items") or []
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    ngspice = _ars._resolve_ngspice(a.container)
    if not ngspice:
        report["status"] = "NO_SIMULATOR"
        report["work_items"] = [
            f"no ngspice in container {a.container!r}; a PDK's constants are "
            f"measured from its models, and nothing here estimates them"]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    supply_v, supply_basis = resolve_supply(a.pdk, ctx, a.supply,
                                            registry_path)
    if supply_v is None:
        report["status"] = "NO_SUPPLY"
        report["work_items"] = [supply_basis]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    loads = deck_loads_for(ctx)
    if not loads:
        report["status"] = "NO_MODEL_LIB"
        report["work_items"] = [
            f"the resolver bound no model lib for {a.pdk!r}"]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    ok, why = context_describes_target(ctx, loads)
    if not ok:
        report["status"] = "CONTEXT_IS_NOT_THIS_PDK"
        report["work_items"] = [why]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    reader = _apdc.container_reader(a.container)
    family = registry_family_for(a.pdk, ctx) or a.pdk
    res_w = resolve_res_width(family)
    stage = f"/tmp/pdk_char_{int(time.time())}"
    decks: Dict[str, str] = {}
    corners: Dict[str, Dict[str, Any]] = {}
    notes: Dict[str, Dict[str, str]] = {}
    for corner in wanted:
        cl, cn = corner_loads(loads, corner, reader)
        if cn:
            notes[corner] = cn
        corners[corner] = measure_corner(
            a.container, ngspice, stage, ctx, corner, cl, supply_v,
            float(a.temp_c), res_w, deck_sink=decks)
    try:
        _ars._docker(a.container, f"rm -rf {_sh_quote(stage)}", timeout=60)
    except Exception:                                       # pragma: no cover
        pass

    record = build_record(ctx, corners, wanted[0], supply_basis, res_w,
                          simulator_provenance(a.container, ngspice), notes)
    measured_any = any(c.get("params") for c in corners.values())
    report["status"] = "MEASURED" if measured_any else "NOTHING_MEASURED"
    report["family"] = family
    report["record"] = record

    if a.deck_dir:
        d = Path(a.deck_dir)
        d.mkdir(parents=True, exist_ok=True)
        for name, text in decks.items():
            (d / f"{name}.sp").write_text(text, encoding="utf-8")
        report["deck_dir"] = str(d)

    if a.out:
        p = Path(a.out)
        _aa.write_json(p, {"family": family, _pdp.MEASURED_KEY: record})
        report["out"] = str(p)

    if project is not None:
        p = project / _pdp.PROJECT_RECORD
        _aa.write_json(p, {"family": family, _pdp.MEASURED_KEY: record})
        report["project_record"] = str(p)

    if a.write_registry:
        text = registry_path.read_text(encoding="utf-8")
        ok, why = registry_publishable(json.loads(text), family)
        if not ok:
            report["registry_refused"] = why
        elif not measured_any:
            report["registry_refused"] = (
                "nothing was measured, so there is nothing to publish; the "
                "shipped record is left as it was rather than replaced by an "
                "empty one")
        else:
            spliced, spliced_why = splice_registry_text(text, family, record)
            if spliced is None:
                report["registry_refused"] = spliced_why
            else:
                registry_path.write_text(spliced, encoding="utf-8")
                report["registry_written"] = str(registry_path)

    print(json.dumps(report if a.json else
                     {k: v for k, v in report.items() if k != "record"},
                     indent=2, ensure_ascii=False))
    return 0 if measured_any else 2


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
