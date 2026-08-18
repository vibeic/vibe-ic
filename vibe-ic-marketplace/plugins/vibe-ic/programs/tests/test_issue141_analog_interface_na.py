"""ORGANIC #141 — an ADC / data-converter whose top interface is entirely
analog (no digital clk/reset/data INPUT) must route its digital RTL steps to
N/A / SKIPPED-CONDITION, not WAIVE→spec-to-rtl→FAIL.

The discriminator is a pre-dispatch STRUCTURAL check on L9 top_ports; there is
no IC-name / class-keyword carve-out. A data_converter that DOES expose a
digital clk/rst/data interface (real on-chip decimation) keeps authoring RTL.

Three layers:
  A. the classifier program (analog_interface_classify) — positive + negative
     + fail-safe(no L9) cases.
  B. design_one_shot_runner.step_rtl_gen — all-analog data_converter routes to
     the analog track (deferred_to=analog_track, fallback_skill=None), NOT
     spec-to-rtl; a digital-interface data_converter still WAIVEs to spec-to-rtl.
  C. flow_compliance_check._digital_backend_is_na — True for the all-analog
     converter, False for the digital-interface one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_interface_classify as AIC          # noqa: E402
import design_one_shot_runner as DOR             # noqa: E402
import flow_compliance_check as FCC              # noqa: E402

# 20-port all-analog ADC interface (issue #141 evidence shape): analog ins,
# analog supplies/refs, raw 1-bit modulator-bitstream OUTs, on-chip clocks as
# OUTPUTS. No digital clock/reset/data INPUT.
_ADC_ALL_ANALOG = (
    [{"name": f"in{i}", "direction": "input"} for i in range(1, 7)]
    + [{"name": n, "direction": "input"} for n in ("vhi", "vlo", "vref")]
    + [{"name": "vldo", "direction": "inout"}]
    + [{"name": f"out{i}", "direction": "output"} for i in range(1, 7)]
    + [{"name": "dout", "direction": "output"}]
    + [{"name": n, "direction": "output"} for n in ("ck4", "ck5", "ck6")]
)

# A data_converter WITH a real digital interface (on-chip decimation).
_CONV_DIGITAL_IFACE = [
    {"name": "vin_p", "direction": "input"},
    {"name": "vin_n", "direction": "input"},
    {"name": "vref", "direction": "input"},
    {"name": "vdd", "direction": "input"},
    {"name": "vss", "direction": "input"},
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "start", "direction": "input"},
    {"name": "data_out", "direction": "output"},
    {"name": "valid", "direction": "output"},
]


def _mk_project(tmp_path: Path, ports: list, with_blocks: bool = True) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "dut", "top_ports": ports}))
    if with_blocks:
        ad = tmp_path / "phase3" / "analog"
        ad.mkdir(parents=True)
        (ad / "analog_block_list.json").write_text(
            json.dumps({"blocks": ["modulator"]}))
    return tmp_path


# ── A. classifier ──────────────────────────────────────────────────────────

def test_classifier_all_analog_absent():
    r = AIC.classify_top_ports(_ADC_ALL_ANALOG)
    assert r["digital_datapath_absent"] is True
    # every port is analog / supply / bitstream-out — none digital
    for pp in r["ports"]:
        assert pp["class"] in (
            "analog_input", "analog_supply_inout", "analog_or_bitstream_output"
        ), pp


def test_classifier_digital_iface_present():
    r = AIC.classify_top_ports(_CONV_DIGITAL_IFACE)
    assert r["digital_datapath_absent"] is False
    assert r["has_digital_clock_input"] is True
    assert r["has_digital_reset_input"] is True
    assert r["has_digital_data_input"] is True   # `start`


def test_classifier_no_l9_is_failsafe_false(tmp_path):
    absent, _reason, ev = AIC.digital_datapath_absent(tmp_path)
    assert absent is False               # cannot assert → keep RTL
    assert ev["n_ports"] == 0


def test_classifier_cli_exit_codes(tmp_path):
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    assert AIC.main([str(p)]) == 0       # all-analog → absent
    q = _mk_project(tmp_path / "q", _CONV_DIGITAL_IFACE)
    assert AIC.main([str(q)]) == 1       # digital iface → keep RTL


# ── B. design_one_shot_runner.step_rtl_gen routing ─────────────────────────

def test_step_rtl_gen_all_analog_routes_to_analog_track(tmp_path):
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    res = DOR.step_rtl_gen(p, "data_converter")
    assert res.status == "WAIVED"
    assert res.extras.get("deferred_to") == "analog_track"
    assert res.extras.get("fallback_skill") is None
    assert res.extras.get("digital_datapath_absent") is True
    # crucially NOT the spec-to-rtl handoff
    assert res.extras.get("fallback_skill") != "spec-to-rtl"


def test_step_rtl_gen_digital_iface_keeps_spec_to_rtl(tmp_path):
    p = _mk_project(tmp_path, _CONV_DIGITAL_IFACE)
    res = DOR.step_rtl_gen(p, "data_converter")
    assert res.status == "WAIVED"
    # a converter WITH a digital interface still authors RTL via spec-to-rtl
    assert res.extras.get("fallback_skill") == "spec-to-rtl"
    assert res.extras.get("deferred_to") != "analog_track"


# ── C. flow_compliance_check._digital_backend_is_na ────────────────────────

def test_flow_compliance_marks_backend_na_for_all_analog(tmp_path):
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    FCC._ANALOG_IFACE_NA_CACHE.clear()
    FCC._PURE_ANALOG_CACHE.clear()
    is_na, reason = FCC._digital_backend_is_na(p)
    assert is_na is True, reason
    assert "all-analog" in reason or "analog" in reason


def test_flow_compliance_keeps_backend_for_digital_iface(tmp_path):
    p = _mk_project(tmp_path, _CONV_DIGITAL_IFACE)
    FCC._ANALOG_IFACE_NA_CACHE.clear()
    FCC._PURE_ANALOG_CACHE.clear()
    is_na, _reason = FCC._digital_backend_is_na(p)
    assert is_na is False


def test_flow_compliance_data_converter_all_analog_is_na(tmp_path, monkeypatch):
    """The issue's exact scenario: ic_class == data_converter (analog_applicable,
    rtl_gen=null, fallback_skill=spec-to-rtl) but an all-analog top interface →
    digital backend N/A, not a spec-to-rtl hard-FAIL."""
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    import ic_class_profile as ICP
    monkeypatch.setattr(FCC, "_project_is_pure_analog",
                        lambda proj: (False, "class 'data_converter' is not "
                                             "analog-only"))
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    FCC._ANALOG_IFACE_NA_CACHE.clear()
    is_na, reason = FCC._digital_backend_is_na(p)
    assert is_na is True, reason
    assert "data_converter" in reason


def test_flow_compliance_data_converter_digital_iface_not_na(tmp_path, monkeypatch):
    p = _mk_project(tmp_path, _CONV_DIGITAL_IFACE)
    monkeypatch.setattr(FCC, "_project_is_pure_analog",
                        lambda proj: (False, "not analog-only"))
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    FCC._ANALOG_IFACE_NA_CACHE.clear()
    is_na, _reason = FCC._digital_backend_is_na(p)
    assert is_na is False


def test_flow_compliance_keeps_backend_when_rtl_present(tmp_path):
    """A real digital datapath (RTL present) is never marked N/A even if the
    L9 pinout would otherwise read all-analog."""
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text("module dut(); endmodule\n")
    FCC._ANALOG_IFACE_NA_CACHE.clear()
    FCC._PURE_ANALOG_CACHE.clear()
    is_na, _reason = FCC._digital_backend_is_na(p)
    assert is_na is False


# ── D. phase3_one_shot_runner._is_pure_analog_no_rtl_track ─────────────────
# Layer C marks the digital backend N/A in flow_compliance_check, but the
# STEP RUNNER (phase3_one_shot_runner) has its own gate that decides whether to
# RUN step_synth (which hard-FAILs on empty rtl/ with "no synthesisable RTL")
# or to WAIVE the digital backend and defer to the analog A5..A6 track. That
# gate previously consulted ONLY the static registry contract, so a
# data_converter (analog_applicable=True but fallback_skill='spec-to-rtl') with
# an all-analog top interface fell through to "has a digital RTL track" → phase3
# ran synth → spurious FAIL, INCONSISTENT with phase-2's rtl_gen WAIVE and with
# layer C. The gate must consult the SAME analog_interface_classify signal.
import phase3_one_shot_runner as P3            # noqa: E402


def test_phase3_gate_all_analog_data_converter_defers(tmp_path, monkeypatch):
    """The u_hawaii_adc scenario: data_converter class + all-analog L9 top +
    empty rtl/ → phase3 must DEFER the digital backend (return True), not run
    synth and hard-FAIL on absent RTL."""
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    is_pa, reason = P3._is_pure_analog_no_rtl_track(p)
    assert is_pa is True, reason
    assert "all-analog" in reason
    assert "analog" in reason


def test_phase3_gate_digital_iface_data_converter_keeps_backend(tmp_path, monkeypatch):
    """A data_converter WITH a real digital clk/rst/data interface still runs
    the digital backend (return False) — no false analog-deferral."""
    p = _mk_project(tmp_path, _CONV_DIGITAL_IFACE)
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    is_pa, _reason = P3._is_pure_analog_no_rtl_track(p)
    assert is_pa is False


def test_phase3_gate_all_analog_but_rtl_present_keeps_backend(tmp_path, monkeypatch):
    """RTL present → never deferred, even if the L9 pinout reads all-analog."""
    p = _mk_project(tmp_path, _ADC_ALL_ANALOG)
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text("module dut(); endmodule\n")
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    is_pa, reason = P3._is_pure_analog_no_rtl_track(p)
    assert is_pa is False, reason


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
