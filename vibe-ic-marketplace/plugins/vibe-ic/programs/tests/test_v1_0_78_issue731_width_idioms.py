"""Regression for ORGANIC #731 — Phase-1 port-table width extractor silently
drops the stated bus WIDTH for two common markdown idioms, defaulting buses to
1-bit, while clean-cell siblings extract correctly.

現象 (round-11 v1.0.77 6-IC clean-room): an external-interface port table
declares bus ports with either a tilde/approx-prefixed width cell
(`~10-bit(...)`) or a signal cell carrying trailing parenthetical alias prose
after the backticked primary name (`` `o_sram_data` (or `o_sram_wdata`) ``).
Both idiom rows failed the width-bearing 4COL / DIR2 grid walker and fell
through to the `gfm_multitable_header_role_v0_3_2` fallback, which recovered
the NAME but lost the WIDTH (a third facet: that fallback's
`_v1_6_420_parse_width_cell` only accepted a pure-numeric cell, so it returned
w_int=None for ANY N-bit-format cell — even a clean `8-bit`/`1-bit`). The bus
ports therefore landed width=None (defaulted to 1-bit downstream) while the
clean-cell sibling `o_sram_we` (`1-bit`) extracted fine.

These three lines are the VERBATIM real doc lines cited in the issue
(input/docs + input_doc L3_external_interface.md):
    `o_sram_addr` | ~10-bit(...)
    `o_sram_data` (or `o_sram_wdata`) | 8-bit
    `i_sram_data` (or `i_sram_rdata`) | 8-bit

Fix (chip-AGNOSTIC, three coordinated patches in
phase1_doc_one_shot_runner.py):
  (1) WIDTH-CELL idiom — `_V1_6_423_WIDTH_CELL_PERMISSIVE` and
      `_RE_PORT_WIDTH_NBIT` tolerate an OPTIONAL leading approximation marker
      (`~`, `≈`, `approx`, `about`, `~=`) via the shared `_V1_6_731_APPROX_PFX`;
      `_parse_port_width` strips the marker before resolving the integer.
  (2) SIGNAL-CELL idiom — the 4COL / DIR2 signal-name capture
      (`_V1_6_731_SIGNAL_CELL`) anchors on the FIRST backticked identifier and
      tolerates trailing `(or `alias`)` / `(或 `alias`)` prose (the same
      grammar as `_RE_V610_ALIAS_GROUP`) up to the next column delimiter, so
      the alias is ATTACHED (consumed as prose, not promoted as a second
      top-level port) and the row stays on the width-bearing 4COL/DIR2 path.
  (3) FALLBACK width robustness — `_v1_6_420_parse_width_cell` routes a
      non-numeric cell through `_parse_port_width`, so a row that still falls
      through to the GFM multitable walker carries its `8-bit`/`1-bit`/bracket
      width instead of None.

NO-REGRESSION (§4.05, load-bearing — these RELAX a structural row-regex):
  (a) a normal `8-bit`/`10-bit` width cell WITHOUT the tilde still resolves
      exactly as before (the #664 cases stay green);
  (b) a plain `` `name` `` signal cell WITHOUT alias prose still matches the
      4COL/DIR2 walker exactly as before (the #610 alias-attach behaviour in
      the bullet walker is untouched);
  (c) symbolic / placeholder width cells (`[WIDTH-1:0]`, `*`, `-`,
      `(variable)`) still resolve to None (never a fabricated integer).

chip-AGNOSTIC: pure structural grammar (approximation marker / alias
grammar / `-bit` suffix / bracket); NO chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


def _run_l1(tmp_path: Path, extracted: dict) -> dict:
    """Drive gen_l1_datasheet and return the written L1_DATASHEET dict."""
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l1_datasheet(tmp_path, extracted)
    return json.loads(
        (tmp_path / _GEN_DIR / "L1_DATASHEET.json").read_text())


def _by_name(l1: dict) -> dict:
    return {p["name"]: p for p in l1.get("pin_table", [])}


# ── The three VERBATIM real doc lines from #731, plus a clean-cell sibling ───
# Lines 37-39 of the real L3_external_interface.md cited in the issue, used
# verbatim as the fixture per Step 2.6 doctrine.
ISSUE_731_TABLE = """## SRAM Interface

| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| `o_sram_addr` | ~10-bit(...) | output | sram address bus |
| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | sram write data |
| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input | sram read data |
| `o_sram_we` | 1-bit | output | sram write enable |
"""


def test_issue731_idiom_rows_carry_stated_width(tmp_path: Path):
    """The three idiom rows extract with their stated bus WIDTH (10/8/8),
    not None/1; the clean-cell sibling still extracts at 1."""
    l1 = _run_l1(tmp_path, {"L3_external_interface.md": ISSUE_731_TABLE})
    pins = _by_name(l1)
    for nm in ("o_sram_addr", "o_sram_data", "i_sram_data", "o_sram_we"):
        assert nm in pins, f"port {nm!r} dropped from L1.pin_table: {list(pins)}"
    # tilde/approx-prefixed width cell → concrete 10-bit bus
    assert pins["o_sram_addr"]["width"] == 10
    assert pins["o_sram_addr"]["msb"] == 9 and pins["o_sram_addr"]["lsb"] == 0
    # alias-prose signal cells → concrete 8-bit buses
    assert pins["o_sram_data"]["width"] == 8
    assert pins["o_sram_data"]["msb"] == 7 and pins["o_sram_data"]["lsb"] == 0
    assert pins["i_sram_data"]["width"] == 8
    assert pins["i_sram_data"]["msb"] == 7 and pins["i_sram_data"]["lsb"] == 0
    # clean-cell sibling still extracts at 1 (unchanged)
    assert pins["o_sram_we"]["width"] == 1


def test_issue731_alias_attached_not_promoted(tmp_path: Path):
    """The trailing `(or `alias`)` prose is ATTACHED (consumed), never
    promoted as a second top-level port."""
    l1 = _run_l1(tmp_path, {"L3_external_interface.md": ISSUE_731_TABLE})
    names = set(_by_name(l1))
    assert "o_sram_wdata" not in names, (
        f"alias o_sram_wdata promoted as a separate port: {sorted(names)}")
    assert "o_sram_rdata" not in names, (
        f"alias o_sram_rdata promoted as a separate port: {sorted(names)}")
    # And the primary names are present.
    assert {"o_sram_data", "i_sram_data"} <= names


# ── unit: the parser strips the approximation marker before resolving ────────

@pytest.mark.parametrize("cell,expect", [
    ("~10-bit", (10, 9, 0, None)),
    ("~10-bit(...)", (10, 9, 0, None)),
    ("≈10-bit", (10, 9, 0, None)),
    ("approx 10-bit", (10, 9, 0, None)),
    ("about 8-bit", (8, 7, 0, None)),
    ("~=32-bit", (32, 31, 0, None)),
    ("~10", (10, 9, 0, None)),
    ("about 16", (16, 15, 0, None)),
])
def test_issue731_parse_port_width_approx_marker(cell, expect):
    assert R._parse_port_width(cell) == expect


def test_issue731_v1_6_420_resolves_nbit_for_fallback():
    """Patch 3: the multitable-fallback width-cell parser now resolves the
    `N-bit` / `~N-bit` / bracket idioms to a concrete int (was None before)."""
    assert R._v1_6_420_parse_width_cell("8-bit")[0] == 8
    assert R._v1_6_420_parse_width_cell("1-bit")[0] == 1
    assert R._v1_6_420_parse_width_cell("~10-bit")[0] == 10
    assert R._v1_6_420_parse_width_cell("[31:0]")[0] == 32
    # symbolic / placeholder still None (preserve prior behaviour)
    assert R._v1_6_420_parse_width_cell("[WIDTH-1:0]")[0] is None
    assert R._v1_6_420_parse_width_cell("N")[0] is None
    assert R._v1_6_420_parse_width_cell("*")[0] is None


def test_issue731_gfm_borderless_fallback_carries_nbit_width():
    """A borderless GFM table (only the multitable walker catches it) now
    carries the `N-bit` width via Patch 3 — was None before."""
    doc = (
        "## Ports\n\n"
        "Name | Width | Dir | Description\n"
        "---- | ----- | --- | -----------\n"
        "data_bus | 8-bit | input | data\n"
        "ctrl | 1-bit | output | control\n"
    )
    rows = {r["name"]: r for r in R._v0_3_2_emit_pins_from_gfm_tables(doc)}
    assert rows["data_bus"]["width"] == "8"
    assert rows["ctrl"]["width"] == "1"


# ── NO-REGRESSION (§4.05) ────────────────────────────────────────────────────

CLEAN_TABLE = """## External Interface

| signal | width | direction | description |
|--------|-------|-----------|-------------|
| `data` | 8-bit | input | data bus |
| `addr` | 10-bit | input | address bus |
| `en` | 1 | input | enable |
"""


def test_issue731_clean_cells_unchanged_NOREGRESSION(tmp_path: Path):
    """A normal `8-bit`/`10-bit` width cell WITHOUT the tilde, and a plain
    `` `name` `` signal cell WITHOUT alias prose, extract exactly as before."""
    l1 = _run_l1(tmp_path, {"L3_external_interface.md": CLEAN_TABLE})
    pins = _by_name(l1)
    for nm in ("data", "addr", "en"):
        assert nm in pins, f"port {nm!r} dropped: {list(pins)}"
    assert pins["data"]["width"] == 8
    assert pins["data"]["msb"] == 7 and pins["data"]["lsb"] == 0
    assert pins["addr"]["width"] == 10
    assert pins["addr"]["msb"] == 9 and pins["addr"]["lsb"] == 0
    assert pins["en"]["width"] == 1


@pytest.mark.parametrize("cell", ["-", "*", "(variable)", "variable", "N-bit", ""])
def test_issue731_placeholders_still_none_NOREGRESSION(cell):
    """Symbolic / placeholder width cells never fabricate an integer."""
    assert R._parse_port_width(cell) == (None, None, None, None)


def test_issue731_symbolic_bracket_still_symbolic_NOREGRESSION():
    """A bracketed symbolic width stays width_symbolic (no int fabricated)."""
    assert R._parse_port_width("[WIDTH-1:0]") == (None, None, 0, "WIDTH-1:0")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
