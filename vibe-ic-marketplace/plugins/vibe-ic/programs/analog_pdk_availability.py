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


# ── family matching ──────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


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
    if not tnorm:
        return {"available": False, "probe_ok": False, "target": target,
                "family": None, "matched_dir": None, "source": None,
                "rung": None, "reason": "no target"}

    # ── rung 1: project-staged custom PDK (checked first, local-FS, cheap) ──
    if project is not None:
        r1 = _resolve_project_custom_pdk(Path(project), target)
        if r1["available"]:
            return r1

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
        "ngspice_dir": f"{pdk_root}/libs.tech/ngspice" if tech_present["ngspice"] else None,
        "magic_dir": f"{pdk_root}/libs.tech/magic" if tech_present["magic"] else None,
        "klayout_dir": f"{pdk_root}/libs.tech/klayout" if tech_present["klayout"] else None,
        "netgen_dir": f"{pdk_root}/libs.tech/netgen" if tech_present["netgen"] else None,
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
        f"ngspice={res.get('ngspice_dir')} — the L19 target PDK is INSTALLED "
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
