#!/usr/bin/env python3
"""ds_quality_check.py — Datasheet (L1) quality scorer, 0-100.

Implements the 10-criterion rubric declared in
`skills/spec-validator/SKILL.md` ("ds_quality_check.py — Datasheet Scoring").
Each criterion scores 0-10, total 0-100. **Checkpoint-1 threshold: >= 70/100.**

Criteria (0-10 each, exactly as the SKILL rubric states):
   1 Features                          — section exists, >=5 bullet items
   2 Description                        — >=2 paragraphs
   3 Pin Configuration                 — table with >=3 columns
   4 Absolute Maximum Ratings          — table exists with >=5 params (rows)
   5 Recommended Operating Conditions  — table with min/typ/max columns
   6 Electrical Characteristics        — DC + AC sections, with tables
   7 Timing Diagrams                   — ASCII art or description present
   8 Block Diagram                     — visual diagram present
   9 Detailed Description + Reg Map     — long description + register table
  10 Application Information           — circuit diagram + component values

chip-AGNOSTIC: every check is structural/keyword on Markdown. No IC, vendor,
SKU, pin-name or register-address literals appear here.

No-false-alert posture: a missing/empty/non-Markdown file degrades to score 0
with a single MISSING/SKIP finding — it never crashes and never over-flags
(every criterion needs a *length floor* of real content before it can score,
so an empty heading earns 0, not a partial pass).

CLI:
    python3 ds_quality_check.py <datasheet.md>
    python3 ds_quality_check.py <datasheet.md> --json
    python3 ds_quality_check.py <project_dir>          # auto-locate datasheet

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
from typing import List, Optional, Tuple

THRESHOLD = 70
MAX_SCORE = 100

# Filenames a project may store the datasheet under (auto-locate, chip-agnostic).
_DS_GLOBS = (
    "**/04_datasheet.md",
    "**/*datasheet*.md",
    "**/L1*.md",
    "**/*L1_DATASHEET*.md",
)


@dataclass
class CriterionScore:
    index: int
    name: str
    score: int          # 0..10
    max: int            # 10
    note: str


@dataclass
class DSResult:
    score: int
    max: int
    verdict: str        # PASS / FAIL / MISSING
    threshold: int
    breakdown: List[CriterionScore]
    source: str

    def to_dict(self) -> dict:
        return {
            "program": "ds_quality_check",
            "version": "1.0.0",
            "source": self.source,
            "score": self.score,
            "max": self.max,
            "threshold": self.threshold,
            "verdict": self.verdict,
            "breakdown": [asdict(c) for c in self.breakdown],
        }


# ---------------------------------------------------------------------------
# Markdown structural helpers (all generic, no chip literals)
# ---------------------------------------------------------------------------
def _section_body(text: str, *keywords: str) -> Optional[str]:
    """Return the body text between a heading matching any keyword and the next
    heading of the same-or-shallower level, or None if no such heading exists.

    Headings are ``#``-style ATX or ``Name`` followed by ``---``/``===`` setext.
    Matching is case-insensitive substring on the heading text."""
    lines = text.splitlines()
    kws = [k.lower() for k in keywords]
    # Locate heading.
    start = None
    head_level = 6
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", ln)
        htext = None
        level = 6
        if m:
            level = len(m.group(1))
            htext = m.group(2)
        elif i + 1 < len(lines) and re.match(r"^\s*[-=]{3,}\s*$", lines[i + 1]) and ln.strip():
            level = 1 if lines[i + 1].lstrip().startswith("=") else 2
            htext = ln.strip()
        if htext is not None:
            hl = htext.lower()
            if any(k in hl for k in kws):
                start = i + 1
                head_level = level
                break
    if start is None:
        return None
    # Collect until next heading of same-or-shallower level.
    body: List[str] = []
    for ln in lines[start:]:
        m = re.match(r"^(#{1,6})\s+", ln)
        if m and len(m.group(1)) <= head_level:
            break
        body.append(ln)
    return "\n".join(body)


def _bullet_count(body: str) -> int:
    return sum(1 for ln in body.splitlines()
               if re.match(r"^\s*[-*+]\s+\S", ln)
               or re.match(r"^\s*\d+[.)]\s+\S", ln))


def _paragraph_count(body: str) -> int:
    """Count non-trivial paragraphs (blank-line-separated blocks of prose)."""
    blocks = re.split(r"\n\s*\n", body.strip())
    n = 0
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        # Ignore tables, bullet-only blocks and code fences — count prose only.
        if b.startswith("```"):
            continue
        prose_lines = [ln for ln in b.splitlines()
                       if not ln.lstrip().startswith(("|", "-", "*", "+", "#"))
                       and not re.match(r"^\s*\d+[.)]\s", ln)]
        if prose_lines and len(" ".join(prose_lines).strip()) >= 40:
            n += 1
    return n


def _markdown_tables(body: str) -> List[List[str]]:
    """Return each Markdown table as a list of its data rows (header excluded).

    A table is >=2 consecutive ``|`` lines where the 2nd line is a ``---``
    separator. Returns the header + data rows for column counting upstream."""
    tables: List[List[str]] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and re.match(
            r"^\s*\|?\s*:?-{2,}", lines[i + 1].replace(" ", "")
        ) and "|" in lines[i + 1]:
            block = [lines[i]]              # header row
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                block.append(lines[j])
                j += 1
            tables.append(block)
            i = j
        else:
            i += 1
    return tables


def _max_columns(table: List[str]) -> int:
    if not table:
        return 0
    cells = [c for c in table[0].split("|") if c.strip()]
    return len(cells)


def _data_rows(table: List[str]) -> int:
    # Whole block minus the header row.
    return max(0, len(table) - 1)


def _has_code_fence(body: str) -> bool:
    return body.count("```") >= 2


def _looks_like_diagram(body: str) -> bool:
    """ASCII-art / fenced-diagram heuristic: a code fence, or >=3 lines that
    contain box-drawing or connector glyphs (length floor avoids flagging a
    single stray '+')."""
    if _has_code_fence(body):
        return True
    glyph_lines = [ln for ln in body.splitlines()
                   if len(ln.strip()) >= 4
                   and len(re.findall(r"[+|/\\_<>─│┌┐└┘├┤┬┴┼►▲▼\-]", ln)) >= 3]
    return len(glyph_lines) >= 3


# ---------------------------------------------------------------------------
# The 10 criteria
# ---------------------------------------------------------------------------
def _c1_features(text: str) -> CriterionScore:
    body = _section_body(text, "feature")
    if body is None:
        return CriterionScore(1, "Features", 0, 10, "no Features section")
    n = _bullet_count(body)
    if n >= 5:
        return CriterionScore(1, "Features", 10, 10, f"{n} bullets (>=5)")
    sc = max(0, round(n / 5 * 10))
    return CriterionScore(1, "Features", sc, 10, f"{n} bullets (<5)")


def _c2_description(text: str) -> CriterionScore:
    body = _section_body(text, "description", "overview", "general description")
    # Exclude the *detailed* description which is scored separately.
    if body is None:
        return CriterionScore(2, "Description", 0, 10, "no Description section")
    n = _paragraph_count(body)
    if n >= 2:
        return CriterionScore(2, "Description", 10, 10, f"{n} paragraphs (>=2)")
    return CriterionScore(2, "Description", 5 if n == 1 else 0, 10,
                          f"{n} paragraph(s) (<2)")


def _c3_pin_config(text: str) -> CriterionScore:
    body = _section_body(text, "pin config", "pin description", "pin assignment",
                         "pinout", "pin function")
    if body is None:
        return CriterionScore(3, "Pin Configuration", 0, 10, "no Pin section")
    tables = _markdown_tables(body)
    cols = max((_max_columns(t) for t in tables), default=0)
    if cols >= 3:
        return CriterionScore(3, "Pin Configuration", 10, 10,
                              f"table with {cols} columns (>=3)")
    if tables:
        return CriterionScore(3, "Pin Configuration", 5, 10,
                              f"table with {cols} columns (<3)")
    return CriterionScore(3, "Pin Configuration", 0, 10, "section but no table")


def _c4_abs_max(text: str) -> CriterionScore:
    body = _section_body(text, "absolute maximum", "abs max", "absolute max")
    if body is None:
        return CriterionScore(4, "Absolute Maximum Ratings", 0, 10, "no AMR section")
    tables = _markdown_tables(body)
    rows = max((_data_rows(t) for t in tables), default=0)
    if rows >= 5:
        return CriterionScore(4, "Absolute Maximum Ratings", 10, 10,
                              f"table with {rows} params (>=5)")
    if tables:
        return CriterionScore(4, "Absolute Maximum Ratings", 5, 10,
                              f"table with {rows} params (<5)")
    return CriterionScore(4, "Absolute Maximum Ratings", 0, 10, "section but no table")


def _c5_rec_op(text: str) -> CriterionScore:
    body = _section_body(text, "recommended operating", "operating condition")
    if body is None:
        return CriterionScore(5, "Recommended Operating Conditions", 0, 10,
                              "no ROC section")
    tables = _markdown_tables(body)
    has_minmaxtyp = False
    for t in tables:
        header = t[0].lower()
        if "min" in header and "max" in header and "typ" in header:
            has_minmaxtyp = True
            break
    if has_minmaxtyp:
        return CriterionScore(5, "Recommended Operating Conditions", 10, 10,
                              "table with min/typ/max")
    if tables:
        return CriterionScore(5, "Recommended Operating Conditions", 5, 10,
                              "table without full min/typ/max")
    return CriterionScore(5, "Recommended Operating Conditions", 0, 10,
                          "section but no table")


def _c6_electrical(text: str) -> CriterionScore:
    body = _section_body(text, "electrical characteristic", "electrical spec")
    if body is None:
        return CriterionScore(6, "Electrical Characteristics", 0, 10,
                              "no Electrical section")
    low = body.lower()
    # DC + AC sub-content (either explicit "DC"/"AC" markers or dc/ac headings).
    has_dc = bool(re.search(r"\bdc\b", low)) or "direct current" in low
    has_ac = bool(re.search(r"\bac\b", low)) or "alternating current" in low \
        or "switching" in low
    tables = _markdown_tables(body)
    score = 0
    notes = []
    if has_dc:
        score += 4
        notes.append("DC")
    if has_ac:
        score += 4
        notes.append("AC")
    if tables:
        score += 2
        notes.append(f"{len(tables)} table(s)")
    score = min(score, 10)
    return CriterionScore(6, "Electrical Characteristics", score, 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c7_timing(text: str) -> CriterionScore:
    body = _section_body(text, "timing diagram", "timing waveform", "timing",
                         "waveform")
    if body is None:
        return CriterionScore(7, "Timing Diagrams", 0, 10, "no Timing section")
    if _looks_like_diagram(body):
        return CriterionScore(7, "Timing Diagrams", 10, 10, "diagram/ascii present")
    if len(body.strip()) >= 80:
        return CriterionScore(7, "Timing Diagrams", 5, 10, "description only")
    return CriterionScore(7, "Timing Diagrams", 0, 10, "section but empty")


def _c8_block_diagram(text: str) -> CriterionScore:
    body = _section_body(text, "block diagram", "functional block", "architecture")
    if body is None:
        return CriterionScore(8, "Block Diagram", 0, 10, "no Block Diagram section")
    if _looks_like_diagram(body):
        return CriterionScore(8, "Block Diagram", 10, 10, "visual diagram present")
    if len(body.strip()) >= 60:
        return CriterionScore(8, "Block Diagram", 5, 10, "text only, no diagram")
    return CriterionScore(8, "Block Diagram", 0, 10, "section but empty")


def _c9_detailed_regmap(text: str) -> CriterionScore:
    body = _section_body(text, "detailed description", "functional description",
                         "register map", "register description", "register table")
    if body is None:
        return CriterionScore(9, "Detailed Description + Register Map", 0, 10,
                              "no Detailed/Register section")
    long_desc = len(body.strip()) >= 300
    tables = _markdown_tables(body)
    # A register table: header mentions addr/reg/offset/bit.
    reg_table = any(
        re.search(r"addr|offset|register|\breg\b|bit", t[0].lower())
        for t in tables
    )
    score = 0
    notes = []
    if long_desc:
        score += 5
        notes.append("long desc")
    if reg_table:
        score += 5
        notes.append("register table")
    elif tables:
        score += 2
        notes.append("table (non-register)")
    score = min(score, 10)
    return CriterionScore(9, "Detailed Description + Register Map", score, 10,
                          ("+".join(notes) if notes else "section present, sparse"))


def _c10_application(text: str) -> CriterionScore:
    body = _section_body(text, "application information", "application note",
                         "typical application", "application circuit")
    if body is None:
        return CriterionScore(10, "Application Information", 0, 10,
                              "no Application section")
    diagram = _looks_like_diagram(body)
    # Component values: things like 10 kΩ, 0.1 uF, 4.7k, 100nF.
    has_values = bool(re.search(
        r"\b\d+(?:\.\d+)?\s?(?:k|m|u|µ|n|p|M)?\s?(?:ohm|Ω|F|H|Hz|V|A)\b",
        body, re.IGNORECASE))
    score = 0
    notes = []
    if diagram:
        score += 5
        notes.append("circuit diagram")
    if has_values:
        score += 5
        notes.append("component values")
    score = min(score, 10)
    return CriterionScore(10, "Application Information", score, 10,
                          ("+".join(notes) if notes else "section present, sparse"))


_CRITERIA = (
    _c1_features, _c2_description, _c3_pin_config, _c4_abs_max, _c5_rec_op,
    _c6_electrical, _c7_timing, _c8_block_diagram, _c9_detailed_regmap,
    _c10_application,
)


# ---------------------------------------------------------------------------
# Importable scoring entry point
# ---------------------------------------------------------------------------
def score_datasheet_text(text: str, source: str = "<text>") -> DSResult:
    """Score datasheet Markdown text. Pure function — deterministic."""
    if not text or not text.strip():
        return DSResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, "empty document")],
                        source)
    breakdown = [c(text) for c in _CRITERIA]
    total = sum(c.score for c in breakdown)
    verdict = "PASS" if total >= THRESHOLD else "FAIL"
    return DSResult(total, MAX_SCORE, verdict, THRESHOLD, breakdown, source)


def _locate_datasheet(project_dir: Path) -> Optional[Path]:
    for pat in _DS_GLOBS:
        for hit in sorted(project_dir.glob(pat)):
            if hit.is_file():
                return hit
    return None


def score_datasheet_path(path: Path) -> DSResult:
    """Score a datasheet file, or auto-locate one inside a project directory."""
    if path.is_dir():
        located = _locate_datasheet(path)
        if located is None:
            return DSResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                            [CriterionScore(0, "input", 0, 0,
                                            f"no datasheet found under {path}")],
                            str(path))
        path = located
    if not path.exists():
        return DSResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, f"file not found: {path}")],
                        str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - defensive
        return DSResult(0, MAX_SCORE, "MISSING", THRESHOLD,
                        [CriterionScore(0, "input", 0, 0, f"unreadable: {e}")],
                        str(path))
    return score_datasheet_text(text, str(path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="Datasheet .md file OR a project directory")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    result = score_datasheet_path(Path(args.path))

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Datasheet quality: {result.source}")
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
