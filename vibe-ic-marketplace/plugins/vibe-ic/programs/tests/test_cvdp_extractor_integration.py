"""CVDP enhance integration — the 5 program-first structural extractors
(register-map / enum-set+boundary / FSM transitions / worked-examples / rounding-
packing) are wired into spec_coverage_check.extract_checklist, so the four artifact
classes the legacy checklist extractor missed now ENTER coverage attribution.

§3.9 evidence: a CVDP-open behaviour audit found 59% of failing TB checks were
IN-SPEC (our extraction/coverage gap), and the dominant missed structures were
exactly these — an enumerated-mode table's outside-the-set boundary, a register
map's per-register requirement, an FSM's per-transition requirement, and a worked
I/O example. Before this wiring extract_checklist emitted none of them.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import spec_coverage_check as S  # noqa: E402


def _kinds(text):
    return {i.kind for i in S.extract_checklist(text)}


def test_all_extractors_loaded():
    # the original 5 structural extractors + the 6 GENERAL L-doc facet extractors
    # (L5 analog / L7 test-debug / L11 OTP / L13 calibration / signedness /
    # electrical) — any missing would silently degrade coverage recovery.
    loaded = {getattr(m, "__name__", "") for m in S._CVDP_EXTRACTORS}
    expected = {
        "spec_regmap_extract", "spec_enumset_extract", "spec_fsm_extract",
        "spec_numeric_pack_extract", "spec_worked_example_extract",
        "spec_analog_iface_extract", "spec_test_debug_extract", "spec_otp_extract",
        "spec_calibration_extract", "spec_signedness_extract", "spec_electrical_extract",
    }
    assert expected <= loaded, f"missing extractors: {sorted(expected - loaded)}"
    assert len(S._CVDP_EXTRACTORS) == 11


def test_register_map_enters_checklist():
    spec = (
        "Design an APB peripheral with the following register map.\n\n"
        "| Offset | Name | Width | Access |\n"
        "|--------|------|-------|--------|\n"
        "| 0x00 | CTRL | 32 | RW |\n"
        "| 0x04 | STATUS | 32 | RO |\n"
        "| 0x08 | DATA | 32 | RW |\n")
    kinds = _kinds(spec)
    assert "register" in kinds


def test_enum_set_and_boundary_enter_checklist():
    spec = (
        "The rounding mode is selected by rmode:\n"
        "  3'b000 : round to nearest even\n"
        "  3'b001 : round toward zero\n"
        "  3'b010 : round up\n"
        "  3'b011 : round down\n"
        "Values other than 3'b000 to 3'b011 default to round toward zero.\n")
    kinds = _kinds(spec)
    assert "enum_set" in kinds
    # the §3.9 most-missed item — the outside-the-set / default boundary
    assert "enum_boundary" in kinds


def test_fsm_transitions_enter_checklist():
    spec = (
        "The controller is an FSM with states IDLE, LOAD, RUN, DONE.\n"
        "In state IDLE, when start is high, go to LOAD.\n"
        "In state LOAD, go to RUN.\n"
        "In state RUN, when done is high, go to DONE.\n"
        "In state DONE, go to IDLE.\n")
    kinds = _kinds(spec)
    assert "fsm_state" in kinds and "fsm_transition" in kinds


def test_worked_example_enters_checklist():
    spec = (
        "Compute the dot product of two vectors.\n"
        "For example, for input a=3 and b=4, the output result is 12.\n")
    kinds = _kinds(spec)
    assert "worked_example" in kinds


def test_additive_does_not_break_a_plain_spec():
    # a prompt with NONE of the four structures must not gain spurious items
    spec = ("Implement a module TopModule with input clk and output q.\n"
            "q toggles on every clock.\n")
    kinds = _kinds(spec)
    for k in ("register", "enum_set", "enum_boundary", "fsm_transition", "worked_example"):
        assert k not in kinds
