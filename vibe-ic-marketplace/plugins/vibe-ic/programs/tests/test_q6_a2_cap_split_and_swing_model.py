"""q6-a2-cap-osr — the A2 capacitor split and the delta-sigma swing model.

WHAT WAS WRONG, MEASURED on an incremental delta-sigma declaration of the
u_hawaii_adc shape (ihp-sg13g2; every name and number in this file's fixture
is invented, only the SHAPE is copied):

(a) FOUR CAPACITORS REACHED A5 ABOVE THE GENCELL MAXIMUM although A2 had
    "split" them. A2 overwrote the declared `osr` with the graded-range choice
    (512) and split in THAT environment; A3 rendered the same expressions with
    the declared `osr` (256) applied last. `caz` was 17.23u at A2 and 34.51u
    at A3; `c_vcm` was split into 3 x 22.99u and rendered at 3 x 46.03u.
    Rule now: ONE rendering environment (`rendering_env`) and the applied
    choice published as `effective_spec_values`.

    Fixing only that exposes the other end: at osr 512 `cs`/`cf` come out at
    1.675u, below the gencell's 2.0u minimum, and the split's single-device
    path never checked a minimum. Rule now: both ends, and a device below the
    minimum is re-solved as a square or refused by name.

    The kT/C budget divided by OSR; the incremental decode averages with the
    loop's own triangular weights, worth N_eff = (sum w)^2 / sum w^2 = 0.749 N.
    Rule now: `n_eff`, published as a constant.

(b) "EVERY OSR IS OVER THE SWING BUDGET" WAS A MODEL DEFECT. The recurrence
    tied every coefficient to one scalar and was evaluated at a plugin test
    tone against the target corner. Rule now: per-stage coefficients (from a
    MEASUREMENT of the emitted netlist when one exists), the declared input
    span, the declared worst corner, attenuation with margin below the stable
    input limit, and diagonal state scaling to x_lim * (1 - m) with the
    bitstream-identity assertion.

No chip / SKU / foundry literal in any assertion's logic.
"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _analog_producer_fixture import (A1, A2, bdir, block, make_project,  # noqa: E402
                                      run_prog)
import analog_a2_topology_emit as a2                  # noqa: E402
import analog_a3_netlist_emit as a3                   # noqa: E402
import analog_incremental_decimator as dec            # noqa: E402
import analog_incremental_resolution as R             # noqa: E402
import pdk_analog_layout_minima as mn                 # noqa: E402

PDK = "ihp-sg13g2"
BLK = "mod_q6"


def _specs():
    # The u_hawaii_adc SHAPE: an OSR declared as an estimate inside a range,
    # a graded ENOB the range must be searched for, a differential input span
    # equal to the reference, and supply / reference ranges (the worst corner).
    return [
        {"name": "Order", "target": 2.0, "min": 1.0, "max": 3.0, "unit": "—"},
        {"name": "OSR", "target": 256.0, "min": 64.0, "max": 512.0,
         "unit": "—"},
        {"name": "ENOB", "min": 14.0, "unit": "bit"},
        {"name": "Vref", "target": 1.0, "min": 0.8, "max": 1.2, "unit": "V"},
        {"name": "Vdd (core)", "target": 1.2, "min": 1.1, "max": 1.3,
         "unit": "V"},
        {"name": "Vin (diff)", "target": 1.0, "min": 0.0, "max": 1.2,
         "unit": "V"},
        {"name": "fclk", "target": 1.0, "min": 0.1, "max": 1.2823,
         "unit": "MHz"},
    ]


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    root = tmp_path_factory.mktemp("q6")
    make_project(root, [block(BLK, "delta_sigma", _specs())])
    assert run_prog(A1, root).returncode == 0
    res = run_prog(A2, root, "--pdk", PDK)
    assert res.returncode == 0, res.stderr
    d = bdir(root, BLK)
    ir = json.loads((d / "topology.json").read_text())
    spec = json.loads((d / "spec.json").read_text())
    return root, d, ir, spec


def _rendered(ir, spec):
    ov, _sb, _nom, _env = a3._resolve_params(ir, a3.spec_values(spec))
    out = {}
    for dv in ir["devices"]:
        if dv["role"] != "cap":
            continue
        o = ov.get(dv["name"], {})
        out[dv["name"]] = (float(o.get("w", dv.get("w"))),
                           float(o.get("l", dv.get("l"))))
    return out


# ── (a) the capacitors ────────────────────────────────────────────────────
def test_every_capacitor_renders_inside_the_drawable_bounds(emitted):
    """(i) RED on main: `caz` and the `c_vcm` units render above the 30u
    gencell maximum, because A2 split them at one OSR and A3 renders them at
    another. Bounds read from the registry, never typed here."""
    _root, _d, ir, spec = emitted
    maxima = mn.layout_maxima(PDK)[1]
    minima = mn.layout_minima(PDK)[1]
    lmax, amax = mn.max_length_um(maxima, "cap"), mn.max_area_um2(maxima,
                                                                  "cap")
    lmin = mn.min_length_um(minima, "cap")
    assert lmax and amax and lmin
    bad = {n: wl for n, wl in _rendered(ir, spec).items()
           if not (lmin - 1e-9 <= wl[0] <= lmax + 1e-9
                   and lmin - 1e-9 <= wl[1] <= lmax + 1e-9
                   and wl[0] * wl[1] <= amax)}
    assert not bad, bad


def test_a3_renders_what_a2_split(emitted):
    """(ii) The unit length A2 records for every array is the length A3
    renders — one environment. Dropping `effective_spec_values` from the IR
    moves the rendering (so the key is load-bearing, not decoration)."""
    _root, _d, ir, spec = emitted
    assert ir[a2.EFFECTIVE_SPEC_KEY] == {"osr": 512.0}
    rendered = _rendered(ir, spec)
    arrays = ir["_provenance"]["layout_maxima"]["capacitor_arrays"]
    assert arrays
    for rec in arrays:
        base = rec["device"]
        units = [n for n in rendered if n == base or n.startswith(base + "_u")]
        for u in units:
            assert rendered[u][1] == pytest.approx(rec["unit_l_um"],
                                                   rel=1e-9), (u, rec)
    # The key is load-bearing: an expression naming the free spec renders at
    # the EFFECTIVE value, and at the declared one only when the key is gone.
    probe_ir = copy.deepcopy(ir)
    probe_ir["device_param_exprs"].append(
        {"device": "cs1", "param": "m", "expr": "osr"})
    ov = a3._resolve_params(probe_ir, a3.spec_values(spec))[0]
    assert ov["cs1"]["m"] == 512.0
    probe_ir.pop(a2.EFFECTIVE_SPEC_KEY)
    ov = a3._resolve_params(probe_ir, a3.spec_values(spec))[0]
    assert ov["cs1"]["m"] == 256.0
    # and no capacitor length depends on the free spec by name any more: the
    # window reaches the sizing only through the published `n_eff`
    for e in ir["device_param_exprs"]:
        if e.get("param") == "l":
            assert "osr" not in e["expr"], e


def test_an_ir_that_applied_nothing_renders_as_it_always_did():
    """(iv) The control: with no `effective_spec_values` the environment is
    the old seeding order exactly."""
    ir = {"pdk_measured_params": {"cap_area_ff_per_um2": 1.5, "flag": True},
          "constants": {"k": 2.0, "osr": 1.0}, "knobs": {"kn": 3.0,
                                                         "s": "x"}}
    sv = {"osr": 256.0, "enob": 14.0}
    old = {}
    old.update({"cap_area_ff_per_um2": 1.5})
    old.update(ir["constants"])
    old.update({"kn": 3.0})
    old.update(sv)
    assert a2.rendering_env(ir["pdk_measured_params"], ir["constants"],
                            ir["knobs"], sv,
                            ir.get(a2.EFFECTIVE_SPEC_KEY)) == old
    assert a2.rendering_env(ir["pdk_measured_params"], ir["constants"],
                            ir["knobs"], sv, {"osr": 512.0})["osr"] == 512.0


def test_the_ihp_registry_states_both_ends_and_labels_the_tool_bound():
    minima = mn.layout_minima(PDK)[1]
    maxima = mn.layout_maxima(PDK)[1]
    assert mn.min_length_um(minima, "cap") == 2.0
    assert mn.min_width_um(minima, "cap") == 2.0
    cap = maxima["cap"]
    assert cap["bound_kind"] == "magic_gencell"
    assert "Magic gencell" in cap["bound_label"]
    assert mn.max_area_um2(maxima, "cap") == 5625.0
    assert cap["max_area_rule"] == "MIM.g"
    # the maxima record no longer claims the minima record reads a cap row
    # that it did not carry
    assert "already reads" not in mn.maxima_source(PDK)


def test_a_capacitor_below_the_minimum_is_resolved_or_refused():
    """(iii) RED on main: a 1.675u device at the library width came back
    `(1, 1.675, "")` — "legal" — and went to a gencell that clamps it up."""
    carea, cperi = 1.5, 0.04
    n, lu, why = a2.unit_capacitor_split(
        10.0, 1.675, max_l=30.0, max_w=30.0, min_l=2.0, carea=carea,
        cperi=cperi)
    assert n == 1 and lu is None and why.startswith(a2.BELOW_MINIMUM)
    dev = [{"name": "cz", "role": "cap", "nets": ["a", "b"], "w": 10.0,
            "l": 1.675}]
    devs, exprs, recs, refs = a2.split_oversize_capacitors(
        dev, [], {}, {"cap": {"max_length_um": 30.0, "max_width_um": 30.0,
                              "max_area_um2": 5625.0}},
        {"cap": {"min_width_um": 2.0, "min_length_um": 2.0}},
        {"cap_area_ff_per_um2": carea, "cap_perim_ff_per_um": cperi})
    assert not refs
    sq = devs[0]
    assert sq["w"] == pytest.approx(sq["l"]) and 2.0 <= sq["l"] <= 30.0
    want = a2.capacitance_ff(10.0, 1.675, carea, cperi)
    assert a2.capacitance_ff(sq["w"], sq["l"], carea, cperi) == \
        pytest.approx(want, rel=1e-12)
    assert recs[0]["resolution"] == "square_resolve_below_minimum"
    # and one too small even as a square is refused BY NAME, never emitted
    tiny = [{"name": "ct", "role": "cap", "nets": ["a", "b"], "w": 10.0,
             "l": 0.05}]
    _d, _e, _r, refs = a2.split_oversize_capacitors(
        tiny, [], {}, {"cap": {"max_length_um": 30.0}},
        {"cap": {"min_width_um": 2.0}},
        {"cap_area_ff_per_um2": carea, "cap_perim_ff_per_um": cperi})
    assert refs and refs[0].startswith("ct:")


def test_the_area_ceiling_caps_the_unit_length():
    n, lu, _ = a2.unit_capacitor_split(
        100.0, 80.0, max_l=None, max_w=None, min_l=None, carea=1.5,
        cperi=0.0, max_area=5625.0)
    assert n == 2 and 100.0 * lu <= 5625.0 + 1e-9


def test_the_sampling_cap_divides_by_n_eff_not_osr(emitted):
    """RED on main: no `n_eff`, and the budget divided by `osr`."""
    _root, _d, ir, spec = emitted
    n = int(ir["constants"]["window_clocks"])
    w = dec.input_weights(n, 2, 0.25)
    want = sum(w) ** 2 / sum(x * x for x in w)
    assert ir["constants"][a2.N_EFF_CONSTANT] == pytest.approx(want)
    assert 0.74 * n < want < 0.76 * n
    assert "n_eff" in a2.SAMPLING_CAP_FF_EXPR
    assert "osr" not in a2.SAMPLING_CAP_FF_EXPR


# ── (b) the swing model ───────────────────────────────────────────────────
def test_the_per_stage_loop_reproduces_the_scalar_recurrence():
    """B1: the all-equal case is the recurrence the resolution model runs."""
    tone = R._stim.incremental_tone(R._stim.incremental_record_windows())
    g, cyc = tone["graded_windows"], tone["cycles"]
    legacy = R._run(256, 2, 0.2499, 1, g, cyc, 0.0, 0.72, 0.20)
    f = cyc / float(g * 256)
    new = R.run_loop(256, 0.2499, [0.2499, 0.2499], [0.0, 0.2499], 1,
                     lambda n: 0.20 + 0.72 * math.sin(2 * math.pi * f * n),
                     windows=g + 1)
    for x, y in zip(legacy["peak_per_stage"], new["peak_per_stage"]):
        assert x == pytest.approx(y, rel=1e-12)


def test_scaling_leaves_the_bitstream_and_scales_the_peak_exactly():
    a, c = [0.2499, 0.2499], [0.0, 0.2499]
    base = R.run_loop(256, a[0], a, c, 1, R._dc(0.6))
    sc = R.scale_states(a[0], a, c, [0.5, 0.25])
    got = R.run_loop(256, sc["b1"], sc["a"], sc["c"], 1, R._dc(0.6))
    assert got["bits"] == base["bits"]
    assert got["peak_per_stage"][0] == pytest.approx(
        0.5 * base["peak_per_stage"][0], rel=1e-9)
    assert got["peak_per_stage"][1] == pytest.approx(
        0.25 * base["peak_per_stage"][1], rel=1e-9)


def test_the_swing_limit_is_the_declared_worst_corner(emitted):
    _root, _d, ir, spec = emitted
    sv = a3.spec_values(spec)
    frac = ir["constants"]["integrator_swing_fraction_of_vdd"]
    assert R.declared_swing_limit(ir["constants"], sv) == pytest.approx(
        frac * sv["vdd_min"] / sv["vref_max"])
    assert R.declared_input_span(sv) == pytest.approx(
        sv["vindiff"] / sv["vref"])


def test_the_emitted_loop_is_scaled_with_margin_at_the_declared_span(emitted):
    """RED on main: no `loop_swing`, and every candidate reads over budget.
    Mutation guard: scaling to EXACTLY x_lim (m = 0) must fail here."""
    _root, _d, ir, spec = emitted
    sw = ir["loop_swing"]
    assert sw["feasible"] and sw["bitstream_identical"]
    assert sw["u_decl"] == pytest.approx(1.0)
    assert sw["swing_scale_margin"] >= 0.1
    assert sw["input_stability_margin"] >= 0.07
    assert sw["u_eff_max"] <= sw["u_stable"] - sw["input_stability_margin"] \
        + 1e-12
    lim = sw["x_lim"] * (1.0 - sw["swing_scale_margin"])
    for p in sw["peaks_after"]:
        assert p <= lim + 1e-9
        assert p < sw["x_lim"] - 1e-6
    # sized at the chosen window; at every other candidate the scaled loop
    # stays under x_lim (the margin absorbs the few-percent variation a
    # shorter window's limit cycle shows) — and the record says so
    assert sw["within_x_lim_every_candidate"] is True
    for peaks in sw["peaks_after_per_candidate_window"].values():
        assert max(peaks) <= sw["x_lim"] + 1e-9
    rec = ir["graded_range_choice"]
    assert rec["swing"]["record"] == "loop_swing"
    assert rec["chosen_over_swing_budget"] is False
    # B5: `met` is still resolution-only
    assert rec["met"] is False


def test_the_drawn_capacitors_realise_the_scaled_loop(emitted):
    """The integrating and feedback capacitors are sized FROM the scaled
    coefficients; the sampling capacitor stays at the kT/C value."""
    _root, _d, ir, spec = emitted
    sw = ir["loop_swing"]
    ov, _sb, _nom, env = a3._resolve_params(ir, a3.spec_values(spec))
    meas = ir["pdk_measured_params"]
    ca, cp = meas["cap_area_ff_per_um2"], meas.get("cap_perim_ff_per_um", 0)

    def cap(n):
        d = [x for x in ir["devices"] if x["name"] == n][0]
        o = ov.get(n, {})
        return a2.capacitance_ff(float(o.get("w", d["w"])),
                                 float(o.get("l", d["l"])), ca, cp)

    cs_ff = a2._safe_eval(a2.SAMPLING_CAP_FF_EXPR, dict(env))
    scl = sw["coefficients_scaled"]
    for i in (1, 2):
        assert cap(f"cs{i}") == pytest.approx(cs_ff, rel=1e-6)
        cin = scl["b1"] if i == 1 else scl["c"][i - 1]
        assert cap(f"cs{i}") / cap(f"ci{i}") == pytest.approx(cin, rel=1e-6)
        assert cap(f"cf{i}") / cap(f"ci{i}") == pytest.approx(
            scl["a"][i - 1], rel=1e-6)


def _measurement(ir, g_in1=1.077):
    rows = []
    for i in (1, 2):
        rows.append({"stage": i, "status": "MEASURED",
                     "input_coefficient": 0.2499 * (g_in1 if i == 1 else 1),
                     "dac_coefficient": 0.2494,
                     "offset_v_per_clock": 0.007 if i == 1 else 0.0,
                     "offset_state_per_clock": 0.014 if i == 1 else 0.0,
                     "gain_input_over_ratio": g_in1 if i == 1 else 1.0,
                     "gain_dac_over_ratio": 0.2494 / 0.2499})
    return {"status": "MEASURED", "stages": rows}


def _rebuild(ir, spec, measured_loop):
    lib = a2.LIBRARY["delta_sigma"]
    sv = a3.spec_values(spec)
    return a2.build_ir(BLK, "delta_sigma", {}, lib, sv, None, Path("."),
                       PDK, {}, mn.layout_minima(PDK)[1], None,
                       ir["pdk_measured_params"], None,
                       mn.layout_maxima(PDK)[1], None,
                       measured_loop=measured_loop)


def test_a_measured_input_branch_gain_is_used_not_the_cap_ratio(emitted):
    """B1' — RED if b1 were taken from the capacitor ratio while the
    measurement says it is 7.7 % larger: the drawn cs1/cf1 must come down by
    the measured gain, and the record must name the stage whose branch does
    not realise its ratio."""
    _root, _d, ir, spec = emitted
    base = _rebuild(ir, spec, None)["loop_swing"]
    assert base["coefficient_source"] == "cap_ratio_unmeasured"
    got = _rebuild(ir, spec, _measurement(ir))["loop_swing"]
    assert got["coefficient_source"] == "measured"
    assert got["ratio_not_realised"] == [1]
    assert got["cs1_over_cf1_drawn"] == pytest.approx(
        got["b1_over_a1"] / got["input_branch_gain_over_cap_ratio"])
    assert got["input_branch_gain_over_cap_ratio"] == pytest.approx(
        1.077 / (0.2494 / 0.2499))
    assert got["cs1_over_cf1_drawn"] < base["cs1_over_cf1_drawn"] * 0.95
    # the offset is referred to the input and eats margin
    assert got["offset_u"] > 0 and got["b1_over_a1"] < base["b1_over_a1"]




def test_the_input_branches_sample_on_the_bottom_plate():
    """B1' circuit fix: every input / inter-stage source switch opens AFTER
    its capacitor's upper-plate switch — on a phase that resolves to the same
    sampling phase but is not the upper plate's own net."""
    lib = a2.LIBRARY["delta_sigma"]
    aliases = lib[a2.CLOCK_PHASE_ALIASES_KEY]
    st = [g for g in a2._stage_groups(lib) if g.get("first_in")][0]
    by = {d["name"]: d for d in st["devices"]}
    smp, cstc = by["mn_smp{i}"]["nets"][1], by["mn_cstc{i}"]["nets"][1]
    assert smp != cstc
    assert a2._resolve_phase(smp, aliases) == a2._resolve_phase(cstc, aliases)
    # the delayed phase is BUILT from the upper plate's phase
    drv = [d for d in lib["devices"] if d["nets"][0] == smp]
    assert drv and any(d["nets"][1] != cstc for d in drv)
    assert a2.derived_feedback_delay(lib) == 1



def test_a_declaration_whose_caps_are_below_the_minimum_is_refused_by_name(
        tmp_path):
    """The other half of the split in `test_analog_a2_delta_sigma_spec_bound
    ::test_the_sampling_capacitor_follows_the_declared_resolution`: at enob 12
    the kT/C sampling capacitor (4.35 fF) is below the smallest drawable
    device even as a square. Main emitted it at 0.24u for a gencell that
    clamps it to 2.0u; it is now refused by name, with the bound's label."""
    specs = [r for r in _specs() if r["name"] not in ("ENOB", "OSR",
                                                       "Vin (diff)")]
    specs += [{"name": "ENOB", "min": 12.0, "unit": "bit"},
              {"name": "OSR", "target": 256.0, "unit": "—"}]
    root = tmp_path / "e12"
    root.mkdir()
    make_project(root, [block(BLK, "delta_sigma", specs)])
    assert run_prog(A1, root).returncode == 0
    res = run_prog(A2, root, "--pdk", PDK)
    assert res.returncode != 0
    gap = json.loads((bdir(root, BLK) / "topology_gap.json").read_text())
    txt = json.dumps(gap)
    assert "cs1:" in txt and a2.BELOW_MINIMUM in txt
    assert "Magic gencell" in txt
    assert not (bdir(root, BLK) / "topology.json").exists()




def test_a2_uses_the_measured_stage_and_discloses_the_other(emitted):
    _root, _d, ir, spec = emitted
    meas = _measurement(ir)
    meas["status"] = "PARTIALLY_MEASURED"
    meas["stages"][1]["status"] = "POOR_FIT"
    meas["stages"][1]["gain_input_over_ratio"] = 0.60
    sw = _rebuild(ir, spec, meas)["loop_swing"]
    assert sw["coefficient_source"] == "partially_measured"
    assert sw["coefficient_source_per_stage"] == ["measured",
                                                  "cap_ratio_unmeasured"]
    assert sw["gain_input_over_ratio"][1] == 1.0
    assert sw["gain_input_over_ratio"][0] == pytest.approx(1.077)
