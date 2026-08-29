#!/usr/bin/env python3
"""Regression for ORGANIC #613 — data-converter / mixed-signal-with-digital-
readout IC class.

現象 (round-1 v1.0.0 6-IC clean-room benchmark): an IC whose function is
analog→digital conversion emitting a digital serial bitstream (a data
converter: sigma-delta / SAR / pipeline ADC, or DAC) had NO home in
ic_class_registry.json. The profiler's is_mixed_signal predicate requires
has_command_protocol OR has_fsm; a free-running data converter has analog
content but no command bus and no FSM, so it failed is_mixed_signal and
collapsed to `pure_analog` — which has BOTH rtl_gen=null AND
fallback_skill=null, so Phase 2 SKIPs RTL entirely and there is NO
generation path (deterministic OR spec-to-rtl) for the digital decimation /
serial-readout datapath the chip genuinely needs. Separately,
L5.analog_digital_interface_present was only ever setdefault(False), so the
analog/digital boundary of any data converter was structurally
unrecognised.

Fix (chip-AGNOSTIC, no chip / vendor / SKU literal):
  1. ic_class_registry.json gains a `data_converter` class with rtl_gen=null
     + fallback_skill="spec-to-rtl" + analog_applicable=true + a real
     tb_gen — i.e. a GENERATION PATH, unlike pure_analog's double-null
     dead-end.
  2. ic_class_profile.detect_ic_class classifies (has_analog ∧ digital
     serial readout ∧ no cmd ∧ no fsm) as `data_converter` ABOVE the
     pure_analog fall-through, and sets is_pure_analog=False so the design
     does NOT receive the pure-analog no-RTL WAIVE.
  3. phase1 gen_l5_adi_spec sets analog_digital_interface_present=True (and a
     mixed-signal signaling_summary) whenever analog blocks are detected AND
     the input docs declare a digital serial readout.

This test builds defect-artifact fixtures shaped like the 現象 and invokes
the REAL entry points (detect_ic_class, gen_l5_adi_spec) to assert
END-STATES — not mere file existence. The NEGATIVE no-leak half (a genuine
pure-analog IC with NO digital readout still classifies as pure_analog) is
the load-bearing guard against the new branch being too wide.
"""
import json

from _skill_routes import assert_route_ships
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ic_class_profile as ICP                       # noqa: E402
import phase1_doc_one_shot_runner as RUNNER          # noqa: E402

_REG = json.loads(
    (_PROGRAMS / "ic_class_registry.json").read_text(encoding="utf-8"))


def _reg_class(name):
    for c in _REG["classes"]:
        if c.get("name") == name:
            return c
    raise AssertionError(f"class {name!r} absent from registry")


# ── defect-artifact fixture builders (shape the 現象) ────────────────────────

def _write_data_converter_project(tmp_path: Path) -> Path:
    """A data converter: analog conversion blocks (L5) + an L1-declared
    analog class + a DIGITAL serial readout, but NO command protocol and NO
    FSM. This is the exact shape that collapsed to pure_analog pre-fix."""
    proj = tmp_path / "data_converter_chip"
    gd = ICP._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_converter",
        "class": "mixed_signal_adc",
        "description": (
            "Multi-channel sigma-delta converter front-end with "
            "Digital serial outputs OUT1..OUT6 (+ dout serial)."),
    }), encoding="utf-8")
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "schema_version": "1.0",
        "doc_class": "L5_ADI_SPEC",
        "no_analog": False,
        "analog_blocks": [
            {"name": "modulator_ch", "type": "delta_sigma",
             "spec": {"order": 2}, "low_confidence": False},
        ],
        "signaling_summary": (
            "Each channel: output 1-bit serial (OUTn / dout) — a digital "
            "bitstream per channel from the decimation datapath."),
    }), encoding="utf-8")
    return proj


def _write_pure_analog_project(tmp_path: Path) -> Path:
    """A genuine pure-analog IC: analog blocks but NO digital serial readout,
    no cmd, no FSM. The no-leak negative — must STAY pure_analog."""
    proj = tmp_path / "pure_analog_chip"
    gd = ICP._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_ldo",
        "class": "pure_analog",
    }), encoding="utf-8")
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "schema_version": "1.0",
        "doc_class": "L5_ADI_SPEC",
        "no_analog": False,
        "analog_blocks": [
            {"name": "regulator", "type": "adc",
             "spec": {"resolution_bits": 12}, "low_confidence": False},
        ],
    }), encoding="utf-8")
    return proj


# ── (1) registry: data_converter HAS a generation path (not the dead-end) ────

def test_registry_data_converter_has_generation_path():
    c = _reg_class("data_converter")
    # rtl_gen=null is fine (AI authors), but fallback_skill MUST be non-null
    # — that is precisely what pure_analog lacks (double-null dead-end).
    assert c["rtl_gen"] is None
    assert c["fallback_skill"] == "spec-to-rtl", (
        "data_converter must route to spec-to-rtl, NOT inherit pure_analog's "
        "fallback_skill=null (which SKIPs RTL entirely)")
    assert c["analog_applicable"] is True
    # contract: a class with a generation path + no reference_tb needs the
    # oracle TB generator (test_registry_tb_gen_contract pins this too).
    assert c["tb_gen"] == "oracle_tb_gen.py"
    assert_route_ships(c["tb_fallback_skill"],
                       "registry class data_converter.tb_fallback_skill")


def test_pure_analog_remains_the_double_null_dead_end():
    """Anchors the contrast: pure_analog is rtl_gen=null AND fallback_skill=
    null (Phase 2 SKIPs RTL). The whole point of #613 is that a data
    converter must NOT land here."""
    c = _reg_class("pure_analog")
    assert c["rtl_gen"] is None and c["fallback_skill"] is None


def test_data_converter_in_taxonomy_and_reaches_dispatch():
    assert "data_converter" in ICP.ALL_IC_CLASSES, (
        "data_converter assigned by detect_ic_class must be declared in "
        "ALL_IC_CLASSES or it is silently unrouted")
    dec = RUNNER.protocol_dispatch_decision("data_converter")
    assert dec["reachable"] is True and dec["signal"] is None


# ── (2) profiler END-STATE: the data converter no longer collapses ───────────

def test_data_converter_classifies_not_pure_analog(tmp_path):
    proj = _write_data_converter_project(tmp_path)
    prof = ICP.detect_ic_class(proj)            # REAL entry point
    assert prof["ic_class"] == "data_converter", (
        f"data converter drifted to {prof['ic_class']!r} (the #613 collapse)")
    # CRITICAL: is_pure_analog=False so it does NOT get the no-RTL WAIVE.
    assert prof["is_pure_analog"] is False
    assert prof["is_data_converter"] is True
    assert prof["has_analog"] is True
    assert prof["decisive_evidence"] and "data_converter" in \
        prof["decisive_evidence"]
    # persisted single-source-of-truth carries the same verdict (#435).
    persisted = json.loads(
        (proj / "reports" / "ic_class.json").read_text(encoding="utf-8"))
    assert persisted["ic_class"] == "data_converter"


def test_pure_analog_no_readout_stays_pure_analog_NOLEAK(tmp_path):
    """Load-bearing NEGATIVE: the new branch must not be too wide. A genuine
    pure-analog IC (analog blocks, NO digital serial readout, no cmd/FSM)
    must STILL classify as pure_analog with is_pure_analog=True — otherwise
    the relaxation leaks and drags every analog PMIC/LDO into an RTL track
    it does not need."""
    proj = _write_pure_analog_project(tmp_path)
    prof = ICP.detect_ic_class(proj)
    assert prof["ic_class"] == "pure_analog", (
        f"pure-analog IC leaked to {prof['ic_class']!r} — branch too wide")
    assert prof["is_pure_analog"] is True
    assert prof["is_data_converter"] is False


# ── (3) L5 END-STATE: analog→digital interface flag no longer hardwired ──────

def test_l5_analog_digital_interface_present_true_for_data_converter(tmp_path):
    """gen_l5_adi_spec (REAL entry point) must set
    analog_digital_interface_present=True when analog blocks are detected AND
    the input docs declare a digital serial readout — instead of the prior
    unconditional setdefault(False)."""
    proj = tmp_path / "adi_proj"
    extracted = {
        "L1_DATASHEET.md": (
            "Multi-channel sigma-delta ADC. Each channel uses a 2nd-order "
            "delta-sigma modulator (analog front-end, switched-capacitor "
            "integrator, 3.3V supply, SNR 90 dB).\n\n"
            "Digital serial outputs OUT1..OUT6 (+ dout serial).\n"),
        "L5_ANALOG_SPEC.md": (
            "The analog modulator output is a 1-bit serial (OUTn / dout) "
            "digital bitstream per channel from the decimation datapath.\n"),
    }
    RUNNER.gen_l5_adi_spec(proj, extracted)
    doc = json.loads(
        (ICP._pl.generated_docs_dir(proj) / "L5_ADI_SPEC.json").read_text(
            encoding="utf-8"))
    assert doc["analog_blocks_detected"] is True
    assert doc["analog_digital_interface_present"] is True, (
        "data converter's analog→digital boundary still unrecognised")
    assert "data converter" in doc.get("signaling_summary", "").lower()


def test_l5_pure_analog_no_readout_interface_absent_NOLEAK(tmp_path):
    """No-leak for the L5 flag: a pure-analog datasheet with NO digital serial
    readout keeps analog_digital_interface_present=False."""
    proj = tmp_path / "adi_pa_proj"
    extracted = {
        "L1_DATASHEET.md": (
            "Low-dropout regulator with a bandgap reference. Analog 3.3V "
            "supply, switched-capacitor integrator, no digital output.\n"),
    }
    RUNNER.gen_l5_adi_spec(proj, extracted)
    doc = json.loads(
        (ICP._pl.generated_docs_dir(proj) / "L5_ADI_SPEC.json").read_text(
            encoding="utf-8"))
    assert doc.get("analog_digital_interface_present") is False


def test_serial_readout_discriminator_is_chip_agnostic():
    """The discriminator fires on GENERIC serial-bitstream vocabulary and is
    silent on pure-analog prose — no chip/vendor token involved."""
    assert RUNNER._v1_6_613_input_has_digital_serial_readout(
        {"x": "Digital serial outputs OUT1..OUT6 (+ dout serial)."}) is True
    assert RUNNER._v1_6_613_input_has_digital_serial_readout(
        {"x": "1-bit serial (OUTn / dout) digital bitstream per channel"}) \
        is True
    assert RUNNER._v1_6_613_input_has_digital_serial_readout(
        {"x": "LDO with bandgap reference, 3.3V analog supply only."}) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
