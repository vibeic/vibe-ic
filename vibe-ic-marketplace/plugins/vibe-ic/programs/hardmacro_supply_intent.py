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

import _path_layout as _pl
from typing import Any, Dict, List, Optional, Tuple

# `PIN <name>` ... `USE <type>` ... `END <name>` — LEF is whitespace and
# newline tolerant, so scan the pin block rather than assuming a line layout.
_PIN_BLOCK_RE = re.compile(
    r"\bPIN\s+(?P<name>[A-Za-z_][\w\[\]\.$<>]*)\b(?P<body>.*?)\bEND\s+(?P=name)\b",
    re.S | re.IGNORECASE)
#: Any `USE` record, not only the supply ones. The difference between "this pin
#: is typed SIGNAL" and "this pin carries no typing at all" is a fact about the
#: ABSTRACT, and it is invisible to a scan that can only see POWER/GROUND.
_ANY_USE_RE = re.compile(r"\bUSE\s+([A-Za-z]+)\s*;", re.IGNORECASE)
_MACRO_RE = re.compile(r"\bMACRO\s+([A-Za-z_][\w\.$]*)", re.IGNORECASE)

ACCOUNTED = {"declared_rail", "declared_gap", "rail_name_match"}


def lef_all_pins(lef_text: str) -> List[Dict[str, Any]]:
    """EVERY pin a LEF declares — typed or not — with the MACRO it belongs to.

    Returns ``[{"master", "pin", "use", "uses"}]`` where ``uses`` is every
    ``USE`` record found in the pin body (upper-cased, in file order) and
    ``use`` is the first of them, or ``""`` when the abstract types the pin
    with none.

    WHY THIS IS THE PRIMITIVE AND `lef_pg_pins` IS THE FILTER (vibe-ic#774)
    ----------------------------------------------------------------------
    A reader that can only see POWER/GROUND-typed pins cannot tell these two
    apart:

        (a) a hard macro whose abstract types its pins and none is a supply pin
        (b) a hard macro whose abstract types NOTHING

    `magic`'s ``lef write`` emits neither ``DIRECTION`` nor ``USE`` on any PIN,
    so (b) is what an HONESTLY regenerated abstract looks like — and every
    consumer keyed on ``USE POWER``/``USE GROUND`` reads it as (a) and goes
    quiet. The two facts have to be separable at the parser, or every consumer
    re-derives the same blind spot. Pure LEF grammar; no PDK literal.
    """
    out: List[Dict[str, Any]] = []
    if not lef_text:
        return out
    # Segment by MACRO so each pin is attributed to its own master.
    bounds = [(m.start(), m.group(1)) for m in _MACRO_RE.finditer(lef_text)]
    if not bounds:
        bounds = [(0, "")]
    for i, (start, master) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(lef_text)
        for pm in _PIN_BLOCK_RE.finditer(lef_text[start:end]):
            uses = [u.upper() for u in _ANY_USE_RE.findall(pm.group("body") or "")]
            out.append({"master": master, "pin": pm.group("name"),
                        "use": uses[0] if uses else "", "uses": uses})
    return out


def lef_pg_pins(lef_text: str) -> List[Dict[str, str]]:
    """Every LEF-typed POWER/GROUND pin, with the MACRO it belongs to.

    Returns [{"master", "pin", "use"}]. Pure LEF grammar — this is the
    AUTHORITATIVE statement that a pin is a supply terminal, and it is what
    TritonRoute honours when it aborts.

    A FILTER over `lef_all_pins`, not a second walk: the two answers come from
    one parse, so "which pins exist" and "which pins are typed supply" can never
    disagree about the same file.
    """
    out: List[Dict[str, str]] = []
    for rec in lef_all_pins(lef_text):
        pg = next((u for u in rec["uses"] if u in ("POWER", "GROUND")), None)
        if pg:
            out.append({"master": rec["master"], "pin": rec["pin"], "use": pg})
    return out


# The independence the docstring above calls "the anti-cheat anchor" was stated
# and never enforced. A synthesiser writes rails INTO this layer, deriving them
# from the macro PG pins, and those entries were then returned as independent
# declarations — so every pin matched a rail BY CONSTRUCTION and the
# "N pins with no matching rail" count could not be non-zero.
#
# Measured on a real run: the flow reported `0 POWER/GROUND pin(s) have NO
# matching supply rail` while OpenROAD's own power-grid analysis on the same DEF
# reported `Unconnected instance <macro>/VDD` and `PSM-0069 Check connectivity
# failed`. Both statements were about the same instance. The entries carried
#     "derived_by":   "l21_macro_supply_rail_synth"
#     "derived_from": {"macro_lef_pin_use": "POWER", "declared_by_macros": [...]}
# which says plainly where they came from; nothing read it.
#
# Keyed on the PROVENANCE the synthesiser records about itself rather than on a
# list of synthesiser names, so a new producer is covered the day it is written.
_SELF_DERIVED_KEYS = ("macro_lef_pin_use", "declared_by_macros", "from_macro_pins")


def _derived_from_the_macros_under_test(entry: Dict[str, Any]) -> bool:
    """Was this rail synthesised FROM the macro pins it would be used to check?

    A declaration derived from its own subject cannot falsify anything about it.
    Absence of provenance is NOT treated as self-derived: a hand-written rail
    carries no `derived_from`, and refusing those would lock the door this
    escape hatch exists to open (#348).
    """
    src = entry.get("derived_from")
    if isinstance(src, dict) and any(k in src for k in _SELF_DERIVED_KEYS):
        return True
    by = entry.get("derived_by")
    return isinstance(by, str) and "macro" in by.lower() and "rail" in by.lower()


def rail_producers_that_did_not_run(project) -> List[str]:
    """Which L21 rail producers this run dispatched and FAILED. vibe-ic#691.

    Reads `reports/phase1/l21_rail_producers.json`, written unconditionally by
    the Phase-1 doc runner. Returns [] when every producer ran, and [] ALSO when
    the record is absent — an older run has no record, and inventing a failure
    from its absence would flag every project that predates the record.

    That asymmetry is deliberate and is the opposite of the usual rule here: an
    absent record cannot prove a producer ran, but neither can it prove one
    failed, and the cost of the two mistakes is not equal. This is used to EXPLAIN
    a finding that already exists on its own evidence, never to create one."""
    try:
        f = _pl.report_path(Path(project), "phase1/l21_rail_producers.json")
        if not f.is_file():
            return []
        d = json.loads(f.read_text(errors="replace"))
    except (OSError, ValueError, TypeError):
        return []
    return [r.get("producer", "?") for r in (d.get("producers") or [])
            if r.get("outcome") != "ran"]


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
            if _derived_from_the_macros_under_test(r):
                continue
            v = r.get("rail") or r.get("name")
        else:
            v = r
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
    for d in (f.get("power_domains") or []):
        if isinstance(d, dict):
            if _derived_from_the_macros_under_test(d):
                continue
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
    return specialnets_split(project)[0]


# A SPECIALNETS entry may be a connect-all-by-name and nothing else:
#
#     - <RAIL> ( * <RAIL> ) + USE POWER ;
#
# one line, no stripe, no via, no followpin. Measured on a real routed DEF beside
# two real rails:
#
#     VSS  33,141 lines   VDD  32,642 lines   third rail  1 line
#
# The docstring above argues the DEF is better than a claim because "a rail is
# here because the PDN built it". That argument is right and this entry does not
# satisfy it — the PDN did not build anything, the design merely NAMED a net. So
# the name alone was accepted as physical evidence, and a macro pin bound to that
# rail counted as covered while carrying no current at all.
#
# The tool downstream says so in the same run, vacuously and truthfully:
#     [INFO PSM-0040] All shapes on net <RAIL> are connected.
# There are no shapes.
_CONDUCTOR_RE = re.compile(r"\+\s*(?:ROUTED|FIXED|COVER|SHAPE)\b")


def _specialnets_with_and_without_conductor(section: str):
    """(rails the PDN actually built, rails that are a name and nothing else).

    Split on entry starts rather than on `;`, because a routed entry contains
    many `;`-free continuation lines and one terminator; the entry boundary is
    the reliable delimiter.
    """
    built, bare = set(), set()
    for ent in re.split(r"\n(?=\s*-\s+\S)", section)[1:]:
        m = re.match(r"\s*-\s+(\S+)", ent)
        if not m:
            continue
        body = ent[:ent.find(";") + 1] if ";" in ent else ent
        (built if _CONDUCTOR_RE.search(body) else bare).add(m.group(1))
    return built, bare


def specialnets_split(project: Path) -> Tuple[List[str], List[str]]:
    """``(rails the PDN built, rails that are a name and nothing else)``.

    ONE scan of the first `_DEF_CANDIDATES` entry that has a non-empty
    SPECIALNETS section. `measured_rails` and `rails_named_but_not_built` are
    the two halves of this result and were byte-for-byte the same scan; a
    caller that wants both used to read and re-parse the DEF twice, and a DEF
    here runs to tens of thousands of lines.
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
        built, bare = _specialnets_with_and_without_conductor(sec)
        if built or bare:
            return sorted(built), sorted(bare)
    return [], []


def rails_named_but_not_built(project: Path) -> List[str]:
    """Rails that appear in SPECIALNETS carrying no conductor.

    The COMPLEMENT of `measured_rails` — the other half of one
    `specialnets_split`. It is the reason a macro pin can be reported as a gap
    while its rail is plainly visible in the DEF: `measured_rails` drops the
    bare rail, and the drop is what turns the pin from accounted to gap.

    WHO CONSUMES IT
    ---------------
    `_macro_supply_preroute_decision` (phase3_one_shot_runner) carries this
    into the same dict it blocks with, and the PnR FAIL row puts it in
    `extras` — serialized to `reports/phase3/phase3_one_shot.json`. So the
    drop is stated on the verdict it explains, in a channel that outlives the
    terminal, and ONLY when there is something to state (see below).

    WHEN IT IS EMPTY, AND WHY THAT IS NOT A CLEAN BILL OF HEALTH
    -----------------------------------------------------------
    MEASURED: every DEF in `_DEF_CANDIDATES` is written by `step_pnr`'s OWN
    OpenROAD TCL — `floorplan.def`, `post_cts.def`, `routed.def` — and that
    TCL runs AFTER the pre-route gate calls this. On a FIRST run
    `phase3/stage3/pnr/` is therefore empty at the gate and this returns `[]`
    having examined nothing. `[]` here means "no bare rail was SEEN", never
    "no bare rail EXISTS", which is why the runner reports the key only when
    it is non-empty rather than publishing an empty list that would read as a
    clean examination.

    `floorplan.def` can never contribute either: it is written BEFORE the PDN
    block, so no supply rail exists in it yet — and an absent or empty
    SPECIALNETS section falls through to the next candidate either way.

    RELATIONSHIP TO `pg_rail_geometry_check` — COMPLEMENTS, NOT DUPLICATES
    ---------------------------------------------------------------------
    The same fact is JUDGED, with a governed waiver channel, by
    `pg_rail_geometry_check` at flow step 31. That gate reads `routed.def`
    ONLY. MEASURED, one bare rail, three DEF placements:

        DEF present     this function   pg_rail_geometry_check
        routed.def      ['<RAIL>']      FAIL, names the rail
        post_cts.def    ['<RAIL>']      SKIP ("no routed.def")
        none            []              SKIP

    So where `routed.def` exists the fact already has a channel and this adds
    nothing; the band where this is both non-empty and otherwise UNREPORTED is
    a re-run whose previous PnR wrote `post_cts.def` and died before
    `routed.def`. Narrow, and deliberately not widened into a second report of
    a finding that already has one.
    """
    return specialnets_split(project)[1]


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
           extra_rails: Optional[List[str]] = None,
           project=None) -> Dict[str, Any]:
    """Classify every LEF-typed PG pin across the given macro LEFs.

    `project` is OPTIONAL and changes no verdict: it lets the result carry WHY
    a rail is undeclared when the reason is that a producer never ran
    (vibe-ic#691). Omitting it leaves the output byte-identical to before."""
    pins: List[Dict[str, Any]] = []
    for txt in lef_texts or []:
        for p in lef_pg_pins(txt):
            pins.append({**classify_pin(p["master"], p["pin"], l21, extra_rails),
                         "use": p["use"]})
    out = {
        "pins": pins,
        "accounted": [p for p in pins if p["status"] in ACCOUNTED],
        "gaps": [p for p in pins if p["status"] not in ACCOUNTED],
        "declared_rails": declared_rails(l21),
        "measured_rails": sorted(set(extra_rails or [])),
    }
    # #691 — a rail can be undeclared because the design does not declare it, or
    # because the INDEPENDENT declaration step never ran. Those are the same
    # finding and different work. MEASURED on a real Phase-3 run: 0 power_rails,
    # 3 power_domains all stamped `derived_by: l21_macro_supply_rail_synth`, and
    # the doc synthesiser had left no artefact anywhere. The visible symptom was
    # one rail `rail_undeclared` — `measured_rails()` re-derives from DEF
    # geometry and rescues the two rails that HAVE geometry, and the third has
    # none precisely because it was never declared.
    #
    # ANNOTATION ONLY. The finding stands on its own evidence; this says which
    # of the two it is, so chasing it leads to the producer instead of the rail.
    if project is not None:
        missing = rail_producers_that_did_not_run(project)
        if missing and out["gaps"]:
            out["undeclared_cause"] = {
                "producers_that_did_not_run": missing,
                "note": (f"{len(out['gaps'])} pin(s) are unaccounted AND "
                         f"{len(missing)} L21 rail producer(s) did not run "
                         f"({', '.join(missing)}). An undeclared rail here is "
                         f"as likely to be a missing PRODUCER as a missing "
                         f"declaration — fix the producer first."),
            }
    return out


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
