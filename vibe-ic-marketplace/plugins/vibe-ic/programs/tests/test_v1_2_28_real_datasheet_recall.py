"""Real-datasheet recall + precision fixes for the Phase-1 facet extractors.

Running real datasheets (a mixed-signal ADC, a RISC-V SoC, a crypto core) through
spec_complete_extract.assess_spec surfaced two classes of defect the synthetic
self-tests missed — fixed here and pinned with the real discriminating lines:

  PRECISION — spec_otp_extract bound EVERY "register" in a multi-section design
    doc to a doc-wide OTP mention, even a NEGATED N/A one ("無 OTP-based
    calibration"): a digital SoC scored 9 phantom OTP fields, a SHA-256 core 17.
    Fixed with a LOCAL, negation-aware anchor (an otp_field needs a non-negated
    OTP/fuse token within ~160 chars).

  RECALL — real datasheets state specs in MARKDOWN TABLES (`| fclk | 1.0 | … |
    MHz |`) and name converter ARCHITECTURES ("delta-sigma") / pin RANGES
    ("`IN1..IN6`"), none of which the prose-adjacency passes caught. Added: a
    spec-table-row pass + corner-temperature slash-list + Unicode-minus
    normalization (electrical); broadened converter vocabulary + a words-between
    channel count + plural pad nouns + a `..`-safe clause splitter (analog).
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_otp_extract as OTP            # noqa: E402
import spec_electrical_extract as ELEC    # noqa: E402
import spec_analog_iface_extract as ANA   # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_ADC = str(corpus_path("u_hawaii_adc_e2e_v034/input/docs"))


def _kinds(items):
    return {d["kind"] for d in items}


# ── PRECISION: OTP must not bind a register to a negated / far OTP mention ──
def test_otp_no_false_field_from_negated_na_section():
    # the real subservient L6 N/A shape: an OTP mention in an N/A section + a
    # "register file" far away must mint NO otp_field.
    doc = ("# L2 Architecture\nThe core uses a shared register file (RF) and a "
           "chip-level configuration register.\n\n"
           "# L6 Calibration\nstatus: not-applicable\n無 trimming. 無 OTP-based "
           "calibration. 無 analog bias adjustment.\n")
    assert OTP.extract(doc) == []


def test_otp_still_fires_on_real_local_otp_field():
    # a genuine local OTP field is still recovered (no over-correction)
    it = OTP.extract("The 32-bit OTP fuse bank holds a trim_code field at offset 0x10.")
    assert "otp_field" in _kinds(it)


# ── RECALL: electrical spec tables + corner-temp list + Unicode minus ──
def test_electrical_table_rows_recovered():
    tbl = ("| Spec | Target | Range | Unit |\n"
           "| fclk | 1.0 | 0.1–10 | MHz |\n"
           "| Iout | 0.5 | 0.1–1.0 | mA |\n"
           "| Vdd (core) | 1.2 | 1.1–1.3 | V |\n"
           "The modulator clock and core supply current budget above.")
    k = _kinds(ELEC.extract(tbl))
    assert {"clock_frequency", "current_spec", "supply_voltage"} <= k


def test_electrical_corner_temp_list_with_unicode_minus():
    # the real ADC corner list uses a Unicode minus (U+2212) and a slash list
    it = [d for d in ELEC.extract("Multi-corner: TT/SS/FF × −40/27/125 °C.")
          if d["kind"] == "temperature_range"]
    assert it and it[0]["lo"] == -40.0 and it[0]["hi"] == 125.0


def test_electrical_prose_still_works():
    k = _kinds(ELEC.extract("Runs at 100 MHz from a 1.8 V supply, draws 5 mA."))
    assert {"clock_frequency", "supply_voltage", "current_spec"} <= k


# ── RECALL: analog converter architecture + channel array + pin-range pad ──
def test_analog_converter_architecture_and_channel_array():
    it = ANA.extract("An array of 6 incremental delta-sigma modulator channels.")
    assert "analog_converter" in _kinds(it)
    conv = next(d for d in it if d["kind"] == "analog_converter")
    assert conv.get("channels") == 6


def test_analog_pad_pin_range_syntax():
    # `IN1..IN6` (range inside one backtick) must not be severed by the splitter
    it = ANA.extract("- Analog inputs `IN1..IN6` (PAD), differential referenced "
                     "to `VHI`/`VLO`.")
    assert "analog_pad" in _kinds(it)


def test_analog_negative_unchanged():
    assert ANA.extract("Design a digital UART.") == []


# ── end-to-end on the real ADC datasheet (skip if the corpus is absent) ──
def test_real_adc_datasheet_facet_recall():
    files = sorted(glob.glob(os.path.join(_ADC, "*.md")))
    if not files:
        pytest.skip("ADC datasheet corpus absent")
    doc = "\n\n".join(open(f, errors="ignore").read() for f in files)
    import spec_complete_extract as SCE
    st = SCE.assess_spec(doc, [], [], module_name="u_hawaii_adc")["structures"]
    # analog: converter + reference_voltage + analog_pad all recovered
    assert {d["kind"] for d in st["analog_interface"]} == {
        "analog_converter", "reference_voltage", "analog_pad"}
    # electrical: clock + supply + current + temperature all recovered
    ek = {d["kind"] for d in st["electrical"]}
    assert {"clock_frequency", "supply_voltage", "current_spec",
            "temperature_range"} <= ek
    # precision: this digital-light analog datasheet has NO OTP fields
    assert st["otp"] == []
