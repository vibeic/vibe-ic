"""tests/test_render_humanizer_per_denominator.py — v1.6.300

Closes the ORGANIC #201 follow-on to #144: the v1.6.280 humanizer
extension (adding engineering-suffix coverage to `_UNIT_SUFFIX_HUMAN`)
inadvertently catches per-denominator ratio fields whose keys carry
the unit token in the suffix family. Real-benchmark evidence:

  * `coremarks_per_mhz: 0.95`  → wrongly rendered "0.95 MHz"
  * `dmips_per_mhz: 0.516`     → wrongly rendered "0.516 MHz"
  * `samples_per_ms: 100`      → wrongly rendered "100 ms"

These are dimensionless ratio-class fields (numerator / denominator-unit),
not absolute-value fields whose unit is the suffix.

Fix (v1.6.300): one-line veto inside `_humanize_value` rejecting any
key whose lowercase form contains the substring `_per_`. Regression
guard: bona-fide `freq_mhz` / `period_ns` / `size_bytes` fields still
get their `_human` sibling (the v1.6.280 #144 contract is preserved).

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
# v1.6.300 — REJECT ratio keys
# ------------------------------------------------------------------

def test_v1_6_300_coremarks_per_mhz_no_human() -> None:
    """`coremarks_per_mhz: 0.95` is a CoreMark / MHz ratio score —
    NOT a frequency in MHz. No humanizer sibling."""
    assert _humanize_value("coremarks_per_mhz", 0.95) is None


def test_v1_6_300_dmips_per_mhz_no_human() -> None:
    """`dmips_per_mhz: 0.516` is a DMIPS / MHz ratio."""
    assert _humanize_value("dmips_per_mhz", 0.516) is None


def test_v1_6_300_mips_per_mhz_no_human() -> None:
    assert _humanize_value("mips_per_mhz", 1.6) is None


def test_v1_6_300_samples_per_ms_no_human() -> None:
    """`samples_per_ms: 100` is a sample rate per millisecond ratio —
    NOT a duration in ms."""
    assert _humanize_value("samples_per_ms", 100) is None


def test_v1_6_300_instructions_per_sec_per_mhz_no_human() -> None:
    """`per_sec_per_mhz` compound denominator — instructions/sec/MHz."""
    assert _humanize_value("instructions_per_sec_per_mhz", 908) is None


def test_v1_6_300_energy_per_ns_no_human() -> None:
    assert _humanize_value("energy_per_ns", 0.001) is None


def test_v1_6_300_power_per_mhz_no_human() -> None:
    """Even when the value would round to an integer."""
    assert _humanize_value("power_per_mhz", 5) is None


# ------------------------------------------------------------------
# v1.6.300 — REGRESSION GUARD: #144 contract preserved
# ------------------------------------------------------------------

def test_v1_6_300_regression_freq_mhz_still_humanized() -> None:
    """v1.6.280 #144 contract: `freq_mhz: 100` → `"100 MHz"`."""
    assert _humanize_value("freq_mhz", 100) == "100 MHz"


def test_v1_6_300_regression_clock_mhz_still_humanized() -> None:
    """v1.6.303 — for #204 contract update: float-typed
    integer-valued inputs now preserve the `.0` for haystack
    fidelity. Previously this rendered as `"50 MHz"`."""
    assert _humanize_value("clock_mhz", 50.0) == "50.0 MHz"


def test_v1_6_300_regression_period_ns_still_humanized() -> None:
    assert _humanize_value("period_ns", 10) == "10 ns"


def test_v1_6_300_regression_freq_ghz_still_humanized() -> None:
    assert _humanize_value("max_freq_ghz", 3) == "3 GHz"


def test_v1_6_300_regression_freq_khz_still_humanized() -> None:
    assert _humanize_value("sample_rate_khz", 44) == "44 kHz"


# ------------------------------------------------------------------
# v1.6.300 — Edge cases
# ------------------------------------------------------------------

def test_v1_6_300_uppercase_per_token_also_rejected() -> None:
    """`_PER_` uppercase should also be caught — `_humanize_value`
    lowercases internally for matching."""
    assert _humanize_value("DMIPS_PER_MHZ", 0.5) is None


def test_v1_6_300_underscore_per_underscore_substring_required() -> None:
    """The veto matches the EXACT substring `_per_` — both
    underscores required (otherwise common roots like `super_mhz`
    would falsely demote). `nominal_per_mhz` (internal `_per_`) is
    rejected; `super_mhz` (no underscore separator) is not."""
    assert _humanize_value("nominal_per_mhz", 1.0) is None
    # v1.6.303 — for #204 contract update: float-typed values
    # preserve `.0`; was `"1 MHz"`.
    assert _humanize_value("super_mhz", 1.0) == "1.0 MHz"


def test_v1_6_300_per_not_surrounded_by_underscores_not_rejected() -> None:
    """`super_mhz` does NOT contain `_per_` substring — humanizer
    should NOT reject (it's a regular `_mhz` suffix key). Note: this
    is a synthetic edge case; real benchmark wouldn't produce this,
    but the veto rule's precision matters."""
    # "super_mhz" contains "per_mhz" but NOT "_per_" — should still
    # humanize as MHz value.
    assert _humanize_value("super_mhz", 100) == "100 MHz"
