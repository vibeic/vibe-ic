#!/usr/bin/env python3
"""analog_netlist_pdk_check.py — deterministic gate for SPICE netlist PDK compliance

Validates that analog SPICE netlists follow correct PDK conventions:
  0. On a resolved NATIVE (rung-1/2 custom) PDK, every model include is on the
     resolved ladder. An `.include` of the in-project netlist UNDER TEST is a
     DUT include, not a model include: the models arrive through it, so it is
     legal exactly when its own include chain reaches the ladder (#1954).
  1. Model include present (.include/.lib with recognized PDK model path)
  2. Body connections correct (PMOS→VDD, NMOS→VSS/0)
  3. Device names match PDK (nfet_03v3/pfet_03v3 for GF180, etc.)
  4. KNOWN_MODELS: every X-line model token that belongs to the detected
     PDK's device-model namespace is a real device for that PDK. A token in
     the namespace but absent from the registry => UNKNOWN_PDK_MODEL (a
     stray / typo'd model name). Tokens OUTSIDE the namespace (user-defined
     subckts) are not validated — zero false positives by construction. The
     known-model set is sourced from programs/pdk_registry.json (per-PDK
     `device_models`), NOT a hardcoded literal in this file.

Self-skips when:
  - No analog/ directory, or no .sp files under it

Usage:
    python3 analog_netlist_pdk_check.py <project_dir>
    python3 analog_netlist_pdk_check.py <project_dir> --json reports/gates/analog_pdk.json

Exit codes:
    0 = PASS: at least one .sp deck was read and its PDK conventions hold
    1 = FAIL (PDK convention violation)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no .sp file
        in it, so no model include and no body connection was ever inspected.
        #521: both used to be rc 0, on 197 of the 200 tracked project roots.
        Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple
import _path_layout as _pl
import _waiver_entries as _we
import _vacuous_exit as _vx
from _analog_stub_marker import is_stub_text  # v1.6.177 (#72 P1-6)
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


GF180_MODEL_MARKERS = ("design.ngspice", "sm141064.ngspice")
SKY130_MODEL_MARKERS = ("sky130.lib.spice", "sky130A_setup")

GF180_PMOS = re.compile(r"pfet_0[36]v[03]", re.IGNORECASE)
GF180_NMOS = re.compile(r"nfet_0[36]v[03]", re.IGNORECASE)
SKY130_PMOS = re.compile(r"sky130_fd_pr__pfet", re.IGNORECASE)
SKY130_NMOS = re.compile(r"sky130_fd_pr__nfet", re.IGNORECASE)

VDD_NAMES = {"vdd", "vcc", "vpwr", "avdd", "dvdd", "supply"}
VSS_NAMES = {"vss", "gnd", "0", "vgnd", "avss", "dvss", "ground"}

DEVICE_RE = re.compile(
    r"^[Xx](\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
    re.MULTILINE,
)

INCLUDE_RE = re.compile(
    r"^\s*\.(include|lib)\s+(\S+)",
    re.MULTILINE | re.IGNORECASE,
)

# Map the short PDK token returned by _detect_pdk() to the registry entry name.
_PDK_REGISTRY_NAME = {"sky130": "sky130A", "gf180": "gf180mcuD"}

_REGISTRY_PATH = Path(__file__).resolve().parent / "pdk_registry.json"


def _load_device_model_registry() -> dict:
    """Read programs/pdk_registry.json → {short_pdk: {prefix, bare_re, models:set}}.

    Honest-skip on any IO/parse problem: returns {} so the KNOWN_MODELS check
    is silently disabled rather than emitting garbage findings. The model set
    is NEVER hardcoded here — it lives in the registry data file.
    """
    out: dict = {}
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return out
    for pdk in data.get("pdks", []):
        models = pdk.get("device_models")
        if not models:
            continue
        # find the short token that maps to this registry name
        short = next(
            (s for s, name in _PDK_REGISTRY_NAME.items() if name == pdk.get("name")),
            None,
        )
        if short is None:
            continue
        out[short] = {
            "prefix": pdk.get("device_model_prefix", ""),
            "bare_re": pdk.get("device_model_bare_re"),
            "models": {m.lower() for m in models},
        }
    return out


def _in_pdk_namespace(model: str, reg: dict) -> bool:
    """True iff `model` looks like it belongs to this PDK's device-model
    namespace (and is therefore validated against the known-model set).

    A token is in-namespace when EITHER it carries the canonical PDK prefix
    (e.g. ``sky130_fd_pr__``) OR it matches the optional bare-form regex
    (e.g. GF180 ``nfet_03v3``). Everything else (user subckt calls) is
    out-of-namespace and never flagged — this is the zero-false-positive
    guarantee.
    """
    ml = model.lower()
    prefix = (reg.get("prefix") or "").lower()
    if prefix and ml.startswith(prefix):
        return True
    bare_re = reg.get("bare_re")
    if bare_re and re.search(bare_re, ml, re.IGNORECASE):
        return True
    return False


def _check_known_models(
    text: str, rel_path: str, pdk: Optional[str], findings: List[Finding]
) -> int:
    """For the detected PDK, verify each X-line model token that belongs to
    that PDK's device-model namespace is a known device. Emit
    UNKNOWN_PDK_MODEL for a stray/typo token. Returns the error count.

    Honest-skip when PDK is unknown or the registry has no entry for it
    (returns 0, no findings) — never a vacuous pass and never a false flag.
    """
    if pdk is None:
        return 0
    registry = _load_device_model_registry()
    reg = registry.get(pdk)
    if not reg or not reg.get("models"):
        return 0

    known = reg["models"]
    errors = 0
    for m in DEVICE_RE.finditer(text):
        inst = m.group(1)
        model = m.group(6)
        if not _in_pdk_namespace(model, reg):
            continue  # user subckt or foreign token — not our concern
        if model.lower() not in known:
            line_num = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                rule="UNKNOWN_PDK_MODEL",
                severity="ERROR",
                message=(
                    f"Device X{inst} references model '{model}' which is in the "
                    f"{pdk} device-model namespace but is not a known {pdk} device "
                    f"(stray or typo'd model name). Check programs/pdk_registry.json "
                    f"device_models for the valid set."
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1
    return errors


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_netlist_pdk_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _detect_pdk(text: str) -> Optional[str]:
    for marker in GF180_MODEL_MARKERS:
        if marker in text:
            return "gf180"
    for marker in SKY130_MODEL_MARKERS:
        if marker in text:
            return "sky130"
    return None


# ── ORGANIC-20260606 #438(b): declared-PDK-target consistency ──────────────
# The audited rot: the project's input docs / L1 target one PDK family
# while every real device deck instantiates a different foundry's
# devices/models — the corner numbers, even where real, are for the
# wrong process. The DECLARED target lives in
# phase1/generated_docs/L19_CONSTRAINTS_PDK.json → fields.pdk_target.
# chip-AGNOSTIC: family-token containment, no chip-class literals.

def _declared_pdk_target(project: Path) -> Optional[str]:
    """The project's declared PDK target string, or None when absent /
    explicitly N-A (nothing concrete to compare against)."""
    l19 = project / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
    try:
        declared = json.loads(l19.read_text(errors="replace")) \
            .get("fields", {}).get("pdk_target")
    except (OSError, ValueError):
        return None
    if not isinstance(declared, str) or not declared.strip():
        return None
    if declared.strip().lower().startswith(("n/a", "na ", "none", "tbd")):
        return None
    return declared.strip()


def _pdk_mismatch_waived(project: Path) -> bool:
    """True when waivers.json documents a PDK_MISMATCH waiver with a
    rationale (the issue's documented waiver path)."""
    wpath = project / "waivers.json"
    try:
        data = json.loads(wpath.read_text(errors="replace"))
    except (OSError, ValueError):
        return False
    # #519 — via the ONE shared reader. This site already unioned both keys
    # by hand; the union now has a single definition all consumers share.
    entries = _we.entries(data)
    for w in entries:
        if not isinstance(w, dict):
            continue
        blob = " ".join(str(w.get(k, "")) for k in
                        ("rule", "ticket", "id", "reason", "rationale"))
        if "pdk_mismatch" in blob.lower().replace("-", "_") \
                and (w.get("reason") or w.get("rationale")):
            return True
    return False


def _check_model_includes(text: str, rel_path: str, findings: List[Finding]) -> bool:
    includes = INCLUDE_RE.findall(text)
    if not includes:
        findings.append(Finding(
            rule="NO_MODEL_INCLUDE",
            severity="ERROR",
            message=(
                f"No .include or .lib directive found. "
                f"SPICE netlist must include PDK device models."
            ),
            file=rel_path,
        ))
        return False
    return True


def _check_body_connections(
    text: str, rel_path: str, findings: List[Finding]
) -> int:
    errors = 0
    for m in DEVICE_RE.finditer(text):
        inst = m.group(1)
        body = m.group(5).lower()
        model = m.group(6)

        is_pmos = GF180_PMOS.search(model) or SKY130_PMOS.search(model)
        is_nmos = GF180_NMOS.search(model) or SKY130_NMOS.search(model)

        if is_pmos and body in VSS_NAMES:
            line_num = text[:m.start()].count("\n") + 1
            findings.append(Finding(
                rule="PMOS_BODY_TO_VSS",
                severity="ERROR",
                message=(
                    f"PMOS device X{inst} has body connected to '{m.group(5)}' "
                    f"(should be VDD/supply). Model: {model}"
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1

        if is_nmos and body in VDD_NAMES:
            line_num = text[:m.start()].count("\n") + 1
            findings.append(Finding(
                rule="NMOS_BODY_TO_VDD",
                severity="ERROR",
                message=(
                    f"NMOS device X{inst} has body connected to '{m.group(5)}' "
                    f"(should be VSS/GND/0). Model: {model}"
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1

    return errors


# ── ORGANIC #151 — native custom-PDK model-include recognition ──────────────
# The A3 gate historically recognised ONLY the open PDKs (sky130 / gf180): a
# netlist that includes a rung-1/2 RESOLVED native model lib was NOT accepted as
# a "PDK model include" (NO_MODEL_INCLUDE), and the authored native `.subckt`
# definition libraries (whose models are supplied by the deck that includes
# them) hard-FAILed. This block consumes the v1.4.24 resolver verdict so a
# fully-native custom-PDK project can pass A3, WITHOUT relaxing the gate for
# open-PDK / rung-3 projects. NDA-safe (basenames only); no vendor/SKU literal.

# A top-level analysis card — its presence means the netlist is a RUNNABLE deck
# (which must carry its model source), not a reusable `.subckt` DEFINITION
# library (whose models come from the deck that `.include`s it).
_ANALYSIS_CARD_RE = re.compile(
    r"(?im)^\s*\.(control|tran|ac|dc|op|meas|noise|four|disto|pz|sens|tf)\b")
_SUBCKT_DEF_RE = re.compile(r"(?im)^\s*\.subckt\b")


def _resolve_native_libset(project: Path, declared_target: Optional[str]):
    """The set of resolved-native model-lib BASENAMES for a rung-1/2 native PDK,
    or (None, None) when no native resolution applies (no target / rung 3 / a
    known open family). Basename match (not full path) so a deck that references
    the staged lib from a different mount still validates against the resolver's
    spice_libs/mc_libs set. rung-1 resolves on the local FS (no container)."""
    if not declared_target:
        return None, None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import analog_pdk_availability as _apa
    except Exception:
        return None, None
    try:
        res = _apa.resolve_pdk(declared_target, project=str(project))
    except Exception:
        return None, None
    if not res.get("available"):
        return None, None
    src = res.get("source")
    if src not in ("project_custom_pdk", "container_installed"):
        return None, None
    matched = (res.get("matched_dir") or "").lower()
    if src == "container_installed" and any(
            k in matched for k in ("sky130", "gf180")):
        return None, None            # known open family → unchanged behaviour
    libs = list(res.get("spice_libs") or []) + list(res.get("mc_libs") or [])
    if not libs:
        return None, None
    return {Path(p).name for p in libs}, src


def _is_definition_library(text: str) -> bool:
    """A reusable `.subckt` model/block library — has `.subckt` and NO top-level
    analysis card, so its device models are supplied by the deck that
    `.include`s it. For such a library a missing model include is EXPECTED, not
    a defect."""
    return (_SUBCKT_DEF_RE.search(text) is not None
            and _ANALYSIS_CARD_RE.search(text) is None)


# ── ORGANIC #1954 — the DUT include is not a model include ─────────────────
# A testbench's whole purpose is to `.include` the netlist UNDER TEST, and the
# device models arrive THROUGH that include: the block deck carries the model
# `.lib` cards, and the A4 deck composer refuses a composed deck carrying more
# than one such card — so the TB must NOT duplicate them. The out-of-ladder
# guard below judges MODEL includes; with only two categories ("a resolved
# native lib" / "an out-of-ladder model file") it had nowhere to put the DUT
# and refused the very stimulus deck A3 emits. There was no content of
# `tb_<block>.sp` that satisfied producer, composer and gate at once.
#
# The third category is decided by RESOLUTION, not by naming: an `.include`
# is a DUT include when its target resolves to a file inside the project tree
# whose OWN include chain REACHES the resolved native ladder. Resolving
# in-project is deliberately not enough — a foreign model file staged inside
# the project still never reaches the ladder and is still refused, which is
# what keeps this a no-leak guard rather than a hole in one.
# chip-AGNOSTIC: pure include-graph resolution, no chip / vendor / PDK literal.

_MAX_INCLUDE_DEPTH = 8


def _include_targets(text: str) -> List[str]:
    """Every `.include`/`.lib` target in `text`, de-quoted."""
    return [p.strip().strip('"\'') for (_kind, p) in INCLUDE_RE.findall(text)]


def _resolve_in_project(inc: str, from_dir: Path, project: Path) -> Optional[Path]:
    """The in-project file an include target names, or None.

    Resolved the way a SPICE reader would: relative to the including deck
    first, then to the project root. A target that resolves OUTSIDE the
    project tree returns None — an out-of-project path is exactly the
    out-of-ladder case this gate exists to refuse, so it can never be
    reclassified as a DUT include.
    """
    raw = (inc or "").strip().strip('"\'')
    if not raw:
        return None
    p = Path(raw)
    candidates = [p] if p.is_absolute() else [from_dir / p, project / p]
    try:
        root = project.resolve()
    except OSError:
        return None
    for cand in candidates:
        try:
            real = cand.resolve()
        except OSError:
            continue
        if not real.is_file():
            continue
        try:
            real.relative_to(root)
        except ValueError:
            continue                      # outside the project tree
        return real
    return None


def _reaches_native_ladder(sp: Path, project: Path, native_libset: Set[str],
                           seen: Set[str], depth: int = 0) -> bool:
    """True when following this netlist's include graph reaches a model lib in
    the resolved native set — i.e. the models this deck needs really are loaded
    from the staged ladder, however many files down the chain.

    Cycle-safe (`seen`, seeded by the caller with the deck being judged, so a
    TB↔DUT cycle cannot bootstrap itself into a pass) and depth-bounded. A file
    that cannot be read proves nothing and returns False — never a pass by
    default."""
    if depth > _MAX_INCLUDE_DEPTH:
        return False
    key = str(sp)
    if key in seen:
        return False
    seen.add(key)
    try:
        text = sp.read_text(errors="replace")
    except OSError:
        return False
    includes = _include_targets(text)
    if any(Path(p).name in native_libset for p in includes):
        return True
    for inc in includes:
        target = _resolve_in_project(inc, sp.parent, project)
        if target is not None and _reaches_native_ladder(
                target, project, native_libset, seen, depth + 1):
            return True
    return False


def _native_model_include_ok(text: str, rel_path: str, native_libset: Set[str],
                             findings: List[Finding], sp: Optional[Path] = None,
                             project: Optional[Path] = None) -> bool:
    """Native-PDK-aware model-include acceptance (#151, #1954). Returns True
    when the netlist carries a valid native model source, False (with a
    finding) when it FAILs:
      * an include whose basename is in the resolved native set → VALID;
      * an include that resolves to an in-project netlist whose own include
        chain reaches the resolved native set → VALID (#1954: the deck under
        test — the models arrive transitively through it);
      * no model include but a `.subckt` DEFINITION library → VALID;
      * a model include present but NONE of the above hold (out-of-ladder
        path, unresolvable path, or a resolvable path that never reaches the
        ladder) → FAIL (the no-leak guard);
      * no include and a RUNNABLE deck → FAIL (NO_MODEL_INCLUDE — a runnable
        native deck must load the staged native models)."""
    model_includes = [
        p for (_kind, p) in INCLUDE_RE.findall(text)
        if ("/" in p or "\\" in p or "." in Path(p).name)
    ]
    if model_includes:
        if any(Path(p).name in native_libset for p in model_includes):
            findings.append(Finding(
                rule="NATIVE_MODEL_INCLUDE", severity="INFO",
                message=(f"{rel_path}: native custom-PDK model include "
                         f"recognised (resolved via analog_pdk_availability)"),
                file=rel_path))
            return True
        # #1954 — is any of them the netlist UNDER TEST rather than a claimed
        # model source? Only a target that resolves in-project AND whose own
        # include chain reaches the ladder qualifies.
        if sp is not None and project is not None:
            try:
                self_key = str(sp.resolve())
            except OSError:
                self_key = str(sp)
            dut = []
            for p in model_includes:
                target = _resolve_in_project(p, sp.parent, project)
                if target is None:
                    continue
                # A FRESH visited set per include: sharing one across siblings
                # would let a branch pruned by the depth bound in an earlier
                # traversal suppress a later, shorter path to the ladder — a
                # false FAIL. Seeded with this deck so a TB↔DUT cycle still
                # cannot bootstrap itself.
                if _reaches_native_ladder(target, project, native_libset,
                                          {self_key}):
                    dut.append(Path(p).name)
            if dut:
                findings.append(Finding(
                    rule="DUT_NETLIST_INCLUDE_ACCEPTED", severity="INFO",
                    message=(f"{rel_path}: include(s) {dut} resolve to the "
                             f"in-project netlist(s) under test, whose own "
                             f"include chain reaches the resolved native PDK "
                             f"set — the models arrive through the deck under "
                             f"test, so this is not a model include (#1954)"),
                    file=rel_path))
                return True
        findings.append(Finding(
            rule="NATIVE_PDK_INCLUDE_OUT_OF_LADDER", severity="ERROR",
            message=(f"{rel_path}: model include(s) "
                     f"{[Path(p).name for p in model_includes]} are NOT in the "
                     f"resolved native PDK set, and none resolves to an "
                     f"in-project netlist whose include chain reaches it — "
                     f"out-of-ladder include. Only a resolved-native model lib "
                     f"(the staged custom-PDK spice_libs/mc_libs), or the "
                     f"in-project deck under test that itself loads one, is a "
                     f"legal include here."),
            file=rel_path))
        return False
    if _is_definition_library(text):
        findings.append(Finding(
            rule="NATIVE_SUBCKT_LIB_ACCEPTED", severity="INFO",
            message=(f"{rel_path}: native `.subckt` definition library "
                     f"accepted (models supplied by the including deck; native "
                     f"PDK resolved)"),
            file=rel_path))
        return True
    findings.append(Finding(
        rule="NO_MODEL_INCLUDE", severity="ERROR",
        message=(f"{rel_path}: no .include/.lib model source and this is a "
                 f"runnable deck — a native custom-PDK deck must load the "
                 f"staged native model lib."),
        file=rel_path))
    return False


def _analog_roots(project: Path) -> list:
    """Every analog root this audit must read.

    `_pl.analog_dir` is the CANONICAL root (`phase3/analog/`) — where the
    analog runner writes every block artefact. But `_path_layout` also splits
    the layout by phase (`phase2_analog_block_dir` == `phase2/analog/`, "A2-A4
    analog frontend") and `flow/phase1_phase2_phase3.yaml` declares A3's
    required_output as `phase2/analog/*/*.sp` — the very files this gate is
    wired to judge. Reading only `phase3/analog/` meant a project laid out
    exactly as its own flow declares (or migrated by `migrate_to_layout_p.py`)
    returned SKIP_NO_ANALOG_DIR / SKIP_NO_SP_FILES with `passed=True`: the A3
    gate of record certified the step having opened no file at all.
    chip-AGNOSTIC: pure path resolution, no chip / vendor literal."""
    roots = [_pl.analog_dir(project),
             project / "phase2/analog",
             project / "phase1/analog"]
    seen: set = set()
    out = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.is_dir():
            out.append(r)
    return out


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_roots = _analog_roots(project)
    if not analog_roots:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping netlist PDK check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_seen: set = set()
    sp_files = []
    for root in analog_roots:
        for sp in sorted(root.rglob("*.sp")):
            key = str(sp.resolve())
            if key in sp_seen:
                continue
            sp_seen.add(key)
            sp_files.append(sp)

    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES",
            severity="INFO",
            message="No .sp files under analog/; skipping netlist PDK check",
        ))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

    files_checked = 0
    files_pass = 0
    files_stub = 0   # v1.6.177 (#72 P1-6)
    total_body_errors = 0
    total_model_errors = 0
    total_pdk_mismatches = 0  # v0.2.68 (#438b)
    declared_target = _declared_pdk_target(project)
    mismatch_waived = _pdk_mismatch_waived(project)
    # ORGANIC #151 — resolve the project's native custom PDK ONCE (rung-1/2).
    # When it resolves, a netlist that includes a resolved-native model lib (or a
    # native `.subckt` definition library) is a legal model source; an
    # out-of-ladder include still FAILs. None → unchanged open-PDK / rung-3 gate.
    native_libset, native_src = _resolve_native_libset(project, declared_target)
    _pdk_undeclared_warned = False  # #451 — one named WARNING per run

    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue

        rel = str(sp.relative_to(project))
        files_checked += 1

        # v1.6.177 (#72 P1-6) — when a SPICE netlist carries the
        # deterministic-stub marker (`extraction_strategy=
        # deterministic_stub` on the first non-empty line),
        # skip the strict model-include + body-connection checks.
        # Stubs are intentionally minimal substance; failing them
        # here causes the gate to FAIL on every PASS_WITH_STUB
        # benchmark run. chip-AGNOSTIC: the marker is a structural
        # property of the artefact, never a chip-class literal.
        if is_stub_text(text):
            files_stub += 1
            files_pass += 1
            result.findings.append(Finding(
                rule="NETLIST_PDK_STUB_ACCEPTED",
                severity="INFO",
                message=(f"{rel}: deterministic-stub netlist "
                         f"accepted (PASS_WITH_STUB tier)"),
                file=rel,
            ))
            continue

        file_ok = True

        pdk = _detect_pdk(text)

        # ORGANIC #151 — model-include acceptance. For a native custom-PDK
        # project, a deck that is NOT an open-PDK deck (pdk is None) is judged
        # native-aware: a resolved-native include or a `.subckt` definition
        # library is legal; an out-of-ladder include FAILs. A deck that still
        # carries an open-PDK (sky130/gf180) include (pdk not None) falls through
        # to the unchanged presence check + the #438b PDK_MISMATCH gate below —
        # so a cross-family overlay on a native project still FAILs. Non-native
        # projects (native_libset is None) are entirely unchanged.
        if native_libset is not None and pdk is None:
            if not _native_model_include_ok(text, rel, native_libset,
                                            result.findings, sp=sp,
                                            project=project):
                file_ok = False
        else:
            if not _check_model_includes(text, rel, result.findings):
                file_ok = False

        body_errs = _check_body_connections(text, rel, result.findings)
        if body_errs > 0:
            file_ok = False
            total_body_errors += body_errs

        model_errs = _check_known_models(text, rel, pdk, result.findings)
        if model_errs > 0:
            file_ok = False
            total_model_errors += model_errs

        # #438(b) — deck PDK family vs the project's DECLARED target.
        # Mismatch = declared target is concrete AND the deck's detected
        # family token does not appear in it. Waivable with rationale.
        # ORGANIC-20260606 #451 — UNDECLARED is VISIBLE, never silent:
        # an analog deck with no L19 pdk_target gets a named WARNING so
        # the wrong-process risk surfaces instead of vacuously passing.
        if pdk and declared_target is None and not _pdk_undeclared_warned:
            _pdk_undeclared_warned = True
            result.findings.append(Finding(
                rule="PDK_TARGET_UNDECLARED",
                severity="WARNING",
                message=("decks instantiate "
                         f"{pdk} device models but L19.fields.pdk_target "
                         "is not declared — the #438b PDK-mismatch gate "
                         "cannot compare; populate L19 (Phase 1 extracts "
                         "it from the input docs since #451) or declare "
                         "the target explicitly"),
                file=rel,
            ))
        if pdk and declared_target and \
                pdk.lower() not in declared_target.lower():
            if mismatch_waived:
                result.findings.append(Finding(
                    rule="PDK_MISMATCH_WAIVED",
                    severity="WARNING",
                    message=(f"{rel}: deck instantiates {pdk} device "
                             f"models but the project declares PDK "
                             f"target '{declared_target}' — waived via "
                             f"documented PDK_MISMATCH waiver (#438b)"),
                    file=rel,
                ))
            else:
                file_ok = False
                total_pdk_mismatches += 1
                result.findings.append(Finding(
                    rule="PDK_MISMATCH",
                    severity="ERROR",
                    message=(f"{rel}: deck instantiates {pdk} device "
                             f"models but the project declares PDK "
                             f"target '{declared_target}' — corner "
                             f"numbers, even where real, are for the "
                             f"wrong process (#438b). Waivable via "
                             f"waivers.json with a PDK_MISMATCH "
                             f"rationale."),
                    file=rel,
                ))

        if file_ok:
            files_pass += 1
            result.findings.append(Finding(
                rule="NETLIST_PDK_OK",
                severity="INFO",
                message=f"{rel}: model includes present, body connections correct",
                file=rel,
            ))

    if files_checked > files_pass:
        result.passed = False

    # v1.6.177 (#72 P1-6) — surface tier in the summary so
    # flow_compliance_check / downstream readers can distinguish
    # real PASS from PASS_WITH_STUB.
    verdict_tier = "PASS"
    if result.passed and files_stub and files_stub == files_checked:
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and files_stub:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"

    result.summary = {
        "skipped": False,
        "files_checked": files_checked,
        "files_pass": files_pass,
        "files_stub": files_stub,
        "files_fail": files_checked - files_pass,
        "body_connection_errors": total_body_errors,
        "unknown_pdk_model_errors": total_model_errors,
        "declared_pdk_target": declared_target,       # #438(b)
        "pdk_mismatch_errors": total_pdk_mismatches,  # #438(b)
        "pdk_mismatch_waived": mismatch_waived,       # #438(b)
        "native_pdk_source": native_src,              # #151 (None=open/rung-3)
        "native_pdk_lib_count": (len(native_libset)
                                 if native_libset is not None else 0),
        "pass": result.passed,
        "verdict_tier": verdict_tier,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if not args.json:
        print(_vx.verdict_line("analog_netlist_pdk_check", result.passed,
                               skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
