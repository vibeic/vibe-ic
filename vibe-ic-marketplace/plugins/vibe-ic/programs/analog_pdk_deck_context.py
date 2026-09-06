#!/usr/bin/env python3
"""analog_pdk_deck_context.py — family-agnostic ngspice deck-emission context.

Consumes an `analog_pdk_availability.resolve_pdk()` result (the v1.4.24 native
PDK resolver) and turns it into the CONCRETE context a corner-sweep deck needs
to be emitted for the RESOLVED PDK family — never a hardcoded sky130 literal:

  * model_lib        — the `.lib` path the deck loads (+ model_lib_includes)
  * corner_sections  — the corner section names those libs actually ship
                       (ss/tt/ff for the open PDKs; whatever the custom lib has)
  * device_map       — {role: device_subckt} for the device ROLES the templates
                       instantiate, derived by PARSING `.subckt` names from the
                       RESOLVED libs + a generic token→role heuristic.

When a REQUIRED device role cannot be resolved deterministically from the
resolved libs, the context is returned with `status="NEEDS_NATIVE_TEMPLATE"` and
a named work-item. The deck emitter must then FAIL HONESTLY rather than emit
sky130 devices against a non-sky130 lib (the whole point of this module).

chip-AGNOSTIC: the only family LITERALS here are the two OPEN PDKs the corner
templates were authored against (sky130 / gf180 — already present throughout the
plugin) as a known-good fast path that keeps the sky130 regression bit-identical.
EVERY other family is resolved purely by structural lib parsing + generic role
token heuristics — no chip / vendor / SKU literal. Reports PATHS ONLY (NDA
hygiene — never PDK content).
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv

# ── canonical sky130 device tokens the corner templates are authored against ──
# These are the tokens the deck emitter REMAPS to the resolved family's device
# names (see analog_real_corner_sweep.render_deck). They double as the known
# open-PDK fast-path device map (sky130 stays byte-identical; gf180 keeps the
# historical sky130 device names — its native template is a separate work item,
# out of scope for this family-agnostic consumption batch).
SKY130_DEVICES = {
    "nmos": "sky130_fd_pr__nfet_01v8",
    "pmos": "sky130_fd_pr__pfet_01v8",
}

# Known OPEN-PDK families (the corner templates' authored targets). Keyed on the
# `--pdk` selector value used by analog_real_corner_sweep. NOT a probe of a
# proprietary node — purely the two open PDKs already hardcoded across the plugin.
_KNOWN_FAMILIES = {
    "sky130": {
        "device_map": dict(SKY130_DEVICES),
        "corner_sections": ["ss", "tt", "ff"],
        "model_lib": "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice",
    },
    "gf180": {
        # historical behaviour preserved: gf180 kept the sky130 device tokens
        # (its own native template was never authored). Unchanged here.
        "device_map": dict(SKY130_DEVICES),
        "corner_sections": ["ss", "tt", "ff"],
        "model_lib": "/foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice",
    },
}

# Generic device-ROLE token sets (chip-AGNOSTIC — structural device-class tokens
# every foundry SPICE lib uses, not any vendor/SKU literal). A `.subckt` name is
# assigned a role only when it matches exactly ONE role's tokens (an ambiguous
# name that matches both n- and p- tokens is left UNASSIGNED — honest, not a
# guess). Required roles for the current templates are nmos + pmos; res/cap are
# resolved-if-present but never gate emission (the templates model R/C with
# ngspice primitives, not PDK subckts).
_ROLE_TOKENS = {
    "nmos": ("nfet", "nmos", "nch"),
    "pmos": ("pfet", "pmos", "pch"),
    "res":  ("rpoly", "rppd", "rnwell", "resistor", "res_", "_res"),
    "cap":  ("mimcap", "moscap", "varactor", "mim_", "_cap", "cap_"),
}
_REQUIRED_ROLES_DEFAULT = ("nmos", "pmos")

# Corner-section role tokens (slow / typ / fast). typ is the nominal section the
# knob sweep runs at; slow/fast bracket the process grid.
_SECTION_ROLE_TOKENS = {
    "slow": ("ss", "slow"),
    "typ":  ("tt", "typ", "nom", "tm"),
    "fast": ("ff", "fast"),
}
# process offsets mirror analog_real_corner_sweep.PVT_PROCESS (±3% off nominal)
_SECTION_ROLE_OFFSET = {"slow": -0.03, "typ": 0.0, "fast": +0.03}

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+(\S+)\s+(.*)$")
_MODEL_RE = re.compile(r"(?im)^\s*\.model\s+(\S+)\s+(\w+)")
# ── geometry-UNIT convention of a foundry's OWN device subckt ──────────────
# Two conventions exist in the wild and they are NOT interchangeable:
#   METRIC   — the subckt declares metric defaults (`+ w=0.35u l=0.34u ...`)
#              and its junction expressions mix the CALLER's `w` with
#              HARD-CODED metric constants, e.g. IHP sg13g2:
#                  as='max(w/ng,wmin)*(z1+((ng-1)/2)*z2)'
#                  z1=0.34e-6  z2=0.38e-6  wmin=0.15e-6
#              so `w` MUST arrive in metres. (gf180 is metric too: `w=10u`.)
#   UNITLESS — no metric default on the header; the deck passes bare numbers
#              and `.option scale` converts them. This is the sky130 idiom the
#              corner templates are AUTHORED in.
# `.option scale` is applied by ngspice to PRIMITIVE device geometry; it does
# NOT rescale a bare number handed to a SUBCKT before that subckt's own
# arithmetic consumes it. So a bare `w=8` under `.option scale=1u` reaching a
# METRIC subckt makes `as/ad/ps/pd` come out ~1e6x wrong, and the junction
# leakage they imply swamps the circuit at high temperature (measured on the
# u_hawaii_adc LDO: every -40C/27C corner regulated, every 125C corner did not,
# at EVERY pass-device size). Detected from the PDK's OWN text — structural,
# no vendor/SKU literal, and a PDK with no metric default is left UNITLESS so
# the sky130 path stays byte-identical.
_GEOM_DEFAULT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])([wl])\s*=\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"
    r"\s*([a-zA-Z]*)")
# SPICE engineering suffixes that denote a sub-millimetre magnitude.
_SI_SUB_MM = ("u", "n", "p", "f", "a", "meg")  # 'm' is ambiguous (milli/metre)
# section DEFINITION form: `.lib <bare-identifier>` alone (NOT the include form
# `.lib "path" section`, which carries a path/quote after `.lib`).
_LIB_SECTION_RE = re.compile(r"(?im)^\s*\.lib\s+([A-Za-z_]\w*)\s*$")
# section END form: `.endl [name]`.
_ENDL_RE = re.compile(r"(?im)^\s*\.endl\b")


def _iter_section_bodies(text: str):
    """Yield (section_name, body_text) for every `.lib <bare> ... .endl` block.
    Non-nesting (HSPICE/ngspice section DEFs do not nest); a stray inner
    `.lib <bare>` closes the current block defensively. Lines outside any block
    are ignored. Pure — chip-AGNOSTIC (directive syntax only)."""
    lines = (text or "").splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = _LIB_SECTION_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        j = i + 1
        body: List[str] = []
        while j < n and not _ENDL_RE.match(lines[j]):
            if _LIB_SECTION_RE.match(lines[j]):        # defensive: no nesting
                break
            body.append(lines[j])
            j += 1
        yield name, "\n".join(body)
        i = j + 1


def parse_composed_corner_sections(lib_path: str, text: str) -> List[str]:
    """Return the section names in `text` that are CROSS-FILE COMPOSED corners.

    A foundry ships a corner ENTRY-POINT lib (e.g. a `corner<X>.lib`) whose
    top-level `.lib <corner> ... .endl` sections do not define devices/params
    themselves — they COMPOSE the process-param, noise-flag, passive and diode
    sub-sections that a single device building-block sub-lib's per-section does
    NOT. Structurally, such a section's body `.include`s / `.lib '<file>'
    <section>`-includes at least one model file OTHER than its own — the signal
    that it is the self-contained corner the deck should load, and the only lib
    whose closure can carry the HSPICE-only packaging directives (`.malias`) the
    ngspice normalizer strips.

    A device building-block sub-lib's per-section (e.g. `tt_tn`) only includes
    sections of its OWN file, so it is NOT reported here — it is not a complete
    corner on its own. chip-AGNOSTIC: keyed purely on cross-file composition
    structure, never a vendor / SKU / section-name literal."""
    own = posixpath.basename(str(lib_path)).lower()
    out: List[str] = []
    for name, body in _iter_section_bodies(text):
        cross_file = False
        for inc in _iter_includes(body):
            ref = posixpath.basename(inc).lower()
            if ref and ref != own:
                cross_file = True
                break
        if cross_file:
            out.append(name)
    return out


@dataclass
class DeckContext:
    """The concrete, family-resolved context the corner-sweep deck emitter
    consumes. `status == "OK"` means the required device roles + a nominal
    corner section resolved; `status == "NEEDS_NATIVE_TEMPLATE"` means the
    emitter must fail honestly (never emit a cross-family deck)."""
    status: str                                    # OK | NEEDS_NATIVE_TEMPLATE
    source: str                                    # known_family | project_custom_pdk | container_installed
    family: Optional[str] = None
    # ORGANIC #410 — the template this context ACTUALLY carries. Equal to
    # `family` for a known open PDK; for an unknown selector `family` is the
    # name that was asked for while the device map / model lib come from the
    # fallback named here. Without it the context claims to describe a PDK it
    # does not carry, which is #389's misattribution in the analog track.
    template_family: Optional[str] = None
    model_lib: Optional[str] = None
    model_lib_includes: List[str] = field(default_factory=list)
    corner_sections: List[str] = field(default_factory=list)
    typ_section: Optional[str] = None
    process_corners: List[Tuple[str, float]] = field(default_factory=list)
    device_map: Dict[str, str] = field(default_factory=dict)
    # {role: n_terminals} for each resolved device subckt. The corner templates
    # are authored for a 4-terminal (d g s b) MOS; a foundry subckt that carries
    # EXTRA terminals (e.g. a 5th p-substrate node, `d g s b sub`) needs those
    # extra nodes supplied at instantiation, else ngspice aborts "Too few
    # parameters for subcircuit". The deck emitter reads this to inject the
    # missing substrate/well ties (see render_deck). chip-AGNOSTIC.
    device_terminals: Dict[str, int] = field(default_factory=dict)
    # {role: "metric"|"unitless"} — the geometry-UNIT convention each resolved
    # device subckt declares for ITSELF (see _GEOM_DEFAULT_RE). The deck emitter
    # reads this to decide whether the templates' `.option scale=1u` + bare
    # `w=`/`l=` idiom is valid for the resolved family, or whether the geometry
    # must be emitted in explicit metres (see render_deck). chip-AGNOSTIC.
    device_geometry_units: Dict[str, str] = field(default_factory=dict)
    unresolved_roles: List[str] = field(default_factory=list)
    # vibe-ic#903 — HOW each device role's flavour was elected, and WHAT was
    # rejected. The device binding is an ELECTRICAL choice; before #903 it was
    # decided by name ORDER and the artefact recorded nothing about it, so a
    # reader had to re-derive the rule from the lib names to know why a deck
    # binds the device it binds. See ELECTION_BASIS_* and `elect_device_roles`.
    # It also carries the fact this fix does NOT resolve: when a family ships
    # more than one voltage domain, ONE flavour is elected for the whole design.
    device_election: Dict[str, Any] = field(default_factory=dict)
    # vibe-ic#907 — EVERY (lib, section) THE DECK MUST LOAD, in order.
    #
    # The deck used to load exactly one: `.lib <model_lib> <typ_section>`. That
    # is correct only while every bound device lives in that lib's closure. A
    # family that splits its devices across several corner libs (actives in one,
    # passives in another) resolves its device_map from the cross-lib UNION and
    # then binds a device the single loaded section never defines — ngspice
    # stops at `unknown subckt`. Each entry carries its OWN section name because
    # the split libs do not share a corner vocabulary.
    #
    # A single-lib family yields exactly ONE entry (the primary), so the emitted
    # deck is byte-identical to what it was. Empty = "the caller should keep
    # emitting the single `model_lib` line" (the known-family fast path never
    # populates this).
    deck_loads: List[Tuple[str, str]] = field(default_factory=list)
    work_items: List[str] = field(default_factory=list)
    disclosure: str = ""
    # vibe-ic#193 — WHICH primary-selection strategy elected `model_lib`. There
    # is now exactly ONE election strategy (see RETIRED_PRIMARY_STRATEGIES for
    # the second one and why it is gone), so this is no longer a "which world am
    # I in" disambiguator — it is the artefact's positive statement of the
    # strategy it was produced under, which is what makes a future SECOND
    # strategy visible in the artefact from day one. One of:
    #   PRIMARY_BY_DEVICE_RANK  — the device-defining ranking (#149 / v1.4.58)
    #   PRIMARY_BY_KNOWN_TABLE  — the open-PDK authored table (no election)
    #   PRIMARY_NONE            — nothing readable to elect
    primary_policy: Optional[str] = None

    def as_json(self) -> Dict[str, Any]:
        return {
            "status": self.status, "source": self.source, "family": self.family,
            "template_family": self.template_family,
            "model_lib": self.model_lib,
            "model_lib_includes": self.model_lib_includes,
            "corner_sections": self.corner_sections,
            "typ_section": self.typ_section,
            "process_corners": [list(pc) for pc in self.process_corners],
            "device_map": self.device_map,
            "device_terminals": self.device_terminals,
            "device_geometry_units": self.device_geometry_units,
            "unresolved_roles": self.unresolved_roles,
            "device_election": self.device_election,
            "deck_loads": [list(dl) for dl in self.deck_loads],
            "work_items": self.work_items, "disclosure": self.disclosure,
            "primary_policy": self.primary_policy,
        }


# vibe-ic#193 — the SINGLE primary-selection strategy for a parsed custom family
# (`PRIMARY_BY_DEVICE_RANK`), plus the two non-election outcomes. A second
# strategy used to live beside it; see RETIRED_PRIMARY_STRATEGIES.
PRIMARY_BY_DEVICE_RANK = "device-defining-rank"
PRIMARY_BY_KNOWN_TABLE = "known-family-table"
PRIMARY_NONE = "none"

# ── the record of a DELETED strategy ────────────────────────────────────────
# A deletion that leaves no trace is indistinguishable from a strategy that was
# never considered. This module carried TWO primary-selection strategies for
# eight months; the owner's vibe-ic#193 decision keeps one. What follows is the
# retired one's epitaph — what it did, why it went, and what to do if it is
# wanted back — kept HERE rather than in a commit message because the next
# person to need it will be reading this file, not the log.
#
# It is also LOAD-BEARING: the #193 guard reads `switch_parameter` and
# `deleted_symbols` from this record to check that the retired strategy has not
# quietly returned. Editing this record loosens that guard, so edit it
# deliberately.
RETIRED_PRIMARY_STRATEGIES = {
    "resolver-entry-lib": {
        "aka": ("first-staged lib", "entry shim", "the afec ordering"),
        "retired_in": "vibe-ic#193 (owner decision)",
        "what_it_did": (
            "Elected `res['spice_lib']` — the resolver's DECLARED entry lib, "
            "which is `spice_libs[0]` — as the deck's primary model lib, and "
            "loaded it through a per-root basename symlink farm so its bare "
            "relative `.include` / `.lib` targets resolved even when the PDK "
            "was staged across several directories."),
        "switch_parameter": "farm_dir",
        "how_it_was_selected": (
            "`custom_family_context(..., farm_dir=<dir>)` — a runtime argument, "
            "not a config value. farm_dir=None ran the device-defining rank; "
            "farm_dir set ran this one. One argument, two products."),
        "deleted_symbols": (
            "PRIMARY_BY_ENTRY_LIB", "build_lib_include_farm", "lib_farm_dir",
            "LIB_FARM_DIRNAME", "_resolve_include_closure",
            "_cross_file_include_targets"),
        "deleted_fields": ("include_farm",),
        "why_removed": (
            "(1) UNREACHABLE: an AST scan of every .py in the repo — with the "
            "positional index of `farm_dir` read from `inspect.signature`, so a "
            "positional pass could not hide — found exactly ONE production call "
            "site (analog_real_corner_sweep -> resolve_deck_context) and it "
            "passed no farm_dir. The strategy's other half was unwired too: the "
            "farm only works if ngspice also RUNS from it, and both production "
            "`_run_ngspice` call sites pass cwd=None. "
            "(2) NOT FREE TO KEEP: while both strategies were live the repo "
            "could not say which one it was running. A one-line POSITIONAL edit "
            "at that single call site switched the product's primary selection "
            "for every custom PDK and left the analog/PDK suite green. "
            "(3) MEASURED AGAINST IT: on the tracked corpus the two strategies "
            "elect a different lib in 8 of 17 configurations, and in every "
            "arrangement a simulator could tell apart, ngspice favoured the "
            "surviving strategy — including one shape where this one elects a "
            "lib whose transitive closure defines ZERO device subckts."),
        "evidence": (
            "test_issue193_custom_pdk_primary_selection_ngspice.py — the "
            "ngspice cases (A/B/C/D/E), the corpus census, and the "
            "zero-device-lib consequence are all still executed and still "
            "record what this strategy WOULD have done."),
        "how_to_reintroduce": (
            "Do NOT resurrect it as an argument. The defect was never the "
            "ranking — it was that a runtime switch made the product's policy "
            "invisible. If a farm-lineage consumer (afec) needs entry-lib "
            "primary selection: (a) restore the include-farm builder from git "
            "history at vibe-ic v1.7.69 (analog_pdk_deck_context.py, "
            "`build_lib_include_farm` + `_resolve_include_closure` + "
            "`_cross_file_include_targets`) and its tests from "
            "test_analog_pdk_lib_include_farm.py at the same revision; "
            "(b) make the strategy an EXPLICIT, declared property of the "
            "resolved PDK — carried in the resolver result and echoed in "
            "`primary_policy` and the sweep artefact — not a call-site "
            "argument, so the artefact names the policy without anyone having "
            "to read the call site; (c) wire the sweep's ngspice cwd to the "
            "farm at the same time, or the farm is inert; (d) re-state the "
            "corpus census in "
            "test_the_retired_strategy_would_still_change_the_corpus and add "
            "this strategy to the guard's expected set — the guard is designed "
            "to go red on its return, which is the point."),
    },
}


# ── lib parsing (pure) ──────────────────────────────────────────────────────

def _subckt_terminals(rest: str) -> List[str]:
    """Leading terminal-node tokens on a `.subckt` line (before the first
    `key=value` / `PARAMS:` token). MOS roles require ≥4 (d g s b)."""
    nodes: List[str] = []
    for tok in rest.split():
        if "=" in tok or tok.lower().rstrip(":") == "params":
            break
        nodes.append(tok)
    return nodes


def _assign_role(name: str) -> Optional[str]:
    """Return the single device role a subckt/model NAME maps to, or None when
    it matches zero or MORE-than-one role (ambiguous → unassigned, honest)."""
    low = name.lower()
    hits = [role for role, toks in _ROLE_TOKENS.items()
            if any(t in low for t in toks)]
    # n/p ambiguity: a name that trips BOTH nmos and pmos tokens is not a clean
    # MOS device → leave unassigned rather than guess.
    if "nmos" in hits and "pmos" in hits:
        hits = [h for h in hits if h not in ("nmos", "pmos")]
    return hits[0] if len(hits) == 1 else None


def parse_devices(text: str) -> Dict[str, Any]:
    """Parse a SPICE model-lib's `.subckt` / `.model` device definitions.

    Returns {"subckts": {name: n_terminals}, "models": {name: type}}. Pure —
    the caller supplies the text (local read or container read)."""
    subckts: Dict[str, int] = {}
    for m in _SUBCKT_RE.finditer(text or ""):
        subckts[m.group(1)] = len(_subckt_terminals(m.group(2)))
    models: Dict[str, str] = {}
    for m in _MODEL_RE.finditer(text or ""):
        models[m.group(1)] = m.group(2).lower()
    return {"subckts": subckts, "models": models,
            "geometry_units": parse_subckt_geometry_units(text)}


def _geom_default_is_metric(value: str, suffix: str) -> bool:
    """True when a `.subckt` default w=/l= states a METRIC length.

    Metric either explicitly (an SI sub-millimetre suffix: `0.35u`) or by bare
    magnitude (`3.5e-7` — no transistor is 3.5e-7 *scaled* units). A bare
    number of ordinary transistor magnitude (`0.35`, `8`) is the scaled
    (sky130) idiom."""
    suf = (suffix or "").lower()
    if suf:
        return any(suf.startswith(s) for s in _SI_SUB_MM)
    try:
        return 0.0 < float(value) < 1e-3
    except (TypeError, ValueError):
        return False


def parse_subckt_geometry_units(text: str) -> Dict[str, str]:
    """{subckt_name: "metric"|"unitless"} from each `.subckt`'s OWN declared
    default `w=`/`l=`, following `+` continuation lines (IHP declares its
    defaults on the continuation, not the header). A subckt that declares no
    w/l default at all is reported "unitless" — the historical assumption, so
    an unparseable PDK degrades to today's behaviour rather than to a guess.
    Pure; chip-AGNOSTIC (SPICE syntax only)."""
    out: Dict[str, str] = {}
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        m = _SUBCKT_RE.match(ln)
        if not m:
            continue
        decl = m.group(2)
        # absorb `+` continuation lines — the declaration's real parameter list
        for nxt in lines[i + 1:]:
            s = nxt.lstrip()
            if not s.startswith("+"):
                break
            decl += " " + s[1:]
        verdict = "unitless"
        for _key, val, suf in _GEOM_DEFAULT_RE.findall(decl):
            if _geom_default_is_metric(val, suf):
                verdict = "metric"
                break
        out[m.group(1)] = verdict
    return out


# Directives that pull another model file into a lib's parse scope. A PDK
# commonly ships a `corner<X>.lib` that DEFINES the `.lib <section>` corner
# sections and, inside each section, `.include`s the file(s) that actually
# DEFINE the device `.subckt`s (confirmed: IHP sg13g2 cornerMOSlv.lib includes
# sg13g2_moslv_mod.lib). Parsing only the corner lib's own text then sees the
# sections but NOT the devices, so the section-bearing lib (the one the deck's
# `.lib <path> <section>` line must point at) looked device-less. Following the
# includes lets a section-bearing lib self-report its transitive devices.
_INCLUDE_RE = re.compile(
    r'(?im)^\s*\.(?:include|inc)\s+["\']?([^"\'\s]+)["\']?\s*$')
# `.lib <path> <section>` INCLUDE form (a path — has a '/' or '.ext' — followed
# by a section name); distinct from the `.lib <bare-identifier>` section DEF.
_LIB_INCLUDE_RE = re.compile(
    r'(?im)^\s*\.lib\s+["\']?([^"\'\s]*[./][^"\'\s]*)["\']?\s+\S+')
# (vibe-ic#193: the bare-name include-TARGET regexes that used to sit here
# served only the retired entry-lib strategy's symlink farm — see
# RETIRED_PRIMARY_STRATEGIES. `_LIB_INCLUDE_RE` above, which the surviving
# device-rank parse uses, is a different pattern and stays.)


def _iter_includes(text: str):
    """Yield the referenced file paths of every `.include`/`.inc`/`.lib <path>
    <section>` directive in `text` (verbatim, unresolved)."""
    for m in _INCLUDE_RE.finditer(text or ""):
        yield m.group(1)
    for m in _LIB_INCLUDE_RE.finditer(text or ""):
        yield m.group(1)


def transitive_subckts(lib_path: str, text: str,
                       reader: Optional[Callable[[str], Optional[str]]],
                       _seen: Optional[set] = None, _depth: int = 0,
                       ) -> Dict[str, int]:
    """Union of `.subckt {name: n_terminals}` reachable from `text` by following
    `.include`/`.inc`/`.lib <path> <section>` directives, resolved relative to
    the including file's directory. Bounded depth + visited-set (a model-lib
    include graph is a DAG in practice). A missing `reader`, an unreadable
    include, or a cycle is skipped silently → degrades to the lib's OWN devices.
    chip-AGNOSTIC (directive syntax only, no vendor/SKU literal)."""
    subckts = dict(parse_devices(text)["subckts"])
    if reader is None or _depth >= 8:
        return subckts
    seen = _seen if _seen is not None else set()
    base = posixpath.dirname(str(lib_path))
    for inc in _iter_includes(text):
        tgt = inc if posixpath.isabs(inc) else posixpath.normpath(
            posixpath.join(base, inc))
        if tgt in seen:
            continue
        seen.add(tgt)
        itxt = reader(tgt)
        if itxt is None:
            continue
        subckts.update(transitive_subckts(tgt, itxt, reader, seen, _depth + 1))
    return subckts


def transitive_geometry_units(lib_path: str, text: str,
                              reader: Optional[Callable[[str], Optional[str]]],
                              _seen: Optional[set] = None, _depth: int = 0,
                              ) -> Dict[str, str]:
    """`transitive_subckts`'s sibling for the geometry-UNIT convention: union of
    {subckt: "metric"|"unitless"} reachable by following the same
    `.include`/`.lib <path> <section>` graph. Separate walk (not folded into
    `transitive_subckts`) so that function's return contract is unchanged.
    A foundry commonly DEFINES devices in an included file while the corner lib
    only selects sections (confirmed: IHP cornerMOShv.lib -> sg13g2_moshv_mod.lib),
    so following includes is required, not optional."""
    units = dict(parse_subckt_geometry_units(text))
    if reader is None or _depth >= 8:
        return units
    seen = _seen if _seen is not None else set()
    base = posixpath.dirname(str(lib_path))
    for inc in _iter_includes(text):
        tgt = inc if posixpath.isabs(inc) else posixpath.normpath(
            posixpath.join(base, inc))
        if tgt in seen:
            continue
        seen.add(tgt)
        itxt = reader(tgt)
        if itxt is None:
            continue
        units.update(transitive_geometry_units(tgt, itxt, reader, seen,
                                               _depth + 1))
    return units


# ── device FLAVOUR election (vibe-ic#903) ───────────────────────────────────
# A foundry family commonly ships the SAME device ROLE in several FLAVOURS: a
# plain core-voltage device, an elevated-voltage device, and special-Vt /
# isolated / native / varactor variants. Which flavour a deck binds is an
# ELECTRICAL decision. Until #903 it was decided by name ORDER alone — shortest
# name, then lexicographic — so a family whose flavour names are the same
# length elected whichever spelled first, and the electrical question was never
# asked.
#
# MEASURED, on a container-installed family shipping two MOS flavours with
# IDENTICAL corner-section vocabularies and EQUAL-LENGTH device names. One
# `.op`, Vgs = Vds = core supply, W = 1 um, L = drawn minimum, typical section:
#
#     plain core-voltage flavour     |Id| = 4.005261e-04 A
#     elevated-voltage flavour       |Id| = 1.703823e-15 A
#
# ~2.4e11 apart — and ngspice exits 0 with no error on BOTH. The wrong flavour
# does not fail, it answers. That is why name order is not an acceptable
# stand-in: nothing downstream can tell the two runs apart.
#
# The preference applied below is the one `analog_a3_netlist_emit._ROLE_PREFER`
# already STATES — "prefer a plain core-voltage device over a high-voltage /
# low-Vt / isolated variant … so the choice is auditable instead of
# alphabetical" — moved to the ELECTION site, where it decides something. In a3
# that ranking sits on the REGISTRY fallback branch, which a PARSED family never
# reaches, so the families that can actually ship a flavour split were exactly
# the ones the stated rule never ran for.
#
# WHAT THE RULE CANNOT DO — IT CANNOT PROMOTE. An ordinary-domain component and
# NO domain component at all rank EQUAL, so the rule can only push an elevated
# domain (or a special variant) DOWN. A candidate set carrying no flavour signal
# therefore elects exactly what it always did: the historical
# (shortest, lexicographic) pair is kept as the FINAL tiebreak for that reason,
# and `test_903_guard_no_flavour_signal_still_elects_shortest_then_lexicographic`
# is the paired guard that must pass on the UNFIXED program too.
#
# #903's OTHER HALF — SCOPE — IS NOW ANSWERED HERE TOO (see `VoltageDomain`).
# The election used to be CHIP-GLOBAL: `analog_a3_netlist_emit
# .resolve_pdk_context` took no block argument, so a design with an
# elevated-voltage pass path and a core-voltage core got ONE flavour for EVERY
# block. Measured on this tree before the change: two blocks of one project,
# one declaring 1.8 V and one declaring 1.2 V, both bound the same flavour.
#
# The seam that was missing was NOT a parameter — it was a domain the design
# actually states. It states one: a block's A1 `spec.json` carries its supply
# and terminal voltages with `units`, so the voltage a block's devices must
# withstand is DISCOVERABLE from the spec rather than declared a second time.
# `analog_a3_netlist_emit.block_voltage_domains` reads it off the specs the
# design already wrote and passes it down as `domain`; the election is then
# scoped to that domain. That is the existing seam WIDENED — the ranking is
# still this module's property and no call site chooses a POLICY, only which
# DOMAIN it is asking about, which is the distinction
# RETIRED_PRIMARY_STRATEGIES draws.
#
# WHAT IS STILL CHIP-GLOBAL, and is disclosed rather than pretended away: a
# design that states NO voltage anywhere has no domain to scope to, so it gets
# ONE flavour for every block exactly as before — and `device_election` still
# says so. The rule reads voltages, not intent: a block whose spec omits its
# supply is indistinguishable from a core block. And the rule still cannot
# PROMOTE — a candidate spelling neither a domain component nor a rating is
# neither demoted nor overstressed, so an elevated block cannot prefer an
# elevated flavour over it.
#
# chip-AGNOSTIC: generic device-class name COMPONENTS, the same category as
# `_ROLE_TOKENS`' nfet / pmos / nch. No vendor, SKU or node literal.

# Voltage-domain name COMPONENTS. Component-matched, NEVER substring: `hvt` is
# a threshold flavour and must not read as a high-voltage domain.
_DOMAIN_ELEVATED = ("mv", "hv", "ehv", "uhv", "xhv")
_DOMAIN_ORDINARY = ("lv",)
# Components that mark a device as something other than the plain one of its
# role (special threshold, isolated, native, varactor, ESD).
_SPECIAL_VARIANT = ("lvt", "hvt", "svt", "ulvt", "nvt", "zvt", "iso", "dss",
                    "nat", "native", "var", "varicap", "varactor", "esd",
                    "dnw", "nbl")
# A name that SPELLS a voltage rating: `01v8` -> 1.8, `g5v0d10v5` -> 5.0/10.5.
_RATING_RE = re.compile(r"(?<![0-9])(\d{1,3})v(\d{1,3})(?![0-9])")

# The basis vocabulary an election record may report. Named constants rather
# than inline strings so a consumer (and the tests) can DISCOVER the set from
# the module instead of retyping it — a hand-copied vocabulary is how two
# copies of one list each hide the other's gap.
ELECTION_BASIS_KNOWN_TABLE = "known-family-table"
ELECTION_BASIS_SOLE = "sole-candidate"
ELECTION_BASIS_FLAVOUR = "flavour-preference"
ELECTION_BASIS_NAME_ORDER = "name-order"
ELECTION_BASIS_DOMAIN = "stated-voltage-domain"

# Which candidate SET the election ran over.
ELECTION_SCOPE_KNOWN_TABLE = "known-family-table"
ELECTION_SCOPE_UNION = "cross-lib-union"
ELECTION_SCOPE_PRIMARY = "primary-lib-closure"

# How many leading components of `device_flavour_rank` are the FLAVOUR decision
# rather than the alphabetical tiebreak. Declared once, so `elect_device_roles`
# and anything holding the two flavour vocabularies to each other slice the key
# the same way and cannot drift when the key grows another component.
FLAVOUR_KEY_WIDTH = 3

# How WIDE one election's result applies — #903's second claim, in the record.
DOMAIN_SCOPE_CHIP_GLOBAL = "chip-global"
DOMAIN_SCOPE_STATED = "stated-voltage-domain"


class VoltageDomain(NamedTuple):
    """The voltage domain ONE election is being asked about.

    `volts`    — what this block's devices must WITHSTAND, in volts, as the
                 design states it. None when the design states none.
    `elevated` — True when this domain is above the LOWEST domain the design
                 declares. Carried separately because a family may split its
                 flavours by a NAME COMPONENT that spells no number at all:
                 `volts` cannot rank those, `elevated` can. A design with one
                 domain has `elevated=False` everywhere.

    A `None` domain means "the design stated nothing" and every ranking below
    is then bit-identical to the chip-global rule. chip-AGNOSTIC: volts and an
    ordering, no family, SKU or node."""
    volts: Optional[float] = None
    elevated: bool = False


def domain_is_stated(domain: Optional["VoltageDomain"]) -> bool:
    """True when a domain carries something a ranker can actually use."""
    return bool(domain is not None
                and (domain.volts is not None or domain.elevated))


def _name_components(name: str) -> List[str]:
    """`_`/non-alphanumeric-delimited components of a device name, lowercased."""
    return [c for c in re.split(r"[^a-z0-9]+", str(name).lower()) if c]


def name_voltage_domain(name: str) -> Optional[str]:
    """The voltage-domain COMPONENT a device name declares, or None when it
    declares none. Component-matched, so a threshold-flavour component (`hvt`)
    is not misread as a high-voltage domain. chip-AGNOSTIC."""
    for c in _name_components(name):
        if c in _DOMAIN_ELEVATED or c in _DOMAIN_ORDINARY:
            return c
    return None


def name_voltage_rating(name: str) -> float:
    """The HIGHEST voltage a device name SPELLS (`01v8` -> 1.8,
    `g5v0d10v5` -> 10.5), or 0.0 when it spells none — a name that claims no
    rating is treated as the plain device, never demoted by a number it does
    not carry. chip-AGNOSTIC (a spelling convention, not a family)."""
    best = 0.0
    for whole, frac in _RATING_RE.findall(str(name).lower()):
        try:
            best = max(best, float("%d.%s" % (int(whole), frac)))
        except ValueError:
            continue
    return best


def device_flavour_rank(name: str,
                        domain: Optional[VoltageDomain] = None,
                        ) -> Tuple[int, int, float, int, str]:
    """Sort key for ONE device-role candidate — LOWER is the better device FOR
    THE DOMAIN ASKED ABOUT. `(overstressed, demoted, fit, len(name), name)`.

    `domain is None` (or a domain the design never stated) is the CHIP-GLOBAL
    rule verbatim: `overstressed` is then constant 0 and `fit` is the spelled
    rating, so the ordering is exactly the `(demote, rating, len, name)` key
    this function shipped before — a design that states no domain keeps the
    same sane default, and a family with one flavour per role is untouched
    either way. The last two components are the pre-#903 rule verbatim, kept as
    the FINAL tiebreak so a candidate set carrying no flavour signal at all
    elects exactly what it always did.

    With a domain STATED, three things separate candidates before the alphabet
    ever runs:

    `overstressed` — the name says the device cannot take this domain: it
        spells a rating BELOW the stated volts, or it spells the ordinary
        domain when an elevated one was asked for. Overstressed candidates rank
        last; they are never REMOVED, so a family that offers nothing else
        still elects something and the deck still says what it bound.
    `demoted`      — special variants (isolated / special-Vt / native / ESD)
        always, and an elevated-domain component only when the domain asked for
        is NOT elevated. This is the pre-existing preference; scoping it to the
        request is the whole change.
    `fit`          — the TIGHTEST adequate rating wins, so a family spelling
        `01v8` / `03v3` binds `01v8` at 1.8 V and `03v3` at 3.3 V rather than
        always the smaller. A name that spells NO rating is UNKNOWN, not
        preferred: it ranks after every candidate whose name says it CAN take
        the domain, and ahead of one whose name says it cannot (`overstressed`
        already holds those). Measured before it worked that way: an unrated
        MOS-capacitor name outranked the correctly rated device for its role
        because "unrated sorts first" was carried over from the no-domain key,
        where it is right and here is not.

    chip-AGNOSTIC: name COMPONENTS and volts, no vendor/SKU/node literal."""
    comps = set(_name_components(name))
    special = len(comps & set(_SPECIAL_VARIANT))
    elevated_comp = bool(comps & set(_DOMAIN_ELEVATED))
    ordinary_comp = bool(comps & set(_DOMAIN_ORDINARY))
    rating = name_voltage_rating(name)
    if not domain_is_stated(domain):
        demote = (1 if elevated_comp else 0) + special
        return (0, demote, rating, len(str(name)), str(name))
    volts = domain.volts                              # type: ignore[union-attr]
    want_elevated = bool(domain.elevated)             # type: ignore[union-attr]
    over = int(bool((volts is not None and rating and rating < volts)
                    or (want_elevated and ordinary_comp)))
    demote = special + (0 if want_elevated else (1 if elevated_comp else 0))
    if volts is None:
        fit = rating
    elif not rating:
        fit = float("inf")
    elif rating >= volts:
        fit = rating - volts
    else:
        fit = volts - rating          # only reachable with over == 1
    return (over, demote, fit, len(str(name)), str(name))


def elect_device_roles(subckts: Dict[str, int],
                       required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                       domain: Optional[VoltageDomain] = None,
                       ) -> Tuple[Dict[str, str], List[str], List[str],
                                  Dict[str, Any]]:
    """`map_device_roles` plus the ELECTION RECORD (vibe-ic#903).

    Returns (device_map, unresolved_required_roles, notes, election). The
    election states, per role, WHAT was elected, WHICH RULE decided it
    (ELECTION_BASIS_*), what was rejected, which voltage domains the candidate
    set spanned, and — since #903's second half — WHICH DOMAIN was asked about
    and therefore how wide the answer is (`domain_scope`). So a deck's device
    binding is auditable from the artefact instead of re-derived from the lib
    names.

    `domain=None` elects chip-globally, exactly as before."""
    candidates: Dict[str, List[str]] = {}
    notes: List[str] = []
    for name, nterm in subckts.items():
        role = _assign_role(name)
        if role is None:
            continue
        if role in ("nmos", "pmos") and nterm < 4:
            notes.append(f"{name}: {role}-like but only {nterm} terminal(s) "
                         f"(templates need a 4-terminal d/g/s/b subckt)")
            continue
        candidates.setdefault(role, []).append(name)
    device_map: Dict[str, str] = {}
    roles_rec: Dict[str, Any] = {}
    multi_domain: List[str] = []
    stated = domain_is_stated(domain)
    for role, names in candidates.items():
        ranked = sorted(names, key=lambda n: device_flavour_rank(n, domain))
        elected = ranked[0]
        device_map[role] = elected
        if len(ranked) == 1:
            basis = ELECTION_BASIS_SOLE
        elif (device_flavour_rank(elected, domain)[:FLAVOUR_KEY_WIDTH]
              < device_flavour_rank(ranked[1], domain)[:FLAVOUR_KEY_WIDTH]):
            basis = (ELECTION_BASIS_DOMAIN if stated
                     else ELECTION_BASIS_FLAVOUR)
        else:
            # the flavour rule separated nothing — the historical pair decided.
            basis = ELECTION_BASIS_NAME_ORDER
        domains = sorted({d for d in (name_voltage_domain(n) for n in names)
                          if d})
        if len(domains) > 1:
            multi_domain.append(role)
        roles_rec[role] = {"elected": elected, "basis": basis,
                           "rejected": ranked[1:], "voltage_domains": domains}
    election: Dict[str, Any] = {
        "scope": ELECTION_SCOPE_UNION,
        "roles": roles_rec,
        "multi_domain_roles": sorted(multi_domain),
        # HOW WIDE this answer is. Present on every record, stated or not, so a
        # reader never has to infer the scope from the absence of a note.
        "domain_scope": (DOMAIN_SCOPE_STATED if stated
                         else DOMAIN_SCOPE_CHIP_GLOBAL),
        "domain": ({"volts": domain.volts, "elevated": domain.elevated}
                   if domain is not None else None),
    }
    if multi_domain and not stated:
        # #903's second half where it is STILL unfixed — a design that states
        # no voltage anywhere. The gap is a FACT about the election, not a work
        # item: refusing to emit for every multi-flavour family is a contract
        # decision the owner has not taken, so the deck is still emitted and
        # still says so.
        election["chip_global_note"] = (
            "the resolved family ships more than one VOLTAGE DOMAIN for "
            f"role(s) {sorted(multi_domain)} and ONE flavour is elected for "
            "the WHOLE design: this design states no voltage domain for its "
            "blocks, so there is nothing to scope the election to and no "
            "block can differ (vibe-ic#903 — the per-block half applies only "
            "to a design that states its domains)")
    elif multi_domain:
        election["block_domain_note"] = (
            "the resolved family ships more than one VOLTAGE DOMAIN for "
            f"role(s) {sorted(multi_domain)}; this election was scoped to the "
            f"domain the design states for THIS block "
            f"(volts={domain.volts}, elevated={domain.elevated}), so a block "
            f"stating a different domain can and does bind a different "
            f"flavour (vibe-ic#903)")
    unresolved = [r for r in required if r not in device_map]
    return device_map, unresolved, notes, election


def map_device_roles(subckts: Dict[str, int],
                     required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                     domain: Optional[VoltageDomain] = None,
                     ) -> Tuple[Dict[str, str], List[str], List[str]]:
    """Map parsed `.subckt` names → {role: device_name} via the generic role
    heuristic. A MOS role (nmos/pmos) requires a ≥4-terminal subckt (matching
    the templates' `X<inst> d g s b <subckt> w= l=` instantiation). Returns
    (device_map, unresolved_required_roles, notes).

    Deterministic pick when a role has several candidates (vibe-ic#903): the
    FLAVOUR preference first — `device_flavour_rank`, a plain core-voltage
    device over an elevated-voltage / special-Vt / isolated variant — and the
    historical shortest-name-then-lexicographic pair as the FINAL tiebreak, so
    a candidate set with no flavour signal is unchanged. `elect_device_roles`
    returns the same three values plus the per-role election record.

    `domain` (vibe-ic#903, second half) scopes the election to the voltage
    domain the design states for the block being resolved; None elects
    chip-globally as before."""
    device_map, unresolved, notes, _election = elect_device_roles(
        subckts, required, domain)
    return device_map, unresolved, notes


def parse_sections(text: str) -> List[str]:
    """Ordered, de-duplicated `.lib <section>` DEFINITION names in a model lib."""
    out: List[str] = []
    for m in _LIB_SECTION_RE.finditer(text or ""):
        s = m.group(1).lower()
        if s not in out:
            out.append(s)
    return out


def map_corner_sections(sections: List[str]
                        ) -> Tuple[Optional[str], List[Tuple[str, float]]]:
    """Map available section names → (typ_section, process_corners). typ is the
    nominal knob-sweep section; process_corners is the slow/typ/fast grid built
    ONLY from sections that actually exist (never a fabricated corner)."""
    role_hit: Dict[str, str] = {}
    for sec in sections:
        # `_`/non-alnum-delimited components, so a prefixed corner name like
        # sg13g2's `mos_tt` / `mos_ss` / `mos_ff` maps to typ/slow/fast by its
        # `tt`/`ss`/`ff` COMPONENT (not only a bare or leading token). Component
        # equality (not substring) avoids false hits like `cutt` → `tt`.
        comps = {c for c in re.split(r"[^a-z0-9]+", sec.lower()) if c}
        for role, toks in _SECTION_ROLE_TOKENS.items():
            if role in role_hit:
                continue
            if any(sec == t or sec.startswith(t) or t in comps for t in toks):
                role_hit[role] = sec
    typ = role_hit.get("typ")
    if typ is None and sections:
        typ = sections[0]                          # honest fallback: first section
        role_hit.setdefault("typ", typ)
    process: List[Tuple[str, float]] = []
    for role in ("slow", "typ", "fast"):
        sec = role_hit.get(role)
        if sec:
            process.append((sec, _SECTION_ROLE_OFFSET[role]))
    return typ, process


# ── context builders ────────────────────────────────────────────────────────

def known_family_context(selector: str) -> DeckContext:
    """The open-PDK fast path (sky130 / gf180) — keeps the sky130 regression
    bit-identical (device_map + sections + lib from the known table, no parse).

    ORGANIC #410 (analog half). An UNKNOWN selector falls back to sky130's
    template while `family` records the name that was ASKED FOR, so the
    context claims to describe a PDK whose devices and model lib it does not
    carry — the #389 misattribution, in the analog track.

    MEASURED BEFORE CHANGING ANYTHING, and the result is narrower than it
    looks: no consumer today SIMULATES with the substituted values. The one
    caller of `resolve_deck_context` (`analog_real_corner_sweep`) takes its
    own `PDK_LIB` on the `source == "known_family"` fast path, gets `None`
    for an unknown selector, and stops at "pdk lib not reachable";
    `analog_mc_yield_run` only uses `parse_sections`. So this is a LATENT
    trap for the next consumer that reads `ctx.device_map` / `ctx.model_lib`
    at face value, not a wrong simulation happening now. Saying otherwise
    would overstate it.

    CONTROL FLOW IS DELIBERATELY UNCHANGED. Marking the fallback with a
    different `source` would push unknown selectors into the caller's `else`
    branch, where `ctx.model_lib` (sky130's) WOULD be used — strictly worse
    than today's honest stop. What changes is only that the context now says
    which template it actually carries.
    """
    fam = _KNOWN_FAMILIES.get(selector, _KNOWN_FAMILIES["sky130"])
    _template_family = selector if selector in _KNOWN_FAMILIES else "sky130"
    typ, process = map_corner_sections(list(fam["corner_sections"]))
    return DeckContext(
        status="OK", source="known_family", family=selector,
        model_lib=fam["model_lib"], model_lib_includes=[fam["model_lib"]],
        corner_sections=list(fam["corner_sections"]),
        typ_section=typ, process_corners=process,
        device_map=dict(fam["device_map"]),
        # the open-PDK device templates are 4-terminal (d g s b) — no extra
        # substrate/well node injection (keeps the sky130 deck byte-identical).
        device_terminals={role: 4 for role in fam["device_map"]},
        template_family=_template_family,
        # vibe-ic#903 — no DEVICE election happens on this path either: the
        # device map is the plugin's authored table. Stated positively rather
        # than left blank, so an artefact from this path is not silent about a
        # question the other path now answers.
        device_election={
            "scope": ELECTION_SCOPE_KNOWN_TABLE,
            "roles": {role: {"elected": dev,
                             "basis": ELECTION_BASIS_KNOWN_TABLE,
                             "rejected": [],
                             "voltage_domains": (
                                 [name_voltage_domain(dev)]
                                 if name_voltage_domain(dev) else [])}
                      for role, dev in fam["device_map"].items()},
            "multi_domain_roles": [],
            # the authored table holds ONE device per role, so there is no
            # domain to scope to and nothing a block could differ on.
            "domain_scope": DOMAIN_SCOPE_CHIP_GLOBAL,
            "domain": None,
        },
        # no election happens on this path — the lib comes from the table.
        primary_policy=PRIMARY_BY_KNOWN_TABLE,
        disclosure=(
            f"known open PDK '{selector}' — device map + corner sections "
            f"from the plugin's authored template family (no lib parse)."
            if _template_family == selector else
            f"NO authored template family for '{selector}' — this context "
            f"carries the '{_template_family}' device map, corner sections "
            f"and model lib. It does NOT describe '{selector}'. A consumer "
            f"must not read these as that PDK's values (vibe-ic#410)."),
    )


def _default_reader(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def container_reader(container: str) -> Callable[[str], Optional[str]]:
    """Host read, falling back to `docker exec <container> cat <path>`.

    vibe-ic 535f2e3fb — A CONTAINER-INSTALLED PDK CANNOT BE READ FROM THE HOST.

    `resolve_deck_context` accepted a `reader` and its own docstring said the
    caller supplies "local read or container read" — but every call site left
    it defaulted, so `_default_reader` did a HOST `Path(path).read_text()`
    against paths that exist only inside the image. Measured: `/foss/pdks` is
    absent on the host and present in the container, while the resolver
    reported `source: container_installed` with 32 libs. Every lib therefore
    read as unreadable and the deck context came back empty — which surfaced
    as `NEEDS_NATIVE_TEMPLATE`, i.e. "this PDK does not ship what we need",
    when the PDK ships it and we simply never looked.

    Control, same PDK and same call, only the reader changed:

        host reader       device_map {}                       NEEDS_NATIVE_TEMPLATE
        container reader  {nmos: sg13_hv_nmos, pmos: ...}     OK, work_items=0

    WHY THE DEFECT HID: `resolve_deck_context` routes sky130/gf180 to
    `known_family_context`, which never parses a lib. Only an UNKNOWN
    container-installed family reaches the parsing path — so the two PDKs
    everything is tested against could not expose it.

    The same fallback already exists for the digital flow
    (`phase3_one_shot_runner._v1_6_604_read_text_or_container_cat`, added for
    the via-analyzer tech-LEF read). This is that fix, for the analog deck
    path.
    """
    def _read(path: str) -> Optional[str]:
        txt = _default_reader(path)
        if txt is not None:
            return txt
        if not container:
            return None
        try:
            r = subprocess.run(_ce.docker_exec_argv(container, "cat", path),
                               capture_output=True, text=True, timeout=30,
                               errors="replace")
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
        return None
    return _read


# vibe-ic#193 — the include-farm builder that served the retired entry-lib
# strategy stood here (`_cross_file_include_targets`,
# `_resolve_include_closure`, `LIB_FARM_DIRNAME`, `lib_farm_dir`,
# `build_lib_include_farm`). It is gone with the strategy it existed for:
# the farm's only effect was to redirect `primary` to the resolver's entry
# lib, so without that redirect it built symlinks nothing ever loaded. See
# RETIRED_PRIMARY_STRATEGIES for the epitaph and the restore instructions.


def _record_closure_narrowing(union_election: Dict[str, Any],
                              closure_election: Dict[str, Any],
                              closure_map: Dict[str, str]) -> Dict[str, Any]:
    """Fold the primary-lib closure re-derivation into the UNION election
    record, keeping the union one as the election of record.

    WHY THE UNION RECORD SURVIVES (vibe-ic#903). The primary lib is ranked by
    the devices the UNION election resolved, so re-deriving the map from that
    lib's closure is a CONSEQUENCE of that election, not a second one. Letting
    the narrowed record replace it was measured to erase exactly the thing the
    issue is about: the closure of a single-flavour corner lib holds ONE
    candidate per role, so every role reported `sole-candidate`, `rejected` came
    back empty, and the family's multi-voltage-domain census disappeared —
    a record that says "there was nothing to choose between" about a family that
    ships two flavours. What the narrowing CAN still do is bind a different
    device than the union did; that is recorded per role and in `closure`."""
    roles = {r: dict(rec) for r, rec in (union_election.get("roles") or
                                         {}).items() if r in closure_map}
    changed: Dict[str, Any] = {}
    for role, name in closure_map.items():
        rec = roles.get(role)
        if rec is None:
            rec = dict((closure_election.get("roles") or {}).get(role) or {})
            roles[role] = rec
        if rec.get("elected") != name:
            changed[role] = {"union_election": rec.get("elected"),
                             "primary_lib_closure": name}
            rec["elected"] = name
            rec["basis"] = ((closure_election.get("roles") or {}
                             ).get(role) or {}).get(
                                 "basis", ELECTION_BASIS_NAME_ORDER)
    out = dict(union_election)
    out["roles"] = roles
    out["multi_domain_roles"] = [r for r in
                                 (union_election.get("multi_domain_roles")
                                  or []) if r in closure_map]
    if not out["multi_domain_roles"]:
        out.pop("chip_global_note", None)
    out["closure"] = {
        "scope": ELECTION_SCOPE_PRIMARY,
        "rebound_roles": changed,
    }
    return out


def custom_family_context(res: Dict[str, Any],
                          required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                          reader: Optional[Callable[[str], Optional[str]]] = None,
                          domain: Optional[VoltageDomain] = None,
                          ) -> DeckContext:
    """Build the deck context for a RESOLVED custom / installed non-open family
    (rung 1 project_custom_pdk, or rung 2 container_installed of an unknown
    family) by PARSING its resolved model libs. Fails HONESTLY
    (NEEDS_NATIVE_TEMPLATE) when a required device role or a corner section
    cannot be resolved — never emits sky130 devices for a foreign lib.

    vibe-ic#193: the primary model lib is elected by ONE strategy, the
    device-defining rank below. There is no argument that changes that — the
    strategy this function runs is a property of the function, so the call site
    no longer decides the product's PDK policy."""
    reader = reader or _default_reader
    source = res.get("source") or "container_installed"
    family = res.get("family") or res.get("target")
    libs = list(res.get("spice_libs") or [])
    if not libs and res.get("spice_lib"):
        libs = [res["spice_lib"]]
    # rung 2 (installed) has no staged spice_libs list; point at its ngspice dir
    # top lib when present (best-effort). If nothing is readable, honest fail.
    unread: List[str] = []
    union_subckts: Dict[str, int] = {}
    union_models: Dict[str, str] = {}
    union_geom_units: Dict[str, str] = {}
    per_lib_sections: Dict[str, List[str]] = {}
    per_lib_subckts: Dict[str, Dict[str, int]] = {}
    per_lib_composed: Dict[str, List[str]] = {}
    per_lib_own_devices: Dict[str, int] = {}
    for lib in libs:
        txt = reader(lib)
        if txt is None:
            unread.append(lib)
            continue
        dev = parse_devices(txt)
        per_lib_own_devices[lib] = len(dev["subckts"])
        # Follow `.include`/`.lib <path> <section>` so a section-bearing corner
        # lib self-reports the devices it pulls in transitively (the deck's
        # `.lib <path> <section>` line loads exactly that closure). Degrades to
        # the lib's OWN devices when includes are unreadable.
        tsub = transitive_subckts(lib, txt, reader)
        union_subckts.update(tsub)
        union_models.update(dev["models"])
        union_geom_units.update(transitive_geometry_units(lib, txt, reader))
        per_lib_sections[lib] = parse_sections(txt)
        per_lib_subckts[lib] = tsub
        # cross-file COMPOSED corner sections (a foundry corner ENTRY-POINT lib
        # ships these; a device building-block sub-lib does not).
        per_lib_composed[lib] = parse_composed_corner_sections(lib, txt)

    device_map, unresolved, notes, election = elect_device_roles(
        union_subckts, required, domain)

    # ORGANIC #149 — pick the primary lib (the file the `.lib <path> <section>`
    # deck line points at) by whether it DEFINES the RESOLVED device-role
    # subckts, NOT merely by which lib ships the most `.lib <section>` corner
    # definitions. The device ROLES resolve from the UNION of all libs and can
    # live in one lib (e.g. the LV-CMOS lib) while a DIFFERENT lib (e.g. an
    # HV/LDMOS lib) has more corner sections — the old "most sections" pick then
    # loaded a corner section from a lib that does not define the instantiated
    # device subckt → ngspice `unknown subckt`. Rank readable libs by the count
    # of resolved device_map subckts they define; section count is only the
    # tiebreaker. A single readable lib is unchanged (it wins trivially); when
    # NO devices resolved, n_defines is 0 for all libs and the ranking degrades
    # to the historical section-count pick. Structural, no vendor/SKU literal.
    readable = [l for l in libs if l not in unread]
    resolved_dev_names = {v for v in device_map.values()}

    # v1.4.58 — a foundry that ships a CORNER ENTRY-POINT lib (`corner<X>.lib`)
    # whose top-level `.lib <corner>` sections CROSS-FILE-COMPOSE the process /
    # noise / passive / diode sub-sections must be picked over a device
    # building-block sub-lib: a single sub-lib section (e.g. `tt_tn`) is NOT a
    # self-contained corner (its `.subckt` needs noise-flag params + well-diode
    # subckts from OTHER sections/files), so loading it aborts ngspice with
    # `unknown subckt` / `Undefined parameter`. The entry-point lib's composed
    # section pulls the whole closure AND is the only lib whose include graph
    # carries the HSPICE-only `.malias` the ngspice normalizer strips. Rank a
    # composed-corner lib above a non-composed one (device-role coverage stays
    # the top gate; a composed lib that resolves NO device wins nothing).
    # chip-AGNOSTIC: keyed on cross-file composition structure, no PDK literal.
    #
    # The strongest signal for a corner ENTRY-POINT lib is a PURE AGGREGATOR: it
    # cross-file-composes corner sections AND defines ZERO devices in its OWN
    # text (every device comes transitively). A device building-block sub-lib
    # whose sections merely reference a passive sub-lib is composed too, but it
    # DEFINES its devices inline (own_devices > 0), so it is NOT the entry point.
    # Preferring the pure aggregator picks the `corner<X>.lib` over the device
    # sub-libs (raw or pre-translated) deterministically; the sort-order fallback
    # (base name before a `_ngspice`-suffixed variant) then favours the canonical
    # raw corner file whose closure carries the `.malias` the normalizer strips.
    def _primary_rank(lib: str) -> Tuple[int, int, int, int]:
        defined = set(per_lib_subckts.get(lib, {}))
        n_defines = len(resolved_dev_names & defined)
        n_composed = len(per_lib_composed.get(lib, []))
        own_dev = per_lib_own_devices.get(lib, 0)
        is_aggregator = 1 if (n_composed and own_dev == 0) else 0
        n_sections = len(per_lib_sections.get(lib, []))
        return (n_defines, is_aggregator, n_composed, n_sections)

    primary = None
    primary_policy = PRIMARY_NONE
    if readable:
        primary = max(readable, key=_primary_rank)
        primary_policy = PRIMARY_BY_DEVICE_RANK

    # The emitted deck loads ONE lib: `.lib <primary> <section>`. The device
    # subckts it instantiates must come from THAT lib's closure — otherwise a
    # family shipping separate LV/HV corner libs can bind a device the loaded
    # section never defines (ngspice `unknown subckt`). Re-derive device_map
    # from the primary's own (transitive) devices; keep the union map only when
    # the primary cannot cover a required role (honest fallback). A single-lib
    # family (the synthetic fixtures + rung-1 staged libs) is unchanged: primary
    # IS that lib, so its closure == the union.
    if primary:
        p_map, p_unres, p_notes, p_election = elect_device_roles(
            per_lib_subckts.get(primary, {}), required, domain)
        if not p_unres:
            device_map, unresolved, notes = p_map, p_unres, p_notes
            election = _record_closure_narrowing(election, p_election, p_map)

    # Terminal count per resolved role (from the primary's transitive subckts).
    # A foundry MOS subckt may carry a 5th (or more) substrate/well terminal the
    # 4-terminal template does not supply — the deck emitter injects the extra
    # ground ties from this map. Falls back to the union closure for a role the
    # primary does not itself define (honest — matches the device_map fallback).
    primary_subs = per_lib_subckts.get(primary, {}) if primary else {}
    device_terminals: Dict[str, int] = {}
    for role, dname in device_map.items():
        nterm = primary_subs.get(dname, union_subckts.get(dname))
        if isinstance(nterm, int):
            device_terminals[role] = nterm

    # {role: unit-convention} for the RESOLVED devices, mirroring
    # device_terminals above. A role whose subckt was never parsed is OMITTED
    # (absent -> the emitter keeps today's scaled idiom), never guessed.
    device_geometry_units: Dict[str, str] = {}
    for role, dname in device_map.items():
        u = union_geom_units.get(dname)
        if u:
            device_geometry_units[role] = u

    # vibe-ic#907 — THE DECK MUST LOAD EVERY LIB WHOSE DEVICES IT BINDS.
    #
    # The re-derivation above keeps the cross-lib UNION map whenever the primary
    # cannot cover a required role. That is the honest choice for the MAP — the
    # devices really do exist — but the deck emitted one `.lib <primary>
    # <section>` line, so a device resolved from a DIFFERENT lib was bound and
    # never defined. ngspice: `unknown subckt`. The comment directly above
    # predicted this failure; the union fallback is what reaches it.
    #
    # So: for every bound device NOT in the primary's closure, add the lib that
    # does define it. `.lib` needs a SECTION, and the split corner libs do not
    # share a corner vocabulary (a family may name them `mos_tt` in one file and
    # `res_typ` in another), so each extra lib is mapped through
    # `map_corner_sections` OVER ITS OWN sections. An unsectioned device sub-lib
    # is never loaded directly — the sectioned corner lib whose closure contains
    # it is, which is how such a family is meant to be consumed.
    #
    # SINGLE-LIB FAMILIES ARE UNCHANGED: the primary's closure is the union, so
    # nothing is ever added and the deck keeps its single `.lib` line. The
    # known-family (sky130/gf180) fast path does not run this function at all.
    def _deck_loads_for(dev_map: Dict[str, str]) -> List[Tuple[str, str]]:
        if not primary:
            return []
        loads: List[Tuple[str, str]] = []
        primary_closure = set(per_lib_subckts.get(primary, {}))
        missing = sorted({d for d in dev_map.values()
                          if d not in primary_closure})
        for dname in missing:
            # Prefer a SECTIONED lib that carries the device in its closure;
            # among those prefer the one defining the FEWEST devices in its own
            # text (the corner aggregator over a broad catch-all).
            cands = [l for l in readable
                     if l != primary
                     and dname in per_lib_subckts.get(l, {})
                     and per_lib_sections.get(l)]
            if not cands:
                continue
            cands.sort(key=lambda l: (per_lib_own_devices.get(l, 0), l))
            lib = cands[0]
            if any(lib == have for have, _ in loads):
                continue
            pool = per_lib_composed.get(lib) or per_lib_sections.get(lib) or []
            sec, _proc = map_corner_sections(pool)
            if sec:
                loads.append((lib, sec))
        return loads

    sections = per_lib_sections.get(primary, []) if primary else []
    # union sections across libs is what's "available"; primary drives the deck.
    all_sections: List[str] = []
    for l in readable:
        for s in per_lib_sections.get(l, []):
            if s not in all_sections:
                all_sections.append(s)
    # When the primary is a CORNER ENTRY-POINT lib, map typ/slow/fast over its
    # cross-file COMPOSED corner sections ONLY — never a device/noise-flag stub
    # sub-section that would abort ngspice. Otherwise (a plain sectioned sub-lib,
    # incl. the single-lib rung-1 fixtures) map over its own sections as before.
    primary_composed = per_lib_composed.get(primary, []) if primary else []
    corner_pool = primary_composed or sections or all_sections
    typ, process = map_corner_sections(corner_pool)

    work_items: List[str] = []
    if unresolved:
        found_roles = sorted(device_map)
        work_items.append(
            f"NEEDS_NATIVE_TEMPLATE: required device role(s) {unresolved} have "
            f"no template-compatible (.subckt, ≥4-terminal) device in the "
            f"resolved libs; roles resolved={found_roles}; "
            f".model-only devices present={sorted(union_models)}"
            + (f"; notes={notes}" if notes else ""))
    if not typ:
        work_items.append(
            "NEEDS_NATIVE_TEMPLATE: no `.lib <section>` corner section found in "
            "the resolved libs (a single-file, sectioned model lib is required "
            "for the `.lib <path> <section>` deck model)")
    if not primary:
        work_items.append(
            "NEEDS_NATIVE_TEMPLATE: no readable model lib among the resolved "
            "custom-PDK spice libs")
    # Unread libs BLOCK only when they left the deck unresolved. When the
    # required roles + corner section + primary ALL resolved from the READABLE
    # libs, a few unreadable AUXILIARY libs (e.g. a non-CMOS HBT/ESD model file
    # irrelevant to the nmos/pmos template — common when rung-2 lists EVERY
    # installed lib, not a curated set) are informational, not a blocker.
    unread_note = (
        f"{len(unread)} model lib(s) not readable at emit time (paths only): "
        f"{[Path(p).name for p in unread]}") if unread else ""
    if unread and work_items:
        work_items.append("NEEDS_NATIVE_TEMPLATE: " + unread_note)

    # (vibe-ic#193: an OPT-IN branch stood here that replaced `primary` with the
    # resolver's declared entry lib, loaded through a symlink farm. It was the
    # second primary-selection strategy and it is retired — see
    # RETIRED_PRIMARY_STRATEGIES. `primary` is now whatever the rank above
    # elected, on every path.)

    status = "OK" if (not work_items) else "NEEDS_NATIVE_TEMPLATE"
    composed_note = (f"; composed-corner sections={primary_composed}"
                     if primary_composed else "")
    term_note = (f"; device_terminals={device_terminals}"
                 if any(v > 4 for v in device_terminals.values()) else "")
    geom_note = (f"; device_geometry_units={device_geometry_units} "
                 f"(deck emits explicit metres, not `.option scale`)"
                 if any(v == "metric"
                        for v in device_geometry_units.values()) else "")
    # vibe-ic#193 — name the electing strategy in the human-readable disclosure
    # too, so an artefact carrying only the prose still states its policy. With
    # one strategy left this is a positive record rather than a disambiguator:
    # it is what would make a future second strategy visible immediately.
    policy_note = f" [primary elected by: {primary_policy}]"
    # vibe-ic#903 — the DEVICE election's basis belongs in the prose too, so an
    # artefact carrying only the disclosure still states why it bound what it
    # bound, and states the multi-domain fact when there is one.
    election_note = "".join(
        f" [device role '{r}' elected by: {rec['basis']}"
        + (f"; rejected={rec['rejected']}" if rec.get("rejected") else "")
        + (f"; voltage domains present={rec['voltage_domains']}"
           if len(rec.get("voltage_domains") or []) > 1 else "")
        + "]"
        for r, rec in sorted((election.get("roles") or {}).items()))
    if election.get("chip_global_note"):
        election_note += " [NOT per-block: " + election["chip_global_note"] + "]"
    elif election.get("block_domain_note"):
        election_note += " [per-block: " + election["block_domain_note"] + "]"
    disclosure = (
        f"custom PDK family '{family}' ({source}) — device map + corner "
        f"sections parsed from {len(readable)} resolved model lib(s); "
        f"devices={device_map}, sections={corner_pool}{composed_note}{term_note}{geom_note}."
        + (f" (note: {unread_note})" if unread_note else "")
        if status == "OK" else
        f"custom PDK family '{family}' ({source}) NOT natively emittable: "
        + " | ".join(work_items)) + policy_note + election_note
    return DeckContext(
        status=status, source=source, family=str(family) if family else None,
        model_lib=primary, model_lib_includes=readable,
        corner_sections=corner_pool,
        typ_section=typ, process_corners=process,
        device_map=device_map, device_terminals=device_terminals,
        device_geometry_units=device_geometry_units,
        unresolved_roles=unresolved, device_election=election,
        deck_loads=(([(primary, typ)] + _deck_loads_for(device_map))
                    if (primary and typ) else []),
        work_items=work_items, disclosure=disclosure,
        primary_policy=primary_policy)


def resolve_deck_context(pdk_selector: str,
                         res: Optional[Dict[str, Any]] = None,
                         required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                         reader: Optional[Callable[[str], Optional[str]]] = None,
                         container: str = "",
                         domain: Optional[VoltageDomain] = None,
                         ) -> DeckContext:
    """Dispatcher — the ONE entry point the deck emitter calls.

    `domain` (vibe-ic#903) is the voltage domain the DESIGN states for the
    block being resolved. It is NOT a policy switch — the ranking stays this
    module's property; the caller only says which domain it is asking about.
    None (the default, and every design that states no voltage) resolves
    chip-globally, bit-identically to before.

    * A resolver result that resolves a PROJECT-STAGED custom PDK (rung 1), or a
      CONTAINER-INSTALLED family that is NOT one of the known open PDKs (rung 2
      unknown family) → parse-driven `custom_family_context` (family-agnostic).
    * Everything else (no native custom resolution, or the known open sky130 /
      gf180 container family) → `known_family_context(pdk_selector)`, keeping the
      sky130 regression bit-identical.

    chip-AGNOSTIC; NDA-safe (paths only)."""
    # vibe-ic 535f2e3fb: THE DISPATCHER OWNS THE READER CHOICE.
    # `reader` existed and every call site left it defaulted to a HOST read,
    # so a container-installed PDK parsed as empty and reported
    # NEEDS_NATIVE_TEMPLATE — "this PDK does not ship what we need" — when it
    # ships it and we never looked. Defaulting here rather than per call site
    # is deliberate: threading an argument through every caller is exactly how
    # the seam went unused, and would leave the next caller free to
    # reintroduce it.
    if reader is None and container and res is not None:
        if (res.get("source") or "") == "container_installed":
            reader = container_reader(container)
    if res and res.get("available"):
        src = res.get("source")
        if src == "project_custom_pdk":
            return custom_family_context(res, required, reader, domain)
        if src == "container_installed":
            matched = (res.get("matched_dir") or "").lower()
            # a known open family installed in the container → fast path;
            # an UNKNOWN installed family → parse it (family-agnostic).
            if not any(k in matched for k in _KNOWN_FAMILIES):
                return custom_family_context(res, required, reader, domain)
    return known_family_context(pdk_selector)
