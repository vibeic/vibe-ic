#!/usr/bin/env python3
"""hardmacro_supply_intent.py — chip-AGNOSTIC hard-macro supply-pin intent.

A hard macro types its supply pins USE POWER / USE GROUND in its OWN LEF. The
design's power intent (L21_POWER_INTENT) must ACCOUNT for every such pin —
either BIND it to a rail the design declares, or mark it an acknowledged
INTEGRATION GAP ("this design provides no such supply"). A pin accounted for by
NEITHER is an *undeclared supply*.

Why this module exists in ONE place: the requirement is verified in Phase 1
(ip_integration_check surfaces every undeclared macro supply pin as a named
review finding so it flows into L21) and ENFORCED in Phase 3
(phase3_one_shot_runner binds the declared ones before routing and BLOCKS the
one case that would otherwise land a signal net on a POWER/GROUND terminal and
abort TritonRoute mid-route). Both phases must agree byte-for-byte on *what
"accounted for" means*, so the decision lives here and is imported by both.

chip-AGNOSTIC by construction: every input is the macro's own LEF USE records and
the design's own declared supplies / declared mapping. There is NO PDK, design,
vendor, or pin-name literal anywhere in this file. A design with no hard-macro
POWER/GROUND pins produces an empty report (the flow is byte-identical).

DESIGN-DECLARED MAPPING (the "the design says so" mechanism):
  L21_POWER_INTENT `fields.hard_macro_supplies` is a list the DESIGN authors:
      {"master": <macro>, "pin": <pin>, "rail": <declared_supply_net>}
      {"master": <macro>, "pin": <pin>, "integration_gap": true, "reason": ...}
  The rail form binds a macro pin to a rail EVEN WHEN the names differ (so the
  flow follows the design, it does not guess). The integration_gap form is the
  design explicitly acknowledging it provides no such supply. A rail that is NOT
  itself a declared supply is a dangling mapping — surfaced, never silently
  honored (anti-cheat: a design cannot fabricate coverage by naming a phantom
  rail).
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Set, Tuple


def parse_macro_supply_pins(
        lef_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Parse a (macro) LEF and return ``{MACRO_NAME: [(pin_name, USE), ...]}``
    for every pin the LEF types ``USE POWER`` or ``USE GROUND``. USE is
    upper-cased and normalised to ``POWER``/``GROUND``. Pure LEF grammar
    (MACRO / PIN / USE walk); no literal, so any vendor's hard macro parses.
    Masters with no PG pin are omitted."""
    result: Dict[str, List[Tuple[str, str]]] = {}
    cur_macro = cur_pin = cur_use = None
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        m = re.match(r"MACRO\s+(\S+)", s)
        if m:
            cur_macro = m.group(1)
            result.setdefault(cur_macro, [])
            cur_pin = cur_use = None
            continue
        if (cur_macro and s.startswith("END ")
                and s.split()[1:2] == [cur_macro]):
            cur_macro = cur_pin = cur_use = None
            continue
        if cur_macro is None:
            continue
        m = re.match(r"PIN\s+(\S+)", s)
        if m:
            cur_pin = m.group(1)
            cur_use = None
            continue
        if (cur_pin and s.startswith("END ")
                and s.split()[1:2] == [cur_pin]):
            if cur_use in ("POWER", "GROUND"):
                result[cur_macro].append((cur_pin, cur_use))
            cur_pin = cur_use = None
            continue
        if cur_pin is None:
            continue
        m = re.match(r"USE\s+(\S+)", s)
        if m:
            cur_use = m.group(1).rstrip(";").upper()
    return {k: v for k, v in result.items() if v}


def _l21_fields(l21_obj) -> dict:
    """L21 docs carry their payload under ``fields``; some stubs are flat.
    Return the field container either way (never raises)."""
    if not isinstance(l21_obj, dict):
        return {}
    f = l21_obj.get("fields")
    return f if isinstance(f, dict) else l21_obj


def parse_declared_supply_map(l21_obj) -> Dict[Tuple[str, str], Dict]:
    """Return the DESIGN-DECLARED macro supply map from an L21 object:

        {(master, pin): {"rail": <str>}}            explicit rail binding
        {(master, pin): {"gap": True, "reason": s}} acknowledged integration gap

    Read from ``fields.hard_macro_supplies`` (a list the design authors).
    Malformed / partial entries are skipped; absent → ``{}``."""
    out: Dict[Tuple[str, str], Dict] = {}
    entries = _l21_fields(l21_obj).get("hard_macro_supplies")
    if not isinstance(entries, list):
        return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        master = e.get("master")
        pin = e.get("pin")
        if not master or not pin:
            continue
        key = (str(master), str(pin))
        if e.get("integration_gap") is True:
            out[key] = {"gap": True, "reason": str(e.get("reason", ""))}
        elif e.get("rail"):
            out[key] = {"rail": str(e.get("rail"))}
    return out


def declared_supply_rails(l21_obj) -> Set[str]:
    """Return the set of supply-net names the design DECLARES in L21 —
    ``power_domains[].supply``. A rail merely named inside
    ``hard_macro_supplies`` is deliberately NOT counted here: only a rail the
    design independently declares as a supply can anchor a binding (that is the
    discriminator that keeps a real rail apart from a fabricated one)."""
    rails: Set[str] = set()
    doms = _l21_fields(l21_obj).get("power_domains")
    if isinstance(doms, list):
        for d in doms:
            if isinstance(d, dict) and d.get("supply"):
                rails.add(str(d["supply"]))
    return rails


def classify_macro_supply_pin(
        master: str, pin: str, use: str,
        declared_rails: Set[str],
        declared_map: Dict[Tuple[str, str], Dict]) -> str:
    """Classify one macro POWER/GROUND pin against the design's declared rails
    and declared mapping. Returns exactly one of:

      ``declared_rail``   — map binds (master,pin) to a rail that IS declared.
      ``declared_gap``    — map marks (master,pin) an acknowledged gap.
      ``rail_name_match`` — the pin name is itself a declared rail (implicit
                            bind — the ordinary VDD/VSS-style case).
      ``rail_undeclared`` — map binds to a rail the design does NOT declare
                            (dangling mapping; not coverage).
      ``undeclared``      — accounted for by none of the above.

    ``use`` is accepted for symmetry / future power-vs-ground rail splitting;
    matching is name-equality against ``declared_rails`` (which the caller
    supplies for the relevant use)."""
    ent = declared_map.get((str(master), str(pin)))
    if ent:
        if ent.get("gap"):
            return "declared_gap"
        rail = ent.get("rail")
        if rail:
            return ("declared_rail" if rail in declared_rails
                    else "rail_undeclared")
    if pin in declared_rails:
        return "rail_name_match"
    return "undeclared"


# Verdicts that mean "the design has ACCOUNTED for this pin".
_ACCOUNTED = frozenset({"declared_rail", "declared_gap", "rail_name_match"})


def coverage_findings(
        macro_lef_texts: Sequence[str],
        declared_rails: Set[str],
        declared_map: Dict[Tuple[str, str], Dict] = None) -> dict:
    """Cross every hard-macro POWER/GROUND pin (from the macros' own LEFs)
    against the design's declared rails + mapping, and return a report:

        {
          "total_pins":     int,
          "covered_count":  int,
          "undeclared":     [{master,pin,use}, ...],   # named findings
          "rail_undeclared":[{master,pin,use,rail}, ...],  # dangling mappings
          "declared_gaps":  [{master,pin,use,reason}, ...],
        }

    Deduplicated by (master, pin) across LEFs. A design with no PG pins yields
    an all-empty report (vacuous)."""
    declared_map = declared_map or {}
    pins_by_master: Dict[str, Dict[str, str]] = {}
    for txt in (macro_lef_texts or []):
        for mst, pins in parse_macro_supply_pins(txt or "").items():
            d = pins_by_master.setdefault(mst, {})
            for pin, use in pins:
                d.setdefault(pin, use)
    undeclared: List[Dict[str, str]] = []
    rail_undeclared: List[Dict[str, str]] = []
    declared_gaps: List[Dict[str, str]] = []
    total = covered = 0
    for master in sorted(pins_by_master):
        for pin in sorted(pins_by_master[master]):
            use = pins_by_master[master][pin]
            total += 1
            verdict = classify_macro_supply_pin(
                master, pin, use, declared_rails, declared_map)
            if verdict in _ACCOUNTED:
                covered += 1
            if verdict == "undeclared":
                undeclared.append(
                    {"master": master, "pin": pin, "use": use})
            elif verdict == "rail_undeclared":
                ent = declared_map.get((master, pin), {})
                rail_undeclared.append(
                    {"master": master, "pin": pin, "use": use,
                     "rail": str(ent.get("rail", ""))})
            elif verdict == "declared_gap":
                ent = declared_map.get((master, pin), {})
                declared_gaps.append(
                    {"master": master, "pin": pin, "use": use,
                     "reason": str(ent.get("reason", ""))})
    return {
        "total_pins": total,
        "covered_count": covered,
        "undeclared": undeclared,
        "rail_undeclared": rail_undeclared,
        "declared_gaps": declared_gaps,
    }
