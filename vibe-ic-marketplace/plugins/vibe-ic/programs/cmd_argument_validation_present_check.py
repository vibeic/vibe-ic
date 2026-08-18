#!/usr/bin/env python3
"""
cmd_argument_validation_present_check.py — every opcode in
L3_CMD_PROTOCOL.json that takes ≥2 inbound argument bytes must
declare an `argument_validation_predicate` field referencing an L11
constant or an RX_EVENT validation rule.

Why this gate exists
====================
Surfaced by ROOT_CAUSE_ANALYSIS Area 4 (<benchmark> fresh agent vs vendor).
The vendor RX_CMD module has per-opcode VID/PID/range gate predicates
(e.g. `vid_e0_pass_2p5m`, `pid_e0_pass_2p5m`) that hold off the
response unless the inbound argument bytes match OTP-stored
expectations. The fresh agent's cmd-protocol-gen extractor folded all
validation into a coarse opcode+length check, so commands like 0xE0/
0xE2/0xE6 respond unconditionally. That means a host VID/PID
mismatch is not detected, and the chip emits the wrong response
sentinel which the host then mis-interprets.

The doc evidence is RX_EVENT.txt step 8 (translated from the vendor
spec): "For special opcodes, verify the conditions (e.g., E0 and E2
have read-range limits); if the special-case conditions are not met,
do not reply, and clear the FIFO while preserving BR_Flag." I.e., for
every multi-byte arg opcode the receive validator must check argument
range / VID / PID before the chip can respond.

Rule
----
For each opcode in L3_CMD_PROTOCOL.json:
  - Compute arg_byte_count from `arg_bytes` (int) OR the length of
    `fields_rx` after stripping framing slots (CRC, opcode itself).
  - If arg_byte_count >= 2:
      Require a non-empty `argument_validation_predicate` (string).
      If the field is absent or empty string → FAIL.

Skips silently when:
  - L3_CMD_PROTOCOL.json absent
  - L3 declares `protocol_present: false`
  - no opcode has ≥2 inbound argument bytes

Honors waivers.json key `cmd_argument_validation_present_alternative`
(≥20-char rationale).

Usage
-----
python3 cmd_argument_validation_present_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_l3(project: Path) -> Path | None:
    for base in (project, _pl.generated_docs_dir(project)):
        p = base / "L3_CMD_PROTOCOL.json"
        if p.exists():
            return p
    return None


def _is_framing_slot(s: str) -> bool:
    """Is this `fields_rx` entry a framing slot (opcode/CRC/sentinel),
    not an inbound payload byte the host actually controls?"""
    if not isinstance(s, str):
        return False
    su = s.strip().upper()
    if su in ("CRC", "CRC1", "CRC2", "CRC8", "CRC16",
              "OPCODE", "OP", "BREAK", "WAKE", "EOF", "STOP", "START"):
        return True
    # literal byte (e.g. "0x77") — these are framing/opcode bytes
    if re.match(r"^0?X?[0-9A-F]{1,2}$", su):
        return True
    return False


def _arg_byte_count(cmd: dict) -> int:
    """Count inbound argument bytes for an opcode."""
    # 1) explicit numeric arg_bytes / argument_bytes / payload_bytes
    for key in ("arg_bytes", "argument_bytes", "payload_bytes",
                "in_payload_bytes"):
        v = cmd.get(key)
        if isinstance(v, int) and v >= 0:
            return v
        if isinstance(v, str):
            try:
                return int(v, 0)
            except ValueError:
                pass
    # 2) derive from rx_len_bytes - 2 (opcode byte + CRC byte)
    rx_len = cmd.get("rx_len_bytes")
    if isinstance(rx_len, int) and rx_len >= 2:
        return max(rx_len - 2, 0)
    # 3) walk `fields_rx` and count non-framing entries
    fr = cmd.get("fields_rx") or cmd.get("rx_fields")
    if isinstance(fr, list):
        n = 0
        for x in fr:
            if isinstance(x, str) and _is_framing_slot(x):
                continue
            n += 1
        return n
    return 0


def _waived(project: Path) -> bool:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("cmd_argument_validation_present_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: cmd_argument_validation_present_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}")
        return 1

    l3_path = _find_l3(project)
    if l3_path is None:
        print("PASS — no L3_CMD_PROTOCOL.json (gate not applicable)")
        return 0
    l3 = _load_json(l3_path)
    if not l3 or l3.get("protocol_present") is False:
        print("PASS — L3 declares no protocol (gate not applicable)")
        return 0

    cmds = (l3.get("commands") or l3.get("command_table") or [])
    if not isinstance(cmds, list) or not cmds:
        print("PASS — L3 has no commands (gate not applicable)")
        return 0

    fails: list[tuple[str, int]] = []
    checked: list[tuple[str, int]] = []
    for cmd in cmds:
        if not isinstance(cmd, dict):
            continue
        opcode = (cmd.get("opcode") or cmd.get("code") or
                  cmd.get("name") or "?")
        n = _arg_byte_count(cmd)
        if n < 2:
            continue
        checked.append((str(opcode), n))
        pred = cmd.get("argument_validation_predicate")
        if not isinstance(pred, str) or not pred.strip():
            fails.append((str(opcode), n))

    if not checked:
        print("PASS — no opcode takes ≥2 inbound argument bytes "
              "(gate not applicable)")
        return 0

    if not fails:
        print(f"PASS — all {len(checked)} multi-arg opcode(s) declare "
              "argument_validation_predicate")
        for op, n in checked:
            print(f"  • {op} ({n} arg byte(s))")
        return 0

    if _waived(project):
        print(f"PASS_WITH_WAIVER — {len(fails)} multi-arg opcode(s) "
              "lack argument_validation_predicate but waiver is set:")
        for op, n in fails:
            print(f"  • {op} ({n} arg byte(s))")
        return 0

    print(f"FAIL — {len(fails)} of {len(checked)} multi-arg opcode(s) "
          "lack argument_validation_predicate:")
    for op, n in fails:
        print(f"  • opcode {op} takes {n} inbound argument byte(s) "
              "but no validation predicate")
    print()
    print("Why this matters:")
    print("  Multi-byte arg opcodes typically carry a VID/PID/range")
    print("  the chip is supposed to validate against OTP-stored")
    print("  values BEFORE responding (RX_EVENT step 8). Without an")
    print("  explicit predicate, the chip responds to every arg —")
    print("  the host then sees an unexpected response on a mismatch")
    print("  and falls back to a CRC-error sentinel byte.")
    print()
    print("Fix: regenerate L3 with one of (per opcode):")
    print('    "argument_validation_predicate": "L11.VID == arg[0..1]"')
    print('    "argument_validation_predicate": "RX_EVENT.step8_vid_pass"')
    print('    "argument_validation_predicate": "addr in [0x00, 0x7F]"')
    print("Or document an exception in waivers.json (≥20 chars):")
    print('    {"cmd_argument_validation_present_alternative": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
