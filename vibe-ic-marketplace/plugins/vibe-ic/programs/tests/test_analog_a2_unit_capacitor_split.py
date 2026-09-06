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
    against is not a licence to guess one."""
    devices, exprs, maxima, minima, _measured = _ir_bits()
    devs, out_exprs, recs, refusals = A2.split_oversize_capacitors(
        devices, exprs, {}, maxima, minima, {})
    assert devs is devices and out_exprs is exprs
    assert recs == [] and refusals == []
