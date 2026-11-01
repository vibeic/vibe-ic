#!/usr/bin/env python3
"""analog_resolution_stimulus.py — the A4 corner deck's RESOLUTION stimulus.

WHY THIS MODULE EXISTS (vibe-ic#2188, MEASURED)
===============================================
`analog_adc_enob_corner_check` grades the one figure of merit a data converter
is defined by — its effective resolution — and it states, per corner and by
name, the two properties a deck must have before that number can exist:

    no_transient_dump: the deck writes no `wrdata` file
    stimulus_not_a_coherent_tone: the deck drives the converter input from a
        DC source, and SNDR is a signal bin against everything else

Measured on the live tip (base ``e2b3c08170b5``) against a real front-door run
of a second-order incremental modulator: nine corners really simulated, every
one of them ``UNMEASURED`` with BOTH reasons, ``blocks_graded 0``. Nothing in
the A-track emitted a deck either property could be read off — not for that
design, and not for any design, because no producer ever wrote a `wrdata` into
a corner deck and no testbench drove a converter input from anything but a DC
level. The consumer was honest and the capability did not exist.

This module is that capability. It is a pure text-in / text-out transform over
ONE corner deck, so it is testable without a simulator, and it is wired into
`analog_real_corner_sweep` at the single point where a corner deck is rendered.

WHAT IT CHANGES IN A DECK, AND ONLY THIS
========================================
For a block whose bound spec declares an ENOB (or SNDR) target:

  1. the DC source on the block's DECLARED signal-input port becomes a SIN
     source CENTRED ON THE SAME DC LEVEL, so every measurement the delivered
     deck already takes over that input keeps its expected value — a bitstream
     density that reads the input's fraction of the reference span reads the
     same fraction, because the mean of a symmetric tone is its offset;
  2. one `wrdata` of the block's own measured output node is added to the
     transient the deck already runs.

It does NOT lengthen the record, move a device, re-time a clock, or add an
analysis. The corner sweep runs exactly the simulations it already ran.

IT REFUSES BY NAME RATHER THAN GUESS
====================================
Every input above is read off the DESIGN — the deck the corner is about to run
and the topology IR that block was emitted from — never off a table here. When
one of them is not there the transform is not applied and the record says which
one, with the arithmetic, so the reader is told what to change:

    signal_input_port_not_declared        the IR names no signal-chain input
    signal_input_source_absent            no top-level DC source drives it
    output_node_not_measured              the deck measures no top-level node
    output_node_ambiguous                 it measures more than one
    sample_clock_not_identifiable         no single top-level pulse source
    no_transient                          the deck runs no `tran`
    record_too_short_for_an_in_band_tone  the arithmetic below does not close

THE ARITHMETIC, AND WHY THE TONE SITS WHERE IT DOES
===================================================
The record holds ``N = tstop * fclk`` converter samples. An oversampled
converter is graded over its SIGNAL BAND, ``fclk / (2 * OSR)``, which is the
first ``N / (2 * OSR)`` bins of the record's spectrum — that is what OSR MEANS,
and a resolution taken over the whole Nyquist span of a 1-bit modulator output
measures its shaped out-of-band noise instead of its resolution.

The tone is placed at an ODD bin at most a THIRD of the way to the band edge.
Odd, so the bins either side of it are not its own leakage. A third, so the
second and third harmonics of the tone land INSIDE the graded band: SNDR is
signal against noise AND DISTORTION, and a tone parked at the band edge pushes
every harmonic out of the band and quietly reports an SNR as if it were an
SNDR. That is the flattering answer, so it is the one this file refuses to
give.

Hence the floor: the band must hold ``3 x _MIN_SIGNAL_CYCLES`` bins, i.e.

    N >= 2 * OSR * HARMONICS_IN_BAND * (the first ODD bin at or above
                                        _MIN_SIGNAL_CYCLES)

with ``_MIN_SIGNAL_CYCLES`` imported from the consumer that will do the fit, so
the producer's floor and the consumer's refusal cannot drift apart. The bin is
rounded UP to odd because an even one is never emitted, and a floor that
ignored that would publish a record length that is still refused when a reader
lengthens the deck to exactly it.

chip-AGNOSTIC. No design, block, PDK, node or vendor literal appears here; the
only constants are the ones named above and the amplitude margin.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import math
import re
from typing import Any, Dict, List, Optional, Tuple

# ONE definition of "how few whole cycles is too few". The consumer refuses
# below it; this producer must not emit below it either, and importing rather
# than restating is what keeps the two from drifting.
import analog_incremental_decimator as _inc
from analog_adc_enob_corner_check import _MIN_SIGNAL_CYCLES
import instrument_calibration as _instrument_calibration  # noqa: E402  R-0915-86(3)

PRODUCER = "analog_resolution_stimulus"

#: The tone's harmonics that must stay inside the graded band for the fit to be
#: an SNDR rather than an SNR. See the module note.
HARMONICS_IN_BAND = 3

#: How close the tone is allowed to come to the nearest OTHER DC level the deck
#: drives on the device under test. Below 1.0 by construction: at 1.0 the tone
#: would touch the reference (or the rail) at its peak, and a converter driven
#: to its reference clips, which is a distortion this file would have authored
#: rather than measured.
AMPLITUDE_MARGIN = 0.9

#: The `wrdata` column the consumer reads is the FIRST value column, so exactly
#: one vector is exported. More would still be readable, but the extra columns
#: would be written for nobody.
_EXPORTED_VECTORS = 1

# ── deck grammar ───────────────────────────────────────────────────────────
_SUBCKT_RE = re.compile(r"(?i)^\s*\.subckt\b")
_ENDS_RE = re.compile(r"(?i)^\s*\.ends\b")
_CONTROL_RE = re.compile(r"(?i)^\s*\.control\b")
_ENDC_RE = re.compile(r"(?i)^\s*\.endc\b")
_COMMENT_RE = re.compile(r"^\s*[*;]")
#: An independent VOLTAGE source card: `v<name> <n+> <n-> <value...>`.
_VSRC_RE = re.compile(r"(?i)^\s*(v\w*)\s+(\S+)\s+(\S+)\s+(.+?)\s*$")
#: A subcircuit INSTANCE card: `x<name> <nets...> <subckt>`.
_XINST_RE = re.compile(r"(?i)^\s*(x\w*)\s+(.+?)\s*$")
#: `pulse(v1 v2 td tr tf pw per)` — the last field is the period.
_PULSE_RE = re.compile(r"(?i)^\s*pulse\s*\(([^)]*)\)")
#: A plain DC level: a bare SPICE scalar, optionally after a `dc` keyword.
_DC_RE = re.compile(r"(?i)^\s*(?:dc\s+)?([0-9.eE+-]+[a-zA-Z]*)\s*$")
#: `tran <step> <stop>` inside `.control` (or a top-level `.tran`).
_TRAN_RE = re.compile(r"(?i)^\s*\.?tran\s+(\S+)\s+(\S+)")
#: `meas tran <name> <func> v(<node>)` — the deck saying what it measures.
_MEAS_RE = re.compile(r"(?i)^\s*meas\s+tran\s+\S+\s+\w+\s+v\(\s*([^)\s]+)\s*\)")
_WRDATA_RE = re.compile(r"(?im)^\s*wrdata\s+\S+\s+")

_SUFFIX = {"meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9,
           "p": 1e-12, "f": 1e-15, "g": 1e9, "t": 1e12}


def si(tok: str) -> Optional[float]:
    """A SPICE scalar with an optional engineering suffix, in SI units."""
    m = re.match(r"^([0-9.eE+-]+)\s*([a-zA-Z]*)$", str(tok).strip())
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    for key in ("meg", "k", "m", "u", "n", "p", "f", "g", "t"):
        if suffix.startswith(key):
            return value * _SUFFIX[key]
    return value


def _num(value: float) -> str:
    """A SPICE-safe literal: no engineering suffix, so it cannot be re-read as
    one (`1m` is a milli, and a frequency written that way would be silently a
    million times wrong)."""
    return f"{value:.10g}"


# ── the record the tone needs ──────────────────────────────────────────────
def coherent_record_samples(osr: float,
                            window_clocks: Optional[float] = None
                            ) -> Dict[str, Any]:
    """The SHORTEST record, in converter samples, over which this file will
    emit a coherent in-band tone at oversampling ratio `osr`.

    THE ONE DEFINITION of that floor. `plan` refuses below it, and whatever
    SIZES the record has to be able to read it — a producer that derives a
    record length from its own restatement of this arithmetic and a consumer
    that refuses against this one is the shape vibe-ic#2200 reports: a record
    of 512 samples where the tone needed 13824, and no way for the second
    number to reach the first. So the number is exported rather than inlined
    twice.

    `samples` is the ACTUAL threshold, not a convenient lower bound: the tone
    bin is always ODD, so a reader who lengthens a record to the even closed
    form gets the same refusal back (measured at OSR 256: 13824 works, 12288
    does not — vibe-ic#2188).

    Raises `ValueError` when `osr` is not a usable ratio, because "no record
    length satisfies this" is the honest answer to an undeclared signal band
    and a silently-assumed 1 grades a modulator over the noise it shaped out
    on purpose.
    """
    if isinstance(osr, bool) or not isinstance(osr, (int, float)):
        raise ValueError(f"osr must be a number, got {osr!r}")
    osr = float(osr)
    if not math.isfinite(osr) or osr < 1.0:
        raise ValueError(f"osr must be finite and at least 1, got {osr!r}")
    min_bin = _MIN_SIGNAL_CYCLES + (1 - _MIN_SIGNAL_CYCLES % 2)
    base = {"osr": osr, "min_tone_bin": min_bin,
            "min_signal_cycles": _MIN_SIGNAL_CYCLES,
            "harmonics_in_band": HARMONICS_IN_BAND}
    # AN INCREMENTAL CONVERTER IS GRADED IN THE DECODED DOMAIN, so its record
    # is counted in CONVERSION WINDOWS and not in raw samples: the tone has to
    # be coherent over the windows that are decoded, one of them is dropped
    # because the counter's power-up state is not a declared reset, and the
    # cycle count has to be coprime with what remains (see `incremental_tone`
    # — F167: without the coprimality the instrument read the WORST tone
    # placement as 2.8 bit the BEST). An entry that publishes a conversion
    # window IS that class; one that does not takes the path below, unchanged.
    if isinstance(window_clocks, (int, float)) and not isinstance(
            window_clocks, bool) and window_clocks >= 1:
        windows = incremental_record_windows()
        tone = incremental_tone(windows)
        base.update({"samples": int(windows * int(window_clocks)),
                     "window_clocks": int(window_clocks),
                     "conversion_windows": windows,
                     "graded_windows": tone["graded_windows"],
                     "cycles": tone["cycles"],
                     "rule": "coherent_over_the_decoded_conversion_windows"})
        return base
    base["samples"] = int(math.ceil(2.0 * osr * HARMONICS_IN_BAND * min_bin))
    base["rule"] = "coherent_over_the_raw_record"
    return base


# ── what the DESIGN declares ───────────────────────────────────────────────
def resolution_axis(spec: Any) -> Optional[Dict[str, Any]]:
    """`{"axis", "enob_bits", "osr"}` when the block's bound spec declares an
    effective-resolution target, else None (not a resolution-graded converter).

    The ENOB/SNDR pair and the ENOB<->SNDR relation are read the same way the
    consumer reads them, so a block this producer acts on is exactly a block
    that consumer grades."""
    if not isinstance(spec, dict):
        return None
    rows = spec.get("specs")
    if not isinstance(rows, list):
        return None
    enob: Optional[float] = None
    sndr: Optional[float] = None
    osr: Optional[float] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip().lower()
        value = row.get("target")
        if not (isinstance(value, (int, float)) and math.isfinite(value)):
            value = row.get("min")
        if not (isinstance(value, (int, float)) and math.isfinite(value)):
            continue
        if name == "enob":
            enob = float(value)
        elif name in ("sndr", "sndr_db", "snr", "snr_db"):
            sndr = float(value)
        elif name == "osr":
            osr = float(value)
    if enob is not None:
        axis = "enob"
    elif sndr is not None:
        axis = "sndr"
        enob = (sndr - 1.76) / 6.02
    else:
        return None
    return {"axis": axis, "enob_bits": enob,
            "osr": (osr if (osr and osr >= 1.0) else 1.0),
            "osr_declared": osr is not None}


def signal_input_port(topology: Any) -> Tuple[Optional[str], Optional[str]]:
    """`(port, why_not)` — the port the DESIGN declares its signal enters on.

    Read from the topology IR, in the order a declaration binds:

      1. `testbench.signal_input_port`, when a topology entry states it
         outright. Nothing in the shipped library needs to today; the key
         exists so a converter whose input is NOT the head of a signal chain
         (a SAR's sampling node, say) has somewhere to say so without this
         file growing a table of block types.
      2. `stage_expansion.chain[0]`, the head of the block's own signal chain,
         when it is one of the block's declared ports.

    Never guessed. Two reference sources and a supply are DC-driven ports of a
    converter too, and picking the wrong one would make a tone out of the
    reference — which would not fail, it would silently measure nonsense."""
    if not isinstance(topology, dict):
        return None, "no topology IR beside the block"
    tb = topology.get("testbench")
    if isinstance(tb, dict):
        declared = tb.get("signal_input_port")
        if isinstance(declared, str) and declared.strip():
            return declared.strip(), None
    ports = [p for p in (topology.get("ports") or []) if isinstance(p, str)]
    chain = ((topology.get("stage_expansion") or {}).get("chain")
             if isinstance(topology.get("stage_expansion"), dict) else None)
    if isinstance(chain, list) and chain and isinstance(chain[0], str):
        if chain[0] in ports:
            return chain[0], None
        return None, (
            f"the topology IR's signal chain starts at {chain[0]!r}, which is "
            f"not one of the block's declared ports ({', '.join(ports)}); a "
            f"tone can only be driven onto a port")
    return None, (
        "the topology IR declares neither `testbench.signal_input_port` nor a "
        "`stage_expansion.chain`, so nothing in the design says which port "
        "carries the signal this converter converts")


# ── what the DECK says about itself ────────────────────────────────────────
def deck_facts(deck_text: str) -> Dict[str, Any]:
    """Everything this transform needs, read off the corner deck's TOP LEVEL.

    Cards inside a `.subckt` belong to the device under test and are not this
    step's to read: the same net name can exist in every instance."""
    sources: List[Dict[str, Any]] = []
    instance_nets: List[str] = []
    measured: List[str] = []
    tran: Optional[Dict[str, Any]] = None
    depth = 0
    in_control = False
    for index, line in enumerate(deck_text.splitlines()):
        if _COMMENT_RE.match(line):
            continue
        if _SUBCKT_RE.match(line):
            depth += 1
            continue
        if _ENDS_RE.match(line):
            depth = max(0, depth - 1)
            continue
        if _CONTROL_RE.match(line):
            in_control = True
            continue
        if _ENDC_RE.match(line):
            in_control = False
            continue
        if depth:
            continue
        if in_control:
            m = _MEAS_RE.match(line)
            if m and "." not in m.group(1):
                # A HIERARCHICAL node (`xdut.vint`) is an internal probe, not
                # the block's declared output. Only a top-level net can be the
                # thing the block presents to the world.
                measured.append(m.group(1))
            mt = _TRAN_RE.match(line)
            if mt and tran is None:
                tran = {"line": index, "step_s": si(mt.group(1)),
                        "stop_s": si(mt.group(2))}
            continue
        mv = _VSRC_RE.match(line)
        if mv:
            body = mv.group(4)
            mp = _PULSE_RE.match(body)
            dc = _DC_RE.match(body)
            sources.append({
                "line": index, "name": mv.group(1), "pos": mv.group(2),
                "neg": mv.group(3), "body": body,
                "dc_v": (si(dc.group(1)) if dc else None),
                "period_s": (si(mp.group(1).split()[-1])
                             if mp and mp.group(1).split() else None),
            })
            continue
        mx = _XINST_RE.match(line)
        if mx:
            instance_nets.extend(mx.group(2).split()[:-1])
        mt = _TRAN_RE.match(line)
        if mt and tran is None:
            tran = {"line": index, "step_s": si(mt.group(1)),
                    "stop_s": si(mt.group(2))}
    return {"sources": sources, "instance_nets": instance_nets,
            "measured_nodes": measured, "tran": tran,
            "has_wrdata": bool(_WRDATA_RE.search(deck_text))}


def _output_node(facts: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """The converter's output, as the DECK ITSELF declares it: the top-level
    node the deck's own transient measurements are taken on. The design already
    said which net carries its answer by measuring it; this reads that back
    instead of naming a net here."""
    distinct = sorted(set(facts["measured_nodes"]))
    if not distinct:
        return None, ("the deck takes no `meas tran` over a top-level node, so "
                      "it never says which net carries this block's output")
    if len(distinct) > 1:
        return None, (
            f"the deck measures {len(distinct)} top-level nodes "
            f"({', '.join(distinct)}); exactly one is required to know which "
            f"net the resolution is a resolution OF")
    return distinct[0], None


def _sample_clock_hz(facts: Dict[str, Any]
                     ) -> Tuple[Optional[float], Optional[str]]:
    """The converter's sample rate, from the ONE top-level pulse source the
    deck drives the device under test with."""
    pulses = [s for s in facts["sources"]
              if s["period_s"] and s["pos"] in facts["instance_nets"]]
    if len(pulses) != 1:
        return None, (
            f"the deck drives the device under test from {len(pulses)} "
            f"top-level pulse source(s); exactly one is required to know the "
            f"rate this converter samples at")
    period = pulses[0]["period_s"]
    if not period or period <= 0:
        return None, (f"the clock source {pulses[0]['name']!r} declares a "
                      f"period of {period!r}, which is not a rate")
    return 1.0 / period, None


def _amplitude(facts: Dict[str, Any], node: str, dc_v: float
               ) -> Tuple[Optional[float], Optional[str]]:
    """The largest tone amplitude that keeps the input strictly between the
    NEAREST OTHER DC levels the deck drives on the device under test, less
    `AMPLITUDE_MARGIN`.

    Those levels are the block's own references and rails — the deck put them
    there — so a tone that never reaches one can never overdrive the converter
    past its reference nor past its supply, on any design, without this file
    knowing which of them is which."""
    others = [s["dc_v"] for s in facts["sources"]
              if s["dc_v"] is not None and s["pos"] != node
              and s["pos"] in facts["instance_nets"]]
    gaps = [abs(level - dc_v) for level in others if abs(level - dc_v) > 0]
    if not gaps:
        return None, (
            "the deck drives no other DC level on the device under test, so "
            "there is nothing here that bounds how far the input may swing "
            "before it overdrives the converter")
    amplitude = AMPLITUDE_MARGIN * min(gaps)
    if amplitude <= 0:
        return None, "the bounding DC level coincides with the input's own"
    return amplitude, None


# ── the transform ──────────────────────────────────────────────────────────
# ── the INCREMENTAL DECODE this deck's converter needs ─────────────────────
#
# WHY IT IS STAMPED HERE. This module already renders the one deck the ENOB
# gate reads, and it already holds both halves the decode needs — the spec
# (which declares the conversion mode) and the topology IR (which declares the
# window, the order, the coefficient and the loop's feedback delay). Nothing
# else in the flow sees both at the point the deck exists. The stamp is a
# SPICE comment, so the simulation is byte-for-byte the one that ran before.
#
# MEASURED, and this is why it is worth a stamp at all (lane icadc, F159/F161):
# reading an INCREMENTAL converter's bitstream with a free-running converter's
# FFT under-reads it, and decoding it with the INPUT's weights instead of the
# DAC's under-reads it by 7.4 bit. Both are decode errors; neither is visible
# in the deck unless the deck says which decode it needs.
_INC_NO_WINDOW = "incremental_conversion_window_not_declared"
_INC_NO_ORDER = "incremental_loop_order_not_declared"
_INC_NO_COEFF = "incremental_loop_coefficient_not_declared"
_INC_NO_DELAY = "incremental_feedback_delay_not_declared"
_INC_UNEQUAL_COEFF = "incremental_cascade_coefficients_unequal"

#: The IR constant a topology entry declares its loop's feedback delay in.
FEEDBACK_DELAY_CONSTANT = "feedback_delay_clocks"


def incremental_loop_adapter(topology: Any, *, decision_encoding=None) -> Optional[Dict[str, Any]]:
    """Map loop_declaration schema 1 to the shared decoder/stability model.

    Field names are bound to producer 061758e3e38455fb406ef9cc099b052882b78be7,
    docs/analog-ciff.md and analog_ciff.declaration(). A/input_vector/
    feedback_vector own the state equations, including optimized-zero paths.
    Schema 1 emits two levels; future multilevel measurement methods must
    supply their explicit output codebook via decision_encoding, not infer
    it from captured values or add guessed fields to the producer contract.
    """
    if not isinstance(topology, dict) or "loop_declaration" not in topology:
        return None
    raw = topology["loop_declaration"]
    try:
        order, delay, count = raw["order"], raw["D"], raw["quantizer_levels"]
        if (raw["schema"] != 1 or raw["family"] not in ("CIFF", "CIFB")
                or not isinstance(order, int) or isinstance(order, bool) or order < 1
                or not isinstance(delay, int) or isinstance(delay, bool) or delay not in (0, 1)
                or not isinstance(count, int) or isinstance(count, bool) or count < 2
                or any(len(raw[key]) != order for key in ("a", "b", "c", "state_nets", "input_vector", "feedback_vector"))
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                       for key in ("a", "b", "c") for x in raw[key])
                or any(x == 0 for x in raw["a"])
                or raw["feedback_vector"] != [-b for b in raw["b"]]
                or raw["dac_stages"] != [i+1 for i,b in enumerate(raw["b"]) if b]
                or not raw["dac_stages"] or len(set(raw["state_nets"])) != order):
            raise ValueError(_inc.BAD_STATE_EQUATIONS)
        normalization = raw["normalization"]
        levels, scale = normalization["dac_output_levels"], normalization["full_scale_over_reference"]
        if len(levels) != count or not math.isfinite(scale) or scale <= 0:
            raise ValueError(_inc.BAD_STATE_EQUATIONS)
        paths = raw["paths"]
        dac_paths = [path for path in paths if path["kind"] == "dac"]
        if (sorted(path["destination_stage"] for path in dac_paths) != raw["dac_stages"]
                or any(path["delay_clocks"] != delay or
                       path["gain"] != raw["feedback_vector"][path["destination_stage"]-1] or
                       path["destination"] != raw["state_nets"][path["destination_stage"]-1]
                       for path in dac_paths)):
            raise ValueError(_inc.BAD_STATE_EQUATIONS)
        k0_path = raw["k0_path"]
        if raw["k0"] and (delay != 1 or not k0_path or
                k0_path["delay_clocks"] != 1 or k0_path["gain"] != -raw["k0"]):
            raise ValueError(_inc.BAD_STATE_EQUATIONS)
        encoding = decision_encoding
        if encoding is None and count == 2:
            sources = {path["source"] for path in dac_paths}
            if len(sources) != 1:
                raise ValueError(_inc.BAD_DECISION)
            encoding = {"output_nodes": [next(iter(sources))],
                        "codes": [[[0], levels[0]], [[1], levels[1]]]}
        if encoding is not None:
            encoding = {"output_nodes": encoding["output_nodes"], "codes": encoding["codes"],
                        "threshold_fractions": encoding.get("threshold_fractions", [.5]*len(encoding["output_nodes"]))}
        model = {"transition": raw["A"], "input_vector": raw["input_vector"],
                 "feedback_vector": raw["feedback_vector"], "feedback_delay_clocks": delay,
                 "feedforward_weights": raw["c"], "input_feedforward": raw["c0"],
                 "feedback_compensation": raw["k0"], "quantizer_levels": levels,
                 "decision_encoding": encoding, "normalization": normalization,
                 "state_nets": raw["state_nets"],
                 "state_paths": [path for path in paths if path["kind"] in
                                 ("input", "integrator", "dac", "zero_feedback")],
                 "producer_schema": raw["schema"], "family": raw["family"]}
        return _inc.validate_loop_model(model)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(_inc.BAD_STATE_EQUATIONS) from exc


def incremental_decode(spec: Any, topology: Any, *, decision_encoding=None) -> Dict[str, Any]:
    """The decode declaration for this block, or a NAMED refusal.

    Always a dict; `declared` is the one field a caller must read. A block
    whose spec does not declare an incremental converter is not refused — it
    keeps the free-running instrument, which is right for it."""
    rec: Dict[str, Any] = {"declared": False}
    mode = _inc.conversion_mode(spec, topology)
    rec["mode"] = mode
    if mode != _inc.MODE_INCREMENTAL:
        rec["reason"] = "converter_is_not_declared_incremental"
        return rec
    if not isinstance(topology, dict):
        rec["reason"] = _INC_NO_WINDOW
        rec["detail"] = "no topology IR beside the block"
        return rec
    consts = topology.get("constants") or {}
    try:
        model = incremental_loop_adapter(topology, decision_encoding=decision_encoding)
    except ValueError as exc:
        rec["reason"] = str(exc)
        rec["loop_model_invalid"] = True
        return rec
    if model is not None:
        window = consts.get("window_clocks")
        if (not isinstance(window, (int, float)) or isinstance(window, bool)
                or not math.isfinite(window) or window < 1 or int(window) != window):
            rec["reason"] = _INC_NO_WINDOW
            return rec
        window = int(window)
        order, delay = len(model["input_vector"]), model["feedback_delay_clocks"]
        # Topology labels do not select the weights in this path: the
        # complete declared equations own the input and DAC impulses.
        rec.update({"declared": True, "window_clocks": window, "order": order,
                    "coeff": 1., "feedback_delay_clocks": delay, "loop_model": model})
        rec["stamp"] = _inc.stamp(mode, window, order, 1., delay, loop_model=model)
        return rec
    # Original A2/A3 records describe the CIFB recurrence. New topologies
    # declare constants.loop_topology; the existing topology prose is also
    # a declaration (and must not contradict the structured field).
    named = re.findall(r"\b(CIFF|CIFB)\b", str(topology.get("topology", "")), re.I)
    kinds = {value.lower() for value in named}
    if "loop_topology" in consts:
        kinds.add(str(consts["loop_topology"]).lower())
    try:
        kind = _inc.loop_topology(next(iter(kinds)) if len(kinds) == 1 else
                                  ("cifb" if not kinds else "conflicting_declarations"))
    except ValueError as exc:
        rec["reason"] = str(exc)
        return rec
    window = consts.get("window_clocks")
    if not isinstance(window, (int, float)) or int(window) < 1:
        rec["reason"] = _INC_NO_WINDOW
        rec["detail"] = (
            "the topology IR publishes no `constants.window_clocks`, so the "
            "deck cannot say how many clocks one conversion is and a decoder "
            "would have to assume it")
        return rec

    stage = topology.get("stage_expansion")
    stage = stage if isinstance(stage, dict) else {}
    order = stage.get("stages")
    if stage.get("count_from") != "order" or not isinstance(order, int):
        rec["reason"] = _INC_NO_ORDER
        rec["detail"] = (
            "the topology IR's signal cascade does not declare `count_from: "
            "\"order\"`, so the loop order the decode has to run is not "
            "stated by the design")
        return rec
    coeffs = [c for c in (stage.get("coefficients") or [])
              if isinstance(c, (int, float)) and not isinstance(c, bool)]
    if len(coeffs) != order or any(not math.isfinite(c) or c <= 0 for c in coeffs):
        rec["reason"] = _INC_NO_COEFF
        rec["detail"] = (f"the cascade declares {len(coeffs)} coefficient(s) "
                         f"for {order} stage(s)")
        return rec
    if kind == "cifb" and any(abs(c - coeffs[0]) > 1e-12 * max(1.0, abs(coeffs[0]))
           for c in coeffs):
        # NOT decoded on the first one. The flat DAC term carries `a2` where
        # the triangular term carries `a1*a2`, so unequal coefficients need
        # them separately and `analog_incremental_decimator` takes one.
        rec["reason"] = _INC_UNEQUAL_COEFF
        rec["detail"] = (f"coefficients {coeffs} differ; the matched decode "
                         f"takes one per-stage coefficient")
        return rec
    delay = consts.get(FEEDBACK_DELAY_CONSTANT)
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) \
            or int(delay) < 0:
        rec["reason"] = _INC_NO_DELAY
        rec["detail"] = (
            f"the topology IR publishes no `constants.{FEEDBACK_DELAY_CONSTANT}"
            f"`. A CIFB that LATCHES its decision and presents it to the DAC "
            f"on the next phase realises 1; one that transfers it in the same "
            f"phase realises 0. The decode has to run the recurrence the loop "
            f"realises, and a default would be a guess about the emitted "
            f"circuit")
        return rec

    rec.update({"declared": True, "window_clocks": int(window),
                "order": int(order), "coeff": float(coeffs[0]),
                "loop_topology": kind,
                "feedback_delay_clocks": int(delay)})
    rec["stamp"] = _inc.stamp(mode, int(window), int(order), float(coeffs[0]),
                              int(delay), kind)
    return rec



# ── the tone an INCREMENTAL converter can actually be graded at ────────────
#
# WHAT WAS WRONG, MEASURED (lane icadc, F167). The rule below the incremental
# branch picks `band_bins // HARMONICS_IN_BAND` — one third of the decoded
# Nyquist, BY CONSTRUCTION. At OSR 256 over a 13824-sample record that is bin
# 9 of 54 conversion windows: exactly ONE TONE CYCLE PER SIX WINDOWS, with
# `gcd(9, 54) = 9`.
#
# An incremental converter's decoded error is DETERMINISTIC and periodic with
# the tone. When the tone's period in conversion windows is a small integer,
# so is the error's, and the error becomes a component AT THE SIGNAL'S OWN
# FREQUENCY — which an SNDR removes as signal. Measured on a pure-arithmetic
# ideal CIFB2, same loop, same graded span of 48 decoded windows, tone bin
# swept: every bin from 2 to 15 reads 10.7 - 11.6 bit and bin 8 (= 48/6, the
# bin the rule picks) reads 13.37. Against the method-free truth — the decoded
# value against the input the loop actually saw, no spectrum anywhere — that
# same placement is the WORST of the set (rms 3.35e-4 where the others are
# 2.7e-4 to 3.0e-4, i.e. 10.54 bit). **The instrument read the worst placement
# as 2.8 bit the best.** That is a false green in a graded metric, and it is
# systematic: one third of a Nyquist is a simple rational of the decoded
# record for every OSR whose band edge is divisible by three.
#
# THE RULE THAT REPLACES IT. The tone is chosen in the DECODED domain, where
# the converter is actually graded: `c` whole cycles across `m` graded
# conversion windows, with
#
#     gcd(c, m) == 1     so the error's period is the WHOLE graded span and
#                        its energy cannot collapse onto the signal bin
#     c odd              (kept from the old rule)
#     c * HARMONICS_IN_BAND <= m / 2    so the harmonics are graded too
#     c >= _MIN_SIGNAL_CYCLES           so the bin is not too coarse to mean
#                                       anything
#
# and the record holds `m + 1` windows, because the gate drops the power-up
# window — the counter's first reset can fall anywhere inside it.
_INC_NO_GRADABLE_TONE = (
    "no_tone_bin_is_coprime_with_the_conversion_window_count: every candidate "
    "in the band would put the decoded error at the signal's own frequency, "
    "where an SNDR removes it as signal")


def incremental_tone(windows_total: int) -> Optional[Dict[str, Any]]:
    """`{"graded_windows", "cycles"}` — the highest gradable tone over a record
    of `windows_total` conversion windows, or None when none exists.

    Highest, because a converter is graded nearest the band edge its OSR
    declares; gradable, because of the coprimality above."""
    _instrument_calibration.assert_calibrated(
        "analog_resolution_stimulus::incremental_tone")  # R-0915-86(3)
    m = int(windows_total) - 1
    if m < 2:
        return None
    top = m // (2 * HARMONICS_IN_BAND)
    c = top if top % 2 else top - 1
    while c >= _MIN_SIGNAL_CYCLES:
        if math.gcd(c, m) == 1:
            return {"graded_windows": m, "cycles": c,
                    "rule": "coprime_with_the_conversion_window_count"}
        c -= 2
    return None


def incremental_record_windows() -> int:
    """The fewest conversion windows a record needs for `incremental_tone` to
    find one. Derived by searching, not typed: the bound is a coprimality and
    there is no closed form for it."""
    w = 2 * HARMONICS_IN_BAND * (_MIN_SIGNAL_CYCLES
                                 + (1 - _MIN_SIGNAL_CYCLES % 2))
    while w < 4096:
        if incremental_tone(w) is not None:
            return w
        w += 1
    raise AssertionError("no conversion-window count admits a gradable tone")


def plan(deck_text: str, spec: Any, topology: Any, *, decision_encoding=None) -> Dict[str, Any]:
    """The record of what this transform would do to `deck_text`, applied or
    refused. Always a dict; `applied` is the one field a caller must read."""
    record: Dict[str, Any] = {"producer": PRODUCER, "applied": False}
    axis = resolution_axis(spec)
    if axis is None:
        record["reason"] = "block_declares_no_resolution_target"
        return record
    record.update({"axis": axis["axis"], "enob_target": axis["enob_bits"],
                   "osr": axis["osr"], "osr_declared": axis["osr_declared"]})

    facts = deck_facts(deck_text)
    if facts["has_wrdata"]:
        record["reason"] = "deck_already_carries_a_transient_dump"
        return record
    if not facts["tran"] or not facts["tran"].get("stop_s"):
        record["reason"] = "no_transient"
        record["detail"] = ("the deck runs no `tran`, so there is no record "
                            "for a tone to be coherent over")
        return record

    port, why = signal_input_port(topology)
    if port is None:
        record["reason"] = "signal_input_port_not_declared"
        record["detail"] = why
        return record
    record["signal_input_port"] = port

    driver = next((s for s in facts["sources"]
                   if s["pos"] == port and s["dc_v"] is not None), None)
    if driver is None:
        record["reason"] = "signal_input_source_absent"
        record["detail"] = (
            f"no top-level DC voltage source drives the declared signal-input "
            f"port {port!r}; this step re-stamps the source the design already "
            f"put there and does not author one")
        return record

    dec = incremental_decode(spec, topology, decision_encoding=decision_encoding)
    if dec.get("loop_model_invalid"):
        record["reason"] = dec["reason"]
        return record
    encoding = (dec.get("loop_model") or {}).get("decision_encoding")
    if encoding:
        nodes = encoding["output_nodes"]
        node, why = nodes[0], None
        record["output_nodes"] = nodes
    else:
        node, why = _output_node(facts)
    if node is None:
        record["reason"] = ("output_node_ambiguous" if facts["measured_nodes"]
                            else "output_node_not_measured")
        record["detail"] = why
        return record
    record["output_node"] = node

    fclk, why = _sample_clock_hz(facts)
    if fclk is None:
        record["reason"] = "sample_clock_not_identifiable"
        record["detail"] = why
        return record
    record["fclk_hz"] = fclk

    # THE DECODE DECLARATION IS READ BEFORE THE TONE, because for an
    # incremental converter it decides which domain the tone is coherent in.
    record["incremental_decode"] = dec

    stop_s = facts["tran"]["stop_s"]
    samples = int(stop_s * fclk)
    osr = axis["osr"]
    band_bins = int(samples / (2.0 * osr))
    # THE NUMBER A READER WILL ACT ON, so it is the ACTUAL threshold and not a
    # convenient lower bound. The tone bin must be ODD, so the smallest one
    # this will ever emit is the first odd integer at or above the cycle floor
    # — 9, not 8 — and it must fit `HARMONICS_IN_BAND` times inside the band.
    # Rounding `_MIN_SIGNAL_CYCLES` up to that odd bin is the difference
    # between a record that works and one that is lengthened and still
    # refused: at OSR 256 it is 13824 samples against 12288, and 12288 comes
    # back UNMEASURED. Caught by bisecting the real refusal rather than by
    # reading this arithmetic (vibe-ic#2188).
    floor = coherent_record_samples(
        osr, dec.get("window_clocks") if dec.get("declared") else None)
    min_bin = floor["min_tone_bin"]
    required = floor["samples"]
    record.update({"record_s": stop_s, "samples_available": samples,
                   "band_bins": band_bins, "samples_required": required,
                   "min_signal_cycles": floor["min_signal_cycles"],
                   "min_tone_bin": min_bin,
                   "harmonics_in_band": floor["harmonics_in_band"]})
    # THE INCREMENTAL BRANCH. The tone is `cycles` whole cycles across the
    # GRADED conversion windows — the domain the matched decode measures in —
    # and its cycle count is coprime with them, so the decoded error's period
    # is the whole graded span instead of collapsing onto the signal's own
    # frequency (F167). The free-running branch below is byte-for-byte the
    # rule it always was: for a modulator the raw record IS the graded domain.
    inc_tone = None
    if dec.get("declared"):
        inc_tone = incremental_tone(samples // int(dec["window_clocks"]))
        if inc_tone is None:
            record["reason"] = _INC_NO_GRADABLE_TONE
            record["detail"] = (
                f"the record holds "
                f"{samples // int(dec['window_clocks'])} conversion window(s) "
                f"of {int(dec['window_clocks'])} clocks; it needs at least "
                f"{floor.get('conversion_windows')}")
            return record
        record.update({
            "graded_windows": inc_tone["graded_windows"],
            "cycles": inc_tone["cycles"],
            "tone_rule": inc_tone["rule"],
            "conversion_windows": samples // int(dec["window_clocks"])})
        tone_bin = inc_tone["cycles"]
    else:
        highest = int(band_bins // HARMONICS_IN_BAND)
        tone_bin = highest if highest % 2 else highest - 1
    if tone_bin < _MIN_SIGNAL_CYCLES:
        record["reason"] = "record_too_short_for_an_in_band_tone"
        record["detail"] = (
            f"the deck's {stop_s:g} s record holds {samples} converter "
            f"samples, whose signal band (OSR {osr:g}) is {band_bins} bin(s). "
            f"A tone needs an ODD bin at or below {HARMONICS_IN_BAND} times "
            f"under the band edge so its harmonics are graded too, and at "
            f"least {_MIN_SIGNAL_CYCLES} whole cycles for the fit — so the "
            f"lowest bin this will emit is {min_bin} and the record has to "
            f"hold {required} samples. Lengthening it to anything less comes "
            f"back here. The record is not this step's to lengthen: "
            f"the conversion window is the design's own declaration")
        return record
    record["tone_bin"] = tone_bin

    dc_v = driver["dc_v"]
    amplitude, why = _amplitude(facts, port, dc_v)
    if amplitude is None:
        record["reason"] = "tone_amplitude_unbounded"
        record["detail"] = why
        return record

    record.update({
        "applied": True,
        "source": driver["name"],
        "dc_offset_v": dc_v,
        "amplitude_v": amplitude,
        # For the incremental class the tone is `cycles` per GRADED WINDOW
        # SPAN, not per raw record: those are different denominators and the
        # difference is the whole of F167.
        "tone_hz": (inc_tone["cycles"] * fclk
                    / (inc_tone["graded_windows"] * int(dec["window_clocks"]))
                    if inc_tone else tone_bin * fclk / samples),
        "replaced_source_card": driver["body"],
        "source_line": driver["line"],
        "tran_line": facts["tran"]["line"],
        "exported_vectors": _EXPORTED_VECTORS,
    })
    return record


def apply(deck_text: str, spec: Any, topology: Any, dump_ref: str
          ) -> Tuple[str, Dict[str, Any]]:
    """`(deck, record)`. The deck is returned UNCHANGED when the record says
    `applied` is false — a refusal never half-edits a deck."""
    record = plan(deck_text, spec, topology)
    if not record.get("applied"):
        return deck_text, record
    lines = deck_text.splitlines()
    tone = (f"{record['source']} {record['signal_input_port']} "
            f"{lines[record['source_line']].split()[2]} "
            f"sin({_num(record['dc_offset_v'])} "
            f"{_num(record['amplitude_v'])} {_num(record['tone_hz'])})")
    lines[record["source_line"]] = tone
    note = (
        f"* {PRODUCER}: the declared signal input is driven by a COHERENT TONE "
        f"centred on the level the design's own deck held it at "
        f"({_num(record['dc_offset_v'])} V), so every measurement that deck "
        f"already takes keeps its expected value, and the converter's output "
        f"is exported so its effective resolution can be fitted. Bin "
        f"{record['tone_bin']} of {record['samples_available']} samples at "
        f"{_num(record['fclk_hz'])} Hz; band edge "
        f"{record['band_bins']} bin(s) at OSR {record['osr']:g}.")
    lines.insert(record["source_line"], note)
    dump = f"wrdata {dump_ref} " + " ".join(f"v({node})" for node in
        record.get("output_nodes", [record["output_node"]]))
    if (record.get("incremental_decode", {}).get("loop_model") or {}).get("decision_encoding"):
        dump = "set wr_singlescale\nset wr_vecnames\n" + dump
    lines.insert(record["tran_line"] + 2, dump)
    # The decode declaration travels ON THE DECK, beside the tone note, so the
    # gate that reads the dump reads it off the same file. A SPICE comment.
    _dec = record.get("incremental_decode") or {}
    if _dec.get("declared"):
        lines.insert(record["source_line"], _dec["stamp"])
    record["dump"] = dump_ref
    return "\n".join(lines) + "\n", record


# ── R-0915-117(2): ONE CORNER, TWO DECKS ────────────────────────────────────
#
# WHY. MEASURED on 8hd-3 (image 0.3.67), two decks identical but for the save
# list and the rail cards, 21 us each -- the ratio is duration-independent:
#     122 vectors, 240 railx_* cards : peak RSS 111596 kB, wall 249.3 s
#       1 vector,    0 railx_* cards : peak RSS  39424 kB, wall 238.4 s
# giving a fixed cost of 38827 kB and 28.4 kB of storage per saved vector per
# microsecond of simulated time. Extrapolated to the declared 28.673 ms record
# that is 94.79 GiB against 0.81 GiB -- 116x -- while the wall moves 1.05x.
# Cross-checked against a live corner's own RSS slope over 87 samples, which
# gave 96.9 GiB by a completely different method: the two agree to 2%.
# ngspice-47 in this image offers only -o / -r / --soa-log, so there is no
# streaming transient writer and memory is bounded only by vectors x timepoints.
#
# WHAT THAT BUYS, AND WHAT IT DOES NOT. It is a MEMORY result, not a speed one.
# At 0.81 GiB a corner stops being RAM-bound, so a host runs as many corners as
# it has cores for rather than ONE. The wall per corner is unchanged.
#
# THE SPLIT. The cost was A3's rails instrumentation riding on A4's graded
# record: 120 of the 122 vectors exist only for the `railx_*` cards, and that
# claim settles in two conversion windows (R-0915-117(1)). So one corner emits
# two decks from the SAME netlist identity:
#   RAILS  -- every `railx_*` card and every vector they read, over the bounded
#             two-window span, derived the same way and never typed. Its receipt
#             is the rails verdict AT THAT CORNER, which today no corner carries.
#   GRADED -- the full declared record, retaining ONLY the vectors the receipt
#             reads. Derived from the receipt's own column contract: the dump is
#             what `sndr_db_incremental` reads, and the dump is this deck's own
#             `wrdata` card, so the card names the retention.
# A corner is PASS only when both decks PASS; a missing deck is NOT_MEASURED by
# name, never a default.
_RAILS_MEAS_RE = re.compile(r"(?im)^\s*meas\s+tran\s+railx_\S+.*$")
_SAVE_RE = re.compile(r"(?im)^\s*\.save\b.*$")
_WRDATA_CARD_RE = re.compile(r"(?im)^\s*wrdata\s+\S+\s+(.*)$")
_TRAN_RE = re.compile(r"(?im)^\s*tran\s+(\S+)\s+(\S+)\s*$")

SPLIT_NO_WINDOW = (
    "rails_deck_window_not_derivable: the deck declares no conversion window, "
    "so the span over which its rail cards settle cannot be derived from it")
SPLIT_NO_CLOCK = (
    "rails_deck_window_not_derivable_no_clock_card: no single top-level pulse "
    "source names the conversion clock")
SPLIT_NO_TRAN = "deck_runs_no_transient_to_split"
SPLIT_NO_WRDATA = (
    "graded_deck_retention_not_derivable: the deck writes no `wrdata`, so the "
    "receipt's own column contract names no vector to retain")

#: Storage per saved vector per second of simulated time, MEASURED above.
#: Stated as a measurement with its provenance rather than a tuning knob, and
#: overridable for a machine that measures its own.
RSS_BYTES_PER_VECTOR_SECOND = 28.4 * 1024 * 1e6
RSS_FIXED_BYTES = 38827 * 1024


def rails_deck(deck_text: str, window_clocks: Optional[int] = None
               ) -> Tuple[Optional[str], Dict[str, Any]]:
    """The corner's RAILS deck: the instrumentation it already carries, over
    two conversion windows. Refuses by name rather than defaulting."""
    decl, why = _inc.read_stamp(deck_text or "")
    if decl is not None:
        window = int(decl["window_clocks"])
    elif isinstance(window_clocks, int) and window_clocks > 0:
        window = window_clocks
    else:
        return None, {"reason": SPLIT_NO_WINDOW, "detail": why}
    facts = deck_facts(deck_text or "")
    periods = [s["period_s"] for s in facts["sources"] if s.get("period_s")]
    if len(periods) != 1:
        return None, {"reason": SPLIT_NO_CLOCK, "pulse_sources": len(periods)}
    period = periods[0]
    m = _TRAN_RE.search(deck_text or "")
    if not m:
        return None, {"reason": SPLIT_NO_TRAN}
    stop = 2 * window * period
    # Written in the nanosecond token the emitted decks are written in, so a
    # rewritten card reads like a written one.
    _ns = stop * 1e9
    span = (f"{int(round(_ns))}n" if abs(_ns - round(_ns)) < 1e-6
            else f"{_ns:.6f}".rstrip("0").rstrip(".") + "n")
    out = (deck_text[:m.start()] + "tran " + m.group(1) + " "
           + span + deck_text[m.end():])
    return out, {"claim": "rails", "conversion_windows": 2,
                 "window_clocks": window, "span_s": stop,
                 "rail_cards": len(_RAILS_MEAS_RE.findall(deck_text or "")),
                 "rule": "two_conversion_windows_from_the_decks_own_numbers"}


def graded_deck(deck_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """The corner's GRADED deck: the full declared record, retaining only the
    vectors the receipt reads. The rail cards go to the rails deck, and the
    vectors that existed only for them go with them."""
    w = _WRDATA_CARD_RE.search(deck_text or "")
    if not w:
        return None, {"reason": SPLIT_NO_WRDATA}
    kept = re.findall(r"[vi]\([^)]*\)", w.group(1))
    if not kept:
        return None, {"reason": SPLIT_NO_WRDATA}
    out = _RAILS_MEAS_RE.sub("", deck_text or "")
    out = "\n".join(ln for ln in out.splitlines() if ln.strip())
    dropped = len(re.findall(r"[vi]\([^)]*\)", _SAVE_RE.search(out).group(0))
                  ) if _SAVE_RE.search(out) else 0
    out = _SAVE_RE.sub(".save " + " ".join(kept), out, count=1)
    return out + "\n", {
        "claim": "graded", "retained_vectors": kept,
        "retained": len(kept), "previously_retained": dropped,
        "rail_cards_removed": len(_RAILS_MEAS_RE.findall(deck_text or "")),
        "rule": "retention_is_the_decks_own_wrdata_card_which_is_what_the_receipt_reads",
    }


def estimated_peak_rss_bytes(deck_text: str) -> Optional[int]:
    """What this deck will hold, from ITS OWN numbers: saved vectors times the
    record it runs. Replaces a declared constant, which under-estimated the
    graded deck by about 4x and would have admitted a second corner that was
    later killed. An estimate, and named as one."""
    m = _TRAN_RE.search(deck_text or "")
    if not m:
        return None
    stop = si(m.group(2))
    sv = _SAVE_RE.search(deck_text or "")
    if stop is None or sv is None:
        return None
    n = len(re.findall(r"[vi]\([^)]*\)", sv.group(0)))
    return int(RSS_FIXED_BYTES + RSS_BYTES_PER_VECTOR_SECOND * n * stop)
