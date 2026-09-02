"""An incremental converter's coefficients are DERIVED, not tabulated.

MEASURED (round 20): the entry carried the FREE-RUNNING second-order set
a1 = a2 = 1/2, cited to Boser & Wooley 1988, for a converter the same entry
calls incremental in five places and whose own L5 declares
"resets/accumulates per conversion window". With that set one DAC decision
moves the loop filter by half the reference and the first integrator saturates
in TWO clocks of a 256-clock window; the bitstream carried no code at any
input.

The defect is not the number, it is that `osr` never entered the choice. These
tests pin that it does.
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as m  # noqa: E402

CONSTS = {"integrator_swing_fraction_of_vdd": 0.833}
DERIVE = m.COEFFICIENT_DERIVATIONS["incremental_cifb"]


def _c(order, osr, vref=1.0, vdd=1.2):
    return DERIVE(order, {"osr": osr, "vref": vref, "vdd": vdd}, CONSTS)


def test_THE_CONTROL_the_set_changes_when_osr_changes():
    # This is the whole finding. The tabulated set returned [0.5, 0.5] at
    # every OSR; a coefficient that does not move with the window length is
    # not a coefficient for a converter that resets every window.
    seen = {osr: _c(2, osr)[0] for osr in (64, 128, 256, 512)}
    assert len(set(seen.values())) == 4, seen
    # and it moves the RIGHT way: a longer window needs a smaller coefficient
    ordered = [seen[o] for o in (64, 128, 256, 512)]
    assert ordered == sorted(ordered, reverse=True), seen


def test_the_set_changes_when_order_changes():
    assert _c(1, 256)[0] != _c(2, 256)[0]
    assert len(_c(1, 256)) == 1 and len(_c(2, 256)) == 2


def test_first_order_lands_on_the_textbook_result():
    # a first-order incremental integrator accumulates N residues from zero,
    # so a = usable_swing / (N * vref). Independent check on the closed form.
    a = _c(1, 256)[0]
    assert a == pytest.approx(1.2 * 0.833 / (256 * 1.0), rel=1e-9)


def test_the_second_order_set_satisfies_its_own_bound():
    # prod(a) * vref * N**L / L! <= usable_swing, with equality at the bound
    for order, osr in ((1, 64), (2, 64), (2, 256), (2, 512)):
        a = _c(order, osr)
        prod = math.prod(a)
        assert prod * 1.0 * osr ** order / math.factorial(order) == \
            pytest.approx(1.2 * 0.833, rel=1e-9)


def test_the_derived_set_is_far_below_the_free_running_one():
    # the regression this catches: silently reverting to the tabulated value
    assert _c(2, 256)[0] < 0.5 / 10


def test_coefficients_are_per_stage_and_equal():
    a = _c(2, 256)
    assert len(a) == 2 and a[0] == a[1]


@pytest.mark.parametrize("sv,missing", [
    ({"osr": 0, "vref": 1.0, "vdd": 1.2}, "osr"),
    ({"osr": 256, "vref": 0, "vdd": 1.2}, "vref"),
    ({"osr": 256, "vref": 1.0, "vdd": 0}, "vdd"),
    ({}, "everything"),
])
def test_an_underivable_set_is_refused_by_name_never_defaulted(sv, missing):
    with pytest.raises(m.LibraryEntryError) as e:
        DERIVE(2, sv, CONSTS)
    assert "ABSENT, never defaulted" in str(e.value)


def test_a_zero_or_negative_order_is_refused():
    with pytest.raises(m.LibraryEntryError):
        DERIVE(0, {"osr": 256, "vref": 1.0, "vdd": 1.2}, CONSTS)


def test_the_entry_derives_rather_than_tabulating():
    ds = None
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            cand = v["delta_sigma"]
            if isinstance(cand, dict) and "circuit_class_citation" in cand:
                ds = cand
                break
    assert ds is not None, "delta_sigma library entry not found"
    assert ds.get(m.COEFFICIENT_DERIVATION_KEY) == "incremental_cifb"
    assert m.COEFFICIENT_SETS_KEY not in ds, (
        "the tabulated free-running set is back")


def test_the_citation_names_the_regime_it_is_used_in():
    ds = None
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            cand = v["delta_sigma"]
            if isinstance(cand, dict) and "circuit_class_citation" in cand:
                ds = cand
                break
    cite = ds["circuit_class_citation"]
    assert "INCREMENTAL" in cite.upper()
    assert "different regime" in cite


# ── the bias the coefficient implies, and the liveness the window needs ────

def _entry():
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            cand = v["delta_sigma"]
            if isinstance(cand, dict) and "circuit_class_citation" in cand:
                return cand
    raise AssertionError("delta_sigma entry not found")


def _env(order=2, osr=256, vref=1.0, vdd=1.2, enob=14, fclk=1.0):
    e = {"order": order, "osr": osr, "vref": vref, "vdd": vdd,
         "enob": enob, "fclk": fclk}
    e.update(_entry()["constants"])
    e.update({"kt_j_300k": 4.141947e-21, "cap_area_ff_per_um2": 1.5,
              "rsheet_ohm_per_sq": 260.0, "vth_n_extracted_v": 0.5})
    return e


def _derived(name, **kw):
    for spec in _entry()["requires_derived"]:
        if spec["name"] == name:
            return eval(spec["expr"], {"__builtins__": {}}, _env(**kw)), spec
    raise AssertionError(name)


def test_the_bias_resistor_is_derived_not_a_nominal():
    assert "r_ib_l_um" not in _entry()["constants"], (
        "the bias length is back as a hand number")
    exprs = {e["device"]: e for e in _entry()["device_param_exprs"]}
    assert "r_ib" in exprs and exprs["r_ib"]["param"] == "l"


def test_the_derived_bias_meets_the_slew_by_construction():
    # slew_margin was 0.167 with the nominal bias; deriving the bias FROM the
    # slew makes it the stated design margin exactly
    val, spec = _derived("slew_margin")
    assert val == pytest.approx(_entry()["constants"]["slew_design_margin"])
    assert val >= spec["min"]


def test_the_bias_length_moves_with_every_bound_row_it_depends_on():
    # THE CONTROL. A bias that does not follow the declaration is the defect.
    base, _ = _derived("bias_resistor_l_um")
    for kw in ({"vref": 0.8}, {"fclk": 2.0}, {"enob": 12}, {"vdd": 1.1}):
        other, _ = _derived("bias_resistor_l_um", **kw)
        assert other != pytest.approx(base), kw


def test_the_bias_is_INDEPENDENT_of_osr_and_that_is_physics():
    # MEASURED while writing the control above, and it is not a missing
    # dependency: the sampling capacitor's kT/C budget scales as 1/osr while
    # the load ratio (1 + miller)/coefficient scales as osr, so the OTA's
    # LOAD — and therefore the current that slews it — is invariant. A longer
    # window needs a smaller coefficient AND a smaller sampling capacitor,
    # and the two cancel exactly. Pinned so a future edit that breaks the
    # cancellation is visible rather than silent.
    base, _ = _derived("bias_resistor_l_um")
    for osr in (64, 128, 512, 1024):
        other, _ = _derived("bias_resistor_l_um", osr=osr)
        assert other == pytest.approx(base, rel=1e-9), osr
    # the two halves that cancel must each still be moving
    assert _c(2, 64)[0] != _c(2, 512)[0]


def test_the_bias_length_is_admitted_for_this_declaration():
    val, spec = _derived("bias_resistor_l_um")
    assert spec["min"] <= val <= spec["max"]
    assert val == pytest.approx(15.0889, rel=1e-3)


def test_liveness_nodes_are_declared_and_drawn():
    live = _entry()[m.LIVENESS_NODES_KEY]
    assert set(live) == {"reset", "feedback", "decision"}
    assert m.library_invariants() == []


def test_a_liveness_net_the_entry_never_draws_is_faulted():
    import copy
    lib = copy.deepcopy({k: v for k, v in m.LIBRARY.items()
                         if v.get(m.STAGE_KEY)})
    for e in lib.values():
        e[m.LIVENESS_NODES_KEY] = {"reset": "not_a_net"}
    assert any("never draws" in p for p in m.library_invariants(lib))


def test_the_derivation_states_what_it_does_NOT_claim():
    """A bound that prevents overflow is not a converter, and the docstring
    must say so. v1.16.10's landing message credited this derivation with a
    density measured on a DIFFERENT coefficient; the narrowed claim is the
    thing that stops that being inherited."""
    doc = DERIVE.__doc__
    assert "DOES NOT SET THE GAIN" in doc
    assert "NECESSARY" in doc and "SUFFICIENT" in doc
    # the measured pair that makes the point must stay with it
    assert "0.1288" in doc and "0.0325" in doc
