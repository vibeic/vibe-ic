#!/usr/bin/env python3
"""pdk_metal_density_windows.py — serve a PDK's OWN per-layer density window.

`metal_layer_density_check` judges each metal layer's density against a window.
Until now nothing ever supplied one: its only caller passed an empty dict, so
every run — on every PDK — was judged by the gate's generic DISCLOSED default,
while the foundry's real numbers sat unread in the PDK tree. This module is the
supply side. It does not decide anything; it reads the window table out of
`pdk_registry.json` (where the per-PDK data already lives) and hands it to the
gate together with the provenance of where each number was measured from.

Design points that are load-bearing:

  * A bound may be `null`. Some PDKs state a minimum and no maximum; a null
    bound means "this PDK states nothing here", and the consumer falls back to
    its generic default FOR THAT BOUND ALONE and says so. Filling a null in with
    a neighbouring PDK's number would be fabricating a foundry rule.
  * An EMPTY layer table is a real answer, not a missing one. It records that
    the PDK was read and states no density rule at all, so the generic default
    stands on evidence rather than on nobody having looked.
  * An UNKNOWN pdk name resolves to no windows at all — the pre-existing
    behaviour, unchanged. A PDK whose rules we have not read must not be judged
    by another PDK's numbers.

Usage:
    python3 pdk_metal_density_windows.py <pdk-name> [--json OUT]
    windows_for_pdk(name) -> (windows, provenance)
    main(argv) -> int : 0 windows found / 1 none for this PDK / 2 IO error.

chip-AGNOSTIC: no design/vendor literal here; this module only reads a data file
and reshapes it. The PDK names are keys in that data file, not code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REGISTRY_PATH = Path(__file__).resolve().parent / "pdk_registry.json"

# A per-layer window as served to the gate. Either bound may be None, meaning
# "the PDK states no bound here" (NOT "no rule" and NOT "unbounded").
Window = Tuple[Optional[float], Optional[float]]


def _load_registry(path: Optional[Path] = None) -> dict:
    p = path or _REGISTRY_PATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def _entry_for(name: str, registry: dict) -> Optional[dict]:
    """Case-insensitive lookup of a PDK entry by its registry name."""
    if not name:
        return None
    want = name.strip().lower()
    for e in registry.get("pdks", []) or []:
        if isinstance(e, dict) and str(e.get("name", "")).lower() == want:
            return e
    return None


def _coerce_bound(v: object) -> Optional[float]:
    """A stated bound -> float; a null / unparsable bound -> None (unstated).

    A percentage (>1) is normalised to a fraction so the table can be written in
    whichever unit the PDK source states it in without the reader having to
    remember which one this file chose.
    """
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f / 100.0 if f > 1.0 else f


def windows_for_pdk(name: str,
                    registry_path: Optional[Path] = None
                    ) -> Tuple[Dict[str, Window], Dict[str, object]]:
    """Return (windows, provenance) for `name`.

    `windows` maps a lower-cased layer name to a (min, max) pair in which either
    bound may be None. `provenance` always explains WHICH of the three distinct
    outcomes this is, because they mean different things and a caller that
    conflates them will misreport its own confidence:

        status="stated"        the PDK states windows; they are in `windows`
        status="states-none"   the PDK was read and states no density rule
        status="unknown-pdk"   this PDK is not in the registry — not read
    """
    reg = _load_registry(registry_path)
    if not reg:
        return {}, {"status": "unknown-pdk", "pdk": name,
                    "detail": "PDK registry unreadable"}
    entry = _entry_for(name, reg)
    if entry is None:
        return {}, {
            "status": "unknown-pdk", "pdk": name,
            "detail": ("no registry entry for this PDK — its density rules have "
                       "not been read, so no foundry window is supplied and the "
                       "caller's disclosed generic default stands")}

    block = entry.get("metal_density_windows")
    if not isinstance(block, dict):
        return {}, {
            "status": "unknown-pdk", "pdk": entry.get("name", name),
            "detail": ("registry entry carries no metal_density_windows block — "
                       "this PDK's density rules have not been measured")}

    raw = block.get("layers")
    layers: Dict[str, Window] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                continue
            lo, hi = _coerce_bound(v[0]), _coerce_bound(v[1])
            if lo is None and hi is None:
                continue  # a pair that states neither bound states nothing
            layers[str(k).lower()] = (lo, hi)

    prov: Dict[str, object] = {
        "status": "stated" if layers else "states-none",
        "pdk": entry.get("name", name),
        "layers_stated": len(layers),
        "bounds_unstated": sorted(
            layer for layer, (lo, hi) in layers.items() if lo is None or hi is None),
    }
    # Carry every `_`-prefixed annotation through verbatim: the measurement
    # provenance, the corroborating source, and — where they exist — the
    # recorded disagreement / partiality notes. A verdict that cites a foundry
    # number should be able to show where the number came from.
    for k, v in block.items():
        if k.startswith("_"):
            prov[k.lstrip("_")] = v
    return layers, prov


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Serve a PDK's own per-layer metal-density windows.")
    ap.add_argument("pdk", help="PDK name as spelled in pdk_registry.json")
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ns = ap.parse_args(argv)
    if ns.registry is not None and not ns.registry.is_file():
        print(f"registry not found: {ns.registry}", file=sys.stderr)
        return 2
    wins, prov = windows_for_pdk(ns.pdk, ns.registry)
    out = json.dumps(
        {"windows": {k: list(v) for k, v in sorted(wins.items())},
         "provenance": prov}, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    return 0 if wins else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
