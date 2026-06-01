"""Tests for opcode_field_width_consistency_check (v0.2.13).

Pins the two checks that would have caught the usb_pd fabricated-opcode bug
(0x11-0x1F on a 4-bit Type field; L3 said 0x11 while L15 said 0x01).
"""
import importlib
import json

mod = importlib.import_module("opcode_field_width_consistency_check")


def _proj(tmp_path, l3, l4=None, l8=None, l15=None):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if l4 is not None:
        (gd / "L4_REGMAP.json").write_text(json.dumps(l4))
    if l8 is not None:
        (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    if l15 is not None:
        (gd / "L15_ENCODING_TABLES.json").write_text(json.dumps(l15))
    return tmp_path


def test_clean_project_passes(tmp_path):
    l3 = {"opcodes": [{"hex": "0x01", "name": "GoodCRC"},
                      {"hex": "0x0F", "name": "Vendor_Defined"}]}
    l15 = {"fields": {"t": {"rows": [["0x01", "GoodCRC"], ["0x0F", "Vendor_Defined"]]}}}
    assert mod.check_project(_proj(tmp_path, l3, l15=l15)) == []


def test_field_width_overflow_flagged(tmp_path):
    # The usb_pd bug: a 4-bit Message Type field but an opcode hex 0x11 (>0xF).
    l3 = {"opcodes": [{"hex": "0x11", "name": "Source_Capabilities"}]}
    l4 = {"registers": [{"name": "Message Header",
                         "fields": "Message Type [3:0], Number of Data Objects [14:12]"}]}
    findings = mod.check_project(_proj(tmp_path, l3, l4=l4))
    kinds = {f["kind"] for f in findings}
    assert "FIELD_WIDTH_OVERFLOW" in kinds

    # And no overflow when the hex fits the field.
    l3ok = {"opcodes": [{"hex": "0x01", "name": "Source_Capabilities"}]}
    assert not any(f["kind"] == "FIELD_WIDTH_OVERFLOW"
                   for f in mod.check_project(_proj(tmp_path / "ok", l3ok, l4=l4)))


def test_l3_l15_hex_mismatch_flagged(tmp_path):
    # L3 says Source_Capabilities=0x11 but L15 says 0x01 (the usb_pd contradiction).
    l3 = {"opcodes": [{"hex": "0x11", "name": "Source_Capabilities"}]}
    l15 = {"fields": {"data_message_table": {
        "rows": [["0x01", "Source_Capabilities"]]}}}
    findings = mod.check_project(_proj(tmp_path, l3, l15=l15))
    assert any(f["kind"] == "L3_L15_HEX_MISMATCH"
               and f["mnemonic"] == "source_capabilities" for f in findings)


def test_l3_l15_agreement_passes(tmp_path):
    l3 = {"opcodes": [{"hex": "0x01", "name": "Source_Capabilities"}]}
    l15 = {"fields": {"data_message_table": {
        "rows": [["0x01", "Source_Capabilities"]]}}}
    assert not any(f["kind"] == "L3_L15_HEX_MISMATCH"
                   for f in mod.check_project(_proj(tmp_path, l3, l15=l15)))


def test_no_opcodes_is_noop(tmp_path):
    # Bus protocol with no command opcodes -> nothing to check.
    l3 = {"opcodes": [], "no_opcodes_in_input": True}
    assert mod.check_project(_proj(tmp_path, l3)) == []
