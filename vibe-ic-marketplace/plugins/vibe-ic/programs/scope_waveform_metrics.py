#!/usr/bin/env python3
"""scope_waveform_metrics.py — deterministic scope-CSV metric extractor.

Parses a two-column oscilloscope CSV (``time,voltage``) and emits the six
waveform metrics that ``skills/analog-hw-measure/SKILL.md`` defines under
its "Waveform parsing" section, plus an optional per-spec PASS/FAIL when a
spec JSON is supplied.

The formulas are *exactly* the ones in SKILL.md — this program freezes them
so they run identically every time instead of being re-derived by an agent:

  * DC level      — mean of the LAST 20% of the capture window
  * Rise time     — 10%-90% transition time (first low→high edge)
  * Settling time — time to enter and STAY within ±2% of the final value
  * Overshoot     — (peak - final) / final × 100%
  * Frequency     — zero-crossing period measurement (mean-crossing based)
  * Jitter        — std-dev of the period over the N cycles measured

DESIGN PRINCIPLES (mirrors scope_periodic_pulse_check.py)
---------------------------------------------------------
* chip-AGNOSTIC: no benchmark/chip names, no hard-coded pins or register
  addresses. Everything is read from the CSV + optional spec JSON + CLI.
* deterministic: pure arithmetic over the samples; no RNG, no FFT library
  dependence (zero-crossing period, the SKILL's first-listed method).
* graceful on short / no-edge data: metrics that cannot be computed are
  reported as ``null`` with a ``notes[]`` entry (MISSING / SKIP), NEVER a
  crash and NEVER an over-flag. A spec on a null metric is reported
  ``SKIP`` (cannot evaluate), not ``FAIL``.

NO-FALSE-ALERT GUARDS
---------------------
* length floor: fewer than ``--min-samples`` (default 8) usable rows → the
  whole capture is reported as too-short; every metric null, exit 0, no
  PASS/FAIL emitted.
* edge guard: rise/settling/overshoot need a detectable step (a low→high
  excursion spanning the 10%/90% levels). If no such edge exists the metric
  is null with a note, not a fabricated number.
* frequency guard: needs ≥ ``--min-cycles`` (default 2) full mean-crossing
  periods before a frequency / jitter is reported.

SPEC JSON SHAPE (all keys optional; ``*_min`` / ``*_max`` per metric)
---------------------------------------------------------------------
    {
      "dc_level":       {"min": 1.75, "max": 1.85, "unit": "V"},
      "rise_time":      {"max": 5e-6, "unit": "s"},
      "settling_time":  {"max": 50e-6, "unit": "s"},
      "overshoot":      {"max": 10.0, "unit": "%"},
      "freq":           {"min": 0.9e6, "max": 1.1e6, "unit": "Hz"},
      "jitter":         {"max": 1e-9, "unit": "s"}
    }
A metric with no spec entry is reported but not graded. A spec entry whose
metric is null is graded ``SKIP``.

USAGE
-----
    python3 scope_waveform_metrics.py CAPTURE.csv
    python3 scope_waveform_metrics.py CAPTURE.csv --spec spec.json
    python3 scope_waveform_metrics.py CAPTURE.csv --json out/metrics.json

EXIT CODES
----------
    0 = metrics extracted (and, if --spec given, all gradeable specs PASS
        or SKIP). Also 0 when the capture is too short to grade.
    1 = at least one spec graded FAIL.
    2 = IO / parse / argument error (file missing, no usable rows, etc.)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAM = "scope_waveform_metrics"
VERSION = "1.0.0"

# The six metrics SKILL.md's "Waveform parsing" section defines, in order.
METRIC_KEYS = ("dc_level", "rise_time", "settling_time",
               "overshoot", "freq", "jitter")

# SKILL-fixed constants (do not invent new thresholds — these are the
# percentages written verbatim in the "Waveform parsing" section).
_DC_TAIL_FRACTION = 0.20     # mean of last 20% of capture window
_RISE_LOW_PCT = 0.10         # 10%-90% transition
_RISE_HIGH_PCT = 0.90
_SETTLE_BAND = 0.02          # ±2% of final value


# ---------------------------------------------------------------------------
# CSV I/O  (header row tolerated, junk rows skipped — graceful, never crash)
# ---------------------------------------------------------------------------
def load_waveform_csv(path: str) -> Tuple[List[float], List[float]]:
    """Read a two-column CSV ``time,voltage``.

    A non-numeric first row is treated as a header and skipped. Rows with
    fewer than two columns or non-numeric values are silently dropped, so a
    partially-corrupt capture degrades to "fewer usable samples" rather than
    a parse crash.
    """
    times: List[float] = []
    volts: List[float] = []
    with open(path, "r", newline="") as f:
        reader = csv.reader(f)
        first = True
        for row in reader:
            if not row:
                continue
            if first:
                first = False
                try:
                    float(row[0])
                    float(row[1])
                except (ValueError, IndexError):
                    continue  # header row
            if len(row) < 2:
                continue
            try:
                t = float(row[0])
                v = float(row[1])
            except ValueError:
                continue
            times.append(t)
            volts.append(v)
    return times, volts


# ---------------------------------------------------------------------------
# Pure-logic metric core (no I/O — fully unit-testable)
# ---------------------------------------------------------------------------
def _dc_level(times: List[float], volts: List[float]) -> float:
    """Mean of the last 20% of the capture window (SKILL: 'DC level')."""
    n = len(volts)
    tail = max(1, int(round(n * _DC_TAIL_FRACTION)))
    seg = volts[n - tail:]
    return sum(seg) / len(seg)


def _baseline(volts: List[float]) -> float:
    """Mean of the first 20% — the pre-step low level (symmetric to DC tail)."""
    n = len(volts)
    head = max(1, int(round(n * _DC_TAIL_FRACTION)))
    seg = volts[:head]
    return sum(seg) / len(seg)


def _interp_cross(times: List[float], volts: List[float],
                  start_idx: int, level: float) -> Optional[float]:
    """First time at/after ``start_idx`` where the trace rises through level.

    Linear interpolation between the bracketing samples. Returns None if the
    level is never crossed upward after start_idx.
    """
    for i in range(max(1, start_idx), len(volts)):
        if volts[i - 1] < level <= volts[i]:
            v0, v1 = volts[i - 1], volts[i]
            t0, t1 = times[i - 1], times[i]
            if v1 == v0:
                return t1
            frac = (level - v0) / (v1 - v0)
            return t0 + frac * (t1 - t0)
    return None


def _rise_time(times: List[float], volts: List[float],
               base: float, final: float) -> Optional[float]:
    """10%-90% rise time of the first low→high step (SKILL: 'Rise time')."""
    span = final - base
    if span <= 0:
        return None
    lo = base + _RISE_LOW_PCT * span
    hi = base + _RISE_HIGH_PCT * span
    t_lo = _interp_cross(times, volts, 1, lo)
    if t_lo is None:
        return None
    # 90% crossing must come AFTER the 10% crossing → find its sample index.
    start = 1
    for i in range(1, len(times)):
        if times[i] >= t_lo:
            start = i
            break
    t_hi = _interp_cross(times, volts, start, hi)
    if t_hi is None or t_hi < t_lo:
        return None
    return t_hi - t_lo


def _settling_time(times: List[float], volts: List[float],
                   final: float) -> Optional[float]:
    """Time from t0 to entering and STAYING within ±2% of final value.

    SKILL: 'Settling time — time to stay within ±2% of final value'.
    Walks backward to find the LAST sample outside the band; settling is the
    time of the next sample (first one that stays inside forever after).
    """
    if final == 0:
        # avoid a 0%-band degenerate; band defined relative to |final|.
        band = _SETTLE_BAND  # absolute fallback of ±0.02 V
    else:
        band = abs(final) * _SETTLE_BAND
    lo = final - band
    hi = final + band
    last_outside = -1
    for i in range(len(volts)):
        if volts[i] < lo or volts[i] > hi:
            last_outside = i
    if last_outside == -1:
        # Already inside the band for the whole window → settled at t0.
        return 0.0
    if last_outside + 1 >= len(times):
        # Never settles within the captured window.
        return None
    return times[last_outside + 1] - times[0]


def _overshoot(volts: List[float], final: float) -> Optional[float]:
    """(peak - final) / final × 100%  (SKILL: 'Overshoot')."""
    if final == 0:
        return None
    peak = max(volts)
    return (peak - final) / final * 100.0


def _periods_by_mean_crossing(times: List[float],
                              volts: List[float]) -> List[float]:
    """Successive periods via rising mean-crossings (SKILL: 'zero-crossing
    period measurement', taken about the signal mean so a DC-offset sine
    still works)."""
    mean = sum(volts) / len(volts)
    cross_times: List[float] = []
    for i in range(1, len(volts)):
        if volts[i - 1] < mean <= volts[i]:
            v0, v1 = volts[i - 1], volts[i]
            t0, t1 = times[i - 1], times[i]
            if v1 == v0:
                cross_times.append(t1)
            else:
                frac = (mean - v0) / (v1 - v0)
                cross_times.append(t0 + frac * (t1 - t0))
    return [cross_times[i + 1] - cross_times[i]
            for i in range(len(cross_times) - 1)]


def _frequency(periods: List[float]) -> Optional[float]:
    """Frequency = 1 / mean(period)  (SKILL: 'FFT peak or zero-crossing
    period measurement' — we use the deterministic zero-crossing path)."""
    if not periods:
        return None
    mean_p = sum(periods) / len(periods)
    if mean_p <= 0:
        return None
    return 1.0 / mean_p


def _jitter(periods: List[float]) -> Optional[float]:
    """Std-dev of the period over N cycles (SKILL: 'Jitter')."""
    n = len(periods)
    if n < 2:
        return None
    mean_p = sum(periods) / n
    var = sum((p - mean_p) ** 2 for p in periods) / n  # population std-dev
    return math.sqrt(var)


def extract_metrics(times: List[float], volts: List[float],
                    min_samples: int = 8,
                    min_cycles: int = 2) -> Dict:
    """Compute all six SKILL metrics with graceful degradation.

    Returns a dict with ``metrics`` (value-or-None per key) and ``notes``
    (human-readable MISSING/SKIP reasons). Never raises on short/no-edge
    data.
    """
    metrics: Dict[str, Optional[float]] = {k: None for k in METRIC_KEYS}
    notes: List[str] = []

    n = len(volts)
    if n < min_samples:
        notes.append(
            f"capture has only {n} usable sample(s) (< min {min_samples}); "
            f"all metrics SKIPPED (too short to measure)"
        )
        return {"metrics": metrics, "notes": notes,
                "samples": n, "too_short": True}

    # Monotonic-time sanity (graceful: just note it, don't crash / over-flag).
    if any(times[i] <= times[i - 1] for i in range(1, n)):
        notes.append("time column is not strictly increasing; "
                     "metrics computed on raw sample order")

    base = _baseline(volts)
    final = _dc_level(times, volts)
    metrics["dc_level"] = final

    rt = _rise_time(times, volts, base, final)
    metrics["rise_time"] = rt
    if rt is None:
        notes.append("rise_time: no detectable 10%-90% low→high step "
                     "(no step edge) — MISSING")

    st = _settling_time(times, volts, final)
    metrics["settling_time"] = st
    if st is None:
        notes.append("settling_time: signal never stays within ±2% of final "
                     "value inside the window — MISSING")

    ov = _overshoot(volts, final)
    metrics["overshoot"] = ov
    if ov is None:
        notes.append("overshoot: final value is 0; ratio undefined — MISSING")

    periods = _periods_by_mean_crossing(times, volts)
    if len(periods) >= max(1, min_cycles):
        metrics["freq"] = _frequency(periods)
        metrics["jitter"] = _jitter(periods)
        if metrics["jitter"] is None:
            notes.append(f"jitter: only {len(periods)} period(s) measured "
                         f"(need ≥ 2 for std-dev) — MISSING")
    else:
        notes.append(
            f"freq/jitter: only {len(periods)} full mean-crossing period(s) "
            f"(< min {min_cycles}); not a periodic capture — MISSING"
        )

    return {"metrics": metrics, "notes": notes,
            "samples": n, "too_short": False,
            "cycles_measured": len(periods)}


# ---------------------------------------------------------------------------
# Spec grading (per-metric PASS / FAIL / SKIP — no over-flag on null metrics)
# ---------------------------------------------------------------------------
def grade_against_spec(metrics: Dict[str, Optional[float]],
                       spec: Dict) -> Tuple[List[Dict], bool]:
    """Grade each metric that has a spec entry. Returns (rows, all_pass).

    A null metric with a spec is graded ``SKIP`` (cannot evaluate) so a
    missing edge / non-periodic capture never produces a false FAIL.
    """
    rows: List[Dict] = []
    all_pass = True
    for key in METRIC_KEYS:
        sp = spec.get(key)
        if not isinstance(sp, dict):
            continue
        val = metrics.get(key)
        lo = sp.get("min")
        hi = sp.get("max")
        unit = sp.get("unit", "")
        if val is None:
            rows.append({"metric": key, "value": None, "unit": unit,
                         "spec_min": lo, "spec_max": hi, "status": "SKIP",
                         "reason": "metric unavailable (graceful)"})
            continue
        status = "PASS"
        if lo is not None and val < lo:
            status = "FAIL"
        if hi is not None and val > hi:
            status = "FAIL"
        if status == "FAIL":
            all_pass = False
        rows.append({"metric": key, "value": val, "unit": unit,
                     "spec_min": lo, "spec_max": hi, "status": status})
    return rows, all_pass


def _load_spec(path: str) -> Optional[Dict]:
    try:
        data = json.loads(Path(path).read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Extract DC/rise/settling/overshoot/freq/jitter from a "
                    "scope CSV (time,voltage) using analog-hw-measure SKILL "
                    "formulas; optional per-spec PASS/FAIL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("csv", help="Scope capture CSV: two columns time,voltage "
                                "(header row tolerated).")
    ap.add_argument("--spec", default=None,
                    help="Optional spec JSON with per-metric min/max; grades "
                         "PASS/FAIL (null metric → SKIP).")
    ap.add_argument("--json", default=None,
                    help="Write the full result as JSON to this path.")
    ap.add_argument("--min-samples", type=int, default=8,
                    help="Length floor: fewer usable rows → all metrics "
                         "SKIPPED, no PASS/FAIL emitted (default 8).")
    ap.add_argument("--min-cycles", type=int, default=2,
                    help="Minimum full mean-crossing periods before freq/"
                         "jitter are reported (default 2).")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"ERROR: CSV not found: {args.csv}", file=sys.stderr)
        return 2
    try:
        times, volts = load_waveform_csv(args.csv)
    except OSError as e:
        print(f"ERROR: cannot read CSV: {e}", file=sys.stderr)
        return 2
    if not volts:
        print(f"ERROR: no usable (time,voltage) rows in {args.csv}",
              file=sys.stderr)
        return 2

    spec: Dict = {}
    if args.spec:
        spec_loaded = _load_spec(args.spec)
        if spec_loaded is None:
            print(f"ERROR: cannot parse --spec JSON: {args.spec}",
                  file=sys.stderr)
            return 2
        spec = spec_loaded

    ext = extract_metrics(times, volts,
                          min_samples=args.min_samples,
                          min_cycles=args.min_cycles)
    metrics = ext["metrics"]

    spec_rows: List[Dict] = []
    all_pass = True
    graded = False
    if spec and not ext["too_short"]:
        spec_rows, all_pass = grade_against_spec(metrics, spec)
        graded = any(r["status"] in ("PASS", "FAIL") for r in spec_rows)

    result = {
        "program": PROGRAM,
        "version": VERSION,
        "source": str(csv_path),
        "samples": ext["samples"],
        "too_short": ext["too_short"],
        "metrics": metrics,
        "notes": ext["notes"],
        "spec_results": spec_rows,
        "all_pass": all_pass if (spec and graded) else None,
    }

    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    # Human-readable summary to stdout (always print metric table).
    print(f"=== scope_waveform_metrics ({ext['samples']} samples) ===")

    def _fmt(v: Optional[float]) -> str:
        if v is None:
            return "MISSING"
        if abs(v) != 0 and (abs(v) < 1e-3 or abs(v) >= 1e4):
            return f"{v:.4e}"
        return f"{v:.6g}"

    units = {"dc_level": "V", "rise_time": "s", "settling_time": "s",
             "overshoot": "%", "freq": "Hz", "jitter": "s"}
    for k in METRIC_KEYS:
        print(f"  {k:<14}: {_fmt(metrics[k]):>14}  {units[k]}")
    for note in ext["notes"]:
        print(f"  note: {note}")

    if spec_rows:
        print("--- spec grading ---")
        for r in spec_rows:
            print(f"  [{r['status']}] {r['metric']}: "
                  f"value={_fmt(r['value'])} "
                  f"min={r['spec_min']} max={r['spec_max']} {r['unit']}")

    if spec and graded:
        verdict = "PASS" if all_pass else "FAIL"
        print(f"VERDICT: {verdict}")
        return 0 if all_pass else 1

    if spec and not graded:
        print("VERDICT: SKIP (no gradeable spec/metric pair)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
