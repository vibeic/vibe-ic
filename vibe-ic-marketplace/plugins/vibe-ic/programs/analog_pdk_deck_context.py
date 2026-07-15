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
        for role, toks in _SECTION_ROLE_TOKENS.items():
            if role in role_hit:
                continue
            if any(sec == t or sec.startswith(t) for t in toks):
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
    for lib in libs:
        txt = reader(lib)
        if txt is None:
            unread.append(lib)
            continue
        dev = parse_devices(txt)
        union_subckts.update(dev["subckts"])
        union_models.update(dev["models"])
        per_lib_sections[lib] = parse_sections(txt)

    device_map, unresolved, notes = map_device_roles(union_subckts, required)

    # pick the primary lib: the readable staged lib that defines the MOST corner
    # sections (that is the file the `.lib <path> <section>` line points at);
    # fall back to the first readable lib.
    readable = [l for l in libs if l not in unread]
    primary = None
    if readable:
        primary = max(readable, key=lambda l: len(per_lib_sections.get(l, [])))
    sections = per_lib_sections.get(primary, []) if primary else []
    # union sections across libs is what's "available"; primary drives the deck.
    all_sections: List[str] = []
    for l in readable:
        for s in per_lib_sections.get(l, []):
            if s not in all_sections:
                all_sections.append(s)
    typ, process = map_corner_sections(sections or all_sections)

    work_items: List[str] = []
    if unread:
        work_items.append(
            f"NEEDS_NATIVE_TEMPLATE: {len(unread)} resolved model lib(s) not "
            f"readable at emit time (paths only): {[Path(p).name for p in unread]}")
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

    status = "OK" if (not work_items) else "NEEDS_NATIVE_TEMPLATE"
    disclosure = (
        f"custom PDK family '{family}' ({source}) — device map + corner "
        f"sections parsed from {len(readable)} resolved model lib(s); "
        f"devices={device_map}, sections={sections or all_sections}."
        if status == "OK" else
        f"custom PDK family '{family}' ({source}) NOT natively emittable: "
        + " | ".join(work_items))
    return DeckContext(
        status=status, source=source, family=str(family) if family else None,
        model_lib=primary, model_lib_includes=readable,
        corner_sections=sections or all_sections,
        typ_section=typ, process_corners=process,
        device_map=device_map, unresolved_roles=unresolved,
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
