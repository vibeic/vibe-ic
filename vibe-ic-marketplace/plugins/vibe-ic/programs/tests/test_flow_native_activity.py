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


@pytest.mark.parametrize("ports", ["empty", "input", "output", "inout", "model_empty",
                                   "model_output", "model_inout", "library_error",
                                   "model_conditional_input", "model_conditional_output"])
def test_native_outputless_blackboxes_preserve_functional_activity(activity_case, ports):
    native_tools()
    assert shutil.which("yosys"), "Native Yosys is required"
    project, state, config, tool = activity_case
    direction = "input" if ports == "library_error" else ports.removeprefix("model_").removeprefix("conditional_")
    declaration = "" if direction == "empty" else f"{direction} P"
    model = Path(config["CELL_VERILOG_MODELS"][0])
    body = f"module ballast({declaration}); endmodule\n"
    if ports.startswith("model_conditional_"):
        other = "output" if direction == "input" else "input"
        body = f"`ifdef SYNTHESIS\nmodule ballast({other} P); endmodule\n`else\n{body}`endif\n"
    model.write_text(model.read_text() + body)
    connections = "" if direction == "empty" else ".P(a)" if direction == "input" else ".P(passive_signal)"
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("endmodule",
        f"\nwire passive_signal;\nballast passive({connections});\nendmodule"))
    library = project / "cells.lib"
    text = Path(config["LIB"]["nominal"][0]).read_text()
    pin = "" if direction == "empty" else f"pin(P) {{ direction: {direction}; }}"
    extra = "" if ports.startswith("model_") else f"cell(ballast) {{ {pin} }}"
    library.write_text(text.rsplit("}", 1)[0] + extra + "}\n")
    if ports == "library_error":
        library.write_text("library(neutral) { malformed library\n")
    config["LIB"] = {"nominal": [str(library)]}
    before = netlist.read_bytes()
    result = run_case(activity_case)
    expected = ("FAIL" if ports == "library_error" else "PASS"
                if ports in {"empty", "input", "model_empty", "model_conditional_input"} else "NOT_MEASURED")
    assert evaluate(ToolResult(**result), []) == expected, result
    assert netlist.read_bytes() == before
    if expected == "PASS":
        assert result["metrics"]["activity__annotated_pin_count"] > 0
    else:
        assert result["metrics"] == {}


@pytest.mark.parametrize("backend", ["icarus", "verilator"])
@pytest.mark.parametrize("scenario", ["pass", "failure", "assertion", "skipped", "no_trace"])
def test_native_cocotb_activity_runs_hdl_and_reads_only_its_dump(activity_case, monkeypatch, backend, scenario):
    native_tools()
    if not shutil.which("cocotb-config") or not shutil.which("verilator"):
        pytest.skip("Native cocotb and Verilator are required")
    import flow_native_adapters
    from sim_activity_dump import vcd_scopes

    project,state,config,tool=activity_case
    bench=project/"tb_activity.py"
    bench.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
        f"@cocotb.test(skip={scenario=='skipped'})\nasync def workload(dut):\n"
        "    for value in (0,1,0,1):\n        dut.a.value=value\n"
        "        await Timer(1,unit='ns')\n        assert int(dut.y.value)==value\n"
        + ("    assert False, 'native scenario failure'\n" if scenario=="failure" else ""))
    tool["testbenches"]=[str(bench)]
    if backend=="verilator":
        available=shutil.which
        monkeypatch.setattr(shutil,"which",lambda name: None if name in {"iverilog","vvp"} else available(name))
    if scenario=="assertion":
        Path(config["CELL_VERILOG_MODELS"][0]).write_text(
            "module plain(input A,output Y); assign Y=A;\n"
            "always @* if(A===1'b1) assert(A==0) else $fatal(1,\"native design assertion\"); endmodule\n")
    if scenario=="no_trace":
        run=flow_native_adapters.cocotb_run
        def without_trace(*args,**kwargs):
            kwargs["waves"]=False
            return run(*args,**kwargs)
        monkeypatch.setattr(flow_native_adapters,"cocotb_run",without_trace)
    original=bench.read_bytes()
    result=run_case(activity_case)
    expected="PASS" if scenario=="pass" else "FAIL" if scenario in {"failure","assertion"} else "NOT_MEASURED"
    assert evaluate(ToolResult(**result),[])==expected,result
    assert any(r["name"]=="make" for r in result["native_steps"]),result
    assert bench.read_bytes()==original
    if expected=="PASS":
        assert result["metrics"]["activity__annotated_pin_count"]>0,result
        manifest=json.loads((project/"result/activity/activity.json").read_text())
        trace=Path(manifest["vcd"])
        assert trace.is_file() and trace.stat().st_size>0
        assert manifest["scope"] in vcd_scopes(trace)
        assert str(trace) in (project/"result/power.tcl").read_text()
    else:
        assert "activity__annotated_pin_count" not in result["metrics"],result


@pytest.mark.parametrize("scoped_sdc", [False, True])
@pytest.mark.parametrize("core_sdc_source", ["state", "config", "missing"])
def test_native_cocotb_core_scenario_annotates_the_wrapper(activity_case, scoped_sdc, core_sdc_source):
    native_tools()
    if not shutil.which("cocotb-config"):
        pytest.skip("Native cocotb is required")
    project,state,config,tool=activity_case
    core_netlist=Path(state["nl"])
    chip=project/"work/flow/chip"
    chip.mkdir(parents=True)
    core_sdc = chip/"core.sdc"
    core_sdc.write_text("current_design unit\n" + Path(config["SIGNOFF_SDC_FILE"]).read_text())
    core_state = {"nl":str(core_netlist)}
    if core_sdc_source == "state":
        core_state["sdc"] = str(core_sdc)
    elif core_sdc_source == "config":
        (chip/"config.json").write_text(json.dumps({"SIGNOFF_SDC_FILE":str(core_sdc)}))
    (chip/"core_state.json").write_text(json.dumps(core_state))
    (chip/"sizing.json").write_text(json.dumps({"top":"unit","state_out":str(chip/"core_state.json")}))
    wrapper="module package_unit(input pad_a,output pad_y); unit compute_stage(.a(pad_a),.y(pad_y)); endmodule\n"
    (chip/"wrapper.v").write_text(wrapper)
    mapped=project/"chip.v"
    mapped.write_text(core_netlist.read_text()+wrapper)
    state["nl"],config["DESIGN_NAME"]=str(mapped),"package_unit"
    if scoped_sdc:
        Path(config["SIGNOFF_SDC_FILE"]).write_text(
            'current_design package_unit\ncreate_clock -name reference -period 10\n'
            'set_load 0.1 [get_ports pad_y]\nputs "SCOPED_SDC_READ"\n')
    bench=project/"tb_activity.py"
    bench.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
        "@cocotb.test()\nasync def workload(dut):\n"
        "    for value in (0,1,0,1):\n        dut.a.value=value\n"
        "        await Timer(1,unit='ns')\n        assert int(dut.y.value)==value\n")
    tool["testbenches"]=[str(bench)]
    result=run_case(activity_case)
    if core_sdc_source == "missing":
        assert evaluate(ToolResult(**result),[]) == "NOT_MEASURED", result
        assert result["metrics"] == {}
        assert "native core SDC" in result["detail"]
        return
    assert evaluate(ToolResult(**result),[])=="PASS",result
    assert result["metrics"]["activity__annotated_pin_count"]>0,result
    manifest=json.loads((project/"result/activity/activity.json").read_text())
    assert manifest["dut_module"]=="unit"
    assert "compute_stage" in (project/"result/power.tcl").read_text()
    if scoped_sdc:
        native = (project/"result/power.rpt").read_text()
        assert "current_design for other than top cell" not in native
        assert native.count("SCOPED_SDC_READ") == 1


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_native_base_sdc_uses_each_linked_designs_captured_configuration(activity_case, wrapped, complete):
    native_tools()
    from librelane.common import get_script_dir

    project, state, config, tool = activity_case
    base = str(Path(get_script_dir()) / "base.sdc")
    settings = {"DESIGN_NAME": "unit", "FALLBACK_SDC": base, "CLOCK_PORT": ["a"],
        "IO_DELAY_CONSTRAINT": 20, "MAX_FANOUT_CONSTRAINT": 4,
        "CLOCK_UNCERTAINTY_CONSTRAINT": 0.1, "CLOCK_TRANSITION_CONSTRAINT": 0.1,
        "OUTPUT_CAP_LOAD": 1, "SYNTH_DRIVING_CELL": "plain/Y", "TIME_DERATING_CONSTRAINT": 0}
    if complete:
        settings["CLOCK_PERIOD"] = 24
    if wrapped:
        chip = project / "work/flow/chip"
        chip.mkdir(parents=True)
        (chip / "core_state.json").write_text(json.dumps(state))
        (chip / "config.json").write_text(json.dumps(settings))
        (chip / "sizing.json").write_text(json.dumps(
            {"top": "unit", "state_out": str(chip / "core_state.json")}))
        wrapper = "module package_unit(input pad_a,output pad_y); unit compute_stage(.a(pad_a),.y(pad_y)); endmodule\n"
        (chip / "wrapper.v").write_text(wrapper)
        mapped = project / "chip.v"
        mapped.write_text(Path(state["nl"]).read_text() + wrapper)
        state["nl"], config["DESIGN_NAME"], config["CLOCK_PERIOD"] = str(mapped), "package_unit", 30
        Path(config["SIGNOFF_SDC_FILE"]).write_text(
            'current_design package_unit\n'
            'if {$::env(DESIGN_NAME) ne "package_unit" || $::env(CLOCK_PERIOD) != 30} {error "wrong chip configuration"}\n'
            'create_clock -name reference -period $::env(CLOCK_PERIOD)\n')
    else:
        config.pop("SIGNOFF_SDC_FILE")
        config.update(settings)
    result = run_case(activity_case)
    assert evaluate(ToolResult(**result), []) == ("PASS" if complete else "FAIL"), result
    if complete:
        assert result["metrics"]["activity__annotated_pin_count"] > 0
        native = (project / "result/power.rpt").read_text()
        assert "[INFO] Using clock a" in native
        assert "[INFO] Setting input delay to: 4.8" in native
        assert "[INFO] Setting clock transition to: 0.1\n" in native
    else:
        assert result["metrics"] == {}
        assert 'can\'t read "::env(CLOCK_PERIOD)"' in (project / "result/power.rpt").read_text()


@pytest.mark.parametrize("instance", ["compute_stage", "signal_core"])
@pytest.mark.parametrize("flattened", [False, True, "yosys", "renamed"])
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
    core_sdc = chip / "core.sdc"
    core_sdc.write_text("current_design unit\n" + Path(config["SIGNOFF_SDC_FILE"]).read_text())
    core_state.write_text(json.dumps({"nl": str(core_netlist), "sdc": str(core_sdc)}))
    (chip / "sizing.json").write_text(json.dumps({"top": "unit", "state_out": str(core_state)}))
    wrapper = f"module package_unit(input [1:0] pad_a, output [1:0] pad_y); unit {instance}(.a(pad_a), .y(pad_y)); endmodule\n"
    (chip / "wrapper.v").write_text(wrapper)
    mapped = project / "chip.v"
    if flattened in ("yosys", "renamed"):
        import subprocess
        if not shutil.which("yosys"):
            pytest.skip("Native Yosys is required for flattened naming")
        library = config["LIB"]["nominal"][0]
        rename = (f"select -module package_unit; rename {instance}.buffer0 rewritten_0; "
                  f"rename {instance}.buffer1 rewritten_1; ") if flattened == "renamed" else ""
        subprocess.run(["yosys", "-Q", "-T", "-p", f"read_liberty -lib {library}; "
            f"read_verilog {core_netlist} {chip / 'wrapper.v'}; hierarchy -top package_unit; "
            f"flatten; {rename}write_verilog {mapped}"], cwd=project, check=True, capture_output=True, text=True)
        if flattened == "renamed":
            assert "plain rewritten_0" in mapped.read_text()
            assert f"wire [1:0] \\{instance}.y " in mapped.read_text()
    else:
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
                + ('rewritten_0/Y' if flattened == "renamed" else instance
                   + ("." if flattened == "yosys" else "/") + 'buffer0/Y') + '}] activity]"\n')
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
