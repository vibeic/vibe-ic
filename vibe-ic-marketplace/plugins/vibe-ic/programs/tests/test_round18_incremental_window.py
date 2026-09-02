"""Round 18: the converter the design declares — an INCREMENTAL delta-sigma.

Round 17 closed the modulator's boundary and MEASURED that the loop did not
convert: a bitstream density of 0.51 that did not move across the input's full
range, on every one of eight structural arms. The diagnosis was that a
single-ended loop filter with no per-conversion reset carries a free output
common mode while the quantiser's threshold is fixed, so the input-referred
offset is unbounded.

L5 Block A says what to do about it: the converter "resets/accumulates per
conversion window". The design's own interface declaration carries no `rst`
and no start-of-conversion pin and states that `rst` is "INTERNAL to the
block's chosen topology". So the window is generated ON THE BLOCK, from the
one timing signal the boundary declares, and this module pins the machinery
that does it.

  1. TWO REPEATED GROUPS, NOT ONE. The integrator cascade's count is the
     declared loop ORDER; the counter's is the number of divide-by-two stages
     the declared OSR asks for. One `count_from` cannot express both, so
     `stage` may now be a LIST. An entry that declares a single dict takes the
     identical path it always did.

  2. A RIPPLE DIVIDER'S PERIOD IS A POWER OF TWO. `count_bits_for` counts
     stages rather than reading a value, and the window it really gives is
     published as `window_clocks` — greater than or equal to the declared OSR,
     never less, and stated rather than implied.

  3. THE RESET IS "THE COUNTER READS ALL ONES". The bits are named per stage,
     so nothing outside the group can name them all; each stage ANDs its own
     bit into a second chain that ends on the fixed name `nall`. All-ONES and
     not all-zeros because a transmission-gate flip-flop powers up with its
     bit HIGH — measured on this block, an all-zeros decode left the reset
     unasserted for the whole of the first window and the first integrator
     sat at 0.828 V, never reset. Decoding all-ones makes the block start IN
     reset.

  4. AN ADMISSION BOUND THAT CAN REFUSE. The bias the library draws has to
     move the output a full reference step inside the clock the declaration
     asks for. That is a race the DECLARATION can lose, and `slew_margin`
     below 1 is the entry saying so instead of sizing silently to whatever was
     asked.

  5. NO UNDECLARED PIN. The whole point: the block's ports are still exactly
     the seven the corpus declares.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_a2_topology_emit as a2  # noqa: E402

ENTRY = a2.LIBRARY["delta_sigma"]

#: The interface the corpus declares, every pin citing a document line.
DECLARED = ["vdd", "vss", "vin", "vrefp", "vrefn", "clk", "bit_out"]

#: The declaration in hand (u_hawaii_adc, L5 Block A).
SPEC = {"order": 2.0, "osr": 256.0, "enob": 14.0, "vref": 1.0,
        "fclk": 1.0, "fclk_max": 10.0, "vdd": 1.2}

#: The process constants `pdk_analog_characterize` measured for ihp-sg13g2.
MEASURED = {"cap_area_ff_per_um2": 1.5, "rsheet_ohm_per_sq": 260.0009360028072,
            "k_prime_n_ua_per_v2": 328.2147637102496,
            "vth_n_extracted_v": 0.1970889179379298}


def _expand(spec=None):
    return a2.expand_stages(ENTRY, dict(spec or SPEC))


# ── 5. the boundary did not move ──────────────────────────────────────────
def test_the_window_generator_added_no_pin():
    """The head constraint of the whole round. An incremental converter wants
    a start-of-conversion; the declaration does not carry one; so it is
    generated inside and the port list is untouched."""
    assert sorted(ENTRY["ports"]) == sorted(DECLARED)
    assert "rst" not in ENTRY["ports"]


def test_the_reset_exists_and_is_internal():
    assert "nall" in ENTRY["internal_nets"]
    assert "nrstb" in ENTRY["internal_nets"]


# ── 1. two groups ─────────────────────────────────────────────────────────
def test_the_entry_declares_two_repeated_groups():
    groups = a2._stage_groups(ENTRY)
    assert len(groups) == 2
    roles = [g.get("role", "cascade") for g in groups]
    assert roles == ["cascade", "conversion_window_counter"]


def test_a_single_dict_stage_still_expands_exactly_as_before():
    """The control that keeps every other entry — and every entry anyone
    writes next — on the path it had. A dict is one group."""
    one = json.loads(json.dumps(ENTRY))
    one["stage"] = a2._stage_groups(ENTRY)[0]
    devices, _n, _e, rec = a2.expand_stages(one, dict(SPEC))
    assert rec["stages"] == 2
    assert "groups" not in rec
    assert not [d for d in devices if d["name"].startswith("mn_sinv")]


def test_every_other_library_entry_expands_to_its_own_lists_unchanged():
    for btype, entry in sorted(a2.LIBRARY.items()):
        if btype == "delta_sigma":
            continue
        devices, nets, exprs, rec = a2.expand_stages(entry, {})
        assert rec is None, btype
        assert devices == list(entry.get("devices") or []), btype
        assert nets == list(entry.get("internal_nets") or []), btype
        assert exprs == list(entry.get("device_param_exprs") or []), btype


# ── 2. the counter's count, and the window it really gives ────────────────
@pytest.mark.parametrize("osr,bits,window", [
    (64, 6, 64), (128, 7, 128), (256, 8, 256), (512, 9, 512),
    # NOT a power of two: the window is the next one UP, and saying so is the
    # point of publishing `window_clocks` at all.
    (100, 7, 128), (300, 9, 512),
])
def test_the_counter_covers_the_declared_osr_and_says_what_it_gives(
        osr, bits, window):
    _d, _n, _e, rec = _expand({**SPEC, "osr": float(osr)})
    counter = rec["groups"][1]
    assert counter["stages"] == bits
    assert counter["window_clocks"] == window
    assert window >= osr


def test_the_window_is_published_where_the_testbench_can_name_it():
    """The expression grammar has no logarithm, so nothing downstream could
    derive the window. It is carried into the constants during expansion, and
    the entry's own testbench reads it from there."""
    assert "window_clocks" in ENTRY["testbench"]["env_exprs"]["twin_ns"]


def test_the_counter_stage_count_follows_the_declaration_not_a_constant():
    a = _expand({**SPEC, "osr": 64.0})[3]["groups"][1]["stages"]
    b = _expand({**SPEC, "osr": 512.0})[3]["groups"][1]["stages"]
    assert a == 6 and b == 9


@pytest.mark.parametrize("value,bits", [
    (1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (255, 8), (256, 8), (257, 9)])
def test_bits_to_cover_is_exact_on_the_boundaries(value, bits):
    assert a2._bits_to_cover(value) == bits


# ── 3. the reset decode ───────────────────────────────────────────────────
def test_every_counter_bit_is_folded_into_the_accumulator():
    """`nany` has to see EVERY bit. A decode that misses one asserts reset
    twice per window — or never."""
    devices, _n, _e, rec = _expand()
    bits = rec["groups"][1]["stages"]
    for i in range(1, bits + 1):
        gate = [d for d in devices if d["name"] == f"mn_nandb{i}"]
        assert gate, f"bit {i} is folded into no accumulator gate"
        assert f"q{i}" in gate[0]["nets"]


def test_the_accumulator_chain_ends_on_the_fixed_name_the_reset_reads():
    devices, nets, _e, _r = _expand()
    assert "nall" in nets or "nall" in ENTRY["internal_nets"]
    inv = [d for d in devices if d["name"] == "mp_rstinv"][0]
    assert inv["nets"][1] == "nall"
    assert inv["nets"][0] == "nrstb"


def test_the_accumulator_pull_downs_are_in_series():
    """A CMOS NAND pulls low only when BOTH inputs are high. Wired in
    parallel it is an inverter of one input and the chain forgets every
    earlier bit — which would assert the reset on half the counts instead of
    one."""
    devices, _n, _e, _r = _expand()
    a = [d for d in devices if d["name"] == "mn_nanda3"][0]
    b = [d for d in devices if d["name"] == "mn_nandb3"][0]
    assert a["nets"][0] == "nnand3" and a["nets"][2] == "nnandp3"
    assert b["nets"][0] == "nnandp3" and b["nets"][2] == "vss"


def test_the_first_accumulator_stage_starts_from_the_supply_rail():
    """The AND of no bits is true, and each stage can only take it away."""
    devices, _n, _e, _r = _expand()
    a = [d for d in devices if d["name"] == "mn_nanda1"][0]
    assert a["nets"][1] == "vdd"


def test_the_second_chain_is_optional_and_absent_by_default():
    """A group that declares no second chain never sees `{in2}`/`{out2}`, so
    an entry written without one cannot break on a key it does not use."""
    one = json.loads(json.dumps(ENTRY))
    g = a2._stage_groups(ENTRY)[0]
    assert "inner_out2" not in g
    one["stage"] = g
    a2.expand_stages(one, dict(SPEC))  # must not raise


# ── the reset reaches the integrators ─────────────────────────────────────
def test_each_integrator_carries_the_per_conversion_reset():
    devices, _n, _e, rec = _expand()
    order = rec["stages"]
    for i in range(1, order + 1):
        across = [d for d in devices if d["name"] == f"mn_rsti{i}"]
        assert across, f"stage {i} has no conversion reset"
        assert across[0]["nets"][1] == "nall"
        # ...and it is a UNITY-GAIN short, not a tie to the reference.
        assert across[0]["nets"][0] == f"vsum{i}"
        assert across[0]["nets"][2] in (f"vo{i}", "vint")


def test_the_reset_does_not_load_the_on_chip_reference():
    """MEASURED. An arm of this round also tied the summing node to `vcm`
    during reset. That connects the OTA's output to the reference through two
    switches, and the output stage sources far more current than the divider
    that makes `vcm`: `vcm`, `vsum1` and `vo1` all sat at 0.035 V against a
    0.6 V reference and the block reset to the wrong voltage. The unity-gain
    short is sufficient alone — the amplifier's own equilibrium IS the
    reference."""
    devices, _n, _e, _r = _expand()
    assert not [d for d in devices if d["name"].startswith("mn_rstc")]
    reset_switches = [d for d in devices
                      if d["name"].startswith(("mn_rsti", "mp_rsti"))]
    assert reset_switches
    assert not any("vcm" in d["nets"] for d in reset_switches)


def test_the_block_powers_up_in_reset():
    """MEASURED, and the reason the decode is all-ONES. A flip-flop's output
    inverter drives its bit high out of reset-less power-up, so the counter
    reads all ones at t=0 and the block starts by resetting its integrators
    — instead of running a whole window unreset, which is what an all-zeros
    decode did."""
    devices, _n, _e, _r = _expand()
    # every stage's bit is the output of an inverter whose input is the
    # slave latch node, and that node powers up low
    inv = [d for d in devices if d["name"] == "mp_sinv1"][0]
    assert inv["nets"][0] == "q1" and inv["nets"][1] == "ns1"


def test_the_reset_switches_are_transmission_gates():
    """An n-channel pass device cannot hold the summing node at the 0.6 V
    common mode from a 1.2 V rail; round 17 measured that on the sampling
    switches."""
    devices, _n, _e, _r = _expand()
    for name in ("mp_rsti1", "mp_rsti2"):
        d = [x for x in devices if x["name"] == name]
        assert d, name
        assert d[0]["nets"][1] == "nrstb", "the p-side takes the complement"


# ── 4. the admission bound ────────────────────────────────────────────────
def _margin(spec):
    env = a2.admission_env(ENTRY, dict(spec), MEASURED)
    return a2._safe_eval(a2.SLEW_MARGIN_EXPR, env)


def test_the_declaration_in_hand_clears_the_slew_bound():
    m = _margin(SPEC)
    assert m > 1.0, m
    assert 10.0 < m < 100.0, m


def test_a_clock_the_library_bias_cannot_follow_is_refused_by_name():
    """The CONTROL. The bound has to be reachable from a declaration, or it
    is a bound that cannot bind."""
    fast = {**SPEC, "fclk": 1000.0}
    assert _margin(fast) < 1.0
    refusals = a2.entry_admission(ENTRY, fast, {}, MEASURED)
    assert any("slew_margin" in json.dumps(r) for r in refusals), refusals


def test_the_bound_reads_the_resistor_the_library_actually_draws():
    """A constant that restates a drawn geometry is a second copy of one
    number, and the copy is what the expression reads."""
    r_ib = [d for d in ENTRY["devices"] if d["name"] == "r_ib"][0]
    assert ENTRY["constants"]["r_ib_l_um"] == r_ib["l"]


def test_a_constant_that_drifts_from_its_device_is_an_authoring_error():
    entry = json.loads(json.dumps(ENTRY))
    entry["constants"]["r_ib_l_um"] = 12.0
    problems = a2.library_invariants({"x": entry})
    assert any("r_ib_l_um" in p for p in problems), problems


def test_the_shared_load_ratio_must_cover_the_worst_admitted_coefficient():
    entry = json.loads(json.dumps(ENTRY))
    entry["constants"]["load_over_sampling_cap"] = 1.0
    problems = a2.library_invariants({"x": entry})
    assert any("load_over_sampling_cap" in p for p in problems), problems


# ── the Miller capacitor is sized against the load ────────────────────────
def test_the_miller_capacitor_follows_the_integrating_capacitor():
    _d, _n, exprs, _r = _expand()
    cc = [e for e in exprs if e["device"] == "cc1"]
    assert cc, "the compensation capacitor is still a library constant"
    assert "miller_fraction_of_load" in cc[0]["expr"]


# ── the library still holds together ──────────────────────────────────────
def test_the_shipped_library_satisfies_every_invariant():
    assert a2.library_invariants() == []


def test_a_counter_group_may_not_ask_for_loop_coefficients():
    entry = json.loads(json.dumps(ENTRY))
    entry["stage"][1]["coefficients"] = True
    problems = a2.library_invariants({"x": entry})
    assert any("coefficients" in p for p in problems), problems


def test_a_counter_group_whose_row_is_unbound_is_refused_before_expansion():
    with pytest.raises(a2.LibraryEntryError) as e:
        _expand({"order": 2.0})
    assert "osr" in str(e.value)


# ── the refusal carries what was RULED OUT, not only what failed ──────────
def test_a_refuted_hypothesis_is_carried_and_printed(tmp_path, capsys):
    """ROUND 18 added `refuted` to the behaviour record, and it earns its
    place: this round spent one conversion window per arm, and two of those
    arms went to hypotheses that turned out to be wrong (StrongARM kickback
    on the auto-zero node; the feedback sign). A record that lists only the
    failures sends the next reader to buy the same two measurements again."""
    import analog_topology_behaviour_check as beh
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps({"behaviour_record": {
        "claim": "c", "verified": False, "diagnosis": "d", "next": "n",
        "arms": ["an arm"],
        "subsystems_demonstrated": ["a thing that works"],
        "refuted": ["a thing it is NOT"]}}))
    r = beh.check_block(tmp_path, "m")
    assert r["refuted"] == ["a thing it is NOT"]
    assert beh.main([str(tmp_path), "--block", "m"]) == 1
    out = capsys.readouterr().out
    assert "ruled out: a thing it is NOT" in out
    assert "demonstrated: a thing that works" in out


def test_the_shipped_record_carries_both_lists():
    """The entry states what works and what has been ruled out, because the
    round measured both."""
    rec = ENTRY["behaviour_record"]
    assert rec["subsystems_demonstrated"]
    assert rec["refuted"]
    assert rec["verified"] is False


def test_an_entry_without_the_lists_prints_neither(tmp_path, capsys):
    """The control: a record that claims nothing extra must not grow
    headings for empty lists."""
    import analog_topology_behaviour_check as beh
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps({"behaviour_record": {
        "claim": "c", "verified": False, "diagnosis": "d", "next": "n",
        "arms": ["an arm"]}}))
    beh.main([str(tmp_path), "--block", "m"])
    out = capsys.readouterr().out
    assert "ruled out:" not in out
    assert "demonstrated:" not in out
