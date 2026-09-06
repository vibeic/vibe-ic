#!/usr/bin/env python3
"""analog_pdk_availability.py — native PDK availability resolver / ladder
(headline analog-track honesty fix).

Answers ONE chip-AGNOSTIC question before the analog pdk-SUBSTITUTION predicate
fires: can the L19-declared tapeout target PDK be satisfied NATIVELY? If it
can, there is NO genuine substitution — the analog deck / magic / klayout /
netgen steps consume the NATIVE PDK and the substitution waiver (which defers
A3/A5-A9) does NOT apply. The substitution waiver stays ONLY for a target that
resolves on NEITHER native rung.

The 3-rung resolution ladder (all chip-AGNOSTIC, NO proprietary/NDA/SKU token
in source):
  rung 1 — PROJECT CUSTOM PDK: the project stages its own analog assets under
           `input/pdk/` (foundry SPICE model libs + sign-off SVRF decks). The
           commercial / NDA-node case (e.g. a 180 nm foundry node whose model
           libs + Calibre decks ship with the project, not in the container).
           Reuses the plugin's canonical `input/pdk/` convention (the SAME
           globs `pdk_analog_completeness_check` enforces). Consumed natively;
           deck `.lib`/`.include` point at the staged model libs, A6 DRC/LVS at
           the staged SVRF decks. Reports PATHS ONLY (NDA hygiene).
  rung 2 — CONTAINER-INSTALLED FAMILY: the target family is installed in the
           EDA container (`/foss/pdks/<family>` with libs.tech/ngspice). The
           open-PDK case: sky130A / gf180mcuD / ihp-sg13g2 / ihp-sg13cmos5l.
           Matched by normalised token containment — no family carve-out.
  rung 3 — NOT RESOLVED: neither staged nor installed → available=False → the
           honest substitution waiver (the ONLY case that still defers A-steps).

Usage:
    python3 analog_pdk_availability.py <l19_target> [--project <dir>]
        [--container vibeic-eda] [--pdks-root /foss/pdks] [--json out.json]
    exit 0 → target natively resolved (rung 1 or 2; no substitution)
    exit 1 → target NOT resolved (rung 3; genuine substitution path)
    exit 2 → could not probe (no lister / container unreachable)
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_PDKS_ROOT = "/foss/pdks"

# Monte-Carlo STATISTICAL CARD keywords — the parse-verified signal that a model
# lib actually carries statistical / mismatch distributions (vs a pure name-hint
# alias/wrapper). chip-AGNOSTIC: standard SPICE MC card idioms, no vendor/SKU
# literal. Counted as KEYWORD OCCURRENCES only (never values) — NDA-safe.
_STAT_CARD_RE = re.compile(r"(?i)\b(?:agauss|aunif|gauss|unif|mc_global)\b")
_SUBCKT_DEF_RE = re.compile(r"(?im)^\s*\.subckt\b")


def _statistical_card_count(path: str) -> int:
    """Count of Monte-Carlo statistical CARD KEYWORDS (agauss/gauss/mc_global/…)
    in a staged model lib — the parse-verified signal that the lib can actually
    resample device mismatch (vs a pure alias/wrapper with none). Reads the
    staged host path; returns 0 on any read failure. NDA-safe: keyword
    OCCURRENCE counts only, never PDK values / content."""
    try:
        txt = Path(path).read_text(errors="replace")
    except OSError:
        return 0
    return len(_STAT_CARD_RE.findall(txt))


def _mc_lib_rank_key(path: str):
    """Rank key for a Monte-Carlo model lib (Python sort ascending, so all keys
    are NEGATED to put the best first): a SELF-CONTAINED statistical lib — one
    that both carries statistical cards AND DEFINES the device `.subckt`s it
    resamples — outranks a pure param-OVERLAY lib (stat cards but no device
    definitions), which itself outranks a card-less alias/wrapper. The MC-run
    layer wraps ONE model file as its single source, so a lib that defines its
    devices can be wrapped standalone; a param-overlay whose devices live in a
    SEPARATE base lib cannot (the deck's device instantiation would be undefined
    → no spread). Card count then name break ties. Reads the staged host path
    ONCE; a card-less alias sinks to the bottom. NDA-safe: keyword-occurrence /
    structural counts only, never PDK values / content."""
    try:
        txt = Path(path).read_text(errors="replace")
    except OSError:
        return (0, 0, 0, Path(path).name)
    cards = len(_STAT_CARD_RE.findall(txt))
    defines_devices = bool(_SUBCKT_DEF_RE.search(txt))
    self_contained = 1 if (cards > 0 and defines_devices) else 0
    has_cards = 1 if cards > 0 else 0
    return (-self_contained, -has_cards, -cards, Path(path).name)

# The tech subdirs (under `<pdk>/libs.tech/`) each flow stage consumes.
_TECH_KEYS = ("ngspice", "magic", "klayout", "netgen", "openroad", "xschem")

# Non-PDK entries that may appear alongside PDK dirs under the pdks root.
_NON_PDK_ENTRIES = frozenset({"versions.txt", "ciel", "volare", ".", ".."})

_RESOLVE_CACHE: Dict[tuple, Dict[str, Any]] = {}


# ── listers ────────────────────────────────────────────────────────────────

def _local_lister(path: str) -> List[str]:
    p = Path(path)
    if not p.is_dir():
        return []
    try:
        return sorted(e.name for e in p.iterdir())
    except OSError:
        return []


def _docker_lister(container: str) -> Callable[[str], List[str]]:
    """List entries under a path INSIDE the EDA container. Filters the
    iic-osic-tools login banner (`[INFO] …`) lines the profile prints on
    stdout before the real `ls` output. Returns [] on any failure."""
    def L(path: str) -> List[str]:
        try:
            r = subprocess.run(
                ["docker", "exec", container, "bash", "-lc",
                 f"ls -1 {shlex.quote(path)} 2>/dev/null"],
                capture_output=True, text=True, timeout=60)
        except Exception:
            return []
        if r.returncode != 0:
            return []
        out = []
        for raw in (r.stdout or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("[INFO]") or line.startswith("[ERROR]"):
                continue
            out.append(line)
        return sorted(out)
    return L


# ── rung-2 model-lib discovery ─────────────────────────────────────────────
# The corner-sweep deck-context resolver (analog_pdk_deck_context) needs the
# actual ngspice model-lib FILES of an installed PDK to parse device roles +
# corner sections. Rung 1 (project-staged) populates `spice_libs` by scanning
# input/pdk/**; rung 2 (container-installed, e.g. ihp-sg13g2) previously left
# `spice_libs` UNSET, so custom_family_context had nothing to parse and every
# installed non-open family dead-ended at NEEDS_NATIVE_TEMPLATE — the whole
# reason a native sg13g2 corner sweep never ran. This enumerates the ngspice
# model libs the installed PDK ships so the resolver can parse them.
_MODEL_LIB_EXTS = (".lib", ".spice", ".scs", ".mod")


def _model_lib_candidates(lister: Callable[[str], List[str]],
                          ngspice_dir: Optional[str]) -> List[str]:
    """Enumerate the ngspice model-lib files a rung-2 installed PDK ships.

    Best-effort + chip-AGNOSTIC: scans `<ngspice_dir>` and `<ngspice_dir>/models`
    for model-lib files (`.lib`/`.spice`/`.scs`/`.mod`). Returns sorted, de-duped
    container-absolute paths (possibly `[]` — then the caller keeps the honest
    empty `spice_libs` and the deck resolver still fails NEEDS_NATIVE_TEMPLATE).
    No family/SKU literal — pure extension + directory-layout scan."""
    if not ngspice_dir:
        return []
    libs: List[str] = []
    for sub in ("", "/models"):
        d = f"{ngspice_dir.rstrip('/')}{sub}"
        for name in (lister(d) or []):
            if name.lower().endswith(_MODEL_LIB_EXTS):
                libs.append(f"{d}/{name}")
    return sorted(dict.fromkeys(libs))


# ── rung-2 SIGN-OFF DECK discovery ─────────────────────────────────────────
# THE DEFECT THIS CLOSES, MEASURED (vibe-ic#2062, lane rbadc2 then czadcfd).
# The rung-2 result carried `pdk_root` / `klayout_dir` / `netgen_dir` /
# `magic_dir` and NO `drc_deck` and NO `lvs_deck` key at all, while
# `analog_one_shot_runner._try_native_a6_pv` returns None unless one of those
# two is set. So for every project whose PDK comes from the IMAGE — which is
# every open-PDK project — A6 abandoned the native per-block PV before it named
# a tool, and the step then FAILed `A6_PV_DRC_NO_EVIDENCE` /
# `A6_PV_LVS_NO_EVIDENCE`: "the tool has not run". Only rung 1 (a project that
# stages its own `input/pdk/`) ever populated them, which is why the lanes that
# staged a PDK got a real A6 and the front door never did. Measured on
# ihp-sg13g2, same block, same container: as shipped `run_block_pv` returned
# ran=False in 0.00 s; with the image's own two decks present in the result it
# ran for 21.4 s and returned DRC 0 violations / LVS match. The decks were in
# the image the whole time.
#
# DERIVED FROM THE PDK VOLUME, NEVER A TYPED PATH. The relative sub-paths below
# are the plugin's OWN canonical deck globs (`pdk_analog_completeness_check.
# _AXES["drc_deck"] / ["lvs_deck"]`) with the project roots stripped and
# re-rooted at the installed PDK's `libs.tech` — the same convention, the same
# deliberate deepest-first order, one definition shared with rung 1. No family,
# vendor or SKU literal appears; a PDK this repo has never heard of resolves by
# the same rule as the open ones. Reports PATHS ONLY (NDA hygiene).
_RUNG2_MACRO_DRC_EXTS = (".lydrc",)
_RUNG2_MACRO_LVS_EXTS = (".lylvs",)


def _a6_runnable_suffixes() -> Dict[str, tuple]:
    """The deck extensions the CONSUMER can actually run, taken from the
    consumer itself (`analog_a6_native_pv.deck_kind` / `.lvs_deck_kind` map
    exactly these to an engine). Enumerating anything else would hand A6 a
    deck it refuses as `unknown` — naming a tool and then not running it is
    the same silent hole this closes, one step later. Falls back to the same
    literals when the consumer is not importable (it is a sibling program, so
    that is a shipping fault, not a normal path)."""
    drc = (".rule", ".svrf", ".drc")
    lvs = (".lvs", ".rule", ".svrf")
    try:
        import analog_a6_native_pv as _pv
        drc = tuple(_pv._SVRF_DECK_SUFFIXES) + tuple(
            e for e in _pv._KLAYOUT_DECK_SUFFIXES
            if e not in _RUNG2_MACRO_DRC_EXTS)
        lvs = tuple(
            e for e in _pv._KLAYOUT_LVS_SUFFIXES
            if e not in _RUNG2_MACRO_LVS_EXTS) + tuple(_pv._SVRF_DECK_SUFFIXES)
    except Exception:
        pass
    return {"drc_deck": drc, "lvs_deck": lvs}


def _axis_rel_globs(axis: str) -> List[str]:
    """`pdk_analog_completeness_check._AXES[axis]` with the project-root
    prefixes (`input/pdk`, `pdk`, …) stripped and de-duped, order preserved.
    That axis is the plugin's ONE definition of what a staged sign-off deck
    looks like; expressed relative to a PDK tree it is equally the definition
    of what an INSTALLED one looks like."""
    try:
        import pdk_analog_completeness_check as _pac
        roots = tuple(_pac._PDK_ROOTS)
        raw = tuple(_pac._AXES[axis])
    except Exception:
        # Inline fallback mirroring the canonical convention, deepest-first.
        return (["klayout/tech/drc/*.drc", "klayout/drc/*.drc", "klayout/*.drc"]
                if axis == "drc_deck" else
                ["klayout/tech/lvs/*.lvs", "klayout/lvs/*.lvs", "klayout/*.lvs"])
    out: List[str] = []
    for g in raw:
        for r in roots:
            if g.startswith(r + "/"):
                g = g[len(r) + 1:]
                break
        if g not in out:
            out.append(g)
    return out


def _deck_family_rank(name: str, matched_dir: Optional[str]) -> int:
    """0 exact / 1 same family / 2 unrelated — how strongly a deck FILE NAME
    identifies the PDK directory it was found under, by the SAME structural
    token rule `families_agree` already uses to match a target to an installed
    directory. This is load-bearing and was measured: one open PDK ships six
    files matching the deck glob in one directory, and plain alphabetical order
    puts a per-rule helper first and its sign-off deck fourth."""
    stem = re.sub(r"\.[^.]*$", "", name)
    if not matched_dir:
        return 2
    if _norm(stem) == _norm(matched_dir):
        return 0
    return 1 if families_agree(stem, matched_dir) else 2


def _rung2_deck_candidates(lister: Callable[[str], List[str]],
                           pdk_root: Optional[str],
                           matched_dir: Optional[str],
                           axis: str) -> List[str]:
    """Every sign-off deck of `axis` the installed PDK ships that A6 can run,
    RANKED best-first: family affinity, then the axis's own deepest-first
    order, then name (so the answer is deterministic). The full ranked list is
    published beside the chosen deck — a resolver that silently picks one of
    six is the next version of this same defect."""
    if not pdk_root:
        return []
    libs_tech = f"{pdk_root.rstrip('/')}/libs.tech"
    plain = _a6_runnable_suffixes()[axis]
    macro = (_RUNG2_MACRO_DRC_EXTS if axis == "drc_deck"
             else _RUNG2_MACRO_LVS_EXTS)
    # (rel-dir, suffix) pairs in axis order; the KLayout XML macro form is a
    # LOWER tier than the plain runset of the same directory — where a PDK
    # ships both, the plain runset is the one its own tooling runs.
    probes: List[tuple] = []
    dirs: List[str] = []
    for rel in _axis_rel_globs(axis):
        d, _, pat = rel.rpartition("/")
        if "*" in d or not pat.startswith("*.") or "*" in pat[1:]:
            continue                    # `**` / `*DRC*.rule`: not a plain suffix
        suf = pat[1:].lower()
        if suf not in plain:
            continue                    # the consumer has no engine for it
        probes.append((d, suf))
        if d not in dirs:
            dirs.append(d)
    for d in dirs:
        for suf in macro:
            probes.append((d, suf))
    listed: Dict[str, List[str]] = {}
    ranked: List[tuple] = []
    seen = set()
    for idx, (d, suf) in enumerate(probes):
        base = f"{libs_tech}/{d}" if d else libs_tech
        if base not in listed:
            listed[base] = lister(base) or []
        for name in listed[base]:
            if not name.lower().endswith(suf):
                continue
            path = f"{base}/{name}"
            if path in seen:
                continue
            seen.add(path)
            ranked.append((_deck_family_rank(name, matched_dir), idx, name, path))
    ranked.sort()
    return [r[3] for r in ranked]


# ── family matching ──────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def families_agree(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    """Do two PDK selector strings denote the SAME family?

    Returns True (they agree), False (they contradict), or None when the
    question cannot be asked — either side empty, or neither side carries a
    token long enough to identify a family. `None` is NOT `False`: a caller
    must not report a contradiction it could not actually observe.

    Matching is the same structural token containment `_match_installed`
    already uses against installed directory names, so a declaration and a
    flag are compared exactly the way a flag is compared to a PDK on disk:

        ihp-sg13g2 vs sg13g2   -> True   (the L19 target is the bare family)
        sky130A    vs sky130   -> True   (the installed dir carries a suffix)
        sky130A    vs sg13g2   -> False
        ""         vs sg13g2   -> None

    No family literal appears here; the rule is purely structural, so a PDK
    this repo has never heard of compares by the same rule as the open ones.
    """
    an, bn = _norm(a or ""), _norm(b or "")
    if not an or not bn:
        return None
    if an == bn:
        return True
    a_toks = [t for t in _tokens(a or "") if len(t) >= 4]
    b_toks = [t for t in _tokens(b or "") if len(t) >= 4]
    if not a_toks and len(an) >= 4:
        a_toks = [an]
    if not b_toks and len(bn) >= 4:
        b_toks = [bn]
    if not a_toks or not b_toks:
        # Nothing on one side is specific enough to name a family. Saying
        # "they contradict" here would invent a finding out of a string too
        # short to carry one.
        return None
    if any(t in bn for t in a_toks) or any(t in an for t in b_toks):
        return True
    return False


def _match_installed(target: str, installed: List[str]) -> Optional[str]:
    """Return the installed PDK dir whose name best matches the L19 target
    family token, or None. Matching is token containment on the NORMALISED
    strings: the longest target token (≥4 chars) that is a substring of an
    installed dir's normalised name scores; the highest score wins (so
    `sg13g2` prefers `ihp-sg13g2` over `ihp-sg13cmos5l`, and a generic `sg13`
    that matches both is ambiguous → require a specific hit). No family
    literal — purely structural token containment."""
    tgt_tokens = [t for t in _tokens(target) if len(t) >= 4]
    if not tgt_tokens:
        # very short tokens only (e.g. "hp") — fall back to the whole
        # normalised target, still ≥4 required below.
        tn = _norm(target)
        tgt_tokens = [tn] if len(tn) >= 4 else []
    best: Optional[tuple] = None
    for entry in installed:
        if entry in _NON_PDK_ENTRIES:
            continue
        dn = _norm(entry)
        if not dn:
            continue
        score = 0
        for t in tgt_tokens:
            if t in dn:
                score = max(score, len(t))
        # whole-target containment either direction is a strong signal.
        tn = _norm(target)
        if tn and (tn in dn or dn in tn):
            score = max(score, min(len(tn), len(dn)))
        if score >= 4:
            cand = (score, -len(dn), entry)  # prefer higher score, shorter dir
            if best is None or cand > best:
                best = cand
    return best[2] if best else None


# ── rung 1: project-staged custom PDK (the NDA commercial-node case) ────────

def _is_spice_model_lib(path: str) -> bool:
    """True when `path` is an actual SPICE/device model lib the corner sweep can
    `.lib`/`.include`, vs a HARDMACRO artefact that shares the `.lib` extension.

    The staged-PDK `spice_models` axis (shared with pdk_analog_completeness_check)
    also globs `hardmacro(s)/**/*.lef` and `**/*.lib` for macro-completeness — but
    a LEF layout abstract or a Liberty timing `.lib` is NOT a simulatable model
    lib. Treating a generated `phase3/analog/hardmacro/<blk>.lib` (Liberty) as a
    rung-1 staged PDK made resolve_pdk return a device-less custom family, which
    SHADOWED the real installed (rung-2) PDK once a sibling block's A8 hardmacro
    existed → the block's A4 corner sweep dead-ended at NEEDS_NATIVE_TEMPLATE.
    Content-probed, chip-AGNOSTIC (SPICE vs Liberty syntax, no vendor/SKU token).
    Fail-open: an unreadable `.lib` is kept (prior behaviour)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".lef":
        return False                       # LEF is never a SPICE model lib
    if ext != ".lib":
        return True                        # .scs/.cir/.sp/.va/.osdi → SPICE
    try:
        head = p.read_text(errors="replace")[:4000]
    except OSError:
        return True
    low = head.lower()
    if ".model" in low or ".subckt" in low:
        return True                        # unambiguous SPICE model lib
    if re.search(r"(?im)^\s*library\s*\(", head) or re.search(
            r"(?im)^\s*cell\s*\(", head):
        return False                       # Liberty timing lib → not SPICE
    return True                            # ambiguous → keep (fail-open)


def _resolve_project_custom_pdk(project: Path,
                                target: Optional[str]) -> Dict[str, Any]:
    """Rung 1 of the ladder — a project that STAGES its own analog PDK assets
    under `input/pdk/` consumes them NATIVELY (no substitution). This is the
    commercial / NDA-node case: the foundry SPICE model libs + sign-off SVRF
    decks ship with the project, not in the open-source container.

    Reuses the plugin's canonical analog custom-PDK convention (the SAME globs
    `pdk_analog_completeness_check` enforces) so the digital `input/pdk/`
    convention (liberty/lef + spice/calibre) extends generically to analog —
    NO NDA-specific / vendor / SKU literal is introduced. `available` is True
    when at least one SPICE model lib is staged (the minimum for a native
    analog sim); the DRC/LVS sign-off decks are reported when present so A6 can
    point the native svrfdrc / klayout-LVS path at them. Reports PATHS ONLY —
    never PDK content (NDA hygiene)."""
    spice_libs: List[str] = []
    drc_deck = lvs_deck = None
    try:
        import pdk_analog_completeness_check as _pac
        axes = _pac._AXES
        for pat in axes["spice_models"]:
            for h in sorted(project.glob(pat)):
                if h.is_file():
                    spice_libs.append(str(h))
        drc = _pac._find_first(project, axes["drc_deck"])
        lvs = _pac._find_first(project, axes["lvs_deck"])
        drc_deck = str(drc) if drc else None
        lvs_deck = str(lvs) if lvs else None
    except Exception:
        # Inline fallback mirroring the canonical convention.
        for pat in ("input/pdk/spice/**/*.lib", "input/pdk/spice/**/*.scs",
                    "input/pdk/spice/**/*.cir", "input/pdk/spice/**/*.sp",
                    "input/pdk/models/**/*.lib", "input/pdk/models/**/*.scs"):
            for h in sorted(project.glob(pat)):
                if h.is_file():
                    spice_libs.append(str(h))
    # Drop hardmacro LEF/Liberty artefacts the shared `spice_models` axis also
    # globs — only real SPICE/device model libs are simulatable rung-1 assets.
    spice_libs = [s for s in spice_libs if _is_spice_model_lib(s)]
    # MC-SECTION SLOT (ORGANIC #142 addendum): a Monte-Carlo run must load the
    # PDK's STATISTICAL / MISMATCH model libs (mc_global / mismatch / statistical
    # variants), NOT the deterministic corner overlaid with an MC switch (the
    # deterministic device subckt silently wins → sigma stays 0 — the same
    # failure shape as sky130 tt-vs-tt_mm). Surface the MC-hinted staged libs as
    # a first-class slot so the MC-run layer selects the statistical variant. The
    # degeneracy guard in analog_mc_yield_run is the family-agnostic backstop.
    # Name-hint only (chip-AGNOSTIC): mc / mismatch / statistical / stat / agauss.
    _MC_HINT = re.compile(r"(?i)(mc|mismatch|statistical|stat|agauss)")
    mc_hinted = [p for p in spice_libs if _MC_HINT.search(Path(p).name)]
    # GAP-ANALOG (verified statistical content): rank the MC-hinted libs by
    # PARSE-VERIFIED statistical content — a SELF-CONTAINED statistical lib (real
    # agauss/gauss/mc_global cards AND device `.subckt` definitions) outranks a
    # param-OVERLAY lib (cards but no device defs — the MC-run layer can't wrap
    # it standalone, the device would be undefined) which outranks a NAME-hinted
    # alias/wrapper with NO cards at all. Never rank by filename order: an
    # alphabetical `mc_libs[0]` can be the alias, which the MC-run layer would
    # `.include` for zero spread → UNSCOREABLE. Reads the staged host path and
    # counts CARD KEYWORDS / structural markers only (never values) — NDA-safe.
    mc_libs = sorted(mc_hinted, key=_mc_lib_rank_key)
    available = bool(spice_libs)
    return {
        "available": available,
        "probe_ok": True,
        "source": "project_custom_pdk" if available else None,
        "rung": 1 if available else None,
        "target": target,
        "family": _norm(target or "") or None,
        "matched_dir": None,
        "pdk_root": None,
        "spice_libs": spice_libs,
        "spice_lib": spice_libs[0] if spice_libs else None,
        "mc_libs": mc_libs,               # MC-section slot (statistical/mismatch)
        "drc_deck": drc_deck,
        "lvs_deck": lvs_deck,
        "tech_present": {"ngspice": available, "svrf_drc": bool(drc_deck),
                         "lvs": bool(lvs_deck), "mc": bool(mc_libs)},
        "reason": (
            f"project stages a custom analog PDK under input/pdk/ "
            f"({len(spice_libs)} SPICE model lib(s)"
            + (f", {len(mc_libs)} MC/mismatch lib(s)" if mc_libs else "")
            + (", + SVRF DRC deck" if drc_deck else "")
            + (", + LVS deck" if lvs_deck else "")
            + ") — native custom-PDK path applies (no substitution)"
            if available else
            "no staged analog PDK assets under input/pdk/spice or input/pdk/models"),
    }


# ── resolution ladder ──────────────────────────────────────────────────────

def resolve_pdk(target: Optional[str], project=None,
                pdks_root: str = DEFAULT_PDKS_ROOT,
                container: Optional[str] = None,
                lister: Optional[Callable[[str], List[str]]] = None,
                ) -> Dict[str, Any]:
    """Resolve how the L19 tapeout `target` PDK is satisfied — the 3-rung
    ladder (chip-AGNOSTIC, no proprietary tokens):

      rung 1 — PROJECT CUSTOM PDK: the project stages its own analog assets
               under `input/pdk/` (SPICE model libs + sign-off decks). The
               commercial / NDA-node case. Consumed NATIVELY.
      rung 2 — CONTAINER-INSTALLED FAMILY: the target family is installed in
               the EDA container (`/foss/pdks/<family>`, ngspice tech present).
               The open-PDK case (sky130A / gf180mcuD / ihp-sg13g2). Native.
      rung 3 — NOT RESOLVED → available=False → the honest substitution waiver
               (only for a target neither staged nor installed).

    Returns a dict with at least {available, probe_ok, source, rung, target,
    reason} plus rung-specific native paths.

    `available` is True only when a native path (rung 1 or 2) resolves. A
    container-less, project-less call that finds nothing → available=False,
    probe_ok=False."""
    tnorm = (target or "").strip()

    # ── rung 1: project-staged custom PDK (checked first, local-FS, cheap) ──
    #
    # vibe-ic#576 — MOVED ABOVE THE `no target` GUARD, which used to return
    # before this and made rung 1 unreachable without an L19 declaration.
    #
    # Rung 1 detects by GLOB over `input/pdk/` (the canonical axes
    # `pdk_analog_completeness_check` enforces). The target string is carried
    # into the RESULT for the record; it is not an input to the detection.
    # Measured by calling `_resolve_project_custom_pdk` directly on a fixture
    # staging exactly those globs:
    #
    #     target=None          -> available=True  rung=1
    #     target="custom_node" -> available=True  rung=1
    #
    # Identical. So a project whose assets are all on disk was being refused by
    # a guard protecting a decision its own subject does not participate in —
    # and `analog_one_shot_runner._try_native_a6_pv` then abandoned native
    # per-block PV before naming a tool.
    #
    # The guard stays for rungs 2 and 3, which genuinely need a family name to
    # match against an installed directory.
    if project is not None:
        r1 = _resolve_project_custom_pdk(Path(project), target)
        if r1["available"]:
            return r1

    if not tnorm:
        # Nothing staged AND nothing declared. Distinct reason from the
        # pre-#576 "no target": that one could not tell "no declaration" from
        # "no declaration and no assets either", and only the second is a real
        # dead end.
        return {"available": False, "probe_ok": False, "target": target,
                "family": None, "matched_dir": None, "source": None,
                "rung": None,
                "reason": "no target declared and no project-staged PDK found"}

    # ── rung 2: container-installed PDK family ──────────────────────────────
    # Cache ONLY the real docker-probe path (expensive). An injected lister
    # (tests) or local-FS probe is cheap and its identity is not a stable cache
    # key (id() can be recycled), so skip the cache for it.
    cacheable = lister is None and container is not None
    key = (tnorm, pdks_root, container)
    if cacheable and key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[key]

    if lister is None:
        if container:
            lister = _docker_lister(container)
        elif pdks_root != DEFAULT_PDKS_ROOT:
            # an explicit non-default root is a real local path (test fixture /
            # host-mounted PDK) → probe it directly.
            lister = _local_lister
        else:
            # No container, no lister, and the DEFAULT root `/foss/pdks` is a
            # CONTAINER path — probing the host FS for it would be wrong (and
            # CI-nondeterministic). Rung 2 is not probeable here → fall through
            # to substitution. chip-AGNOSTIC + CI-safe.
            res = {"available": False, "probe_ok": False, "target": target,
                   "source": None, "rung": None, "family": _norm(tnorm),
                   "matched_dir": None, "pdk_root": None, "installed": [],
                   "tech_present": {}, "reason": (
                       "rung 2 not probeable — no container/lister and the "
                       "default /foss/pdks is a container path")}
            if cacheable:
                _RESOLVE_CACHE[key] = res
            return res

    installed = lister(pdks_root)
    probe_ok = True
    if not installed:
        # An empty listing could mean "no PDKs" or "probe failed" — either way
        # we cannot affirm native availability, so we fall back to the
        # substitution path. Mark probe_ok False so callers can tell.
        probe_ok = False

    matched = _match_installed(tnorm, installed) if installed else None
    if not matched:
        res = {"available": False, "probe_ok": probe_ok, "target": target,
               "source": None, "rung": None,
               "family": _norm(tnorm), "matched_dir": None,
               "pdk_root": None, "installed": installed,
               "tech_present": {}, "reason": (
                   "target neither staged (input/pdk/) nor installed "
                   f"(/foss/pdks) — genuine substitution; installed={installed!r}"
                   if probe_ok else
                   "PDK root not listable (no container / empty) — "
                   "cannot affirm native availability")}
        if cacheable:
            _RESOLVE_CACHE[key] = res
        return res

    pdk_root = f"{pdks_root.rstrip('/')}/{matched}"
    tech_entries = lister(f"{pdk_root}/libs.tech")
    tech_present = {k: (k in tech_entries) for k in _TECH_KEYS}
    available = bool(tech_present.get("ngspice"))
    ngspice_dir = f"{pdk_root}/libs.tech/ngspice" if tech_present["ngspice"] else None
    # Wire the installed PDK's ngspice model libs so the deck-context resolver
    # can PARSE them (device roles + corner sections) — the missing piece that
    # kept every rung-2 native family at NEEDS_NATIVE_TEMPLATE.
    spice_libs = _model_lib_candidates(lister, ngspice_dir) if available else []
    # The installed PDK's OWN sign-off decks. Without these two keys A6's
    # native per-block PV is abandoned before it names a tool — see
    # `_rung2_deck_candidates`.
    klayout_present = bool(tech_present.get("klayout"))
    drc_cands = (_rung2_deck_candidates(lister, pdk_root, matched, "drc_deck")
                 if (available and klayout_present) else [])
    lvs_cands = (_rung2_deck_candidates(lister, pdk_root, matched, "lvs_deck")
                 if (available and klayout_present) else [])
    res = {
        "available": available,
        "probe_ok": probe_ok,
        "source": "container_installed" if available else None,
        "rung": 2 if available else None,
        "target": target,
        "family": _norm(tnorm),
        "matched_dir": matched,
        "pdk_root": pdk_root,
        "installed": installed,
        "tech_present": tech_present,
        "spice_libs": spice_libs,
        "spice_lib": spice_libs[0] if spice_libs else None,
        "ngspice_dir": ngspice_dir,
        "magic_dir": f"{pdk_root}/libs.tech/magic" if tech_present["magic"] else None,
        "klayout_dir": f"{pdk_root}/libs.tech/klayout" if tech_present["klayout"] else None,
        "netgen_dir": f"{pdk_root}/libs.tech/netgen" if tech_present["netgen"] else None,
        "drc_deck": drc_cands[0] if drc_cands else None,
        "lvs_deck": lvs_cands[0] if lvs_cands else None,
        "drc_deck_candidates": drc_cands,
        "lvs_deck_candidates": lvs_cands,
        "reason": (
            f"native PDK {matched!r} installed with ngspice tech"
            if available else
            f"PDK dir {matched!r} present but no ngspice tech — "
            f"not a native analog sim path"),
    }
    if cacheable:
        _RESOLVE_CACHE[key] = res
    return res


def native_available_header(res: Dict[str, Any], sim_pdk: str) -> str:
    """The structured deck-head marker written when the L19 target resolves to
    a NATIVE path (rung 1 project-custom OR rung 2 container-installed) — so the
    deck must NOT falsely disclose a substitution. Deliberately avoids the
    `pdk_substitution` / `PDK NOTE` / `disclose` / `substitut` tokens so
    flow_compliance_check's substitution-disclosure predicate does NOT
    synthesise a (now-inapplicable) deferral waiver from it. chip-AGNOSTIC;
    reports PATHS ONLY (NDA hygiene — never PDK content)."""
    src = res.get("source")
    if src == "project_custom_pdk":
        libs = res.get("spice_libs") or []
        return (
            f"* pdk_native_available: target={res.get('target')} "
            f"source=project_custom_pdk rung=1 "
            f"spice_models={libs[0] if libs else '?'} "
            f"n_model_libs={len(libs)} "
            f"drc_deck={res.get('drc_deck')} lvs_deck={res.get('lvs_deck')} "
            f"— the project STAGES its own analog PDK under input/pdk/; the "
            f"native custom-PDK path applies (no open-source-default fallback "
            f"/ no deferral).\n")
    return (
        f"* pdk_native_available: target={res.get('target')} "
        f"source=container_installed rung=2 "
        f"installed={res.get('matched_dir')} root={res.get('pdk_root')} "
        f"ngspice={res.get('ngspice_dir')} "
        f"drc_deck={res.get('drc_deck')} lvs_deck={res.get('lvs_deck')} "
        f"— the L19 target PDK is INSTALLED "
        f"in the EDA container; the native analog path applies (no "
        f"open-source-default fallback / no deferral).\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("target", help="L19 pdk_target string, e.g. 'IHP SG13G2'")
    ap.add_argument("--project", default=None,
                    help="project dir (rung 1: probe input/pdk/ staged assets)")
    ap.add_argument("--container", default=None)
    ap.add_argument("--pdks-root", default=DEFAULT_PDKS_ROOT)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    res = resolve_pdk(args.target, project=args.project,
                      pdks_root=args.pdks_root, container=args.container)
    blob = json.dumps(res, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(blob + "\n")
    print(blob)
    if not res.get("probe_ok"):
        return 2
    return 0 if res.get("available") else 1


if __name__ == "__main__":
    sys.exit(main())
