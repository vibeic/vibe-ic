#!/usr/bin/env python3
"""scope_periodic_pulse_check.py — Layer-3 hardware attestation gate.

Generic SCPI-driven oscilloscope check for "channel <N> must NOT show a
periodic LOW-pulse pattern with period P and pulse-width W after some
external state has been triggered."

WHY THIS EXISTS — motivating specimen
-------------------------------------
v0.64's static analyser `timer_freeze_after_state_check.py` flagged a
real bug in `wake_ctrl.v` where a wakeup timer continued generating
periodic pulses after the bus had already entered the awake state.
v0.65 adds a runtime hardware check (this program): a Keysight DSO-X
3014T probed the offending IO line, captured a 50 ms window, and found
10 LOW pulses — every one ~26 µs wide, gaps 5.000-5.001 ms apart —
which matched the tITO-shaped buggy waveform predicted from the RTL
defect. The static checker and this scope check are COMPLEMENTARY
layers: the static check screens before silicon, this one attests on
silicon.

Generalised from an earlier IC-specific hardware-debug script (v0.64,
~280 LOC with hard-coded device IDs and ID_BUS / tITO terminology).
This file is the IC-agnostic re-implementation.

DESIGN
------
* Stdlib only at import time; `usbtmc` is imported lazily, ONLY when
  the program is actually told to talk to a scope. Tests and CI use
  ``--mock-samples-csv`` to feed a captured waveform from disk and
  exercise the same pulse-detect + verdict logic without any USB.
* All hardware-specific knobs (USB VID/PID, channel, vertical scale,
  thresholds, trigger slope, period of interest, accepted pulse-width
  band, capture span) are CLI args — defaults match Keysight DSO-X
  3014T but are flagged as vendor-specific and meant to be overridden.

VERDICT MODEL
-------------
* PASS — 0 or 1 in-band LOW pulse in window
* PASS (note) — >=2 in-band pulses but no two consecutive gaps within
  ``--period-tol-ms`` of ``--period-ms`` ("not the timer-bug pattern")
* FAIL — >=2 in-band pulses with at least one consecutive-gap match

EXIT CODES
----------
* 0 — PASS
* 1 — FAIL
* 2 — argument / scope / capture error
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


# Vendor-specific defaults — Keysight DSO-X 3014T.
# Override --vid/--pid for any other USBTMC scope.
_DEFAULT_VID = 0x2A8D
_DEFAULT_PID = 0x1768


@dataclass
class Pulse:
    fall_us: float    # falling-edge time (µs from window start)
    rise_us: float    # rising-edge time
    width_us: float   # rise - fall


# ---------------------------------------------------------------------------
# Pure-logic core (no scope, no USB, fully unit-testable)
# ---------------------------------------------------------------------------
def detect_low_pulses(
    times_us: List[float],
    voltages: List[float],
    low_v: float,
    high_v: float,
    pulse_min_us: float,
    pulse_max_us: float,
) -> List[Pulse]:
    """Find LOW pulses with hysteresis.

    A pulse is a falling crossing of ``low_v`` followed by a rising
    crossing of ``high_v``. Only pulses whose width is in
    ``[pulse_min_us, pulse_max_us]`` are returned.
    """
    pulses: List[Pulse] = []
    state = "high"  # idle-high digital line
    fall_t: Optional[float] = None
    for t, val in zip(times_us, voltages):
        if state == "high" and val < low_v:
            state = "low"
            fall_t = t
        elif state == "low" and val > high_v:
            state = "high"
            if fall_t is not None:
                w = t - fall_t
                if pulse_min_us <= w <= pulse_max_us:
                    pulses.append(Pulse(fall_us=fall_t, rise_us=t, width_us=w))
                fall_t = None
    return pulses


def verdict(
    pulses: List[Pulse],
    period_ms: float,
    period_tol_ms: float,
    expect: str = "absent",
    min_periodic: int = 1,
) -> Tuple[bool, str]:
    """Classify the pulse pattern against the user's expectation.

    ``expect`` values:
      * ``"absent"`` (default): PASS when the forbidden periodic pattern is
        NOT present — i.e. the timer correctly froze / the RTL doesn't
        leak spurious pulses. This is the "freeze-after-state" regression
        shape and matches the v0.64 ``timer_freeze_after_state_check``
        static rule.
      * ``"present"``: PASS when the pattern IS present with at least
        ``min_periodic`` consecutive tITO gaps. Used to POSITIVELY confirm
        that the pre-awake idle wake pulses fire as required by the spec
        (if they were missing, the IC would fail host-wake-up).

    Returns ``(passed, message)``. ``min_periodic`` only affects the
    ``present`` path; ``absent`` still PASSes for 0-1 pulses.
    """
    gaps_ms = [
        (pulses[i + 1].fall_us - pulses[i].fall_us) / 1000.0
        for i in range(len(pulses) - 1)
    ]
    periodic_count = sum(1 for g in gaps_ms if abs(g - period_ms) <= period_tol_ms)

    if expect == "present":
        if periodic_count >= min_periodic:
            return True, (
                f"{len(pulses)} in-band pulses; {periodic_count} consecutive gaps "
                f"within {period_tol_ms} ms of {period_ms} ms — "
                f"expected periodic pattern confirmed (PASS, ≥{min_periodic})"
            )
        return False, (
            f"{len(pulses)} in-band pulses; only {periodic_count} consecutive "
            f"gaps match {period_ms} ± {period_tol_ms} ms (need ≥ {min_periodic}) "
            f"— expected periodic pattern MISSING (FAIL)"
        )

    # expect == "absent" (default)
    if len(pulses) <= 1:
        return True, (
            f"{len(pulses)} in-band pulse(s) in window — "
            f"no periodic pattern (PASS)"
        )
    if periodic_count >= 1:
        return False, (
            f"{len(pulses)} in-band pulses; {periodic_count} consecutive gaps "
            f"within {period_tol_ms} ms of the target period {period_ms} ms — "
            f"forbidden periodic pattern present (FAIL)"
        )
    return True, (
        f"{len(pulses)} in-band pulses but no consecutive gap matches "
        f"{period_ms} ± {period_tol_ms} ms — not the timer-bug pattern (PASS)"
    )


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------
def load_samples_csv(path: str) -> Tuple[List[float], List[float]]:
    """Read a two-column CSV ``time_us,voltage`` (header row tolerated)."""
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
                # Skip header row if non-numeric
                try:
                    float(row[0])
                except ValueError:
                    continue
            if len(row) < 2:
                continue
            try:
                times.append(float(row[0]))
                volts.append(float(row[1]))
            except ValueError:
                continue
    return times, volts


def save_samples_csv(path: str, times_us: List[float], volts: List[float]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_us", "voltage"])
        for t, v in zip(times_us, volts):
            w.writerow([f"{t:.3f}", f"{v:.4f}"])


# ---------------------------------------------------------------------------
# SCPI helpers (only imported when the user is actually talking to a scope)
# ---------------------------------------------------------------------------
def _scope_open(vid: int, pid: int):
    import usbtmc  # type: ignore  # lazy import — keeps tests + CI usbtmc-free
    inst = usbtmc.Instrument(vid, pid)
    inst.timeout = 10  # seconds
    inst.write("*CLS")
    return inst


def _scope_configure(
    inst,
    channel: int,
    span_ms: float,
    probe_attenuation: float,
    vert_scale_v_per_div: float,
    vert_offset_v: float,
    trigger_slope: str,
    trigger_level_v: float,
) -> None:
    ch = f"CHAN{channel}"
    inst.write(":STOP")
    inst.write(f":{ch}:DISPLAY ON")
    inst.write(f":{ch}:PROBE {probe_attenuation}")
    inst.write(f":{ch}:COUPLING DC")
    inst.write(f":{ch}:SCALE {vert_scale_v_per_div}")
    inst.write(f":{ch}:OFFSET {vert_offset_v}")
    inst.write(f":{ch}:BWLIMIT ON")
    inst.write(f":TIMEBASE:RANGE {span_ms * 1e-3}")
    inst.write(":TIMEBASE:REFERENCE LEFT")
    inst.write(":TRIGGER:MODE EDGE")
    inst.write(f":TRIGGER:EDGE:SOURCE {ch}")
    inst.write(f":TRIGGER:EDGE:SLOPE {trigger_slope}")
    inst.write(f":TRIGGER:EDGE:LEVEL {trigger_level_v}")
    inst.write(":ACQUIRE:TYPE NORMAL")
    inst.write(":ACQUIRE:COMPLETE 100")
    inst.write(f":WAVEFORM:SOURCE {ch}")
    inst.write(":WAVEFORM:FORMAT WORD")
    inst.write(":WAVEFORM:BYTEORDER LSBFIRST")
    inst.write(":WAVEFORM:POINTS:MODE RAW")
    inst.write(":WAVEFORM:POINTS 50000")


def _scope_arm_and_wait(inst, timeout_s: float) -> bool:
    inst.write(":SINGLE")
    deadline = time.time() + timeout_s
    # watchdog-exempt: bounded hardware-scope trigger poll — the wall-clock
    # `deadline` (time.time()+timeout_s) hard-bounds it; it cannot spin forever
    # and launches no sub-process (a pyvisa instrument query, not an EDA tool).
    while time.time() < deadline:
        time.sleep(0.2)
        try:
            ter = int(inst.ask(":TER?").strip())
            if ter == 1:
                return True
        except Exception:
            continue
    return False


def _scope_fetch_waveform(inst) -> Tuple[List[float], List[float]]:
    import struct
    pre = inst.ask(":WAVEFORM:PREAMBLE?").strip().split(",")
    if len(pre) < 10:
        raise RuntimeError(f"unexpected preamble: {pre}")
    xinc, xorg, xref = float(pre[4]), float(pre[5]), float(pre[6])
    yinc, yorg, yref = float(pre[7]), float(pre[8]), float(pre[9])

    raw = inst.ask_raw(b":WAVEFORM:DATA?\n")
    if raw[0:1] != b"#":
        raise RuntimeError(f"bad block header: {raw[:8]!r}")
    n = int(raw[1:2])
    nbytes = int(raw[2:2 + n])
    data = raw[2 + n:2 + n + nbytes]
    samples = struct.unpack(f"<{nbytes // 2}H", data)
    voltages = [(s - yref) * yinc + yorg for s in samples]
    times_us = [(i - xref) * xinc * 1e6 + xorg * 1e6 for i in range(len(samples))]
    return times_us, voltages


# ---------------------------------------------------------------------------
# Capture orchestration
# ---------------------------------------------------------------------------
def capture_from_scope(args: argparse.Namespace) -> Tuple[List[float], List[float]]:
    try:
        inst = _scope_open(args.vid, args.pid)
    except ImportError:
        print("ERROR: python-usbtmc not installed. "
              "Run: pip install --user --break-system-packages python-usbtmc pyusb",
              file=sys.stderr)
        raise SystemExit(2)
    except Exception as e:
        print(f"ERROR: cannot open scope (vid=0x{args.vid:04x} "
              f"pid=0x{args.pid:04x}): {e}", file=sys.stderr)
        raise SystemExit(2)

    try:
        idn = inst.ask("*IDN?").strip()
    except Exception as e:
        print(f"ERROR: scope not responding to *IDN?: {e}", file=sys.stderr)
        raise SystemExit(2)
    print(f"connected: {idn}")

    if not args.no_configure:
        print(f"configuring CH{args.channel}, {args.span_ms} ms span, "
              f"{args.trigger_slope} edge trigger @ {args.trigger_level_v} V")
        _scope_configure(
            inst, args.channel, args.span_ms,
            args.probe_attenuation, args.vert_scale_v_per_div,
            args.vert_offset_v, args.trigger_slope, args.trigger_level_v,
        )

    print(f"arming single-shot, waiting up to {args.trigger_timeout_s} s for "
          f"{args.trigger_slope.lower()} edge on CH{args.channel}...")
    triggered = _scope_arm_and_wait(inst, args.trigger_timeout_s)
    if not triggered:
        # No edge within the window. Under --expect absent this is the
        # strongest possible evidence of PASS — the line really is silent.
        # Force-stop the (never-fired) single-shot and read whatever the
        # scope has so we still produce an artifact to save / inspect.
        inst.write(":STOP")
        try:
            times_us, volts = _scope_fetch_waveform(inst)
        except Exception as e:
            print(f"note: could not read waveform after no-trigger timeout: {e}",
                  file=sys.stderr)
            times_us, volts = [], []
        try:
            inst.close()
        except Exception:
            pass
        if args.expect == "absent":
            # Short-circuit with a zero-pulse artifact. main() will run
            # verdict() on the empty pulse list and produce PASS.
            print(f"no edge in {args.trigger_timeout_s:.0f}s — line silent "
                  f"(consistent with --expect absent).")
            return times_us, volts
        # expect=present: this is a real failure — we WANTED pulses and got none.
        print(f"ERROR: no trigger within {args.trigger_timeout_s:.0f}s on "
              f"CH{args.channel}; --expect present requires pulses",
              file=sys.stderr)
        raise SystemExit(1)

    time.sleep(args.span_ms / 1000.0 + 0.3)
    inst.write(":STOP")
    times_us, volts = _scope_fetch_waveform(inst)
    try:
        inst.close()
    except Exception:
        pass
    return times_us, volts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generic SCPI-scope check for periodic LOW-pulse patterns "
                    "on a digital IO line. v0.65 Layer-3 hardware attestation.",
    )

    # USB / scope identity (vendor-specific defaults — override for other scopes)
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=_DEFAULT_VID,
                    help="USB vendor ID (vendor-specific default for "
                         "Keysight DSO-X 3014T; override for other scopes)")
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=_DEFAULT_PID,
                    help="USB product ID (vendor-specific default for "
                         "Keysight DSO-X 3014T; override for other scopes)")

    # Channel + timebase
    ap.add_argument("--channel", type=int, default=4,
                    help="Scope channel the IO line is wired to (1..4)")
    ap.add_argument("--span-ms", type=float, default=50.0,
                    help="Capture window in ms (default 50)")

    # Period / pulse-width / verdict knobs
    ap.add_argument("--period-ms", type=float, default=5.0,
                    help="Forbidden inter-pulse period to test for, in ms")
    ap.add_argument("--period-tol-ms", type=float, default=1.0,
                    help="Tolerance for period match (ms)")
    ap.add_argument("--pulse-min-us", type=float, default=10.0,
                    help="Minimum acceptable pulse width (µs)")
    ap.add_argument("--pulse-max-us", type=float, default=100.0,
                    help="Maximum acceptable pulse width (µs)")

    # Positive / negative verification
    ap.add_argument("--expect", choices=["present", "absent"], default="absent",
                    help="What to PASS on: 'absent' (default) PASSes when the "
                         "forbidden periodic pattern is NOT present "
                         "(freeze-after-state regression). 'present' PASSes "
                         "when the pattern IS present — use for positively "
                         "verifying that required idle-wake pulses do emit "
                         "as spec'd (POR-to-awake window). See v0.65.1 "
                         "release note.")
    ap.add_argument("--min-periodic", type=int, default=1,
                    help="With --expect present, require at least N "
                         "consecutive inter-pulse gaps matching the target "
                         "period before declaring PASS (default 1; raise to "
                         "5 or more for high-confidence existence proof).")

    # Vertical / threshold
    ap.add_argument("--low-threshold-v", type=float, default=0.8,
                    help="Hysteresis low threshold (V)")
    ap.add_argument("--high-threshold-v", type=float, default=2.0,
                    help="Hysteresis high threshold (V)")
    ap.add_argument("--probe-attenuation", type=float, default=10.0,
                    help="Probe attenuation ratio (e.g. 10 for 10:1)")
    ap.add_argument("--vert-scale-v-per-div", type=float, default=1.0,
                    help="Vertical scale (V per division)")
    ap.add_argument("--vert-offset-v", type=float, default=1.5,
                    help="Vertical offset (V)")

    # Trigger
    ap.add_argument("--trigger-slope", choices=["NEGATIVE", "POSITIVE"],
                    default="NEGATIVE", help="Trigger edge slope")
    ap.add_argument("--trigger-level-v", type=float, default=1.5,
                    help="Trigger level (V)")
    ap.add_argument("--trigger-timeout-s", type=float, default=30.0,
                    help="Seconds to wait for first edge")

    # I/O
    ap.add_argument("--save-csv",
                    help="Dump captured (time_us,voltage) samples to CSV")
    ap.add_argument("--no-configure", action="store_true",
                    help="Skip channel/trigger/timebase setup; "
                         "use whatever scope state is already loaded")
    ap.add_argument("--mock-samples-csv",
                    help="Read samples from CSV instead of scope. Two columns: "
                         "time_us,voltage. Enables CI / unit testing without "
                         "any USB scope.")

    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.mock_samples_csv:
        try:
            times_us, volts = load_samples_csv(args.mock_samples_csv)
        except FileNotFoundError:
            print(f"ERROR: --mock-samples-csv file not found: "
                  f"{args.mock_samples_csv}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"ERROR: cannot read --mock-samples-csv: {e}", file=sys.stderr)
            return 2
        if not times_us:
            print("ERROR: --mock-samples-csv had no usable rows",
                  file=sys.stderr)
            return 2
        print(f"loaded {len(volts)} samples from {args.mock_samples_csv} "
              f"({(times_us[-1] - times_us[0]) / 1000.0:.1f} ms)")
    else:
        try:
            times_us, volts = capture_from_scope(args)
        except SystemExit as e:
            return int(e.code) if e.code is not None else 2
        print(f"captured {len(volts)} samples spanning "
              f"{(times_us[-1] - times_us[0]) / 1000.0:.1f} ms")

    if args.save_csv and not args.mock_samples_csv:
        try:
            save_samples_csv(args.save_csv, times_us, volts)
            print(f"raw samples -> {args.save_csv}")
        except Exception as e:
            print(f"WARN: cannot write --save-csv: {e}", file=sys.stderr)

    pulses = detect_low_pulses(
        times_us, volts,
        low_v=args.low_threshold_v,
        high_v=args.high_threshold_v,
        pulse_min_us=args.pulse_min_us,
        pulse_max_us=args.pulse_max_us,
    )
    print(f"detected {len(pulses)} LOW pulses in width range "
          f"[{args.pulse_min_us:.0f}, {args.pulse_max_us:.0f}] µs")
    for i, p in enumerate(pulses[:20]):
        print(f"  pulse {i}: fall @ {p.fall_us / 1000:7.3f} ms, "
              f"width {p.width_us:6.1f} µs")
    if len(pulses) > 20:
        print(f"  ... ({len(pulses) - 20} more)")

    passed, msg = verdict(
        pulses, args.period_ms, args.period_tol_ms,
        expect=args.expect, min_periodic=args.min_periodic,
    )
    print(f"VERDICT: {'PASS' if passed else 'FAIL'} [--expect {args.expect}] — {msg}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
