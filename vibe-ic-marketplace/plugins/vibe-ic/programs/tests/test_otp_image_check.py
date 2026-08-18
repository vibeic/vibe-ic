"""Unit tests for otp_image_check.py.

Covers: happy-path vs IC-A benchmark, address-out-of-range, duplicate
address, byte-out-of-range, malformed line, required-field coverage gap,
and benchmark lenient JSON (hex literals).
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "otp_image_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import otp_image_check as oic  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Happy path — synthetic .ver against synthetic L4_REGMAP, chip-AGNOSTIC.
# ---------------------------------------------------------------------------
def test_happy_path(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({
        "otp_size_bytes": 16,
        "fields": [
            {"name": "ID", "offset": 0, "length": 2, "required": True},
        ],
    }))
    ver = tmp_path / "img.ver"
    ver.write_text("@00000000 AA\n@00000001 55\n")
    findings = oic.check(ver, l4)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], f"Unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# 2. File missing
# ---------------------------------------------------------------------------
def test_missing_ver(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({"otp_size_bytes": 128}))
    findings = oic.check(tmp_path / "nope.ver", l4)
    assert any(f.rule == "FILE_MISSING" for f in findings)


def test_missing_regmap(tmp_path):
    ver = tmp_path / "x.ver"
    ver.write_text("@00000000 00\n")
    findings = oic.check(ver, tmp_path / "nope.json")
    assert any(f.rule == "FILE_MISSING" for f in findings)


# ---------------------------------------------------------------------------
# 3. Address out of range
# ---------------------------------------------------------------------------
def test_address_out_of_range(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({"otp_size_bytes": 16}))
    ver = tmp_path / "x.ver"
    # addr 0x20 is beyond 16-byte OTP
    ver.write_text("@00000020 AA\n")
    findings = oic.check(ver, l4)
    assert any(f.rule == "ADDRESS_OUT_OF_RANGE" for f in findings)


# ---------------------------------------------------------------------------
# 4. Duplicate address
# ---------------------------------------------------------------------------
def test_duplicate_address(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({"otp_size_bytes": 128}))
    ver = tmp_path / "x.ver"
    ver.write_text("@00000005 11\n@00000005 22\n")
    findings = oic.check(ver, l4)
    assert any(f.rule == "DUPLICATE_ADDRESS" for f in findings)


# ---------------------------------------------------------------------------
# 5. Malformed line
# ---------------------------------------------------------------------------
def test_malformed_line(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({"otp_size_bytes": 128}))
    ver = tmp_path / "x.ver"
    ver.write_text("@00000000 XX\nthis is junk\n@00000001 55\n")
    findings = oic.check(ver, l4)
    rules = {f.rule for f in findings}
    assert "MALFORMED_LINE" in rules


# ---------------------------------------------------------------------------
# 6. Required-field coverage
# ---------------------------------------------------------------------------
def test_required_field_coverage_gap(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({
        "otp_size_bytes": 16,
        "fields": [
            {"name": "ID", "offset": 0, "length": 4, "required": True},
        ],
    }))
    ver = tmp_path / "x.ver"
    # Only bytes 0,1 written; 2,3 missing → FIELD_COVERAGE error
    ver.write_text("@00000000 10\n@00000001 20\n")
    findings = oic.check(ver, l4)
    assert any(f.rule == "FIELD_COVERAGE" for f in findings)


def test_required_field_coverage_ok(tmp_path):
    l4 = tmp_path / "L4.json"
    l4.write_text(json.dumps({
        "otp_size_bytes": 16,
        "fields": [
            {"name": "ID", "offset": 0, "length": 4, "required": True},
        ],
    }))
    ver = tmp_path / "x.ver"
    ver.write_text("@00000000 10\n@00000001 20\n@00000002 30\n@00000003 40\n")
    findings = oic.check(ver, l4)
    assert not any(f.rule == "FIELD_COVERAGE" for f in findings)


# ---------------------------------------------------------------------------
# 7. Lenient JSON (0xNN hex literals that L3 of benchmark uses)
# ---------------------------------------------------------------------------
def test_lenient_json_hex_literals(tmp_path):
    l4 = tmp_path / "L4.json"
    # Invalid strict JSON but parseable by lenient loader
    l4.write_text('{"otp_size_bytes": 128, "example_cmd": 0x70}')
    data = oic.lenient_load(l4)
    assert data["otp_size_bytes"] == 128
    assert data["example_cmd"] == 0x70


# ---------------------------------------------------------------------------
# 8. extract_otp_size fallback on otp_map_<N>x<W>
# ---------------------------------------------------------------------------
def test_extract_size_from_otp_map_key():
    assert oic.extract_otp_size({"otp_map_128x8": []}) == 128
    assert oic.extract_otp_size({"otp_map_64x16": []}) == 64
    assert oic.extract_otp_size({"otp_size_bytes": 256}) == 256


# ---------------------------------------------------------------------------
# 9. Wave 73 (v0.128) S2 — extract_otp_size returns None when no hint;
#    otp_table_layout / otp_macro_size hints supported.
# ---------------------------------------------------------------------------
def test_extract_size_returns_none_without_hint():
    # No otp_size_bytes / otp_size / size_bytes / otp_map_<N>x<W> /
    # otp_table_layout / otp_macro_size — must return None, not 128.
    assert oic.extract_otp_size({}) is None
    assert oic.extract_otp_size({"unrelated": 42}) is None


def test_extract_size_from_otp_macro_size():
    assert oic.extract_otp_size({"otp_macro_size": 64}) == 64


def test_extract_size_from_otp_table_layout():
    assert oic.extract_otp_size(
        {"otp_table_layout": {"size_bytes": 96}}) == 96
    assert oic.extract_otp_size(
        {"otp_table_layout": {"start": 0, "end": 31}}) == 32


def test_check_emits_otp_size_undetermined(tmp_path):
    """When neither L4 nor L11 declares a size, check() must emit a
    FAIL finding with the canonical guidance message."""
    l4 = tmp_path / "L4_REGMAP.json"
    l4.write_text(json.dumps({"fields": []}))
    ver = tmp_path / "x.ver"
    ver.write_text("@00000000 11\n")
    findings = oic.check(ver, l4)
    rules = {f.rule for f in findings}
    assert "OTP_SIZE_UNDETERMINED" in rules, rules
    msgs = [f.message for f in findings
            if f.rule == "OTP_SIZE_UNDETERMINED"]
    assert any("could not be determined" in m for m in msgs), msgs


def test_check_uses_l11_otp_macro_size_when_l4_silent(tmp_path):
    """If L4 is silent on size but a sibling L11_CALIBRATION.json
    declares otp_macro_size, check() must pick it up — and *not* emit
    OTP_SIZE_UNDETERMINED."""
    l4 = tmp_path / "L4_REGMAP.json"
    l4.write_text(json.dumps({"fields": []}))
    l11 = tmp_path / "L11_CALIBRATION.json"
    l11.write_text(json.dumps({"otp_macro_size": 256}))
    ver = tmp_path / "x.ver"
    ver.write_text("@00000000 11\n")
    findings = oic.check(ver, l4)
    rules = {f.rule for f in findings}
    assert "OTP_SIZE_UNDETERMINED" not in rules, rules
