#!/usr/bin/env python3
"""Tests for v1.6.50 harvester regex tightening in
phase1_doc_input_completeness_check.py.

Two chip-AGNOSTIC false-positive classes were observed on the
phase2+3_v10648 benchmark and traced to the harvester regex:

  Class A — numeric+unit harvester crossed whitespace into an
            English word starting with the same letter as a unit:
              `2016.06   V1.0`        → harvested `2016.06 V`
              `2018.5    V1.5`        → harvested `2018.5 V`
              `<date>  Vertical`      → harvested `<digits> V`
              `36 user pins`          → harvested `36 us`
              `17 user pins`          → harvested `17 us`

  Class B — `0x[hex]+` regex matched the `0x<hex>` substring inside
            a `<digits>x<digits>` resolution literal:
              `640x480`               → harvested `0x480`
              `1024x768`              → harvested `0x768`

The fix tightens the regex with a trailing `(?![A-Za-z])` on the unit
alternation and a leading `(?<![0-9A-Fa-f])` on the `0x` prefix, both
chip-AGNOSTIC. These tests pin both fixes."""

from __future__ import annotations

import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import phase1_doc_input_completeness_check as G  # noqa: E402


def _harvest(text: str):
    design, _garble = G._harvest_tokens(text)
    return design


# ---------------------------------------------------------------------------
# Class A — numeric+unit must not bleed into adjacent English words.
# ---------------------------------------------------------------------------

def test_unit_V_does_not_match_into_Vertical_word():
    """`<date>     Vertical` line from a vendor PDF page footer must
    not be tokenized as `<digits> V`."""
    text = "2015.11.02   MAX 10 I/O Vertical Migration Support"
    tokens = _harvest(text)
    # No `* V` token harvested
    bleed = [t for t in tokens if t.endswith(" V")]
    assert bleed == [], (
        f"Class-A false-positive: harvested numeric+V tokens from "
        f"a Vertical-word context: {bleed}"
    )


def test_unit_V_does_not_match_into_revision_history_V_column():
    """`2016.06   V1.0   Initial Version` revision-history rows must
    not produce `2016.06 V`."""
    text = "2016.06       V1.0          Initial Version (Preliminary)"
    tokens = _harvest(text)
    bleed = [t for t in tokens if t.endswith(" V") or t.endswith("V")
             and "2016" in t]
    assert "2016.06 V" not in tokens
    assert "2016.06V" not in tokens
    assert not any("2016.06" in t and t.endswith("V") for t in tokens), (
        f"Class-A false-positive: revision-history date harvested "
        f"with V revision-tag suffix: {bleed}"
    )


def test_unit_us_does_not_match_into_user_word():
    """`17 user pins` and `36 user pins` from the DE10-Lite expansion
    header description must not be tokenized as `17 us` / `36 us`."""
    text = "The expansion header has 17 user pins (16 GPIO + 1 Reset)"
    tokens = _harvest(text)
    assert "17 us" not in tokens, (
        f"Class-A false-positive: '17 user pins' tokenized as '17 us'."
        f" tokens={tokens}"
    )

    text2 = "Each header has 36 user pins connected directly to the FPGA"
    tokens2 = _harvest(text2)
    assert "36 us" not in tokens2, (
        f"Class-A false-positive: '36 user pins' tokenized as '36 us'."
        f" tokens={tokens2}"
    )


def test_unit_ms_does_not_match_into_message_word():
    """A timing-style integer next to an English `m`-word must not be
    harvested. Synthetic input — no real benchmark observed yet, but
    covers a class the regex is now contractually rejecting."""
    text = "12 message bytes are followed by a CRC"
    tokens = _harvest(text)
    assert "12 ms" not in tokens, (
        f"Class-A false-positive: '12 message bytes' tokenized as "
        f"'12 ms'. tokens={tokens}"
    )


def test_unit_V_still_matches_legitimate_voltage_line():
    """Sanity: real `<digits> V` voltage lines must still harvest."""
    text = "Absolute maximum supply voltage: 6.1 V"
    tokens = _harvest(text)
    assert "6.1 V" in tokens or "6.1V" in tokens, (
        f"Regression: legitimate voltage token dropped. tokens={tokens}"
    )


def test_unit_V_still_matches_ESD_kv_spec_line():
    """Sanity: ESD spec rows with `2000 V` / `6000 V` must still
    harvest. v1.6.10 round 2 explicitly preserved this case."""
    text = "ESD HBM rating: ±2000 V (JEDEC JS-001)"
    tokens = _harvest(text)
    assert "2000 V" in tokens, (
        f"Regression: legitimate ESD voltage token dropped. "
        f"tokens={tokens}"
    )


def test_unit_us_still_matches_legitimate_microsecond_value():
    """Sanity: real `<digits> us` microsecond values must still
    harvest. Two variants — with and without trailing punctuation."""
    text = "Wake pulse pulls the bus low for 17 us, then releases."
    tokens = _harvest(text)
    assert "17 us" in tokens, (
        f"Regression: legitimate '17 us' before comma dropped. "
        f"tokens={tokens}"
    )

    text2 = "tPULSE_min = 36 us"
    tokens2 = _harvest(text2)
    assert "36 us" in tokens2, (
        f"Regression: legitimate '36 us' end-of-line dropped. "
        f"tokens={tokens2}"
    )


# ---------------------------------------------------------------------------
# Class A.2 — leading lookbehind: `<letter><digit>+ V` must not match.
# ---------------------------------------------------------------------------

def test_unit_V_does_not_match_after_reference_designator():
    """`C129 V-` is a capacitor designator (C129) next to a negative-
    supply rail label (V-). It is NOT a `129 V` voltage reading.
    Both `C129 V-` and the regex-engine-picks-suffix variant `29 V`
    / `9 V` (engine retrying from each digit position inside `129`)
    must be rejected."""
    text = "C129                         V-                     C141"
    tokens = _harvest(text)
    for bad in ("129 V", "29 V", "9 V"):
        assert bad not in tokens, (
            f"Class-A.2 false-positive: 'C129 V-' tokenized as "
            f"{bad!r}. tokens={tokens}"
        )


def test_unit_V_does_not_match_after_chip_name_prefix():
    """`<chip-prefix><digits> V` (e.g. `<vendor-prefix>5678 V` from
    `<vendor>5678` chip name + neighbouring V) must not match.
    Synthetic — covers the chip-name regression class."""
    text = "Refer to xy26100 V cells specification, page 12"
    tokens = _harvest(text)
    assert "26100 V" not in tokens, (
        f"Class-A.2 false-positive: chip-name digits + neighbouring V "
        f"tokenized as voltage. tokens={tokens}"
    )


def test_unit_V_still_matches_with_plus_minus_prefix():
    """Sanity: `±2000 V` ESD spec still harvests — `±` is not [A-Za-z]
    so the leading lookbehind does not block."""
    text = "ESD: ±2000 V (HBM, JEDEC JS-001)"
    tokens = _harvest(text)
    assert "2000 V" in tokens, (
        f"Regression: ±-prefixed ESD voltage dropped. tokens={tokens}"
    )


def test_unit_V_still_matches_after_colon_or_paren():
    """Sanity: `(6.1 V)`, `Vmax: 6.1 V` still harvest."""
    for prefix in ("(", " ", ":", "=", "±", "≤", "≥"):
        text = f"value{prefix}6.1 V end"
        tokens = _harvest(text)
        assert "6.1 V" in tokens, (
            f"Regression: numeric+V after '{prefix}' dropped. "
            f"tokens={tokens}"
        )


# ---------------------------------------------------------------------------
# Stoplist additions — generic English nouns harvested by all-caps regex.
# ---------------------------------------------------------------------------

def test_stoplist_blocks_generic_table_header_words():
    """`TYPE`, `NAME`, `PIN`, `PINS`, `PORT` are generic table-header
    English words; the all-caps regex `[A-Z][A-Z0-9_]{2,}` would
    harvest them verbatim. Stoplist must reject them. Real case:
    `USB B-TYPE` → harvested `TYPE`."""
    text = "Connector pinout: USB B-TYPE PORT NAME PINS"
    tokens = _harvest(text)
    for word in ("TYPE", "NAME", "PORT", "PINS"):
        assert word not in tokens, (
            f"Stoplist regression: generic table-header word "
            f"{word!r} leaked into design tokens. tokens={tokens}"
        )


# ---------------------------------------------------------------------------
# Class B — `0x[hex]+` must not match inside `<digit>+x<digit>+`.
# ---------------------------------------------------------------------------

def test_hex_does_not_match_inside_resolution_literal():
    """`640x480` is a display resolution, not a hex constant. The `0x`
    inside (last digit of `640` + `x` + first digit of `480`) must not
    be harvested as a hex literal."""
    text = "Standard VGA resolution (640x480 pixels, at 25 MHz)"
    tokens = _harvest(text)
    assert "0x480" not in tokens, (
        f"Class-B false-positive: '640x480' tokenized as hex 0x480."
        f" tokens={tokens}"
    )

    text2 = "1024x768 (XGA), 1280x1024 (SXGA), 1920x1080 (Full HD)"
    tokens2 = _harvest(text2)
    bleed = [t for t in tokens2 if t.startswith("0x")
             and t.lstrip("0x") in ("768", "1024", "1080")]
    assert bleed == [], (
        f"Class-B false-positive: resolution literals tokenized as "
        f"hex constants: {bleed}"
    )


def test_hex_still_matches_legitimate_hex_constant():
    """Sanity: real `0xABCD`-style hex constants must still harvest."""
    text = "Address 0x1621 holds the challenge response register."
    tokens = _harvest(text)
    assert "0x1621" in tokens, (
        f"Regression: legitimate hex constant dropped. tokens={tokens}"
    )

    text2 = "Page 0 spans 0x0000–0x001F (32 bytes)"
    tokens2 = _harvest(text2)
    assert "0x0000" in tokens2 and "0x001F" in tokens2, (
        f"Regression: page-boundary hex constants dropped. "
        f"tokens={tokens2}"
    )


def test_hex_still_matches_at_string_start():
    """`0xFF00` at start of line must still harvest (lookbehind must
    not block when there's no preceding char)."""
    text = "0xFF00 mask is the upper byte selector."
    tokens = _harvest(text)
    assert "0xFF00" in tokens, (
        f"Regression: line-start hex constant dropped. tokens={tokens}"
    )


def test_hex_still_matches_after_whitespace():
    """`<space>0x<hex>` and `<comma>0x<hex>` and `(0x<hex>)` must still
    harvest — only `<hexdigit>0x<hex>` should be rejected."""
    for prefix in ("(", " ", ",", "=", "[", "{"):
        text = f"value {prefix}0xDEAD)"
        tokens = _harvest(text)
        assert "0xDEAD" in tokens, (
            f"Regression: hex after '{prefix}' dropped. "
            f"tokens={tokens}"
        )


# ---------------------------------------------------------------------------
# Integration: end-to-end on representative noise + real-content mix.
# ---------------------------------------------------------------------------

def test_integration_revision_history_table():
    """Synthesised revision-history table — the false-positives
    documented in the deep-review report should disappear, while
    every real ESD / supply voltage in the same blob still harvests."""
    text = """
    Revision History:
      2016.06       V1.0          Initial Version (Preliminary)
      2016.09       V1.1          Minor corrections.
      2018.10       V1.6          Latest revision.

    Electrical Characteristics:
      Supply voltage:               3.3 V (typ.), 6.1 V (max.)
      ESD HBM:                      ±2000 V
      Wake pulse min duration:      17 us
      Inter-byte timeout:           36 us

    Display interface:
      Maximum resolution:           1920x1080 (Full HD)
    """
    tokens = _harvest(text)
    # False-positives must NOT appear:
    for bad in (
        "2016.06 V", "2016.06V", "2016.09 V", "2018.10 V",
        "0x1080", "0x1920",
    ):
        assert bad not in tokens, (
            f"Integration FAIL: {bad!r} should have been rejected "
            f"by v1.6.50 regex tightening. tokens={sorted(tokens)}"
        )
    # Legitimate facts still present:
    expected = ("3.3 V", "6.1 V", "2000 V", "17 us", "36 us")
    for good in expected:
        assert good in tokens, (
            f"Integration FAIL: real fact {good!r} dropped. "
            f"tokens={sorted(tokens)}"
        )
