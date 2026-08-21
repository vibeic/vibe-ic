"""tests/test_render_humanizer_hz_trailing_zero.py — v1.6.304

Closes ORGANIC #204 round-2 NOT VERIFIED: v1.6.303 fixed the
`_humanize_value` integer-shortcut for FLOAT-typed inputs but did NOT
address `_humanize_hz`, which is a separate auto-scaling path called
for `_hz` suffix fields. Field-agent darkriscv pass-12 evidence:
source `100.0MHz` → extractor stores `clock_frequency_hz: 100_000_000`
(int Hz) → `_humanize_hz(100_000_000)` returned `"100 MHz"` (no `.0`)
→ source token `"100.0MHz"` still in `missing_sample`.

Fix (v1.6.304): mirror the v1.6.303 trailing-`.0` preservation logic
in `_humanize_hz`. When the Hz value divides cleanly into GHz/MHz/kHz,
emit the scaled value with explicit `.0` suffix:
  * `1_000_000_000` Hz → `"1.0 GHz"` (was `"1 GHz"`)
  * `100_000_000` Hz   → `"100.0 MHz"` (was `"100 MHz"`)
  * `8_000` Hz         → `"8.0 kHz"` (was `"8 kHz"`)

The bare-Hz path (sub-kHz values like `50` Hz) is UNCHANGED — Hz
values are rarely written with explicit decimal precision in source
docs, so the integer-shortcut stays for that path.

Chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.phase1_engine.render import _humanize_hz, _humanize_value  # noqa: E402


# ------------------------------------------------------------------
# v1.6.304 — Divisible-MHz/GHz/kHz preserves `.0`
# ------------------------------------------------------------------

def test_v1_6_304_field_agent_darkriscv_100mhz_evidence() -> None:
    """Field-agent darkriscv pass-12 cross-IC evidence: source
    `100.0MHz` → `_humanize_hz(100_000_000)` must produce
    `"100.0 MHz"` (was `"100 MHz"`)."""
    assert _humanize_hz(100_000_000) == "100.0 MHz"


def test_v1_6_304_divisible_ghz_preserves_decimal() -> None:
    """`1_000_000_000` Hz → `"1.0 GHz"`."""
    assert _humanize_hz(1_000_000_000) == "1.0 GHz"


def test_v1_6_304_divisible_khz_preserves_decimal() -> None:
    """`8_000` Hz → `"8.0 kHz"`."""
    assert _humanize_hz(8_000) == "8.0 kHz"


def test_v1_6_304_25mhz_preserves_decimal() -> None:
    """`25_000_000` Hz → `"25.0 MHz"`."""
    assert _humanize_hz(25_000_000) == "25.0 MHz"


def test_v1_6_304_50khz_preserves_decimal() -> None:
    """`50_000` Hz → `"50.0 kHz"`."""
    assert _humanize_hz(50_000) == "50.0 kHz"


def test_v1_6_304_float_input_also_preserves() -> None:
    """`100_000_000.0` (float input) — same result as int."""
    assert _humanize_hz(100_000_000.0) == "100.0 MHz"


# ------------------------------------------------------------------
# v1.6.304 — Non-divisible values use :g formatting (unchanged)
# ------------------------------------------------------------------

def test_v1_6_304_kHz_divisible_path_still_picks_lowest_scale() -> None:
    """Pre-existing behavior: `100_500_000` Hz is divisible by 1e3
    but NOT 1e6, so the divisible-kHz path fires before the
    g-formatted-MHz path. v1.6.304 only ADDS `.0` to the existing
    divisible paths — does NOT change which path wins."""
    assert _humanize_hz(100_500_000) == "100500.0 kHz"


def test_v1_6_304_truly_non_divisible_mhz_uses_g_format() -> None:
    """`1_234_567` Hz — not divisible by 1e3/1e6/1e9; falls through
    to `:g` MHz path."""
    assert _humanize_hz(1_234_567) == "1.23457 MHz"


def test_v1_6_304_non_divisible_khz_uses_g_format() -> None:
    """`8_500` Hz IS divisible by 1e3, so takes the divisible path."""
    assert _humanize_hz(8_500) == "8.5 kHz"


# ------------------------------------------------------------------
# v1.6.304 — Bare-Hz path unchanged
# ------------------------------------------------------------------

def test_v1_6_304_sub_khz_bare_hz_no_decimal_suffix() -> None:
    """`50` Hz (sub-kHz) stays in Hz with bare-int format.
    v1.6.304 only changes the divisible-scaled-unit paths."""
    assert _humanize_hz(50) == "50 Hz"


def test_v1_6_304_sub_khz_float_no_decimal_suffix() -> None:
    """`50.0` Hz (float, integer-valued, sub-kHz). The `int(v) if
    v.is_integer() else v` shortcut emits `"50 Hz"` — bare-Hz path
    is unchanged from pre-v1.6.304 (Hz values rarely encode
    decimal precision in source docs)."""
    assert _humanize_hz(50.0) == "50 Hz"


# ------------------------------------------------------------------
# v1.6.304 — End-to-end via `_humanize_value("*_hz", N)`
# ------------------------------------------------------------------

def test_v1_6_304_humanize_value_hz_suffix_calls_humanize_hz() -> None:
    """`_humanize_value("clock_frequency_hz", 100_000_000)` dispatches
    to `_humanize_hz` and now produces `"100.0 MHz"`."""
    assert _humanize_value(
        "clock_frequency_hz", 100_000_000
    ) == "100.0 MHz"


def test_v1_6_304_humanize_value_hz_suffix_int_50mhz() -> None:
    """`50_000_000` Hz → `"50.0 MHz"` via `_humanize_value` →
    `_humanize_hz`."""
    assert _humanize_value(
        "system_clock_hz", 50_000_000
    ) == "50.0 MHz"
