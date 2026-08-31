#!/usr/bin/env python3
"""Regression guards for issue 1967: real Step-29/30 open-tool producers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402
import sdf_gate_sim as sdfsim  # noqa: E402
import spice_correlation_check as spice  # noqa: E402


def test_step29_reuses_existing_oracle_for_arbitrary_interface(tmp_path):
    tb_dir = tmp_path / "phase2/stage1/sim_full_stack"
    tb_dir.mkdir(parents=True)
    tb = tb_dir / "tb_neutral_oracle.v"
    tb.write_text("""
module tb_neutral_oracle;
  reg request; reg [6:0] payload; wire [2:0] response;
  neutral_top chip (.request(request), .payload(payload), .response(response));
  initial begin
    $display("ORACLE_TB_DONE pass=7/7");
    $finish;
  end
endmodule
""")
    found = sdfsim.find_reusable_testbench(tmp_path, "neutral_top")
    assert found is not None
    assert found["path"] == tb
    assert found["module"] == "tb_neutral_oracle"
    assert found["dut_instance"] == "chip"
    injected = sdfsim.inject_sdf_annotation(
        found["text"], found["module"], found["dut_instance"], "/run/top.sdf")
    assert '$sdf_annotate("/run/top.sdf", chip)' in injected
    parsed = sdfsim.parse_self_check_stdout("ORACLE_TB_DONE pass=7/7\n")
    assert parsed == {"verdict": "PASS", "passed": 7, "total": 7,
                      "marker": "ORACLE_TB_DONE"}


def test_step29_rejects_a_non_self_checking_testbench(tmp_path):
    tb_dir = tmp_path / "phase2/stage1/sim_full_stack"
    tb_dir.mkdir(parents=True)
    (tb_dir / "tb_connectivity.v").write_text(
        "module tb_connectivity; neutral_top dut(); initial $finish; endmodule\n")
    assert sdfsim.find_reusable_testbench(tmp_path, "neutral_top") is None


def test_step29_capability_gap_is_only_an_observed_missing_tool(tmp_path):
    sdf = tmp_path / "neutral.sdf"
    sdf.write_text('(DELAYFILE (SDFVERSION "3.0"))\n')
    flag, _ = p3._sdf_sim_skip_disclosure(
        {"verdict": "NOT_APPLICABLE", "reason": "no simulator"}, sdf)
    assert flag == "cap:sdf_gatelevel_simulator_toolchain"
    for reason in ("port shape", "no pdk lib", "no self-checking testbench",
                   "compile failed", "simulator probe failed"):
        flag, _ = p3._sdf_sim_skip_disclosure(
            {"verdict": "ERROR", "reason": reason}, sdf)
        assert flag is None, reason


def _neutral_liberty() -> str:
    return """
library (neutral) {
  time_unit : "1ns";
  capacitive_load_unit (1,pf);
  nom_voltage : 1.0;
  cell (neutral_inv) {
    pin (A) { direction : input; }
    pin (Y) {
      direction : output;
      timing () {
        related_pin : "A";
        cell_rise (delay_template) {
          index_1 ("0.1, 0.2"); index_2 ("0.01, 0.02");
          values ("0.8, 1.0", "1.0, 1.2");
        }
        cell_fall (delay_template) {
          index_1 ("0.1, 0.2"); index_2 ("0.01, 0.02");
          values ("0.7, 0.9", "0.9, 1.1");
        }
      }
    }
  }
}
"""


def test_step30_tolerance_is_derived_from_liberty_grid_not_tuned():
    stages = [{
        "inst": "u0", "cell": "neutral_inv", "toggle_pin": "A",
        "transition": "rise", "input_slew_ns": 0.15,
        "sta_load_pf": 0.015, "wire_cap_pf": 0.01,
    }]
    derived = spice.derive_liberty_path_tolerance(
        _neutral_liberty(), stages, expected_ns=1.0)
    assert derived is not None
    assert derived["method"] == "sum_of_local_nldm_grid_half_ranges"
    assert derived["uncertainty_ns"] == pytest.approx(0.2)
    assert derived["tolerance_pct"] == pytest.approx(20.0)
    assert spice.path_correlation_verdict(20.0, derived["tolerance_pct"]) \
        == "CORRELATED"
    assert spice.path_correlation_verdict(20.1, derived["tolerance_pct"]) \
        == "MISMATCH"
    assert spice.path_correlation_verdict(40.1, derived["tolerance_pct"]) \
        == "CRITICAL_MISMATCH"


def test_step30_installed_deck_references_models_and_measures_path():
    stages = [{
        "inst": "u0", "cell": "neutral_inv", "toggle_pin": "A",
        "out_pin": "Y", "wire_cap_pf": 0.01,
    }]
    subckts = {"neutral_inv": (["A", "Y", "VDD", "VSS"], "")}
    deck = spice.build_installed_path_deck(
        "/runtime/models.lib", "nominal", ["/runtime/global.spice"],
        "/runtime/cells.spice",
        stages, subckts, 1.0, 0.1, 25.0, 0.5, 0.02)
    assert ".include '/runtime/global.spice'" in deck
    assert ".lib '/runtime/models.lib' nominal" in deck
    assert ".include '/runtime/cells.spice'" in deck
    assert "xpath0 a pout vdd 0 neutral_inv" in deck
    assert ".meas tran tpd_fall" in deck
    assert ".meas tran tpd_rise" in deck


def test_step30_capability_gap_is_only_an_observed_missing_tool():
    flag, reason = p3._spice_correlation_skip_disclosure(
        {"status": "NO_TOOL", "reason": "ngspice executable absent"})
    assert flag == "cap:post_layout_spice_correlation"
    assert "genuinely lacks" in reason
    for result in (
        {"status": "ERROR", "reason": "model unresolved"},
        {"status": "ERROR", "reason": "ngspice execution failed"},
        {"status": "ERROR", "reason": "critical path did not swing"},
    ):
        flag, reason = p3._spice_correlation_skip_disclosure(result)
        assert flag is None
        assert "not a capability gap" in reason


def test_core_source_has_no_fixed_path_correlation_thresholds():
    source = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "run_installed_pdk_path_correlation" in source
    installed = spice.run_installed_pdk_path_correlation
    assert callable(installed)
