#!/usr/bin/env python3
"""Unit tests for programs/regmap_table_extractor.py.

Pins the real two-form register-table extraction logic:
  (a) v1.6.106 dash-separated prose  `0xADDR access name - description`
  (b) v1.6.108 column-whitespace aligned tables (with optional range
      addresses and optional description column)
plus the header-row stop-list filter and the empty/garbage no-match
contract. Logic-pinned.
"""
from __future__ import annotations

import regmap_table_extractor as mod


# ---------------------------------------------------------------------------
# (a) dash-separated prose form
# ---------------------------------------------------------------------------
def test_dash_form_extracts_addr_access_name_desc():
    rows = mod.extract_regmap_table("0x10 r/w ctrl - control register", "d.txt")
    assert len(rows) == 1
    e = rows[0]
    assert e["addr_hex"] == "0x10"
    assert e["access"] == "r_w"  # "/" -> "_"
    assert e["name"] == "ctrl"
    assert e["description"] == "control register"
    assert e["evidence"]["extraction_strategy"] == "pdf_regmap_table_match"
    assert e["evidence"]["line"] == 1


def test_dash_form_lowercases_hex_addr():
    rows = mod.extract_regmap_table("0xAB r status - the status", "d.txt")
    assert rows[0]["addr_hex"] == "0xab"


# ---------------------------------------------------------------------------
# (b) column-whitespace form
# ---------------------------------------------------------------------------
_COLS = (
    "       0x00          r       name0\n"
    "       0x10          r/w     ctrl\n"
    "       0x20-0x2F     w       block0..F\n"
)


def test_column_form_single_addr_row():
    rows = mod.extract_regmap_table(_COLS, "pdf.txt")
    first = next(r for r in rows if r.get("addr_hex") == "0x00")
    assert first["access"] == "r"
    assert first["name"] == "name0"
    assert first["evidence"]["extraction_strategy"] == \
        "pdf_regmap_table_columns_match"


def test_column_form_range_row_emits_addr_range():
    rows = mod.extract_regmap_table(_COLS, "pdf.txt")
    rng = next(r for r in rows if "addr_range_hex" in r)
    assert rng["addr_range_hex"] == "0x20-0x2f"  # normalized lower, ascii dash
    assert "addr_hex" not in rng
    assert rng["access"] == "w"
    assert rng["name"] == "block0..F"


def test_column_form_count():
    # exactly 3 register rows, no header/junk in this block
    rows = mod.extract_regmap_table(_COLS, "pdf.txt")
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# header-row stop-list (the defect this guards: junk header rows leaking in)
# ---------------------------------------------------------------------------
def test_header_row_is_filtered_out():
    text = (
        "       Address       Type    Name\n"   # header, must be dropped
        "       0x00          r       name0\n"  # real row
    )
    rows = mod.extract_regmap_table(text, "pdf.txt")
    names = [r["name"] for r in rows]
    assert "Name" not in names
    assert names == ["name0"]


def test_dash_header_row_filtered():
    text = "0x00 r Name - column header that should not survive"
    # "Name" is in the stop-list -> the dash row is dropped
    rows = mod.extract_regmap_table(text, "d.txt")
    assert rows == []


# ---------------------------------------------------------------------------
# empty / garbage contract
# ---------------------------------------------------------------------------
def test_empty_text_returns_empty_list():
    assert mod.extract_regmap_table("", "d.txt") == []


def test_garbage_returns_empty_list():
    assert mod.extract_regmap_table(
        "lorem ipsum, no register table here", "d.txt"
    ) == []


def test_single_space_columns_not_matched():
    # spec: columns require 2+ spaces; single-space prose must NOT match
    assert mod.extract_regmap_table("see 0x00 r register elsewhere", "d.txt") == []
