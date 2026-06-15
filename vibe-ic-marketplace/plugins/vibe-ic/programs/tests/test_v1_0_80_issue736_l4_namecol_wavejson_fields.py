"""Regression for ORGANIC #736 P2 — L4 register field detail lost for the
Name-column table + wavejson reg-block doc family.

現象: the pre-v1.0.80 L4 CSR bit-field grid parsers
(`_parse_csr_bitfield_grid` / `_RE_CSR_BITFIELD_HEADER` and siblings) only
recognise the `| Bit | R/W | … | Description |` table form (field name
recovered from a Description-column lead). The canonical OpenTitan-style
per-register field table puts the field NAME in a dedicated `Name` column with
NO Description-lead name:

    |  Bits  |  Type  |  Reset  | Name        | Description         |
    |:------:|:------:|:-------:|:------------|:--------------------|
    |  31:0  |   wo   |   0x0   | key_share0  | Initial Key Share 0 |

That header fails the existing regex → ZERO `register.fields[]`. The same doc
family also renders the layout as a fenced ```wavejson {"reg":[…]} block whose
width-accumulated entries were never JSON-parsed into fields. Net: register-
level capture worked but ALL bit-field detail (name/bit/access/reset) was lost
(pre-fix: 0 fields for the whole doc).

Fix (chip-AGNOSTIC, Bucket B, additive):
  - `_v1_0_80_parse_namecol_bitfield_table` — Name-column field-table walker
    (header tokens {Bit|Bits|Bit#} + {Type|R/W|Access|Mode|Attr} + optional
    {Reset|Default} + {Name|Field|Field Name}); strips markdown-link wrappers
    from the Name cell; reserved/nameless rows skipped.
  - `_v1_0_80_parse_wavejson_reg_block` — fenced ```wavejson/wavedrom
    {"reg":[…]} parser; accumulates each entry's `bits` width to derive
    lsb/msb; skips nameless {"bits":N} reserved gaps; tolerant json.loads.
  - `_v1_0_80_harvest_namecol_register_fields` — attaches the harvested fields
    to the nearest `## REG_NAME` heading; dedup on (field_name, bits).

NEGATIVE no-leak (load-bearing):
  - the existing `| Bit | R/W | … | Description |` form is NOT mis-claimed by
    the Name-column walker (no Name column → 0 fields);
  - a doc with neither form harvests ZERO fields;
  - a malformed wavejson block yields [] (never raises / fabricates);
  - a nameless `{"bits":N}` reserved gap advances the bit cursor but emits no
    field.

chip-AGNOSTIC: pure column-header token sets + markdown-link strip + tolerant
json.loads; NO chip / vendor / SKU literal (chip names appear ONLY in fixture
prose, never in detection logic).
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


# ── (1) Name-column table → fields populated (name/bit/access/reset) ─────────

NAMECOL_DOC = """## ALERT_TEST
Alert Test Register
- Offset: `0x0`
- Reset default: `0x0`

### Fields

|  Bits  |  Type  |  Reset  | Name                  | Description                   |
|:------:|:------:|:-------:|:----------------------|:------------------------------|
|  31:2  |        |         |                       | Reserved                      |
|   1    |   wo   |   0x0   | fatal_fault           | Write 1 to trigger an alert.  |
|   0    |   wo   |   0x0   | recov_ctrl_update_err | Write 1 to trigger an alert.  |

## CTRL
Control Register
- Offset: `0x10`
- Reset default: `0x1`

### Fields

|  Bits  |  Type  |  Reset  | Name   | Description    |
|:------:|:------:|:-------:|:-------|:---------------|
|  31:1  |        |         |        | Reserved       |
|   0    |   rw   |   0x1   | enable | Enable the IP. |
"""


def test_namecol_table_populates_fields():
    regs = R._v1_0_80_harvest_namecol_register_fields(
        {"aes_registers.md": NAMECOL_DOC})
    by_name = {r["name"]: r for r in regs}
    assert "ALERT_TEST" in by_name and "CTRL" in by_name
    at = by_name["ALERT_TEST"]
    # reserved 31:2 row (empty Name) is SKIPPED; 2 named fields remain.
    fnames = {f["field_name"] for f in at["fields"]}
    assert fnames == {"fatal_fault", "recov_ctrl_update_err"}
    ff = next(f for f in at["fields"] if f["field_name"] == "fatal_fault")
    assert ff["bits"] == "1" and ff["access"] == "WO" and ff["reset"] == "0x0"
    assert ff["msb"] == 1 and ff["lsb"] == 1
    assert ff["extraction_strategy"] == "l4_namecol_bitfield_v1_0_80"
    assert at["address"] == "0x0" and at["reset_value"] == "0x0"


def test_namecol_table_strips_markdown_link_in_name_cell():
    doc = {"r_checklist_unrelated.md": (
        "## STATUS\n- Offset: `0x4`\n\n### Fields\n\n"
        "| Bits | Type | Reset | Name              | Description |\n"
        "|:----:|:----:|:-----:|:------------------|:-----------|\n"
        "| 0    | ro   | 0x0   | [busy](#busy-anch)| Busy flag. |\n")}
    regs = R._v1_0_80_harvest_namecol_register_fields(doc)
    f = regs[0]["fields"][0]
    assert f["field_name"] == "busy", f"markdown link not stripped: {f}"


# ── (2) wavejson reg block → named fields, reserved gap skipped ──────────────

WAVEJSON_DOC = """## TRIGGER
- Offset: `0x20`

### Fields

```wavejson
{"reg": [{"name": "start", "bits": 1, "attr": ["rw"]}, {"bits": 7}, {"name": "stop", "bits": 1, "attr": ["rw"]}], "config": {"lanes": 1}}
```
"""


def test_wavejson_reg_block_named_fields_and_reserved_gap():
    fields = R._v1_0_80_parse_wavejson_reg_block(WAVEJSON_DOC)
    by_name = {f["field_name"]: f for f in fields}
    # nameless {"bits":7} reserved gap emits no field but advances cursor.
    assert set(by_name) == {"start", "stop"}
    assert by_name["start"]["lsb"] == 0 and by_name["start"]["msb"] == 0
    # 1 (start) + 7 (reserved) = 8 → stop at bit 8.
    assert by_name["stop"]["lsb"] == 8 and by_name["stop"]["msb"] == 8
    assert by_name["start"]["access"] == "RW"
    assert by_name["stop"]["extraction_strategy"] == "l4_wavejson_reg_v1_0_80"


def test_wavejson_reg_block_through_harvester():
    regs = R._v1_0_80_harvest_namecol_register_fields(
        {"aes_registers.md": WAVEJSON_DOC})
    assert len(regs) == 1 and regs[0]["name"] == "TRIGGER"
    assert {f["field_name"] for f in regs[0]["fields"]} == {"start", "stop"}


# ── (3) existing Bit|R/W|Description form STILL parses (regression) ──────────

def test_existing_desc_form_not_claimed_by_namecol_walker_NOLEAK():
    """The Name-column walker must NOT fire on the `| Bit | R/W | Description |`
    form (no dedicated Name column) — that form is owned by the existing
    `_parse_csr_bitfield_grid` path."""
    desc_form = (
        "| Bit # | R/W | Description |\n"
        "|-------|-----|-------------|\n"
        "| 7:0   | RW  | **MODE**: select mode |\n"
        "| 15:8  | RO  | **STAT**: status |\n")
    assert R._v1_0_80_parse_namecol_bitfield_table(desc_form) == []


# ── (4) neither form → 0 fields; malformed wavejson → [] ─────────────────────

def test_neither_form_zero_fields_NOLEAK():
    plain = {"prose.md": "## FOO\n\nJust prose, no field table or wavejson.\n"}
    assert R._v1_0_80_harvest_namecol_register_fields(plain) == []


def test_malformed_wavejson_yields_empty_NOLEAK():
    assert R._v1_0_80_parse_wavejson_reg_block(
        "```wavejson\n{not valid json\n```") == []
    # a wavejson block that is L8 timing (signal: not reg:) is NOT harvested
    assert R._v1_0_80_parse_wavejson_reg_block(
        '```wavejson\n{"signal": [{"name": "clk"}]}\n```') == []


# ── (5) END-STATE through the L4 emitter on a real-shaped doc ────────────────

def test_l4_emitter_populates_fields_and_clears_flag(tmp_path: Path):
    """END-STATE: gen_l4_regmap on the Name-column + wavejson doc emits
    registers with populated fields[] (pre-fix: 0 fields) and clears the false
    no_registers_in_input flag."""
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    combined = NAMECOL_DOC + "\n" + WAVEJSON_DOC
    R.gen_l4_regmap(tmp_path, {"aes_registers.md": combined})
    l4 = json.loads(
        (tmp_path / _GEN_DIR / "L4_REGMAP.json").read_text())
    regs = l4.get("registers") or []
    by_name = {r.get("name"): r for r in regs}
    assert {"ALERT_TEST", "CTRL", "TRIGGER"} <= set(by_name)
    total_fields = sum(len(r.get("fields") or []) for r in regs)
    assert total_fields >= 5, f"bit-field detail lost: {total_fields} fields"
    assert l4.get("no_registers_in_input") is False
    # named field detail survives the emitter
    at = by_name["ALERT_TEST"]
    assert any(f.get("field_name") == "fatal_fault"
               and f.get("access") == "WO"
               for f in (at.get("fields") or []))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
