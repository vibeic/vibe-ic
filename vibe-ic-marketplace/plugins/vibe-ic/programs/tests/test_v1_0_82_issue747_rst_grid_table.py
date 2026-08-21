"""ORGANIC #747 [P2] — the regmap/token extractor missed reStructuredText GRID
tables. #616 added a GFM `|`-pipe table parser, but it RESETS its column map on
EVERY non-pipe line — so the rst grid `+---+`/`+===+` border lines (which
separate every rst row) aborted the table before any data row was read, and
multi-word headers like `CSR Address` were not in the keyword sets. Per-row
CSR/memory-map hex constants inside rst grid tables were dropped → P0
completeness FAILs on rst-input docs (33 tokens missing across 4 docs;
perf-counters 38.6%).

POSITIVE: an rst GRID CSR table now yields register rows (name + addr_hex),
treating the plus-dash / plus-equals border lines as IN-TABLE separators.

NEGATIVE no-leak: a doc with NO grid table is UNCHANGED, the existing GFM pipe
table STILL parses (and is not double-counted), and an rst grid WITHOUT a
name+offset header does NOT spuriously emit rows.

chip-AGNOSTIC: pure rst grid-table grammar; no chip/register-name vocabulary.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import regmap_table_extractor as R  # noqa: E402


# A minimal rst GRID table: `+---+` cell borders + a `+===+` header
# separator + `| cell |` rows. The header uses the multi-word `CSR Address`
# key that #616's single-word keyword set never matched.
_RST_GRID = """Performance Counter CSRs
========================

+-------------+-------------+----------------------+
| CSR Address | Name        | Description          |
+=============+=============+======================+
| 0xB04       | minstret    | Instructions retired |
+-------------+-------------+----------------------+
| 0xB8C       | mhpmcounter | HW perf counter      |
+-------------+-------------+----------------------+
"""

# existing GFM pipe table (#616) — must keep working, no border lines.
_GFM = """# AES registers

| Name                          | Offset | Length | Description          |
|-------------------------------|--------|--------|----------------------|
| [`ALERT_TEST`](#alert_test)   | 0x0    | 4      | Alert Test Register  |
| [`KEY_SHARE0_0`](#k)          | 0x14   | 4      | Initial Key Share 0  |
"""

# an rst grid table that is NOT a register table (no name+offset header).
_RST_NO_HDR = """+------+------+
| Foo  | Bar  |
+======+======+
| x    | y    |
+------+------+
"""


def test_rst_grid_csr_table_extracted(tmp_path):
    p = tmp_path / "perf-counters.rst"
    p.write_text(_RST_GRID)
    rows = R.extract_regmap_table(p.read_text(), str(p))
    by_name = {r["name"]: r for r in rows}
    assert "minstret" in by_name, (
        f"rst GRID CSR row not extracted (pre-fix: 0 rows); got {sorted(by_name)}")
    assert by_name["minstret"]["addr_hex"] == "0xb04"
    assert by_name["mhpmcounter"]["addr_hex"] == "0xb8c"
    for r in rows:
        assert r["evidence"]["extraction_strategy"] == "rst_grid_table_match"


def test_rst_grid_multiword_base_address_header(tmp_path):
    # the `Base Address` / `Register Name` multi-word headers from the issue.
    txt = (
        "+--------------+----------------+\n"
        "| Base Address | Register Name  |\n"
        "+==============+================+\n"
        "| 0x1A110000   | dma_base       |\n"
        "+--------------+----------------+\n"
        "| 0x324        | status         |\n"
        "+--------------+----------------+\n"
    )
    rows = R.extract_regmap_table(txt, "dma.rst")
    by_name = {r["name"]: r["addr_hex"] for r in rows}
    assert by_name == {"dma_base": "0x1a110000", "status": "0x324"}


def test_existing_gfm_pipe_table_still_parses_no_dup(tmp_path):
    # NO-LEAK regression: the #616 GFM path still extracts, and the rst-grid
    # branch does NOT double-count it (a GFM doc has no `+---+` borders).
    rows = R.extract_regmap_table(_GFM, "aes_registers.md")
    names = {r["name"] for r in rows}
    assert names == {"ALERT_TEST", "KEY_SHARE0_0"}, (
        f"GFM pipe-table path regressed: {names}")
    strategies = {r["evidence"]["extraction_strategy"] for r in rows}
    assert strategies == {"gfm_pipe_table_match"}, (
        f"unexpected strategy / double-count: {strategies}")
    # the rst branch alone must emit nothing on a GFM doc.
    assert R._extract_rst_grid_table(_GFM, "aes_registers.md") == []


def test_no_grid_table_doc_unchanged():
    # NO-LEAK: a doc with NO grid table is UNCHANGED (no spurious rows).
    plain = "Just some prose about a chip.\nNo tables here.\n"
    assert R.extract_regmap_table(plain, "p.txt") == []
    # the existing column-whitespace form (#40 Bug 1B) still extracts.
    cols = "0x00          r       name0\n0x10          r/w     ctrl\n"
    assert {r["name"] for r in R.extract_regmap_table(cols, "x.txt")} == {
        "name0", "ctrl"}


def test_rst_grid_without_name_offset_header_emits_nothing():
    # NO-LEAK: an rst grid that is NOT a register table (no name+offset
    # header) must not be mistaken for one.
    assert R.extract_regmap_table(_RST_NO_HDR, "misc.rst") == []


def test_stray_border_abutting_gfm_table_no_double_count():
    """adversarial-review MEDIUM: a stray `+---+` border directly above a GFM
    pipe table must NOT cause the rst branch to re-emit the GFM rows."""
    doc = ("+-----+\n"
           "| Name   | Offset |\n"
           "|--------|--------|\n"
           "| reg_y  | 0x44   |\n")
    rows = R.extract_regmap_table(doc, "p.md")
    assert len(rows) == 1, [(r["name"], r["evidence"]["extraction_strategy"]) for r in rows]
    assert rows[0]["name"] == "reg_y"
    assert rows[0]["evidence"]["extraction_strategy"] == "gfm_pipe_table_match"
