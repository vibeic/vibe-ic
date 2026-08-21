"""#593 — the register summary table contributed nothing, and no register had fields.

Two defects, one upstream of the other, both found by running the extractor on
the shipped OpenTitan AES register document rather than by reading the issue.

1. THE SUMMARY TABLE'S NAME CELL. A register-tool summary writes

       | aes.[`CTRL_SHADOWED`](#ctrl_shadowed) | 0x74 | 4 | Control Register. |

   and the identifier match rejected the WHOLE cell, so that table contributed
   nothing at all. The 28 registers that did come out were read from a different
   table elsewhere in the document — and the ones the summary uniquely carries
   are exactly the ones with FIELDS: `CTRL_SHADOWED`, `CTRL_AUX_SHADOWED`,
   `CTRL_GCM_SHADOWED`, `TRIGGER`, `STATUS`.

   The issue reports L4 as having zero registers. That is a STALE artefact: the
   extractor did return 28 on this document before the fix. What it could not
   return was these seven.

2. NO `fields[]`. The fields are already MACHINE-READABLE — the register tool
   writes them as a `wavejson` diagram whose `reg` array is JSON, LSB first.
   An unnamed entry is reserved padding: not emitted, but its width still
   advances the bit position, because dropping it shifts every field above it.

MEASURED, before -> after, on the shipped document:

    registers        28 -> 35
    with fields[]     0 -> 7
    fields total      0 -> 24

and the 24 include every field behind the 12 tokens #593 lists as uncaptured:
`CTRL_SHADOWED.{OPERATION,MODE,KEY_LEN,MANUAL_OPERATION}`,
`TRIGGER.{KEY_IV_DATA_IN_CLEAR,DATA_OUT_CLEAR}`,
`STATUS.{OUTPUT_VALID,INPUT_READY}`.

CORPUS SWEEP, 390 tracked input docs: **0 register names lost** — the change is
additive — 21 gained, 72 fields emitted, 387 docs unchanged.

A SLICING BUG OF MY OWN, recorded because it produced a confident zero: the
per-register section was first cut at the NEXT HEADING OF ANY DEPTH, and the
wavejson diagram lives in a `### Fields` SUBSECTION — so every slice ended just
before the only thing worth reading and the ingester emitted nothing while
being entirely correct.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "phase1_port_extract", _PROGRAMS / "phase1_port_extract.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase1_port_extract"] = mod
    spec.loader.exec_module(mod)
    return mod


PE = _load()

_SUMMARY = """| Name                                  | Offset | Length | Description |
|:--------------------------------------|:-------|-------:|:------------|
| aes.[`CTRL_SHADOWED`](#ctrl_shadowed) | 0x74   |      4 | Control.    |
| aes.[`TRIGGER`](#trigger)             | 0x80   |      4 | Trigger.    |
"""

_WITH_FIELDS = _SUMMARY + """
## CTRL_SHADOWED
Control Register.
- Offset: `0x74`

### Fields

```wavejson
{"reg": [{"name": "OPERATION", "bits": 2, "attr": ["rw"]},
         {"name": "MODE", "bits": 6, "attr": ["rw"]},
         {"bits": 24}], "config": {"lanes": 1}}
```

### Instances
nothing here
"""


# ── the name cell ───────────────────────────────────────────────────────────
def test_a_linked_and_block_qualified_name_is_read():
    assert PE._regmap_name_cell("aes.[`CTRL_SHADOWED`](#ctrl_shadowed)") \
        == "CTRL_SHADOWED"


def test_a_plain_name_is_unchanged():
    assert PE._regmap_name_cell("STATUS") == "STATUS"
    assert PE._regmap_name_cell("`STATUS`") == "STATUS"


def test_a_cell_that_is_not_a_name_is_still_rejected():
    """LOAD-BEARING. The normaliser must not turn prose into a register."""
    got = PE.extract_regmap(
        "| Name | Offset |\n|:--|:--|\n| see the table below | 0x4 |\n")
    assert got == [], got


def test_the_summary_table_registers_are_extracted():
    got = {r["name"] for r in PE.extract_regmap(_SUMMARY)}
    assert got == {"CTRL_SHADOWED", "TRIGGER"}, got


# ── the fields ──────────────────────────────────────────────────────────────
def test_wavejson_fields_are_lifted_with_bit_positions():
    got = PE.extract_register_fields(_WITH_FIELDS)
    assert got == [
        {"name": "OPERATION", "lsb": 0, "width": 2, "msb": 1, "access": "rw"},
        {"name": "MODE", "lsb": 2, "width": 6, "msb": 7, "access": "rw"},
    ], got


def test_reserved_padding_advances_the_position_without_becoming_a_field():
    """Dropping an unnamed entry instead of counting it shifts every field
    above it — a wrong bit position is worse than no field."""
    t = ('```wavejson\n{"reg": [{"bits": 4}, {"name": "F", "bits": 2}]}\n```')
    assert PE.extract_register_fields(t) == [
        {"name": "F", "lsb": 4, "width": 2, "msb": 5}]


def test_an_unparseable_fence_yields_no_fields_rather_than_a_guess():
    assert PE.extract_register_fields('```wavejson\n{not json\n```') == []
    assert PE.extract_register_fields('```wavejson\n{"reg": "nope"}\n```') == []
    assert PE.extract_register_fields("no fence here") == []


def test_the_fields_reach_the_register_record():
    regs = {r["name"]: r for r in PE.extract_regmap(_WITH_FIELDS)}
    assert [f["name"] for f in regs["CTRL_SHADOWED"]["fields"]] \
        == ["OPERATION", "MODE"]
    assert "fields" not in regs["TRIGGER"], (
        "a register with no diagram must not get an empty fields[]")


def test_the_section_slice_survives_a_subsection():
    """The bug that produced a confident zero: the diagram lives under
    `### Fields`, and slicing at the next heading of ANY depth cut it off."""
    regs = {r["name"]: r for r in PE.extract_regmap(_WITH_FIELDS)}
    assert regs["CTRL_SHADOWED"].get("fields"), (
        "the per-register slice ends before its own `### Fields` subsection")


# ── the shipped document ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real():
    doc = (_REPO / "benchmark-data/ic/opentitan_aes/phase1/input_doc"
           / "aes_registers.txt")
    if not doc.is_file():
        pytest.skip("the tracked input doc is absent")
    return {r["name"]: r for r in
            PE.extract_regmap(doc.read_text(errors="replace"))}


def test_the_registers_only_the_summary_carries_are_now_found(real):
    for n in ("CTRL_SHADOWED", "CTRL_AUX_SHADOWED", "CTRL_GCM_SHADOWED",
              "TRIGGER", "STATUS"):
        assert n in real, f"{n} is still missing from the register map"


def test_the_fields_behind_the_uncaptured_tokens_are_emitted(real):
    """The 12 tokens #593 lists are `<REG>_<FIELD>_MASK` / `_OFFSET` / bit
    positions built on exactly these."""
    want = {
        "CTRL_SHADOWED": {"OPERATION", "MODE", "KEY_LEN", "MANUAL_OPERATION"},
        "TRIGGER": {"KEY_IV_DATA_IN_CLEAR", "DATA_OUT_CLEAR"},
        "STATUS": {"OUTPUT_VALID", "INPUT_READY"},
    }
    for reg, names in want.items():
        got = {f["name"] for f in (real[reg].get("fields") or [])}
        assert names <= got, f"{reg}: missing {names - got}"


def test_the_bit_positions_are_the_documents(real):
    """Not just present — correct. `MODE` is bits 7:2 of CTRL_SHADOWED."""
    f = {x["name"]: x for x in real["CTRL_SHADOWED"]["fields"]}
    assert (f["OPERATION"]["lsb"], f["OPERATION"]["msb"]) == (0, 1)
    assert (f["MODE"]["lsb"], f["MODE"]["msb"]) == (2, 7)
    assert (f["KEY_LEN"]["lsb"], f["KEY_LEN"]["msb"]) == (8, 10)
