"""tests/test_render_humanizer_trailing_zero.py — v1.6.303

Closes ORGANIC #204: the v1.6.280 (#144) humanizer's `value.is_integer()`
integer-shortcut collapsed float-typed integer-valued inputs
(`2.0`, `100.0`) to display form without `.0` (`"2 ns"`, `"100 MHz"`),
dropping the trailing-zero suffix that source datasheets / READMEs
encode in decimal-precision form. Coverage gate then logged the
source token (`"2.0 ns"`, `"100.0 MHz"`) as missing while the
rendered `_human` sibling was unfingerprintable.

Field-agent's cross-IC evidence:
  * picorv32 pass-11 iter=87:  `clock_period_ns=2.0` → `"2 ns"`
  * darkriscv pass-12 iter=98: `100.0MHz` source     → `"100 MHz"`
  * picorv32 pass-12 iter=104: TWO `clock_period_ns=2.0` rows
                                                    → `"2 ns"` (deterministic)

Fix (v1.6.303): drop the integer-shortcut entirely. Always emit
`f"{value} {unit}"` for typed values. Python's default float repr
preserves `.0` for integer-valued floats (`2.0`, `100.0`), so source
fidelity is restored. Integer-typed inputs (`int(100)`) still render
without `.0` — only float-typed values keep their format.

Trade-off accepted: integer-valued floats no longer display as
`"2 ns"` (lost prettiness) but DO match source-faithful `"2.0 ns"`
form (gained haystack fidelity). The display loss is intentional;
the source author's `.0` is a precision-of-spec signal, not noise.

Chip-AGNOSTIC.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.phase1_engine.render import _humanize_value  # noqa: E402


# ------------------------------------------------------------------
# v1.6.303 — Integer-valued floats preserve `.0`
# ------------------------------------------------------------------

def test_v1_6_303_clock_period_ns_2_dot_0_preserves_decimal() -> None:
    """Field-agent picorv32 evidence: `clock_period_ns=2.0` (float)
    must render as `"2.0 ns"` (source-faithful), not `"2 ns"`."""
    assert _humanize_value("clock_period_ns", 2.0) == "2.0 ns"


def test_v1_6_303_clock_mhz_100_dot_0_preserves_decimal() -> None:
    """Field-agent darkriscv evidence: `100.0MHz` source must
    fingerprint as `"100.0 MHz"`, not `"100 MHz"`."""
    assert _humanize_value("clock_mhz", 100.0) == "100.0 MHz"


def test_v1_6_303_voltage_v_1_dot_0_preserves_decimal() -> None:
    """`1.0 V` voltage rail (common datasheet form)."""
    assert _humanize_value("supply_v", 1.0) == "1.0 V"


def test_v1_6_303_voltage_v_5_dot_0_preserves_decimal() -> None:
    """`5.0 V` voltage rail."""
    assert _humanize_value("max_voltage_v", 5.0) == "5.0 V"


def test_v1_6_303_current_ma_5_dot_0_preserves_decimal() -> None:
    """`5.0 mA` current spec line."""
    assert _humanize_value("typical_current_ma", 5.0) == "5.0 mA"


def test_v1_6_303_period_us_50_dot_0_preserves_decimal() -> None:
    """`50.0 us` spec-line timing window."""
    assert _humanize_value("startup_time_us", 50.0) == "50.0 us"


# ------------------------------------------------------------------
# v1.6.303 — Non-integer-valued floats unchanged (regression guard)
# ------------------------------------------------------------------

def test_v1_6_303_clock_period_ns_2_dot_4_unchanged() -> None:
    """Non-integer-valued float `2.4` already renders correctly."""
    assert _humanize_value("clock_period_ns", 2.4) == "2.4 ns"


def test_v1_6_303_supply_v_3_dot_3_unchanged() -> None:
    """v1.6.271 regression — `3.3 V` is a non-integer-valued float."""
    assert _humanize_value("supply_v", 3.3) == "3.3 V"


def test_v1_6_303_clock_ns_1_dot_5_unchanged() -> None:
    assert _humanize_value("clock_period_ns", 1.5) == "1.5 ns"


# ------------------------------------------------------------------
# v1.6.303 — Integer-typed inputs unchanged (no `.0` suffix)
# ------------------------------------------------------------------

def test_v1_6_303_int_typed_100_no_decimal_suffix() -> None:
    """Integer-typed `100` (not `100.0`) renders without `.0`."""
    assert _humanize_value("freq_mhz", 100) == "100 MHz"


def test_v1_6_303_int_typed_50_no_decimal_suffix() -> None:
    """v1.6.280 contract preserved for int-typed inputs."""
    assert _humanize_value("clock_mhz", 50) == "50 MHz"


def test_v1_6_303_int_typed_zero_no_decimal_suffix() -> None:
    assert _humanize_value("offset_ms", 0) == "0 ms"


def test_v1_6_303_int_typed_416_v1_6_280_contract() -> None:
    """v1.6.280 #144 test case — `clock_mhz: 416` (int) → `"416 MHz"`."""
    assert _humanize_value("clock_mhz", 416) == "416 MHz"


# ------------------------------------------------------------------
# v1.6.303 — Ratio rejection still wins over decimal preservation
# ------------------------------------------------------------------

def test_v1_6_303_ratio_per_mhz_still_rejected() -> None:
    """v1.6.300 #201 contract preserved — `_per_` veto fires first,
    `dmips_per_mhz: 0.5` still returns None."""
    assert _humanize_value("dmips_per_mhz", 0.5) is None


def test_v1_6_303_ratio_per_mhz_integer_float_also_rejected() -> None:
    """Edge case: `mips_per_mhz: 2.0` — integer-valued float, but
    `_per_` veto still fires before suffix-match."""
    assert _humanize_value("mips_per_mhz", 2.0) is None


# ------------------------------------------------------------------
# v1.6.303 — `_hz` autoscaling unaffected
# ------------------------------------------------------------------

def test_v1_6_303_clock_frequency_hz_100M_still_autoscales() -> None:
    """`clock_frequency_hz: 100_000_000.0` should still autoscale to
    MHz via `_humanize_hz` — bypass the suffix-match emit path."""
    # 100_000_000.0 / 1e6 == 100.0 → expected display depends on the
    # _humanize_hz helper which is NOT affected by v1.6.303. Verify
    # it still produces a sensible MHz form.
    result = _humanize_value("clock_frequency_hz", 100_000_000.0)
    assert result is not None
    assert "MHz" in result or "GHz" in result or "kHz" in result
