#!/usr/bin/env python3
"""analog_a3_netlist_emit.py — the A3 netlist PRODUCER that was missing.

WHAT WAS BROKEN — and it is sharper than "a file is absent"
===========================================================
`programs/` ships FOUR netlist checkers —
`analog_netlist_connectivity_check`, `analog_netlist_include_order_check`,
`analog_netlist_path_lint`, `analog_netlist_pdk_check` — and NO program that
generates a netlist. A3 was skill-only, so the runner correctly WAIVED it and
the checkers validated a file nothing wrote.

They were not idle, though. On a real run they examined the 126 flat corner
decks `analog_real_corner_sweep` leaves behind, found `files_with_subckt: 0`,
and printed PASS on all four. So the sign-off surface was green over a tree
containing zero analog block netlists.

WHAT THIS PROGRAM DOES
======================
It renders SPICE from the A2 topology IR — and it has **no per-type netlist
template of its own**. `analog_a2_topology_emit.LIBRARY` holds the circuit
classes; this program is a generic IR -> SPICE renderer plus a PDK binder plus
a verifier. That separation is deliberate: a producer that carried a
per-block-type deck table would be the thing being replaced, one directory
over. `analog_real_corner_sweep.T[...]` is that table, and it is why the
analog headline of a whole run was a self-test of the plugin's own template
library.

    phase3/analog/<block>/topology.json  (A2 IR — required)
    phase3/analog/<block>/spec.json      (A1 spec — REQUIRED, see below)
        -> phase3/analog/<block>/<block>.sp        the declared A3 artefact
           phase3/analog/<block>/tb_<block>.sp     its stimulus
           phase3/analog/<block>/netlist_provenance.json

THE CONTROL THAT STOPS THIS BECOMING A FANCIER TEMPLATE TABLE
=============================================================
**A block with no extractable spec gets no netlist.** If `spec.json` is
absent, this program writes `netlist_gap.json` with status
`NO_SPEC_NO_NETLIST` and emits nothing — even though the topology library
could render a perfectly valid `.sp` for the block's circuit class from the
class alone. That netlist would be a template with the design's block name
substituted into it, which is the exact defect this round exists to remove:
it would pass all five gates, it would simulate, and every number it produced
would be about the template.

The design content that DOES enter the netlist is recorded, per field, in the
provenance: which device parameters were solved against a bound spec value
(`spec_bound_params`) and which are library nominals
(`library_nominal_params`). For most classes the honest answer today is that
the structure is design-derived and the geometry is not — so the artefact says
that, and hands sizing to skill `analog-sizing`, rather than letting a reader
assume a simulated netlist was also a sized one.

SELF-VERIFICATION BEFORE THE ARTEFACT IS DECLARED
=================================================
An emitted `.sp` is put through the four netlist checkers AND the A3 gate, in
an isolated staging project so the verdict is about THIS file and not about
whatever else the run has left in the tree. A file that fails any of them is
DELETED and replaced by `netlist_gap.json` carrying the findings — a netlist
that cannot pass the checks that exist is worse than an absent one, because
the absent one is honestly WAIVED.

With `--verify-sim` the testbench is additionally run through ngspice in the
EDA container. Non-convergence deletes the artefact. An UNREACHABLE container
does not: that is a capability gap, not a netlist defect, and it is recorded
as `simulation_verified: false` /
`simulation_status: NOT_VERIFIED_NO_SIMULATOR` in both the sidecar and the
`.sp` header, so nobody can read an unsimulated deck as a simulated one.

Netlist STYLE RULES, each forced by a measured failure
======================================================
  * Passives are instantiated as PDK subcircuits with their full terminal
    list (a 3-terminal resistor, not an `R` card). `analog_netlist_
    connectivity_check._device_nets` parses only `X` cards, so an `R` card
    is invisible to it and the feedback node it terminates was measured to
    raise a false `FLOATING_NODE: internal net 'vfb' touched by only 1
    device pin`.
  * That blind spot is GONE — `_device_nets` now parses a two-net device —
    and the pre-check below reads the floor out of
    `analog_netlist_connectivity_check.MIN_DEVICE_NETS` rather than holding
    its own copy. MEASURED, and the reason the constant is imported: the
    checker was fixed and this file was not, so its pre-check refused a
    switched-capacitor netlist (a summing node reached by a transistor gate
    and two capacitor plates) that the checker itself accepts. A rule
    written down twice gets fixed once.
  * PMOS bodies tie to the positive rail and NMOS bodies to ground
    (`PMOS_BODY_TO_VSS` / `NMOS_BODY_TO_VDD`).
  * Every model token must be in `programs/pdk_registry.json#device_models`
    (`UNKNOWN_PDK_MODEL`), and absolute includes must live under the PDK root
    (`NON_WHITELISTED_ABSOLUTE_PATH`).

RC CONTRACT
===========
    rc 0  at least one selected block produced a verified `<block>.sp`
          (or already carried one this producer must not overwrite).
    rc 1  the inputs themselves are unusable (no project dir / no block list).
    rc 2  no selected block produced a netlist. `netlist_gap.json` written per
          block naming WHY; hand off to skill `analog-netlist-gen`.

chip-AGNOSTIC: circuit structure comes from the A2 IR, device names from the
resolved PDK, numbers from the A1 spec. No chip, PDK SKU, vendor or part
number appears below.

Usage:
    python3 analog_a3_netlist_emit.py <project> [--block NAME] [--pdk sky130]
            [--container vibeic-eda] [--verify-sim] [--json OUT]
"""
from __future__ import annotations

import argparse
import ast as _ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _analog_producer_common as _pc  # noqa: E402
# The vocabulary this producer WRITES is defined once, beside the gates that
# certify on it. This program decides which token to write; whenever it READS
# one back — to count its own records for the run report — it classifies
# through the shared site, because a raw `==` here is free to drift from the
# whitelist the gate uses and then the run report and the gate disagree about
# a netlist neither of them has to re-read.
import _analog_a_check_common as _acc  # noqa: E402
# The per-PDK CURATED generic-role -> foundry-model table lives in
# `pdk_registry.json#device_map` and is read through its own reader/validator
# rather than off `family_entry` here, so the map and its legal-token set stay
# checked in ONE place (`pdk_device_map.validate`). Imported unconditionally:
# a broken reader must break this producer loudly, not silently drop back to
# the substring heuristic and bind a role by name order.
import pdk_device_map as _pdm  # noqa: E402
# The FLOOR the connectivity checker applies, read from the checker rather
# than restated here — see `_validate_ir`.
import analog_netlist_connectivity_check as _conncheck  # noqa: E402
# The A1 spec-row reading rule, owned by A2 — see `spec_values`.
import analog_a2_topology_emit as _a2  # noqa: E402
import pdk_analog_device_params as _pdp  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

PRODUCER = "analog_a3_netlist_emit"
PROVENANCE_SCHEMA = 1
SKILL = "analog-netlist-gen"

_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
_REGISTRY = _HERE / "pdk_registry.json"
DEFAULT_CONTAINER = os.environ.get("VIBEIC_ANALOG_CONTAINER", "vibeic-eda")

# Role -> the device-class tokens a foundry SPICE lib spells its subcircuits
# with. Structural, not a vendor literal — the same vocabulary
# `analog_pdk_deck_context._ROLE_TOKENS` uses, extended with the passive roles
# the topology IR can ask for.
_ROLE_TOKENS = {
    "nmos": ("nfet", "nmos", "nch"),
    "pmos": ("pfet", "pmos", "pch"),
    "res": ("res_", "rpoly", "rppd", "rhigh", "rsil", "resistor"),
    "cap": ("cap_mim", "mimcap", "cap_cmim", "moscap"),
}
# Within a role, prefer the most ordinary flavour: a plain core-voltage device
# over a high-voltage / low-Vt / isolated variant. Deterministic and stated,
# so the choice is auditable instead of alphabetical.
#
# WHERE THIS RANKING RUNS, AND WHERE IT DOES NOT (vibe-ic#903). It ranks the
# REGISTRY's declared `device_models` — the fallback branch of
# `resolve_role_models`. A role the deck-context resolver already elected does
# NOT come through here, and a family whose libs are PARSED (the only kind that
# can ship a high/low-voltage split) resolves every role that way. So until
# #903 the sentence above described a rule that never ran for the families it
# was written for: `"hv_"` sat in `_ROLE_AVOID` while a high-voltage device was
# what got bound. The preference is now ALSO applied at the election site
# (`analog_pdk_deck_context.device_flavour_rank`), structurally, so the two
# paths agree; `test_issue903_device_flavour_election` holds them to that by
# feeding THIS tuple to THAT ranker rather than restating either list.
_ROLE_PREFER = {
    "nmos": ("01v8", "03v3", "lv_"),
    "pmos": ("01v8", "03v3", "lv_"),
    "res": ("res_high_po_0p35", "res_generic_po", "rhigh"),
    "cap": ("cap_mim", "cap_cmim"),
}
_ROLE_AVOID = ("_lvt", "_hvt", "_nvt", "_zvt", "_iso", "_dss", "20v0",
               "g5v0", "05v0", "06v0", "11v0", "_var", "hv_")


# ── small helpers ─────────────────────────────────────────────────────────
def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_ALLOWED_NODES = (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Name,
                  _ast.Load, _ast.Constant, _ast.Add, _ast.Sub, _ast.Mult,
                  _ast.Div, _ast.Pow, _ast.USub, _ast.UAdd)


def safe_eval(expr: str, env: Dict[str, float]) -> float:
    """Arithmetic over named values only. The IR is data read off disk, so it
    must never be executable: no calls, attributes or subscripts."""
    tree = _ast.parse(str(expr), mode="eval")
    for node in _ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"disallowed node {type(node).__name__}")
        if isinstance(node, _ast.Name) and node.id not in env:
            raise KeyError(node.id)
    return float(eval(compile(tree, "<ir-expr>", "eval"),  # noqa: S307
                      {"__builtins__": {}}, dict(env)))


def _fmt(v: float) -> str:
    """A geometry number SPICE reads back the same way it was computed."""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6g}"


# ── inputs ────────────────────────────────────────────────────────────────
def block_entries(project: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    for rel in (f"{_CANONICAL_ANALOG}/analog_block_list.json",
                f"{_DECLARED_ANALOG}/analog_block_list.json"):
        data = _read_json(project / rel)
        if data is None:
            continue
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if isinstance(blocks, list):
            return ([b for b in blocks if isinstance(b, dict)], rel)
    data = _read_json(project / "phase1/generated_docs/L5_ADI_SPEC.json")
    if isinstance(data, dict) and isinstance(data.get("analog_blocks"), list):
        return ([b for b in data["analog_blocks"] if isinstance(b, dict)],
                "phase1/generated_docs/L5_ADI_SPEC.json")
    return ([], None)


# ── the design's stated voltage domains (vibe-ic#903, second half) ─────────
#
# THE SEAM #903's SCOPE HALF NEEDED, AND WHY IT IS THIS ONE. The election was
# chip-global because `resolve_pdk_context` had no way to tell one block from
# another. The missing thing was never a parameter — it was a DOMAIN the design
# states. It states one already: an A1 `spec.json` carries the block's supply
# and terminal voltages WITH THEIR UNITS, because every other consumer needs
# them. So the domain is DISCOVERED from the specs the design already wrote,
# not declared a second time in a field someone has to remember to fill.
#
# WHAT IS READ: every spec row whose UNIT is a volt unit — under either key
# spelling this pipeline produces, see `_UNIT_KEYS`; the block's domain is the
# HIGHEST voltage any of them states, over every numeric field on the row.
# Highest, because a device must survive the worst case its own block puts
# across it — that is the question a flavour answers.
#
# WHAT `elevated` MEANS: above the LOWEST domain the design declares across its
# blocks. Relative, not absolute, because "elevated" is not a property of a
# number — 1.8 V is the core of one design and the elevated rail of the next.
# A design whose blocks all state the same voltage has no elevated block and
# elects exactly as it did before.
#
# THE UNITS ARE SI, NOT A FAMILY. This table is a unit vocabulary in the same
# category as `_ROLE_TOKENS`' nfet/pmos — no vendor, SKU or node literal, and
# nothing here enumerates a PDK's families: those are DISCOVERED by parsing.
_VOLT_UNITS = {"v": 1.0, "volt": 1.0, "volts": 1.0,
               "mv": 1e-3, "millivolt": 1e-3, "millivolts": 1e-3,
               "kv": 1e3, "kilovolt": 1e3, "kilovolts": 1e3}


# BOTH SPELLINGS ARE REAL, measured on this tree: `analog_a1_spec_emit` writes
# `unit` (singular) and the `analog-spec-extract` skill writes `units`. Reading
# one of them would have made the domain discoverable for half the pipeline and
# invisible for the other half — the shape of gap that reads as "this design
# states no domain" when it states one.
_UNIT_KEYS = ("units", "unit")


def _unit_scale(units: Any) -> Optional[float]:
    """The volts-per-unit of a spec row's unit, or None when the row is not a
    voltage at all."""
    u = str(units or "").strip().lower().rstrip(".")
    return _VOLT_UNITS.get(u)


def _row_unit_scale(row: Dict[str, Any]) -> Optional[float]:
    """The volts-per-unit of a spec ROW, under either key spelling."""
    for key in _UNIT_KEYS:
        scale = _unit_scale(row.get(key))
        if scale is not None:
            return scale
    return None


def spec_voltage(spec: Dict[str, Any]) -> Optional[float]:
    """The HIGHEST voltage a block's spec STATES, in volts, or None when it
    states none. Discovered from the rows' UNIT (either spelling — see
    `_UNIT_KEYS`), never from a list of blessed spec NAMES: a design is free to
    call its supply anything."""
    best: Optional[float] = None
    rows = spec.get("specs") if isinstance(spec, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        scale = _row_unit_scale(row)
        if scale is None:
            continue
        for v in row.values():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            volts = float(v) * scale
            if best is None or volts > best:
                best = volts
    return best


# The synthetic key `block_voltage_domains` reports the design's core domain
# under. Named rather than inlined so it is greppable, and so the one way it
# could go wrong — a block actually called this — is visible instead of latent.
CORE_VOLTS_KEY = "_core_volts"


def block_voltage_domains(project: Path, entries: List[Dict[str, Any]]
                          ) -> Dict[str, Any]:
    """{block name: VoltageDomain} for every declared block, plus the design's
    core (lowest stated) domain under `CORE_VOLTS_KEY`. A block named that
    would shadow it; nothing else in the tree would, and the shadowing costs a
    reader the core value, not a block its domain.

    A block whose spec states no voltage — and every block of a design that
    states none anywhere — gets `VoltageDomain()`, which every ranker below
    treats as "not stated" and resolves chip-globally, exactly as before."""
    import analog_pdk_deck_context as _apdc
    volts: Dict[str, Optional[float]] = {}
    for entry in entries:
        name = str(entry.get("name") or entry.get("block")
                   or entry.get("type"))
        spec = _read_json(project / _CANONICAL_ANALOG / name / "spec.json")
        volts[name] = spec_voltage(spec) if isinstance(spec, dict) else None
    stated = [v for v in volts.values() if v is not None]
    core = min(stated) if stated else None
    out: Dict[str, Any] = {CORE_VOLTS_KEY: core}
    for name, v in volts.items():
        out[name] = _apdc.VoltageDomain(
            volts=v,
            elevated=bool(v is not None and core is not None and v > core))
    return out


def spec_values(spec: Dict[str, Any]) -> Dict[str, float]:
    """The rows this block's declaration binds — READ BY THE FUNCTION THAT
    OWNS THE RULE, not by a second copy of it here.

    MEASURED: the copy that lived here was byte-identical to A2's when it was
    written and then was not. A2's grew the ends of a declared range
    (`<name>_max`), an entry started naming one, and A2 admitted the block
    while this file reported `tper_ns needs 1000 / fclk_max, which the bound
    spec does not supply` — so the topology emitted and its own testbench did
    not, on one declaration read two ways.
    """
    return _a2.spec_row_values(spec.get("specs"))


# ── PDK binding ───────────────────────────────────────────────────────────
def _registry_entry(selector: str) -> Tuple[Optional[str], Dict[str, Any]]:
    data = _read_json(_REGISTRY)
    sel = str(selector or "").strip().lower()
    for ent in (data or {}).get("pdks") or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "")
        if name and (name.lower() == sel or name.lower().startswith(sel)
                     or sel.startswith(name.lower())):
            return name, ent
    return None, {}


# vibe-ic#903 — the two paths a role's model can be bound by. Named so the
# artefact can say WHICH ONE bound each role instead of leaving it to be
# inferred from which branch happened to fire.
BOUND_BY_DECK_CONTEXT = "deck_context"
BOUND_BY_REGISTRY = "registry"
# The third: the PDK's own CURATED generic->foundry table. It is not a third
# guess at the same question — it is the only source that can answer a role
# `_ROLE_TOKENS` does not spell (npn, diode, varactor, the hv MOS pair, the
# three distinct poly/silicided/high resistors). MEASURED on the one populated
# family before this edge existed: 4 of 13 requested roles resolved and 9 came
# back unresolved, which A3 surfaces as IR_NOT_RENDERABLE.
BOUND_BY_DEVICE_MAP = "curated_device_map"


def resolve_role_models(family_entry: Dict[str, Any], roles: List[str],
                        ctx_device_map: Dict[str, str],
                        domain: Optional[Any] = None,
                        family: Optional[str] = None,
                        ) -> Tuple[Dict[str, str], List[str], Dict[str, str]]:
    """{role: model name} for the resolved family, the roles that could NOT be
    resolved, and {role: which path bound it} (BOUND_BY_*). Prefers whatever
    the deck-context resolver already elected, then falls back to the
    registry's declared device list. A role that resolves to nothing is
    reported, never substituted.

    vibe-ic#903 — WHY THE THIRD RETURN VALUE EXISTS. The `_ROLE_PREFER` /
    `_ROLE_AVOID` ranking below runs ONLY on the registry branch. Taking the
    deck context's election verbatim is correct — that resolver now applies the
    same preference at its own election site, over the family's PARSED
    candidates, which is the only place it can see them — but the split was
    invisible in the artefact, so a comment claiming an auditable preference
    and a binding chosen by name order were indistinguishable to a reader.

    vibe-ic#903, SECOND HALF — `domain`. The deck-context branch is already
    scoped to the block's stated domain by the time it gets here. The REGISTRY
    branch below is not, because `_ROLE_PREFER` / `_ROLE_AVOID` are a fixed
    polarity: they prefer the core-voltage device and avoid the elevated one,
    which is the wrong answer for an elevated block. So when a domain IS
    stated, the same ranker the election site uses runs FIRST here, and the
    fixed lists become the tiebreak. When no domain is stated the key is
    untouched — a design that declares no voltage binds what it always did.

    `family` is the registry key `_registry_entry` resolved. When given, the
    PDK's CURATED `device_map` is consulted after the deck context and BEFORE
    the substring heuristic below. Precedence is deliberate and does not move
    any binding that already worked: the curated table is authored per PDK, so
    where it answers at all it answers exactly, and where it is absent (every
    family that declares no `device_map`) the branch is a no-op. What it adds
    is the roles the heuristic CANNOT reach -- `_ROLE_TOKENS` has four keys, so
    any other role the topology IR asks for falls straight through to
    `unresolved` no matter how completely the PDK declares it."""
    _curated: Dict[str, str] = {}
    if family:
        _curated = _pdm.device_map(family)
    _rank_for_domain = None
    if domain is not None:
        try:
            import analog_pdk_deck_context as _apdc
            if _apdc.domain_is_stated(domain):
                _width = _apdc.FLAVOUR_KEY_WIDTH

                def _rank_for_domain(m: str) -> tuple:
                    # ONLY the FLAVOUR components. Letting the ranker's own
                    # length/name tiebreak through would override the stated
                    # `_ROLE_PREFER` order for candidates the domain does not
                    # separate at all — measured: a stated domain re-bound the
                    # passive role from the preferred device to a shorter name
                    # that the preference list does not mention.
                    return _apdc.device_flavour_rank(m, domain)[:_width]
        except Exception:                                  # pragma: no cover
            _rank_for_domain = None
    models = [m for m in (family_entry.get("device_models") or [])
              if isinstance(m, str)]
    out: Dict[str, str] = {}
    unresolved: List[str] = []
    bound_by: Dict[str, str] = {}
    for role in roles:
        if ctx_device_map.get(role):
            out[role] = ctx_device_map[role]
            bound_by[role] = BOUND_BY_DECK_CONTEXT
            continue
        if _curated.get(role):
            out[role] = _curated[role]
            bound_by[role] = BOUND_BY_DEVICE_MAP
            continue
        toks = _ROLE_TOKENS.get(role, ())
        cands = [m for m in models
                 if any(t in m.lower() for t in toks)]
        if not cands:
            unresolved.append(role)
            continue
        pref = _ROLE_PREFER.get(role, ())

        def rank(m: str) -> tuple:
            low = m.lower()
            exact = next((i for i, p in enumerate(pref) if p in low),
                         len(pref))
            avoid = sum(1 for a in _ROLE_AVOID if a in low)
            fixed = (exact, avoid, len(low), low)
            if _rank_for_domain is None:
                return fixed
            return _rank_for_domain(m) + fixed

        out[role] = sorted(cands, key=rank)[0]
        bound_by[role] = BOUND_BY_REGISTRY
    return out, unresolved, bound_by


def resolve_pdk_context(project: Path, pdk: str, container: str,
                        roles: List[str],
                        domain: Optional[Any] = None,
                        resolution: Optional[Dict[str, Any]] = None,
                        ) -> Dict[str, Any]:
    """model lib + corner section + per-role model names, through the EXISTING
    family-agnostic resolvers so a project that declares a native target never
    gets one foundry's device tokens against another's model lib.

    `domain` (vibe-ic#903, second half) is the `VoltageDomain` the DESIGN
    states for the block being resolved — see `block_voltage_domains`, which
    discovers it from the block's own A1 spec. Two blocks of one project that
    state different domains resolve to different flavours; `domain=None` (and
    every design that states no voltage) resolves chip-globally, exactly as
    this function did before.

    `resolution` (vibe-ic#1962) is an ALREADY-RESOLVED
    `analog_pdk_availability.resolve_pdk` result. This function discovers the
    target from the PROJECT's L19 document, which is right for its per-block
    callers and wrong for a caller that is asked about a PDK rather than about
    a design: with no L19 to read, the resolver result stayed None and the
    request fell through to the fallback family — measured, a request naming
    one family came back carrying ANOTHER family's model lib AND its device
    names. Passing the result in is how a PDK-shaped caller uses this one
    binder instead of growing a second one. `None` (every existing call site)
    reads the project exactly as before."""
    ctx_json: Dict[str, Any] = {}
    device_map: Dict[str, str] = {}
    model_lib: Optional[str] = None
    typ_section: Optional[str] = None
    device_terminals: Dict[str, int] = {}
    geometry_units: Dict[str, str] = {}
    status = "OK"
    work_items: List[str] = []
    family = pdk
    try:
        import analog_pdk_deck_context as _apdc
        res = resolution
        if res is None:
            try:
                import analog_pdk_availability as _apa
                declared = _declared_pdk_target(project)
                if declared:
                    res = _apa.resolve_pdk(declared, project=project,
                                           container=container)
            except Exception:
                res = None
        # vibe-ic#906 — ASK FOR EVERY ROLE THE IR ACTUALLY USES.
        #
        # This filtered the topology's roles down to the MOS pair before asking
        # the resolver, so a role the IR genuinely instantiates (cap, res, ...)
        # was never requested. `required` is not a cosmetic argument: the deck
        # resolver re-derives `device_map` from the ELECTED PRIMARY lib and only
        # falls back to the cross-lib union map when the primary cannot cover a
        # REQUIRED role. Roles absent from `required` are therefore dropped from
        # `device_map` whenever the primary happens to satisfy the MOS pair —
        # and `resolve_role_models` then reports them unresolved, which A3
        # surfaces as IR_NOT_RENDERABLE: "device role(s) cap, res do not
        # resolve". Measured on a container-installed PDK: the resolver returns
        # those very roles correctly WHEN ASKED, so the refusal described our
        # own request, not the PDK.
        #
        # WHY IT HID: the fallback that rescues this for the two PDKs
        # everything is tested against is the REGISTRY (`_registry_entry` ->
        # `device_models`), which `resolve_role_models` consults after the
        # context map. sky130/gf180 have a registry entry listing passives; an
        # unknown / container-installed family resolves to `(None, {})`, so the
        # context map is the ONLY source and the dropped roles become fatal.
        # Same shape as the host-vs-container reader defect: only a family that
        # is NOT one of the two tested open PDKs can reach it.
        ctx = _apdc.resolve_deck_context(pdk, res=res,
                                         required=tuple(roles),
                                         container=container or "",
                                         domain=domain)
        ctx_json = ctx.as_json()
        status = ctx_json.get("status") or "OK"
        family = ctx_json.get("family") or pdk
        model_lib = ctx_json.get("model_lib")
        typ_section = ctx_json.get("typ_section")
        device_map = dict(ctx_json.get("device_map") or {})
        device_terminals = dict(ctx_json.get("device_terminals") or {})
        geometry_units = dict(ctx_json.get("device_geometry_units") or {})
        work_items = list(ctx_json.get("work_items") or [])
    except Exception as exc:                                  # pragma: no cover
        status = "NEEDS_NATIVE_TEMPLATE"
        work_items = [f"deck-context resolver unavailable: {exc}"]

    fam_name, fam_entry = _registry_entry(family or pdk)
    models, unresolved, bound_by = resolve_role_models(
        fam_entry, roles, device_map, domain, family=fam_name)
    return {
        "status": status,
        "family": family,
        "registry_family": fam_name,
        "model_lib": model_lib,
        "typ_section": typ_section,
        "corner_sections": ctx_json.get("corner_sections") or [],
        # vibe-ic#907 — every (lib, section) the emitted deck must load. Empty
        # for a single-lib / known family, where the single `model_lib` line is
        # still correct.
        "deck_loads": [tuple(dl) for dl in (ctx_json.get("deck_loads") or [])],
        "role_models": models,
        # vibe-ic#903 — WHICH rule bound each role, and (for a parsed family)
        # the deck resolver's own per-role election record: the basis, the
        # rejected candidates, and whether the family spans more than one
        # voltage domain — in which case ONE flavour is bound for every block,
        # because this function takes no block argument.
        "role_model_election": {
            "bound_by": bound_by,
            "deck_context": dict(ctx_json.get("device_election") or {}),
            # WHICH domain this binding is for. `None` means the design stated
            # none, in which case the binding really is chip-global and the
            # deck_context record above says so.
            "domain": ({"volts": domain.volts, "elevated": domain.elevated}
                       if domain is not None else None),
        },
        "unresolved_roles": unresolved,
        "device_terminals": device_terminals,
        "geometry_units": geometry_units,
        # vibe-ic#1962 — the DECLARED half only, taken off THIS function's own
        # already-resolved entry rather than re-resolved through a second
        # matcher. The measured sub-record is a different kind of fact and is
        # served through its own reader; folding it in here would change what
        # every existing reader of this key sees the moment a family is
        # characterized. Byte-identical for a family with no measured record.
        "analog_device_params": {
            k: v for k, v in (fam_entry.get("analog_device_params") or
                              {}).items() if k != _pdp.MEASURED_KEY},
        "work_items": work_items,
        "deck_context": ctx_json,
    }


def _declared_pdk_target(project: Path) -> Optional[str]:
    d = _read_json(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
    if isinstance(d, dict):
        f = d.get("fields")
        if isinstance(f, dict) and isinstance(f.get("pdk_target"), str):
            return f["pdk_target"] or None
    return None


# ── rendering ─────────────────────────────────────────────────────────────
def _resolve_params(ir: Dict[str, Any], sv: Dict[str, float]
                    ) -> Tuple[Dict[str, Dict[str, float]], List[str],
                               List[str], Dict[str, Any]]:
    """Apply the IR's device_param_exprs. Returns (overrides, spec_bound,
    library_nominal, env).

    vibe-ic#1962 — the target process's MEASURED electrical constants are
    seeded FIRST, so a `device_param_exprs` entry may be written against the
    sheet resistance, the transconductance parameter or the capacitance density
    the PDK's own models were measured for. Seeded first and not last, and
    deliberately: a library `constants` entry or a spec-bound knob of the same
    name still wins, because a process constant is what the design is built
    ON, never what it is built FROM. A family nobody has characterized seeds
    nothing and every expression resolves exactly as it did before."""
    env: Dict[str, Any] = {}
    env.update({k: v for k, v in (ir.get("pdk_measured_params") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)})
    env.update(ir.get("constants") or {})
    env.update({k: v for k, v in (ir.get("knobs") or {}).items()
                if isinstance(v, (int, float))})
    env.update(sv)
    overrides: Dict[str, Dict[str, float]] = {}
    spec_bound: List[str] = []
    knob_src = ir.get("knob_sources") or {}
    for e in ir.get("device_param_exprs") or []:
        try:
            val = safe_eval(e["expr"], env)
        except Exception:
            continue
        overrides.setdefault(e["device"], {})[e["param"]] = val
        names = set()
        try:
            names = {n.id for n in _ast.walk(_ast.parse(e["expr"], "<e>",
                                                        "eval"))
                     if isinstance(n, _ast.Name)}
        except SyntaxError:
            pass
        if any(n in sv for n in names) or any(
                knob_src.get(n) == "spec" for n in names):
            spec_bound.append(f"{e['device']}.{e['param']}")
    nominal = [f"{d['name']}.{p}"
               for d in ir.get("devices") or []
               for p in ("w", "l", "m")
               if d.get(p) is not None
               and f"{d['name']}.{p}" not in spec_bound]
    # DEDUPED. An entry may carry more than one expression for the same
    # device parameter -- a unit-element form and a spec-sized form that
    # overwrites it when the declaration carries the row it needs -- and each
    # one that resolves off a bound name credits the parameter again. The
    # artefact lists WHICH parameters a bound value reached, so a parameter
    # named twice says nothing a reader can use and reads as two devices.
    return overrides, sorted(set(spec_bound)), sorted(nominal), env


def _validate_ir(ir: Dict[str, Any], pdkctx: Dict[str, Any]) -> List[str]:
    """Structural problems that must stop emission. Every one of these was a
    real failure mode measured on a hand-built fixture."""
    problems: List[str] = []
    role_terms = ir.get("role_terminals") or {}
    ports = set(ir.get("ports") or [])
    rails = set((ir.get("rails") or {}).values())
    declared_internal = set(ir.get("internal_nets") or [])
    pin_count: Dict[str, int] = {}
    visible_pin_count: Dict[str, int] = {}
    for d in ir.get("devices") or []:
        role = d.get("role")
        nets = d.get("nets") or []
        want = role_terms.get(role)
        if want is not None and len(nets) != want:
            problems.append(
                f"device `{d.get('name')}` role `{role}` declares "
                f"{len(nets)} nets, the role's subcircuit takes {want}")
        ctx_terms = (pdkctx.get("device_terminals") or {}).get(role)
        if ctx_terms and want and ctx_terms != want:
            problems.append(
                f"resolved `{role}` subcircuit takes {ctx_terms} terminals "
                f"but the IR is written for {want}; ngspice would abort "
                f"'Too few parameters for subcircuit'")
        for n in nets:
            pin_count[n] = pin_count.get(n, 0) + 1
            # The floor is READ from the checker that owns it, never
            # restated. A literal here is a second copy of one rule: the
            # checker was fixed to see two-terminal devices and this line
            # kept saying 3, so a netlist the checker accepts was refused
            # by the program predicting the checker's answer.
            if len(nets) >= _conncheck.MIN_DEVICE_NETS:
                visible_pin_count[n] = visible_pin_count.get(n, 0) + 1
        if role == "pmos" and nets and nets[-1] not in rails:
            problems.append(f"device `{d.get('name')}` is a PMOS whose body "
                            f"net `{nets[-1]}` is not a declared rail")
        if role == "nmos" and nets and nets[-1] not in rails:
            problems.append(f"device `{d.get('name')}` is an NMOS whose body "
                            f"net `{nets[-1]}` is not a declared rail")
    for net in sorted(declared_internal):
        if visible_pin_count.get(net, 0) < 2:
            problems.append(
                f"internal net `{net}` is touched by "
                f"{visible_pin_count.get(net, 0)} pin(s) that the "
                f"connectivity checker can see (its floor is "
                f"{_conncheck.MIN_DEVICE_NETS} net(s) per device) — it "
                f"would be reported FLOATING_NODE")
    for p in sorted(ports - rails):
        if pin_count.get(p, 0) < 1:
            problems.append(f"port `{p}` is declared and never connected — "
                            f"UNUSED_PORT")
    if pdkctx.get("unresolved_roles"):
        problems.append(
            "device role(s) " + ", ".join(pdkctx["unresolved_roles"]) +
            f" do not resolve to a model in the `{pdkctx.get('registry_family')}`"
            " device list")
    if not pdkctx.get("model_lib"):
        problems.append("no model library resolves for the requested PDK; a "
                        "netlist with no `.lib` is NO_MODEL_INCLUDE")
    return problems


def render_netlist(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                   prov_lines: List[str],
                   overrides: Dict[str, Dict[str, float]]) -> str:
    block = ir["block"]
    metric = any(u == "metric" for u in
                 (pdkctx.get("geometry_units") or {}).values())
    L: List[str] = [f"* {block} — analog block netlist "
                    f"({ir['block_type']} class)",
                    f"* topology: {ir['topology']}"]
    L += [f"* {ln}" for ln in prov_lines]
    L.append("*")
    if not metric:
        L.append(".option scale=1u")
    section = pdkctx.get("typ_section") or ""
    # vibe-ic#907 — LOAD EVERY LIB THIS DECK BINDS A DEVICE FROM.
    #
    # One `.lib` line is right only while every bound device lives in that
    # lib's closure. A family that splits actives and passives across separate
    # corner libs resolves its device map from the cross-lib union, so the deck
    # bound a device the single loaded section never defined and ngspice stopped
    # at `unknown subckt`. `deck_loads` carries each (lib, section) the resolver
    # says is needed — each with its OWN section, because split corner libs do
    # not share a corner vocabulary.
    #
    # A single-lib family (and every known-family sky130/gf180 context, which
    # never populates `deck_loads`) falls through to the single line below, so
    # the emitted deck is byte-identical for them.
    deck_loads = [tuple(dl) for dl in (pdkctx.get("deck_loads") or [])
                  if len(tuple(dl)) == 2]
    if deck_loads:
        for lib, sec in deck_loads:
            L.append(f".lib {lib} {sec}".rstrip())
    else:
        L.append(f".lib {pdkctx['model_lib']} {section}".rstrip())
    L.append("")
    L.append(f".subckt {block} {' '.join(ir['ports'])}")
    for d in ir["devices"]:
        model = pdkctx["role_models"][d["role"]]
        parts = [f"x{d['name']}"] + list(d["nets"]) + [model]
        for p in ("w", "l"):
            v = (overrides.get(d["name"], {}).get(p, d.get(p)))
            if v is None:
                continue
            parts.append(f"{p}={_fmt(float(v))}u" if metric
                         else f"{p}={_fmt(float(v))}")
        m = overrides.get(d["name"], {}).get("m", d.get("m"))
        if m is not None:
            parts.append(f"m={_fmt(float(m))}")
        for k, v in (d.get("params") or {}).items():
            parts.append(f"{k}={v}")
        L.append(" ".join(parts))
    L.append(f".ends {block}")
    L.append("")
    # Deliberately NO `.end`: this file is `.include`d by its testbench, and a
    # terminating card there truncates the caller's netlist.
    return "\n".join(L)


def render_testbench(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                     env: Dict[str, Any], prov_lines: List[str]
                     ) -> Tuple[Optional[str], Dict[str, Any], List[str]]:
    """Returns (text, tb_env, notes). None when the IR declares no testbench —
    an honest absence, not an invented stimulus."""
    tb = ir.get("testbench")
    if not isinstance(tb, dict):
        return None, {}, ["the topology IR declares no testbench"]
    block = ir["block"]
    notes: List[str] = []
    e: Dict[str, Any] = dict(env)
    nominal = (pdkctx.get("analog_device_params") or {}).get(
        "nominal_supply_v")
    if isinstance(nominal, (int, float)):
        e["nominal_supply_v"] = float(nominal)
    supply = None
    for expr in tb.get("supply_exprs") or []:
        try:
            supply = safe_eval(expr, {k: v for k, v in e.items()
                                      if isinstance(v, (int, float))})
            notes.append(f"supply = {expr} = {supply:g} V")
            break
        except Exception:
            continue
    if supply is None:
        return None, {}, ["no supply expression in the topology IR resolves "
                          "against the bound spec and the PDK constants"]
    e["supply"] = supply
    for name, expr in (tb.get("env_exprs") or {}).items():
        try:
            e[name] = safe_eval(expr, {k: v for k, v in e.items()
                                       if isinstance(v, (int, float))})
            notes.append(f"{name} = {expr} = {e[name]:g}")
        except Exception:
            return None, {}, [f"testbench value `{name}` needs `{expr}`, "
                              f"which the bound spec does not supply"]
    fmt = {k: (_fmt(v) if isinstance(v, float) else v) for k, v in e.items()}
    L: List[str] = [f"* tb_{block} — stimulus for the A3 block netlist"]
    L += [f"* {ln}" for ln in prov_lines]
    L.append("*")
    for ln in tb.get("conditions") or []:
        L.append(f"* condition: {ln.format(**fmt)}")
    L.append(f".include {block}.sp")
    for ln in tb.get("stimulus") or []:
        L.append(ln.format(**fmt))
    ports = []
    for p in ir["ports"]:
        ports.append("0" if p == (ir.get("rails") or {}).get("vss") else p)
    L.append(f"xdut {' '.join(ports)} {block}")
    for ln in tb.get("cards") or []:
        L.append(ln.format(**fmt))
    L.append(".control")
    for ln in tb.get("control") or []:
        L.append(ln.format(**fmt))
    L.append(".endc")
    L.append(".end")
    L.append("")
    return "\n".join(L), e, notes


# ── self-verification ─────────────────────────────────────────────────────
_CHECKERS = (
    ("a3_gate", "analog_a3_netlist_gen_check.py", True),
    ("pdk", "analog_netlist_pdk_check.py", False),
    ("connectivity", "analog_netlist_connectivity_check.py", False),
    ("include_order", "analog_netlist_include_order_check.py", False),
    ("path_lint", "analog_netlist_path_lint.py", False),
)


def verify_with_checkers(block: str, sp_text: str, tb_text: Optional[str],
                         design_content: Optional[str] = None,
                         real_project: Optional[Path] = None
                         ) -> Tuple[bool, List[Dict[str, Any]]]:
    """Run the real checkers over a staging project holding ONLY this block's
    netlist, so the verdict is about this file and not about whatever else the
    run has left in the tree.

    STAGE WHAT WILL BE EMITTED, not a subset of it. The A3 gate now asks the
    netlist what circuit is in it, and the answer lives in the sidecar this
    producer writes a few lines below — so a staging tree carrying the deck
    WITHOUT the record is a tree that will never exist on disk, and a verdict
    taken on it is a verdict about a different artefact set. Measured when the
    sidecar was left out: every emitted netlist came back
    NETLIST_REJECTED_BY_CHECKS and the producer wrote an honest-gap file for a
    deck it had just rendered correctly.

    `design_content` is passed in rather than re-derived here for the reason
    every other consumer reads it rather than inferring it: only the caller that
    resolved the parameters knows the answer, and a second derivation is free to
    disagree with the one it writes."""
    findings: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="a3verify_") as td:
        proj = Path(td)
        bdir = proj / _CANONICAL_ANALOG / block
        bdir.mkdir(parents=True, exist_ok=True)
        (proj / _CANONICAL_ANALOG / "analog_block_list.json").write_text(
            json.dumps({"blocks": [{"name": block}]}), encoding="utf-8")
        (bdir / f"{block}.sp").write_text(sp_text, encoding="utf-8")
        if design_content is not None:
            (bdir / _acc.NETLIST_PROVENANCE_ARTEFACT).write_text(
                json.dumps({"block": block,
                            "_provenance": {"producer": PRODUCER,
                                            "design_content": design_content}}),
                encoding="utf-8")
        if tb_text:
            (bdir / f"tb_{block}.sp").write_text(tb_text, encoding="utf-8")
        ok = True
        for label, prog, per_block in _CHECKERS:
            path = _HERE / prog
            if not path.is_file():
                continue
            cmd = [sys.executable, str(path), str(proj)]
            if per_block:
                cmd += ["--block", block]
            # The staging tree is NOT the project the deck belongs to: a deck
            # correctly binding the REAL project's own input/pdk copy would
            # read as a foreign absolute path when containment is tested
            # against this TemporaryDirectory (measured: u_hawaii_adc
            # round-5b). Hand the lint the real root so the project-internal
            # rung judges the tree that will actually exist on disk.
            if label == "path_lint" and real_project is not None:
                cmd += ["--project-root", str(real_project)]
            try:
                cp = _pr.run(cmd, capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError) as exc:
                findings.append({"checker": label, "rc": None,
                                 "detail": f"could not run: {exc}"})
                ok = False
                continue
            if cp.returncode != 0:
                ok = False
                findings.append({
                    "checker": label, "rc": cp.returncode,
                    "detail": ((cp.stderr or cp.stdout or "").strip()
                               [-800:] or "non-zero exit, no output")})
            else:
                findings.append({"checker": label, "rc": 0,
                                 "detail": (cp.stdout or "").strip()[-200:]})
    return ok, findings


def _docker_ok(container: str) -> bool:
    try:
        cp = _pr.run_best_effort(["docker", "exec", container, "true"],
                            capture_output=True, text=True)
        return cp.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def verify_with_ngspice(container: str, block: str, sp_text: str,
                        tb_text: str) -> Dict[str, Any]:
    """Run the testbench in the EDA container. An unreachable container is a
    CAPABILITY gap (`NOT_VERIFIED_NO_SIMULATOR`), never a netlist defect."""
    if shutil.which("docker") is None or not _docker_ok(container):
        return {"simulation_verified": False,
                "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                "detail": f"container `{container}` is not reachable"}
    stage = f"/tmp/a3emit_{block}_{int(time.time())}"
    try:
        subprocess.run(["docker", "exec", container, "mkdir", "-p", stage],
                       capture_output=True, text=True, timeout=120)
        with tempfile.TemporaryDirectory(prefix="a3sim_") as td:
            local = Path(td)
            (local / f"{block}.sp").write_text(sp_text, encoding="utf-8")
            (local / f"tb_{block}.sp").write_text(tb_text, encoding="utf-8")
            for f in (f"{block}.sp", f"tb_{block}.sp"):
                subprocess.run(["docker", "cp", str(local / f),
                                f"{container}:{stage}/{f}"],
                               capture_output=True, text=True, timeout=300)
        # `sh -lc` is deliberately NOT used: a login shell sources the EDA
        # image's profile, which was measured to abort with a syntax error
        # under dash and swallow the probe's answer, so every block came back
        # NOT_VERIFIED_NO_SIMULATOR on a container that had ngspice.
        ng = None
        for cand in ("ngspice", "/foss/tools/bin/ngspice"):
            probe = subprocess.run(
                ["docker", "exec", container, "sh", "-c",
                 f"command -v {cand} >/dev/null 2>&1 && echo yes || echo no"],
                capture_output=True, text=True, timeout=120)
            if "yes" in (probe.stdout or ""):
                ng = cand
                break
        if ng is None:
            return {"simulation_verified": False,
                    "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                    "detail": "no ngspice in the container"}
        # The simulator must be started through a LOGIN shell. A PDK's
        # ngspice init file -- the one that issues the `osdi` directives
        # registering compiled Verilog-A model types -- is located only via
        # `SPICE_USERINIT_DIR`, and that variable is exported by the EDA
        # image's login profile; a non-login shell never sets it. Without it
        # ngspice ignores every `.model <name> <va-type>` line ("Unknown
        # model type ... - ignored"), then resolves no device at all
        # ("Unable to find definition of model ..."), aborts before any
        # analysis ("no simulations run!") and exits 1 -- which this function
        # recorded as DID_NOT_CONVERGE, charging a renderable netlist for a
        # missing environment and refusing to emit it.
        #
        # `bash -lc`, not `sh -lc`: the image profile is bash syntax and
        # aborts under dash, which is why the login shell was dropped here.
        # Dropping the login shell was the wrong half of that fix.
        # `analog_real_corner_sweep` and `analog_a6_native_pv` already invoke
        # the container through `bash -lc` for exactly this reason.
        cp = subprocess.run(
            ["docker", "exec", container, "bash", "-lc",
             f"cd {stage} && {ng} -b tb_{block}.sp 2>&1"],
            capture_output=True, text=True, timeout=900)
        out = (cp.stdout or "") + (cp.stderr or "")
        tail = out.strip().splitlines()[-25:]
        bad = ("doAnalyses: iteration limit reached" in out
               or "singular matrix" in out.lower()
               or "Too few parameters" in out
               or "aborted" in out.lower()
               or "MEAS" not in out)
        meas = [ln.strip() for ln in out.splitlines() if "MEAS" in ln]
        return {
            "simulation_verified": (cp.returncode == 0 and not bad),
            "simulation_status": ("CONVERGED" if (cp.returncode == 0 and
                                                  not bad)
                                  else "DID_NOT_CONVERGE"),
            "ngspice_rc": cp.returncode,
            "measurements": meas,
            "log_tail": tail,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"simulation_verified": False,
                "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                "detail": f"container invocation failed: {exc}"}
    finally:
        try:
            subprocess.run(["docker", "exec", container, "rm", "-rf", stage],
                           capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass


# ── gap artefact ──────────────────────────────────────────────────────────
def write_gap(bdir: Path, project: Path, block: str, btype: str, status: str,
              reason: str, **extra) -> Path:
    body = {
        "block": block,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": _now(),
            "fields_bound": [],
            "fields_defaulted": [],
            "defaults_used": False,
        },
        "status": status,
        "netlist_written": False,
        "reason": reason,
        "ai_handoff": {
            "track": "skill",
            "skill": SKILL,
            "required_output": f"{_CANONICAL_ANALOG}/{block}/{block}.sp",
            "reason": reason,
        },
    }
    body.update(extra)
    bdir.mkdir(parents=True, exist_ok=True)
    p = bdir / "netlist_gap.json"
    p.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def _drop_stale(bdir: Path, block: str) -> List[str]:
    """Remove artefacts a PREVIOUS run of this producer left behind whose
    inputs no longer support them. Another author's file is never touched."""
    dropped = []
    for name in (f"{block}.sp", f"tb_{block}.sp", "netlist_provenance.json"):
        p = bdir / name
        if not p.is_file():
            continue
        try:
            if PRODUCER in p.read_text(encoding="utf-8", errors="replace"):
                p.unlink()
                dropped.append(name)
        except OSError:
            pass
    return dropped


# ── per-block driver ──────────────────────────────────────────────────────
def emit_for_block(project: Path, entry: Dict[str, Any], pdk: str,
                   container: str, verify_sim: bool,
                   domain: Optional[Any] = None) -> Dict[str, Any]:
    name = str(entry.get("name") or entry.get("block") or entry.get("type"))
    bdir = project / _CANONICAL_ANALOG / name
    sp_path = bdir / f"{name}.sp"
    rec: Dict[str, Any] = {"block": name}

    if sp_path.is_file():
        text = sp_path.read_text(encoding="utf-8", errors="replace")
        if PRODUCER not in text:
            rec.update(action="kept_preexisting", emitted=False,
                       netlist=str(sp_path.relative_to(project)))
            return rec

    ir_path = bdir / "topology.json"
    ir = _read_json(ir_path) if ir_path.is_file() else None
    btype = str((ir or {}).get("block_type")
                or entry.get("type") or "unknown")
    if not isinstance(ir, dict):
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NO_TOPOLOGY_IR",
                        ("no `topology.json` for this block: the A2 producer "
                         "either has no library entry for its circuit class "
                         "or has not run. A3 renders SPICE from the A2 IR and "
                         "carries no per-type template of its own, so there "
                         "is nothing to render."),
                        expected_input=f"{_CANONICAL_ANALOG}/{name}/topology.json")
        rec.update(action="gap", emitted=False, status="NO_TOPOLOGY_IR",
                   gap_path=str(gap.relative_to(project)))
        return rec

    spec_path = bdir / "spec.json"
    spec = _read_json(spec_path) if spec_path.is_file() else None
    if not isinstance(spec, dict) or not spec_values(spec):
        # ── THE CONTROL. The library could render this block's circuit class
        # right now. Doing so would produce a template with the design's block
        # name substituted into it: it would pass all five gates, it would
        # simulate, and every number it produced would be about the template.
        dropped = _drop_stale(bdir, name)
        gap = write_gap(
            bdir, project, name, btype, "NO_SPEC_NO_NETLIST",
            ("no A1 spec is bound for this block, so no design number can "
             "enter its netlist. The topology library COULD render its "
             "circuit class — and that netlist would be a template with this "
             "block's name substituted into it, indistinguishable to every "
             "downstream gate from a designed one. It is deliberately not "
             "emitted."),
            expected_input=f"{_CANONICAL_ANALOG}/{name}/spec.json",
            topology_available=True,
            topology=ir.get("topology"),
            stale_artefacts_removed=dropped,
            unblocked_by=("an A1 spec for this block — from "
                          "`analog_a1_spec_emit` when the documents attribute "
                          "one, or from skill `analog-spec-extract` when they "
                          "do not"))
        rec.update(action="gap", emitted=False, status="NO_SPEC_NO_NETLIST",
                   gap_path=str(gap.relative_to(project)))
        return rec

    sv = spec_values(spec)
    roles = sorted({d["role"] for d in ir.get("devices") or []})
    pdkctx = resolve_pdk_context(project, pdk, container, roles, domain)
    if pdkctx["status"] != "OK":
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NEEDS_NATIVE_TEMPLATE",
                        ("the declared PDK target resolves to a family whose "
                         "deck context is incomplete; emitting one foundry's "
                         "device tokens against another's model library is "
                         "forbidden"),
                        deck_context=pdkctx.get("deck_context"),
                        work_items=pdkctx.get("work_items"))
        rec.update(action="gap", emitted=False,
                   status="NEEDS_NATIVE_TEMPLATE",
                   gap_path=str(gap.relative_to(project)))
        return rec

    problems = _validate_ir(ir, pdkctx)
    if problems:
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "IR_NOT_RENDERABLE",
                        ("the topology IR cannot be rendered into a netlist "
                         "that the shipped netlist checkers would accept"),
                        problems=problems)
        rec.update(action="gap", emitted=False, status="IR_NOT_RENDERABLE",
                   gap_path=str(gap.relative_to(project)), problems=problems)
        return rec

    overrides, spec_bound, nominal, env = _resolve_params(ir, sv)
    # ONE word a reader does not have to reconstruct from two lists. The
    # structure always follows from the block's circuit class; whether any
    # bound spec value reached the DEVICES is the question that separates a
    # designed netlist from a class netlist carrying a design's name, and it
    # must be answerable without inference.
    design_content = ("structure_and_geometry" if spec_bound
                      else "structure_only")
    ir_prov = ir.get("_provenance") or {}
    defaulted = list(ir_prov.get("fields_defaulted") or [])
    handoff = ir_prov.get("ai_handoff")
    if nominal and not handoff:
        # Any device parameter the bound spec did not reach is unsolved
        # SIZING. That is judgment the deterministic track does not do, so the
        # artefact has to name who does — otherwise a netlist that simulates
        # reads as a netlist that was designed.
        handoff = {
            "track": "skill",
            "skill": "analog-sizing",
            "reason": (
                f"{len(nominal)} device parameter(s) carry the topology "
                f"library's nominal value because no bound spec value "
                f"determines them; solving them against the spec is sizing "
                f"judgment"),
            "scope": "device_geometry",
            "unsized_params": nominal,
        }

    # ONE stamp for this emission, used by the netlist header, the sidecar and
    # the run reference. Calling `_now()` three times gave three values for one
    # event, so nothing downstream could tell whether two records described the
    # same emission.
    stamp = _now()
    prov_lines = [
        f"_provenance: producer={PRODUCER} schema={PROVENANCE_SCHEMA}",
        f"_provenance: produced_at={stamp}",
        f"_provenance: topology_ir={_CANONICAL_ANALOG}/{name}/topology.json "
        f"sha256={_sha256(ir_path)}",
        f"_provenance: spec={_CANONICAL_ANALOG}/{name}/spec.json "
        f"sha256={_sha256(spec_path)}",
        f"_provenance: spec_values_bound={sorted(sv.keys())}",
        f"_provenance: design_content={design_content}",
        f"_provenance: spec_bound_params={spec_bound or 'none'}",
        f"_provenance: library_nominal_params={nominal or 'none'}",
        f"_provenance: knobs_defaulted_by_library={defaulted or 'none'}",
        f"_provenance: pdk_family={pdkctx.get('registry_family') or pdkctx.get('family')}",
        f"_provenance: model_lib={pdkctx.get('model_lib')} "
        f"section={pdkctx.get('typ_section')}",
        f"_provenance: role_models={pdkctx.get('role_models')}",
    ]
    # vibe-ic#903 — WHICH voltage domain elected those models. Emitted ONLY
    # when the design states one: a design that states none binds chip-globally
    # and its deck is byte-identical to before, which is the paired guard.
    _dom = (pdkctx.get("role_model_election") or {}).get("domain")
    if _dom and (_dom.get("volts") is not None or _dom.get("elevated")):
        prov_lines.append(
            f"_provenance: voltage_domain=volts={_dom.get('volts')} "
            f"elevated={_dom.get('elevated')} (stated by this block's spec; "
            f"the device flavour above is elected FOR IT)")
    if handoff:
        prov_lines.append(
            f"_provenance: ai_handoff=skill:{handoff.get('skill')} "
            f"reason={handoff.get('reason')}")
    else:
        prov_lines.append("_provenance: ai_handoff=none")
    prov_lines.append(
        "_provenance: device geometry above is the topology library nominal "
        "EXCEPT the spec_bound_params listed; sizing to the bound spec is "
        "skill `analog-sizing`, not this producer")

    sp_text = render_netlist(ir, pdkctx, prov_lines, overrides)
    tb_text, tb_env, tb_notes = render_testbench(ir, pdkctx, env, prov_lines)

    ok, findings = verify_with_checkers(name, sp_text, tb_text,
                                        design_content,
                                        real_project=project)
    if not ok:
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NETLIST_REJECTED_BY_CHECKS",
                        ("the rendered netlist does not pass the shipped "
                         "netlist checkers, so it was not emitted: a netlist "
                         "that cannot pass the checks that exist is worse "
                         "than an absent one, which is honestly WAIVED"),
                        checker_findings=findings)
        rec.update(action="gap", emitted=False,
                   status="NETLIST_REJECTED_BY_CHECKS",
                   gap_path=str(gap.relative_to(project)),
                   checker_findings=findings)
        return rec

    sim: Dict[str, Any] = {"simulation_verified": False,
                           "simulation_status": "NOT_ATTEMPTED"}
    if verify_sim and tb_text:
        sim = verify_with_ngspice(container, name, sp_text, tb_text)
        if sim.get("simulation_status") == "DID_NOT_CONVERGE":
            _drop_stale(bdir, name)
            gap = write_gap(bdir, project, name, btype,
                            "NETLIST_NOT_SIMULATABLE",
                            ("the rendered netlist passed every static check "
                             "and did not converge in the simulator, so it "
                             "was not emitted"),
                            checker_findings=findings, simulation=sim)
            rec.update(action="gap", emitted=False,
                       status="NETLIST_NOT_SIMULATABLE",
                       gap_path=str(gap.relative_to(project)))
            return rec
    elif verify_sim and not tb_text:
        sim = {"simulation_verified": False,
               "simulation_status": "NOT_VERIFIED_NO_TESTBENCH",
               "detail": "; ".join(tb_notes)}

    sp_text = sp_text.replace(
        f"* _provenance: ai_handoff",
        f"* _provenance: simulation_verified={sim.get('simulation_verified')}"
        f" status={sim.get('simulation_status')}"
        f"\n* _provenance: ai_handoff", 1)

    # ── the digest a report quotes has to name the run it came from ───────
    # The two digests already in the header are over files that embed a
    # wall-clock stamp and an absolute path, so they change on every run of
    # identical inputs and identify neither the content nor the run. Measured
    # across five sibling run trees of the same inputs: five different quoted
    # digests, and nothing on any of them saying which tree produced it.
    # `content_sha256` is stable across runs (every `* _provenance:` line is
    # excluded before hashing, including these two, so stamping them cannot
    # move it) and `provenance_ref` carries the run tree, the artefact and the
    # content in ONE token. `analog_a3_netlist_gen_check` recomputes both.
    sp_rel = str(sp_path.relative_to(project))
    content_sha = _pc.content_digest(sp_text)
    rref = _pc.new_run_ref()
    ref = _pc.provenance_ref(rref, sp_rel, content_sha)
    sp_text = sp_text.replace(
        "* _provenance: ai_handoff",
        f"* _provenance: run_ref={rref}\n"
        f"* _provenance: content_sha256={content_sha}\n"
        f"* _provenance: provenance_ref={ref}\n"
        f"* _provenance: ai_handoff", 1)

    bdir.mkdir(parents=True, exist_ok=True)
    sp_path.write_text(sp_text, encoding="utf-8")
    tb_content_sha = None
    if tb_text:
        (bdir / f"tb_{name}.sp").write_text(tb_text, encoding="utf-8")
        tb_content_sha = _pc.content_digest(tb_text)
    sidecar = {
        "block": name,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            # The SAME stamp the netlist header carries — one event, one time.
            "produced_at": stamp,
            "rendered_from": {
                "topology_json": {
                    "path": f"{_CANONICAL_ANALOG}/{name}/topology.json",
                    "sha256": _sha256(ir_path)},
                "spec_json": {
                    "path": f"{_CANONICAL_ANALOG}/{name}/spec.json",
                    "sha256": _sha256(spec_path)},
            },
            "has_own_netlist_template": False,
            # ONE token that names the run tree, the artefact and the content
            # it is proof of. `content_sha256` is recomputable by a reader
            # from the artefact alone and is stable across runs of the same
            # inputs; `run_ref` is stamped into BOTH this record and the
            # artefact, so a record from another run disagrees with the
            # artefact it claims to describe while a whole tree copied intact
            # still agrees with itself.
            "run_ref": rref,
            "provenance_ref": ref,
            "content_sha256": content_sha,
            "artifact_sha256": _pc.file_digest(sp_path),
            "testbench_content_sha256": tb_content_sha,
            "content_digest_definition": (
                "sha256 over the artefact with every `* _provenance:` line "
                "removed — the design content, not the run. Stable across "
                "runs of the same inputs; the `sha256=` values under "
                "rendered_from are NOT, because their subjects embed a "
                "timestamp and an absolute path."),
            "design_content": design_content,
            "design_content_meaning": (
                "structure_and_geometry — at least one device parameter was "
                "solved against a bound spec value"
                if spec_bound else
                "structure_only — the circuit class came from the topology "
                "library and NO bound spec value reached any device "
                "parameter; the geometry below is a library nominal. The "
                "netlist exists because a spec IS bound for this block (see "
                "fields_bound), but it is not sized to it."),
            "fields_bound": sorted(sv.keys()),
            "fields_defaulted": defaulted,
            "defaults_used": bool(defaulted),
            "spec_bound_params": spec_bound,
            "library_nominal_params": nominal,
            "ai_handoff": handoff,
            "limits": (
                "the STRUCTURE is the topology library's circuit class and "
                "the bound spec values entered only the parameters listed in "
                "spec_bound_params; every other geometry is a library "
                "nominal, not a solution of this design's spec."),
        },
        "pdk": dict({k: pdkctx[k] for k in
                     ("family", "registry_family", "model_lib", "typ_section",
                      "corner_sections", "role_models")},
                    # vibe-ic#903 — the election and the domain it was scoped
                    # to, so the sidecar answers "why THIS device" without a
                    # reader re-deriving it from the lib names.
                    role_model_election=pdkctx.get("role_model_election")),
        "testbench": {"path": (f"tb_{name}.sp" if tb_text else None),
                      "conditions": tb_notes},
        "verification": {"checkers": findings, "simulation": sim},
        "outputs": [f"{name}.sp"] + ([f"tb_{name}.sp"] if tb_text else []),
    }
    (bdir / "netlist_provenance.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    gapf = bdir / "netlist_gap.json"
    if gapf.is_file():
        gapf.unlink()
    rec.update(action="emitted", emitted=True,
               netlist=str(sp_path.relative_to(project)),
               testbench=(f"tb_{name}.sp" if tb_text else None),
               spec_bound_params=spec_bound,
               design_content=design_content,
               provenance_ref=ref,
               simulation_status=sim.get("simulation_status"))
    return rec


def run(project: Path, only: Optional[str], pdk: str, container: str,
        verify_sim: bool) -> Tuple[int, Dict[str, Any]]:
    entries, src = block_entries(project)
    if not entries:
        return 1, {"producer": PRODUCER, "verdict": "NO_INPUT",
                   "reason": "no analog block list and no L5 analog_blocks[]",
                   "records": []}
    all_entries = list(entries)
    if only:
        entries = [e for e in entries
                   if (e.get("name") or e.get("block") or e.get("type"))
                   == only]
        if not entries:
            return 1, {"producer": PRODUCER, "verdict": "NO_SUCH_BLOCK",
                       "reason": f"block `{only}` is not declared in {src}",
                       "records": []}
    # vibe-ic#903 (second half) — the DESIGN's stated voltage domains, read off
    # the blocks' own A1 specs, so the per-block election below has something
    # to scope to. Computed once over ALL declared blocks (not just `--block`
    # ones): "elevated" is relative to the design's LOWEST domain, and a
    # single-block invocation must not silently redefine which that is.
    domains = block_voltage_domains(project, all_entries)
    records = [emit_for_block(
        project, e, pdk, container, verify_sim,
        domains.get(str(e.get("name") or e.get("block") or e.get("type"))))
        for e in entries]
    emitted = [r for r in records if r.get("emitted")]
    kept = [r for r in records if r.get("action") == "kept_preexisting"]
    gaps = [r for r in records if r.get("action") == "gap"]
    report = {
        "producer": PRODUCER,
        "block_list_source": src,
        "verdict": "EMITTED" if (emitted or kept) else "ALL_GAP",
        "blocks_total": len(records),
        "blocks_emitted": len(emitted),
        "blocks_kept_preexisting": len(kept),
        "blocks_gap": len(gaps),
        # WHAT was emitted, not only HOW MANY. A caller that reads only the
        # count cannot tell a design-bound netlist from a library topology
        # carrying a design's name, which is the whole distinction A4 and the
        # compliance line are now required to carry.
        "blocks_structure_only": sum(
            1 for r in records
            if _acc.classify_design_content(r.get("design_content"))
            == _acc.CONTENT_STRUCTURE_ONLY),
        "design_content": {r["block"]: r.get("design_content")
                           for r in records if r.get("emitted")},
        "provenance_ref": {r["block"]: r.get("provenance_ref")
                           for r in records if r.get("emitted")},
        "gap_status": {r["block"]: r.get("status") for r in gaps},
        "ai_handoff_blocks": [r["block"] for r in gaps],
        "suggested_skill": SKILL if gaps else None,
        "records": records,
    }
    return (0 if (emitted or kept) else 2), report


def main(argv: Optional[List[str]] = None) -> int:
    # A usage error exits `_pc.EX_USAGE`, never the honest-gap tier — see
    # `_analog_producer_common` for the measurement that forced the split.
    ap = _pc.ProducerArgumentParser(prog=PRODUCER, description=__doc__,
                                    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", default=None)
    ap.add_argument("--pdk", default=os.environ.get("VIBEIC_ANALOG_PDK",
                                                    "sky130"))
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--verify-sim", action="store_true",
                    help="additionally run the generated testbench through "
                         "ngspice in the EDA container; a deck that does not "
                         "converge is not emitted")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 1
    rc, report = run(project, args.block, args.pdk, args.container,
                     args.verify_sim)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    if rc == 0:
        print(f"{PRODUCER}: {report['blocks_emitted']} netlist(s) emitted "
              f"and verified, {report['blocks_gap']} honest gap(s) "
              f"(hand off to `{SKILL}`)")
    elif rc == _pc.RC_HONEST_GAP:
        print(_pc.honest_gap_line(
            PRODUCER,
            f"NO netlist emitted — {report['blocks_gap']} netlist_gap.json "
            f"written ({report['gap_status']}); invoke skill `{SKILL}`"),
            file=sys.stderr)
    else:
        print(f"{PRODUCER}: {report.get('verdict')} — "
              f"{report.get('reason')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
