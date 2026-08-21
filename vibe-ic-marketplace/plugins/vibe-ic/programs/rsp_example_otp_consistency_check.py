#!/usr/bin/env python3
"""
rsp_example_otp_consistency_check.py — L3 response examples must match L11 OTP content.

Problem (2026-04-25, v068 <half-duplex-tester> FAIL root cause #3):
  Phase 1 (doc-extraction) extracted L3_CMD_PROTOCOL.rsp_example for cmd 0x74 as
  `75 10 09 08 00 00 00 A8` (ID bytes = 10 09 08 00 00 00, CRC = 0xA8).
  This is the CANONICAL spec example — taken verbatim from the vendor
  spec doc's "example transaction" section, keyed to a template chip
  with OTP[0..5] = 10 09 08 00 00 00.

  But v068's L11_OTP_CONTENT (and the physical otp_image.mem loaded at
  sim/synth) has OTP[0..5] = 10 00 00 00 00 00 — a DIFFERENT chip's
  serial number.  The spec example and the actual OTP are bound to
  different chip IDs.

  Phase 2 agent built cmd_fsm.v with the CRC from the spec example
  hardcoded as rsp_bytes[7] = 8'hA8.  At runtime the DUT fetches the
  REAL OTP (10 00 00 00 00 00), prepends 0x75, then appends the
  hardcoded CRC 0xA8 — which does NOT match the data payload's actual
  CRC (0x47 for `75 10 00 00 00 00 00`).  Every response failed the
  <half-duplex-tester> tester's CRC check.

  v052 avoided this by computing CRC dynamically from the rsp payload
  bytes at runtime (not hardcoding).  v068 agent conflated "L10 example
  CRC in the spec" with "CRC to emit in RTL".

Rule enforced
-------------
For every L3_CMD_PROTOCOL.opcodes[].rsp_example that contains bytes
sourced from the OTP (ID, MSN, ASN, SMA, FCH, VID/PID, etc.), each of
those byte positions in the response MUST equal the same byte position
in L11_OTP_CONTENT.

Additionally, the CRC byte at the end of the rsp_example MUST verify
against the declared CRC polynomial over the example's preceding
bytes — OR the doc must declare `"crc_policy": "runtime-compute"` on
that opcode to indicate the example CRC is illustrative only and RTL
will compute it dynamically.

Usage
-----
    rsp_example_otp_consistency_check.py <L3_CMD_PROTOCOL.json>
        --otp <L11_OTP_CONTENT.json>
        [--poly 0x8C --reflected --init 0xFF]
        [--json]

Exit codes
----------
    0 = every rsp_example either matches L11 OTP at the OTP-sourced
        positions AND passes CRC, OR is marked runtime-compute.
    1 = any inconsistency or CRC mismatch.
    2 = IO / JSON parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# OTP-sourced opcodes and their response-byte layout.
# (opcode, otp_start_index, num_otp_bytes_in_response, response_starts_at_byte)
OTP_SOURCED = {
    "0X74": (0,   6, 1),   # ID[0..5]  at rsp_bytes[1..6]
    "0X78": (6,  20, 1),   # MSN[0..19]
    "0X7A": (26, 20, 1),   # ASN[0..19]
    "0XE6": (63, 20, 1),   # SMA[0..19]  (offset varies per PDK)
    "0XE8": (49, 14, 1),   # FCH[0..13]  (offset varies per PDK)
}


@dataclass
class Finding:
    severity: str
    rule: str
    opcode: str
    message: str


def _parse_hex_seq(s: Any) -> list[int] | None:
    """Parse 'AA BB CC' / 'AA,BB,CC' / '[0xAA,0xBB]' / a list into [int,...]."""
    if isinstance(s, list):
        out = []
        for item in s:
            if isinstance(item, int):
                out.append(item & 0xFF)
            elif isinstance(item, str):
                m = re.fullmatch(r"\s*(?:0[xX])?([0-9a-fA-F]{1,2})\s*", item)
                if m:
                    out.append(int(m.group(1), 16))
                else:
                    return None
        return out
    if not isinstance(s, str):
        return None
    # Extract all 2-hex-digit tokens, allowing 0x prefix
    tokens = re.findall(r"\b(?:0[xX])?([0-9a-fA-F]{1,2})\b", s)
    if not tokens:
        return None
    try:
        return [int(t, 16) for t in tokens]
    except ValueError:
        return None


def _crc8_maxim(data: list[int], init: int = 0xFF, poly_reflected: int = 0x8C) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ poly_reflected) if (crc & 1) else (crc >> 1)
    return crc & 0xFF


def _otp_bytes(otp_doc: Any, start: int, n: int) -> list[int] | None:
    """Extract n bytes starting at `start` from L11_OTP_CONTENT."""
    # Accept several shapes:
    #   {"otp": {"0x00": "0x10", "0x01": "0x00", ...}}
    #   {"bytes": [16, 0, 0, ...]}
    #   {"content_hex": "10 00 00 ..."}
    #   {"otp_bytes": [...]}
    for key in ("otp_bytes", "bytes", "content", "otp_content", "content_hex"):
        if key in otp_doc:
            v = otp_doc[key]
            seq = _parse_hex_seq(v) if not isinstance(v, list) else v
            if isinstance(seq, list) and len(seq) >= start + n:
                return [int(x) & 0xFF for x in seq[start:start + n]]
    # otp table / dict form: {"0x00": "0x10", ...} or {0: 0x10, ...}
    for key in ("otp", "table", "otp_map"):
        if key in otp_doc and isinstance(otp_doc[key], dict):
            tbl = otp_doc[key]
            out: list[int] = []
            for i in range(start, start + n):
                # look up as int, hex-string, or plain string
                for k_try in (i, str(i), f"0x{i:02X}", f"0x{i:02x}", f"{i:02X}", f"{i:02x}"):
                    if k_try in tbl:
                        v = tbl[k_try]
                        if isinstance(v, int):
                            out.append(v & 0xFF)
                        elif isinstance(v, str):
                            m = re.fullmatch(r"\s*(?:0[xX])?([0-9a-fA-F]{1,2})\s*", v)
                            if m:
                                out.append(int(m.group(1), 16))
                            else:
                                return None
                        break
                else:
                    return None
            if len(out) == n:
                return out
    return None


def check(l3: Any, otp: Any, poly_ref: int = 0x8C, crc_init: int = 0xFF) -> list[Finding]:
    findings: list[Finding] = []

    # Locate opcode list: either top-level "opcodes": [...] or a flat
    # per-opcode dict.
    opcodes_list: list[dict] = []
    if isinstance(l3, dict):
        for key in ("opcodes", "commands", "cmds"):
            v = l3.get(key)
            if isinstance(v, list):
                opcodes_list = [x for x in v if isinstance(x, dict)]
                break

    if not opcodes_list:
        # v0.2.55 — N/A escape for genuinely NON-PROTOCOL ICs (CPU SoCs, pure
        # datapath, reused-IP glue). When L3 truthfully declares it has no
        # command opcodes (`no_opcodes_in_input: true` /
        # `command_protocol_applicable: false`), there is nothing to cross-check
        # against OTP — the rsp-example↔OTP consistency oracle is N/A, not a
        # defect. Return NO findings (gate is VACUOUS PASS). A protocol IC that
        # SHOULD have opcodes but doesn't still FAILs (no honest N/A flag).
        # chip-AGNOSTIC: keyed on L3's own declaration, never a chip name.
        if isinstance(l3, dict) and (
                l3.get("no_opcodes_in_input") is True
                or l3.get("command_protocol_applicable") is False):
            return findings
        findings.append(Finding(
            "ERROR", "no_opcodes_found", "(root)",
            "L3 must contain a list of opcodes under 'opcodes' or 'commands'.",
        ))
        return findings

    for entry in opcodes_list:
        op_str = str(entry.get("opcode") or entry.get("op") or "").strip().lower()
        if not op_str.startswith("0x"):
            continue
        op_u = op_str.upper()

        rsp_example = entry.get("rsp_example") or entry.get("response_example") or entry.get("rsp")
        if rsp_example is None:
            continue

        # Parse the example to a byte list
        rsp_bytes = _parse_hex_seq(rsp_example)
        if rsp_bytes is None:
            findings.append(Finding(
                "ERROR", "unparseable_rsp_example", op_u,
                f"rsp_example could not be parsed as a hex byte sequence: {rsp_example!r}",
            ))
            continue

        policy = str(entry.get("crc_policy", "")).lower()

        # (A) OTP consistency — if this opcode is OTP-sourced, compare
        #     the OTP-origin bytes in rsp_example to L11 OTP content.
        if op_u in OTP_SOURCED:
            otp_start, n_otp, rsp_offset = OTP_SOURCED[op_u]
            # Require enough bytes in example: opcode + n_otp + CRC
            min_len = rsp_offset + n_otp + 1
            if len(rsp_bytes) < min_len:
                findings.append(Finding(
                    "ERROR", "rsp_example_too_short", op_u,
                    f"rsp_example length {len(rsp_bytes)} < expected {min_len} "
                    f"(opcode + {n_otp} OTP bytes + CRC).",
                ))
                continue
            example_otp = rsp_bytes[rsp_offset:rsp_offset + n_otp]
            actual_otp = _otp_bytes(otp, otp_start, n_otp)
            if actual_otp is None:
                findings.append(Finding(
                    "ERROR", "otp_lookup_failed", op_u,
                    f"Could not extract OTP[{otp_start}..{otp_start+n_otp-1}] "
                    f"from L11_OTP_CONTENT.",
                ))
                continue
            if example_otp != actual_otp:
                findings.append(Finding(
                    "ERROR", "rsp_example_otp_mismatch", op_u,
                    f"rsp_example OTP-sourced bytes "
                    f"{[f'0x{b:02X}' for b in example_otp]} do NOT match "
                    f"L11 OTP[{otp_start}..{otp_start+n_otp-1}] = "
                    f"{[f'0x{b:02X}' for b in actual_otp]}. Phase 2 will "
                    f"hardcode the example's CRC, but at runtime the DUT "
                    f"reads the real OTP — CRC mismatch → tester FAIL. "
                    f"Either sync OTP content with the example chip, or "
                    f"set crc_policy=runtime-compute on this opcode.",
                ))

        # (B) CRC self-consistency — example's last byte must match
        #     computed CRC over preceding bytes.
        if len(rsp_bytes) >= 2 and policy != "runtime-compute" and policy != "illustrative":
            payload = rsp_bytes[:-1]
            claimed_crc = rsp_bytes[-1]
            computed_crc = _crc8_maxim(payload, init=crc_init, poly_reflected=poly_ref)
            if claimed_crc != computed_crc:
                findings.append(Finding(
                    "ERROR", "rsp_example_crc_mismatch", op_u,
                    f"rsp_example CRC 0x{claimed_crc:02X} != computed "
                    f"0x{computed_crc:02X} over "
                    f"{[f'0x{b:02X}' for b in payload]} with poly_ref="
                    f"0x{poly_ref:02X} init=0x{crc_init:02X}. Either fix "
                    f"the CRC in the example, change poly, or mark opcode "
                    f"crc_policy=runtime-compute.",
                ))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify L3 rsp_example bytes match L11 OTP + self-consistent CRC.",
    )
    ap.add_argument("l3", help="L3_CMD_PROTOCOL.json")
    ap.add_argument("--otp", required=True, help="L11_OTP_CONTENT.json")
    ap.add_argument("--poly", default="0x8C", help="Reflected CRC polynomial (default 0x8C = MAXIM).")
    ap.add_argument("--init", default="0xFF", help="CRC initial value (default 0xFF).")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    try:
        with open(args.l3, "r") as f:
            l3 = json.load(f)
        with open(args.otp, "r") as f:
            otp = json.load(f)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: JSON parse: {e}", file=sys.stderr)
        return 2

    try:
        poly = int(args.poly, 16) if args.poly.lower().startswith("0x") else int(args.poly)
        init = int(args.init, 16) if args.init.lower().startswith("0x") else int(args.init)
    except ValueError as e:
        print(f"error: invalid poly/init: {e}", file=sys.stderr)
        return 2

    findings = check(l3, otp, poly_ref=poly, crc_init=init)
    errors = [f for f in findings if f.severity == "ERROR"]

    if args.json:
        _txt = json.dumps({
            "source_file": args.l3,
            "otp_file": args.otp,
            "total_findings": len(findings),
            "errors": len(errors),
            "findings": [asdict(f) for f in findings],
            "verdict": "PASS" if not errors else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.opcode}: {f.message}")
        print(f"\n{len(errors)} error(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
