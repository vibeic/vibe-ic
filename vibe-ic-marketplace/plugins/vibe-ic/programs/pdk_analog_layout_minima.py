#!/usr/bin/env python3
"""pdk_analog_layout_minima.py — the target PDK's DRAWN-GEOMETRY minima,
read out of `programs/pdk_registry.json` for whatever family is asked for.

WHAT WAS BROKEN
===============
The analog topology library sized its devices from library CONSTANTS. A
constant cannot know what the target process will let you draw, so a constant
that is legal on one PDK is illegal on the next one, and nothing in the flow
noticed until KLayout-extract -> netgen compared the netlist against the drawn
layout, six steps later:

    w circuit1: 5e-07   circuit2: 3.5e-07   (delta=35.3%, cutoff=0%)
    Final result: Circuits do NOT match uniquely (property errors present)

The layout generator had already clamped the DRAWN device up to the process
minimum — correctly, and it recorded the clamp — but the netlist still carried
the library constant, so the two disagreed by construction on every block.

WHAT THIS MODULE IS
===================
One generic reader. Given a PDK selector it returns that family's
`analog_device_layout_minima` record from the registry, keyed by the same
generic device ROLE tokens the analog IR uses (`res`, `nmos`, `pmos`, `cap`).
A producer then floors its geometry to whatever the resolved family declares.

The floor is **derived, never tuned**: the number is the registry's record of
the PDK's OWN rule (each entry carries `rule`, `rule_text` and the registry
block carries `_measured_from` naming the file and line it was read from). This
module supplies no default, no fallback constant, and no per-family branch — a
family with no record floors nothing, and says so.

chip-AGNOSTIC: no PDK family, foundry, vendor or device name appears anywhere
below. Everything family-specific is DATA in `pdk_registry.json`; adding or
correcting a family's minima is a registry edit with no code change, and this
module behaves identically for a family it has never seen.

RECORD SHAPE (in `pdk_registry.json`, per PDK entry)
====================================================
    "analog_device_layout_minima": {
      "_measured_from": "<file:line — the PDK's own rule record>",
      "roles": {
        "<generic role token>": {
          "min_width_um": <float>,
          "device": "<the foundry primitive the rule is stated for>",
          "rule": "<rule id>",
          "rule_text": "<the rule as the deck states it>"
        }
      }
    }

`roles` is deliberately partial: a role appears only when its rule was actually
read out of that PDK. An ABSENT role means "not measured", which floors
nothing — never "no minimum exists".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_REGISTRY = Path(__file__).resolve().parent / "pdk_registry.json"

# The key the registry states a role's drawn-width floor under.
MIN_WIDTH_KEY = "min_width_um"
_MINIMA_KEY = "analog_device_layout_minima"


def _read_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    try:
        data = json.loads((path or _REGISTRY).read_text(encoding="utf-8",
                                                        errors="replace"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_family(selector: str, path: Optional[Path] = None
                   ) -> Tuple[Optional[str], Dict[str, Any]]:
    """The registry entry whose `name` matches `selector`.

    Exact, then prefix either way, then containment either way: an L-doc
    commonly declares the family by its bare process token while the registry
    entry carries a vendor prefix, and prefix matching ALONE answered None for
    exactly that declared-target case. This is the one matcher — the analog
    producers share it so a selector that resolves for one of them cannot
    silently fail to resolve for another.
    """
    sel = str(selector or "").strip().lower()
    if not sel:
        return None, {}
    for ent in _read_registry(path).get("pdks") or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "")
        if not name:
            continue
        low = name.lower()
        if (low == sel or low.startswith(sel) or sel.startswith(low)
                or sel in low or low in sel):
            return name, ent
    return None, {}


def layout_minima(selector: str, path: Optional[Path] = None
                  ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(family_name, {role: {min_width_um, device, rule, rule_text}})`.

    `({}, )` — an empty role map — is the honest answer for a family the
    registry carries no measured minima for. The caller must record that it
    floored nothing, not assume the geometry was checked."""
    fam, ent = resolve_family(selector, path)
    rec = ent.get(_MINIMA_KEY)
    if not isinstance(rec, dict):
        return fam, {}
    roles = rec.get("roles")
    if not isinstance(roles, dict):
        return fam, {}
    return fam, {str(k): v for k, v in roles.items() if isinstance(v, dict)}


def minima_source(selector: str, path: Optional[Path] = None
                  ) -> Optional[str]:
    """The `_measured_from` citation the family's record carries, or None."""
    _fam, ent = resolve_family(selector, path)
    rec = ent.get(_MINIMA_KEY)
    if isinstance(rec, dict):
        src = rec.get("_measured_from")
        if isinstance(src, str) and src.strip():
            return src
    return None


def min_width_um(roles: Dict[str, Any], role: str) -> Optional[float]:
    """The declared drawn-width floor for `role`, or None when the family
    declares none for it."""
    rec = roles.get(str(role))
    if not isinstance(rec, dict):
        return None
    v = rec.get(MIN_WIDTH_KEY)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def floor_width(value: Any, minimum: Optional[float]
                ) -> Tuple[Any, Optional[float]]:
    """`(value_or_floor, raised_from)`.

    `raised_from` is the ORIGINAL value when the floor moved it and None when
    it did not, so the caller can record the clamp instead of hiding it. A
    value at or above the floor is returned unchanged and byte-identical —
    a floor is not a retune, and a PDK whose minimum sits below the library
    value must come out of here with the library value intact."""
    if minimum is None:
        return value, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value, None
    if float(value) >= float(minimum):
        return value, None
    return float(minimum), float(value)
