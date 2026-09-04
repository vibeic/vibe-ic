"""Phase-1 GENERAL facet extractors — close the L-doc completeness gaps.

A survey of the Phase-1 recognizer/extractor coverage found six facets with NO
dedicated, general-purpose structural extractor (only the unified table tier or
the LLM): L5 analog/digital interface, L7 test/debug, L11 OTP, L13 lab
calibration, per-signal signedness, and clock-frequency/electrical specs.

This adds one GENERAL `spec_<facet>_extract.py` per gap (chip-AGNOSTIC,
§4.05-no-leak, `extract(text)->[ChecklistItem dict]`, [] when no structural
anchor) and wires all six into `spec_coverage_check._CVDP_EXTRACTORS` so the
spec-coverage checklist now carries these facets for ANY design doc — the
benchmark-convergence engine and the general Phase-1 path both benefit.

Each extractor is tested for: (1) a positive doc emits the expected kinds with
the right ChecklistItem shape, (2) a §4.05 negative (topic absent OR a bare
keyword with no structural qualifier) returns []. A final union test proves all
new kinds surface through `spec_coverage_check.extract_checklist`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_analog_iface_extract as ANALOG   # noqa: E402
import spec_test_debug_extract as TESTDBG    # noqa: E402
import spec_otp_extract as OTP               # noqa: E402
import spec_calibration_extract as CAL       # noqa: E402
import spec_signedness_extract as SIGN       # noqa: E402
import spec_electrical_extract as ELEC       # noqa: E402
import spec_coverage_check as COV            # noqa: E402


def _kinds(items):
    return sorted({d["kind"] for d in items})


def _shape_ok(items):
    return all(isinstance(d, dict) and d.get("kind") and d.get("requirement")
               and isinstance(d.get("coverage_tokens", []), list) for d in items)


# ── L5 analog/digital interface ──
def test_analog_positive_and_shape():
    it = ANALOG.extract("A 12-bit ADC with 8 channels samples the sensor. "
                        "Vref = 2.5 V. The analog input pin ain feeds the front-end.")
    assert _shape_ok(it)
    assert {"analog_converter", "reference_voltage", "analog_pad"} <= set(_kinds(it))


def test_analog_noleak():
    assert ANALOG.extract("Design a digital UART.") == []
    # bare keywords with no structural qualifier
    assert ANALOG.extract("It is analog in nature.") == []
    assert ANALOG.extract("The ADC result is stored.") == []  # no resolution/channel/rate


def test_digital_instruction_pipeline_is_not_an_adc():
    prompt = (
        "The 32-bit fetched instruction data enters the processor pipeline "
        "from instruction memory."
    )
    assert not any(d["kind"] == "analog_converter"
                   for d in ANALOG.extract(prompt))


def test_pipelined_adc_remains_an_explicit_converter_architecture():
    items = ANALOG.extract("A 12-bit pipelined ADC converts the analog input.")
    converters = [d for d in items if d["kind"] == "analog_converter"]
    assert len(converters) == 1
    assert converters[0]["converter"] == "ADC"
    assert converters[0]["resolution"] == 12
    assert converters[0]["coverage_tokens"] == ["adc", "12"]


# ── L7 test/debug ──
def test_testdebug_positive():
    it = TESTDBG.extract("The chip has a JTAG TAP (TMS,TCK,TDI,TDO), a scan chain "
                        "with scan_en, MBIST, and a test_mode pin.")
    assert _shape_ok(it)
    assert {"scan_chain", "jtag_tap", "bist", "test_mode"} <= set(_kinds(it))


def test_testdebug_noleak_bare_scan_verb():
    # the ordinary verb "scan" must NOT mint a DFT scan_chain
    assert TESTDBG.extract("Scan the input bus and add the values.") == []
    assert TESTDBG.extract("Design a counter.") == []


# ── L11 OTP ──
def test_otp_positive():
    it = OTP.extract("The 32-bit OTP fuse bank holds a trim_code field at offset "
                    "0x10. A write-once lock bit prevents reprogramming.")
    assert _shape_ok(it)
    assert {"otp_field", "otp_lock"} <= set(_kinds(it))


def test_otp_noleak_fuse_verb():
    assert OTP.extract("Add a 32-bit register.") == []
    assert OTP.extract("Fuse the two clock domains together.") == []  # verb, not OTP


# ── L13 lab calibration ──
def test_calibration_positive():
    it = CAL.extract("An 8-bit trim_code register at offset 0x4 sets the oscillator. "
                    "Calibration step 1 measures the reference.")
    assert _shape_ok(it)
    assert {"calibration_field", "calibration_procedure"} <= set(_kinds(it))


def test_calibration_noleak_trim_verb():
    assert CAL.extract("Trim trailing whitespace from the string.") == []
    assert CAL.extract("Compute the average.") == []


# ── per-signal signedness (extend-not-duplicate) ──
_SIGN_DOC = """## Ports
- input signed [15:0] coeff
- input wire [15:0] din
- output reg [31:0] acc
The signed [15:0] coeff multiplies din. operand acc is treated as two's complement.
"""


def test_signedness_positive_named_signal():
    it = SIGN.extract(_SIGN_DOC)
    assert _shape_ok(it)
    assert _kinds(it) == ["signed_operand"]
    toks = " ".join(t for d in it for t in d.get("coverage_tokens", []))
    assert "coeff" in toks and "acc" in toks


def test_signedness_noleak_bare_topic():
    # bare topic with no NAMED signal is spec_coverage_check's coarse kind, not ours
    assert SIGN.extract("Perform signed arithmetic.") == []
    assert SIGN.extract("Add two numbers.") == []


def test_signedness_noleak_common_noun_after_keyword():
    # §4.05: a common noun following signed/unsigned ("unsigned integers", an
    # "unsigned add" title) is NOT a declared signal -> must mint nothing.
    leak = SIGN.extract("# adder — unsigned add\n"
                        "Computes modular arithmetic of unsigned integers.\n"
                        "## Ports\n- input wire [7:0] a\n- output wire [8:0] y\n")
    assert leak == [], leak


# ── clock-frequency + electrical ──
def test_electrical_positive():
    it = ELEC.extract("The core runs at 100 MHz from a 1.8 V supply, drawing 5 mA, "
                      "over -40°C to 125°C. Output slew rate is 2 V/ns.")
    assert _shape_ok(it)
    assert {"clock_frequency", "supply_voltage", "current_spec",
            "temperature_range", "slew_rate"} <= set(_kinds(it))


def test_electrical_noleak_bare_number():
    assert ELEC.extract("Multiply two 8-bit numbers.") == []
    assert ELEC.extract("The value is 100.") == []  # number, no unit/context


# ── union through the aggregator ──
_UNION_DOC = """
Design a mixed-signal controller msc.
A 12-bit ADC with 8 channels samples the input. Vref = 2.5 V. The analog input pin ain feeds the front-end.
It has a JTAG TAP (TMS, TCK, TDI, TDO), a scan chain with scan_en, MBIST, and a test_mode pin.
A 32-bit OTP fuse bank holds a trim_code field at offset 0x10; a write-once lock bit prevents reprogramming.
An 8-bit cal_code register at offset 0x4 calibrates the oscillator. Calibration step 1 measures the reference.
The signed [15:0] coeff multiplies din.
The core runs at 100 MHz from a 1.8 V supply, drawing 5 mA, operating temperature -40 to 125 degC. Output slew rate is 2 V/ns.
"""
_NEW_KINDS = {
    "analog_converter", "reference_voltage", "analog_pad",
    "scan_chain", "jtag_tap", "bist", "test_mode",
    "otp_field", "otp_lock", "calibration_field", "calibration_procedure",
    "signed_operand", "clock_frequency", "supply_voltage", "current_spec",
    "temperature_range", "slew_rate",
}


def test_all_new_kinds_surface_through_checklist():
    kinds = {it.kind for it in COV.extract_checklist(_UNION_DOC)}
    missing = _NEW_KINDS - kinds
    assert not missing, f"new facet kinds not surfaced by extract_checklist: {sorted(missing)}"


def test_new_kinds_are_non_blocking_prose_heuristic():
    # additive coverage facets must be registered as prose-heuristic (non-blocking
    # unless RTL corroborates) so they never spuriously BLOCK an emit.
    assert _NEW_KINDS <= COV._PROSE_HEURISTIC_KINDS


def test_empty_doc_adds_no_facets():
    kinds = {it.kind for it in COV.extract_checklist("Add two numbers and output the sum.")}
    assert not (_NEW_KINDS & kinds)


# ── general-engine structures wiring (assess_spec carries every facet) ──
_FACET_KEYS = ("analog_interface", "test_debug", "otp",
               "calibration", "signedness", "electrical")


def test_general_engine_surfaces_all_facets():
    import spec_complete_extract as SCE
    doc = (
        "Design `msc`. Ports: input wire [7:0] din, output reg [7:0] dout.\n"
        "A 12-bit ADC with 8 channels samples the input. Vref = 2.5 V. analog input pin ain.\n"
        "JTAG TAP (TMS,TCK,TDI,TDO), scan chain with scan_en, MBIST, test_mode pin.\n"
        "32-bit OTP fuse bank with trim_code at offset 0x10; write-once lock bit.\n"
        "8-bit cal_code register at 0x4; calibration step 1 measures reference.\n"
        "input signed [15:0] coeff. Runs at 100 MHz, 1.8 V supply, 5 mA, slew rate 2 V/ns.\n")
    st = SCE.assess_spec(doc, ["din", "coeff"], ["dout"], module_name="msc")["structures"]
    for k in _FACET_KEYS:
        assert k in st and len(st[k]) > 0, f"facet {k} not surfaced by assess_spec"


def test_facets_additive_empty_on_plain_doc():
    # a plain arithmetic doc yields every facet key present but EMPTY (§4.05: no
    # facet fabricated where there is no structural anchor).
    import spec_complete_extract as SCE
    doc = "Design `add8`. input [7:0] a, input [7:0] b, output [8:0] y. y = a + b."
    st = SCE.assess_spec(doc, ["a", "b"], ["y"], module_name="add8")["structures"]
    for k in _FACET_KEYS:
        assert st.get(k) == [], f"facet {k} fabricated on a plain doc: {st.get(k)}"
