#!/usr/bin/env python3
"""
crc_seed_consistency_check.py — Validate that RTL CRC params match spec test vectors.

Common bug class: an RTL author copies a CRC polynomial from spec but uses
the wrong INIT seed (0x00 vs 0xFF), wrong reflection (in / out), or wrong
output XOR. The bit pattern looks plausible in waveforms but the host
tester rejects every response. The fresh-agent benchmark surfaced exactly
this — RTL had `crc_q <= 8'h00` but spec C-code seeded 0xFF (Dallas /
1-Wire variant).

This gate runs a Python CRC simulator with the *RTL-declared* parameters,
computes CRC for each spec-supplied test vector, and flags any mismatch
along with which spec source vouches for the expected value. Saves the
"why does my response always fail CRC check on the host" debug loop.

Generality: any CRC-N variant (default supports up to 64-bit) on any
single-wire / serial / packetised protocol. No chip / tester / PDK names.

Usage:
    python3 crc_seed_consistency_check.py \\
        --vectors-json ./tb/crc_vectors.json

`--out-dir` is OPTIONAL and has no default: omit it and the gate writes no
file at all (verdict on stdout). Pass a project-relative directory —
e.g. `--out-dir ./reports/` — when you want the JSON report on disk.

`crc_vectors.json` schema:
    {
      "rtl_params": {
        "width": 8,
        "init":  "0x00",          // or 0
        "poly":  "0x31",           // forward poly (Dallas) or
        "poly_reflected": "0x8C",  // pre-reflected (use one or the other)
        "reflect_input":  true,
        "reflect_output": true,
        "xor_output":     "0x00"
      },
      "spec_vectors": [
        {
          "input_hex":         "70 00",    // input bytes (space/comma separated)
          "expected_crc_hex":  "AB",
          "source":            "FRS_C_code_line_42",
          "note":              "(optional) extra context"
        },
        ...
      ]
    }

Exit codes:
    0 = PASS (every spec vector matches)
    1 = FAIL (one or more vectors mismatch)
    2 = Usage / file / schema error
"""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Any


def _reflect(value: int, width: int) -> int:
    out = 0
    for i in range(width):
        if value & (1 << i):
            out |= 1 << (width - 1 - i)
    return out


def crc_compute(data: bytes, params: Dict[str, Any]) -> int:
    """Reference CRC implementation. Matches RTL bit-serial when reflect=true."""
    width = int(params["width"])
    if "poly_reflected" in params and params["poly_reflected"] is not None:
        poly = int(str(params["poly_reflected"]), 0)
        # When poly_reflected is given AND reflect_input is also true,
        # the iteration-shift convention matches Dallas / 1-Wire / CRC-8/MAXIM.
        # We unify by always converting to forward poly internally.
        poly = _reflect(poly, width)
    else:
        poly = int(str(params["poly"]), 0)
    init = int(str(params.get("init", 0)), 0)
    refin = bool(params.get("reflect_input", False))
    refout = bool(params.get("reflect_output", False))
    xorout = int(str(params.get("xor_output", 0)), 0)
    mask = (1 << width) - 1

    crc = init & mask
    for b in data:
        if refin:
            b = _reflect(b, 8)
        crc ^= b << (width - 8)
        for _ in range(8):
            if crc & (1 << (width - 1)):
                crc = ((crc << 1) ^ poly) & mask
            else:
                crc = (crc << 1) & mask
    if refout:
        crc = _reflect(crc, width)
    crc ^= xorout
    return crc & mask


def _parse_hex_bytes(s: str) -> bytes:
    cleaned = s.replace(",", " ").split()
    return bytes(int(tok, 16) for tok in cleaned if tok.strip())


@dataclass
class VectorResult:
    input_hex: str
    expected_hex: str
    actual_hex: str
    matches: bool
    source: str
    note: str = ""


@dataclass
class Result:
    status: str
    rtl_params: Dict[str, Any] = field(default_factory=dict)
    vectors_total: int = 0
    vectors_match: int = 0
    vectors_mismatch: int = 0
    vector_results: List[VectorResult] = field(default_factory=list)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--vectors-json", required=True, type=Path)
    # #494 — a read-only validator writes NOTHING unless a caller asks for it.
    # See the sibling note in `sustained_vs_edge_check.py`: a hardcoded
    # `/tmp/<gatename>` default made every invocation deposit a report at a
    # fixed shared path, which concurrent runs overwrite without a trace and
    # which is a standing symlink-hijack target on a multi-user host.
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Directory to write the JSON report into. Omitted "
                         "(the default) = write no file at all; the verdict "
                         "goes to stdout only.")
    args = ap.parse_args(argv)

    if not args.vectors_json.is_file():
        print(f"ERROR: vectors-json not found: {args.vectors_json}", file=sys.stderr)
        return 2
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        spec = json.loads(args.vectors_json.read_text())
    except Exception as e:
        print(f"ERROR: parse {args.vectors_json}: {e}", file=sys.stderr)
        return 2
    rtl = spec.get("rtl_params") or {}
    vectors = spec.get("spec_vectors") or []
    if not rtl or not vectors:
        print("ERROR: vectors-json must contain rtl_params and spec_vectors", file=sys.stderr)
        return 2

    width = int(rtl.get("width", 8))
    nibbles = (width + 3) // 4

    results: List[VectorResult] = []
    for v in vectors:
        in_hex = v.get("input_hex", "")
        exp_hex = v.get("expected_crc_hex", "")
        try:
            data = _parse_hex_bytes(in_hex)
            exp = int(exp_hex, 16)
        except Exception as e:
            results.append(VectorResult(
                input_hex=in_hex, expected_hex=exp_hex, actual_hex="<parse-error>",
                matches=False, source=v.get("source", ""), note=f"parse error: {e}",
            ))
            continue
        actual = crc_compute(data, rtl)
        results.append(VectorResult(
            input_hex=in_hex,
            expected_hex=f"0x{exp:0{nibbles}X}",
            actual_hex=f"0x{actual:0{nibbles}X}",
            matches=(actual == exp),
            source=v.get("source", ""),
            note=v.get("note", ""),
        ))

    matches = sum(1 for r in results if r.matches)
    status = "PASS" if matches == len(results) and len(results) > 0 else "FAIL"
    final = Result(
        status=status,
        rtl_params=rtl,
        vectors_total=len(results),
        vectors_match=matches,
        vectors_mismatch=len(results) - matches,
        vector_results=results,
    )
    # #494 — write only when asked; position preserved so stdout is
    # byte-identical when --out-dir IS supplied.
    out_json = None
    if args.out_dir is not None:
        out_json = args.out_dir / "crc_seed_consistency_check.json"
        out_json.write_text(json.dumps(asdict(final), indent=2))
    print(f"crc_seed_consistency_check: {status} — {matches}/{len(results)} vectors match")
    print(f"rtl_params: width={rtl.get('width')} init={rtl.get('init')} "
          f"poly={rtl.get('poly') or rtl.get('poly_reflected')+' (reflected)'} "
          f"refin={rtl.get('reflect_input')} refout={rtl.get('reflect_output')} "
          f"xorout={rtl.get('xor_output', 0)}")
    for r in results:
        mark = "OK " if r.matches else "FAIL"
        print(f"  [{mark}] in={r.input_hex} expected={r.expected_hex} got={r.actual_hex}  ({r.source})")
        if r.note:
            print(f"          note: {r.note}")
    if out_json is not None:
        print(f"json: {out_json}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
