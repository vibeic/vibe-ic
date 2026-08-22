"""ORGANIC #616 [HIGH] — the regmap table extractor missed pipe-delimited GFM
register summary tables (Name-first column order). Both row regexes anchored on
a LEADING 0x address, so an auto-generated `*_registers.md` with
`| Name | Offset | Length | Description |` rows produced ZERO rows → L4 had
register_map_present=True but registers=[] (a 40+ register map silently dropped).

POSITIVE: a Name-first GFM table now yields register rows (name + addr_hex),
stripping markdown-link / backtick name syntax.

NEGATIVE no-leak: the existing column-whitespace + dash forms still extract;
a pipe table WITHOUT a name+offset header does NOT spuriously emit rows.

chip-AGNOSTIC: pure GFM grammar; no chip/register-name vocabulary.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import regmap_table_extractor as R  # noqa: E402

_GFM = """# AES registers

| Name                          | Offset | Length | Description          |
|-------------------------------|--------|--------|----------------------|
| [`ALERT_TEST`](#alert_test)   | 0x0    | 4      | Alert Test Register  |
| crypto.[`CTRL_SHADOWED`](#c)  | 0x10   | 4      | Control (shadowed)   |
| [`KEY_SHARE0_0`](#k)          | 0x14   | 4      | Initial Key Share 0  |
"""

# existing column-whitespace form (#40 Bug 1B) — must keep working
_COLS = "0x00          r       name0\n0x10          r/w     ctrl\n"

# a pipe table that is NOT a register table (no name+offset header)
_NO_HDR = "| Foo | Bar |\n|-----|-----|\n| `x` | y |\n"


def test_gfm_pipe_table_name_first_extracted():
    rows = R.extract_regmap_table(_GFM, "input/docs/aes_registers.md")
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"ALERT_TEST", "CTRL_SHADOWED", "KEY_SHARE0_0"}, (
        f"expected the 3 GFM register rows, got {sorted(by_name)}")
    assert by_name["ALERT_TEST"]["addr_hex"] == "0x0"
    assert by_name["CTRL_SHADOWED"]["addr_hex"] == "0x10"  # prose prefix stripped, link name won
    assert by_name["KEY_SHARE0_0"]["addr_hex"] == "0x14"
    for r in rows:
        assert r["evidence"]["extraction_strategy"] == "gfm_pipe_table_match"


def test_existing_column_form_still_extracts():
    rows = R.extract_regmap_table(_COLS, "x.txt")
    names = {r["name"] for r in rows}
    assert names == {"name0", "ctrl"}, f"column-whitespace form regressed: {names}"


def test_pipe_table_without_register_header_emits_nothing():
    # NO-LEAK: a generic 2-col pipe table (no name+offset header) must not
    # be mistaken for a register table.
    assert R.extract_regmap_table(_NO_HDR, "misc.md") == []


def test_gfm_header_with_name_but_no_offset_emits_nothing():
    txt = "| Name | Width |\n|------|-------|\n| `CFG` | 32 |\n"
    assert R.extract_regmap_table(txt, "x.md") == []
