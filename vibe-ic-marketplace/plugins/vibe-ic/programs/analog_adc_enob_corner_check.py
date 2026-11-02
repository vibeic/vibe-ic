#!/usr/bin/env python3
"""analog_adc_enob_corner_check.py — R12 system-ENOB per-corner gate (A4).

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
For any ADC/DAC block that declares an ENOB (or SNDR) target, assert the
converter's measured effective resolution meets the spec on EVERY corner of
the corner sweep — not just the typical (TT/27C) corner. The classic escape
this closes: ENOB is measured and reported for the nominal corner only, so a
converter that meets ENOB typ but droops below it at a slow/hot corner ships
with an un-flagged spec violation. (A real hot-corner residual: an
oversampled modulator whose in-band SQNR — hence ENOB — collapses at SS/125C
because the integrator gain sags there.)

ENOB is derived from the sim-measured SNDR the standard way:

        ENOB = (SNDR_dB - 1.76) / 6.02

SNDR (and therefore ENOB) is a legitimate TOOL OUTPUT of the FFT/behavioural
converter sim — never a golden/oracle value. This gate READS that measured
output + the ENOB target from the design INPUT spec (spec.json) and compares;
it does not itself simulate.

Per block, reads:
  * phase3/analog/<block>/spec.json          — the ENOB target (design INPUT)
  * phase3/analog/<block>/corner_results.json — per-corner SNDR/ENOB (OUTPUT)

Applicability (chip-AGNOSTIC, no chip/SKU literal):
  * the block's spec.json declares a spec named `enob` OR `sndr`/`sndr_db`.
    (No ENOB/SNDR target => this is not a resolution-graded converter => SKIP.)

Per-corner resolution is read in priority order:
  1. a direct `enob` field on the corner, else
  2. computed from an SNDR field (`sndr_db` / `sndr` / `snr_db` alias) via the
     6.02/1.76 relation, else
  3. MEASURED HERE, from the corner's own A4 TRANSIENT: an FFT of the
     converter output over the simulated window, signal bin against everything
     else, `ENOB = (SNDR - 1.76) / 6.02` (see `sndr_db_from_transient`).

WHY (3) EXISTS, MEASURED (vibe-ic#2062). `ENOB >= 14` is the headline spec the
design INPUT declares for the larger of this chip's two analog blocks, and
NOTHING in the A-track measured it: the delivered testbench measures bitstream
density and swing, no corner carried an `sndr`/`enob` field, and this gate
returned `UNMEASURED / ZERO_DENOMINATOR` with `corners_seen: 9` — honest, and
still a headline spec that had never been evaluated by anything.

AND WHY IT STILL REFUSES ON THE DESIGN THAT PROMPTED IT. An FFT-based SNDR is
not a thing a gate can compute out of goodwill: it needs the converter's output
SAMPLES over the window, and it needs the input to be a COHERENT TONE, because
SNDR is the ratio of a signal bin to everything else and a DC input has no
signal bin at all. On the block in hand the emitted deck holds the input at a
DC level and dumps no waveform, so BOTH preconditions are absent — and the
refusal now SAYS WHICH ONE, per corner, by name (`_UNMEASURABLE_*` below),
instead of the single undifferentiated `no_sndr_or_enob`. A reader who is told
`stimulus_not_a_coherent_tone` can go and fix the testbench; a reader told
"no data" cannot.

Corners with none of the three are counted as UNMEASURED, each with the NAMED
reason it could not be measured. If NO corner yields a resolution the gate is
UNMEASURED (rc 2) — never a vacuous PASS and never a false FAIL.

Verdict:
  PASS  — every measured corner's ENOB >= target.
  FAIL  — >=1 measured corner ENOB < target; the finding lists each failing
          corner with its ENOB and the shortfall.
  SKIP  — no ADC/DAC block with an ENOB/SNDR target, or no per-corner
          SNDR/ENOB data present.

Exit codes: 0 = PASS / SKIP, 1 = FAIL, 2 = IO / argument error.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl
import analog_incremental_decimator as _inc

GATE = "analog_adc_enob_corner_check"

# ENOB <-> SNDR ideal-quantiser relation (both are chip-AGNOSTIC constants).
_SNDR_SLOPE = 6.02   # dB per bit
_SNDR_INTERCEPT = 1.76  # dB

# ── measuring SNDR from a transient ────────────────────────────────────────
#
# Every name below is a NAMED refusal: the precondition an FFT-based SNDR
# needs and this corner does not have. None of them is ever a pass.
_UNMEASURABLE_NO_LOG = "no_transient_log_named_by_the_corner"
_UNMEASURABLE_NO_DECK = "no_deck_beside_the_corner_log"
_UNMEASURABLE_NO_DUMP = "no_transient_dump: the deck writes no `wrdata` file"
_UNMEASURABLE_NO_TONE = ("stimulus_not_a_coherent_tone: the deck drives the "
                         "converter input from a DC source, and SNDR is a "
                         "signal bin against everything else")
_UNMEASURABLE_SHORT = "transient_too_short_for_{n}_signal_cycles"
_UNMEASURABLE_NO_ROWS = "transient_dump_present_but_carries_no_rows"
#: An OVERSAMPLED converter is graded over its signal band, and the band is
#: `fclk / (2 * OSR)` — so without the clock there is no band, and the only
#: spectrum left to integrate is the whole Nyquist span. For a 1-bit modulator
#: that span is dominated by the noise it deliberately shaped OUT of the band:
#: the number it yields is near 0 dB for a converter that is working perfectly.
#: Reporting that as an effective resolution would be a FALSE FAIL, so the
#: honest answer is that the band could not be established. (vibe-ic#2188)
#: The window is longer than the largest grid this gate will build at the
#: converter's own rate. Refused BY NAME rather than measured on a coarser
#: grid, because a coarser grid is the aliasing `_resample_pow2` documents.
_UNMEASURABLE_GRID_TOO_LARGE = (
    "record_longer_than_the_grid_this_gate_can_build_at_the_sample_clock: "
    "measuring it would mean sampling below the converter's own clock, which "
    "folds the noise it shaped out of band back into the band")
_UNMEASURABLE_NO_CLOCK = ("oversampled_but_sample_clock_not_in_the_deck: OSR "
                          "is declared and the deck names no single pulse "
                          "source, so the signal band cannot be established")
_UNMEASURABLE_OUT_OF_BAND = ("tone_outside_the_graded_band: the deck's tone "
                             "sits above `fclk / (2 * OSR)`, where an "
                             "oversampled converter is not graded")

#: The fewest whole signal cycles an FFT-based SNDR is taken over here. Below
#: this the signal bin is too coarse for the noise floor around it to mean
#: anything, and the honest answer is that the window is too short — not a
#: number computed over two cycles and reported as a resolution.
_MIN_SIGNAL_CYCLES = 8

_SIN_RE = re.compile(
    r"(?im)^\s*v\w*\s+\S+\s+\S+\s+sin\s*\(\s*"
    r"([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+[a-zA-Z]*)")
_WRDATA_RE = re.compile(r"(?im)^\s*wrdata\s+(\S+)\s+(.+?)\s*$")
_TRAN_RE = re.compile(
    r"(?im)^\s*\.?tran\s+\S+\s+([0-9.eE+-]+)\s*([munpf]?)s?\b")
#: `pulse(v1 v2 td tr tf pw per)` on a top-level source — the converter's own
#: sample clock, read off the DECK THIS CORNER RAN like everything else here.
_PULSE_RE = re.compile(
    r"(?im)^\s*v\w*\s+\S+\s+\S+\s+pulse\s*\(([^)]*)\)")
_T_SCALE = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}


def _si(tok: str) -> Optional[float]:
    """A SPICE scalar with an optional engineering suffix, in SI units."""
    m = re.match(r"^([0-9.eE+-]+)\s*([a-zA-Z]*)$", str(tok).strip())
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    for key in ("meg", "k", "m", "u", "n", "p", "f", "g", "t"):
        if suf.startswith(key):
            return v * {"meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9,
                        "p": 1e-12, "f": 1e-15, "g": 1e9, "t": 1e12}[key]
    return v


def _fft(re_in: List[float]) -> List[complex]:
    """Iterative radix-2 FFT over a power-of-two real input.

    Written out rather than imported: this repo's programs carry no numpy
    dependency, and adding one so a gate can refuse politely would make the
    gate's availability depend on the host's site-packages. N is a power of
    two by construction (`_resample_pow2`)."""
    n = len(re_in)
    data = [complex(x, 0.0) for x in re_in]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            data[i], data[j] = data[j], data[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wl = complex(math.cos(ang), math.sin(ang))
        for i in range(0, n, length):
            w = complex(1.0, 0.0)
            for k in range(i, i + length // 2):
                u = data[k]
                v = data[k + length // 2] * w
                data[k] = u + v
                data[k + length // 2] = u - v
                w *= wl
        length <<= 1
    return data


#: The largest grid this gate will build. A radix-2 FFT over it is O(n log n)
#: in pure Python, and past this the gate stops being usable inside a run.
_GRID_CAP = 1 << 18


def _resample_at(times: List[float], vals: List[float],
                 t0: float, t1: float, fs: float) -> Optional[List[float]]:
    """`vals` zero-order-held onto a grid of EXACTLY `fs`, over [t0, t1).

    THE GRID MUST BE COMMENSURATE WITH THE CONVERTER'S CLOCK (lane icadc,
    2026-09-15, MEASURED). A bitstream is piecewise constant on a 1/fs
    lattice. Resampling it onto a grid whose step is not that lattice beats the
    two rates together, and the beat lands in the signal band as noise the
    circuit never made. ONE waveform, three grids, everything else held:

        last 8 cycles, grid = fs exactly (12288 pts)   SNDR  96.129 dB
        last 8 cycles, grid = 16384 pts (1333 kHz)     SNDR  21.706 dB
        whole record from t=0, grid = fs               SNDR  15.430 dB
                                                       (startup is in the window)

    **74 dB** between the first two, on identical samples. The grid, not the
    circuit, was the measurement.
    """
    if t1 <= t0 or fs <= 0 or len(times) < 4:
        return None
    n = int(round((t1 - t0) * fs))
    if n < 64 or n > _GRID_CAP:
        return None
    dt = 1.0 / fs
    # A GRID POINT THAT LANDS ON A SAMPLE BOUNDARY MUST TAKE THAT SAMPLE.
    # MEASURED: with a strict `<=` the window start came out 4.9e-19 s below
    # the sample it was meant to start on — the last bits of `t1 - cycles /
    # f_sig` — and the hold then took the PREVIOUS sample for 3924 of 3968
    # points while the other 44 took the right one. That is not a delay (a
    # uniform delay costs nothing); it is one-sample JITTER, and it cost
    # **58 dB**: the same 16-bit record measures 110.758 dB sliced exactly and
    # 52.392 dB through the jittered hold. The tolerance is a hundred-
    # thousandth of a grid step — far above the accumulated error of `t0 + k *
    # dt` over the largest grid this gate builds, and far below anything a
    # circuit does.
    tol = dt * 1e-5
    out: List[float] = []
    i = 0
    for k in range(n):
        t = t0 + k * dt
        while i + 1 < len(times) and times[i + 1] <= t + tol:
            i += 1
        out.append(vals[i])
    return out


def _in_band_power(x: List[float], top: int) -> List[float]:
    """|X(k)|^2 for k = 1..top by direct DFT.

    NOT an FFT, and deliberately: the commensurate grid above is `cycles * fs /
    f_sig` points, which is not a power of two, and a radix-2 FFT is what
    forced the old code onto a grid the converter does not run at. An
    oversampled converter is graded over `fs / (2 * OSR)`, which is a few dozen
    bins -- `top * n` multiply-adds, not `n log n` -- so the narrow band that
    makes the DFT affordable is the same property that makes the measurement
    meaningful.
    """
    n = len(x)
    mean = sum(x) / n
    xs = [v - mean for v in x]
    out: List[float] = []
    for k in range(1, top + 1):
        re = im = 0.0
        w = -2.0 * math.pi * k / n
        for i, v in enumerate(xs):
            a = w * i
            re += v * math.cos(a)
            im += v * math.sin(a)
        out.append(re * re + im * im)
    return out


def _resample_pow2(times: List[float], vals: List[float],
                   t0: float, t1: float) -> Optional[List[float]]:
    """`vals` linearly resampled onto a uniform power-of-two grid over
    [t0, t1). A SPICE transient has a NON-UNIFORM time step, so an FFT taken
    over the rows as written measures the solver's step control as much as the
    circuit."""
    if t1 <= t0 or len(times) < 4:
        return None
    n = 1
    while n * 2 <= min(len(times), 1 << 16):
        n *= 2
    if n < 64:
        return None
    dt = (t1 - t0) / n
    out: List[float] = []
    i = 0
    for k in range(n):
        t = t0 + k * dt
        while i + 1 < len(times) and times[i + 1] < t:
            i += 1
        if i + 1 >= len(times):
            out.append(vals[-1])
            continue
        span = times[i + 1] - times[i]
        frac = 0.0 if span <= 0 else (t - times[i]) / span
        out.append(vals[i] + frac * (vals[i + 1] - vals[i]))
    return out


def sample_clock_hz(deck_text: str) -> Optional[float]:
    """The converter's sample rate from the ONE top-level pulse source the
    deck drives, or None when the deck names none or more than one.

    Read off the deck rather than the spec on purpose: the deck is what RAN,
    and a spec `fclk` the deck did not honour would put the band edge
    somewhere the spectrum never was."""
    periods = []
    for body in _PULSE_RE.findall(deck_text or ""):
        fields = body.split()
        if len(fields) < 7:
            continue
        per = _si(fields[6])
        if per and per > 0:
            periods.append(per)
    if len(periods) != 1:
        return None
    return 1.0 / periods[0]


def sndr_db_from_transient(deck_text: str, dump_text: str,
                           column: int = 1, osr: float = 1.0
                           ) -> Tuple[Optional[float], dict]:
    """SNDR in dB from one corner's transient, or (None, {"reason": ...}).

    The method the brief names and the one every converter datasheet uses:
    resample the output onto a uniform grid over a WHOLE NUMBER of signal
    cycles, FFT it, and compare the signal bin's power against everything else
    in the spectrum except DC. Coherent sampling makes a rectangular window
    correct; the bin the tone lands in is `cycles`, exactly, by construction.

    `osr` IS THE WHOLE DIFFERENCE FOR AN OVERSAMPLED CONVERTER (vibe-ic#2188).
    An oversampling converter's resolution is defined over its SIGNAL BAND,
    `fclk / (2 * OSR)`; that is what oversampling MEANS, and it is why the
    modulator is allowed to push its quantisation noise out of that band. Sum
    the whole Nyquist span instead and a 1-bit modulator that is working
    perfectly measures near 0 dB, because almost all the power in that span is
    the noise it shaped out on purpose. With `osr` at its default of 1 the
    integration is the full span, which is right for a Nyquist-rate converter
    and is what this function did before.

    chip-AGNOSTIC: the signal frequency, the window, the sample clock and the
    dump path all come from the DECK THIS CORNER RAN, never from a table here.
    """
    m = _SIN_RE.search(deck_text or "")
    if not m:
        return None, {"reason": _UNMEASURABLE_NO_TONE}
    f_sig = _si(m.group(3))
    if not f_sig or f_sig <= 0:
        return None, {"reason": _UNMEASURABLE_NO_TONE}
    mt = _TRAN_RE.search(deck_text or "")
    if not mt:
        return None, {"reason": _UNMEASURABLE_SHORT.format(
            n=_MIN_SIGNAL_CYCLES)}
    t_stop = float(mt.group(1)) * _T_SCALE.get(mt.group(2).lower(), 1.0)

    times: List[float] = []
    vals: List[float] = []
    for line in (dump_text or "").splitlines():
        parts = line.split()
        if len(parts) <= column:
            continue
        try:
            t = float(parts[0])
            v = float(parts[column])
        except ValueError:
            continue                      # a header row, not a sample
        times.append(t)
        vals.append(v)
        if reset_node:
            reset_values.append(reset_v)
    if len(times) < 64:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}

    span = min(t_stop, times[-1]) - times[0]
    cycles = int(span * f_sig)
    if cycles < _MIN_SIGNAL_CYCLES:
        return None, {"reason": _UNMEASURABLE_SHORT.format(
            n=_MIN_SIGNAL_CYCLES),
            "signal_hz": f_sig, "window_s": span, "cycles_available": cycles}
    # An ODD number of whole cycles puts the tone in a bin whose neighbours are
    # not its own leakage; either way the count is an integer, which is what
    # makes the rectangular window exact.
    t1 = times[-1]
    t0 = t1 - cycles / f_sig
    # THE GRID RATE IS THE CONVERTER'S OWN CLOCK (lane icadc). Read here, not
    # inside the `osr > 1` branch below, because the rate the record is
    # resampled at decides the answer for EVERY converter — the band edge only
    # decides which part of that answer is graded.
    f_clk = sample_clock_hz(deck_text)

    # THE OVERSAMPLED PATH. An OSR the design declares is exactly the case the
    # grid rate decides (see `_resample_at`), and it is also the case whose
    # band is narrow enough to measure by direct DFT. The Nyquist path below is
    # left byte-for-byte as it was: there the full span IS the band, a
    # power-of-two FFT is the only affordable transform, and the grid rate was
    # never the thing that was wrong.
    if osr and osr > 1.0 and f_clk:
        band_hz = f_clk / (2.0 * osr)
        grid = _resample_at(times, vals, t0, t1, f_clk)
        if grid is None:
            need = int(round((t1 - t0) * f_clk))
            if need > _GRID_CAP:
                return None, {"reason": _UNMEASURABLE_GRID_TOO_LARGE,
                              "sample_clock_hz": f_clk, "window_s": t1 - t0,
                              "grid_points_required": need,
                              "grid_cap": _GRID_CAP}
            return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
        n = len(grid)
        bin_sig = cycles
        # bin k of this grid sits at k * f_sig / cycles Hz, because the window
        # is exactly `cycles / f_sig` seconds long however many points it holds.
        top = min(n // 2 - 1, int(band_hz * cycles / f_sig))
        if not (1 <= bin_sig < n // 2) or top < bin_sig + 1:
            return None, {"reason": _UNMEASURABLE_OUT_OF_BAND,
                          "osr": osr, "signal_hz": f_sig, "band_hz": band_hz,
                          "signal_bin": bin_sig, "band_edge_bin": top}
        power = _in_band_power(grid, top)
        sig_bins = {b for b in (bin_sig - 1, bin_sig, bin_sig + 1)
                    if 1 <= b <= top}
        p_sig = sum(power[b - 1] for b in sig_bins)
        p_noise = sum(power) - p_sig
        if p_sig <= 0 or p_noise <= 0:
            return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
        return 10.0 * math.log10(p_sig / p_noise), {
            "method": "dft_signal_bin_vs_in_band_rest_at_sample_clock",
            "signal_hz": f_sig, "signal_bin": bin_sig, "band_hz": band_hz,
            "osr": osr, "band_edge_bin": top, "cycles": cycles,
            "fft_points": n, "rows_read": len(times),
            "sample_clock_hz": f_clk, "grid_hz": f_clk,
            "grid_rule": "sample_clock_commensurate",
        }

    grid = _resample_pow2(times, vals, t0, t1)
    if grid is None:
        if f_clk and (t1 - t0) * f_clk > _GRID_CAP:
            return None, {"reason": _UNMEASURABLE_GRID_TOO_LARGE,
                          "sample_clock_hz": f_clk, "window_s": t1 - t0,
                          "grid_points_required": int((t1 - t0) * f_clk),
                          "grid_cap": _GRID_CAP}
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    n = len(grid)
    mean = sum(grid) / n
    spec = _fft([g - mean for g in grid])
    half = n // 2
    power = [abs(spec[k]) ** 2 for k in range(1, half)]
    if not power:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    bin_sig = cycles
    if not (1 <= bin_sig < half):
        return None, {"reason": _UNMEASURABLE_SHORT.format(
            n=_MIN_SIGNAL_CYCLES), "signal_bin": bin_sig, "bins": half}
    # THE BAND THE CONVERTER IS GRADED OVER. The resampled grid spans
    # `cycles / f_sig` seconds, so its bin k is at `k * f_sig / cycles` Hz and
    # the band edge `fclk / (2 * OSR)` lands at `band_hz * cycles / f_sig`.
    band_hz: Optional[float] = None
    top = half - 1
    if osr and osr > 1.0:
        if not f_clk:
            return None, {"reason": _UNMEASURABLE_NO_CLOCK, "osr": osr}
        band_hz = f_clk / (2.0 * osr)
        top = min(top, int(band_hz * cycles / f_sig))
        if top < bin_sig + 1:
            return None, {"reason": _UNMEASURABLE_OUT_OF_BAND,
                          "osr": osr, "signal_hz": f_sig,
                          "band_hz": band_hz, "signal_bin": bin_sig,
                          "band_edge_bin": top}
    if top < 1:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    # The tone plus its two immediate neighbours: a whole-cycle window puts the
    # tone in one bin, and taking the neighbours with it makes the answer
    # robust to a solver whose last step lands a hair off the boundary. They
    # are removed from the noise sum too, so no power is counted twice.
    sig_bins = {b for b in (bin_sig - 1, bin_sig, bin_sig + 1)
                if 1 <= b <= top}
    p_sig = sum(power[b - 1] for b in sig_bins)
    p_noise = sum(power[b - 1] for b in range(1, top + 1)) - p_sig
    if p_sig <= 0 or p_noise <= 0:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    return 10.0 * math.log10(p_sig / p_noise), {
        "method": ("fft_signal_bin_vs_in_band_rest" if band_hz
                   else "fft_signal_bin_vs_rest"),
        "signal_hz": f_sig, "signal_bin": bin_sig, "band_hz": band_hz,
        "osr": osr, "band_edge_bin": top,
        "cycles": cycles, "fft_points": n, "rows_read": len(times),
        "sample_clock_hz": f_clk,
        "grid_hz": n / (t1 - t0) if t1 > t0 else None,
        "grid_rule": "row_count",
    }


#: The incremental path's own refusals. An incremental converter's decoded
#: stream is `window` times shorter than its bitstream, so the cycle floor
#: bites there first and the number that would come back is a spectrum over
#: two or three bins. Refused by name, like every other precondition here.
_INC_TOO_FEW_CYCLES = (
    "decimated_record_holds_fewer_than_{n}_tone_cycles: an incremental "
    "converter's decoded stream is one sample per conversion window, so the "
    "record has to hold that many cycles AFTER decimation")
_INC_NO_CLOCK_CARD = (
    "sample_clock_card_not_readable: the incremental decode has to start on "
    "the clock edge the window counter starts on, and no single top-level "
    "pulse source names it")
_INC_SHORT_RECORD = "record_shorter_than_one_conversion_window"


def sample_clock_card(deck_text: str) -> Optional[Tuple[float, float, float]]:
    """`(first_edge_s, period_s, high_v)` from the ONE top-level pulse source,
    or None when the deck names none or more than one.

    `sample_clock_hz` already reads the period off this card; the incremental
    decode needs the DELAY too, because the window counter powers up in its
    reset state and is clocked by this same edge — so the deck's own `td` is
    where conversion window 0 begins. Deriving it rather than assuming t=0 is
    the difference between windows aligned to the resets and windows that
    straddle two conversions."""
    cards = []
    for body in _PULSE_RE.findall(deck_text or ""):
        f = body.split()
        if len(f) < 7:
            continue
        v2, td, per = _si(f[1]), _si(f[2]), _si(f[6])
        if per and per > 0 and td is not None and v2 is not None:
            cards.append((td, per, v2))
    return cards[0] if len(cards) == 1 else None


def sndr_db_incremental(deck_text: str, dump_text: str, column: int = 1
                        ) -> Tuple[Optional[float], dict]:
    """SNDR in dB from the MATCHED DECIMATION of one incremental corner, or
    (None, {"reason": ...}).

    The instrument the converter's declared conversion mode calls for. An
    incremental converter resets and accumulates per conversion window BY
    DESIGN and earns its resolution from the matched decode of each window; an
    FFT of its raw bitstream measures a modulator that is not there and
    UNDER-READS it (vibe-ic#2321, #2322).

    Every input is read off THE DECK THAT RAN — the decode declaration the
    producer stamped on it, the clock card the counter starts on, the tone the
    deck drives — for the same reason `sndr_db_from_transient` reads the band
    off the deck: a document the deck did not honour puts the measurement
    somewhere the record never was.
    """
    decl, why = _inc.read_stamp(deck_text)
    if decl is None:
        return None, why
    if decl.get("mode") != _inc.MODE_INCREMENTAL:
        return None, {"reason": "deck_declares_a_free_running_converter",
                      "mode": decl.get("mode")}
    m = _SIN_RE.search(deck_text or "")
    if not m:
        return None, {"reason": _UNMEASURABLE_NO_TONE}
    f_sig = _si(m.group(3))
    if not f_sig or f_sig <= 0:
        return None, {"reason": _UNMEASURABLE_NO_TONE}
    card = sample_clock_card(deck_text)
    if card is None:
        return None, {"reason": _INC_NO_CLOCK_CARD}
    td, period, v_high = card

    times: List[float] = []
    vals: List[float] = []
    model = decl.get("loop_model")
    encoding = (model or {}).get("decision_encoding")
    decision_columns = None
    reset_node = decl.get("reset_release_node")
    reset_column = None
    reset_values = []
    for line in (dump_text or "").splitlines():
        parts = line.split()
        if len(parts) <= column:
            continue
        try:
            t = float(parts[0])
            if reset_node:
                if reset_column is None:
                    return None, {"reason": "incremental_reset_release_header_absent"}
                reset_v = float(parts[reset_column])
            if encoding:
                if decision_columns is None:
                    return None, {"reason": "incremental_decision_header_absent"}
                v = [float(parts[index]) for index in decision_columns]
            else:
                v = float(parts[column])
        except ValueError:
            if reset_node and parts and parts[0].casefold() == "time":
                names = [field.casefold() for field in parts]
                label = f"v({reset_node})".casefold()
                if names.count(label) != 1:
                    return None, {"reason": "incremental_reset_release_header_mismatch"}
                reset_column = names.index(label)
            if encoding and parts and parts[0].casefold() == "time":
                names = [field.casefold() for field in parts]
                wanted = [f"v({node})".casefold() for node in encoding["output_nodes"]]
                if any(names.count(name) != 1 for name in wanted):
                    return None, {"reason": "incremental_decision_header_mismatch"}
                decision_columns = [names.index(name) for name in wanted]
            continue
        except IndexError:
            return None, {"reason": "incremental_decision_columns_incomplete"}
        times.append(t)
        vals.append(v)
        if reset_node:
            reset_values.append(reset_v)
    if len(times) < 64:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}

    bits, bmeta = _inc.sample_decisions(
        times, vals, td, period, v_high / 2.0, encoding=encoding,
        reset_release_values=reset_values if reset_node else None,
        window_clocks=int(decl["window_clocks"]) if reset_node else None)
    if not bits:
        return None, bmeta
    window = int(decl["window_clocks"])
    updates = int(decl["active_transfers"]) if reset_node else window
    if len(bits) < 2 * updates:
        return None, {"reason": _INC_SHORT_RECORD, "clocks": len(bits),
                      "window": window}
    samples, dmeta = _inc.decimate(
        bits, updates, order=int(decl["order"]), coeff=float(decl["coeff"]),
        feedback_delay=int(decl["feedback_delay_clocks"]),
        topology=decl.get("loop_topology", "cifb"), loop_model=model)
    if samples is None:
        return None, dmeta

    # THE FIRST WINDOW IS NOT A CONVERSION. The counter's power-up state is not
    # a declared reset instant, so its first boundary can fall anywhere inside
    # that window — the emitted deck's own condition line says exactly this.
    # Dropped rather than measured, because a window that is part of two
    # conversions is not one.
    samples = samples[1:]
    f_dec = 1.0 / (window * period)
    cycles = int(len(samples) * f_sig / f_dec)
    if cycles < _MIN_SIGNAL_CYCLES:
        return None, {"reason": _INC_TOO_FEW_CYCLES.format(
            n=_MIN_SIGNAL_CYCLES), "signal_hz": f_sig,
            "decimated_rate_hz": f_dec, "windows_available": len(samples),
            "cycles_available": cycles, "window_clocks": window}
    n = int(round(cycles * f_dec / f_sig))
    if n > len(samples):
        return None, {"reason": _INC_TOO_FEW_CYCLES.format(
            n=_MIN_SIGNAL_CYCLES), "windows_available": len(samples),
            "windows_required": n}
    grid = samples[-n:]
    top = n // 2 - 1
    if top < cycles + 1:
        return None, {"reason": _UNMEASURABLE_OUT_OF_BAND,
                      "signal_bin": cycles, "band_edge_bin": top,
                      "decimated_rate_hz": f_dec, "signal_hz": f_sig}
    power = _in_band_power(grid, top)
    sig_bins = {b for b in (cycles - 1, cycles, cycles + 1) if 1 <= b <= top}
    p_sig = sum(power[b - 1] for b in sig_bins)
    p_noise = sum(power) - p_sig
    if p_sig <= 0 or p_noise <= 0:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    return 10.0 * math.log10(p_sig / p_noise), {
        "method": "matched_incremental_decimation_then_dft",
        "conversion_mode": _inc.MODE_INCREMENTAL,
        "window_clocks": window, "order": decl["order"],
        "coeff": decl["coeff"],
        "feedback_delay_clocks": decl["feedback_delay_clocks"],
        "signal_hz": f_sig, "signal_bin": cycles, "cycles": cycles,
        "decimated_rate_hz": f_dec, "windows_decoded": dmeta["windows"],
        "windows_graded": n, "clocks_sampled": bmeta["clocks"],
        "first_clock_s": bmeta["first_clock_s"], "sample_clock_hz": 1.0 / period,
        "decision_alignment": bmeta["alignment"], "active_transfers": updates,
        "rows_read": len(times),
        "grid_rule": "one_sample_per_conversion_window_matched_decode",
    }


def _measure_corner_from_transient(block_dir: Path, project: Path,
                                   corner: dict, osr: float = 1.0
                                   ) -> Tuple[Optional[float], dict]:
    """Measure this corner's SNDR from the transient IT names, or say — by
    name — which precondition it does not have."""
    log = corner.get("ngspice_log")
    if not log:
        return None, {"reason": _UNMEASURABLE_NO_LOG}
    lp = (project / str(log))
    if not lp.is_file():
        lp = block_dir / Path(str(log)).name
    deck = lp.with_suffix("")
    if deck.suffix != ".sp":
        deck = Path(str(lp).replace(".ngspice.log", ".sp"))
    if not deck.is_file():
        return None, {"reason": _UNMEASURABLE_NO_DECK, "looked_for": str(deck)}
    text = deck.read_text(encoding="utf-8", errors="replace")
    md = _WRDATA_RE.search(text)
    if not md:
        # No dump: say so BEFORE the tone, because a deck with neither needs
        # both and the dump is the one a producer adds first.
        detail = {"reason": _UNMEASURABLE_NO_DUMP, "deck": deck.name}
        if not _SIN_RE.search(text):
            detail["also"] = _UNMEASURABLE_NO_TONE
        return None, detail
    dump = deck.parent / Path(md.group(1)).name
    if not dump.is_file():
        return None, {"reason": _UNMEASURABLE_NO_DUMP, "declared": md.group(1)}
    dump_text = dump.read_text(encoding="utf-8", errors="replace")
    # THE INSTRUMENT FOLLOWS THE DECLARED CONVERSION MODE. A deck the producer
    # stamped with an incremental decode declaration is decoded, not FFT'd:
    # reading an incremental converter with a free-running converter's
    # instrument under-reads it, and the deck is where the design says which
    # it is. No stamp => the FFT path, byte-for-byte as before.
    if _inc.read_stamp(text)[0] is not None:
        sndr, meta = sndr_db_incremental(text, dump_text)
    else:
        sndr, meta = sndr_db_from_transient(text, dump_text, osr=osr)
    if sndr is None:
        return None, meta
    meta["sndr_db"] = round(sndr, 3)
    return (sndr - _SNDR_INTERCEPT) / _SNDR_SLOPE, meta


def _load_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _enob_target(spec: dict) -> Optional[float]:
    """The ENOB floor from spec.json, or None when the block declares no
    ENOB / SNDR resolution target (=> not applicable)."""
    if not isinstance(spec, dict):
        return None
    specs = spec.get("specs")
    if not isinstance(specs, list):
        return None
    enob_target: Optional[float] = None
    sndr_target: Optional[float] = None
    for s in specs:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip().lower()
        # prefer an explicit target, else a min floor.
        val = s.get("target")
        if not (isinstance(val, (int, float)) and math.isfinite(val)):
            val = s.get("min")
        if not (isinstance(val, (int, float)) and math.isfinite(val)):
            continue
        if name == "enob":
            enob_target = float(val)
        elif name in ("sndr", "sndr_db", "snr", "snr_db"):
            sndr_target = float(val)
    if enob_target is not None:
        return enob_target
    if sndr_target is not None:
        return (sndr_target - _SNDR_INTERCEPT) / _SNDR_SLOPE
    return None


def _declared_osr(spec: dict) -> float:
    """The oversampling ratio the block's spec declares, else 1.0.

    1.0 is the Nyquist-rate case and makes the SNDR integration the whole
    span, which is what it has always been. A converter that declares an OSR
    is graded over `fclk / (2 * OSR)` instead — see `sndr_db_from_transient`
    and vibe-ic#2188."""
    if not isinstance(spec, dict):
        return 1.0
    for row in (spec.get("specs") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("name", "")).strip().lower() != "osr":
            continue
        for key in ("target", "min"):
            value = row.get(key)
            if (isinstance(value, (int, float)) and math.isfinite(value)
                    and value >= 1.0):
                return float(value)
    return 1.0


def _corner_enob(corner: dict) -> Optional[float]:
    """Read/derive one corner's ENOB, or None when unmeasured here."""
    if not isinstance(corner, dict):
        return None
    # A non-finite value (NaN / inf) is a non-converged / invalid sim
    # measurement, NOT a clean pass — treat it as UNMEASURED so it can never
    # silently clear the ENOB target (NaN < target is always False).
    direct = corner.get("enob")
    if isinstance(direct, (int, float)) and math.isfinite(direct):
        return float(direct)
    for k in ("sndr_db", "sndr", "snr_db", "snr"):
        v = corner.get(k)
        if isinstance(v, (int, float)) and math.isfinite(v):
            return (float(v) - _SNDR_INTERCEPT) / _SNDR_SLOPE
    return None


def _check_block(project: Path, block_dir: Path
                 ) -> Tuple[str, Optional[dict]]:
    """Return (status, detail). status in {PASS, FAIL, SKIP}."""
    spec = _load_json(block_dir / "spec.json")
    target = _enob_target(spec or {})
    if target is None:
        return "SKIP", None  # not an ENOB/SNDR-graded converter

    corners_doc = _load_json(block_dir / "corner_results.json")
    corners = (corners_doc or {}).get("corners")
    if not isinstance(corners, list) or not corners:
        return "UNMEASURED", {"block": block_dir.name, "reason": "no_corner_data",
                        "enob_target": target}
    osr = _declared_osr(spec or {})
    # THE PRODUCER'S OWN CAUSE OUTRANKS THIS GATE'S INFERENCE (vibe-ic#2188).
    # `analog_resolution_stimulus` is the step that decides whether a corner
    # deck can carry a tone and a dump at all, and when it refuses it records
    # WHY with the arithmetic — "the record holds 512 converter samples where
    # 12288 are needed". Re-deriving "no wrdata" from the deck's shape here
    # would be true and would send the reader to the wrong producer. Read what
    # the producer said; fall back to the deck only when it said nothing.
    stim = corners_doc.get("resolution_stimulus") if corners_doc else None
    producer_refusal: Optional[dict] = None
    if isinstance(stim, dict) and not stim.get("applied") and stim.get("reason"):
        producer_refusal = {"reason": str(stim["reason"]),
                            "producer": stim.get("producer"),
                            "detail": stim.get("detail")}
        for key in ("samples_available", "samples_required", "band_bins",
                    "osr", "record_s", "fclk_hz"):
            if stim.get(key) is not None:
                producer_refusal[key] = stim[key]

    measured: List[dict] = []
    failing: List[dict] = []
    unmeasurable: List[dict] = []
    for idx, c in enumerate(corners):
        c = c if isinstance(c, dict) else {}
        cname = c.get("name") or f"#{idx}"
        enob = _corner_enob(c)
        source = "corner_field"
        meta: dict = {}
        if enob is None:
            # NOT a shrug. Only a corner that was EXECUTED has a transient to
            # measure; one that was not completed is already accounted for by
            # its own cause upstream, and re-reporting it here as an ENOB hole
            # would double-count one absence as two.
            if producer_refusal is not None:
                meta = dict(producer_refusal)
            elif c.get("simulator_run") is True:
                enob, meta = _measure_corner_from_transient(
                    block_dir, project, c, osr=osr)
                source = "fft_of_a4_transient"
            else:
                meta = {"reason": "corner_not_executed",
                        "corner_provenance": c.get("_provenance")}
        if enob is None:
            unmeasurable.append({"corner": cname, **meta})
            continue
        rec = {"corner": cname, "enob": round(enob, 3), "source": source}
        if meta:
            rec["measurement"] = meta
        measured.append(rec)
        if enob < target - 1e-9:
            rec["shortfall_bits"] = round(target - enob, 3)
            failing.append(rec)

    if not measured:
        # NAME WHAT WAS MISSING, never a bare "no data". Each distinct reason
        # is a different thing a reader would have to go and fix.
        reasons = sorted({str(u.get("reason")) for u in unmeasurable
                          if u.get("reason")})
        return "UNMEASURED", {
            "block": block_dir.name,
            "reason": (reasons[0] if len(reasons) == 1
                       else "no_sndr_or_enob"),
            "reasons": reasons,
            "enob_target": target,
            "osr": osr,
            "resolution_stimulus": stim if isinstance(stim, dict) else None,
            "corners_seen": len(corners),
            "unmeasurable_corners": unmeasurable,
        }

    detail = {
        "block": block_dir.name,
        "enob_target": target,
        "osr": osr,
        "corners_measured": len(measured),
        "corners_unmeasured": len(unmeasurable),
        "measured_corners": measured,
        "unmeasurable_corners": unmeasurable,
        "worst_enob": min(m["enob"] for m in measured),
        "failing_corners": failing,
    }
    return ("FAIL" if failing else "PASS"), detail


def run_audit(project: Path) -> dict:
    analog = _pl.analog_dir(project)
    if not analog.is_dir():
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no_analog_dir", "blocks": []}

    results = []
    verdict = "SKIP"
    for bdir in sorted(d for d in analog.iterdir() if d.is_dir()):
        status, detail = _check_block(project, bdir)
        if status == "UNMEASURED":
            verdict = "UNMEASURED" if verdict != "FAIL" else verdict
            if detail:
                results.append({"status": "UNMEASURED", **detail})
            continue
        if status == "SKIP":
            if detail is not None:
                results.append({"status": "SKIP", **detail})
            continue
        results.append({"status": status, **(detail or {})})
        if status == "FAIL":
            verdict = "FAIL"
        elif verdict != "FAIL":
            verdict = "PASS"

    graded = [r for r in results if r.get("status") in ("PASS", "FAIL")]
    report = {
        "gate": GATE,
        "verdict": verdict,
        "blocks_graded": len(graded),
        "blocks": results,
    }
    # PUBLISH THE REASON, NOT ONLY THE REFUSAL. An UNMEASURED verdict exits 2,
    # and a consumer that reads only the exit code and the prose has no typed
    # reason to read: `_flow_reason_taxonomy.infer_nonverdict_reason` is
    # deliberately fail-closed, so an unclassified non-verdict is reported as
    # EXECUTION_ERROR — i.e. "this gate crashed". This gate did not crash. It
    # ran, it examined every block, and it found that no corner carries the
    # `sndr`/`enob` field the declared axis is graded on: a zero measured
    # denominator, which the taxonomy already has a word for.
    #
    # ZERO_DENOMINATOR is in `_flow_reason_taxonomy.INCOMPLETE`, NOT in
    # `SKIP_ELIGIBLE`, so naming it cannot launder this into a skip or a pass:
    # the step stays INCOMPLETE either way. The only thing that changes is
    # whether the reader is told the gate errored or told what it measured.
    if verdict == "UNMEASURED":
        report["reason_class"] = "ZERO_DENOMINATOR"
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    report = run_audit(args.project_dir.resolve())

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2,
                                              ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    print(f"[{verdict}] {GATE}")
    for b in report["blocks"]:
        if b.get("status") == "FAIL":
            for fc in b.get("failing_corners", []):
                print(f"  FAIL {b['block']} @ {fc['corner']}: ENOB "
                      f"{fc['enob']} < target {b['enob_target']} "
                      f"(short {fc.get('shortfall_bits')} bits)")
    # UNMEASURED IS NOT NOT-APPLICABLE (vibe-ic#693 family). Two different
    # situations shared the SKIP status and therefore shared rc 0:
    #
    #   no target/OSR in the spec  -> the formula genuinely does not apply to
    #                                 this block. Not a finding.
    #   target/OSR DECLARED but no corner data -> the block IS graded on this
    #                                 axis and nobody measured it. That is an
    #                                 absence, and it was reported as a pass.
    #
    # Found by RUNNING the gate on the published corpus, which nothing had done:
    # it prints `[SKIP]` and exits 0, so a wired flow counts it among the gates
    # that passed. The second case is now UNMEASURED and exits 2.
    if verdict == "FAIL":
        return 1
    if verdict == "UNMEASURED":
        print(f"[UNMEASURED] {GATE}: a block declares this axis and no data "
              f"measures it — not a pass.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
