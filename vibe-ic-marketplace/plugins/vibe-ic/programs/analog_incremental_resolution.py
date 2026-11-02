#!/usr/bin/env python3
"""analog_incremental_resolution.py — what resolution an INCREMENTAL loop can
actually reach, MEASURED on its own recurrence.

CHIP_AGNOSTIC: strict-logic

WHY THIS EXISTS. An incremental converter's textbook ceiling is
`log2(N(N-1)/2)` at order 2 — 14.994 at N=256, 16.997 at N=512. A generator
that sizes a loop against that number sizes it against a bound the loop does
not reach: measured on the recurrence the emitter actually emits, with the
matched decode and a coherent in-band tone, N=256 order 2 reaches **10.68 bit**
and N=512 reaches **12.75** (lane icadc, F168). The 4.3-bit shortfall is not
noise and not the tone's position — a HELD input reads the same to 0.2 bit —
it is the loop.

So a choice between two oversampling ratios, or between two loop orders, or
between a delaying and a delay-free feedback branch, cannot be made from the
closed form. It is made HERE, by running the recurrence.

WHAT IT RUNS, AND WHY THAT IS NOT A SIMULATION. The model is the same
difference equation `analog_incremental_decimator` derives its weights from,
with the same per-stage coefficient and the same feedback delay:

    v[n]   = +1 if I_last > 0 else -1          (a 1-bit quantiser)
    I_s[n] = I_s[n-1] + a * (I_{s-1}[n-1] - d[n])
    I_0[n] = I_0[n-1] + a * (u[n]         - d[n])
    d[n]   = v[n - feedback_delay]

Arithmetic only: no device, no PDK, no simulator. It answers "what can this
RECURRENCE resolve", which is the ceiling every device below it is then held
to — never "what does this circuit do".

WHAT IT CANNOT SEE, AND IT COST A COMMIT TO FIND OUT. The model treats each
integrator as a STATE HELD BETWEEN STEPS, so it will happily tell you that a
decision taken "in step n" beats one taken "in step n-1" — it has no notion of
WHICH PHYSICAL INSTANT inside a clock period a decision is taken at. The
circuit does. MEASURED on the emitted deck (lane icadc, R-0915-81): the last
integrator's output is flat to 0.2 mV for the whole CHARGE-TRANSFER phase
(-0.01240, -0.01223, -0.01223, -0.01222 V from the common mode across 440 ns)
and wanders over 270 mV during the SAMPLING phase (+0.148, +0.193, -0.081,
-0.061, +0.023, -0.029). A model that says "move the decision earlier by one
step" is describing a node that, at that instant, is not holding a value.

So this module chooses between things a DIFFERENCE EQUATION can distinguish —
how many clocks a window holds, how many integrators, what coefficient — and
NOT between things only a waveform can. On the one occasion it was asked to,
it preferred a delay-free loop by 1.5 bit and the harness measured the same
change at MINUS 7.4. Its preference for a smaller feedback delay is recorded
here as a known blind spot rather than removed, because the delay is still a
real input to the WEIGHTS and the model must run the loop it is decoding.

IT REPORTS THE EXCURSION WITH THE BITS, and that is load-bearing: a
coefficient that resolves better by driving the integrators past the supply
has not resolved better, it has clipped. `peak_per_stage` is in units of the
half reference span, so the declared budget
`integrator_swing_fraction_of_vdd * vdd / 2 / (vref / 2)` is directly
comparable. MEASURED: at a feedback delay of 1 the SECOND integrator peaks at
2.95 for a=0.25 and 74.6 for a=0.5; at delay 0, at 0.74 and 3.49. The delay is
what forces the small coefficient.

THE TONE IS COPRIME WITH THE WINDOWS, from `analog_resolution_stimulus`'s own
rule and never a second copy: a tone whose period in conversion windows is a
small integer makes the loop's deterministic error a component at the SIGNAL's
frequency, where an SNDR removes it as signal, and the instrument then reads
the worst placement as the best (vibe-ic F167).

AND IT IS SCORED WITHOUT A SPECTRUM. The decoded value is compared against the
INPUT-WEIGHTED truth — the same input weights the decode normalises by, so the
comparison is against what the loop was actually asked to average — and the
resolution is `-log2(2 * rms)` against full scale. No bin is excluded, so no
error can hide at the signal's own frequency by construction rather than by
luck.

No chip / SKU / foundry literal.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                     # noqa: E402
import sys as _sys                                                   # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import math                                                          # noqa: E402
import statistics                                                    # noqa: E402
from typing import Any, Dict, List, Optional, Sequence                # noqa: E402

import analog_incremental_decimator as _dec                          # noqa: E402
import analog_resolution_stimulus as _stim                           # noqa: E402

PRODUCER = "analog_incremental_resolution"

#: How many tone phases each arm is measured over, and why more than one: the
#: loop is EXACTLY periodic in `graded_windows / cycles` windows, so a single
#: phase is an accident. MEASURED: an 8x longer record returns the identical
#: number, which is what proves the periodicity — only the phase moves it.
DEFAULT_PHASES = 4

#: The default stimulus, when the declaration names none. `amplitude` and
#: `offset` are in units of the HALF reference span, so +-1 is the reference.
#: DISCLOSED rather than derived: L5 carries no test-amplitude row for this
#: class, so this is the plugin's own declared test condition and is published
#: with every answer.
DEFAULT_AMPLITUDE = 0.72
DEFAULT_OFFSET = 0.20

NO_TONE = "no_gradable_tone_for_this_record"
BAD_INPUT = "resolution_model_input_out_of_range"


def _run(window: int, order: int, coeff: float, feedback_delay: int,
         graded: int, cycles: int, phase: float,
         amplitude: float, offset: float) -> Dict[str, Any]:
    weights = _dec.matched_weights(window, order, coeff, feedback_delay)
    in_w = _dec.input_weights(window, order, coeff)
    norm = sum(in_w)
    f_sig = cycles / float(graded * window)
    peak = [0.0] * order
    errs: List[float] = []
    for win in range(graded + 1):
        st = [0.0] * order
        pipe = [0.0] * max(feedback_delay, 0)
        decoded = 0.0
        truth = 0.0
        for k in range(window):
            n = win * window + k
            u = offset + amplitude * math.sin(2.0 * math.pi * f_sig * n + phase)
            v = 1.0 if st[order - 1] > 0.0 else -1.0
            d = v if feedback_delay == 0 else pipe[0]
            for s in range(order - 1, 0, -1):
                st[s] += coeff * (st[s - 1] - d)
            st[0] += coeff * (u - d)
            for s in range(order):
                if abs(st[s]) > peak[s]:
                    peak[s] = abs(st[s])
            if feedback_delay:
                pipe = pipe[1:] + [v]
            decoded += weights[k] * v
            truth += in_w[k] * u
        # the FIRST window is not a conversion: the counter's power-up state
        # is not a declared reset instant, which is what the emitted deck's
        # own condition line says.
        if win:
            errs.append((decoded - truth) / norm)
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    return {"rms": rms, "peak_per_stage": peak}


def achievable(window_clocks: int, order: int, coeff: float,
               feedback_delay: int, amplitude: float = DEFAULT_AMPLITUDE,
               offset: float = DEFAULT_OFFSET, phases: int = DEFAULT_PHASES
               ) -> Dict[str, Any]:
    """`{"bits", "peak_per_stage", ...}` — what this recurrence resolves, or
    `{"reason": ...}` when no gradable tone exists for it."""
    if not all(isinstance(x, int) and not isinstance(x, bool)
               for x in (window_clocks, order, feedback_delay)):
        return {"reason": BAD_INPUT}
    if window_clocks < 2 or order < 1 or feedback_delay < 0 or coeff <= 0:
        return {"reason": BAD_INPUT}
    tone = _stim.incremental_tone(_stim.incremental_record_windows())
    if tone is None:
        return {"reason": NO_TONE}
    graded, cycles = tone["graded_windows"], tone["cycles"]
    runs = [_run(window_clocks, order, float(coeff), feedback_delay,
                 graded, cycles, 2.0 * math.pi * i / phases,
                 float(amplitude), float(offset))
            for i in range(max(int(phases), 1))]
    rms = [r["rms"] for r in runs]
    peak = [max(r["peak_per_stage"][s] for r in runs) for s in range(order)]
    worst = max(rms)
    return {
        "producer": PRODUCER,
        # WORST over the phases, never the median: the number a design is
        # admitted on has to be the one it is worst at.
        "bits": -math.log2(2.0 * worst),
        "bits_median": -math.log2(2.0 * statistics.median(rms)),
        "rms_worst": worst,
        "peak_per_stage": peak,
        "window_clocks": window_clocks, "order": order, "coeff": float(coeff),
        "feedback_delay_clocks": feedback_delay,
        "graded_windows": graded, "cycles": cycles,
        "tone_rule": tone["rule"],
        "amplitude": float(amplitude), "offset": float(offset),
        "amplitude_source": "plugin_declared_test_condition",
        "phases": int(phases),
        "ceiling_bits": (math.log2(math.comb(window_clocks, order))
                         if window_clocks > order else 0.0),
        "rule": "measured_on_the_loops_own_recurrence",
    }


def swing_budget(constants: Dict[str, Any], spec_values: Dict[str, float]
                 ) -> Optional[float]:
    """The integrator excursion the declaration allows, in the same units
    `peak_per_stage` is reported in — or None when the declaration does not
    bound it. Derived from the entry's own constant and the bound rows; never
    a number typed here."""
    frac = (constants or {}).get("integrator_swing_fraction_of_vdd")
    vdd = (spec_values or {}).get("vdd")
    vref = (spec_values or {}).get("vref")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
               and x > 0 for x in (frac, vdd, vref)):
        return None
    return (float(frac) * float(vdd) / 2.0) / (float(vref) / 2.0)


def choose(candidates: Sequence[int], order: int, coeff_of,
           feedback_delay: int, target_bits: float,
           amplitude: float = DEFAULT_AMPLITUDE,
           offset: float = DEFAULT_OFFSET,
           swing_max: Optional[float] = None,
           phases: int = DEFAULT_PHASES) -> Dict[str, Any]:
    """The SMALLEST candidate window that reaches `target_bits` inside the
    swing budget, with every candidate's measurement kept.

    Smallest, not best: an oversampling ratio buys resolution with conversion
    time, and taking more than the declaration is held to would be spending
    someone else's budget. When none reaches the target the largest is
    returned with `met` false — a refusal a caller can act on, never silently
    the closed form's answer.
    """
    rows: List[Dict[str, Any]] = []
    for n in sorted(int(c) for c in candidates):
        got = achievable(n, order, float(coeff_of(n)), feedback_delay,
                         amplitude, offset, phases)
        if "bits" not in got:
            rows.append({"window_clocks": n, "reason": got.get("reason")})
            continue
        over = (swing_max is not None
                and max(got["peak_per_stage"]) > float(swing_max))
        rows.append({"window_clocks": n, "bits": got["bits"],
                     "coeff": got["coeff"],
                     "peak_per_stage": got["peak_per_stage"],
                     "over_swing_budget": over,
                     "ceiling_bits": got["ceiling_bits"]})
    ok = [r for r in rows if r.get("bits", -1.0) >= float(target_bits)]
    chosen = ok[0] if ok else None
    # THE SWING IS REPORTED AT THE TOP LEVEL, not only inside the row. A
    # candidate that reaches the graded target by driving the integrators past
    # the supply has not reached it, and a consumer must not have to dig for
    # that. It is NOT used to filter here: which of two failures a design has
    # is the caller's to act on, and silently returning "no candidate" would
    # hide a loop that resolves and needs more headroom behind one that does
    # not resolve at all.
    picked = chosen if chosen is not None else (rows[-1] if rows else None)
    return {"producer": PRODUCER, "candidates": rows,
            "target_bits": float(target_bits),
            "swing_budget": swing_max,
            "chosen_over_swing_budget": bool(
                (picked or {}).get("over_swing_budget")),
            "met": chosen is not None,
            "chosen": picked,
            "rule": "smallest_window_measured_to_reach_the_graded_target"}


# ══ THE SWING MODEL, PER STAGE (q6-a2-cap-osr) ═════════════════════════════
#
# WHY THE SCALAR RECURRENCE ABOVE CANNOT JUDGE SWING. `_run` ties the input,
# inter-stage and DAC coefficients of every stage to ONE number, while the
# emitted circuit has separate `cs_i`, `cf_i` and `ci_i` devices. So it cannot
# express the one transformation that fixes swing — diagonal state scaling
# (Schreier's `scaleABCD`: x' = S x, which takes no OSR argument) — and its
# verdict "over the swing budget at every OSR" was a MODEL defect, not an OSR
# property: MEASURED on this recurrence, the peaks at DC inputs up to 0.92 are
# identical at N = 64 and N = 512, and scaling stage i by k leaves the
# bitstream bit-identical while multiplying that stage's peak by exactly k.
#
# The generalised loop, in units of the HALF reference span:
#
#     x_1[n] = x_1[n-1] + b_1 * u[n]      - a_1 * d[n] + o_1
#     x_s[n] = x_s[n-1] + c_s * x_{s-1}   - a_s * d[n] + o_s
#     v[n]   = +1 if x_last > 0 else -1 ;  d[n] = v[n - feedback_delay]
#
# with `b_1`, `a_s`, `c_s` and the per-clock offsets `o_s` MEASURED on the
# emitted netlist (`analog_sc_loop_probe`), never taken from the capacitor
# ratios alone: on u_hawaii_adc the DAC branch measured 0.2494 against a cap
# ratio of 0.2499, and the input branch 0.2686 against the SAME ratio — a
# branch without bottom-plate sampling takes signal-dependent charge
# injection, which no ratio shows.

#: The margin below the first N-dependent input level that the loop's
#: effective full-scale input must keep (q6 verifier, B4'): it covers cap
#: mismatch, reference/supply tolerance and injection drift across corners.
INPUT_STABILITY_MARGIN = 0.07
#: The fraction of the swing limit each scaled stage is allowed to reach
#: (B3'): scaled to x_lim * (1 - m), never to x_lim itself.
SWING_SCALE_MARGIN = 0.10
#: The extra input level the peaks are evaluated at, above the effective
#: full-scale input (B3').
PEAK_EVAL_HEADROOM = 0.03
#: Relative growth of the peak ENVELOPE between two windows that counts as
#: "the loop's swing has become N-dependent" (see `stable_input_limit`).
N_DEPENDENCE_TOLERANCE = 0.25
#: A measured coefficient further than this from its capacitor ratio says the
#: branch does not realise its ratio (q6 verifier, B1').
COEFFICIENT_RATIO_TOLERANCE = 0.02


def run_loop(window: int, b1: float, a: Sequence[float], c: Sequence[float],
             feedback_delay: int, stimulus, offsets: Sequence[float] = (),
             windows: int = 1, *, feedforward: Sequence[float] = (),
             input_feedforward: float = 0.0, feedback_compensation: float = 0.0,
             state_limits: Sequence[float] = (),
             loop_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the per-stage loop for `windows` conversion windows, each from a
    reset state. `stimulus(n)` is the input at clock n. Returns the per-stage
    peak and the bitstream (so two coefficient sets can be compared for
    bit-identity). `c[0]` is unused (stage 1 takes `b1`).

    `a` declares DAC injection at each stage; CIFF uses a[1:] = 0 and
    declares the quantiser's state/input feedforward and delayed-decision
    compensation separately. Empty feedforward keeps the CIFB quantiser.
    Declared physical state limits clip the states and report saturation;
    bounded clipping must never masquerade as loop stability."""
    if loop_model is not None:
        model = _dec.validate_loop_model(loop_model)
        a = [-x for x in model["feedback_vector"]]
        c = [0.] + [model["transition"][i][i-1] for i in range(1, len(a))]
        feedback_delay = model["feedback_delay_clocks"]
        feedforward = model["feedforward_weights"]
        input_feedforward, feedback_compensation = model["input_feedforward"], model["feedback_compensation"]
    order = len(a)
    if (order < 1 or len(c) != order or feedback_delay < 0
            or (feedforward and len(feedforward) != order)
            or (state_limits and (len(state_limits) != order or
                any(not math.isfinite(x) or x <= 0 for x in state_limits)))):
        raise ValueError(BAD_INPUT)
    off = list(offsets) + [0.0] * (order - len(offsets))
    peak = [0.0] * order
    bits: List[int] = []
    decisions: List[float] = []
    saturated = False
    for win in range(windows):
        st = [0.0] * order
        pipe = [0.0] * max(feedback_delay, 0)
        previous = 0.0
        for k in range(window):
            n = win * window + k
            u = stimulus(n)
            y = (input_feedforward * u + sum(g * x for g, x in zip(feedforward, st))
                 - feedback_compensation * previous) if feedforward else st[order - 1]
            if loop_model is None:
                v = 1.0 if y > 0.0 else -1.0
            else:
                levels = model["quantizer_levels"]
                thresholds = model.get("quantizer_thresholds", [(x + z) / 2 for x,z in zip(levels, levels[1:])])
                index = sum(y > threshold for threshold in thresholds)
                v = levels[index]
                if index < len(thresholds) and y == thresholds[index]:
                    v = min(levels[index:index+2], key=abs)
            d = v if feedback_delay == 0 else pipe[0]
            if loop_model is None:
                for s in range(order - 1, 0, -1):
                    st[s] += c[s] * st[s - 1] - a[s] * d + off[s]
                st[0] += b1 * u - a[0] * d + off[0]
            else:
                st = [sum(g*x for g,x in zip(row, st)) + model["input_vector"][i]*u
                      + model["feedback_vector"][i]*d + off[i]
                      for i,row in enumerate(model["transition"])]
            if not all(math.isfinite(x) for x in st) or not math.isfinite(y):
                return {"peak_per_stage": [math.inf] * order, "bits": bits,
                        "saturated": saturated, "unbounded": True}
            if state_limits:
                saturated |= any(abs(x) >= limit for x, limit in zip(st, state_limits))
                st = [max(-limit, min(limit, x)) for x, limit in zip(st, state_limits)]
            for s in range(order):
                if abs(st[s]) > peak[s]:
                    peak[s] = abs(st[s])
            if feedback_delay:
                pipe = pipe[1:] + [v]
            previous = v
            bits.append(1 if v > 0 else 0)
            decisions.append(v)
    result = {"peak_per_stage": peak, "bits": bits, "saturated": saturated, "unbounded": False}
    if loop_model is not None:
        result["decisions"] = decisions
    return result


def _dc(u: float):
    return lambda n: u


def _tone(amplitude: float, window: int, phase: float, cycles: int,
          graded: int):
    f = cycles / float(graded * window)
    return lambda n: amplitude * math.sin(2.0 * math.pi * f * n + phase)


def loop_peaks(window: int, b1: float, a: Sequence[float],
               c: Sequence[float], feedback_delay: int, u: float,
               phases: int = DEFAULT_PHASES) -> Dict[str, Any]:
    """The per-stage peak over DC inputs at +u and -u AND a coherent tone of
    amplitude u (the same coprime tone rule `achievable` uses), with every
    arm's peaks kept so a reader can see which one bound."""
    arms: Dict[str, List[float]] = {}
    for sgn in (1.0, -1.0):
        arms[f"dc_{sgn * u:+.4f}"] = run_loop(
            window, b1, a, c, feedback_delay, _dc(sgn * u))["peak_per_stage"]
    tone = _stim.incremental_tone(_stim.incremental_record_windows())
    if tone is not None:
        g, cyc = tone["graded_windows"], tone["cycles"]
        tp = [0.0] * len(a)
        for i in range(max(int(phases), 1)):
            r = run_loop(window, b1, a, c, feedback_delay,
                         _tone(u, window, 2.0 * math.pi * i / phases, cyc, g),
                         windows=g + 1)["peak_per_stage"]
            tp = [max(x, y) for x, y in zip(tp, r)]
        arms[f"tone_{u:.4f}"] = tp
    peak = [max(v[s] for v in arms.values()) for s in range(len(a))]
    return {"peak_per_stage": peak, "arms": arms, "u": u}


def stable_input_limit(b1: float, a: Sequence[float], c: Sequence[float],
                       feedback_delay: int, window: int, reference_window: Optional[int] = None,
                       step: float = 0.01, top: float = 1.0,
                       tolerance: float = N_DEPENDENCE_TOLERANCE, *,
                       feedforward: Sequence[float] = (), input_feedforward: float = 0.0,
                       feedback_compensation: float = 0.0,
                       state_limits: Sequence[float] = (),
                       loop_model: Optional[Dict[str, Any]] = None) -> float:
    """The largest DC input level (on a `step` grid, in units of the loop's
    own full scale b1 = a1) below which the loop's swing does not grow with
    the window length.

    ON THE ENVELOPE, NOT THE POINT. A single DC level is a bad witness: a
    rational input puts the loop on a long limit cycle whose extreme a short
    window may not reach. MEASURED on this recurrence (a = 0.2499, delay 1):
    at u = 0.50 the stage peak doubles between N = 512 and N = 1024 while the
    loop is perfectly bounded, and at u = 0.92 the two windows happen to
    agree although the envelope has already grown by 23 %. So the quantity
    compared is the ENVELOPE E_N(u) = max over |u'| <= u of the per-stage
    peak. Compare N with at least 4*N: a bounded higher-order loop can need
    more than 64 clocks to reach its envelope. `reference_window` may request
    a longer observation, but cannot shorten that reference. The limit is
    the last grid level before any stage grows by more than `tolerance`,
    becomes non-finite, or reaches a declared physical state limit."""
    if (window < 1 or step <= 0 or top < 0 or tolerance < 0
            or (reference_window is not None and reference_window < 1)):
        raise ValueError(BAD_INPUT)
    long_window = max(4 * window, reference_window or 0)
    options = {"feedforward": feedforward, "input_feedforward": input_feedforward,
               "feedback_compensation": feedback_compensation, "state_limits": state_limits,
               "loop_model": loop_model}
    if loop_model is not None:
        a = _dec.validate_loop_model(loop_model)["feedback_vector"]
    env_w = [0.0] * len(a)
    env_r = [0.0] * len(a)
    last = 0.0
    n = int(round(top / step))
    for i in range(0, n + 1):
        u = i * step
        for sgn in ((1.0,) if i == 0 else (1.0, -1.0)):
            short = run_loop(window, b1, a, c, feedback_delay, _dc(sgn * u), **options)
            long = run_loop(long_window, b1, a, c, feedback_delay, _dc(sgn * u), **options)
            if any(r["saturated"] or r["unbounded"] for r in (short, long)):
                return last
            p1, p0 = long["peak_per_stage"], short["peak_per_stage"]
            env_w = [max(x, y) for x, y in zip(env_w, p1)]
            env_r = [max(x, y) for x, y in zip(env_r, p0)]
        if any(x > (1.0 + tolerance) * max(y, 1e-12)
               for x, y in zip(env_w, env_r)):
            return last
        last = u
    return last


def declared_stable_input_limit(loop_model: Dict[str, Any], window: int, **options) -> float:
    """Stability consumer of the SAME canonical model used by the decoder."""
    model = _dec.validate_loop_model(loop_model)
    order = len(model["input_vector"])
    return stable_input_limit(0., [0.] * order, [0.] * order,
        model["feedback_delay_clocks"], window, loop_model=model, **options)


def scale_states(b1: float, a: Sequence[float], c: Sequence[float],
                 k: Sequence[float], offsets: Sequence[float] = ()
                 ) -> Dict[str, Any]:
    """Diagonal state scaling x'_i = k_i x_i: b1, a_1 x k_1; c_i x
    k_i / k_{i-1}; a_i x k_i; o_i x k_i. The quantiser reads only the SIGN of
    the last state, so any k_i > 0 leaves the bitstream unchanged."""
    order = len(a)
    a2 = [a[i] * k[i] for i in range(order)]
    c2 = [0.0] + [c[i] * k[i] / k[i - 1] for i in range(1, order)]
    off = list(offsets) + [0.0] * (order - len(offsets))
    return {"b1": b1 * k[0], "a": a2, "c": c2,
            "offsets": [off[i] * k[i] for i in range(order)]}


def swing_design(window: int, reference_window: int, feedback_delay: int,
                 a: Sequence[float], c: Sequence[float],
                 b1_over_a1_per_cap_ratio: float, offset_u: float,
                 u_decl: float, x_lim: float,
                 margin_u: float = INPUT_STABILITY_MARGIN,
                 margin_scale: float = SWING_SCALE_MARGIN,
                 headroom: float = PEAK_EVAL_HEADROOM,
                 phases: int = DEFAULT_PHASES) -> Dict[str, Any]:
    """Input attenuation and dynamic-range scaling FROM THE DESIGN'S OWN
    DECLARED SPAN, with margin (q6 verifier's B3'/B4').

    `a`, `c` are the loop's DAC and inter-stage coefficients as MEASURED (or,
    disclosed, as the capacitor ratios when no measurement exists).
    `b1_over_a1_per_cap_ratio` is the MEASURED input-branch gain relative to
    its capacitor ratio, (b1/a1)_meas / (cs1/cf1): 1.0 for a branch that
    realises its ratio, 1.077 measured on a branch without bottom-plate
    sampling. `offset_u` is the per-clock offset referred to the input, in
    units of the loop's full scale.

    1. u_stable: the largest input at which the loop's peaks do not grow with
       N (`stable_input_limit`).
    2. The effective full-scale input must keep `margin_u` below it:
       u_eff_max = (b1/a1) * u_decl + |offset_u| <= u_stable - margin_u.
       That fixes b1/a1, and the DRAWN ratio cs1/cf1 = (b1/a1) / gain.
    3. Peaks at u_eff_max + headroom over DC and a full-span tone.
    4. k_i = x_lim * (1 - margin_scale) / peak_i, the scaled loop, and the
       assertion that its bitstream is bit-identical to the unscaled one.
    """
    order = len(a)
    u_stable = stable_input_limit(a[0], a, c, feedback_delay, window,
                                  reference_window)
    ratio = (u_stable - margin_u - abs(offset_u)) / float(u_decl)
    rec: Dict[str, Any] = {
        "producer": PRODUCER, "window_clocks": window,
        "reference_window_clocks": max(4 * window, reference_window),
        "feedback_delay_clocks": feedback_delay,
        "u_decl": float(u_decl), "x_lim": float(x_lim),
        "u_stable": u_stable, "input_stability_margin": margin_u,
        "offset_u": float(offset_u), "swing_scale_margin": margin_scale,
        "peak_eval_headroom": headroom,
        "coefficients_unscaled": {"a": list(a), "c": list(c)},
        "input_branch_gain_over_cap_ratio": float(b1_over_a1_per_cap_ratio),
        "rule": "diagonal_state_scaling_at_the_declared_span_with_margin",
    }
    if ratio <= 0:
        rec.update({"feasible": False,
                    "reason": ("no positive input attenuation keeps the "
                               "declared span inside the stable region with "
                               "the stated margin")})
        return rec
    u_eff_max = ratio * u_decl + abs(offset_u)
    b1 = ratio * a[0]
    u_eval = u_eff_max + headroom
    # Evaluated with b1 = a1 at u_eval: u_eval IS the effective input.
    pk = loop_peaks(window, a[0], a, c, feedback_delay, u_eval, phases)
    k = [x_lim * (1.0 - margin_scale) / p if p > 0 else 1.0
         for p in pk["peak_per_stage"]]
    sc = scale_states(a[0], a, c, k)
    after = loop_peaks(window, sc["b1"], sc["a"], sc["c"], feedback_delay,
                       u_eval, phases)
    # BIT-IDENTITY, on every arm the peaks were taken over.
    ident = True
    for u in (u_eval, -u_eval):
        r0 = run_loop(window, a[0], a, c, feedback_delay, _dc(u))["bits"]
        r1 = run_loop(window, sc["b1"], sc["a"], sc["c"], feedback_delay,
                      _dc(u))["bits"]
        ident = ident and (r0 == r1)
    tone = _stim.incremental_tone(_stim.incremental_record_windows())
    if tone is not None:
        g, cyc = tone["graded_windows"], tone["cycles"]
        st = _tone(u_eval, window, 0.0, cyc, g)
        r0 = run_loop(window, a[0], a, c, feedback_delay, st,
                      windows=g + 1)["bits"]
        r1 = run_loop(window, sc["b1"], sc["a"], sc["c"], feedback_delay,
                      st, windows=g + 1)["bits"]
        ident = ident and (r0 == r1)
    drawn_ratio = ratio / float(b1_over_a1_per_cap_ratio)
    rec.update({
        "feasible": True,
        "b1_over_a1": ratio,
        "cs1_over_cf1_drawn": drawn_ratio,
        "u_eff_max": u_eff_max, "u_eval": u_eval,
        "attenuation_db": 20.0 * math.log10(ratio),
        "peaks_before": pk["peak_per_stage"], "peak_arms_before": pk["arms"],
        "scale": k,
        # the SCALED loop, in the loop's own coefficient terms, with the
        # input path carrying the attenuation: b1' = k1 * ratio * a1.
        "coefficients_scaled": {"b1": k[0] * b1, "a": sc["a"],
                                "c": sc["c"]},
        "peaks_after": after["peak_per_stage"],
        "peak_arms_after": after["arms"],
        "bitstream_identical": ident,
        "within_x_lim": all(p <= x_lim + 1e-12
                            for p in after["peak_per_stage"]),
        "n_invariant_note": (
            "sized at the CHOSEN window, inside the input range where the "
            "loop's swing does not GROW with N (`u_stable`). At the other "
            "candidate windows the scaled peaks move by a few percent (a "
            "limit cycle a shorter window samples differently) and the "
            "emitter records them; the scale margin is what keeps them under "
            "x_lim. OSR is chosen on resolution alone"),
    })
    return rec


def declared_swing_limit(constants: Dict[str, Any],
                         spec_values: Dict[str, float]) -> Optional[float]:
    """x_lim at the DECLARED WORST CORNER: the entry's swing fraction of the
    LOWEST declared supply, over the HIGHEST declared reference, in half-span
    units — 0.833 * 1.1 / 1.2 = 0.764 on u_hawaii_adc, where the target-corner
    `swing_budget` reads 0.9996. None when the rows are not bound."""
    frac = (constants or {}).get("integrator_swing_fraction_of_vdd")
    sv = spec_values or {}
    vdd = sv.get("vdd_min", sv.get("vdd"))
    vref = sv.get("vref_max", sv.get("vref"))
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
               and x > 0 for x in (frac, vdd, vref)):
        return None
    return float(frac) * float(vdd) / float(vref)


def declared_input_span(spec_values: Dict[str, float],
                        input_spec: str = "vindiff") -> Optional[float]:
    """u_decl = the declared differential input over the declared reference
    (1.0 on u_hawaii_adc: full VHI-VLO span), in the loop's own units — not
    the plugin's 0.72 + 0.20 test tone. None when not bound."""
    sv = spec_values or {}
    vin = sv.get(input_spec)
    vref = sv.get("vref")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
               and x > 0 for x in (vin, vref)):
        return None
    return float(vin) / float(vref)
