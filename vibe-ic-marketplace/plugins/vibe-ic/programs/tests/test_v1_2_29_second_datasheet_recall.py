"""Second mixed-signal datasheet (SAR ADC + PGA + I2C + bandgap reference) recall.

A second, architecturally-DIFFERENT mixed-signal datasheet — a 16-bit SAR ADC with
a programmable-gain amp, I2C, and an internal bandgap reference — stresses analog
vocabulary the delta-sigma ADC did not exercise. It surfaced one recall gap and one
precision blemish, fixed here:

  RECALL — `reference_voltage` stated in a TABLE (`| Vref (internal) | 2.048 | … |
    V |`) and as "bandgap `REF` = 2.048 V" was missed (the Vref detector was
    prose-adjacency only, and "bandgap" was not a reference token). Added a
    markdown reference-table row pass + the "bandgap" token.

  PRECISION — that 2.048 V reference was mis-labeled a `supply_voltage`, and an ADC
    full-scale input row (`| Vin (FS, diff) | ±2.048 | … | V |`) was read as a
    supply rail. Added a reference-context skip + a full-scale/input-range
    exclusion to the supply passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_analog_iface_extract as ANA   # noqa: E402
import spec_electrical_extract as ELEC    # noqa: E402


def _kinds(items):
    return {d["kind"] for d in items}


# ── reference_voltage RECALL ──
def test_vref_table_row_recovered():
    it = ANA.extract("| Spec | Target | Range | Unit |\n"
                     "| Vref (internal) | 2.048 | — | V |\n")
    refs = [d for d in it if d["kind"] == "reference_voltage"]
    assert refs and refs[0]["value"] == "2.048 V"


def test_bandgap_prose_is_reference():
    it = ANA.extract("Internal bandgap `REF` = 2.048 V supplies the converter.")
    assert "reference_voltage" in _kinds(it)


def test_vref_table_needs_all_three_cells():
    # §4.05: a ref-name row with no numeric or no unit cell mints nothing
    assert ANA.extract("| Vref | internal | — | — |") == []
    assert ANA.extract("| Vref | 2.048 | — | — |") == []   # no unit cell


# ── supply PRECISION (reference / full-scale are NOT supplies) ──
def test_reference_value_not_counted_as_supply():
    it = ELEC.extract("Internal bandgap REF = 2.048 V; the 3.3 V supply rail.")
    sup = sorted(d["value"] for d in it if d["kind"] == "supply_voltage")
    assert 2.048 not in sup and 3.3 in sup


def test_full_scale_input_row_not_supply():
    it = ELEC.extract("| AVDD (supply) | 3.3 | — | V |\n"
                      "| Vin (FS, diff) | 2.048 | — | V |\n")
    sup = sorted(d["value"] for d in it if d["kind"] == "supply_voltage")
    assert sup == [3.3]   # full-scale input row excluded


def test_normal_supply_prose_unchanged():
    it = ELEC.extract("The core runs from a 1.8 V supply.")
    assert [d["value"] for d in it if d["kind"] == "supply_voltage"] == [1.8]


# ── the SAR datasheet's own facet set (inline, corpus-free) ──
_SAR_L5 = """
# L5 — Analog Spec
## Block A — `sar_adc` : 16-bit successive-approximation ADC
| Spec | Target | Range | Unit |
| converter_type | successive-approximation (SAR) | — | — |
| resolution | 16 | — | bit |
| channels | 4 | 1–4 | — |
| Vref (internal) | 2.048 | — | V |
| fclk | 1.0 | — | MHz |
- Analog inputs `AIN0..AIN3` (PAD), single-ended or differential.
- Internal bandgap `REF` = 2.048 V; quiescent current Iq ≤ 150 µA.
Multi-corner: TT/SS/FF × −40/25/85 °C.
"""


def test_sar_datasheet_analog_and_electrical_recall():
    a = _kinds(ANA.extract(_SAR_L5))
    assert {"analog_converter", "reference_voltage", "analog_pad"} <= a
    e = _kinds(ELEC.extract(_SAR_L5))
    assert {"clock_frequency", "current_spec", "temperature_range"} <= e
    # precision: no OTP / calibration / test-debug / signedness fabricated
    import spec_otp_extract, spec_calibration_extract, spec_test_debug_extract, spec_signedness_extract
    assert spec_otp_extract.extract(_SAR_L5) == []
    assert spec_calibration_extract.extract(_SAR_L5) == []
    assert spec_test_debug_extract.extract(_SAR_L5) == []
    assert spec_signedness_extract.extract(_SAR_L5) == []
