"""The A2 topology producer's first SPEC-BOUND library entry, and the
two-terminal blindness that stopped its netlist reaching A3.

WHAT WAS BROKEN, MEASURED ON A REAL RUN
=======================================
`analog_a2_topology_select_check` returned INCOMPLETE for a declared
`delta_sigma` block, and A3/A4/A5 were `derived-from-upstream` behind it,
because the circuit class sat in `LIBRARY_GAPS` under an UNCONDITIONAL
refusal:

    "the switched-capacitor integrator's capacitor ratio IS the loop
     coefficient, so the structure is not separable from the sizing"

Both halves of that are true. Together they name what the entry NEEDS — and
the block's own declaration bound every one of them (`order`, `osr`, `enob`,
`vref` all reached `phase3/analog/<block>/spec.json`) and reached nothing,
because a library entry had no way to be conditional.

THE PROPERTY EVERY TEST BELOW IS ABOUT
======================================
A topology emitted for this class must be a function of the DECLARATION, not
of the library. So the tests drive the producer with declarations that DIFFER
and assert the artefacts differ in the way the physics says they must:

  * the stage count follows `order`;
  * the sampling capacitor follows the sampled kT/C budget, so it moves by
    4x per bit of `enob`, by 1/`osr`, and by 1/`vref`**2;
  * cs/ci is the loop coefficient, and it is the coefficient set `order`
    selected.

An entry that merely EXISTS would pass a test that only checks a file was
written. None of these can be passed by a library default, because a library
default cannot move when the declaration does.

AND THE OTHER HALF: every refusal path is asserted too. A producer that
emits on a bound declaration and ALSO emits on an unbound one has not gained
a capability, it has lost a refusal.

BLOCKING vs ADVISORY
====================
Both subjects are BLOCKING at their own tier and the tests assert the rc:
`entry_admission` refusing returns rc 2 (`RC_HONEST_GAP`) with NO
`topology.md`, so the A2 gate keeps reporting the block uncovered rather than
passing a document written on defaults; `analog_netlist_connectivity_check`
returns rc 1 on a finding, which is what stopped A3 emitting at all.
"""
from __future__ import annotations

import json

import pytest

import _plugin_tree  # noqa: F401,E402  — puts programs/ on sys.path
import analog_a2_topology_emit as _A2M  # noqa: E402

#: The tolerance the sizing itself holds. Taken FROM the producer, not typed
#: here: these ratios are exact once the capacitor is sized on the PDK's own
#: model, and the number that bounds "exact" is the producer's own.
A2_TOL = _A2M.CAP_SPLIT_TOLERANCE

from _analog_producer_fixture import (
    A1, A2, A3, GATE_A2, NETLIST_CHECKERS, PROGRAMS, bdir, block,
    make_project, read_json, run_prog)
from _hostpaths import repo_path_opt

CONNECTIVITY = PROGRAMS / "analog_netlist_connectivity_check.py"

# A declaration SHAPED like the one this round was reported on — an
# incremental delta-sigma modulator whose Phase-1 table binds the loop order,
# the oversampling ratio, the target resolution and the reference. Every name
# and number here is invented; what is copied is only the SHAPE (the L5 label
# spellings a datasheet table actually carries, so `analog_a1_spec_emit`'s
# normalisation is exercised rather than bypassed).
BLK = "mod_alpha"


# ROUND 34 — `fclk_max` DEFAULTS TO 1.0, NOT 10.0, and the decade of range it
# used to declare is now asserted as a REFUSAL instead of silently carried.
# `settling_time_constants` is evaluated at the clock the emitted testbench
# runs at (`fclk_max`), and this topology's settling count is
# (fclk/fclk_max) * vref * slew_design_margin / integrator_input_overdrive_v
# = (fclk/fclk_max) * 13.33 against (enob+1)*ln2 = 10.40 -- so it tolerates a
# stated clock range of only 1.28x. A fixture declaring 0.1-10 MHz declares a
# converter this entry cannot serve, and the capability tests below cannot
# exercise a capability through a declaration that is refused.
#
# This is a SPLIT, not a narrowing: the refused declaration is asserted by
# name in `test_a_decade_of_clock_range_is_refused_because_it_cannot_settle`,
# and the measured evidence that it genuinely does not work is in that test's
# docstring. Nothing that used to be checked stopped being checked.
def ds_specs(order=2.0, osr=256.0, enob=14.0, vref=1.0, vref_unit="V",
             fclk=1.0, fclk_max=1.0, drop=()):
    rows = [
        {"name": "Order", "target": order, "unit": "—"},
        {"name": "OSR", "target": osr, "unit": "—"},
        {"name": "ENOB", "min": enob, "unit": "bit"},
        {"name": "Vref", "target": vref, "unit": vref_unit},
        {"name": "Vdd (core)", "target": 1.2, "unit": "V"},
        # ROUND 18: the entry now also needs the CLOCK, and specifically the
        # top of its declared range. An incremental modulator's integrator
        # has to settle inside a clock phase, and the fastest clock the
        # declaration admits is the corner it is held to — so a row that
        # states a target and no range no longer closes this entry, and the
        # block is refused by name instead of sized against a number nobody
        # declared.
        {"name": "fclk", "target": fclk, "min": 0.1, "max": fclk_max,
         "unit": "MHz"},
    ]
    return [r for r in rows if r["name"] not in drop]


def a2(tmp_path, name="p", pdk="ihp-sg13g2", **kw):
    """Drive A1 then A2 on a shaped declaration; return the block dir.

    ROUND 18 moved the default family from sky130A to ihp-sg13g2. The entry's
    slew bound is evaluated against the process's own MEASURED constants —
    among them the poly sheet resistance, which turns the drawn bias resistor
    into a current — and `pdk_analog_characterize.py` has measured that for
    ihp-sg13g2 and not for sky130A. The entry names the constant and refuses
    the uncharacterised family by name; that refusal has its own test below,
    so this change moves the fixture to a family the bound can be evaluated
    on rather than hiding what happens on one it cannot.
    """
    root = tmp_path / name
    root.mkdir()
    make_project(root, [block(BLK, "delta_sigma", ds_specs(**kw))])
    assert run_prog(A1, root).returncode == 0
    res = run_prog(A2, root, "--pdk", pdk)
    return bdir(root, BLK), res, root


# ── the capability ────────────────────────────────────────────────────────
def test_a_spec_bound_delta_sigma_block_gets_a_topology(tmp_path):
    """RED without the entry: the class was in LIBRARY_GAPS, so the block got
    `topology_gap.json` and never a topology."""
    d, res, _ = a2(tmp_path)
    assert res.returncode == 0, res.stderr
    assert (d / "topology.md").is_file()
    assert (d / "topology.json").is_file()
    assert not (d / "topology_gap.json").exists()


def test_the_emitted_topology_clears_the_a2_gate_with_the_block_name_removed(
        tmp_path):
    """The A2 gate measures VOCABULARY, and several block names are in its own
    panel. The document has to clear the floor on its own prose, so the block
    name is stripped before the gate sees it — the same guard the sibling
    suite holds every other entry to."""
    d, res, root = a2(tmp_path)
    assert res.returncode == 0
    md = d / "topology.md"
    md.write_text(md.read_text(encoding="utf-8").replace(BLK, "zzz"),
                  encoding="utf-8")
    assert run_prog(GATE_A2, root).returncode == 0


# ── the declaration reaches the STRUCTURE ─────────────────────────────────
def test_the_stage_count_follows_the_bound_order(tmp_path):
    """The device count is not a library constant. Two declarations that
    differ only in `order` must produce different circuits — which is the
    half of the old refusal that said the structure was undetermined."""
    d1, r1, _ = a2(tmp_path, "one", order=1.0)
    d2, r2, _ = a2(tmp_path, "two", order=2.0)
    assert r1.returncode == 0 and r2.returncode == 0
    ir1, ir2 = read_json(d1 / "topology.json"), read_json(d2 / "topology.json")
    assert ir1["stage_expansion"]["stages"] == 1
    assert ir2["stage_expansion"]["stages"] == 2
    assert len(ir2["devices"]) > len(ir1["devices"])
    # ...and the chain is wired end to end on both, so the extra stage is
    # connected and not merely present.
    assert ir1["stage_expansion"]["chain"][0] == "vin"
    # Round 17: the cascade ends on `vint`, an INTERNAL net, not on `vout`.
    # The entry closed the loop — the last integrator drives a quantiser on
    # the same block, and the block's declared output is that quantiser's
    # 1-bit decision (`bit_out`) — so ending the chain on a PORT would be
    # exposing the loop filter's output as the modulator's. What this
    # assertion is for is unchanged: the chain is wired end to end, so the
    # extra stage is connected and not merely present. The terminal name is
    # READ from the entry rather than retyped, so the next entry that moves
    # it does not have to move this line too.
    _last = ir1["stage_expansion"]["chain"][-1]
    assert _last not in ir1["ports"]
    assert _last in ir1["internal_nets"]
    assert ir2["stage_expansion"]["chain"] == ["vin", "vo1", _last]


def test_each_stage_carries_the_coefficient_its_order_selected(tmp_path):
    d, res, _ = a2(tmp_path)
    assert res.returncode == 0
    ir = read_json(d / "topology.json")
    coeffs = ir["stage_expansion"]["coefficients"]
    assert len(coeffs) == ir["stage_expansion"]["stages"]
    assert all(0.0 < c <= 1.0 for c in coeffs)
    # every stage's integrating capacitor is derived from its OWN coefficient
    per_stage = {e["stage"]: e for e in ir["device_param_exprs"]
                 if e["param"] == "l" and e["device"].startswith("ci")}
    assert set(per_stage) == set(range(1, len(coeffs) + 1))
    for i, c in enumerate(coeffs, start=1):
        assert per_stage[i]["coefficient"] == c


def test_the_stage_count_is_reported_as_bound_from_the_spec(tmp_path):
    """A structure that followed from a declaration must not be recorded as
    one with nothing bound — `fields_bound` is what a reader and the A3
    content rule both go by."""
    d, res, _ = a2(tmp_path)
    assert res.returncode == 0
    ir = read_json(d / "topology.json")
    assert "order" in ir["_provenance"]["fields_bound"]
    assert ir["selection_basis"] == "block_type_and_spec"


# ── the declaration reaches the DEVICE GEOMETRY ───────────────────────────
def _cap_lengths(root, d):
    """Render the netlist and read back each capacitor's CAPACITANCE in fF,
    on the PDK's own two-term model, with a UNIT ARRAY summed into the single
    device it realises.

    IT USED TO RETURN LENGTHS, and every assertion below is about a
    capacitor RATIO — a loop coefficient, a resolution, an oversampling
    factor. Under the old AREA-ONLY sizing those were the same statement,
    because capacitance was proportional to length. They are not the same
    statement under the PDK's real model, where the fringe term is a larger
    share of a small capacitor than of a large one: on this block the two
    ends differ by about 1.5%, so a length ratio and a capacitance ratio are
    two different numbers and only the second is what the prose below claims.
    Returning capacitance makes each assertion say what it always meant, and
    makes it EXACT rather than approximately right.

    A capacitor the target PDK cannot draw at the length this library sizes it
    to is emitted as N unit devices in parallel
    (`analog_a2_topology_emit.split_oversize_capacitors`), so the netlist
    carries `ci1_u0 .. ci1_u20` where it used to carry `ci1`. The properties
    asserted below are about the CAPACITOR, not about how many pieces it is
    drawn in, so the units are summed. That also fails loudly if the split
    ever stops preserving the value."""
    assert run_prog(A3, root, "--pdk", "sky130A").returncode == 0
    text = (d / f"{BLK}.sp").read_text(encoding="utf-8")
    import re as _re
    import analog_a2_topology_emit as _a2
    import pdk_analog_layout_minima as _m
    _fam, _ent = _m.resolve_family("ihp-sg13g2")

    def _const(key):
        def find(o):
            if isinstance(o, dict):
                if key in o:
                    return o[key]
                for v in o.values():
                    r = find(v)
                    if r is not None:
                        return r
            return None
        return find(_ent)

    carea = _const("cap_area_ff_per_um2") or 1.0
    cperi = _const("cap_perim_ff_per_um") or 0.0
    out = {}
    for ln in text.splitlines():
        toks = ln.split()
        if not toks or not toks[0].startswith("x") or "cap" not in ln:
            continue
        name = toks[0][1:]
        w = l = None
        for t in toks:
            if t.startswith("l="):
                l = float(t[2:].rstrip("u"))
            elif t.startswith("w="):
                w = float(t[2:].rstrip("u"))
        if l is None or w is None:
            continue
        m = _re.match(r"^(.*)_u\d+$", name)
        base = m.group(1) if m else name
        out[base] = out.get(base, 0.0) + _a2.capacitance_ff(w, l, carea, cperi)
    return out


def test_the_sampling_capacitor_follows_the_declared_resolution(tmp_path):
    """Sampled kT/C noise against the quantisation floor: one bit of ENOB is
    4x the capacitance. Two bits is 16x, and a library default is 1x."""
    d14, _, r14 = a2(tmp_path, "e14", enob=14.0)
    d12, _, r12 = a2(tmp_path, "e12", enob=12.0)
    c14, c12 = _cap_lengths(r14, d14), _cap_lengths(r12, d12)
    assert c14["cs1"] == pytest.approx(c12["cs1"] * 16.0, rel=A2_TOL)


def test_the_sampling_capacitor_follows_the_declared_oversampling(tmp_path):
    """Oversampling spreads the sampled noise, so it buys the capacitance
    back one for one."""
    d_hi, _, r_hi = a2(tmp_path, "o256", osr=256.0)
    d_lo, _, r_lo = a2(tmp_path, "o64", osr=64.0)
    c_hi, c_lo = _cap_lengths(r_hi, d_hi), _cap_lengths(r_lo, d_lo)
    assert c_lo["cs1"] == pytest.approx(c_hi["cs1"] * 4.0, rel=1e-3)


def test_the_sampling_capacitor_follows_the_declared_reference(tmp_path):
    """The LSB is measured against the reference, so the budget goes as
    1/Vref**2.

    SWEPT ACROSS THE DECLARED Vref RANGE (0.8-1.2), not across 1.0/0.5 as it
    was. `settling_time_constants` refuses vref 0.5 at enob 14 -- the
    slew-derived bias delivers 6.67 time constants against the 10.40 that
    resolution needs -- so the old low point declared a converter that does
    not settle, and the capability could not be exercised through it. The
    ASSERTION is unchanged in kind and the ratio is still exact: (1.2/0.8)**2
    = 2.25. The refused point is not dropped, it is asserted as a refusal in
    `test_a_reference_too_small_to_settle_the_declared_resolution_is_refused`
    below, so the population is split rather than narrowed.
    """
    d1, _, r1 = a2(tmp_path, "v12", vref=1.2)
    d2, _, r2 = a2(tmp_path, "v08", vref=0.8)
    c1, c2 = _cap_lengths(r1, d1), _cap_lengths(r2, d2)
    assert c2["cs1"] == pytest.approx(c1["cs1"] * 2.25, rel=1e-3)


def test_a_decade_of_clock_range_is_refused_because_it_cannot_settle(tmp_path):
    """The declaration this fixture used to carry by default: fclk 1.0 MHz over
    a stated 0.1-10 MHz range.

    MEASURED end to end, on the real block and reproduced to six decimals on
    two hosts by two independent lanes: the emitted deck runs the modulator at
    `fclk_max` (100 ns period -- the deck's own condition line calls it "the
    binding settling corner"), holds the input one tenth of the reference above
    mid-scale, and states that the mean of the 1-bit output "must be 0.5 plus
    the input's fraction of the reference span -- 0.6 here". It measures
    density 0.462028 with swing 1.04976: below mid-scale for an input above it,
    with the quantiser toggling rather than latched. The converter does not
    carry its input code.

    The settling count at that clock is (1/10) * 13.33 = 1.33 against the 10.40
    that enob 14 needs. Emitting a topology here would render a modulator whose
    bitstream carries no code, so the entry refuses instead.
    """
    d, res, _ = a2(tmp_path, "decade", fclk=1.0, fclk_max=10.0)
    assert res.returncode == 2
    g = _gap(d)
    bad = [r for r in g["admission_refusals"]
           if r.get("field") == "settling_time_constants"]
    assert bad, g["admission_refusals"]
    assert bad[0]["value"] == pytest.approx(1.3333333, rel=1e-5)
    assert float(bad[0]["min"]) == pytest.approx(10.3972077, rel=1e-6)


def test_a_reference_too_small_to_settle_the_declared_resolution_is_refused(
        tmp_path):
    """The low point the sweep above used to run at, kept as a REFUSAL rather
    than dropped. At vref 0.5 the slew-derived bias delivers 6.67 settling
    time constants against the 10.40 that enob 14 needs, so the converter
    slews to the answer and never settles on it. Emitting a topology here
    would render a modulator whose bitstream carries no code."""
    d, res, _ = a2(tmp_path, "v05", vref=0.5)
    assert res.returncode == 2
    g = _gap(d)
    bad = [r for r in g["admission_refusals"]
           if r.get("field") == "settling_time_constants"]
    assert bad, g["admission_refusals"]
    assert bad[0]["value"] < float(bad[0]["min"])


def test_the_capacitor_ratio_is_the_loop_coefficient(tmp_path):
    """The claim the old refusal turned on. cs/ci must BE the coefficient the
    order selected, on every stage."""
    d, _, root = a2(tmp_path)
    caps = _cap_lengths(root, d)
    ir = read_json(d / "topology.json")
    for i, coeff in enumerate(ir["stage_expansion"]["coefficients"], start=1):
        # EXACT now, not approximately right: it is a ratio of capacitances,
        # which is what the claim has always been about, and the sizing
        # realises each one on the PDK's own model.
        assert caps[f"cs{i}"] / caps[f"ci{i}"] == pytest.approx(
            coeff, rel=A2_TOL), (i, caps[f"cs{i}"], caps[f"ci{i}"])


def test_a_capacitor_above_the_pdk_maximum_is_emitted_as_a_unit_array(
        tmp_path):
    """END TO END through the real A2 and the real A3, on the family whose
    registry record states a capacitor maximum.

    MEASURED before this: the PDK's gencell CLAMPS a capacitor above `lmax`
    and draws it, so twelve netlist capacitors became two drawn cells, the
    largest 21x smaller than the netlist asks for, and only the sign-off LVS
    noticed — six steps later. The netlist must now carry the array, so that
    the netlist and the layout agree device for device."""
    d, _, root = a2(tmp_path)
    ir = read_json(d / "topology.json")
    rec = ir["_provenance"]["layout_maxima"]
    assert rec["maxima_available"] is True
    arrays = {a["device"]: a for a in rec["capacitor_arrays"]}
    assert arrays, "no capacitor was split on a family that states a maximum"
    assert rec["refusals"] == []
    lmax = rec["roles"]["cap"]["max_length_um"]
    for name, a in arrays.items():
        assert a["units"] >= 2 and a["unit_l_um"] <= lmax, (name, a)
        assert a["library_l_um"] > lmax, (name, a)
        assert a["relative_value_error"] <= a["tolerance"], (name, a)
        assert a["relative_value_error"] < 1e-9, (name, a)

    assert run_prog(A3, root, "--pdk", "sky130A").returncode == 0
    text = (d / f"{BLK}.sp").read_text(encoding="utf-8")
    for name, a in arrays.items():
        units = [ln for ln in text.splitlines()
                 if ln.split() and ln.split()[0].startswith(f"x{name}_u")]
        assert len(units) == a["units"], (name, len(units), a["units"])
        nets = {tuple(ln.split()[1:3]) for ln in units}
        assert len(nets) == 1, (
            f"{name}'s units must be in PARALLEL — one pair of nets, not "
            f"{len(nets)}")
        assert not [ln for ln in text.splitlines()
                    if ln.split() and ln.split()[0] == f"x{name}"], (
            f"the un-drawable single device {name} is still in the netlist "
            f"beside its own array")


def test_every_capacitor_realises_the_multiple_its_entry_declares(tmp_path):
    """EVERY capacitor, not the two a ratio test happened to cover.

    The sizing was rewritten from "a multiple of another capacitor's LENGTH"
    to "a multiple of the sampling CAPACITANCE, converted once" — seven
    expressions, of which only `cs` and `ci` had any value coverage. A typo in
    any of the other five (a dropped factor, the wrong sub-expression wrapped)
    would put a wrong capacitor in the netlist and every test would still
    pass.

    So each one is checked against the multiple its OWN entry declares, read
    out of the IR rather than restated here, and measured on the PDK's own
    two-term model. Exact, because that is what the conversion buys."""
    d, _, root = a2(tmp_path)
    caps = _cap_lengths(root, d)                     # capacitance, in fF
    ir = read_json(d / "topology.json")
    env = {}
    env.update({k: v for k, v in (ir.get("pdk_measured_params") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)})
    env.update(ir.get("constants") or {})
    env.update({k: v for k, v in (ir.get("knobs") or {}).items()
                if isinstance(v, (int, float))})
    # ...and the BOUND SPEC VALUES last, which is the order
    # `analog_a3_netlist_emit._resolve_params` seeds its own environment in.
    # Seeding it any other way would be a second, private answer to "what does
    # this expression resolve to", which is the thing this test exists to
    # check against.
    env.update(_A2M.bound_spec_values(root, BLK)[0])
    coeffs = ir["stage_expansion"]["coefficients"]
    cs = caps["cs1"]

    expected = {}
    for i, coeff in enumerate(coeffs, start=1):
        expected[f"cs{i}"] = 1.0
        expected[f"ci{i}"] = 1.0 / coeff
        expected[f"cc{i}"] = env["miller_fraction_of_load"] / coeff
        expected[f"cf{i}"] = 1.0
    expected["caz"] = env["autozero_over_sampling_cap"]
    expected["c_vcm"] = 40.0
    expected["c_cmc"] = (env["miller_fraction_of_load"]
                         * _A2M._safe_eval(_A2M._LOAD_OVER_CS_DERIVED_EXPR,
                                           dict(env)))

    missing = sorted(set(expected) - set(caps))
    assert not missing, f"the netlist carries no capacitor for {missing}"
    # `c_qdly` is the one capacitor this entry does NOT size from the
    # sampling capacitance: it carries a library-nominal `l` and has no
    # `device_param_exprs` entry at all, so there is no declared multiple to
    # check it against. Excluded by that PROPERTY, read off the IR, rather
    # than by name — a device that later gains an expression stops being
    # excluded and starts being checked.
    sized = {e["device"] for e in (ir.get("device_param_exprs") or [])}
    for grp in (ir.get("stage_expansion") or {}).get("groups", []) or []:
        sized |= {e["device"] for e in (grp.get("param_exprs") or [])}
    unchecked = sorted((set(caps) & sized) - set(expected))
    assert not unchecked, (
        f"these capacitors are SIZED by an expression and this test says "
        f"nothing about their value: {unchecked}")
    assert "c_qdly" in caps and "c_qdly" not in sized, (
        "c_qdly is expected to be the library-nominal capacitor; if it has "
        "gained a sizing expression it now needs a declared multiple here")
    for name, mult in sorted(expected.items()):
        assert caps[name] / cs == pytest.approx(mult, rel=A2_TOL), (
            f"{name} realises {caps[name] / cs:.6g} x the sampling capacitor "
            f"and its entry declares {mult:.6g} x")


def test_a3_records_the_netlist_as_design_bound_not_structure_only(tmp_path):
    """The acceptance property. `structure_only` is A3's honest ceiling for a
    deck whose circuit class came from the library with NO bound spec value
    reaching a device parameter — which is what the sibling block in the
    reported run got. A spec-bound entry must clear it."""
    d, _, root = a2(tmp_path)
    assert run_prog(A3, root, "--pdk", "sky130A").returncode == 0
    prov = read_json(d / "netlist_provenance.json")["_provenance"]
    assert prov["design_content"] == "structure_and_geometry"
    assert prov["spec_bound_params"], "no device parameter is spec-bound"


# ── the refusals ──────────────────────────────────────────────────────────
def _gap(d):
    assert not (d / "topology.md").exists(), "a refusal must emit NO topology"
    return read_json(d / "topology_gap.json")


@pytest.mark.parametrize("label,kw,unmet", [
    ("the oversampling ratio is not declared", {"drop": ("OSR",)}, "osr"),
    ("the resolution is not declared", {"drop": ("ENOB",)}, "enob"),
    ("the reference is not declared", {"drop": ("Vref",)}, "vref"),
    ("the order is not declared", {"drop": ("Order",)}, "order"),
])
def test_an_unbound_sizing_input_is_refused_BY_NAME(tmp_path, label, kw,
                                                    unmet):
    """An entry that emitted here would produce a document the A2 gate cannot
    tell from a real selection, because that gate measures vocabulary. And
    saying only that something was missing is not actionable — the gap has to
    name WHICH."""
    d, res, _ = a2(tmp_path, "p", **kw)
    assert res.returncode == 2, f"{label}: expected the honest-gap rc"
    g = _gap(d)
    assert g["status"] == "ENTRY_REQUIREMENTS_NOT_MET"
    assert unmet in g["unmet_requirements"], (label, g["unmet_requirements"])
    assert g["library_entry_exists"] is True


def test_an_order_with_no_coefficient_set_is_refused_not_approximated(
        tmp_path):
    """A third-order single-bit loop is stable only under a coefficient set
    that is a design solution rather than a fixed structure. Selecting the
    nearest admitted order would emit another design's document under this
    one's name."""
    d, res, _ = a2(tmp_path, "p", order=3.0)
    assert res.returncode == 2
    g = _gap(d)
    assert "order" in g["unmet_requirements"]
    assert any(r["requirement"] == "domain" for r in g["admission_refusals"])


def test_a_unit_the_expressions_do_not_assume_is_refused_not_scaled(tmp_path):
    """The expression environment carries no units, so a row declared in mV
    would be read as volts and scale the answer by 1000 with nothing recording
    it. The refusal is the only safe answer available."""
    d, res, _ = a2(tmp_path, "p", vref=1000.0, vref_unit="mV")
    assert res.returncode == 2
    g = _gap(d)
    kinds = {r["requirement"] for r in g["admission_refusals"]}
    assert "spec_unit" in kinds, g["admission_refusals"]


def test_a_process_with_no_measured_capacitance_is_refused_not_defaulted(
        tmp_path):
    """`_resolve_params` drops an expression over an unknown name SILENTLY, so
    an uncharacterised process would emit a library nominal with nothing
    saying it was never sized. The entry declares the constant it needs and
    stands down instead."""
    d, res, _ = a2(tmp_path, "p", pdk="gf180mcuD")
    assert res.returncode == 2
    g = _gap(d)
    kinds = {r["requirement"] for r in g["admission_refusals"]}
    assert "pdk_measured" in kinds, g["admission_refusals"]
    assert any("characterize" in str(r.get("remedy", ""))
               for r in g["admission_refusals"])


def test_a_declaration_whose_budget_is_undrawable_is_refused(tmp_path):
    """An admission condition on the INPUTS cannot see that a legal-looking
    declaration derives a device nobody can draw. A resolution this high asks
    for a capacitor outside the admitted range, and saying so IS the answer."""
    d, res, _ = a2(tmp_path, "p", enob=28.0)
    assert res.returncode == 2
    g = _gap(d)
    assert any(r["requirement"] == "derived_range"
               for r in g["admission_refusals"]), g["admission_refusals"]


def test_a_refusal_still_names_the_skill_that_takes_over(tmp_path):
    d, res, _ = a2(tmp_path, "p", drop=("OSR",))
    g = _gap(d)
    assert g["ai_handoff"]["skill"] == "analog-topology-select"
    assert g["how_to_close"]


# ── the entries that declare NO requirement must be untouched ─────────────
def test_an_entry_with_no_requirements_is_unaffected(tmp_path):
    """Every pre-existing entry declares no admission condition, so it must
    take the identical path it always did — emitted, with no stage expansion
    and no admission refusal."""
    root = tmp_path / "old"
    root.mkdir()
    make_project(root, [block("vreg_alpha", "ldo", [
        {"name": "Vout", "target": 1.8, "unit": "V"},
        {"name": "Iout", "target": 0.5, "unit": "mA"}])])
    assert run_prog(A1, root).returncode == 0
    assert run_prog(A2, root, "--pdk", "ihp-sg13g2").returncode == 0
    ir = read_json(bdir(root, "vreg_alpha") / "topology.json")
    assert ir["stage_expansion"] is None
    assert ir["_provenance"]["admission"]["requires_bound"] == []
    # ...and its DOWNSTREAM disposition is unchanged too. This entry's only
    # spec knob is written over `vref`, which an LDO block declaration does
    # not carry, so every bound value reaches zero device parameters and A3
    # certifies it at the STRUCTURE-ONLY tier. That is a pre-existing,
    # separately-recorded defect; what this asserts is that the change above
    # did not move it in either direction — neither silently repairing it nor
    # making it worse.
    assert run_prog(A3, root, "--pdk", "sky130A").returncode == 0
    prov = read_json(bdir(root, "vreg_alpha")
                     / "netlist_provenance.json")["_provenance"]
    assert prov["design_content"] == "structure_only"
    assert prov["spec_bound_params"] == []


def test_a_class_with_no_entry_at_all_is_still_told_apart_from_a_refusal(
        tmp_path):
    """Two different gaps that a reader must not confuse: a class nobody
    authored is closed by AUTHORING a topology; a spec-bound entry that stood
    down is closed by BINDING a spec row."""
    root = tmp_path / "none"
    root.mkdir()
    make_project(root, [block("ref_alpha", "bandgap", None)])
    run_prog(A1, root)
    res = run_prog(A2, root, "--pdk", "ihp-sg13g2")
    assert res.returncode == 2
    g = read_json(bdir(root, "ref_alpha") / "topology_gap.json")
    assert g["status"] == "NO_TOPOLOGY_IN_LIBRARY"
    assert g["library_entry_exists"] is False
    assert g["unmet_requirements"] == []


# ── the round trip, in the reported run's own shape ───────────────────────
def test_a_stale_topology_cannot_survive_a_declaration_it_no_longer_supports(
        tmp_path):
    """The shape the blocker was reported in — one covered block beside one
    that is not — driven forwards and then backwards.

    The backwards half is the one that matters. If a `topology.md` emitted
    under a declaration the entry CAN support were left on disk after the
    declaration changed to one it cannot, the A2 gate would keep passing on a
    document nothing supports any more. That is a flow that lies, and it is
    the failure mode a producer that only ever ADDS artefacts walks into.
    """
    root = tmp_path / "rt"
    root.mkdir()
    make_project(root, [
        block(BLK, "delta_sigma", ds_specs()),
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
    ])
    assert run_prog(A1, root).returncode == 0
    assert run_prog(A2, root, "--pdk", "ihp-sg13g2").returncode == 0
    assert (bdir(root, BLK) / "topology.md").is_file()
    assert run_prog(GATE_A2, root).returncode == 0, "the gate should be clean"

    # the declaration changes to an order this entry carries no set for
    make_project(root, [
        block(BLK, "delta_sigma", ds_specs(order=3.0)),
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
    ])
    assert run_prog(A1, root).returncode == 0
    run_prog(A2, root, "--pdk", "ihp-sg13g2")

    assert not (bdir(root, BLK) / "topology.md").exists(), (
        "a topology the declaration no longer supports survived")
    assert (bdir(root, BLK) / "topology_gap.json").is_file()
    res = run_prog(GATE_A2, root)
    assert res.returncode == 1, "the gate must go red again, and BLOCK"
    # the gate writes its verdict line to stderr, so read BOTH streams rather
    # than assume which one — an assertion on the wrong stream reads as a
    # missing verdict and blames the subject for the reader's mistake.
    assert "INCOMPLETE" in (res.stdout + res.stderr)
    # ...and the sibling block is untouched by the refusal
    assert (bdir(root, "vreg_alpha") / "topology.md").is_file()


# ── the library cannot be authored into either failure ────────────────────
def test_the_shipped_library_holds_its_own_authoring_invariants():
    """A stage template whose count field is not in `requires_bound` reaches
    expansion instead of being refused, and an admitted order with no
    coefficient set would be emitted on a default — one design's coefficients
    under another design's name. Both are AUTHORING mistakes, so they are
    caught here rather than by a reviewer remembering."""
    import analog_a2_topology_emit as m
    assert m.library_invariants() == []


def test_the_invariant_check_is_not_vacuous():
    """The check above passes on a clean library, which is also what a check
    that measures nothing does. Break each rule and it must object — a
    library the checker cannot fault is a checker, not a library."""
    import analog_a2_topology_emit as m
    import copy
    broken = copy.deepcopy(
        {k: v for k, v in m.LIBRARY.items() if v.get(m.STAGE_KEY)})
    assert broken, "no entry declares a stage; this test measures nothing"

    no_req = copy.deepcopy(broken)
    for e in no_req.values():
        e[m.REQUIRES_BOUND_KEY] = {}
    assert m.library_invariants(no_req), "an unbound count field went unseen"

    # An entry supplies coefficients EITHER as a table or as a derivation.
    # Both mechanisms are broken here, and so is having neither.
    no_set = copy.deepcopy(broken)
    for e in no_set.values():
        e[m.COEFFICIENT_SETS_KEY] = {}
        e.pop(m.COEFFICIENT_DERIVATION_KEY, None)
    assert m.library_invariants(no_set), (
        "an entry with neither a coefficient table nor a derivation went "
        "unseen")

    bad_deriv = copy.deepcopy(broken)
    for e in bad_deriv.values():
        e[m.COEFFICIENT_DERIVATION_KEY] = "no_such_derivation"
    assert m.library_invariants(bad_deriv), (
        "a coefficient derivation naming nothing this program carries went "
        "unseen")

    stale_load = copy.deepcopy(broken)
    for e in stale_load.values():
        if e.get(m.COEFFICIENT_DERIVATION_KEY):
            e.setdefault("constants", {})["load_over_sampling_cap"] = 2.6
    assert m.library_invariants(stale_load), (
        "an entry that DERIVES its coefficients and still states the OTA "
        "load ratio as a constant went unseen — the ratio is "
        "(1 + miller) / coefficient and follows osr with it")

    wrong_len = copy.deepcopy(broken)
    for e in wrong_len.values():
        e.pop(m.COEFFICIENT_DERIVATION_KEY, None)
        e[m.COEFFICIENT_SETS_KEY] = {"1": [0.5], "2": [0.5]}
    assert m.library_invariants(wrong_len), (
        "a coefficient set with the wrong number of stages went unseen")


# ── the netlist checker's two-terminal blindness ──────────────────────────
_CAP_ONLY_PORT = """\
* a port that reaches the circuit ONLY through a 2-terminal device
.subckt blk vdd vss vin vout
xc_in  vin nsum   some_cap_model w=10 l=2
xm_a   vout nsum vss vss some_nfet_model w=1 l=1
xm_b   vout nsum vdd vdd some_pfet_model w=1 l=1
.ends blk
"""

_CAP_SECOND_PIN = """\
* an internal net whose only second pin is a 2-terminal device
.subckt blk vdd vss vin vout
xm_a   nmid vin vss vss some_nfet_model w=1 l=1
xc_f   nmid vout  some_cap_model w=10 l=2
xm_b   vout vin vdd vdd some_pfet_model w=1 l=1
.ends blk
"""


@pytest.mark.parametrize("label,deck", [
    ("a port connected only through a capacitor", _CAP_ONLY_PORT),
    ("a net whose second pin is a capacitor", _CAP_SECOND_PIN),
])
def test_a_two_terminal_device_is_a_connection(tmp_path, label, deck):
    """RED without the fix, and it is rc 1 — BLOCKING. The checker required
    three nets plus a model, so a capacitor parsed as nothing and was counted
    by nothing; both of its rules then read that absence as a defect. Which is
    every switched-capacitor circuit, whose defining feature is that the
    signal enters through a capacitor."""
    root = tmp_path / "conn"
    (root / "analog/blk").mkdir(parents=True)
    (root / "analog/blk/blk.sp").write_text(deck, encoding="utf-8")
    res = run_prog(CONNECTIVITY, root)
    assert res.returncode == 0, f"{label}: {res.stdout}\n{res.stderr}"


def test_the_emitted_delta_sigma_netlist_passes_every_shipped_checker(
        tmp_path):
    """The end of the chain: A1 -> A2 -> A3 -> the checkers A3 itself runs
    before it will emit. This is what the two-terminal blindness stopped."""
    d, _, root = a2(tmp_path)
    assert run_prog(A3, root, "--pdk", "sky130A").returncode == 0
    assert (d / f"{BLK}.sp").is_file(), "A3 emitted no netlist"
    for chk in NETLIST_CHECKERS:
        res = run_prog(chk, root)
        assert res.returncode in (0, 2), (
            f"{chk.name} rejected the emitted netlist:\n{res.stdout}")


# ── a real, checked-in artefact (vibe-ic#400) ─────────────────────────────
_REAL_DECKS = [
    repo_path_opt("docs/research/fleet_run_folder_triage_evidence/121/"
                  "_c3_adc_scratch", d)
    for d in ("a3incl", "a3runnable", "a3lib")]


@pytest.mark.parametrize("root", _REAL_DECKS,
                         ids=lambda p: p.name if p else "unresolved")
def test_the_checked_in_analog_decks_keep_their_verdict(root):
    """Corpus control for the connectivity change, driven by an artefact this
    change did not author: three `.sp` trees checked into the repo from a real
    run. The fix can only make MORE pins visible, so it must not move a
    verdict on a deck that already had one — and these three carry a genuine
    pre-existing FLOATING_NODE, so they are a live signal and not a silent
    pass. If this ever goes green, the checker stopped seeing something."""
    if root is None or not (root / "phase3/analog").is_dir():
        pytest.skip("checked-in analog evidence tree not in this checkout")
    res = run_prog(CONNECTIVITY, root)
    assert res.returncode == 1
    assert "FLOATING_NODE" in res.stdout
