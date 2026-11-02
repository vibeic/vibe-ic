"""R-0915-73 — the conversion-window reset has to clear the FEEDBACK BRANCH,
not just the integrators.

WHAT WAS WRONG, MEASURED (lane icadc, F164/F165). The emitted incremental
modulator's reset shorted the two integrators and nothing else. The feedback
branch went on sampling the DAC node straight through the reset, so the FIRST
charge transfer of every conversion carried the LAST DECISION OF THE PREVIOUS
ONE — one full reference step of charge belonging to a different conversion,
dumped into freshly zeroed integrators. No decode can remove it: the bit that
caused it is outside the window being decoded.

BOTH DIRECTIONS, pure arithmetic, no simulator (54 conversion windows of 256
clocks, coherent tone at bin 9, worst over 12 tone phases because the loop is
exactly periodic in 6 windows and a single phase is an accident):

    feedback branch sampling through the reset    ENOB  6.691   (worst)
    feedback branch held at the common mode       ENOB 13.367   (worst)

**6.68 bit**, from one gate term. Confirmed on the ideal-element SPICE harness
of this exact topology — one variable, same deck, same tone, same decode:
sine-fit ENOB 5.685 -> 13.532, with the fit residual falling 236x
(0.008017 -> 0.000034).

WHY IT IS RIGHT AND NOT A TRICK. The loop has made NO DECISION YET for the
first step of a conversion, so the honest feedback value there is ZERO — and a
1-bit DAC cannot produce zero any other way than by not sampling. The gate term
is `clk AND nrstb`, built from the reset complement the design already carries;
outside the reset `nckdac` IS the clock and the branch behaves exactly as it
always did.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

import json
from itertools import product
import math
import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_incremental_decimator as D          # noqa: E402

import analog_a2_topology_emit as a2              # noqa: E402
from test_incremental_reset_phase_alignment import logic

N = 256
COEFF = 0.2499
WINDOWS = 54
TONE_BIN = 9
FCLK = 1.0e6
DELAY = 1
PHASES = [2 * math.pi * i / 12 for i in range(12)]


# ── the pure-arithmetic control, both directions ──────────────────────────
def _decode(phase, clear_feedback_at_reset):
    """An ideal incremental CIFB2 with a one-clock feedback delay, decoded by
    the matched weights. `clear_feedback_at_reset` is the ONE variable."""
    f_sig = TONE_BIN * FCLK / (WINDOWS * N)
    w = D.matched_weights(N, 2, COEFF, DELAY)
    wn = sum(D.input_weights(N, 2, COEFF))
    out = []
    carry = [0.0] * DELAY
    for win in range(WINDOWS):
        i1 = i2 = 0.0
        pipe = [0.0] * DELAY if clear_feedback_at_reset else list(carry)
        acc = 0.0
        for k in range(N):
            n = win * N + k
            u = 0.20 + 0.72 * math.sin(2 * math.pi * f_sig * n / FCLK + phase)
            v = 1.0 if i2 > 0.0 else -1.0
            d = pipe[0]
            i2 += COEFF * (i1 - d)
            i1 += COEFF * (u - d)
            pipe = pipe[1:] + [v]
            acc += w[k] * v
        carry = list(pipe)
        out.append(acc / wn)
    return out[1:], f_sig


def _power(x, top):
    n = len(x)
    mean = sum(x) / n
    xs = [v - mean for v in x]
    out = []
    for k in range(1, top + 1):
        re = im = 0.0
        ww = -2.0 * math.pi * k / n
        for i, v in enumerate(xs):
            a = ww * i
            re += v * math.cos(a)
            im += v * math.sin(a)
        out.append(re * re + im * im)
    return out


def _enob(samples, f_sig):
    f_dec = FCLK / N
    cycles = int(len(samples) * f_sig / f_dec)
    n = min(int(round(cycles * f_dec / f_sig)), len(samples))
    grid = samples[-n:]
    top = n // 2 - 1
    p = _power(grid, top)
    sig = sum(p[b - 1] for b in (cycles - 1, cycles, cycles + 1)
              if 1 <= b <= top)
    noise = sum(p) - sig
    if sig <= 0 or noise <= 0:
        return None
    return (10.0 * math.log10(sig / noise) - 1.76) / 6.02


def _worst(clear_feedback_at_reset):
    vals = []
    for ph in PHASES:
        s, f = _decode(ph, clear_feedback_at_reset)
        e = _enob(s, f)
        if e is not None:
            vals.append(e)
    assert vals
    return min(vals), statistics.median(vals)


@pytest.fixture(scope="module")
def arms():
    return {"leaks": _worst(False), "clears": _worst(True)}


def test_the_control_the_branch_sampling_through_the_reset_is_short(arms):
    """THE CONTROL DIRECTION. Without the gate the loop cannot reach 8 bit,
    however good its devices are — the error is charge, not noise."""
    worst, median = arms["leaks"]
    assert worst < 8.0, f"worst {worst:.3f} / median {median:.3f}"


def test_clearing_the_feedback_branch_at_the_reset_is_worth_five_bits(arms):
    """THE FIX DIRECTION, and the size of it."""
    worst, _ = arms["clears"]
    leak_worst, _ = arms["leaks"]
    assert worst > 13.0, f"cleared worst {worst:.3f}"
    assert worst - leak_worst > 5.0, (
        f"cleared {worst:.3f} vs leaking {leak_worst:.3f} — the whole reason "
        f"the gate term exists is that this difference is several bits")


def test_the_measurement_does_not_depend_on_the_tone_phase_being_lucky(arms):
    """The loop is exactly periodic in 6 conversion windows, so ONE tone phase
    is an accident. Both arms are stated worst-case over 12, and the spread on
    the cleared arm has to be small or the number is not a property."""
    worst, median = arms["clears"]
    assert median - worst < 1.0, f"worst {worst:.3f} median {median:.3f}"


# ── and the EMITTER actually builds it ────────────────────────────────────
#: The declaration this entry admits — the smallest values satisfying its own
#: declared domains, so the fixture cannot drift from the entry's requirements.
_SPEC = {"order": 2.0, "vdd": 1.2, "osr": 256.0, "enob": 14.0, "vref": 1.0,
         "fclk": 1.0, "fclk_max": 1.0}
_MEASURED = {"cap_area_ff_per_um2": 1.5, "rsheet_ohm_per_sq": 260.0,
             "vth_n_extracted_v": 0.42, "cap_perim_ff_per_um": 0.1}


@pytest.fixture(scope="module")
def emitted_ir():
    """The IR the SHIPPED library entry emits — not a hand-written structure."""
    return a2.build_ir("mod", "delta_sigma", {}, a2.LIBRARY["delta_sigma"],
                       dict(_SPEC), None, Path("."), "sky130", {},
                       measured_params=dict(_MEASURED))


def _gate_of(ir, name):
    for d in ir["devices"]:
        if d["name"] == name:
            return d["nets"][1]
    raise AssertionError(f"{name} not in the emitted IR")


def test_every_dac_sampling_switch_is_gated_by_the_reset_gated_clock(emitted_ir):
    """The defect direction: a switch on the RAW clock samples through the
    reset, which is exactly what the measurement above costs 6.7 bit."""
    dacs = [d["name"] for d in emitted_ir["devices"]
            if d["name"].startswith(("mn_dacs", "mp_dacs"))]
    assert dacs, "the emitted IR carries no DAC sampling switch"
    for name in dacs:
        gate = _gate_of(emitted_ir, name)
        assert gate in ("nckdac", "nckdacb"), (
            f"{name} is gated by {gate!r}: it samples the reference through "
            f"the conversion-window reset")


def test_every_dac_return_switch_holds_the_plate_through_the_reset(emitted_ir):
    """The return switch is what makes the held value the COMMON MODE — i.e.
    zero feedback — rather than leaving the plate floating."""
    for d in emitted_ir["devices"]:
        if d["name"].startswith(("mn_dacr", "mp_dacr")):
            assert d["nets"][1] in ("nckdac", "nckdacb"), d
            assert d["nets"][2] == "vcm", d


def test_the_gated_clock_is_the_clock_ANDed_with_the_resets_complement(emitted_ir):
    """The original sample phase is admitted only after reset and a fresh decision."""
    rows = {d["name"]: d for d in emitted_ir["devices"]}
    gates = {name: d["nets"] for name, d in rows.items()}
    aliases = a2.LIBRARY["delta_sigma"][a2.CLOCK_PHASE_ALIASES_KEY]
    for name in ("mp_ndac1", "mn_ndac1"):
        assert a2._resolve_phase(gates[name][1], aliases) == "clk"
    assert gates["mp_ndac2"][1] == gates["mn_ndac2"][1]
    valid = emitted_ir["incremental_startup"]["decision_valid_net"]
    for reset, decision_valid, sample in product((0, 1), repeat=3):
        known = {"nrstb": 1-reset, valid: decision_valid, "nph1": sample}
        assert logic(rows, gates["mn_ndac2"][1], known) == int(not reset and decision_valid)
        expected = int(sample and not reset and decision_valid)
        assert logic(rows, "nckdac", known) == expected
        assert logic(rows, "nckdacb", known) == 1-expected
    assert gates["mn_ndac1"][2] == gates["mn_ndac2"][0] == "nndacs"
    assert gates["mp_ckdac"][1] == gates["mn_ckdac"][1] == "nndac"
    assert gates["mp_ckdacb"][1] == gates["mn_ckdacb"][1] == "nckdac"


def test_outside_the_reset_the_branch_is_on_the_clock_it_always_was(emitted_ir):
    """Qualified input and feedback still transfer together in steady operation.

    D1's first input update retains its zero feedback pipeline; it must not
    wait for the comparator decision that this same update produces.
    """
    rows = {d["name"]: d for d in emitted_ir["devices"]}
    gates = {name: d["nets"] for name, d in rows.items()}
    control = emitted_ir["incremental_startup"]
    assert emitted_ir["loop_declaration"]["D"] == 1
    valid, ready = control["decision_valid_net"], control["transfer_ready_net"]
    feedback_ready = control["feedback_ready_net"]
    for reset, phi2 in product((0, 1), repeat=2):
        known = {"nrstb": 1-reset, "nph1": 1-phi2, "nph2": phi2,
                 valid: 1, ready: 1, feedback_ready: 1}
        expected = int(not reset and phi2)
        for stem in ("cstv1", "cftv1"):
            assert logic(rows, gates["mn_"+stem][1], known) == expected
            assert logic(rows, gates["mp_"+stem][1], known) == 1-expected
        assert logic(rows, "nckdac", known) == int(not reset and not phi2)
    first = {"nrstb": 1, "nph1": 0, "nph2": 1,
             valid: 0, ready: 1, feedback_ready: 0}
    assert logic(rows, gates["mn_cstv1"][1], first) == 1
    assert logic(rows, gates["mn_cftv1"][1], first) == 0
    assert logic(rows, "nckdac", first) == 0
    assert gates["mn_dacs1"][1] == "nckdac"
    assert gates["mn_dacr1"][1] == "nckdacb"


# ── the gate term must not move the derived parity ────────────────────────
#
# `sc_branch_polarities` decides a branch's polarity by comparing the IDENTITY
# of two gate nets. The feedback branch's sampling switch is now on
# `clk AND nrstb` — the SAME PHASE, released, and a DIFFERENT NET — so an
# identity comparison read it as a re-timed branch and flipped the derived
# feedback selector. Round17's contract is landed and correct; what was wrong
# was that the derivation could not tell a gated clock from another phase.
# The entry that BUILDS the gate declares what phase its output carries, and
# that declaration is about a NET, never about a polarity.
def test_the_entry_declares_the_phase_its_gated_clock_carries():
    """The two nets THIS change builds. The entry declares others too — the
    quantiser's strobe chain, added by R-0915-77 — so the assertion is on the
    pair this commit is about, by membership rather than by equality: a set
    equality here would make every later gate a red in this file."""
    # ROUND-ICADC2: the gated clock is now declared against the PHASE it is
    # really gated from, which resolves on to `clk`. Asked as a resolution so
    # the assertion is about the phase the net carries -- which is what this
    # test is named for -- and not about how many hops the entry takes to say
    # it. A genuinely different phase still fails.
    aliases = a2.LIBRARY["delta_sigma"][a2.CLOCK_PHASE_ALIASES_KEY]
    assert a2._resolve_phase("nckdac", aliases) == "clk"
    assert a2._resolve_phase("nckdacb", aliases) == "nclkb"


def test_resolving_a_phase_follows_the_alias_and_terminates_on_a_cycle():
    a = {"nckdac": "clk", "nckdacb": "nclkb"}
    assert a2._resolve_phase("nckdac", a) == "clk"
    assert a2._resolve_phase("nckdacb", a) == "nclkb"
    assert a2._resolve_phase("clk", a) == "clk"
    assert a2._resolve_phase("nsomething", a) == "nsomething"
    assert a2._resolve_phase(None, a) is None
    # a malformed alias must not hang an emitter
    assert a2._resolve_phase("x", {"x": "y", "y": "x"}) in ("x", "y")


def _stage_group():
    st = [g for g in a2._stage_groups(a2.LIBRARY["delta_sigma"])
          if g.get("first_in")][0]
    return json.loads(json.dumps(st))


def _polarities(st, aliases):
    probe = {"i": 1, "i1": 2, "in": "vin", "out": "vo1", "coeff": "1.0",
             "alt": a2._SC_ALT_SENTINEL, "in2": "x2", "out2": "y2"}
    devs = []
    for d in st["devices"]:
        nd = dict(d)
        nd["nets"] = [str(n).format(**probe) for n in d.get("nets") or []]
        nd["name"] = str(d["name"]).format(**probe)
        devs.append(nd)
    return {k: v["polarity"] for k, v in
            a2.sc_branch_polarities(devs, aliases).items()}


def test_the_gated_clock_reads_as_the_phase_it_carries():
    """THE FIX DIRECTION: with the alias the branch has the polarity it would
    have on the raw clock — the gate term changed WHEN the switch is allowed
    to close, not WHICH phase it closes on."""
    st = _stage_group()
    aliased = _polarities(st, a2.LIBRARY["delta_sigma"][a2.CLOCK_PHASE_ALIASES_KEY])
    # the same stage with the gate term removed by hand — the pre-change deck
    raw = json.loads(json.dumps(st))
    for d in raw["devices"]:
        if d["name"] in ("mn_dacs{i}",):
            d["nets"][1] = "clk"
        elif d["name"] in ("mp_dacs{i}",):
            d["nets"][1] = "nclkb"
        elif d["name"] in ("mn_dacr{i}",):
            d["nets"][1] = "nclkb"
        elif d["name"] in ("mp_dacr{i}",):
            d["nets"][1] = "clk"
    assert aliased == _polarities(raw, None), (aliased, _polarities(raw, None))


def test_the_control_without_the_alias_the_gated_clock_reads_as_another_phase():
    """THE CONTROL, and it is why the declaration has to exist.

    It has to be taken on the topology where the two readings CAN differ. On
    the shipped entry the feedback branch's two gates are `nckdac` and
    `nclkb`, which are unequal either way — so that arm proves nothing, and a
    control that passed there would be pinning nothing. Take it on round17's
    own mutation instead: the feedback branch made delay-free, where the top
    plate's throw moves onto `clk`. Read WITH the alias the two gates are
    `clk` and `clk` — equal, polarity -1, which is what "delay-free" means.
    Read WITHOUT it they are `nckdac` and `clk` — unequal, polarity +1, and
    the mutation the test performed has been silently undone."""
    st = _stage_group()
    for d in st["devices"]:
        if d["name"] == "mn_cftv{i}":
            d["nets"][1] = "clk"
        elif d["name"] == "mp_cftv{i}":
            d["nets"][1] = "nclkb"
        elif d["name"] == "mn_cftc{i}":
            d["nets"][1] = "nclkb"
        elif d["name"] == "mp_cftc{i}":
            d["nets"][1] = "clk"
    with_alias = _polarities(
        st, a2.LIBRARY["delta_sigma"][a2.CLOCK_PHASE_ALIASES_KEY])
    without = _polarities(st, None)
    assert with_alias["cf1"] == -1, with_alias
    assert without["cf1"] == +1, without


def test_the_alias_does_not_collapse_two_genuinely_different_phases():
    """The way an alias goes wrong: by making everything equal. A branch moved
    onto the OPPOSITE phase must still read as the opposite phase, alias or
    no alias."""
    st = _stage_group()
    aliases = a2.LIBRARY["delta_sigma"][a2.CLOCK_PHASE_ALIASES_KEY]
    base = _polarities(st, aliases)
    flipped = json.loads(json.dumps(st))
    for d in flipped["devices"]:
        if d["name"] == "mn_cftv{i}":
            d["nets"][1] = "clk"
        elif d["name"] == "mp_cftv{i}":
            d["nets"][1] = "nclkb"
        elif d["name"] == "mn_cftc{i}":
            d["nets"][1] = "nclkb"
        elif d["name"] == "mp_cftc{i}":
            d["nets"][1] = "clk"
    assert _polarities(flipped, aliases) != base
