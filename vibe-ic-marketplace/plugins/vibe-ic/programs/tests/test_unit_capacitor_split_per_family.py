"""The unit-array capacitor split, on EVERY family the registry describes.

vibe-ic#2056's last residual. The split has been live since v1.17.95 and was
exercised on ONE family (ihp-sg13g2). Two families reach it and neither was
covered: sky130A, whose measured constants are different numbers entirely
(carea 2.00009 / cperi 0.164325 against 1.5 / 0.04), and gf180mcuD, which
states a device maximum and carries NO measured capacitance constants at all.

WHAT THAT SECOND CASE WAS DOING, MEASURED. `split_oversize_capacitors` returned
`(devices, exprs, [], [])` the moment `cap_area_ff_per_um2` was missing —
"nothing was split", which is indistinguishable from "nothing was oversize" —
while the provenance block, keyed on `maxima_available` alone, went on to print
the note saying a capacitor above the maximum "is realised as N unit devices in
parallel". So on gf180mcuD an oversize capacitor was carried at its library
length under a record asserting it had been split. Detecting the oversize needs
only the maximum and the drawn length, so it is now REFUSED BY NAME, naming the
constant that is missing.

The test is SYNTHETIC and family-agnostic: one capacitor, the same one, offered
to every family in the registry, and each family graded against ITS OWN stated
constants. No family literal decides an assertion — the registry does.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_a2_topology_emit as A2          # noqa: E402
import pdk_analog_layout_minima as MIN        # noqa: E402

_REG = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
_FAMILIES = [p["name"] for p in _REG["pdks"]]

#: One oversize capacitor, offered unchanged to every family. 400 u is above
#: every maximum any family in the registry states, so no family is exempted
#: from the question by the fixture rather than by its own record.
_W_UM = 10.0
_L_UM = 400.0


def _measured(family):
    p = [x for x in _REG["pdks"] if x["name"] == family][0]
    m = (((p.get("analog_device_params") or {}).get("measured") or {})
         .get("corners", {}).get("typ", {}).get("params", {}) or {})
    return {k: v for k, v in m.items() if isinstance(v, (int, float))}


def _split(family):
    _f, maxima = MIN.layout_maxima(family)
    _g, minima = MIN.layout_minima(family)
    devs = [{"name": "c_big", "role": A2.CAP_ROLE, "w": _W_UM}]
    exprs = [{"device": "c_big", "param": "l", "expr": repr(_L_UM)}]
    return A2.split_oversize_capacitors(devs, exprs, {}, maxima, minima,
                                        _measured(family))


def _states_maximum(family):
    _f, maxima = MIN.layout_maxima(family)
    return MIN.max_length_um(maxima, A2.CAP_ROLE) is not None


def _has_constants(family):
    c = _measured(family).get("cap_area_ff_per_um2")
    return isinstance(c, (int, float)) and c > 0


def test_the_registry_still_carries_all_three_states():
    """The population this module is about. If a registry edit collapses it to
    two, the parametrised tests below silently stop covering a case — so the
    membership is asserted, not assumed."""
    splits = [f for f in _FAMILIES if _states_maximum(f) and _has_constants(f)]
    refuses = [f for f in _FAMILIES
               if _states_maximum(f) and not _has_constants(f)]
    silent = [f for f in _FAMILIES if not _states_maximum(f)]
    assert len(splits) >= 2, splits
    assert refuses, "no family exercises the no-constants refusal any more"
    assert silent, "no family exercises the no-maximum path any more"


@pytest.mark.parametrize("family", _FAMILIES)
def test_every_family_answers_the_same_capacitor_from_its_own_record(family):
    """Three outcomes, and which one a family gets is decided by ITS OWN
    registry record — never by a name in this file."""
    _devs, _exprs, records, refusals = _split(family)
    if _states_maximum(family) and _has_constants(family):
        assert records and not refusals, (family, refusals)
    elif _states_maximum(family):
        assert refusals and not records, (family, records)
    else:
        assert not records and not refusals, (family, records, refusals)


@pytest.mark.parametrize(
    "family", [f for f in _FAMILIES
               if _states_maximum(f) and _has_constants(f)])
def test_the_units_are_in_range_and_preserve_the_value(family):
    """N in-range units whose total value, on THIS family's own carea/cperi,
    is within CAP_SPLIT_TOLERANCE of what the sizing asked for."""
    _f, maxima = MIN.layout_maxima(family)
    lmax = MIN.max_length_um(maxima, A2.CAP_ROLE)
    wmax = MIN.max_width_um(maxima, A2.CAP_ROLE)
    _devs, _exprs, records, refusals = _split(family)
    assert not refusals, (family, refusals)
    r = records[0]
    assert r["units"] > 1, r
    assert 0 < r["unit_l_um"] <= lmax, r
    if wmax is not None:
        assert r["unit_w_um"] <= wmax, r

    m = _measured(family)
    carea = float(m["cap_area_ff_per_um2"])
    cperi = float(m.get("cap_perim_ff_per_um") or 0.0)
    target = A2.capacitance_ff(_W_UM, _L_UM, carea, cperi)
    got = r["units"] * A2.capacitance_ff(r["unit_w_um"], r["unit_l_um"],
                                         carea, cperi)
    assert abs(got - target) <= A2.CAP_SPLIT_TOLERANCE * target, (
        family, target, got)
    # ...and the record's own arithmetic agrees with the recomputation, so a
    # published `relative_value_error` cannot drift from the numbers beside it.
    assert r["relative_value_error"] <= A2.CAP_SPLIT_TOLERANCE, r
    assert r["cap_area_ff_per_um2"] == pytest.approx(carea)


@pytest.mark.parametrize(
    "family", [f for f in _FAMILIES
               if _states_maximum(f) and not _has_constants(f)])
def test_a_family_with_no_constants_is_REFUSED_BY_NAME(family):
    """Not silently carried at the library length. The refusal names the
    device, the length, the maximum it is above, and the missing constant."""
    _devs, _exprs, records, refusals = _split(family)
    assert not records
    assert len(refusals) == 1, refusals
    msg = refusals[0]
    assert msg.startswith("c_big:"), msg
    assert "cap_area_ff_per_um2" in msg, msg
    assert "400" in msg, msg


@pytest.mark.parametrize(
    "family", [f for f in _FAMILIES
               if _states_maximum(f) and not _has_constants(f)])
def test_that_refusal_does_NOT_fire_on_a_capacitor_that_is_IN_range(family):
    """THE CONTROL. A refusal that fires whatever the geometry is an accusation
    about the PDK, not a finding about the device."""
    _f, maxima = MIN.layout_maxima(family)
    _g, minima = MIN.layout_minima(family)
    lmax = MIN.max_length_um(maxima, A2.CAP_ROLE)
    devs = [{"name": "c_small", "role": A2.CAP_ROLE, "w": _W_UM}]
    exprs = [{"device": "c_small", "param": "l", "expr": repr(lmax / 2.0)}]
    _d, _e, records, refusals = A2.split_oversize_capacitors(
        devs, exprs, {}, maxima, minima, _measured(family))
    assert not refusals and not records, (family, refusals, records)
