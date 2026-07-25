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
from typing import Any, Dict, List, Optional, Tuple

# `PIN <name>` ... `USE POWER|GROUND` ... `END <name>` — LEF is whitespace and
# newline tolerant, so scan the pin block rather than assuming a line layout.
_PIN_BLOCK_RE = re.compile(
    r"\bPIN\s+(?P<name>[A-Za-z_][\w\[\]\.$<>]*)\b(?P<body>.*?)\bEND\s+(?P=name)\b",
    re.S | re.IGNORECASE)
_USE_RE = re.compile(r"\bUSE\s+(POWER|GROUND)\s*;", re.IGNORECASE)
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


# The DEF's SPECIALNETS section: the rails the PDN ACTUALLY built.
_SPECIALNETS_RE = re.compile(r"^\s*SPECIALNETS\b", re.M)
_END_SPECIALNETS_RE = re.compile(r"^\s*END\s+SPECIALNETS\b", re.M)
_SPECIALNET_NAME_RE = re.compile(r"^\s*-\s+(\S+)", re.M)

_DEF_CANDIDATES = (
    "phase3/stage3/pnr/routed.def",
    "phase3/stage3/pnr/post_cts.def",
    "phase3/stage3/pnr/floorplan.def",
)


def measured_rails(project: Path) -> List[str]:
    """Rails the PDN ACTUALLY BUILT, read from the DEF's SPECIALNETS section.

    #348: the declared escape hatch had no producer. `declared_rails` reads
    `L21.fields.power_rails` / `power_domains[]`, and across the real IC designs
    in this repo those structured fields are empty — measured 3 of 30 usable. So
    every macro PG pin fell to `undeclared` and a design had NO legitimate way
    to clear the gate: the escape hatch existed and the door was locked. The
    rail names DO exist in L21, but in prose fields (`power_domains_summary`,
    `power_up_sequence`) rather than the structured ones the consumer reads —
    the exact producer/consumer split that let the macro supply requirement
    slip through in the first place (#309), reproduced inside its own fix.

    Reading the DEF instead is strictly BETTER than trusting either field:
      * it is a PHYSICAL FACT, not a claim — a rail is here because the PDN
        built it, and a design cannot manufacture coverage by naming a rail
        that does not exist (the `rail_undeclared` anti-cheat is preserved by
        construction rather than by a name check);
      * it is exactly what the issue asks the producer to eventually write —
        "rails the design ACTUALLY has (the PDN really built, whose macro pins
        are really global-connected)".

    Phase 1 has no DEF yet, so it keeps warning on the declared fields alone;
    Phase 3 — the phase that BLOCKS — gets the measured evidence. That split
    matches what each phase can actually know.

    Empty list when no DEF exists or none has a SPECIALNETS section.
    """
    for rel in _DEF_CANDIDATES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        m = _SPECIALNETS_RE.search(txt)
        if not m:
            continue
        end = _END_SPECIALNETS_RE.search(txt[m.start():])
        sec = txt[m.start():m.start() + end.start()] if end else txt[m.start():]
        names = [n for n in _SPECIALNET_NAME_RE.findall(sec) if n]
        if names:
            return sorted(set(names))
    return []


def rail_name_tokens(rails: List[str]) -> List[str]:
    """Expand prose rail declarations into their identifier tokens, using the
    SAME prose-separator split as `_rail_token_match` (whitespace, slash,
    comma, brackets — NEVER the underscore). `"VDD / core supply (1.8 V)"`
    yields `VDD`, `core`, `supply`, `1.8`, `V` — needed wherever a rail must
    be compared against a NETLIST NET NAME (a bare token), e.g. the tie
    whitelist in the pre-route gate (#329)."""
    toks: List[str] = []
    seen: set = set()
    for r in rails or []:
        for tok in re.split(r"[\s/,;()\[\]]+", str(r)):
            if tok and tok not in seen:
                seen.add(tok)
                toks.append(tok)
    return toks


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


def classify_pin(master: str, pin: str, l21: Dict[str, Any],
                 extra_rails: Optional[List[str]] = None) -> Dict[str, Any]:
    """Classify ONE macro PG pin against the design's power-intent layer.

    `extra_rails` are rails established by EVIDENCE rather than declaration —
    in practice the PDN the DEF actually built (#348). They count as declared,
    because a rail the PDN really built is a stronger statement than a rail a
    document claims, and it cannot be fabricated.
    """
    f = (l21 or {}).get("fields") or {}
    rails = declared_rails(l21) + list(extra_rails or [])
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


def declared_binding_map(l21: Dict[str, Any],
                         rails: "Optional[List[str]]" = None,
                         ) -> Dict[Tuple[str, str], str]:
    """``(master, pin) -> rail`` for every EXPLICIT L21 mapping whose rail is
    independently established (declared in L21, measured from the DEF, or a
    design supply net the caller passes in `rails`).

    #329 delta 1 (harvested via #349): the pre-route GATE accepted a declared
    mapping as accounted-for, but the PHYSICAL binding emitter only bound
    name-equality pins — so a pin whose name differs from its rail passed the
    gate and still arrived at routing constant-tied (the exact DRT-0307 the
    gate exists to prevent). This map feeds the emitter so what the gate
    accepts is exactly what gets bound.

    ANTI-CHEAT preserved: a mapping pointing at a rail nobody established
    (`rail_undeclared` in classify_pin) is EXCLUDED — honoring it would let a
    document fabricate a rail. Acknowledged gaps carry no rail and are skipped.
    """
    f = (l21 or {}).get("fields") or {}
    rs = {str(r) for r in (rails or [])}
    out: Dict[Tuple[str, str], str] = {}
    for m in (f.get("hard_macro_supplies") or []):
        if not isinstance(m, dict) or m.get("integration_gap") is True:
            continue
        master = str(m.get("master", "")).strip()
        pin = str(m.get("pin", "")).strip()
        rail = str(m.get("rail", "")).strip()
        if master and pin and rail and rail in rs:
            out[(master, pin)] = rail
    return out


def assess(lef_texts: List[str], l21: Dict[str, Any],
           extra_rails: Optional[List[str]] = None) -> Dict[str, Any]:
    """Classify every LEF-typed PG pin across the given macro LEFs."""
    pins: List[Dict[str, Any]] = []
    for txt in lef_texts or []:
        for p in lef_pg_pins(txt):
            pins.append({**classify_pin(p["master"], p["pin"], l21, extra_rails),
                         "use": p["use"]})
    return {
        "pins": pins,
        "accounted": [p for p in pins if p["status"] in ACCOUNTED],
        "gaps": [p for p in pins if p["status"] not in ACCOUNTED],
        "declared_rails": declared_rails(l21),
        "measured_rails": sorted(set(extra_rails or [])),
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

#: Generic vocabulary for "this is a programmable non-volatile memory" / "this
#: signal drives a programming operation". Whole-token matched (see
#: `_carries_token`), so `prog` never matches `progress` and `fuse` never
#: matches `defuse`. Deliberately EXCLUDES `write`/`we`/`wr`: an SRAM write is
#: not a fuse programming operation, and including them would fire on every
#: design with a RAM macro.
PROGRAM_INTENT_TOKENS = frozenset({
    "program", "programming", "programmed", "programmable",
    "prog", "pgm", "pgming",
    "burn", "burning", "burned",
    "blow", "blowing", "blown",
    "fuse", "fuses", "efuse", "efuses", "antifuse",
    "otp", "mtp", "nvm",
})

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


def program_intent_evidence(master: str,
                            pin_names: List[str],
                            net_names: List[str]) -> List[Dict[str, str]]:
    """Evidence, from the DESIGN'S OWN names, that this macro is a programmable
    non-volatile memory the design intends to PROGRAM (not merely read).

    Three independent sources, each a name the design itself authored or
    accepted: the macro master name, the macro's own pin names (from its LEF),
    and the RTL nets bound to that instance. Returns one entry per hit:
    ``[{"source", "name", "token"}]`` — empty means no programming intent is
    visible, which is a legitimate design (a part programmed by the IP vendor
    before delivery carries no programming logic at all).
    """
    ev: List[Dict[str, str]] = []
    for source, names in (("master", [master] if master else []),
                          ("macro_pin", list(pin_names or [])),
                          ("rtl_net", list(net_names or []))):
        for n in names:
            tok = _carries_token(n, PROGRAM_INTENT_TOKENS)
            if tok:
                ev.append({"source": source, "name": n, "token": tok})
    return ev


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
                              and raising it would be a false alarm.
    """
    rtl_nets_by_master = rtl_nets_by_master or {}
    results: List[Dict[str, Any]] = []
    for master in sorted(macros):
        pins = macros[master] or []
        power = [p["pin"] for p in pins if p.get("use") == "POWER"]
        if not power:
            continue
        if rails:
            need = [p for p in power if not _rail_token_match(p, rails)]
            allowance = 0
        else:
            need = list(power)
            allowance = 1 if len(power) > 1 else len(power)
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
                 "requires_external": [p["pin"] for p in need],
                 "carried": carried,
                 "uncarried": [p["pin"] for p in missing],
                 "rails_known": bool(rails),
                 "core_rail_allowance": allowance}
        if shortfall <= 0:
            entry["status"] = "ok"
            results.append(entry)
            continue
        ev = program_intent_evidence(
            master, [p["pin"] for p in pins],
            rtl_nets_by_master.get(master) or [])
        entry["program_intent"] = ev
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
