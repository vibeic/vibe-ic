#!/usr/bin/env python3
"""
oracle_dump_required_check.py — Category-B workflow gate.

Why this gate exists
====================
Some L3 fields_tx items cannot be resolved to byte-exact form from
L1-L23 alone because the vendor doc disagrees with the actual silicon
(Category B). v0118-vendor STATUS lists 4 such items: 0xE6 length
22→18, 0xE4 drop trailing 0x20, 0xE2 missing opcode, 0x76 OTP scatter
non-contiguous addresses. Plugin extractors cannot detect these — the
spec says one thing, the chip does another.

When that happens, the spec-to-rtl Rule G workflow says:
  1. Capture the oracle byte stream with eda_oracle_bytewise_dump.
  2. Diff vs L3 fields_tx.
  3. Patch L3 to match silicon, document in waivers.json
     under key `oracle_referenced_fix`.

This gate enforces step 1: if `waivers.json` references
`oracle_referenced_fix`, the project must contain a captured oracle
bytewise dump artifact. No silent oracle reference allowed.

Rule
----
If `waivers.json` has key `oracle_referenced_fix` (any non-empty
value), the project must contain at least one of:

    input/oracle/<name>_bytewise_dump.json
    input/oracle/<name>_bytewise_dump.csv
    docs/oracle_dump.md

Else FAIL with the workflow instruction.

If no waivers.json reference, gate skips (PASS).

Usage
-----
python3 oracle_dump_required_check.py <project_dir>

Returns 0 on PASS, 1 on FAIL.
"""

import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: oracle_dump_required_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    waivers_path = project_dir / "waivers.json"
    if not waivers_path.exists():
        print("PASS — no waivers.json (gate not applicable)")
        sys.exit(0)
    try:
        waivers = json.loads(waivers_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse waivers.json: {e}")
        sys.exit(1)

    oracle_ref = waivers.get("oracle_referenced_fix")
    if not oracle_ref:
        print("PASS — waivers.json does not reference oracle_referenced_fix")
        sys.exit(0)

    # Look for an oracle dump artifact.
    candidates = [
        project_dir / "input" / "oracle",
        project_dir / "docs" / "oracle_dump.md",
    ]
    found = []
    for c in candidates:
        if c.is_dir():
            for f in c.iterdir():
                if "bytewise_dump" in f.name and \
                   f.suffix in (".json", ".csv", ".txt"):
                    found.append(str(f.relative_to(project_dir)))
        elif c.is_file():
            found.append(str(c.relative_to(project_dir)))

    if found:
        print(f"PASS — oracle bytewise dump artifact present "
              f"({len(found)} file(s))")
        for f in found[:3]:
            print(f"  • {f}")
        sys.exit(0)

    print("FAIL — waivers.json references `oracle_referenced_fix` but no "
          "captured oracle dump artifact found.")
    print()
    print("Workflow (spec-to-rtl Rule G, Category-B):")
    print("  1. Capture the known-PASS oracle byte stream:")
    print("       mcp__eda-tools__eda_oracle_bytewise_dump")
    print("       → save to input/oracle/<name>_bytewise_dump.json")
    print("  2. Diff vs L3.command_table.fields_tx for each opcode")
    print("  3. Patch L3 fields_tx to match silicon. Each patched")
    print("     field gets an entry in waivers.json:")
    print('       {"oracle_referenced_fix": [')
    print('         {"opcode": "0xE6", "field": "tx_len",')
    print('          "spec": 22, "silicon": 18,')
    print('          "evidence": "input/oracle/example_bytewise_dump.json"}')
    print("       ]}")
    print("  4. Re-run spec-to-rtl. The patched L3 is now byte-exact.")
    print()
    print("Why this matters:")
    print("  Silently using oracle bytes without recording the discrepancy")
    print("  makes the L1-L23 → RTL flow non-reproducible. The next agent")
    print("  reading the spec re-introduces the bug.")
    sys.exit(1)


if __name__ == "__main__":
    main()
