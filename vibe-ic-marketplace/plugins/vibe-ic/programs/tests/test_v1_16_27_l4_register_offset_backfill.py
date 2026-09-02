"""A register-summary table that lists every element, and an L4 that addressed
none of them.

Measured on opentitan_aes: `aes_registers.md` opens with a 35-row summary table
naming `KEY_SHARE0_0 0x4` ... `DATA_OUT_3 0x70` ... `STATUS 0x84`, one row per
element, and the shipped L4 carried `address: null` on 23 of them — every array
element. Anything that has to ADDRESS a register works from nothing.

BACKFILL, never a stride guess. Bidirectional: a register the table names gets
its stated offset; a register the table does not name keeps `address: null`,
which is the fail-closed answer a bus driver has to be able to refuse on.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

# One row per element, exactly the shape a Comportable register document uses.
LISTED = """# widget registers

## Summary

| Name                              | Offset   |   Length | Description        |
|:----------------------------------|:---------|---------:|:-------------------|
| widget.[`DATA_IN_0`](#data_in)    | 0x54     |        4 | Input Data.        |
| widget.[`DATA_IN_1`](#data_in)    | 0x58     |        4 | Input Data.        |
| widget.[`STATUS`](#status)        | 0x84     |        4 | Status Register    |
"""

# A table that names only the array BASE. The elements must stay unaddressed.
BASE_ONLY = """# widget registers

## Summary

| Name                          | Offset   |   Length | Description   |
|:------------------------------|:---------|---------:|:--------------|
| widget.[`DATA_IN`](#data_in)  | 0x54     |        4 | Input Data.   |
"""


def test_the_stated_offsets_are_filled():
    """The load-bearing red, at the unit the pass is built on."""
    import phase1_doc_one_shot_runner as R
    table = R._g19_summary_table_offsets({"regs.txt": LISTED})
    assert table == {"DATA_IN_0": "0x54", "DATA_IN_1": "0x58",
                     "STATUS": "0x84"}, table
    regs = [{"name": "DATA_IN_0", "address": None},
            {"name": "DATA_IN_1", "address": None},
            {"name": "STATUS", "address": "0x84"}]
    filled = R._g19_backfill_register_offsets(regs, {"regs.txt": LISTED})
    assert filled == 2, filled
    assert regs[1]["address"] == "0x58"
    assert regs[1]["address_int"] == 0x58
    assert regs[1]["address_source"] == "register_summary_table_backfill_g19"
    # An address already present is never rewritten.
    assert regs[2].get("address_source") is None


def test_an_unlisted_register_keeps_no_address():
    """Over-reach control, and it must pass on BOTH trees: no stride guess.
    `DATA_IN_1` is one word after a base the table DOES state, which is exactly
    the inference a driver must not be handed silently."""
    import phase1_doc_one_shot_runner as R
    regs = [{"name": "DATA_IN_0", "address": None},
            {"name": "DATA_IN_1", "address": None}]
    filled = R._g19_backfill_register_offsets(regs, {"regs.txt": BASE_ONLY})
    assert filled == 0, filled
    assert regs[0]["address"] is None and regs[1]["address"] is None


def test_end_to_end_the_shipped_l4_carries_the_offsets(tmp_path):
    """Behavioural, through the real Phase-1 runner: the pass must run LAST,
    because the array elements are appended after the L4 emitter returns."""
    proj = tmp_path / "proj"
    d = proj / "input" / "docs"
    d.mkdir(parents=True)
    (d / "widget_registers.md").write_text(LISTED)
    (proj / "input" / "phase1_prompt.md").write_text(
        "Build a widget peripheral with a register-mapped interface.\n")
    subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(proj), "--ic-name", "widget"],
        capture_output=True, text=True, timeout=1800)
    l4 = json.loads((proj / "phase1" / "generated_docs"
                     / "L4_REGMAP.json").read_text())
    census = l4.get("register_offset_backfill_g19")
    assert census is not None, sorted(l4)
    assert census["summary_table_rows"] == 3, census
    assert census["still_without_address"] == [], census
    by_name = {r.get("name"): r for r in l4.get("registers") or []}
    for name, addr in (("DATA_IN_0", "0x54"), ("DATA_IN_1", "0x58"),
                       ("STATUS", "0x84")):
        assert by_name.get(name), sorted(by_name)
        assert by_name[name].get("address") == addr, by_name[name]
