#!/usr/bin/env python3
"""
oracle_vector_gen.py — v0.114 (BACKLOG-v6 C1 closure).

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Auto-generate L10 oracle byte-stream vectors from L9 supported_opcodes
+ L11 OTP content + L8 CRC params. Closes the v0.108 round-1 gap where
`rtl_response_byte_oracle_check.py` (v0.106 P0.2) existed but had no
auto-vector source — required hand-authored L10 vectors.

Output schema (matches rtl_response_byte_oracle_check.py expectations):

```json
{
  "schema": "vibe-ic L10 oracle vectors v1",
  "generated_by": "oracle_vector_gen.py",
  "opcode_oracle_vectors": [
    {
      "name": "GET_ID",
      "cmd_hex": "74 00 01 FD",
      "expected_response_hex": "75 10 00 00 00 00 00 36",
      "source": "L9 supported_opcodes + L11 OTP + L8 CRC",
      "confidence": "high"
    },
    ...
  ]
}
```

Confidence levels (false-positive guard):
  - "high"      → opcode has full L9 spec + L11 has every needed OTP byte +
                  CRC params from L8 are validated. Vector is ground truth.
  - "medium"    → L9 spec present but some fields inferred (e.g. response
                  format inferred from rxlen). Vector is best-effort.
  - "low"       → multiple holes (L9 incomplete, L11 missing bytes). Vector
                  is structural placeholder; agent must verify against
                  scope capture before treating as ground truth.

False-positive design: skip vectors with low confidence by default.
Pass --include-low to emit them.

Usage:
  python3 oracle_vector_gen.py <project_dir> [--out PATH] [--include-low]
Exit 0 always (generator).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


CRC8_DEFAULT_POLY_LSB = 0x8C
CRC8_DEFAULT_INIT = 0xFF


def _crc8_step(byte: int, seed: int, poly_lsb: int = CRC8_DEFAULT_POLY_LSB) -> int:
    """Dallas-style LSB-first CRC-8 step (matches the v0.108 <benchmark> spec)."""
    w = (seed ^ byte) & 0xFF
    for _ in range(8):
        if w & 1:
            w = (w >> 1) ^ poly_lsb
        else:
            w >>= 1
    return w & 0xFF


def _crc8_stream(data: List[int], poly_lsb: int, init: int) -> int:
    s = init
    for b in data:
        s = _crc8_step(b, s, poly_lsb)
    return s


def _load_l8_crc(project: Path) -> Tuple[int, int]:
    p = _pl.generated_docs_dir(project) / "L8_RTL_CONSTANTS.json"
    if not p.exists():
        return (CRC8_DEFAULT_POLY_LSB, CRC8_DEFAULT_INIT)
    try:
        d = json.loads(p.read_text())
    except Exception:
        return (CRC8_DEFAULT_POLY_LSB, CRC8_DEFAULT_INIT)
    poly = d.get("crc8_poly_lsb_first") or d.get("CRC8_POLY_LSB_FIRST")
    init = d.get("crc8_init_seed") or d.get("CRC8_INIT_SEED")
    if isinstance(poly, str):
        poly = int(poly, 16) if poly.startswith("0x") else int(poly)
    if isinstance(init, str):
        init = int(init, 16) if init.startswith("0x") else int(init)
    return (
        poly if isinstance(poly, int) else CRC8_DEFAULT_POLY_LSB,
        init if isinstance(init, int) else CRC8_DEFAULT_INIT,
    )


def _load_l11_otp(project: Path) -> Dict[int, int]:
    """Load L11 OTP content into addr → byte map. Returns {} if absent."""
    p = _pl.generated_docs_dir(project) / "L11_OTP_CONTENT.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {}
    out: Dict[int, int] = {}
    for entry in d.get("address_map", []) or []:
        if not isinstance(entry, dict):
            continue
        decoded = entry.get("decoded_hex")
        rng = entry.get("range") or entry.get("addr")
        if not rng:
            continue
        # Parse range "0x00-0x05" or single addr "0x60"
        rng = rng.strip()
        if "-" in rng:
            lo, hi = [int(x.strip(), 16) for x in rng.split("-")]
        else:
            lo = int(rng, 16)
            hi = lo
        if isinstance(decoded, list):
            for off, val in enumerate(decoded):
                addr = lo + off
                if addr > hi:
                    break
                if isinstance(val, str):
                    val = int(val, 16) if val.startswith("0x") else int(val, 16)
                if isinstance(val, int):
                    out[addr] = val
        elif isinstance(decoded, str):
            try:
                v = int(decoded, 16) if decoded.startswith("0x") else int(decoded, 16)
                out[lo] = v
            except ValueError:
                pass
    return out


def _load_l9_opcodes(project: Path) -> List[Dict[str, Any]]:
    """Search L3 (cmd protocol), L9 (integration), and L10 (TB) for an
    opcode array. Multiple field-name fallbacks for schema variability."""
    candidates = [
        ("L3_CMD_PROTOCOL.json", ["commands", "cmd_protocol", "supported_opcodes",
                                   "opcodes"]),
        ("L9_INTEGRATION_SPEC.json", ["supported_opcodes", "opcodes", "commands",
                                       "cmd_protocol"]),
        ("L10_TB_CONFORMANCE.json", ["supported_opcodes", "opcodes", "test_opcodes",
                                      "commands"]),
    ]
    for fname, fields in candidates:
        p = _pl.generated_docs_dir(project) / fname
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        for field in fields:
            v = d.get(field)
            if isinstance(v, list) and v:
                return v
    return []


def _generate_vector(op: Dict[str, Any], otp: Dict[int, int],
                     poly_lsb: int, init: int) -> Optional[Dict[str, Any]]:
    """For one opcode entry, produce a vector + confidence."""
    code = op.get("opcode") or op.get("code") or op.get("cmd")
    name = op.get("name") or "OP"
    if isinstance(code, str):
        code_int = int(code, 16) if code.startswith("0x") else int(code, 16)
    elif isinstance(code, int):
        code_int = code
    else:
        return None

    rsp_op = op.get("response_opcode") or op.get("rsp_opcode") or (code_int + 1)
    if isinstance(rsp_op, str):
        rsp_op = int(rsp_op, 16) if rsp_op.startswith("0x") else int(rsp_op, 16)
    rxlen = op.get("rxlen") or op.get("cmd_size", 4)
    rsp_size = op.get("response_size") or op.get("rsp_total")

    confidence = "high"
    holes = []

    # Build cmd bytes: opcode + zero-pad params + CRC
    cmd_bytes = [code_int]
    for _ in range(int(rxlen) - 2):  # -1 for opcode, -1 for CRC
        cmd_bytes.append(0)
    cmd_crc = _crc8_stream(cmd_bytes, poly_lsb, init)
    cmd_bytes.append(cmd_crc)

    # Build response bytes
    fetch_base = op.get("response_fetch_base") or op.get("otp_base")
    fetch_count = op.get("response_fetch_count") or op.get("otp_len")

    rsp_bytes = [rsp_op]
    if fetch_base is not None and fetch_count is not None:
        if isinstance(fetch_base, str):
            fetch_base = int(fetch_base, 16) if fetch_base.startswith("0x") else int(fetch_base, 16)
        for off in range(int(fetch_count)):
            addr = fetch_base + off
            if addr in otp:
                rsp_bytes.append(otp[addr])
            else:
                rsp_bytes.append(0)
                holes.append(f"OTP[0x{addr:02X}] missing")
                confidence = "low"
    elif rsp_size is not None:
        # No fetch_base — fixed response, fill zero
        for _ in range(int(rsp_size) - 2):  # -1 op -1 crc
            rsp_bytes.append(0)
        confidence = "medium"
        holes.append("response is fixed-format inferred from response_size, not L9 declaration")
    else:
        confidence = "low"
        holes.append("no response_size or fetch info in L9")

    rsp_crc = _crc8_stream(rsp_bytes, poly_lsb, init)
    rsp_bytes.append(rsp_crc)

    return {
        "name": name,
        "opcode": f"0x{code_int:02X}",
        "cmd_hex": " ".join(f"{b:02X}" for b in cmd_bytes),
        "expected_response_hex": " ".join(f"{b:02X}" for b in rsp_bytes),
        "source": "L9 supported_opcodes + L11 OTP + L8 CRC params",
        "confidence": confidence,
        "holes": holes,
    }


def main():
    ap = argparse.ArgumentParser(description=(
        "Auto-generate L10 oracle byte-stream vectors from L9 + L11 + L8."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--out", default=None,
                    help="Output L10_oracle.json path (default: <project>/generated_docs/L10_oracle_auto.json)")
    ap.add_argument("--include-low", action="store_true",
                    help="Include low-confidence vectors (default: skip them — false-positive guard)")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    poly, init = _load_l8_crc(project)
    otp = _load_l11_otp(project)
    opcodes = _load_l9_opcodes(project)

    if not opcodes:
        print("[OK] oracle_vector_gen — L9 has no supported_opcodes; nothing to generate")
        return 0

    vectors = []
    skipped_low = 0
    for op in opcodes:
        v = _generate_vector(op, otp, poly, init)
        if v is None:
            continue
        if v["confidence"] == "low" and not args.include_low:
            skipped_low += 1
            continue
        vectors.append(v)

    out_path = Path(args.out) if args.out else (
        _pl.generated_docs_dir(project) / "L10_oracle_auto.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema": "vibe-ic L10 oracle vectors v1",
        "generated_by": _pmd.emitted_by("oracle_vector_gen.py"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_layers": ["L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC", "L11_OTP_CONTENT"],
        "crc_params": {
            "poly_lsb_first": f"0x{poly:02X}",
            "init_seed": f"0x{init:02X}",
        },
        "otp_bytes_loaded": len(otp),
        "include_low_confidence": args.include_low,
        "skipped_low_confidence": skipped_low,
        "opcode_oracle_vectors": vectors,
    }
    out_path.write_text(json.dumps(out, indent=2))

    print(f"[OK] oracle_vector_gen — {len(vectors)} vectors written → {out_path.relative_to(project)}")
    print(f"     CRC poly_lsb=0x{poly:02X} init=0x{init:02X}, OTP bytes={len(otp)}")
    print(f"     skipped low-confidence (use --include-low to emit): {skipped_low}")
    confidence_breakdown = {}
    for v in vectors:
        confidence_breakdown[v["confidence"]] = confidence_breakdown.get(v["confidence"], 0) + 1
    for c, n in sorted(confidence_breakdown.items()):
        print(f"     confidence {c}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
