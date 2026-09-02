#!/usr/bin/env python3
"""l21_macro_supply_rail_declared_check.py — L21 SEMANTIC completeness gate.

ENFORCEMENT: advisory

WHY THIS GATE EXISTS (the measured defect it is distilled from)
---------------------------------------------------------------
The pre-existing global check `phase1_doc_input_completeness_check` models
completeness as "does this vendor token appear as a substring in ANY L doc JSON
serialization". A hard macro's supply pin name appeared in L1_DATASHEET (7x) and
L2_FRS (8x), so the check reported CAPTURED — while L21_POWER_INTENT, the layer
the BACKEND consumes, contained it 0 times. Consequence chain, all measured:

    L21 declares no rail for the macro's supply pin
      -> the PDN carries no such rail
      -> synthesis ties the macro's POWER-typed terminal off with a TIEHI cell
      -> a SIGNAL net lands on a POWER-typed terminal
      -> TritonRoute aborts the WHOLE detailed route (not just that net)
      -> 3278 signal nets, 0 routed, LVS unreachable

...discovered FIVE steps downstream behind an opaque router error. So the
principle this gate embodies is:

    A layer is complete when the requirement is present IN THE LAYER THAT
    CONSUMES IT, in an actionable form — not when a token appears somewhere.

THE CONSUMER CONTRACT THIS GATE ASSERTS
---------------------------------------
`phase3_one_shot_runner._macro_supply_gc_plan(macro_lef_texts, power_nets,
ground_nets)` decides, for EVERY hard-macro pin the macro's own LEF types
`USE POWER` / `USE GROUND`, whether it binds to a supply rail. The match is
NAME-EQUALITY against the declared nets OF THE SAME USE. A pin that matches
nothing becomes `HARDMACRO_SUPPLY_UNCONNECTED` and is (honestly) left floating —
which is the exact input state of the failure chain above.

So the load-bearing clause is:

    every supply/ground pin that ANY instantiated hard macro types USE POWER /
    USE GROUND in that design's OWN macro LEF must appear as a declared rail of
    the SAME use in L21.power_domains[].

Everything this gate needs is DERIVED from the design's own machine-readable
inputs — the macro's own LEF `MACRO/PIN/USE` records, the macro's own Liberty
`pg_pin` groups, and the design's own RTL/netlist instantiations. There is no
PDK name, design name, vendor part number or hardcoded pin/signal literal
anywhere in this file. A design that stages no macro LEF SKIPs (rc=2) and is
byte-identically unaffected.

AN ABSTRACT THAT TYPES NOTHING IS NOT AN ABSTRACT WITH NOTHING TO SAY (#774)
---------------------------------------------------------------------------
The first version keyed the WHOLE gate on `USE POWER` / `USE GROUND` and SKIPped
when it found none — reading absence of evidence as non-applicability. Measured
twice in one session: against a HAND-AUTHORED `<macro>.lef` the gate FAILed;
regenerating that same macro HONESTLY — `magic`'s `lef write` from the routed,
LVS-clean layout, replacing an abstract that had claimed invented pin rectangles
— flipped it to SKIP, because **`lef write` emits neither `DIRECTION` nor `USE`
on any PIN**. The run got more honest and the gate got quieter, and the SKIP it
printed was byte-identical to the one a design with no macro at all gets.

That is fatal for a gate, because the tool-written abstract is the COMMON case:
any producer switching from a hand-written abstract to a tool-written one
silently loses the check, and the loss is indistinguishable from having nothing
to check. So absence is now split into the three facts it was hiding:

  * no macro LEF staged at all                  -> SKIP (genuinely nothing to read)
  * a staged abstract that types its pins, and
    none of them POWER/GROUND                   -> SKIP (an AFFIRMATIVE "no supply
                                                  terminal", which IS evidence)
  * a staged abstract that types NO pin at all  -> **NOT a SKIP** (L21-5): the
                                                  evidence is missing from an
                                                  artefact that exists

And the third case does not degrade to a louder skip — it degrades to a PARTIAL
CHECK. The macro's typing is recovered from the design's own independent views,
in priority order: the macro's own Liberty `pg_pin`/`pg_type` (staged beside the
abstract), then name-equality against `L21.power_domains[]`. Every pin so
recovered is then run through the SAME L21-1 clause, so an untyped abstract
still produces the real rail finding instead of silence.

WHAT IT CHECKS
--------------
  L21-1  (rc=1)    For every instantiated hard-macro supply pin, L21.
                   power_domains[] must declare a rail of the SAME use with the
                   SAME name. The pin's use comes from the design's OWN macro
                   LEF `USE POWER`/`USE GROUND` when the abstract types it, and
                   otherwise is RECOVERED from the macro's own Liberty `pg_pin`
                   or from L21 name-equality (see #774 above). This is the
                   clause whose absence aborts detailed routing.
  L21-2  (rc=1)    Every declared power_domains[] entry must carry a name, a
                   primary POWER net and a primary GROUND net — otherwise the
                   rail set the consumer name-matches against is not derivable
                   from the layer at all. (Only evaluated on entries that exist,
                   so it cannot fire on a design with no domains.)
  L21-3  (rc=1)    Every declared isolation_cells[] / level_shifters[] entry
                   must carry its domain binding, and every isolation cell must
                   carry a clamp_value — an isolation strategy with no clamp
                   value is not actionable by the UPF emitter. (Only evaluated
                   on entries that exist.)
  L21-4  (note)    Reports `extraction_status` / `upf_path` observations that
                   contextualise a finding. Never changes the exit code.
  L21-5  (rc=1)    An instantiated hard macro whose OWN abstract declares PINs
                   and types NONE of them with a `USE` record. Measured, not
                   asserted: `_macro_supply_gc_plan` returns `([], [])` for such
                   a LEF — the macro contributes ZERO global-connect entries AND
                   ZERO `HARDMACRO_SUPPLY_UNCONNECTED` findings, so it is
                   invisible to the binder and to the binder's own honesty
                   report at the same time. Silence there is not a clean bill.

WHAT ITS VERDICT ACTUALLY DOES — MEASURED, NOT CLAIMED (#316)
--------------------------------------------------------------
ADVISORY. Wired as `advisory_program_exit_zero` in
`flow/phase1_phase2_phase3.yaml` step 0, so it RUNS on every real project and
its findings are reported, and rc=1 does not fail the step.

The first draft of this file declared "THIS GATE BLOCKS" and said it was
registered in `flow_compliance_check._STRUCTURAL_RTL_GATES`. It was registered
nowhere. #316's independent verification found that same contradiction in 9 of
its 30 gates — a gate that says it stops a run and does not — which is #306's
finding (62 of 72 gates unable to block) reproduced on brand-new code. So the
declaration above is now the machine-readable one
`flow_gate_enforcement_audit.py` reads, and that audit FAILS if this file ever
declares blocking again without a runner that invokes it inline.

Advisory is also what the measurement supports. Swept over every published cell
under `benchmark-data/`, this gate FAILs two of them —
`edge_llm_accel` (`fakeram45_2048x39` VDD/VSS) and `u_hawaii_adc` (`ldo`
IOVDD/VSS, `delta_sigma` VDD/VSS), both with `power_domains: []` — and SKIPs the
rest. Wired blocking today it would turn two shipped campaign cells red as a
side effect of landing a gate, which is a flow-owner decision and not this
file's to take. Promoting it is a one-line change once those two cells declare
their rails; `programs/tests/test_issue316_layergates_on_published_cells.py`
pins both findings so the promotion can be argued from a measurement.

The honest escape hatch is a NAMED, REVIEWED waiver, not silence: a macro may
carry a dedicated programming/HV supply this design genuinely provides no rail
for. Set `l21_macro_supply_rail_absent_disclosed` in `<project>/waivers.json`
to a >=40-char justification and the gate reports PASS_WITH_WAIVERS (rc=0) while
still printing every finding, so the gap is disclosed rather than invisible.
That is the difference between "reported, never faked" and the original defect.

A waiver must NAME the defect it excuses, so L21-5 has its OWN key,
`l21_macro_lef_pin_use_absent_disclosed`. The rail-absence waiver says "this
design provides no such rail", which is not an excuse for "this abstract types
no pin" — letting it absorb a defect class that did not exist when it was
written is how a waiver outlives its truth.

SINGLE DETERMINISTIC TRACK — NO AI BACKUP
-----------------------------------------
This gate is 100% deterministic: LEF grammar + JSON schema walk. It deliberately
has NO "AI second track". The completeness report that preceded this work shipped
`ai_captured_tokens_count: 0` — an AI backup track that contributed nothing to
the 52 tokens the program flagged, i.e. a dual-track that was really one track.
A single honest track is better than a second one that produces nothing.

NOT A DUPLICATE OF
------------------
  * `power_domain_signal_crossing_check` — wired only into flow step M2, whose
    stage condition is files_exist:[phase1/analog/analog_block_list.json], so it
    is SKIPPED ENTIRELY for a pure-digital design, and it self-guards to SKIP
    when there is no UPF and no L21 domain. It never reaches the failing case.
  * `ip_integration_check` — its L21-vs-macro-Liberty supply check is WARNING
    severity only and is gated on condition_files_exist:[input/pdk_local,
    phase3/analog/hardmacro].
  * `l21_to_upf_emit` — an EMITTER, not a gate: it exits rc=2/SKIP precisely
    when power_domains is empty, i.e. it is silent exactly when the layer is
    hollow. (It is also not referenced anywhere in
    flow/phase1_phase2_phase3.yaml, so the UPF is never emitted by the flow.)

USAGE
-----
    python3 l21_macro_supply_rail_declared_check.py <project_dir> [--json OUT]

EXIT CODES
----------
    0 = PASS (or PASS_WITH_WAIVERS)
    1 = FAIL (blocks)
    2 = not applicable / input missing (SKIP)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # emitter/checker doctrine: reuse the CONSUMER's own LEF walk.
    from phase3_one_shot_runner import (  # type: ignore
        _parse_macro_supply_pins as _consumer_parse_macro_supply_pins,
    )
except Exception:  # pragma: no cover - fallback keeps the gate usable stand-alone
    _consumer_parse_macro_supply_pins = None  # type: ignore

try:  # the SAME block parser the consumer's PG walk delegates to (#774)
    from hardmacro_supply_intent import (  # type: ignore
        lef_all_pins as _shared_lef_all_pins,
        liberty_pg_pins as _shared_liberty_pg_pins,
        pg_type_to_use as _shared_pg_type_to_use,
    )
except Exception:  # pragma: no cover - fallback keeps the gate usable stand-alone
    _shared_lef_all_pins = None  # type: ignore
    _shared_liberty_pg_pins = None  # type: ignore
    _shared_pg_type_to_use = None  # type: ignore

# The ONE negation vocabulary (#712). `_macro_classes` reads a DECLARATION out
# of a text file; see its docstring for why the polarity of that declaration is
# not a formality here.
from _prose_polarity import (  # type: ignore  # noqa: E402
    blank_bracketed as _blank_bracketed,
    is_denied as _is_denied,
)

WAIVER_KEY = "l21_macro_supply_rail_absent_disclosed"
#: L21-5 has its OWN key. A waiver must name the defect it excuses; the
#: rail-absence waiver above predates this defect class and must not absorb it.
WAIVER_KEY_UNTYPED_LEF = "l21_macro_lef_pin_use_absent_disclosed"
WAIVER_MIN = 40
_WAIVER_BY_RULE: Dict[str, str] = {"L21-5": WAIVER_KEY_UNTYPED_LEF}

#: The consequence every L21-1 finding shares, whether the pin's use came from
#: the abstract's own `USE` record or was recovered from a sibling view.
_GC_PLAN_CONSEQUENCE = (
    "_macro_supply_gc_plan name-matches this pin against the declared rails of "
    "the same use; with no match it becomes HARDMACRO_SUPPLY_UNCONNECTED, "
    "synthesis ties the terminal off with TIEHI/TIELO, a SIGNAL net lands on a "
    "POWER-typed terminal and TritonRoute aborts the WHOLE detailed route.")

L21_NAMES = ("L21_POWER_INTENT.json", "L21_POWER_INTENT.JSON")

# Design-OWNED macro LEF roots. These mirror the roots the backend itself
# consumes (`phase3_one_shot_runner._collect_project_macros` reads
# `input/pdk_local/**`; the mixed-signal track reads
# `phase3/analog/hardmacro/**`). All are project-relative; none names a vendor.
_MACRO_LEF_GLOBS: Tuple[str, ...] = (
    "input/pdk_local/**/*.lef",
    "input/macros/**/*.lef",
    "input/hardmacro/**/*.lef",
    "phase3/analog/hardmacro/**/*.lef",
    "phase2/analog/hardmacro/**/*.lef",
)

# The macro's own Liberty view lives beside its abstract, under exactly the same
# roots. DERIVED from the LEF glob list rather than copied, so a root added there
# is searched here the same day.
_MACRO_LIB_GLOBS: Tuple[str, ...] = tuple(
    g[:-len(".lef")] + ".lib" for g in _MACRO_LEF_GLOBS)
#: Bounds on the Liberty sweep. A hard macro's own view is kilobytes; a full
#: std-cell library is not, and this gate does not need it (those cells are
#: CLASS CORE and already out of scope). Losing an oversized library costs a
#: corroboration, never a verdict.
_MAX_LIB_FILES = 200
_MAX_LIB_BYTES = 16 * 1024 * 1024
_MAX_LIB_TOTAL_BYTES = 64 * 1024 * 1024

# Where the design's own instantiations live (RTL first, then gate netlist).
_INSTANCE_TEXT_GLOBS: Tuple[str, ...] = (
    "phase2/stage1/rtl/**/*.v",
    "phase2/stage1/rtl/**/*.sv",
    "phase2/stage2/synth/**/*.v",
    "phase3/stage3/pnr/**/*.v",
)

# LEF CLASS values that denote a hard macro (as opposed to a std cell, whose
# CLASS is CORE, or a filler/tap, whose CLASS is CORE SPACER/WELLTAP). Pure LEF
# grammar; PDK-agnostic.
_HARD_MACRO_CLASSES = ("BLOCK", "RING", "PAD", "COVER")

_POWER_NET_KEYS = (
    "power_net", "power_nets", "primary_power", "primary_power_net",
    "power", "supply_net", "supply_nets", "vdd", "vdd_net", "pwr_net",
    "power_supply", "primary_supply",
)
_GROUND_NET_KEYS = (
    "ground_net", "ground_nets", "primary_ground", "primary_ground_net",
    "ground", "gnd", "gnd_net", "vss", "vss_net", "ground_supply",
)
_NAME_KEYS = ("name", "domain", "domain_name", "id", "power_domain")
_NESTED_SUPPLY_KEYS = ("supply", "supplies", "nets", "rails")
_ISO_DOMAIN_KEYS = ("domain", "power_domain", "from_domain", "source_domain",
                    "from", "src_domain")
_ISO_CLAMP_KEYS = ("clamp_value", "clamp", "isolation_value", "clamp_val")
_LS_DOMAIN_KEYS = ("domain", "from_domain", "source_domain", "from",
                   "src_domain", "power_domain")
_LS_TO_DOMAIN_KEYS = ("to_domain", "dest_domain", "target_domain", "to",
                      "dst_domain")


# --------------------------------------------------------------------------- #
# LEF parsing
# --------------------------------------------------------------------------- #
def _parse_macro_supply_pins(lef_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """``{MACRO_NAME: [(pin_name, USE), ...]}`` for every USE POWER/GROUND pin.

    Delegates to `phase3_one_shot_runner._parse_macro_supply_pins` — the exact
    function the backend uses to build its connect plan — so the gate and the
    consumer can never drift. The inline fallback below is a byte-equivalent
    MACRO/PIN/USE walk kept only so the gate still runs stand-alone."""
    if _consumer_parse_macro_supply_pins is not None:
        return _consumer_parse_macro_supply_pins(lef_text)
    result: Dict[str, List[Tuple[str, str]]] = {}
    cur_macro: Optional[str] = None
    cur_pin: Optional[str] = None
    cur_use: Optional[str] = None
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
        if cur_pin and s.startswith("END ") and s.split()[1:2] == [cur_pin]:
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


def _macro_classes(lef_text: str) -> Dict[str, str]:
    """``{MACRO_NAME: CLASS}`` from a LEF — minus any CLASS its own comment DENIES.

    LEF grammar, and the grammar is INTERLEAVED WITH ENGLISH. That second half
    is why `_prose_polarity` is consulted here rather than waved off as
    ceremony: a LEF is a text file that authors annotate, and the annotation
    can retire the statement under it. vibe-ic#777 measured exactly that on a
    shipped tech LEF, which writes

        # Centered via rule, we really do not want to use it
        VIA <name> DEFAULT

    directly above a block a gate publishes findings from.

    AND THE VALUE READ HERE IS SUBTRACTIVE. `CLASS CORE` is what removes a
    master from an audit's scope — here (a std-cell library staged under a
    macro root is not a hard macro) and in `macro_non_seq_arc_contract_check`
    (`_std_cell_masters`). So a reader that honours a DENIED `CLASS CORE`
    hands the audited file the switch that silences its own audit, which is
    the shape #706/#711 named and the one this vocabulary exists for.

    SCOPE, and it is deliberately narrow. Only the CLASS statement's OWN
    comment counts: the contiguous comment lines immediately above it inside
    the macro (any statement or blank line clears them) plus its own trailing
    `#` comment, with bracketed qualifiers blanked first per #711. MEASURED
    over the 6199 LEF/tech-LEF files reachable on the development host
    (244188 MACRO blocks, 251647 in-macro CLASS statements):

        MACRO-block lead comments carrying a denial word : 126
        CLASS statements denied in their OWN scope       :   0

    Those 126 deny a PIN, a manufacturing grid or an obstruction — never the
    class. Attaching them to CLASS would report 126 macros as unclassified on
    evidence about something else, the same over-attribution #777 refused for
    a file-header line. So the narrow scope is the measurement's answer, and
    the consult changes NO shipped answer today; it closes the shape before a
    vendor LEF writes `CLASS CORE ;  # deprecated, not a core cell`.

    FAIL-SAFE, in the only direction that is safe: a denied CLASS is simply
    not published. Both consumers already treat "no CLASS record" as "keep it
    in scope", so an over-firing vocabulary costs one extra audited macro and
    an under-firing one costs a silenced audit. The full vocabulary is used
    unrefined for that reason.
    """
    out: Dict[str, str] = {}
    cur: Optional[str] = None
    lead: List[str] = []
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        body, _, trail = s.partition("#")
        body, trail = body.strip(), trail.strip()
        if not body:
            # A comment line joins the lead; anything else clears it.
            lead = lead + [trail] if s.startswith("#") else []
            continue
        m = re.match(r"MACRO\s+(\S+)", body)
        if m:
            cur = m.group(1)
            lead = []
            continue
        if cur and body.startswith("END ") and body.split()[1:2] == [cur]:
            cur = None
            lead = []
            continue
        if cur is None:
            lead = []
            continue
        m = re.match(r"CLASS\s+(\S+)", body)
        if m:
            span = _blank_bracketed(
                " ".join(lead + ([trail] if trail else [])))
            if not _is_denied(span):
                out[cur] = m.group(1).rstrip(";").upper()
        lead = []
    return out


# --- EVERY pin, typed or not — the fact the PG-only walk cannot express (#774) #
_FALLBACK_MACRO_RE = re.compile(r"\bMACRO\s+([A-Za-z_][\w\.$]*)", re.IGNORECASE)
_FALLBACK_PIN_BLOCK_RE = re.compile(
    r"\bPIN\s+(?P<name>[A-Za-z_][\w\[\]\.$<>]*)\b(?P<body>.*?)\bEND\s+(?P=name)\b",
    re.S | re.IGNORECASE)
_FALLBACK_ANY_USE_RE = re.compile(r"\bUSE\s+([A-Za-z]+)\s*;", re.IGNORECASE)


def _fallback_all_lef_pins(lef_text: str) -> List[Dict[str, Any]]:
    """Stand-alone equivalent of `hardmacro_supply_intent.lef_all_pins`."""
    out: List[Dict[str, Any]] = []
    if not lef_text:
        return out
    bounds = [(m.start(), m.group(1))
              for m in _FALLBACK_MACRO_RE.finditer(lef_text)]
    if not bounds:
        bounds = [(0, "")]
    for i, (start, master) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(lef_text)
        for pm in _FALLBACK_PIN_BLOCK_RE.finditer(lef_text[start:end]):
            uses = [u.upper()
                    for u in _FALLBACK_ANY_USE_RE.findall(pm.group("body") or "")]
            out.append({"master": master, "pin": pm.group("name"),
                        "use": uses[0] if uses else "", "uses": uses})
    return out


def _all_lef_pins(lef_text: str) -> List[Dict[str, Any]]:
    """``[{"master", "pin", "use", "uses"}]`` for EVERY pin the LEF declares.

    Delegates to `hardmacro_supply_intent.lef_all_pins` — the same block walk
    the backend's own `_parse_macro_supply_pins` delegates to — so "which pins
    exist" and "which pins are typed supply" are two answers from ONE parse and
    can never disagree about the same file."""
    if _shared_lef_all_pins is not None:
        return _shared_lef_all_pins(lef_text)
    return _fallback_all_lef_pins(lef_text)


# --------------------------------------------------------------------------- #
# Liberty parsing — the macro's OWN independent view of its supply pins
# --------------------------------------------------------------------------- #
_LIB_CELL_RE = re.compile(
    r"\bcell\s*\(\s*\"?([A-Za-z_][\w\.\$\[\]/]*)\"?\s*\)", re.IGNORECASE)
_LIB_PG_PIN_RE = re.compile(
    r"\bpg_pin\s*\(\s*\"?(?P<pin>[A-Za-z_][\w\.\$\[\]<>]*)\"?\s*\)"
    r"\s*\{(?P<body>[^{}]*)\}", re.S | re.IGNORECASE)
_LIB_PG_TYPE_RE = re.compile(r"\bpg_type\s*:\s*\"?([A-Za-z_]+)\"?",
                             re.IGNORECASE)


def _pg_type_to_use(pg_type: str) -> str:
    """Liberty ``pg_type`` -> LEF ``USE``. Grammar-level mapping over Liberty's
    own enumeration (primary/backup/internal power|ground plus the well-bias
    types); ``""`` when the group declares no type — the pin is still a declared
    supply terminal, its polarity is just not stated.

    Delegates to `hardmacro_supply_intent.pg_type_to_use` (#785): the Liberty
    walk moved beside the LEF walk once THREE more gates needed it, so there is
    ONE Liberty grammar rather than a fourth private copy — the shape that gave
    one copy of the LEF walk a one-line-pin blind spot the others did not have.
    The body below is retained only as the stand-alone fallback."""
    if _shared_pg_type_to_use is not None:
        return _shared_pg_type_to_use(pg_type)
    v = (pg_type or "").strip().lower()
    if not v:
        return ""
    if "ground" in v or v in ("pwell", "deeppwell"):
        return "GROUND"
    if "power" in v or v in ("nwell", "deepnwell"):
        return "POWER"
    return ""


def _liberty_pg_pins(lib_text: str) -> List[Dict[str, str]]:
    """``[{"cell", "pin", "use"}]`` for every ``pg_pin`` group a Liberty view
    declares. Pure Liberty grammar; no PDK, vendor or cell literal.

    Delegates to `hardmacro_supply_intent.liberty_pg_pins` — see
    `_pg_type_to_use` for why. Body retained as the stand-alone fallback."""
    if _shared_liberty_pg_pins is not None:
        return _shared_liberty_pg_pins(lib_text)
    out: List[Dict[str, str]] = []
    if not lib_text:
        return out
    bounds = [(m.start(), m.group(1)) for m in _LIB_CELL_RE.finditer(lib_text)]
    for i, (start, cell) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(lib_text)
        for pm in _LIB_PG_PIN_RE.finditer(lib_text[start:end]):
            tm = _LIB_PG_TYPE_RE.search(pm.group("body") or "")
            out.append({"cell": cell, "pin": pm.group("pin"),
                        "use": _pg_type_to_use(tm.group(1) if tm else "")})
    return out


def _collect_design_liberty_pg_pins(project: Path) -> Dict[str, Dict[str, str]]:
    """``{cell: {pin: USE}}`` from every Liberty view staged beside the design's
    own macro abstracts. This is the macro's OWN independent statement about
    which of its pins are supply terminals, and it survives a `lef write` that
    drops the LEF `USE` records."""
    out: Dict[str, Dict[str, str]] = {}
    seen: Set[Path] = set()
    budget = _MAX_LIB_TOTAL_BYTES
    for pat in _MACRO_LIB_GLOBS:
        for lib in sorted(project.glob(pat))[:_MAX_LIB_FILES]:
            if not lib.is_file() or lib in seen:
                continue
            seen.add(lib)
            try:
                size = lib.stat().st_size
                if size > _MAX_LIB_BYTES or size > budget:
                    continue
                budget -= size
                text = lib.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for rec in _liberty_pg_pins(text):
                out.setdefault(rec["cell"], {}).setdefault(rec["pin"],
                                                           rec["use"])
    return out


# --------------------------------------------------------------------------- #
class MacroLefFacts(NamedTuple):
    """What the design's OWN macro abstracts say — including what they DON'T.

    `untyped_pins` is the whole point of #774: it separates "this abstract says
    the macro has no supply terminal" from "this abstract says nothing", which
    a PG-only walk collapses into one silent answer."""
    pg_pins: Dict[str, List[Tuple[str, str]]]   # master -> [(pin, USE POWER|GROUND)]
    untyped_pins: Dict[str, List[str]]          # master -> [pin] (abstract types NOTHING)
    pg_lefs: List[str]                          # LEFs contributing a typed PG pin
    untyped_lefs: Dict[str, str]                # master -> the LEF that types nothing
    staged_lefs: List[str]                      # every LEF staged under the roots
    hard_macros_with_pins: List[str]            # every hard macro declaring >=1 PIN


def _collect_design_macro_lef_facts(project: Path) -> MacroLefFacts:
    """Walk the design's OWN macro LEFs once and keep all three facts.

    A std-cell library LEF (CLASS CORE) is excluded by LEF grammar, not by
    filename — so a PDK that ships its std cells under one of these roots does
    not pollute the hard-macro set."""
    pins: Dict[str, List[Tuple[str, str]]] = {}
    untyped: Dict[str, List[str]] = {}
    untyped_lefs: Dict[str, str] = {}
    used_lefs: List[str] = []
    staged: List[str] = []
    hard_with_pins: List[str] = []
    seen: Set[Path] = set()
    for pat in _MACRO_LEF_GLOBS:
        for lef in sorted(project.glob(pat)):
            if not lef.is_file() or lef in seen:
                continue
            seen.add(lef)
            rel = str(lef.relative_to(project))
            staged.append(rel)
            try:
                text = lef.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            classes = _macro_classes(text)
            typed = _parse_macro_supply_pins(text)
            by_master: Dict[str, List[Dict[str, Any]]] = {}
            for rec in _all_lef_pins(text):
                by_master.setdefault(str(rec.get("master") or ""),
                                     []).append(rec)
            contributed = False
            for master in sorted(by_master):
                recs = by_master[master]
                if not master or not recs:
                    continue
                cls = classes.get(master, "")
                # No CLASS record at all -> treat as a hard macro (many vendor
                # macro LEFs omit it); an explicit CORE class is a std cell.
                if cls and not any(cls.startswith(c)
                                   for c in _HARD_MACRO_CLASSES):
                    continue
                if master not in hard_with_pins:
                    hard_with_pins.append(master)
                pinlist = typed.get(master) or []
                if pinlist:
                    bucket = pins.setdefault(master, [])
                    for entry in pinlist:
                        if entry not in bucket:
                            bucket.append(entry)
                    contributed = True
                    continue
                if any(r.get("uses") for r in recs):
                    # The abstract DOES type its pins and none of them is a
                    # supply pin. That is an affirmative declaration, not
                    # missing evidence — nothing to report.
                    continue
                names = untyped.setdefault(master, [])
                for r in recs:
                    name = str(r.get("pin") or "")
                    if name and name not in names:
                        names.append(name)
                untyped_lefs.setdefault(master, rel)
            if contributed:
                used_lefs.append(rel)
    # A master typed in ONE staged abstract and untyped in another is covered by
    # the typed one — the conservative reading, and it keeps a stale duplicate
    # abstract from manufacturing a finding.
    untyped = {m: v for m, v in untyped.items() if m not in pins and v}
    untyped_lefs = {m: p for m, p in untyped_lefs.items() if m in untyped}
    return MacroLefFacts(pins, untyped, used_lefs, untyped_lefs, staged,
                         hard_with_pins)


def _collect_design_macro_pg_pins(
        project: Path) -> Tuple[Dict[str, List[Tuple[str, str]]], List[str]]:
    """``({master: [(pin, USE)...]}, [lef_path...])`` — the typed-PG view of
    `_collect_design_macro_lef_facts`, kept as the historical entry point."""
    facts = _collect_design_macro_lef_facts(project)
    return facts.pg_pins, facts.pg_lefs


def _instantiated_masters(project: Path,
                          masters: Sequence[str]) -> Optional[Set[str]]:
    """Subset of `masters` instantiated in the design's own RTL / netlist.

    Returns None when NO RTL or netlist text is available yet (the gate may run
    before RTL generation) — the caller then treats every design-staged macro as
    in scope, which is the conservative reading of a design that deliberately
    staged that macro."""
    texts: List[str] = []
    for pat in _INSTANCE_TEXT_GLOBS:
        for f in sorted(project.glob(pat))[:400]:
            if not f.is_file():
                continue
            try:
                texts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
    if not texts:
        return None
    blob = "\n".join(texts)
    hit: Set[str] = set()
    for m in masters:
        if re.search(r"\b" + re.escape(m) + r"\b", blob):
            hit.add(m)
    return hit


# --------------------------------------------------------------------------- #
# L21 schema walk
# --------------------------------------------------------------------------- #
def _as_name_list(value) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        s = value.strip()
        if s:
            out.append(s)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_as_name_list(v))
    elif isinstance(value, dict):
        for key in ("name", "net", "net_name", "value"):
            if key in value:
                out.extend(_as_name_list(value[key]))
                break
    return out


def _nets_from_entry(entry: dict, keys: Sequence[str]) -> List[str]:
    out: List[str] = []
    for k in keys:
        if k in entry:
            out.extend(_as_name_list(entry[k]))
    for nk in _NESTED_SUPPLY_KEYS:
        nested = entry.get(nk)
        if isinstance(nested, dict):
            for k in keys:
                if k in nested:
                    out.extend(_as_name_list(nested[k]))
    # de-dup, order-preserving
    seen: Set[str] = set()
    uniq: List[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _l21_fields(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    fields = doc.get("fields")
    if isinstance(fields, dict):
        return fields
    return doc


def _declared_rails(fields: dict) -> Tuple[Set[str], Set[str], List[dict]]:
    domains = fields.get("power_domains")
    if not isinstance(domains, list):
        domains = []
    entries = [d for d in domains if isinstance(d, dict)]
    power: Set[str] = set()
    ground: Set[str] = set()
    for d in entries:
        power.update(_nets_from_entry(d, _POWER_NET_KEYS))
        ground.update(_nets_from_entry(d, _GROUND_NET_KEYS))
    return power, ground, entries


def _entry_name(entry: dict) -> Optional[str]:
    for k in _NAME_KEYS:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _waivers(project: Path) -> Dict[str, str]:
    """Every waiver key this gate honours that carries a >=WAIVER_MIN
    justification. Keyed per DEFECT CLASS (see `_WAIVER_BY_RULE`), so a waiver
    written for one finding cannot silently absorb another."""
    out: Dict[str, str] = {}
    p = project / "waivers.json"
    if not p.is_file():
        return out
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out
    if not isinstance(doc, dict):
        return out
    for key in (WAIVER_KEY, WAIVER_KEY_UNTYPED_LEF):
        v = doc.get(key)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            out[key] = v.strip()
    return out


def _waived(project: Path) -> Tuple[bool, str]:
    """Historical single-key entry point (the rail-absence waiver)."""
    w = _waivers(project)
    return (WAIVER_KEY in w), w.get(WAIVER_KEY, "")


def _find_l21(project: Path) -> Optional[Path]:
    for name in L21_NAMES:
        p = project / "phase1" / "generated_docs" / name
        if p.is_file():
            return p
    for hit in sorted(project.glob("**/generated_docs/L21_*.json")):
        if hit.is_file():
            return hit
    return None


# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L21 power-intent macro-supply-rail semantic gate")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    if not project.is_dir():
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              f"not a directory: {project}")
        return 2

    facts = _collect_design_macro_lef_facts(project)
    macro_pins = facts.pg_pins
    untyped_pins = facts.untyped_pins
    lef_paths = facts.pg_lefs
    l21_path = _find_l21(project)

    report: Dict[str, object] = {
        "gate": "l21_macro_supply_rail_declared_check",
        "project": str(project),
        "macro_lefs": lef_paths,
        "staged_macro_lefs": facts.staged_lefs,
        "untyped_macro_lefs": facts.untyped_lefs,
        "findings": [],
        "advisories": [],
    }

    # ---- THE THREE-WAY SPLIT (#774) ------------------------------------- #
    # "No USE POWER/GROUND pin found" used to be ONE answer covering three
    # different facts. Only the first two are non-applicability.
    if not macro_pins and not untyped_pins:
        if not facts.staged_lefs:
            reason = ("no macro LEF at all declared or staged by the design "
                      "under any root the backend reads ("
                      + ", ".join(_MACRO_LEF_GLOBS)
                      + ") — there is genuinely nothing to read.")
        elif not facts.hard_macros_with_pins:
            reason = (f"the {len(facts.staged_lefs)} staged LEF(s) declare no "
                      "hard macro with a PIN (CLASS CORE std cells / technology "
                      "LEF only) — nothing for the backend to name-match "
                      "against.")
        else:
            reason = (
                f"every pin the {len(facts.hard_macros_with_pins)} staged hard "
                "macro(s) declare carries an explicit `USE` and none of them is "
                "POWER or GROUND — an AFFIRMATIVE declaration that these macros "
                "have no supply terminal, which is evidence, not its absence.")
        print(f"[SKIP] l21_macro_supply_rail_declared_check: {reason}")
        report["verdict"] = "SKIP"
        report["skip_reason"] = reason
        # v1.15.45 (sha256 capture) — all three arms are the DESIGN's own
        # declaration (no macro, no pinned macro, or an affirmative no-supply
        # pin set); classify them so the audit reads a disclosed skip, not an
        # execution error (which turned D1 INCOMPLETE on every macro-less IC).
        report["reason_class"] = "DESIGN_DECLARED_NA"
        report["skip_kind"] = "class-not-applicable"
        _emit(args.json, report)
        return 2

    all_masters = sorted(set(macro_pins) | set(untyped_pins))
    inst = _instantiated_masters(project, all_masters)
    if inst is None:
        in_scope = all_masters
        scope_note = ("no RTL/netlist text available yet — every design-staged "
                      "hard macro treated as in scope")
    else:
        in_scope = [m for m in all_masters if m in inst]
        scope_note = (f"{len(in_scope)}/{len(all_masters)} staged hard macro(s) "
                      "instantiated in the design's own RTL/netlist")
    in_scope_pg = [m for m in in_scope if m in macro_pins]
    in_scope_untyped = [m for m in in_scope if m in untyped_pins]
    report["scope_note"] = scope_note
    report["in_scope_masters"] = in_scope
    report["in_scope_untyped_masters"] = in_scope_untyped

    if not in_scope:
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              f"{scope_note}; no instantiated hard macro with PG pins.")
        report["verdict"] = "SKIP"
        report["skip_reason"] = scope_note
        _emit(args.json, report)
        return 2

    if l21_path is None:
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              "no L21_POWER_INTENT.json in this project.")
        # Not a verdict change — but the untyped abstract must not vanish with
        # the layer it would have been compared against.
        for master in in_scope_untyped:
            print(f"  [note] hard macro `{master}` "
                  f"(`{facts.untyped_lefs.get(master, '?')}`) types NONE of its "
                  f"{len(untyped_pins[master])} PIN(s) with a `USE` record; "
                  "there is no L21 here to compare it against.")
        report["verdict"] = "SKIP"
        report["skip_reason"] = "no L21_POWER_INTENT.json in this project"
        _emit(args.json, report)
        return 2

    try:
        doc = json.loads(l21_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        print(f"[FAIL] l21_macro_supply_rail_declared_check: {l21_path} is not "
              f"parseable JSON ({exc}); the backend's rail contract is "
              "unreadable.")
        report["verdict"] = "FAIL"
        report["findings"] = [{"rule": "L21-0", "message": f"unparseable: {exc}"}]
        _emit(args.json, report)
        return 1

    fields = _l21_fields(doc)
    power_rails, ground_rails, domain_entries = _declared_rails(fields)
    findings: List[Dict[str, str]] = []

    # ---- RECOVER a typing for the macros whose abstract declares none ----- #
    # Priority: the macro's OWN Liberty view (an independent statement about the
    # same macro), then name-equality against the rails L21 itself declares.
    # Both are the design's own machine-readable artefacts; neither is a
    # name pattern or a keyword list.
    lib_pg = _collect_design_liberty_pg_pins(project) if in_scope_untyped else {}
    corroborated: Dict[str, List[Dict[str, str]]] = {}
    for master in in_scope_untyped:
        recs: List[Dict[str, str]] = []
        cell_pg = lib_pg.get(master) or {}
        for pin in untyped_pins[master]:
            if pin in cell_pg:
                use = cell_pg[pin]
                recs.append({
                    "pin": pin, "use": use,
                    "source": (
                        f"the macro's OWN Liberty view declares `pg_pin ({pin})`"
                        + (f" with pg_type -> {use}" if use
                           else " (no pg_type, so its polarity is unstated)"))})
            elif pin in power_rails:
                recs.append({
                    "pin": pin, "use": "POWER",
                    "source": ("L21.power_domains[] declares a POWER rail of "
                               "exactly that name")})
            elif pin in ground_rails:
                recs.append({
                    "pin": pin, "use": "GROUND",
                    "source": ("L21.power_domains[] declares a GROUND rail of "
                               "exactly that name")})
        corroborated[master] = recs
    report["recovered_pg_pins"] = {m: v for m, v in corroborated.items() if v}

    # ---- L21-1: macro supply pin must have a declared rail of the SAME use - #
    # `checked` is (master, pin, use, typing_source). A pin whose use came from
    # the abstract's own `USE` record and a pin whose use was recovered from a
    # sibling view answer the SAME question, so they run the SAME clause.
    checked: List[Tuple[str, str, str, str]] = []
    for master in in_scope_pg:
        for pin, use in macro_pins[master]:
            checked.append((master, pin, use, "lef_use"))
    for master in in_scope_untyped:
        for rec in corroborated[master]:
            if rec["use"]:
                checked.append((master, rec["pin"], rec["use"], rec["source"]))

    for master, pin, use, source in checked:
        rails = power_rails if use == "POWER" else ground_rails
        if pin in rails:
            continue
        if source == "lef_use":
            head = (f"hard macro `{master}` types pin `{pin}` as USE {use} "
                    f"in its OWN macro LEF, but L21.power_domains[] "
                    f"declares no {use} rail named `{pin}`. ")
        else:
            head = (f"hard macro `{master}` exposes pin `{pin}` and its OWN "
                    f"macro LEF (`{facts.untyped_lefs.get(master, '?')}`) types "
                    f"NO pin at all — but {source}, so `{pin}` is a {use} "
                    f"terminal — and L21.power_domains[] declares no {use} rail "
                    f"named `{pin}`. ")
        findings.append({
            "rule": "L21-1",
            "master": master,
            "pin": pin,
            "use": use,
            "typing_source": source,
            "message": head + _GC_PLAN_CONSEQUENCE,
        })

    # ---- L21-5: an abstract that types NOTHING is not an absent abstract -- #
    for master in in_scope_untyped:
        pins_here = untyped_pins[master]
        recs = corroborated[master]
        if recs:
            named = ", ".join(f"`{r['pin']}` ({r['use'] or 'polarity unstated'}"
                              f", via {r['source']})" for r in recs)
            evidence = (f"CORROBORATED: {len(recs)} of these pin(s) are supply "
                        f"terminals by the design's OWN independent view — "
                        f"{named}. So this abstract is UNDER-DECLARED, not "
                        "supply-less.")
        else:
            evidence = ("No independent view of this macro is staged (no "
                        "Liberty `pg_pin` beside the abstract, and "
                        "L21.power_domains[] declares no rail name matching any "
                        "of its pins), so the supply contract is UNVERIFIABLE "
                        "from either side — which is a different fact from a "
                        "design with no supply pin to declare.")
        findings.append({
            "rule": "L21-5",
            "master": master,
            "lef": facts.untyped_lefs.get(master, "?"),
            "message": (
                f"hard macro `{master}` is staged as "
                f"`{facts.untyped_lefs.get(master, '?')}` and declares "
                f"{len(pins_here)} PIN(s) — and types NONE of them with a `USE` "
                f"record. `_macro_supply_gc_plan` keys on `USE POWER` / `USE "
                f"GROUND`, so this macro contributes ZERO entries to the "
                f"global-connect plan AND ZERO HARDMACRO_SUPPLY_UNCONNECTED "
                f"findings: it is invisible to the binder and to the binder's "
                f"own honesty report at the same time, so silence about it is "
                f"not a clean bill. A tool-written abstract is the common case "
                f"here — `magic`'s `lef write` emits neither `DIRECTION` nor "
                f"`USE` on any PIN. {evidence}"),
        })

    # ---- L21-2: every declared domain must be actionable ---- #
    for i, entry in enumerate(domain_entries):
        missing: List[str] = []
        if _entry_name(entry) is None:
            missing.append("name")
        if not _nets_from_entry(entry, _POWER_NET_KEYS):
            missing.append("primary power net")
        if not _nets_from_entry(entry, _GROUND_NET_KEYS):
            missing.append("primary ground net")
        if missing:
            findings.append({
                "rule": "L21-2",
                "entry": _entry_name(entry) or f"power_domains[{i}]",
                "message": (
                    f"power_domains[{i}] "
                    f"({_entry_name(entry) or 'unnamed'}) is missing "
                    f"{', '.join(missing)} — the rail set the backend "
                    "name-matches against is not derivable from this entry."),
            })

    # ---- L21-3: declared isolation / level-shifter entries must be typed --- #
    for i, entry in enumerate(fields.get("isolation_cells") or []):
        if not isinstance(entry, dict):
            findings.append({
                "rule": "L21-3", "entry": f"isolation_cells[{i}]",
                "message": (f"isolation_cells[{i}] is not an object; an "
                            "isolation strategy must be typed to be "
                            "actionable.")})
            continue
        missing = []
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _ISO_DOMAIN_KEYS):
            missing.append("domain")
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _ISO_CLAMP_KEYS):
            missing.append("clamp_value")
        if missing:
            findings.append({
                "rule": "L21-3", "entry": f"isolation_cells[{i}]",
                "message": (f"isolation_cells[{i}] is missing "
                            f"{', '.join(missing)} — an isolation cell with no "
                            "clamp value / domain binding cannot be emitted "
                            "into UPF.")})
    for i, entry in enumerate(fields.get("level_shifters") or []):
        if not isinstance(entry, dict):
            findings.append({
                "rule": "L21-3", "entry": f"level_shifters[{i}]",
                "message": (f"level_shifters[{i}] is not an object; a level "
                            "shifter must be typed to be actionable.")})
            continue
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _LS_DOMAIN_KEYS) and not any(
                       k in entry and entry[k] not in (None, "")
                       for k in _LS_TO_DOMAIN_KEYS):
            findings.append({
                "rule": "L21-3", "entry": f"level_shifters[{i}]",
                "message": (f"level_shifters[{i}] declares no domain binding — "
                            "a level shifter with no from/to domain cannot be "
                            "placed on a crossing.")})

    # ---- L21-4: advisories (never change the exit code) ---- #
    advisories: List[str] = []
    status = doc.get("extraction_status")
    if isinstance(status, str) and status.upper().startswith("NOT_YET"):
        advisories.append(
            f"extraction_status={status} and emitted_by="
            f"{doc.get('emitted_by')!r}: this L21 is still the untouched "
            "post-process skeleton, so an empty power_domains[] here is "
            "indistinguishable from a legitimately single-domain design.")
    # DELIBERATELY NOT READ: `fields["upf_path"]`.
    #
    # The first draft raised an advisory when it was null. `l_doc_field_
    # producer_check` refused that reader and was right: upf_path is present
    # as a KEY in 15 published L21 docs and carries a value in ZERO of them,
    # so the advisory fires on every project and distinguishes nothing — an
    # empty value read as if it were a measurement, which is the exact shape
    # (#309/#348: L21 `declared_rails`, read by the phase-3 supply gate,
    # populated in 3 of 30 docs) that gate exists to stop. That no UPF is ever
    # emitted is a real gap, but it is a property of the emitter, not of the
    # design under test; it is documented in "NOT A DUPLICATE OF" above and
    # belongs in a gate on `l21_to_upf_emit`, not in a per-run note here.
    report["advisories"] = advisories
    report["findings"] = findings
    report["declared_power_rails"] = sorted(power_rails)
    report["declared_ground_rails"] = sorted(ground_rails)
    report["macro_pg_pins"] = {m: macro_pins[m] for m in in_scope_pg}
    report["untyped_macro_pins"] = {m: untyped_pins[m]
                                    for m in in_scope_untyped}

    if not findings:
        report["verdict"] = "PASS"
        _emit(args.json, report)
        print("[PASS] l21_macro_supply_rail_declared_check: every USE "
              "POWER/GROUND pin of the "
              f"{len(in_scope)} instantiated hard macro(s) "
              f"({scope_note}) has a same-use rail declared in "
              f"L21.power_domains[] "
              f"(POWER={sorted(power_rails)}, GROUND={sorted(ground_rails)}).")
        for a in advisories:
            print(f"  [note] {a}")
        return 0

    # A waiver covers the DEFECT CLASS it names, and nothing else.
    waivers = _waivers(project)
    uncovered = [f for f in findings
                 if _WAIVER_BY_RULE.get(str(f["rule"]), WAIVER_KEY)
                 not in waivers]
    waived = not uncovered
    report["verdict"] = "PASS_WITH_WAIVERS" if waived else "FAIL"
    report["waivers_applied"] = sorted(waivers)
    _emit(args.json, report)
    head = ("PASS_WITH_WAIVERS" if waived else "[FAIL]")
    print(f"{head} l21_macro_supply_rail_declared_check: "
          f"{len(findings)} L21 power-intent finding(s) "
          f"({scope_note}; macro LEFs: {lef_paths}).")
    for f in findings:
        print(f"  - {f['rule']}: {f['message']}")
    for a in advisories:
        print(f"  [note] {a}")
    if waived:
        for key in sorted(waivers):
            print(f"  waiver `{key}` set: {waivers[key][:120]}")
        return 0
    if any(f["rule"] != "L21-5" for f in uncovered):
        print("  Fix: declare the missing rail(s) in L21.power_domains[] (the "
              "layer the backend's supply contract is read from), or set waiver "
              f"`{WAIVER_KEY}` (>={WAIVER_MIN} chars) to DISCLOSE that this "
              "design genuinely provides no such rail.")
    if any(f["rule"] == "L21-5" for f in uncovered):
        print("  Fix (L21-5): re-attach `DIRECTION` + `USE "
              "POWER|GROUND|SIGNAL` to the abstract's pins — a `lef write` from "
              "the layout emits neither, so the typing has to be restored after "
              "it — or set waiver "
              f"`{WAIVER_KEY_UNTYPED_LEF}` (>={WAIVER_MIN} chars) to DISCLOSE "
              "that this macro genuinely has no supply terminal to type.")
    return 1


def _emit(path: Optional[Path], report: Dict[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
