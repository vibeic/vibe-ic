#!/usr/bin/env python3
"""
phase1_coverage_report_gen.py — Phase 1 (doc-extraction) extraction-coverage REPORT.

BACKLOG-v13 Wave 4. Companion to LL-38 (extraction_coverage_check),
which is the GATE. This program is the REPORT artefact: it always
runs at end-of-Phase 1, walks the same pattern-resolution rules as
LL-38, and emits a per-doc breakdown of which verbatim literals
made it from `<project>/input/docs/<doc>` into
`<project>/generated_docs/L*.json` and which did not.

Why a separate program
======================
LL-38 only emits a single overall coverage number + a top-15 miss
list to stderr; that suffices for gating but is not human-reviewable
per-doc. The deep audit (`docs/design/EXTRACTION_COVERAGE_AUDIT_DEEP_v0119.34.md`)
showed that humans need the per-doc table + per-literal hit/miss
list to diagnose extraction skill misses (e.g. RSP_70[91] missing
from L8_TIMING but RSP_74[91] present → L8 generator regex bug).

This program produces that same kind of table as a regular Phase 1 (doc-extraction)
deliverable so every project gets it, not only when an audit script
is run by hand.

Outputs
-------
  <project>/reports/extraction_coverage_report.md
  <project>/reports/extraction_coverage_report.json

Always exits 0 unless `<project_dir>` is missing/invalid (exit 2).
This is a REPORT, not a gate; threshold-checking is LL-38's job.

CLI
---
  python3 phase1_coverage_report_gen.py <project_dir>
  python3 phase1_coverage_report_gen.py <project_dir> --json-only
  python3 phase1_coverage_report_gen.py <project_dir> --md-only
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import _path_layout as _pl

# BACKLOG-v13 Wave 7 — binary-doc extensions to input_doc/.
_BINARY_DOC_SUFFIXES = (".pdf", ".xlsx", ".xls", ".pptx", ".ppt",
                        ".doc", ".docx")


def _ensure_extracted_docs(project: Path) -> dict:
    """If `<project>/input_doc/*.txt` is empty AND
    `<project>/input/docs/` has any binary docs (PDF/xlsx/pptx/doc),
    invoke `doc_extract.py` to populate `input_doc/`.

    Returns a small status dict for logging:
      {"action": "noop"|"extracted"|"warn",
       "extracted_count": int, "warnings": [str]}

    Wave 7 — closes the v0.119.37 fresh-agent gap where 14 binary
    docs in input/docs/ were invisible to auto-discovery (only
    *.txt was scanned).
    """
    status = {"action": "noop", "extracted_count": 0, "warnings": []}
    out_dir = _pl.input_doc_dir(project)
    in_dir = project / "input" / "docs"

    # Already populated -> no-op.
    if out_dir.is_dir() and any(out_dir.glob("*.txt")):
        status["action"] = "noop"
        return status

    if not in_dir.is_dir():
        status["action"] = "noop"
        return status

    binary_docs = [p for p in in_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in _BINARY_DOC_SUFFIXES]
    if not binary_docs:
        status["action"] = "noop"
        return status

    # Locate doc_extract.py shipped alongside this program.
    helper = Path(__file__).resolve().parent / "doc_extract.py"
    if not helper.is_file():
        status["action"] = "warn"
        status["warnings"].append(
            f"doc_extract.py not found at {helper}; "
            "binary docs left unextracted")
        return status

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [sys.executable, str(helper),
             "--in-dir", str(in_dir),
             "--out-dir", str(out_dir)],
            check=False, capture_output=True, text=True, timeout=600,
        )
    except Exception as e:
        status["action"] = "warn"
        status["warnings"].append(
            f"doc_extract.py invocation failed: {e}; "
            "continuing with whatever .txt files exist")
        return status

    extracted = sorted(out_dir.glob("*.txt"))
    status["extracted_count"] = len(extracted)
    if extracted:
        status["action"] = "extracted"
    else:
        status["action"] = "warn"
        status["warnings"].append(
            "doc_extract.py produced no .txt outputs "
            f"(exit={proc.returncode}); pdftotext/libreoffice/openpyxl "
            "may be unavailable")
    return status


SCHEMA_VERSION = 2
# Wave 23 (v0.119.55) — extraction coverage is non-waivable. 100% is
# the HARD acceptance threshold for Phase 1 (doc-extraction). If a literal cannot be
# extracted by the auto-discovery patterns, the agent MUST add a
# project-level `extraction_patterns.json` to teach the extractor how
# to find it. There is NO "we'll skip this doc" option.
LL38_THRESHOLD = 1.0

# BACKLOG-v13 Wave 5 — expanded auto-discovery regex families. Each family
# carries a label so the auto-discovered pattern is human-reviewable.
# Cap per-regex hits per doc at _AUTODISCOVERY_PER_REGEX_CAP to avoid
# runaway harvest (e.g. all-caps regex on a vendor datasheet).
_AUTODISCOVERY_REGEX_FAMILIES = (
    # decimal_addr (with @-prefix) FIRST so 0xNN inside `@0xNN` is
    # consumed as a single token rather than split.
    ("decimal_addr",    re.compile(r"@(?:0x)?[0-9A-Fa-f]+")),
    ("hex_const",       re.compile(r"0x[0-9A-Fa-f]+")),
    ("bracket_kv",      re.compile(r"[A-Z][A-Z0-9_]*\[\d+\]")),
    # numeric_unit: number + unit. v0.119.40 — gap between number and
    # unit is `[ \t\r]*` (optional same-line spaces/tabs/CR), NOT `\s+`,
    # so it cannot span an LF / cell-broken PDF row. Cross-line literals
    # like `'3.5\nV'` cannot match the JSON haystack (json.dumps escapes
    # LF to `\\n`), so harvesting them produced 26 unmatchable patterns
    # in the v0.119.39 fresh-agent verify run.
    ("numeric_unit",    re.compile(
        r"\d+\.?\d*[ \t\r]*(?:us|ms|ns|MHz|Hz|kHz|V|mV|kΩ|Ω|pF|nF|μF|nm)")),
    ("section_ref",     re.compile(
        r"(?:Section|Table|Figure)\s+\d+(?:\.\d+)?")),
    ("upper_ident",     re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")),
    # Wave 31 (v0.119.63) — 7 new patterns surfaced by
    # SEMANTIC_AUDIT_v0119.57. All chip-AGNOSTIC.
    ("crc_polynomial",  re.compile(
        r"polynomial|多項式|X\^8(?:[^\n]{0,40}?X\^[0-9]+)+",
        re.IGNORECASE)),
    ("golden_crc_vector", re.compile(
        r"Table\s+\d+|0x[0-9A-Fa-f]{2}\s*,\s*0x[0-9A-Fa-f]{2}")),
    ("opcode_packet",   re.compile(
        r"0x[0-9A-Fa-f]{2}[ \t]*(?:GET|SET|cmd|response|CMD|RESP)",
        re.IGNORECASE)),
    # Wave 36 (v0.119.68) — chip-AGNOSTIC pin pattern; <chip-class>-specific
    # `ACC_ID` / `OUT1` / `OUT2` removed.  Per-project custom pin
    # regexes go in `<project>/extraction_patterns.json`.
    ("pin_table",       re.compile(
        r"\bPIN_[A-Z]\d+\b")),
    ("electrical_table", re.compile(
        r"\b(?:VDD|VSS|3\.3\s*V|Typ\.|Min\.|Max\.)\b")),
    ("state_machine_step", re.compile(
        r"Step\s+\d+|\bS_[A-Z][A-Z0-9_]*\b|\bstate\s*[:=]")),
    # Wave 38 (v0.119.70) — 6 new typed-depth patterns surfaced by
    # PHASE2A_FULL_AUDIT_v0119.67. All chip-AGNOSTIC.
    #   electrical_value: V/I/T value tied to a typical power-rail
    #   identifier (closes audit line 22 IDD/VTH/VOH gap).
    ("electrical_value", re.compile(
        r"(?:VDD|VDDA|VSS|VDDIO|IDD|IDDQ|VTH|VOH|VOL|VIH|VIL|VBG|VREF)"
        r"[^\n]{0,40}?\d+\.?\d*\s*(?:V|mV|mA|μA|uA)",
        re.IGNORECASE)),
    #   clock_freq: explicit frequency tokens (master / divided
    #   clock map gap, audit line 24+32).
    ("clock_freq", re.compile(
        r"\d+\.?\d*\s*(?:MHz|kHz|GHz|Hz)\b", re.IGNORECASE)),
    #   power_mode: ACTIVE/SLEEP/STANDBY/IDLE-style mode tokens
    #   (audit category bullet "Power modes").
    ("power_mode", re.compile(
        r"\b(?:ACTIVE|SLEEP|DEEP_SLEEP|STANDBY|IDLE|POWER_DOWN)"
        r"\s*MODE\b",
        re.IGNORECASE)),
    #   pin_alias: parallel slash-separated identifier list (e.g.
    #   "ACC_ID / id_bus / GPIO_0[0]") — datasheet vs RTL vs board
    #   alias group (audit category bullet "Signal naming aliases").
    ("pin_alias", re.compile(
        r"[A-Z][A-Z0-9_]{1,20}\s*/\s*[A-Za-z][A-Za-z0-9_\[\]]{1,30}"
        r"(?:\s*/\s*[A-Za-z][A-Za-z0-9_\[\]]{1,30})?")),
    #   test_mode_entry: engineer / factory / production mode entry
    #   sequence (audit line 29).
    ("test_mode_entry", re.compile(
        r"(?:engineer|factory|production|test)\s*mode"
        r"[^\n]{0,40}?(?:0x[0-9A-Fa-f]{2}|enter|sequence)",
        re.IGNORECASE)),
    #   state_in_table: explicit state-name token used in a debounce
    #   / filter / FSM step row (audit category bullet "State
    #   debounce / filter enums").
    ("state_in_table", re.compile(
        r"\b(?:idle|wait|stable|release|active|hold|capture|"
        r"settle|charging|discharging|locked|unlocked|"
        r"engineer|factory|production)\b",
        re.IGNORECASE)),
)
# Raised 100 → 10000 to align with extraction_coverage_denominator_audit
# (which has no cap). Cap-100 was dropping ~70% of distinct vendor tokens
# per Wave-on-fix v1.6.10, causing the denominator-shrink gating pattern
# even on legitimate runs.
_AUTODISCOVERY_PER_REGEX_CAP = 10000

# Stop-list of common false-positive all-caps tokens. Chip-AGNOSTIC.
_AUTODISCOVERY_STOPLIST = frozenset({
    "JSON", "TRUE", "FALSE", "NULL", "TODO", "FIXME", "NOTE",
    "TBD", "TBA", "RTL", "PASS", "FAIL", "WARN", "INFO",
    "MIN", "MAX", "AVG", "STD",
    # English filler
    "THE", "AND", "WITH", "FOR", "MUST", "SHALL", "WILL", "FROM",
    "INTO", "THIS", "THAT", "WHEN", "WHERE", "WHILE", "BETWEEN",
    "OVER", "UNDER", "EACH", "ANY", "ALL", "BOTH", "SUCH",
    "BASED", "USED", "USE", "USES", "NEW", "OLD", "ONLY",
    "ONE", "TWO", "THREE", "BIT", "BYTE", "WORD",
})


# ---------------------------------------------------------------------
# Pattern resolution — parallel to LL-38's _load_patterns().
# ---------------------------------------------------------------------
def _load_explicit_patterns(project: Path):
    """Returns (patterns_dict, source_path_or_None).

    patterns_dict[filename] = list[(literal, label)].
    """
    candidates = [
        _pl.phase1_extraction_patterns_file(project),
        project / "input" / "extraction_patterns.json",
    ]
    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            raw = json.loads(cand.read_text())
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        out = {}
        for filename, items in raw.items():
            if not isinstance(items, list):
                continue
            tuples = []
            for it in items:
                if isinstance(it, dict):
                    lit = it.get("literal") or it.get("pattern")
                    lbl = it.get("label") or it.get("desc") or lit or ""
                    if lit:
                        tuples.append((str(lit), str(lbl)))
                elif isinstance(it, str):
                    tuples.append((it, it))
            if tuples:
                out[filename] = tuples
        out = _reconcile_with_docs(project, out)
        return out, cand
    return {}, None



_RE_NUM_UNIT_SPACE = re.compile(r"(?<=[0-9])[ \u00a0\u3000]+(?=[A-Za-z\u00b0\u00b5\u03bc])")


def _is_auto_seeded(label: str) -> bool:
    """True for entries the seeder harvested, not a human's curation."""
    return str(label or "").strip().lower().startswith("auto-discovered")


def _lit_in(lit: str, hay_low: str) -> bool:
    """Credit a literal the extractor stored in NORMALISED form.

    Mirrors extraction_coverage_check._lit_present. The extractor writes
    `<value> <unit>` typed fields with the separating space removed, so a
    verbatim-only test reports the extractor's own successful extraction as
    a coverage gap. The collapse is anchored between a digit and a
    unit-leading letter, so it cannot join two unrelated tokens.
    """
    low = lit.lower()
    if low in hay_low:
        return True
    squeezed = _RE_NUM_UNIT_SPACE.sub("", lit).lower()
    return squeezed != low and squeezed in hay_low


def _reconcile_with_docs(project, patterns):
    """Drop AUTO-SEEDED literals absent from their own source document.

    The canonical pattern file is seeded once and then loaded verbatim
    forever, so literals a later documentation edit DELETED stay pinned in
    the denominator where nothing can ever credit them. Human-curated
    entries are never pruned -- a curated pattern is deliberately allowed
    not to occur in the document.
    """
    out = {}
    for filename, tuples in patterns.items():
        text = None
        for sub in (_pl.input_doc_dir(project), project / "input" / "docs"):
            for cand in (sub / filename,
                         sub / (pathlib.Path(filename).stem + ".md"),
                         sub / (pathlib.Path(filename).stem + ".txt")):
                if cand.is_file():
                    try:
                        text = cand.read_text(errors="replace")
                    except OSError:
                        text = None
                    break
            if text is not None:
                break
        if text is None:
            out[filename] = tuples
            continue
        kept = [(lit, lbl) for lit, lbl in tuples
                if not _is_auto_seeded(lbl) or lit in text]
        if kept:
            out[filename] = kept
    return out


def _autodiscover_patterns(project: Path, *, persist: bool = True):
    """Scan input_doc/*.txt + input/docs/*.txt for verbatim literal
    candidates. Returns {filename: [(literal, label)]}.

    BACKLOG-v13 Wave 5 — six regex families with per-regex hit cap to
    avoid runaway harvest, plus a chip-AGNOSTIC stop-list of English
    fillers. When ``persist`` is True and any patterns are found, the
    auto-discovered set is written to
    ``<project>/extraction_patterns.auto.json`` so users can review +
    promote the file to the canonical ``extraction_patterns.json``.
    """
    # Wave 7 — populate input_doc/ from binary inputs first if needed.
    status = _ensure_extracted_docs(project)
    if status.get("warnings"):
        for w in status["warnings"]:
            print(f"WARN — {w}")

    sources = []
    p1 = _pl.input_doc_dir(project)
    if p1.is_dir():
        sources.extend(sorted(p1.glob("*.txt")))
    p2 = project / "input" / "docs"
    if p2.is_dir():
        sources.extend(sorted(p2.glob("*.txt")))
    if not sources:
        return {}

    out = {}
    seen_keys = set()  # dedupe across both source dirs

    def _scan(text: str):
        seen = set()
        items = []
        for label, rx in _AUTODISCOVERY_REGEX_FAMILIES:
            hits = 0
            for m in rx.findall(text):
                tok = m.strip() if isinstance(m, str) else ""
                # v0.119.40 — belt-and-suspenders: drop any literal that
                # carries an embedded LF/CR/TAB. These bytes get escaped
                # by json.dumps when the L*.json haystack is serialised,
                # so the literal can never substring-match. Defensive
                # against any future regex slipping past the same-line
                # constraint in numeric_unit / section_ref.
                if (not tok
                        or "\n" in tok
                        or "\r" in tok
                        or "\t" in tok
                        or tok in seen
                        or tok.upper() in _AUTODISCOVERY_STOPLIST):
                    continue
                seen.add(tok)
                items.append(
                    (tok, f"auto-discovered ({label})"))
                hits += 1
                if hits >= _AUTODISCOVERY_PER_REGEX_CAP:
                    break
        return items

    for p in sources:
        if p.name in seen_keys:
            continue
        seen_keys.add(p.name)
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        items = _scan(text)
        # Wave 31 (v0.119.63) — full_file_scan_fix: ensure 100% of
        # input/docs/ files appear in the coverage tally even when zero
        # auto-discovered patterns fire. Use the doc filename itself as
        # the trivially-present probe (json.dumps preserves it via
        # `source_files`). Skip rig_spec which is reference material,
        # not extraction input.
        if not items and "rig_spec" not in p.name.lower():
            items = [(p.name, "auto-discovered (full_file_scan_fix)")]
        if items:
            out[p.name] = items

    if persist and out:
        try:
            persisted = {
                "_comment": (
                    "Auto-discovered extraction patterns (Wave 5). "
                    "Review and promote curated entries to "
                    "extraction_patterns.json."),
            }
            for fn, items in out.items():
                persisted[fn] = [
                    {"literal": lit, "label": lbl}
                    for lit, lbl in items
                ]
            auto_path = _pl.phase1_extraction_patterns_auto_file(project)
            auto_path.parent.mkdir(parents=True, exist_ok=True)
            auto_path.write_text(
                json.dumps(persisted, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            n = sum(len(v) for v in out.values())
            print(
                f"Auto-discovered {n} patterns; review "
                f"phase1/extraction_patterns.auto.json")
        except Exception:
            pass
    return out


def _resolve_patterns(project: Path):
    """Returns (patterns, source_label, source_path_or_None)."""
    explicit, src = _load_explicit_patterns(project)
    if explicit:
        return explicit, "explicit", src
    auto = _autodiscover_patterns(project)
    if auto:
        return auto, "auto-discovered", None
    return {}, "none", None


def _load_l_text(project: Path) -> str:
    base = _pl.generated_docs_dir(project)
    if not base.is_dir():
        return ""
    parts = []
    for p in sorted(base.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            parts.append(json.dumps(data, ensure_ascii=False))
        except Exception:
            try:
                parts.append(p.read_text(errors="replace"))
            except Exception:
                continue
    return "".join(parts)


# =====================================================================
# v0.119.41 (Wave 9, gap #5) — dump-field detection.
#
# A fresh agent can inflate Phase 1 coverage to 100% by dropping a
# verbatim copy of every input doc into a single catch-all field
# (e.g. `LX_DUMP`) of any L*.json. The literals all substring-match,
# so LL-38 reports PASS while semantic extraction is empty. Wave 9
# adds:
#   - per-field "dump quality" detection (size > 50 KB AND > 80%
#     verbatim copy of a single input doc by longest-common-substring
#     ratio).
#   - evidence_quality_score per data-point (0..1): high when the
#     hit lives in a structured (parsed-key) field, low when it lives
#     in a dump field.
#   - dump fields are EXCLUDED from the primary coverage tally; the
#     report flags them WARN.
# =====================================================================

DUMP_SIZE_THRESHOLD = 50_000     # bytes
DUMP_LCS_RATIO = 0.80            # fraction of field copied from a doc
QUALITY_DUMP = 0.20
QUALITY_PARSED = 1.00


def _walk_string_fields(data, path=""):
    """Yield (jsonpath, value) for every string leaf in `data`."""
    if isinstance(data, dict):
        for k, v in data.items():
            sub = f"{path}.{k}" if path else str(k)
            yield from _walk_string_fields(v, sub)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _walk_string_fields(v, f"{path}[{i}]")
    elif isinstance(data, str):
        yield path, data


def _lcs_length(a: str, b: str, *, sample_chars: int = 4096) -> int:
    """Approximate longest-common-substring length.

    Exact LCS is O(N*M) memory; for our threshold check (>80% of a
    >=50 KB field) we only need a quick lower bound. Sample a sliding
    window from `a` (the field) and check whether each chunk appears
    in `b` (the input doc); the running total is a tight lower bound
    on the true LCS length when `a` is a true substring of `b`.

    For the dump-detection threshold this is sufficient: a verbatim
    copy of a 50 KB doc into a field WILL match, while well-structured
    JSON keys will not.
    """
    if not a or not b:
        return 0
    if len(a) <= sample_chars and a in b:
        return len(a)
    # Sliding sample windows.
    chunk = max(64, min(sample_chars, len(a) // 8 or 64))
    total = 0
    pos = 0
    while pos < len(a):
        end = min(pos + chunk, len(a))
        snippet = a[pos:end]
        if snippet and snippet in b:
            total += len(snippet)
        pos = end
    return total


def _classify_l_fields(project: Path) -> tuple[dict, list[dict]]:
    """Walk generated_docs/L*.json and classify each string field as
    DUMP or PARSED.

    Returns (field_index, l_fields_list).
      field_index[lower_field_value] = list of {doc, path, classification}
      l_fields_list: ordered list of field metadata for the report.
    """
    field_index: dict[str, list[dict]] = {}
    l_fields: list[dict] = []
    docs_dir = _pl.generated_docs_dir(project)
    if not docs_dir.is_dir():
        return field_index, l_fields

    # Read input doc text once.
    input_texts: list[tuple[str, str]] = []
    for sub in ("phase1/input_doc", "input/docs", "extracted_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.txt")):
            try:
                input_texts.append((p.name, p.read_text(errors="replace")))
            except Exception:
                continue

    for lp in sorted(docs_dir.glob("*.json")):
        try:
            data = json.loads(lp.read_text())
        except Exception:
            continue
        for jpath, val in _walk_string_fields(data):
            size = len(val.encode("utf-8"))
            classification = "PARSED"
            quality = QUALITY_PARSED
            best_doc = None
            best_ratio = 0.0
            if size >= DUMP_SIZE_THRESHOLD:
                for in_name, in_text in input_texts:
                    if not in_text:
                        continue
                    lcs = _lcs_length(val, in_text)
                    ratio = lcs / size if size else 0.0
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_doc = in_name
                if best_ratio >= DUMP_LCS_RATIO:
                    classification = "DUMP"
                    quality = QUALITY_DUMP
            entry = {
                "doc": lp.name,
                "path": jpath,
                "size": size,
                "classification": classification,
                "quality": quality,
                "matched_input_doc": best_doc if classification == "DUMP" else None,
                "lcs_ratio": round(best_ratio, 3),
            }
            l_fields.append(entry)
            # Index for credit lookup. Include the entire field value in
            # lower-case so we can later find which classification a hit
            # belongs to.
            field_index.setdefault(val.lower(), []).append(entry)
    return field_index, l_fields


def _credit_with_quality(patterns,
                         field_index: dict,
                         l_text_low: str) -> tuple[list, dict]:
    """Build per-doc credit but split each literal into PARSED-only
    coverage and ALL-fields coverage. Emits an evidence-quality
    distribution.
    """
    quality_dist = {"high": 0, "low": 0, "missing": 0}
    primary_per_doc = []
    full_per_doc = []
    for filename in sorted(patterns):
        items = patterns[filename]
        primary_hit = []
        primary_miss = []
        full_hit = []
        full_miss = []
        for literal, label in items:
            lit_low = literal.lower()
            # Find which classifications contain the literal.
            classes = []
            for field_val_low, entries in field_index.items():
                if _lit_in(literal, field_val_low):
                    for e in entries:
                        classes.append(e["classification"])
            ent = {"literal": literal, "label": label}
            if any(c == "PARSED" for c in classes):
                quality_dist["high"] += 1
                primary_hit.append(ent)
                full_hit.append(ent)
            elif classes:  # only DUMP matches
                quality_dist["low"] += 1
                primary_miss.append(ent)  # excluded from primary tally
                full_hit.append(ent)
            else:
                # Fall back to the substring-on-full-haystack semantics
                # (covers cases where the value is split across small
                # nested fields that the field walker enumerated as
                # separate strings).
                if _lit_in(literal, l_text_low):
                    quality_dist["high"] += 1
                    primary_hit.append(ent)
                    full_hit.append(ent)
                else:
                    quality_dist["missing"] += 1
                    primary_miss.append(ent)
                    full_miss.append(ent)
        total = len(items)
        primary_per_doc.append({
            "doc": filename,
            "hit": len(primary_hit),
            "total": total,
            "pct": round((len(primary_hit) / total) * 100, 1) if total else 0.0,
            "hit_literals": primary_hit,
            "missing_literals": primary_miss,
        })
        full_per_doc.append({
            "doc": filename,
            "hit": len(full_hit),
            "total": total,
            "pct": round((len(full_hit) / total) * 100, 1) if total else 0.0,
            "hit_literals": full_hit,
            "missing_literals": full_miss,
        })
    return primary_per_doc, {
        "quality_distribution": quality_dist,
        "full_per_doc": full_per_doc,
    }


def _read_plugin_version() -> str:
    here = Path(__file__).resolve()
    cand = here.parent.parent / ".claude-plugin" / "plugin.json"
    if cand.is_file():
        try:
            return json.loads(cand.read_text()).get("version", "unknown")
        except Exception:
            return "unknown"
    return "unknown"


def _ll38_verdict(per_doc):
    if not per_doc:
        return "skipped"
    total = sum(d["total"] for d in per_doc)
    hit = sum(d["hit"] for d in per_doc)
    if total == 0:
        return "skipped"
    pct = hit / total
    return "PASS" if pct >= LL38_THRESHOLD else "FAIL"


# ---------------------------------------------------------------------
# Report assembly.
# ---------------------------------------------------------------------
def _build_per_doc(patterns, l_text):
    """Return list of per-doc dicts (sorted by filename)."""
    haystack_low = l_text.lower()
    out = []
    for filename in sorted(patterns):
        items = patterns[filename]
        hit_list = []
        miss_list = []
        for literal, label in items:
            if _lit_in(literal, haystack_low):
                hit_list.append({"literal": literal, "label": label})
            else:
                miss_list.append({"literal": literal, "label": label})
        total = len(items)
        hit = len(hit_list)
        pct = round((hit / total) * 100, 1) if total else 0.0
        out.append({
            "doc": filename,
            "hit": hit,
            "total": total,
            "pct": pct,
            "hit_literals": hit_list,
            "missing_literals": miss_list,
        })
    return out


def _emit_md(report: dict) -> str:
    overall = report["overall"]
    pct = overall["pct"]
    lines = []
    lines.append("# Phase 1 (doc-extraction) Extraction Coverage Report")
    lines.append("")
    lines.append(f"**Project**: {report['project_dir']}")
    lines.append(f"**Generated**: {report['generated_at']}")
    lines.append(f"**Plugin version**: {report['plugin_version']}")
    pat_src = report["pattern_source"]
    if pat_src == "explicit" and report.get("pattern_source_path"):
        pat_src = report["pattern_source_path"]
    lines.append(f"**Pattern source**: {pat_src}")
    lines.append("")
    lines.append(
        f"## Overall: {overall['hit']} / {overall['total']} = {pct}%"
    )
    lines.append("")

    # Summary table
    lines.append("| Source doc | Hit / Total | % | Status |")
    lines.append("|------------|-------------|---|--------|")
    for d in report["per_doc"]:
        status = "OK" if d["pct"] >= LL38_THRESHOLD * 100 else "GAP"
        lines.append(
            f"| `{d['doc']}` | {d['hit']} / {d['total']} | "
            f"{d['pct']}% | {status} |"
        )
    lines.append("")

    # Per-doc detail
    lines.append("## Per-doc detail")
    lines.append("")
    for d in report["per_doc"]:
        lines.append(
            f"### {d['doc']} — {d['hit']}/{d['total']} ({d['pct']}%)"
        )
        lines.append("")
        # Hit sample (up to 10)
        lines.append("**Hit literals** (sample, up to 10):")
        sample = d["hit_literals"][:10]
        if sample:
            for h in sample:
                lines.append(f"- `{h['literal']}` -> {h['label']}")
        else:
            lines.append("- (none)")
        lines.append("")
        # Missing literals (full when not 100%)
        if d["missing_literals"]:
            lines.append("**Missing literals** (full list when not 100%):")
            for m in d["missing_literals"]:
                lines.append(f"- `{m['literal']}` -> {m['label']}")
        else:
            lines.append("**Missing literals**: none (100% coverage).")
        lines.append("")

    # Wired-in gates
    lines.append("## Wired-in gates")
    lines.append(
        f"- LL-38 `extraction_coverage_check`: {report['ll38_verdict']}"
    )
    lines.append(f"- Threshold: {int(LL38_THRESHOLD * 100)}%")
    lines.append("")

    # v0.119.41 Wave 9 — evidence-quality + dump-field section.
    qd = report.get("evidence_quality_distribution") or {}
    if qd:
        lines.append("## Evidence quality distribution")
        lines.append(
            f"- high (parsed/structured): {qd.get('high', 0)}")
        lines.append(
            f"- low (dump-field only): {qd.get('low', 0)}")
        lines.append(
            f"- missing: {qd.get('missing', 0)}")
        lines.append("")
    dump_fields = report.get("dump_fields") or []
    if dump_fields:
        lines.append("## Dump fields detected (excluded from primary tally)")
        lines.append("")
        lines.append("| Doc | Field path | Size | LCS ratio | Matched input |")
        lines.append("|-----|------------|------|-----------|---------------|")
        for d in dump_fields:
            lines.append(
                f"| `{d['doc']}` | `{d['path']}` | {d['size']} B | "
                f"{d['lcs_ratio']:.2f} | "
                f"`{d.get('matched_input_doc') or '-'}` |"
            )
        lines.append("")
        lines.append(
            "> WARN: literals found ONLY in these fields are not "
            "credited in the primary coverage tally; promote them to "
            "structured L1-L23 fields (e.g. `L3.fields_tx[].byte_value`) "
            "to earn full credit.")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: phase1_coverage_report_gen.py <project_dir> "
              "[--json-only] [--md-only]")
        return 2
    json_only = "--json-only" in argv
    md_only = "--md-only" in argv
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: phase1_coverage_report_gen.py <project_dir> "
              "[--json-only] [--md-only]")
        return 2
    project = Path(pos[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2

    patterns, source_label, source_path = _resolve_patterns(project)
    l_text = _load_l_text(project)

    if not patterns or not l_text:
        # Nothing to report. Don't write files; print explanatory note.
        if not patterns and not l_text:
            reason = "no patterns and no extracted docs"
        elif not patterns:
            reason = "no patterns"
        else:
            reason = "no generated_docs/*.json"
        print(f"phase1_coverage_report_gen: {reason} — "
              f"report not generated (this is a no-op skip).")
        return 0

    # v0.119.41 Wave 9 — dump-aware credit. Build per-doc using the
    # quality-aware classifier first; fall back to the legacy
    # haystack-only classifier if the quality classifier yielded zero
    # docs (e.g. project shipped raw text rather than .json L docs).
    field_index, l_fields = _classify_l_fields(project)
    dump_fields = [f for f in l_fields if f["classification"] == "DUMP"]
    if field_index:
        per_doc, quality_extras = _credit_with_quality(
            patterns, field_index, l_text.lower())
        quality_distribution = quality_extras["quality_distribution"]
        full_per_doc = quality_extras["full_per_doc"]
    else:
        per_doc = _build_per_doc(patterns, l_text)
        quality_distribution = {"high": 0, "low": 0, "missing": 0}
        full_per_doc = per_doc
    total = sum(d["total"] for d in per_doc)
    hit = sum(d["hit"] for d in per_doc)
    pct = round((hit / total) * 100, 1) if total else 0.0
    verdict = _ll38_verdict(per_doc)
    if dump_fields:
        print(
            f"WARN — {len(dump_fields)} dump-classified field(s) in "
            "L*.json (>=50 KB AND >=80% verbatim copy of an input doc); "
            "excluded from the primary coverage tally.")
        for d in dump_fields[:5]:
            print(
                f"  WARN dump: {d['doc']} field={d['path']} "
                f"size={d['size']}B lcs_ratio={d['lcs_ratio']} "
                f"matched_input={d['matched_input_doc']}")

    pattern_source = (
        "phase1/extraction_patterns.json" if source_label == "explicit"
        else "auto-discovered"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "project_dir": str(project),
        "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "plugin_version": _read_plugin_version(),
        "pattern_source": pattern_source,
        "pattern_source_path": (
            str(source_path) if source_path else None
        ),
        "overall": {"hit": hit, "total": total, "pct": pct},
        "per_doc": per_doc,
        "ll38_verdict": verdict,
        # Wave-9 additions:
        "evidence_quality_distribution": quality_distribution,
        "dump_fields": dump_fields,
        "full_per_doc": full_per_doc,
    }

    md_path = _pl.report_path(project, "extraction_coverage_report.md")
    json_path = _pl.report_path(project, "extraction_coverage_report.json")
    md_path.parent.mkdir(parents=True, exist_ok=True)

    if not json_only:
        md_path.write_text(_emit_md(report), encoding="utf-8")
    if not md_only:
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        f"phase1_coverage_report_gen: {hit}/{total} = {pct}% "
        f"({len(per_doc)} doc(s); pattern source = {pattern_source}; "
        f"LL-38 verdict = {verdict})"
    )
    if not json_only:
        print(f"  wrote {md_path}")
    if not md_only:
        print(f"  wrote {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
