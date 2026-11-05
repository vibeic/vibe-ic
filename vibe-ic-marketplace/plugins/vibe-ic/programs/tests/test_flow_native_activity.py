"""Activity uses the captured native netlist and the real simulation/power tools."""
import json
from pathlib import Path
import shutil

import pytest

import flow_activity
from flow_engine import ToolResult, evaluate
from programs.tests._hostpaths import require_repo


@pytest.fixture
def activity_case(tmp_path):
    library = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
                           "fixtures", "m2_placed", "input", "pdk", "liberty", "neutral.lib")
    netlist = tmp_path / "netlist.v"
    netlist.write_text("module unit(a, y); input a; output y;\n"
                       "plain buffer0(.A(a), .Y(y)); endmodule\n")
    model = tmp_path / "cells.v"
    model.write_text("module plain(input A, output Y); assign Y=A; endmodule\n")
    sdc = tmp_path / "timing.sdc"
    sdc.write_text("create_clock -name reference -period 10\nset_load 0.1 [all_outputs]\n")
    bench = tmp_path / "workload.v"
    bench.write_text("`timescale 1ns/1ps\nmodule workload; reg a=0; wire y;\n"
        "unit dut(.a(a), .y(y)); initial begin #1 a=1; #1;\n"
        "if(y !== 1) $fatal(1, \"wrong output\"); #1 a=0; #1 $finish; end endmodule\n")
    config = {"DESIGN_NAME": "unit", "DEFAULT_CORNER": "nominal",
              "LIB": {"nominal": [str(library)]}, "CELL_VERILOG_MODELS": [str(model)],
              "SIGNOFF_SDC_FILE": str(sdc)}
    tool = {"testbenches": [str(bench)]}
    return tmp_path, {"nl": str(netlist)}, config, tool


def run_case(case):
    project, state, config, tool = case
    return flow_activity.execute(project, project / "result", tool, {}, state=state, config=config)


def native_tools():
    if any(not shutil.which(name) for name in ("iverilog", "vvp", "sta")):
        pytest.skip("Native Icarus and OpenSTA executables are required")


def test_native_activity_dump_and_vector_power_read_the_state_netlist(activity_case):
    native_tools()
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == "PASS", result
    assert result["metrics"]["activity__annotated_pin_count"] > 0
    assert result["metrics"]["power__total__corner:nominal"] >= 0
    project = activity_case[0]
    assert str(activity_case[1]["nl"]) in (project / "result/power.tcl").read_text()
    manifest = json.loads((project / "result/activity/activity.json").read_text())
    assert manifest["scope"] == "workload/dut"
    assert manifest["scope_verified"] is True
    assert "report_power" in (project / "result/power.tcl").read_text()


@pytest.mark.parametrize("instance", ["compute_stage", "signal_core"])
@pytest.mark.parametrize("flattened", [False, True])
def test_native_core_scenario_annotates_the_wrapper_core(activity_case, monkeypatch, instance, flattened):
    native_tools()
    from flow_native_adapters import Commands
    import re

    project, state, config, tool = activity_case
    core_netlist = Path(state["nl"])
    core_netlist.write_text("module unit(input [1:0] a, output [1:0] y);\n"
        "plain buffer0(.A(a[0]), .Y(y[0])); plain buffer1(.A(a[1]), .Y(y[1])); endmodule\n")
    bench = Path(tool["testbenches"][0])
    bench.write_text(bench.read_text().replace("reg a=0", "reg [1:0] a=0").replace("wire y;", "wire [1:0] y;"))
    chip = project / "work/flow/chip"
    chip.mkdir(parents=True)
    core_state = chip / "core_state.json"
    core_state.write_text(json.dumps({"nl": str(core_netlist)}))
    (chip / "sizing.json").write_text(json.dumps({"top": "unit", "state_out": str(core_state)}))
    wrapper = f"module package_unit(input [1:0] pad_a, output [1:0] pad_y); unit {instance}(.a(pad_a), .y(pad_y)); endmodule\n"
    (chip / "wrapper.v").write_text(wrapper)
    mapped = project / "chip.v"
    mapped.write_text((f"module package_unit(input [1:0] pad_a, output [1:0] pad_y);\n"
        f"wire [1:0] \\{instance}/a ; wire [1:0] \\{instance}/y ;\n"
        f"assign \\{instance}/a = pad_a; assign pad_y = \\{instance}/y ;\n"
        f"plain \\{instance}/buffer0 (.A(\\{instance}/a [0]), .Y(\\{instance}/y [0]));\n"
        f"plain \\{instance}/buffer1 (.A(\\{instance}/a [1]), .Y(\\{instance}/y [1])); endmodule\n")
        if flattened else core_netlist.read_text() + wrapper)
    state["nl"], config["DESIGN_NAME"] = str(mapped), "package_unit"
    original = bench.read_bytes()
    run = Commands.run
    def probe(self, argv, cwd=None):
        if argv[0] == "sta":
            script = Path(argv[-1])
            script.write_text(script.read_text() + '\nputs "CORE_ACTIVITY: [get_property [get_pins {'
                + instance + '/buffer0/A}] activity]"\n')
        return run(self, argv, cwd=cwd)
    monkeypatch.setattr(Commands, "run", probe)

    result = run_case(activity_case)

    assert evaluate(ToolResult(**result), []) == "PASS", result
    assert result["metrics"]["activity__annotated_pin_count"] > 0
    measured = re.search(r"CORE_ACTIVITY:\s+(\S+)\s+(\S+)\s+user", (project / "result/power.rpt").read_text())
    assert measured and float(measured[1]) > 0
    assert bench.read_bytes() == original
    assert json.loads((project / "result/activity/activity.json").read_text())["dut_module"] == "unit"
    (chip / "wrapper.v").write_text(wrapper.replace(instance, "absent_core"))
    missing = flow_activity.execute(project, project / "missing_result", tool, {}, state=state, config=config)
    assert evaluate(ToolResult(**missing), []) == "NOT_MEASURED", missing
    assert missing["metrics"] == {}


@pytest.mark.parametrize("missing", ["netlist", "library", "scenario", "models", "sdc"])
def test_missing_activity_inputs_are_not_measured(activity_case, missing):
    project, state, config, tool = activity_case
    if missing == "netlist":
        state.clear()
    elif missing == "library":
        config["LIB"] = {}
    elif missing == "scenario":
        tool["testbenches"] = []
    elif missing == "models":
        config["CELL_VERILOG_MODELS"] = [str(project / "absent.v")]
    else:
        config["SIGNOFF_SDC_FILE"] = str(project / "absent.sdc")
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED", result
    assert result["metrics"] == {}
    assert result["ran"] is False


def test_native_simulation_failure_remains_fail(activity_case):
    native_tools()
    project = activity_case[0]
    bench = Path(activity_case[3]["testbenches"][0])
    bench.write_text(bench.read_text().replace("if(y !== 1)", "if(y === 1)"))
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == "FAIL", result
    assert result["metrics"] == {}
    assert not (project / "result/power.tcl").exists()


def test_native_opensta_failure_remains_fail(activity_case):
    native_tools()
    Path(activity_case[2]["SIGNOFF_SDC_FILE"]).write_text("unknown_native_command\n")
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == "FAIL", result
    assert result["metrics"] == {}


def test_zero_annotation_is_not_vector_power(activity_case, monkeypatch):
    native_tools()
    from flow_native_adapters import Commands

    original = Commands.run
    def wrong_scope(self, argv, cwd=None):
        if argv[0] == "sta":
            path = Path(argv[-1])
            path.write_text(path.read_text().replace("workload/dut", "workload/absent"))
        return original(self, argv, cwd=cwd)
    monkeypatch.setattr(Commands, "run", wrong_scope)
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED", result
    assert result["metrics"] == {}
