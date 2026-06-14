"""Regression for ORGANIC #630 — the section-header walker drops every
CJK/non-ASCII-titled ATX/AsciiDoc/setext heading (leading [A-Z] anchor),
under-filling L2.frs_sections and failing the L2 ≥15 typed-field floor.

現象 (round-2 v1.0.22 6-IC clean-room): a datapath-multiplier IC whose L2
architecture spec is authored in CJK headings (`## 功能定義` / `## 資料寬度`
/ …). The three non-numbered section-header regexes (md_atx / adoc /
md_setext-rst_underline) anchored the title group on `[A-Z]` (ASCII upper),
so a content-rich CJK doc matched ZERO headings:
`_v1_6_334_extract_multi_shape_section_headers` returned 0 while the doc had 6
well-formed ATX sections, the L2 extraction_evidence was [], the typed-field
tally fell below the ≥15 floor, and l_doc_structured_field_count_check FAILed
(no-waiver).

Fix: the title's FIRST char admits ASCII-uppercase OR any non-ASCII LETTER
(`(?:[A-Z]|[^\\x00-\\x7F\\W\\d_])`) in all three regexes. The ASCII path stays
byte-identical (lowercase-led prose still rejected, downstream noise guards
unaffected); CJK / accented-Latin / Greek / Cyrillic headings now mine.

NEGATIVE no-leak: an uppercase-English doc yields the same hits as before; a
lowercase-led line is still rejected (not a heading).

chip-AGNOSTIC: pure docs-tooling grammar; no chip / vendor / SKU literal.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_CJK_ATX = (
    "## 功能定義\n本模組計算乘法。\n\n"
    "## 資料寬度\n參數 size 可調。\n\n"
    "## 同步行為\nclk 上升緣。\n\n"
    "## 輸出時序語意\n輸出 p 為組合邏輯。\n\n"
    "## 演算法選擇空間\n可選 Booth 或 array。\n\n"
    "## 不在 L2 約束的事\n佈局留給後端。\n")


def _hits(text):
    return R._v1_6_334_extract_multi_shape_section_headers(text)


# ── (1) the fix: CJK headings now mine ───────────────────────────────────────

def test_cjk_atx_headings_mined():
    assert len(_hits(_CJK_ATX)) == 6


def test_cjk_adoc_headings_mined():
    adoc = "== 功能定義\nx\n\n== 資料寬度\ny\n"
    assert len(_hits(adoc)) == 2


def test_cjk_rst_setext_headings_mined():
    rst = "功能定義\n=========\nx\n\n資料寬度\n=========\ny\n"
    assert len(_hits(rst)) == 2


def test_accented_latin_heading_mined():
    """Non-ASCII Latin (accented) headings mine too — the fix is general, not
    CJK-keyed."""
    doc = "## Définition\nx\n\n## Spécification\ny\n"
    assert len(_hits(doc)) == 2


# ── (2) NEGATIVE no-leak: ASCII path byte-identical ──────────────────────────

def test_uppercase_english_unchanged_NOLEAK():
    eng = "## Function Definition\nx\n\n## Data Width\ny\n"
    assert len(_hits(eng)) == 2


def test_lowercase_led_still_rejected_NOLEAK():
    """A lowercase-led line is still NOT a heading (the ASCII discipline is
    preserved; the fix only ADDS non-ASCII letters)."""
    low = "## function definition\nx\n\n## data width\ny\n"
    assert len(_hits(low)) == 0


# ── (3) end-to-end: gen_l2_frs fills frs_sections for a CJK L2 ────────────────

def test_gen_l2_frs_mines_cjk_sections(tmp_path):
    """The real entry point: gen_l2_frs on a CJK L2 doc populates
    frs_sections + extraction_evidence (was [] pre-fix), so the downstream L2
    ≥15 typed-field floor is reachable honestly."""
    proj = tmp_path / "proj"
    R.gen_l2_frs(proj, {"L2_architecture.md": _CJK_ATX})
    d = json.loads(
        (R._pl.generated_docs_dir(proj) / "L2_FRS.json").read_text())
    assert len(d.get("frs_sections") or []) == 6
    ev = d.get("extraction_evidence", {}).get(
        "input/docs/L2_architecture.md", [])
    assert len(ev) == 6, "CJK L2 extraction_evidence still empty"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
