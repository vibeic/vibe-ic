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

TWO questions, one module
------------------------
  1. `classify_pin` / `assess`         — DECLARATION: is this supply pin
     accounted for in the design's power-intent layer? (#309, above)
  2. `assess_program_supply`           — PHYSICS: for a programmable
     non-volatile memory the design intends to PROGRAM, is there a physical
     external entry (package pin / probe pad) for the programming supply?

(2) is strictly EARLIER in causality than (1): (1) blocks the symptom (a signal
net on a power terminal aborting detailed routing); (2) names the cause (this
design was never given a way to bring its programming supply in from outside).
A design can pass (1) — the rail is declared — and still fail (2), because a
declared internal rail is not an answer for a supply that is, by definition,
above core voltage and externally supplied. See the long block comment above
`PROGRAM_INTENT_TOKENS`.
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
# Any USE record, not just POWER/GROUND: `lef_pg_pins` filters this down, and
# the programming-supply layer below needs the SIGNAL pins too.
_USE_ANY_RE = re.compile(r"\bUSE\s+([A-Za-z]+)\s*;", re.IGNORECASE)
_MACRO_RE = re.compile(r"\bMACRO\s+([A-Za-z_][\w\.$]*)", re.IGNORECASE)

ACCOUNTED = {"declared_rail", "declared_gap", "rail_name_match"}


def lef_all_pins(lef_text: str) -> List[Dict[str, str]]:
    """Every LEF PIN, with the MACRO it belongs to and its USE.

    Returns ``[{"master", "pin", "use"}]`` where ``use`` is the upper-cased USE
    record, or ``"SIGNAL"`` when the pin declares none (the LEF default). Pure
    LEF grammar — no PDK, vendor or pin-name literal.

    ``lef_pg_pins`` is the POWER/GROUND filter over this; the programming-supply
    layer below needs the SIGNAL pins too, because a macro's own signal pin
    names are the design's own statement of what the macro is FOR.
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
            um = _USE_ANY_RE.search(pm.group("body") or "")
            out.append({"master": master, "pin": pm.group("name"),
                        "use": um.group(1).upper() if um else "SIGNAL"})
    return out


def lef_pg_pins(lef_text: str) -> List[Dict[str, str]]:
    """Every LEF-typed POWER/GROUND pin, with the MACRO it belongs to.

    Returns [{"master", "pin", "use"}]. Pure LEF grammar — this is the
    AUTHORITATIVE statement that a pin is a supply terminal, and it is what
    TritonRoute honours when it aborts.
    """
    return [p for p in lef_all_pins(lef_text) if p["use"] in ("POWER", "GROUND")]


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


# ===========================================================================
# PROGRAMMING-SUPPLY ENTRY — the cause one step EARLIER than the block above
# ===========================================================================
#
# THE DOMAIN CONVENTION being encoded here
# ----------------------------------------
# Any PROGRAMMABLE non-volatile memory (one-time-programmable, fuse-based,
# multiple-time-programmable, antifuse — the whole family) needs, for its
# PROGRAMMING operation, a supply that is
#
#     (a) EXTERNALLY supplied, and
#     (b) at a voltage ABOVE the digital core supply,
#
# delivered through a DEDICATED terminal — a package pin for in-field
# programming, or a wafer-probe pad for programming before the part ships.
# READING such a memory generally needs only the core supply, which is why a
# read-only integration looks complete while a programming integration is not.
#
# This is not a vendor preference, it is the physics of the bit cell. Measured
# corroboration: within a single process, two INDEPENDENT programmable-memory IP
# families — one native to the process, one third-party — both specify their
# programming supply as externally supplied, and both specify a voltage window
# above that process's core supply. Two unrelated vendors do not converge by
# accident; they converge because the cell cannot be written at core voltage.
#
# THE INFERENCE CHAIN
# -------------------
#   1. A design instantiates such a memory AND its RTL carries programming
#      control logic (a program request / address / data / busy handshake)
#      => the design INTENDS to program the part at some stage.
#   2. Programming intent REQUIRES a physical path for the programming supply:
#      a package pin, or a probe pad. There is no third option — the supply
#      cannot be manufactured on-die from the core rail.
#   3. Neither present => the design CANNOT DO THE THING IT SAYS IT DOES, and
#      nothing in the digital flow notices, because every digital check passes.
#      What actually happened: synthesis tie-cells the macro's supply pin, a
#      signal net lands on a power terminal, and detailed routing aborts with a
#      message that names none of this — five steps after the information was
#      already on the table.
#
# WHY THIS IS A SEPARATE QUESTION FROM `classify_pin` ABOVE
# ---------------------------------------------------------
# `classify_pin` asks a DECLARATION question: is this pin accounted for in the
# design's power-intent layer? A pin can be perfectly `declared_rail` there and
# STILL have no way in from outside — the power-intent layer describes internal
# rails, and an internal rail is not a valid answer for a supply that is above
# core voltage BY DEFINITION. So a design can pass the declaration question and
# fail the physics one. This asks the physics one: is there an EXTERNAL ENTRY?
#
# chip-AGNOSTIC boundary, stated precisely
# ----------------------------------------
# No macro name, no pin name, no vendor, no PDK, no SKU appears here or in the
# gate that calls it. Which pin is a supply comes from the macro's OWN LEF USE
# record; which supply is the core rail comes from the design's OWN declared
# rails; which names reach the outside comes from the design's OWN top-level
# port list and pad declarations. The ONLY literals below are generic
# English/EDA words for the ACT of programming a fuse-type memory — the same
# generic vocabulary `otp_image_layer_consistency_check` already relies on.
# They classify INTENT; they never identify a part.

# TWO vocabularies, deliberately NOT one.
#
# Naming a memory is not the same as planning to write it. A part whose macro
# is called `otp_...` and which the design only READS — programmed by its IP
# vendor before delivery — is a complete, correct design that needs no
# programming terminal at all. Folding the technology words into the intent
# words would raise a blocking finding on exactly that design. So:
#
#   NVM_TECHNOLOGY_TOKENS  identify the memory FAMILY. Context for the report;
#                          never sufficient to raise anything.
#   PROGRAM_ACTION_TOKENS  name the ACT of writing a fuse-type cell. THIS is
#                          what establishes that the design intends to program.
#
# Both are whole-token matched (see `_carries_token`), so `prog` never matches
# `progress` and `fuse` never matches `defuse`.

#: The memory family. Generic technology words — the same vocabulary
#: `otp_image_layer_consistency_check` already relies on.
NVM_TECHNOLOGY_TOKENS = frozenset({
    "otp", "mtp", "nvm", "efuse", "efuses", "antifuse", "fuse", "fuses",
})

#: The act of programming one. Deliberately EXCLUDES `write`/`we`/`wr`/`wdata`:
#: an SRAM write is not a fuse programming operation, and including them would
#: fire on every design that instantiates a RAM macro.
PROGRAM_ACTION_TOKENS = frozenset({
    "program", "programming", "programmed", "programmable",
    "prog", "pgm", "pgming",
    "burn", "burning", "burned",
    "blow", "blowing", "blown",
})

#: Everything the two vocabularies cover, for callers that want the union.
PROGRAM_INTENT_TOKENS = NVM_TECHNOLOGY_TOKENS | PROGRAM_ACTION_TOKENS

#: Token splitter for an identifier: underscores/dashes/dots/brackets, digit
#: runs, and camelCase humps all separate tokens. `progReq[3]` -> prog, Req, 3.
_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def identifier_tokens(name: str) -> List[str]:
    """Lower-cased whole tokens of an identifier. chip-AGNOSTIC."""
    return [t.lower() for t in _TOKEN_SPLIT_RE.split(name or "") if t]


def _carries_token(name: str, vocabulary: frozenset) -> Optional[str]:
    """The first vocabulary token this identifier carries as a WHOLE token."""
    for t in identifier_tokens(name):
        if t in vocabulary:
            return t
    return None


def _evidence(master: str, pin_names: List[str], net_names: List[str],
              vocabulary: frozenset) -> List[Dict[str, str]]:
    """Hits for `vocabulary` across the three DESIGN-OWNED name sources: the
    macro master name, the macro's own LEF pin names, and the RTL nets bound to
    that instance. ``[{"source", "name", "token"}]``."""
    ev: List[Dict[str, str]] = []
    for source, names in (("master", [master] if master else []),
                          ("macro_pin", list(pin_names or [])),
                          ("rtl_net", list(net_names or []))):
        for n in names:
            tok = _carries_token(n, vocabulary)
            if tok:
                ev.append({"source": source, "name": n, "token": tok})
    return ev


def program_intent_evidence(master: str,
                            pin_names: List[str],
                            net_names: List[str]) -> List[Dict[str, str]]:
    """Evidence, from the DESIGN'S OWN names, that it intends to PROGRAM this
    memory — not merely that the memory is programmABLE.

    Only `PROGRAM_ACTION_TOKENS` count. A macro NAMED for a fuse technology
    establishes what the part IS, not what this design plans to do with it: a
    memory programmed by its IP vendor before delivery is read-only here,
    carries no programming logic, needs no programming terminal, and is a
    complete correct design. Counting the technology name as intent would raise
    a blocking finding on exactly that design.

    Empty means no programming intent is visible.

    KNOWN LIMIT, stated rather than hidden: a design whose programming signals
    carry no action verb at all (say `otp_req` / `otp_busy` and nothing else)
    reads as no-intent and is recorded, not raised. Since this gate BLOCKS,
    under-firing with an explicit disclosure is the right way to be wrong.
    """
    return _evidence(master, pin_names, net_names, PROGRAM_ACTION_TOKENS)


def nvm_technology_evidence(master: str,
                            pin_names: List[str],
                            net_names: List[str]) -> List[Dict[str, str]]:
    """Evidence that this macro is a programmable non-volatile memory FAMILY.
    Context for the report; never sufficient on its own to raise anything."""
    return _evidence(master, pin_names, net_names, NVM_TECHNOLOGY_TOKENS)


def _names_match(a: str, b: str) -> bool:
    """Two names denote the same supply terminal.

    Equality after normalisation, OR one name's token sequence contains the
    other's as a contiguous run — so a LEF pin ``VPP`` is carried by a top-level
    port written ``VPP``, ``vpp``, ``vpp_pad`` or ``pad_vpp``, but NOT by an
    unrelated ``VPPX``. Both literals come from the DESIGN (a LEF pin name and a
    port/pad name); neither is written into this source.
    """
    ta, tb = identifier_tokens(a), identifier_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    n = len(short)
    return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))


def external_entry_for(pin: str, external_names: List[str]) -> Optional[str]:
    """The external terminal (top-level port / declared package pin / probe pad)
    that carries this supply pin out of the die, or None."""
    for name in external_names or []:
        if _names_match(pin, name):
            return name
    return None


def assess_program_supply(
        macros: Dict[str, List[Dict[str, str]]],
        rails: List[str],
        external_names: List[str],
        rtl_nets_by_master: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Does every macro that the design intends to PROGRAM have a physical path
    for its programming supply?

    Inputs are all DESIGN-OWNED:
      * ``macros``            ``{master: [{"pin","use"}, ...]}`` from the macros'
                              OWN LEFs, restricted by the caller to masters the
                              RTL actually instantiates.
      * ``rails``             supply rails the design independently declares.
      * ``external_names``    top-level port names + declared package pins /
                              probe pads — every way a supply can enter the die.
      * ``rtl_nets_by_master`` nets the RTL binds to each master's instances.

    Core-vs-programming discrimination, without a single hardcoded pin name:
      * rails KNOWN    — a POWER pin whose name corresponds to a declared rail is
                         the core supply (the PDN provides it internally); any
                         OTHER POWER pin must come from outside.
      * rails UNKNOWN  — at most ONE of a macro's POWER pins can be the core
                         rail, so a macro with N POWER pins needs at least N-1
                         of them carried to the outside. Weaker, never wrong.

    Verdict per macro:
      ``ok``                  nothing to require, or every required supply has an
                              external entry.
      ``program_supply_absent`` programming INTENT is visible and a required
                              external supply has NO package pin and NO probe
                              pad — the design cannot perform its own programming
                              step. THE finding.
      ``no_program_intent``   a non-core supply has no external entry, but no
                              programming logic is visible either: consistent
                              with a part programmed before delivery. Recorded,
                              not raised — silence about it would be dishonest,
                              and raising it would be a false alarm. This is
                              where a read-only `otp_*` macro lands, which is
                              why the technology vocabulary is kept SEPARATE
                              from the action vocabulary.
    """
    rtl_nets_by_master = rtl_nets_by_master or {}
    results: List[Dict[str, Any]] = []
    for master in sorted(macros):
        pins = macros[master] or []
        power = [p["pin"] for p in pins if p.get("use") == "POWER"]
        if not power:
            continue
        # Which POWER pin is the CORE supply, named by nothing in this file:
        #
        #  * If at least one of the macro's POWER pins corresponds to a rail the
        #    design declares, the two naming conventions line up — that pin is
        #    the core supply and every OTHER POWER pin is an extra one the
        #    internal PDN does not provide. Exact, so `allowance` is 0.
        #  * If NONE of them corresponds (the design and the macro vendor simply
        #    name the same rail differently, which is routine), we cannot say
        #    WHICH pin is the core one — but we can still say that AT MOST ONE
        #    of them is, because a die has one core rail. Same rule as when the
        #    design declares no rails at all. Weaker, never wrong.
        matched = [p for p in power if _rail_token_match(p, rails or [])]
        if rails and matched:
            need = [p for p in power if p not in matched]
            allowance = 0
        else:
            need = list(power)
            allowance = 1
        if not need:
            continue
        carried, missing = [], []
        for p in need:
            entry = external_entry_for(p, external_names)
            (carried if entry else missing).append(
                {"pin": p, "external_entry": entry} if entry else {"pin": p})
        # `allowance` lets the rails-unknown branch attribute exactly one
        # uncarried POWER pin to the core rail it cannot name.
        shortfall = len(missing) - allowance
        entry = {"master": master,
                 "power_pins": power,
                 "requires_external": list(need),
                 "carried": carried,
                 "uncarried": [p["pin"] for p in missing],
                 "rails_known": bool(rails),
                 "core_rail_identified": matched,
                 "core_rail_allowance": allowance}
        if shortfall <= 0:
            entry["status"] = "ok"
            results.append(entry)
            continue
        pin_names = [p["pin"] for p in pins]
        nets = rtl_nets_by_master.get(master) or []
        ev = program_intent_evidence(master, pin_names, nets)
        entry["program_intent"] = ev
        entry["nvm_technology"] = nvm_technology_evidence(
            master, pin_names, nets)
        entry["status"] = "program_supply_absent" if ev else "no_program_intent"
        results.append(entry)
    return {
        "macros": results,
        "findings": [r for r in results
                     if r["status"] == "program_supply_absent"],
        "notes": [r for r in results if r["status"] == "no_program_intent"],
        "declared_rails": list(rails or []),
        "external_names": list(external_names or []),
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
