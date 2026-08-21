#!/usr/bin/env python3
"""an_validator.py — Application-Note (AN) validator / quality scorer, 0-80.

Implements the 8-criterion rubric declared in
`skills/spec-validator/SKILL.md` ("an_validator.py — Application Note Scoring").
Each criterion scores 0-10, total 0-80. **Checkpoint-1 threshold: >= 56/80.**

Criteria (0-10 each, exactly as the SKILL rubric states):
   1 Overview                       — >=2 paragraphs, >300 chars
   2 Typical Application Circuit    — ASCII schematic + components
   3 External Component Selection   — table + values
   4 PCB Layout                     — guidelines + diagram
   5 Firmware Example               — code block + register ops
   6 Design Calculations            — >=3 formulas + values
   7 FAQ                            — >=5 Q&A items
   8 Competitive Comparison         — table with >=3 products

chip-AGNOSTIC: every check is structural/keyword on Markdown. No IC, vendor,
SKU, pin-name or register-address literals appear here.

No-false-alert posture: a missing/empty/non-Markdown file degrades to score 0
with one MISSING/SKIP finding — it never crashes and never over-flags. Every
criterion needs a *length / count floor* of real content before scoring, so an
empty heading earns 0 (not a partial credit).

CLI:
    python3 an_validator.py <appnote.md>
    python3 an_validator.py <appnote.md> --json
    python3 an_validator.py <project_dir>          # auto-locate appnote

Exit codes:
    0 = score >= threshold (PASS)
    1 = score <  threshold (FAIL)
    2 = file missing / unreadable / empty (MISSING — never a false FAIL)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

# Reuse the shared structural Markdown helpers from ds_quality_check.
try:
    from ds_quality_check import (
        _section_body, _bullet_count, _paragraph_count, _markdown_tables,
        _max_columns, _data_rows, _has_code_fence, _looks_like_diagram,
    )
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ds_quality_check import (  # noqa: E402
        _section_body, _bullet_count, _paragraph_count, _markdown_tables,
        _max_columns, _data_rows, _has_code_fence, _looks_like_diagram,
    )

THRESHOLD = 56
MAX_SCORE = 80

_AN_GLOBS = (
    "**/05_appnote.md",
    "**/*appnote*.md",
    "**/*app_note*.md",
    "**/*application_note*.md",
    "**/L5*.md",
)

_COMPONENT_VALUE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:k|m|u|µ|n|p|M)?\s?(?:ohm|Ω|F|H|Hz|V|A)\b",
    re.IGNORECASE,
)


@dataclass
class CriterionScore:
    index: int
    name: str
    score: int
    max: int
    note: str


@dataclass
class ANResult:
    score: int
    max: int
    verdict: str        # PASS / FAIL / MISSING
    threshold: int
    breakdown: List[CriterionScore]
    source: str

    def to_dict(self) -> dict:
        return {
            "program": "an_validator",
            "version": "1.0.0",
            "source": self.source,
            "score": self.score,
            "max": self.max,
            "threshold": self.threshold,
            "verdict": self.verdict,
            "breakdown": [asdict(c) for c in self.breakdown],
        }


# ---------------------------------------------------------------------------
# The 8 criteria
# ---------------------------------------------------------------------------
def _c1_overview(text: str) -> CriterionScore:
    body = _section_body(text, "overview", "introduction", "abstract")
    if body is None:
        return CriterionScore(1, "Overview", 0, 10, "no Overview section")
    n = _paragraph_count(body)
    chars = len(body.strip())
    if n >= 2 and chars > 300:
        return CriterionScore(1, "Overview", 10, 10,
                              f"{n} paragraphs, {chars} chars (>300)")
    score = 0
    if n >= 2:
        score += 5
    if chars > 300:
        score += 5
    return CriterionScore(1, "Overview", min(score, 9), 10,
                          f"{n} paragraphs, {chars} chars")


def _c2_typical_circuit(text: str) -> CriterionScore:
    body = _section_body(text, "typical application circuit",
                         "typical application", "application circuit",
                         "schematic")
    if body is None:
        return CriterionScore(2, "Typical Application Circuit", 0, 10,
                              "no Typical Circuit section")
    diagram = _looks_like_diagram(body)
    components = bool(_COMPONENT_VALUE_RE.search(body))
    score = 0
    notes = []
    if diagram:
        score += 5
        notes.append("ascii schematic")
    if components:
        score += 5
        notes.append("components")
    return CriterionScore(2, "Typical Application Circuit", min(score, 10), 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c3_external_components(text: str) -> CriterionScore:
    body = _section_body(text, "external component", "component selection",
                         "bill of materials", "bom")
    if body is None:
        return CriterionScore(3, "External Component Selection", 0, 10,
                              "no External Component section")
    tables = _markdown_tables(body)
    values = bool(_COMPONENT_VALUE_RE.search(body))
    score = 0
    notes = []
    if tables:
        score += 5
        notes.append(f"{len(tables)} table(s)")
    if values:
        score += 5
        notes.append("values")
    return CriterionScore(3, "External Component Selection", min(score, 10), 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c4_pcb_layout(text: str) -> CriterionScore:
    body = _section_body(text, "pcb layout", "layout guideline", "layout",
                         "board layout")
    if body is None:
        return CriterionScore(4, "PCB Layout", 0, 10, "no PCB Layout section")
    bullets = _bullet_count(body)
    guidelines = bullets >= 2 or len(body.strip()) >= 120
    diagram = _looks_like_diagram(body)
    score = 0
    notes = []
    if guidelines:
        score += 5
        notes.append("guidelines")
    if diagram:
        score += 5
        notes.append("diagram")
    return CriterionScore(4, "PCB Layout", min(score, 10), 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c5_firmware(text: str) -> CriterionScore:
    body = _section_body(text, "firmware example", "firmware", "code example",
                         "software", "driver example")
    if body is None:
        return CriterionScore(5, "Firmware Example", 0, 10, "no Firmware section")
    has_code = _has_code_fence(body)
    # Register ops: read/write style API calls or HEX register accesses.
    reg_ops = bool(re.search(
        r"\b(?:write|read|reg_write|reg_read|i2c_write|i2c_read|spi_write|"
        r"spi_read|write_reg|read_reg)\b", body, re.IGNORECASE)) \
        or bool(re.search(r"0x[0-9A-Fa-f]{1,4}", body))
    score = 0
    notes = []
    if has_code:
        score += 5
        notes.append("code block")
    if reg_ops:
        score += 5
        notes.append("register ops")
    return CriterionScore(5, "Firmware Example", min(score, 10), 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c6_design_calculations(text: str) -> CriterionScore:
    body = _section_body(text, "design calculation", "calculation",
                         "design equation", "design formula")
    if body is None:
        return CriterionScore(6, "Design Calculations", 0, 10,
                              "no Design Calculations section")
    # Formulas: lines containing '=' with an arithmetic / variable structure,
    # or fenced math. Length floor avoids flagging a single stray '='.
    formula_lines = [ln for ln in body.splitlines()
                     if "=" in ln and len(ln.strip()) >= 5
                     and re.search(r"[*/+\-^()]|[A-Za-z]\s*=", ln)
                     and not ln.lstrip().startswith("|")]
    n_formulas = len(formula_lines)
    values = bool(_COMPONENT_VALUE_RE.search(body)) or bool(
        re.search(r"\b\d+(?:\.\d+)?\b", body))
    if n_formulas >= 3 and values:
        return CriterionScore(6, "Design Calculations", 10, 10,
                              f"{n_formulas} formulas (>=3) + values")
    score = 0
    notes = []
    if n_formulas >= 3:
        score += 6
        notes.append(f"{n_formulas} formulas")
    elif n_formulas:
        score += min(n_formulas * 2, 5)
        notes.append(f"{n_formulas} formula(s)")
    if values:
        score += 2
        notes.append("values")
    return CriterionScore(6, "Design Calculations", min(score, 9), 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c7_faq(text: str) -> CriterionScore:
    body = _section_body(text, "faq", "frequently asked", "q&a", "questions")
    if body is None:
        return CriterionScore(7, "FAQ", 0, 10, "no FAQ section")
    # Count Q&A items: 'Q:' / 'Q.' / '**Q' markers (optionally bulleted), or
    # '?'-terminated numbered list items.
    q_markers = len(re.findall(
        r"(?m)^\s*(?:[-*+]\s*)?(?:\*{0,2}Q\b[\d.: )]|\d+[.)]\s+.*\?)", body))
    if q_markers == 0:
        # Fallback: count question-mark lines.
        q_markers = sum(1 for ln in body.splitlines()
                        if ln.strip().endswith("?") and len(ln.strip()) >= 8)
    if q_markers >= 5:
        return CriterionScore(7, "FAQ", 10, 10, f"{q_markers} Q&A (>=5)")
    sc = max(0, min(round(q_markers / 5 * 10), 9))
    return CriterionScore(7, "FAQ", sc, 10, f"{q_markers} Q&A (<5)")


def _c8_competitive(text: str) -> CriterionScore:
    body = _section_body(text, "competitive comparison", "comparison",
                         "competitor", "vs.", "competitive")
    if body is None:
        return CriterionScore(8, "Competitive Comparison", 0, 10,
                              "no Competitive Comparison section")
    tables = _markdown_tables(body)
    # >=3 products: a table with >=3 data rows OR >=4 columns (product columns).
    best_rows = max((_data_rows(t) for t in tables), default=0)
    best_cols = max((_max_columns(t) for t in tables), default=0)
    if best_rows >= 3 or best_cols >= 4:
        return CriterionScore(8, "Competitive Comparison", 10, 10,
                              f"table {best_rows} rows / {best_cols} cols (>=3 products)")
    if tables:
        return CriterionScore(8, "Competitive Comparison", 5, 10,
                              f"table {best_rows} rows / {best_cols} cols (<3 products)")
    return CriterionScore(8, "Competitive Comparison", 0, 10,
                          "section but no table")


_CRITERIA = (
    _c1_overview, _c2_typical_circuit, _c3_external_components, _c4_pcb_layout,
    _c5_firmware, _c6_design_calculations, _c7_faq, _c8_competitive,
)


# ---------------------------------------------------------------------------
# Importable scoring entry point
# ---------------------------------------------------------------------------
def score_appnote_text(text: str, source: str = "<text>") -> ANResult:
    """Score application-note Markdown text. Pure function — deterministic."""
    if not text or not text.strip():
        return ANResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, "empty document")],
                        source)
    breakdown = [c(text) for c in _CRITERIA]
    total = sum(c.score for c in breakdown)
    verdict = "PASS" if total >= THRESHOLD else "FAIL"
    return ANResult(total, MAX_SCORE, verdict, THRESHOLD, breakdown, source)


def _locate_appnote(project_dir: Path) -> Optional[Path]:
    for pat in _AN_GLOBS:
        for hit in sorted(project_dir.glob(pat)):
            if hit.is_file():
                return hit
    return None


def score_appnote_path(path: Path) -> ANResult:
    if path.is_dir():
        located = _locate_appnote(path)
        if located is None:
            return ANResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                            [CriterionScore(0, "input", 0, 0,
                                            f"no appnote found under {path}")],
                            str(path))
        path = located
    if not path.exists():
        return ANResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, f"file not found: {path}")],
                        str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - defensive
        return ANResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, f"unreadable: {e}")],
                        str(path))
    return score_appnote_text(text, str(path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="Application-note .md file OR a project directory")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    result = score_appnote_path(Path(args.path))

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Application-note quality: {result.source}")
        for c in result.breakdown:
            if c.max:
                print(f"  [{c.score:2d}/{c.max}] {c.index:2d}. {c.name} — {c.note}")
            else:
                print(f"  {c.note}")
        print(f"\nScore: {result.score}/{result.max}  "
              f"Threshold: {result.threshold}  Verdict: {result.verdict}")

    if result.verdict == "MISSING":
        return 2
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
