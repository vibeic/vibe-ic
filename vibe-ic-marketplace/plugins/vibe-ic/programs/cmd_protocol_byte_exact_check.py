#!/usr/bin/env python3
"""
cmd_protocol_byte_exact_check.py — gate that catches L3_CMD_PROTOCOL.json
with symbolic/abstract entries in fields_tx instead of byte-exact bytes.

Why this gate exists
====================
A common skill-extraction failure: cmd-protocol-gen reads vendor docs and
encodes a response payload as a list of *symbolic* names — for example:

    "0x76 Get Interface Device Info":
        fields_tx: ["0x77", "VID", "PID", "REV", "AV", "SN[0..5]", "CRC2"]

A fresh agent compiling RTL from this list cannot generate correct
rsp_buf assignments — there is no mapping from "VID" / "REV" / "AV" /
"SN[0..5]" to the OTP byte addresses the chip must read. The agent
guesses (often wrong), the BFM passes a sim-only canned response, and
real-silicon connect_test then FAILs because the response bytes don't
match what the host expects.

This is category A in the A/B/C analysis: the spec layer has the
information (or could carry it after `otp-content-gen` resolves
symbolic names to addresses), but cmd-protocol-gen left it in
symbolic form for the downstream skill to figure out — and downstream
typically didn't.

Rule: every entry in `fields_tx` must be one of:

    - A literal byte: "0x71", "0x00", "0xCC"
    - An OTP-resolved field with explicit byte address(es), e.g.:
          {"name": "ID[0]", "otp_addr": 0x00}
          {"name": "SMA[0..16]", "otp_addrs": [0x80, 0x81, ..., 0x90]}
    - A computed field with explicit derivation, e.g.:
          {"name": "CRC", "compute": "crc8_reflected"}
          {"name": "REG[0]", "register_id": "REG0"}

Plain bare strings like "VID" or "DATA[0..LEN-1]" or "AV" are FAIL
because they have no byte-level resolution.

The rule is GENERAL — applies to any IC's L3_CMD_PROTOCOL.json.

Usage
-----
python3 cmd_protocol_byte_exact_check.py <project_dir>

Honors waivers.json with key "cmd_protocol_symbolic_intentional".
Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


# Bare strings that look symbolic and have no byte-level resolution.
# These are the patterns we reject as "FAIL — needs concrete resolution".
SYMBOLIC_PATTERNS = (
    re.compile(r"^[A-Z][A-Z0-9_]*$"),                  # VID, PID, REV, AV
    re.compile(r"^[A-Z][A-Z0-9_]*\[[\d\.]+\]$"),       # SN[0..5], ID[0..5]
    re.compile(r"^[A-Z][A-Z0-9_]*\[[\d]+\.\.[A-Z]+(-\d)?\]$"),  # DATA[0..LEN-1]
    re.compile(r"^[A-Z][A-Z0-9_]*\(.*\)$"),            # F8(or OTP@0x6E)
)

# Allowed literal byte forms.
LITERAL_BYTE = re.compile(r"^0x[0-9A-Fa-f]{2}$")
LITERAL_BYTES_RANGE = re.compile(r"^0x[0-9A-Fa-f]+\s*\.\.\s*0x[0-9A-Fa-f]+$")

# v0.119.15: conventional names with implicit zero-fill semantics.
# Across most byte-oriented protocols `RSVD`/`RESERVED`/`PADDING` etc.
# always emit 0x00 — RTL doesn't need explicit per-field byte resolution
# for them. Keep this list narrow: only names with universal zero-fill
# convention. Do NOT add `LEN`, `CMD`, `DATA`, `STATUS`, `PAYLOAD` etc.
# — those genuinely vary per command and need explicit resolution.
_IMPLICIT_ZERO_FILL_NAMES = frozenset({
    "RSVD", "RESERVED", "PADDING", "PAD",
    "ZERO", "ZEROS", "NULL",
})

# CRC marker names — RTL fills these via runtime crc generator.
_CRC_MARKER_NAMES = frozenset({
    "CRC", "CRC1", "CRC2", "CRC8", "CRC16",
})


def find_l3(project_dir: Path) -> Path | None:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / "L3_CMD_PROTOCOL.json"
        if p.exists():
            return p
    return None


def is_byte_exact(item) -> bool:
    """An entry is byte-exact if it's a literal byte, a literal byte range,
    a CRC marker, an implicit-zero-fill conventional name, or a structured
    dict with explicit byte/address info."""
    if isinstance(item, str):
        s = item.strip()
        if LITERAL_BYTE.match(s) or LITERAL_BYTES_RANGE.match(s):
            return True
        if s.upper() in _CRC_MARKER_NAMES:
            return True
        if s.upper() in _IMPLICIT_ZERO_FILL_NAMES:
            return True
        return False
    if isinstance(item, dict):
        # Dict entries with concrete resolution.
        if "byte" in item or "value_hex" in item:
            return True
        if "otp_addr" in item or "otp_addrs" in item:
            return True
        if "register_id" in item:
            return True
        if "compute" in item:
            return True
        return False
    return False


def is_symbolic(item) -> bool:
    if not isinstance(item, str):
        return False
    s = item.strip()
    if LITERAL_BYTE.match(s) or LITERAL_BYTES_RANGE.match(s):
        return False
    if s.upper() in _CRC_MARKER_NAMES:
        return False
    if s.upper() in _IMPLICIT_ZERO_FILL_NAMES:
        return False
    return any(p.match(s) for p in SYMBOLIC_PATTERNS)


def _load_waiver_config(project_dir: Path) -> dict:
    """Return parsed waiver config. Three forms supported:

      1. {"cmd_protocol_symbolic_intentional": true}
         — project-wide waiver, all symbolic fields silenced.
      2. {"cmd_protocol_symbolic_intentional": "<rationale string>"}
         — same as form 1 (truthy string), with rationale recorded.
      3. {"cmd_protocol_symbolic_intentional":
            {"per_field": ["LEN", "STATUS", ...],
             "rationale": "..."}}
         — v0.119.15: per-field waiver. Only the listed names are
         silenced; other symbolic fields still FAIL the gate.
    """
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return {}
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return {}
    val = d.get("cmd_protocol_symbolic_intentional")
    if val is True or (isinstance(val, str) and val.strip()):
        return {"mode": "all"}
    if isinstance(val, dict):
        per_field = val.get("per_field")
        if isinstance(per_field, list) and per_field:
            return {
                "mode": "per_field",
                "names": frozenset(str(n).upper().strip()
                                   for n in per_field if str(n).strip()),
            }
        # Truthy dict with no per_field → treat as project-wide.
        return {"mode": "all"}
    return {}


def waived(project_dir: Path) -> bool:
    """Back-compat shim: returns True iff project has a project-wide
    waiver (form 1 or 2). Per-field waivers are evaluated inline."""
    cfg = _load_waiver_config(project_dir)
    return cfg.get("mode") == "all"


def main():
    if len(sys.argv) < 2:
        print("Usage: cmd_protocol_byte_exact_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)
    l3_path = find_l3(project_dir)
    if not l3_path:
        print("PASS — no L3_CMD_PROTOCOL.json (gate not applicable)")
        sys.exit(0)
    try:
        l3 = json.loads(l3_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L3_CMD_PROTOCOL.json: {e}")
        sys.exit(1)

    cmds = l3.get("command_table") or []
    if not cmds:
        print("PASS — L3 has no command_table (gate not applicable)")
        sys.exit(0)

    waiver_cfg = _load_waiver_config(project_dir)
    per_field_silenced = (waiver_cfg.get("names")
                          if waiver_cfg.get("mode") == "per_field"
                          else frozenset())
    failures = []
    for cmd in cmds:
        op = cmd.get("opcode", "?")
        name = cmd.get("name", "")
        fields_tx = cmd.get("fields_tx") or []
        for idx, item in enumerate(fields_tx):
            if is_byte_exact(item):
                continue
            if is_symbolic(item):
                # v0.119.15: per-field waiver. The base symbolic name
                # (strip [..] / (..) decoration) is matched against the
                # per_field allowlist.
                if isinstance(item, str) and per_field_silenced:
                    base = re.split(r"[\[\(]", item.strip(), 1)[0].upper()
                    if base in per_field_silenced:
                        continue
                failures.append({
                    "opcode": op,
                    "name": name,
                    "field_idx": idx,
                    "symbolic": item,
                })

    if not failures:
        print("PASS — every L3 fields_tx entry is byte-exact "
              "(literal bytes, OTP-addr-resolved, CRC marker, or "
              "structured dict with explicit byte info)")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} symbolic fields_tx "
              "entries (waiver set)")
        sys.exit(0)

    print(f"FAIL — L3_CMD_PROTOCOL.json has {len(failures)} fields_tx "
          "entries left in SYMBOLIC form (needs byte-level resolution):")
    for f in failures[:15]:
        print(f"  • opcode {f['opcode']} ({f['name']!r}) field[{f['field_idx']}] = "
              f"{f['symbolic']!r}")
    if len(failures) > 15:
        print(f"  ... and {len(failures) - 15} more")
    print()
    print("Why this matters:")
    print("  RTL must emit concrete byte values. A symbolic entry like")
    print('  "VID" or "SN[0..5]" gives the agent no way to fill rsp_buf;')
    print("  it guesses (e.g., reads OTP from address 0x00 when the real")
    print("  chip reads from 0x61), the BFM passes a canned-payload sim,")
    print("  and the host's connect_test FAILs on real silicon because")
    print("  the bytes don't match.")
    print()
    print("Fix: re-run cmd-protocol-gen + otp-content-gen with byte-exact")
    print("     mode. Each fields_tx entry should resolve to one of:")
    print('       - "0xXX"                     (literal byte)')
    print('       - "0xXX..0xYY"               (literal byte range)')
    print('       - {"otp_addr": 0xNN}         (single OTP byte)')
    print('       - {"otp_addrs": [...]}       (scattered OTP bytes)')
    print('       - {"register_id": "REG0"}    (RAM-backed register)')
    print('       - {"compute": "crc8_reflected"}  (runtime CRC)')
    print('       - "CRC" / "CRC1" / "CRC2"    (CRC marker — accepted)')
    print()
    print('Or document an exception in waivers.json (one of):')
    print('    {"cmd_protocol_symbolic_intentional": "<reason>"}')
    print('    {"cmd_protocol_symbolic_intentional":')
    print('       {"per_field": ["LEN", "STATUS"], "rationale": "..."}}')
    sys.exit(1)


if __name__ == "__main__":
    main()
