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

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _path_layout as _pl

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


def sndr_db_from_transient(deck_text: str, dump_text: str,
                           column: int = 1) -> Tuple[Optional[float], dict]:
    """SNDR in dB from one corner's transient, or (None, {"reason": ...}).

    The method the brief names and the one every converter datasheet uses:
    resample the output onto a uniform grid over a WHOLE NUMBER of signal
    cycles, FFT it, and compare the signal bin's power against everything else
    in the spectrum except DC. Coherent sampling makes a rectangular window
    correct; the bin the tone lands in is `cycles`, exactly, by construction.

    chip-AGNOSTIC: the signal frequency, the window and the dump path all come
    from the DECK THIS CORNER RAN, never from a table here.
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
    grid = _resample_pow2(times, vals, t0, t1)
    if grid is None:
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
    # The tone plus its two immediate neighbours: a whole-cycle window puts the
    # tone in one bin, and taking the neighbours with it makes the answer
    # robust to a solver whose last step lands a hair off the boundary. They
    # are removed from the noise sum too, so no power is counted twice.
    sig_bins = {b for b in (bin_sig - 1, bin_sig, bin_sig + 1)
                if 1 <= b < half}
    p_sig = sum(power[b - 1] for b in sig_bins)
    p_noise = sum(power) - p_sig
    if p_sig <= 0 or p_noise <= 0:
        return None, {"reason": _UNMEASURABLE_NO_ROWS, "rows": len(times)}
    return 10.0 * math.log10(p_sig / p_noise), {
        "method": "fft_signal_bin_vs_rest",
        "signal_hz": f_sig, "signal_bin": bin_sig,
        "cycles": cycles, "fft_points": n, "rows_read": len(times),
    }


def _measure_corner_from_transient(block_dir: Path, project: Path,
                                   corner: dict) -> Tuple[Optional[float],
                                                          dict]:
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
    sndr, meta = sndr_db_from_transient(
        text, dump.read_text(encoding="utf-8", errors="replace"))
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
            if c.get("simulator_run") is True:
                enob, meta = _measure_corner_from_transient(
                    block_dir, project, c)
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
            "corners_seen": len(corners),
            "unmeasurable_corners": unmeasurable,
        }

    detail = {
        "block": block_dir.name,
        "enob_target": target,
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
