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
DEFAULT_CLASS_KB = Path(
    "vibe-ic-marketplace/plugins/vibe-ic-core/agents/class_kb"
)

# Default defaults/ directory (K3 library) — for suggested_default lookup.
DEFAULT_DEFAULTS_DIR = Path(
    "vibe-ic-marketplace/plugins/vibe-ic-core/agents/defaults"
)


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

    # (2b) typical_scaffolds — full-path match via class chain (v0.68).
    # Lets us inject L6.submodule_control_logic, L9.dtop_top_level, etc.
    # as class-typical defaults when the NL ingest didn't surface them.
    # The scaffold dict is keyed by layer-prefixed path, e.g.
    #   typical_scaffolds:
    #     L6.submodule_control_logic: { decoder: {...}, alu: {...} }
    #     L9.dtop_top_level: { module_name: ..., ports: [...] }
    full_path = f"{gap_layer}.{gap_path}"
    for cls in reversed(chain):
        cr = class_ref.get(cls) or {}
        scaffolds = cr.get("typical_scaffolds") or {}
        if full_path in scaffolds:
            return scaffolds[full_path]

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

    # (0b) Typical-scaffolds pass — apply every class_reference.typical_scaffolds
    # entry unconditionally (if not already covered in graph). Catches parity
    # floor fields like L9.internal_wires and L4.register_map that aren't
    # declared as "required" in the K1 template but are checked downstream.
    scaffolds_applied = _apply_typical_scaffolds(graph, chain)

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
        "scaffolds_applied": scaffolds_applied,
        "interfaces_added": interfaces_added,
    }


def _apply_typical_scaffolds(graph: FactGraph, chain: List[str]) -> int:
    """Inject class_reference.typical_scaffolds entries unconditionally
    (if not already covered in graph). Walks the class chain, most-specific
    first; first match wins per path.

    Used for parity-floor fields (L9.internal_wires, L4.register_map, etc.)
    that aren't declared in K1 as "required" but are checked by downstream
    gates like phase1_quality_parity_check.
    """
    k3 = _load_k3_defaults()
    class_ref = k3.get("class_reference", {}) or {}
    added = 0
    seen_paths = set()

    for cls in reversed(chain):
        cr = class_ref.get(cls) or {}
        scaffolds = cr.get("typical_scaffolds") or {}
        for full_path, value in scaffolds.items():
            if full_path in seen_paths:
                continue  # already injected by a more-specific class
            seen_paths.add(full_path)
            if _fact_covers_path(graph, full_path):
                continue  # user-stated / NL-extracted already — don't overwrite
            layer = full_path.split(".", 1)[0]
            graph.add_fact(
                path=full_path,
                value=value,
                views=[layer],
                source="defaulted",
                origin=f"class_reference:{cls}:typical_scaffolds",
                confidence=0.8,
                reasoning=f"unconditional class-typical scaffold for {cls}",
            )
            added += 1
    return added


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
