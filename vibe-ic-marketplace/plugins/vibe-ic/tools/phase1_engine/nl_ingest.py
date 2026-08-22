"""Natural-language ingest — turn a free-text description into seed facts.

Two modes:
  (1) Prompt-only: build the extraction instruction and write it to stdout.
      The calling agent (IC Expert Agent, human, or CI script) runs an LLM and
      feeds the resulting JSON back via `ingest-extracted`.

  (2) API call: if ANTHROPIC_API_KEY is set, call Anthropic directly via
      HTTPS (no SDK dependency — uses urllib), parse response, return facts.

The mode used is transparent to the caller: the `nl-ingest` CLI verb runs
(2) when a key is available, else falls back to (1).

Extracted facts are tagged with:
    provenance.source      = "inferred"
    provenance.confidence  = 0.7   (LLM-level confidence; user confirms later)
    provenance.auto_decided = True
    provenance.origin      = "nl_ingest: <hash-of-input>"

The user may confirm or edit via `set-fact` in the gap-dialogue phase.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import textwrap
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import ALL_LAYER_CODES, FactGraph


# ---------------------------------------------------------------------------
# v1.6.286 — for #155 ORGANIC-phase1 canonical-path alias rewrites.
#
# Issue: closed-fix renderer assertions and the under-spec hard-gate's
# required-fact registry look up facts at fixed canonical L-layer paths
# (e.g. `L1.tapeout_metadata.process_node.pdk_id`). Across LLM extraction
# runs the fact-graph ingest can route semantically-equivalent facts to
# ALTERNATE canonical paths instead (e.g. `L9.process`,
# `L10.performance.example_config.synthesis_results`). The renderer / gate
# then sees the canonical slot empty and reports a false REGRESSED.
#
# Fix (issue body recommendation (a) + (c)):
#   (a) ingest normalisation alias-table — rewrites known-alias paths into
#       their canonical home at ingest time. Source-of-truth lives in
#       `canonical_alias_map.yaml`.
#   (c) required-fact registry expansion — `render.py
#       :: compute_required_facts_coverage` consults the same alias map
#       so a fact at the alias source path counts toward the canonical
#       required fact's satisfied-pct.
#
# Chip-AGNOSTIC: alias map carries only generic typed-block slot paths,
# never chip-class / vendor / part-number literals.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# v1.6.290 — for #170 ORGANIC-phase1 follow-on to #155. Two-dimensional
# widening of the canonical alias rewrite system:
#   (a) concrete entries for L8R / L9.<block> / L2.<block> / notes.* alt-
#       path families observed in rotation-pass-4 fresh LLM extractions
#       (synthesis_results / product_family / tapeout_metadata).
#   (b) regex pattern source-key syntax — `_is_regex_alias_pattern` detects
#       regex-shape keys; the rewriter does exact-match first, then walks
#       extracted keys against regex sources for any that did not match
#       exactly. Heuristic: a source key that starts with `^` OR contains
#       `(`, `[`, `.*`, `\\` is treated as a regex (`re.fullmatch`).
#   (c) multi-source MERGE on collision — when two or more alias sources
#       (or alias source + canonical) all resolve to the same canonical
#       target and the underlying value is a list, the rewriter performs
#       an additive union with identifying-key dedupe (`config_name +
#       technology + frequency_mhz` for synthesis_results; `name` for
#       configuration_axes). For dict values, shallow merge (first-source
#       keys preserved). Records `alias_merged` in the audit trail.
#
# The required-fact registry consumer (`render._alias_satisfies_canonical`)
# also walks regex patterns so registry coverage stays in lock-step.
#
# Chip-AGNOSTIC: regex patterns are structural (L-layer paths only); no
# chip-class / chip-name / vendor literals.
# ---------------------------------------------------------------------------
_DEFAULT_ALIAS_MAP_PATH = Path(__file__).resolve().parent / "canonical_alias_map.yaml"


# v1.6.290 — for #170. Heuristic regex-pattern detection on alias source
# keys. Any source key that starts with `^` OR contains a structural regex
# token (`(`, `[`, `.*`, `\\`) is treated as a regex (matched with
# `re.fullmatch` against extracted-dict keys). Plain dotted paths like
# `L1.meta.tapeout_date` remain exact-match (unchanged behaviour).
_REGEX_HINT_TOKENS = ("(", "[", ".*", "\\")


def _is_regex_alias_pattern(key: str) -> bool:
    """True iff `key` looks like a regex source pattern, not a plain dotted
    fact-path. Used to dispatch between exact-string match and `re.fullmatch`
    semantics in the alias rewriter and required-fact registry consumer."""
    if not isinstance(key, str) or not key:
        return False
    if key.startswith("^"):
        return True
    return any(tok in key for tok in _REGEX_HINT_TOKENS)


# v1.6.290 — for #170. Identifying-key tuple per canonical target slot used
# for additive-union dedupe when multiple alias sources contribute to the
# same canonical LIST target. Keys not in this table fall through to a
# generic "json-serialised whole row" dedupe (exact-row match), which is
# still safe (slightly less aggressive). Order of fields inside a tuple
# matters only for hashing; dedupe is order-insensitive.
_LIST_DEDUPE_KEYS: Dict[str, Tuple[str, ...]] = {
    "L1.synthesis_results": (
        "config_name", "technology", "device_family", "device_part",
        "frequency_mhz", "frequency_hz",
    ),
    "L1.product_family.configuration_axes": ("name",),
}


def _identifying_tuple(target_path: str, row: Any) -> Any:
    """Compute a hashable identifying tuple for `row` against the dedupe-key
    set for `target_path`. Falls back to `json.dumps(row, sort_keys=True)`
    when no key set is registered or the row is not a dict (still
    deterministic dedupe, just stricter).
    """
    keys = _LIST_DEDUPE_KEYS.get(target_path)
    if not isinstance(row, dict) or not keys:
        try:
            return ("__row_json__", json.dumps(row, sort_keys=True, default=str))
        except Exception:
            return ("__row_repr__", repr(row))
    # Only include keys that are actually present + non-empty so partial
    # rows still dedupe against full rows when overlap is unambiguous.
    parts = tuple((k, row.get(k)) for k in keys if row.get(k) not in (None, ""))
    if not parts:
        # No identifying fields populated — fall back to whole-row dedupe.
        try:
            return ("__row_json__", json.dumps(row, sort_keys=True, default=str))
        except Exception:
            return ("__row_repr__", repr(row))
    return parts


def _merge_alias_values(
    target_path: str,
    existing: Any,
    incoming: Any,
) -> Tuple[Any, int, int]:
    """Merge `incoming` into `existing` for the canonical `target_path` slot.
    Returns `(merged_value, merged_count, dedupe_count)`:
      * list + list      → additive union deduped on identifying-key tuple
      * dict + dict      → shallow merge, existing-keys take priority
      * any other shape  → existing wins (no merge possible); merged_count=0
    `merged_count` = number of rows / keys from `incoming` actually added.
    `dedupe_count` = number of rows / keys from `incoming` skipped as dupes.
    """
    if isinstance(existing, list) and isinstance(incoming, list):
        seen: Dict[Any, bool] = {}
        merged: List[Any] = []
        for row in existing:
            tup = _identifying_tuple(target_path, row)
            if tup not in seen:
                seen[tup] = True
                merged.append(row)
        merged_count = 0
        dedupe_count = 0
        for row in incoming:
            tup = _identifying_tuple(target_path, row)
            if tup in seen:
                dedupe_count += 1
                continue
            seen[tup] = True
            merged.append(row)
            merged_count += 1
        return merged, merged_count, dedupe_count

    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged_d = dict(existing)
        merged_count = 0
        dedupe_count = 0
        for k, v in incoming.items():
            if k in merged_d:
                dedupe_count += 1
                continue
            merged_d[k] = v
            merged_count += 1
        return merged_d, merged_count, dedupe_count

    # Incompatible shapes — keep existing (canonical wins).
    return existing, 0, 0


def _load_canonical_alias_map(
    yaml_path: Optional[Path] = None,
) -> Dict[str, str]:
    """Load the alias map from `canonical_alias_map.yaml`. Returns
    `{source_path: target_path}` dict. Missing file → empty map (NO-OP
    behaviour: the rewriter is a no-op when there's no map). Loaded fresh
    on each call so config drives behavior, not code (one source of truth).
    """
    import yaml
    p = Path(yaml_path) if yaml_path else _DEFAULT_ALIAS_MAP_PATH
    if not p.exists():
        return {}
    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}
    aliases = doc.get("aliases") or {}
    if not isinstance(aliases, dict):
        return {}
    return {
        str(k).strip(): str(v).strip()
        for k, v in aliases.items()
        if k and v
    }


def _get_by_path(node: Any, path: str) -> Tuple[bool, Any]:
    """Walk `node` by dotted path `path` (e.g. "L1.meta.project_name").
    Returns `(found, value)`. Used by both the flat-key shortcut and the
    nested-dict descent.
    """
    if not isinstance(node, dict):
        return False, None
    parts = path.split(".")
    cur: Any = node
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _delete_by_path(node: Any, path: str) -> None:
    """Delete the leaf at `path` if present. Leaves empty intermediate
    dicts (caller responsibility to GC; safe because rewrites are sparse).
    """
    if not isinstance(node, dict):
        return
    parts = path.split(".")
    cur: Any = node
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return
        cur = cur[part]
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]


def _set_by_path_flat(node: Any, path: str, value: Any) -> None:
    """Set the FLAT layer-prefixed dotted key `node[path] = value`.

    The LLM extraction protocol (see `EXTRACT_SYSTEM_PROMPT`) emits flat
    layer-prefixed dotted keys like `"L1.tapeout_metadata.tapeout_date"`,
    NOT nested dicts. The canonical alias rewrite preserves that shape so
    downstream `from_extracted_facts` walks the same flat-key form.
    """
    if not isinstance(node, dict):
        return
    node[path] = value


def _is_empty(value: Any) -> bool:
    """True when a value should be treated as "absent" by the rewrite
    rules: None, empty string, empty list, empty dict.
    """
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


# v1.6.301 — for #202 ORGANIC. Nested layer-dict shape detector +
# auto-flattener. The Phase 1 EXTRACT_SYSTEM_PROMPT documents the
# FLAT dotted-key shape (`{"L1.product_family.name": "..."}`), but
# LLM agents routinely emit the more intuitive NESTED-DICT shape
# (`{"L1": {"product_family": {"name": "..."}}}`). Both are
# semantically identical; pre-v1.6.301 the nested shape was silently
# folded into `L1.L2.*` / `L1.L8R.*` paths under v1.6.301 had
# no detection layer, producing a 41pp captured_pct silent loss.
_V1_6_301_LAYER_KEY_RE = re.compile(r"^L[0-9]+R?$", re.IGNORECASE)


def _is_nested_layer_dict_shape(extracted: Dict[str, Any]) -> bool:
    """v1.6.301 — for #202 ORGANIC. True iff every top-level key is
    a layer code (`L1`, `L2`, ..., `L8R`, `L9`, ...) AND every value
    is a dict. Triggers auto-flatten; otherwise the dict is assumed
    to be in the documented flat dotted form.

    Empty / non-dict input → False (no recovery needed).

    Chip-AGNOSTIC.
    """
    if not isinstance(extracted, dict):
        return False
    top_keys = list(extracted.keys())
    if not top_keys:
        return False
    all_layer_keyed = all(
        isinstance(k, str) and _V1_6_301_LAYER_KEY_RE.match(k)
        for k in top_keys
    )
    if not all_layer_keyed:
        return False
    all_dict_valued = all(
        isinstance(extracted[k], dict) for k in top_keys
    )
    return all_dict_valued


def _flatten_nested_layer_dict(
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    """v1.6.301 — for #202 ORGANIC. Walk every nested key under each
    top-level layer code and emit a flat dict whose keys are
    dot-joined paths from the layer code down to each leaf value.

    Example:
        {"L1": {"product_family": {"name": "X"}}}
      →
        {"L1.product_family.name": "X"}

    Lists/scalars are leaves (not recursed into). Empty-leaf values
    are preserved. Chip-AGNOSTIC.
    """
    flat: Dict[str, Any] = {}

    def _walk(prefix: str, val: Any) -> None:
        if isinstance(val, dict):
            if not val:
                flat[prefix] = val
                return
            for k, v in val.items():
                if not isinstance(k, str):
                    flat[prefix] = val
                    return
                _walk(f"{prefix}.{k}", v)
        else:
            flat[prefix] = val

    for layer_code, layer_body in extracted.items():
        _walk(layer_code, layer_body)
    return flat


def _apply_canonical_alias_rewrites(
    extracted: Dict[str, Any],
    alias_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Rewrite alias source paths to canonical target paths IN-PLACE on the
    LLM extraction dict (the keys may be flat layer-prefixed paths like
    `L1.meta.tapeout_date` OR nested dicts like `{"L1": {"meta": {...}}}`).
    Both forms are scanned.

    Conflict policy
    ---------------
      * canonical already populated (non-empty) → NO-OP; if source also
        present with a different value, audit records `path_conflict`.
        v1.6.290 — for #170: when BOTH source and canonical hold list /
        dict values, MERGE rather than drop (additive union deduped on
        identifying-key tuple for lists; shallow merge for dicts).
      * canonical missing / empty AND source present → MOVE source value
        to canonical, delete source, audit records `rewrite_applied`.
      * neither present → silent.

    v1.6.290 — for #170. Source key may be a regex pattern (detected by
    `_is_regex_alias_pattern`). The rewriter does exact-match in a first
    pass, then in a second pass walks remaining extracted keys against the
    regex patterns. Multiple sources resolving to the same canonical target
    accumulate via merge rather than last-write-wins overwrite.

    Audit trail
    -----------
    Every action records a dict into `extracted["_canonical_alias_rewrites"]`
    (a list at the fact-graph root). The list is the only side-effect when
    no rewrite is needed (i.e. it stays empty). Existing entries are
    preserved (idempotent across multiple ingests of the same JSON).

    Chip-AGNOSTIC: alias map + regex patterns are class-agnostic vocabulary;
    no chip-class literal touches this code path.
    """
    if not isinstance(extracted, dict):
        return extracted
    if alias_map is None:
        alias_map = _load_canonical_alias_map()
    if not alias_map:
        return extracted

    audit: List[Dict[str, Any]] = list(
        extracted.get("_canonical_alias_rewrites") or []
    )

    # v1.6.290 — partition alias map into exact-match vs regex-pattern.
    # Exact-match runs FIRST (unchanged v1.6.286 semantics), then regex
    # patterns scan any remaining unmatched keys. This preserves backward
    # compatibility with the v1.6.286 deterministic order.
    exact_aliases: List[Tuple[str, str]] = []
    regex_aliases: List[Tuple[str, str]] = []
    for src, tgt in alias_map.items():
        if _is_regex_alias_pattern(src):
            regex_aliases.append((src, tgt))
        else:
            exact_aliases.append((src, tgt))

    # --- Pass 1: exact-match aliases ---------------------------------------
    for source_path, target_path in exact_aliases:
        _apply_single_alias_rewrite(
            extracted=extracted,
            source_path=source_path,
            target_path=target_path,
            audit=audit,
            match_reason=None,
        )

    # --- Pass 2: regex-pattern aliases -------------------------------------
    # For each regex source pattern, scan the remaining FLAT keys for any
    # that re.fullmatch the pattern, and rewrite each to the canonical
    # target. Each match is treated as if it were its own concrete alias
    # entry (so multi-source merge still works). Skip the canonical target
    # itself (would self-trigger an infinite rewrite loop).
    for pattern, target_path in regex_aliases:
        try:
            compiled = re.compile(pattern)
        except re.error:
            # Malformed regex — log into audit and skip.
            audit.append({
                "source": pattern,
                "target": target_path,
                "reason": "regex_compile_error",
            })
            continue
        # Snapshot keys — extracted is mutated below; we must iterate over
        # a stable copy.
        flat_keys = [k for k in list(extracted.keys()) if isinstance(k, str)]
        for k in flat_keys:
            if k == target_path:
                continue
            if k.startswith("_canonical_alias"):
                continue
            if not compiled.fullmatch(k):
                continue
            _apply_single_alias_rewrite(
                extracted=extracted,
                source_path=k,
                target_path=target_path,
                audit=audit,
                match_reason=f"regex:{pattern}",
            )

    extracted["_canonical_alias_rewrites"] = audit
    return extracted


def _apply_single_alias_rewrite(
    extracted: Dict[str, Any],
    source_path: str,
    target_path: str,
    audit: List[Dict[str, Any]],
    match_reason: Optional[str],
) -> None:
    """Apply ONE source → target rewrite to `extracted`, updating `audit`.

    v1.6.286 base semantics — MOVE source value to canonical when canonical
    empty/missing, otherwise canonical WINS with `path_conflict` recorded.

    v1.6.290 — for #170. When BOTH source and canonical hold list / dict
    values, MERGE rather than path_conflict-drop. Records `alias_merged`
    in the audit with `merged_count` / `dedupe_count` fields.

    `match_reason` is appended to the audit entry's `reason` field for
    regex-pattern matches (e.g. `regex:L[2-9]R?(\\.[a-z_]+)?\\.synth*`)
    so the provenance trail records WHICH regex pattern matched.
    """
    # (1) Lookup in FLAT key form first (LLM most commonly emits flat
    # keys like "L1.meta.project_name").
    src_found_flat = source_path in extracted
    src_value: Any = None
    if src_found_flat:
        src_value = extracted[source_path]

    # (2) Fallback: nested-dict descent for the same logical path.
    src_found_nested = False
    if not src_found_flat:
        src_found_nested, src_value = _get_by_path(extracted, source_path)

    src_found = src_found_flat or src_found_nested
    src_empty = _is_empty(src_value) if src_found else True

    # Canonical: check both flat and nested form.
    tgt_found_flat = target_path in extracted
    tgt_value: Any = extracted.get(target_path) if tgt_found_flat else None
    tgt_found_nested = False
    if not tgt_found_flat:
        tgt_found_nested, tgt_value = _get_by_path(extracted, target_path)
    tgt_found = tgt_found_flat or tgt_found_nested
    tgt_empty = _is_empty(tgt_value) if tgt_found else True

    if not src_found or src_empty:
        return

    def _audit_entry(reason: str, **extra: Any) -> Dict[str, Any]:
        entry = {
            "source": source_path,
            "target": target_path,
            "reason": reason,
        }
        if match_reason:
            entry["matched_by"] = match_reason
        entry.update(extra)
        return entry

    if tgt_found and not tgt_empty:
        # v1.6.290 — if both source and canonical are mergeable shapes
        # (both lists or both dicts), MERGE rather than drop. Otherwise
        # fall through to v1.6.286 path_conflict-drop semantics.
        mergeable = (
            (isinstance(tgt_value, list) and isinstance(src_value, list))
            or (isinstance(tgt_value, dict) and isinstance(src_value, dict))
        )
        if mergeable:
            merged, merged_count, dedupe_count = _merge_alias_values(
                target_path, tgt_value, src_value,
            )
            # Write merged value back to canonical (preserving flat-key form
            # iff canonical was originally flat).
            if tgt_found_flat or not tgt_found_nested:
                _set_by_path_flat(extracted, target_path, merged)
            else:
                # Canonical lives nested — set both for safety (flat shadow
                # preferred for downstream from_extracted_facts).
                _set_by_path_flat(extracted, target_path, merged)
                _delete_by_path(extracted, target_path)
                _set_by_path_flat(extracted, target_path, merged)
            # Drop source (no double-counting in registry expansion).
            if src_found_flat:
                del extracted[source_path]
            else:
                _delete_by_path(extracted, source_path)
            audit.append(_audit_entry(
                "alias_merged",
                merged_count=merged_count,
                dedupe_count=dedupe_count,
            ))
            return

        # Non-mergeable shapes — v1.6.286 path_conflict semantics.
        if tgt_value != src_value:
            audit.append(_audit_entry("path_conflict", kept="canonical"))
        if src_found_flat:
            del extracted[source_path]
        else:
            _delete_by_path(extracted, source_path)
        return

    # Canonical empty / missing → MOVE source value to canonical.
    # Preserve flat-key form (LLM-protocol-compatible shape).
    _set_by_path_flat(extracted, target_path, src_value)
    if src_found_flat:
        del extracted[source_path]
    else:
        _delete_by_path(extracted, source_path)
    audit.append(_audit_entry("rewrite_applied"))


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# Class template → schema summary
# ---------------------------------------------------------------------------
def _summarize_class_schema(
    class_kb_root: Path,
    class_path: str,
) -> str:
    """Inline the class chain's fact paths into a compact schema block for
    the LLM to fill. Keeps the prompt self-contained and class-aware."""
    import yaml
    tree_path = class_kb_root / "class-tree.yaml"
    try:
        tree = yaml.safe_load(tree_path.read_text())
    except FileNotFoundError:
        return "# (class-tree.yaml not found; extract free-form facts)"

    # Compute parent chain.
    parent_of: Dict[str, Optional[str]] = {}

    def rec(node, parent):
        for name, body in node.items():
            if not isinstance(body, dict):
                continue
            parent_of[name] = parent
            children = body.get("children")
            if isinstance(children, dict):
                rec(children, name)

    rec(tree, None)
    chain = [class_path]
    while parent_of.get(chain[-1]) is not None:
        chain.append(parent_of[chain[-1]])
    chain = list(reversed(chain))

    lines: List[str] = []
    for cls in chain:
        f = class_kb_root / "templates" / f"{cls}.yaml"
        if not f.exists():
            continue
        lines.append(f"## class: {cls}")
        try:
            tpl = yaml.safe_load(f.read_text())
        except Exception:
            continue
        for layer, entries in (tpl.get("facts") or {}).items():
            if not isinstance(entries, list):
                continue
            layer_lines: List[str] = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                path = e.get("path")
                if not path:
                    continue
                req = "required" if e.get("required") else "optional"
                layer_lines.append(f"  - {path}  ({req}, {e.get('type','?')})")
            if layer_lines:
                lines.append(f"### {layer}")
                lines.extend(layer_lines)
    return "\n".join(lines) if lines else "# (class template paths unavailable)"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------
EXTRACT_SYSTEM_PROMPT = """\
You are the IC Expert Agent sub-routine for Vibe-IC Phase-1 (plain-language elicitation register).

Your job: read the user's natural-language description of an IC and
extract every fact you can attribute with high confidence into a flat JSON
object. Do NOT invent details the user did not say. If a fact is implied
but not stated, leave it out — it will be surfaced later as a gap.

Output strictly ONE JSON object, keys = layer-prefixed dotted paths like:
    "L1.ic_name"
    "L1.overview.purpose"
    "L3.frame_format.crc.poly"
    "L3.commands[0].opcode"
Values are scalars, dicts, or lists matching the class schema below.

Do NOT wrap in markdown fences. Do NOT explain. Output ONLY the JSON.

Extra extraction rules (v1.6.271 — for #128 / #129):

  * If the description names a marketing FAMILY alongside the specific
    part number (common shapes: "<Org> <FAMILY-N> <PARTNUMBER> ...",
    "<FAMILY> Series — <PARTNUMBER>", "<PARTNUMBER>: <FAMILY> ..."),
    capture BOTH:
        L1.part_number      = the specific part number
        L1.product_family   = { name: <family>, vendor_owner: <org-or-null>,
                                sibling_members: <list-or-null>,
                                source: "user_stated" }
    Do not invent family if absent.

  * If the description carries fabrication / tapeout metadata (foundry
    process node, tapeout date, die dimensions, upstream public repo,
    project origin like academic / commercial / vendor reference),
    capture into L1.tapeout_metadata with shape:
        L1.tapeout_metadata = {
          process_node:      { vendor: ..., pdk_id: ..., node_nm: ... },
          tapeout_date:      { year: ..., month: ..., week: ... },
          die_dimensions_um: { length: ..., width: ...,
                               includes_seal_ring: ... },
          upstream_repo:     { url: ..., type: ... },
          project_origin:    { kind: ..., organisation: ...,
                               course_code: ... }
        }
    Each sub-field is INDIVIDUALLY optional — only emit the ones the
    description actually states. Do NOT push these facts into
    L9.process_technology free-text or L9.power_domains as catch-all;
    L1.tapeout_metadata is the canonical home.

  * For every numeric+unit literal the description carries (e.g.
    "100 MHz", "3.3 V", "4 KB", "8 us"), the underlying integer fact
    is normalised by Phase-1 to its base-SI form (clock_frequency_hz,
    supply_voltage_v, mem_size_bytes, t_us). The renderer will emit
    a sibling `<field>_human` string carrying the original literal —
    you do NOT need to emit `_human` keys yourself; just stick to the
    base-SI integer.

  * v1.6.273 — for #132. If the description includes a per-{device |
    speedgrade | corner} PPA / synthesis-evaluation table — common in
    FPGA soft-IP READMEs and ASIC datasheet electrical sections —
    capture EVERY row into L8R.synthesis_results[] (FPGA / per-device
    shape) or L8R.power_corners[] (ASIC / PVT-corner shape). Do NOT
    collapse the table into the scalar clock_frequency_hz field;
    pre-v1.6.273 every row but one dropped because there was no typed
    home. Each row shape (all fields optional):
        synthesis_results[i] = {
            device_family:   <family-id-or-null>,
            device_part:     <part-number-or-null>,
            corner:          <speedgrade-or-null>,
            frequency_hz:    <base-SI int>,
            lut_count:       <int>,
            register_count:  <int>,
            dsp_count:       <int>,
            bram_count:      <int>,
            area_um2:        <int>,
            power_mw:        <int>,
            toolchain:       <str>,
            toolchain_version: <str>,
            source:          <citation-or-null>,
        }
        power_corners[i] = {
            process:         <"ss"|"tt"|"ff"|"fs"|"sf"-or-null>,
            voltage_v:       <float>,
            temperature_c:   <int>,
            dynamic_power_mw: <float>,
            leakage_power_uw: <float>,
            source:          <citation-or-null>,
        }
    Both lists are optional; only emit them when the description carries
    such a table. Scalar `clock_frequency_hz` may still be set independently
    when the description names a single design-target frequency.

  * v1.6.273 — for #131. When a REQUIRED integer field (pin_count,
    pipeline_depth, channel_count, register_count, scratchpad_size_bytes,
    ...) has NO honest answer in the description (soft-IP / configurable-
    generic designs where the value is set by the integrating SoC, not by
    this IP), DO NOT emit a placeholder integer like `0` or `1`. Simply
    omit the key — Phase-1 will emit a typed NOT_SPECIFIED sentinel that
    the renderer rewrites into `<field>_status: NOT_SPECIFIED` /
    `<field>_reason: ...` siblings, OMITTING the numeric key entirely.
    The honest "value unknown" answer must NOT be confused with a real
    `0` value.
"""


def build_extract_prompt(
    text: str,
    class_path: str,
    class_kb_root: Path,
) -> str:
    schema = _summarize_class_schema(class_kb_root, class_path)
    return textwrap.dedent("""\
        # Class schema (these are the fact paths you should use when appropriate)

        {schema}

        # User's natural-language description

        {text}

        # Task

        Extract every fact explicitly stated in the user's description into a flat
        JSON object with layer-prefixed dotted keys (e.g. "L1.pinout.VBUS").
        Omit anything the user did not say. Output ONE JSON object only.
        """).format(schema=schema, text=text)


# ---------------------------------------------------------------------------
# Anthropic API call (optional, no SDK)
# ---------------------------------------------------------------------------
def call_anthropic_extract(
    text: str,
    class_path: str,
    class_kb_root: Path,
    model: str,
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """Call Anthropic /v1/messages directly. Returns the parsed extraction JSON.

    Raises RuntimeError on missing key, HTTPError, or malformed response.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    prompt = build_extract_prompt(text, class_path, class_kb_root)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": EXTRACT_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise RuntimeError(f"Anthropic API HTTP {e.code}: {err_body}") from e

    content = payload.get("content") or []
    if not content:
        raise RuntimeError("Anthropic API returned empty content")
    text_out = ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_out += block.get("text", "")
    if not text_out.strip():
        raise RuntimeError("Anthropic API returned non-text content")

    # Strip code fences if any.
    stripped = text_out.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Anthropic API returned non-JSON: {stripped[:200]}..."
        ) from e


# ---------------------------------------------------------------------------
# Extracted-facts → FactGraph
# ---------------------------------------------------------------------------
def from_extracted_facts(
    extracted: Dict[str, Any],
    class_path: str,
    ic_name: Optional[str] = None,
    source_text: Optional[str] = None,
    confidence: float = 0.7,
    alias_map: Optional[Dict[str, str]] = None,
) -> FactGraph:
    """Build a FactGraph from a flat dict of layer-prefixed fact paths.

    v1.6.286 — for #155. Runs `_apply_canonical_alias_rewrites` as the
    FIRST normalisation step so semantically-equivalent facts emitted at
    alternate canonical paths (e.g. `L1.meta.tapeout_date`,
    `L9.die_width_um`) get moved to their canonical home (e.g.
    `L1.tapeout_metadata.tapeout_date`, `L1.tapeout_metadata.die_dimensions_um.width`).
    See `canonical_alias_map.yaml` for the alias table; the audit trail is
    stamped into the graph's metadata as `canonical_alias_rewrites`.
    """
    # Plenty of LLMs put ic_name and class_path at top level — accept both.
    name = (
        ic_name
        or extracted.get("ic_name")
        or extracted.get("L1.ic_name")
        or "__unknown__"
    )

    # v1.6.286 — apply canonical alias rewrites BEFORE any fact-building.
    # Copy the dict so the caller's input is not mutated.
    extracted = copy.deepcopy(extracted) if isinstance(extracted, dict) else extracted

    # v1.6.301 — for #202 ORGANIC. Detect and auto-flatten nested
    # layer-dict shape (`{"L1": {...}, "L2": {...}}`) before any
    # downstream processing. LLM extraction agents (including Claude)
    # routinely emit the nested shape instead of the documented flat
    # dotted form (`{"L1.field": ...}`). Without recovery the
    # nested shape silently folded into `L1.L2.*` paths and the
    # renderer saw all non-L1 layers empty — observed 41pp
    # captured_pct loss on same fact content.
    if isinstance(extracted, dict) and _is_nested_layer_dict_shape(extracted):
        import sys as _sys
        print(
            "[ingest-extracted] nested-layer-dict shape detected; "
            "auto-flattening to flat dotted form",
            file=_sys.stderr,
        )
        extracted = _flatten_nested_layer_dict(extracted)

    if isinstance(extracted, dict):
        _apply_canonical_alias_rewrites(extracted, alias_map=alias_map)

    fg = FactGraph(ic_name=str(name), class_path=class_path)

    origin = "nl_ingest"
    if source_text:
        h = hashlib.sha256(source_text.encode()).hexdigest()[:8]
        origin = f"nl_ingest:{h}"

    # Capture the alias-rewrite audit trail into graph metadata so it
    # survives serialisation. Pop the audit key from `extracted` so it
    # is NOT promoted to a fact (it isn't an IC fact, it's provenance).
    audit_entries: List[Dict[str, Any]] = []
    if isinstance(extracted, dict):
        audit_entries = list(
            extracted.pop("_canonical_alias_rewrites", []) or []
        )

    for path, value in extracted.items():
        if not isinstance(path, str):
            continue
        if path in ("ic_name", "class_path"):
            continue
        # Classify source: the LLM extracted from user text, so it's inferred,
        # but the user literally said it, so confidence is high-ish (0.7).
        layer = path.split(".", 1)[0]
        if layer not in ALL_LAYER_CODES:
            # Not a layer-prefixed path; stash into L1 as freeform annotation.
            layer = "L1"
            full_path = f"L1.{path}"
        else:
            full_path = path
        fg.add_fact(
            path=full_path,
            value=value,
            views=[layer],
            source="inferred",
            origin=origin,
            confidence=confidence,
            reasoning="extracted from user's natural-language description",
        )

    fg.metadata["ingested_from"] = "natural_language"
    if source_text:
        fg.metadata["source_text_sha256"] = hashlib.sha256(
            source_text.encode()
        ).hexdigest()
        fg.metadata["source_text_chars"] = len(source_text)
    # v1.6.286 — stamp the alias-rewrite audit trail into graph metadata.
    if audit_entries:
        fg.metadata["canonical_alias_rewrites"] = audit_entries
    return fg
