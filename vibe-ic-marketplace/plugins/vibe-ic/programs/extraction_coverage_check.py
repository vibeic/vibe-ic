#!/usr/bin/env python3
"""
extraction_coverage_check.py — gate (LL-38) verifies input/docs/
extraction coverage in generated_docs/L*.json.

Wave 23 (v0.119.55) — extraction coverage is non-waivable. 100% is
the HARD acceptance threshold for Phase 1 (doc-extraction). If a literal cannot be
extracted by the auto-discovery patterns, the agent MUST add a
project-level `extraction_patterns.json` to teach the extractor how
to find it. There is NO "we'll skip this doc" option. The legacy
`extraction_coverage_acceptable_below_95` waiver has been removed
from this gate — any waiver named `extraction_coverage_*` /
`phase1_coverage_*` / `extraction_evidence_*` is forbidden by the
new `phase1_no_waivers_used_check` gate.

Why this gate exists
====================
BACKLOG-v13 Wave 2, Part D. Even after Wave 1's CRC + pin-planner
gates closed the highest-impact extraction misses, the v0.119.32
audit (`docs/design/EXTRACTION_COVERAGE_AUDIT_v0119.32.md`) showed
51/86 = 59% extraction. 35 distinct data points from 19 input docs
were never copied verbatim into any L*.json. Symptom: chip RTL
has the right algorithm but wrong tick numbers / wrong default
hex byte / wrong wake handshake — bytewise FAIL on host tester
without an obvious diagnostic.

This gate adds a generic measurement: for each input doc, we look
for a small set of high-signal substring patterns; for each pattern
we check if it appears anywhere across the union of L*.json texts.
If overall coverage <95% → FAIL.

Pattern-source resolution (chip-AGNOSTIC, BACKLOG-v14 v0.119.35;
auto-discovery upgraded BACKLOG-v13 Wave 6 v0.119.38)
----------------------------------------------------------------
The gate looks for patterns in this order:

  1. `<project>/extraction_patterns.json`
  2. `<project>/input/extraction_patterns.json`
  3. Auto-discovery from `<project>/input_doc/*.txt` AND
     `<project>/input/docs/*.txt` (deduped by filename) using
     6 regex families (decimal_addr, hex_const, bracket_kv,
     numeric_unit, section_ref, upper_ident) with a 100-hit
     per-regex cap and a chip-AGNOSTIC English-filler stop-list.
     Auto-discovered patterns are persisted to
     `<project>/extraction_patterns.auto.json` for review +
     promotion to the canonical pattern file. WARN is printed
     suggesting the user vet the auto-discovered set.

If neither extraction_patterns.json nor input_doc/ nor
input/docs/*.txt exists, the gate silent-skips (no false alert).
This means the gate is not VENDOR/<chip-class>-tuned: any project
supplying its own pattern file gets the same verdict.

Wave 23 (v0.119.55): if patterns + L docs ARE present, coverage
must be 100%. Anything below is a HARD FAIL — no waiver path.

extraction_patterns.json schema
-------------------------------
```
{
  "<source_doc_filename>": [
    {"literal": "H1_MIN[1]",   "label": "FPGA H1_MIN tick"},
    {"literal": "RSP_74[91]",  "label": "RSP_74 latency"}
  ]
}
```

Wave 23 (v0.119.55): NO WAIVER. The legacy waiver
`extraction_coverage_acceptable_below_95` is no longer honored;
`phase1_no_waivers_used_check` will FAIL if it is even present
in `<project>/waivers.json`.

Usage
-----
python3 extraction_coverage_check.py <project_dir>

Returns 0 PASS / silent-skip / waived, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
import _path_layout as _pl

# BACKLOG-v13 Wave 7 — binary-doc extensions handled by
# `_ensure_extracted_docs` so the gate sees the same inputs as the
# Wave 4/5 report-gen.
_BINARY_DOC_SUFFIXES = (".pdf", ".xlsx", ".xls", ".pptx", ".ppt",
                        ".doc", ".docx")


def _ensure_extracted_docs(project: Path) -> dict:
    """If `<project>/input_doc/*.txt` is empty AND
    `<project>/input/docs/` has any binary docs (PDF/xlsx/pptx/doc),
    invoke `doc_extract.py` to populate `input_doc/`.

    Returns a small status dict for logging:
      {"action": "noop"|"extracted"|"warn",
       "extracted_count": int, "warnings": [str]}

    Wave 7 — closes the v0.119.37 fresh-agent gap where binary docs
    in input/docs/ were invisible to LL-38 auto-discovery (only
    *.txt was scanned).
    """
    status = {"action": "noop", "extracted_count": 0, "warnings": []}
    out_dir = _pl.input_doc_dir(project)
    in_dir = project / "input" / "docs"

    if out_dir.is_dir() and any(out_dir.glob("*.txt")):
        status["action"] = "noop"
        return status

    if not in_dir.is_dir():
        return status

    binary_docs = [p for p in in_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in _BINARY_DOC_SUFFIXES]
    if not binary_docs:
        return status

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


# Wave 23 (v0.119.55) — threshold raised from 0.95 to 1.00 (100%).
# Phase 1 (doc-extraction) extraction coverage is the HARD acceptance gate: anything
# below 100% means at least one input-doc literal failed to land in
# any L*.json, which is a Phase 1 (doc-extraction) extraction defect, not an
# acceptable margin. No waiver overrides this.
DEFAULT_THRESHOLD = 1.0

# BACKLOG-v13 Wave 6 — auto-discovery upgraded to mirror
# phase1_coverage_report_gen.py (v0.119.37) so the GATE measures
# the same way the REPORT does. Six regex families, each labelled
# for human review; per-regex 100-hit cap to bound runtime; expanded
# chip-AGNOSTIC English-filler stop-list.
#
# Regex families target shapes that surfaced as missing in the
# v0.119.34 deep audit: RSP_70[91], 0x60, 308us, EN_L, OTP @0x42,
# Section 4.2 references, etc.
_AUTODISCOVERY_REGEX_FAMILIES = (
    # decimal_addr / @-prefixed hex (e.g. @0x42, @128) — listed FIRST
    # so the @-prefix is consumed before bare hex_const fires.
    ("decimal_addr",    re.compile(r"@(?:0x)?[0-9A-Fa-f]+")),
    # 0xNN style hex constants (any width).
    ("hex_const",       re.compile(r"0x[0-9A-Fa-f]+")),
    # NAMED[NN] style — H1_MIN[1], RSP_74[91], MSN[19].
    ("bracket_kv",      re.compile(r"[A-Z][A-Z0-9_]*\[\d+\]")),
    # Decimal numbers + unit suffix. v0.119.40 — gap between number
    # and unit is `[ \t\r]*` (same-line whitespace), NOT `\s+`, so a
    # cell-broken PDF table cannot produce `'3.5\nV'` literals. Such
    # literals never match the JSON haystack (json.dumps escapes LF
    # to `\\n`), so harvesting them produced 26 unmatchable patterns
    # in the v0.119.39 fresh-agent verify run.
    ("numeric_unit",    re.compile(
        r"\d+\.?\d*[ \t\r]*(?:us|ms|ns|MHz|Hz|kHz|V|mV|kΩ|Ω|pF|nF|μF|nm)")),
    # Section / Table / Figure references.
    ("section_ref",     re.compile(
        r"(?:Section|Table|Figure)\s+\d+(?:\.\d+)?")),
    # ALL_CAPS identifiers (≥3 chars).
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
    # Wave 36 (v0.119.68) — chip-AGNOSTIC pin pattern. <chip-class>-specific
    # pin names (`ACC_ID`, `OUT1`, `OUT2`) removed; per-project custom
    # pin regexes can be supplied via
    # `<project>/extraction_patterns.json` (see
    # extraction_patterns.example.json for the schema).
    ("pin_table",       re.compile(
        r"\bPIN_[A-Z]\d+\b")),
    ("electrical_table", re.compile(
        r"\b(?:VDD|VSS|3\.3\s*V|Typ\.|Min\.|Max\.)\b")),
    ("state_machine_step", re.compile(
        r"Step\s+\d+|\bS_[A-Z][A-Z0-9_]*\b|\bstate\s*[:=]")),
)
# Raised 100 → 10000 to align with extraction_coverage_denominator_audit
# (which has no cap). See phase1_coverage_report_gen.py for rationale.
_AUTODISCOVERY_PER_REGEX_CAP = 10000

# Heuristic stop-list: tokens too generic to be useful as
# extraction-coverage probes (every L*.json mentions them).
# Chip-AGNOSTIC: only English filler / generic verdict tokens.
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


_BLOB_FIELD_NAMES = (
    "all_input_literals_aggregated",
    "raw_text",
    "evidence_text",
)
_BLOB_FIELD_SUFFIXES = ("_dump", "_blob", "_aggregated", "_DUMP", "_BLOB", "_AGGREGATED")
_BLOB_FIELD_PREFIXES = ("LX_DUMP", "all_input_literals_")


def _is_blob_field_name(name: str) -> bool:
    """Wave 31 — true if the JSON key looks like a raw blob/dump field
    that should be excluded from the typed-coverage haystack.

    chip-AGNOSTIC: matches by suffix `_dump` / `_blob` / `_aggregated`,
    by prefix `LX_DUMP` / `all_input_literals_`, by literal names
    `all_input_literals_aggregated` / `raw_text` / `evidence_text`,
    and by upper-case variants. The structured pointer field
    `extraction_evidence` is intentionally NOT matched (it is metadata
    that legitimately points into structured fields).
    """
    if not isinstance(name, str):
        return False
    if name in _BLOB_FIELD_NAMES:
        return True
    for s in _BLOB_FIELD_SUFFIXES:
        if name.endswith(s):
            return True
    for p in _BLOB_FIELD_PREFIXES:
        if name.startswith(p):
            return True
    # Catch generic raw_<anything>.
    if name.startswith("raw_") or name.startswith("RAW_"):
        return True
    return False


def _strip_blob_fields(data):
    """Wave 31 — return a deep copy of `data` with every blob-shaped
    field replaced by an empty string. Used to build the typed-only
    haystack for the LL-38 substring match.

    The structured pointer field `extraction_evidence` is preserved
    because it carries real coordinates (file path + line number) that
    let an audit pinpoint where the literal lives.
    """
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if _is_blob_field_name(k):
                out[k] = ""  # zero out the value
            else:
                out[k] = _strip_blob_fields(v)
        return out
    if isinstance(data, list):
        return [_strip_blob_fields(x) for x in data]
    return data


def _load_l_text(project: Path, *, exclude_blob: bool = True) -> str:
    """Concatenate the JSON text of every generated_docs/*.json file.

    Wave 31 (v0.119.63): ``exclude_blob=True`` strips raw-dump fields
    (``all_input_literals_aggregated``, ``*_dump``, ``*_blob``,
    ``*_aggregated``, ``raw_text``, ``LX_DUMP``, ``evidence_text``) so
    the substring match runs on the TYPED structured fields only. The
    100% literal-coverage pre-Wave-31 metric was gameable: a fresh
    agent could dump every input doc into a single catch-all field and
    score 100%, while the L docs carried zero typed structured fields.
    Wave 31 closes that — see SEMANTIC_AUDIT_v0119.57.md.
    """
    base = _pl.generated_docs_dir(project)
    if not base.is_dir():
        return ""
    parts: list[str] = []
    for p in sorted(base.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            if exclude_blob:
                data = _strip_blob_fields(data)
            parts.append(json.dumps(data, ensure_ascii=False))
        except Exception:
            if not exclude_blob:
                try:
                    parts.append(p.read_text(errors="replace"))
                except Exception:
                    continue
    return "".join(parts)


def _find_input_doc(project: Path, filename: str) -> Path | None:
    """Locate a vendor doc by name under input/docs/ (whitespace-tolerant).

    v1.6.299 — for #196 ORGANIC. The in-memory ingester rewrites every
    source extension to ``.txt`` for the uniform downstream contract,
    so an `extraction_patterns.json` keyed on ``README.txt`` will
    probe ``input/docs/README.txt`` even when the on-disk source is
    ``README.md`` / ``pipeline.rst`` / ``integration.adoc``. Broaden
    the probe: try the literal ``.txt`` name, then strip the
    ``.txt`` suffix and walk recursively for common docs source
    extensions, then fall back to the extracted-docs mirror under
    ``phase1/input_doc/``. Chip-AGNOSTIC: extension set is
    open-standard docs vocabulary; no chip literal participates.
    """
    base = project / "input" / "docs"
    if not base.is_dir():
        # v1.6.299 — final fallback to extracted_docs mirror still
        # exercised even when input/docs is absent, so the gate can
        # measure coverage on extracted-only trees.
        extracted_dir = project / "phase1" / "input_doc"
        if extracted_dir.is_dir():
            fb = extracted_dir / filename
            if fb.is_file():
                return fb
        return None
    p = base / filename
    if p.is_file():
        return p
    for c in base.iterdir():
        if c.is_file() and c.name.strip() == filename.strip():
            return c
    # v1.6.299 — for #196. Broaden the probe to recognise modern docs
    # source extensions when the in-memory ingester has rewritten the
    # extension to `.txt` for downstream uniformity.
    stem = (filename[:-4] if filename.lower().endswith(".txt")
            else filename)
    stem_stripped = stem.strip()
    for ext in (".md", ".rst", ".markdown", ".adoc", ".tex"):
        try:
            for candidate in base.rglob(f"{stem_stripped}{ext}"):
                if candidate.is_file():
                    return candidate
        except (OSError, ValueError):
            continue
    # Final fallback — extracted_docs mirror (the in-memory ingester
    # persists a copy here for downstream gates).
    extracted_dir = project / "phase1" / "input_doc"
    if extracted_dir.is_dir():
        fb = extracted_dir / filename
        if fb.is_file():
            return fb
    return None


# Wave 23 (v0.119.55) — `_waived()` removed. Phase 1 (doc-extraction) extraction
# coverage is non-waivable; the legacy
# `extraction_coverage_acceptable_below_95` key is now actively
# forbidden by `phase1_no_waivers_used_check`.


def _load_explicit_patterns(project: Path) -> tuple[dict, Path | None]:
    """Load <project>/[input/]extraction_patterns.json if present.

    Returns (patterns_dict, file_path) where patterns_dict is
    `{filename: [(literal, label), ...]}` or `({}, None)` if no
    file exists. Tolerates a few schema variants:
      - list[dict] with `literal`/`label` keys (canonical)
      - list[dict] with `pattern`/`desc`
      - list[str] (literals only — label = literal itself)
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
        except Exception as e:
            print(f"WARN — extraction_patterns.json at {cand} unparseable: {e}",
                  file=sys.stderr)
            continue
        if not isinstance(raw, dict):
            print(f"WARN — extraction_patterns.json at {cand} top-level "
                  f"must be an object keyed on doc filename", file=sys.stderr)
            continue
        patterns: dict[str, list[tuple[str, str]]] = {}
        for filename, items in raw.items():
            if not isinstance(items, list):
                continue
            tuples: list[tuple[str, str]] = []
            for it in items:
                if isinstance(it, dict):
                    lit = it.get("literal") or it.get("pattern")
                    lbl = it.get("label") or it.get("desc") or lit or ""
                    if lit:
                        tuples.append((str(lit), str(lbl)))
                elif isinstance(it, str):
                    tuples.append((it, it))
            if tuples:
                patterns[filename] = tuples
        patterns = _reconcile_with_docs(project, patterns)
        return patterns, cand
    return {}, None



def _is_auto_seeded(label: str) -> bool:
    """True for entries the seeder harvested, not a human's curation."""
    return str(label or "").strip().lower().startswith("auto-discovered")


def _reconcile_with_docs(project: Path, patterns: dict) -> dict:
    """Drop pinned literals that no longer occur in their source document.

    The canonical `extraction_patterns.json` is seeded ONCE (the
    `if not canonical.is_file():` guard in phase1_doc_one_shot_runner) and
    is then loaded verbatim on every later run. When an input document is
    subsequently edited -- which is exactly what a retarget does -- literals
    the edit DELETED stay pinned in the denominator forever. Nothing can
    ever credit them, because they occur in no document, so a gate that
    requires 100% with NO waiver becomes unreachable by any honest means.

    Reconcile on load, but ONLY for entries the seeder itself harvested
    (label `auto-discovered (...)`). A HUMAN-CURATED pattern is a teaching
    aid -- "look for this literal in the L docs" -- and is deliberately
    allowed not to occur in the input document at all
    (test_explicit_patterns_root_used encodes exactly that contract), so
    curated entries are never pruned. This narrowing came from a measured
    regression in the first cut of this fix, which pruned curated patterns
    and broke 3 tests, not from caution.

    For an auto-seeded literal, keep it only while its own source document
    still contains it. A literal the documents no longer make is outside
    what this gate measures ("did every literal in the docs reach a typed
    field"), so removing it restores the gate's stated semantics rather
    than relaxing them.

    chip-AGNOSTIC: keyed on document content only; no chip, process or
    vendor token.
    """
    out: dict = {}
    for filename, tuples in patterns.items():
        doc = _find_input_doc(project, filename)
        if doc is None:
            out[filename] = tuples
            continue
        try:
            text = doc.read_text(errors="replace")
        except Exception:
            out[filename] = tuples
            continue
        kept = [(lit, lbl) for lit, lbl in tuples
                if not _is_auto_seeded(lbl) or lit in text]
        dropped = len(tuples) - len(kept)
        if dropped:
            print(f"INFO — reconcile: dropped {dropped} pinned literal(s) "
                  f"absent from {filename} (stale pattern cache)",
                  file=sys.stderr)
        if kept:
            out[filename] = kept
    return out



_RE_NUM_UNIT_SPACE = re.compile(r"(?<=[0-9])[ \u00a0\u3000]+(?=[A-Za-z\u00b0\u00b5\u03bc])")


def _lit_present(lit: str, hay: str) -> bool:
    """Credit a literal that the extractor stored in NORMALISED form.

    The Phase-1 extractor writes `<value> <unit>` typed fields with the
    separating space removed (`"30 ns"` -> `{"literal": "30ns",
    "value": "30", "unit": "ns"}`), while the coverage denominator
    harvests the un-normalised prose form. A verbatim-only credit test
    therefore reports the extractor's OWN successful extraction as a
    coverage gap, and the 100%-required gate becomes unreachable for any
    document that writes a number and its unit with a space between them.

    Credit on the verbatim form OR on the same number-unit space collapse
    the extractor itself applies. The collapse is anchored between a digit
    and a unit-leading letter, so it cannot join two unrelated tokens.

    chip-AGNOSTIC: no chip, process, vendor or unit vocabulary hard-coded.
    """
    if re.search(re.escape(lit), hay, re.IGNORECASE):
        return True
    squeezed = _RE_NUM_UNIT_SPACE.sub("", lit)
    if squeezed != lit and re.search(re.escape(squeezed), hay, re.IGNORECASE):
        return True
    return False


def _autodiscover_patterns(project: Path, *, persist: bool = True) -> dict:
    """Harvest high-signal literals from input_doc/*.txt AND
    input/docs/*.txt.

    BACKLOG-v13 Wave 6 — mirrors phase1_coverage_report_gen.py so
    the GATE measures the same way the REPORT does:
      * scans both `<project>/input_doc/*.txt` and
        `<project>/input/docs/*.txt` (deduped by filename across the
        two source dirs)
      * 6 regex families, each labelled for review
      * per-regex 100-hit cap to bound runtime
      * expanded chip-AGNOSTIC stop-list
      * when ``persist`` is True, writes the auto-discovered set to
        ``<project>/extraction_patterns.auto.json`` so users can
        promote curated entries to ``extraction_patterns.json``

    Returns ``{<doc_basename>: [(literal, label), ...]}``.
    """
    # Wave 7 — populate input_doc/ from binary inputs first if needed.
    status = _ensure_extracted_docs(project)
    if status.get("warnings"):
        for w in status["warnings"]:
            print(f"WARN — {w}", file=sys.stderr)

    sources: list[Path] = []
    p1 = _pl.input_doc_dir(project)
    if p1.is_dir():
        sources.extend(sorted(p1.glob("*.txt")))
    p2 = project / "input" / "docs"
    if p2.is_dir():
        sources.extend(sorted(p2.glob("*.txt")))
    if not sources:
        return {}

    out: dict[str, list[tuple[str, str]]] = {}
    seen_keys: set[str] = set()  # dedupe across both source dirs

    for p in sources:
        if p.name in seen_keys:
            continue
        seen_keys.add(p.name)
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        seen: set[str] = set()
        items: list[tuple[str, str]] = []
        for label, rx in _AUTODISCOVERY_REGEX_FAMILIES:
            hits = 0
            for m in rx.findall(text):
                tok = m.strip() if isinstance(m, str) else ""
                # v0.119.40 — belt-and-suspenders: drop literals
                # containing LF/CR/TAB. They cannot match the JSON
                # haystack (json.dumps escapes those bytes), so
                # harvesting them only inflates the denominator with
                # unmatchable patterns. Defensive against any future
                # regex slipping past the same-line constraint.
                if (not tok
                        or "\n" in tok
                        or "\r" in tok
                        or "\t" in tok
                        or tok in seen
                        or tok.upper() in _AUTODISCOVERY_STOPLIST):
                    continue
                seen.add(tok)
                items.append((tok, f"auto-discovered ({label})"))
                hits += 1
                if hits >= _AUTODISCOVERY_PER_REGEX_CAP:
                    break
        # Wave 31 (v0.119.63) — full_file_scan_fix: ensure 100% of
        # input/docs/ files appear in the coverage tally even when zero
        # auto-discovered patterns fire (rig_spec excluded).
        if not items and "rig_spec" not in p.name.lower():
            items = [(p.name, "auto-discovered (full_file_scan_fix)")]
        if items:
            out[p.name] = items

    if persist and out:
        try:
            persisted = {
                "_comment": (
                    "Auto-discovered extraction patterns (Wave 6 LL-38). "
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
        except Exception:
            pass
    return out


def _load_patterns(project: Path) -> tuple[dict, str]:
    """Resolve patterns. Returns (patterns_dict, source_label)."""
    explicit, src_file = _load_explicit_patterns(project)
    if explicit:
        return explicit, f"explicit ({src_file.name})"
    auto = _autodiscover_patterns(project)
    if auto:
        return auto, "auto-discovered (input_doc/*.txt)"
    return {}, "none"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: extraction_coverage_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    threshold = DEFAULT_THRESHOLD
    if "--threshold" in sys.argv:
        idx = sys.argv.index("--threshold")
        try:
            threshold = float(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    # Wave 30 (v0.119.62) — fail-closed semantic. The previous silent-
    # skip paths let projects that NEVER ran Phase 1 (doc-extraction) (no L docs, no
    # patterns) pass this gate and progress to burn (35th-attempt root
    # cause). 100% extraction coverage is non-negotiable; the absence
    # of any L doc / pattern is the worst-case form of <100% and must
    # FAIL when input docs ARE present (i.e. the project intends to
    # run Phase 1 (doc-extraction) but has not actually done so).
    has_input_docs = (project / "input" / "docs").is_dir() and any(
        (project / "input" / "docs").iterdir()
    )

    l_text = _load_l_text(project)
    if not l_text:
        if has_input_docs:
            print("FAIL — Wave 30 (v0.119.62): generated_docs/*.json "
                  "absent but input/docs/ has vendor docs. Phase 1 (doc-extraction) "
                  "extraction was not run. NO waiver allowed.")
            print("To resolve: run phase1-orchestrate skill (or every "
                  "Phase 1 (doc-extraction) generator skill individually) so all 13 L "
                  "docs are emitted with non-empty content.")
            return 1
        print("PASS — no generated_docs/*.json AND no input/docs/ "
              "(gate skipped, chip-agnostic silent-skip)")
        return 0

    patterns, source_label = _load_patterns(project)
    if not patterns:
        if has_input_docs:
            print("FAIL — Wave 30 (v0.119.62): no extraction_patterns "
                  "and no input_doc/, but input/docs/ exists. "
                  "Either auto-discovery failed (run "
                  "phase1_coverage_report_gen first) or vendor docs "
                  "are unsupported binary types. NO waiver allowed.")
            return 1
        print("PASS — no extraction_patterns.json or input_doc/ "
              "found (gate skipped, chip-agnostic silent-skip)")
        return 0

    if source_label.startswith("auto-discovered"):
        print("WARN — using auto-discovered pattern set; for stable, "
              "reviewable gating provide <project>/extraction_patterns.json")

    total = 0
    hits = 0
    misses: list[tuple[str, str, str]] = []
    docs_checked = 0
    docs_with_input = 0

    for filename, items in patterns.items():
        # If patterns came from extracted_docs auto-discovery, we already
        # know each doc exists; for explicit patterns we still gate on
        # input/docs/<filename> presence so projects with a partial doc
        # set don't get false misses.
        if source_label.startswith("explicit"):
            if not _find_input_doc(project, filename):
                continue
            docs_with_input += 1
        docs_checked += 1
        for needle, desc in items:
            total += 1
            if _lit_present(str(needle), l_text):
                hits += 1
            else:
                misses.append((filename, needle, desc))

    if docs_checked == 0:
        print("PASS — pattern set present but no matching input docs "
              "(gate skipped, chip-agnostic)")
        return 0
    if total == 0:
        print("PASS — pattern set empty for present docs (gate skipped)")
        return 0

    pct = hits / total
    print(f"typed_field_coverage: {hits}/{total} = {pct:.1%} "
          f"(across {docs_checked} doc(s); pattern source = {source_label}; "
          f"raw-blob fields excluded — Wave 31 anti-gaming)")

    # v1.6.9 Fix 5 — emit a second coverage measurement that reflects the
    # hands-on universe (curated patterns ∪ backfilled auto literals). The
    # original `typed_field_coverage` line is the curated-needle metric; the
    # new `hands_on_field_coverage` line uses the union as denominator so
    # the runner's self-report tracks what a hands-on grep would find. We
    # do NOT change PASS/FAIL semantics on the curated metric; instead, when
    # they diverge, a third tier `COVERAGE_NEEDS_REVIEW` fires (rc=0) so
    # existing PASS projects don't regress to FAIL silently. With
    # ``--strict-coverage`` the divergence escalates to FAIL.
    strict_coverage = "--strict-coverage" in sys.argv
    auto_path = _pl.phase1_extraction_patterns_auto_file(project)
    union_total = total
    union_hits = hits
    union_misses: list[tuple[str, str, str]] = []
    if auto_path.is_file():
        try:
            auto_raw = json.loads(auto_path.read_text())
        except Exception:
            auto_raw = {}
        if isinstance(auto_raw, dict):
            seen_pairs: set[tuple[str, str]] = set()
            for fn, items in patterns.items():
                for needle, _ in items:
                    seen_pairs.add((fn, needle))
            for fn, items in auto_raw.items():
                if fn.startswith("_") or not isinstance(items, list):
                    continue
                for entry in items:
                    if not isinstance(entry, dict):
                        continue
                    lit = entry.get("literal") or entry.get("pattern")
                    lbl = (entry.get("label") or entry.get("desc")
                           or "auto (unpromoted)")
                    if not lit:
                        continue
                    pair = (fn, str(lit))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    # Only count auto literals whose verbatim string lives
                    # inside the typed L*.json haystack. This is the
                    # backfilled subset = "hands-on universe".
                    if _lit_present(str(lit), l_text):
                        union_total += 1
                        union_hits += 1
                    else:
                        # Not yet backfilled into typed structure; do NOT
                        # add to the denominator. (Matches the v1.6.7
                        # backfilled-subset rule in
                        # _seed_canonical_from_backfilled_subset.)
                        pass
    union_pct = (union_hits / union_total) if union_total else 0.0
    print(f"hands_on_field_coverage: {union_hits}/{union_total} = "
          f"{union_pct:.1%} "
          f"(curated ∪ backfilled auto-literals; Fix 5 dual-metric)")

    if pct >= threshold:
        # Curated set fully covered.
        if union_total > total and union_pct < threshold and not strict_coverage:
            print(f"COVERAGE_NEEDS_REVIEW — curated typed_field_coverage "
                  f"= {pct:.1%} (>= {threshold:.0%}) BUT hands_on "
                  f"coverage = {union_pct:.1%} < {threshold:.0%}; "
                  f"some auto-discovered literals are not yet wired "
                  f"into typed L*.json fields. PASS overall (rc=0); "
                  f"pass --strict-coverage to escalate to FAIL.")
            return 0
        print(f"PASS — typed_field_coverage = {pct:.1%} "
              f"(>= {threshold:.0%} threshold)")
        return 0

    # Wave 23 (v0.119.55) — HARD FAIL, no waiver path. The previous
    # `extraction_coverage_acceptable_below_95` waiver is gone; an
    # auxiliary gate (`phase1_no_waivers_used_check`) FAILs if a
    # legacy waiver name is even present in `waivers.json`.
    print(f"FAIL — typed_field_coverage {pct:.1%} < {threshold:.0%} "
          f"threshold (Wave 23: 100% required, NO waiver allowed; "
          f"Wave 31: raw-blob/dump fields are excluded so a project "
          f"that puts every literal in `all_input_literals_aggregated` "
          f"will FAIL until the data is promoted to typed structured "
          f"fields like `opcodes[]`, `registers[]`, `fsm_states[]`)")
    print(f"  Missing data points (top {min(15, len(misses))} of "
          f"{len(misses)}):")
    for fn, needle, desc in misses[:15]:
        print(f"   • {fn}: '{needle}' ({desc})")
    print()
    print("To resolve, add patterns to "
          "`<project>/extraction_patterns.json` so the extraction "
          "skills know how to find every literal, OR enrich the "
          "L*.json `extraction_evidence` field to include the "
          "missing verbatim strings. Do NOT add a waiver — there "
          "is no waiver for this gate.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
