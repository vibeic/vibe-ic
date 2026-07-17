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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    unresolved_roles: List[str] = field(default_factory=list)
    work_items: List[str] = field(default_factory=list)
    disclosure: str = ""

    def as_json(self) -> Dict[str, Any]:
        return {
            "status": self.status, "source": self.source, "family": self.family,
            "model_lib": self.model_lib,
            "model_lib_includes": self.model_lib_includes,
            "corner_sections": self.corner_sections,
            "typ_section": self.typ_section,
            "process_corners": [list(pc) for pc in self.process_corners],
            "device_map": self.device_map,
            "device_terminals": self.device_terminals,
            "unresolved_roles": self.unresolved_roles,
            "work_items": self.work_items, "disclosure": self.disclosure,
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
    return {"subckts": subckts, "models": models}


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


def map_device_roles(subckts: Dict[str, int],
                     required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                     ) -> Tuple[Dict[str, str], List[str], List[str]]:
    """Map parsed `.subckt` names → {role: device_name} via the generic role
    heuristic. A MOS role (nmos/pmos) requires a ≥4-terminal subckt (matching
    the templates' `X<inst> d g s b <subckt> w= l=` instantiation). Returns
    (device_map, unresolved_required_roles, notes). Deterministic pick when a
    role has several candidates: shortest name, then lexicographic."""
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
    for role, names in candidates.items():
        device_map[role] = sorted(names, key=lambda n: (len(n), n))[0]
    unresolved = [r for r in required if r not in device_map]
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
    bit-identical (device_map + sections + lib from the known table, no parse)."""
    fam = _KNOWN_FAMILIES.get(selector, _KNOWN_FAMILIES["sky130"])
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
        disclosure=(f"known open PDK '{selector}' — device map + corner sections "
                    f"from the plugin's authored template family (no lib parse)."),
    )


def _default_reader(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def custom_family_context(res: Dict[str, Any],
                          required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                          reader: Optional[Callable[[str], Optional[str]]] = None,
                          ) -> DeckContext:
    """Build the deck context for a RESOLVED custom / installed non-open family
    (rung 1 project_custom_pdk, or rung 2 container_installed of an unknown
    family) by PARSING its resolved model libs. Fails HONESTLY
    (NEEDS_NATIVE_TEMPLATE) when a required device role or a corner section
    cannot be resolved — never emits sky130 devices for a foreign lib."""
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
        per_lib_sections[lib] = parse_sections(txt)
        per_lib_subckts[lib] = tsub
        # cross-file COMPOSED corner sections (a foundry corner ENTRY-POINT lib
        # ships these; a device building-block sub-lib does not).
        per_lib_composed[lib] = parse_composed_corner_sections(lib, txt)

    device_map, unresolved, notes = map_device_roles(union_subckts, required)

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
    if readable:
        primary = max(readable, key=_primary_rank)

    # The emitted deck loads ONE lib: `.lib <primary> <section>`. The device
    # subckts it instantiates must come from THAT lib's closure — otherwise a
    # family shipping separate LV/HV corner libs can bind a device the loaded
    # section never defines (ngspice `unknown subckt`). Re-derive device_map
    # from the primary's own (transitive) devices; keep the union map only when
    # the primary cannot cover a required role (honest fallback). A single-lib
    # family (the synthetic fixtures + rung-1 staged libs) is unchanged: primary
    # IS that lib, so its closure == the union.
    if primary:
        p_map, p_unres, p_notes = map_device_roles(
            per_lib_subckts.get(primary, {}), required)
        if not p_unres:
            device_map, unresolved, notes = p_map, p_unres, p_notes

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

    status = "OK" if (not work_items) else "NEEDS_NATIVE_TEMPLATE"
    composed_note = (f"; composed-corner sections={primary_composed}"
                     if primary_composed else "")
    term_note = (f"; device_terminals={device_terminals}"
                 if any(v > 4 for v in device_terminals.values()) else "")
    disclosure = (
        f"custom PDK family '{family}' ({source}) — device map + corner "
        f"sections parsed from {len(readable)} resolved model lib(s); "
        f"devices={device_map}, sections={corner_pool}{composed_note}{term_note}."
        + (f" (note: {unread_note})" if unread_note else "")
        if status == "OK" else
        f"custom PDK family '{family}' ({source}) NOT natively emittable: "
        + " | ".join(work_items))
    return DeckContext(
        status=status, source=source, family=str(family) if family else None,
        model_lib=primary, model_lib_includes=readable,
        corner_sections=corner_pool,
        typ_section=typ, process_corners=process,
        device_map=device_map, device_terminals=device_terminals,
        unresolved_roles=unresolved,
        work_items=work_items, disclosure=disclosure)


def resolve_deck_context(pdk_selector: str,
                         res: Optional[Dict[str, Any]] = None,
                         required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                         reader: Optional[Callable[[str], Optional[str]]] = None,
                         ) -> DeckContext:
    """Dispatcher — the ONE entry point the deck emitter calls.

    * A resolver result that resolves a PROJECT-STAGED custom PDK (rung 1), or a
      CONTAINER-INSTALLED family that is NOT one of the known open PDKs (rung 2
      unknown family) → parse-driven `custom_family_context` (family-agnostic).
    * Everything else (no native custom resolution, or the known open sky130 /
      gf180 container family) → `known_family_context(pdk_selector)`, keeping the
      sky130 regression bit-identical.

    chip-AGNOSTIC; NDA-safe (paths only)."""
    if res and res.get("available"):
        src = res.get("source")
        if src == "project_custom_pdk":
            return custom_family_context(res, required, reader)
        if src == "container_installed":
            matched = (res.get("matched_dir") or "").lower()
            # a known open family installed in the container → fast path;
            # an UNKNOWN installed family → parse it (family-agnostic).
            if not any(k in matched for k in _KNOWN_FAMILIES):
                return custom_family_context(res, required, reader)
    return known_family_context(pdk_selector)
