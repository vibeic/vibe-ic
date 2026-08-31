"""vibe-ic#1962 — the PDK's analog device constants are MEASURED once and
published, instead of being re-derived by hand in every sizing pass.

WHAT WAS BROKEN

`pdk_registry.json` carried three hand-typed constants per family — two
thresholds and a supply — and nothing a sizing pass actually solves with. So
clearing an analog block's STRUCTURE_ONLY state meant deriving the process
transconductance, the resistor sheet, the MiM density and the gate drive by
hand, from throwaway ngspice decks, in the session, on every design and every
PDK. Same four measurements, no provenance, and no way for a later reader to
tell a measured number from a remembered one.

WHAT MAKES EACH ARM BELOW A REAL TEST

* RED arm — the shipped registry now carries a MEASURED record for the open
  families that can be characterized, and A2's artefacts quote it with its
  provenance. Every assertion here fails on the pre-fix sources: the reader
  module does not exist, the registry field does not exist, and the IR key does
  not exist.
* CONTROL arm — a SECOND shipped family. Every registry-backed assertion is
  parametrized over both, and the two families' constants are asserted to
  DIFFER: a "measured" constant that comes out the same on two processes is not
  a measurement of either.
* NOT-CHARACTERIZED arm — shipped families that carry no record must quote
  NOTHING and say so positively. An absent constant must be distinguishable
  from a zero one, in the reader, in the IR and in the human document.
* GENERIC arm — the extraction, the bias grid, the deck emission and the
  registry upsert are driven against INVENTED families, invented primitives and
  synthetic currents. No shipped family is involved, so the core cannot be
  passing by knowing about one.
* REFUSAL arm — every way a measurement can fail to be physical is asserted to
  produce a NAMED gap rather than a number.
* SOURCE arm — the producer and the reader are read and asserted to contain no
  PDK family name at all.
* IN-CONTAINER arm — skipped, never failed, when no EDA container is present:
  re-measures a shipped family end to end and requires the published constants
  to reproduce.

Every number asserted against a shipped family is READ OUT OF THE REGISTRY at
test time and never retyped here, so this file cannot drift from the data and
cannot be the place a wrong constant is kept alive.
"""
from __future__ import annotations

import inspect
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path
import pdk_analog_characterize as char
import pdk_analog_device_params as params

from _analog_producer_fixture import (
    A2, PROGRAMS, block, make_project, run_prog, bdir, read_json)

REGISTRY = PROGRAMS / "pdk_registry.json"
READER = PROGRAMS / "pdk_analog_device_params.py"
PRODUCER = PROGRAMS / "pdk_analog_characterize.py"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _characterized_families() -> list:
    """Every shipped family that carries a measured record. Read, not listed —
    a family characterized later is covered by these tests automatically."""
    out = []
    for ent in _registry().get("pdks") or []:
        if not isinstance(ent, dict) or not ent.get("name"):
            continue
        rec = (ent.get(params.PARAMS_KEY) or {})
        if isinstance(rec, dict) and isinstance(rec.get(params.MEASURED_KEY),
                                                dict):
            out.append(str(ent["name"]))
    return out


def _uncharacterized_families() -> list:
    out = []
    for ent in _registry().get("pdks") or []:
        if not isinstance(ent, dict) or not ent.get("name"):
            continue
        rec = (ent.get(params.PARAMS_KEY) or {})
        if not isinstance(rec.get(params.MEASURED_KEY), dict):
            out.append(str(ent["name"]))
    return out


CHARACTERIZED = _characterized_families()
UNCHARACTERIZED = _uncharacterized_families()


def test_the_shipped_registry_carries_more_than_one_characterized_family():
    """The control arm below is only a control while there are two. If this
    ever drops to one, the parametrized arms stop proving genericity and the
    file must say so loudly rather than quietly test one family."""
    assert len(CHARACTERIZED) >= 2, (
        f"vibe-ic#1962 needs at least two shipped families with a measured "
        f"record so the second is a control on the first; found "
        f"{CHARACTERIZED}")
    assert UNCHARACTERIZED, (
        "and at least one shipped family WITHOUT a record, so 'quoted "
        "nothing' stays distinguishable from 'quoted a zero'")


# ── RED: the record exists, is complete, and is attributed ────────────────
@pytest.mark.parametrize("family", CHARACTERIZED)
def test_the_measured_record_states_how_and_on_what_it_was_measured(family):
    """A number with no method, no device and no section is the remembered
    constant this issue replaces, wearing a measurement's name."""
    fam, rec = params.measured_record(family)
    assert fam == family
    assert rec["_generated_by"] == char.PRODUCER, (
        "the record must name the program that produced it; a hand-typed "
        "record is exactly what this replaces")
    assert rec["_schema"] == params.RECORD_SCHEMA
    assert rec["_method"], "the record does not state HOW it was extracted"
    assert (rec.get("simulator") or {}).get("tool"), (
        "the record does not name the simulator that measured it")

    corner = params.nominal_corner(rec)
    assert corner, "the record declares no nominal corner"
    name, cr = params.corner_record(rec)
    assert name == corner and cr

    assert cr["sections"], "the corner names no model lib section"
    for lib, section in cr["sections"]:
        assert lib and section, "a model-lib load is recorded incompletely"
    assert cr["devices"], "the corner attributes no primitive to any role"
    assert isinstance(cr["supply_v"], (int, float)) and cr["supply_v"] > 0
    assert isinstance(cr["temp_c"], (int, float))


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_every_published_constant_is_physical(family):
    """The numbers themselves. Asserted as INVARIANTS a real silicon process
    obeys, never as the literals in the registry — a test that retypes the
    constants is a copy of the data, not a check on it."""
    v = params.measured_values(family)
    assert v, f"{family} carries a measured record with no values in it"
    for key, val in v.items():
        assert math.isfinite(val), f"{key} is not finite"

    prov = params.measured_provenance(family)
    supply = prov["supply_v"]
    for role_key in ("k_prime_n_ua_per_v2", "k_prime_p_ua_per_v2"):
        if role_key in v:
            assert v[role_key] > 0, f"{role_key} is not positive"
    for vth_key in ("vth_n_extracted_v", "vth_p_extracted_v"):
        if vth_key in v:
            assert 0.0 < v[vth_key] < supply, (
                f"{vth_key} = {v[vth_key]} is not a threshold this rail can "
                f"even reach ({supply} V)")
    if "k_prime_n_ua_per_v2" in v and "k_prime_p_ua_per_v2" in v:
        assert v["k_prime_n_ua_per_v2"] > v["k_prime_p_ua_per_v2"], (
            "the n-role transconductance parameter is not larger than the "
            "p-role's. Electron mobility exceeds hole mobility in silicon, so "
            "this ordering holds on every MOS process; a record that breaks "
            "it was not measured on one")
    for pos in ("cap_area_ff_per_um2", "rsheet_ohm_per_sq", "r_per_um_ohm"):
        if pos in v:
            assert v[pos] > 0, f"{pos} is not positive"
    for vgs in ("vgs_at_id_n_v", "vgs_at_id_p_v"):
        if vgs in v:
            assert 0.0 < v[vgs] < supply


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_every_gap_is_named_and_no_gap_is_also_a_value(family):
    """Degrade loudly. A metric that could not be measured must appear in
    `not_measured` with a reason and must NOT appear in `params` — a key in
    both would let a reader take a fabricated number for a measured one."""
    _n, cr = params.corner_record(params.measured_record(family)[1])
    gaps = cr.get("not_measured") or {}
    for key, why in gaps.items():
        assert isinstance(why, str) and len(why) > 20, (
            f"`{key}` is recorded as unmeasured with no usable reason")
        assert key not in (cr.get("params") or {}), (
            f"`{key}` is published as a value AND recorded as not measured")


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_the_fit_residual_is_published_with_every_square_law_constant(family):
    """A k' quoted with no residual cannot be told apart from one that fits.
    The interior bias point is not used by the fit precisely so it can score
    it, and the score has to reach the record."""
    _n, cr = params.corner_record(params.measured_record(family)[1])
    v = cr.get("params") or {}
    fit = cr.get("fit") or {}
    for k_key, fit_key in (("k_prime_n_ua_per_v2", "n_fit_residual_rel"),
                           ("k_prime_p_ua_per_v2", "p_fit_residual_rel")):
        if k_key not in v:
            continue
        assert fit_key in fit, (
            f"{k_key} is published without the residual that says how well "
            f"the square law describes this device")
        assert 0.0 <= fit[fit_key] < 10.0


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_the_published_bias_is_threshold_referred_and_stated(family):
    """The bias grid is a testbench CONDITION, so it must be in the record.

    It also has to be the SECOND grid. A supply-referred grid puts the low
    point at or below threshold on a high-threshold device — measured on a
    shipped family: 0.17 uA against 41 uA across the grid, and an interior
    point 90% away from the model. Publishing that k' would be publishing an
    artefact of where the grid happened to fall."""
    _n, cr = params.corner_record(params.measured_record(family)[1])
    bias = cr.get("bias") or {}
    assert bias, "the corner does not state the bias its MOS roles were at"
    for role, b in bias.items():
        pts = b.get("vgs_v") or []
        assert len(pts) == 3 and pts == sorted(pts), (
            f"{role} was not measured on three ordered gate biases")
        assert b.get("basis"), f"{role} does not state what chose its bias"
        seed = b.get("seed_vth_v")
        if seed is not None:
            assert "threshold-referred" in b["basis"], (
                f"{role} had a seed threshold and still published a "
                f"supply-referred grid")
            assert pts[0] > seed, (
                f"{role}'s lowest gate bias {pts[0]} is not above the seed "
                f"threshold {seed}; the fit would be anchored in subthreshold")


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_the_process_corners_are_ordered_the_way_silicon_orders_them(family):
    """A family characterized at more than one corner must come out MONOTONIC:
    the slow corner is slower and the fast corner is faster, on both roles, and
    the thresholds run the other way. This is a property of what a process
    corner IS, so a record that breaks it was not measured at the corners it
    claims — it re-ran the same section under three names."""
    _fam, rec = params.measured_record(family)
    have = {c: (rec["corners"][c].get("params") or {})
            for c in ("slow", "typ", "fast") if c in rec.get("corners", {})}
    if len(have) < 3:
        pytest.skip(f"{family} is characterized at {sorted(have)} only")
    for k_key, vth_key in (("k_prime_n_ua_per_v2", "vth_n_extracted_v"),
                           ("k_prime_p_ua_per_v2", "vth_p_extracted_v")):
        if not all(k_key in v for v in have.values()):
            continue
        assert (have["slow"][k_key] < have["typ"][k_key]
                < have["fast"][k_key]), (
            f"{family} {k_key} is not ordered slow < typ < fast: "
            f"{[have[c][k_key] for c in ('slow', 'typ', 'fast')]}")
        assert have["slow"][vth_key] > have["typ"][vth_key] > \
            have["fast"][vth_key], (
            f"{family} {vth_key} is not ordered slow > typ > fast")


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_each_corner_loaded_its_own_model_section(family):
    """The other half of the same argument, on the artefact rather than on the
    numbers: `per corner lib` means each corner names the section IT loaded."""
    _fam, rec = params.measured_record(family)
    corners = rec.get("corners") or {}
    if len(corners) < 2:
        pytest.skip(f"{family} is characterized at one corner")
    primary = {c: tuple(cr["sections"][0]) for c, cr in corners.items()}
    assert len(set(primary.values())) == len(primary), (
        f"{family} reports the SAME primary model section for more than one "
        f"corner: {primary}")


def test_two_families_do_not_report_the_same_constants():
    """The control that makes these measurements. Two different processes
    cannot have the same transconductance parameter to six digits; if they did,
    the record would be a shared default wearing two families' names."""
    a, b = CHARACTERIZED[0], CHARACTERIZED[1]
    va, vb = params.measured_values(a), params.measured_values(b)
    shared = set(va) & set(vb)
    assert shared, f"{a} and {b} publish no comparable constant"
    differing = [k for k in shared
                 if abs(va[k] - vb[k]) > 1e-9 * max(abs(va[k]), abs(vb[k]))]
    assert len(differing) >= len(shared) - 1, (
        f"{a} and {b} report identical values for "
        f"{sorted(set(shared) - set(differing))}")


# ── CONTROL: a family nobody has characterized quotes nothing, and says so ─
@pytest.mark.parametrize("family", UNCHARACTERIZED)
def test_an_uncharacterized_family_quotes_nothing_and_states_that(family):
    assert params.measured_values(family) == {}, (
        f"{family} has no measured record and still yielded values")
    prov = params.measured_provenance(family)
    assert prov["measured"] is False
    assert prov["reason"], (
        "a family with no record must say WHY it quoted nothing; an empty "
        "answer is indistinguishable from a measured zero")


@pytest.mark.parametrize("family", UNCHARACTERIZED)
def test_the_declared_constants_of_an_uncharacterized_family_are_untouched(
        family):
    """Characterizing SOME families must not move a number any existing reader
    was already relying on for the others."""
    fam, declared = params.declared_params(family)
    entry = next((e for e in _registry()["pdks"]
                  if isinstance(e, dict) and e.get("name") == family), {})
    assert declared == {k: v for k, v in
                        (entry.get(params.PARAMS_KEY) or {}).items()
                        if k != params.MEASURED_KEY}


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_characterizing_a_family_does_not_move_its_declared_constants(family):
    """Same invariant on the other side: the declared half of a family that HAS
    been characterized must still answer exactly what it answered before, so a
    consumer that reads `nominal_supply_v` is unaffected by the new record."""
    _fam, declared = params.declared_params(family)
    assert params.MEASURED_KEY not in declared
    entry = next((e for e in _registry()["pdks"]
                  if isinstance(e, dict) and e.get("name") == family), {})
    for key in ("vth_n_v", "vth_p_v", "nominal_supply_v"):
        if key in (entry.get(params.PARAMS_KEY) or {}):
            assert declared[key] == entry[params.PARAMS_KEY][key]


# ═══════════════════════════════════════════════════════════════════════════
# THE CONSUMPTION SEAM — what the measurement is FOR
# ═══════════════════════════════════════════════════════════════════════════
def _emit(tmp_path: Path, selector: str, name: str = "vreg_alpha"):
    p = make_project(tmp_path / re.sub(r"\W+", "_", selector),
                     [block(name, "ldo")])
    cp = run_prog(A2, p, "--pdk", selector)
    assert cp.returncode == 0, f"{cp.stdout}{cp.stderr}"
    return read_json(bdir(p, name) / "topology.json"), \
        (bdir(p, name) / "topology.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_a2_carries_the_measured_constants_into_the_ir(tmp_path, family):
    """The A2 -> A3 data path. `device_param_exprs` are evaluated in A3 over an
    environment built from the IR, so a measured constant that never reaches
    the IR cannot be referenced by any library expression, and the sizing pass
    is back to re-deriving it."""
    ir, _md = _emit(tmp_path, family)
    got = ir["pdk_measured_params"]
    assert got, (f"topology.json for {family} carries no measured process "
                 f"constants, so no device_param_exprs entry can reference "
                 f"one")
    assert got == params.measured_values(family), (
        "the IR's copy disagrees with the registry it was read from")


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_a2_states_where_every_measured_constant_came_from(tmp_path, family):
    """A constant with no provenance in the artefact is not better than a
    constant re-derived in the session; it is worse, because it looks
    authoritative."""
    ir, md = _emit(tmp_path, family)
    prov = ir["_provenance"]["pdk_constants_source"]["measured"]
    assert prov["measured"] is True
    assert prov["corner"] and prov["sections"] and prov["devices"]
    assert prov["generated_by"] == char.PRODUCER
    assert prov["method"]

    assert "## Measured process constants" in md
    for role, dev in prov["devices"].items():
        assert dev in md, (
            f"topology.md quotes measured constants without naming the "
            f"`{role}` primitive `{dev}` they were measured on")
    for key in params.measured_values(family):
        assert f"`{key}`" in md


@pytest.mark.parametrize("family", UNCHARACTERIZED)
def test_a2_states_positively_that_a_family_was_not_characterized(
        tmp_path, family):
    ir, md = _emit(tmp_path, family)
    assert ir["pdk_measured_params"] == {}
    assert ir["_provenance"]["pdk_constants_source"]["measured"]["measured"] \
        is False
    assert "has NOT been characterized" in md
    assert "pdk_analog_characterize.py" in md, (
        "the document does not say how to obtain what it could not quote")


# ── the A3 half: the constants reach the expression environment ───────────
def _ir_with(exprs, measured, constants=None):
    """The smallest IR `_resolve_params` reads. Invented names throughout."""
    return {
        "constants": dict(constants or {}),
        "knobs": {}, "knob_sources": {},
        "pdk_measured_params": dict(measured),
        "device_param_exprs": list(exprs),
        "devices": [{"name": "r_zeta", "role": "res", "w": 1.0, "l": 1.0}],
    }


def test_a_library_expression_may_be_written_against_a_measured_constant():
    """The seam vibe-ic#1962 exists to open, asserted on the smallest possible
    input. Pre-fix the IR carries no measured constants and this expression
    resolves against nothing, so no override is produced at all."""
    import analog_a3_netlist_emit as a3
    ir = _ir_with(
        [{"device": "r_zeta", "param": "l",
          "expr": "r_target_ohm * w_res / rsheet_ohm_per_sq"}],
        {"rsheet_ohm_per_sq": 250.0},
        {"w_res": 0.5, "r_target_ohm": 10000.0})
    overrides, _bound, _nominal, env = a3._resolve_params(ir, {})
    assert overrides["r_zeta"]["l"] == pytest.approx(10000.0 * 0.5 / 250.0)
    assert env["rsheet_ohm_per_sq"] == 250.0


def test_a_library_constant_outranks_a_measured_constant_of_the_same_name():
    """Seeded FIRST, deliberately. A process constant is what a design is built
    ON, never what it is built FROM, so a library or spec name of the same
    spelling must still win — otherwise characterizing a PDK would silently
    retune every topology that happens to share a name."""
    import analog_a3_netlist_emit as a3
    ir = _ir_with([{"device": "r_zeta", "param": "l", "expr": "collide * 2"}],
                  {"collide": 1.0}, {"collide": 7.0})
    overrides, _b, _n, env = a3._resolve_params(ir, {})
    assert env["collide"] == 7.0
    assert overrides["r_zeta"]["l"] == 14.0


def test_an_uncharacterized_family_leaves_every_expression_as_it_was():
    """The regression control for the seam: an IR with no measured constants
    must evaluate byte-identically to how it did before the seam existed."""
    import analog_a3_netlist_emit as a3
    exprs = [{"device": "r_zeta", "param": "l", "expr": "l_unit * 3"}]
    with_key = a3._resolve_params(_ir_with(exprs, {}, {"l_unit": 20.0}), {})
    without = a3._resolve_params(
        {"constants": {"l_unit": 20.0}, "knobs": {}, "knob_sources": {},
         "device_param_exprs": exprs, "devices": []}, {})
    assert with_key[0] == without[0]


# ═══════════════════════════════════════════════════════════════════════════
# GENERIC: the core is arithmetic and text, driven on invented inputs
# ═══════════════════════════════════════════════════════════════════════════
def test_the_square_law_fit_recovers_a_synthetic_device_exactly():
    """Feed the extraction currents a textbook square-law device WOULD draw and
    require the constants back. No simulator, no PDK, no tolerance games."""
    k, vth, wl = 250e-6, 0.42, 10.0
    vlo, vhi = 0.9, 1.4
    ilo = 0.5 * k * wl * (vlo - vth) ** 2
    ihi = 0.5 * k * wl * (vhi - vth) ** 2
    got_k, got_vth, why = char.extract_square_law(vlo, ilo, vhi, ihi, wl)
    assert why == ""
    assert got_k == pytest.approx(k, rel=1e-9)
    assert got_vth == pytest.approx(vth, rel=1e-9)
    # and the residual of a device that IS square-law is zero
    assert char.fit_residual(got_k, got_vth, wl, 1.1,
                             0.5 * k * wl * (1.1 - vth) ** 2) \
        == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("lo,hi,frag", [
    (1e-4, 1e-5, "does not increase"),          # current falls with Vgs
    (1e-4, 1e-4, "does not increase"),          # no change at all
    (0.0, 1e-4, "finite positive"),             # a dead point
    (None, 1e-4, "finite positive"),            # the deck never echoed it
])
def test_an_unphysical_pair_yields_a_named_refusal_and_no_number(lo, hi, frag):
    k, vth, why = char.extract_square_law(0.9, lo, 1.4, hi, 10.0)
    assert (k, vth) == (None, None)
    assert frag in why


def test_the_two_length_method_cancels_the_end_resistance_exactly():
    """One resistor is not a sheet. Build R(L) = Rs*L/W + 2*Rc from invented
    constants and require BOTH back — the sheet AND the end term the
    single-device method silently folds into it."""
    rs, r_end, w = 260.0, 175.0, 0.5
    r1 = rs * 20.0 / w + r_end
    r2 = rs * 40.0 / w + r_end
    got_rs, got_end, per_um, why = char.extract_sheet_resistance(
        r1, r2, w, 20.0, 40.0)
    assert why == ""
    assert got_rs == pytest.approx(rs, rel=1e-9)
    assert got_end == pytest.approx(r_end, rel=1e-9)
    assert per_um == pytest.approx(rs / w, rel=1e-9)


def test_a_resistance_that_does_not_grow_with_length_is_refused():
    rs, _e, per, why = char.extract_sheet_resistance(1000.0, 1000.0, 0.5,
                                                     20.0, 40.0)
    assert (rs, per) == (None, None)
    assert "does not increase with length" in why


def test_a_primitive_that_ignores_the_drawn_width_is_detected():
    """The measured trap: a fixed-width resistor flavour returns the same
    resistance at w and at 2w, and a sheet derived from a width it ignored
    would be a fabricated number."""
    assert char.width_is_honoured(1000.0, 500.0) is True
    assert char.width_is_honoured(1000.0, 1000.0) is False
    assert char.width_is_honoured(1000.0, 1000.0 * 1.01) is False


def test_the_two_area_method_separates_the_fringe_from_the_density():
    ca, cp = 1.5e-15, 4.0e-17
    c1 = ca * 100.0 + cp * 40.0
    c2 = ca * 400.0 + cp * 80.0
    got_a, got_p, why = char.extract_cap_density(c1, c2, 10.0, 20.0)
    assert why == ""
    assert got_a == pytest.approx(ca, rel=1e-9)
    assert got_p == pytest.approx(cp, rel=1e-9)
    # the single-plate answer is the contaminated one this replaces
    assert c1 / 100.0 > ca


def test_a_negative_separated_density_is_refused():
    got_a, _p, why = char.extract_cap_density(1e-12, 1e-15, 10.0, 20.0)
    assert got_a is None and "not positive" in why


def test_the_bias_grid_starts_supply_referred_and_then_refers_to_threshold():
    grid, basis = char.bias_grid(1.8, None)
    assert grid == [1.8 * f for f in char.VGS_FRACTIONS]
    assert "no threshold known yet" in basis

    grid, basis = char.bias_grid(1.8, 0.9)
    assert "threshold-referred" in basis
    assert all(v > 0.9 for v in grid), (
        "a threshold-referred grid put a point at or below the threshold")
    assert grid == sorted(grid)
    assert max(grid) <= 1.8 * char.VGS_CEILING_FRACTION + 1e-12


def test_the_bias_grid_never_drives_the_gate_past_the_rail():
    """A seed threshold close to the rail must not produce a bias above it: a
    voltage the design cannot apply is not a measurement of anything."""
    grid, _b = char.bias_grid(1.2, 1.15)
    assert max(grid) <= 1.2 * char.VGS_CEILING_FRACTION + 1e-12


# ── deck emission on an invented family ──────────────────────────────────
def test_the_geometry_idiom_follows_the_declared_unit_convention():
    """Measured, and not a preference: a family whose subckt declares METRIC
    defaults gets a bare number ~1e6x too large, and a family whose libs set
    `.option scale` gets an explicit-metre number ~1e6x too small — outside
    every model bin. Same rule as the corner-sweep emitter's."""
    loads = [("/invented/path/zeta.lib", "zeta_typ")]
    scaled = char.render_mos_deck("nmos", "zeta_prim", 4, False, loads,
                                  1.8, 27.0, [0.8, 0.9, 1.0])
    metric = char.render_mos_deck("nmos", "zeta_prim", 4, True, loads,
                                  1.8, 27.0, [0.8, 0.9, 1.0])
    assert ".option scale=1u" in scaled and "w=10 l=1" in scaled
    assert ".option scale" not in metric and "w=10u l=1u" in metric
    for deck in (scaled, metric):
        assert ".lib /invented/path/zeta.lib zeta_typ" in deck


def test_a_primitive_with_extra_terminals_gets_them_tied():
    """A foundry MOS subckt may carry a fifth substrate node; ngspice aborts
    `Too few parameters for subcircuit` unless it is supplied. Keyed on the
    RESOLVED count, so a four-terminal primitive is byte-identical."""
    four = char.render_mos_deck("nmos", "zeta_prim", 4, False, [], 1.8, 27.0,
                                [0.8, 0.9, 1.0])
    five = char.render_mos_deck("nmos", "zeta_prim", 5, False, [], 1.8, 27.0,
                                [0.8, 0.9, 1.0])
    assert "xm1 d1 g1 0 0 zeta_prim" in four
    assert "xm1 d1 g1 0 0 0 zeta_prim" in five


def test_the_pmos_deck_is_the_same_circuit_referred_to_the_top_rail():
    deck = char.render_mos_deck("pmos", "zeta_prim", 4, False, [], 1.8, 27.0,
                                [0.9, 1.2, 1.5])
    assert "vsup vsup 0 1.8" in deck
    # |Vgs| = 0.9 means a gate at supply - 0.9
    assert "vg1 g1 0 0.9" in deck
    assert "vg3 g3 0 0.3" in deck
    assert "xm1 d1 g1 vsup vsup zeta_prim" in deck


def test_the_resistor_deck_probes_two_lengths_and_a_doubled_width():
    deck = char.render_res_deck("zeta_res", 3, False, [], 0.5, 27.0)
    assert f"w=0.5 l={char.RES_L1_UM:g}" in deck
    assert f"w=0.5 l={char.RES_L2_UM:g}" in deck
    assert f"w=1 l={char.RES_L1_UM:g}" in deck


def test_the_capacitor_deck_probes_two_square_plates():
    deck = char.render_cap_deck("zeta_cap", 2, False, [], 27.0)
    assert f"w={char.CAP_S1_UM:g} l={char.CAP_S1_UM:g}" in deck
    assert f"w={char.CAP_S2_UM:g} l={char.CAP_S2_UM:g}" in deck
    assert "ac lin 1" in deck


def test_the_measurement_parser_reads_only_what_the_deck_echoed():
    log = ("noise\nMEAS id1= 0.000141565\nmore noise\n"
           "MEAS id2=4.58573e-04\nMEAS vdio= 0.75\n")
    assert char.parse_measurements(log) == {
        "id1": 0.000141565, "id2": 4.58573e-04, "vdio": 0.75}
    assert char.parse_measurements("") == {}


@pytest.mark.parametrize("marker", [
    "could not find a valid modelname",
    "Unable to find definition of model xa:zeta",
    "Too few parameters for subcircuit",
    "Simulation interrupted due to error!",
])
def test_a_failed_deck_is_reported_in_the_simulators_own_words(marker):
    got = char.deck_failed(f"banner\nsome line\n  {marker}\ntail\n")
    assert got and marker.lower() in got.lower()


def test_a_deck_that_ran_reports_no_failure():
    assert char.deck_failed("Doing analysis\nMEAS id1= 1e-4\n") is None


@pytest.mark.parametrize("corners", ["", "typ,not-a-corner"])
def test_cli_refuses_an_invalid_corner_list_before_touching_the_pdk(
        monkeypatch, capsys, corners):
    """A typo must not be published as if it named a process corner.

    This refusal happens before PDK resolution or simulation: an empty list
    used to reach ``wanted[0]`` and crash only after the decks, while an
    unknown name could be recorded as a corner even though no such model
    section had been selected.
    """
    def unexpected_resolution(*_args, **_kwargs):
        raise AssertionError("invalid --corners reached PDK resolution")

    monkeypatch.setattr(char, "resolve_target", unexpected_resolution)
    assert char.main(["--pdk", "zeta-fictional-process",
                      "--corners", corners]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "INVALID_CORNERS"
    assert report["work_items"]
    assert "typ, slow, fast" in report["work_items"][0]


# ═══════════════════════════════════════════════════════════════════════════
# PUBLICATION: where a record may go, and where it may not
# ═══════════════════════════════════════════════════════════════════════════
def _synthetic_registry(tmp_path: Path, open_source: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "synthetic_registry.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "pdks": [{
            "name": "zeta-fictional-process",
            "open_source": open_source,
            "analog_device_params": {"vth_n_v": 0.31, "nominal_supply_v": 2.5},
        }],
    }), encoding="utf-8")
    return p


def _record(**params_) -> dict:
    return {
        "_schema": params.RECORD_SCHEMA,
        "_generated_by": char.PRODUCER,
        "_method": "an invented method",
        "nominal_corner": "typ",
        "simulator": {"tool": "invented"},
        "corners": {"typ": {"sections": [["/invented/zeta.lib", "zeta_typ"]],
                            "devices": {"nmos": "zeta_prim"},
                            "temp_c": 27.0, "supply_v": 2.5,
                            "bias": {}, "params": dict(params_),
                            "fit": {}, "not_measured": {}}},
    }


def test_the_reader_answers_for_a_family_it_has_never_seen(tmp_path):
    reg = _synthetic_registry(tmp_path)
    body = json.loads(reg.read_text())
    assert char.upsert_registry(body, "zeta-fictional-process",
                                _record(k_prime_n_ua_per_v2=123.5))
    reg.write_text(json.dumps(body), encoding="utf-8")

    fam, rec = params.measured_record("zeta-fictional", reg)
    assert fam == "zeta-fictional-process" and rec["_method"]
    assert params.measured_values("zeta-fictional", None, reg) == \
        {"k_prime_n_ua_per_v2": 123.5}
    # and the DECLARED half is untouched by the upsert
    assert params.declared_params("zeta-fictional", reg)[1] == \
        {"vth_n_v": 0.31, "nominal_supply_v": 2.5}
    assert params.measured_values("no-such-family", None, reg) == {}


def test_an_unknown_corner_is_not_answered_with_the_nominal_one(tmp_path):
    """Answering a question about the slow corner with the typical corner's
    numbers is the quietest way to publish a wrong margin."""
    reg = _synthetic_registry(tmp_path)
    body = json.loads(reg.read_text())
    char.upsert_registry(body, "zeta-fictional-process",
                         _record(k_prime_n_ua_per_v2=123.5))
    reg.write_text(json.dumps(body), encoding="utf-8")
    assert params.measured_values("zeta-fictional", "slow", reg) == {}
    prov = params.measured_provenance("zeta-fictional", "slow", reg)
    assert prov["measured"] is False and "slow" in prov["reason"]


def test_a_project_staged_record_outranks_the_shipped_one(tmp_path):
    """The shape vibe-ic#1962 was reported on: the PDK is staged INTO the
    design. The staged PDK is the one the design's decks load, so it is the one
    whose constants describe them."""
    reg = _synthetic_registry(tmp_path)
    body = json.loads(reg.read_text())
    char.upsert_registry(body, "zeta-fictional-process",
                         _record(k_prime_n_ua_per_v2=111.0))
    reg.write_text(json.dumps(body), encoding="utf-8")

    proj = tmp_path / "design"
    local = proj / params.PROJECT_RECORD
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({
        "family": "zeta-fictional-process",
        "measured": _record(k_prime_n_ua_per_v2=222.0)}), encoding="utf-8")

    assert params.measured_values("zeta-fictional", None, reg)[
        "k_prime_n_ua_per_v2"] == 111.0
    assert params.measured_values("zeta-fictional", None, reg, proj)[
        "k_prime_n_ua_per_v2"] == 222.0


def test_a_family_the_registry_does_not_call_open_may_not_be_published(
        tmp_path):
    """NDA. Measuring a PDK is reading it, and a proprietary process's device
    constants are not the plugin's to distribute."""
    reg = json.loads(_synthetic_registry(tmp_path, open_source=False)
                     .read_text())
    ok, why = char.registry_publishable(reg, "zeta-fictional-process")
    assert ok is False
    assert "open_source" in why and "--project" in why

    ok, why = char.registry_publishable(reg, "a-family-with-no-entry")
    assert ok is False and "no entry" in why

    reg_open = json.loads(_synthetic_registry(tmp_path / "b").read_text())
    assert char.registry_publishable(reg_open, "zeta-fictional-process")[0]


def test_publishing_touches_only_the_member_it_writes():
    """`pdk_registry.json` is hand-maintained: escaped prose, hand-compacted
    arrays, a chosen key order. Re-dumping it with `json.dumps` reproduces none
    of that — measured, adding one key rewrote 63 unrelated lines, which is how
    a data edit stops being reviewable. The write is a SPLICE, and this is the
    test that keeps it one."""
    import difflib
    orig = REGISTRY.read_text(encoding="utf-8")
    family = CHARACTERIZED[0]
    _fam, rec = params.measured_record(family)
    out, why = char.splice_registry_text(orig, family, rec)
    assert out is not None, why

    # re-writing the record it already carries must be a byte-for-byte no-op
    assert out == orig, (
        "splicing back the record the registry already carries changed the "
        "file; the write is not idempotent and every refresh will churn")

    # and changing it must move only the member's own lines
    edited = json.loads(json.dumps(rec))
    edited["_method"] = "an invented method"
    out2, why2 = char.splice_registry_text(orig, family, edited)
    assert out2 is not None, why2
    moved = [ln for ln in difflib.unified_diff(orig.splitlines(),
                                               out2.splitlines(), n=0)
             if ln.startswith(("+", "-"))
             and not ln.startswith(("+++", "---"))]
    assert len(moved) <= 4, (
        f"changing one string in the record moved {len(moved)} lines: {moved}")
    # semantically, nothing but that member changed
    a, b = json.loads(orig), json.loads(out2)
    for reg in (a, b):
        for e in reg["pdks"]:
            (e.get(params.PARAMS_KEY) or {}).pop(params.MEASURED_KEY, None)
    assert a == b


def test_the_splice_refuses_a_family_it_cannot_write_into(tmp_path):
    orig = REGISTRY.read_text(encoding="utf-8")
    out, why = char.splice_registry_text(orig, "a-family-with-no-entry", {})
    assert out is None and "no entry" in why


def test_the_splice_is_not_fooled_by_a_brace_inside_the_registrys_prose():
    """The registry's own `_comment` fields are long prose. A brace or a quote
    in one of them must not move the parse."""
    text = json.dumps({"pdks": [
        {"name": "zeta-a", "_comment": 'prose with { and } and a \\" quote',
         "analog_device_params": {"vth_n_v": 0.3}},
        {"name": "zeta-b", "analog_device_params": {"vth_n_v": 0.4}},
    ]}, indent=2)
    out, why = char.splice_registry_text(text, "zeta-b", {"_schema": 1})
    assert out is not None, why
    body = json.loads(out)
    got = body["pdks"][1]["analog_device_params"]["measured"]
    assert got == {"_schema": 1}
    assert "measured" not in body["pdks"][0]["analog_device_params"]
    assert (body["pdks"][0]["_comment"]
            == json.loads(text)["pdks"][0]["_comment"])


def test_the_upsert_refuses_a_family_that_is_not_in_the_registry(tmp_path):
    body = json.loads(_synthetic_registry(tmp_path).read_text())
    assert char.upsert_registry(body, "not-present", _record()) is False


def test_every_shipped_open_family_is_the_only_kind_that_carries_a_record():
    """The NDA invariant on the SHIPPED data, not only on the code path."""
    for ent in _registry()["pdks"]:
        if not isinstance(ent, dict):
            continue
        rec = (ent.get(params.PARAMS_KEY) or {}).get(params.MEASURED_KEY)
        if isinstance(rec, dict):
            assert ent.get("open_source") is True, (
                f"`{ent.get('name')}` is not marked open_source and still "
                f"ships measured device constants")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE: the fix is data-driven, not family-driven
# ═══════════════════════════════════════════════════════════════════════════
def test_no_pdk_family_name_appears_in_the_producer_or_the_reader():
    """If a family name appeared in either, this would be a patch for one PDK
    with a general-sounding docstring. Checked against the names the SHIPPED
    registry declares, so a family added later is covered automatically."""
    families = [str(e.get("name")) for e in _registry()["pdks"]
                if isinstance(e, dict) and e.get("name")]
    assert len(families) >= 3
    for path in (PRODUCER, READER):
        src = path.read_text(encoding="utf-8").lower()
        for fam in families:
            assert fam.lower() not in src, (
                f"`{path.name}` names the PDK family `{fam}`; it must behave "
                f"identically for every family and know none of them")


def test_no_device_primitive_name_appears_in_the_producer_or_the_reader():
    """Same argument one level down: a device name is a family literal too."""
    devices = set()
    for e in _registry()["pdks"]:
        if not isinstance(e, dict):
            continue
        for d in (e.get("device_models") or []):
            if isinstance(d, str) and len(d) > 6:
                devices.add(d.lower())
        for d in (e.get("device_map") or {}).values():
            if isinstance(d, str) and len(d) > 6:
                devices.add(d.lower())
    assert devices
    for path in (PRODUCER, READER):
        src = path.read_text(encoding="utf-8").lower()
        for dev in devices:
            assert dev not in src, f"`{path.name}` names the primitive `{dev}`"


def test_a_context_carrying_another_pdks_libs_is_refused(tmp_path):
    """The most dangerous failure this program can have, and it HAPPENED.

    The deck resolver keeps an authored fast-path table for a couple of open
    families; a selector that is not a key of that table falls back to another
    family's entry while still reporting the name that was asked for. Measured
    before this guard: a request for one shipped open family came back carrying
    ANOTHER family's model lib and device names, the MOS decks ran happily
    against the wrong process, and a full record — transconductance parameter,
    threshold, gate drive — was published under the requested family's name.
    Only the passive roles failed loudly, and only because that family's
    passive names are not the other one's.

    The guard is STRUCTURAL and trusts no name: every lib the decks would load
    must belong to the PDK root the resolver matched.
    """
    ctx = {"pdk_root": "/invented/pdks/zeta", "resolved_libs": [],
           "deck_context": {"family": "zeta", "template_family": "omega"}}
    ok, why = char.context_describes_target(
        ctx, [("/invented/pdks/omega/models/omega.lib", "tt")])
    assert ok is False
    assert "do not belong to this PDK" in why
    assert "omega" in why and "zeta" in why

    ok, _why = char.context_describes_target(
        ctx, [("/invented/pdks/zeta/models/zeta.lib", "tt")])
    assert ok is True

    # a lib the resolver itself listed is this PDK's, wherever it sits
    ctx2 = {"pdk_root": None, "resolved_libs": ["/staged/in/a/project.lib"],
            "deck_context": {}}
    assert char.context_describes_target(ctx2,
                                        [("/staged/in/a/project.lib", "")])[0]
    assert char.context_describes_target(ctx2, [("/elsewhere.lib", "")])[0] \
        is False

    # nothing to check against -> do not invent a check
    assert char.context_describes_target(
        {}, [("/anything.lib", "")])[0] is True


def test_a_prefix_collision_is_not_treated_as_containment():
    """`/foss/pdks/zeta2` is not under `/foss/pdks/zeta`."""
    ctx = {"pdk_root": "/foss/pdks/zeta", "resolved_libs": [],
           "deck_context": {}}
    assert char.context_describes_target(
        ctx, [("/foss/pdks/zeta2/models/x.lib", "tt")])[0] is False
    assert char.context_describes_target(
        ctx, [("/foss/pdks/zeta/models/x.lib", "tt")])[0] is True


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_every_published_section_lives_under_its_own_pdk(family):
    """The same invariant asserted on the SHIPPED data, so a record measured
    against a foreign lib cannot sit in the registry even if the guard that
    now prevents it were removed."""
    _fam, rec = params.measured_record(family)
    roots = set()
    for cr in (rec.get("corners") or {}).values():
        for lib, _sec in cr.get("sections") or []:
            roots.add("/".join(str(lib).split("/")[:4]))
    assert len(roots) == 1, (
        f"{family}'s record was measured against model libs from more than "
        f"one PDK tree: {sorted(roots)}")


def test_the_registry_family_resolves_from_the_selector_the_caller_asked_for():
    """Measured defect: a family whose libs PARSE to a name with the
    punctuation dropped matched no registry entry, so its declared supply could
    not be read and the run refused with NO_SUPPLY on a family whose supply the
    registry states plainly. The selector is the thing the caller and the
    registry agree on, so it has to be one of the candidates."""
    for family in CHARACTERIZED:
        parsed = re.sub(r"\W+", "", family)          # the parse's own shape
        ctx = {"registry_family": None, "family": parsed}
        assert char.registry_family_for(family, ctx) == family
    assert char.registry_family_for("no-such-family-anywhere",
                                    {"family": None}) is None


def test_the_measured_half_is_read_through_the_one_matcher():
    """Two matchers is how the electrical constants silently end up read off a
    different family than the layout minima of the same request."""
    import pdk_analog_layout_minima as minima
    assert params.resolve_family is minima.resolve_family


def test_the_producer_binds_devices_through_the_one_binder():
    """Measuring k' on a device A3 does not instantiate would publish a
    constant describing something the design never builds."""
    src = inspect.getsource(char.resolve_target)
    assert "resolve_pdk_context" in src
    import analog_a3_netlist_emit as a3
    assert "resolution" in inspect.signature(a3.resolve_pdk_context).parameters


def test_passing_a_resolution_in_does_not_change_the_project_driven_path():
    """The kwarg added for the PDK-shaped caller must be a no-op for every
    existing per-block call site."""
    import analog_a3_netlist_emit as a3
    sig = inspect.signature(a3.resolve_pdk_context)
    assert sig.parameters["resolution"].default is None


# ═══════════════════════════════════════════════════════════════════════════
# IN-CONTAINER: the record reproduces from what it itself states
# ═══════════════════════════════════════════════════════════════════════════
def _eda_container():
    """A RUNNING container that exposes ngspice, or None -> the caller SKIPS.

    Skip, never fail: a published constant is a property of the PDK, and a
    machine with no EDA container has no opinion about it."""
    if not shutil.which("docker"):
        return None
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                               capture_output=True, text=True,
                               timeout=60).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    for name in names:
        try:
            if char._ars._resolve_ngspice(name):
                return name
        except Exception:
            continue
    return None


@pytest.mark.parametrize("family", CHARACTERIZED)
def test_the_published_constants_reproduce_from_the_record_itself(family):
    """The strongest arm, and the one that makes the record a MEASUREMENT.

    Nothing here consults the resolvers. The deck is rebuilt from what the
    record ITSELF states — the model-lib sections, the primitive, the geometry
    idiom, the terminal count, the bias grid, the supply and the temperature —
    it is run against the real PDK, and the extracted transconductance
    parameter must come back to the published value. A record that cannot be
    re-run from its own provenance is a number somebody remembers.
    """
    container = _eda_container()
    if container is None:
        pytest.skip("no running container exposes ngspice")
    ngspice = char._ars._resolve_ngspice(container)

    prov = params.measured_provenance(family)
    published = params.measured_values(family)
    role = "nmos"
    key = "k_prime_n_ua_per_v2"
    if key not in published or role not in (prov.get("bias") or {}):
        pytest.skip(f"{family} publishes no {key}")
    idiom = (prov.get("deck_idiom") or {}).get(role) or {}
    deck = char.render_mos_deck(
        role, prov["devices"][role], idiom.get("terminals"),
        idiom.get("geometry_units") == "metric",
        [tuple(s) for s in prov["sections"]],
        float(prov["supply_v"]), float(prov["temp_c"]),
        prov["bias"][role]["vgs_v"], with_diode=False)

    stage = f"/tmp/pdk_char_repro_{abs(hash(family)) % 10 ** 8}"
    r = char.run_deck(container, ngspice, stage, f"{role}_repro", deck)
    try:
        char._ars._docker(container, f"rm -rf {stage}", timeout=60)
    except Exception:
        pass
    if not r["ok"]:
        pytest.skip(f"this container cannot run {family}'s deck: {r['fatal']}")

    vgs = prov["bias"][role]["vgs_v"]
    k, vth, why = char.extract_square_law(
        vgs[0], r["meas"].get("id1"), vgs[2], r["meas"].get("id3"),
        char.MOS_W_UM / char.MOS_L_UM)
    assert why == "", why
    assert k * 1e6 == pytest.approx(published[key], rel=1e-6), (
        f"{family} publishes {key} = {published[key]}, but re-running the "
        f"record's own deck against the PDK measures {k * 1e6}")
    assert vth == pytest.approx(published["vth_n_extracted_v"], rel=1e-6)
