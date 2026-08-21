"""Step-2.7 §4.05 guard for the gapK weak-offset port (PR #1).

The PR ported the rst-grid weak-offset HEX guard onto the GFM primary path of
`regmap_table_extractor._extract_gfm_pipe_table`. The original port set the
`offset_weak` flag GLOBALLY — whenever ANY weak-vocabulary header
(`default`/`reset value`/`value`) appeared — decoupled from the column that
actually claimed the `offset` role. So a perfectly legitimate, extremely common
register table that pairs a STRONG `Offset` column with a `Reset Value` column
had its strong decimal offsets gated to HEX-only and extracted ZERO registers
(reproduced by Step-2.7 against origin/main, which extracts all rows).

FIX: bind `offset_weak` to the column that actually CLAIMS the offset role; a
later STRONG `Offset`/`Address` column supersedes an earlier WEAK claim
(strong-preferred). This file PINS:
  - the §4.05 no-false-block case (strong Offset + Reset Value → all rows), and
  - the original FP-fix it must NOT regress (weak-only Value table → no phantom
    registers; a genuine 0x in a weak column still extracts).

chip-AGNOSTIC: pure GFM-table column-role logic.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import regmap_table_extractor as R  # noqa: E402


def _rows(doc):
    return [(r.get("addr_hex"), r.get("name"))
            for r in R.extract_regmap_table(doc, "regs.md")]


_STRONG_OFFSET_WEAK_SIBLING = (
    "| Register | Offset | Reset Value | Description |\n"
    "|----------|--------|-------------|-------------|\n"
    "| CTRL   | 0 | 0x00000000 | Control |\n"
    "| STATUS | 4 | 0x00000001 | Status  |\n"
    "| DATA   | 8 | 0x00000000 | Data    |\n"
)


def test_strong_offset_with_reset_value_sibling_extracts_all_rows():
    # §4.05 NO-FALSE-BLOCK: the strong `Offset` column stays decimal-tolerant
    # even though a weak `Reset Value` column co-exists. (This is the exact
    # Step-2.7 HIGH reproduction — was [] before the fix.)
    assert _rows(_STRONG_OFFSET_WEAK_SIBLING) == [
        ("0x0", "CTRL"), ("0x4", "STATUS"), ("0x8", "DATA")]


@pytest.mark.parametrize("hdr_extra", ["Reset Value", "Default", "Value"])
def test_strong_offset_immune_to_any_weak_sibling(hdr_extra):
    doc = (f"| Register | Offset | {hdr_extra} | Description |\n"
           "|---|---|---|---|\n"
           "| A | 0  | 0x1 | x |\n"
           "| B | 16 | 0x2 | y |\n")
    assert _rows(doc) == [("0x0", "A"), ("0x10", "B")]


def test_weak_only_value_table_still_no_phantom_registers():
    # FP-fix PRESERVED: a `| Field | Value |` spec table with bare decimals in
    # the Value prose must NOT fabricate phantom registers.
    weak = "| Field | Value |\n|-------|-------|\n| GAIN | 5 |\n| MODE | 12 |\n"
    assert _rows(weak) == []


def test_weak_value_only_table_yields_nothing_even_for_a_genuine_hex():
    """REVERSED by #512 (was `test_weak_value_with_genuine_hex_still_extracts`,
    which asserted `[("0x40", "BASE")]`).

    gapK stopped a `| Field | Value |` spec table from promoting a BARE DECIMAL
    to an address but still let a hex one through, and this assertion pinned
    that residue. #512 measured what the residue actually produces: on a real
    corpus doc it turned seven enumerated one-hot FIELD VALUES into registers
    (`AES_ECB @ 0x01`, `AES_NONE @ 0x3f`, …) and welded three more onto real
    registers as `also_named`. A `Value` header states what a thing is SET TO,
    not where it LIVES; the hex under it is a constant whichever base it is
    written in. A table whose ONLY address role is such a column yields no
    registers — and says so (see the disclosure assertion below).

    The gapK POSITIVE case this file exists for is untouched: a STRONG `Offset`
    column beside a weak sibling still extracts every row (tests above).
    """
    weak = "| Field | Value |\n|-------|-------|\n| BASE | 0x40 |\n"
    assert _rows(weak) == []
    disc = []
    R.extract_regmap_table(weak, "regs.md", disclosures=disc)
    assert [d["reason"] for d in disc] == [
        R.NOT_REGISTERS_VALUE_COLUMN_ONLY], disc
    assert disc[0]["addresses_read_and_dropped"] == ["0x40"], disc


def test_weak_before_strong_offset_strong_wins():
    # strong-preferred: a STRONG Offset column appearing AFTER a weak Value
    # column supersedes the weak claim and stays decimal-tolerant.
    wbs = ("| Field | Value | Offset |\n|---|---|---|\n"
           "| A | foo | 0 |\n| B | bar | 4 |\n")
    assert _rows(wbs) == [("0x0", "A"), ("0x4", "B")]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
