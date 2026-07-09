#!/usr/bin/env python3
"""pdk_device_map.py — PDK-AGNOSTIC generic->foundry device-map accessor (R13).

An analog corner-sweep deck template needs to instantiate primitive devices
by an ABSTRACT role (an "nmos", a "cap_mim", ...) and have the concrete
foundry model-name filled in per PDK, so the SAME template drives any
populated PDK instead of hardcoding one foundry's token strings. That
generic->foundry mapping is DATA, curated per-PDK in
``programs/pdk_registry.json`` under each PDK's optional ``device_map`` field:

    "device_map": { "nmos": "sg13_lv_nmos", "pmos": "sg13_lv_pmos", ... }

This module is the small reusable READER + VALIDATOR for that data. It is
PDK-agnostic: it never hardcodes a foundry token, it just resolves whatever
the registry declares. The IHP SG13G2 entry is the first populated map (the
real IHP Open-PDK PSP primitive-device names encoded as reusable data — not a
one-off in a sweep script); sky130A / gf180mcuD keep their existing
``device_models`` lists and simply have no ``device_map`` yet, in which case
``device_map()`` returns an empty dict and callers fall back to their
existing behaviour. Nothing here is chip-specific: the registry key is a
PDK family name, never an IC / SKU / vendor codename.

API
    load_registry()                       -> full parsed registry dict
    list_pdks()                           -> [pdk_name, ...]
    device_map(pdk)                       -> {generic: foundry, ...} ({} if none)
    foundry_model(pdk, generic)           -> foundry model name or None
    device_models(pdk)                    -> [legal foundry model tokens]
    validate()                            -> [inconsistency strings]  (empty=OK)

CLI
    python3 pdk_device_map.py --list
    python3 pdk_device_map.py --pdk ihp-sg13g2            # print its map
    python3 pdk_device_map.py --pdk ihp-sg13g2 --generic nmos
    python3 pdk_device_map.py --validate                 # exit 1 on drift

Exit codes: 0 = OK, 1 = validation drift / lookup miss, 2 = registry IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_REGISTRY_PATH = Path(__file__).resolve().parent / "pdk_registry.json"


def load_registry(path: Optional[Path] = None) -> dict:
    """Parse pdk_registry.json. Raises OSError/ValueError on IO/parse error
    so callers can honest-skip; the CLI turns those into exit 2."""
    p = path or _REGISTRY_PATH
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _pdk_entry(reg: dict, pdk: str) -> Optional[dict]:
    for entry in reg.get("pdks", []):
        if isinstance(entry, dict) and entry.get("name") == pdk:
            return entry
    return None


def list_pdks(reg: Optional[dict] = None) -> List[str]:
    reg = reg if reg is not None else load_registry()
    return [e.get("name") for e in reg.get("pdks", [])
            if isinstance(e, dict) and e.get("name")]


def device_map(pdk: str, reg: Optional[dict] = None) -> Dict[str, str]:
    """generic-role -> foundry-model-name map for `pdk`. Empty dict when the
    PDK is unknown or has no `device_map` (caller falls back gracefully)."""
    reg = reg if reg is not None else load_registry()
    entry = _pdk_entry(reg, pdk)
    if not entry:
        return {}
    dm = entry.get("device_map")
    if not isinstance(dm, dict):
        return {}
    return {str(k): str(v) for k, v in dm.items() if isinstance(v, str)}


def foundry_model(pdk: str, generic: str,
                  reg: Optional[dict] = None) -> Optional[str]:
    """Resolve one generic role token to its foundry model name for `pdk`,
    or None when the PDK / role is not mapped."""
    return device_map(pdk, reg).get(generic)


def device_models(pdk: str, reg: Optional[dict] = None) -> List[str]:
    reg = reg if reg is not None else load_registry()
    entry = _pdk_entry(reg, pdk)
    if not entry:
        return []
    models = entry.get("device_models")
    return [str(m) for m in models] if isinstance(models, list) else []


def validate(reg: Optional[dict] = None) -> List[str]:
    """Consistency check across every PDK that declares a `device_map`:
    each mapped foundry value MUST also appear in that PDK's `device_models`
    flat list (so the map and the legal-token set can't silently drift).
    Returns a list of human-readable drift strings; empty list == OK.
    PDK-agnostic: only structural containment is asserted."""
    reg = reg if reg is not None else load_registry()
    problems: List[str] = []
    for entry in reg.get("pdks", []):
        if not isinstance(entry, dict):
            continue
        dm = entry.get("device_map")
        if not isinstance(dm, dict) or not dm:
            continue
        name = entry.get("name", "?")
        models = {str(m) for m in (entry.get("device_models") or [])
                  if isinstance(m, str)}
        if not models:
            problems.append(
                f"{name}: declares device_map but no device_models flat set")
            continue
        for generic, foundry in dm.items():
            if not isinstance(foundry, str):
                problems.append(
                    f"{name}: device_map['{generic}'] is not a string")
                continue
            if foundry not in models:
                problems.append(
                    f"{name}: device_map['{generic}']='{foundry}' not in "
                    f"device_models (generic->foundry map vs legal-token "
                    f"set drift)")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--list", action="store_true",
                    help="list registered PDK names")
    ap.add_argument("--pdk", default=None, help="PDK family name")
    ap.add_argument("--generic", default=None,
                    help="resolve one generic role token (with --pdk)")
    ap.add_argument("--validate", action="store_true",
                    help="check device_map<->device_models consistency")
    ap.add_argument("--json", default=None, help="write result as JSON here")
    args = ap.parse_args(argv)

    try:
        reg = load_registry()
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read pdk_registry.json: {exc}", file=sys.stderr)
        return 2

    if args.validate:
        problems = validate(reg)
        report = {"program": "pdk_device_map", "check": "validate",
                  "ok": not problems, "problems": problems}
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2))
        if problems:
            print("[FAIL] pdk_device_map validate — device_map drift:")
            for p in problems:
                print(f"  {p}")
            return 1
        print(f"[PASS] pdk_device_map validate — {len(list_pdks(reg))} PDK(s), "
              f"all device_map values present in device_models")
        return 0

    if args.list:
        for n in list_pdks(reg):
            dm = device_map(n, reg)
            print(f"{n}\t(device_map: {len(dm)} entries)")
        return 0

    if args.pdk:
        if args.generic:
            m = foundry_model(args.pdk, args.generic, reg)
            if m is None:
                print(f"(no mapping for generic '{args.generic}' in "
                      f"'{args.pdk}')", file=sys.stderr)
                return 1
            print(m)
            return 0
        dm = device_map(args.pdk, reg)
        report = {"pdk": args.pdk, "device_map": dm}
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2))
        if not dm:
            print(f"(PDK '{args.pdk}' has no device_map)", file=sys.stderr)
        for g, f in dm.items():
            print(f"{g}\t{f}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
