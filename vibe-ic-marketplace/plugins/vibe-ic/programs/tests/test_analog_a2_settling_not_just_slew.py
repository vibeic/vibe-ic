"""Slewing to the answer and settling on it are different questions.

WHAT WAS MISSING, AND WHY IT SURVIVED
=====================================
The `delta_sigma` entry has bounded the LARGE-signal question since v1.16.10
-- can the bias move a full reference step in the part of a clock phase the
entry budgets for the transfer -- and `slew_margin` passes it comfortably. It
never bounded whether the loop then SETTLES on that step to the resolution
the declaration asks for. A converter can slew to the answer and never settle
on it, and the bitstream it emits carries no code.

MEASURED (round 31, on the emitted netlist at OSR 64): `vsum2` and `vint`
swing TOGETHER with their difference fixed at 0.011 V, so the integrating
capacitor never changes charge. `vint` covers 0.4571..0.7427 V within ONE
clock and covers the same range over eight consecutive clocks -- it moves
0.285 V per clock and accumulates nothing.

WHAT THE BOUND IS, EXACTLY
==========================
    gm  = I_tail / integrator_input_overdrive_v
    tau = C_load / gm
    n   = t_available / tau          [time constants]
required:
    n  >= (enob + settling_lsb_fraction_bits) * ln2      [1/2 LSB of full scale]

The bias is DERIVED from the slew requirement, so substituting that
derivation collapses the value side to `vref * slew_design_margin /
integrator_input_overdrive_v`: `C_load` cancels, and with it `sampling_cap_ff`,
`osr`, `order`, `fclk` and every process constant. That is real physics -- the
slew current and the settling current are both proportional to the load -- and
it is asserted below rather than left for a reader to discover, because a
bound believed to respond to the capacitor is a bound read wrongly.

It is NOT the `slew_margin` defect (a value identically equal to a library
constant, which cannot fail on any declaration). Both sides here move on
BOUND SPEC ROWS -- the value on `vref`, the requirement on `enob` -- so the
comparison can be, and is, lost on a design's own numbers.

THE REQUIREMENT IS DERIVED, NOT TABULATED
=========================================
The retired branch `uhadc31-settling` used a flat floor of 7.0, which is the
~10-bit answer (7.62) carried against a declaration that asks for 14 bits
(10.40). Deriving the floor from `enob` is STRICTLY TIGHTER here, not looser.

BLOCKING vs ADVISORY
====================
BLOCKING at the producer's own tier, like every other `requires_derived` row:
a refusal means `topology_gap.json` and rc 2 (`RC_HONEST_GAP`) with NO
`topology.md`, so the A2 gate keeps reporting the block uncovered. It never
downgrades to a topology emitted on a default.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from _analog_producer_fixture import PROGRAMS

A2SRC = PROGRAMS / "analog_a2_topology_emit.py"


def _mod(path: Path = A2SRC):
    spec = importlib.util.spec_from_file_location(f"a2_{abs(hash(str(path)))}",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


a2 = _mod()
UNITS = {"order": "", "vdd": "V", "osr": "", "enob": "bit", "vref": "V",
         "fclk": "MHz", "fclk_max": "MHz"}
BASE = {"order": 2.0, "vdd": 1.2, "osr": 256.0, "enob": 14.0, "vref": 1.0,
        "fclk": 1.0, "fclk_max": 10.0}
FIELD = "settling_time_constants"


def _measured(mod=a2, drop=()):
    reg = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    p = [x for x in reg["pdks"] if x["name"] == "ihp-sg13g2"][0]
    m = p["analog_device_params"]["measured"]["corners"]["typ"]["params"]
    return {k: v for k, v in m.items()
            if isinstance(v, (int, float)) and k not in drop}


def _verdict(mod=a2, measured=None, **over):
    """SATISFIED / REFUSED / NOT_EVALUATED for this bound, plus the numbers."""
    sp = dict(BASE)
    sp.update(over)
    lib = mod.LIBRARY["delta_sigma"]
    units = {k: UNITS[k] for k in sp}
    ref = [r for r in mod.entry_admission(
        lib, sp, units, _measured() if measured is None else measured)
        if r.get("field") == FIELD]
    if not ref:
        return "SATISFIED", None
    if ref[0]["requirement"] == "derived_unresolvable":
        return "NOT_EVALUATED", ref[0]
    return "REFUSED", ref[0]


# ── the capability: the bound exists and is a real comparison ─────────────
def test_the_entry_carries_a_settling_bound_at_all():
    """RED before this change: the entry's `requires_derived` bounded slew,
    the drawn bias length and the sampling capacitor, and nothing asked
    whether the loop settles."""
    names = [d["name"] for d in a2.LIBRARY["delta_sigma"]["requires_derived"]]
    assert FIELD in names, names


def test_the_requirement_is_derived_from_the_declared_resolution():
    """A flat floor is a hidden resolution assumption. (enob+1)*ln2 is the
    half-LSB settling of a first-order exponential, and it MOVES."""
    env = a2.admission_env(a2.LIBRARY["delta_sigma"], dict(BASE), _measured())
    for enob in (10.0, 12.0, 14.0, 16.0):
        env["enob"] = enob
        got = a2._safe_eval(a2._SETTLING_TC_REQUIRED_EXPR, env)
        assert got == pytest.approx((enob + 1.0) * math.log(2.0), rel=1e-12)
    # and it is strictly tighter than the retired branch's flat 7.0 here
    env["enob"] = 14.0
    assert a2._safe_eval(a2._SETTLING_TC_REQUIRED_EXPR, env) > 7.0


# ── the three states ──────────────────────────────────────────────────────
def test_state_1_a_declaration_that_settles_is_admitted():
    """vref 1.0 / enob 14: 13.33 time constants against 10.40 required.

    ASSERTS THE NUMBERS, not merely the absence of a refusal. Measured
    against the base emitter during the negative control, the absence form
    of this test PASSED -- an entry with no settling bound at all also
    produces no settling refusal, so "admitted" was indistinguishable from
    "never checked". It was the one test of eighteen that did not go red
    without the change, which is the definition of a vacuous pass.
    """
    state, _ = _verdict()
    assert state == "SATISFIED"
    env = a2.admission_env(a2.LIBRARY["delta_sigma"], dict(BASE), _measured())
    value = a2._safe_eval(a2._SETTLING_TC_EXPR, env)
    need = a2._safe_eval(a2._SETTLING_TC_REQUIRED_EXPR, env)
    assert value == pytest.approx(13.3333333, rel=1e-6), value
    assert need == pytest.approx(10.3972077, rel=1e-6), need
    assert value > need


@pytest.mark.parametrize("label,over", [
    ("a reference too small for the resolution", {"vref": 0.8, "enob": 16.0}),
    ("a resolution too fine for the reference", {"enob": 19.0}),
])
def test_state_2_a_declaration_that_does_not_settle_is_REFUSED(label, over):
    """The comparison is lost on the design's OWN numbers -- which is the
    property `slew_margin` does not have, since it is identically a library
    constant for every declaration."""
    state, r = _verdict(**over)
    assert state == "REFUSED", label
    assert r["value"] < float(r["min"]), (label, r["value"], r["min"])
    # the refusal names the requirement it was held to, not only the value
    assert r["min_expr"] == a2._SETTLING_TC_REQUIRED_EXPR


def test_state_3_an_unresolvable_constant_is_NOT_EVALUATED_and_is_NAMED():
    """"Could not read it" is not "read it and it failed". A bound whose
    environment binds no value for a name has not been evaluated, and the
    report has to carry the NAME so a reader can go and bind it."""
    state, r = _verdict(measured=_measured(drop=("rsheet_ohm_per_sq",)))
    assert state == "NOT_EVALUATED"
    assert r["missing"] == ["rsheet_ohm_per_sq"]
    assert "rsheet_ohm_per_sq" in r["detail"]
    assert "NOT" in r["detail"] and "EVALUATED" in r["detail"]


def test_the_unresolvable_state_is_not_reported_as_a_failed_bound():
    """The distinction is the whole point of the third state: a missing
    constant must not be indistinguishable from a design that was measured
    and lost."""
    _, r = _verdict(measured=_measured(drop=("rsheet_ohm_per_sq",)))
    assert r["requirement"] == "derived_unresolvable"
    assert "value" not in r and "min" not in r


# ── what the bound does and does not respond to ───────────────────────────
@pytest.mark.parametrize("over", [
    {"osr": 64.0}, {"osr": 512.0}, {"order": 1.0}, {"vdd": 1.3},
    {"fclk": 0.1}, {"fclk": 10.0}, {"fclk_max": 1.0}, {"enob": 12.0},
])
def test_the_count_is_independent_of_the_load_and_of_the_clock(over):
    """`C_load` CANCELS, because the slew current and the settling current
    are both proportional to it -- so does `fclk`, because the bias is
    derived at the same clock the settling is evaluated at. Asserted, not
    left to be rediscovered: a reader who thinks this number responds to the
    capacitor will read a moved bound as evidence of something it is not.

    `enob` is in the list on purpose -- it moves the REQUIREMENT, never the
    count.
    """
    env = a2.admission_env(a2.LIBRARY["delta_sigma"], {**BASE, **over},
                           _measured())
    got = a2._safe_eval(a2._SETTLING_TC_EXPR, env)
    closed = BASE["vref"] * env["slew_design_margin"] \
        / env["integrator_input_overdrive_v"]
    assert got == pytest.approx(closed, rel=1e-9), over


def test_the_count_DOES_respond_to_the_declared_reference():
    """The one bound spec row it must move on: less reference is less
    slew-derived current, so less gm, so a longer time constant."""
    seen = {}
    for vref in (0.8, 1.0, 1.2):
        env = a2.admission_env(a2.LIBRARY["delta_sigma"],
                               {**BASE, "vref": vref}, _measured())
        seen[vref] = a2._safe_eval(a2._SETTLING_TC_EXPR, env)
    assert seen[0.8] < seen[1.0] < seen[1.2], seen


# ── BOTH DIRECTIONS: break it deliberately and watch the bound go red ─────
def test_MUTATION_a_bias_sized_apart_from_the_load_is_caught(tmp_path):
    """BOTH DIRECTIONS. A check that cannot go red is not a check, so this
    breaks the source on purpose and asserts the bound refuses.

    AIMED AT THE BIAS DERIVATION, not at `_LOAD_F_EXPR`. The load expression
    is string-composed INTO `_R_IB_L_UM_EXPR` and `_TAIL_I_EXPR`, so editing
    it moves every side at once and the cancellation correctly survives --
    measured, and the reason this mutation is aimed where it is. The
    regression that CAN happen is the bias being sized against something
    other than the load the amplifier actually drives; here the drawn bias
    length is drawn 1.35x too long, which cuts the tail current and the gm
    by the same factor.

    AND THE POINT OF THE WHOLE ENTRY: `slew_margin` does NOT catch it.
    1.35x is chosen to sit in the gap between the two bounds -- slew falls
    2.0 -> 1.48 and stays above its floor of 1.0, `bias_resistor_l_um` grows
    23.4 -> 31.6 um and stays inside [1, 2000] -- so the settling bound is
    the ONLY thing between this regression and a rendered netlist. Measured
    at 2.0x, slew_margin does catch it (it lands a float's width under 1.0),
    which is exactly why the control is run at a realistic sizing error
    rather than a dramatic one.
    """
    mutant = tmp_path / "analog_a2_topology_emit.py"
    src = A2SRC.read_text(encoding="utf-8")
    old = ('    "/ ((" + _LOAD_F_EXPR + ") * vref * slew_design_margin)) "\n'
           '    "* w_res / rsheet_ohm_per_sq")')
    assert src.count(old) == 1, "the mutation target moved; re-aim it"
    mutant.write_text(src.replace(
        old, old.replace('"* w_res / rsheet_ohm_per_sq")',
                         '"* 1.35 * w_res / rsheet_ohm_per_sq")'), 1),
        encoding="utf-8")

    m = _mod(mutant)
    env = m.admission_env(m.LIBRARY["delta_sigma"], dict(BASE), _measured())
    env0 = a2.admission_env(a2.LIBRARY["delta_sigma"], dict(BASE), _measured())
    mutated = m._safe_eval(m._SETTLING_TC_EXPR, env)
    intact = a2._safe_eval(a2._SETTLING_TC_EXPR, env0)

    assert mutated == pytest.approx(intact / 1.35, rel=1e-6), (mutated, intact)

    refs = m.entry_admission(m.LIBRARY["delta_sigma"], dict(BASE),
                             {k: UNITS[k] for k in BASE}, _measured())
    settling = [r for r in refs if r.get("field") == FIELD]
    assert settling and settling[0]["requirement"] == "derived_range", refs

    # the half of this that is the entry's whole reason for existing
    assert not [r for r in refs if r.get("field") == "slew_margin"], (
        "slew_margin was expected to still PASS on the mutant -- if it "
        "catches this too, the settling bound is not the only thing "
        "standing between this regression and a rendered netlist")
    assert m._safe_eval(m.SLEW_MARGIN_EXPR, env) == pytest.approx(2.0 / 1.35)
    assert not [r for r in refs if r.get("field") == "bias_resistor_l_um"]


def test_MUTATION_a_looser_requirement_would_admit_what_is_refused(tmp_path):
    """The negative control for the REQUIREMENT side: the retired branch's
    flat 7.0 admits a declaration that the derived floor refuses. Proves the
    derived floor is doing work rather than agreeing with the old constant.
    """
    over = {"vref": 0.8, "enob": 16.0}
    state, r = _verdict(**over)
    assert state == "REFUSED"
    assert r["value"] > 7.0, (
        "this declaration must be one the retired branch's flat 7.0 would "
        "have ADMITTED, or it is not a control on the derived requirement")
    assert r["value"] < float(r["min"])
