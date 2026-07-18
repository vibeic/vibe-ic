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

import hashlib
import os
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

# Corner-section role tokens. typ is the nominal section the knob sweep runs at;
# slow/fast bracket the process grid; skew_sf / skew_fs are the N/P CROSS-skew
# corners (slow-N/fast-P and fast-N/slow-P) where an OTA bias point splits — added
# to the grid ONLY when the resolved shim actually exposes a skew section (never
# fabricated). NB: the skew tokens `sf`/`fs` are matched as a section-name PREFIX
# distinct from the process `ss`/`ff` (a `sf…` section is skew, `ss…` is slow).
_SECTION_ROLE_TOKENS = {
    "slow": ("ss", "slow"),
    "typ":  ("tt", "typ", "nom", "tm"),
    "fast": ("ff", "fast"),
    "skew_sf": ("sf", "snfp", "sfnp", "snf"),   # slow-N / fast-P
    "skew_fs": ("fs", "fnsp", "fsnp", "fsn"),   # fast-N / slow-P
}
# process offsets mirror analog_real_corner_sweep.PVT_PROCESS (±3% off nominal).
# The SKEW corners carry offset None — a mixed N/P skew has NO scalar ±% model, so
# a skew corner that cannot be REALLY simulated is left un-derived (value None),
# never fabricated off the typ base.
_SECTION_ROLE_OFFSET = {"slow": -0.03, "typ": 0.0, "fast": +0.03,
                        "skew_sf": None, "skew_fs": None}

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+(\S+)\s+(.*)$")
_MODEL_RE = re.compile(r"(?im)^\s*\.model\s+(\S+)\s+(\w+)")
# section DEFINITION form: `.lib <bare-identifier>` alone (NOT the include form
# `.lib "path" section`, which carries a path/quote after `.lib`).
_LIB_SECTION_RE = re.compile(r"(?im)^\s*\.lib\s+([A-Za-z_]\w*)\s*$")
# include-FORM `.lib` line: `.lib <path-or-name> <section>` — a lib section that
# pulls in ANOTHER section/lib (TWO args after `.lib`, vs the single-arg
# DEFINITION form above). `.include <path>` is the other compose form. A lib
# carrying BOTH `.lib <section>` DEFINITIONS and these include forms is a
# COMPOSED WRAPPER (see _lib_is_composed_wrapper). Structural — no PDK-name match.
# NB: horizontal-whitespace-only ([ \t], not \s) between the two args so a
# newline cannot bridge two consecutive single-arg `.lib <section>` DEFINITION
# lines into a false "two-arg include" match — both args must be on one line.
_LIB_INCLUDE_RE = re.compile(
    r"""(?im)^[ \t]*\.lib[ \t]+(?:"[^"]*"|'[^']*'|\S+)[ \t]+\S""")
_INCLUDE_DIRECTIVE_RE = re.compile(r"(?im)^[ \t]*\.include\b")
# The FILE token pulled in by an include-FORM line: `.lib <target> <section>` or
# `.include <target>`. Used to tell a COMPOSITION shim (whose sections stitch in
# OTHER lib files) from a raw device lib (whose sections define devices inline).
_LIB_INCLUDE_TARGET_RE = re.compile(
    r"""(?im)^[ \t]*\.lib[ \t]+("[^"]*"|'[^']*'|\S+)[ \t]+\S+[ \t]*$""")
_INCLUDE_TARGET_RE = re.compile(
    r"""(?im)^[ \t]*\.include[ \t]+("[^"]*"|'[^']*'|\S+)""")
# A Monte-Carlo / statistical / alias lib name (family-agnostic tokens, no
# vendor/SKU literal). A NOMINAL corner-sweep shim must NOT fold these in — that
# is the MC-yield path's job; a wrapper that composes them is a statistical /
# aggregator index, not the nominal ngspice corner shim.
_MC_LIB_HINT_RE = re.compile(
    r"(?i)(?:(?<![a-z0-9])mc(?![a-z0-9])|mismatch|statistical|montecarlo|agauss)")
# A PASSIVE / parasitic corner section (the block that defines the well-diode /
# resistor / cap parasitic subckts an LV-CMOS device instance references). Loaded
# ALONGSIDE the LV corner so a >4-terminal device's parasitic well-diode resolves.
# Family-agnostic name tokens, no vendor/SKU literal.
_PASSIVE_SECTION_RE = re.compile(r"(?i)(?:passiv|(?:^|_)pas(?:$|_)|(?:^|_)rc(?:$|_))")


def _passive_companion(corner_section: str, sections: List[str]) -> Optional[str]:
    """The passive/parasitic corner section to load ALONGSIDE `corner_section`
    (an LV-CMOS section) so the PMOS parasitic well-diode subckt resolves. Prefers
    a passive section sharing the corner's leading process token (e.g. `tt_lv` →
    `tt_passive`); falls back to any single passive section (a shared parasitic
    block). None when the lib has no LV/passive split. chip-AGNOSTIC."""
    passives = [s for s in sections
                if _PASSIVE_SECTION_RE.search(s) and s != corner_section]
    if not passives:
        return None
    head = corner_section.split("_", 1)[0]
    for s in passives:
        if s.split("_", 1)[0] == head or s.startswith(head):
            return s
    return passives[0]


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
    # {role: terminal-count} for the resolved devices — so the deck emitter can
    # PAD a 4-terminal template instantiation to a >4-terminal commercial device
    # (e.g. a 5-terminal PMOS carrying a well/deep-nwell tie). {} for the open
    # PDKs (their devices are 4-terminal → no padding).
    device_terms: Dict[str, int] = field(default_factory=dict)
    # {corner-section: passive-companion-section} — the passive section to LOAD
    # ALONGSIDE each LV-CMOS corner section so the PMOS parasitic well-diode
    # subckt resolves (an LV-only section leaves it "unknown subckt"). {} for the
    # open PDKs / single-section libs (no LV/passive split).
    passive_sections: Dict[str, str] = field(default_factory=dict)
    unresolved_roles: List[str] = field(default_factory=list)
    work_items: List[str] = field(default_factory=list)
    disclosure: str = ""
    # {"dir", "n_linked", "collisions"} when the caller asked for an include
    # farm (see build_lib_include_farm); None when no farm was built. Counts +
    # the farm dir only — never a lib basename (NDA hygiene).
    include_farm: Optional[Dict[str, Any]] = None

    def as_json(self) -> Dict[str, Any]:
        return {
            "status": self.status, "source": self.source, "family": self.family,
            "model_lib": self.model_lib,
            "model_lib_includes": self.model_lib_includes,
            "include_farm": self.include_farm,
            "corner_sections": self.corner_sections,
            "typ_section": self.typ_section,
            "device_terms": self.device_terms,
            "passive_sections": self.passive_sections,
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


def _lib_is_composed_wrapper(text: str) -> bool:
    """Structural detector: True when a model lib is a COMPOSED CORNER WRAPPER —
    it DEFINES `.lib <section>` corner blocks whose bodies themselves pull in
    OTHER sections/libs (an include-form `.lib <path> <section>` line, or a
    `.include`). The ngspice bridge needs such a wrapper section loaded as a
    unit: it composes the prerequisite blocks (e.g. a noise-flag / temperature /
    well-diode block) BEFORE the device model section, so a bare
    `.lib <raw-lib> <corner>` that skips those prerequisites errors out. A raw
    device lib has `.lib <section>` DEFINITIONS but NO include forms → not a
    wrapper. Structural — no chip / vendor / SKU literal (never a PDK-name
    match)."""
    if not text:
        return False
    has_section_def = bool(_LIB_SECTION_RE.search(text))
    has_compose = bool(_LIB_INCLUDE_RE.search(text)) or bool(
        _INCLUDE_DIRECTIVE_RE.search(text))
    return has_section_def and has_compose


def _cross_file_include_targets(text: str, self_basename: str) -> set:
    """The set of OTHER lib-file basenames a lib pulls in via include-form lines
    (`.lib <file> <section>` / `.include <file>`), excluding a self-reference.
    A COMPOSITION shim stitches in the device model lib(s) + prerequisite libs
    this way; a raw device lib defines devices inline and pulls in nothing (or
    only self). Structural — no chip / vendor / SKU literal."""
    out: set = set()
    for rex in (_LIB_INCLUDE_TARGET_RE, _INCLUDE_TARGET_RE):
        for m in rex.finditer(text or ""):
            tgt = m.group(1).strip("\"'")
            base = Path(tgt).name
            if base and base != self_basename:
                out.add(base)
    return out


LIB_FARM_DIRNAME = ".pdk_lib_farm"


def lib_farm_dir(project: Any) -> Path:
    """The canonical per-project model-lib include farm (see
    build_lib_include_farm). One farm per project, shared by every analog block
    and by the MC-yield path, so the same staged lib is always loaded through the
    same path. Dot-prefixed and git-excluded from the inside — the SKU-bearing
    link names never enter the repo."""
    return Path(project) / "phase3" / "analog" / LIB_FARM_DIRNAME


def _resolve_include_closure(roots: List[Path], libs: List[Path]
                             ) -> Tuple[List[Path], List[str], List[str]]:
    """Walk the transitive bare-name include graph from `roots` over the staged
    `libs`. Returns (closure, ambiguous, missing) where `closure` is the ordered
    set of files really reachable, and the two lists name the UNRESOLVABLE hops
    (as target basenames, for the caller to count — never to guess with).

    Each hop is resolved the way ngspice itself would, then widened by exactly
    one deterministic step:
      1. a file of that name NEXT TO the including file wins outright (this is
         ngspice's own rule — unambiguous by construction);
      2. otherwise the staged set is searched by basename: exactly ONE distinct
         file → that one; TWO OR MORE → AMBIGUOUS, resolved for neither.
    So the closure only ever contains files a correct resolver would have loaded;
    it never picks between same-named candidates."""
    by_base: Dict[str, List[Path]] = {}
    for p in libs:
        by_base.setdefault(p.name, []).append(p)
    closure: List[Path] = []
    seen: set = set()
    ambiguous: List[str] = []
    missing: List[str] = []
    queue = list(roots)
    while queue:
        cur = queue.pop(0)
        try:
            key = str(cur.resolve())
        except OSError:
            continue
        if key in seen or not cur.is_file():
            continue
        seen.add(key)
        closure.append(cur)
        try:
            txt = cur.read_text(errors="replace")
        except OSError:
            continue
        for tgt in sorted(_cross_file_include_targets(txt, cur.name)):
            sib = cur.parent / tgt
            if sib.is_file():
                queue.append(sib)                        # rule 1: ngspice's own
                continue
            cands = {str(p.resolve()): p for p in by_base.get(tgt, [])
                     if p.is_file()}
            if len(cands) == 1:
                queue.append(next(iter(cands.values())))  # rule 2: unique
            elif len(cands) > 1:
                ambiguous.append(tgt)
            else:
                missing.append(tgt)
    return closure, ambiguous, missing


def build_lib_include_farm(libs: List[str], farm_dir: Any,
                           roots: Optional[List[str]] = None) -> Dict[str, Any]:
    """Co-locate the model libs REACHABLE from `roots` under one directory as
    SYMLINKS keyed by basename, and return
    {"dir", "map": {staged-path: farm-path}, "n_linked", "ambiguous", "missing"}.

    WHY (GAP-ANALOG, corner-include resolution): a PDK's composed corner shim
    stitches in its prerequisite / device libs by BARE RELATIVE NAME, and ngspice
    resolves a relative `.include` / `.lib` target against the directory of the
    INCLUDING FILE — never against the process cwd. When the staged libs span
    several directories, a bare include that crosses a directory boundary is
    unresolvable from ANY cwd ("Could not find library file …" → fatal exit(1) on
    every corner). Loading the entry lib through a farm whose members are all
    basename-siblings makes every hop resolve, transitively, without copying or
    rewriting a single byte of PDK content.

    Scoped to the include CLOSURE of `roots`, not to every staged lib: a PDK may
    legitimately stage two different files under one basename in different
    directories, and only one of them is reachable. Farming the whole staged set
    flat would make that name ambiguous and block an otherwise-resolvable deck.

    Cannot silently substitute a wrong lib:
      * a hop whose basename has two DISTINCT candidates and no same-directory
        winner is AMBIGUOUS — it is linked for NEITHER, so ngspice fails loudly
        rather than loading an arbitrary one;
      * a target genuinely absent from the staged set is absent from the farm too
        — ngspice still errors and the run still fails;
      * the farm holds symlinks only, so a linked lib is byte-for-byte the file
        the resolver chose.

    chip/PDK-AGNOSTIC (structural — no vendor / SKU / filename literal). NDA: the
    summary carries COUNTS and the farm dir only, never a lib basename, and the
    farm self-excludes from git so the SKU-bearing link names never enter the
    repo."""
    staged = []
    for lib in libs:
        p = Path(lib)
        try:
            if p.is_file():
                staged.append(p)
        except OSError:
            continue
    root_paths = [Path(r) for r in (roots if roots is not None else libs)]
    closure, ambiguous, missing = _resolve_include_closure(root_paths, staged)
    empty = {"dir": None, "map": {}, "n_linked": 0,
             "ambiguous": len(set(ambiguous)), "missing": len(set(missing))}
    if not closure:
        return empty
    # One farm per ROOT SET: two entry libs whose closures disagree on a basename
    # must not share a directory, or the second would silently shadow the first.
    tag = hashlib.sha256(
        "\n".join(sorted(str(p.resolve()) for p in root_paths)).encode()
    ).hexdigest()[:12]
    farm = Path(farm_dir) / tag
    try:
        farm.mkdir(parents=True, exist_ok=True)
        (Path(farm_dir) / ".gitignore").write_text("*\n")
    except OSError as exc:
        return dict(empty, error=str(exc))
    # a basename claimed by two DISTINCT files INSIDE the closure cannot be
    # represented in a flat farm — link neither, and report it as ambiguous.
    by_base: Dict[str, set] = {}
    for p in closure:
        by_base.setdefault(p.name, set()).add(str(p.resolve()))
    shadowed = {b for b, reals in by_base.items() if len(reals) > 1}
    mapping: Dict[str, str] = {}
    for p in closure:
        if p.name in shadowed:
            continue
        # link to the ABSOLUTE STAGED path (not the realpath): the container
        # already reaches the staged path today, and the PDK's own symlink chain
        # stays exactly as it was staged.
        target = str(p.absolute())
        link = farm / p.name
        try:
            if link.is_symlink():
                if os.readlink(str(link)) != target:
                    link.unlink()
                    link.symlink_to(target)
            elif link.exists():
                continue                    # a real file squats the name — leave it
            else:
                link.symlink_to(target)
        except OSError:
            continue
        mapping[str(p)] = str(link)
    return {"dir": str(farm), "map": mapping, "n_linked": len(mapping),
            "ambiguous": len(set(ambiguous) | shadowed),
            "missing": len(set(missing))}


def map_corner_sections(sections: List[str]
                        ) -> Tuple[Optional[str], List[Tuple[str, Any]]]:
    """Map available section names → (typ_section, process_corners). typ is the
    nominal knob-sweep section; process_corners is the slow/typ/fast (+ N/P skew
    when present) grid built ONLY from sections that actually exist (never a
    fabricated corner). A skew corner carries offset None (no scalar ±% model);
    it is added ONLY when the shim exposes a skew section."""
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
    process: List[Tuple[str, Any]] = []
    for role in ("slow", "typ", "fast", "skew_sf", "skew_fs"):
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
                          farm_dir: Any = None,
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
    per_lib_composed: Dict[str, bool] = {}
    per_lib_cross_targets: Dict[str, set] = {}
    for lib in libs:
        txt = reader(lib)
        if txt is None:
            unread.append(lib)
            continue
        dev = parse_devices(txt)
        union_subckts.update(dev["subckts"])
        union_models.update(dev["models"])
        per_lib_sections[lib] = parse_sections(txt)
        per_lib_subckts[lib] = dev["subckts"]
        per_lib_composed[lib] = _lib_is_composed_wrapper(txt)
        per_lib_cross_targets[lib] = _cross_file_include_targets(
            txt, Path(lib).name)

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
    #
    # GAP-ANALOG (composed ngspice wrapper): when a PDK ships BOTH a COMPOSITION
    # SHIM (a wrapper whose corner section stitches in the prerequisite blocks +
    # the device model section as a unit) AND raw device libs, PREFER the shim
    # for ngspice. A bare `.lib <raw-lib> <corner>` skips the prerequisite blocks
    # the ngspice bridge needs and errors (~142 errors); the shim composes
    # everything. The shim is identified STRUCTURALLY (no PDK-name match) as a lib
    # that is (a) a composed wrapper, (b) defines NO device subckts of its OWN
    # (a raw device lib defines them inline — even if it self-includes a
    # noiseflag/temp block, so bare `_lib_is_composed_wrapper` alone is too
    # coarse), (c) COMPOSES (cross-file includes) a device-DEFINING lib, and
    # (d) does NOT fold in Monte-Carlo / statistical / alias libs (a wrapper that
    # composes those is a statistical / aggregator index, not the nominal corner
    # shim — that content belongs to the MC-yield path). The shim flag ranks
    # ABOVE the #149 device-defining signal. When NO shim exists (e.g.
    # sky130-style bare libs, or a single raw lib), is_shim is 0 for all libs and
    # the ranking degrades EXACTLY to the historical (n_defines, n_sections) pick.
    readable = [l for l in libs if l not in unread]
    resolved_dev_names = {v for v in device_map.values()}
    # basenames of the libs that DEFINE a resolved device-role subckt — the libs
    # a composition shim must stitch in to be the ngspice corner entry point.
    definer_basenames = {
        Path(l).name for l in readable
        if resolved_dev_names & set(per_lib_subckts.get(l, {}))}

    def _is_composition_shim(lib: str) -> bool:
        if not per_lib_composed.get(lib):
            return False                                   # not a wrapper at all
        own = set(per_lib_subckts.get(lib, {}))
        if resolved_dev_names & own:
            return False                        # defines devices → raw device lib
        tgts = per_lib_cross_targets.get(lib, set())
        if not (tgts & definer_basenames):
            return False                        # composes no device-defining lib
        if any(_MC_LIB_HINT_RE.search(t) for t in tgts):
            return False                # folds in MC/stat/alias → not a nominal shim
        return True

    def _primary_rank(lib: str) -> Tuple[int, int, int]:
        is_shim = 1 if _is_composition_shim(lib) else 0
        defined = set(per_lib_subckts.get(lib, {}))
        n_defines = len(resolved_dev_names & defined)
        n_sections = len(per_lib_sections.get(lib, []))
        return (is_shim, n_defines, n_sections)

    primary = None
    if readable:
        primary = max(readable, key=_primary_rank)
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

    # {role: terminal-count} for the resolved devices (from the parsed subckt
    # terminal counts) — the deck emitter pads a 4-terminal template to a
    # >4-terminal commercial device (e.g. a 5-terminal PMOS w/ well tie).
    device_terms = {role: union_subckts.get(sub, 4)
                    for role, sub in device_map.items()}
    # {corner-section: passive-companion} — the passive section to load ALONGSIDE
    # each corner section so a >4-terminal device's parasitic well-diode resolves.
    avail_sections = sections or all_sections
    passive_map: Dict[str, str] = {}
    for sec in avail_sections:
        if _PASSIVE_SECTION_RE.search(sec):
            continue                                   # a passive section itself
        comp = _passive_companion(sec, avail_sections)
        if comp:
            passive_map[sec] = comp

    # ── include farm (GAP-ANALOG corner-include resolution) ──────────────────
    # Load the primary lib through a basename-farm so its bare relative
    # `.include` / `.lib` targets — which ngspice resolves against the INCLUDING
    # FILE's directory, so no cwd choice can help — resolve transitively even
    # when the staged libs span several directories. Opt-in: a caller that
    # passes no farm_dir (and every known open PDK, which never reaches here)
    # keeps the previous raw-path behaviour byte-identical.
    farm = None
    if farm_dir is not None and primary:
        farm = build_lib_include_farm(readable, farm_dir, roots=[primary])
        primary_composes = bool(per_lib_composed.get(primary))
        farmed_primary = (farm.get("map") or {}).get(primary)
        if farmed_primary:
            primary = farmed_primary
        if primary_composes and (farm.get("ambiguous") or farm.get("missing")):
            # A hop the primary really needs could not be resolved to ONE file.
            # Picking either candidate — or leaving it for ngspice to not find —
            # would be a guess or a late fatal; say so honestly here instead.
            work_items.append(
                "NEEDS_NATIVE_TEMPLATE: the primary model lib composes other "
                "libs by bare relative name (which ngspice resolves against the "
                "INCLUDING FILE's directory), and "
                f"{farm.get('ambiguous')} such target(s) are ambiguous across "
                f"the staged libs while {farm.get('missing')} are absent from "
                "them — refusing to guess which file is meant")
        farm = {k: v for k, v in farm.items() if k != "map"}

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
        device_map=device_map, device_terms=device_terms,
        passive_sections=passive_map, unresolved_roles=unresolved,
        work_items=work_items, disclosure=disclosure, include_farm=farm)


def resolve_deck_context(pdk_selector: str,
                         res: Optional[Dict[str, Any]] = None,
                         required: Tuple[str, ...] = _REQUIRED_ROLES_DEFAULT,
                         reader: Optional[Callable[[str], Optional[str]]] = None,
                         farm_dir: Any = None,
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
            return custom_family_context(res, required, reader, farm_dir)
        if src == "container_installed":
            matched = (res.get("matched_dir") or "").lower()
            # a known open family installed in the container → fast path;
            # an UNKNOWN installed family → parse it (family-agnostic).
            if not any(k in matched for k in _KNOWN_FAMILIES):
                return custom_family_context(res, required, reader, farm_dir)
    return known_family_context(pdk_selector)
