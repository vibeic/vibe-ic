#!/usr/bin/env python3
"""
cmd_protocol_crc_verify.py — Derive + verify CRC params from xlsx golden vectors.

Problem this addresses (2026-04-22 audit):
  cmd-protocol-gen skill was guessing CRC params (e.g. "CRC-8/SMBUS" by
  name) when the spec xlsx contained 16 rows of command+payload+
  MEASURED-CRC golden triples. Any fresh agent could have cross-verified
  candidate CRC parameters against the xlsx vectors in seconds — but the
  skill never did. Result: wrong poly/init/refin → RTL compiles clean,
  sim looks right, <half-duplex-tester> rejects the packet.

This program inverts the loop: given a list of (data_hex, expected_crc_hex)
golden vectors, try all standard CRC-8 / CRC-16 configs and report the
ones that match ALL vectors. Output is deterministic JSON the doc-gen
skill consumes to populate L3.

Input
-----
A JSON file (typically produced by xlsx_extract.py + manual curation)
with the shape:
  {
    "width": 8,                                # 8 / 16 / 32
    "vectors": [
       {"data_hex": "70 00 00", "crc_hex": "3D"},
       {"data_hex": "72",        "crc_hex": "71"},
       ...
    ]
  }

Output (printed + optional --json)
----------------------------------
  {
    "vectors_total": N,
    "best_match": {
      "poly": "0x07", "init": "0xFF", "refin": true, "refout": true,
      "xorout": "0x00",
      "matched": N,
      "known_preset": "crc8_MAXIM / DALLAS / 1-Wire"
    },
    "all_full_matches": [ ... ],
    "near_misses": [ ... ]    # configs matching >= 80%
  }

Exit codes
----------
    0 = at least one config matched ALL vectors (unique derivation
        complete OR caller supplied explicit preset)
    1 = no full match — caller must either fix vectors or accept
        "CRC params cannot be derived from the supplied vectors"
    2 = io / parse error

Why this matters
----------------
Without this check, cmd-protocol-gen produces L3 with CRC params that
never get tested against real data. With it, L3 completion is gated on
"your claimed algorithm reproduces every observed CRC", which catches
byte-order / init-value / reflection errors before they reach RTL.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import List, Dict, Any


# Known CRC-8 presets (name, poly, init, refin, refout, xorout)
# Sources: Catalogue of parametrised CRC algorithms by Greg Cook.
CRC8_PRESETS = [
    ("CRC-8 / SMBUS",       0x07, 0x00, False, False, 0x00),
    ("CRC-8 / MAXIM (1-Wire)", 0x31, 0x00, True,  True,  0x00),  # refin==refout
    ("CRC-8 / MAXIM alt init=0xFF", 0x31, 0xFF, True,  True,  0x00),
    ("CRC-8 / AUTOSAR",     0x2F, 0xFF, False, False, 0xFF),
    ("CRC-8 / CCITT",       0x07, 0x00, False, False, 0x00),
    ("CRC-8 / DARC",        0x39, 0x00, True,  True,  0x00),
    ("CRC-8 / DVB-S2",      0xD5, 0x00, False, False, 0x00),
    ("CRC-8 / EBU",         0x1D, 0xFF, True,  True,  0x00),
    ("CRC-8 / I-CODE",      0x1D, 0xFD, False, False, 0x00),
    ("CRC-8 / ITU",         0x07, 0x00, False, False, 0x55),
    ("CRC-8 / ROHC",        0x07, 0xFF, True,  True,  0x00),
    ("CRC-8 / SAE J1850",   0x1D, 0xFF, False, False, 0xFF),
    ("CRC-8 / WCDMA",       0x9B, 0x00, True,  True,  0x00),
    # Generic: same canonical preset as CRC-8/MAXIM but with init=0xFF.
    # Used by some single-wire ID protocols and field-bus packet checkers.
    ("CRC-8 / MAXIM-VARIANT init=0xFF",
                            0x31, 0xFF, True,  True,  0x00),
]


def _reflect(x: int, width: int) -> int:
    r = 0
    for i in range(width):
        if x & (1 << i):
            r |= 1 << (width - 1 - i)
    return r


def crc_compute(data: bytes, width: int, poly: int, init: int,
                 refin: bool, refout: bool, xorout: int) -> int:
    mask = (1 << width) - 1
    reg = init & mask
    for byte in data:
        if refin:
            byte = _reflect(byte, 8)
        reg ^= (byte << (width - 8)) & mask
        for _ in range(8):
            if reg & (1 << (width - 1)):
                reg = ((reg << 1) ^ poly) & mask
            else:
                reg = (reg << 1) & mask
    if refout:
        reg = _reflect(reg, width)
    return (reg ^ xorout) & mask


def _parse_hex_bytes(s: str) -> bytes:
    """Accept "70 00 00", "0x70,0x00", "700000", "70-00-00" — all work."""
    s = s.replace(",", " ").replace("-", " ").replace("0x", "").replace("0X", "")
    tokens = s.split()
    if not tokens:
        return b""
    # "700000" single token, treat as hex stream
    if len(tokens) == 1 and len(tokens[0]) > 2 and len(tokens[0]) % 2 == 0:
        return bytes.fromhex(tokens[0])
    return bytes(int(t, 16) for t in tokens if t)


def _parse_hex_scalar(s: str) -> int:
    s = s.strip().replace("0x", "").replace("0X", "")
    return int(s, 16)


def verify(vectors: List[Dict[str, str]], width: int) -> Dict[str, Any]:
    if width != 8:
        return {"error": f"width={width} not yet supported; stick to 8 for now"}

    full_matches: List[Dict[str, Any]] = []
    near_misses: List[Dict[str, Any]] = []

    # Build data/expected pairs
    parsed = []
    for v in vectors:
        try:
            data = _parse_hex_bytes(v["data_hex"])
            expected = _parse_hex_scalar(v["crc_hex"])
            parsed.append((data, expected, v))
        except Exception as exc:
            return {"error": f"bad vector {v}: {exc}"}

    n = len(parsed)

    # Try every preset
    for name, poly, init, refin, refout, xorout in CRC8_PRESETS:
        matches = 0
        mismatches = []
        for data, expected, v in parsed:
            got = crc_compute(data, 8, poly, init, refin, refout, xorout)
            if got == expected:
                matches += 1
            else:
                mismatches.append({
                    "data_hex": v["data_hex"], "expected": f"0x{expected:02X}",
                    "got": f"0x{got:02X}",
                })
        cfg = {
            "preset": name, "poly": f"0x{poly:02X}",
            "init": f"0x{init:02X}", "refin": refin, "refout": refout,
            "xorout": f"0x{xorout:02X}", "matched": matches, "total": n,
        }
        if matches == n:
            full_matches.append(cfg)
        elif matches >= int(0.8 * n):
            cfg["mismatches_sample"] = mismatches[:3]
            near_misses.append(cfg)

    # Also brute-force scan over every 8-bit poly with common init/refin combos,
    # in case the spec uses a non-standard CRC.
    if not full_matches:
        for poly in range(1, 256):
            for init in (0x00, 0xFF):
                for refin in (True, False):
                    refout = refin  # refin/refout tied in the vast majority of real CRCs
                    xorout = 0
                    m = 0
                    for data, expected, v in parsed:
                        if crc_compute(data, 8, poly, init, refin, refout, xorout) == expected:
                            m += 1
                    if m == n:
                        full_matches.append({
                            "preset": "brute-force",
                            "poly": f"0x{poly:02X}",
                            "init": f"0x{init:02X}",
                            "refin": refin, "refout": refout,
                            "xorout": f"0x{xorout:02X}",
                            "matched": m, "total": n,
                        })

    # Deduplicate full_matches on (poly, init, refin, refout, xorout)
    seen = set()
    unique = []
    for cfg in full_matches:
        key = (cfg["poly"], cfg["init"], cfg["refin"], cfg["refout"], cfg["xorout"])
        if key not in seen:
            seen.add(key)
            unique.append(cfg)
    full_matches = unique

    return {
        "vectors_total": n,
        "all_full_matches": full_matches,
        "best_match": full_matches[0] if full_matches else None,
        "near_misses": sorted(near_misses,
                               key=lambda c: -c["matched"])[:5],
    }


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("input_json",
                   help="JSON file with 'width' and 'vectors' (see docstring)")
    p.add_argument("--json", help="Write result JSON to this path")
    p.add_argument("--min-vectors", type=int, default=3,
                   help="Minimum vector count required to trust the derivation")
    args = p.parse_args(argv)

    try:
        spec = json.loads(Path(args.input_json).read_text())
    except Exception as exc:
        print(f"cmd_protocol_crc_verify: cannot read {args.input_json}: {exc}",
              file=sys.stderr)
        return 2

    # v0.56: no-protocol sentinel — when an L3 doc declares
    # `protocol_present: false`, this gate is N/A. Memory-access /
    # register-pointer / analog-front-end ICs have no command CRC to
    # derive. Exit 0 cleanly so the gate doesn't block the rest of
    # the flow. JSON report records the skip with the supplied reason.
    if spec.get("protocol_present") is False:
        reason = spec.get("reason", "no reason given")
        report = {
            "skipped": True,
            "reason": f"L3 sentinel: protocol_present=false ({reason})",
            "vectors_total": 0,
            "best_match": None,
            "all_full_matches": [],
            "near_misses": [],
        }
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2,
                                                  ensure_ascii=False))
        print(f"cmd_protocol_crc_verify: SKIPPED (no-protocol sentinel: {reason})")
        return 0

    width = int(spec.get("width", 8))
    vectors = spec.get("vectors", [])
    if not isinstance(vectors, list) or len(vectors) < args.min_vectors:
        print(f"cmd_protocol_crc_verify: need >= {args.min_vectors} vectors, "
              f"got {len(vectors)}", file=sys.stderr)
        return 1

    result = verify(vectors, width)

    if "error" in result:
        print(f"cmd_protocol_crc_verify: {result['error']}", file=sys.stderr)
        return 2

    n_full = len(result["all_full_matches"])
    print(f"\n=== cmd_protocol_crc_verify ===")
    print(f"  vectors: {result['vectors_total']}")
    print(f"  full matches: {n_full}")
    if n_full:
        bm = result["best_match"]
        print(f"  best: {bm['preset']}")
        print(f"        poly={bm['poly']} init={bm['init']} "
              f"refin={bm['refin']} refout={bm['refout']} "
              f"xorout={bm['xorout']}")
    else:
        print(f"  NO full match. Top near-miss:")
        for nm in result["near_misses"][:3]:
            print(f"    {nm['preset']}: {nm['matched']}/{nm['total']}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    return 0 if n_full > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
