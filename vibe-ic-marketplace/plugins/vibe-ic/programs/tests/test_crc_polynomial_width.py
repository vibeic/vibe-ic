"""v0.2.14 — CRC polynomial width regression.

Pins the program-first fix for the CRC-truncation bug found via the phase1
close-loop on usb_pd / interlaken / automotive_ethernet: the reflected
polynomial was computed with a FIXED 8-bit reversal, silently clipping any
CRC wider than 8 bits (CRC-16/24/32). The poly/init extraction regexes were
likewise locked to exactly 2 hex digits.

These tests target the deterministic module-level helper `_reflect_crc_poly`
in phase1_doc_one_shot_runner so the runner's own reflection logic is under
test (not a re-implemented copy of the formula), plus the extraction regexes.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as runner  # noqa: E402


# ---------------------------------------------------------------------------
# _reflect_crc_poly — width-aware bit reversal (the core of the fix)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("poly,expected", [
    # CRC-8 — unchanged from the old 8-bit path (no regression).
    ("0x07", "0xE0"),          # CRC-8 / ATM-HEC, CCITT
    ("0x31", "0x8C"),          # CRC-8 / MAXIM (reflected 0x8C is the canonical val)
    ("0x1D", "0xB8"),          # CRC-8 / SAE-J1850
    # CRC-16 — previously clipped to 8 bits.
    ("0x1021", "0x8408"),      # CRC-16 / CCITT (reflected = CRC-16/KERMIT poly)
    ("0x8005", "0xA001"),      # CRC-16 / IBM-ARC (reflected = MODBUS poly)
    # CRC-24.
    ("0x328B63", "0xC6D14C"),  # Interlaken CRC-24
    # CRC-32 — the headline bug (IEEE 802.3).
    ("0x04C11DB7", "0xEDB88320"),  # canonical reflected IEEE-802.3 CRC-32
])
def test_reflect_crc_poly_width_aware(poly, expected):
    assert runner._reflect_crc_poly(poly) == expected


def test_reflect_crc_poly_preserves_width_digits():
    # The reflected value keeps the SAME hex-digit count as the input poly
    # (no truncation): a 32-bit poly reflects to 8 hex digits, 24->6, 16->4.
    assert len(runner._reflect_crc_poly("0x04C11DB7")) == len("0x04C11DB7")
    assert len(runner._reflect_crc_poly("0x328B63")) == len("0x328B63")
    assert len(runner._reflect_crc_poly("0x1021")) == len("0x1021")
    assert len(runner._reflect_crc_poly("0x07")) == len("0x07")


def test_reflect_crc_poly_double_reflect_is_identity():
    # Reflecting twice at the same width returns the original (sanity on
    # the width-floor: an 8-bit poly stays 8-bit through both reflects).
    for poly in ("0x07", "0x31", "0x1021", "0x328B63", "0x04C11DB7"):
        once = runner._reflect_crc_poly(poly)
        twice = runner._reflect_crc_poly(once)
        assert int(twice, 16) == int(poly, 16)


def test_reflect_crc_poly_handles_no_0x_prefix():
    assert runner._reflect_crc_poly("04C11DB7") == "0xEDB88320"


@pytest.mark.parametrize("bad", [None, "", "0x", "0xZZ", "nope"])
def test_reflect_crc_poly_garbage_returns_none(bad):
    assert runner._reflect_crc_poly(bad) is None


# ---------------------------------------------------------------------------
# extraction regexes — must accept 2..8 hex digits (not exactly 2)
# ---------------------------------------------------------------------------
def test_poly_regex_accepts_wide_polynomials():
    pat = re.compile(r"poly(?:nomial)?\s*[\-—:=]?\s*0x([0-9a-fA-F]{2,8})",
                     re.IGNORECASE)
    assert pat.search("polynomial 0x04C11DB7").group(1).upper() == "04C11DB7"
    assert pat.search("poly = 0x328B63").group(1).upper() == "328B63"
    assert pat.search("poly: 0x1021").group(1).upper() == "1021"
    # CRC-8 still captured (2 digits, nothing wider follows).
    assert pat.search("polynomial 0x07").group(1).upper() == "07"


def test_crc_named_regex_accepts_wide_polynomials():
    # The named-CRC fallback forbids crossing '=' so a worked-example RESULT
    # value ("CRC16 = 0x7FA1") is NOT mistaken for the generator polynomial.
    pat = re.compile(r"CRC[\s\-]?(?:8|16|24|32)\b[^=\n]{0,40}?0x([0-9a-fA-F]{2,8})",
                     re.IGNORECASE)
    assert pat.search("CRC-32, polynomial 0x04C11DB7").group(1).upper() == "04C11DB7"
    assert pat.search("CRC-32 (0x04C11DB7, init 0xFFFFFFFF)").group(1).upper() == "04C11DB7"
    assert pat.search("CRC-16 with 0x1021").group(1).upper() == "1021"
    assert pat.search("CRC-8 uses 0x07").group(1).upper() == "07"


def test_crc_named_regex_rejects_worked_example_result_value():
    # SD/MMC false-positive: "512 bytes with 0xFF data --> CRC16 = 0x7FA1" is
    # the CRC *of some data*, not the polynomial. The '=' boundary excludes it.
    pat = re.compile(r"CRC[\s\-]?(?:8|16|24|32)\b[^=\n]{0,40}?0x([0-9a-fA-F]{2,8})",
                     re.IGNORECASE)
    assert pat.search("512 bytes with 0xFF data --> CRC16 = 0x7FA1") is None
    assert pat.search("CRC16 = 0x7FA1") is None
    # A real poly declaration that happens to USE '=' is still caught by the
    # 1st (polynomial-keyword) pattern, which intentionally allows '='.
    poly_pat = re.compile(r"poly(?:nomial)?\s*[\-—:=]?\s*0x([0-9a-fA-F]{2,8})",
                          re.IGNORECASE)
    assert poly_pat.search("polynomial = 0x04C11DB7").group(1).upper() == "04C11DB7"


def test_init_regex_accepts_wide_init():
    pat = re.compile(r"init\s*[:=]?\s*0?x?([0-9a-fA-F]{2,8})", re.IGNORECASE)
    assert pat.search("init = 0xFFFFFFFF").group(1).upper() == "FFFFFFFF"
    assert pat.search("init: 0xFF").group(1).upper() == "FF"
