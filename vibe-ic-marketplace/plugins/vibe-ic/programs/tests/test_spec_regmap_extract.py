#!/usr/bin/env python3
"""tests/test_spec_regmap_extract.py — spec_regmap_extract structural extractor.

Covers the three load-bearing contracts:
  (a) POSITIVE  — a real CVDP register-map table (verbatim from ttc_lite_0001)
                  extracts one item per register with correct offset / width /
                  access;
  (b) §4.05 NEGATIVE — prose that merely mentions "register" with NO table and
                  NO `0xNN` offset yields [] (no fabrication);
  (c) chip-AGNOSTIC — renaming every identifier yields the SAME item count.

Bare `import spec_regmap_extract` resolves via the tree conftest (programs/ on
sys.path).
"""
from __future__ import annotations

import spec_regmap_extract as rm


# Verbatim register-map table from cvdp_copilot_ttc_lite_0001.txt (the prompt
# the scout assigned). Header synonyms: Address / Register Name / Width /
# Access. Width cells say "32 bits"; access cells say Read / Read/Write.
_TTC_LITE_TABLE = """\
## Register Map

| Address         | Register Name       | Width  | Access  | Description                                 |
|------------------|---------------------|--------|---------|---------------------------------------------|
| `0x0`           | Count Register      | 32 bits| Read    | Current counter value (lower 16 bits).     |
| `0x1`           | Match Value Register| 32 bits| Read/Write | Counter match value (lower 16 bits).      |
| `0x2`           | Reload Value Register| 32 bits| Read/Write | Counter reload value (lower 16 bits).    |
| `0x3`           | Control Register    | 32 bits| Read/Write | Control bits: Enable, Interval Mode, Interrupt Enable. |
| `0x4`           | Status Register     | 32 bits| Read/Write | Interrupt status: 1 if interrupt is asserted, 0 otherwise. |
"""


# ---------------------------------------------------------------------------
# (a) POSITIVE — real table extracts with correct offset / width / access
# ---------------------------------------------------------------------------
def test_positive_real_register_map_table():
    items = rm.extract(_TTC_LITE_TABLE)
    regs = [i for i in items if i["kind"] == "register"]
    assert len(regs) == 5, f"expected 5 registers, got {len(regs)}"

    by_off = {i["offset"]: i for i in regs}
    assert set(by_off) == {"0x0", "0x1", "0x2", "0x3", "0x4"}

    # names parsed from the Register Name column
    assert by_off["0x0"]["name"] == "Count Register"
    assert by_off["0x4"]["name"] == "Status Register"

    # width normalised: "32 bits" -> "32"
    assert all(i["width"] == "32" for i in regs), [i["width"] for i in regs]

    # access normalised: Read -> RO, Read/Write -> RW
    assert by_off["0x0"]["access"] == "RO"
    assert by_off["0x1"]["access"] == "RW"
    assert by_off["0x4"]["access"] == "RW"

    # STRUCTURAL kind, not a prose-heuristic kind
    assert all(i["kind"] in ("register", "register_field") for i in items)

    # §4.05: evidence quotes the EXACT source table row it came from
    assert by_off["0x0"]["evidence"].startswith("| `0x0`")
    assert "Count Register" in by_off["0x0"]["evidence"]

    # drops straight into spec_coverage_check's checklist shape
    for i in items:
        assert {"kind", "requirement", "evidence"} <= set(i)
        assert i["stations"] == ["user_prompt"]


def test_positive_inline_offset_lines():
    """An inline `NAME (0xNN)` register list (the ahb_clk_counter convention,
    no markdown table) still recovers one item per register."""
    prompt = (
        "The controller exposes these memory-mapped registers:\n"
        "- `ADDR_START` (0x00): Write 1 to start the counter.\n"
        "- `ADDR_STOP` (0x04): Write 1 to stop the counter.\n"
        "- `ADDR_COUNTER` (0x08): Read the current counter value.\n"
    )
    items = rm.extract(prompt)
    assert len(items) == 3
    offs = {i["offset"] for i in items}
    assert offs == {"0x00", "0x04", "0x08"}
    assert {i["name"] for i in items} == {"ADDR_START", "ADDR_STOP", "ADDR_COUNTER"}
    # evidence is the exact source line
    start = next(i for i in items if i["name"] == "ADDR_START")
    assert "`ADDR_START` (0x00)" in start["evidence"]


def test_positive_bitfield_column_carves_fields():
    """A register table with a dedicated Bitfield column spawns one
    register_field item per bit-range token."""
    prompt = (
        "| Register Address | Name        | Bitfield                          |\n"
        "|------------------|-------------|-----------------------------------|\n"
        "| `0x20`           | Power Mgmt  | **Bit[0]**: power-down. **Bits[31:1]**: Reserved. |\n"
    )
    items = rm.extract(prompt)
    regs = [i for i in items if i["kind"] == "register"]
    fields = [i for i in items if i["kind"] == "register_field"]
    assert len(regs) == 1
    assert regs[0]["offset"] == "0x20"
    assert len(fields) == 2, [f["field_bits"] for f in fields]
    assert {f["field_bits"] for f in fields} == {"[0]", "[31:1]"}


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — prose with "register" but NO table/offset -> []
# ---------------------------------------------------------------------------
def test_negative_prose_register_no_table_returns_empty():
    prompt = (
        "Design a module that stores its configuration in an internal register.\n"
        "The register is updated every clock cycle and its value drives the\n"
        "output. There is a status register that the CPU may read. Each\n"
        "register must reset to a known state. No table or address map is\n"
        "given here — only prose mentioning the word register many times.\n"
    )
    assert rm.extract(prompt) == []


def test_negative_register_table_without_offset_column_returns_empty():
    """A `Register Name | Functionality` summary table (the ic_0017
    convention) has NO offset/address column, so it is NOT an addressed
    register map — §4.05 demands the offset anchor, so it must extract nothing.
    """
    prompt = (
        "### Register Summary Table\n\n"
        "| **Register Name**    | **Functionality**                         |\n"
        "|----------------------|-------------------------------------------|\n"
        "| `pending_interrupts` | Holds the currently pending interrupts.   |\n"
        "| `wait_counters`      | Tracks the wait time for each interrupt.  |\n"
    )
    assert rm.extract(prompt) == []


def test_negative_offset_inside_code_fence_is_not_a_register():
    """A `0xNN` inside a ```-fenced code/diagram block (e.g. a mermaid graph or
    Verilog listing) is NOT a register offset and must not leak in."""
    prompt = (
        "The linked-list structure looks like:\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  A1[index=1, addr=0x44, next_idx=3] --> B1[index=3, addr=0x44]\n"
        "```\n\n"
        "No register map is defined in this prompt.\n"
    )
    assert rm.extract(prompt) == []


def test_negative_empty_and_garbage_inputs():
    assert rm.extract("") == []
    assert rm.extract(None) == []  # type: ignore[arg-type]
    assert rm.extract("just a sentence with no structure at all") == []


# ---------------------------------------------------------------------------
# (c) chip-AGNOSTIC — rename all identifiers -> same item count
# ---------------------------------------------------------------------------
def test_chip_agnostic_rename_preserves_item_count():
    base = rm.extract(_TTC_LITE_TABLE)
    assert len(base) == 5

    # Rename every register/identifier token; structure is untouched.
    renamed = _TTC_LITE_TABLE
    for old, new in [
        ("Count Register", "Foo Reg Alpha"),
        ("Match Value Register", "Bar Reg Beta"),
        ("Reload Value Register", "Baz Reg Gamma"),
        ("Control Register", "Qux Reg Delta"),
        ("Status Register", "Zap Reg Epsilon"),
        ("Register Map", "Programming Model"),
    ]:
        renamed = renamed.replace(old, new)

    out = rm.extract(renamed)
    assert len(out) == len(base), (len(out), len(base))
    # same offsets recovered (the structural anchors don't move)
    assert {i["offset"] for i in out} == {i["offset"] for i in base}
    # widths/access unchanged by renaming the names
    assert sorted(i["access"] for i in out) == sorted(i["access"] for i in base)


def test_chip_agnostic_offset_relabel_preserves_count():
    """Relabelling offsets (different address base) keeps the same count — the
    extractor keys on the `0xNN` SHAPE, not on specific address literals."""
    relabel = _TTC_LITE_TABLE
    for old, new in [("0x0", "0x100"), ("0x1", "0x104"),
                     ("0x2", "0x108"), ("0x3", "0x10C"), ("0x4", "0x110")]:
        relabel = relabel.replace(f"`{old}`", f"`{new}`")
    out = rm.extract(relabel)
    assert len([i for i in out if i["kind"] == "register"]) == 5


def test_module_exposes_extract_and_cli():
    assert callable(rm.extract)
    assert callable(rm.main)
