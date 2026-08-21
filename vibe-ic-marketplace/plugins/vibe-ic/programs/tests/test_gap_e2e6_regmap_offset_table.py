"""GAP-E2E-6 — register-SUMMARY offset table walker.

The #736 Name-column walker (`_v1_0_80_parse_namecol_bitfield_table`) parses
per-register BIT-FIELD tables (`| Bits | Type | Reset | Name |`) but NEVER the
register-map SUMMARY table (`| Name | Offset | Length |`), so on a doc such as
OpenTitan's `aes_registers.md` every L4 register entry lost its `offset`. This
adds `_gap_e2e6_parse_register_offset_table` (a pure header-token + hex/int
walker) plus a post-collapse application step that inherits each register's
offset (exact-name) or a multireg family's base_offset + per-index offsets +
stride (`PREFIX_<i>` rows).

§4.05 NO-LEAK is load-bearing here because the extractor is ADDITIVE: the risk
is FALSE inheritance. The tests below prove an offset is applied ONLY to a
name-matched register — a register absent from the offset table keeps its
offset absent (no fabrication), a non-offset / bit-field table yields `{}` and
changes nothing, and a bare-name mismatch never inherits a neighbour's offset.
chip-AGNOSTIC: NO chip / vendor / SKU literal anywhere.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as R   # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


# An aes-style register-summary table: an `<ip>.`-prefixed, markdown-link
# Name cell, an Offset column, and a Length column. chip-AGNOSTIC fixture.
_SUMMARY_TABLE = """
## Summary

| Name                              | Offset   |   Length | Description         |
|:----------------------------------|:---------|---------:|:--------------------|
| aes.[`ALERT_TEST`](#alert_test)   | 0x0      |        4 | Alert Test Register |
| aes.[`KEY_SHARE0_0`](#key_share0) | 0x4      |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_1`](#key_share0) | 0x8      |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_2`](#key_share0) | 0xc      |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_3`](#key_share0) | 0x10     |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_4`](#key_share0) | 0x14     |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_5`](#key_share0) | 0x18     |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_6`](#key_share0) | 0x1c     |        4 | Initial Key Share 0 |
| aes.[`KEY_SHARE0_7`](#key_share0) | 0x20     |        4 | Initial Key Share 0 |
| aes.[`CTRL_SHADOWED`](#ctrl)      | 0x74     |        4 | Control Register    |
| aes.[`CTRL_AUX_SHADOWED`](#aux)   | 0x78     |        4 | Aux Control         |
| aes.[`CTRL_AUX_REGWEN`](#regwen)  | 0x7c     |        4 | Aux lock bit        |
| aes.[`TRIGGER`](#trigger)         | 0x80     |        4 | Trigger Register    |
| aes.[`STATUS`](#status)           | 0x84     |        4 | Status Register     |
| aes.[`CTRL_GCM_SHADOWED`](#gcm)   | 0x88     |        4 | GCM Control         |
"""

# A #736 BIT-FIELD table (Bits column, NO Offset column). Must yield {}.
_BITFIELD_TABLE = """
### Fields

|  Bits  |  Type  |  Reset  | Name       | Description         |
|:------:|:------:|:-------:|:-----------|:--------------------|
|  31:0  |   wo   |   0x0   | key_share0 | Initial Key Share 0 |
"""

# A summary table WITH an access column (the aes doc has none; synth here).
_TABLE_WITH_ACCESS = """
| Name        | Offset | Access | Description |
|:------------|:-------|:-------|:------------|
| `CFG`       | 0x10   | RW     | Config      |
| `IRQ_STATE` | 0x14   | RO     | IRQ state   |
"""


# ---------------------------------------------------------------------------
# POSITIVE — the walker parses the summary table.
# ---------------------------------------------------------------------------

def test_positive_scalar_and_multireg_offsets_parsed():
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    # bare register name (aes. prefix + markdown-link + backticks stripped)
    assert tbl["ALERT_TEST"]["offset"] == "0x0"
    assert tbl["ALERT_TEST"]["length"] == 4
    # multireg per-index rows KEY_SHARE0_0..7 at 0x4,0x8,...,0x20
    expected = {i: hex(0x4 + 4 * i) for i in range(8)}
    for i in range(8):
        assert tbl[f"KEY_SHARE0_{i}"]["offset"] == expected[i]
    # scalars at their offsets
    assert tbl["CTRL_SHADOWED"]["offset"] == "0x74"
    assert tbl["CTRL_AUX_SHADOWED"]["offset"] == "0x78"
    assert tbl["CTRL_AUX_REGWEN"]["offset"] == "0x7c"
    assert tbl["TRIGGER"]["offset"] == "0x80"
    assert tbl["STATUS"]["offset"] == "0x84"
    assert tbl["CTRL_GCM_SHADOWED"]["offset"] == "0x88"


def test_positive_apply_scalar_offset_onto_entry():
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    regs = [{"name": "ALERT_TEST"}, {"name": "STATUS"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 2
    assert regs[0]["offset"] == "0x0"
    assert regs[0]["length"] == 4
    # address / address_int back-filled from the matched row
    assert regs[0]["address"] == "0x0"
    assert regs[0]["address_int"] == 0
    assert regs[1]["offset"] == "0x84"
    assert regs[1]["address_int"] == 0x84


def test_positive_hex_normalisation_lowercase():
    tbl = R._gap_e2e6_parse_register_offset_table(
        "| Name | Offset |\n|:--|:--|\n| `FOO` | 0X1A |\n")
    assert tbl["FOO"]["offset"] == "0x1a"


def test_positive_decimal_offset_normalised_to_hex():
    tbl = R._gap_e2e6_parse_register_offset_table(
        "| Name | Offset |\n|:--|:--|\n| `BAR` | 16 |\n")
    assert tbl["BAR"]["offset"] == "0x10"


def test_positive_access_column_carried_through():
    tbl = R._gap_e2e6_parse_register_offset_table(_TABLE_WITH_ACCESS)
    assert tbl["CFG"]["access"] == "RW"
    assert tbl["IRQ_STATE"]["access"] == "RO"
    # entry lacking an access inherits it; an entry that already has one keeps it
    regs = [{"name": "CFG"}, {"name": "IRQ_STATE", "access": "W1C"}]
    R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert regs[0]["access"] == "RW"
    assert regs[1]["access"] == "W1C"   # not overwritten


# ---------------------------------------------------------------------------
# MULTIREG — collapsed family carries base_offset 0x4 + stride 4.
# ---------------------------------------------------------------------------

def test_multireg_family_base_offset_and_stride():
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    # a single collapsed family entry named KEY_SHARE0 (as the #736 harvest
    # emits from one `## KEY_SHARE0` heading)
    regs = [{"name": "KEY_SHARE0"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 1
    fam = regs[0]
    assert fam["offset"] == "0x4"
    assert fam["base_offset"] == "0x4"
    assert fam["base_addr"] == "0x4"
    assert fam["stride_bytes"] == 4
    assert fam["array_size"] == 8
    # per-index offsets preserved
    idx_to_off = {e["index"]: e["offset"] for e in fam["element_offsets"]}
    assert idx_to_off[0] == "0x4"
    assert idx_to_off[7] == "0x20"


def test_multireg_does_not_overwrite_existing_base():
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    regs = [{"name": "KEY_SHARE0", "offset": "0xDEAD", "stride_bytes": 99}]
    R._gap_e2e6_apply_register_offsets(regs, tbl)
    # existing offset/stride are not clobbered
    assert regs[0]["offset"] == "0xDEAD"
    assert regs[0]["stride_bytes"] == 99
    # but per-index offsets are still recorded additively
    assert len(regs[0]["element_offsets"]) == 8


# ---------------------------------------------------------------------------
# NEGATIVE / §4.05 NO-LEAK.
# ---------------------------------------------------------------------------

def test_noleak_absent_register_keeps_offset_absent():
    """A register named in the doc's FIELD tables but ABSENT from the offset
    table must not gain a fabricated offset."""
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    regs = [{"name": "SOME_OTHER_REG"}, {"name": "ALERT_TEST"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 1                       # only ALERT_TEST matched
    assert "offset" not in regs[0]            # no fabrication
    assert regs[1]["offset"] == "0x0"


def test_noleak_bitfield_table_yields_empty():
    """A `| Bits | Type | Reset | Name |` bit-field table is NOT a register-
    summary table (Bits column present, no Offset column) → {} and no apply."""
    tbl = R._gap_e2e6_parse_register_offset_table(_BITFIELD_TABLE)
    assert tbl == {}
    regs = [{"name": "key_share0"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 0
    assert "offset" not in regs[0]


def test_noleak_non_offset_table_yields_empty():
    """A table with a Name column but NO Offset/Address column yields {}."""
    doc = ("| Name | Description |\n|:--|:--|\n"
           "| FOO | some prose |\n| BAR | more prose |\n")
    assert R._gap_e2e6_parse_register_offset_table(doc) == {}


def test_noleak_barename_mismatch_no_neighbor_inherit():
    """A register whose bare name does not match any row must not inherit a
    neighbouring row's offset."""
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    # STATUS_TYPO is neither an exact match nor a `PREFIX_<i>` family of any row
    regs = [{"name": "STATUS_TYPO"}, {"name": "KEY_SHARE9"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 0
    assert "offset" not in regs[0]
    assert "offset" not in regs[1]


def test_noleak_family_prefix_boundary_is_underscore():
    """`KEY_SHARE0_*` rows must NOT be captured by a register named
    `KEY_SHARE` (the `_` boundary protects against prefix bleed)."""
    tbl = R._gap_e2e6_parse_register_offset_table(_SUMMARY_TABLE)
    regs = [{"name": "KEY_SHARE"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, tbl)
    assert applied == 0
    assert "offset" not in regs[0]


def test_noleak_empty_map_changes_nothing():
    regs = [{"name": "ALERT_TEST", "access": "WO"}]
    applied = R._gap_e2e6_apply_register_offsets(regs, {})
    assert applied == 0
    assert "offset" not in regs[0]


def test_noleak_non_hex_offset_cell_skipped():
    """A row whose Offset cell is not a hex/int literal is skipped (never
    fabricated)."""
    doc = ("| Name | Offset |\n|:--|:--|\n"
           "| `GOOD` | 0x8 |\n| `BAD` | TBD |\n")
    tbl = R._gap_e2e6_parse_register_offset_table(doc)
    assert tbl["GOOD"]["offset"] == "0x8"
    assert "BAD" not in tbl


# ---------------------------------------------------------------------------
# REAL-ARTIFACT smoke (skipped if the reference doc is absent).
# ---------------------------------------------------------------------------

def test_real_artifact_offsets_populate():
    doc = require_corpus("opentitan_aes_e2e_v1263/phase1/input_doc/aes_registers.txt")
    if not doc.exists():
        return  # reference artifact not present in this checkout
    tbl = R._gap_e2e6_parse_register_offset_table(doc.read_text())
    assert tbl["ALERT_TEST"]["offset"] == "0x0"
    assert tbl["KEY_SHARE0_0"]["offset"] == "0x4"
    for off in ("0x74", "0x78", "0x7c", "0x80", "0x84", "0x88"):
        assert any(v["offset"] == off for v in tbl.values())
