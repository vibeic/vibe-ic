"""SPI-datasheet residuals closed: selector-table enum recall + register-table
precision, and the L14-L18 protocol path wired into the general structures.

(a) spec_enumset_extract
    PRECISION — a REGISTER-MAP pipe table (`| 0x00 | CTRL | RW | 32 | … |`,
      header Offset+Access/Width) was mis-read as an enum set (the hex offset
      minted an enum member, via both the table pass AND the bullet pass). Now a
      register-map-headed table is skipped, and `_from_bullets` no longer
      re-mints table rows.
    RECALL — a SELECTOR table (first header column = MODE/sel/encoding/…) with
      small DECIMAL codes (the SPI CPOL/CPHA 4-mode table `| MODE | … |` / `0 |
      … | meaning`) is now captured (a fixed survivable decimal cohort).

(b) cvdp_complete_extract._structures now also composes the L14-L18 protocol
    extractor (phase1_protocol_spec_extract) — protocol_versioning / encoding_tables
    / compliance / channel_catalog / interconnect — so the general engine's
    structures carry the protocol path for an AMBA/USB/PCIe-style spec. §4.05:
    populated ONLY when the extractor reports EXTRACTED; empty for an ordinary doc.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_enumset_extract as EN          # noqa: E402
import spec_complete_extract as SCE        # noqa: E402


def _enum_kinds(text):
    return [e for e in EN.extract(text) if e["kind"] == "enum_set"]


# ── (a) PRECISION: register-map table is NOT an enum ──
_REGMAP = (
    "| Offset | Name | Access | Width | Description |\n"
    "|--------|------|--------|-------|-------------|\n"
    "| 0x00 | CTRL | RW | 32 | Control |\n"
    "| 0x04 | STATUS | RO | 32 | Status |\n"
    "| 0x08 | TXDATA | WO | 8 | Transmit byte |\n")


def test_register_map_table_not_read_as_enum():
    assert _enum_kinds(_REGMAP) == []


# ── (a) RECALL: selector mode table IS an enum ──
_MODE = (
    "| MODE | CPOL | CPHA | Meaning |\n"
    "|------|------|------|---------|\n"
    "| 0 | 0 | 0 | clock idle low, sample leading |\n"
    "| 1 | 0 | 1 | clock idle low, sample trailing |\n"
    "| 2 | 1 | 0 | clock idle high, sample leading |\n"
    "| 3 | 1 | 1 | clock idle high, sample trailing |\n")


def test_selector_mode_table_is_enum():
    items = _enum_kinds(_MODE)
    assert len(items) == 4
    codes = {e.get("evidence", "")[:3] for e in items}
    assert any("0" in c for c in codes)


def test_non_selector_decimal_table_not_over_fired():
    # a plain data table with no selector header + no code literals stays empty
    plain = ("| Param | Value |\n|-------|-------|\n"
             "| latency | 8 |\n| depth | 16 |\n")
    assert _enum_kinds(plain) == []


# ── (b) protocol path wired into structures ──
def test_protocol_compliance_surfaces_in_structures():
    proto = (
        "# AXI-lite Protocol Spec\n## Compliance\n"
        "- The master shall assert AWVALID until AWREADY is high.\n"
        "- A slave must not wait for AWVALID before asserting AWREADY.\n"
        "- The interconnect is required to preserve transaction ordering.\n")
    st = SCE.assess_spec(proto, [], [], module_name="axi")["structures"]
    for k in ("protocol_versioning", "encoding_tables", "compliance",
              "channel_catalog", "interconnect"):
        assert k in st
    assert len(st["compliance"]) >= 2


def test_protocol_facets_empty_on_ordinary_doc():
    st = SCE.assess_spec("Add two 8-bit numbers a and b, output the 9-bit sum y.",
                         [], [], module_name="add8")["structures"]
    for k in ("protocol_versioning", "encoding_tables", "compliance",
              "channel_catalog", "interconnect"):
        assert st[k] == []
