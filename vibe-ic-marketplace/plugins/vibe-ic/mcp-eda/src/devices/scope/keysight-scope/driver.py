#!/usr/bin/env python3
"""mcp-eda / keysight-scope / driver.py — JSON-IO scope driver.

Standalone CLI driver for Keysight InfiniiVision-class oscilloscopes
(verified on DSO-X 3014T, VID 0x2a8d / PID 0x1768). Spoken to by the
mcp-eda device registry (see src/devices/_registry.js); also runnable
by hand for one-off debug:

    python3 driver.py --mode pulse_check --json-args '{"channel":4,"span_ms":50}'

Why this lives in mcp-eda (not in vibe-ic-marketplace):
    Device IO is a pure capability of the EDA server side. Plugin skills
    request "go look at scope channel 4 for a periodic pulse" via MCP and
    the server arbitrates the hardware. Keeping driver code on the server
    side prevents N skill-side reimplementations + N USB-permission knot.

Origin:
    Generalised from an earlier IC-specific hardware-debug script (v0.64)
    that was the live-hardware companion to the v0.64 plugin program
    `timer_freeze_after_state_check.py`. The static checker found the
    missing freeze; this driver confirms it on real silicon by detecting
    the periodic 5ms wake-pulse pattern that the bug emits.

JSON-IO contract:
    stdin OR --json-args '<json>' (use '-' to mean stdin)
        → a JSON object whose keys match the tool's manifest.json schema.
    stdout
        → exactly ONE JSON object on success or detected FAIL.
        → progress / debug logs go to STDERR (never stdout).
    exit codes:
        0 = success (capture OK and, if pulse_check, verdict == PASS)
        1 = detected FAIL (pulse_check found a periodic-pulse pattern
            OR recoverable runtime error: timeout, protocol, busy)
        2 = arg / connection / scope-IO error (device_not_found,
            permission_denied, vendor_tool_not_found, invalid_argument)

v0.67: All error returns go through the DeviceError taxonomy in
`../../../_shared/errors.py`. MCP clients can branch on `error_code`
without parsing English messages.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Shared DeviceError taxonomy. Adds `_shared/` to sys.path so we can import
# the error base classes from the neighbour directory.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.normpath(os.path.join(_HERE, "..", "..", "_shared"))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from errors import (  # noqa: E402
    DeviceError,
    DeviceNotFoundError,
    PermissionError_,
    DeviceTimeoutError,
    DeviceProtocolError,
    VendorToolNotFoundError,
    DeviceBusyError,
    InvalidArgumentError,
    EXIT_FOR_CODE,
)


# ---------------------------------------------------------------------------
# Defaults — Keysight InfiniiVision DSO-X 3000 series
# ---------------------------------------------------------------------------
# Caller may override `pid` via --json-args. If the override is omitted, the
# driver auto-probes _CANDIDATE_PIDS in order and uses the first that opens.
# Adding a new model = append to this list.
_DEFAULT_VID = 0x2a8d
_DEFAULT_PID = 0x1768                           # legacy default for backward compat
_CANDIDATE_PIDS = (
    0x1768,    # DSO-X 3014T
    0x1766,    # DSO-X 3024G
    0x1764,    # DSO-X 3034T   (extend as new models are encountered)
    0x1760,    # DSO-X 3000 generic
)

# Hysteresis rails for digital edge detection on a 3.3V signal.
_DEFAULT_LOW_V  = 0.8
_DEFAULT_HIGH_V = 2.0


@dataclass
class Pulse:
    fall_us: float
    rise_us: float
    width_us: float


# ---------------------------------------------------------------------------
# usbtmc lazy import — keep --help working without deps installed
# ---------------------------------------------------------------------------
def _import_usbtmc():
    try:
        import usbtmc  # type: ignore
        return usbtmc, None
    except ImportError as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# SCPI helpers
# ---------------------------------------------------------------------------
def open_scope(vid: int, pid: int):
    usbtmc, err = _import_usbtmc()
    if usbtmc is None:
        raise VendorToolNotFoundError(
            f"python-usbtmc not installed ({err}). "
            "Install: pip install --user --break-system-packages python-usbtmc pyusb",
            context={"vid": vid, "pid": pid},
        )
    # If caller passes the legacy default PID and the device isn't there,
    # auto-probe the candidate list — covers DSO-X 3014T / 3024G / 3034T
    # without forcing the agent to know which model is plugged in.
    pids_to_try: List[int] = [pid]
    if pid == _DEFAULT_PID:
        pids_to_try = list(_CANDIDATE_PIDS)
    last_err: Optional[Exception] = None
    inst = None
    for try_pid in pids_to_try:
        try:
            inst = usbtmc.Instrument(vid, try_pid)
            pid = try_pid
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            low = msg.lower()
            if "permission" in low or "access" in low or "errno 13" in low:
                # Permission errors are deterministic — don't keep probing.
                raise PermissionError_(
                    f"permission denied opening scope VID={vid:#06x} "
                    f"PID={try_pid:#06x}: {msg}",
                    context={"vid": vid, "pid": try_pid},
                )
            continue
    if inst is None:
        raise DeviceNotFoundError(
            f"scope not found at VID={vid:#06x} (probed PIDs="
            f"{','.join(f'{p:#06x}' for p in pids_to_try)}): {last_err}",
            context={"vid": vid, "probed_pids": pids_to_try},
        )
    inst.timeout = 10
    try:
        inst.write("*CLS")
    except Exception as e:
        raise DeviceProtocolError(
            f"scope rejected *CLS: {e}",
            context={"vid": vid, "pid": pid},
        )
    return inst


def configure(inst, channel: int, span_ms: float, trigger_slope: str, trigger_level_v: float):
    ch = f"CHAN{channel}"
    slope = "POSITIVE" if trigger_slope == "rising" else "NEGATIVE"
    inst.write(":STOP")
    inst.write(f":{ch}:DISPLAY ON")
    inst.write(f":{ch}:PROBE 10")
    inst.write(f":{ch}:COUPLING DC")
    inst.write(f":{ch}:SCALE 1.0")
    inst.write(f":{ch}:OFFSET 1.5")
    inst.write(f":{ch}:BWLIMIT ON")
    inst.write(f":TIMEBASE:RANGE {span_ms * 1e-3}")
    inst.write(":TIMEBASE:REFERENCE LEFT")
    inst.write(":TRIGGER:MODE EDGE")
    inst.write(f":TRIGGER:EDGE:SOURCE {ch}")
    inst.write(f":TRIGGER:EDGE:SLOPE {slope}")
    inst.write(f":TRIGGER:EDGE:LEVEL {trigger_level_v}")
    inst.write(":ACQUIRE:TYPE NORMAL")
    inst.write(":ACQUIRE:COMPLETE 100")
    inst.write(f":WAVEFORM:SOURCE {ch}")
    inst.write(":WAVEFORM:FORMAT WORD")
    inst.write(":WAVEFORM:BYTEORDER LSBFIRST")
    inst.write(":WAVEFORM:POINTS:MODE RAW")
    inst.write(":WAVEFORM:POINTS 50000")


def arm_and_wait(inst, timeout_s: float) -> bool:
    inst.write(":SINGLE")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.2)
        try:
            ter = int(inst.ask(":TER?").strip())
            if ter == 1:
                return True
        except Exception:
            continue
    return False


def fetch_waveform(inst) -> Tuple[List[float], List[float]]:
    pre = inst.ask(":WAVEFORM:PREAMBLE?").strip().split(",")
    if len(pre) < 10:
        raise DeviceProtocolError(
            f"unexpected :WAVEFORM:PREAMBLE? reply (expected ≥10 fields): {pre}",
            last_seen_output=",".join(pre)[-500:],
        )
    xinc, xorg, xref = float(pre[4]), float(pre[5]), float(pre[6])
    yinc, yorg, yref = float(pre[7]), float(pre[8]), float(pre[9])
    raw = inst.ask_raw(b":WAVEFORM:DATA?\n")
    if raw[0:1] != b"#":
        raise DeviceProtocolError(
            f"bad :WAVEFORM:DATA? block header: {raw[:8]!r}",
            last_seen_output=repr(raw[:64]),
        )
    n = int(raw[1:2])
    nbytes = int(raw[2:2 + n])
    data = raw[2 + n:2 + n + nbytes]
    samples = struct.unpack(f"<{nbytes // 2}H", data)
    voltages = [(s - yref) * yinc + yorg for s in samples]
    times_us = [(i - xref) * xinc * 1e6 + xorg * 1e6 for i in range(len(samples))]
    return times_us, voltages


# ---------------------------------------------------------------------------
# Pulse detection
# ---------------------------------------------------------------------------
def detect_low_pulses(times_us: List[float], v: List[float],
                      low_v: float, high_v: float,
                      pulse_min_us: float, pulse_max_us: float) -> List[Pulse]:
    pulses: List[Pulse] = []
    state = "high"
    fall_t: Optional[float] = None
    for t, val in zip(times_us, v):
        if state == "high" and val < low_v:
            state = "low"
            fall_t = t
        elif state == "low" and val > high_v:
            state = "high"
            if fall_t is not None:
                w = t - fall_t
                if pulse_min_us <= w <= pulse_max_us:
                    pulses.append(Pulse(fall_us=fall_t, rise_us=t, width_us=w))
    return pulses


def verdict(pulses: List[Pulse], period_ms: float, tol_ms: float) -> Tuple[bool, str, int]:
    if len(pulses) <= 1:
        return True, f"{len(pulses)} pulse(s) in window — no periodic-pulse pattern (PASS)", 0
    gaps_ms = [(pulses[i + 1].fall_us - pulses[i].fall_us) / 1000.0
               for i in range(len(pulses) - 1)]
    periodic = sum(1 for g in gaps_ms if abs(g - period_ms) <= tol_ms)
    if periodic >= 1:
        return False, (
            f"{len(pulses)} pulses; {periodic} consecutive gap(s) ≈ {period_ms} ms "
            f"± {tol_ms} ms — periodic pattern detected (FAIL)"
        ), periodic
    return True, (
        f"{len(pulses)} pulses but no consecutive gap ≈ {period_ms} ms — "
        f"likely user-driven, not the periodic-bug pattern (PASS)"
    ), 0


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def _samples_to_csv(times_us: List[float], volts: List[float], max_rows: int = 100_000) -> str:
    buf = io.StringIO()
    buf.write("time_us,voltage\n")
    n = min(len(times_us), max_rows)
    for i in range(n):
        buf.write(f"{times_us[i]:.3f},{volts[i]:.4f}\n")
    if n < len(times_us):
        buf.write(f"# truncated to {max_rows} of {len(times_us)} samples\n")
    return buf.getvalue()


def _coerce_int(name: str, val: Any) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        raise InvalidArgumentError(
            f"arg '{name}' must be an integer (got: {val!r})"
        )


def _coerce_float(name: str, val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        raise InvalidArgumentError(
            f"arg '{name}' must be a number (got: {val!r})"
        )


def mode_capture(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    vid = _coerce_int("vid", args.get("vid") or _DEFAULT_VID)
    pid = _coerce_int("pid", args.get("pid") or _DEFAULT_PID)
    channel = _coerce_int("channel", args.get("channel", 4))
    span_ms = _coerce_float("span_ms", args.get("span_ms", 50.0))
    trigger_slope = str(args.get("trigger_slope", "falling"))
    if trigger_slope not in ("rising", "falling"):
        raise InvalidArgumentError(
            f"arg 'trigger_slope' must be 'rising' or 'falling' (got: {trigger_slope!r})"
        )
    trigger_level_v = _coerce_float("trigger_level_v", args.get("trigger_level_v", 1.5))
    trigger_timeout_s = _coerce_float("trigger_timeout_s", args.get("trigger_timeout_s", 30.0))
    no_configure = bool(args.get("no_configure", False))

    inst = open_scope(vid, pid)
    try:
        try:
            idn = inst.ask("*IDN?").strip()
        except Exception as e:
            raise DeviceProtocolError(
                f"scope rejected *IDN?: {e}",
                context={"vid": vid, "pid": pid},
            )
        print(f"connected: {idn}", file=sys.stderr)
        if not no_configure:
            configure(inst, channel, span_ms, trigger_slope, trigger_level_v)
        triggered = arm_and_wait(inst, trigger_timeout_s)
        if not triggered:
            raise DeviceTimeoutError(
                f"no scope trigger within {trigger_timeout_s}s",
                context={"channel": channel, "trigger_timeout_s": trigger_timeout_s, "idn": idn},
            )
        time.sleep(span_ms / 1000.0 + 0.3)
        inst.write(":STOP")
        times_us, volts = fetch_waveform(inst)
    finally:
        try: inst.close()
        except Exception: pass

    return 0, {
        "success": True,
        "mode": "capture",
        "idn": idn,
        "channel": channel,
        "span_ms": span_ms,
        "samples": len(volts),
        "csv": _samples_to_csv(times_us, volts),
    }


def mode_read_state(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """v0.68: read-only scope setup query (no capture armed).

    Queries identification, timebase, trigger edge config, and — for each
    currently-displayed channel — scale / offset / probe / coupling / BW
    limit. Every SCPI query is small and read-only; the scope is NOT
    armed and its run state is not disturbed.

    Backs the `scope://keysight-dso-x-3014t/current_setup` MCP resource.
    """
    vid = _coerce_int("vid", args.get("vid") or _DEFAULT_VID)
    pid = _coerce_int("pid", args.get("pid") or _DEFAULT_PID)

    inst = open_scope(vid, pid)
    try:
        try:
            idn = inst.ask("*IDN?").strip()
        except Exception as e:
            raise DeviceProtocolError(
                f"scope rejected *IDN?: {e}",
                context={"vid": vid, "pid": pid},
            )

        def _ask(cmd: str) -> str:
            try:
                return inst.ask(cmd).strip()
            except Exception as e:
                raise DeviceProtocolError(
                    f"scope rejected '{cmd}': {e}",
                    context={"vid": vid, "pid": pid, "idn": idn},
                )

        # Which channels are currently displayed (:CHANn:DISPLAY? → "0" or "1").
        channels_enabled: List[int] = []
        for n in (1, 2, 3, 4):
            try:
                raw = _ask(f":CHAN{n}:DISP?")
            except DeviceProtocolError:
                # Some models expose only 2 channels; ignore unknown channels.
                continue
            if raw.lstrip("+-").startswith("1") or raw.upper() == "ON":
                channels_enabled.append(n)

        # Timebase.
        tb_range = _coerce_float("timebase_range", _ask(":TIMEBASE:RANGE?"))
        tb_ref = _ask(":TIMEBASE:REFERENCE?")

        # Trigger (edge mode; match what we configure in mode_capture).
        trg_source = _ask(":TRIG:EDGE:SOURCE?")
        trg_slope = _ask(":TRIG:EDGE:SLOPE?")
        trg_level = _coerce_float("trigger_level", _ask(":TRIG:EDGE:LEVEL?"))

        # Per-enabled-channel settings.
        channels: Dict[str, Dict[str, Any]] = {}
        for n in channels_enabled:
            channels[str(n)] = {
                "scale_v_per_div":    _coerce_float(f"chan{n}_scale",  _ask(f":CHAN{n}:SCALE?")),
                "offset_v":           _coerce_float(f"chan{n}_offset", _ask(f":CHAN{n}:OFFSET?")),
                "probe_attenuation":  _coerce_float(f"chan{n}_probe",  _ask(f":CHAN{n}:PROBE?")),
                "coupling":           _ask(f":CHAN{n}:COUPLING?"),
                "bandwidth_limit":    _ask(f":CHAN{n}:BWLIMIT?"),
            }
    finally:
        try: inst.close()
        except Exception: pass

    return 0, {
        "success": True,
        "mode": "read_state",
        "idn_string": idn,
        "channels_enabled": channels_enabled,
        "timebase": {
            "range_s":   tb_range,
            "reference": tb_ref,
        },
        "trigger": {
            "source":  trg_source,
            "slope":   trg_slope,
            "level_v": trg_level,
        },
        "channels": channels,
    }


def mode_pulse_check(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    # Capture first. DeviceError propagates up to main().
    code, cap = mode_capture(args)
    if code != 0:
        # (Only reachable historically; new paths raise DeviceError.)
        cap["mode"] = "pulse_check"
        return code, cap

    # Re-parse CSV cheaply (we kept it as text for stdout, decode here).
    times_us: List[float] = []
    volts: List[float] = []
    for line in cap["csv"].splitlines()[1:]:
        if not line or line.startswith("#"): continue
        try:
            t, v = line.split(",")
            times_us.append(float(t)); volts.append(float(v))
        except ValueError:
            continue

    low_v   = _coerce_float("low_thresh_v",   args.get("low_thresh_v",   _DEFAULT_LOW_V))
    high_v  = _coerce_float("high_thresh_v",  args.get("high_thresh_v",  _DEFAULT_HIGH_V))
    pmin_us = _coerce_float("pulse_min_us",   args.get("pulse_min_us",   10.0))
    pmax_us = _coerce_float("pulse_max_us",   args.get("pulse_max_us",   100.0))
    per_ms  = _coerce_float("period_ms",      args.get("period_ms",       5.0))
    tol_ms  = _coerce_float("period_tol_ms",  args.get("period_tol_ms",   1.0))

    pulses = detect_low_pulses(times_us, volts, low_v, high_v, pmin_us, pmax_us)
    passed, msg, periodic_count = verdict(pulses, per_ms, tol_ms)
    body = {
        "success": True,
        "mode": "pulse_check",
        "idn": cap["idn"],
        "channel": cap["channel"],
        "span_ms": cap["span_ms"],
        "samples": cap["samples"],
        "verdict": "PASS" if passed else "FAIL",
        "message": msg,
        "pulses": [asdict(p) for p in pulses],
        "periodic_count": periodic_count,
        "period_ms_target": per_ms,
        "period_tol_ms": tol_ms,
    }
    return (0 if passed else 1), body


# ---------------------------------------------------------------------------
# Arg loading
# ---------------------------------------------------------------------------
def load_json_args(spec: Optional[str]) -> Dict[str, Any]:
    if spec is None:
        # No --json-args; read stdin if non-tty, else empty.
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            return json.loads(data) if data else {}
        return {}
    if spec == "-":
        data = sys.stdin.read().strip()
        return json.loads(data) if data else {}
    return json.loads(spec)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keysight InfiniiVision scope driver (mcp-eda device).",
        epilog="Reads JSON args from stdin or --json-args; emits one JSON object on stdout.",
    )
    ap.add_argument("--mode", choices=["capture", "pulse_check", "read_state"], default="capture",
                    help="Tool mode (matches manifest.json 'tool_mode' field).")
    ap.add_argument("--json-args",
                    help="JSON-encoded args, or '-' to read JSON from stdin.")
    args = ap.parse_args(argv)

    try:
        params = load_json_args(args.json_args)
    except json.JSONDecodeError as e:
        err = InvalidArgumentError(f"invalid JSON args: {e}")
        json.dump(err.as_json_body(), sys.stdout)
        sys.stdout.write("\n")
        return EXIT_FOR_CODE[err.error_code]

    try:
        if args.mode == "capture":
            code, body = mode_capture(params)
        elif args.mode == "pulse_check":
            code, body = mode_pulse_check(params)
        elif args.mode == "read_state":
            code, body = mode_read_state(params)
        else:
            raise InvalidArgumentError(f"unknown mode: {args.mode}")
    except DeviceError as e:
        body = e.as_json_body()
        body["mode"] = args.mode
        print(json.dumps(body))
        return EXIT_FOR_CODE[e.error_code]
    except Exception as e:
        # Unexpected: map to protocol_error (driver crash vs structured error).
        err = DeviceProtocolError(f"{type(e).__name__}: {e}")
        body = err.as_json_body()
        body["mode"] = args.mode
        print(json.dumps(body))
        return EXIT_FOR_CODE[err.error_code]

    print(json.dumps(body))
    return code


if __name__ == "__main__":
    sys.exit(main())
