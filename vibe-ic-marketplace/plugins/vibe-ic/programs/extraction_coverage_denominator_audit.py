#!/usr/bin/env python3
"""
extraction_coverage_denominator_audit.py — gate (Wave 31, v0.119.63).

Catches denominator-shrinking gameplay. v0.119.50 / v0.119.56 produced
``38 / 118`` = 100% on `extraction_coverage_report.md` while a legitimate
run on the same vendor docs shows ``1091 / 1094``. The numerator/
denominator both shrank, so percentage stayed at 100% but only a tiny
fraction of the input vocabulary was actually probed.

This audit gate works irrespective of `extraction_patterns.json` —
it independently counts the distinct content tokens in
`input_doc/*.txt` (vendor doc text) and compares the count to
the denominator recorded in `reports/extraction_coverage_report.md`.

  * FAIL when denominator < 50% of distinct-token count
  * WARN (still exit 0) when denominator < 80%
  * PASS when denominator ≥ 80%

The forbidden-waiver list in `phase1_no_waivers_used_check` is
extended in Wave 31 to include the prefix
``extraction_coverage_denominator_*``.

Usage
-----
    python3 extraction_coverage_denominator_audit.py <project_dir>

Returns 0 PASS / WARN / silent-skip, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import _path_layout as _pl


# Same auto-discovery vocabulary as
# `extraction_coverage_check.py` / `phase1_coverage_report_gen.py`,
# so the comparison is apples-to-apples.
_REGEX_FAMILIES = (
    re.compile(r"@(?:0x)?[0-9A-Fa-f]+"),
    re.compile(r"0x[0-9A-Fa-f]+"),
    re.compile(r"[A-Z][A-Z0-9_]*\[\d+\]"),
    re.compile(
        r"\d+\.?\d*[ \t\r]*(?:us|ms|ns|MHz|Hz|kHz|V|mV|kΩ|Ω|pF|nF|μF|nm)"),
    re.compile(r"(?:Section|Table|Figure)\s+\d+(?:\.\d+)?"),
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"),
)
_STOPLIST = frozenset({
    "JSON", "TRUE", "FALSE", "NULL", "TODO", "FIXME", "NOTE",
    "TBD", "TBA", "RTL", "PASS", "FAIL", "WARN", "INFO",
    "MIN", "MAX", "AVG", "STD",
    "THE", "AND", "WITH", "FOR", "MUST", "SHALL", "WILL", "FROM",
    "INTO", "THIS", "THAT", "WHEN", "WHERE", "WHILE", "BETWEEN",
    "OVER", "UNDER", "EACH", "ANY", "ALL", "BOTH", "SUCH",
    "BASED", "USED", "USE", "USES", "NEW", "OLD", "ONLY",
    "ONE", "TWO", "THREE", "BIT", "BYTE", "WORD",
})


def _count_distinct_tokens(project: Path) -> int:
    """Count distinct content tokens across input_doc/*.txt and
    input/docs/*.txt (deduped by filename)."""
    sources = []
    p1 = _pl.input_doc_dir(project)
    if p1.is_dir():
        sources.extend(sorted(p1.glob("*.txt")))
    p2 = project / "input" / "docs"
    if p2.is_dir():
        sources.extend(sorted(p2.glob("*.txt")))
    if not sources:
        return 0
    seen_files: set[str] = set()
    distinct: set[str] = set()
    for p in sources:
        if p.name in seen_files:
            continue
        seen_files.add(p.name)
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        for rx in _REGEX_FAMILIES:
            for m in rx.findall(text):
                tok = m.strip() if isinstance(m, str) else ""
                if (not tok or "\n" in tok or "\r" in tok or "\t" in tok
                        or tok.upper() in _STOPLIST):
                    continue
                distinct.add(tok)
    return len(distinct)


_DENOM_RX_PRIMARY = re.compile(
    r"(?:Overall|overall|coverage|Coverage)[^\n]*?(\d+)\s*/\s*(\d+)")
# Markdown table / sentence variants.
_DENOM_RX_FALLBACK = re.compile(
    r"\b(\d+)\s*/\s*(\d+)\b")


def _read_recorded_denominator(project: Path) -> int | None:
    """Return the denominator recorded in
    `reports/extraction_coverage_report.md` (or .json), or None."""
    md = _pl.report_path(project, "extraction_coverage_report.md")
    js = _pl.report_path(project, "extraction_coverage_report.json")
    if js.is_file():
        try:
            import json
            data = json.loads(js.read_text())
            ov = data.get("overall") or {}
            tot = ov.get("total")
            if isinstance(tot, int):
                return tot
        except Exception:
            pass
    if md.is_file():
        try:
            txt = md.read_text(errors="replace")
        except Exception:
            return None
        m = _DENOM_RX_PRIMARY.search(txt)
        if m:
            try:
                return int(m.group(2))
            except ValueError:
                pass
        # Fallback: scan all "X/Y" pairs and pick the largest Y as the
        # canonical overall denominator.
        best = 0
        for m in _DENOM_RX_FALLBACK.finditer(txt):
            try:
                y = int(m.group(2))
                if y > best:
                    best = y
            except ValueError:
                continue
        return best or None
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: extraction_coverage_denominator_audit.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2

    distinct = _count_distinct_tokens(project)
    if distinct == 0:
        print("SKIP — no input_doc/ / input/docs/ text "
              "(chip-agnostic silent-skip).")
        return 2

    denom = _read_recorded_denominator(project)
    if denom is None:
        print("SKIP — no reports/extraction_coverage_report.{md,json} "
              "recorded yet (run phase1_coverage_report_gen first).")
        return 2

    pct = (denom / distinct) if distinct else 0.0
    if pct < 0.50:
        print(f"FAIL — recorded denominator = {denom}, distinct vendor "
              f"tokens = {distinct} ({pct:.1%}); below 50% threshold. "
              "This is the canonical denominator-shrink gaming pattern "
              "(v0.119.50 ‘38 / 118’ vs legit ‘1091 / 1094’).")
        print()
        print("To resolve: run phase1_coverage_report_gen.py with the "
              "current input_doc/ / input/docs/ corpus so the "
              "denominator reflects the real vocabulary. NO waiver "
              "allowed (forbidden prefix "
              "`extraction_coverage_denominator_*`).")
        return 1
    if pct < 0.80:
        print(f"WARN — recorded denominator = {denom}, distinct vendor "
              f"tokens = {distinct} ({pct:.1%}); below 80%. The "
              "extraction_coverage_report.md denominator should "
              "ideally reflect at least 80% of the auto-discovered "
              "vendor token vocabulary.")
        return 0
    print(f"PASS — recorded denominator = {denom}, distinct vendor "
          f"tokens = {distinct} ({pct:.1%}); ≥80%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
