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
        - L3 opcodes lifted from page-format numbers (e.g. "23 16"
          and "55 48" in §A3.4.4 narrow-transfer figures of AMBA AXI)

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

# Importable as both a script and a module
try:
    import l_doc_taxonomy as _tx
except ImportError:  # pragma: no cover
    from . import l_doc_taxonomy as _tx  # type: ignore


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
    # opcode hex lifted from byte-position numbers like "23 16" / "55 48"
    # (AMBA AXI §A3.4.4 narrow-transfer figures), where the value is
    # really a bit-position label not an opcode encoding.
    HallucPattern(
        name="opcode_from_two_digit_decimal_page_number",
        affected_keys=[r"opcodes\[\d+\]\.hex", "opcode_hex", "hex"],
        value_pattern=re.compile(
            r"^0x(?:16|17|23|24|47|48|55|56)$"),
        replacement="<HALLUCINATION_SCRUBBED>",
        why="hex value matches a 2-digit decimal page-format number "
            "commonly lifted from byte-position figures; not a real "
            "opcode encoding",
    ),
    # The same opcode hex appearing in a value string (e.g. L10 test
    # cases referencing the L3 hallucinated opcode by quoting it as
    # part of a test description like "opcode_hex": "0x16").
    HallucPattern(
        name="opcode_hex_in_test_case_value",
        affected_keys=[r".*opcode.*"],
        value_pattern=re.compile(
            r'.*"opcode_hex"\s*:\s*"0x(?:16|17|23|24|47|48|55|56)".*'),
        replacement="<HALLUCINATION_SCRUBBED>",
        why="L10 test case references the L3 hallucinated page-number "
            "opcode by quoting; clean up downstream contamination",
    ),
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
    # it carries no trustworthy encoding and (for bus-interconnect specs
    # with no real command protocol, e.g. AMBA AXI) was synthesised from
    # page-format figures in the first place. Leaving it in `opcodes`
    # makes `no_opcodes_in_input` lie (False) and trips
    # l3_opcode_name_coverage_check (every zombie name is
    # OPCODE_NAME_UNKNOWN → 100% placeholder → FAIL → runner exit 1).
    # ic_class_profile._l3_has_commands already filters these out; do the
    # same at the source so generated_docs match a fresh extraction
    # (which carries no opcodes key at all). General / sentinel-based —
    # no protocol name in the predicate.
    log.extend(_drop_scrubbed_opcodes(obj, l_doc_name))
    return log


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
# L14-L23 skeleton emission
# ---------------------------------------------------------------------------
def emit_l_doc_skeleton(l_doc_code: str, ic_class: str) -> Dict[str, Any]:
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
    """
    spec = _tx.l_doc_spec(l_doc_code)
    fields_template = _skeleton_fields_for(l_doc_code)
    hints = _extraction_hints_for(l_doc_code)
    return {
        "doc_id": spec.code,
        "doc_name": spec.full_name,
        "applicability": "APPLICABLE",
        "ic_class": ic_class,
        "fields": fields_template,
        "evidence": [],
        "extraction_hints": hints,
        "extraction_status": "NOT_YET_EXTRACTED",
        "emitted_by": "phase1_post_process.emit_l_doc_skeleton v0.1.51",
    }


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
            "emitted_by": "phase1_post_process v0.1.51",
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
            target_path.write_text(
                json.dumps(stub, indent=2), encoding="utf-8")
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
                target_path.write_text(
                    json.dumps(content, indent=2), encoding="utf-8")
            continue

        # Case (c): applicable but missing → emit skeleton
        if spec.code in applicable:
            sk = emit_l_doc_skeleton(spec.code, ic_class)
            target_path.write_text(
                json.dumps(sk, indent=2), encoding="utf-8")
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
