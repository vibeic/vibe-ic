#!/usr/bin/env python3
"""phase1_doc_content_implementation_completeness_check.py — Wave 47

Generic Phase 1 (doc-extraction) coverage gate: every section heading / numbered list
entry in ``input/docs/`` (or ``input_doc/``) should be cited by
at least one L1-L23 doc field. Catches the recurring "agent skipped
half the spec" pattern observed across multiple fresh-agent runs.

User directive (Wave 47):
    "EVERY ITEM IN DESIGN DOCUMENTS SHOULD BE IMPLEMENTED!!!! EVERY!!!"

Algorithm (chip-AGNOSTIC):
  1. Parse ``input_doc/*.txt`` (and ``input/docs/*.txt``) for
     section markers — lines matching one of:
       ^\\d+\\.        e.g. ``1. Overview``
       ^\\d+\\.\\d+    e.g. ``2.3 Pinout``
       ^§              e.g. ``§ 4 Power``
       ^第\\d+         e.g. ``第 3 章 介面``
       ^[A-Z][A-Za-z0-9 ,/\\-]{5,40}:?$  (capitalized standalone heading)
  2. Reject section IDs that are obvious noise:
       - Empty / single-char
       - Common boilerplate (``Page``, ``TABLE``, ``Figure``, etc.)
  3. For each accepted section, search every L*.json under
     ``generated_docs/`` for any string field that cites either:
       - the section number / id (``1.2``, ``§4``, ``2.3``, ...)
       - the section heading text (>=4 chars)
       - the source file:line of the heading
  4. Compute coverage = covered_sections / total_sections.
  5. FAIL when coverage < 80% (more than 20% sections un-cited).
  6. WARN when coverage in [80%, 90%].
  7. PASS when coverage >= 90%.
  8. Honors per-section waivers
     ``phase1_section_intentionally_unimplemented_<section_id>``
     (>=40 chars each). The section_id is the slugified (lowercase
     alnum + underscore) form of the heading.

Usage:
    python3 phase1_doc_content_implementation_completeness_check.py \\
        <project_dir>

Exit codes:
    0 = PASS / SKIP
    1 = FAIL (coverage < 80% AND not waived)
    2 = IO error
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import _path_layout as _pl


WAIVER_PREFIX = "phase1_section_intentionally_unimplemented_"
WAIVER_MIN = 40

FAIL_THRESHOLD = 0.80   # coverage < 80% → FAIL
WARN_THRESHOLD = 0.90   # 80% <= coverage < 90% → WARN


_DOC_DIRS = (
    "input/docs",
    "phase1/input_doc",
)


# Section heading detectors — a line matches a heading iff at least
# one pattern fires AND the line is short (<80 chars typical heading).
_HEADING_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("dotted_numeric",
     re.compile(r"^\s*(\d+(?:\.\d+){0,3})\.?\s+(\S.{2,80})$")),
    ("section_marker",
     re.compile(r"^\s*§\s*(\d+(?:\.\d+)?)\s*[:\.]?\s*(\S.{2,80})$")),
    ("chinese_chapter",
     re.compile(r"^\s*第\s*(\d+)\s*[章節]\s+(\S.{2,80})$")),
    # Title-case heading: at least 2 words, each starting with uppercase
    # letter (e.g. "Pinout Description", "Electrical Specs") on its own
    # line. This is intentionally narrow to avoid false positives on
    # short labels like "DC params" or "VDD typ".
    ("capitalized_heading",
     re.compile(
         r"^\s*((?:[A-Z][A-Za-z0-9_\-]{2,}\s+){1,5}"
         r"[A-Z][A-Za-z0-9_\-]{2,}):?\s*$"
     )),
)


# Boilerplate / noise rejected even when matching a heading pattern.
_REJECT_TOKENS: Tuple[str, ...] = (
    "page", "figure", "fig.", "table of contents",
    "datasheet", "rev.", "version", "draft", "confidential",
    "copyright", "all rights reserved", "preliminary",
    "AustriaMicroSystems", "trademark", "internal use",
)


def _is_noise(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 3 or len(t) > 80:
        return True
    for tok in _REJECT_TOKENS:
        if tok.lower() in t:
            return True
    # Reject if line is purely punctuation / digits / dashes
    if not any(c.isalpha() for c in t):
        return True
    return False


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:60]


def _scan_sections(project: Path) -> List[dict]:
    """Returns list of {file, line, sec_id, heading, slug}."""
    out: List[dict] = []
    seen_files: Set[Path] = set()
    seen_slugs: Set[str] = set()
    for sub in _DOC_DIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.suffix.lower() not in (".txt", ".md"):
                continue
            if f in seen_files:
                continue
            seen_files.add(f)
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = str(f.relative_to(project))
            for i, raw in enumerate(text.splitlines(), start=1):
                line = raw.rstrip()
                if not line.strip():
                    continue
                for kind, pat in _HEADING_PATTERNS:
                    m = pat.match(line)
                    if not m:
                        continue
                    if kind == "capitalized_heading":
                        heading = m.group(1).strip()
                        sec_id = ""
                    else:
                        sec_id = m.group(1).strip()
                        heading = m.group(2).strip() if m.lastindex >= 2 else ""
                    if _is_noise(heading or sec_id):
                        break
                    slug = _slugify(heading or sec_id)
                    if not slug or slug in seen_slugs:
                        break
                    seen_slugs.add(slug)
                    out.append({
                        "file": rel,
                        "line": i,
                        "sec_id": sec_id,
                        "heading": heading,
                        "slug": slug,
                    })
                    break
    return out


def _load_l_doc_text(project: Path) -> str:
    """Concatenate all generated L*.json content as one searchable string."""
    chunks: List[str] = []
    gdir = _pl.generated_docs_dir(project)
    if not gdir.is_dir():
        return ""
    for f in sorted(gdir.glob("L*.json")):
        try:
            chunks.append(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
    return "\n".join(chunks)


def _owned_clause_coverage(project: Path) -> Tuple[int, List[str]]:
    """Check source obligations at the two existing integration/timing owners.

    A heading or unrelated L-doc token cannot stand in for its mandatory
    body clauses. This reads source lines independently of the emitter and
    requires the same source in the owning field's evidence.
    """
    from _prose_polarity import is_denied
    owners = {}
    for layer, keys in (('L9_INTEGRATION_SPEC', ('integration', 'architecture')),
                        ('L19_CONSTRAINTS_PDK', ('constraints', 'io_delay'))):
        try:
            node = json.loads((_pl.generated_docs_dir(project) / f'{layer}.json').read_text())
            for key in keys:
                node = node[key]
            owners[layer] = node if isinstance(node, list) else [node]
        except (OSError, ValueError, KeyError, TypeError):
            owners[layer] = []
    count, missing, seen = 0, [], set()
    for sub in _DOC_DIRS:
        root = project / sub
        if not root.is_dir():
            continue
        for source in sorted(root.iterdir()):
            if not source.is_file() or source.suffix.lower() not in ('.md', '.txt'):
                continue
            text = source.read_text(encoding='utf-8', errors='replace')
            layer = re.search(r'(?mi)^\s*layer\s*:\s*(L[89])\s*$', text)
            layer = layer.group(1) if layer else (
                re.match(r'(L[89])(?:_|\b)', source.name).group(1)
                if re.match(r'(L[89])(?:_|\b)', source.name) else '')
            if not layer or (layer, text) in seen:
                continue
            seen.add((layer, text))
            rel = source.relative_to(project).as_posix()
            parents = []
            for line_no, line in enumerate(text.splitlines(), 1):
                heading = re.match(r'^(#{1,6})\s+(.+)$', line)
                if heading:
                    depth, title = len(heading.group(1)), heading.group(2)
                    parents = [p for p in parents if p[0] < depth]
                    owner = parents[-1][1] if parents else ''
                    if layer == 'L8' and re.search(
                            r'sub[\s_-]?module|integration|hierarchy|階層|整合', title, re.I):
                        owner = 'L9_INTEGRATION_SPEC'
                    elif layer == 'L9' and re.search(
                            r'I/O\s+delay|input.*delay|output.*delay|I/O.*延遲', title, re.I):
                        owner = 'L19_CONSTRAINTS_PDK'
                    if is_denied(title):
                        owner = ''
                    parents.append((depth, owner, line.strip()))
                    continue
                owner = parents[-1][1] if parents else ''
                if not owner:
                    continue
                mandatory = re.search(r'\bmust\b|\brequired\b|\bshall\b|必須|必须|須|不得|禁止', line, re.I)
                default = owner == 'L19_CONSTRAINTS_PDK' and '%' in line and re.search(
                    r'delay|延遲|延迟', line, re.I)
                if not (mandatory or default):
                    continue
                clause = re.sub(r'^\s*[-*+]\s+', '', line).strip()
                context = [p[2] for p in parents if re.search(
                    r'\bif\b|\bwhen\b|假如|若|僅當|仅当', p[2], re.I)]
                normalize = lambda s: ' '.join(s.split())
                count += 1
                if not any(isinstance(row, dict) and row.get('source') == rel
                           and isinstance(row.get('evidence'), str)
                           and all(normalize(part) in normalize(row['evidence'])
                                   for part in [clause, *context])
                           for row in owners[owner]):
                    missing.append(f'{rel}:{line_no} -> {owner}: {clause}')
    return count, missing


def _section_covered(section: dict, l_text: str) -> bool:
    """A section is covered if its sec_id, heading text, or file:line
    appears anywhere in the concatenated L*.json text."""
    sec_id = section["sec_id"]
    heading = section["heading"]
    file_ref = f"{section['file']}:{section['line']}"

    if file_ref in l_text:
        return True
    if sec_id and len(sec_id) >= 1:
        # Match the sec_id as a token (e.g. "1.2" appearing in evidence)
        if re.search(rf"\b{re.escape(sec_id)}\b", l_text):
            return True
    # Heading text — require at least 4 chars and case-insensitive
    # substring match.
    if heading and len(heading) >= 4:
        if heading.lower() in l_text.lower():
            return True
    return False


def _load_waivers(project: Path) -> Set[str]:
    """Returns set of slugs that have a valid waiver."""
    out: Set[str] = set()
    p = project / "waivers.json"
    if not p.exists():
        return out
    try:
        d = json.loads(p.read_text())
    except Exception:
        return out
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if not isinstance(k, str) or not k.startswith(WAIVER_PREFIX):
            continue
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            out.add(k[len(WAIVER_PREFIX):])
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: phase1_doc_content_implementation_completeness_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    clause_count, missing_clauses = _owned_clause_coverage(project)
    if missing_clauses:
        print('[FAIL] phase1_doc_content_implementation_completeness_check: '
              'source-owned integration/timing obligations missing: '
              + '; '.join(missing_clauses))
        return 1

    sections = _scan_sections(project)
    if not sections:
        if clause_count:
            print('[PASS] phase1_doc_content_implementation_completeness_check: '
                  f'{clause_count} source-owned integration/timing clauses preserved')
            return 0
        print("[SKIP] phase1_doc_content_implementation_completeness_check: "
              "no parseable section headings in input/docs or extracted_docs")
        return 0

    l_text = _load_l_doc_text(project)
    if not l_text:
        print(f"[FAIL] "
              f"phase1_doc_content_implementation_completeness_check: "
              f"{len(sections)} section heading(s) in docs but "
              f"generated_docs/L*.json missing or empty")
        return 1

    waivers = _load_waivers(project)

    covered: List[dict] = []
    uncovered: List[dict] = []
    waived: List[dict] = []
    for sec in sections:
        if sec["slug"] in waivers:
            waived.append(sec)
            continue
        if _section_covered(sec, l_text):
            covered.append(sec)
        else:
            uncovered.append(sec)

    eligible = len(sections) - len(waived)
    if eligible <= 0:
        print(f"[PASS_WITH_WAIVER] "
              f"phase1_doc_content_implementation_completeness_check: "
              f"all {len(sections)} sections waived")
        return 0

    coverage = len(covered) / eligible

    if coverage >= WARN_THRESHOLD:
        print(f"[PASS] "
              f"phase1_doc_content_implementation_completeness_check: "
              f"{len(covered)}/{eligible} sections cited in L*.json "
              f"({coverage*100:.1f}%, "
              f"{len(waived)} waived)")
        return 0

    sample = []
    for s in uncovered[:8]:
        head = s["heading"] or s["sec_id"]
        sample.append(f"{s['file']}:{s['line']} [{head}] "
                       f"slug={s['slug']}")

    if coverage >= FAIL_THRESHOLD:
        print(f"[WARN] "
              f"phase1_doc_content_implementation_completeness_check: "
              f"coverage {coverage*100:.1f}% in [80%, 90%) — "
              f"{len(uncovered)}/{eligible} sections un-cited. "
              f"Examples: {'; '.join(sample)}")
        return 0  # WARN exits 0

    print(f"[FAIL] "
          f"phase1_doc_content_implementation_completeness_check: "
          f"coverage {coverage*100:.1f}% < 80% — "
          f"{len(uncovered)}/{eligible} sections un-cited in any "
          f"L*.json. EVERY ITEM IN DESIGN DOCUMENTS SHOULD BE "
          f"IMPLEMENTED. Examples: {'; '.join(sample)}. "
          f"Per-section waiver: '{WAIVER_PREFIX}<slug>' "
          f"(>={WAIVER_MIN} chars).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
