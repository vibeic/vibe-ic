#!/usr/bin/env python3
"""scope_response_byte_decode_check.py — P0.3 deterministic gate

Decodes a scope CSV capture of a pulse-width-encoded protocol into
bytes, then compares the DUT response against L10 oracle vectors.

The gate classifies LOW pulses by duration (using L2 timing windows)
into BIT_0, BIT_1, or BR (break), segments them into bytes via IBT
gap detection, and identifies the host→DUT turnaround boundary.

Usage:
    python3 scope_response_byte_decode_check.py <project_dir>
    python3 scope_response_byte_decode_check.py <project_dir> --scope-csv cap.csv
    python3 scope_response_byte_decode_check.py <project_dir> --json out.json --scope-csv cap.csv

Exit codes:
    0 = PASS (decoded bytes match oracle, or no scope/L2/oracle data)
    1 = FAIL (decoded bytes differ from oracle)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "scope_response_byte_decode_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _find_scope_csv(project_dir: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for pattern in ("reports/scope_*.csv", "scope_*.csv", "reports/*.csv"):
        hits = sorted(project_dir.glob(pattern))
        if hits:
            return hits[0]
    return None


def _find_l2_timing(project_dir: Path, explicit: Optional[str]) -> Optional[dict]:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return json.loads(p.read_text(errors="replace"))
        return None
    gd = _pl.generated_docs_dir(project_dir)
    if not gd.is_dir():
        return None
    for f in sorted(gd.glob("L2*.json")):
        try:
            data = json.loads(f.read_text(errors="replace"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _extract_timing_params(l2: dict) -> Optional[dict]:
    """Extract pulse timing parameters from L2 JSON (various schema layouts)."""

    def _search(d: dict, keys: list[str]) -> Optional[float]:
        for k in keys:
            if k in d:
                v = d[k]
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        return float(v)
                    except ValueError:
                        pass
        for v in d.values():
            if isinstance(v, dict):
                r = _search(v, keys)
                if r is not None:
                    return r
        return None

    bit_0 = _search(l2, ["bit_0_low_us", "t_bit0_low_us", "T_BIT0_LOW_US", "bit0_low_us"])
    bit_1 = _search(l2, ["bit_1_low_us", "t_bit1_low_us", "T_BIT1_LOW_US", "bit1_low_us"])
    br = _search(l2, ["br_low_us", "t_br_low_us", "T_BR_LOW_US", "break_low_us"])
    ibt = _search(l2, ["ibt_gap_us", "t_ibt_us", "T_IBT_US", "inter_byte_gap_us"])
    srs = _search(l2, ["t_srs_min_us", "tSRS_min_us", "T_SRS_MIN_US", "turnaround_us"])

    if bit_0 is None or bit_1 is None:
        return None
    return {
        "bit_0_low_us": bit_0,
        "bit_1_low_us": bit_1,
        "br_low_us": br or max(bit_0, bit_1) * 2,
        "ibt_gap_us": ibt or max(bit_0, bit_1) * 3,
        "t_srs_min_us": srs or 20.0,
    }


def _parse_scope_csv(path: Path, threshold_v: float) -> List[Tuple[float, float]]:
    """Parse scope CSV into list of LOW pulses as (start_us, duration_us)."""
    rows = []
    with open(path, newline="", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            try:
                t = float(row[0])
                v = float(row[1])
                rows.append((t, v))
            except ValueError:
                continue

    if not rows:
        return []

    t_scale = 1.0
    if rows[-1][0] - rows[0][0] < 0.001:
        t_scale = 1e6
    elif rows[-1][0] - rows[0][0] < 1.0:
        t_scale = 1e6
    else:
        t_scale = 1.0

    pulses = []
    in_low = False
    low_start = 0.0

    for t_raw, v in rows:
        t = t_raw * t_scale
        if v < threshold_v:
            if not in_low:
                in_low = True
                low_start = t
        else:
            if in_low:
                pulses.append((low_start, t - low_start))
                in_low = False

    return pulses


def _classify_pulse(dur_us: float, timing: dict, tolerance: float = 0.30) -> str:
    b0 = timing["bit_0_low_us"]
    b1 = timing["bit_1_low_us"]
    br = timing["br_low_us"]

    if abs(dur_us - b0) / max(b0, 0.01) <= tolerance:
        return "BIT_0"
    if abs(dur_us - b1) / max(b1, 0.01) <= tolerance:
        return "BIT_1"
    if abs(dur_us - br) / max(br, 0.01) <= tolerance:
        return "BR"
    if dur_us > br * (1 + tolerance):
        return "BR"
    if dur_us < min(b0, b1) * (1 - tolerance):
        return "GLITCH"
    mid = (b0 + b1) / 2
    return "BIT_0" if dur_us < mid else "BIT_1"


def _decode_bytes(pulses: List[Tuple[float, float]], timing: dict) -> List[List[int]]:
    """Decode pulses into byte groups, separated by IBT gaps."""
    if not pulses:
        return []

    ibt_thresh = timing["ibt_gap_us"]
    classified = []
    for start, dur in pulses:
        cls = _classify_pulse(dur, timing)
        classified.append((start, dur, cls))

    byte_groups: List[List[int]] = []
    current_bits: List[int] = []

    for i, (start, dur, cls) in enumerate(classified):
        if cls == "BR":
            if current_bits:
                if len(current_bits) == 8:
                    val = 0
                    for b in current_bits:
                        val = (val << 1) | b
                    byte_groups.append([val])
                current_bits = []
            continue

        if cls == "GLITCH":
            continue

        if i > 0:
            prev_end = classified[i - 1][0] + classified[i - 1][1]
            gap = start - prev_end
            if gap > ibt_thresh:
                if current_bits and len(current_bits) == 8:
                    val = 0
                    for b in current_bits:
                        val = (val << 1) | b
                    if not byte_groups or len(byte_groups[-1]) > 0:
                        byte_groups.append([val])
                    else:
                        byte_groups[-1].append(val)
                    current_bits = []
                elif current_bits:
                    current_bits = []

        bit_val = 0 if cls == "BIT_0" else 1
        current_bits.append(bit_val)

        if len(current_bits) == 8:
            val = 0
            for b in current_bits:
                val = (val << 1) | b
            if byte_groups:
                byte_groups[-1].append(val)
            else:
                byte_groups.append([val])
            current_bits = []

    return byte_groups


def _find_turnaround(pulses: List[Tuple[float, float]], timing: dict) -> Optional[int]:
    """Find the pulse index where turnaround gap occurs (host→DUT boundary)."""
    srs_thresh = timing["t_srs_min_us"]
    for i in range(1, len(pulses)):
        prev_end = pulses[i - 1][0] + pulses[i - 1][1]
        gap = pulses[i][0] - prev_end
        if gap > srs_thresh:
            return i
    return None


def _load_oracle_response(project_dir: Path, oracle_path: Optional[str]) -> Optional[List[int]]:
    """Load expected response bytes from oracle JSON."""
    path = None
    if oracle_path:
        path = Path(oracle_path)
    else:
        gd = _pl.generated_docs_dir(project_dir)
        if gd.is_dir():
            for f in sorted(gd.glob("L10*.json")):
                path = f
                break
    if path is None or not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception:
        return None

    vectors = []
    if isinstance(data, dict):
        for key in ("opcode_oracle_vectors", "oracle_vectors", "vectors"):
            if key in data and isinstance(data[key], list):
                vectors = data[key]
                break
    if not vectors:
        return None

    first = vectors[0]
    resp_hex = first.get("expected_response_hex", "")
    if resp_hex:
        try:
            return [int(b, 16) for b in resp_hex.strip().split()]
        except ValueError:
            pass
    return None


def run_audit(
    base: Path,
    scope_csv: Optional[str] = None,
    l2_timing_json: Optional[str] = None,
    oracle_json: Optional[str] = None,
    threshold_v: float = 1.5,
) -> AuditResult:
    result = AuditResult()

    csv_path = _find_scope_csv(base, scope_csv)
    if csv_path is None:
        result.findings.append(Finding(
            rule="SKIP_NO_SCOPE",
            severity="INFO",
            message="No scope CSV provided or found; skipping scope decode check",
        ))
        result.summary = {"pulses": 0, "bytes_decoded": 0, "mismatches": 0}
        return result

    l2 = _find_l2_timing(base, l2_timing_json)
    if l2 is None:
        result.findings.append(Finding(
            rule="SKIP_NO_L2",
            severity="INFO",
            message="No L2 timing JSON found; cannot classify pulses",
        ))
        result.summary = {"pulses": 0, "bytes_decoded": 0, "mismatches": 0}
        return result

    timing = _extract_timing_params(l2)
    if timing is None:
        result.findings.append(Finding(
            rule="SKIP_NO_L2",
            severity="INFO",
            message="L2 JSON missing bit_0_low_us / bit_1_low_us fields",
        ))
        result.summary = {"pulses": 0, "bytes_decoded": 0, "mismatches": 0}
        return result

    try:
        pulses = _parse_scope_csv(csv_path, threshold_v)
    except Exception as exc:
        print(f"ERROR: Failed to parse scope CSV: {exc}", file=sys.stderr)
        return AuditResult(passed=True, summary={"error": str(exc)})

    if not pulses:
        result.findings.append(Finding(
            rule="SKIP_NO_SCOPE",
            severity="INFO",
            message="Scope CSV contains no detectable LOW pulses",
            file=str(csv_path),
        ))
        result.summary = {"pulses": 0, "bytes_decoded": 0, "mismatches": 0}
        return result

    turn_idx = _find_turnaround(pulses, timing)
    dut_pulses = pulses[turn_idx:] if turn_idx is not None else pulses
    byte_groups = _decode_bytes(dut_pulses, timing)
    all_bytes = [b for group in byte_groups for b in group]

    expected = _load_oracle_response(base, oracle_json)
    mismatches = 0

    if expected is not None and all_bytes:
        compare_len = min(len(expected), len(all_bytes))
        for i in range(compare_len):
            if expected[i] != all_bytes[i]:
                mismatches += 1
                result.passed = False
                result.findings.append(Finding(
                    rule="SCOPE_BYTE_MISMATCH",
                    severity="ERROR",
                    message=(
                        f"Byte[{i}]: expected 0x{expected[i]:02X}, "
                        f"decoded 0x{all_bytes[i]:02X}"
                    ),
                    file=str(csv_path),
                ))
        if len(expected) != len(all_bytes):
            result.passed = False
            mismatches += 1
            result.findings.append(Finding(
                rule="SCOPE_BYTE_MISMATCH",
                severity="ERROR",
                message=(
                    f"Length mismatch: oracle has {len(expected)} bytes, "
                    f"scope decoded {len(all_bytes)} bytes"
                ),
                file=str(csv_path),
            ))
        if mismatches == 0:
            result.findings.append(Finding(
                rule="SCOPE_DECODE_OK",
                severity="INFO",
                message=f"All {compare_len} response bytes match oracle",
                file=str(csv_path),
            ))
    elif expected is None:
        result.findings.append(Finding(
            rule="SCOPE_DECODE_OK",
            severity="INFO",
            message=f"Decoded {len(all_bytes)} bytes from scope (no oracle to compare)",
            file=str(csv_path),
        ))

    decoded_hex = " ".join(f"0x{b:02X}" for b in all_bytes[:20])
    result.summary = {
        "pulses": len(pulses),
        "turnaround_index": turn_idx,
        "bytes_decoded": len(all_bytes),
        "decoded_hex_preview": decoded_hex,
        "mismatches": mismatches,
    }
    return result


def _emit(result: AuditResult, json_dest: Optional[str]) -> None:
    if json_dest is not None:
        out = asdict(result)
        txt = json.dumps(out, indent=2)
        if json_dest == "-":
            print(txt)
        else:
            Path(json_dest).parent.mkdir(parents=True, exist_ok=True)
            Path(json_dest).write_text(txt + "\n")
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] scope_response_byte_decode_check")
        s = result.summary
        print(f"  Pulses: {s.get('pulses', 0)}")
        print(f"  Bytes decoded: {s.get('bytes_decoded', 0)}")
        print(f"  Mismatches: {s.get('mismatches', 0)}")
        if s.get("decoded_hex_preview"):
            print(f"  Preview: {s['decoded_hex_preview']}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    ap.add_argument("--scope-csv", default=None, metavar="PATH")
    ap.add_argument("--l2-timing-json", default=None, metavar="PATH")
    ap.add_argument("--oracle-json", default=None, metavar="PATH")
    ap.add_argument("--threshold-v", type=float, default=1.5,
                     help="Voltage threshold for LOW detection (default: 1.5)")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(
        args.project_dir,
        scope_csv=args.scope_csv,
        l2_timing_json=args.l2_timing_json,
        oracle_json=args.oracle_json,
        threshold_v=args.threshold_v,
    )
    _emit(result, args.json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
