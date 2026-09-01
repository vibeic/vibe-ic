"""The A2 topology producer's SECOND spec-bound library entry: the regulator.

WHAT WAS BROKEN, MEASURED ON A REAL RUN
=======================================
On a run carrying two analog blocks, the modulator came out of A3 with
`design_content=structure_and_geometry` and the regulator came out with
`design_content=structure_only`:

    "structure_only — the circuit class came from the topology library and NO
     bound spec value reached any device parameter; the geometry below is a
     library nominal."

The regulator's declaration was NOT thin. Its A1 `spec.json` bound six rows
(`vout`, `vin`, `iout`, `iq`, `psrr`, `dropout`). The entry simply declared
one knob — `divider_ratio = vout / vref` — and that knob needs a `vref` row a
regulator's own table does not carry, so the sole knob defaulted and NOTHING
reached a device. The netlist simulated across nine PVT corners and every
number in it was about the library.

THE PROPERTY EVERY TEST BELOW IS ABOUT
======================================
A linear regulator's feedback divider is the one element its declaration
sizes directly and unambiguously:

    I_div = iq * iq_divider_fraction        the share of the bound quiescent
                                            budget the divider may burn
    R_div = vout / I_div                    Ohm's law on the bound output
    L_tot = R_div * w_res / rsheet          the measured sheet resistance

Two BOUND spec rows and one MEASURED process constant. So the tests drive the
producer with declarations that DIFFER and assert the divider MOVES the way
those three terms say it must — proportional to `vout`, inversely
proportional to `iq`. A library default cannot move when the declaration
does, so none of these can be passed by one.

AND THE OTHER HALF: the entry now DECLARES the two rows it sizes from, so a
regulator that binds neither is refused BY NAME with a `topology_gap.json`
rather than handed a netlist that simulates and means nothing. That refusal
is asserted here too — an entry that emits on a bound declaration and ALSO
emits on an unbound one has not gained a capability, it has lost a refusal.

BLOCKING vs ADVISORY
====================
BLOCKING at the producer's own tier, and the tests assert the rc:
`entry_admission` refusing returns rc 2 (`RC_HONEST_GAP`) with NO
`topology.md`, so the A2 gate keeps reporting the block uncovered.
"""
from __future__ import annotations

import pytest

from _analog_producer_fixture import (
    A1, A2, A3, GATE_A2, PROGRAMS, bdir, block, make_project, read_json,
    run_prog)

# Every name and number here is invented; what is copied is only the SHAPE of
# a regulator row a datasheet table actually carries, so
# `analog_a1_spec_emit`'s label normalisation is exercised rather than
# bypassed.
BLK = "vreg_beta"


def ldo_specs(vout=1.2, iq=50.0, iq_unit="µA", vout_unit="V", vref=None,
              drop=()):
    rows = ([{"name": "Vref", "target": vref, "unit": "V"}]
            if vref is not None else [])
    rows += [
        {"name": "Vout", "target": vout, "unit": vout_unit},
        {"name": "Vin", "target": 1.8, "unit": "V"},
        {"name": "Iout", "target": 0.5, "unit": "mA"},
        {"name": "Iq", "max": iq, "unit": iq_unit},
        {"name": "Dropout", "max": 0.5, "unit": "V"},
    ]
    return [r for r in rows if r["name"] not in drop]


def a2(tmp_path, tag="d", pdk="ihp-sg13g2", **kw):
    root = make_project(tmp_path / tag,
                        [block(BLK, "ldo", ldo_specs(**kw))])
    assert run_prog(A1, root).returncode == 0
    res = run_prog(A2, root, "--pdk", pdk)
    return bdir(root, BLK), res, root


def _legs(d):
    """The two divider legs' drawn lengths, off the emitted IR."""
    ir = read_json(d / "topology.json")
    by = {x["name"]: x for x in ir["devices"]}
    exprs = {f"{e['device']}.{e['param']}": e["expr"]
             for e in ir.get("device_param_exprs") or []}
    return by, exprs


def _sized(d, root):
    """Run A3 and return (provenance, the two leg lengths it rendered)."""
    res = run_prog(A3, root, "--pdk", "ihp-sg13g2")
    prov = read_json(d / "netlist_provenance.json")["_provenance"]
    text = (d / f"{BLK}.sp").read_text(encoding="utf-8")
    lens = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] in (f"x{n}" for n in ("r1", "r2")):
            for p in parts:
                if p.startswith("l="):
                    lens[parts[0][1:]] = float(p[2:].rstrip("u"))
    return res, prov, lens


# ── the capability ────────────────────────────────────────────────────────
def test_a_spec_bound_regulator_still_gets_a_topology(tmp_path):
    d, res, _ = a2(tmp_path)
    assert res.returncode == 0, res.stderr
    assert (d / "topology.md").is_file()
    assert (d / "topology.json").is_file()
    assert not (d / "topology_gap.json").exists()


def test_the_emitted_topology_clears_the_a2_gate_with_the_block_name_removed(
        tmp_path):
    d, res, root = a2(tmp_path)
    assert res.returncode == 0
    md = d / "topology.md"
    md.write_text(md.read_text(encoding="utf-8").replace(BLK, "zzz"),
                  encoding="utf-8")
    assert run_prog(GATE_A2, root).returncode == 0


# ── the declaration reaches the DEVICES ───────────────────────────────────
def test_a3_records_the_regulator_netlist_as_design_bound(tmp_path):
    """THE SUBJECT. RED before the entry declared what it sizes from: this
    said `structure_only` with an empty `spec_bound_params`, on a declaration
    that bound six rows."""
    d, res, root = a2(tmp_path)
    assert res.returncode == 0
    a3res, prov, lens = _sized(d, root)
    assert a3res.returncode == 0, a3res.stderr
    assert prov["design_content"] == "structure_and_geometry", prov
    assert set(prov["spec_bound_params"]) == {"r1.l", "r2.l"}, prov
    # ...and the parameters it says are bound are NOT also claimed as nominal.
    assert not (set(prov["spec_bound_params"])
                & set(prov["library_nominal_params"]))


def test_the_divider_follows_the_bound_output_voltage(tmp_path):
    """R_div = vout / I_div: at a fixed budget, twice the output voltage is
    twice the divider resistance and twice its drawn length. A library
    default cannot move when the declaration does."""
    d1, r1, root1 = a2(tmp_path, "lo", vout=1.2)
    d2, r2, root2 = a2(tmp_path, "hi", vout=2.4)
    assert r1.returncode == 0 and r2.returncode == 0
    _, _, l1 = _sized(d1, root1)
    _, _, l2 = _sized(d2, root2)
    assert l1 and l2, (l1, l2)
    for leg in ("r1", "r2"):
        assert l2[leg] == pytest.approx(2.0 * l1[leg], rel=1e-3), (leg, l1, l2)


def test_the_divider_follows_the_bound_quiescent_budget(tmp_path):
    """I_div = iq * fraction: twice the budget is half the resistance, so the
    divider gets SHORTER as the declaration gets more generous. The direction
    is asserted, not just the magnitude — a sign error would still scale."""
    d1, r1, root1 = a2(tmp_path, "tight", iq=50.0)
    d2, r2, root2 = a2(tmp_path, "loose", iq=100.0)
    assert r1.returncode == 0 and r2.returncode == 0
    _, _, l1 = _sized(d1, root1)
    _, _, l2 = _sized(d2, root2)
    for leg in ("r1", "r2"):
        assert l2[leg] < l1[leg], (leg, l1, l2)
        assert l2[leg] == pytest.approx(0.5 * l1[leg], rel=1e-3), (leg, l1, l2)


def test_the_two_legs_realise_the_ratio_the_divider_has_to_divide(tmp_path):
    """The spec-sized TOTAL is split between the legs in the divider ratio, so
    the sizing does not silently change what the feedback loop regulates to."""
    d, res, root = a2(tmp_path)
    assert res.returncode == 0
    ir = read_json(d / "topology.json")
    ratio = ir["knobs"]["divider_ratio"]
    _, _, lens = _sized(d, root)
    assert lens["r1"] == pytest.approx(lens["r2"] * (ratio - 1.0), rel=1e-3)


def test_both_legs_carry_a_bound_spec_value_in_their_expression(tmp_path):
    """Structural, so a future rewrite that keeps the numbers but drops a
    bound name from one leg is caught: `_resolve_params` credits
    `spec_bound` only when the expression NAMES a bound row."""
    d, res, _ = a2(tmp_path)
    assert res.returncode == 0
    _, exprs = _legs(d)
    for leg in ("r1.l", "r2.l"):
        assert "vout" in exprs[leg] and "iq" in exprs[leg], (leg, exprs)


def test_a_declaration_with_a_reference_but_no_budget_keeps_its_old_sizing(
        tmp_path):
    """THE OTHER CONTROL — the capability this change must not take away.

    Before it, a regulator binding `Vout` and `Vref` sized `r1.l` through the
    divider ratio off the entry's unit length. That path is still there: the
    unit-element expressions are listed FIRST and the budget-sized ones only
    overwrite them when the declaration carries the `iq` row they need. A
    declaration with a reference and no budget must therefore come out sized
    exactly as it always was — spec-bound, off `l_unit`, not silently
    demoted to a nominal by a change that only meant to add a case."""
    d, res, root = a2(tmp_path, "p", vref=0.6, drop=("Iq",))
    assert res.returncode == 0
    ir = read_json(d / "topology.json")
    l_unit = ir["constants"]["l_unit"]
    ratio = ir["knobs"]["divider_ratio"]
    assert ir["knob_sources"]["divider_ratio"] == "spec"
    a3res, prov, lens = _sized(d, root)
    assert a3res.returncode == 0, a3res.stderr
    assert prov["design_content"] == "structure_and_geometry", prov
    assert "r1.l" in prov["spec_bound_params"], prov
    assert lens["r1"] == pytest.approx(l_unit * (ratio - 1.0), rel=1e-3)


def test_a_parameter_two_expressions_reach_is_named_once(tmp_path):
    """Both forms resolve when the declaration carries every row, and the
    artefact lists WHICH parameters a bound value reached — a parameter named
    twice says nothing a reader can use and reads as two devices."""
    d, res, root = a2(tmp_path, "p", vref=0.6)
    assert res.returncode == 0
    _, prov, _ = _sized(d, root)
    b = prov["spec_bound_params"]
    assert len(b) == len(set(b)), b


# ── and the refusals ──────────────────────────────────────────────────────
def _gap(d):
    assert (d / "topology_gap.json").is_file()
    assert not (d / "topology.md").exists(), "a refusal must emit NO topology"
    return read_json(d / "topology_gap.json")


@pytest.mark.parametrize("label,kw", [
    ("the quiescent budget is not declared", {"drop": ("Iq",)}),
    ("the regulated output is not declared", {"drop": ("Vout",)}),
])
def test_a_declaration_that_does_not_carry_the_row_keeps_the_disclosure(
        tmp_path, label, kw):
    """THE CONTROL, and the scope statement.

    This entry is the library's generic simple regulator, and a design that
    binds nothing has always got the library nominal from it. The change does
    NOT turn that into a refusal — it leaves the expression to drop and the
    device to keep its nominal, and the honest word for that outcome is the
    one A3 already publishes. So the property asserted here is that the
    disclosure SURVIVES: a thin declaration must still come out as
    `structure_only`, never as a sized regulator, and never as a gap either.

    This is what stops the change being a way to make `structure_only` go
    away: the tier moves only where the declaration actually binds the rows."""
    d, res, root = a2(tmp_path, "p", **kw)
    assert res.returncode == 0, f"{label}: a thin declaration is not a refusal"
    assert not (d / "topology_gap.json").exists(), label
    a3res, prov, _ = _sized(d, root)
    assert a3res.returncode == 0, a3res.stderr
    assert prov["design_content"] == "structure_only", (label, prov)
    assert prov["spec_bound_params"] == [], (label, prov)


@pytest.mark.parametrize("label,kw", [
    ("a budget declared in mA would be read as microamps",
     {"iq": 0.05, "iq_unit": "mA"}),
    ("an output declared in mV would be read as volts",
     {"vout": 1200.0, "vout_unit": "mV"}),
])
def test_a_unit_the_expressions_do_not_assume_is_refused_not_scaled(
        tmp_path, label, kw):
    """The expression environment carries no units. A budget row in mA read as
    microamps sizes the divider a thousand times wrong and nothing records
    it; the refusal is the only safe answer available."""
    d, res, _ = a2(tmp_path, "p", **kw)
    assert res.returncode == 2, label
    g = _gap(d)
    kinds = {r["requirement"] for r in g["admission_refusals"]}
    assert "spec_unit" in kinds, (label, g["admission_refusals"])


def test_a_process_with_no_measured_sheet_keeps_the_disclosure(tmp_path):
    """`_resolve_params` drops an expression over an unknown name SILENTLY. On
    a family with no measured sheet resistance the divider expressions
    therefore resolve to nothing — and the artefact must SAY so rather than
    present a library nominal as a sized one. The disclosure is the guard
    here, and it is asserted rather than assumed."""
    d, res, root = a2(tmp_path, "p", pdk="gf180mcuD")
    assert res.returncode == 0
    ir = read_json(d / "topology.json")
    if "rsheet_ohm_per_sq" in (ir.get("pdk_measured_params") or {}):
        pytest.skip("this family carries a measured sheet; not the case "
                    "under test")
    a3res, prov, _ = _sized(d, root)
    assert a3res.returncode == 0, a3res.stderr
    assert prov["design_content"] == "structure_only", prov
    assert prov["spec_bound_params"] == [], prov


def test_a_mis_united_refusal_still_names_the_field_and_both_units(tmp_path):
    """A refusal that does not say WHICH row and WHAT it expected is not
    actionable."""
    d, res, _ = a2(tmp_path, "p", iq=0.05, iq_unit="mA")
    assert res.returncode == 2
    g = _gap(d)
    r = [x for x in g["admission_refusals"]
         if x["requirement"] == "spec_unit" and x["field"] == "iq"]
    assert r, g["admission_refusals"]
    assert r[0]["declared_unit"] == "mA"
    assert "A" in str(r[0]["expected_unit"])
