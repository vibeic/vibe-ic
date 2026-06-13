#!/usr/bin/env python3
"""
regmap_bit_layout_check.py — gate that catches L4_REGMAP.json registers
that don't specify explicit bit positions for their fields.

Why this gate exists
====================
A common Category-A residual: regmap-gen describes registers in prose
("REG[0] holds PH, PT, RD_DIS, GPM bits") without saying which bit is
which. Fresh-agent RTL then guesses the layout — often producing
{PH at bit 0, PT at bit 1, ...} when the silicon actually uses
{PH at bit 7, PT at bit 6, ...}. The chip RTL passes BFM (since BFM
echoes the agent's own bit layout) but real-silicon connect_test
returns wrong REG[0] readback bytes.

Rule
----
For every register in `L4_REGMAP.json.registers` whose `bit_fields`
list is non-empty, every entry must specify either:

    {"name": "PH", "bit": 7}                 single-bit field
    {"name": "MODE", "bits": [4, 5]}         contiguous multi-bit
    {"name": "MODE", "msb": 5, "lsb": 4}     msb/lsb form
    {"name": "RES",  "bit_range": "5:4"}     verilog range string

**Forbidden** (gate FAILs):

    {"name": "PH"}                  no bit position
    {"name": "PH", "bit": null}     null position
    {"name": "PH", "position": "?"} placeholder

Usage
-----
python3 regmap_bit_layout_check.py <project_dir>

Honors waivers.json["regmap_bit_layout_unresolved"].
Returns 0 on PASS, 1 on FAIL.
"""

import json
import sys
from pathlib import Path
import _path_layout as _pl


def find_doc(project_dir: Path, name: str) -> Path | None:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / name
        if p.exists():
            return p
    return None


def field_has_explicit_bits(field: dict) -> bool:
    if not isinstance(field, dict):
        return False
    if isinstance(field.get("bit"), int):
        return True
    if isinstance(field.get("bits"), list) and \
       all(isinstance(b, int) for b in field["bits"]):
        return True
    if isinstance(field.get("msb"), int) and isinstance(field.get("lsb"), int):
        return True
    if isinstance(field.get("bit_range"), str) and ":" in field["bit_range"]:
        return True
    return False


def waived(project_dir: Path, name: str) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        unresolved = d.get("regmap_bit_layout_unresolved", [])
        if isinstance(unresolved, list):
            return any(name in str(item) for item in unresolved)
        return name in str(unresolved)
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: regmap_bit_layout_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    l4_path = find_doc(project_dir, "L4_REGMAP.json")
    if not l4_path:
        print("PASS — no L4_REGMAP.json (gate not applicable)")
        sys.exit(0)
    try:
        l4 = json.loads(l4_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L4: {e}")
        sys.exit(1)

    # L4_REGMAP.json `registers` may be either:
    #   list of dicts: [{"name":"REG0", "bit_fields":[{"name":"PH","bit":7}]}]
    #   dict of dicts: {"REG0": {"bits": {"PH": {"bit":7}}}}
    # Both schemas have appeared in regmap-gen output; accept both.
    raw = l4.get("registers")
    if isinstance(raw, dict):
        reg_iter = [
            {"name": rname, **(rdef if isinstance(rdef, dict) else {})}
            for rname, rdef in raw.items()
        ]
    elif isinstance(raw, list):
        reg_iter = [r for r in raw if isinstance(r, dict)]
    else:
        reg_iter = []

    failures = []
    for reg in reg_iter:
        rname = reg.get("name") or reg.get("addr") or "<unnamed>"
        # bit_fields is the list-schema name, bits is the dict-schema name
        bit_fields = reg.get("bit_fields")
        bits = reg.get("bits")
        field_iter = []
        if isinstance(bit_fields, list):
            field_iter = [(f.get("name") if isinstance(f, dict) else str(f), f)
                          for f in bit_fields]
        elif isinstance(bits, dict):
            field_iter = [(fname, fdef if isinstance(fdef, dict) else {})
                          for fname, fdef in bits.items()]
        for fname, field in field_iter:
            if field_has_explicit_bits(field):
                continue
            if waived(project_dir, f"{rname}.{fname}"):
                continue
            failures.append(f"{rname}.{fname}")

    if not failures:
        print(f"PASS — every L4 register field has explicit bit position(s)")
        sys.exit(0)

    print(f"FAIL — {len(failures)} register field(s) lack explicit bit position:")
    for f in failures[:15]:
        print(f"  • {f}")
    if len(failures) > 15:
        print(f"  ... and {len(failures) - 15} more")
    print()
    print("Why this matters:")
    print("  Without explicit bit positions, fresh-agent RTL guesses the")
    print("  layout. BFM echoes the agent's own ordering and passes; real")
    print("  silicon returns differently-laid-out bytes and connect_test")
    print("  FAILs on 0x72 GET_STATE / 0x70 SET_STATE byte mismatch.")
    print()
    print("Fix: regmap-gen must emit each bit_fields entry as one of:")
    print('    {"name": "PH",   "bit": 7}')
    print('    {"name": "MODE", "msb": 5, "lsb": 4}')
    print('    {"name": "RES",  "bit_range": "5:4"}')
    print()
    print('Or document unresolvable layout in waivers.json:')
    print('    {"regmap_bit_layout_unresolved": ["REG0.PH — vendor doc')
    print('       names but does not place; needs silicon decode."]}')
    sys.exit(1)


if __name__ == "__main__":
    main()
