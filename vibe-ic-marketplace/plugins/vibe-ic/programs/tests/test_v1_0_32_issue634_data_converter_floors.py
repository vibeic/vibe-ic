"""Partial (gate-side) progress for ORGANIC #634 — the Phase-1 typed-field gate
(l_doc_structured_field_count_check) had no data-converter-class coverage, so a
legitimate data-converter / mixed-signal IC FAILed the L5 (≥3 analog blocks)
and L8 (≥10 timing constants) protocol-genre floors with no class relaxation —
a no-waiver, unrecoverable FAIL.

This change ships the GATE-SIDE class coverage (issue facets b + c):
  * registry: data_converter gains `sparse_control_timing: true` (→ relaxed L8
    ≥3 / L6 ≥2 floors, the same treatment the other sparse-compute classes
    already get) and `sparse_analog_block_set: true`;
  * `_class_sparse_analog_blocks` + an IC-class-aware L5 floor: a class flagged
    `sparse_analog_block_set` gets ≥2 typed analog blocks (a delta-sigma ADC =
    modulator + on-chip regulator/reference is a legitimate 2-block set)
    instead of the strict ≥3.

NEGATIVE no-leak (load-bearing — this RELAXES floors): the relaxation is a REAL
floor, never a skip — an empty / 0-block / 1-block analog doc still FAILs; and
a class NOT flagged in the registry (unknown, mixed_signal_otp, a multi-block
analog system) keeps the strict ≥3 floor. bare_fpga / unknown stay
fail-closed.

NOTE (residual): the GENERATION-side extraction facets (a: L8 spec-table
fclk/OSR/order timing harvest; d: L7/L10 "Verification intent" bullet harvest;
e: L12 no_calibration auto-set) are tracked as the remaining work on #634 — a
content-rich converter whose docs are populated now clears L5/L8, but the
extraction that POPULATES sparse L7/L10/L12 docs is a separate generation-side
change. This test pins the gate-side floors only.

chip-AGNOSTIC: registry semantic flags + numeric floors; no chip/vendor/SKU
literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l_doc_structured_field_count_check as G  # noqa: E402


def _l5(n_blocks, ic_class):
    return G._check_l_doc(
        5, {"analog_blocks": [{"type": f"b{i}"} for i in range(n_blocks)]},
        ic_class=ic_class)[0]


# ── (1) the fix: data_converter L5 ≥2 / L8 ≥3 ────────────────────────────────

def test_data_converter_l5_floor_relaxed_to_two():
    assert _l5(2, "data_converter") is True
    assert _l5(3, "data_converter") is True


def test_registry_flags_present():
    assert G._class_sparse_analog_blocks("data_converter") is True
    assert G._class_sparse_control_timing("data_converter") is True


def test_data_converter_l8_floor_relaxed_to_three():
    # 3 sparse timing constants (fclk / OSR / order) clear the relaxed ≥3 floor
    ok, _ = G._check_l_doc(
        8, {"timing_constants": [{"k": "fclk"}, {"k": "osr"}, {"k": "order"}]},
        ic_class="data_converter")
    assert ok is True


# ── (2) NEGATIVE no-leak ─────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [0, 1])
def test_data_converter_under_two_blocks_still_fails_NOLEAK(n):
    assert _l5(n, "data_converter") is False


@pytest.mark.parametrize("ic_class", ["unknown", "mixed_signal_otp",
                                      "pure_analog"])
def test_non_flagged_class_keeps_strict_three_NOLEAK(ic_class):
    """A class NOT flagged sparse_analog_block_set keeps the strict ≥3 floor —
    a multi-block analog system must still carry ≥3."""
    assert _l5(2, ic_class) is False
    assert _l5(3, ic_class) is True


def test_bare_fpga_fail_closed_NOLEAK():
    assert G._class_sparse_analog_blocks("bare_fpga") is False
    assert G._class_sparse_analog_blocks("unknown_protocol_class") is False


def test_data_converter_l8_two_consts_still_below_floor_NOLEAK():
    """The L8 floor is still a REAL floor: 2 timing constants (< the relaxed
    ≥3) still FAILs — the relaxation does not let an under-populated timing doc
    pass."""
    ok, _ = G._check_l_doc(
        8, {"timing_constants": [{"k": "a"}, {"k": "b"}]},
        ic_class="data_converter")
    assert ok is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
