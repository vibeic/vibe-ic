"""vibe-ic#1952 — the A2 topology library sized its resistors from a static
constant, so on any PDK whose poly-resistor rule states a wider minimum the
NETLIST carried a width the LAYOUT is not allowed to draw.

The measured symptom sits six steps downstream, at A6, where KLayout-extract ->
netgen compares the two:

    w circuit1: 5e-07   circuit2: 3.5e-07   (delta=35.3%, cutoff=0%)
    Final result: Circuits do NOT match uniquely (property errors present)

WHAT MAKES EACH TEST BELOW A REAL TEST

* RED arm — `ihp-sg13g2` and `gf180mcuD`. On the pre-fix sources the emitted
  `w_res` is 0.35 on both, and both assertions below fail. Reproduced on
  `origin/main` 6b7136f4c before the fix was written.
* CONTROL arm — `sky130A`, whose measured minimum (0.33) sits BELOW the library
  nominal. This one PASSES on the pre-fix sources too, and that is the point:
  it fails against a "fix" that sets the width from the PDK rather than
  flooring it at it, and against any fix that raises the constant globally. It
  is what separates a floor from a retune.
* GENERIC arm — the reader is driven against a SYNTHETIC registry carrying an
  invented family with an invented minimum. No shipped family is involved, so
  the core cannot be passing by knowing about one.
* SOURCE arm — the clamp path is read and asserted to contain no PDK family
  name at all: which family is affected must be a property of the registry
  DATA, not of a branch in the code.

Every number asserted against a shipped family is READ OUT OF THE REGISTRY at
test time and never retyped here, so this file cannot drift from the data and
cannot be the place a wrong constant is kept alive.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path
import pdk_analog_layout_minima as minima

from _analog_producer_fixture import (
    A2, PROGRAMS, block, make_project, run_prog, bdir, read_json)

# The role whose floor vibe-ic#1952 is about, and the library constant that
# carries it. Both are generic tokens, not PDK content.
ROLE = "res"
CONSTANT = "w_res"

REGISTRY = PROGRAMS / "pdk_registry.json"
READER = PROGRAMS / "pdk_analog_layout_minima.py"
EMITTER = PROGRAMS / "analog_a2_topology_emit.py"


def _declared_min(selector: str) -> float:
    """The floor the SHIPPED registry declares for `selector`. Read, never
    retyped — a test that hardcodes the number stops testing the registry."""
    _fam, roles = minima.layout_minima(selector)
    w = minima.min_width_um(roles, ROLE)
    assert w is not None, (
        f"the registry declares no measured `{ROLE}` minimum for "
        f"`{selector}`; this test is about that record and cannot run "
        f"without it")
    return w


def _library_nominal() -> float:
    """The library's own un-floored `w_res`, read out of the emitter source's
    LIBRARY table rather than restated, so the control below compares against
    what the library actually ships."""
    import analog_a2_topology_emit as a2
    v = (a2.LIBRARY["ldo"].get("constants") or {})[CONSTANT]
    return float(v)


def _emit(tmp_path: Path, selector: str, name: str = "vreg_alpha"):
    p = make_project(tmp_path / re.sub(r"\W+", "_", selector),
                     [block(name, "ldo")])
    cp = run_prog(A2, p, "--pdk", selector)
    assert cp.returncode == 0, f"{cp.stdout}{cp.stderr}"
    return read_json(bdir(p, name) / "topology.json"), \
        (bdir(p, name) / "topology.md").read_text(encoding="utf-8")


def _res_widths(ir) -> list:
    return [d["w"] for d in ir["devices"] if d["role"] == ROLE]


# ── RED on the pre-fix sources: two shipped families, one static constant ──
@pytest.mark.parametrize("selector", ["ihp-sg13g2", "gf180mcuD"])
def test_res_width_is_not_emitted_below_the_target_pdk_layout_minimum(
        tmp_path, selector):
    """The defect itself. Pre-fix this emits 0.35 against a 0.50 / 0.80 rule.

    Asserted as `>= the registry's own number` and not as `== 0.5`: the test
    states the INVARIANT (a netlist width the layout cannot draw is illegal),
    so correcting the registry constant corrects the test with it.
    """
    lo = _declared_min(selector)
    ir, _md = _emit(tmp_path, selector)

    assert ir["constants"][CONSTANT] >= lo, (
        f"`constants.{CONSTANT}` = {ir['constants'][CONSTANT]} is below the "
        f"{selector} drawn minimum {lo}. The layout generator must clamp the "
        f"drawn device up to {lo} while this netlist keeps "
        f"{ir['constants'][CONSTANT]}, which is a device-property mismatch on "
        f"every block by construction (vibe-ic#1952).")
    for w in _res_widths(ir):
        assert w >= lo, (
            f"a `{ROLE}` device is emitted at w={w}, below the {selector} "
            f"drawn minimum {lo}")


@pytest.mark.parametrize("selector", ["ihp-sg13g2", "gf180mcuD"])
def test_the_floor_is_exactly_the_pdk_rule_and_not_a_chosen_number(
        tmp_path, selector):
    """Derive, don't tune: when the floor fires the emitted width is the
    registry's rule value EXACTLY — not that value plus a margin somebody
    liked, which would be a tuning constant wearing a rule's name."""
    lo = _declared_min(selector)
    ir, _md = _emit(tmp_path, selector)
    assert ir["constants"][CONSTANT] == lo
    assert set(_res_widths(ir)) == {lo}


@pytest.mark.parametrize("selector", ["ihp-sg13g2", "gf180mcuD"])
def test_every_clamp_is_recorded_with_the_rule_it_came_from(
        tmp_path, selector):
    """A silent clamp is the same defect one step later: A4 would sweep, and a
    reader would compare, a geometry nothing disclosed had been changed."""
    lo = _declared_min(selector)
    ir, md = _emit(tmp_path, selector)
    prov = ir["_provenance"]
    lm = prov["layout_minima"]

    assert lm["minima_available"] is True
    assert lm["family"], "the resolved registry family is not recorded"
    assert lm["measured_from"], (
        "the record must carry the `_measured_from` citation of the PDK rule "
        "it was read from; a number with no source is the thing this replaces")
    assert f"constants.{CONSTANT}" in prov["fields_clamped"]
    assert prov["clamped_to_pdk_minimum"] is True

    targets = {c["target"] for c in lm["clamps"]}
    assert f"constants.{CONSTANT}" in targets
    assert {f"devices.{d['name']}.w"
            for d in ir["devices"] if d["role"] == ROLE} <= targets
    for c in lm["clamps"]:
        assert c["pdk_minimum"] == lo
        assert c["library_value"] < lo
        assert c["value"] == lo
        assert c["rule"], "the clamp does not name the rule that forced it"
        assert c["rule_text"], "the clamp does not quote the rule"

    assert "floored" in md, "topology.md does not state that a width was moved"
    assert str(lo) in md


# ── CONTROL: a PDK whose minimum is BELOW the library value keeps it ───────
def test_a_pdk_whose_minimum_is_below_the_library_value_is_left_untouched(
        tmp_path):
    """The control that makes this a FLOOR.

    `sky130A` states 0.33 for the generic poly resistor — below the library's
    own nominal. A fix that SET the width from the PDK, or that raised the
    library constant globally, would change this family's geometry; a floor
    must not. This test passes on the pre-fix sources by construction, which
    is exactly what a control is for.
    """
    lo = _declared_min("sky130A")
    nominal = _library_nominal()
    assert lo < nominal, (
        "this control is only meaningful while the family's minimum sits "
        f"below the library nominal; registry says {lo}, library says "
        f"{nominal}. If the registry changed, pick another control family.")

    ir, _md = _emit(tmp_path, "sky130A")
    assert ir["constants"][CONSTANT] == nominal, (
        f"the library nominal {nominal} is legal on this process ({lo}) and "
        f"must survive untouched; got {ir['constants'][CONSTANT]}")
    assert set(_res_widths(ir)) == {nominal}
    # Deliberately NO assertion about the provenance shape here: this test
    # must be runnable, and green, against the PRE-FIX sources, which carry no
    # such field. Mixing the two would turn the control into another RED arm
    # and it would stop proving that the fix left this family alone.


def test_the_control_family_still_records_that_the_floor_was_checked(
        tmp_path):
    """The other half of the control, and this one IS red pre-fix: an
    unchanged width must be distinguishable from an unchecked one."""
    ir, md = _emit(tmp_path, "sky130A")
    assert ir["_provenance"]["fields_clamped"] == []
    assert ir["_provenance"]["clamped_to_pdk_minimum"] is False
    assert ir["_provenance"]["layout_minima"]["clamps"] == []
    assert ir["_provenance"]["layout_minima"]["minima_available"] is True
    assert "no width was changed" in md


def test_a_length_constant_is_not_floored_by_a_width_rule(tmp_path):
    """`l_unit` is a length in the same units as the width. The family with
    the largest floor is the one that would corrupt it, so assert there."""
    import analog_a2_topology_emit as a2
    l_nominal = (a2.LIBRARY["ldo"]["constants"] or {})["l_unit"]
    ir, _md = _emit(tmp_path, "gf180mcuD")
    assert ir["constants"]["l_unit"] == l_nominal, (
        "a width rule moved a LENGTH constant — the floor is being applied by "
        "guessing from the name instead of from the declared constant_roles")


def test_a_family_with_no_measured_minimum_floors_nothing_and_says_so(
        tmp_path):
    """Degrade loudly. A family the registry carries no minima for must not
    read as 'checked and clean' — the artefact has to distinguish
    'nothing was below the floor' from 'no floor was applied'."""
    fam, roles = minima.layout_minima("nangate45")
    assert fam and not roles, (
        "this test needs a shipped family with NO measured minima record; "
        "`nangate45` now has one, so pick another")
    ir, md = _emit(tmp_path, "nangate45")
    assert ir["constants"][CONSTANT] == _library_nominal()
    lm = ir["_provenance"]["layout_minima"]
    assert lm["minima_available"] is False
    assert lm["clamps"] == []
    assert "has not been checked against this process" in md


# ── the core is generic: an invented family, an invented rule ─────────────
def test_the_reader_floors_against_a_pdk_it_has_never_seen(tmp_path):
    """Drive the reader against a SYNTHETIC registry. No shipped family name
    appears, so nothing here can be satisfied by a special case."""
    synth = tmp_path / "synthetic_registry.json"
    synth.write_text(json.dumps({
        "schema_version": 1,
        "pdks": [{
            "name": "zeta-fictional-process",
            "analog_device_layout_minima": {
                "_measured_from": "an invented rule record",
                "roles": {ROLE: {"min_width_um": 4.25,
                                 "device": "invented_primitive",
                                 "rule": "ZR.1",
                                 "rule_text": "invented minimum width"}},
            },
        }],
    }), encoding="utf-8")

    fam, roles = minima.layout_minima("zeta-fictional", path=synth)
    assert fam == "zeta-fictional-process"
    assert minima.min_width_um(roles, ROLE) == 4.25
    assert minima.minima_source("zeta-fictional", path=synth) == \
        "an invented rule record"

    # the floor itself: below -> raised to the rule; at/above -> untouched
    assert minima.floor_width(0.35, 4.25) == (4.25, 0.35)
    assert minima.floor_width(4.25, 4.25) == (4.25, None)
    assert minima.floor_width(9.0, 4.25) == (9.0, None)
    # and a family with no record floors nothing rather than defaulting
    assert minima.floor_width(0.35, None) == (0.35, None)
    assert minima.layout_minima("no-such-family", path=synth) == (None, {})


def test_the_producer_floors_a_synthetic_family_through_its_own_code_path(
        tmp_path, monkeypatch):
    """Same invented family, but driven through the PRODUCER's clamp so the
    genericity claim covers the emitter and not only the reader."""
    import analog_a2_topology_emit as a2
    lib = a2.LIBRARY["ldo"]
    constants = dict(lib["constants"])
    devices = [dict(d) for d in lib["devices"]]
    roles = {ROLE: {"min_width_um": 4.25, "rule": "ZR.1",
                    "rule_text": "invented minimum width"}}

    clamps = a2.floor_geometry_to_pdk(lib, constants, devices, roles)

    assert constants[CONSTANT] == 4.25
    assert constants["l_unit"] == lib["constants"]["l_unit"]
    assert all(d["w"] == 4.25 for d in devices if d["role"] == ROLE)
    assert {c["rule"] for c in clamps} == {"ZR.1"}
    # the library table itself must be unchanged — the clamp works on a copy,
    # or the second block emitted in one process would inherit the first
    # block's PDK.
    assert lib["constants"][CONSTANT] != 4.25
    assert all(d["w"] != 4.25 for d in lib["devices"] if d["role"] == ROLE)


def test_two_blocks_on_one_run_do_not_contaminate_each_other(tmp_path):
    """Guards the same in-place-mutation failure end to end: the LIBRARY is a
    module-level dict shared by every block in a run."""
    p = make_project(tmp_path / "multi",
                     [block("vreg_alpha", "ldo"), block("vreg_beta", "ldo")])
    assert run_prog(A2, p, "--pdk", "gf180mcuD").returncode == 0
    lo = _declared_min("gf180mcuD")
    for name in ("vreg_alpha", "vreg_beta"):
        ir = read_json(bdir(p, name) / "topology.json")
        assert ir["constants"][CONSTANT] == lo
        for c in ir["_provenance"]["layout_minima"]["clamps"]:
            assert c["library_value"] == _library_nominal(), (
                f"{name} was floored from {c['library_value']}, not from the "
                f"library nominal — a previous block's clamp persisted")


# ── the fix is data-driven, not family-driven ─────────────────────────────
def test_no_pdk_family_name_appears_in_the_reader_or_the_clamp(tmp_path):
    """If a family name appeared in either, the fix would be an SG13G2 patch
    with a general-sounding docstring. Checked against the names the SHIPPED
    registry declares, so a family added later is covered automatically."""
    families = [str(e.get("name")) for e in
                json.loads(REGISTRY.read_text(encoding="utf-8"))["pdks"]
                if isinstance(e, dict) and e.get("name")]
    assert len(families) >= 3

    reader = READER.read_text(encoding="utf-8")
    for fam in families:
        assert fam.lower() not in reader.lower(), (
            f"`{READER.name}` names the PDK family `{fam}`; the reader must "
            f"behave identically for every family and know none of them")

    # In the emitter, the check is scoped to the functions that IMPLEMENT the
    # floor and resolve the family — asserted on the live objects, so renaming
    # or moving one cannot quietly drop it from the scan. (The module's
    # `--pdk` help text has named a family in prose since long before this
    # issue; a whole-file scan would be measuring that, not the fix.)
    import inspect

    import analog_a2_topology_emit as a2
    scanned = (a2.floor_geometry_to_pdk, a2.pdk_device_params, a2.build_ir,
               a2.emit_for_block)
    for fn in scanned:
        body = inspect.getsource(fn)
        for fam in families:
            assert fam.lower() not in body.lower(), (
                f"`{EMITTER.name}.{fn.__name__}` names the PDK family "
                f"`{fam}`; which family is floored must be registry DATA")


def test_every_registry_minimum_cites_the_rule_it_was_read_from(tmp_path):
    """A number with no provenance is the constant this issue is about,
    relocated. Holds for every family that declares a record, including any
    added after this test was written."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    declared = 0
    for ent in data["pdks"]:
        rec = ent.get("analog_device_layout_minima")
        if not isinstance(rec, dict):
            continue
        declared += 1
        assert isinstance(rec.get("_measured_from"), str) \
            and rec["_measured_from"].strip(), (
            f"{ent.get('name')}.analog_device_layout_minima has no "
            f"`_measured_from` citation")
        roles = rec.get("roles") or {}
        assert roles, f"{ent.get('name')} declares an empty `roles` map"
        for role, r in roles.items():
            assert isinstance(r.get(minima.MIN_WIDTH_KEY), (int, float))
            assert r[minima.MIN_WIDTH_KEY] > 0
            assert r.get("rule"), f"{ent.get('name')}.{role} names no rule"
            assert r.get("rule_text"), \
                f"{ent.get('name')}.{role} quotes no rule text"
    assert declared >= 3, (
        "fewer than three families declare layout minima; this fix was "
        "measured on three")
