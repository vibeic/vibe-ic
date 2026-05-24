#!/usr/bin/env python3
"""scope_long_decode.py — LL-9 (debug helper, not a structural gate).

Wake-pulse-aware long-window scope decoder for half-duplex protocol ICs.
Closes the device-feedback loop that was missing in v0.119.1: when a
fresh-agent SOF FAILs <half-duplex-tester> (or any host tester), the developer's only
information is byte[6]=0x02 (1 bit of feedback). This tool decodes the
scope CSV captured during the test into a structured byte timeline and
diffs it against L3 spec, identifying the first divergent byte.

Pipeline:

  CSV (time_us, voltage)
    -> threshold to LOW pulses (start_us, dur_us)
    -> classify each pulse via L2.pulse_classes (BIT0/BIT1/BR/IBT/BOR/WAKE)
    -> filter WAKE-class pulses (kept in summary, dropped from analysis)
    -> group into PROTOCOL BURSTS (clusters with intra-gap < 100us)
    -> for each burst: split on BR pulses; per-segment bit-decode LSB-first
                       (BIT0/BIT1 -> 8-bit byte; rejection on out-of-window)
    -> infer direction:
         * a burst containing a BR pulse is MASTER cmd
         * the burst immediately following (within ~1ms) is CHIP response
    -> pair MASTER cmd <-> CHIP response, look up L3.command_table by opcode
    -> diff actual vs L3.fields_tx + verify CRC over the wire bytes
    -> emit JSON: bursts, pairs, first divergent byte, recommended fix hint

Usage:
  python3 scope_long_decode.py <project_dir> --scope-csv <file.csv> [--json out.json]

Exit codes:
  0 = decode succeeded, no divergence found vs L3
  1 = decode succeeded, found at least one divergent byte (per-strict)
  2 = input/CSV could not be parsed

The tool is OFFLINE — capture is up to the caller (use device_scope_capture
with span_ms=200, trigger_slope=falling, trigger_level_v=1.5; capture
during connect_test). For a fully-automated capture+decode wrapper, see
the docstring section "Companion shell wrapper".
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from gate_utils import read_text
import _path_layout as _pl


# ============================================================================
# Stage 1 — CSV → LOW pulse list
# ============================================================================

def parse_scope_csv(path: Path,
                    threshold_v: float = 1.5
                    ) -> list[tuple[float, float]]:
    """Return [(start_us, dur_us)] LOW pulses (voltage < threshold)."""
    if not path.exists():
        return []
    text = read_text(path)
    pulses: list[tuple[float, float]] = []
    in_low = False
    start: float | None = None
    for line in text.strip().split("\n")[1:]:  # skip CSV header
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            t = float(parts[0])
            v = float(parts[1])
        except ValueError:
            continue
        if v < threshold_v and not in_low:
            in_low = True
            start = t
        elif v >= threshold_v and in_low:
            in_low = False
            if start is not None:
                pulses.append((start, t - start))
    return pulses


# ============================================================================
# Stage 2 — Classify pulses by L2 pulse_classes
# ============================================================================

@dataclass
class PulseClass:
    name: str
    min_us: float
    max_us: float


def load_l2_pulse_classes(project: Path) -> list[PulseClass]:
    for cand in (_pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json",
                 project / "input" / "docs" / "L2_TIMING_WAVEFORM.json"):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
            except Exception:
                continue
            classes: list[PulseClass] = []
            for pc in data.get("pulse_classes", []):
                if not isinstance(pc, dict):
                    continue
                try:
                    classes.append(PulseClass(
                        name=pc["class_name"],
                        min_us=float(pc["min_us"]),
                        max_us=float(pc["max_us"]),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
            return classes
    return []


def classify_pulse(dur_us: float,
                   classes: list[PulseClass]) -> str:
    for c in classes:
        if c.min_us <= dur_us < c.max_us:
            return c.name
    return "OOB"  # out-of-band — likely noise or transient


# ============================================================================
# Stage 3 — Filter WAKE-class pulses, find protocol bursts
# ============================================================================

@dataclass
class Burst:
    start_us: float
    end_us: float
    pulses: list[tuple[float, float, str]] = field(default_factory=list)
    # Each entry = (start_us, dur_us, class_name)

    def add(self, t: float, d: float, cls: str) -> None:
        self.pulses.append((t, d, cls))
        self.end_us = t + d


def cluster_into_bursts(classified: list[tuple[float, float, str]],
                        intra_gap_us: float = 100.0) -> list[Burst]:
    """Cluster non-WAKE pulses into bursts. A burst is a sequence of pulses
    where consecutive members have gap < intra_gap_us. WAKE-class pulses
    are skipped (they are chip's idle wake pulses, not protocol)."""
    bursts: list[Burst] = []
    current: Burst | None = None
    last_end: float = -1e9
    for (t, d, cls) in classified:
        if cls == "WAKE":
            # Wake pulses break bursts (they're idle, far from any protocol)
            if current is not None and not current.pulses:
                current = None
            continue
        if cls in ("BOR",):
            # BOR (host brownout) starts a new context; end any current burst
            if current is not None and current.pulses:
                bursts.append(current)
            current = Burst(start_us=t, end_us=t + d)
            current.add(t, d, cls)
            last_end = t + d
            continue
        gap = t - last_end
        if current is None or gap > intra_gap_us:
            if current is not None and current.pulses:
                bursts.append(current)
            current = Burst(start_us=t, end_us=t + d)
        current.add(t, d, cls)
        last_end = t + d
    if current is not None and current.pulses:
        bursts.append(current)
    return bursts


# ============================================================================
# Stage 4 — Bit-decode bursts to byte streams
# ============================================================================

def decode_burst_bytes(burst: Burst) -> dict:
    """Split burst on BR pulses; bit-decode each segment LSB-first into
    bytes. Returns dict with `segments` list and `flags`."""
    segments: list[dict] = []
    cur_bits: list[int] = []
    saw_br = False
    bytes_acc: list[int] = []
    flags: list[str] = []

    def flush_segment(reason: str) -> None:
        nonlocal cur_bits, bytes_acc
        if bytes_acc:
            segments.append({
                "bytes_hex": [f"{b:02X}" for b in bytes_acc],
                "byte_count": len(bytes_acc),
                "trailing_bits": cur_bits,
                "end_reason": reason,
            })
        cur_bits = []
        bytes_acc = []

    for (t, d, cls) in burst.pulses:
        if cls == "BR":
            flush_segment("BR")
            saw_br = True
            continue
        if cls == "BIT1":
            cur_bits.append(1)
        elif cls == "BIT0":
            cur_bits.append(0)
        elif cls == "BOR":
            flags.append(f"BOR@{t:.1f}us")
            flush_segment("BOR")
            continue
        else:  # OOB
            flags.append(f"OOB({d:.1f}us)@{t:.1f}us")
            continue
        if len(cur_bits) == 8:
            # LSB first → cur_bits[0] is bit0
            byte_val = sum(b << i for i, b in enumerate(cur_bits))
            bytes_acc.append(byte_val)
            cur_bits = []
    flush_segment("end-of-burst")
    return {
        "start_us": burst.start_us,
        "end_us": burst.end_us,
        "saw_br": saw_br,
        "segments": segments,
        "flags": flags,
    }


# ============================================================================
# Stage 5 — Infer master/chip direction & pair bursts
# ============================================================================

def infer_direction(burst_decoded: dict) -> str:
    """A burst that begins with BR is master cmd; otherwise chip response.
    More precisely: if any BR appears in the burst it's master; else chip."""
    return "master" if burst_decoded["saw_br"] else "chip"


def pair_cmd_response(decoded_bursts: list[dict],
                      max_response_gap_us: float = 5000.0
                      ) -> list[dict]:
    """Pair each master cmd burst with the chip response burst that
    follows it within max_response_gap_us. Returns list of pair dicts."""
    pairs: list[dict] = []
    i = 0
    while i < len(decoded_bursts):
        b = decoded_bursts[i]
        if infer_direction(b) == "master":
            cmd_b = b
            resp_b = None
            if i + 1 < len(decoded_bursts):
                next_b = decoded_bursts[i + 1]
                gap = next_b["start_us"] - b["end_us"]
                if (infer_direction(next_b) == "chip"
                        and gap < max_response_gap_us):
                    resp_b = next_b
                    i += 1
            pairs.append({
                "cmd": cmd_b,
                "response": resp_b,
                "response_latency_us":
                    (resp_b["start_us"] - cmd_b["end_us"])
                    if resp_b else None,
            })
        i += 1
    return pairs


# ============================================================================
# Stage 6 — Diff against L3 spec
# ============================================================================

def load_l3_command_table(project: Path) -> dict[int, dict]:
    for cand in (_pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json",
                 project / "input" / "docs" / "L3_CMD_PROTOCOL.json"):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
            except Exception:
                continue
            table: dict[int, dict] = {}
            for cmd in data.get("command_table", []):
                if not isinstance(cmd, dict):
                    continue
                op_str = cmd.get("opcode", "")
                try:
                    op_int = int(op_str, 16) if op_str.startswith("0x") \
                             else int(op_str, 16)
                except ValueError:
                    continue
                table[op_int] = cmd
            return table
    return {}


def crc8_reflected(data: list[int],
                   poly: int = 0x8C,
                   init: int = 0xFF) -> int:
    s = init
    for b in data:
        s ^= b
        for _ in range(8):
            if s & 1:
                s = (s >> 1) ^ poly
            else:
                s >>= 1
    return s


def diff_pair_against_l3(pair: dict,
                         l3: dict[int, dict]) -> dict:
    """Inspect a (cmd, response) pair vs L3 spec. Return diff report."""
    cmd_segments = pair["cmd"]["segments"] if pair["cmd"] else []
    if not cmd_segments:
        return {"verdict": "NO_CMD_BYTES", "detail": ""}
    # First segment of cmd burst (after the leading BR) holds the cmd bytes.
    # If multiple segments (multiple BRs), pick the LAST one (master might
    # have re-issued; common pattern).
    cmd_bytes = []
    for seg in cmd_segments:
        if seg["byte_count"] > 0:
            cmd_bytes = [int(b, 16) for b in seg["bytes_hex"]]
    if not cmd_bytes:
        return {"verdict": "NO_CMD_BYTES_AFTER_BR", "detail": ""}
    op = cmd_bytes[0]
    if op not in l3:
        return {"verdict": "OP_NOT_IN_L3", "opcode": f"0x{op:02X}"}
    l3_entry = l3[op]
    expected_rx_len = l3_entry.get("rx_len_bytes")
    if expected_rx_len and len(cmd_bytes) != expected_rx_len:
        return {
            "verdict": "CMD_LEN_MISMATCH",
            "opcode": f"0x{op:02X}",
            "expected_rx_len": expected_rx_len,
            "actual_rx_len": len(cmd_bytes),
        }
    # Verify cmd CRC: last byte should equal crc8 over cmd_bytes[:-1]
    cmd_crc_actual = cmd_bytes[-1]
    cmd_crc_expected = crc8_reflected(cmd_bytes[:-1])
    cmd_crc_ok = (cmd_crc_actual == cmd_crc_expected)

    # Check response
    if pair["response"] is None:
        return {
            "verdict": "NO_RESPONSE",
            "opcode": f"0x{op:02X}",
            "cmd_crc_ok": cmd_crc_ok,
        }
    resp_bytes: list[int] = []
    for seg in pair["response"]["segments"]:
        resp_bytes += [int(b, 16) for b in seg["bytes_hex"]]
    expected_tx_len = l3_entry.get("tx_len_bytes")
    detail: dict = {
        "opcode": f"0x{op:02X}",
        "cmd_bytes": [f"{b:02X}" for b in cmd_bytes],
        "cmd_crc_ok": cmd_crc_ok,
        "resp_bytes": [f"{b:02X}" for b in resp_bytes],
        "resp_byte_count": len(resp_bytes),
        "expected_tx_len": expected_tx_len,
    }
    if expected_tx_len and len(resp_bytes) != expected_tx_len:
        detail["verdict"] = "RESP_LEN_MISMATCH"
        return detail
    # Verify response CRC
    if len(resp_bytes) >= 2:
        resp_crc_actual = resp_bytes[-1]
        resp_crc_expected = crc8_reflected(resp_bytes[:-1])
        detail["resp_crc_ok"] = (resp_crc_actual == resp_crc_expected)
        if not detail["resp_crc_ok"]:
            detail["verdict"] = "RESP_CRC_MISMATCH"
            detail["resp_crc_actual"] = f"{resp_crc_actual:02X}"
            detail["resp_crc_expected"] = f"{resp_crc_expected:02X}"
            return detail
    # Compare against rsp_example_hex if present (byte-by-byte first divergence)
    rsp_example = l3_entry.get("rsp_example_hex", "")
    if rsp_example:
        try:
            example_bytes = [int(x, 16) for x in rsp_example.split()]
            for idx in range(min(len(resp_bytes), len(example_bytes))):
                if resp_bytes[idx] != example_bytes[idx]:
                    # Byte 0 (rsp_op) and CRC are most diagnostic; data may
                    # legitimately differ if OTP is chip-specific. So flag
                    # only the rsp_op (byte 0) for STRICT.
                    if idx == 0:
                        detail["verdict"] = "RESP_OPCODE_MISMATCH"
                        detail["first_divergent_byte"] = idx
                        detail["expected"] = f"{example_bytes[idx]:02X}"
                        detail["actual"] = f"{resp_bytes[idx]:02X}"
                        return detail
                    # Else informational
        except ValueError:
            pass
    detail["verdict"] = "OK"
    return detail


# ============================================================================
# Top-level orchestrator
# ============================================================================

def decode(project: Path, csv_path: Path) -> dict:
    pulses = parse_scope_csv(csv_path)
    classes = load_l2_pulse_classes(project)
    if not classes:
        return {"error": "no L2.pulse_classes found in project"}
    classified: list[tuple[float, float, str]] = []
    wake_count = 0
    bor_count = 0
    for (t, d) in pulses:
        cls = classify_pulse(d, classes)
        if cls == "WAKE":
            wake_count += 1
        elif cls == "BOR":
            bor_count += 1
        classified.append((t, d, cls))
    bursts = cluster_into_bursts(classified)
    decoded = [decode_burst_bytes(b) for b in bursts]
    pairs = pair_cmd_response(decoded)
    l3 = load_l3_command_table(project)
    diffs = [diff_pair_against_l3(p, l3) for p in pairs]
    return {
        "project": project.name,
        "csv": str(csv_path),
        "stats": {
            "total_pulses": len(pulses),
            "wake_pulses": wake_count,
            "bor_pulses": bor_count,
            "non_wake_pulses": len(pulses) - wake_count,
            "bursts": len(bursts),
            "cmd_response_pairs": len(pairs),
        },
        "bursts": decoded,
        "pairs_diff": diffs,
        "first_divergence": next(
            (d for d in diffs if d.get("verdict") not in ("OK", None)),
            None,
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="scope_long_decode")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--scope-csv", required=True, type=Path,
                    help="CSV from device_scope_capture (time_us,voltage)")
    ap.add_argument("--json", default=None,
                    help="Output JSON report path")
    args = ap.parse_args()
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2
    if not args.scope_csv.exists():
        print(f"[error] scope CSV not found: {args.scope_csv}",
              file=sys.stderr)
        return 2

    report = decode(project, args.scope_csv)
    if "error" in report:
        print(f"[error] {report['error']}", file=sys.stderr)
        return 2

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))

    # Console summary
    s = report["stats"]
    print(f"=== scope_long_decode ({report['project']}) ===")
    print(f"pulses: {s['total_pulses']} (wake={s['wake_pulses']} "
          f"bor={s['bor_pulses']} other={s['non_wake_pulses']})")
    print(f"bursts: {s['bursts']}  cmd-response pairs: "
          f"{s['cmd_response_pairs']}")
    if report["first_divergence"]:
        d = report["first_divergence"]
        print(f"FIRST DIVERGENCE: opcode={d.get('opcode')} "
              f"verdict={d.get('verdict')}")
        for k in ("expected", "actual", "first_divergent_byte",
                  "expected_rx_len", "actual_rx_len",
                  "expected_tx_len", "resp_byte_count",
                  "resp_crc_actual", "resp_crc_expected"):
            if k in d:
                print(f"  {k}: {d[k]}")
        return 1
    print("ALL PAIRS OK — no divergence vs L3 spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
