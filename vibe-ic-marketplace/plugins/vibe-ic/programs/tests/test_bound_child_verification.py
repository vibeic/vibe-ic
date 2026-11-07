"""Every native RTL consumer implements the selected parent instance binding."""
import json
from pathlib import Path
import shutil

import pytest

import flow_engine as engine
import flow_native_adapters as native
from test_flow_macro_parameters import design, execute


@pytest.fixture
def child(tmp_path, monkeypatch):
    design(tmp_path)
    with monkeypatch.context() as staging:
        result, children, _ = execute(tmp_path, staging, synthesize=True)
    assert len(children) == 1, result
    project = children[0]
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    for source in (project / "input/rtl").glob("*.v"):
        shutil.copyfile(source, rtl / source.name)
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text('{"top_module":"compute_tile"}')
    config = json.loads((project / "Yosys.Synthesis/config.json").read_text())
    netlist = next((project / "Yosys.Synthesis").glob("*.v"))
    return project, config, netlist


def hook(project):
    path = project / "bound_width.py"
    path.write_text(
        "import cocotb\nfrom cocotb.triggers import Timer\n"
        "@cocotb.test()\nasync def bound_width(dut):\n"
        "    assert len(dut.a) == 9\n    assert len(dut.z) == 9\n"
        "    dut.a.value = 0\n    await Timer(1, units='ns')\n"
        "    assert int(dut.z.value) == 511\n"
        "    dut.a.value = 511\n    await Timer(1, units='ns')\n"
        "    assert int(dut.z.value) == 0\n")
    return path


def test_parent_binding_reaches_both_native_simulators(child):
    project, _, _ = child
    directory = project / "simulation-control"
    directory.mkdir()
    result = native.simulation(project, directory, {"testbenches": [str(hook(project))]},
                               native.Commands(directory))
    assert engine.evaluate(engine.ToolResult(**result), []) == "PASS", result
    from _sim_results_bridge import parse_junit
    for name in ("functional", "coverage"):
        report = parse_junit(directory / f"testbench_1/{name}/results.xml")
        assert report and report["tests"] == 1 and report["failures"] == report["errors"] == 0


@pytest.mark.parametrize("slang", [False, True])
def test_parent_binding_reaches_native_eqy_gold(child, slang):
    from flow_native_verification import eqy
    project, config, netlist = child
    config["USE_SLANG"] = slang
    directory = project / "eqy-control"
    directory.mkdir()
    result = eqy(project, directory, {}, native.Commands(directory),
                 state={"nl": str(netlist)}, config=config)
    assert engine.evaluate(engine.ToolResult(**result), []) == "PASS", result
    assert result["metrics"]["unproved_equivalence"] == 0


def test_changed_binding_cannot_pass_against_old_fixed_gate(child):
    from flow_native_verification import eqy
    project, config, netlist = child
    path = project / "work/flow/native_overrides.json"
    data = json.loads(path.read_text())
    data["SYNTH_PARAMETERS"] = ["WIDTH=11"]
    path.write_text(json.dumps(data))
    directory = project / "eqy-changed-binding"
    directory.mkdir()
    result = eqy(project, directory, {}, native.Commands(directory),
                 state={"nl": str(netlist)}, config=config)
    assert engine.evaluate(engine.ToolResult(**result), []) != "PASS", result


@pytest.mark.parametrize("slang", [False, True])
def test_parent_binding_reaches_native_cdc_and_interface(child, slang):
    from professional_tb_gen import _native_top_ports
    project, _, _ = child
    if not slang:
        (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text('{"top_module":null}')
    if slang:
        for path in (project / "phase2/stage1/rtl").glob("*.v"):
            path.rename(path.with_suffix(".sv"))
    top, ports, reason = _native_top_ports(project)
    assert reason is None
    assert top == "compute_tile"
    assert {p["name"]: p["numeric_width"] for p in ports} == {"a": 9, "z": 9}
    directory = project / "cdc-control"
    directory.mkdir()
    native.cdc(project, directory, {}, native.Commands(directory))
    body = json.loads((directory / "graph_raw.json").read_text())["modules"][top]
    assert len(body["ports"]["a"]["bits"]) == len(body["ports"]["z"]["bits"]) == 9
    if not slang:
        from _cdc_netlist import yosys_script
        from flow_config import resolve_rtl_inputs
        selected = resolve_rtl_inputs(project)
        output = directory / "auto_top.json"
        process = native.Commands(directory).run(["yosys", "-Q", "-T", "-p",
            yosys_script(selected.files, None, output, parameters=selected.parameters)])
        assert process.returncode == 0
        auto = json.loads(output.read_text())["modules"][top]
        assert len(auto["ports"]["a"]["bits"]) == 9


def test_parent_binding_reaches_native_sby_harness(child):
    project, _, _ = child
    source = project / "width_harness.v"
    source.write_text(
        "module width_harness #(parameter WIDTH=3)(input [WIDTH-1:0] a);\n"
        "wire [WIDTH-1:0] z; compute_tile #(.WIDTH(WIDTH)) dut(a,z);\n"
        "always @* assert(WIDTH == 9); endmodule\n")
    rtl = list((project / "phase2/stage1/rtl").glob("*.v"))
    deck = project / "width.sby"
    deck.write_text("[options]\nmode bmc\ndepth 2\n[engines]\nsmtbmc yices\n"
        "[script]\nread_verilog -formal -sv " + " ".join(map(str, [*rtl, source]))
        + "\nprep -top width_harness\n[files]\n")
    directory = project / "formal-control"
    directory.mkdir()
    native.formal(project, directory, {"properties": [str(deck)]}, native.Commands(directory))
    assert (directory / "proof_1_1/status").read_text().split()[0] == "PASS"
    model = (directory / "proof_1_1/model/design.il").read_text()
    assert "width 9 input" in model


def test_activity_uses_the_natively_bound_gate_without_reparameterizing_it(child):
    from flow_activity import _cocotb_activity
    project, config, netlist = child
    directory = project / "activity-control"
    directory.mkdir()
    files = [str(netlist), *(config.get("CELL_VERILOG_MODELS") or [])]
    result = _cocotb_activity(files, hook(project), "compute_tile", directory, native.Commands(directory))
    assert result["status"] == "PASS", result
    assert result["scope_verified"] is True


def test_parent_binding_reaches_native_hdl_testbench_parameters(child):
    project, _, _ = child
    bench = project / "width_tb.v"
    bench.write_text("module width_tb #(parameter WIDTH=3);\n"
        "reg [WIDTH-1:0] a=0; wire [WIDTH-1:0] z;\n"
        "compute_tile #(.WIDTH(WIDTH)) dut(a,z);\n"
        "initial begin #1; if ($bits(z)==9 && z==511)\n"
        '$display("ORACLE_TB_DONE pass=1/1"); else $display("ORACLE_TB_DONE pass=0/1");\n'
        "$finish; end endmodule\n")
    directory = project / "hdl-control"
    directory.mkdir()
    result = native.simulation(project, directory, {"testbenches": [str(bench)]}, native.Commands(directory))
    assert engine.evaluate(engine.ToolResult(**result), []) == "PASS", result
    assert result["metrics"]["assertion_failures"] == 0


def test_power_simulation_binds_the_nested_dut_with_native_xezim_option(child):
    from flow_power import simulation
    project, _, _ = child
    bench = project / "power_tb.v"
    bench.write_text("module power_tb; reg [8:0] a=0; wire [8:0] z;\n"
        "compute_tile dut(a,z); initial begin #1;\n"
        'if ($bits(dut.z)!=9 || z!=511) $fatal(1,"bound width was lost");\n'
        '$display("ORACLE_TB_DONE pass=1/1"); $finish; end endmodule\n')
    (project / "power.upf").write_text("create_power_domain MAIN -elements {.}\n")
    (project / "phase1/generated_docs/L21_POWER_INTENT.json").write_text('{"upf_path":"power.upf"}')
    directory = project / "power-simulation-control"
    directory.mkdir()
    result = simulation(project, directory, {"testbenches": [str(bench)]})
    assert engine.evaluate(engine.ToolResult(**result), []) == "PASS", result
    assert result["metrics"]["isolation_retention_behavior_errors"] == 0
