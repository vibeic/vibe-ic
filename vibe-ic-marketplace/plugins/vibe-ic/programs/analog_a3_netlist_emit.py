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
import math
import os
import re
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
import pdk_family_identity as _ident  # noqa: E402 — the ONE family matcher
# The FLOOR the connectivity checker applies, read from the checker rather
# than restated here — see `_validate_ir`.
import analog_netlist_connectivity_check as _conncheck  # noqa: E402
# The A1 spec-row reading rule, owned by A2 — see `spec_values`.
import analog_a2_topology_emit as _a2  # noqa: E402
import pdk_analog_layout_minima as _limits  # noqa: E402
import analog_poweron_sequence as _poweron  # noqa: E402  (lane icadc)
import analog_deck_vector_retention as _retain  # noqa: E402  (lane icadc)
import pdk_analog_device_params as _pdp  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import analog_incremental_decimator as _inc  # noqa: E402 — the decode stamp
import analog_adc_enob_corner_check as _enob  # noqa: E402 — the clock card
import _progress_run as _pr  # noqa: E402
import _container_exec as _ce  # noqa: E402 — the ONE container-side deadline primitive

PRODUCER = "analog_a3_netlist_emit"


def producer_fingerprint() -> str:
    """A digest of THIS producer's own source, stamped into the provenance.

    MEASURED (round 23): an artefact that names its producer but not WHICH
    producer cannot be told apart from a stale one, so the runner skipped the
    producer and the simulator got the old netlist. See the same function in
    `analog_a2_topology_emit`. Derived from the producer's own bytes -- not
    mtime, not a file name.
    """
    import hashlib
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:                                     # pragma: no cover
        return ""
PROVENANCE_SCHEMA = 1
SKILL = "analog-netlist-gen"

_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
_REGISTRY = _HERE / "pdk_registry.json"
DEFAULT_CONTAINER = os.environ.get("VIBEIC_ANALOG_CONTAINER") or _pin.default_container_name()
#: The family this producer falls back to when NOBODY named one. It is
#: the historical `--pdk` default, moved out of the argparse default so
#: that "the caller asked for this" and "nobody asked for anything" stop
#: being the same string — see `pdk_request_is_bound`.
DEFAULT_PDK = "sky130"

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


_RUN_REF_RE = re.compile(r"^\*\s*_provenance:\s*run_ref=(\S+)\s*$", re.M)


def _run_ref_in(text: str) -> Optional[str]:
    """The `run_ref` nonce already stamped in an artefact's header, if any."""
    m = _RUN_REF_RE.search(text or "")
    return m.group(1) if m else None


def _ir_content_digest(path: Path) -> Optional[str]:
    """The topology's CONTENT digest — its `_provenance` stripped (R-0915-62)."""
    try:
        return _pc.json_content_digest(path.read_text(encoding="utf-8",
                                                      errors="replace"))
    except OSError:
        return None


def _reuse_unchanged(path: Path, new_text: str) -> Optional[str]:
    """The text already on disk when its CONTENT matches `new_text`, else None.

    R-0915-44. `content_digest` strips every `* _provenance:` line, so this
    compares the circuit and not the stamps. Returning the EXISTING text (not
    the new one) is the point: the caller then leaves the file alone, and the
    whole-file sha256 that A4 recorded as `netlist_sha256` stays valid.
    """
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if _pc.content_digest(existing) != _pc.content_digest(new_text):
        return None
    return existing


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
    """The registry entry `selector` names, through the ONE family matcher.

    vibe-ic#2139 — this carried its own prefix-only rule, which is why
    `_registry_entry('sg13g2')` answered None while
    `pdk_analog_layout_minima.resolve_family('sg13g2')` answered `ihp-sg13g2`
    on the same string in the same process. Two readers of one registry
    disagreeing about which entry a name denotes is how one PDK's device
    tokens came to be bound against another PDK's model library.
    """
    return _ident.canonical_entry(selector, _REGISTRY)


def _pdk_token(selector: Optional[str]) -> str:
    """The family a PDK selector names, canonicalised through the registry."""
    raw = str(selector or "").strip().lower()
    if not raw:
        return ""
    canon, _ = _registry_entry(raw)
    return (canon or raw).lower()


def pdk_request_is_bound(requested: Optional[str], bound_family: Optional[str],
                         registry_family: Optional[str]) -> bool:
    """Did an EXPLICIT `--pdk` request name the family the block actually bound?

    A block's family is discovered from the DESIGN (its L19 `pdk_target`, then
    the deck resolver), not from this argument, so `--pdk` is a request and not
    a setting. MEASURED on this repo, 2026-09-07 (czdsm3): a project declaring
    `sg13g2`, emitted twice — once `--pdk sg13g2` and once `--pdk sky130` —
    produced netlists with the SAME content sha (`@3690cae39ff3`), and the
    string `sky130` appeared ZERO times in the JSON report. The requested PDK
    was not honoured, not warned about, and not recorded: the run said EMITTED,
    rc 0, and the reader had no way to learn their request had been dropped.

    Prefix-tolerant on BOTH sides, matching `_registry_entry`'s own matching
    rule, and tolerant of a vendor prefix on one side only (a registry name
    like `ihp-sg13g2` and a bare family `sg13g2` are one family), because the
    point of the predicate is to catch a request for a DIFFERENT FOUNDRY, not
    to police spelling. Chip/PDK-AGNOSTIC: no family literal appears here."""
    req = _pdk_token(requested)
    if not req:
        return True                      # nothing was requested; nothing to check
    seen = False
    for cand in (bound_family, registry_family):
        got = _pdk_token(cand)
        if not got:
            continue
        seen = True
        if req == got or req.startswith(got) or got.startswith(req):
            return True
        if req.rsplit("-", 1)[-1] == got.rsplit("-", 1)[-1]:
            return True
    # NOTHING WAS BOUND, so nothing DISAGREES with the request. Refusing on an
    # unresolved binding would charge the caller for a resolver that could not
    # answer — and the resolver's own `status != OK` branch, three lines below
    # the call site, is what owns that outcome.
    return not seen


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


#: vibe-ic#2139 — the status a context takes when it cannot name ONE PDK.
#: A deck built from it would load one process's models and instantiate
#: another's devices, which is the `unknown subckt` death, and the refusal is
#: what the caller gets instead of that deck.
PDK_CROSS_BINDING = "PDK_CROSS_BINDING"

#: Where each half of a resolved context comes from, for attribution. The
#: deck resolver's model library and its device map are ONE declaration — the
#: authored table entry, or the parse of the libs one family resolved — so a
#: token it bound is attributable to whichever family that declaration is.
#: Every other binding comes from the REGISTRY entry, which is a different
#: declaration and may be a different family.
_LIB_BOUND = frozenset({BOUND_BY_DECK_CONTEXT})


def context_library_family(ctx_json: Dict[str, Any], pdk: str) -> Optional[str]:
    """WHICH PDK the model library in `ctx_json` belongs to.

    Not the same question as "which PDK was asked for", and that is the whole
    point. `analog_pdk_deck_context.known_family_context` records the request
    in `family` and the template it actually carries in `template_family`; a
    parsed context has no template and its library was read out of the family
    it resolved. So the library's owner is `template_family` when there is
    one, and the resolved family otherwise.
    """
    return (ctx_json.get("template_family")
            or ctx_json.get("family") or pdk or None)


def cross_pdk_bindings(named_family: Optional[str],
                       lib_family: Optional[str],
                       model_lib: Optional[str],
                       role_models: Dict[str, str],
                       bound_by: Dict[str, str],
                       registry_family: Optional[str],
                       ) -> List[Dict[str, Any]]:
    """Every element of this context that belongs to a DIFFERENT PDK than the
    model library does. Empty when the context names one PDK throughout.

    THE INVARIANT, stated once: a deck loads exactly one process's models, so
    every device token it instantiates and the library it loads must come from
    the SAME declaration. vibe-ic#2139 measured what happens when they do not
    — a project declaring no L19 asked for one open PDK, the deck resolver had
    no authored template for it and handed back ANOTHER open PDK's model
    library under the requested name, `resolve_role_models` filled the roles
    that library does not cover from the REQUESTED family's registry entry,
    and the emitted deck loaded one process and instantiated the other's
    devices. `analog_a3_netlist_emit` reported `1 netlist(s) emitted and
    verified`, rc 0; ngspice reported `unknown subckt` and simulated nothing.

    Two things can disagree and both are checked:

      * the LIBRARY against the family the context NAMES — this is the
        fall-through, and it is a disagreement even when every token happens
        to come from the library's own family, because the artefact still
        publishes one process's values under another's name;
      * each TOKEN against the library — this is the mix that kills the deck,
        and it names the token that will die.

    `None` FROM THE COMPARATOR IS NOT A DISAGREEMENT. `same_family` answers
    None when the question cannot be asked at all (a side empty, or too short
    to name a family), and refusing on that would charge a design for a
    comparison nobody made. Only an observed contradiction refuses.

    chip-AGNOSTIC: no family, node or device literal appears here — every name
    in the refusal comes from the context and the registry.
    """
    if not model_lib:
        # No library was bound, so there is no library for anything to
        # disagree WITH. The caller's own `status != OK` branch owns that.
        return []
    out: List[Dict[str, Any]] = []
    lib_id = _ident.canonical_or_normalised(lib_family) or str(lib_family)
    named_id = _ident.canonical_or_normalised(named_family) or str(named_family)
    if _ident.same_family(lib_family, named_family) is False:
        out.append({
            "kind": "model_library",
            "role": None,
            "element": model_lib,
            "element_pdk": lib_id,
            "model_lib": model_lib,
            "model_lib_pdk": lib_id,
            "named_pdk": named_id,
            "sentence": (
                f"this context is named `{named_id}` but the model library it "
                f"would load is `{model_lib}`, which belongs to `{lib_id}`. "
                f"There is no authored deck template for `{named_id}`, and "
                f"another PDK's library is not a default to fall through to: "
                f"a deck built from it would characterise `{lib_id}` and "
                f"publish the numbers under `{named_id}`."),
        })
    for role in sorted(role_models):
        token = role_models[role]
        if not token:
            continue
        token_family = (lib_family if bound_by.get(role) in _LIB_BOUND
                        else registry_family)
        if _ident.same_family(token_family, lib_family) is not False:
            continue
        token_id = (_ident.canonical_or_normalised(token_family)
                    or str(token_family))
        out.append({
            "kind": "device_token",
            "role": role,
            "element": token,
            "element_pdk": token_id,
            "model_lib": model_lib,
            "model_lib_pdk": lib_id,
            "named_pdk": named_id,
            "bound_by": bound_by.get(role),
            "sentence": (
                f"device token `{token}` (role `{role}`) is declared by "
                f"`{token_id}`, but the model library this deck would load is "
                f"`{model_lib}`, which belongs to `{lib_id}`. `{lib_id}` does "
                f"not define `{token}`, so the deck loads one process and "
                f"instantiates another's device."),
        })
    return out


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
    deck_prelude: List[str] = []
    geometry_params: Dict[str, Dict[str, str]] = {}
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
            except _ce.ContainerImageMismatch:
                # AN ENVIRONMENT REFUSAL IS NOT A RESOLVER OUTCOME. See the
                # re-raise below for the measurement; this inner handler is the
                # one that would have turned it into `res = None`, i.e. into a
                # PDK the design never declared.
                raise
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
        geometry_params = {k: dict(v) for k, v in
                           (ctx_json.get("device_geometry_params") or {}).items()}
        deck_prelude = [str(x) for x in (ctx_json.get("deck_prelude") or [])]
        work_items = list(ctx_json.get("work_items") or [])
    except _ce.ContainerImageMismatch:
        # THE ONE EXCEPTION THIS BROAD HANDLER MAY NOT ABSORB (vibe-ic#2076,
        # vibe-ic#2088). `NEEDS_NATIVE_TEMPLATE` is a statement about the PDK:
        # it says the resolver looked and this family has no native template.
        # An image mismatch means the resolver was never allowed to look, and
        # recording it as the former is exactly the laundering of a host
        # condition into a verdict about the design that #2088 names. It is
        # re-raised so `emit_for_block` can record it in its own tier.
        raise
    except Exception as exc:                                  # pragma: no cover
        status = "NEEDS_NATIVE_TEMPLATE"
        work_items = [f"deck-context resolver unavailable: {exc}"]

    fam_name, fam_entry = _registry_entry(family or pdk)
    models, unresolved, bound_by = resolve_role_models(
        fam_entry, roles, device_map, domain, family=fam_name)
    # vibe-ic#2139 — THE LIBRARY AND THE TOKENS MUST BE ONE PDK'S.
    # This is the last point at which both halves are visible: the deck
    # resolver has said which library it carries and `resolve_role_models` has
    # just said where every token came from. A disagreement here is refused BY
    # NAME and the library is DROPPED — a context that cannot name one PDK
    # must not hand its caller another PDK's library to emit against, which is
    # what "falls through to a default" meant and what killed the deck.
    lib_family = context_library_family(ctx_json, pdk)
    cross = cross_pdk_bindings(family or pdk, lib_family, model_lib,
                               models, bound_by, fam_name)
    if cross:
        status = PDK_CROSS_BINDING
        work_items = list(work_items) + [c["sentence"] for c in cross]
        model_lib = None
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
        # {role: {"w": formal, "l": formal}} — the geometry parameter NAMES
        # each bound device subckt declares for itself.
        "geometry_params": geometry_params,
        # The family's own global switch/parameter deck — files this netlist
        # must `.include` BEFORE its `.lib` corner line, because its bound
        # device subckts reference parameters their model library does not
        # define. Empty for a self-contained family (the sky130 path).
        "deck_prelude": deck_prelude,
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
        # vibe-ic#2139 — the STRUCTURED half of the refusal above: which
        # element, which role, which two PDKs. Empty on every context that
        # names one PDK throughout, which is every context that was already
        # correct.
        "cross_pdk_bindings": cross,
        "library_family": lib_family,
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
    # THE SAME environment A2 split the capacitors in — one function, so the
    # length A2 checked against the PDK's bounds is the length rendered here
    # (q6-a2-cap-osr: A2 split at the graded-range OSR while this pass
    # rendered at the declared one, and four capacitors came out above the
    # gencell maximum). `effective_spec_values` is absent on an IR that
    # applied nothing, and then this is exactly the environment it always was.
    env: Dict[str, Any] = _a2.rendering_env(
        ir.get("pdk_measured_params"), ir.get("constants"), ir.get("knobs"),
        sv, ir.get(_a2.EFFECTIVE_SPEC_KEY))
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


def bound_geometry_limit_violations(
        ir: Dict[str, Any], pdkctx: Dict[str, Any],
        overrides: Dict[str, Dict[str, float]]) -> List[str]:
    """Name final, spec-bound capacitor geometry the selected PDK cannot draw.

    A2 may divide a library-sized capacitor before A3 has the complete bound
    spec environment. A3 is where final values are resolved and the last point
    at which the netlist can be declined before A5 calls a gencell.
    """
    family = pdkctx.get("registry_family") or pdkctx.get("family")
    if not isinstance(family, str) or not family:
        return []
    try:
        _canonical, ent = _limits.resolve_family(family)
    except (KeyError, TypeError, ValueError):
        return []
    roles = ((ent.get("analog_device_layout_maxima") or {})
             .get("roles") or {})
    lmax = _limits.max_length_um(roles, _a2.CAP_ROLE)
    wmax = _limits.max_width_um(roles, _a2.CAP_ROLE)
    if lmax is None and wmax is None:
        return []
    out: List[str] = []
    for device in ir.get("devices") or []:
        if device.get("role") != _a2.CAP_ROLE:
            continue
        name = str(device.get("name") or "<unnamed>")
        values = overrides.get(name, {})
        for param, maximum in (("l", lmax), ("w", wmax)):
            value = values.get(param, device.get(param))
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if maximum is not None and float(value) > float(maximum):
                out.append(
                    f"{name} ({_a2.CAP_ROLE}): bound {param}="
                    f"{float(value):.6g}u exceeds this PDK's {param}max="
                    f"{float(maximum):.6g}u")
    return out


def _validate_ir(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                 project: Optional[Path] = None) -> List[str]:
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
    elif project is not None:
        # A path that resolves to nothing is NOT the same as no path. Writing
        # a `.lib` line for a file that is not there produces a deck whose
        # only failure mode is ngspice's own `Could not find library file`,
        # 200 lines into a sweep log — and that sentence reads as a defect of
        # the design. Named here instead, at emission, with the path in it.
        #
        # ONLY for a library the PROJECT itself carries. This producer runs on
        # the HOST and the deck runs in a CONTAINER, so an installed PDK under
        # `/foss/pdks/...` is legitimately absent here and present at
        # simulation time. MEASURED: checking every path refused 9 of the
        # emitter's own fixtures, which name exactly such a path. "I cannot
        # see it" is not "it is not there" — the check is confined to the one
        # tree this process can actually speak about.
        for _lib in ([dl[0] for dl in (pdkctx.get("deck_loads") or [])
                      if len(tuple(dl)) == 2]
                     or [pdkctx["model_lib"]]):
            _lp = Path(str(_lib))
            if not _lp.is_absolute():
                continue
            try:
                _lp.relative_to(project)
            except ValueError:
                continue        # outside the project — not ours to judge
            if not _lp.is_file():
                problems.append(
                    f"model library `{_lib}` is inside this project but no "
                    f"such file exists; a `.lib` line pointing at nothing "
                    f"is MODEL_LIB_ABSENT")
    return problems


def _portable_lib_path(lib: str, deck_dir: Optional[Path]) -> str:
    """The `.lib` path a COPIED project can still resolve.

    NOT WIRED INTO THE EMITTER, AND THE REASON IS THE FINDING. Measured
    2026-09-06 on the front door, twice: with the deck's `.lib` made
    project-relative, A3 refuses to emit either block and A4-A7 go BLOCKED
    behind it, because the deck is verified in TWO staging locations that
    carry no `input/` -

      * `verify_with_checkers` - a host `tempfile.TemporaryDirectory()`
        holding only the deck, its sidecar and a block list;
      * `verify_with_ngspice` - a FLAT `/tmp/a3emit_<block>_<ts>` INSIDE the
        container, into which exactly two files are `docker cp`'d.

    An absolute path resolves from both by accident, so both staging sites had
    been getting the right answer for the wrong reason for as long as the
    defect existed - and a staging tree that omits an input the artefact
    depends on cannot detect any defect in how that dependency is expressed.
    Making the emitted deck portable therefore requires making BOTH staging
    sites reproduce the directory relationship the deck names, which is a
    larger change than this function; it is reported rather than half-landed.
    This helper and its test stay so the next author starts from the measured
    ngspice behaviour instead of re-deriving it.

    The deck used to carry the emitting host's ABSOLUTE path
    (`/home/<user>/<lane>/proj/input/pdk/models/cornerCAP.lib`). Copy the
    project anywhere — another lane, another host, a container with a
    different mount — and every deck in it names a file that is not there.
    MEASURED 2026-09-06: a probe on a copy of another lane's project died
    with `Could not find library file .../cornerCAP.lib`, and the failure
    reads as "this design has no models", not as "this path was baked in".

    MEASURED in ngspice-47 (image 0.3.46, same day): a RELATIVE `.lib` path
    is resolved against the directory of the FILE carrying the directive,
    not the process CWD — `ngspice -b /abs/deck.sp` run from `/tmp` still
    resolved `../models/tiny.lib`. So a project-internal library can be
    named relatively and the deck stays runnable wherever it is copied.

    A library OUTSIDE the project is a host INSTALLATION, not part of the
    design. Relativising that would make the deck depend on where the
    project happens to sit relative to the install root, which is the same
    defect pointed the other way, so those keep their absolute path.
    """
    if not lib or deck_dir is None:
        return lib
    try:
        libp = Path(lib)
        if not libp.is_absolute():
            return lib
        project = _project_root_of(deck_dir)
        if project is None:
            return lib
        libp.relative_to(project)          # raises when outside the project
        return os.path.relpath(str(libp), str(deck_dir))
    except (ValueError, OSError):
        return lib


def _project_root_of(deck_dir: Path) -> Optional[Path]:
    """The project root a per-block deck directory sits under, i.e. the
    parent of the `phase3/analog/<block>[/sizing_loop]` chain. Derived by
    walking up to the directory that holds `input/`, so it does not depend
    on how deep the deck is nested."""
    for cand in [deck_dir, *deck_dir.parents]:
        if (cand / "input").is_dir() and (cand / "phase3").is_dir():
            return cand
    return None


def render_netlist(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                   prov_lines: List[str],
                   overrides: Dict[str, Dict[str, float]],
                   deck_dir: Optional[Path] = None) -> str:
    # `deck_dir` is the directory the deck will be written to, and the `.lib`
    # card is written RELATIVE to it for a library the project itself
    # carries — see `_portable_lib_path` for the measured ngspice behaviour
    # and `stage_deck_inputs` for the two staging sites that had to reproduce
    # the project's shape before this was emittable. A library outside the
    # project is a host installation and keeps its absolute path.
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
    # The prelude precedes the `.lib` line: ngspice resolves parameters in read
    # order, and without it a device whose body references a global switch stops
    # the run at `Undefined parameter [...]` before any analysis.
    for _pre in (pdkctx.get("deck_prelude") or []):
        L.append(f".include {_portable_lib_path(str(_pre), deck_dir)}")
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
            L.append(f".lib {_portable_lib_path(lib, deck_dir)} "
                     f"{sec}".rstrip())
    else:
        L.append(f".lib {_portable_lib_path(pdkctx['model_lib'], deck_dir)} "
                 f"{section}".rstrip())
    L.append("")
    L.append(f".subckt {block} {' '.join(ir['ports'])}")
    for d in ir["devices"]:
        model = pdkctx["role_models"][d["role"]]
        parts = [f"x{d['name']}"] + list(d["nets"]) + [model]
        # THE NAME THE SUBCKT ITSELF GIVES THE DIMENSION. `w=`/`l=` is the MOS
        # spelling; a foundry passive commonly declares `r_width`/`r_length` or
        # `c_width`/`c_length` and defaults them to bare `w`/`l`, which no deck
        # defines — so emitting `w=` there passes an undeclared parameter AND
        # leaves the real geometry at an undefined default. The resolver reads
        # the names off the subckt's own header; a role it says nothing about
        # keeps `w=`/`l=` exactly as before.
        _gp = (pdkctx.get("geometry_params") or {}).get(d["role"]) or {}
        for p in ("w", "l"):
            v = (overrides.get(d["name"], {}).get(p, d.get(p)))
            if v is None:
                continue
            _name = _gp.get(p, p)
            parts.append(f"{_name}={_fmt(float(v))}u" if metric
                         else f"{_name}={_fmt(float(v))}")
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


# ── the integration control the emitted testbench carries ─────────────────
# MEASURED (lane czdsm, 2026-09-07, 8HD-6, image vibeic-eda 0.3.47
# sha256:8da785a8…, ngspice-47): the A3 testbench used to carry NO `.options`
# card at all, so every deck this producer verified ran on ngspice's SPICE3
# default `trtol = 7`. On the `delta_sigma` block of a real project that
# default ABORTS the transient:
#
#     doAnalyses: TRAN: Timestep too small; time = 2.61293e-05,
#     timestep = 4.87367e-21: trouble with node "xdut.nbias"
#
# and A3 then deleted a netlist that had passed all five static checkers,
# wrote `NETLIST_NOT_SIMULATABLE`, and left A4..A7 BLOCKED on "no *.sp".
#
# THE NODE IN THE MESSAGE IS THE MESSENGER, NOT THE FAULT. `nbias` was
# measured, isolated and in circuit, to carry 41.13 uA from a 17.32 kohm
# bias resistor into the diode-connected mirror reference, to sit at
# 0.487795 V with roughly 830 ohm of small-signal impedance, and to move
# 2.6 mV over the 33 clock cycles before the abort. Held at that potential
# by an ideal source it stops being named and the same abort reappears on
# `xdut.ntail_cm`. It is not floating and no netlist change reaches it.
#
# `trtol` IS NOT AN ACCURACY TOLERANCE — it is the factor the local
# truncation error bound is MULTIPLIED by when the next timestep is chosen,
# so a smaller value asks for a SMALLER step and a TIGHTER error. Emitting it
# is therefore the opposite of a relabel, and the measurement says so in both
# directions: LOOSENING (reltol 1e-2 / abstol 1e-10 / vntol 1e-5) fails
# SOONER, at 14.05 us; the four idioms that could hide a singularity all fail
# too (rshunt 1e12 -> 143.1 us, gmin 1e-9 -> 87.3 us, method=gear -> 38.2 us,
# itl4=100 -> byte-identical to the default at 26.13 us); trtol 3 -> 8.97 us
# and trtol 2 -> 24.57 us still fail; trtol 1 COMPLETES all 399251 ns and the
# modulator's own measurement comes out real (density 0.4344, swing 1.0659).
#
# IT IS THE INTEGRATION, NOT THE DECK. Under the default the abort time is
# not a property of the circuit at all — halving the maximum step moves it
# from 26.13 us to 203.54 us and quartering it to 145.44 us, non-monotonically.
# Under `trtol=1` the run COMPLETES at both steps and answers the same:
# density 0.434376 at 3.89894 ns and 0.436314 at 1.94947 ns, swing 1.06594
# and 1.06597. Every quiescent node agrees with the default-trtol run to five
# decimals over the window that run reached (nbias 0.48779 both, vcm 0.58996
# both, nd2_cm 0.42144 vs 0.42142): the physics is the same, computed with
# the error control the deck always needed.
#
# It is emitted for EVERY block this producer renders, not for the class that
# was measured: a per-block-type options table is the template table this
# program exists to not be, and an integration control is a property of the
# SIMULATOR and of this producer's own verification, never of the design.
_TB_INTEGRATION_OPTIONS = (
    "* the integration control this producer verifies under — see "
    "`_TB_INTEGRATION_OPTIONS`",
    ".options trtol=1",
)
#: ngspice / SPICE3 ship `trtol = 7`. A value at or above it asks for a step
#: at least as large as the default and so verifies nothing; the guard in
#: `test_a3_testbench_carries_integration_control` holds the emitted card
#: strictly below it rather than to the literal 1, so tightening it further
#: stays legal and silently dropping it cannot.
_NGSPICE_DEFAULT_TRTOL = 7.0

#: The instance name the emitted testbench gives the block. Stated ONCE:
#: `transient_rail_measurement` writes `v(<instance>.<net>)` cards and
#: `render_testbench` writes the instance line, and a literal in each is free
#: to drift into a deck whose measurements name a device that is not there --
#: which ngspice reports as `no such vector` and then measures nothing, on a
#: run that still exits 0.
_TB_DUT_INSTANCE = "xdut"

#: The prefix every transient rail measurement this producer emits carries.
#: It is what makes the emitter's cards and the consumer's rows the SAME
#: population: `transient_rail_measurement` writes it and
#: `tran_rail_report` reads it, so a renamed prefix cannot leave the reader
#: silently matching nothing and reporting a clean transient.
_RAIL_MEAS_PREFIX = "railx"


# ── the transient rail measurement the emitted testbench carries ──────────
# WHY A `.meas` CARD AND NOT THE OPERATING-POINT TABLE (vibe-ic#2077).
#
# MEASURED (lane czdsm3, 2026-09-07): `delta_sigma` put +3.34 V and +2.99 V on
# its own internal nodes on a block powered between 0 and 1.2 V, and the
# operating point was CLEAN throughout -- `nn1` and `nn2` sit at 6.8e-07 V and
# at 0.036 / 1.055 V in the same run. So `dc_op_rail_excursions`, which reads
# the table ngspice prints above the analysis, could never have seen it: the
# excursion lives in the TRANSIENT, and reproduces to three figures by
# deleting the `.options trtol=1` card above. Nobody read it either, because
# the emitted testbench measured the block's OUTPUT and nothing else; the
# excursion was visible only by opening the waveform by hand.
#
# THE COST THAT WAS PAID FOR IT. czdsm3 chose byte-identity of the emitted
# decks over adding cards, which is why this landed as an open issue rather
# than as part of that change. The decks DO differ now, and every deck says so
# in its own provenance (`transient_rail_measurement=`) rather than differing
# quietly -- including the decks that get NO cards, which state why.
#
# WHY IT IS EMITTED FOR EVERY BLOCK AND EVERY INTERNAL NET. A per-class list of
# "interesting" nodes is the template table this producer exists to not be, and
# the node that went out of range here was not one anybody would have listed.
# The population is the IR's own `internal_nets`, so a class added later is
# covered by construction.
#
# WHY ONLY A DECK THAT RUNS A TRANSIENT. `meas tran` reads the vector a
# transient produced; on the `op`-only decks in this library (`ldo`, `pull`)
# it has nothing to read and ngspice answers `no such vector`. An absent
# measurement that is NAMED as absent is honest; one that is emitted and fails
# would be 2N error lines per deck and a reader with no way to tell that from
# a node that really could not be measured.
def _control_runs_a_transient(control_lines: Any) -> bool:
    """True when the deck's own `.control` block issues a transient analysis.

    Read off the control lines THIS producer is about to write, not off the
    IR's `analyses_implied` -- the cards have to follow the analysis that
    actually runs, and those are two different declarations that have been
    measured to disagree (`ldo` implies `op`, `dc` and `ac` and runs `op`)."""
    for ln in (control_lines or []):
        if not isinstance(ln, str):
            continue
        head = ln.strip().split()
        if head and head[0].lower() == "tran":
            return True
    return False


def transient_rail_measurement(ir: Dict[str, Any]
                               ) -> Tuple[List[str], str]:
    """`(cards, provenance)` for the block's transient rail measurement.

    ONE function for both, deliberately: the cards and the sentence the deck
    makes about them cannot then disagree, and a deck that gets NO cards still
    carries a sentence saying which of the three reasons applies. "Could not
    measure it" and "measured it and it was inside the rails" are different
    answers, and this is the first half of keeping them apart -- the second is
    `tran_rail_report`, which grades what came back against what was asked."""
    tb = ir.get("testbench")
    if not isinstance(tb, dict):
        return [], ("transient_rail_measurement=none (the topology IR "
                    "declares no testbench, so no deck is emitted to measure)")
    if not _control_runs_a_transient(tb.get("control")):
        return [], ("transient_rail_measurement=none (this deck runs no "
                    "transient, so there is no transient to measure; its "
                    "operating point is still graded by "
                    "`dc_op_rail_excursions`)")
    rails = {v for v in (ir.get("rails") or {}).values() if isinstance(v, str)}
    nets = [n for n in (ir.get("internal_nets") or [])
            if isinstance(n, str) and n and n not in rails]
    if not nets:
        return [], ("transient_rail_measurement=none (the topology IR "
                    "declares no internal net for this block)")
    cards: List[str] = []
    for n in nets:
        node = f"{_TB_DUT_INSTANCE}.{n}"
        cards.append(f"meas tran {_RAIL_MEAS_PREFIX}_max_{n} max v({node})")
        cards.append(f"meas tran {_RAIL_MEAS_PREFIX}_min_{n} min v({node})")
    return cards, (
        f"transient_rail_measurement={len(nets)} internal node(s), max and "
        f"min over the whole transient, refused outside this block's own "
        f"rails by `tran_rail_report` at a margin of "
        f"{TRAN_RAIL_MARGIN_FRACTION} x the supply the deck drives")


def _current_load(tb: Dict[str, Any], spec: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """Bind an IR-declared current load to its source nominal and SI unit."""
    load = tb.get("current_load")
    if not isinstance(load, dict):
        return [], None
    key = str(load.get("spec") or "")
    rows = spec.get("specs") or []
    row = next((row for row in rows if isinstance(row, dict)
                and str(row.get("name") or "").casefold() == key.casefold()), None)
    if row is None:
        return list(load.get("fallback_cards") or []), load.get("fallback_condition")
    value = next((row[field] for field in ("target", "typ", "value")
                  if isinstance(row.get(field), (int, float)) and not isinstance(row[field], bool)
                  and math.isfinite(row[field])), None)
    if value is None:
        raise ValueError(f"CURRENT_LOAD_UNBOUND: {key} has no finite source nominal target/typ/value")
    unit = next((str(row[field]).strip().replace("µ", "u").replace("μ", "u")
                 for field in _UNIT_KEYS if row.get(field) is not None), "")
    # Keep SI prefixes case-sensitive: mA and MA have different magnitudes.
    scales = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "k": 1e3, "M": 1e6}
    scale = scales.get(unit[:-1]) if unit[-1:].lower() == "a" else None
    if scale is None:
        raise ValueError(f"CURRENT_LOAD_UNBOUND: {key} has unsupported source current unit {unit!r}")
    amps = float(value) * scale
    if not math.isfinite(amps):
        raise ValueError(f"CURRENT_LOAD_UNBOUND: {key} current unit conversion is non-finite")
    card = f"{load['instance']} {load['positive']} {load['negative']} {_fmt(amps)}"
    return [card], f"load = {_fmt(amps)} A (source {key} nominal {value:g} {unit}; current sink)"


def render_testbench(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                     env: Dict[str, Any], prov_lines: List[str], spec: Optional[Dict[str, Any]] = None
                     ) -> Tuple[Optional[str], Dict[str, Any], List[str]]:
    """Returns (text, tb_env, notes). None when the IR declares no testbench —
    an honest absence, not an invented stimulus."""
    tb = ir.get("testbench")
    if not isinstance(tb, dict):
        return None, {}, ["the topology IR declares no testbench"]
    block = ir["block"]
    notes: List[str] = []
    try:
        load_cards, load_condition = _current_load(tb, spec or {})
    except ValueError as exc:
        return None, {}, [str(exc)]
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
    if load_condition:
        L.append(f"* condition: {load_condition}")
    L.append(f".include {block}.sp")
    for ln in tb.get("stimulus") or []:
        L.append(ln.format(**fmt))
    ports = []
    for p in ir["ports"]:
        ports.append("0" if p == (ir.get("rails") or {}).get("vss") else p)
    L.append(f"{_TB_DUT_INSTANCE} {' '.join(ports)} {block}")
    for ln in tb.get("cards") or []:
        L.append(ln.format(**fmt))
    L.extend(load_cards)
    # TOP LEVEL, before `.control`: an `.options` card inside a `.control`
    # block is a `ngspice` interactive command, not a circuit option, and the
    # analysis that follows would still run on the default.
    L.extend(_TB_INTEGRATION_OPTIONS)
    L.append(".control")
    for ln in tb.get("control") or []:
        L.append(ln.format(**fmt))
    # AFTER the analysis and INSIDE `.control`: `meas tran` reads the vector
    # the transient above produced, so the same cards one block higher measure
    # nothing at all — the mirror image of the `.options` placement rule a few
    # lines up, and the two are wrong in opposite directions.
    _rail_cards, _rail_prov = transient_rail_measurement(ir)
    if _rail_cards:
        L.append("* the transient rail measurement this producer refuses on "
                 "— see `transient_rail_measurement`")
        L.extend(_rail_cards)
    L.append(".endc")
    L.append(".end")
    L.append("")
    text = "\n".join(L)

    # THE POWER-ON SEQUENCE (lane icadc, 2026-09-15). MEASURED: the deck this
    # producer renders for a CLOCKED block puts the supply at full rail and
    # starts the clock at t=0, so ngspice has to SOLVE a DC operating point
    # for a bias the clocked loop itself establishes. At the nominal corner it
    # does; at SS/-40 C on `delta_sigma` it exhausted all five homotopies in
    # 20.7 s ("trouble with node \"xdut.nbias\"", `tran simulation(s)
    # aborted`) and the corner yielded NOTHING. The same deck with the rail
    # ramped from 0 and the first clock edge held one period converges
    # ("Dynamic gmin stepping completed") and runs. This is NOT `uic` — see
    # `analog_poweron_sequence`, whose docstring keeps the `delta_sigma`
    # entry's own measured reason for forbidding `uic` and explains why a rail
    # that starts at 0 V is a SOLVED operating point rather than an unsolved
    # initial condition.
    #
    # The transform REFUSES BY NAME on a deck it must not touch — an `op`-only
    # deck (`no_transient`) and an unclocked block (`no_clock_source`) both
    # keep the deck they had, byte for byte — so this cannot reach a block
    # that has no clocked loop to bring up.
    _rail = (ir.get("rails") or {}).get("vdd")
    if isinstance(_rail, str) and _rail:
        text, _po = _poweron.apply(text, _rail)
        notes.append(_po.get("provenance")
                     or f"poweron_sequence=not applied: {_po.get('refused')}")
        e["poweron_sequence"] = _po
    else:
        notes.append("poweron_sequence=not applied: the topology IR declares "
                     "no `vdd` rail to bring up")

    # THE VECTOR RETENTION (lane icadc, 2026-09-15). MEASURED on ONE deck in
    # two arms differing by exactly the `.save` line: without it ngspice
    # retains every internal node's full time vector and grows at 3784 kB per
    # microsecond of simulated time against 542 kB with it — ~52 GB against
    # ~7.5 GB over the conversion record this producer's own deck runs. The
    # 7.5 GB arm was checked against an independent two-day run of the same
    # circuit (measured 7.22 GiB at 11.8 ms). A validation sim that needs 52 GB
    # is how a shared host freezes.
    #
    # It retains EXACTLY the vectors this deck's own meas/wrdata/print cards
    # read — derived from the text above, including the rail cards
    # `transient_rail_measurement` just wrote — so the measurement is unchanged
    # and a block that gains a measurement gains its retention in the same
    # breath. Applied AFTER the rail cards on purpose: retaining a node the
    # deck measures is the requirement, and those cards are part of the deck.
    text, _vr = _retain.apply(text)
    notes.append(_vr.get("provenance")
                 or f"vector_retention=not applied: {_vr.get('refused')}")
    e["vector_retention"] = _vr
    return text, e, notes


# ── self-verification ─────────────────────────────────────────────────────
_CHECKERS = (
    ("a3_gate", "analog_a3_netlist_gen_check.py", True),
    ("pdk", "analog_netlist_pdk_check.py", False),
    ("connectivity", "analog_netlist_connectivity_check.py", False),
    ("include_order", "analog_netlist_include_order_check.py", False),
    ("path_lint", "analog_netlist_path_lint.py", False),
)


#: A `.lib <path> [section]` card, as this emitter writes it.
_LIB_CARD_RE = re.compile(r"(?im)^\s*\.lib\s+(\S+)")


def deck_libs(sp_text: str) -> List[str]:
    """Every library path the deck names, in the order it names them."""
    return _LIB_CARD_RE.findall(sp_text or "")


def stage_deck_inputs(sp_text: str, real_project: Optional[Path],
                      root: Path, deck_dir_rel: str,
                      real_deck_dir: Optional[Path] = None
                      ) -> Tuple[List[str], List[Dict[str, str]]]:
    """Reproduce, under `root`, the directory relationship the deck NAMES.

    THE DEFECT THIS CLOSES, MEASURED (czadc28, 2026-09-06, and re-measured
    here). A3 verifies its deck in two staging sites and NEITHER carried the
    project's `input/`: a host TemporaryDirectory holding only the deck, its
    sidecar and a block list, and a FLAT `/tmp/a3emit_<block>_<ts>` in the
    container holding exactly two files. An ABSOLUTE `.lib` path resolves
    from both by accident, so both had been getting the right answer for the
    wrong reason for as long as the defect existed — and a staging tree that
    omits an input the artefact depends on cannot detect ANY defect in how
    that dependency is expressed. With the path made deck-relative and the
    staging left as it was, A3 refused to emit either block and A4-A7 went
    BLOCKED behind it.

    So the staging site reproduces the shape: every library the deck names
    that lives INSIDE the project is materialised at the SAME path relative
    to the project root, which is what makes `input/` exist in the staging
    tree and a relative `.lib` resolvable there. A library OUTSIDE the
    project is a host INSTALLATION and is left alone — it is not the
    project's to carry, and relativising it would be the same defect pointed
    the other way.

    Returns (staged relative paths, unstageable entries). An entry this
    function cannot stage is NAMED and returned, never dropped: "I could not
    put it there" is not "it did not need to be there".
    """
    staged: List[str] = []
    missing: List[Dict[str, str]] = []
    deck_dir = root / deck_dir_rel
    if real_deck_dir is None and real_project is not None:
        real_deck_dir = real_project / deck_dir_rel
    for lib in deck_libs(sp_text):
        libp = Path(lib)
        if not libp.is_absolute():
            # DECK-RELATIVE, which is what this emitter now writes for a
            # library the project carries. Its SOURCE is that path resolved
            # against the deck's directory in the REAL project; it is staged
            # at the same place relative to this root, so the deck resolves
            # here exactly as it will on disk. Already resolvable (a caller
            # that staged it itself) is fine and is not re-staged.
            if (deck_dir / lib).is_file():
                continue
            src = ((real_deck_dir / lib).resolve()
                   if real_deck_dir is not None else None)
            if src is None or not src.is_file():
                missing.append({"lib": lib, "why": (
                    f"a deck-relative library that does not resolve from the "
                    f"deck's own directory"
                    + (f" in the project ({src})" if src is not None
                       else " and no project root was given to resolve it "
                            "against"))})
                continue
            libp = src
        if real_project is None:
            continue
        try:
            rel = libp.relative_to(real_project)
        except ValueError:
            continue            # a host installation, not the project's
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            staged.append(str(rel))
            continue
        try:
            os.link(str(libp), str(dst))
        except OSError:
            try:
                shutil.copyfile(str(libp), str(dst))
            except OSError as exc:
                missing.append({"lib": lib, "why": (
                    f"the project carries this library but it could not be "
                    f"staged: {exc}")})
                continue
        staged.append(str(rel))
    return staged, missing


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
                                            "producer_fingerprint":
                                                producer_fingerprint(),
                                            "design_content": design_content}}),
                encoding="utf-8")
        if tb_text:
            (bdir / f"tb_{block}.sp").write_text(tb_text, encoding="utf-8")
        # THE SHAPE THE DECK NAMES, not a subset of it. See
        # `stage_deck_inputs`: without the project's own `input/` under this
        # root, a deck-relative `.lib` cannot be resolved here and this site
        # cannot tell a portable deck from an unportable one.
        staged, unstageable = stage_deck_inputs(
            sp_text, real_project, proj,
            f"{_CANONICAL_ANALOG}/{block}",
            real_deck_dir=(real_project / _CANONICAL_ANALOG / block
                           if real_project is not None else None))
        ok = True
        if staged:
            findings.append({"checker": "deck_inputs_staged", "rc": 0,
                             "detail": "staged " + ", ".join(sorted(staged))})
        for entry in unstageable:
            ok = False
            findings.append({
                "checker": "deck_inputs_staged", "rc": 1,
                "detail": (f"`.lib {entry['lib']}` cannot be resolved from "
                           f"the staged deck: {entry['why']}")})
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
    """Can this process actually run something in `container`?

    A `ContainerImageMismatch` is caught HERE and answered `False` — vibe-ic
    #2156. It is a `RuntimeError` raised by the guarded argv builder when the
    container is the wrong image, and it was in no `except` clause on this path,
    so it escaped `verify_with_ngspice` and every caller above it: an operator
    with a stale container got a traceback where the flow documents a capability
    gap. The REASON is not lost by answering False — `container_image_refusal`
    below is what the caller reports, and it is a different status from an
    absent container because they are different facts, and
    `container_refusal_result` is the ONE place that record is composed.
    """
    try:
        cp = _pr.run_best_effort(_ce.docker_exec_argv(container, "true"),
                            capture_output=True, text=True)
        return cp.returncode == 0
    except _ce.ContainerImageMismatch:
        return False
    except (OSError, subprocess.SubprocessError):
        return False


def container_image_refusal(container: str) -> str:
    """The refusal when `container` PROVABLY runs bytes other than the pinned
    ones, else "".

    Delegated to `_eda_pin.container_attach_refusal`, which is the one place
    that judgement is made: a digest that could NOT be read is not a mismatch
    and must not be reported as one, so an unreadable container falls through
    to the ordinary unreachable path below and docker reports its own failure.
    """
    return _pin.container_attach_refusal(container)

#: The simulation status when the container this producer was told to use is
#: PROVABLY not the pinned image, so NOTHING was run in it (vibe-ic#2076).
#:
#: SPELLED APART FROM `NOT_VERIFIED_NO_SIMULATOR` ON PURPOSE, and the distance
#: between them is the whole point. "The simulator is not installed" is a
#: capability gap this flow already knows how to carry: the deck is emitted
#: with `simulation_verified: false` and a reader knows no simulator existed.
#: "The container is running a toolchain the repo does not name" is a
#: different fact — a simulator WAS there and WAS usable, and using it would
#: have produced a verdict about a tool version nobody pinned. The first is a
#: measurement that could not be taken; the second is a measurement that must
#: not be taken.
CONTAINER_IMAGE_MISMATCH_STATUS = "NOT_VERIFIED_CONTAINER_IMAGE_MISMATCH"


def container_refusal_result(why: str) -> Dict[str, Any]:
    """The `verify_with_ngspice` result for a refused container.

    `env_refused` is the machine-readable half — `emit_for_block` routes on it
    rather than on the status string — and `detail` carries the refusal's OWN
    line, which names both digests and is therefore actionable without a
    second lookup.
    """
    return {"simulation_verified": False,
            "simulation_status": CONTAINER_IMAGE_MISMATCH_STATUS,
            "env_refused": True,
            "detail": str(why).strip()}


#: How far outside a rail a node may sit before the operating point is called
#: wrong. A junction that is genuinely forward-biased on a diode-connected tap
#: sits a few hundred millivolts up; a node the solver put outside the rails
#: because nothing in the circuit holds it there is out by VOLTS. The margin is
#: a FRACTION of the block's own supply, not a millivolt constant, so the same
#: rule reads a 1.2 V core and a 5 V I/O domain the same way. Tool/PDK/chip-
#: AGNOSTIC.
DC_OP_RAIL_MARGIN_FRACTION = 0.25

#: `<name> <value>` rows of the operating-point table ngspice prints on every
#: `-b` run ("Initial Transient Solution" / the `op` node table). A branch
#: current row (`v_vdd#branch`) is NOT a node voltage and is excluded by name.
_OP_ROW_RE = re.compile(
    r"^\s*([A-Za-z_][\w.:\[\]]*)\s*=?\s+"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$")


def dc_op_rail_excursions(log_text: str, supply_v: Optional[float]
                          ) -> List[Tuple[str, float]]:
    """INTERNAL node voltages the OPERATING POINT put outside the block's rails.

    THE INVARIANT: a node of a block powered between 0 and `supply_v` cannot
    sit meaningfully above `supply_v` or below 0 at DC. Nothing in the circuit
    can hold it there, so a solution that says it does is a solution about
    nothing -- and it is a solution every downstream number was then computed
    from. Until now no gate in this flow ever looked: the emitted testbench
    measures the block's OUTPUT, and the operating point the simulator prints
    immediately above those measurements was read by nobody.

    READS THE SIMULATOR'S OWN OUTPUT, ADDS NO CARD. The table is printed
    unconditionally by `ngspice -b`, so this costs no simulator time and --
    the load-bearing part -- every emitted deck stays byte-identical, which a
    `.meas`-card implementation could not have promised.

    Returns [(node, volts), ...] sorted worst-first; empty when the operating
    point is inside the rails OR when there is nothing to judge against
    (`supply_v is None`, no table in the log). The caller distinguishes those
    two -- see `rail_invariant` in the sidecar -- because "checked and clean"
    and "could not check" are different answers and this list cannot tell them
    apart on its own."""
    if not isinstance(supply_v, (int, float)) or supply_v <= 0:
        return []
    margin = abs(float(supply_v)) * DC_OP_RAIL_MARGIN_FRACTION
    hi, lo = float(supply_v) + margin, -margin
    worst: Dict[str, float] = {}
    for raw in (log_text or "").splitlines():
        m = _OP_ROW_RE.match(raw)
        if not m:
            continue
        name = m.group(1)
        if "#branch" in name or name.lower() in ("temp", "tnom"):
            continue
        # INTERNAL TO THE BLOCK, which is what the invariant is about. A node
        # inside the device under test is printed with its instance prefix
        # (`xdut.…`); a bare name is a TESTBENCH node. Judging those against
        # the block's core supply would refuse every design whose stimulus
        # legitimately sits in another domain — an I/O rail, a boost node, a
        # reference above the core — and MEASURED here, the one node a raised
        # reference puts out of range first is the testbench source itself.
        if "." not in name:
            continue
        try:
            v = float(m.group(2))
        except ValueError:
            continue
        if v > hi or v < lo:
            # The same node appears once per printed operating point (a run
            # with several analyses prints several); keep the worst.
            if abs(v) > abs(worst.get(name, 0.0)):
                worst[name] = v
    return sorted(worst.items(), key=lambda kv: -abs(kv[1]))


#: How far outside a rail an internal node may go AT ANY POINT IN THE
#: TRANSIENT before the run is refused. A FULL SUPPLY of headroom on each
#: side, i.e. four times the DC margin, and the width is the argument:
#:
#:   * a transient legitimately goes where a DC operating point cannot. Every
#:     bootstrap, charge-pump and clock-coupled node in this library's classes
#:     is DESIGNED to reach about twice its own rail for part of a cycle, and a
#:     rule that refuses those refuses working circuits.
#:   * a node that reaches TWICE the supply because nothing holds it there
#:     keeps going. MEASURED on the block this bound was written for: 3.34 V
#:     on a 1.2 V rail — 2.78x the supply, i.e. clear of a 2x bound by more
#:     than half a supply, not by a rounding.
#:
#: So the bound is set where a designed excursion ends and an unheld one does
#: not, and it is a FRACTION of the block's own supply for the same reason the
#: DC one is: the same rule then reads a 1.2 V core and a 5 V I/O domain.
#: Tool/PDK/chip-AGNOSTIC.
TRAN_RAIL_MARGIN_FRACTION = 1.0

#: One answered `meas` row, as ngspice-47 prints it. TWO SPELLINGS, measured
#: in the pinned image: a short name is padded to a column and the `=` is a
#: separate token (`railx_max_mid            =  4.40543e-01 at=  1.5185e-07`),
#: a long one runs straight into it (`railx_max_<32 chars>=  4.40543e-01
#: at=  …`). `\s*=` covers both. The trailing `at=` is deliberately NOT
#: required: a measurement that came back is a measurement whether or not this
#: build prints where it happened.
_RAIL_MEAS_ROW_RE = re.compile(
    r"^\s*" + _RAIL_MEAS_PREFIX + r"_(max|min)_(\S+?)\s*=\s*"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b")

#: One EMITTED card, read back off the deck. The requested population is taken
#: from the deck rather than recomputed from the IR so that the consumer grades
#: what the simulator was actually asked, and a card the emitter never wrote
#: cannot be counted as a node that came back clean.
_RAIL_MEAS_CARD_RE = re.compile(
    r"^\s*meas\s+tran\s+" + _RAIL_MEAS_PREFIX +
    r"_(?:max|min)_(\S+)\s+(?:max|min)\s", re.IGNORECASE)


def rail_meas_nodes_requested(tb_text: Optional[str]) -> List[str]:
    """Every internal node the EMITTED testbench asks a rail measurement for.

    Read off the deck, so `tran_rail_report` can compare MEMBERSHIP — asked
    against answered — instead of counting rows. A `meas` ngspice refuses
    (`no such vector`) prints an error and the run still exits 0, so a reader
    that only collected the rows it got would report a clean transient for a
    block none of whose nodes were measured at all."""
    seen: Dict[str, None] = {}
    for raw in (tb_text or "").splitlines():
        m = _RAIL_MEAS_CARD_RE.match(raw)
        if m:
            seen.setdefault(m.group(1).lower(), None)
    return list(seen)


def tran_rail_report(log_text: str, supply_v: Optional[float],
                     requested: Optional[List[str]] = None
                     ) -> Dict[str, Any]:
    """INTERNAL nodes the TRANSIENT put outside the block's rails.

    THE INVARIANT, AND HOW IT DIFFERS FROM THE DC ONE. `dc_op_rail_excursions`
    asks whether the SOLUTION the solver settled on is one the circuit holds.
    This asks whether the block STAYED inside its own rails while it ran —
    which is a different question with a different answer, measured: the block
    this was written for had a clean operating point on every node and put
    +3.34 V on two of them during the transient (vibe-ic#2077).

    READS THE MEASUREMENTS THE DECK ASKED FOR, and says which it did not get.
    Returns `invariant` = CHECKED / NOT_MEASURED_NO_SUPPLY / NOT_MEASURED_NO_CARDS,
    `excursions` worst-first, and the asked-against-answered split. An empty
    `excursions` is NOT on its own a claim that the transient was checked — the
    caller reads `invariant` and `nodes_not_measured`, exactly as it already
    does for the DC table."""
    req = [n.lower() for n in (requested or [])]
    if not req:
        return {"invariant": "NOT_MEASURED_NO_CARDS", "excursions": [],
                "nodes_measured": [], "nodes_not_measured": []}
    if not isinstance(supply_v, (int, float)) or supply_v <= 0:
        return {"invariant": "NOT_MEASURED_NO_SUPPLY", "excursions": [],
                "nodes_measured": [], "nodes_not_measured": sorted(req)}
    margin = abs(float(supply_v)) * TRAN_RAIL_MARGIN_FRACTION
    hi, lo = float(supply_v) + margin, -margin
    answered: Dict[str, None] = {}
    worst: Dict[str, float] = {}
    for raw in (log_text or "").splitlines():
        m = _RAIL_MEAS_ROW_RE.match(raw)
        if not m:
            continue
        node = m.group(2).lower()
        try:
            v = float(m.group(3))
        except ValueError:
            continue
        answered.setdefault(node, None)
        if v > hi or v < lo:
            # `max` and `min` of the same node are two rows; keep the one that
            # is further outside, so the node is reported once with its worst.
            if abs(v) > abs(worst.get(node, 0.0)):
                worst[node] = v
    return {
        "invariant": "CHECKED",
        "excursions": sorted(worst.items(), key=lambda kv: -abs(kv[1])),
        "nodes_measured": sorted(answered),
        "nodes_not_measured": sorted(set(req) - set(answered)),
    }

#: THE RECORDED BUDGET for one A3 testbench run. It stops NOTHING
#: (vibe-ic#2051): crossing it prints one `VIBEIC_CEILING_CROSSED` line and the
#: simulator runs on. It is the 900 s this call used to be KILLED at, kept as
#: the number a reader is told about rather than deleted -- MEASURED on the
#: delta-sigma modulator testbench, ~14 m 50 s on a loaded host, i.e. the old
#: clock was a coin toss and losing it reported a simulator that RAN as a
#: simulator that was ABSENT (vibe-ic#2117, and the landing that preceded it).
#: A crossing is therefore EXPECTED on a big block and is information, not a
#: fault.
SIMULATION_CEILING_S = 900.0


#: The A3 VERIFY window, and the ONE reason it is not the deck's own record.
#:
#: A3's verification asks exactly three questions and no others: did the run
#: converge, does the OPERATING POINT put a node outside the supply rails, and
#: does the TRANSIENT. It never decodes the bitstream, never compares against
#: the applied level or tone, and never computes SNDR or ENOB -- see
#: `tran_rail_report`, whose own docstring says it "asks whether the block
#: STAYED inside its own rails while it ran". So the span it needs is the span
#: over which that claim is settled, not the span the GRADED spec asks for.
#:
#: MEASURED (lane icadc2, 8hd-3, the emitted delta_sigma over four conversion
#: windows), cumulative worst excursion -- which is precisely what the
#: `railx_*` cards report, since they carry no `from`/`to` and run over the
#: whole transient:
#:     after 1 window : vo1 +0.1214/+1.0360   vint +0.1426/+1.0282
#:     after 2 windows: vo1 +0.1214/+1.0396   vint +0.1420/+1.0282
#:     after 3 windows: vo1 +0.1214/+1.0396   vint +0.1420/+1.0282
#:     after 4 windows: vo1 +0.1214/+1.0396   vint +0.1385/+1.0282
#: vo1's reported extremes are FINAL after two windows and vint's move 3.5 mV
#: at the third and then stop. The reason is structural rather than
#: statistical: an incremental converter RESETS its integrators every
#: conversion window, so an excursion cannot accumulate across windows.
#:
#: THE SPAN IS DERIVED, NEVER TYPED. It is two conversion windows read off the
#: DECK THAT WILL RUN -- `window_clocks` from the decode declaration the
#: producer stamped on it, and the period from the one top-level pulse source
#: -- the same two numbers `sndr_db_incremental` reads, for the same reason:
#: a number this file typed could disagree with the deck it is about.
#:
#: IT DOES NOT TOUCH THE DELIVERED DECK. The testbench A3 emits keeps its full
#: declared record, because that record is sized by `record_constraints` for
#: the GRADED measurement and is the input `analog_resolution_stimulus` reads
#: to build the A4 corner. Shortening that would narrow the A4 population.
#: Only the copy handed to the simulator here is bounded.
_VERIFY_WINDOWS = 2

#: The deck's own transient card: `tran <step> <stop>` with optional extras.
#: Matched on the deck rather than rebuilt, so the step the producer chose and
#: anything it appended survive the rewrite untouched.
_TRAN_CARD_RE = re.compile(
    r"^tran\s+(\S+)\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def _si_seconds(tok: str) -> Optional[float]:
    """A SPICE time token as seconds. `_enob._si` is the reader the ENOB gate
    already uses on this same deck, so the two cannot disagree about what
    `28673000n` means."""
    return _enob._si(tok)


def _fmt_seconds(value: float) -> str:
    """Seconds back as the nanosecond token the emitted decks are written in.
    Integral where it can be, so a rewritten card reads like a written one."""
    ns = value * 1e9
    return (f"{int(round(ns))}n" if abs(ns - round(ns)) < 1e-6
            else f"{ns:.6f}".rstrip("0").rstrip(".") + "n")

_NO_VERIFY_BOUND_NO_STAMP = (
    "verify_window_not_derivable_no_decode_stamp: the deck declares no "
    "conversion window, so the span over which its rail cards settle cannot "
    "be derived from it and the deck's own record stands")
_NO_VERIFY_BOUND_NO_CLOCK = (
    "verify_window_not_derivable_no_clock_card: no single top-level pulse "
    "source names the conversion clock, so a window count cannot be turned "
    "into a time and the deck's own record stands")
_NO_VERIFY_BOUND_NO_TRAN = (
    "verify_window_not_derivable_no_tran_card: the deck runs no transient to "
    "bound")


def verify_window_bound(tb_text: str, ir: Optional[Dict[str, Any]] = None
                        ) -> Tuple[Optional[str], Dict[str, Any]]:
    """`(deck bounded to the A3 verify window, record)`, or `(None, refusal)`.

    WHERE `window_clocks` COMES FROM, AND WHY IT IS NOT ALWAYS THE STAMP.
    `sndr_db_incremental` reads it off the decode declaration stamped on the
    deck -- but that stamp is written by `analog_resolution_stimulus` when it
    builds the A4 corner, which is AFTER this. At A3 verify time the deck
    carries the pulse card and no stamp, so the window count is taken from the
    IR constant the stamp is itself derived from. Same number, one step
    earlier: the stamp is preferred when the deck already carries one, so a
    deck that states its own decode is always believed over the IR that
    produced it.

    REFUSES BY NAME rather than defaulting. A block that declares no
    conversion window at all -- every non-incremental block -- gets no bound
    and runs exactly the record it always ran; that is not a failure, it is
    this function saying it has nothing to derive a bound from."""
    window = None
    source = None
    decl, why = _inc.read_stamp(tb_text or "")
    if decl is not None:
        window = int(decl["window_clocks"])
        source = "deck_decode_stamp"
    else:
        consts = (ir or {}).get("constants")
        raw = consts.get("window_clocks") if isinstance(consts, dict) else None
        if isinstance(raw, (int, float)) and raw > 0:
            window = int(raw)
            source = "topology_ir_constant"
    if window is None:
        return None, {"reason": _NO_VERIFY_BOUND_NO_STAMP, "detail": why}
    card = _enob.sample_clock_card(tb_text or "")
    if card is None:
        return None, {"reason": _NO_VERIFY_BOUND_NO_CLOCK}
    _td, period, _v = card
    m = _TRAN_CARD_RE.search(tb_text or "")
    if not m:
        return None, {"reason": _NO_VERIFY_BOUND_NO_TRAN}
    stop_s = _VERIFY_WINDOWS * window * period
    declared_s = _si_seconds(m.group(2))
    if declared_s is not None and declared_s <= stop_s:
        return None, {"reason": "deck_record_already_within_the_verify_window",
                      "declared_s": declared_s, "verify_window_s": stop_s}
    bounded = (tb_text[:m.start()] + "tran " + m.group(1) + " "
               + _fmt_seconds(stop_s) + tb_text[m.end():])
    return bounded, {
        "verify_window_clocks": _VERIFY_WINDOWS * window,
        "verify_window_s": stop_s,
        "conversion_windows": _VERIFY_WINDOWS,
        "window_clocks": window,
        "sample_clock_hz": (1.0 / period) if period else None,
        "declared_record_s": declared_s,
        "window_clocks_source": source,
        "rule": "two_conversion_windows_derived_from_the_designs_own_numbers",
        "scope": ("this is the A3 VERIFY bound, NOT the A4 corner window; the "
                  "delivered testbench keeps its full declared record"),
    }


def verify_with_ngspice(container: str, block: str, sp_text: str,
                        tb_text: str,
                        real_project: Optional[Path] = None,
                        supply_v: Optional[float] = None) -> Dict[str, Any]:
    """Run the testbench in the EDA container. An unreachable container is a
    CAPABILITY gap (`NOT_VERIFIED_NO_SIMULATOR`), never a netlist defect.

    `supply_v` is the rail the emitted testbench drives, used ONLY by
    `dc_op_rail_excursions`. `None` leaves the rail invariant unevaluated and
    says so (an empty `rail_excursions` list is then NOT a claim that the
    operating point was checked -- `rail_invariant` records which it was)."""
    # REFUSED IS NOT ABSENT — vibe-ic#2156. A container that is there and runs
    # bytes other than the pinned ones is a MEASURED disagreement, and it is
    # owed a status of its own: `NOT_VERIFIED_NO_SIMULATOR` says the binary is
    # not there, which is a different sentence and sends the reader to fix a
    # different thing. Asked FIRST, because the reachability probe below cannot
    # tell the two apart — it answers False for both.
    #
    # COMPOSED BY `container_refusal_result` (vibe-ic#2076), not inline: the
    # record has to carry `env_refused`, which is what `emit_for_block` routes
    # on to make sure NOTHING is emitted off a run the environment refused. A
    # status string alone falls through to the emit at the end of that function
    # and publishes the deck stamped `simulation_verified=false`.
    _refusal = container_image_refusal(container)
    if _refusal:
        return dict(container_refusal_result(_refusal),
                    container=container, required_digest=_pin.IMAGE_DIGEST)
    # NO SECOND CATCH FOR THE RAISED FORM HERE, and its absence is measured.
    # This lane shipped a `try/except _ce.ContainerImageMismatch` around the
    # probe below; once vibe-ic#2156 landed the catch INSIDE `_docker_ok`, the
    # only expression left on this line that could raise it no longer does, and
    # the mutation arm proved it: deleting the handler reddened NOTHING (52
    # passed). A guard no test can make fire is not a guard, so it is gone
    # rather than kept as reassurance. The raised form is still handled where
    # it can still arrive — the staging `mkdir`, the ngspice probe and the
    # cleanup `rm` all build their argv through the guarded builder, and the
    # `except` on the big `try` below catches all three.
    if shutil.which("docker") is None or not _docker_ok(container):
        return {"simulation_verified": False,
                "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                "detail": f"container `{container}` is not reachable"}
    # THE SAME SHAPE AS THE OTHER STAGING SITE. The deck used to be dropped
    # into a FLAT directory here, so an absolute `.lib` resolved by accident
    # and a deck-relative one could not resolve at all. The deck now sits at
    # the path it sits at in the project, and every library the project
    # itself carries is copied in at the same relative path — see
    # `stage_deck_inputs`, and the measured ngspice behaviour in
    # `_portable_lib_path` (a relative `.lib` resolves against the directory
    # of the FILE carrying the directive, not the process CWD).
    root = f"/tmp/a3emit_{block}_{int(time.time())}"
    deck_rel = f"{_CANONICAL_ANALOG}/{block}"
    stage = f"{root}/{deck_rel}"
    try:
        _pr.run_best_effort(
            _ce.docker_exec_argv(container, "mkdir", "-p", stage),
            capture_output=True, text=True)
        with tempfile.TemporaryDirectory(prefix="a3sim_") as td:
            local = Path(td)
            (local / deck_rel).mkdir(parents=True, exist_ok=True)
            (local / deck_rel / f"{block}.sp").write_text(sp_text,
                                                          encoding="utf-8")
            (local / deck_rel / f"tb_{block}.sp").write_text(tb_text,
                                                             encoding="utf-8")
            staged, _unstageable = stage_deck_inputs(
                sp_text, real_project, local, deck_rel,
                real_deck_dir=(real_project / deck_rel
                               if real_project is not None else None))
            for f in (f"{block}.sp", f"tb_{block}.sp"):
                _pr.run_best_effort(
                    ["docker", "cp", str(local / deck_rel / f),
                     f"{container}:{stage}/{f}"],
                    capture_output=True, text=True)
            for rel in staged:
                _pr.run_best_effort(
                    _ce.docker_exec_argv(
                        container, "mkdir", "-p",
                        f"{root}/{str(Path(rel).parent)}"),
                    capture_output=True, text=True)
                _pr.run_best_effort(["docker", "cp", str(local / rel),
                                     f"{container}:{root}/{rel}"],
                                    capture_output=True, text=True)
        # `sh -lc` is deliberately NOT used: a login shell sources the EDA
        # image's profile, which was measured to abort with a syntax error
        # under dash and swallow the probe's answer, so every block came back
        # NOT_VERIFIED_NO_SIMULATOR on a container that had ngspice.
        ng = None
        for cand in ("ngspice", "/foss/tools/bin/ngspice"):
            probe = _pr.run_best_effort(
                _ce.docker_exec_argv(
                    container, "sh", "-c",
                    f"command -v {cand} >/dev/null 2>&1 && echo yes || echo no"),
                capture_output=True, text=True)
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
        # NO WALL CLOCK. This call carried `timeout=900`, and a 900 s clock on
        # a simulator is the defect vibe-ic#2051 removed everywhere else --
        # restated here in the worst possible place, because of WHERE its
        # expiry landed. `subprocess.TimeoutExpired` is a
        # `subprocess.SubprocessError`, so the deadline firing fell into the
        # handler below and this function answered
        # `NOT_VERIFIED_NO_SIMULATOR`: the ONE status that means the binary is
        # not there. MEASURED on this block: the delta-sigma testbench asks for
        # a 399251 ns transient and takes ~14 m 50 s on a loaded host, i.e. the
        # verdict was a coin toss against a 15 m clock, and losing the toss
        # reported a simulator that RAN as a simulator that was ABSENT.
        #
        # `deadline_s=0` is GNU `timeout`'s documented "disable the associated
        # timeout" -- the same expression `analog_real_corner_sweep._run_ngspice`
        # uses for its `run_to_completion` (A4), built by the same
        # `_container_exec` argv function, so there is one container-entry
        # shape and not two. `_progress_run.run` supervises the child on
        # output / CPU / I/O and reaps only a job that has STOPPED moving:
        # a run that is legitimately slow is never cut off, and a run that is
        # genuinely wedged raises `Stalled`, which is a finding about the child.
        #
        # `run_in_container_supervised`, and it replaced `container_deadline_argv`
        # + `_pr.run` (vibe-ic#2117). The previous shape carried
        # `deadline_s=0` -- GNU `timeout`'s documented "disable the associated
        # timeout" -- so no clock actually fired; what it lacked was the other
        # half. `_pr.run` raised `Stalled` and this function RETURNED, leaving
        # the still ngspice running inside the container as exactly the orphan
        # the whole module exists to prevent: reported as stalled here, holding
        # its cores there, and invisible to the next caller. The supervised
        # helper reaps BY IDENTITY -- the launching shell stamps its own
        # (pid, starttime) and then `exec`s the simulator, so the stamp IS the
        # simulator and a stranger sharing a command line can never be
        # selected.
        #
        # IT ALSO CARRIES THE ATTACH CHECK, which is the second half of
        # vibe-ic#2076: a container running bytes the repo does not pin cannot
        # produce this verdict. That is handled as an rc below rather than as a
        # crash -- see `container_refusal_result`.
        cp = _ce.run_in_container_supervised(
            container, f"cd {stage} && {ng} -b tb_{block}.sp 2>&1",
            ceiling_s=SIMULATION_CEILING_S, shell=("bash", "-lc"))
        if cp.returncode == _ce.STALLED_RC:
            # A STOPPED JOB HAS ITS OWN NAME. It is not an absent simulator and
            # it is not a netlist that did not converge -- every readable
            # progress signal sat still while we looked. Naming it anything
            # else charges the design for a host condition. The reap evidence
            # (`VIBEIC_REAP` / `VIBEIC_REAP_SKIP` lines, naming the pids that
            # were signalled) travels with it, because "we stopped it" and "we
            # gave up on it" are different facts and only one of them leaves
            # the host clean.
            return {"simulation_verified": False,
                    "simulation_status": "SIMULATION_STALLED",
                    "detail": ("the simulator stopped making progress: "
                               + (cp.stderr or "").strip()[-1200:])}
        # THE REFUSAL ARRIVES TWO WAYS AND IS ONE FACT. `docker_exec_argv`
        # RAISES on a measured mismatch (the staging calls above take that
        # route); the run wrappers RETURN `IMAGE_MISMATCH_RC` with the refusal
        # on stderr, because a branch whose contract is to return an rc cannot
        # raise out of it. Both mean NOTHING WAS RUN, so both get the one
        # status -- and neither may fall through to the log reader below,
        # which would parse an empty log and answer DID_NOT_CONVERGE about a
        # simulator that was never started.
        # 125 alone is also a Docker/tool exit; only the shared rc-plus-mark
        # identity establishes that the image was refused.
        refusal = _ce.image_refusal(cp)
        if refusal:
            return container_refusal_result(refusal)
        out = (cp.stdout or "") + (cp.stderr or "")
        # A RUN THAT WAS STOPPED IS NOT A RUN THAT ANSWERED. `_container_exec`
        # returns 124 when a deadline fires -- which cannot happen here, since
        # this call sets none -- so a 124 means something OUTSIDE the flow ended
        # the simulator, and 127 means `timeout` itself was missing from the
        # image. Both are statements about the machine, so neither may be
        # recorded as the netlist's verdict.
        if cp.returncode == _ce.TIMEOUT_EXPIRED_RC:
            # `describe_result` would say "the container-side deadline of 0s
            # expired", which is exactly backwards: this call sets NO deadline,
            # so a 124 means something OUTSIDE the flow ended the simulator.
            # Same wording as `analog_real_corner_sweep._run_ngspice` gives its
            # own no-deadline case, for the same reason.
            not_a_verdict = (
                "SIMULATION_STOPPED_EXTERNALLY",
                "this run was given NO deadline by the flow and was stopped "
                "anyway (rc 124). Something outside the flow ended the "
                "simulator: this is a run that was STOPPED, not a measurement "
                "that came back empty")
        elif cp.returncode == _ce.IMAGE_MISMATCH_RC:
            not_a_verdict = (
                "SIMULATION_INVOCATION_FAILED",
                "the container command returned rc 125 without an image-refusal "
                "marker; this supplies no verified simulation measurement")
        elif cp.returncode == _ce.TIMEOUT_UNAVAILABLE_RC:
            # 127 IS STILL NOT A VERDICT, and since the supervised conversion
            # (vibe-ic#2117) it no longer means what `describe_result` says it
            # means: there is no GNU `timeout` on this path to be missing. It
            # is the shell's "command not found", raised at `exec` time for a
            # binary the probe above had just seen answer -- which is a
            # statement about the image, not about the deck.
            not_a_verdict = (
                "SIMULATION_INVOCATION_FAILED",
                f"the container shell could not execute `{ng}` (rc 127) "
                f"although the probe found it a moment earlier: this run "
                f"never started, so it produced no measurement")
        else:
            not_a_verdict = None
        if not_a_verdict is not None:
            status, why = not_a_verdict
            return {"simulation_verified": False,
                    "simulation_status": status,
                    "ngspice_rc": cp.returncode,
                    "detail": why,
                    "log_tail": out.strip().splitlines()[-25:]}
        tail = out.strip().splitlines()[-25:]
        bad = ("doAnalyses: iteration limit reached" in out
               or "singular matrix" in out.lower()
               or "Too few parameters" in out
               or "aborted" in out.lower()
               or "MEAS" not in out)
        meas = [ln.strip() for ln in out.splitlines() if "MEAS" in ln]
        # THE RAIL INVARIANT. The simulator prints an operating-point node
        # table on every `-b` run; reading it costs nothing and answers a
        # question no other gate asks -- see `dc_op_rail_excursions`.
        rails = dc_op_rail_excursions(out, supply_v)
        # THE TRANSIENT RAIL INVARIANT (vibe-ic#2077), a DIFFERENT question
        # from the one above and one the table above cannot answer: the block
        # this was written for had a clean operating point on every node and
        # went to +3.34 V on two of them while it ran. It is graded on EVERY
        # return below, including the ones that refuse for another reason, so
        # the node is named whether or not the run also failed to converge.
        tran = tran_rail_report(out, supply_v,
                                rail_meas_nodes_requested(tb_text))
        tran_fields = {
            "tran_rail_excursions": tran["excursions"],
            "tran_rail_invariant": tran["invariant"],
            "tran_rail_nodes_measured": len(tran["nodes_measured"]),
            "tran_rail_nodes_not_measured": tran["nodes_not_measured"],
        }
        if cp.returncode == 0 and not bad and rails:
            return {
                "simulation_verified": False,
                "simulation_status": "DC_OP_NODE_ABOVE_RAIL",
                "ngspice_rc": cp.returncode,
                "measurements": meas,
                "rail_excursions": rails,
                "rail_invariant": "CHECKED",
                "detail": ("the operating point puts " + str(len(rails)) +
                           " node(s) outside the supply rails: " +
                           ", ".join(f"{n}={v:.6g}V" for n, v in rails[:8])),
                "log_tail": tail,
                **tran_fields,
            }
        # SECOND, AND ONLY WHEN THE DC TABLE IS CLEAN. The operating point is
        # the solution every other number was computed from, so when BOTH are
        # wrong the DC fact is the one that explains the transient and it keeps
        # the verdict; the transient nodes are carried in the record either way.
        if cp.returncode == 0 and not bad and tran["excursions"]:
            exc = tran["excursions"]
            return {
                "simulation_verified": False,
                "simulation_status": "TRAN_NODE_OUTSIDE_RAIL",
                "ngspice_rc": cp.returncode,
                "measurements": meas,
                "rail_excursions": rails,
                "rail_invariant": ("CHECKED"
                                   if isinstance(supply_v, (int, float))
                                   else "NOT_MEASURED_NO_SUPPLY"),
                "detail": ("the transient takes " + str(len(exc)) +
                           " node(s) outside the supply rails: " +
                           ", ".join(f"{n}={v:.6g}V" for n, v in exc[:8]) +
                           "; the operating point was inside them"),
                "log_tail": tail,
                **tran_fields,
            }
        return {
            "simulation_verified": (cp.returncode == 0 and not bad),
            "simulation_status": ("CONVERGED" if (cp.returncode == 0 and
                                                  not bad)
                                  else "DID_NOT_CONVERGE"),
            "ngspice_rc": cp.returncode,
            "measurements": meas,
            "rail_excursions": rails,
            "rail_invariant": ("CHECKED" if isinstance(supply_v, (int, float))
                               else "NOT_MEASURED_NO_SUPPLY"),
            "log_tail": tail,
            **tran_fields,
        }
    except _ce.ContainerImageMismatch as exc:
        # The staging `mkdir`, the ngspice probe and the cleanup `rm` all build
        # their argv through the guarded builder, so any of them can raise this
        # after the reachability probe passed -- a container can be replaced
        # under a run. Recorded, never absorbed into a verdict about the deck.
        return container_refusal_result(exc)
    except (OSError, subprocess.SubprocessError) as exc:
        # NOT_VERIFIED_NO_SIMULATOR IS OWED ONLY WHEN THE BINARY IS ABSENT --
        # the two returns above this `try` are the only places that can say it.
        # Anything that goes wrong once the run has started is a failure of THIS
        # invocation, and it gets its own name so a reader is never told a
        # simulator was missing when one was running.
        return {"simulation_verified": False,
                "simulation_status": "SIMULATION_INVOCATION_FAILED",
                "detail": f"container invocation failed: {exc}"}
    finally:
        try:
            _pr.run_best_effort(
                _ce.docker_exec_argv(container, "rm", "-rf", stage),
                capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError,
                _ce.ContainerImageMismatch):
            # A REFUSAL IN A `finally` WOULD REPLACE THE RETURN. There is
            # nothing to clean up in a container we were refused entry to, and
            # raising here would discard the refusal result the handler above
            # just composed and put the traceback back -- which is the defect,
            # restored by the cleanup path.
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
            "producer_fingerprint": producer_fingerprint(),
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
#: The refusal a block owes a caller whose explicit `--pdk` it does not bind.
#: Named, because "the PDK you asked for is not the PDK this block uses" is a
#: different fact from every other reason this producer declines, and a reader
#: who is only told "no netlist" will re-run the same command.
PDK_NOT_BOUND_BY_BLOCK = "PDK_NOT_BOUND_BY_BLOCK"

#: The verdict when the ENVIRONMENT refused this producer (vibe-ic#2076,
#: vibe-ic#2088): the container it was told to use is provably not the pinned
#: image, so nothing about the design was learned and nothing may be emitted.
#: Reported at `_pc.EX_ENV_REFUSED`, never as a gap and never as a crash.
CONTAINER_IMAGE_MISMATCH = "CONTAINER_IMAGE_MISMATCH"

#: The `action` such a record carries. A reader scanning `records[]` for
#: `gap` / `refused` / `emitted` must not silently miss this one, which is why
#: it is a fourth value rather than a flag on an existing one.
ACTION_ENV_REFUSED = "env_refused"


def emit_for_block(project: Path, entry: Dict[str, Any], pdk: str,
                   container: str, verify_sim: bool,
                   domain: Optional[Any] = None,
                   pdk_explicit: bool = False) -> Dict[str, Any]:
    """One block's record. NEVER raises for an environment refusal.

    A `ContainerImageMismatch` from ANY container entry inside this call is
    caught here and returned as an `ACTION_ENV_REFUSED` record. Before
    vibe-ic#2076 it left this function as an exception, exited the producer 1
    with a traceback, and wrote neither a gap file nor a `--json` report -- so
    the one line that named the two digests reached the run record nowhere.
    """
    try:
        return _emit_for_block(project, entry, pdk, container, verify_sim,
                               domain, pdk_explicit=pdk_explicit)
    except _ce.ContainerImageMismatch as exc:
        return {"block": str(entry.get("name") or entry.get("block")
                             or entry.get("type")),
                "action": ACTION_ENV_REFUSED, "emitted": False,
                "status": CONTAINER_IMAGE_MISMATCH,
                "reason": str(exc).strip()}


def _emit_for_block(project: Path, entry: Dict[str, Any], pdk: str,
                    container: str, verify_sim: bool,
                    domain: Optional[Any] = None,
                    pdk_explicit: bool = False) -> Dict[str, Any]:
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
    # AN EXPLICIT REQUEST THE BLOCK DOES NOT BIND IS A REFUSAL, NEVER SILENCE.
    # NOTHING IS WRITTEN AND NOTHING IS DROPPED: the block's artefacts are not
    # wrong — the REQUEST is — and deleting a correct netlist because a caller
    # typed the wrong `--pdk` would turn a caller's mistake into data loss.
    if pdk_explicit and not pdk_request_is_bound(
            pdk, pdkctx.get("family"), pdkctx.get("registry_family")):
        rec.update(action="refused", emitted=False,
                   status=PDK_NOT_BOUND_BY_BLOCK,
                   requested_pdk=str(pdk),
                   bound_pdk=(pdkctx.get("registry_family")
                              or pdkctx.get("family")),
                   reason=(f"`--pdk {pdk}` was given explicitly, but this "
                           f"block binds "
                           f"`{pdkctx.get('registry_family') or pdkctx.get('family')}`"
                           f" — the family its own design declares. A PDK is "
                           f"discovered from the design, so this argument is a "
                           f"request; it was not honoured and nothing was "
                           f"emitted for it."))
        return rec
    if pdkctx["status"] != "OK":
        # vibe-ic#2139 — THE GAP CARRIES THE STATUS THE RESOLVER ACTUALLY
        # RETURNED. This wrote NEEDS_NATIVE_TEMPLATE for every non-OK status,
        # which was the only one there was; PDK_CROSS_BINDING is a different
        # finding with a different remedy — the context named two PDKs, and
        # the reader needs to be told WHICH element belonged to which — so
        # flattening it into the older word would delete the answer.
        _drop_stale(bdir, name)
        cross = list(pdkctx.get("cross_pdk_bindings") or [])
        status = str(pdkctx["status"])
        reason = ("the declared PDK target resolves to a family whose "
                  "deck context is incomplete; emitting one foundry's "
                  "device tokens against another's model library is "
                  "forbidden")
        if status == PDK_CROSS_BINDING:
            reason = ("the resolved context does not name ONE PDK: " +
                      " ".join(c["sentence"] for c in cross))
        gap = write_gap(bdir, project, name, btype, status, reason,
                        deck_context=pdkctx.get("deck_context"),
                        cross_pdk_bindings=cross,
                        work_items=pdkctx.get("work_items"))
        rec.update(action="gap", emitted=False,
                   status=status,
                   gap_path=str(gap.relative_to(project)))
        return rec

    problems = _validate_ir(ir, pdkctx, project)
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
    # A3 owns final geometry: these values include bindings A2 could not yet
    # see. Refuse before emitting a deck that A5 could only clamp or reject.
    bound_limit_violations = bound_geometry_limit_violations(ir, pdkctx,
                                                               overrides)
    if bound_limit_violations:
        _drop_stale(bdir, name)
        status = "A3_BOUND_DEVICE_EXCEEDS_PDK_MAXIMUM"
        reason = ("A3 resolved spec-bound geometry above the selected PDK's "
                  "drawable limit; it refuses to emit a netlist A5 could not "
                  "draw without changing its capacitance: "
                  + "; ".join(bound_limit_violations))
        gap = write_gap(bdir, project, name, btype, status, reason,
                        bound_geometry_violations=bound_limit_violations,
                        pdk_family=(pdkctx.get("registry_family")
                                    or pdkctx.get("family")))
        rec.update(action="gap", emitted=False, status=status,
                   gap_path=str(gap.relative_to(project)),
                   bound_geometry_violations=bound_limit_violations)
        return rec
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
        # R-0915-44 — NO WALL CLOCK IN THE DIGESTED ARTEFACT. `produced_at`
        # used to be emitted here, into the `.sp` whose WHOLE-FILE sha256 A4
        # records as `netlist_sha256` and later recomputes. Two emissions of
        # byte-identical content a minute apart therefore produced two
        # different digests, and `analog_a4_corner_sweep_check` fired
        # `A4_SWEEP_STALE_VS_NETLIST` on a netlist that had not changed —
        # throwing away a completed 13-hour PVT sweep because of a timestamp.
        # The stamp is not lost: it is in `netlist_provenance.json` beside
        # this file, which is where a time belongs. Measured (lane icadc,
        # 2026-09-16): `_provenance: produced_at=2026-09-14T18:59:58Z` at line
        # 5 of the shipped `delta_sigma.sp`.
        # R-0915-62 — the whole-file digest is kept (every existing consumer
        # reads it) and a CONTENT digest is stamped beside it, so the staleness
        # check can ask whether the TOPOLOGY changed rather than whether its
        # provenance was re-stamped. `topology.json` carries a `produced_at`
        # wall clock; without this, a topology re-emitted with identical
        # content moves the whole-file digest and the netlist is declared
        # stale. Measured on a real verdict run: the `ldo` topology re-emitted,
        # its digest moved 796eb6b2 -> 711cc1c6, the netlist stayed
        # byte-identical, and A3 FAILED.
        f"_provenance: topology_ir={_CANONICAL_ANALOG}/{name}/topology.json "
        f"sha256={_sha256(ir_path)} "
        f"content_sha256={_ir_content_digest(ir_path) or 'none'}",
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
    # THE UNIT ARRAYS, DECLARED — vibe-ic#2062 follow-up, the fourth red.
    #
    # A capacitor the PDK's gencell cannot draw is emitted as N unit devices in
    # parallel (`ci1` -> `ci1_u0`, `ci1_u1`), and until now the ONLY trace of
    # that in the deck was the `_u<N>` suffix on the instance names. So every
    # consumer that needs to know "these N instances are ONE capacitor" had to
    # scrape a name convention — and one did: a topology guard reading the
    # capacitors welded to a summing node compared a LIST of units against a
    # SINGLE name and went red the first time the split fired on its fixture.
    # The netlist was right and had no way to say so.
    #
    # MEASURED, and it is not the split's landing that did it: v1.17.94 and
    # v1.17.95 (which BUILT the split) both emit `xci1 vsum1 vo1 … l=39.3175`,
    # one instance, because no ceiling was known for that family. v1.17.98 read
    # every shipped PDK's capacitor ceiling from its own gencell tcl, 39.3 um
    # went above the 30 um that family actually states, and the split fired
    # here for the first time.
    #
    # NUMBERS AND NAMES ONLY (NDA hygiene), and emitted ONLY when an array
    # exists — a line that appears unconditionally says nothing when it appears.
    for _arr in ((ir.get("_provenance") or {}).get("layout_maxima")
                 or {}).get("capacitor_arrays") or []:
        if not isinstance(_arr, dict) or not _arr.get("device"):
            continue
        _n = int(_arr.get("units") or 0)
        if _n < 2:
            continue
        _base = str(_arr["device"])
        _insts = [f"{_base}_u{i}" for i in range(_n)]
        prov_lines.append(
            f"_provenance: capacitor_array base={_base} units={_n} "
            f"instances={_insts} "
            f"unit_l_um={_arr.get('unit_l_um')} "
            f"library_l_um={_arr.get('library_l_um')} "
            f"pdk_max_l_um={_arr.get('pdk_max_l_um')} — one capacitor the PDK "
            f"cannot draw, realised as {_n} identical units in PARALLEL: every "
            f"unit carries the SAME two nodes, so the array is electrically the "
            f"single device the sizing asked for")
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
    # vibe-ic#2077 — THE DECK SAYS WHAT IT MEASURES, AND SAYS SO WHEN IT
    # MEASURES NOTHING. Adding `.meas` cards is the one thing that makes an
    # emitted deck differ from the byte-identical decks that preceded it, so
    # the difference is stated here rather than left for a reader to diff:
    # every deck carries this line, including the `op`-only ones, whose
    # sentence names WHY they carry no cards. Emitted UNCONDITIONALLY on
    # purpose — a provenance line that only appears when there is something to
    # boast about says nothing when it appears.
    prov_lines.append(f"_provenance: {transient_rail_measurement(ir)[1]}")

    sp_text = render_netlist(ir, pdkctx, prov_lines, overrides, bdir)
    tb_text, tb_env, tb_notes = render_testbench(ir, pdkctx, env, prov_lines, spec)
    if tb_text is None and any(note.startswith("CURRENT_LOAD_UNBOUND:") for note in tb_notes):
        gap = write_gap(bdir, project, name, btype, "TESTBENCH_LOAD_UNBOUND", "; ".join(tb_notes))
        rec.update(action="gap", emitted=False, status="TESTBENCH_LOAD_UNBOUND",
                   gap_path=str(gap.relative_to(project)), reason="; ".join(tb_notes))
        return rec

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
        _supply = (tb_env or {}).get("supply")
        # THE VERIFY RUNS A BOUNDED COPY, THE DELIVERED DECK IS UNTOUCHED.
        # See `verify_window_bound`: A3 asks a rails question, and the span
        # over which that question settles is two conversion windows derived
        # from this design's own numbers. The deck written to disk below keeps
        # its full declared record, because that record is sized for the
        # GRADED measurement and is what `analog_resolution_stimulus` reads to
        # build the A4 corner.
        _verify_text, _verify_window = verify_window_bound(tb_text, ir)
        sim = verify_with_ngspice(
            container, name, sp_text, _verify_text or tb_text,
            real_project=project,
            supply_v=(float(_supply) if isinstance(_supply, (int, float))
                      else None))
        sim["verify_window"] = _verify_window
        # BEFORE EVERY OTHER SIMULATION OUTCOME. `env_refused` means the
        # simulator was never started, so none of the branches below have an
        # observation to judge -- and the fall-through at the end of this
        # function would EMIT the deck stamped `simulation_verified=false`,
        # publishing an artefact off a run the environment refused.
        if sim.get("env_refused"):
            _drop_stale(bdir, name)
            rec.update(action=ACTION_ENV_REFUSED, emitted=False,
                       status=CONTAINER_IMAGE_MISMATCH,
                       reason=str(sim.get("detail") or "").strip(),
                       simulation_status=sim.get("simulation_status"))
            return rec
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
        # BLOCKING, and deliberately the same tier as non-convergence. A run
        # that converged onto an operating point putting the block's own nodes
        # outside its own rails has not verified the netlist -- it has produced
        # a solution the circuit does not hold -- and every measurement in the
        # same log was computed from it. Emitting on it would publish a deck
        # whose sidecar says `simulation_verified: false` while every reader
        # downstream sees a `.sp` that exists.
        if sim.get("simulation_status") == "DC_OP_NODE_ABOVE_RAIL":
            _drop_stale(bdir, name)
            gap = write_gap(bdir, project, name, btype,
                            "NETLIST_DC_OP_OUTSIDE_RAILS",
                            ("the rendered netlist passed every static check "
                             "and the simulator converged, but the operating "
                             "point puts node(s) of the block outside its own "
                             "supply rails, so the solution every measurement "
                             "was taken from is not one the circuit holds"),
                            checker_findings=findings, simulation=sim)
            rec.update(action="gap", emitted=False,
                       status="NETLIST_DC_OP_OUTSIDE_RAILS",
                       gap_path=str(gap.relative_to(project)),
                       rail_excursions=sim.get("rail_excursions"))
            return rec
        # BLOCKING, same tier and for the same reason one step later in time:
        # a run that took the block's own nodes outside its own rails while it
        # ran has not verified the netlist either, and every measurement the
        # same log reports was taken across that excursion. vibe-ic#2077.
        if sim.get("simulation_status") == "TRAN_NODE_OUTSIDE_RAIL":
            _drop_stale(bdir, name)
            gap = write_gap(bdir, project, name, btype,
                            "NETLIST_TRAN_OUTSIDE_RAILS",
                            ("the rendered netlist passed every static check "
                             "and the simulator ran it to the end, but the "
                             "transient takes node(s) of the block outside "
                             "its own supply rails, so the window every "
                             "measurement was taken over is not one the "
                             "circuit holds"),
                            checker_findings=findings, simulation=sim)
            rec.update(action="gap", emitted=False,
                       status="NETLIST_TRAN_OUTSIDE_RAILS",
                       gap_path=str(gap.relative_to(project)),
                       tran_rail_excursions=sim.get("tran_rail_excursions"))
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
    # R-0915-44, the load-bearing half: RE-EMITTING BYTE-IDENTICAL CONTENT IS
    # A NO-OP, so the whole-file digest a downstream gate pinned survives.
    #
    # Dropping `produced_at` above is not enough on its own. `run_ref` is a
    # NONCE (`_pc.new_run_ref`) — deliberately so, because it is checked by
    # AGREEMENT between this artefact and the record beside it, not by
    # re-derivation — and it lands in the header too. So a second emission of
    # identical content still rewrote the file with a different nonce and a
    # different whole-file sha256.
    #
    # `content_digest` already ignores every `* _provenance:` line, so it
    # answers exactly the question that matters: is the CIRCUIT the same? When
    # it is, the file on disk is kept verbatim — including its existing
    # `run_ref` — and the sidecar is written against THAT run_ref, so the
    # agreement check still holds and nothing downstream goes stale.
    #
    # A real netlist change still rewrites and still fires the staleness gate:
    # `content_digest` moves the moment a device, a value or a node moves.
    reused = _reuse_unchanged(sp_path, sp_text)
    if reused is not None:
        sp_text = reused
        rref = _run_ref_in(sp_text) or rref
        content_sha = _pc.content_digest(sp_text)
        ref = _pc.provenance_ref(rref, sp_rel, content_sha)
    else:
        sp_path.write_text(sp_text, encoding="utf-8")
    tb_content_sha = None
    if tb_text:
        tb_path = bdir / f"tb_{name}.sp"
        tb_reused = _reuse_unchanged(tb_path, tb_text)
        if tb_reused is not None:
            tb_text = tb_reused
        else:
            tb_path.write_text(tb_text, encoding="utf-8")
        tb_content_sha = _pc.content_digest(tb_text)
    sidecar = {
        "block": name,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(),
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
        verify_sim: bool, pdk_explicit: bool = False
        ) -> Tuple[int, Dict[str, Any]]:
    entries, src = block_entries(project)
    if not entries:
        return 1, {"producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(), "verdict": "NO_INPUT",
                   "reason": "no analog block list and no L5 analog_blocks[]",
                   "records": []}
    all_entries = list(entries)
    if only:
        entries = [e for e in entries
                   if (e.get("name") or e.get("block") or e.get("type"))
                   == only]
        if not entries:
            return 1, {"producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(), "verdict": "NO_SUCH_BLOCK",
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
        domains.get(str(e.get("name") or e.get("block") or e.get("type"))),
        pdk_explicit=pdk_explicit)
        for e in entries]
    emitted = [r for r in records if r.get("emitted")]
    kept = [r for r in records if r.get("action") == "kept_preexisting"]
    gaps = [r for r in records if r.get("action") == "gap"]
    refused = [r for r in records if r.get("action") == "refused"]
    env_refused = [r for r in records
                   if r.get("action") == ACTION_ENV_REFUSED]
    # AN ENVIRONMENT REFUSAL OUTRANKS EVERYTHING, INCLUDING THE PDK REFUSAL
    # BELOW (vibe-ic#2076, vibe-ic#2088). Every other verdict in this report is
    # a statement ABOUT THE DESIGN; this one says the producer was never
    # allowed to look, and reporting a design verdict alongside it would let a
    # host condition be read as something the design did. It is its own exit
    # tier, `_pc.EX_ENV_REFUSED`, so a caller can tell it from an honest gap
    # (rc 2), from a usage error (rc 64) and from a crash -- which it was.
    if env_refused:
        return _pc.EX_ENV_REFUSED, {
            "producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(),
            "block_list_source": src,
            "verdict": CONTAINER_IMAGE_MISMATCH,
            # THE REFUSAL'S OWN LINE, unchanged. It names both digests, which
            # is what makes it actionable without a second lookup.
            "reason": "; ".join(str(r.get("reason")) for r in env_refused),
            "container": container,
            "blocks_env_refused": [r["block"] for r in env_refused],
            "blocks_total": len(records),
            "blocks_emitted": 0,
            "records": records,
        }
    # A REFUSED REQUEST OUTRANKS EVERY OTHER VERDICT IN THIS REPORT. The other
    # blocks of the same invocation may have emitted perfectly well, and saying
    # EMITTED because they did would let the one refusal be read as noise on a
    # successful run — which is the silence this refusal exists to end.
    if refused:
        return 1, {
            "producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(),
            "block_list_source": src,
            "verdict": PDK_NOT_BOUND_BY_BLOCK,
            "reason": "; ".join(str(r.get("reason")) for r in refused),
            "requested_pdk": str(pdk),
            "blocks_refused": [r["block"] for r in refused],
            "bound_pdk": {r["block"]: r.get("bound_pdk") for r in refused},
            "blocks_total": len(records),
            "blocks_emitted": len(emitted),
            "records": records,
        }
    report = {
        "producer": PRODUCER,
            "producer_fingerprint": producer_fingerprint(),
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
    # DEFAULT `None`, NOT the family name. `--pdk` is a REQUEST (the family is
    # discovered from the design), so the refusal below has to tell a caller who
    # ASKED for a family from a caller who asked for nothing and got this
    # producer's historical default. With `default="sky130"` the two are the
    # same string and every sg13g2/gf180 project in the repo would refuse.
    ap.add_argument("--pdk", default=None)
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
    env_pdk = os.environ.get("VIBEIC_ANALOG_PDK")
    # An env var IS an explicit request — somebody typed it — and it is the one
    # `--pdk` has always read, so it keeps that meaning here.
    pdk = args.pdk or env_pdk or DEFAULT_PDK
    rc, report = run(project, args.block, pdk, args.container,
                     args.verify_sim,
                     pdk_explicit=bool(args.pdk or env_pdk))
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
    elif rc == _pc.EX_ENV_REFUSED:
        print(_pc.env_refused_line(PRODUCER, str(report.get("reason"))),
              file=sys.stderr)
        print(f"{_pc.ENV_REFUSED_TOKEN} nothing was emitted and NO gap file "
              f"was written: this is NOT a statement about the design. "
              f"Blocks not examined: "
              f"{report.get('blocks_env_refused')}", file=sys.stderr)
    elif report.get("verdict") == PDK_NOT_BOUND_BY_BLOCK:
        print(f"{PRODUCER}: {PDK_NOT_BOUND_BY_BLOCK} — requested "
              f"`{report.get('requested_pdk')}`, "
              f"bound {report.get('bound_pdk')}; nothing was emitted. "
              f"{report.get('reason')}", file=sys.stderr)
    else:
        print(f"{PRODUCER}: {report.get('verdict')} — "
              f"{report.get('reason')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
