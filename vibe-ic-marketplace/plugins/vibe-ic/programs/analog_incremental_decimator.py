#!/usr/bin/env python3
"""analog_incremental_decimator.py — R-0915-70: the matched decimator for an
INCREMENTAL converter, DERIVED from the loop's own recurrence.

WHY THIS EXISTS. L5 can declare a converter INCREMENTAL — "resets/accumulates
per conversion window" — and the emitted deck then resets its integrators every
N clocks (measured on this IC: exactly every 256 clocks, lane icadc
2026-09-16). A free-running delta-sigma earns its resolution from noise shaping
accumulated over the WHOLE record, and an FFT of the raw bitstream is the right
instrument for it. An incremental converter throws that accumulation away every
window BY DESIGN and earns its resolution from the MATCHED DECIMATION of each
window. Reading one with the other's instrument UNDER-READS it.

MEASURED, end to end through `analog_adc_enob_corner_check`'s own path, on a
bitstream from a pure-arithmetic ideal CIFB2 with no simulator anywhere
(54 conversion windows of 256 clocks, a coherent tone at bin 9):

    matched decimation (this module)   ENOB 13.366 bit   SNDR 82.226 dB
    the raw bitstream's in-band FFT    ENOB  7.775 bit   SNDR 48.565 dB

**5.6 bits.** That difference is the whole reason this module exists, and it is
a property of the DECODE, not of any circuit: the same bits read two ways.

AND THE WINDOW HAS TO BE ALIGNED TO THE RESET. The same record with every
window boundary moved half a conversion — the identical bits — reads **6.368
bit**, 7.0 bit below the aligned decode. An incremental converter's window is
the unit of its answer, and a boundary put half a window wrong averages two
conversions together. That is why the alignment is derived from the deck's own
clock card rather than assumed at t=0.

THE WEIGHTS ARE DERIVED, NOT TYPED. For a CIFB2 with reset,

    I1[n] = I1[n-1] + a1 * (u[n] - v[n])          I1[0] = 0  (the reset)
    I2[n] = I2[n-1] + a2 * I1[n-1]                I2[0] = 0

so the second integrator's value after N clocks is a DOUBLE sum, and collecting
terms gives

    I2[N] = a1*a2 * sum_{k} (N-1-k) * (u[k] - v[k])

I2[N] is bounded by the loop, so the weighted sums of u and v agree and the
decoded output is the TRIANGULARLY weighted mean of the bitstream. This module
computes those weights by running the recurrence itself
(:func:`matched_weights`) rather than writing `N-1-k` down: a coefficient set or
a cascade depth this file does not anticipate then gets the weights its own
recurrence implies, and a typed closed form would silently be wrong.

CIFF WITH THE DAC IN STAGE 1 ONLY uses the input path for feedback as well.
Its common product of stage gains cancels, even for unequal gains. The
normalised kernel is therefore CoI_L: at L=3 it is
`(N-1-k)(N-2-k)/2`, with a one-sample decision shift for D=1. The A2/A3
declaration selects this recurrence; no bitstream statistic selects it.
Legacy records/stamps retain their original CIFB recurrence.
An explicit state-equation model supplies both impulse paths directly and
also supports unequal CIFB gains and any declared finite decision alphabet.

FOR CIFB THE COEFFICIENT DOES APPEAR, and the earlier version of this paragraph said it
did not. That was true of the INPUT-injected weights, where `a1*a2` is a common
factor of every term and cancels in the normalised mean; it stopped being true
with the DAC-injected correction below, because the bit-to-output response
carries a FLAT `a2` term where the input's carries only `a1*a2`. So the decode
is insensitive to the coefficient only while every stage shares it — which is
what the shipped entries declare, one derivation per cascade — and a cascade
with UNEQUAL coefficients has to extend this rather than pass the first one.
`analog_resolution_stimulus.incremental_decode` refuses such an entry BY NAME
instead of averaging them.

What remains scale-invariant is the BITSTREAM: the same ideal model at a1=a2 of
1.0, 0.5, 0.25, 0.125 and 0.0625 produces the identical bits, because a
sign-based quantiser is scale-invariant. Only the decode's normalisation cares.

WHAT THIS MODULE DOES NOT CLAIM. On the pure-arithmetic ideal model the
matched decode reaches 13.366 bit where the standard incremental-2nd-order
result is log2(N(N-1)/2) = 14.994. The 1.6-bit gap that remains is the input
MOVING inside a conversion window — an incremental converter answers about one
window, and a tone is not constant across it — and it is a property of the
architecture at this N and this order, not of the decode. It is recorded here
because it is the honest ceiling this instrument can report, and it is BELOW a
14-bit target: a design graded against one has to change N or the order, and
no decode can be asked to make up the difference.

This module is the right instrument for the class; it is not a claim that any
particular loop meets its target.

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
import base64                                                        # noqa: E402
import json                                                          # noqa: E402
import re                                                            # noqa: E402
from typing import Any, Dict, List, Optional, Sequence, Tuple        # noqa: E402

PRODUCER = "analog_incremental_decimator"

#: Refusals, by name.
NO_WINDOW = "incremental_no_conversion_window"
NO_BITS = "incremental_no_bitstream"
SHORT_RECORD = "incremental_record_shorter_than_one_window"
BAD_ORDER = "incremental_unsupported_order"
BAD_DELAY = "incremental_negative_feedback_delay"
BAD_TOPOLOGY = "incremental_unsupported_loop_topology"
BAD_STATE_EQUATIONS = "incremental_invalid_state_equations"
BAD_DECISION = "incremental_invalid_decision_code"


def validate_loop_model(model: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the decoder's canonical state model, independent of IR names."""
    try:
        order = len(model["input_vector"])
        state_weights(1, model["transition"], model["input_vector"], model["feedback_vector"],
                      model["feedback_delay_clocks"])
        levels = model["quantizer_levels"]
        if (not isinstance(levels, list) or len(levels) < 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) for x in levels)
                or levels != sorted(set(levels))
                or len(model["feedforward_weights"]) != order
                or not all(math.isfinite(x) for x in [*model["feedforward_weights"],
                    model["input_feedforward"], model["feedback_compensation"]])):
            raise ValueError(BAD_STATE_EQUATIONS)
        encoding = model.get("decision_encoding")
        thresholds = model.get("quantizer_thresholds")
        if thresholds is not None and (len(thresholds) != len(levels)-1
                or any(not math.isfinite(x) for x in thresholds) or thresholds != sorted(set(thresholds))):
            raise ValueError(BAD_STATE_EQUATIONS)
        if encoding is not None:
            nodes, codes = encoding["output_nodes"], encoding["codes"]
            if (not isinstance(nodes, list) or not nodes or len(set(nodes)) != len(nodes)
                    or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:#/$-]*", node) for node in nodes)
                    or len(encoding["threshold_fractions"]) != len(nodes)
                    or any(not math.isfinite(x) or not 0 < x < 1 for x in encoding["threshold_fractions"])
                    or len({tuple(code) for code, value in codes}) != len(codes)
                    or {value for code, value in codes} != set(levels)
                    or any(len(code) != len(nodes) or any(bit not in (0, 1) for bit in code)
                           for code, value in codes)):
                raise ValueError(BAD_DECISION)
        elif levels != [-1., 1.]:
            raise ValueError(BAD_DECISION + ": multilevel outputs require a declared codebook")
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(BAD_STATE_EQUATIONS) from exc
    return model


def decision_value(voltages: Sequence[float], thresholds: Sequence[float],
                   codes: Sequence[Tuple[Sequence[int], float]]) -> Tuple[float, float]:
    """Map declared output codes to DAC decision levels, retaining margin.

    The codebook is supplied by the loop declaration. It may describe any
    finite level alphabet using one or several comparator/latch outputs.
    An undeclared or electrically ambiguous code is refused, never sliced
    down to a fabricated +1/-1 decision.
    """
    if (not voltages or len(voltages) != len(thresholds)
            or not all(math.isfinite(x) for x in [*voltages, *thresholds])):
        raise ValueError(BAD_DECISION)
    pattern = tuple(int(v > t) for v, t in zip(voltages, thresholds))
    margin = min(abs(v - t) for v, t in zip(voltages, thresholds))
    found = [level for code, level in codes if tuple(code) == pattern]
    if (margin <= 0 or len(found) != 1 or isinstance(found[0], bool)
            or not isinstance(found[0], (int, float)) or not math.isfinite(found[0])):
        raise ValueError(BAD_DECISION)
    return float(found[0]), margin


def state_weights(window: int, transition: Sequence[Sequence[float]],
                  input_vector: Sequence[float], feedback_vector: Sequence[float],
                  feedback_delay: int = 0) -> Tuple[List[float], List[float]]:
    """Terminal-state impulse weights for x_next = A*x + B*u + G*d.

    All rows update from the OLD state, and d[n] = decision[n-D]. The last
    declared state is the bounded residual. Its input response normalises
    the decode; minus its decision response weights each decision. No
    topology, coefficient equality, or quantiser level count is assumed.
    """
    size = len(input_vector)
    vectors = [*transition, input_vector, feedback_vector]
    if (not isinstance(window, int) or window < 1 or not size
            or len(transition) != size or len(feedback_vector) != size
            or not isinstance(feedback_delay, int) or feedback_delay < 0
            or any(len(row) != size or any(isinstance(x, bool) or
                not isinstance(x, (int, float)) or not math.isfinite(x) for x in row)
                for row in vectors)):
        raise ValueError(BAD_STATE_EQUATIONS)
    response = [0.] * (size - 1) + [1.]
    wu, wv = [0.] * window, [0.] * window
    for k in range(window - 1, -1, -1):
        wu[k] = sum(x * y for x, y in zip(response, input_vector))
        if k >= feedback_delay:
            wv[k - feedback_delay] = -sum(x * y for x, y in zip(response, feedback_vector))
        response = [sum(response[i] * transition[i][j] for i in range(size))
                    for j in range(size)]
    if not all(math.isfinite(x) for x in wu + wv):
        raise ValueError(BAD_STATE_EQUATIONS)
    return wu, wv


def loop_topology(value: str) -> str:
    """Validate a declared recurrence; never infer topology from decisions."""
    if not isinstance(value, str) or value.lower() not in ("cifb", "ciff"):
        raise ValueError(f"{BAD_TOPOLOGY}: {value!r}")
    return value.lower()

#: The conversion modes this file distinguishes. A free-running converter keeps
#: the FFT instrument; only the incremental class is decimated here.
MODE_INCREMENTAL = "incremental"
MODE_FREE_RUNNING = "free_running"


def _impulse_response(window: int, order: int, at_dac: bool,
                      coeff: float, feedback_delay: int = 0,
                      topology: str = "cifb") -> List[float]:
    """The final integrator's response to a unit impulse injected at ONE node.

    `at_dac=False` injects at the INPUT, which reaches only the first
    integrator. `at_dac=True` injects at the DAC, which in a CIFB reaches
    EVERY integrator. CIFF injects at stage 1 only.

    `feedback_delay` is the number of clocks between a decision being made and
    its charge reaching the summing nodes. A loop that latches the decision and
    presents it to the DAC on the NEXT phase realises 1; a loop that transfers
    it in the same phase realises 0. It shifts the DAC impulse and NOTHING
    else — the input path has no latch to delay it.
    """
    out: List[float] = []
    for k in range(window):
        state = [0.0] * order
        for n in range(window):
            e = 1.0 if n == k else 0.0
            d = (1.0 if (n - feedback_delay) == k else 0.0) if at_dac else 0.0
            u = 0.0 if at_dac else e
            # last stage first, so each stage integrates the PREVIOUS stage's
            # value before it is updated — the one-clock delay a CIFB has.
            for s in range(order - 1, 0, -1):
                state[s] += coeff * (state[s - 1] - (d if topology == "cifb" else 0.0))
            state[0] += coeff * (u - d)
        out.append(state[order - 1])
    return out


def input_weights(window: int, order: int = 2, coeff: float = 0.25,
                  topology: str = "cifb"
                  ) -> List[float]:
    """The INPUT's response — the NORMALISER, and not the bit weights."""
    topology = loop_topology(topology)
    # CIFF's input and DAC share the stage-1 path. The product of all stage
    # gains cancels, including unequal gains: use unit-gain CoI_L weights.
    return _impulse_response(window, order, False,
                             1.0 if topology == "ciff" else coeff)


def matched_weights(window: int, order: int = 2, coeff: float = 0.25,
                    feedback_delay: int = 0, topology: str = "cifb") -> List[float]:
    """The BIT weights the recurrence implies — the DAC's response, not the
    input's.

    CORRECTED (R-0915-70, second pass), and the correction is worth 7.4 bits.
    The first version injected the impulse at the INPUT and took the triangular
    `N-1-k` response. **The bits do not enter at the input.** In a CIFB the DAC
    feeds EVERY integrator — `a1*d` into the first, `a2*d` into the second — so
    the bit-to-output response carries a FLAT term the input's does not:

        input -> output    a1*a2*(N-1-k)
        bit   -> output  -(a1*a2*(N-1-k) + a2)

    Decoding the bits with the INPUT's weights drops that flat `a2*sum(d)`
    term: a signal-dependent error of order `a2*N`. MEASURED on a
    pure-arithmetic ideal CIFB2 — no simulator — scored by ABSOLUTE error
    against the true input over 512 held levels:

        DAC-injected weights    gain 0.99986   rms error   1.60 LSB   14.315 bit
        input-injected weights  gain 0.96898   rms error 263.53 LSB    6.953 bit

    **7.4 bits, and a 3 % gain error.** The input weights give a SMALL residual
    about their own WRONG line, which is exactly why the mistake survived a
    residual-only check: only comparing against the true input exposes it.

    Still derived, not typed — the response is computed by running the cascade,
    from the right injection point.

    `feedback_delay` — MEASURED, and it is NOT a second 7-bit correction. On a
    bitstream that is already fixed the two weight sets differ only by a
    one-sample shift of the flat DAC term, and that is far below the residual:
    the same two real records read 5.693 / 5.685 bit (an ideal-element SPICE
    harness) and 4.173 / 4.172 bit (a real corner) under delay 0 and delay 1
    weights. What the delay DOES cost is 2.0 bit in the LOOP — an incremental
    converter throws its last decision's feedback away at the reset — and that
    is a topology property, not a decode this function can undo. The parameter
    is here so a loop that declares a delayed DAC is decoded by the recurrence
    it actually realises, not so a number can be improved by choosing it.

    `coeff` is the per-stage coefficient. It cancels in the normalised decode
    only while every stage shares it: the flat term carries `a2` where the
    triangular term carries `a1*a2`, so a cascade with UNEQUAL coefficients
    would need them separately. Every entry this file is reached from declares
    one coefficient per stage from a single derivation, so one value is the
    honest CIFB signature; an unequal-coefficient CIFB cascade must extend
    this, not pass the first one. For `topology="ciff"`, the DAC reaches only
    stage 1 and all gains cancel; the returned unit-gain CoI_L weights apply
    regardless of `coeff` or unequal physical stage gains.
    """
    topology = loop_topology(topology)
    # CIFF means DAC injection into stage 1 only. Its CoI_L kernel is
    # independent of loop gains; D shifts only the decision response.
    if not isinstance(window, int) or window < 1:
        raise ValueError(f"window must be a positive integer, got {window!r}")
    if not isinstance(order, int) or order < 1 or order > 4:
        raise ValueError(f"{BAD_ORDER}: order must be 1..4, got {order!r}")
    if not isinstance(feedback_delay, int) or feedback_delay < 0:
        raise ValueError(f"{BAD_DELAY}: feedback_delay must be a "
                         f"non-negative integer, got {feedback_delay!r}")
    return [-w for w in _impulse_response(window, order, True,
                                          1.0 if topology == "ciff" else coeff,
                                          feedback_delay, topology)]


def conversion_mode(spec: Any, topology: Any = None) -> str:
    """INCREMENTAL when the design's own declaration says so, else free-running.

    Read from the declaration, never guessed: L5's `converter_type` row (or the
    topology record's own), matched on the word the documents use.
    """
    def _texts(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield str(k)
                yield from _texts(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                yield from _texts(v)
        elif obj is not None:
            yield str(obj)
    for blob in (spec, topology):
        for t in _texts(blob):
            if "incremental" in t.lower():
                return MODE_INCREMENTAL
    return MODE_FREE_RUNNING


def decimate(bits: Sequence[float], window: int, order: int = 2,
             coeff: float = 0.25, feedback_delay: int = 0,
             topology: str = "cifb", loop_model: Optional[Dict[str, Any]] = None
             ) -> Tuple[Optional[List[float]], Dict[str, Any]]:
    """One decoded sample per conversion window, or (None, {"reason": ...}).

    `bits` are the sampled decisions, one per converter clock, already sliced
    so that `bits[0]` is the first clock AFTER a reset — the alignment is the
    caller's, because only the caller can see the deck's own reset card, and a
    window boundary put one clock wrong mixes two conversions.
    """
    if not bits:
        return None, {"reason": NO_BITS}
    if not isinstance(window, int) or window < 1:
        return None, {"reason": NO_WINDOW}
    if len(bits) < window:
        return None, {"reason": SHORT_RECORD, "clocks": len(bits),
                      "window": window}
    try:
        topology = loop_topology(topology)
        if loop_model is not None:
            model = validate_loop_model(loop_model)
            wn, w = state_weights(window, model["transition"], model["input_vector"],
                                  model["feedback_vector"], model["feedback_delay_clocks"])
            if any(float(value) not in model["quantizer_levels"] for value in bits):
                return None, {"reason": BAD_DECISION}
            order = len(model["input_vector"])
            feedback_delay = model["feedback_delay_clocks"]
        else:
            w = matched_weights(window, order, coeff, feedback_delay, topology)
            wn = input_weights(window, order, coeff, topology)
    except ValueError as exc:
        return None, {"reason": str(exc)}
    # NORMALISE BY THE INPUT's weight sum, not the bits'. The two differ by the
    # flat DAC term, and using the bits' sum for both reintroduces the gain
    # error this correction removes.
    total = float(sum(wn))
    if not math.isfinite(total) or total == 0 or (loop_model is None and total < 0):
        return None, {"reason": BAD_ORDER, "weight_sum": total}
    n_win = len(bits) // window
    out = [sum(w[i] * float(bits[s * window + i]) for i in range(window)) / total
           for s in range(n_win)]
    return out, {"producer": PRODUCER, "windows": n_win, "window": window,
                 "order": order, "coeff": coeff,
                 "loop_topology": topology,
                 "feedback_delay_clocks": feedback_delay,
                 "weight_sum": total,
                 "weights_head": w[:3], "weights_tail": w[-3:],
                 # the LSB count the loop can resolve: the input weight sum divided
           # by the per-stage coefficient product, which is what the
           # normalisation leaves. log2 of it is the theoretical ceiling.
           "quantisation_bits": (None if loop_model is not None else
                math.log2(total / (1.0 if topology == "ciff" else coeff ** order))),
                 "rule": "matched_decimation_from_declared_state_equations" if loop_model is not None
                         else "matched_decimation_from_the_loop_recurrence"}


# ── the DECLARATION that travels on the deck ───────────────────────────────
#
# WHY THE DECK AND NOT THE SPEC. The decode has to match the loop that RAN.
# `analog_adc_enob_corner_check` already reads the tone, the sample clock and
# the band off the corner deck for exactly that reason — "a spec `fclk` the
# deck did not honour would put the band edge somewhere the spectrum never
# was" — and a window, an order or a feedback delay read from a document the
# deck did not honour is the same error one metric further along. So the
# producer that renders the deck stamps what it built, and the consumer reads
# it back from the deck. `stamp` and `read_stamp` are inverses and live
# together here so the two sides cannot drift.
STAMP_PREFIX = f"* {PRODUCER}:"

_STAMP_RE = re.compile(
    r"(?im)^\s*\*\s*" + re.escape(PRODUCER) + r"\s*:\s*(.*)$")
# Retain present-empty values so reserved metadata cannot become an absent
# legacy field before its existing validator sees it.
_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s]*)")

#: The stamp's fields, and the type each is read back as. A field missing from
#: a stamp is a REFUSAL, never a default: a decode that quietly assumed an
#: order or a window would be the typed closed form this module exists to
#: avoid, one level up.
STAMP_FIELDS = {"mode": str, "window_clocks": int, "order": int,
                "coeff": float, "feedback_delay_clocks": int}

NO_STAMP = "deck_carries_no_incremental_decode_declaration"
BAD_STAMP = "incremental_decode_declaration_incomplete"


def stamp(mode: str, window_clocks: int, order: int, coeff: float,
          feedback_delay_clocks: int, topology: str = "cifb",
          loop_model: Optional[Dict[str, Any]] = None) -> str:
    """The one line a producer writes into a deck so a consumer can decode it.

    A SPICE comment, so it changes nothing the simulator does."""
    topology = loop_topology(topology)
    # The original stamp format declares the CIFB recurrence. Preserve its
    # bytes for existing decks; CIFF must explicitly travel with the deck.
    suffix = " loop_topology=ciff" if topology == "ciff" else ""
    if loop_model is not None:
        payload = json.dumps(validate_loop_model(loop_model), separators=(",", ":"), allow_nan=False)
        suffix += " loop_model=" + base64.urlsafe_b64encode(payload.encode()).decode()
    return (f"{STAMP_PREFIX} mode={mode} window_clocks={int(window_clocks)} "
            f"order={int(order)} coeff={float(coeff):.6g} "
            f"feedback_delay_clocks={int(feedback_delay_clocks)}{suffix}")


def read_stamp(deck_text: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """`(declaration, detail)` — the decode this deck declares, or a named
    refusal. Never a default and never a guess."""
    m = _STAMP_RE.search(deck_text or "")
    if not m:
        return None, {"reason": NO_STAMP}
    kv = dict(_KV_RE.findall(m.group(1)))
    out: Dict[str, Any] = {}
    missing: List[str] = []
    for name, caster in STAMP_FIELDS.items():
        raw = kv.get(name)
        if raw is None:
            missing.append(name)
            continue
        try:
            out[name] = caster(raw)
        except (TypeError, ValueError):
            missing.append(name)
    if missing:
        return None, {"reason": BAD_STAMP, "missing_or_unreadable": missing,
                      "line": m.group(0).strip()}
    if "loop_topology" in kv:
        try:
            out["loop_topology"] = loop_topology(kv["loop_topology"])
        except ValueError as exc:
            return None, {"reason": str(exc)}
    if "loop_model" in kv:
        try:
            out["loop_model"] = validate_loop_model(json.loads(base64.b64decode(
                kv["loop_model"], altchars=b"-_", validate=True)))
            if (len(out["loop_model"]["input_vector"]) != out["order"] or
                    out["loop_model"]["feedback_delay_clocks"] != out["feedback_delay_clocks"]):
                raise ValueError(BAD_STATE_EQUATIONS + ": inconsistent stamp order/delay")
        except (ValueError, TypeError, UnicodeError) as exc:
            return None, {"reason": BAD_STATE_EQUATIONS, "detail": str(exc)}
    if "reset_release_node" in kv:
        node = kv["reset_release_node"]
        try:
            active = int(kv["active_transfers"])
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:$-]*", node) or active != out["window_clocks"] - 1 or active < 1:
                raise ValueError
        except (KeyError, ValueError):
            return None, {"reason": BAD_STAMP, "detail": "invalid reset-release timing"}
        out.update(reset_release_node=node, active_transfers=active)
    return out, {"line": m.group(0).strip()}


# ── the RESET-ALIGNED sample of the decisions ──────────────────────────────
NO_CLOCK_CARD = "sample_clock_card_not_readable_from_the_deck"
NO_SAMPLES_IN_RECORD = "record_holds_no_sample_at_the_first_clock_instant"


def sample_decisions(times: Sequence[float], vals: Sequence[float],
                     first_clock_s: float, period_s: float, threshold: float,
                     settle_fraction: float = 0.9,
                     encoding: Optional[Dict[str, Any]] = None,
                     reset_release_values: Optional[Sequence[float]] = None,
                     window_clocks: Optional[int] = None
                     ) -> Tuple[List[float], Dict[str, Any]]:
    """The decision on every clock of the record, as +1 / -1, reset-aligned.

    For controller decks, the observed rising edge of its declared active-low
    reset is the complete phi1 release. Slot zero is the decision for that
    first transfer. Each reset period has N-1 updates; reset-only output has
    no weight. The raw source delay is used only for older decks without this
    controller declaration.
    """
    out: List[float] = []
    if not times or period_s <= 0:
        return out, {"reason": NO_CLOCK_CARD}
    t_end = times[-1]
    n = 0
    idx = 0
    n_rows = len(times)
    wants = None
    aligned_start = first_clock_s
    if reset_release_values is not None:
        if len(reset_release_values) != n_rows or not isinstance(window_clocks, int) or window_clocks < 2:
            return [], {"reason": "incremental_reset_release_record_invalid"}
        releases = [i for i in range(1, n_rows)
                    if reset_release_values[i-1] <= threshold < reset_release_values[i]]
        wants = []
        if releases:
            aligned_start = times[releases[0]]
        for release in releases:
            start = times[release]
            last = start + (window_clocks - 2 + settle_fraction) * period_s
            if last > t_end:
                break
            # Reject a reset assertion inside the proposed update interval.
            end = release
            while end + 1 < n_rows and times[end + 1] <= last:
                end += 1
            if any(v <= threshold for v in reset_release_values[release:end+1]):
                return [], {"reason": "incremental_reset_interrupts_conversion", "release_s": start}
            wants.extend(start + (slot + settle_fraction) * period_s
                         for slot in range(window_clocks - 1))
    while True:
        if wants is not None:
            if n == len(wants):
                break
            want = wants[n]
        else:
            want = first_clock_s + (n + settle_fraction) * period_s
        if want > t_end:
            break
        while idx + 1 < n_rows and times[idx + 1] <= want:
            idx += 1
        if encoding is None:
            out.append(1.0 if float(vals[idx]) > threshold else -1.0)
        else:
            try:
                value, _margin = decision_value(vals[idx],
                    [2 * threshold * x for x in encoding["threshold_fractions"]], encoding["codes"])
            except ValueError as exc:
                return [], {"reason": str(exc), "clock": n}
            out.append(value)
        n += 1
    if not out:
        return out, {"reason": NO_SAMPLES_IN_RECORD,
                     "first_clock_s": first_clock_s, "record_end_s": t_end}
    return out, {"clocks": len(out), "first_clock_s": aligned_start,
                 "period_s": period_s, "threshold_v": threshold,
                 "settle_fraction": settle_fraction,
                 "alignment": "observed_phi1_reset_release" if wants is not None else "legacy_clock_delay",
                 "active_transfers": window_clocks - 1 if wants is not None else None}
