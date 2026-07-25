#!/usr/bin/env python3
"""
hardmacro_supply_intent.py — is a hard macro's LEF-typed POWER/GROUND pin
ACCOUNTED FOR by the design's own power-intent layer?

The defect this exists for (#309)
---------------------------------
A hard macro declares a pin `USE POWER` / `USE GROUND` in its OWN LEF. When the
RTL ties that pin to a constant, synthesis inserts a TIEHI/TIELO cell to drive
it — so a SIGNAL net lands on a POWER terminal.

TritonRoute does not skip that net. It ABORTS DETAILED ROUTING ENTIRELY.
Measured on a real design: 3278 signal nets, ZERO routed; LVS and STA
unreachable; the GDS a placed-but-unrouted shell; the same cause across six
plugin versions, surfacing only as a causally-opaque `DRT-0307` five steps
after the information was already available.

The information IS available in Phase 1 — the macro's LEF says `USE POWER`. It
never reached the power-intent layer the back end consumes, so the back end
built a supply network without that rail. The completeness model in use asks
"does this token appear in ANY layer", and the pin name does appear in a
descriptive datasheet layer — so it scored as captured. IT MEASURED THE THING
NEXT TO IT.

ONE decision point, imported by BOTH phases
-------------------------------------------
Phase 1 warns so the requirement flows into the power-intent layer now; Phase 3
blocks before routing. Both call THIS module, so what Phase 1 validates is
exactly what Phase 3 will enforce — two copies of this judgement would drift,
and a drifting supply rule is how the pin got lost in the first place.

Classification
--------------
  declared_rail     an explicit {master, pin, rail} mapping to a rail the
                    design INDEPENDENTLY declares -> accounted for
  declared_gap      an explicit {..., integration_gap: true} -> accounted for
                    (a known, owned gap is disclosure, not silence)
  rail_name_match   the pin name matches a declared rail name -> accounted for
  rail_undeclared   an explicit mapping pointing at a rail the design does NOT
                    independently declare -> DANGLING, NOT accounted for
  undeclared        nothing accounts for it -> the gap

ANTI-CHEAT: `rail_undeclared` is the load-bearing class. Without it a design
could manufacture coverage by naming a ghost rail in the mapping — declaring
100% coverage against rails that do not exist. A pin whose name matches no
declared rail is NEVER silently wired up.

chip-AGNOSTIC: LEF grammar + the design's own L21 fields. No macro names, no
PDK literals, no rail-name allowlist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# `PIN <name>` ... `USE POWER|GROUND` ... `END <name>` — LEF is whitespace and
# newline tolerant, so scan the pin block rather than assuming a line layout.
_PIN_BLOCK_RE = re.compile(
    r"\bPIN\s+(?P<name>[A-Za-z_][\w\[\]\.$<>]*)\b(?P<body>.*?)\bEND\s+(?P=name)\b",
    re.S | re.IGNORECASE)
_USE_RE = re.compile(r"\bUSE\s+(POWER|GROUND)\s*;", re.IGNORECASE)
_MACRO_RE = re.compile(r"\bMACRO\s+([A-Za-z_][\w\.$]*)", re.IGNORECASE)

ACCOUNTED = {"declared_rail", "declared_gap", "rail_name_match"}


def lef_pg_pins(lef_text: str) -> List[Dict[str, str]]:
    """Every LEF-typed POWER/GROUND pin, with the MACRO it belongs to.

    Returns [{"master", "pin", "use"}]. Pure LEF grammar — this is the
    AUTHORITATIVE statement that a pin is a supply terminal, and it is what
    TritonRoute honours when it aborts.
    """
    out: List[Dict[str, str]] = []
    if not lef_text:
        return out
    # Segment by MACRO so each pin is attributed to its own master.
    bounds = [(m.start(), m.group(1)) for m in _MACRO_RE.finditer(lef_text)]
    if not bounds:
        bounds = [(0, "")]
    for i, (start, master) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(lef_text)
        for pm in _PIN_BLOCK_RE.finditer(lef_text[start:end]):
            um = _USE_RE.search(pm.group("body") or "")
            if um:
                out.append({"master": master, "pin": pm.group("name"),
                            "use": um.group(1).upper()})
    return out


def declared_rails(l21: Dict[str, Any]) -> List[str]:
    """Rail names the design INDEPENDENTLY declares in its power-intent layer.

    Independence is the anti-cheat anchor: a hard_macro_supplies mapping may
    only point at one of THESE. A rail invented inside the mapping itself is
    not a declaration, it is a placeholder.
    """
    f = (l21 or {}).get("fields") or {}
    names: List[str] = []
    for r in (f.get("power_rails") or []):
        if isinstance(r, dict):
            v = r.get("rail") or r.get("name")
        else:
            v = r
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
    for d in (f.get("power_domains") or []):
        if isinstance(d, dict):
            for k in ("rail", "supply", "name"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    names.append(v.strip())
    return names


def _rail_token_match(pin: str, rails: List[str]) -> Optional[str]:
    """Does the pin NAME correspond to a declared rail? Compared on normalised
    tokens so `VDD` matches a rail written `VDD / supply (5 V)` — but only as a
    whole token, so `VDD` never matches `AVDD_REF` by substring."""
    def _norm(x: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", x.lower())

    p = _norm(pin)
    if not p:
        return None
    for r in rails:
        # Split on PROSE separators only — whitespace, slash, comma, brackets.
        # The underscore is an IDENTIFIER character: splitting on it made
        # `AVDD_REF / analog reference` yield the token `AVDD`, so pin `AVDD`
        # wrongly matched an AVDD_REF rail while pin `AVDD_REF` matched NOTHING.
        # Both directions were wrong; a supply rule that mis-binds a rail is
        # worse than one that reports a gap.
        for tok in re.split(r"[\s/,;()\[\]]+", r):
            if tok and _norm(tok) == p:
                return r
    return None


def classify_pin(master: str, pin: str, l21: Dict[str, Any]) -> Dict[str, Any]:
    """Classify ONE macro PG pin against the design's power-intent layer."""
    f = (l21 or {}).get("fields") or {}
    rails = declared_rails(l21)
    for m in (f.get("hard_macro_supplies") or []):
        if not isinstance(m, dict):
            continue
        if (str(m.get("master", "")).strip() != master.strip()
                or str(m.get("pin", "")).strip() != pin.strip()):
            continue
        if m.get("integration_gap") is True:
            return {"master": master, "pin": pin, "status": "declared_gap",
                    "detail": "declared as a known integration gap"}
        rail = str(m.get("rail", "")).strip()
        if not rail:
            return {"master": master, "pin": pin, "status": "undeclared",
                    "detail": "mapping present but names no rail"}
        if rail in rails:
            return {"master": master, "pin": pin, "status": "declared_rail",
                    "rail": rail, "detail": f"mapped to declared rail {rail!r}"}
        # ANTI-CHEAT: the mapping points at a rail the design never declared.
        return {"master": master, "pin": pin, "status": "rail_undeclared",
                "rail": rail,
                "detail": (f"mapping points at rail {rail!r}, which the design "
                           f"does not independently declare — dangling, so it "
                           f"does NOT count as coverage")}
    hit = _rail_token_match(pin, rails)
    if hit:
        return {"master": master, "pin": pin, "status": "rail_name_match",
                "rail": hit, "detail": f"pin name corresponds to declared rail {hit!r}"}
    return {"master": master, "pin": pin, "status": "undeclared",
            "detail": "no rail, no mapping, no declared gap accounts for this pin"}


def assess(lef_texts: List[str], l21: Dict[str, Any]) -> Dict[str, Any]:
    """Classify every LEF-typed PG pin across the given macro LEFs."""
    pins: List[Dict[str, Any]] = []
    for txt in lef_texts or []:
        for p in lef_pg_pins(txt):
            pins.append({**classify_pin(p["master"], p["pin"], l21),
                         "use": p["use"]})
    return {
        "pins": pins,
        "accounted": [p for p in pins if p["status"] in ACCOUNTED],
        "gaps": [p for p in pins if p["status"] not in ACCOUNTED],
        "declared_rails": declared_rails(l21),
    }


def load_l21(project: Path) -> Dict[str, Any]:
    for rel in ("generated_docs/L21_POWER_INTENT.json",
                "phase1/generated_docs/L21_POWER_INTENT.json",
                "input/generated_docs/L21_POWER_INTENT.json"):
        p = project / rel
        if p.is_file():
            try:
                return json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                return {}
    return {}


def load_macro_lefs(project: Path) -> List[str]:
    out: List[str] = []
    for p in sorted((project / "input" / "pdk_local").rglob("*.lef")) \
            if (project / "input" / "pdk_local").is_dir() else []:
        try:
            out.append(p.read_text(errors="replace"))
        except OSError:
            pass
    return out
