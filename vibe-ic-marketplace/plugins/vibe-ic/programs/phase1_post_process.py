"""v0.1.51 — phase1 output post-processor.

Doctrine: the user (2026-05-29) flagged that program extractor output
should match a fresh-Opus-4.7 extraction on the same input. The 47K-line
`phase1_doc_one_shot_runner.py` is legacy; surgical edits there are
risky. This post-processor sits AFTER the runner emits L1..L13 and
performs three doctrine-compliant operations:

  (1) HALLUCINATION SCRUB — remove or downgrade specific known-false
      patterns the legacy runner is observed to emit:
        - ic_name from license-clause boilerplate
          ("SUCH ARM TECHNOLOGY" lifted from
           "USE OR IMPLEMENTATION OF SUCH ARM TECHNOLOGY WILL NOT
            INFRINGE ...")
      A scrub pattern here may only key on a value that is not a
      legitimate value of the field anywhere. It may NOT key on a list
      of encodings: an encoding is data, and the same encoding is
      genuine in the next design. The opcode-from-bit-ruler artefact
      that used to be listed here is refused at source on the row's
      shape — see the removal note in HALLUC_PATTERNS below.

  (2) APPLICABILITY STUB — for L-docs in
      `l_doc_taxonomy.IC_CLASS_APPLICABILITY[ic_class]["not_applicable"]`,
      replace the legacy empty / hallucinated content with the canonical
      `na_stub()`. Honest: surfaces ic_class and rationale instead of
      silent-empty.

  (3) L14-L23 EMISSION — for L-docs in the applicable set that the
      legacy runner doesn't know how to emit (any code ≥ L14), this
      post-processor emits a SKELETON with extraction hints. A
      downstream extractor (per-L-doc) fills in real facts from the
      source corpus; until then, the skeleton makes the bucket exist
      so the AI backstop has a typed slot to write into.

The post-processor is PURE deterministic Python; AI does not run inside
it. Doctrine: 把修法寫進工具，而非寫進 prompt.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)

# Importable as both a script and a module
try:
    import l_doc_taxonomy as _tx
except ImportError:  # pragma: no cover
    from . import l_doc_taxonomy as _tx  # type: ignore

# THE L-document write chokepoint — records the producing release on every
# document this module writes (na_stub overwrite, scrub rewrite, skeleton
# emit). Without it those three paths produced files whose vintage nothing
# on disk could state.
try:
    import l_doc_generator_stamp as _stamp
except ImportError:  # pragma: no cover
    from . import l_doc_generator_stamp as _stamp  # type: ignore


# ---------------------------------------------------------------------------
# Hallucination patterns (catalog grows as new failure modes surface)
# ---------------------------------------------------------------------------
@dataclass
class HallucPattern:
    """One known-false pattern in legacy runner output."""
    name: str
    affected_keys: List[str]    # JSON path patterns (regex)
    value_pattern: re.Pattern
    replacement: str            # what to set the field to
    why: str                    # rationale a human can audit


HALLUC_PATTERNS: List[HallucPattern] = [
    # ic_name lifted from "USE OR IMPLEMENTATION OF SUCH ARM TECHNOLOGY ..."
    HallucPattern(
        name="ic_name_from_license_clause",
        affected_keys=["ic_name"],
        value_pattern=re.compile(
            r"^\s*SUCH\s+(?:ARM\s+)?TECHNOLOGY\s*$", re.I),
        replacement="UNKNOWN_IC",
        why="lifted from license clause 'USE OR IMPLEMENTATION OF "
            "SUCH ARM TECHNOLOGY WILL NOT INFRINGE ...'; not a real "
            "product name",
    ),
    # ic_name lifted from other license boilerplate fragments
    HallucPattern(
        name="ic_name_from_boilerplate_implementation_of",
        affected_keys=["ic_name"],
        value_pattern=re.compile(
            r"^\s*(?:THE\s+)?USE\s+OR\s+IMPLEMENTATION\b.*", re.I),
        replacement="UNKNOWN_IC",
        why="lifted from 'USE OR IMPLEMENTATION OF ...' license clause",
    ),
    # for #454 follow-up — REMOVED: two patterns that keyed on a
    # hard-coded list of eight literal hex VALUES
    # (`opcode_from_two_digit_decimal_page_number` and its downstream
    # companion `opcode_hex_in_test_case_value`). They existed to
    # suppress opcodes the L3 walker synthesised from a figure's decimal
    # bit-position axis. A value list is the wrong instrument for a row
    # shape, in both directions:
    #
    #   * it deleted those eight encodings out of ANY design's command
    #     table — a genuinely declared command carrying one of them was
    #     indistinguishable from the artefact, and the deletion happened
    #     after extraction where no source row was left to check;
    #   * it caught the artefact only where the ruler happened to land on
    #     one of its eight values. Measured over six ruler offsets of the
    #     identical shape it stopped four and let two through.
    #
    # The artefact is now refused AT SOURCE on the row's shape by
    # `phase1_doc_one_shot_runner._i454_bit_position_ruler_row`, which
    # stopped all six, and the refusal is COUNTED into the emitted L3
    # (`non_command_row_refusal_count`) instead of silently deleted.
    #
    # Measured before removal, over the 62 corpus designs that ship their
    # extracted input document: with the value list ON versus OFF the
    # emitted opcode set is IDENTICAL (26 either way) — the list was
    # protecting nothing, and its only live effect was to overwrite the
    # `hex` field of four Strategy-2 refusal records with the scrub
    # sentinel, because `affected_keys` matched the bare leaf key `hex`
    # anywhere in the document, destroying the audit trail it landed on.
]


# ---------------------------------------------------------------------------
# JSON-walking utilities
# ---------------------------------------------------------------------------
def _walk_paths(obj: Any, prefix: str = ""):
    """Yield (path, value) for every leaf and intermediate node."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            yield p, v
            yield from _walk_paths(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{prefix}[{i}]"
            yield p, v
            yield from _walk_paths(v, p)


def _set_path(obj: Any, path: str, new_value: Any) -> bool:
    """Set the value at a dotted path. Returns True if set."""
    parts = re.split(r"\.|\[", path)
    parts = [p.rstrip("]") for p in parts if p]
    cur: Any = obj
    for i, p in enumerate(parts[:-1]):
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return False
        elif isinstance(cur, dict):
            if p not in cur:
                return False
            cur = cur[p]
        else:
            return False
    last = parts[-1]
    if isinstance(cur, list):
        try:
            cur[int(last)] = new_value
            return True
        except (ValueError, IndexError):
            return False
    if isinstance(cur, dict):
        cur[last] = new_value
        return True
    return False


# ---------------------------------------------------------------------------
# Hallucination scrubbing
# ---------------------------------------------------------------------------
@dataclass
class ScrubLog:
    l_doc: str
    pattern_name: str
    path: str
    old_value: Any
    new_value: Any
    why: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def scrub_l_doc(obj: Any, l_doc_name: str,
                patterns: List[HallucPattern] = None) -> List[ScrubLog]:
    """Walk obj, replacing matches of every pattern. Mutates obj in
    place; returns audit log of replacements."""
    pats = patterns if patterns is not None else HALLUC_PATTERNS
    log: List[ScrubLog] = []
    # Snapshot the (path, value) list because we'll mutate during walk.
    paths_values = list(_walk_paths(obj))
    for path, value in paths_values:
        if not isinstance(value, str):
            continue
        # Last segment of path is the "leaf key" — strip array index brackets
        leaf = path.rsplit(".", 1)[-1]
        leaf_no_idx = re.sub(r"\[\d+\]$", "", leaf)
        for pat in pats:
            key_match = any(
                re.match(rf"^{kp}$", leaf_no_idx)
                or re.match(rf"^{kp}$", path)
                or kp == leaf_no_idx
                for kp in pat.affected_keys
            )
            if not key_match:
                continue
            if pat.value_pattern.match(value):
                if _set_path(obj, path, pat.replacement):
                    log.append(ScrubLog(
                        l_doc=l_doc_name, pattern_name=pat.name,
                        path=path, old_value=value,
                        new_value=pat.replacement, why=pat.why,
                    ))
                break
    # v0.2.13 — after the in-place scrub, an opcode entry whose `hex`
    # was replaced by the HALLUCINATION_SCRUBBED sentinel is a zombie:
    # it carries no trustworthy encoding. Leaving it in `opcodes`
    # makes `no_opcodes_in_input` lie (False) and trips
    # l3_opcode_name_coverage_check (every zombie name is
    # OPCODE_NAME_UNKNOWN → 100% placeholder → FAIL → runner exit 1).
    # ic_class_profile._l3_has_commands already filters these out; do the
    # same at the source so generated_docs match a fresh extraction
    # (which carries no opcodes key at all). General / sentinel-based —
    # no protocol name in the predicate.
    log.extend(_drop_scrubbed_opcodes(obj, l_doc_name))
    log.extend(_drop_echoed_direction_pin_duplicates(obj, l_doc_name))
    return log


#: A pin entry that says nothing except its own direction.
#:
#: MEASURED SHAPE, not a guess. A prose spec that writes "SPI data in", "SPI
#: data out" and "the four PWM outputs" yields, beside the seven real pins, two
#: extra entries:
#:
#:     {"name": "SPI", "mode": "input",  "function": "input",  "rtl_name": "spi"}
#:     {"name": "PWM", "mode": "output", "function": "output", "rtl_name": "pwm"}
#:
#: Neither carries a `width`, `msb` or `lsb`. Their `function` — the field that
#: is supposed to say what the pin DOES — is nothing but their own `mode`, the
#: direction word echoed back. `PWM` also duplicates the real `pwm` bus
#: case-insensitively, and that duplicate is the one with the consequence:
#: `spec_conformance_check` reads the width-less entry, defaults its width to 1
#: and reports
#:
#:     [ERROR] port-width-mismatch: port 'pwm' width RTL=4 vs spec=1
#:
#: on a design that is CORRECT. A blocking gate returning a false ERROR is the
#: mirror of the vacuous-PASS defect this tree has a gate family for, and it is
#: just as expensive: it blocks work that should land.
#:
#: WHAT IS DROPPED IS ONLY THE DUPLICATE. An echoed-direction entry that
#: duplicates nothing (`SPI` here) is LEFT IN PLACE and counted below, because
#: dropping it asserts that no real pin is ever named after its bus, and that is
#: a claim about naming conventions this predicate cannot support. The duplicate
#: needs no such claim: a same-named sibling already carries the width, so the
#: echoed entry is strictly less informative than the row it shadows.
_PIN_LIST_KEYS = ("pin_table", "top_ports", "ports", "top_module_pins")


def _is_echoed_direction_pin(entry: Any) -> bool:
    """True when a pin entry carries no width and its `function` is nothing
    but its own `mode` — the direction word echoed back as a description."""
    if not isinstance(entry, dict):
        return False
    if any(k in entry for k in ("width", "msb", "lsb")):
        return False
    mode = str(entry.get("mode") or entry.get("direction") or "").strip().lower()
    if not mode:
        return False
    fn = str(entry.get("function") or "").strip().lower()
    desc = str(entry.get("description") or "").strip().lower()
    # `description` is allowed to be absent; when present it must ALSO be the
    # bare direction, or the entry is carrying real information and stays.
    return fn == mode and desc in ("", mode)


def _drop_echoed_direction_pin_duplicates(obj: Any,
                                          l_doc_name: str) -> List["ScrubLog"]:
    """Remove a width-less, direction-echoing pin entry when a same-named
    sibling (case-insensitively) carries a real width. General: fires on any
    dict holding one of `_PIN_LIST_KEYS`; a no-op otherwise."""
    out: List[ScrubLog] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        for key in _PIN_LIST_KEYS:
            pins = node.get(key)
            if not isinstance(pins, list) or len(pins) < 2:
                continue
            widthed = {
                str(e.get("name", "")).strip().lower()
                for e in pins
                if isinstance(e, dict)
                and e.get("name")
                and any(k in e for k in ("width", "msb", "lsb"))
            }
            kept, dropped = [], []
            for e in pins:
                nm = (str(e.get("name", "")).strip().lower()
                      if isinstance(e, dict) else "")
                if nm and nm in widthed and _is_echoed_direction_pin(e):
                    dropped.append(str(e.get("name")))
                else:
                    kept.append(e)
            if dropped:
                node[key] = kept
                out.append(ScrubLog(
                    l_doc=l_doc_name,
                    pattern_name="echoed_direction_pin_duplicate",
                    path=key,
                    old_value=f"{len(pins)} entr(y/ies)",
                    new_value=f"{len(kept)} entr(y/ies)",
                    why=(f"dropped {len(dropped)} pin entr(y/ies) "
                         f"{dropped} that carried no width and whose "
                         f"`function` was only their own direction, while a "
                         f"same-named sibling carries a real width; the "
                         f"width-less row shadows the real one and makes "
                         f"spec_conformance_check report a false "
                         f"port-width-mismatch"),
                ))
        for v in node.values():
            visit(v)

    visit(obj)
    return out


# Opcode entries whose hex was scrubbed to this sentinel are dropped.
_SCRUBBED_HEX = "<HALLUCINATION_SCRUBBED>"


def _drop_scrubbed_opcodes(obj: Any, l_doc_name: str) -> List["ScrubLog"]:
    """Remove opcode entries whose `hex` is the scrub sentinel and
    recompute the L3 sibling flags. Returns an audit log. General:
    fires on any dict carrying an `opcodes` list; no-op otherwise."""
    out: List[ScrubLog] = []
    if not isinstance(obj, dict):
        return out
    ops = obj.get("opcodes")
    if not isinstance(ops, list) or not ops:
        return out
    kept = [op for op in ops
            if not (isinstance(op, dict) and op.get("hex") == _SCRUBBED_HEX)]
    dropped = len(ops) - len(kept)
    if dropped <= 0:
        return out
    obj["opcodes"] = kept
    out.append(ScrubLog(
        l_doc=l_doc_name, pattern_name="drop_scrubbed_opcode_zombie",
        path="opcodes", old_value=f"{len(ops)} entries",
        new_value=f"{len(kept)} entries",
        why=f"dropped {dropped} opcode(s) whose hex was scrubbed as a "
            f"hallucination; a scrubbed-hex opcode carries no real "
            f"encoding (consistent with ic_class_profile._l3_has_commands)",
    ))
    # Recompute the sibling flags the L3 emitter derives from `opcodes`
    # so they stay truthful after the drop.
    if "no_opcodes_in_input" in obj:
        obj["no_opcodes_in_input"] = not kept
    placeholder_names = {None, "", "OPCODE_NAME_UNKNOWN", "TODO"}
    ph = sum(1 for op in kept
             if isinstance(op, dict) and op.get("name") in placeholder_names)
    if "placeholder_opcode_count" in obj:
        obj["placeholder_opcode_count"] = ph
    if "no_opcode_names_in_input" in obj:
        obj["no_opcode_names_in_input"] = bool(kept) and ph == len(kept)
    return out


# ---------------------------------------------------------------------------
# ic_class single source of truth (ORGANIC-20260606 #465)
# ---------------------------------------------------------------------------
def canonical_ic_class(project_dir: Optional[Path]) -> Optional[str]:
    """Return the project's persisted ic_class from
    `<project_dir>/reports/ic_class.json` (the single source of truth set by
    `ic_class_profile.detect_ic_class`).

    ORGANIC-20260606 (#465 / continuation of #435 / #450): doc emitters must
    NOT stamp a hardcoded class constant nor blindly trust a caller-supplied
    class — that forks the source of truth and lets e.g. a pure-analog
    project carry `digital_arithmetic_primitive` in L19 while
    `reports/ic_class.json` correctly says `pure_analog`. The persisted file
    is authoritative.

    Returns:
      - the persisted `ic_class` string when the file exists and is valid,
      - `"unknown"` when the file is absent / unreadable / has no class
        (honest fail-closed — never a fabricated class),
      - `None` when `project_dir` is None (caller did not point at a project;
        the caller-supplied class is then used verbatim — but a hardcoded
        default constant is still forbidden by the caller contract).
    """
    if project_dir is None:
        return None
    persisted = Path(project_dir) / "reports" / "ic_class.json"
    if not persisted.is_file():
        return "unknown"
    try:
        d = json.loads(persisted.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    if isinstance(d, dict):
        cls = d.get("ic_class")
        if isinstance(cls, str) and cls:
            return cls
    return "unknown"


def restamp_l_doc_skeletons(project_dir: Optional[Path]) -> list[str]:
    """ORGANIC #635 — re-stamp any generated L*.json doc whose top-level
    `ic_class` DIVERGES from the now-authoritative persisted class
    (`reports/ic_class.json` via `canonical_ic_class`).

    Closes the phase1-before-phase2 ORDERING hole: the L14-L23 skeletons are
    stamped during phase1 — BEFORE phase2 persists `reports/ic_class.json`. At
    that point `canonical_ic_class()` reads an absent file → `"unknown"` and
    the emitter's mid-emission fallback can resolve a wrong/default class
    (e.g. `digital_arithmetic_primitive` for a data converter), which then
    freezes to disk and is never re-stamped. Call this at the phase2 boundary
    (right after the authoritative class is re-persisted) to rewrite the frozen
    stamps to the true class.

    SAFE + idempotent + chip-AGNOSTIC: rewrites ONLY a doc that ALREADY carries
    a non-empty string `ic_class` that DIFFERS from the authoritative class
    (never adds the field, never touches a doc that omits it); a no-op when the
    authoritative class is `unknown` (not yet resolved → cannot prove drift) or
    `None` (no project). Returns the list of rewritten relative paths. No chip /
    vendor / SKU literal — pure field comparison."""
    if project_dir is None:
        return []
    project = Path(project_dir)
    authoritative = canonical_ic_class(project)
    if not authoritative or authoritative == "unknown":
        return []
    rewritten: list[str] = []
    seen: set = set()
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("L*.json")):
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            stamped = doc.get("ic_class")
            if (isinstance(stamped, str) and stamped
                    and stamped != authoritative):
                doc["ic_class"] = authoritative
                try:
                    _stamp.dump(f, doc)
                    rewritten.append(str(f.relative_to(project)))
                except OSError:
                    pass
    return rewritten


# ---------------------------------------------------------------------------
# L14-L23 skeleton emission
# ---------------------------------------------------------------------------
def emit_l_doc_skeleton(l_doc_code: str,
                        ic_class: Optional[str] = None,
                        project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Produce a typed skeleton for an L doc the legacy runner doesn't
    know how to emit. Each skeleton carries:
      - doc_id / doc_name
      - applicability: APPLICABLE
      - ic_class
      - fields: { ... structured-typed empty containers ... }
      - evidence: []
      - extraction_hints: free-text guidance for a downstream extractor
                          (or for an AI backstop if no extractor exists)
      - extraction_status: NOT_YET_EXTRACTED
      - emitted_by

    The shape is the same for every L14-L23 emission so downstream
    consumers can detect "skeleton waiting for content".

    ic_class source of truth (ORGANIC-20260606 #465):
      - When `project_dir` is supplied, the stamped `ic_class` is ALWAYS read
        from `<project_dir>/reports/ic_class.json` (via `canonical_ic_class`),
        overriding any caller-supplied `ic_class`. This guarantees a single
        source of truth and prevents a stale/hardcoded class from leaking
        into the emitted doc (the #465 pure-analog/digital fork).
      - When `project_dir` is None, the caller-supplied `ic_class` is used
        verbatim, falling back to honest `"unknown"` if it too is None.
        Hardcoded default class constants are forbidden — never default to a
        concrete class such as `digital_arithmetic_primitive`.
    """
    resolved = canonical_ic_class(project_dir)
    if resolved is None:
        resolved = ic_class if ic_class else "unknown"
    spec = _tx.l_doc_spec(l_doc_code)
    fields_template = _skeleton_fields_for(l_doc_code)
    # stamp2 / l_doc_field_producer_check — `sdc_constraints_path` was a key
    # this emitter wrote and nothing ever populated, while the flow's own SDC
    # ground truth (`sdc_constraints.collect_sdc_files`) was on disk at emit
    # time. Populate it from the design's OWN staged file; a project staging
    # no SDC keeps the honest null. Keyed on the template rather than the
    # code spelling so every L19 emission path gets it.
    if "sdc_constraints_path" in fields_template and project_dir is not None:
        staged = _staged_sdc_rel(Path(project_dir))
        if staged is not None:
            fields_template["sdc_constraints_path"] = staged
    hints = _extraction_hints_for(l_doc_code)
    return {
        "doc_id": spec.code,
        "doc_name": spec.full_name,
        "applicability": "APPLICABLE",
        "ic_class": resolved,
        "fields": fields_template,
        "evidence": [],
        "extraction_hints": hints,
        "extraction_status": "NOT_YET_EXTRACTED",
        "emitted_by": _pmd.emitted_by(
            "phase1_post_process.emit_l_doc_skeleton"),
    }


def _staged_sdc_rel(project_dir: Path) -> Optional[str]:
    """Project-relative posix path of the design's own primary staged SDC.

    `sdc_constraints.collect_sdc_files` is the ONE definition of the staged
    constraints ground truth (`input/constraints/` first, then
    `input/reference_flow/`), and phase3's synth step consumes that list in
    that order — so the path recorded here names the file the flow will
    actually read first. Never invents: the value is a file that exists at
    emit time, so the L19-4 dangling-path advisory cannot fire on a produced
    value. Returns None when the design stages no SDC, or when the staged
    file resolves outside the project (a symlinked stage must not leak an
    absolute foreign path into a published L-doc).
    """
    try:
        from sdc_constraints import collect_sdc_files
    except ImportError:
        return None
    try:
        files = collect_sdc_files(project_dir)
    except OSError:
        return None
    if not files:
        return None
    try:
        return (files[0].resolve()
                .relative_to(project_dir.resolve()).as_posix())
    except (ValueError, OSError):
        return None


def _skeleton_fields_for(l_doc_code: str) -> Dict[str, Any]:
    """Typed empty-fields template per L doc category."""
    return {
        "L14": {
            "versions": [],          # [{version_id, release_date, deltas}]
            "deprecated_features": [],
            "backward_compat_traps": [],
        },
        "L15": {
            "tables": [],            # [{name, field_bits, encoding: [...]}]
        },
        "L16": {
            "properties": [],        # [{id, scope, formal_shape, citation}]
        },
        "L17": {
            "channels": [],          # [{name, direction, signals: [...]}]
            "dependency_graph": {},
        },
        "L18": {
            "interconnect_rules": [],
            "default_signal_values": {},
            "id_routing": {},
        },
        "L19": {
            "pdk_target": None,      # e.g. "sky130A"
            "die_area_budget_um": None,
            "power_budget_uw": None,
            "sdc_constraints_path": None,
            "floorplan_hints": [],
        },
        "L20": {
            "scan_chains": [],       # [{name, length, frequency_mhz}]
            "test_compression": None,
            "bist_mbist": [],
            "jtag_tap": None,
        },
        "L21": {
            "power_domains": [],     # [{name, supply, retention}]
            "isolation_cells": [],
            "level_shifters": [],
            "upf_path": None,
        },
        "L22": {
            "coverage_goals": [],    # [{group, target_pct}]
            "formal_properties": [],
            "regression_matrix": {},
        },
        "L23": {
            "key_handling": {},
            "attack_surface": [],
            "side_channel_mitigation": [],
            "secure_boot": False,
        },
        # ── Completeness extensions (L24-L27). chip-AGNOSTIC placeholders /
        # nulls only — NO fabricated values. ─────────────────────────────
        "L24": {
            "drc_status": None,        # e.g. "CLEAN" / "N violations" / null
            "lvs_status": None,
            "sta_status": None,
            "antenna_status": None,
            "ir_drop_status": None,
            "tapeout_gates": [],       # [{gate, status, waiver_ref}]
        },
        "L25": {
            "mission_profile": None,   # e.g. lifetime-weighted load profile
            "temp_range": None,        # e.g. {"min_c": null, "max_c": null}
            "qual_standard": None,     # e.g. "JESD47" / "AEC-Q100" / null
            "em_budget": None,
            "aging_margin": None,      # NBTI / HCI aging headroom
        },
        "L26": {
            "transducer_type": None,   # transduction principle
            "movable_structures": [],  # [{name, kind, dimensions}]
            "package_stress": None,
        },
        "L27": {
            "spd_revision": None,      # SPD spec revision
            "module_type": None,       # JEDEC module type
            "timing_parameters": [],   # [{name, value, units}]
            "manufacturer_data": {},   # module-level metadata block
        },
    }.get(l_doc_code, {})


def _extraction_hints_for(l_doc_code: str) -> List[str]:
    """Per-category extraction guidance for the downstream extractor /
    AI backstop. Surfaces what KIND of fact the bucket holds."""
    return {
        "L14": [
            "Look for 'Version' / 'Revision' / 'Issue' section headers.",
            "Capture per-version delta-tables (what changed).",
            "Capture explicit 'deprecated' callouts.",
        ],
        "L15": [
            "Look for tables labelled 'encoding' / 'opcodes' / "
            "'<field> encoding'.",
            "Capture the bits, mnemonic, semantic per row.",
            "REQUIRED: each table must cite source page + table number.",
        ],
        "L16": [
            "Look for sentences shaped 'must' / 'shall' / 'is required'.",
            "Capture as {id, scope, english_form, optional_sva_form, citation}.",
        ],
        "L17": [
            "Look for channel definitions (e.g. 'AR channel signals').",
            "Capture {name, direction, width, semantics, optional} per signal.",
            "Build dependency_graph from VALID/READY ordering rules.",
        ],
        "L18": [
            "Look for interconnect / fabric / topology sections.",
            "Capture default-signal-value table.",
            "Capture ID-routing rules (ID width changes at fabric).",
        ],
        "L19": [
            "Look for floorplan, area, power, timing constraints.",
            "Capture PDK target if stated.",
        ],
        "L20": [
            "Look for scan / DFT / BIST / JTAG sections.",
            "Capture chain count, length, frequency.",
        ],
        "L21": [
            "Look for power-domain partitioning, supply nets.",
            "Capture isolation / retention / level-shifting requirements.",
        ],
        "L22": [
            "Look for coverage targets, vplan, regression policy.",
            "Capture per-feature coverage goals.",
        ],
        "L23": [
            "Look for key-management, side-channel, secure-boot sections.",
            "Capture attack surface enumeration.",
        ],
        # ── Completeness extensions (L24-L27). ───────────────────────────
        "L24": [
            "Look for signoff / tapeout / sign-off checklist sections.",
            "Capture DRC / LVS / STA / antenna / IR-drop status per gate.",
            "Capture the tapeout gate list + any waiver references.",
        ],
        "L25": [
            "Look for reliability / qualification / mission-profile sections.",
            "Capture qual standard (JESD47, AEC-Q100/Q200) if stated.",
            "Capture temperature range, EM budget, NBTI/HCI aging margins.",
        ],
        "L26": [
            "Look for MEMS / mechanical / transducer / movable-structure "
            "sections (membranes, cantilevers, springs).",
            "Capture transduction principle + package/mechanical stress.",
            "OPT-IN: only a dedicated MEMS class carries this layer.",
        ],
        "L27": [
            "Look for JEDEC SPD / module-config / self-describing-config "
            "sections (EE1004 / TSE2004av / SPD5118).",
            "Capture SPD revision, module type, module timing parameters.",
            "OPT-IN: only a dedicated memory-module class carries this layer.",
        ],
    }.get(l_doc_code, [])


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@dataclass
class PostProcessResult:
    project_dir: str
    ic_class: str
    scrubbed_count: int
    scrub_log: List[ScrubLog]
    skeleton_emitted: List[str]   # L doc codes
    na_stubs_emitted: List[str]   # L doc codes
    verdict: str                  # PASS | WARN

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "ic_class": self.ic_class,
            "scrubbed_count": self.scrubbed_count,
            "scrub_log": [s.as_dict() for s in self.scrub_log],
            "skeleton_emitted": self.skeleton_emitted,
            "na_stubs_emitted": self.na_stubs_emitted,
            "verdict": self.verdict,
            "emitted_by": _pmd.emitted_by("phase1_post_process"),
        }


def post_process(project_dir: Path, ic_class: str) -> PostProcessResult:
    """Apply scrub + skeleton + N/A-stub emission to a project's
    `phase1/generated_docs/` directory.

    Effects on filesystem:
      - Existing L1..L13 JSONs that contain hallucinated values are
        overwritten with the scrubbed content.
      - L docs in `not_applicable(ic_class)` are overwritten with na_stub.
      - L docs in `applicable(ic_class)` that DON'T exist yet are emitted
        as skeletons.
    """
    docs_dir = project_dir / "phase1" / "generated_docs"
    if not docs_dir.exists():
        docs_dir.mkdir(parents=True, exist_ok=True)

    # ORGANIC-20260606 #465 — single source of truth. The persisted
    # reports/ic_class.json is authoritative; a caller-supplied ic_class is
    # only a fallback for when the project has not persisted one yet. This
    # prevents a stale/hardcoded class from forking emitted-doc stamps away
    # from reports/ic_class.json.
    persisted_class = canonical_ic_class(project_dir)
    if persisted_class is not None and persisted_class != "unknown":
        ic_class = persisted_class

    scrub_log: List[ScrubLog] = []
    skeleton: List[str] = []
    na_stubs: List[str] = []

    applicable = _tx.applicable_l_docs(ic_class)
    not_applicable = _tx.not_applicable_l_docs(ic_class)

    # Scrub + (if not_applicable) replace existing files
    for spec in _tx.L_DOCS_V2:
        target_path = docs_dir / f"{spec.full_name}.json"

        # Case (a): not_applicable — overwrite with na_stub
        if spec.code in not_applicable:
            stub = _tx.na_stub(ic_class, spec.code)
            _stamp.dump(target_path, stub)
            na_stubs.append(spec.code)
            continue

        # Case (b): applicable AND existing → scrub
        if target_path.exists():
            try:
                content = json.loads(target_path.read_text(encoding="utf-8"))
            except Exception:
                content = {}
            entries = scrub_l_doc(content, spec.full_name)
            if entries:
                scrub_log.extend(entries)
                _stamp.dump(target_path, content)
            continue

        # Case (c): applicable but missing → emit skeleton
        if spec.code in applicable:
            sk = emit_l_doc_skeleton(spec.code, ic_class,
                                     project_dir=project_dir)
            _stamp.dump(target_path, sk)
            skeleton.append(spec.code)

    verdict = "WARN" if scrub_log else "PASS"
    return PostProcessResult(
        project_dir=str(project_dir),
        ic_class=ic_class,
        scrubbed_count=len(scrub_log),
        scrub_log=scrub_log,
        skeleton_emitted=skeleton,
        na_stubs_emitted=na_stubs,
        verdict=verdict,
    )


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Phase 1 post-processor: scrub halluc + emit "
                    "applicability-aware L14-L23 skeletons.")
    p.add_argument("project_dir", type=Path)
    p.add_argument("--ic-class", required=True,
                   help="ic_class for the project; controls "
                        "applicability map per l_doc_taxonomy")
    p.add_argument("--out-json", type=Path,
                   help="Audit JSON output (scrub log + skeleton list)")
    args = p.parse_args()
    rep = post_process(args.project_dir, args.ic_class)
    payload = rep.as_dict()
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
