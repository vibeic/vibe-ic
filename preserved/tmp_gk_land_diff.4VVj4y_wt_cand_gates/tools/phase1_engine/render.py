"""Render — facts.yaml → L1..L9 JSON (pure Python, no LLM).

Projection: every fact whose path starts with "L<N>." contributes to the
L<N> layer JSON. The leaf path under the "L<N>." prefix reconstructs the
layer's internal tree.

This is intentionally a dumb, deterministic inverse of the tree-walk in
ingest.py: whatever goes in round-trips back out.

For cross-layer facts (future: views = ["L3","L8R"]), each view gets the
leaf placed at its canonical sub-path — but the MVP uses layer-prefixed
paths so each fact carries exactly one view.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    ALL_LAYER_CODES,
    Fact,
    FactGraph,
    LAYER_FILE_NAMES,
)

# THE L-document write chokepoint. This engine is the OTHER Phase-1 track
# (fact-graph → L*.json), reached through `phase1_engine.cli`, and it emits
# the same artefact class as `phase1_doc_one_shot_runner`. A stamp on one
# track and not the other would make the absence of a stamp ambiguous
# instead of uniform, which is worse than no stamp at all.
#
# THIS FILE EXISTS TWICE — the repo-root `tools/phase1_engine/` master and
# the byte-identical bundle under `plugins/vibe-ic/tools/phase1_engine/`
# (`test_v0_2_58_phase1_engine_bundle` compares their digests). The two
# copies sit at DIFFERENT depths relative to `programs/`, so the resolver
# below searches upward for the directory that actually contains the
# module rather than counting `parents[N]` — a fixed index is correct in
# one copy and silently wrong in the other, which is exactly the drift the
# bundle test exists to prevent.
def _find_programs_dir() -> Path:
    here = Path(__file__).resolve()
    for base in here.parents:
        for cand in (base / "programs",
                     base / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                     / "programs"):
            if (cand / "l_doc_generator_stamp.py").is_file():
                return cand
    raise ImportError(
        "l_doc_generator_stamp not found from "
        f"{here} — this engine emits L documents and cannot do so without "
        "the write chokepoint that records the producing release; a silent "
        "unstamped emit is the ambiguity vibe-ic#522 removed.")


_PROGRAMS = _find_programs_dir()
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
import l_doc_generator_stamp as _stamp  # noqa: E402


_LIST_IDX_RE = re.compile(r"^(.+)\[(\d+)\]$")


# ---------------------------------------------------------------------------
# v1.6.271 — for #127 ORGANIC-phase1 human-form unit sibling emission
#
# Issue: Phase 1 normalises every numeric+unit literal in the input prompt
# to a base-SI integer (e.g. "100 MHz" → clock_frequency_hz: 100000000) and
# the renderer ONLY emits the integer. The original substring "100 MHz" is
# unrecoverable from `generated_docs/L*.json` / `human_docs/L*.md`, which
# breaks `phase1_input_vs_generated_completeness` substring match.
#
# Fix (issue body suggested-fix (a) — sibling key, lower risk than typed
# compound): for every numeric leaf whose key ends in one of the canonical
# base-SI suffixes, emit a sibling `<key>_human` string carrying the
# pretty-printed human form. The integer form remains authoritative.
#
# Applied chip-AGNOSTIC: any key ending in the suffixes below qualifies,
# no chip-class literal, no path whitelist.
# ---------------------------------------------------------------------------
_UNIT_SUFFIX_HUMAN = {
    # frequency
    "_hz":         "Hz",
    # v1.6.280 — for #144 ORGANIC. Pre-scaled engineering-suffix
    # frequency siblings. Extractors that honour the natural
    # engineering form (`frequency_mhz: 416` rather than
    # `frequency_hz: 416000000`) previously emitted no `_human`
    # sibling, defeating the v1.6.271/v1.6.273 input-vs-generated
    # completeness fix on those fields. Treat each as
    # already-converted (no further scaling): `clock_mhz: 100` →
    # `clock_mhz_human: "100 MHz"`.
    "_mhz":        "MHz",
    "_khz":        "kHz",
    "_ghz":        "GHz",
    # time
    "_s":          "s",
    "_ms":         "ms",
    "_us":         "us",
    "_ns":         "ns",
    "_ps":         "ps",
    # memory / size
    "_bytes":      "B",
    "_kbytes":     "KB",
    "_mbytes":     "MB",
    # voltage / current / power (single-letter)
    "_v":          "V",
    "_mv":         "mV",
    "_uv":         "uV",
    "_a":          "A",
    "_ma":         "mA",
    "_ua":         "uA",
    # v1.6.280 — for #144 ORGANIC. Engineering-suffix current siblings
    # for sub-uA leakage / photocurrent literals (datasheet convention).
    "_pa":         "pA",
    "_w":          "W",
    "_mw":         "mW",
    "_uw":         "uW",
    # capacitance / inductance (analog datasheet convention)
    # v1.6.280 — for #144 ORGANIC.
    "_pf":         "pF",
    "_nf":         "nF",
    "_uf":         "uF",
    # distance / length (analog die dims)
    "_um":         "um",
    "_nm":         "nm",
    "_mm":         "mm",
}

# Frequency scaling: emit pretty-print with auto-scaled unit when ≥1e3.
def _humanize_hz(value: float) -> str:
    # v1.6.304 — for #204 round-2 NOT VERIFIED. Mirror v1.6.303
    # trailing-`.0` preservation: when the Hz value divides cleanly
    # into GHz/MHz/kHz, emit the scaled value with `.0` suffix
    # (e.g. `100_000_000` Hz → `"100.0 MHz"` not `"100 MHz"`).
    # Source datasheets / READMEs routinely encode decimal-precision
    # form (`100.0 MHz`); without the `.0` the coverage gate's
    # haystack substring-match against `"100.0 MHz"` fails because
    # rendered form was `"100 MHz"`. The bare-Hz path retains the
    # integer-shortcut because Hz values are rarely written with
    # explicit decimal precision in source docs.
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{value} Hz"
    if v >= 1e9 and v % 1e9 == 0:
        return f"{int(v / 1e9)}.0 GHz"
    if v >= 1e6 and v % 1e6 == 0:
        return f"{int(v / 1e6)}.0 MHz"
    if v >= 1e3 and v % 1e3 == 0:
        return f"{int(v / 1e3)}.0 kHz"
    if v >= 1e9:
        return f"{v / 1e9:g} GHz"
    if v >= 1e6:
        return f"{v / 1e6:g} MHz"
    if v >= 1e3:
        return f"{v / 1e3:g} kHz"
    return f"{int(v) if v.is_integer() else v} Hz"


def _humanize_bytes(value: float) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{value} B"
    if v >= 1024 * 1024 and v % (1024 * 1024) == 0:
        return f"{int(v / (1024 * 1024))} MB"
    if v >= 1024 and v % 1024 == 0:
        return f"{int(v / 1024)} KB"
    return f"{int(v) if v == int(v) else v} B"


def _humanize_value(key: str, value: Any) -> Optional[str]:
    """Return human-form string for `value` based on `key`'s unit suffix.
    Returns None when the key has no recognised unit suffix or the value
    isn't numeric.

    Special-cases:
      * `*_hz` → auto-scale to kHz / MHz / GHz when divisible.
      * `*_bytes` → auto-scale to KB / MB when binary-divisible.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not isinstance(key, str):
        return None
    key_lower = key.lower()
    # v1.6.300 — for #201 ORGANIC follow-on to #144. Reject ratio
    # keys before any unit-suffix match. A key carrying `_per_`
    # encodes the unit as the *denominator* of a ratio (e.g.
    # `coremarks_per_mhz`, `dmips_per_mhz`, `samples_per_ms`), not
    # as the unit of the value itself; appending the suffix as the
    # value's unit would label a dimensionless ratio with the wrong
    # absolute unit (e.g. "0.95 MHz" for a CoreMark/MHz score).
    if "_per_" in key_lower:
        return None
    # Match longest suffix first so "_mbytes" wins over "_bytes".
    for suffix in sorted(_UNIT_SUFFIX_HUMAN.keys(), key=len, reverse=True):
        if key_lower.endswith(suffix):
            if suffix == "_hz":
                return _humanize_hz(value)
            if suffix == "_bytes":
                return _humanize_bytes(value)
            unit = _UNIT_SUFFIX_HUMAN[suffix]
            # v1.6.303 — for #204 ORGANIC. Removed the
            # `value.is_integer()` integer-shortcut that collapsed
            # `2.0` → `"2 ns"`. Source authors writing `X.0 <unit>`
            # encode decimal precision intent; the renderer must
            # preserve the `.0` for haystack fidelity. Integer-typed
            # inputs (`100`) still render without `.0`; only
            # float-typed values keep their format.
            if isinstance(value, float) and value.is_integer():
                return f"{int(value)} {unit}"
            return f"{value} {unit}"
    return None


def _annotate_human_units(node: Any) -> Any:
    """Walk a rendered layer tree in-place and add sibling `<key>_human`
    string entries for every numeric leaf whose key carries a canonical
    base-SI unit suffix.

    Chip-AGNOSTIC: pure structural rule keyed by suffix table. Existing
    `*_human` keys (e.g. user-stated overrides) are never clobbered.
    """
    if isinstance(node, dict):
        # Snapshot keys — we'll mutate node mid-iteration.
        for k in list(node.keys()):
            v = node[k]
            if isinstance(v, (dict, list)):
                _annotate_human_units(v)
            else:
                human_key = f"{k}_human"
                if human_key in node:
                    continue
                human = _humanize_value(k, v)
                if human is not None:
                    node[human_key] = human
    elif isinstance(node, list):
        for item in node:
            _annotate_human_units(item)
    return node


# v1.6.273 — for #131 ORGANIC-phase1 typed NOT_SPECIFIED sentinel.
#
# `gap_detect._make_not_specified_sentinel` returns dict
# `{__phase1_not_specified__: True, _status: NOT_SPECIFIED, _reason: ...}`
# for required-int / required-float gaps with no class-default. The renderer
# detects that shape and rewrites it into sibling `<key>_status` /
# `<key>_reason` keys, OMITTING the numeric key itself. Downstream consumers
# that read `int` get a missing-key signal (the honest answer) rather than
# the misleading literal `0`.
#
# Chip-AGNOSTIC: pure structural detection by sentinel marker; no chip /
# class / field whitelist.
def _is_not_specified_sentinel(v: Any) -> bool:
    """Mirror of `gap_detect._is_not_specified_sentinel` — kept inline so
    `render.py` has no upward dependency on `gap_detect.py`."""
    return (
        isinstance(v, dict)
        and v.get("__phase1_not_specified__") is True
        and v.get("_status") == "NOT_SPECIFIED"
    )


def _apply_not_specified_sentinel(node: Any) -> Any:
    """Walk the rendered tree; replace every NOT_SPECIFIED sentinel dict
    value with sibling `<key>_status` / `<key>_reason` keys and OMIT the
    numeric key itself.

    Runs BEFORE `_annotate_human_units` so the dropped numeric key never
    receives a `<key>_human` annotation (a `0`-derived "0 Hz" would be
    actively misleading)."""
    if isinstance(node, dict):
        for k in list(node.keys()):
            v = node[k]
            if _is_not_specified_sentinel(v):
                # Promote sentinel metadata to sibling keys; drop the
                # original numeric key so consumers detect missing.
                node[f"{k}_status"] = v.get("_status", "NOT_SPECIFIED")
                reason = v.get("_reason")
                if reason:
                    node[f"{k}_reason"] = reason
                del node[k]
            elif isinstance(v, (dict, list)):
                _apply_not_specified_sentinel(v)
    elif isinstance(node, list):
        for item in node:
            _apply_not_specified_sentinel(item)
    return node


def _set_path(root: Any, path: str, value: Any) -> Any:
    """Set root[path] = value. Path segments may be keys or list indices
    like "ports[3]". Creates intermediate dicts and lists as needed.

    Returns the mutated root (may be a new list if the first segment is
    an index).

    Conflict policy (added for v0.74 auto-run-loop robustness): IC Expert
    sometimes emits the same parent path in two forms — once as a list/
    scalar leaf (``L7.test_modes = [{...}]``) and once as a dict sub-tree
    (``L7.test_modes.functional_mode.entry = "..."``). Likewise it may
    mix dict-style (``source_traceability.bus_protocol``) with list-style
    (``source_traceability[0].file``) under the same key. When we detect
    such a conflict, prefer the *richer* structure:

    - descent needs a dict but node is scalar/list → promote to dict
    - descent needs a list but node is dict → promote to list (dict
      values dropped; they're already overridden by the list form's
      child paths arriving later)
    - leaf write over an existing dict/list → skip (structured sub-tree
      wins)
    """
    parts = path.split(".")
    node = root
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        m = _LIST_IDX_RE.match(part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            # Ensure node[key] is a list of sufficient length, promoting
            # over a prior dict/scalar if needed.
            if not isinstance(node, dict):
                # Upstream should have given us a dict to index into;
                # if not, we can't safely set this path. Drop silently.
                return root
            if key not in node or node[key] is None or not isinstance(node[key], list):
                node[key] = []
            lst = node[key]
            while len(lst) <= idx:
                lst.append({})
            if is_last:
                lst[idx] = value
            else:
                if not isinstance(lst[idx], dict):
                    lst[idx] = {}
                node = lst[idx]
        else:
            if not isinstance(node, dict):
                # Descent stepped into a list/scalar where a dict was
                # needed — skip this fact.
                return root
            if is_last:
                # Skip if a structured sub-tree already occupies this slot.
                existing = node.get(part)
                if isinstance(existing, (dict, list)) and existing:
                    return root
                node[part] = value
            else:
                if part not in node or not isinstance(node[part], (dict, list)):
                    node[part] = {}
                # If existing is a list but we need dict sub-keys, coerce
                # to dict (list form loses; structured form wins).
                if isinstance(node[part], list):
                    node[part] = {}
                node = node[part]
    return root


def _layer_tree(graph: FactGraph, layer: str) -> Dict[str, Any]:
    """Rebuild the layer's JSON tree from all facts tagged with that view."""
    out: Dict[str, Any] = {}
    prefix = layer + "."
    # Sort facts so earlier list indices fill before later ones — gives
    # stable output order.
    relevant = [f for f in graph.facts if f.path.startswith(prefix)]
    relevant.sort(key=lambda f: f.path)
    for fact in relevant:
        sub = fact.path[len(prefix):]
        if not sub:
            continue
        _set_path(out, sub, fact.value)
    return out


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def _layer_provenance(graph: FactGraph, code: str) -> Dict[str, Any]:
    """Aggregate per-fact provenance into a layer-level summary block.

    Emitted as the `provenance` top-level field of every L*.json so the
    D6 traceability rubric / phase1_provenance_presence_check gate can
    confirm the layer was rendered from a known-source fact graph
    (not hand-authored by an agent bypassing phase1_engine).

    Companion field `source_documents` is the deduplicated list of
    `origin` strings from contributing facts — these are typically file
    paths or input doc identifiers.
    """
    sources: Dict[str, int] = {}
    origins: List[str] = []
    seen_origins: set[str] = set()
    n_facts = 0
    for fact in graph.facts:
        if code not in fact.views:
            continue
        n_facts += 1
        src = fact.provenance.source
        sources[src] = sources.get(src, 0) + 1
        orig = fact.provenance.origin or ""
        if orig and orig not in seen_origins:
            origins.append(orig)
            seen_origins.add(orig)
    return {
        "auto_decided": True,
        "reason": (f"rendered from fact-graph by phase1_engine.render "
                   f"(layer={code}, facts={n_facts})"),
        "fact_sources": sources,
    }, origins


def render_layers(
    graph: FactGraph,
    output_dir: Path,
    layers: Optional[List[str]] = None,
    indent: int = 2,
) -> Dict[str, Path]:
    """Render the fact graph into L<N>.json files under output_dir.

    Each emitted L*.json gets two top-level traceability fields injected
    by the render engine itself:
      - `source_documents`: list of distinct fact origins
      - `provenance`:       layer-level summary block

    These satisfy the D6 traceability rubric and prevent
    phase1_provenance_presence_check from FAIL'ing on render-path
    output (the v055 regression that the gate was built to catch).
    Existing keys take precedence — render never overwrites if the
    caller already supplied prov fields.

    Returns dict mapping layer code → written file path.
    """
    layers = layers or ALL_LAYER_CODES
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}

    for code in layers:
        tree = _layer_tree(graph, code)
        if not tree:
            continue
        fname = LAYER_FILE_NAMES.get(code)
        if not fname:
            continue
        prov, origins = _layer_provenance(graph, code)
        # Inject only if absent — never clobber upstream callers.
        if "source_documents" not in tree:
            tree["source_documents"] = origins
        if "provenance" not in tree:
            tree["provenance"] = prov
        # v1.6.273 — for #131 ORGANIC-phase1. Rewrite NOT_SPECIFIED sentinel
        # dicts (produced by gap_detect._empty_stub_for_type for required-
        # numeric leaves with no class-default) into sibling `<key>_status` /
        # `<key>_reason` keys, OMITTING the numeric key. Pre-v1.6.273 those
        # leaves were the literal `0`. Runs BEFORE `_annotate_human_units`
        # so the dropped numeric key never receives an "0 Hz"-style sibling.
        _apply_not_specified_sentinel(tree)
        # v1.6.271 — for #127 emit sibling human-form unit strings so the
        # phase1 input→output completeness gate can substring-match the
        # original prompt's unit literals. See _annotate_human_units.
        _annotate_human_units(tree)
        fpath = output_dir / fname
        # THE L-document write chokepoint — stamps the producing release.
        # NOTE the two senses of "provenance" that meet on this line: the
        # `provenance` / `source_documents` keys injected above say WHICH
        # INPUT a value came from; the stamp says WHICH RELEASE wrote the
        # file. A document can be fully traceable to its inputs and still
        # be seventy releases out of date, which is the failure this
        # chokepoint closes.
        _stamp.dump(fpath, tree, indent=indent)
        written[code] = fpath

    return written


_HUMAN_LAYER_TITLE = {
    "L1":  "L1 — Datasheet",
    "L2":  "L2 — Functional Requirements",
    "L3":  "L3 — Command Protocol",
    "L4":  "L4 — Register Map",
    "L5":  "L5 — Analog-Digital Interface",
    "L6":  "L6 — Control Logic",
    "L7":  "L7 — Test & Debug",
    "L8":  "L8 — Timing & Waveform",
    "L8R": "L8R — RTL Constants",
    "L9":  "L9 — Integration Spec",
    "L10": "L10 — Test Cases",
    "L11": "L11 — Calibration",
    "L12": "L12 — Behavioral Sequences",
    "L13": "L13 — Lab Calibration (Phase 1: contract; Phase 2: evidence)",
}


def _markdown_for_value(value: Any, indent: int = 0) -> List[str]:
    """Render a JSON-ish value as Markdown lines.

    Dicts render as bullet lists with `**key**: value`; nested dicts
    indent. Lists of dicts render as markdown sub-bullets; lists of
    scalars render as comma-joined inline. Scalars render as the value.
    """
    pad = "  " * indent
    out: List[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}- **{k}**:")
                out.extend(_markdown_for_value(v, indent + 1))
            else:
                rendered = _scalar_repr(v)
                out.append(f"{pad}- **{k}**: {rendered}")
    elif isinstance(value, list):
        if not value:
            out.append(f"{pad}- (empty list)")
        elif all(not isinstance(x, (dict, list)) for x in value):
            # scalars → inline
            out.append(f"{pad}- " + ", ".join(_scalar_repr(x) for x in value))
        else:
            for i, item in enumerate(value):
                out.append(f"{pad}- _{i}_:")
                out.extend(_markdown_for_value(item, indent + 1))
    else:
        out.append(f"{pad}- {_scalar_repr(value)}")
    return out


def _scalar_repr(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "_(null)_"
    if isinstance(v, str):
        return v if v else "_(empty string)_"
    return str(v)


def render_human_docs(
    graph: FactGraph,
    output_dir: Path,
    layers: Optional[List[str]] = None,
) -> Dict[str, Path]:
    """Render each layer's facts as a human-readable Markdown view.

    Output filenames are `<layer>_<NAME>.md` mirroring the JSON names —
    e.g. `L1_DATASHEET.md`, `L13_LAB_CALIBRATION.md`. Each file starts
    with a title from `_HUMAN_LAYER_TITLE`, then a bulleted tree of the
    same fact data the JSON view renders.

    Added v0.60: closes the gap that v0.58's fact-graph only emitted
    JSON, never the human-readable Markdown that the public 3-phase
    definition expects from a Phase-1 prompt entry.
    """
    layers = layers or ALL_LAYER_CODES
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}

    for code in layers:
        tree = _layer_tree(graph, code)
        if not tree:
            continue
        json_name = LAYER_FILE_NAMES.get(code)
        if not json_name:
            continue
        # Match the JSON filename's stem; e.g. L1_DATASHEET.json → L1_DATASHEET.md
        md_name = json_name.rsplit(".", 1)[0] + ".md"
        md_path = output_dir / md_name

        # v1.6.271 — for #127 same human-form sibling annotation as the
        # JSON renderer; reviewers reading the .md see the prompt's
        # original "100 MHz" / "3.3 V" / "4 KB" literal verbatim.
        _annotate_human_units(tree)

        title = _HUMAN_LAYER_TITLE.get(code, code)
        lines = [
            f"# {title}",
            "",
            f"_IC: **{graph.ic_name}**  •  Class: `{graph.class_path}`  •  "
            f"Source-of-truth: `{json_name}`_",
            "",
        ]
        lines.extend(_markdown_for_value(tree))
        lines.append("")
        md_path.write_text("\n".join(lines))
        written[code] = md_path

    return written


# ---------------------------------------------------------------------------
# v1.6.271 — for #130 ORGANIC-phase1 underspec partial-set WARN
#
# Issue: when a user prompt is severely under-specified (e.g. two-thirds of
# the class's required facts have no textual support), the renderer emits
# only the L layers whose facts are present, writes no INSUFFICIENT_INPUT
# marker, writes no stderr line, and exits 0. Phase 2's
# phase1_doc_presence_check then breaks on the missing L*.json — failure
# surfaces downstream rather than at the Phase-1 step that should catch it.
#
# Fix (issue body — (1) hard-gate <0.50 + (3) mandatory diagnostic):
#   * compute required_facts_satisfied_pct per layer from the gap report
#   * if total satisfied pct <0.50: raise InsufficientRequiredFactsError
#     UNLESS --allow-underspec is set, in which case continue but warn
#   * for every render with pct <1.0, write WARN_INSUFFICIENT_REQUIRED_FIELDS
#     block to PROVENANCE.md listing every missing required-fact-path per
#     layer, AND print a single stderr summary line
#
# Chip-AGNOSTIC: pure class-template walk, no chip-class literal.
# ---------------------------------------------------------------------------
DEFAULT_HARD_GATE_THRESHOLD = 0.50


class InsufficientRequiredFactsError(RuntimeError):
    """Raised by `render_layers` (or the CLI `render` / `run-all` verb) when
    the fact graph satisfies fewer than the configured threshold of the
    class chain's required fact paths. Carries the per-layer gap detail.
    """

    def __init__(self, pct: float, threshold: float,
                 missing_by_layer: Dict[str, List[str]]):
        self.pct = pct
        self.threshold = threshold
        self.missing_by_layer = missing_by_layer
        n_missing = sum(len(v) for v in missing_by_layer.values())
        super().__init__(
            f"required_facts_satisfied_pct={pct:.2f} < threshold "
            f"{threshold:.2f}; {n_missing} required facts missing across "
            f"{len(missing_by_layer)} layers — re-run with --allow-underspec "
            f"to render anyway (Phase 2 will likely FAIL "
            f"phase1_doc_presence_check)"
        )


def _alias_satisfies_canonical(
    graph: FactGraph,
    canonical_full_path: str,
    alias_map: Dict[str, str],
) -> Optional[str]:
    """v1.6.286 — for #155. If the canonical required-fact path is missing
    from the graph but some alias source path that maps to it IS present,
    return the alias source path (so the caller can record the satisfaction
    via alias). Returns None when no alias rescues the requirement.

    The alias map is the inverse of the rewrite map: rewrite goes source
    → target (e.g. `L9.process` → `L1.tapeout_metadata.process_node.pdk_id`);
    here we look up by target to find any source that would satisfy it.

    v1.6.290 — for #170. The alias map source-key may be a regex pattern
    (detected via `nl_ingest._is_regex_alias_pattern`). For regex patterns
    the function walks every fact path present in the graph and returns
    the first path that `re.fullmatch`-es the pattern (or is nested under
    such a match). This keeps the required-fact registry consumer in
    lock-step with the v1.6.290 ingest-time regex rewriter.
    """
    if not alias_map:
        return None
    # Lazy import to avoid render.py ↔ nl_ingest.py cycle at module load
    # time. Function-level import is cheap.
    try:
        from .nl_ingest import _is_regex_alias_pattern
    except Exception:
        _is_regex_alias_pattern = lambda k: False  # noqa: E731
    present = graph.paths()
    # Each alias entry: source_path → target_path. We want the inverse —
    # the canonical target maps back to one (or more) acceptable sources.
    for source_path, target_path in alias_map.items():
        if target_path != canonical_full_path:
            continue

        # v1.6.290 — regex-pattern alias source. Walk every present fact
        # path and return the first one that fullmatches.
        if _is_regex_alias_pattern(source_path):
            try:
                pat = re.compile(source_path)
            except re.error:
                continue
            for fp in present:
                if pat.fullmatch(fp):
                    return fp
                # Nested-prefix case: the regex matches a prefix of a
                # deeper fact path. Find the longest prefix candidate by
                # walking parent dotted-prefixes and trying the regex on
                # each.
                if "." in fp or "[" in fp:
                    # Try prefix-based match: chop fp on `.` / `[` from
                    # the right and re-test.
                    candidate = fp
                    while True:
                        next_dot = candidate.rfind(".")
                        next_brk = candidate.rfind("[")
                        cut = max(next_dot, next_brk)
                        if cut <= 0:
                            break
                        candidate = candidate[:cut]
                        if pat.fullmatch(candidate):
                            return candidate
            continue

        # Exact-string source — unchanged v1.6.286 semantics. The source
        # path counts as "satisfied" if any fact's path equals, nests
        # under, or contains the source path as a dict-nested key.
        if source_path in present:
            return source_path
        for fp in present:
            if fp.startswith(source_path + ".") or fp.startswith(source_path + "["):
                return source_path
            if source_path.startswith(fp + "."):
                # Nested key inside a single dict-valued fact.
                fact = graph.by_path(fp)
                if fact is None:
                    continue
                remainder = source_path[len(fp) + 1:]
                node: Any = fact.value
                ok = True
                for part in remainder.split("."):
                    if not isinstance(node, dict) or part not in node:
                        ok = False
                        break
                    node = node[part]
                if ok:
                    return source_path
    return None


def compute_required_facts_coverage(
    graph: FactGraph,
    class_kb_root: Optional[Path] = None,
    alias_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Return {pct, total, satisfied, missing_by_layer:{layer:[paths]}}.

    Uses gap_detect.detect_gaps to count required-but-missing facts.
    Falls back to empty/100% when gap_detect can't load the class KB
    (e.g. unit test with synthetic fact graphs).

    v1.6.286 — for #155. The under-spec hard-gate's required-fact registry
    now consults `canonical_alias_map.yaml` (loaded fresh by default; can
    be overridden via `alias_map` arg). A fact at an alias source path
    counts toward the canonical target's required-fact satisfaction. This
    closes the false-regress observed when LLM extractions route the same
    facts to alternate canonical paths (`L9.process`, `L1.meta.*`, etc).
    """
    try:
        from .gap_detect import detect_gaps, DEFAULT_CLASS_KB
    except Exception:
        return {"pct": 1.0, "total": 0, "satisfied": 0,
                "missing_by_layer": {}, "alias_rescued": []}
    root = Path(class_kb_root) if class_kb_root else DEFAULT_CLASS_KB
    if not root.exists():
        return {"pct": 1.0, "total": 0, "satisfied": 0,
                "missing_by_layer": {}, "alias_rescued": []}
    try:
        gaps = detect_gaps(graph, class_kb_root=root)
    except Exception:
        return {"pct": 1.0, "total": 0, "satisfied": 0,
                "missing_by_layer": {}, "alias_rescued": []}

    # Count total required across class chain by re-walking the class
    # template (same code path detect_gaps uses).
    from .gap_detect import (
        _aggregate_required_facts,
        _load_yaml,
        _parent_chain,
    )
    try:
        tree = _load_yaml(root / "class-tree.yaml")
        chain = _parent_chain(graph.class_path, tree)
        required = _aggregate_required_facts(chain, root / "templates")
    except Exception:
        required = {}

    total_required = 0
    for entries in required.values():
        for e in entries:
            if e.get("required"):
                total_required += 1

    # v1.6.286 — load the alias map ONCE per call. Falsy when missing /
    # malformed; the rescue check is a no-op in that case (registry behaves
    # exactly like pre-v1.6.286).
    if alias_map is None:
        try:
            from .nl_ingest import _load_canonical_alias_map
            alias_map = _load_canonical_alias_map()
        except Exception:
            alias_map = {}

    missing_by_layer: Dict[str, List[str]] = {}
    alias_rescued: List[Dict[str, str]] = []
    for g in gaps:
        if g.kind != "missing_required":
            continue
        full_path = f"{g.layer}.{g.path}"
        rescue = _alias_satisfies_canonical(graph, full_path, alias_map or {})
        if rescue is not None:
            alias_rescued.append({
                "canonical": full_path,
                "alias_source": rescue,
                "layer": g.layer,
            })
            continue
        missing_by_layer.setdefault(g.layer, []).append(g.path)

    n_missing = sum(len(v) for v in missing_by_layer.values())
    satisfied = max(0, total_required - n_missing)
    pct = 1.0 if total_required == 0 else satisfied / total_required
    return {
        "pct": pct,
        "total": total_required,
        "satisfied": satisfied,
        "missing_by_layer": missing_by_layer,
        "alias_rescued": alias_rescued,
    }


def enforce_required_facts_threshold(
    graph: FactGraph,
    threshold: float = DEFAULT_HARD_GATE_THRESHOLD,
    allow_underspec: bool = False,
    class_kb_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Raise InsufficientRequiredFactsError if coverage < threshold AND
    allow_underspec is False. Returns the coverage dict in either case.
    """
    coverage = compute_required_facts_coverage(graph, class_kb_root)
    if coverage["pct"] < threshold and not allow_underspec:
        raise InsufficientRequiredFactsError(
            pct=coverage["pct"],
            threshold=threshold,
            missing_by_layer=coverage["missing_by_layer"],
        )
    return coverage


def append_warn_insufficient_block(
    provenance_md_path: Path,
    coverage: Dict[str, Any],
) -> bool:
    """If coverage["pct"] < 1.0, append a WARN_INSUFFICIENT_REQUIRED_FIELDS
    block to PROVENANCE.md listing every missing required-fact-path per
    layer. Returns True iff a block was appended.

    Idempotent: if a block is already present, replace it (we always want
    the latest snapshot).
    """
    if coverage["pct"] >= 1.0:
        return False
    provenance_md_path = Path(provenance_md_path)
    lines = [
        "",
        "## WARN_INSUFFICIENT_REQUIRED_FIELDS",
        "",
        f"_required_facts_satisfied_pct = {coverage['pct']:.2f} "
        f"({coverage['satisfied']} / {coverage['total']} satisfied)_",
        "",
        "Phase 2's `phase1_doc_presence_check` and downstream hard-gates "
        "expect 100% required-fact coverage. The following required facts "
        "had no textual support in the input prompt / docs:",
        "",
    ]
    for layer in sorted(coverage["missing_by_layer"].keys()):
        paths = coverage["missing_by_layer"][layer]
        lines.append(f"### {layer}")
        for p in sorted(paths):
            lines.append(f"  - `{layer}.{p}`")
        lines.append("")
    block = "\n".join(lines) + "\n"

    existing = ""
    if provenance_md_path.exists():
        existing = provenance_md_path.read_text()
        # Strip any prior WARN block — header sentinel matches our shape.
        marker = "\n## WARN_INSUFFICIENT_REQUIRED_FIELDS"
        if marker in existing:
            existing = existing.split(marker, 1)[0].rstrip() + "\n"
    provenance_md_path.write_text(existing + block)
    return True


def render_provenance_report(graph: FactGraph, path: Path) -> None:
    """Write a human-readable provenance audit for every fact."""
    path = Path(path)
    lines = [
        f"# Phase-1 Fact-Graph Provenance Audit",
        f"",
        f"- IC: **{graph.ic_name}**",
        f"- Class: `{graph.class_path}`",
        f"- Total facts: {len(graph.facts)}",
        f"",
        "| uuid | path | source | origin | auto_decided | reasoning |",
        "|------|------|--------|--------|--------------|-----------|",
    ]
    for f in sorted(graph.facts, key=lambda x: x.path):
        p = f.provenance
        reasoning = (p.reasoning or "").replace("|", "\\|")
        origin = (p.origin or "").replace("|", "\\|")
        lines.append(
            f"| `{f.uuid}` | `{f.path}` | {p.source} | {origin} | "
            f"{p.auto_decided} | {reasoning} |"
        )
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# v0.74 Task-C PoC: machine-readable fact UUID index for Phase-2 fact-level
# feedback. Complements PROVENANCE.md (human-readable) with a JSON artifact
# that Phase-2 consumers (spec-to-rtl, K5 quality check) can ingest without
# parsing Markdown.
#
# Format: { <fact_path>: <fact_uuid>, ... }  (sorted by path for stability)
#
# PoC scope: render-side emission only. Consumers are NOT wired yet — this
# is the first half of task C. See docs/design/PHASE1_FACT_UUID_PROPOSAL.md
# for the full fact-UUID threading plan.
# ---------------------------------------------------------------------------
def render_fact_index(graph: FactGraph, path: Path) -> None:
    """Emit a stable path→uuid JSON map for downstream consumers."""
    path = Path(path)
    index = {
        f.path: f.uuid
        for f in sorted(graph.facts, key=lambda x: x.path)
    }
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
