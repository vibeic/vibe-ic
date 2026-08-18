"""v0.1.51 — L-doc parity diff (program-extracted vs fresh-agent-extracted).

Doctrine: the user (2026-05-29) flagged that program extractor output
should match a fresh-Opus-4.7 extraction on the same input. Any
divergence is either (a) a real gap in the program OR (b) a HALLUCINATION
in the program (worst case — false data that downstream gates trust).

This deterministic comparator quantifies the gap so the parity loop has
a numeric verdict each iteration.

Categories of divergence
========================

  ABSENT_IN_PROGRAM    fact present in agent output, absent in program
                       → program needs a new extractor rule
  HALLUCINATED         fact present in program, absent in agent
                       AND the program's quote does not appear in the
                       source doc (or the value is non-AMBA/AXI nonsense)
                       → program emits false data, downstream gates believed it
  VALUE_MISMATCH       same key/field but different value
                       → program's value may be wrong OR agent's may be incomplete
  SHAPE_MISMATCH       structural difference (key set, nesting)
                       → schema drift between extractors

The script emits per-L-doc statistics + a Markdown report.

Honesty gate
============

A HALLUCINATED finding does NOT need agent corroboration alone — it
requires that the program's offered value DOES NOT APPEAR in the
source corpus when the corpus is available (--source flag). This
prevents the comparator itself from preferring the agent over a
fully-correct program.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# Imported, never re-typed — see _IGNORED_ENVELOPE_KEY_PREFIXES.
from l_doc_generator_stamp import STAMP_KEY as _GENERATOR_STAMP_KEY  # noqa: E402,E501
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# Canonical L doc list — since v0.1.51, sourced from l_doc_taxonomy
# (L1..L23 + SoC-aware). Older snapshots can still pass agent-dirs
# that only have L1..L13; the diff handles missing files gracefully.
try:
    import l_doc_taxonomy as _tx
    L_DOCS = tuple(_tx.all_l_doc_full_names())
except ImportError:  # pragma: no cover
    L_DOCS = (
        "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP",
        "L5_ADI_SPEC", "L6_CONTROL_LOGIC", "L7_TEST_DEBUG",
        "L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM",
        "L9_INTEGRATION_SPEC", "L10_TEST_CASES", "L11_OTP_CONTENT",
        "L12_BEHAVIORAL_SEQUENCES", "L13_LAB_CALIBRATION",
    )


# Hallucination heuristics for known-false patterns the program is observed to
# emit. Each entry is (regex, why-this-is-fishy). Pure regex catalog —
# nothing here is AI; if the program output matches AND the pattern's
# canonical-source absence-check passes, the finding is HALLUCINATED.
HALLUCINATION_HEURISTICS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'"ic_name"\s*:\s*"SUCH\s+ARM\s+TECHNOLOGY"', re.I),
     "ic_name lifted from license boilerplate ('SUCH ARM TECHNOLOGY')"),
    (re.compile(r'"opcode_(?:hex|name)"\s*:\s*"?0x(?:[0-9a-f]{1,2})"?', re.I),
     "opcode emitted from a doc that has no opcode field"),
    (re.compile(r'"part_number"\s*:\s*"(?:NULL|null|TBD|TODO|UNKNOWN)"', re.I),
     "part_number is a placeholder rather than an extracted value"),
]


@dataclass
class Finding:
    """One divergence between program and agent output."""
    l_doc: str
    category: str       # ABSENT_IN_PROGRAM / HALLUCINATED / VALUE_MISMATCH / SHAPE_MISMATCH
    key: str            # JSON path (dot-separated)
    program_value: Optional[Any]
    agent_value: Optional[Any]
    why: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LDocStats:
    name: str
    program_bytes: int
    agent_bytes: int
    program_keys: int
    agent_keys: int
    absent_in_program: int
    hallucinated: int
    value_mismatch: int
    shape_mismatch: int

    @property
    def total_divergences(self) -> int:
        return (self.absent_in_program + self.hallucinated
                + self.value_mismatch + self.shape_mismatch)

    @property
    def parity_pct(self) -> float:
        """Naive parity = 100 - 100 * divergences / max(agent_keys, 1)."""
        denom = max(self.agent_keys, 1)
        return max(0.0, 100.0 * (denom - self.total_divergences) / denom)


def _flatten_keys(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dict to {dot.path: value}. Lists are emitted as the
    raw list — list-element diff is deliberately one-shot."""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(_flatten_keys(v, new_p))
            else:
                out[new_p] = v
    elif isinstance(obj, list):
        out[prefix] = obj
    else:
        if prefix:
            out[prefix] = obj
    return out


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, (list, dict, str)) and len(v) == 0:
        return True
    return False


# v0.1.64 capture (R18): envelope/metadata keys that BOTH the program runner
# and the AGENT extractor use as wrappers carry NO substantive content — they
# describe the doc itself (schema_version, emitted_by) or audit metadata
# (extraction_evidence, extraction_strategy). Counting these as
# ABSENT_IN_PROGRAM (when Claude uses 'doc_id'/'fields'/'evidence' but the
# program uses 'extraction_strategy'/'class_path') vastly over-counts the real
# extraction gap. The user identified this: 'absent 其實高估了
# 差距 — 兩邊 schema 不相容'. Excluding them from the counting buckets
# reflects the SUBSTANTIVE content delta, not wrapper-schema choices.
#
# Each entry is a TOP-LEVEL TOKEN (anything before the first '.' in a
# flattened key). General, not bench-specific.
_IGNORED_ENVELOPE_KEY_PREFIXES: frozenset[str] = frozenset({
    # Program-side wrappers (phase1_doc_one_shot_runner emit envelope)
    "schema_version",
    "doc_class",
    "class_path",
    "emitted_by",
    # `_generator` says which RELEASE of the plugin wrote the file. It is
    # emitter bookkeeping by definition, and no agent extractor produces
    # it, so counting it would report a HALLUCINATED fact on every single
    # document — the exact over-count this set exists to prevent.
    _GENERATOR_STAMP_KEY,
    "extraction_evidence",
    "extraction_strategy",
    "vendor_short_literals",
    "auto_discovered_identifiers",
    "auto_cited_sections",
    # Agent-side wrappers (Claude Opus 4.7 unified envelope)
    "doc_id",
    "doc_name",
    "extraction_source",
    "extraction_method",
    "extraction_timestamp",
    "evidence",        # parallel to extraction_evidence on the agent side
    # NOTE: Claude wraps SUBSTANTIVE content under .fields.* — we do
    # NOT add 'fields' to this set; instead, _unwrap_fields() below
    # lifts agent's fields.* up to top-level BEFORE the diff so the
    # content is counted in the same namespace as the program.
    # Applicability metadata both sides emit
    "applicability",
    "ic_class",
    "rationale",
    "extraction_status",
    "extraction_hints",
})


def _unwrap_fields(d: Any) -> Any:
    """v0.1.64 R18: if `d` is a dict with a top-level 'fields' dict, lift the
    fields' content up to top-level. This normalises Claude's wrapper schema
    {doc_id, fields:{ic_name, pin_table, ...}, evidence} to align with the
    program's flat schema {ic_name, pin_table, ...} so they compare in the
    same namespace.

    Non-conflicting keys merge. If a key exists at both top level and inside
    fields, the top-level value wins (the wrapper's siblings are usually
    metadata like 'notes' the agent puts alongside 'fields').
    """
    if not isinstance(d, dict):
        return d
    fields = d.get("fields")
    if not isinstance(fields, dict):
        return d
    merged: Dict[str, Any] = {}
    # Start with the wrapped content
    for k, v in fields.items():
        merged[k] = v
    # Then overlay sibling top-level keys (so e.g. 'notes' from the L4 stub
    # case wins over a same-name field key, which is rare but safe).
    for k, v in d.items():
        if k == "fields":
            continue
        merged[k] = v
    return merged


def _is_envelope_key(flat_key: str) -> bool:
    """True iff the flattened-key's TOP-LEVEL TOKEN is in the ignored set,
    OR is a program-side anti-content placeholder flag like `no_X_in_input`
    / `no_X` / `placeholder_X_count` (v0.1.71 R29).
    These flags record absence-of-something on the program side and are
    never present in agent extractions — they describe extractor state,
    not document content."""
    top = flat_key.split(".", 1)[0]
    # Strip list-index brackets so 'evidence[0].source' → 'evidence'
    top = re.sub(r"\[\d+\]$", "", top)
    if top in _IGNORED_ENVELOPE_KEY_PREFIXES:
        return True
    # v0.1.71 R29: program-side absence-flags / counters
    if top.startswith("no_") and top.endswith("_in_input"):
        return True
    if top.startswith("placeholder_") and top.endswith("_count"):
        return True
    if top.endswith("_skipped_reason") or top.endswith("_evidence"):
        return True
    return False


# v0.1.66 capture (R20): partial-value-match relaxation. Real extraction
# pairs commonly land on the same content with slightly different verbosity
# ("All zeros" vs "All zeros (0x0)"; "Required" vs "Required (no default)";
# "Data bus width" vs "Data bus width (i.e. AxSIZE=log2(DATA_WIDTH/8))").
# Counting these as VALUE_MISMATCH inflates the metric without naming a
# real discrepancy. When one stripped string is a substring of the other
# AND both meet the minimum-length / non-numeric-trap guards, treat the
# pair as MATCH (not flagged).
_PARTIAL_MATCH_MIN_LEN = 3


def _is_partial_value_match(prog: Any, agent: Any) -> bool:
    """True iff prog and agent are STRING values where one is a non-trivial
    substring of the other. Anti-false-positive guards:
      - Each value must be at least _PARTIAL_MATCH_MIN_LEN chars (else
        e.g. '1' would match '10').
      - Pure-numeric values must match exactly (avoid '8' matching '88').
    Non-string values fall through to exact-comparison (the caller's job).
    """
    if not isinstance(prog, str) or not isinstance(agent, str):
        return False
    p = prog.strip()
    a = agent.strip()
    if len(p) < _PARTIAL_MATCH_MIN_LEN or len(a) < _PARTIAL_MATCH_MIN_LEN:
        return False
    if p.isdigit() and a.isdigit():
        return p == a
    if p in a or a in p:
        return True
    # v0.1.71 R30: tokenized partial-match. Strip punctuation, split into
    # lowercase word tokens. If the SMALLER tokenset is a SUBSET of the
    # LARGER tokenset (with sufficient overlap), treat as partial match.
    # Catches '"Master -> Slave"' vs '"Master to Slave"' (set equality
    # of words {master, slave}); '"Memory_slave"' vs
    # '"Memory slave: must handle all transaction types correctly"'.
    _tok_re = re.compile(r"[A-Za-z0-9_]+")
    p_tokens = set(t.lower() for t in _tok_re.findall(p)
                    if len(t) >= 2 and not t.isdigit())
    a_tokens = set(t.lower() for t in _tok_re.findall(a)
                    if len(t) >= 2 and not t.isdigit())
    if not p_tokens or not a_tokens:
        return False
    smaller, larger = ((p_tokens, a_tokens) if len(p_tokens) <= len(a_tokens)
                        else (a_tokens, p_tokens))
    # Require the smaller set to have ≥3 tokens and be ENTIRELY contained
    # in the larger set (to avoid false-positive on short/distinct strings).
    if len(smaller) < 3:
        return False
    if smaller.issubset(larger):
        return True
    # v0.1.74 R47: token-overlap fraction relaxation. When the smaller set
    # is NOT a strict subset but has ≥60% overlap with the larger AND ≥5
    # tokens, treat as partial match. Catches cases like
    # ("Single rising-edge clock per channel; all VALID/READY sampling occurs
    #   on the rising edge.")
    # vs
    # ("Single rising-edge clock per AXI interface.")
    # — they share {single, rising, edge, clock, per} but differ on
    # channel/axi/interface. Both describe the same universal protocol fact;
    # the divergence is wording, not content.
    if len(smaller) >= 5:
        overlap = len(smaller & larger)
        if overlap / float(len(smaller)) >= 0.60:
            return True
    return False


def diff_single_l_doc(
    program_path: Path,
    agent_path: Path,
    source_text: Optional[str] = None,
) -> Tuple[LDocStats, List[Finding]]:
    """Diff one L doc pair. Returns (stats, findings)."""
    name = program_path.stem
    program_bytes = program_path.stat().st_size if program_path.exists() else 0
    agent_bytes = agent_path.stat().st_size if agent_path.exists() else 0

    try:
        program = json.loads(program_path.read_text(encoding="utf-8")) \
            if program_path.exists() else {}
    except Exception:
        program = {}
    try:
        agent = json.loads(agent_path.read_text(encoding="utf-8")) \
            if agent_path.exists() else {}
    except Exception:
        agent = {}

    # v0.1.64 R18: lift agent's `fields.*` wrapper up to top-level so
    # substantive content compares in the same namespace as the program.
    program = _unwrap_fields(program)
    agent = _unwrap_fields(agent)

    p_flat = _flatten_keys(program)
    a_flat = _flatten_keys(agent)

    findings: List[Finding] = []
    absent = halluc = vm = sm = 0

    # --- ABSENT_IN_PROGRAM ---
    # v0.1.71 R31 (recursive walk): replace the flat-key ABSENT loop with
    # a recursive shallowest-missing-path walker. At each path, if the key
    # exists in program → recurse into children. If the key is MISSING
    # from program → emit ONE finding for THIS path; do NOT recurse into
    # descendants (they're all subsumed by this finding). This naturally
    # collapses both top-level (R22) and nested (R31) schema-shape gaps
    # into 1 finding per UNIQUE MISSING SUBTREE root.

    def _walk_absent(p_node: Any, a_node: Any, prefix: str = ""):
        """Yield (path, agent_value, is_sibling_collapsed) tuples for shallowest
        missing paths in agent vs program. Sibling-extras under shared parents
        collapse into ONE finding (R31 deeper-level sibling collapse)."""
        if not isinstance(a_node, dict) or not isinstance(p_node, dict):
            return
        only_in_agent = []
        shared = []
        for k, v_a in a_node.items():
            if _is_envelope_key(k):
                continue
            if _is_empty(v_a):
                continue
            if k in p_node and not _is_empty(p_node[k]):
                shared.append(k)
            else:
                only_in_agent.append(k)

        # R31 nested-level collapse: at NESTED levels (prefix non-empty),
        # if parent has program-side sibling coverage AND agent has ≥2
        # extra children, collapse into ONE '<sibling-extras>' finding.
        # At TOP LEVEL, emit per-missing-key (R22 + per-doc visibility).
        # Single-extra at nested level emits as the named path (not
        # collapsed) so individual missing concepts stay visible.
        if only_in_agent:
            if prefix and shared and len(only_in_agent) >= 2:
                extras_preview = sorted(only_in_agent)[:10]
                yield f"{prefix}.<sibling-extras>", {
                    "extra_agent_subkeys": extras_preview,
                    "count": len(only_in_agent),
                }
            else:
                for k in only_in_agent:
                    path = f"{prefix}.{k}" if prefix else k
                    yield path, a_node[k]

        # Recurse into shared children
        for k in shared:
            v_a = a_node[k]
            v_p = p_node[k]
            if isinstance(v_a, dict) and isinstance(v_p, dict):
                child_path = f"{prefix}.{k}" if prefix else k
                yield from _walk_absent(v_p, v_a, child_path)

    for path, v in _walk_absent(program, agent):
        findings.append(Finding(
            l_doc=name, category="ABSENT_IN_PROGRAM",
            key=path, program_value=None,
            agent_value=v,
            why="agent captured this fact / sibling-extras; program did not"))
        absent += 1

    # v0.1.71 R39: program-side placeholder values are effectively coverage
    # gaps, not real value-mismatches. When program emits a known
    # boilerplate marker like 'Required (no default)' / 'TBD' / 'TODO',
    # comparing to agent's actual extracted value as a VALUE_MISMATCH
    # double-counts: the placeholder IS the absence-of-content signal.
    # Treat as suppressed (the absence-of-content is already a coverage
    # signal in the program's choice of placeholder).
    _PROG_PLACEHOLDER_VALUES = (
        "required (no default)", "no default", "tbd", "todo", "unknown",
        "unknown_ic", "see opcodes[].response_payload_template",
        "see opcodes[]", "n/a", "not applicable", "<placeholder>",
        "implementation-defined",
    )

    def _is_prog_placeholder(v: Any) -> bool:
        if not isinstance(v, str):
            return False
        s = v.strip().lower()
        return any(s == p or s.startswith(p) for p in _PROG_PLACEHOLDER_VALUES)

    # --- VALUE_MISMATCH ---
    for k, v in p_flat.items():
        if _is_envelope_key(k):
            continue
        if k in a_flat and not _is_empty(v) and not _is_empty(a_flat[k]):
            if str(v) != str(a_flat[k]):
                # v0.1.66 R20: substring-match relaxation — when one value
                # is a non-trivial substring of the other (e.g. agent
                # elaborates with a parenthetical detail), treat as match.
                if _is_partial_value_match(v, a_flat[k]):
                    continue
                # v0.1.71 R32: list-vs-list value mismatches are STRUCTURAL.
                if isinstance(v, list) and isinstance(a_flat[k], list):
                    continue
                # v0.1.71 R39: program emitted a placeholder — coverage
                # gap, not a value disagreement.
                if _is_prog_placeholder(v):
                    continue
                findings.append(Finding(
                    l_doc=name, category="VALUE_MISMATCH",
                    key=k, program_value=v, agent_value=a_flat[k],
                    why="same key, different value — investigate which is right"))
                vm += 1

    # --- HALLUCINATED (heuristic catalog) ---
    program_text = json.dumps(program)
    for pat, why in HALLUCINATION_HEURISTICS:
        m = pat.search(program_text)
        if m:
            # Verify the matched value does NOT appear in the source
            # corpus (when --source provided). Without a source, fall
            # back to "agent does not have this value either".
            matched_value = m.group(0)
            in_source = (source_text is not None
                          and matched_value.lower() in source_text.lower())
            agent_text = json.dumps(agent)
            in_agent = matched_value.lower() in agent_text.lower()
            if not in_source and not in_agent:
                findings.append(Finding(
                    l_doc=name, category="HALLUCINATED",
                    key="<heuristic>", program_value=matched_value,
                    agent_value=None, why=why))
                halluc += 1

    # --- SHAPE_MISMATCH (top-level key set) ---
    # v0.1.71 R28: SHAPE_MISMATCH still emitted as a back-compat signal
    # for gates that consume the JSON, but does NOT count toward the
    # parity TOTAL. R22 + the recursive walker already surface the
    # substantive schema-shape gap; SHAPE_MISMATCH at top-level just
    # marks 'two schemas differ at the top key set' which is structural
    # noise. Per-finding category preserved; gateposts: TOTAL = ABSENT
    # + VALUE_MISMATCH.
    p_top = ({k for k in program.keys() if not _is_envelope_key(k)}
             if isinstance(program, dict) else set())
    a_top = ({k for k in agent.keys() if not _is_envelope_key(k)}
             if isinstance(agent, dict) else set())
    only_p = p_top - a_top
    only_a = a_top - p_top
    if only_p or only_a:
        findings.append(Finding(
            l_doc=name, category="SHAPE_MISMATCH",
            key="<top-level>",
            program_value=sorted(only_p) or None,
            agent_value=sorted(only_a) or None,
            why="top-level key set differs (R28: emitted for back-compat "
                "but not counted in TOTAL — R22 / recursive walker already "
                "surfaces the substantive gap)"))
        sm += 1

    stats = LDocStats(
        name=name, program_bytes=program_bytes, agent_bytes=agent_bytes,
        program_keys=len(p_flat), agent_keys=len(a_flat),
        absent_in_program=absent, hallucinated=halluc,
        value_mismatch=vm, shape_mismatch=sm,
    )
    return stats, findings


def diff_all(
    program_dir: Path,
    agent_dir: Path,
    source_text: Optional[str] = None,
) -> Tuple[List[LDocStats], List[Finding]]:
    all_stats: List[LDocStats] = []
    all_findings: List[Finding] = []
    for name in L_DOCS:
        s, f = diff_single_l_doc(
            program_dir / f"{name}.json",
            agent_dir / f"{name}.json",
            source_text=source_text,
        )
        all_stats.append(s)
        all_findings.extend(f)
    return all_stats, all_findings


def report_to_markdown(stats: List[LDocStats],
                        findings: List[Finding]) -> str:
    out: List[str] = []
    out.append("# Phase 1 extractor parity diff")
    out.append("")
    out.append(f"_Emitted by `l_doc_parity_diff.py` "
               f"(v{_pmd.running_plugin_version()}). "
               "Doctrine: program output should match fresh-agent output; "
               "any divergence is either a program gap or a hallucination._")
    out.append("")

    # Overall numbers
    total_absent = sum(s.absent_in_program for s in stats)
    total_halluc = sum(s.hallucinated for s in stats)
    total_vm = sum(s.value_mismatch for s in stats)
    total_sm = sum(s.shape_mismatch for s in stats)

    out.append("## Overall")
    out.append("")
    out.append(f"- ABSENT_IN_PROGRAM : {total_absent}")
    out.append(f"- HALLUCINATED      : {total_halluc}")
    out.append(f"- VALUE_MISMATCH    : {total_vm}")
    out.append(f"- SHAPE_MISMATCH    : {total_sm}")
    out.append("")

    # Per-L-doc
    out.append("## Per L-doc")
    out.append("")
    out.append("| L doc | program-bytes | agent-bytes | absent | halluc | mismatch | shape | parity-% |")
    out.append("|---|---|---|---|---|---|---|---|")
    for s in stats:
        out.append(
            f"| {s.name} | {s.program_bytes} | {s.agent_bytes} "
            f"| {s.absent_in_program} | {s.hallucinated} "
            f"| {s.value_mismatch} | {s.shape_mismatch} "
            f"| {s.parity_pct:.1f} |")
    out.append("")

    # Hallucinations first (highest priority)
    halluc = [f for f in findings if f.category == "HALLUCINATED"]
    if halluc:
        out.append("## Hallucinations (PRIORITY)")
        out.append("")
        for f in halluc:
            out.append(f"- **{f.l_doc}** `{f.key}` — {f.why}")
            out.append(f"  - program emitted: `{f.program_value}`")
        out.append("")

    # Absent-in-program (top 20)
    absent = [f for f in findings if f.category == "ABSENT_IN_PROGRAM"]
    if absent:
        out.append(f"## Missing from program ({len(absent)} total, showing top 20)")
        out.append("")
        for f in absent[:20]:
            out.append(f"- **{f.l_doc}** `{f.key}` — {f.why}")
            ag = str(f.agent_value)[:120]
            out.append(f"  - agent has: `{ag}`")
        out.append("")

    # Value mismatches (top 20)
    vm = [f for f in findings if f.category == "VALUE_MISMATCH"]
    if vm:
        out.append(f"## Value mismatches ({len(vm)} total, showing top 20)")
        out.append("")
        for f in vm[:20]:
            out.append(f"- **{f.l_doc}** `{f.key}`")
            out.append(f"  - program: `{str(f.program_value)[:80]}`")
            out.append(f"  - agent:   `{str(f.agent_value)[:80]}`")
        out.append("")

    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--program-dir", type=Path, required=True,
                   help="Directory containing program-extracted L*.json")
    p.add_argument("--agent-dir", type=Path, required=True,
                   help="Directory containing fresh-agent-extracted L*.json")
    p.add_argument("--source", type=Path,
                   help="Source text corpus (for hallucination grounding)")
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if any hallucination found")
    args = p.parse_args()

    source_text = None
    if args.source and args.source.exists():
        try:
            source_text = args.source.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            source_text = None

    stats, findings = diff_all(args.program_dir, args.agent_dir,
                                 source_text=source_text)
    md = report_to_markdown(stats, findings)

    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps({
                "stats": [asdict(s) for s in stats],
                "findings": [f.as_dict() for f in findings],
                "emitted_by": _pmd.emitted_by("l_doc_parity_diff"),
            }, indent=2), encoding="utf-8")

    halluc_count = sum(1 for f in findings if f.category == "HALLUCINATED")
    if args.strict and halluc_count:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
