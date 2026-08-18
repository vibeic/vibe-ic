#!/usr/bin/env python3
"""tester_verdict_frame_decode.py — T1 composability fix

Chip-agnostic, tester-agnostic post-processor that decodes raw tester
frame bytes into per-byte annotations with expected-vs-actual comparison
and diagnosis hints.

Given:
  1. Raw frame hex string from tester output
  2. A project-supplied frame_layout.json describing byte positions

Emits per-byte decoded JSON with annotations and short diagnosis hints
(frame_offset_shift, payload_truncated, crc_mismatch, etc.).

The frame_layout.json is per-project (tester is user's choice). This
post-processor itself embeds ZERO tester-specific or chip-specific
knowledge.

frame_layout.json format:
    {
      "fields": [
        {"name": "header",      "offset": 0, "length": 1, "expected_hex": "AA"},
        {"name": "response_op", "offset": 1, "length": 1},
        {"name": "payload",     "offset": 2, "length": 4},
        {"name": "crc",         "offset": 6, "length": 1},
        {"name": "verdict",     "offset": 7, "length": 1,
         "values": {"00": "PASS", "01": "CRC_FAIL", "02": "NO_RESPONSE"}}
      ]
    }

Usage:
    python3 tester_verdict_frame_decode.py --layout frame_layout.json --frame "AA 55 01 02 03 04 B7 00"
    python3 tester_verdict_frame_decode.py --layout frame_layout.json --frame "AA 55 01 02 03 04 B7 02" --json

Exit codes:
    0 = frame decoded (may still contain mismatches — check output)
    1 = frame has mismatches or diagnosis hints
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def parse_hex_string(s: str) -> List[int]:
    tokens = s.replace(",", " ").split()
    result = []
    for t in tokens:
        t = t.upper().replace("0X", "")
        try:
            result.append(int(t, 16))
        except ValueError:
            result.append(-1)
    return result


def decode_frame(frame_bytes: List[int], layout: dict) -> dict:
    fields = layout.get("fields", [])
    decoded = []
    has_mismatch = False
    diagnosis_hints = []

    for fld in fields:
        name = fld["name"]
        offset = fld["offset"]
        length = fld.get("length", 1)
        expected_hex = fld.get("expected_hex")
        values_map = fld.get("values", {})

        actual_bytes = []
        for i in range(length):
            idx = offset + i
            if idx < len(frame_bytes):
                actual_bytes.append(frame_bytes[idx])
            else:
                actual_bytes.append(None)

        actual_hex = " ".join(f"{b:02X}" if b is not None and b >= 0 else "??" for b in actual_bytes)

        entry: dict = {
            "field": name,
            "offset": offset,
            "length": length,
            "actual_hex": actual_hex,
        }

        if expected_hex:
            entry["expected_hex"] = expected_hex
            exp_bytes = parse_hex_string(expected_hex)
            match = True
            for j, (e, a) in enumerate(zip(exp_bytes, actual_bytes)):
                if e == -1:
                    continue
                if a is None or a != e:
                    match = False
                    break
            if not match:
                entry["match"] = False
                has_mismatch = True
            else:
                entry["match"] = True

        if values_map:
            key = actual_hex.replace(" ", "").upper()
            if len(actual_bytes) == 1 and actual_bytes[0] is not None:
                key = f"{actual_bytes[0]:02X}"
            meaning = values_map.get(key) or values_map.get(key.lower())
            if meaning:
                entry["decoded"] = meaning
            else:
                entry["decoded"] = f"UNKNOWN({key})"

        decoded.append(entry)

    if len(frame_bytes) < sum(f.get("length", 1) for f in fields):
        total_expected = sum(f.get("length", 1) for f in fields)
        diagnosis_hints.append({
            "hint": "payload_truncated",
            "detail": f"Frame has {len(frame_bytes)} bytes, layout expects {total_expected}",
        })

    if len(frame_bytes) > sum(f.get("length", 1) for f in fields):
        total_expected = sum(f.get("length", 1) for f in fields)
        diagnosis_hints.append({
            "hint": "frame_offset_shift",
            "detail": f"Frame has {len(frame_bytes)} bytes, layout expects {total_expected} — possible offset shift",
        })

    for entry in decoded:
        if entry.get("match") is False:
            if entry["field"] == "header":
                diagnosis_hints.append({
                    "hint": "frame_offset_shift",
                    "detail": f"Header mismatch: expected {entry.get('expected_hex')}, got {entry['actual_hex']}",
                })
            elif "crc" in entry["field"].lower():
                diagnosis_hints.append({
                    "hint": "crc_mismatch",
                    "detail": f"CRC field mismatch: expected {entry.get('expected_hex', 'N/A')}, got {entry['actual_hex']}",
                })

    for entry in decoded:
        if entry.get("decoded") == "NO_RESPONSE" or entry.get("decoded") == "TIMEOUT":
            diagnosis_hints.append({
                "hint": "no_device_response",
                "detail": f"Verdict field '{entry['field']}' indicates no response from DUT",
            })

    return {
        "frame_hex": " ".join(f"{b:02X}" if b >= 0 else "??" for b in frame_bytes),
        "fields": decoded,
        "has_mismatch": has_mismatch,
        "diagnosis_hints": diagnosis_hints,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", type=Path, required=True, help="Path to frame_layout.json")
    ap.add_argument("--frame", type=str, required=True, help="Raw frame as hex string")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.layout.is_file():
        print(f"ERROR: {args.layout} not found", file=sys.stderr)
        return 2

    try:
        layout = json.loads(args.layout.read_text())
    except Exception as e:
        print(f"ERROR: Cannot parse layout: {e}", file=sys.stderr)
        return 2

    frame_bytes = parse_hex_string(args.frame)
    result = decode_frame(frame_bytes, layout)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Frame: {result['frame_hex']}")
        print()
        for fld in result["fields"]:
            match_str = ""
            if "match" in fld:
                match_str = " ✓" if fld["match"] else " ✗ MISMATCH"
            decoded_str = f" → {fld['decoded']}" if "decoded" in fld else ""
            exp_str = f" (expected: {fld['expected_hex']})" if "expected_hex" in fld else ""
            print(f"  [{fld['offset']:2d}] {fld['field']:20s}: {fld['actual_hex']}{exp_str}{match_str}{decoded_str}")

        if result["diagnosis_hints"]:
            print()
            print("  Diagnosis hints:")
            for h in result["diagnosis_hints"]:
                print(f"    - {h['hint']}: {h['detail']}")

    return 1 if result["has_mismatch"] or result["diagnosis_hints"] else 0


if __name__ == "__main__":
    sys.exit(main())
