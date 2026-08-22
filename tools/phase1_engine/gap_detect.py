"""Gap detection — compare a fact graph against its class template.

Walks the class template (K1), flags every required fact whose path is
absent from the graph, and emits a gap report that the orchestrator
hands to the IC Expert / PM dialogue for resolution.

Also enforces spec_floor minimums: if the class template declares
L3_opcode_count_min=8 and the graph has 4 opcodes, that's a gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import FactGraph

# Default class_kb root — can be overridden.
# ORGANIC-20260606-plugin-cache-missing-phase1-engine (#429): the legacy
# bare-relative default only resolved when cwd happened to be a repo root
# containing vibe-ic-marketplace/ — an installed plugin cache has neither
# that cwd nor that layout. Resolve ONCE, anchored to THIS file:
#   1. bundled-in-plugin layout: <plugin>/tools/phase1_engine → the kb is
#      the sibling <plugin>/agents/class_kb;
#   2. repo checkout: walk up for vibe-ic-marketplace/plugins/vibe-ic/;
#   3. legacy cwd-relative path as the last resort (old behavior).
def _resolve_default_class_kb() -> Path:
    here = Path(__file__).resolve().parent          # .../phase1_engine
    plugin_kb = here.parent.parent / "agents" / "class_kb"
    if (plugin_kb / "class-tree.yaml").is_file():
        return plugin_kb
    for anc in (here, *here.parents):
        c = (anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
             / "agents" / "class_kb")
        if (c / "class-tree.yaml").is_file():
            return c
    return Path("vibe-ic-marketplace/plugins/vibe-ic/agents/class_kb")


DEFAULT_CLASS_KB = _resolve_default_class_kb()

# Default defaults/ directory (K3 library) — for suggested_default lookup.
# Resolved the same way, and for the same reason: a bare relative path only
# resolves when cwd happens to be a repo root containing vibe-ic-marketplace/.
# `_load_k3_defaults` reads it as `f.exists() else {}`, so a wrong cwd does not
# raise — it yields an EMPTY class_reference and `suggest_default` then finds no
# default for any gap and says nothing. Silent degradation, not a failure.
def _resolve_default_defaults_dir() -> Path:
    here = Path(__file__).resolve().parent          # .../phase1_engine
    plugin_defaults = here.parent.parent / "agents" / "defaults"
    if (plugin_defaults / "class_reference.yaml").is_file():
        return plugin_defaults
    for anc in (here, *here.parents):
        c = (anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
             / "agents" / "defaults")
        if (c / "class_reference.yaml").is_file():
            return c
    return Path("vibe-ic-marketplace/plugins/vibe-ic/agents/defaults")


DEFAULT_DEFAULTS_DIR = _resolve_default_defaults_dir()


@dataclass
class Gap:
    layer: str                       # "L3"
    path: str                        # "commands"
    required_by: str                 # "cable-side-id-ic"
    kind: str                        # "missing_required" | "below_floor" | "not_in_whitelist"
    detail: str                      # human-readable
    suggested_default: Optional[Any] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "path": self.path,
            "required_by": self.required_by,
            "kind": self.kind,
            "detail": self.detail,
            "suggested_default": self.suggested_default,
        }


# ---------------------------------------------------------------------------
# Class-tree walk
# ---------------------------------------------------------------------------
def _load_yaml(path: Path) -> Any:
    import yaml
    return yaml.safe_load(Path(path).read_text())


def _parent_chain(class_path: str, class_tree: Dict[str, Any]) -> List[str]:
    """Return [any-ic, ..., class_path] walking the class_tree inheritance.

    class_tree is the parsed class-tree.yaml (nested dict).

    THIS DOES NOT SPLIT A BREADCRUMB, AND THAT IS CURRENTLY DELIBERATE
    ------------------------------------------------------------------
    A `class_path` of "any-ic > digital-ic > apb-peripheral" is returned as a
    single-element chain, so no template matches, no floor applies, and this
    doc-set silently gets no gaps. `phase1_quality_parity_check`,
    `no_protocol_consistency_check` and `layer_extension_presence_check` all
    reduce the breadcrumb to its leaf first. Normalising here is therefore the
    MASTER SWITCH for vibe-ic#495: it is the one change that makes the
    class-tree floors apply to real doc-sets.

    Measured before leaving it off (re #495 Stage 4) — all 201 tracked
    doc-sets, PYTHONHASHSEED=0, `_parent_chain` monkey-patched in-process
    against a fresh corpus copy:

        gaps      0 -> 105        red   0/201 -> 3/201

    All 105 land on ONE project's three doc-set views, 35 each, and NONE of the
    35 is a real design defect:

        5   the gate reads a key the producer does not write — the Stage-0
            defect, unrepaired on this side: L1.package vs `package_info`,
            L1.electrical_characteristics vs `electrical_specs`,
            L2.requirements vs `functional_requirements`, L4.register_map vs
            `register_map_present`, L9.top_level_ports vs `ports`;
        8   `document_id`, on eight layers — `defaultable: true` in any-ic.yaml
            and emitted by no producer in the tree;
       ~9   facts the document EXPLICITLY declares absent from its source via
            the `no_*_in_input` sentinels it already carries. `detect_gaps` has
            no honest-absence escape and cannot see them;
       ~9   apb-peripheral-specific facts demanded of a matmul accelerator
            whose `apb-peripheral` breadcrumb is itself in question.

    And it is not only a reporting change: with a resolvable chain `auto_fill`
    fills 33 facts per doc-set including `L9.top_level_ports = []`
    (provenance `defaulted`), which trips `l9_completeness_check`'s "Section
    'top_level_ports' exists but is empty" ERROR — the co-requisite hazard
    already recorded in `_RETIRED_MECHANISMS` below.

    PREREQUISITES before throwing the switch, in order:
      1. `_fact_covers_path` reads the producer key spellings (extend the
         Stage-0 `_spec_floor_keys` treatment to the required-fact matcher);
      2. `detect_gaps` honours the `no_*_in_input` honest-absence sentinels the
         producers already emit;
      3. `auto_fill` stops filling a required list-typed fact with `[]`;
      4. the class actually assigned to a design is correct (#495 Stage 1).

    Pinned, both halves, by
    `programs/tests/test_v1_7_72_issue495_parent_chain_switch_cost.py`.
    """
    # Flatten tree: child -> parent.
    parent_of: Dict[str, Optional[str]] = {}

    def rec(node: Dict[str, Any], parent: Optional[str]) -> None:
        for name, body in node.items():
            if not isinstance(body, dict):
                continue
            parent_of[name] = parent
            children = body.get("children")
            if isinstance(children, dict):
                rec(children, name)

    rec(class_tree, None)

    chain: List[str] = [class_path]
    while parent_of.get(chain[-1]) is not None:
        chain.append(parent_of[chain[-1]])
    return list(reversed(chain))


def _load_template(class_name: str, templates_dir: Path) -> Optional[Dict[str, Any]]:
    f = templates_dir / f"{class_name}.yaml"
    if not f.exists():
        return None
    return _load_yaml(f)


def _aggregate_required_facts(
    chain: List[str], templates_dir: Path
) -> Dict[str, List[Dict[str, Any]]]:
    """Union of required fact entries across the class chain, keyed by layer."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cls in chain:
        tpl = _load_template(cls, templates_dir)
        if not tpl:
            continue
        facts_by_layer = tpl.get("facts", {}) or {}
        for layer, entries in facts_by_layer.items():
            if not isinstance(entries, list):
                continue
            out.setdefault(layer, []).extend(
                {**e, "__from_class__": cls} for e in entries
                if isinstance(e, dict)
            )
    return out


def _spec_floor_from_chain(
    chain: List[str], templates_dir: Path
) -> Dict[str, Any]:
    """Most-specific class wins for spec_floor."""
    out: Dict[str, Any] = {}
    for cls in chain:
        tpl = _load_template(cls, templates_dir)
        if not tpl:
            continue
        floor = tpl.get("spec_floor") or {}
        out.update(floor)
    return out


# ---------------------------------------------------------------------------
# K3 default lookup — used to populate Gap.suggested_default
# ---------------------------------------------------------------------------
_CLASS_REFERENCE_CACHE: Optional[Dict[str, Any]] = None
_INDUSTRY_STD_CACHE: Optional[Dict[str, Any]] = None


def _load_k3_defaults(defaults_dir: Path = DEFAULT_DEFAULTS_DIR) -> Dict[str, Any]:
    """Load class_reference.yaml + industry_std.yaml once, cache in memory."""
    global _CLASS_REFERENCE_CACHE, _INDUSTRY_STD_CACHE
    if _CLASS_REFERENCE_CACHE is None:
        f = Path(defaults_dir) / "class_reference.yaml"
        _CLASS_REFERENCE_CACHE = _load_yaml(f) if f.exists() else {}
    if _INDUSTRY_STD_CACHE is None:
        f = Path(defaults_dir) / "industry_std.yaml"
        _INDUSTRY_STD_CACHE = _load_yaml(f) if f.exists() else {}
    return {
        "class_reference": _CLASS_REFERENCE_CACHE or {},
        "industry_std": _INDUSTRY_STD_CACHE or {},
    }


# Map gap path (without layer prefix) → class_reference key to use as default.
# Extended as the corpus grows.
_PATH_TO_CLASS_REF_KEY: Dict[str, str] = {
    "overview.package":            "typical_package",
    "overview.process_node_asic":  "typical_process",
    "overview.process_node_fpga":  "typical_fpga",
    "overview.pin_count":          "typical_pin_count",
    "pin_count":                   "typical_pin_count",
}

# Generic auto-decide values — fields that are always auto-filled and don't
# warrant a K3 citation. Keyed by layer-prefixed path suffix.
def _generic_auto_default(layer: str, path: str, ic_name: str) -> Optional[Any]:
    suffix = path.split(".")[-1]
    if suffix == "document_id":
        return f"{ic_name}-{layer.lower()}-spec"
    if suffix == "generated_by":
        return "phase1-auto (vibe-ic fact-graph)"
    if suffix == "source_documents":
        return [f"auto-generated from {ic_name} repo documentation"]
    return None


# v1.6.273 — for #131 ORGANIC-phase1 typed NOT_SPECIFIED sentinel.
#
# Pre-v1.6.273, required-int gaps with no K3 / class-reference / industry-std
# default coerced to the literal `0`. That silently destroyed the distinction
# between (a) "the chip has zero of X" (rarely meaningful) and (b) "the input
# never stated X" (the honest answer for soft-IP / configurable-generic
# designs where the value is fixed at the integrating SoC, not by this IP).
# Downstream gates read the `0` as authoritative, no provenance, no warn.
#
# v1.6.273 fix: return a typed sentinel object instead of `0`. The renderer
# detects the sentinel and emits `<field>_status: NOT_SPECIFIED` + the
# associated reason metadata, OMITTING the numeric key entirely. The
# `phase1_input_vs_generated_completeness` gate is sentinel-aware: sentinel-
# only fields are NOT scored against the prompt (they are by definition not
# present in input).
#
# Chip-AGNOSTIC: the sentinel applies to EVERY required-int field across
# EVERY class template, not a chip-specific opt-out.
NOT_SPECIFIED_SENTINEL_KEY = "__phase1_not_specified__"


def _make_not_specified_sentinel(
    reason: str = "no input or class-default for required field"
) -> Dict[str, Any]:
    """Build the typed NOT_SPECIFIED marker carried as a fact value when a
    required-int (or other required leaf) has no honest answer. Render-time
    detection via `_is_not_specified_sentinel`.
    """
    return {
        NOT_SPECIFIED_SENTINEL_KEY: True,
        "_status": "NOT_SPECIFIED",
        "_reason": reason,
    }


def _is_not_specified_sentinel(v: Any) -> bool:
    """True iff `v` is the typed NOT_SPECIFIED marker produced by
    `_make_not_specified_sentinel`. Used by the renderer to suppress the
    integer key and emit `<field>_status` / `<field>_reason` siblings.
    """
    return (
        isinstance(v, dict)
        and v.get(NOT_SPECIFIED_SENTINEL_KEY) is True
        and v.get("_status") == "NOT_SPECIFIED"
    )


def _empty_stub_for_type(type_name: Optional[str]) -> Optional[Any]:
    """Last-resort stub when no default is known. Lets the layer render
    with a placeholder rather than silently missing. Class-template `type`
    values come from the K1 schema (e.g. `list_of_dicts`, `dict`, `string`).

    v1.6.273 — for #131. Required-numeric leaves now return the typed
    NOT_SPECIFIED sentinel rather than the literal `0`. Pre-v1.6.273 the
    `0` was indistinguishable from a genuinely-zero value and downstream
    gates treated it as authoritative.
    """
    if not type_name:
        return None
    t = str(type_name).lower()
    if t in ("list_of_strings", "list_of_dicts", "list", "array"):
        return []
    if t in ("dict", "object", "mapping"):
        return {}
    if t in ("string", "str", "text"):
        return ""
    if t in ("integer", "int", "number", "float"):
        return _make_not_specified_sentinel(
            reason="required-numeric field has no honest answer from input "
                   "or class-default; soft-IP / configurable-generic pattern"
        )
    if t in ("bool", "boolean"):
        return False
    return None


def _k3_default_for_gap(
    gap_layer: str,
    gap_path: str,
    class_path: str,
    chain: List[str],
    ic_name: str,
    defaults_dir: Path = DEFAULT_DEFAULTS_DIR,
) -> Optional[Any]:
    """Try to suggest a default for a gap using K3 + generic rules.

    Priority: (1) generic auto-decide fields (document_id, etc.), then
    (2) class_reference.yaml `typical_*` mappings, walking the class chain
    from most-specific to root.
    """
    # (1) generic
    val = _generic_auto_default(gap_layer, gap_path, ic_name)
    if val is not None:
        return val

    # (2) class_reference lookup via known path→key map
    k3 = _load_k3_defaults(defaults_dir)
    class_ref = k3.get("class_reference", {}) or {}
    ref_key = _PATH_TO_CLASS_REF_KEY.get(gap_path)
    if ref_key:
        # Walk chain most-specific → root.
        for cls in reversed(chain):
            cr = class_ref.get(cls) or {}
            if ref_key in cr:
                return cr[ref_key]

    # (2b) typical_scaffolds — REMOVED in #493. This was the second of the
    # mechanism's two readers and the only one on the shipping path
    # (`run-all` → detect_gaps → here). See _RETIRED_MECHANISMS below.

    # (3) clock frequency heuristic — common enough to hardcode
    if gap_path == "clock_frequency_hz":
        for cls in reversed(chain):
            cr = class_ref.get(cls) or {}
            if "typical_osc_mhz" in cr:
                try:
                    return int(cr["typical_osc_mhz"]) * 1_000_000
                except (TypeError, ValueError):
                    pass
        return 50_000_000  # safe default

    return None


# ---------------------------------------------------------------------------
# Actual gap detection
# ---------------------------------------------------------------------------
def detect_gaps(
    graph: FactGraph,
    class_kb_root: Path = DEFAULT_CLASS_KB,
) -> List[Gap]:
    class_kb_root = Path(class_kb_root)
    tree = _load_yaml(class_kb_root / "class-tree.yaml")
    chain = _parent_chain(graph.class_path, tree)
    templates_dir = class_kb_root / "templates"

    required = _aggregate_required_facts(chain, templates_dir)
    floor = _spec_floor_from_chain(chain, templates_dir)
    present = graph.paths()

    gaps: List[Gap] = []

    # (1) Required-but-missing
    for layer, entries in required.items():
        for entry in entries:
            path = entry.get("path")
            if not path:
                continue
            if not entry.get("required", False):
                continue
            full_path = f"{layer}.{path}"
            if _fact_covers_path(graph, full_path):
                continue
            # Default lookup priority:
            #   (a) class_template.default_candidate (existing behaviour)
            #   (b) K3 class_reference typical_* / industry_std
            #   (c) generic auto-decide (document_id, generated_by, ...)
            #   (d) type-based empty stub (list_of_dicts → [], dict → {}, ...)
            suggested = entry.get("default_candidate")
            if suggested is None:
                suggested = _k3_default_for_gap(
                    gap_layer=layer,
                    gap_path=path,
                    class_path=graph.class_path,
                    chain=chain,
                    ic_name=graph.ic_name,
                )
            if suggested is None:
                suggested = _empty_stub_for_type(entry.get("type"))
            gaps.append(Gap(
                layer=layer,
                path=path,
                required_by=entry.get("__from_class__", graph.class_path),
                kind="missing_required",
                detail=entry.get("comment", f"{layer}.{path} is required but absent"),
                suggested_default=suggested,
            ))

    # (2) Spec-floor minimums (count-based)
    # Currently supported: L3_opcode_count_min, L4_otp_bytes_min,
    # L4_regmap_reg_count_min, L6_submodule_count_min.
    _check_count_floor(graph, floor, "L3_opcode_count_min", "L3.commands", gaps,
                       required_by=graph.class_path)
    _check_count_floor(graph, floor, "L6_submodule_count_min",
                       "L6.submodule_control_logic", gaps,
                       required_by=graph.class_path, count_is_keys=True)
    _check_count_floor(graph, floor, "L4_regmap_reg_count_min",
                       "L4.registers", gaps,
                       required_by=graph.class_path)
    _check_otp_floor(graph, floor, gaps, required_by=graph.class_path)

    # (3) Whitelist checks (CRC poly must be in L3_crc_poly_allowed)
    allowed = floor.get("L3_crc_poly_allowed")
    if allowed:
        poly_fact = graph.by_path("L3.frame_format.crc.poly") or graph.by_path("L3.crc.poly")
        if poly_fact and str(poly_fact.value) not in allowed:
            gaps.append(Gap(
                layer="L3",
                path="frame_format.crc.poly",
                required_by=graph.class_path,
                kind="not_in_whitelist",
                detail=f"CRC poly {poly_fact.value!r} not in allowed list {allowed}",
                suggested_default=allowed[0],
            ))

    # (4) Required-submodules
    req_subs = floor.get("L6_required_submodules")
    if req_subs:
        present_subs = _dict_keys_at(graph, "L6.submodule_control_logic")
        missing = [s for s in req_subs if s not in present_subs]
        for s in missing:
            gaps.append(Gap(
                layer="L6",
                path=f"submodule_control_logic.{s}",
                required_by=graph.class_path,
                kind="missing_required",
                detail=f"class requires submodule {s!r} to be present",
                suggested_default={"states": [], "description": f"Required submodule {s}"},
            ))

    return gaps


# ---------------------------------------------------------------------------
# Sentinel detection — emit protocol_present / regmap_present stubs when
# the class chain doesn't declare those layers (e.g. processor, analog,
# memory-controller ICs). Matches the v0.59 sentinel contract read by
# phase1_doc_presence_check / _phase1_sentinel.py.
# ---------------------------------------------------------------------------
def _apply_sentinels(
    graph: FactGraph,
    chain: List[str],
    templates_dir: Path,
) -> int:
    """For any REQUIRED_LAYERS that the class chain never mentions, inject
    a sentinel fact so the presence gate honours it. Returns number of
    sentinel facts added.
    """
    import collections
    layers_with_reqs: Dict[str, bool] = collections.defaultdict(bool)
    for cls in chain:
        tpl = _load_template(cls, templates_dir)
        if not tpl:
            continue
        for layer, entries in (tpl.get("facts") or {}).items():
            if isinstance(entries, list) and entries:
                layers_with_reqs[layer] = True

    added = 0
    # L3 sentinel — no protocol-layer requirements anywhere in chain
    if not layers_with_reqs.get("L3"):
        if not graph.by_path("L1.protocol_present"):
            graph.add_fact(
                path="L1.protocol_present",
                value=False,
                views=["L1"],
                source="class_required",
                origin="sentinel:no_L3_requirements",
                confidence=1.0,
                reasoning="class chain has no L3 requirements; emitting "
                          "protocol_present:false sentinel (see _phase1_sentinel.py)",
            )
            added += 1
        if not graph.by_path("L3.protocol_present"):
            graph.add_fact(
                path="L3.protocol_present",
                value=False,
                views=["L3"],
                source="class_required",
                origin="sentinel:no_L3_requirements",
                confidence=1.0,
                reasoning="class chain declares no command protocol",
            )
            graph.add_fact(
                path="L3.ic_name",
                value=graph.ic_name,
                views=["L3"],
                source="class_required",
                origin="sentinel:no_L3_requirements",
                confidence=1.0,
                reasoning="sentinel stub — preserves ic_name linkage",
            )
            added += 2

    # L4 sentinel — no register-map requirements anywhere
    if not layers_with_reqs.get("L4"):
        if not graph.by_path("L4.regmap_present"):
            graph.add_fact(
                path="L4.regmap_present",
                value=False,
                views=["L4"],
                source="class_required",
                origin="sentinel:no_L4_requirements",
                confidence=1.0,
                reasoning="class chain has no L4 register-map requirements",
            )
            graph.add_fact(
                path="L4.ic_name",
                value=graph.ic_name,
                views=["L4"],
                source="class_required",
                origin="sentinel:no_L4_requirements",
                confidence=1.0,
                reasoning="sentinel stub — preserves ic_name linkage",
            )
            added += 2

    # L8R sentinel — same as L3 (RTL constants derive from protocol)
    if not layers_with_reqs.get("L8R") and not layers_with_reqs.get("L3"):
        if not graph.by_path("L8R.protocol_present"):
            graph.add_fact(
                path="L8R.protocol_present",
                value=False,
                views=["L8R"],
                source="class_required",
                origin="sentinel:no_L3_requirements",
                confidence=1.0,
                reasoning="sentinel — no protocol → no protocol-derived RTL constants",
            )
            added += 1

    return added


# ---------------------------------------------------------------------------
# Auto-fill — apply suggested defaults to the graph, write back in place
# ---------------------------------------------------------------------------
def auto_fill(
    graph: FactGraph,
    class_kb_root: Path = DEFAULT_CLASS_KB,
) -> Dict[str, int]:
    """Fill every gap that has a `suggested_default` into the fact graph,
    tagged with provenance source=`defaulted` (or `class_floor` for floor gaps,
    or `class_required` for required-submodules).

    Returns summary: {filled, no_default, total_gaps, sentinels_added}.
    Operates on the graph in-place; caller is responsible for `graph.save(...)`.
    """
    # (0) Sentinel pass — inject protocol_present / regmap_present for
    # non-protocol / non-regmap classes so presence gate passes.
    class_kb_root = Path(class_kb_root)
    tree = _load_yaml(class_kb_root / "class-tree.yaml")
    chain = _parent_chain(graph.class_path, tree)
    templates_dir = class_kb_root / "templates"
    sentinels_added = _apply_sentinels(graph, chain, templates_dir)

    # (0b) Typical-scaffolds pass — REMOVED in #493. See _RETIRED_MECHANISMS.
    # The sentinel pass (0), the interfaces_floor pass (0c) and the gap-fill
    # pass below are UNAFFECTED and remain live; only the unconditional
    # class-typical injection is gone.

    # (0c) supported_interfaces floor — IC-agnostic L1 bullet-list of buses,
    # derived deterministically from pinout signatures. Closes D3 rubric gap.
    # Implementation lives in tools/phase1_engine/interfaces_floor.py so it
    # survives plugin auto-updates (the plugin's class_kb templates are
    # rewritten on every install).
    try:
        from .interfaces_floor import apply_to_graph as _apply_ifaces
        interfaces_added = _apply_ifaces(graph)
    except Exception:
        interfaces_added = 0

    gaps = detect_gaps(graph, class_kb_root=class_kb_root)
    filled = 0
    no_default = 0

    for gap in gaps:
        if gap.suggested_default is None:
            no_default += 1
            continue

        # Pick provenance source based on gap kind.
        if gap.kind == "below_floor":
            source = "class_floor"
        elif gap.kind == "not_in_whitelist":
            source = "class_floor"
        elif gap.kind == "missing_required" and gap.path.startswith(
            "submodule_control_logic."
        ):
            source = "class_required"
        else:
            source = "defaulted"

        full_path = f"{gap.layer}.{gap.path}"
        reasoning = f"auto-filled from class template / K3 — gap: {gap.detail}"
        if source == "defaulted":
            reasoning = f"K3 / class_reference default applied — {gap.detail}"

        graph.add_fact(
            path=full_path,
            value=gap.suggested_default,
            views=[gap.layer],
            source=source,
            origin=f"auto_fill:{gap.required_by}",
            confidence=0.8,
            reasoning=reasoning,
        )
        filled += 1

    return {
        "filled": filled,
        "no_default": no_default,
        "total_gaps": len(gaps),
        "sentinels_added": sentinels_added,
        "interfaces_added": interfaces_added,
    }


# ---------------------------------------------------------------------------
# ORGANIC #493 — RETIRED mechanism: `typical_scaffolds`.
#
# DELETED, not disabled. This record is kept (and asserted by tests) so the
# deletion carries its reason forward and nobody re-lands the mechanism in its
# original shape without first fixing the two defects below. vibe-ic#439 and
# `phase1_k5_quality_check._RETIRED_CHECKS` (#491, v1.7.69) are the precedent:
# a mechanism that has never done anything, and whose first real firing would
# be harmful, is worse than no mechanism, because its presence reads as
# coverage.
#
# WHAT WAS REMOVED
#   1. `_apply_typical_scaffolds(graph, chain)` — the unconditional injector,
#      called from `auto_fill` pass (0b), plus its `scaffolds_applied` summary
#      counter (a counter that could only ever report 0).
#   2. `_k3_default_for_gap` block (2b) — the gap-conditional lookup. This was
#      the SECOND reader and the only one on the shipping path
#      (`run-all` → detect_gaps → _k3_default_for_gap); the injector itself was
#      reachable only from the `auto-fill` CLI verb, which `run-all` never
#      calls. The issue named only reader 1; reader 2 was found by AST scan and
#      confirmed by a runtime read-trace.
#   3. The 59 `typical_scaffolds:` entries in `agents/defaults/
#      class_reference.yaml` across 5 classes — apb-peripheral 17,
#      uart-peripheral 13, crypto-engine 12, simple-cpu 12, bus-controller 5.
#
# WHAT WAS DELIBERATELY KEPT
#   The `auto-fill` CLI verb, `auto_fill()` itself, and its sentinel pass,
#   `interfaces_floor` pass and gap-fill pass. Those are used by the training
#   loop and are unrelated to this mechanism.
#
# WHY — measured at v1.7.69 over the 201 tracked doc-sets (every directory
# holding an L1_DATASHEET.json), driving `from_existing_docs` → `auto_fill`
# and `from_existing_docs` → `detect_gaps` as pure functions:
#
#   * COVERAGE WAS 0. 0/201 doc-sets received even one scaffold fact; 0
#     scaffold facts landed in total; the engine's own `scaffolds_applied`
#     counter summed to 0 across all 201; `detect_gaps` produced 0 gaps
#     corpus-wide, so reader 2 never got a chance either. The removal's
#     opportunity cost is therefore exactly zero — nothing is being taken
#     away from anyone.
#
#   * IT COULD NOT BECOME NON-ZERO WITHOUT A SEPARATE FIX. `_parent_chain`
#     does not normalize a breadcrumb `class_path` ("any-ic > digital-ic >
#     apb-peripheral") the way phase1_quality_parity_check,
#     no_protocol_consistency_check and layer_extension_presence_check all do,
#     and the registry taxonomy (13 snake_case names) and the class-tree
#     taxonomy (31 kebab-case names) do not intersect at all (vibe-ic#495).
#
#   * AND ONCE CONNECTED IT WOULD BE NEGATIVE, for two mechanical reasons
#     that are properties of the design, not of any one chip:
#
#     (a) WRONG INHERITANCE NODE. The 12 `crypto-engine` scaffolds encode
#         AES-128 specifics but hang on the PARENT of `hash-function`,
#         `stream-cipher` and `rng`. `_apply_typical_scaffolds` walks the
#         whole parent chain, so a SHA-256 core inherits `L2.rounds = 10`
#         (SHA-256 has 64), a `key[256]` port (SHA-256 is keyless),
#         `block_in[128]`/`block_out[128]` (SHA-256 is 512-bit block,
#         256-bit digest) and `sbox`/`mixcol`/`encipher`/`decipher`
#         submodules. An `rng` inherits an encrypt/decrypt datapath. Any
#         revival must first push these down to `block-cipher`.
#
#     (b) EMPTY CONTAINER FILLED INTO A REQUIRED FIELD — a CO-REQUISITE
#         HAZARD, not a property of the scaffolds. Reviving the mechanism
#         requires first making `class_path` resolve in the class tree
#         (#495). That resolution ALONE, with no scaffold data present at
#         all, makes the ROOT `any-ic` template's required
#         `L9.top_level_ports` gap-fill with `suggested_default = []`,
#         render as `"top_level_ports": []`, and trip
#         `l9_completeness_check`'s "Section 'top_level_ports' exists but is
#         empty" ERROR. ATTRIBUTION CORRECTED while landing #493: the
#         original measurement read this as scaffold damage because it only
#         ever appeared in the counterfactual run where class_path was
#         normalized. Driving `auto_fill` on a resolvable class_path AFTER
#         this removal still produces the empty container, with provenance
#         `auto_fill:any-ic` — so it is a PRE-EXISTING gap-fill defect that
#         this removal does not fix and must not claim to. It is recorded
#         here because it is the first thing a revival would hit.
#
#     Beyond the mechanics, the class-typical premise fails for these classes:
#     `apb-peripheral` covers timers, GPIO, watchdogs and accelerators alike,
#     so a class-typical L9 TOPOLOGY does not exist for it; and
#     `uart-peripheral`'s `L8.bit_period_cycles = 434` pins clock AND baud
#     rate (50 MHz / 115200) into a single scalar that is silently wrong at
#     any other operating point.
#
# IF YOU ARE REVIVING THIS: reader 2 (the gap-conditional lookup) is the
# defensible half — it only ever fires on a field the class template already
# declares required and that the input did not supply. Reader 1 (the
# unconditional injector) is the dangerous half. Do not restore either
# without (i) a class_path taxonomy decision (#495), (ii) scaffolds re-homed
# to the node whose members are actually homogeneous in that field, and
# (iii) topology-level claims (`dtop_top_level`, `submodules`,
# `instantiation_order`) dropped — only plain scalars survive scrutiny.
# ---------------------------------------------------------------------------
_RETIRED_MECHANISMS = {
    "typical_scaffolds": {
        "was": [
            "_apply_typical_scaffolds",
            "_k3_default_for_gap block (2b)",
            "class_reference.yaml typical_scaffolds data",
        ],
        "issue": "vibe-ic#493",
        "retired_in": "v1.7.69+",
        "read": "class_reference.yaml[<class>].typical_scaffolds",
        "entries_removed": 59,
        "classes_removed": {
            "apb-peripheral": 17,
            "uart-peripheral": 13,
            "crypto-engine": 12,
            "simple-cpu": 12,
            "bus-controller": 5,
        },
        "measured_coverage": "0 of 201 tracked doc-sets; 0 scaffold facts",
        "reason": (
            "Coverage was 0/201, so removal costs nothing. It could not become "
            "non-zero without a separate class_path taxonomy fix (#495), and "
            "once connected it is NEGATIVE for two mechanical reasons: (a) the "
            "12 crypto-engine scaffolds encode AES-128 specifics but hang on "
            "the PARENT of hash-function/stream-cipher/rng, and the injector "
            "walks the whole parent chain, so a SHA-256 core would inherit "
            "rounds=10 (should be 64), a key[256] port (SHA-256 is keyless) "
            "and block_in[128]/block_out[128] (SHA-256 is 512-bit block, "
            "256-bit digest); (b) as a CO-REQUISITE hazard, reviving it "
            "requires making class_path resolve (#495), and that resolution "
            "alone gap-fills the root any-ic template's required "
            "L9.top_level_ports with suggested_default=[], rendering an empty "
            "list that trips l9_completeness_check's \"Section "
            "'top_level_ports' exists but is empty\" ERROR. (b) is PRE-"
            "EXISTING and still reproduces after this removal with provenance "
            "auto_fill:any-ic; it is recorded, not claimed as fixed."),
        "kept": (
            "The `auto-fill` verb, auto_fill() itself, and its sentinel / "
            "interfaces_floor / gap-fill passes are UNAFFECTED and remain "
            "live; the training loop depends on them."),
    },
}


def _check_count_floor(
    graph: FactGraph,
    floor: Dict[str, Any],
    floor_key: str,
    path_prefix: str,
    gaps: List[Gap],
    required_by: str,
    count_is_keys: bool = False,
) -> None:
    minimum = floor.get(floor_key)
    if minimum is None:
        return
    if count_is_keys:
        count = len(_dict_keys_at(graph, path_prefix))
    else:
        count = _list_length_at(graph, path_prefix)
    if count < minimum:
        layer = floor_key.split("_", 1)[0]
        gaps.append(Gap(
            layer=layer,
            path=path_prefix.split(".", 1)[1] if "." in path_prefix else path_prefix,
            required_by=required_by,
            kind="below_floor",
            detail=f"{path_prefix} has {count} entries; class floor is {minimum}",
        ))


def _check_otp_floor(
    graph: FactGraph,
    floor: Dict[str, Any],
    gaps: List[Gap],
    required_by: str,
) -> None:
    minimum = floor.get("L4_otp_bytes_min")
    if minimum is None:
        return
    # OTP may be represented as L4.otp_map_128x8 list, or L4.otp.size_bytes.
    size = _list_length_at(graph, "L4.otp_map_128x8")
    if size == 0:
        size_fact = graph.by_path("L4.otp.size_bytes")
        if size_fact and isinstance(size_fact.value, int):
            size = size_fact.value
    if size and size < minimum:
        gaps.append(Gap(
            layer="L4",
            path="otp_map",
            required_by=required_by,
            kind="below_floor",
            detail=f"OTP size {size} < class floor {minimum}",
        ))


def _fact_covers_path(graph: FactGraph, full_path: str) -> bool:
    """True if any fact in graph covers `full_path`, either:
      (a) path == full_path,
      (b) some fact's path is a prefix of full_path AND its value contains
          the remaining sub-key (dict nesting inside a single fact), or
      (c) some fact's path starts with full_path + "." / "[".
    """
    for f in graph.facts:
        if f.path == full_path:
            return True
        if f.path.startswith(full_path + ".") or f.path.startswith(full_path + "["):
            return True
        # Case (b): full_path lives inside a dict-valued fact at a shorter path.
        if full_path.startswith(f.path + "."):
            remainder = full_path[len(f.path) + 1:]
            if _dict_has_nested_key(f.value, remainder):
                return True
    return False


def _dict_has_nested_key(value: Any, remainder: str) -> bool:
    if not isinstance(value, dict):
        return False
    parts = remainder.split(".")
    node: Any = value
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return False
        node = node[p]
    return True


def _list_length_at(graph: FactGraph, path_prefix: str) -> int:
    """Count indexed children, e.g. L3.commands[0], L3.commands[1], ..."""
    count = 0
    import re
    pat = re.compile(re.escape(path_prefix) + r"\[(\d+)\]")
    max_idx = -1
    for f in graph.facts:
        m = pat.match(f.path)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1 if max_idx >= 0 else 0


def _dict_keys_at(graph: FactGraph, path_prefix: str) -> List[str]:
    """Keys of dict stored directly under path_prefix."""
    keys: List[str] = []
    prefix = path_prefix + "."
    for f in graph.facts:
        if not f.path.startswith(prefix):
            continue
        remainder = f.path[len(prefix):]
        first = remainder.split(".")[0].split("[")[0]
        if first and first not in keys:
            keys.append(first)
    # Also the case where submodule_control_logic itself is a single dict fact.
    direct = graph.by_path(path_prefix)
    if direct and isinstance(direct.value, dict):
        for k in direct.value.keys():
            if k not in keys:
                keys.append(k)
    return keys


# Typing tidy-up at module top
from typing import Any  # noqa: E402  (kept here so _dict_has_nested_key is self-contained)
