#!/usr/bin/env python3
"""
otp_field_map_check.py — gate that catches L11_OTP_CONTENT.json missing a
byte-address-indexed `field_map` for symbolic names referenced in L3.

Why this gate exists
====================
L3_CMD_PROTOCOL.json `fields_tx` is allowed to use symbolic names
(VID, ID[0..5], SN, MSN) — but only if L11_OTP_CONTENT.json provides
a `field_map` resolving each symbolic name to concrete OTP byte
address(es). Without that map, downstream RTL generation has no
way to fill rsp_buf with the correct bytes from OTP, the agent
guesses (e.g. reads OTP from 0x00 when the real chip reads 0x61),
and real-silicon connect_test FAILs even though BFM passes a sim-
only canned response.

This is the LL-18 companion check on the OTP side. Together they
close Category-A spec-extraction gap.

Rule
----
For every symbolic field name referenced in L3.command_table.fields_tx
that is NOT byte-exact (covered by LL-18), L11_OTP_CONTENT.json
must contain a `field_map` entry resolving it to:

    {"otp_addr":  <int>}                 single byte
    {"otp_addrs": [<int>, <int>, ...]}   scattered bytes

OR the name must appear in waivers.json["otp_field_map_unresolved"].

Usage
-----
python3 otp_field_map_check.py <project_dir>

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


SYMBOLIC_BAREWORD = re.compile(r"^[A-Z][A-Z0-9_]*(\[[\d\.]+\])?$")


def find_doc(project_dir: Path, name: str) -> Path | None:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / name
        if p.exists():
            return p
    return None


def extract_symbolic_names(l3: dict) -> set[str]:
    """Collect every bare symbolic name in L3.command_table.fields_tx."""
    out: set[str] = set()
    for cmd in l3.get("command_table") or []:
        for item in cmd.get("fields_tx") or []:
            if isinstance(item, str):
                s = item.strip()
                if s.startswith("0x"):
                    continue  # literal byte
                if s.upper() in ("CRC", "CRC1", "CRC2", "CRC8", "CRC16"):
                    continue  # CRC marker
                # Strip trailing index ranges (e.g. SN[0..5] → SN)
                base = re.sub(r"\[.*\]$", "", s)
                if SYMBOLIC_BAREWORD.match(base):
                    out.add(base)
    return out


def waived_field(project_dir: Path, name: str) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        unresolved = d.get("otp_field_map_unresolved", [])
        if isinstance(unresolved, str):
            return name in unresolved
        if isinstance(unresolved, list):
            return any(name in str(item) for item in unresolved)
        if isinstance(unresolved, dict):
            return name in unresolved
    except Exception:
        pass
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: otp_field_map_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)
    l3_path = find_doc(project_dir, "L3_CMD_PROTOCOL.json")
    if not l3_path:
        print("PASS — no L3_CMD_PROTOCOL.json (gate not applicable)")
        sys.exit(0)
    try:
        l3 = json.loads(l3_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L3: {e}")
        sys.exit(1)

    symbolic_names = extract_symbolic_names(l3)
    if not symbolic_names:
        print("PASS — L3 fields_tx has no symbolic names "
              "(LL-18 byte-exact already enforces concrete entries)")
        sys.exit(0)

    l11_path = find_doc(project_dir, "L11_OTP_CONTENT.json")
    field_map: dict = {}
    regions: list = []
    if l11_path:
        try:
            l11 = json.loads(l11_path.read_text())
            field_map = l11.get("field_map") or {}
            regions = l11.get("regions") or []
        except Exception:
            pass

    # Build a lookup from regions[*].name → byte range, accepting any
    # of the canonical schemas otp-content-gen has emitted historically.
    def regions_resolve(name: str) -> bool:
        for r in regions:
            if not isinstance(r, dict):
                continue
            rname = str(r.get("name", ""))
            # Accept exact match, or "<name>[idx..idx]" prefix
            base = re.sub(r"\[.*\]$", "", rname)
            if base == name and (r.get("range") or
                                  r.get("otp_addr") is not None or
                                  r.get("otp_addrs")):
                return True
        return False

    missing = []
    for name in sorted(symbolic_names):
        # 1. field_map (preferred byte-exact dict)
        if name in field_map:
            entry = field_map[name]
            if isinstance(entry, dict) and \
               ("otp_addr" in entry or "otp_addrs" in entry):
                continue
            missing.append((name, "field_map entry has no otp_addr/otp_addrs"))
            continue
        # 2. regions array (legacy schema otp-content-gen also emits)
        if regions_resolve(name):
            continue
        if waived_field(project_dir, name):
            continue
        missing.append((name, "not in L11_OTP_CONTENT.field_map / .regions "
                              "and not waived"))

    if not missing:
        print(f"PASS — all {len(symbolic_names)} L3 symbolic names resolve "
              "via L11.field_map (or are waived)")
        sys.exit(0)

    print(f"FAIL — {len(missing)} symbolic field(s) in L3 lack OTP "
          "byte-address resolution:")
    for name, why in missing:
        print(f"  • {name!r}: {why}")
    print()
    print("Why this matters:")
    print("  Fresh-agent RTL has no way to fill rsp_buf for symbolic")
    print("  fields. The agent guesses (e.g. reads OTP from 0x00 when")
    print("  the real chip reads 0x61). BFM passes the agent's own")
    print("  canned bytes; real-silicon connect_test FAILs.")
    print()
    print("Fix: extend L11_OTP_CONTENT.json with field_map:")
    print('    {"field_map": {')
    print('        "VID": {"otp_addr":  0x61},')
    print('        "SN":  {"otp_addrs": [0x76, 0x77, 0x78, ...]},')
    print('        ...')
    print('    }}')
    print()
    print('Or document unresolvable items in waivers.json:')
    print('    {"otp_field_map_unresolved": ["AV — vendor doc names but')
    print('       does not place the byte; needs silicon oracle to resolve."]}')
    sys.exit(1)


if __name__ == "__main__":
    main()
