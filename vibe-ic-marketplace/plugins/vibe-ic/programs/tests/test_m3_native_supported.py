"""Native model component controls; never certify physical/whole-design PASS."""
import json
import shutil
import sys
from pathlib import Path

import pytest

import mixed_signal_m3_run as m3

FIXTURE = Path(__file__).parent / "fixtures/m3_native"


def read(path):
    return json.loads(path.read_text())


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


@pytest.fixture
def project(tmp_path):
    dst = tmp_path / "component"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture
def measured(project):
    # All positive bytes are produced by real tools, never hand-authored PASS.
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    assert m3.audit(project, "cosim")["passed"] is True
    return project


def test_ordinary_producer_runs_native_component_cosim(measured):
    evidence = read(measured / m3.COSIM)
    assert evidence["verdict"] == "PASS"
    scenario = evidence["scenarios"][0]
    assert scenario["sample_count"] >= 3
    assert scenario["criteria"][0]["measured"] >= 0.99
    assert scenario["metrics"]["drive_transitions"] == 1
    assert len(evidence["execution"]) == 8
    assert set(evidence["tool_versions"]) == {"ngspice", "iverilog", "vvp"}
    assert 0 < evidence["execution"][5]["peak_rss_kib"] < 8 * 1024**2
    assert read(measured / m3.SI)["coverage"]["noise"] == "NOT_MEASURED"
    assert m3.audit(measured, "cosim")["full_design_verified"] is False


def test_declared_stricter_limit_fails_audit(measured):
    plan = measured / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    data = read(plan)
    data["fields"]["verification_plan"]["cosim_scenarios"][0]["criteria"][0]["min"] = 1.1
    write(plan, data)
    report = m3.audit(measured, "cosim")
    assert report["verdict"] == "FAIL"
    assert report["findings"][0]["rule"] == "FAILED_MEASUREMENT"



def test_native_execution_failure_remains_a_failure(measured):
    path = measured / m3.COSIM
    data = read(path)
    data["execution"][-1]["exit_code"] = 1
    write(path, data)
    report = m3.audit(measured, "cosim")
    assert report["verdict"] == "FAIL"
    assert report["findings"][0]["rule"] == "NATIVE_EXECUTION_FAILED"


def test_missing_native_measurement_is_not_a_pass(measured):
    path = measured / m3.COSIM
    data = read(path)
    data["scenarios"][0]["metrics"].pop("settled_voltage_min_v")
    write(path, data)
    report = m3.audit(measured, "cosim")
    assert report["verdict"] == "NOT_MEASURED"
    assert report["findings"][0]["rule"] == "MISSING_MEASUREMENT"


@pytest.mark.parametrize("damage", ["wrong_response", "slow_receiver", "failed_spice"])
def test_actual_failed_measurement_propagates_to_m4(project, damage):
    if damage == "wrong_response":
        path = project / "phase3/stage3/pnr/bridge_top_pnr.v"
        path.write_text(path.read_text().replace("accepted <= sense", "accepted <= 0"))
    else:
        path = project / "input/mixed_signal/receiver.sp"
        if damage == "slow_receiver":
            path.write_text(path.read_text().replace("10p", "1u"))
        else:
            path.write_text(path.read_text().replace("Rfunctional din sense 1000", "Rfunctional din sense nonexistent_parameter"))
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 1
    result = read(project / m3.COSIM)
    assert result["verdict"] == "FAIL", result
    assert m3.audit(project, "cosim")["verdict"] == "FAIL"


def test_native_adapter_runs_real_scenarios_and_both_reports(project):
    from flow_native_adapters import execute
    from flow_engine import ToolResult, evaluate
    top = read(project / "input/mixed_signal/native.json")["top"]
    tool = {"adapter": "mixed", "step": "pre_layout_mixed_signal_verification", "top": top}
    result = execute(project, project / "adapter_work", tool, "")
    assert result["ran"] and evaluate(ToolResult(**result), []) == "NOT_MEASURED"
    scenario = read(project / m3.COSIM)["scenarios"][0]
    assert scenario["status"] == "PASS" and scenario["metrics"]["settled_voltage_min_v"] >= 0.99
    assert read(project / m3.SI)["coverage"]["noise"] == "NOT_MEASURED"


@pytest.mark.parametrize("kind", ["cosim", "si"])
def test_native_audit_cannot_overwrite_execution_artifacts(measured, kind):
    report = read(measured / m3.COSIM)
    wave = measured / report["native_root"] / "enable_receiver/wave.txt"
    before = wave.read_bytes()
    assert wave.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing_spef", "missing_liberty", "truncated_spef"])
def test_si_incomplete_current_views_remain_unmeasured(project, damage):
    contract_path = project / "input/mixed_signal/native.json"
    data = read(contract_path)
    data["si"] = {"netlist": data["digital"]["netlist"], "sdc": "input/mixed_signal/timing.sdc",
                  "spef": "input/mixed_signal/current.spef", "liberties": ["input/mixed_signal/current.lib"],
                  "vdd_v": 1, "noise_margin_mv": 100,
                  "interfaces": [{"pin": "sense", "criteria": [{"metric": "slew_rise_max", "max": 1}]}]}
    (project / data["si"]["sdc"]).write_text("create_clock -period 20 [get_ports clk]\n")
    # A real committed extraction EXCERPT has no D_NET records. It cannot be
    # substituted for a complete current post-route parasitic/timing view.
    excerpt = FIXTURE.parent / "librelane_import/8HD-4/runs/cmp3/54-openroad-rcx/nom/spm.nom.spef"
    if damage != "missing_spef":
        text = excerpt.read_text().replace('*DESIGN "spm"', '*DESIGN "bridge_top"')
        (project / data["si"]["spef"]).write_text(text)
    if damage != "missing_liberty":
        # Deliberately invalid library; never creates a positive STA fixture.
        (project / data["si"]["liberties"][0]).write_text("missing qualified Liberty timing\n")
    write(contract_path, data)
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    assert m3.audit(project, "cosim")["passed"] is True
    si = read(project / m3.SI)
    assert si["verdict"] == "NOT_MEASURED"
    assert si["coverage"]["timing"] == "NOT_MEASURED"
    if damage == "truncated_spef":
        assert "complete extracted D_NET" in si["blockers"][0]


def test_absent_native_report_is_not_measured(measured):
    (measured / m3.COSIM).unlink()
    assert m3.audit(measured, "cosim")["verdict"] == "NOT_MEASURED"


def test_driver_changed_by_measured_feedback_requires_coupled_solver(project):
    path = project / "phase3/stage3/pnr/bridge_top_pnr.v"
    path.write_text(path.read_text().replace("enable <= 1", "enable <= !sense"))
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    result = read(project / m3.COSIM)
    assert result["verdict"] == "NOT_MEASURED"
    assert result["scenarios"][0]["rule"] == "FEEDBACK_ALTERS_DRIVE"




@pytest.fixture
def current_interface_project(project, monkeypatch):
    """SOURCE_CONTROL ancestors + actual M3 native measurements.

    Ancestor transport is controlled; this is not native A7/M1/M2, routed
    physical qualification, or native whole-row proof.
    """
    import hashlib
    import analog_a7_post_layout_emit as a7
    import mixed_signal_top_lvs_run as merge
    import mixed_signal_power_domain_run as power
    import librelane_contract as lc
    def put(rel, text):
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    pdk = project / "input/pdk/neutral"
    driver = put("input/pdk/neutral/cells.sp", ".subckt BUF A Y\nRdriver A Y {driver_r}\nCdriver Y 0 1p\n.ends BUF\n")
    models = put("input/pdk/neutral/libs.tech/ngspice/models.spice",
                 ".lib tt\n.param driver_r=100 receiver_r=1000\n.endl tt\n.lib ss\n.param driver_r=200 receiver_r=2000\n.endl ss\n")
    logical = put("input/pdk/neutral/BUF.v", "module BUF(input A, output Y); assign Y=A; endmodule\n")
    lib = put("input/pdk/liberty/current_tt.lib", '''library(neutral) {
 delay_model : table_lookup; time_unit : "1ns"; voltage_unit : "1V";
 current_unit : "1mA"; capacitive_load_unit(1,pf);
 nom_process : 1; nom_temperature : 27; nom_voltage : 1;
 default_operating_conditions : typ;
 operating_conditions(typ) { process : 1; temperature : 27; voltage : 1; }
 voltage_map(VDD,1); voltage_map(VSS,0);
 lu_table_template(t) { variable_1 : input_net_transition;
 variable_2 : total_output_net_capacitance; index_1("0.1,1"); index_2("0.01,1"); }
''' + "\n".join('''cell(%s) { area : 1;
 pin(%s) { direction : input; capacitance : 0.01; }
 pin(%s) { direction : output; function : "%s"; max_capacitance : 1000;
 timing() { related_pin : "%s"; timing_sense : positive_unate;
 cell_rise(t) { values("0.1,0.2","0.2,0.3"); }
 cell_fall(t) { values("0.1,0.2","0.2,0.3"); }
 rise_transition(t) { values("0.1,0.2","0.2,0.3"); }
 fall_transition(t) { values("0.1,0.2","0.2,0.3"); } } } }
''' % (cell, left, right, left, left) for cell, left, right in
          (("BUF", "A", "Y"), ("receiver", "drive", "sense"))) + "}\n")
    netlist = put("phase3/stage3/pnr/bridge_top_pnr.v", '''module bridge_top(input clk, reset_n, output sense, enable, accepted);
 BUF u_driver(.A(reset_n),.Y(enable));
 receiver u_receiver(.drive(enable),.sense(sense));
 assign accepted=sense;
endmodule
''')
    put("phase3/stage3/pnr/routed.def", "DESIGN bridge_top ;\nUNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 2 ;\n- u_driver BUF + PLACED ( 100 100 ) N ;\n- u_receiver receiver + FIXED ( 1000 1000 ) N ;\nEND COMPONENTS\nEND DESIGN\n")
    put("phase3/stage3/pnr/bridge_top.gds", "SOURCE_CONTROL digital layout\n")
    layout = put("phase3/analog/receiver/receiver.gds", "SOURCE_CONTROL A7 layout\n")
    rc_body = ".subckt receiver drive sense\nRreceiver drive sense {receiver_r}\nCreceiver sense 0 1p\n.ends receiver\n"
    a3 = put("phase3/analog/receiver/receiver.sp", f'.lib "{models}" tt\n' + rc_body)
    write(project / "phase3/analog/receiver/topology.json", {"ports": ["drive", "sense"], "rails": {}})
    extracted = put("phase3/librelane/analog/receiver/a7_resim/rcx/receiver.spice", rc_body)
    post_rel = "phase3/librelane/analog/receiver/a7_resim/receiver_post.sp"
    post = put(post_rel, a7.post_layout_netlist("receiver", ["drive", "sense"], extracted.read_text(),
               a7.model_binding_lines(a3.read_text(), a3.parent, (project / post_rel).parent))[0])
    step = extracted.parent
    write(step / "vibeic_receipt.json", {"scope": "SOURCE_CONTROL"})
    for name in ("state_out.json", "input_fingerprint.json", "pdk_root.json"):
        write(step / name, {"scope": "SOURCE_CONTROL"})
    (step / "invocation.log").write_text("SOURCE_CONTROL, not native extraction proof\n")
    monkeypatch.setattr(lc, "validate_step_receipt", lambda folder, sid: {"sha256": {"receiver.spice": sha(extracted)}})
    record = {"producer": "analog_a7_post_layout_emit", "schema": 1, "block": "receiver", "step": "A7",
        "result": "PRODUCED", "layout_path": str(layout.relative_to(project)), "layout_sha256": sha(layout),
        "layout_netlist_identity": {"state": "MATCH"}, "pdk": "neutral", "pdk_root": str(project / "input/pdk"),
        "scope": "SOURCE_CONTROL", "corners": [{"extraction_style": "rcx", "step_dir": str(step.relative_to(project)),
        "extracted_netlist": str(extracted.relative_to(project)), "post_layout_netlist": str(post.relative_to(project)),
        "audit_passed": True, "device_inventory": {"result": "MATCH"}}]}
    write(project / "phase3/analog/receiver/a7_post_layout.json", record)
    write(project / "phase3/analog/receiver/pre_vs_post.json", {"_provenance": {
        "layout_path": record["layout_path"], "layout_sha256": record["layout_sha256"]}})
    macro = project / "phase3/analog/hardmacro/receiver"
    macro_v = put("phase3/analog/hardmacro/receiver/receiver.v", "module receiver(inout drive,sense); endmodule\n")
    for suffix, text in ((".gds", layout.read_text()), (".lib", lib.read_text()), (".lef", "SOURCE_CONTROL abstract\n")):
        put("phase3/analog/hardmacro/receiver/receiver" + suffix, text)
    write(macro / "a8_views_provenance.json", {"producer": "analog_a8_hardmacro_emit", "schema": merge._A8_MANIFEST_SCHEMA,
        "block": "receiver", "source_gds": record["layout_path"], "source_gds_sha256": record["layout_sha256"],
        "views": {suffix: {"path": str((macro / ("receiver" + suffix)).relative_to(project)), "sha256": sha(macro / ("receiver" + suffix))}
                  for suffix in (".gds", ".v", ".lib", ".lef")}})
    put("phase3/mixed_signal/top_merged.gds", "SOURCE_CONTROL M1 merge\n")
    write(project / "phase3/mixed_signal/m1_merge_receipt.json", {"scope": "SOURCE_CONTROL"})
    report = project / "reports/analog/mixed_signal"
    write(report / "top_lvs.json", {"verdict": "PASS", "scope": "SOURCE_CONTROL"})
    monkeypatch.setattr(merge, "validate_current_receipt", lambda p, result: None if result["scope"] == "SOURCE_CONTROL" else "unsupported")
    write(report / "power_domain_run.json", {"scope": "SOURCE_CONTROL"})
    monkeypatch.setattr(power, "verify", lambda p: read(p / "reports/analog/mixed_signal/power_domain_run.json"))
    write(report / "power_domain_tool/netlist.json", {"modules": {"bridge_top": {
        "ports": {name: {"bits": [index], "direction": "input" if name in ("clk", "reset_n") else "output"}
                  for index, name in enumerate(("clk", "reset_n", "sense", "enable", "accepted"), 1)},
        "cells": {"u_receiver": {"type": "receiver", "connections": {"drive": [4], "sense": [3]}},
                  "u_driver": {"type": "BUF", "connections": {"A": [2], "Y": [4]}}}}}})
    sdc = put("phase2/stage2/constraints/bridge_top.sdc", "create_clock -period 20 [get_ports clk]\nset_input_delay -clock clk 0 [get_ports reset_n]\nset_input_transition 0.1 [get_ports reset_n]\n")
    header = '*SPEF "IEEE 1481-1999"\n*DESIGN "bridge_top"\n*DATE "SOURCE_CONTROL"\n*VENDOR "vibe-ic"\n*PROGRAM "hand-authored"\n*VERSION "1.0"\n*DESIGN_FLOW "NETLIST_TYPE_VERILOG"\n*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER []\n*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n'
    spef = put("phase3/stage3/pnr/current.spef", header + '*NAME_MAP\n*1 enable\n*2 sense\n*3 u_driver\n*4 u_receiver\n*5 reset_n\n*D_NET *1 0.2\n*CONN\n*I *3:Y O\n*I *4:drive I\n*P enable O\n*CAP\n1 *3:Y 0.05\n2 *4:drive 0.05\n3 *4:drive *4:sense 0.1\n*RES\n1 *3:Y *4:drive 100\n2 *3:Y enable 1\n*END\n*D_NET *2 0.2\n*CONN\n*I *4:sense O\n*P sense O\n*CAP\n1 *4:sense 0.1\n2 *4:sense *4:drive 0.1\n*RES\n1 *4:sense sense 1\n*END\n*D_NET *5 0.1\n*CONN\n*P reset_n I\n*I *3:A I\n*CAP\n1 *3:A 0.1\n*RES\n1 reset_n *3:A 1\n*END\n')
    sta = project / "phase3/librelane/sta"
    write(sta / "config.json", {"meta": {"step": "OpenROAD.STAPostPNR"}, "PDK": "neutral", "VDD_PIN": "VDD", "GND_PIN": "VSS", "CELL_SPICE_MODELS": [str(driver)], "CELL_VERILOG_MODELS": [str(logical)]})
    write(sta / "state_out.json", {"nl": str(netlist), "sdc": str(sdc), "spef": {"tt": str(spef)}})
    put("phase3/librelane/sta/tt/sta.log", f"Reading cell library for the 'tt' corner at '{lib}'\n")
    write(project / "reports/phase3/sta_postpnr_signoff.json", {"sta_state": str(sta / "state_out.json"), "sta_state_sha256": sha(sta / "state_out.json")})
    data = read(project / "input/mixed_signal/native.json")
    data.update(scope="current_post_layout_interface")
    data["digital"]["extra_sources"] = [str(logical.relative_to(project)), str(macro_v.relative_to(project))]
    data["canonical"] = {"block": "receiver", "instance": "u_receiver", "extraction_style": "rcx", "sta_corner": "tt",
        "driver_instance": "u_driver", "driver_input": "A", "driver_output": "Y", "macro_drive": "drive", "macro_sense": "sense",
        "noise": {"dc_drive_v": 0.5, "frequency_start_hz": 1, "frequency_stop_hz": 1e9, "points_per_decade": 30,
                  "criteria": [{"metric": "integrated_output_noise_v_rms", "units": "V_RMS", "max": 1e-3}]},
        "crosstalk": {"measure_from_ns": 0, "criteria": [{"metric": "peak_crosstalk_v", "units": "V_PEAK", "min": 1e-8, "max": 0.1}]}}
    data["si"] = {"interfaces": [{"pin": "u_receiver/" + port, "criteria": [{"metric": "slew_rise_max", "max": 10}]}
                                 for port in ("drive", "sense")], "vdd_v": 1, "noise_margin_mv": 100}
    write(project / "input/mixed_signal/native.json", data)
    return project


@pytest.mark.parametrize("outcome", ["pass", "threshold_fail", "incomplete_population"])
def test_current_interface_consumes_native_rc_with_controlled_ancestors(current_interface_project, record_property, monkeypatch, capsys, outcome):
    """SOURCE_CONTROL ancestry; actual M3 tools, not native whole-row proof."""
    project = current_interface_project
    import hashlib
    import _mixed_signal_native as native
    contract_path = project / "input/mixed_signal/native.json"
    data = read(contract_path)
    if outcome == "threshold_fail":
        data["canonical"]["crosstalk"]["criteria"][0].update(min=0, max=1e-8)
        write(contract_path, data)
    elif outcome == "incomplete_population":
        write(project / "phase1/analog/analog_block_list.json", {"blocks": ["receiver", "other_receiver"]})
    input_manifest = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(project.rglob("*")) if p.is_file()}
    record_property("input_manifest_sha256", hashlib.sha256(json.dumps(input_manifest, sort_keys=True).encode()).hexdigest())
    write(project / "source_control_inputs.json", input_manifest)
    report = project / "m3_source_control.json"
    calls = []
    original_run = native.Engine.run
    def observed_run(self, command, log, stage, cwd=None):
        calls.append({"command": command, "stage": stage})
        return original_run(self, command, log, stage, cwd)
    monkeypatch.setattr(native.Engine, "run", observed_run)
    rc = m3.main([str(project), "--top", "bridge_top", "--container", "host", "--json", str(report)])
    record_property("proof_scope", "SOURCE_CONTROL ancestors; actual M3 native tools; not native whole-row proof")
    record_property("producer_rc", rc)
    record_property("producer_error", capsys.readouterr().err)
    record_property("producer_report", read(report) if report.is_file() else None)
    measurement_count = sum(call["stage"] == "measurement" and "ngspice" in call["command"] for call in calls)
    record_property("native_ngspice_invocations", measurement_count)
    native_result = read(report) if report.is_file() else {}
    assert rc == {"pass": 0, "threshold_fail": 1, "incomplete_population": 2}[outcome], native_result
    if outcome == "incomplete_population":
        assert measurement_count == 0
        assert read(report)["verdict"] == "NOT_MEASURED"
        assert not (project / m3.RECEIPT).exists()
        return
    assert measurement_count == 1
    assert native_result["verdict"] == ("PASS" if outcome == "pass" else "FAIL")
    assert native_result["scope"] == "current_post_layout_interface"
    assert native_result["full_design_verified"] is False
    si = read(project / m3.SI)
    assert si["coverage"] == {"timing": "MEASURED", "noise": "MEASURED", "crosstalk": "MEASURED"}
    measured = si["current_interfaces"][0]
    assert measured["crosstalk"]["criteria"][0]["measured"] > 1e-8
    assert measured["noise"]["criteria"][0]["measured"] > 0
    expected = 0 if outcome == "pass" else 1


def test_si_audit_rechecks_declared_bounds_and_measured_values(current_interface_project):
    import copy
    project = current_interface_project
    native_path = project / "input/mixed_signal/native.json"
    spec = read(native_path)
    assert m3.main([str(project), "--top", spec["top"], "--container", "host"]) == 0
    assert m3.audit(project, "si")["verdict"] == "PASS"
    report_path = project / m3.SI
    report = read(report_path)
    for kind in ("timing", "noise", "crosstalk"):
        modified = copy.deepcopy(spec)
        if kind == "timing":
            criterion = modified["si"]["interfaces"][0]["criteria"][0]
            measured = report["interfaces"][0]["metrics"][criterion["metric"]]["measured"]
        else:
            criterion = modified["canonical"][kind]["criteria"][0]
            measured = report["current_interfaces"][0][kind]["criteria"][0]["measured"]
        criterion["max"] = measured / 2
        write(native_path, modified)
        assert m3.audit(project, "si")["verdict"] == "FAIL", kind
        write(native_path, spec)
        incomplete = copy.deepcopy(report)
        if kind == "timing":
            del incomplete["interfaces"][0]["metrics"][criterion["metric"]]["measured"]
        else:
            del incomplete["current_interfaces"][0][kind]["criteria"][0]["measured"]
        write(report_path, incomplete)
        assert m3.audit(project, "si")["verdict"] == "NOT_MEASURED", kind
        write(report_path, report)
