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


# ---------------------------------------------------------------------------
# 10. BYTE_OUT_OF_RANGE reachability (both directions).
#
# The docstring promises to distinguish rule 5 (BYTE_OUT_OF_RANGE — "a value
# is outside 0..255") from rule 7 (MALFORMED_LINE — "a line fails the @addr
# byte pattern"). Before the fix the .ver lexer bounded the value token to
# {1,2} hex digits, so `val > 0xFF` could never be true and rule 5 was dead
# code: every over-range byte was reported as "Unparseable line".
#
# These tests drive the CLI and assert on the emitted JSON + exit code only,
# never on the source text.
# ---------------------------------------------------------------------------
def _run_cli(tmp_path, regmap_obj, ver_text):
    """Invoke the program as the CLI does; return (returncode, findings)."""
    import subprocess

    l4 = tmp_path / "L4_REGMAP.json"
    l4.write_text(json.dumps(regmap_obj))
    ver = tmp_path / "img.ver"
    ver.write_text(ver_text)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(ver), "--regmap", str(l4), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode != 2, f"argument/IO error: {proc.stderr}"
    return proc.returncode, json.loads(proc.stdout)


def test_byte_out_of_range_is_reachable(tmp_path):
    """FAILS against the unfixed program.

    An over-range byte value must be reported as BYTE_OUT_OF_RANGE, not
    swallowed by the syntax rule. Unfixed, the only rule emitted here is
    MALFORMED_LINE and this assertion fails.
    """
    rc, findings = _run_cli(
        tmp_path, {"otp_size_bytes": 128}, "@00000000 1FF\n")
    rules = [f["rule"] for f in findings]
    assert "BYTE_OUT_OF_RANGE" in rules, rules
    assert rc == 1, rc
    oor = [f for f in findings if f["rule"] == "BYTE_OUT_OF_RANGE"]
    assert all(f["severity"] == "error" for f in oor), oor
    assert any("0x1FF" in f["message"] for f in oor), oor


def test_byte_out_of_range_reachable_across_widths(tmp_path):
    """Reachable for any width above one byte, not just 3 hex digits."""
    rc, findings = _run_cli(
        tmp_path, {"otp_size_bytes": 128},
        "@00000000 100\n@00000001 FFFF\n@00000002 DEADBEEF\n")
    oor = [f for f in findings if f["rule"] == "BYTE_OUT_OF_RANGE"]
    assert len(oor) == 3, findings
    assert rc == 1, rc


def test_valid_image_still_passes_after_widening(tmp_path):
    """OPPOSITE direction: the gate is not always-fail.

    A well-formed in-range byte image must still emit zero findings and
    exit 0 — widening the lexer must not make every image red.
    """
    rc, findings = _run_cli(
        tmp_path,
        {"otp_size_bytes": 16,
         "fields": [{"name": "ID", "offset": 0, "length": 2,
                     "required": True}]},
        "@00000000 AA\n@00000001 55\n// comment\n\n@0000000F FF\n")
    assert findings == [], findings
    assert rc == 0, rc


def test_malformed_line_still_reachable_and_distinct(tmp_path):
    """OPPOSITE direction for the sibling rule.

    Genuine junk must still be MALFORMED_LINE, and must NOT be relabelled
    as BYTE_OUT_OF_RANGE — the two verdicts stay distinguishable.
    """
    rc, findings = _run_cli(
        tmp_path, {"otp_size_bytes": 128},
        "@00000000 XX\nthis is junk\n@00000001 55\n")
    rules = [f["rule"] for f in findings]
    assert rules.count("MALFORMED_LINE") == 2, findings
    assert "BYTE_OUT_OF_RANGE" not in rules, findings
    assert rc == 1, rc


def test_overwide_but_in_range_token_stays_malformed(tmp_path):
    """Pins the deliberate no-red-to-green decision.

    A zero-padded token like "0AA" evaluates in range but is wider than a
    byte. It failed before the lexer was widened and must keep failing, as
    MALFORMED_LINE rather than the (untrue) BYTE_OUT_OF_RANGE.
    """
    rc, findings = _run_cli(
        tmp_path, {"otp_size_bytes": 128}, "@00000000 0AA\n")
    rules = [f["rule"] for f in findings]
    assert rules == ["MALFORMED_LINE"], findings
    assert rc == 1, rc


def test_out_of_range_byte_does_not_enter_the_image(tmp_path):
    """A rejected byte must not be counted as coverage for a required
    field — otherwise the new rule would mask FIELD_COVERAGE."""
    rc, findings = _run_cli(
        tmp_path,
        {"otp_size_bytes": 16,
         "fields": [{"name": "ID", "offset": 0, "length": 1,
                     "required": True}]},
        "@00000000 1FF\n")
    rules = {f["rule"] for f in findings}
    assert rules == {"BYTE_OUT_OF_RANGE", "FIELD_COVERAGE"}, findings
    assert rc == 1, rc


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
