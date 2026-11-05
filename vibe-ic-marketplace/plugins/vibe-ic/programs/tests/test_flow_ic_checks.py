import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("librelane")

from librelane.state import DesignFormat
import flow_ic_checks as checks


def timing_state(tmp_path):
    return {DesignFormat.SDF: {"slow": str(tmp_path / "sta/sdf/design.sdf")},
            DesignFormat.SPEF: {"slow": ["design.spef"]},
            DesignFormat.NETLIST: "design.v", DesignFormat.SDC: "constraints.sdc"}


@pytest.mark.parametrize("result, expected", [
    ({"verdict": "PASS", "paths": [{"verdict": "PASS"}]}, 0),
    ({"verdict": "FAIL", "paths": [{"verdict": "MISMATCH"}, {"verdict": "NOT_MEASURED"}]}, 1),
    ({"verdict": "NOT_MEASURED", "paths": []}, None),
])
def test_spice_native_failures_and_missing_measurements_remain_distinct(tmp_path, monkeypatch, result, expected):
    import path_spice_tool
    calls = []
    monkeypatch.setattr(path_spice_tool, "run_case_correlation",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    step = SimpleNamespace(step_dir=str(tmp_path), config={"DESIGN_DIR": str(tmp_path),
                           "PDK_ROOT": str(tmp_path), "PDK": "technology"})
    metrics = checks.SpiceCorrelation.run(step, timing_state(tmp_path))[1]
    assert metrics.get("spice_correlation_errors") == expected
    assert calls[0][1] == {"sta_step_dir": tmp_path / "sta"}
    assert json.loads((tmp_path / "spice_correlation.json").read_text()) == result


def test_spice_missing_native_context_is_not_a_pass(tmp_path, monkeypatch):
    import path_spice_tool
    from librelane_contract import Refusal
    def unavailable(*args, **kwargs):
        raise Refusal("MISSING_SPEF", "No extracted corner")
    monkeypatch.setattr(path_spice_tool, "run_case_correlation", unavailable)
    step = SimpleNamespace(step_dir=str(tmp_path), config={"DESIGN_DIR": str(tmp_path),
                           "PDK_ROOT": str(tmp_path), "PDK": "technology"})
    with pytest.raises(checks.StepException, match="NOT_MEASURED: MISSING_SPEF"):
        checks.SpiceCorrelation.run(step, timing_state(tmp_path))


@pytest.mark.parametrize("result", [{"sta_rc": 1},
    {"paths": [{"sim_rc": 1}]}, {"paths": [{"simulator_execution": {"rc": 1}}]}])
def test_spice_native_process_failure_is_not_missing_data(tmp_path, monkeypatch, result):
    import path_spice_tool
    monkeypatch.setattr(path_spice_tool, "run_case_correlation", lambda *args, **kwargs: result)
    step = SimpleNamespace(step_dir=str(tmp_path), config={"DESIGN_DIR": str(tmp_path),
                           "PDK_ROOT": str(tmp_path), "PDK": "technology"})
    with pytest.raises(checks.StepError, match="correlation tool failed"):
        checks.SpiceCorrelation.run(step, timing_state(tmp_path))


def test_spice_case_keeps_native_sta_exit_status(tmp_path, monkeypatch):
    import path_spice_tool as tool
    monkeypatch.setattr(tool, "native_sta_folder", lambda *args: tmp_path)
    monkeypatch.setattr(tool, "worst_setup_corner", lambda *args: "slow")
    monkeypatch.setattr(tool, "prepare_arm", lambda *args, **kwargs: {"sta_rc": 2})
    monkeypatch.setattr(tool, "simulate_arm", lambda *args, **kwargs: {"paths": []})
    result = tool.run_case_correlation(tmp_path, "", tmp_path, "technology", sta_step_dir=tmp_path)
    assert result["sta_rc"] == 2


@pytest.mark.parametrize("failed", [False, True])
def test_si_keeps_native_slack_and_rejects_failed_sta(tmp_path, monkeypatch, failed):
    import path_spice_tool
    import si_mcf_sta
    monkeypatch.setattr(path_spice_tool, "worst_setup_corner", lambda folder: "slow")
    result = {"windows_rc": 0, "coupling_pairs": 7, "nominal": {"sta_rc": 0},
              "corners": {"setup": {"sta_rc": 1 if failed else 0, "worst_slack_after_ns": -.25},
                          "hold": {"sta_rc": 0, "worst_slack_after_ns": .12}}}
    monkeypatch.setattr(si_mcf_sta, "run", lambda *args, **kwargs: result)
    config = {"DESIGN_DIR": str(tmp_path), "DESIGN_NAME": "design", "LIB": ["cells.lib"]}
    toolbox = SimpleNamespace(filter_views=lambda config, views: list(views), get_lib_voltage=lambda path: 5.)
    class Config(dict):
        def copy(self, **kwargs):
            return {**self, **kwargs}
    step = SimpleNamespace(step_dir=str(tmp_path), config=Config(config), toolbox=toolbox)
    if failed:
        with pytest.raises(checks.StepError, match="signal-integrity run failed"):
            checks.SignalIntegrity.run(step, timing_state(tmp_path))
    else:
        assert checks.SignalIntegrity.run(step, timing_state(tmp_path))[1] == {
            "si_setup_slack_ns": -.25, "si_hold_slack_ns": .12, "si_coupling_pairs": 7}


@pytest.mark.parametrize("total, complete, expected", [(0, True, 0), (3, True, 3),
                                                        (0, False, None), (3, False, 3)])
def test_cvc_uses_native_report_not_process_success(tmp_path, monkeypatch, total, complete, expected):
    from flow_native_adapters import Commands
    recipe = tmp_path / "technology/libs.tech/librelane/cvc"
    recipe.mkdir(parents=True)
    for name in ("models", "cdl.awk", "power.awk"):
        (recipe / name).write_text("native recipe")
    (recipe / "cvcrc").write_text("$CVC_SCRIPTS_DIR/models\n$signoff_tmpfiles/$DESIGN_NAME.cdl\n"
                                  "$signoff_tmpfiles/$CVC_TOP.power\n$signoff_reports/$CVC_TOP.rpt")
    cdl = tmp_path / "technology/libs.ref/cells/cdl/cells.cdl"
    cdl.parent.mkdir(parents=True)
    cdl.write_text("native cells")
    report = f"CVC: 2(2) instances, 4(4) nets, 2(2) devices.\nCVC: Total: {total}\n"
    if complete:
        report += "CVC: End: now\n"
    calls = []
    def run(self, argv):
        calls.append(list(map(str, argv)))
        if argv[0] == "cvc_rv":
            (tmp_path / "report.rpt").write_text(report)
        return SimpleNamespace(returncode=0, stdout="native converted input")
    monkeypatch.setattr(Commands, "run", run)
    step = SimpleNamespace(step_dir=str(tmp_path), config={"PDK_ROOT": str(tmp_path),
        "PDK": "technology", "STD_CELL_LIBRARY": "cells", "VDD_NETS": ["supply"],
        "GND_NETS": ["ground"], "DESIGN_NAME": "design"})
    metrics = checks.ElectricalRules.run(step, {DesignFormat.SPICE: "actual.spice",
                                               DesignFormat.NETLIST: "actual.v"})[1]
    assert metrics.get("cvc_electrical_errors") == expected
    assert calls[0][-1] == "actual.spice"
    assert calls[1][-1] == "actual.v"
    assert calls[2][0] == "cvc_rv"
    assert "$signoff_" not in (tmp_path / "cvcrc").read_text()


def test_ic_profile_keeps_published_engineering_tools_and_original_limits(tmp_path):
    from flow_engine import choose_tool, design_features, predicate
    from flow_steps_generate import ROOT, classify_checks, generate
    native = json.loads((ROOT / "flow/native_limits.json").read_text())
    table, _, _ = generate(json.loads((ROOT / "flow/flow109.json").read_text()), native)
    classify_checks(table, native)
    ic = design_features(tmp_path, {"delivery_target": "shippable_gds"}, table)
    ip = design_features(tmp_path, {"delivery_target": "ip_hardmacro"}, table)
    for feature in ("requires_si", "requires_spice", "requires_perc"):
        assert ic[feature] is True
        assert ip[feature] is (feature == "requires_si")
    expected = {
        "candidate_signal_integrity": ({"si_setup_slack_ns": (">=", 0), "si_hold_slack_ns": (">=", 0)}, "VibeIC.SignalIntegrity"),
        "post_layout_spice_correlation": ({"spice_correlation_errors": ("==", 0)}, "VibeIC.SpiceCorrelation"),
        "candidate_reliability_and_esd": ({"cvc_electrical_errors": ("==", 0)}, "VibeIC.ElectricalRules"),
        "final_perc_esd_and_latch_up": ({"cvc_electrical_errors": ("==", 0)}, "VibeIC.ElectricalRules"),
    }
    for name, (limits, tool) in expected.items():
        row = next(row for row in table["steps"] if row["name"] == name)
        assert predicate(row["when"], ic)
        assert tool in choose_tool(row["tool"], ic)["steps"]
        active = {check["metric"]: (check["operator"], check["limit"]) for check in row["checks"]
                  if predicate(check.get("when", "always"), ic)}
        assert limits.items() <= active.items()
        assert "final_perc_latchup_errors" not in active
