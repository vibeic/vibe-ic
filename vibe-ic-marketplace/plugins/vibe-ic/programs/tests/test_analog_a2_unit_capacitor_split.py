"""A capacitor the PDK cannot draw becomes N unit capacitors that it can.

MEASURED (u_hawaii_adc / ihp-sg13g2 / image 0.3.46). This library sized
`delta_sigma`'s capacitors from the noise budget and got drawn lengths of
34.75 to 629.08 um against a gencell that states `lmax 30.0`. A magic gencell
asked for more does NOT refuse the way one below `lmin` does — it CLAMPS to
the maximum and draws — so twelve netlist capacitors came back as TWO drawn
cells, the largest device 21x smaller than the netlist asks for. DRC was
clean, the A5 gate passed, magic's attribution said DEVICE_ONLY, and the only
artefact that noticed was the sign-off LVS six steps later, whose
cross-reference named exactly those eight devices as differing in `l` alone.

Every number below is one of that block's own capacitors and the PDK's own
measured constants, so a change that breaks the split breaks against the case
it was built from.
"""
from __future__ import annotations

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a2_topology_emit as A2
import pdk_analog_layout_minima as M


# The PDK's own measured capacitance constants, out of the registry record
# `pdk_analog_characterize` derives by simulating the model at two sizes.
CAREA, CPERI = 1.5000000000000002, 0.03999999999999902
LMAX = WMAX = 30.0
LMIN = 0.5

#: (name, drawn length the sizing asked for, units the split must produce)
#: — every capacitor of the measured block that is over the maximum.
OVERSIZE = [("c_cmc", 245.341, 9), ("c_vcm", 138.981, 5),
            ("c_qdly", 60.0, 2), ("caz", 34.7452, 2),
            ("cc1", 188.724, 7), ("ci1", 629.081, 21),
            ("cc2", 188.724, 7), ("ci2", 629.081, 21)]
#: ...and the ones that are not, which must come back untouched.
IN_RANGE = [3.47452, 10.0, 30.0]


def _split(l_um, w_um=10.0, **kw):
    kw.setdefault("max_l", LMAX)
    kw.setdefault("max_w", WMAX)
    kw.setdefault("min_l", LMIN)
    kw.setdefault("carea", CAREA)
    kw.setdefault("cperi", CPERI)
    return A2.unit_capacitor_split(w_um, l_um, **kw)


def test_every_oversize_capacitor_of_the_measured_block_splits_and_fits():
    for name, l_um, want_n in OVERSIZE:
        n, lu, why = _split(l_um)
        assert why == "", (name, why)
        assert n == want_n, (name, n, want_n)
        assert lu <= LMAX, (name, lu)
        assert lu >= LMIN, (name, lu)


def test_the_split_preserves_the_capacitance_far_inside_its_own_tolerance():
    """THE TOLERANCE THIS SPLIT HOLDS, stated and asserted. The solve is exact
    in real arithmetic; what the bound covers is rounding and a degenerate
    family. Measured: below 1e-15 on every capacitor of the block."""
    assert A2.CAP_SPLIT_TOLERANCE == 1e-3
    for name, l_um, _n in OVERSIZE:
        n, lu, _ = _split(l_um)
        target = A2.capacitance_ff(10.0, l_um, CAREA, CPERI)
        got = n * A2.capacitance_ff(10.0, lu, CAREA, CPERI)
        rel = abs(got - target) / target
        assert rel <= A2.CAP_SPLIT_TOLERANCE, (name, rel)
        assert rel < 1e-12, (name, rel)


def test_the_naive_area_only_split_is_outside_the_tolerance():
    """THE MUTATION ARM, and the reason the perimeter term is in the solve at
    all. Dividing the LENGTH by N — which is what this library's own sizing
    expression would give, since it models area alone — leaves N units with N
    times the edge of one, and the value moves by the whole extra fringe. The
    tolerance above is tight enough to reject it, which is what makes it a
    bound and not a decoration."""
    worst = 0.0
    for name, l_um, _n in OVERSIZE:
        n, _lu, _ = _split(l_um)
        target = A2.capacitance_ff(10.0, l_um, CAREA, CPERI)
        naive = n * A2.capacitance_ff(10.0, l_um / n, CAREA, CPERI)
        worst = max(worst, abs(naive - target) / target)
    assert worst > A2.CAP_SPLIT_TOLERANCE, worst


def test_a_capacitor_the_pdk_can_already_draw_is_not_touched():
    """THE CONTROL. A design with no oversize capacitor takes a path that
    changes nothing: N is 1 and the length is the one it was given."""
    for l_um in IN_RANGE:
        n, lu, why = _split(l_um)
        assert (n, lu, why) == (1, l_um, "")


def test_a_family_that_declares_no_maximum_bounds_nothing():
    """NOT MEASURED is not "no maximum exists": with no ceiling the device is
    returned as it stands, and the caller's provenance says nothing was
    checked."""
    n, lu, why = _split(629.081, max_l=None)
    assert (n, lu, why) == (1, 629.081, "")


def test_no_legal_unit_set_is_refused_by_name_never_drawn_at_the_maximum():
    """The whole point: the alternative to a legal array is a REFUSAL, not the
    nearest thing the gencell will accept."""
    n, lu, why = _split(629.081, min_l=29.99)
    assert (n, lu) == (None, None)
    assert "below the PDK minimum" in why and "29.99" in why


def test_a_width_above_the_maximum_is_refused_and_says_why():
    n, lu, why = _split(10.0, w_um=45.0)
    assert (n, lu) == (None, None)
    assert "width" in why and "45.0" in why and "LENGTH only" in why


# ── the IR rewrite ──────────────────────────────────────────────────────
def _ir_bits(l_expr="629.081"):
    devices = [{"name": "ci1", "role": "cap", "w": 10.0,
                "nets": ["vsum1", "vo1"]},
               {"name": "mn1", "role": "nmos", "w": 1.0, "nets": ["a", "b"]}]
    exprs = [{"device": "ci1", "param": "l", "expr": l_expr,
              "rationale": "the noise budget"}]
    maxima = {"cap": {"max_length_um": LMAX, "max_width_um": WMAX}}
    minima = {"cap": {"min_width_um": LMIN}}
    measured = {"cap_area_ff_per_um2": CAREA, "cap_perim_ff_per_um": CPERI}
    return devices, exprs, maxima, minima, measured


def test_the_ir_carries_n_devices_on_the_same_two_nets():
    devices, exprs, maxima, minima, measured = _ir_bits()
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, maxima, minima, measured)
    assert refusals == []
    caps = [d for d in devs if d["role"] == "cap"]
    assert len(caps) == 21
    assert [d["name"] for d in caps][:2] == ["ci1_u0", "ci1_u1"]
    assert all(d["nets"] == ["vsum1", "vo1"] for d in caps), (
        "the units are in PARALLEL: same two nets, every one of them")
    assert [d["name"] for d in devs if d["role"] != "cap"] == ["mn1"]
    assert len([e for e in out_exprs if e["param"] == "l"]) == 21
    assert recs[0]["units"] == 21 and recs[0]["device"] == "ci1"
    assert recs[0]["relative_value_error"] < 1e-12


def test_the_emitted_unit_expression_resolves_to_the_unit_length():
    """The unit length stays DERIVED — the original expression is kept whole
    inside the closed form — and it must evaluate, in the environment
    `analog_a3_netlist_emit` uses, to the length the solver chose."""
    devices, exprs, maxima, minima, measured = _ir_bits(
        l_expr="sampling_ff / (cap_area_ff_per_um2 * w_cap)")
    env = {"sampling_ff": 629.081 * CAREA * 10.0,
           "cap_area_ff_per_um2": CAREA, "w_cap": 10.0}
    _devs, out_exprs, recs, _r = A2.split_oversize_capacitors(
        devices, exprs, env, maxima, minima, measured)
    got = A2._safe_eval(out_exprs[0]["expr"], dict(env))
    assert abs(got - recs[0]["unit_l_um"]) < 1e-9, (got, recs[0])
    assert "sampling_ff" in out_exprs[0]["expr"], (
        "the spec-derived expression must survive inside the closed form")
    assert "unit 1 of 21" in out_exprs[0]["rationale"]


def test_a_device_the_split_cannot_resolve_is_left_exactly_as_it_was():
    devices, exprs, maxima, minima, measured = _ir_bits(l_expr="not_a_name")
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, maxima, minima, measured)
    assert recs == [] and refusals == []
    assert [d["name"] for d in devs] == ["ci1", "mn1"]
    assert out_exprs == exprs


def test_the_registry_states_the_maximum_the_split_is_measured_against():
    _fam, roles = M.layout_maxima("ihp-sg13g2")
    assert M.max_length_um(roles, "cap") == LMAX
    assert M.max_width_um(roles, "cap") == WMAX
    assert "lmax" in (M.maxima_source("ihp-sg13g2") or "")
    # a family with no record bounds nothing, and says so by being empty
    assert M.layout_maxima("nangate45")[1] == {}


def test_a_family_with_no_maxima_record_splits_nothing_and_says_so():
    """THE CONTROL AT THE REWRITE. The split is driven entirely by the
    registry record, so a family that declares no capacitor maximum takes the
    path it always took: the device list and the expression list come back
    unchanged and by IDENTITY, and there is nothing to record.

    (The end-to-end form of this control is not reachable on this library
    entry: the only other characterized family in the registry is refused BY
    NAME by the entry's own slew bound before a topology is emitted at all,
    which its own test asserts. So the control is taken here, one level in.)"""
    devices, exprs, _maxima, minima, measured = _ir_bits()
    before = [dict(d) for d in devices]
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, {}, minima, measured)
    assert devs is devices and out_exprs is exprs
    assert devs == before
    assert recs == [] and refusals == []


def test_a_family_with_no_measured_capacitance_constants_splits_nothing():
    """The other half of the same rule: a maximum with no constants to solve
    against is not a licence to guess one. SPLITS NOTHING — unchanged, and
    still asserted by identity.

    RE-AIMED on the SILENCE (vibe-ic#2056 residual). Returning no refusal here
    made "nothing was split" indistinguishable from "nothing was oversize",
    and the provenance block keyed on `maxima_available` alone then printed the
    note saying an oversize capacitor "is realised as N unit devices in
    parallel". So the record asserted the split over a device that had been
    carried at its library length. Detecting the oversize needs only the
    maximum and the drawn length, so the device is now NAMED. The control that
    it does not fire on an in-range capacitor is in
    `test_unit_capacitor_split_per_family.py`.
    """
    devices, exprs, maxima, minima, _measured = _ir_bits()
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, maxima, minima, {})
    assert devs is devices and out_exprs is exprs
    assert recs == []
    assert refusals, "an oversize capacitor was carried in silence"
    assert all("cap_area_ff_per_um2" in r for r in refusals), refusals


# ── the sizing itself is the PDK's own two-term model ────────────────────
#
# MEASURED across u_hawaii_adc's thirteen capacitors, at the library drawn
# width and this family's measured constants. `l = C / (carea * w)` makes the
# AREA term equal the target and the device's own fringe then adds on top, so
# every capacitor realised MORE than it was sized for:
#
#     device      drawn l    target fF   realised fF   error
#     ci1 / ci2   629.081     9436.215     9487.342    +0.542%
#     c_cmc       245.341     3680.115     3700.542    +0.555%
#     caz          34.745      521.178      524.758    +0.687%
#     cc (ldo)     10.000      150.000      151.600    +1.067%
#     cs / cf       3.475       52.118       53.196    +2.068%
#
# — every one outside the 0.1% this file holds, and NOT UNIFORM, so a RATIO
# between two of them carried the difference between the two ends.

_SIZING_ENV = {
    "noise_budget_factor": 12.0, "kt_j_300k": 4.14e-21,
    "farad_to_ff": 1.0e15, "enob": 12.0, "osr": 64.0, "vref": 1.2,
    "cap_area_ff_per_um2": CAREA, "cap_perim_ff_per_um": CPERI,
    "w_cap": 10.0,
}


def _sized(expr, env=None):
    e = dict(_SIZING_ENV, **(env or {}))
    return A2._safe_eval(expr, e)


def test_the_sized_length_realises_its_target_on_the_pdks_own_model():
    """GREEN. Whatever capacitance the entry asks for, the length emitted for
    it realises that capacitance — not that capacitance plus a fringe."""
    for scale in (1.0, 0.25, 40.0, 175.0):
        ff = scale * _sized(A2.SAMPLING_CAP_FF_EXPR)
        l = _sized(A2.cap_l_expr(f"{scale} * ({A2.SAMPLING_CAP_FF_EXPR})"))
        got = A2.capacitance_ff(10.0, l, CAREA, CPERI)
        assert abs(got - ff) / ff < 1e-12, (scale, ff, got)


def test_the_area_only_sizing_is_outside_the_tolerance_this_file_holds():
    """THE MUTATION ARM. Revert to `C / (carea * w)` — the expression this
    library used — and every one of the block's capacitors falls outside the
    tolerance again. That is what makes the two-term form a fix and not a
    refactor."""
    worst = 0.0
    for scale in (1.0, 0.25, 40.0, 175.0):
        ff = scale * _sized(A2.SAMPLING_CAP_FF_EXPR)
        area_only = ff / (CAREA * 10.0)          # the old expression
        got = A2.capacitance_ff(10.0, area_only, CAREA, CPERI)
        worst = max(worst, abs(got - ff) / ff)
    assert worst > A2.CAP_SPLIT_TOLERANCE, worst


def test_the_error_the_old_form_left_was_not_uniform():
    """...and so could not have been absorbed into a constant. The smallest
    capacitor on the block carried about four times the error of the largest,
    and a loop coefficient is a RATIO of two of them."""
    errs = []
    for scale in (0.25, 175.0):                  # cs/cf and ci
        ff = scale * _sized(A2.SAMPLING_CAP_FF_EXPR)
        area_only = ff / (CAREA * 10.0)
        got = A2.capacitance_ff(10.0, area_only, CAREA, CPERI)
        errs.append(abs(got - ff) / ff)
    assert max(errs) / min(errs) > 3.0, errs


def test_every_entry_that_sizes_a_capacitor_declares_the_constants_it_needs():
    """The entry can no longer be sized on a family that carries the area
    density and not the perimeter one, so it REFUSES BY NAME through the
    admission machinery it already had, instead of resolving a term to
    nothing and emitting a capacitor sized on a missing number.

    Derived, not spot-checked: every library entry whose device expressions
    name a constant must declare that constant, and this is the arm that
    catches the next one too."""
    for name, lib in A2.LIBRARY.items():
        exprs = " ".join(str(e.get("expr", ""))
                         for e in (lib.get("device_param_exprs") or []))
        for grp in (lib.get("stages") or {}).get("groups", []) \
                if isinstance(lib.get("stages"), dict) else []:
            exprs += " " + " ".join(str(e.get("expr", ""))
                                    for e in (grp.get("param_exprs") or []))
        declared = set(lib.get("requires_pdk_measured") or [])
        for const in ("cap_area_ff_per_um2", "cap_perim_ff_per_um"):
            if const in exprs:
                assert const in declared, (
                    f"library entry `{name}` sizes a device with `{const}` "
                    f"and does not declare it in requires_pdk_measured, so a "
                    f"family that carries no such constant would be sized "
                    f"against a name that resolves to nothing instead of "
                    f"being refused by name")


def test_the_delta_sigma_entry_declares_the_perimeter_constant():
    """The specific one this change added, pinned so a revert is loud."""
    assert "cap_perim_ff_per_um" in A2.LIBRARY["delta_sigma"][
        "requires_pdk_measured"]


# ── a capacitor smaller than its own fringe ──────────────────────────────
#
# The two-term model has a floor the area-only one did not: inverting
# C = carea*w*l + 2*cperi*(w+l) for `l` gives a NON-POSITIVE length exactly
# when the target is at or below 2*cperi*w — the capacitance a device of that
# WIDTH already has before it has any length. `C / (carea * w)` returns a
# small positive number there instead, so the old sizing could emit a
# capacitor nobody can build and nothing upstream of A5 would notice.

def _fringe_floor(w=10.0):
    return 2.0 * CPERI * w


def test_a_capacitor_below_its_own_fringe_is_refused_by_name():
    """RED, and the message names the CAUSE — the drawn width — not the
    symptom A5 would report six steps later ("below lmin")."""
    devices = [{"name": "ctiny", "role": "cap", "w": 10.0,
                "nets": ["a", "b"]}]
    target = _fringe_floor() * 0.875           # below the floor
    exprs = [{"device": "ctiny", "param": "l",
              "expr": f"({target} - 2*{CPERI}*10.0) / (({CAREA}*10.0) "
                      f"+ 2*{CPERI})"}]
    maxima = {"cap": {"max_length_um": LMAX, "max_width_um": WMAX}}
    minima = {"cap": {"min_width_um": LMIN}}
    measured = {"cap_area_ff_per_um2": CAREA, "cap_perim_ff_per_um": CPERI}
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, maxima, minima, measured)
    assert recs == []
    assert len(refusals) == 1, refusals
    why = refusals[0]
    assert "ctiny" in why
    assert "10.0u wide" in why, why
    assert "DRAWN WIDTH" in why, why
    assert devs == devices and out_exprs == exprs


def test_the_area_only_form_could_not_have_surfaced_it():
    """THE MUTATION ARM, and the reason this guard arrives WITH the two-term
    sizing rather than before it: for the same target the old expression
    returns a small POSITIVE length, so there was nothing to refuse."""
    target = _fringe_floor() * 0.875
    area_only = target / (CAREA * 10.0)
    two_term = (target - 2 * CPERI * 10.0) / (CAREA * 10.0 + 2 * CPERI)
    assert area_only > 0
    assert two_term <= 0


def test_every_capacitor_of_the_measured_blocks_clears_the_fringe_floor():
    """THE CONTROL. The guard must not fire on the designs this landing is
    measured on: the smallest capacitor on either block is 52 fF against a
    0.8 fF floor at the same drawn width, which is a factor of 65."""
    smallest_ff = 52.1178                       # cs / cf, both blocks
    assert smallest_ff > _fringe_floor() * 10, (smallest_ff, _fringe_floor())


def test_the_refusal_reaches_the_caller_as_a_named_exception():
    """It must STOP the topology, not be recorded beside it: an IR that
    reaches disk carrying one is a topology the flow goes on to draw, and the
    A2 gate measures vocabulary."""
    assert issubclass(A2.CapacitorNotRealisable, ValueError)
    exc = A2.CapacitorNotRealisable(["ctiny: too small"])
    assert exc.refusals == ["ctiny: too small"]
    assert "ctiny" in str(exc)


# ── the split on EVERY family that can reach it ─────────────────────────
#
# The split is measured end-to-end on one family, because one family is what
# u_hawaii_adc targets. The registry now states a capacitor ceiling for three,
# so the solver is LIVE on families no design has driven it with — and their
# numbers are not close: sky130A's perimeter density is four times
# ihp-sg13g2's, which is exactly the term the two-term solve turns on. This
# exercises it on each family's OWN constants and OWN ceiling, so "live but
# never exercised" is at least not true at the unit level.

def _family_numbers():
    """(family, carea, cperi, lmax, wmax, lmin) for every registry family that
    carries BOTH a capacitor ceiling and the measured constants to solve
    against. Derived — a family added to the registry later is covered with no
    change here."""
    import json as _json
    reg = _json.loads((PROGRAMS_JSON := A2.__file__.rsplit("/", 1)[0]
                       + "/pdk_registry.json") and open(PROGRAMS_JSON).read())

    def find(o, k):
        if isinstance(o, dict):
            if k in o:
                return o[k]
            for v in o.values():
                r = find(v, k)
                if r is not None:
                    return r
        return None

    out = []
    for ent in reg["pdks"]:
        name = ent.get("name")
        _f, roles = M.layout_maxima(name)
        lmax, wmax = M.max_length_um(roles, "cap"), M.max_width_um(roles, "cap")
        carea, cperi = find(ent, "cap_area_ff_per_um2"), find(ent, "cap_perim_ff_per_um")
        if lmax is None or carea is None:
            continue
        rec = (ent.get("analog_device_layout_maxima") or {}).get("roles", {})
        out.append((name, float(carea), float(cperi or 0.0), lmax, wmax,
                    rec.get("cap", {}).get("device")))
    return out


def test_the_split_holds_on_every_family_that_can_reach_it():
    """Each family's own constants, own ceiling, across the range: under it,
    exactly at it, just over, and far over."""
    fams = _family_numbers()
    assert len(fams) >= 2, (
        f"only {len(fams)} family can reach the split; this arm is meant to "
        f"cover the ones no design drives")
    for name, carea, cperi, lmax, wmax, device in fams:
        for l in (lmax * 0.1, lmax, lmax * 3.7, lmax * 21.0):
            n, lu, why = A2.unit_capacitor_split(
                10.0, l, max_l=lmax, max_w=wmax, min_l=None,
                carea=carea, cperi=cperi)
            assert n is not None, (name, l, why)
            assert lu <= lmax + 1e-9, (name, l, n, lu)
            assert lu > 0, (name, l, n, lu)
            target = A2.capacitance_ff(10.0, l, carea, cperi)
            got = n * A2.capacitance_ff(10.0, lu, carea, cperi)
            assert abs(got - target) <= A2.CAP_SPLIT_TOLERANCE * target, (
                name, l, n, lu, target, got)
            if l <= lmax:
                assert n == 1, (
                    f"{name}: a capacitor at or under the ceiling must not be "
                    f"split, and this one became {n} units")


def test_a_family_that_cannot_reach_the_split_is_excluded_by_MEASUREMENT():
    """The other half: a family carrying a ceiling but no measured
    capacitance constants cannot be solved for, and is left out of the set
    above by that fact rather than by a name in this file."""
    reachable = {f[0] for f in _family_numbers()}
    _fam, roles = M.layout_maxima("gf180mcuD")
    assert roles.get("cap"), "gf180mcuD should carry a ceiling"
    assert "gf180mcuD" not in reachable, (
        "gf180mcuD has no measured capacitance constants, so it must not be "
        "in the solvable set; if it now is, someone characterised it and this "
        "arm should be re-read rather than deleted")
