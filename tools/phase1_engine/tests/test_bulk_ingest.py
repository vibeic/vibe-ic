"""Tests for v0.74 bulk parsers (pin_csv, regmap_csv, otp_hex).

Covers round-trip of each parser output through FactGraph save/load
and verifies the expected L1 / L4 fact shapes land where the IC Expert Agent and
gap detector expect them.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.phase1_engine.ingest import (
    from_pin_csv,
    from_regmap_csv,
    from_otp_hex,
    merge,
)
from tools.phase1_engine.schema import FactGraph


# ---------------------------------------------------------------------------
# pin_csv
# ---------------------------------------------------------------------------
PIN_CSV_BASIC = """\
pin_number,name,type,description
1,VBUS,power,Main supply
2,GND,ground,Reference ground
3,ID_BUS,io,Data line
"""


def test_from_pin_csv_emits_l1_pinout_and_count(tmp_path: Path):
    f = tmp_path / "pins.csv"
    f.write_text(PIN_CSV_BASIC)
    g = from_pin_csv(f)
    paths = g.paths()
    assert "L1.pinout.VBUS.pin_number" in paths
    assert "L1.pinout.VBUS.type" in paths
    assert "L1.pinout.VBUS.description" in paths
    assert "L1.pinout.GND.pin_number" in paths
    assert "L1.pinout.ID_BUS.description" in paths
    assert "L1.pin_count" in paths
    count = g.by_path("L1.pin_count")
    assert count is not None and count.value == 3


def test_from_pin_csv_handles_alias_header_columns(tmp_path: Path):
    f = tmp_path / "pins_alias.csv"
    f.write_text("#,signal,direction\n1,VBUS,in\n2,GND,pwr\n")
    g = from_pin_csv(f)
    paths = g.paths()
    assert "L1.pinout.VBUS.direction" in paths
    assert "L1.pinout.VBUS.pin_number" in paths


def test_from_pin_csv_rejects_missing_name_column(tmp_path: Path):
    f = tmp_path / "pins_bad.csv"
    f.write_text("pin_number,nonsense\n1,foo\n")
    with pytest.raises(ValueError, match="no pin name column"):
        from_pin_csv(f)


# ---------------------------------------------------------------------------
# regmap_csv
# ---------------------------------------------------------------------------
REGMAP_CSV_BASIC = """\
address,name,width,access,reset,description
0x00,CTRL,8,RW,0x00,Control register
0x01,STATUS,8,RO,0x00,Status register
0x02,DATA,8,RW,0x00,Data register
"""


def test_from_regmap_csv_emits_l4_registers_and_count(tmp_path: Path):
    f = tmp_path / "regmap.csv"
    f.write_text(REGMAP_CSV_BASIC)
    g = from_regmap_csv(f)
    paths = g.paths()
    assert "L4.registers.CTRL.address" in paths
    assert "L4.registers.CTRL.access" in paths
    assert "L4.registers.STATUS.description" in paths
    assert "L4.register_count" in paths
    count = g.by_path("L4.register_count")
    assert count is not None and count.value == 3


def test_from_regmap_csv_accepts_offset_column_alias(tmp_path: Path):
    f = tmp_path / "regmap_offset.csv"
    f.write_text("register,offset,width\nCTRL,0x00,8\nSTATUS,0x04,8\n")
    g = from_regmap_csv(f)
    assert "L4.registers.CTRL.address" in g.paths()


# ---------------------------------------------------------------------------
# otp_hex
# ---------------------------------------------------------------------------
INTEL_HEX_3_BYTES = (
    ":03000000AA55CE30\n"
    ":00000001FF\n"
)


def test_from_otp_hex_intel_format(tmp_path: Path):
    f = tmp_path / "otp.hex"
    f.write_text(INTEL_HEX_3_BYTES)
    g = from_otp_hex(f)
    assert g.by_path("L4.otp_present").value is True
    assert g.by_path("L4.otp_size_bytes").value == 3
    assert g.by_path("L4.otp.format").value == "intel_hex"
    assert g.by_path("L4.otp.bytes[0]").value == 0xAA
    assert g.by_path("L4.otp.bytes[1]").value == 0x55
    assert g.by_path("L4.otp.bytes[2]").value == 0xCE


def test_from_otp_hex_raw_format(tmp_path: Path):
    f = tmp_path / "otp_raw.hex"
    f.write_text("# comment\nAA 55 CE\n# trailing\n0xDE,0xAD\n")
    g = from_otp_hex(f)
    assert g.by_path("L4.otp.format").value == "raw_hex"
    assert g.by_path("L4.otp_size_bytes").value == 5
    assert g.by_path("L4.otp.bytes[0]").value == 0xAA
    assert g.by_path("L4.otp.bytes[4]").value == 0xAD


def test_from_otp_hex_rejects_bad_checksum(tmp_path: Path):
    f = tmp_path / "otp_bad.hex"
    # flip last byte of correct checksum record
    f.write_text(":03000000AA55CE00\n:00000001FF\n")
    with pytest.raises(ValueError, match="checksum fail"):
        from_otp_hex(f)


# ---------------------------------------------------------------------------
# merge — bulk graph onto existing facts.yaml
# ---------------------------------------------------------------------------
def test_bulk_parsers_merge_into_existing_graph(tmp_path: Path):
    base = FactGraph(ic_name="MY_IC", class_path="any-ic")
    base.add_fact(
        path="L1.part_number", value="MY_IC",
        views=["L1"], source="user_stated",
    )
    pins_csv = tmp_path / "pins.csv"
    pins_csv.write_text(PIN_CSV_BASIC)
    pins_graph = from_pin_csv(pins_csv)

    combined = merge(base, pins_graph)
    paths = combined.paths()
    # base fact is preserved
    assert "L1.part_number" in paths
    # bulk facts merged in
    assert "L1.pinout.VBUS.pin_number" in paths
    assert "L1.pin_count" in paths
    # inherited metadata (ic_name) not clobbered
    assert combined.ic_name == "MY_IC"
