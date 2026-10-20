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


# #3299: preserve functional H1 prose without admitting host setup guides.
@pytest.mark.parametrize(
    "text,required,forbidden",
    [('# Functional Overview\n'
      '\n'
      'The cipher can either encrypt or decrypt, but not both at the same time.\n'
      '\n'
      '## Block handling\n'
      'A completed block is returned on output_valid.\n',
      ['The cipher can either encrypt or decrypt, but not both at the same time.',
       'A completed block is returned on output_valid.'],
      []),
     ('# Functional Overview\n'
      '\n'
      '## Cipher operation\n'
      'The cipher can either encrypt or decrypt, but not both at the same time.\n'
      '\n'
      '## Block handling\n'
      'A completed block is returned on output_valid.\n',
      ['The cipher can either encrypt or decrypt, but not both at the same time.'],
      []),
     ('# Theory of Operation\n'
      '\n'
      'The cipher can either encrypt or decrypt, but not both at the same time.\n'
      '\n'
      '## Block handling\n'
      'A completed block is returned on output_valid.\n',
      ['The cipher can either encrypt or decrypt, but not both at the same time.'],
      []),
     ('# Build instructions\n'
      '\n'
      'Install the host compiler before running the build.\n'
      '\n'
      '## Setup\n'
      'Run pip install in a virtual environment.\n',
      [],
      ['Install the host compiler before running the build.',
       'Run pip install in a virtual environment.']),
     ('# Functional Overview\n'
      '\n'
      'The cipher can either encrypt or decrypt, but not both at the same time.\n'
      '\n'
      '## Setup\n'
      'Run pip install in a virtual environment.\n'
      '\n'
      '## Block handling\n'
      'A completed block is returned on output_valid.\n',
      ['The cipher can either encrypt or decrypt, but not both at the same time.',
       'A completed block is returned on output_valid.'],
      ['Run pip install in a virtual environment.']),
     ('## Setup and hold timing\n'
      'The data setup time shall be 2 ns before the active clock edge.\n',
      ['The data setup time shall be 2 ns before the active clock edge.'],
      []),
     ('# 功能定義\n本模組每次只能執行一種運算。\n\n## 輸出行為\n輸出有效時結果保持穩定。\n',
      ['本模組每次只能執行一種運算。', '輸出有效時結果保持穩定。'],
      [])],
    ids=['h1-functional', 'h2-positive', 'theory-introduction', 'build-setup-negative', 'functional-before-setup', 'hardware-setup-hold', 'cjk-h1'],
)
def test_l2_functional_preamble_source_scope(tmp_path, text, required, forbidden):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(text)
    R.gen_l2_frs(tmp_path, {"spec.md": text})
    actual = json.loads((tmp_path / "phase1/generated_docs/L2_FRS.json").read_text())
    content = "\n".join(row.get("content", "") for row in actual["frs_sections"])
    for sentence in required:
        assert sentence in content, actual["frs_sections"]
    for sentence in forbidden:
        assert sentence not in content, actual["frs_sections"]
    assert all(row["evidence"] == "input/docs/spec.md" for row in actual["frs_sections"])


def test_general_heading_walker_still_excludes_markdown_h1_by_default():
    hits = _hits("# Functional Overview\nIntro prose.\n\n## Block handling\nBlock body.\n")
    assert [(h["section_id"], h["title"]) for h in hits] == [("h2", "Block handling")]


def test_hardware_setup_contract_survives_host_installation_note(tmp_path):
    text = '## Setup and hold timing\nThe data setup time shall be 2 ns before the active clock edge.\nA software note uses pip install to prepare its optional analysis environment.\n'
    R.gen_l2_frs(tmp_path, {"spec.md": text})
    actual = json.loads((tmp_path / "phase1/generated_docs/L2_FRS.json").read_text())
    content = "\n".join(row.get("content", "") for row in actual["frs_sections"])
    assert 'The data setup time shall be 2 ns before the active clock edge.' in content, actual["frs_sections"]


def test_mixed_functional_body_under_bare_setup_is_not_installation_only(tmp_path):
    text = '## Setup\nThe data setup time shall be 2 ns before the active clock edge.\nRun pip install in a virtual environment.\n'
    R.gen_l2_frs(tmp_path, {"spec.md": text})
    actual = json.loads((tmp_path / "phase1/generated_docs/L2_FRS.json").read_text())
    content = "\n".join(row.get("content", "") for row in actual["frs_sections"])
    assert 'The data setup time shall be 2 ns before the active clock edge.' in content, actual["frs_sections"]


@pytest.mark.parametrize(
    "text,required",
    [('## Setup and hold timing\n'
      'The data setup time shall be 2 ns before the active clock edge.\n'
      'A software note uses pip install to prepare its optional analysis environment.\n'
      '\n'
      '## Output transfer\n'
      'A completed block is returned on output_valid.\n',
      ['The data setup time shall be 2 ns before the active clock edge.',
       'A completed block is returned on output_valid.']),
     ('## Setup\n'
      'The data setup time shall be 2 ns before the active clock edge.\n'
      'Run pip install in a virtual environment.\n'
      '\n'
      '## Output transfer\n'
      'A completed block is returned on output_valid.\n',
      ['The data setup time shall be 2 ns before the active clock edge.',
       'A completed block is returned on output_valid.'])],
    ids=["hardware-title-nonempty", "bare-setup-nonempty"],
)
def test_mixed_setup_retains_hardware_and_unrelated_output_section(tmp_path, text, required):
    R.gen_l2_frs(tmp_path, {"spec.md": text})
    actual = json.loads((tmp_path / "phase1/generated_docs/L2_FRS.json").read_text())
    content = "\n".join(row.get("content", "") for row in actual["frs_sections"])
    assert required[1] in content, actual["frs_sections"]
    assert required[0] in content, actual["frs_sections"]
