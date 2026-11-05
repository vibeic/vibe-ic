import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import flow_engine
from flow_native_adapters import Commands, execute


@pytest.mark.parametrize("exit_code", [0, 7])
def test_commands_publish_output_before_the_process_exits(tmp_path, exit_code):
    release = tmp_path / "release"
    code = ("import pathlib,sys,time; "
            "sys.stdout.write('native output\\r\\n'); sys.stdout.flush(); "
            "sys.stderr.write('native diagnostic\\r'); sys.stderr.flush(); "
            "release=pathlib.Path(sys.argv[1]); "
            "exec('while not release.exists(): time.sleep(0.01)'); "
            "sys.exit(int(sys.argv[2]))")
    commands = Commands(tmp_path)
    log = tmp_path / "command_1.log"
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(commands.run, [sys.executable, "-c", code, release, exit_code])
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not pending.done():
                if log.is_file() and all(word in log.read_text() for word in ("native output", "native diagnostic")):
                    break
                time.sleep(0.01)
            assert not pending.done()
            assert log.is_file()
            assert "native output" in log.read_text()
            assert "native diagnostic" in log.read_text()
        finally:
            release.touch()
            completed = pending.result(timeout=5)
    assert completed.returncode == exit_code
    assert completed.stdout == "native output\n"
    assert completed.stderr == "native diagnostic\n"
    assert commands.records == [{"command": list(map(str, completed.args)),
                                 "exit_code": exit_code, "log": str(log)}]
    assert commands.seconds > 0


def test_missing_command_does_not_publish_a_run(tmp_path):
    commands = Commands(tmp_path)
    assert commands.run([tmp_path / "missing_executable"]) is None
    assert commands.records == []
    assert not (tmp_path / "command_1.log").exists()


@pytest.mark.parametrize("language,outcome,status", [
    ("verilog", "pass", "PASS"), ("verilog", "fail", "FAIL"),
    ("python", "pass", "PASS"), ("python", "fail", "FAIL"),
    ("python", "skip", "NOT_MEASURED"),
])
def test_functional_simulation_uses_a_frontend_that_elaborates_the_source(
        tmp_path, language, outcome, status):
    if not all(shutil.which(name) for name in ("iverilog", "verilator", "verilator_coverage", "cocotb-config")):
        pytest.skip("Native functional and coverage simulators are required")
    package = tmp_path / "unit_pkg.sv"
    package.write_text("package unit_pkg; localparam MASK = 1'b1; endpackage\n")
    rtl = tmp_path / "unit.sv"
    rtl.write_text("`timescale 1ns/1ps\nmodule unit import unit_pkg::*; "
                   "(input wire a, output wire z); assign z=a^MASK; endmodule\n")
    expected = 0 if outcome == "fail" else 1
    tb = tmp_path / ("tb_unit.py" if language == "python" else "tb_unit.v")
    if language == "python":
        tb.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
            f"@cocotb.test(skip={outcome == 'skip'})\n"
            "async def check(dut):\n    dut.a.value=0\n    await Timer(1, unit='ns')\n"
            f"    assert int(dut.z.value)=={expected}\n")
    else:
        tb.write_text("`timescale 1ns/1ps\nmodule tb_unit; reg a; wire z; unit dut(a,z); "
            "initial begin a=0; #1; "
            f"if (z === 1'b{expected}) $display(\"ORACLE_TB_DONE pass=1/1\"); "
            "else $display(\"ORACLE_TB_DONE pass=0/1\"); $finish; end endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {"adapter": "simulation", "top": "unit",
        "rtl": [str(package), str(rtl)], "testbenches": [str(tb)]}, {})
    functional = next(row for row in result["native_steps"] if row["name"] == "Verilator.Functional")
    assert functional["ran"] and functional["status"] == status, result
    if outcome == "skip":
        assert "assertion_failures" not in result["metrics"], result
    else:
        assert result["metrics"]["assertion_failures"] == (outcome == "fail"), result
    if outcome == "pass":
        assert result["exit_code"] == 0, result
    measured = [{"status": status}]
    assert flow_engine.evaluate(flow_engine.ToolResult(**result), measured) == status, result
    logs = "\n".join(Path(path).read_text(errors="replace") for path in result["reports"]
                     if str(path).endswith(".log"))
    assert "syntax error" in logs
    assert commands.result()["ran"] is False


@pytest.mark.parametrize("outcome,status", [("pass", "PASS"), ("fail", "FAIL"), ("skip", "NOT_MEASURED")])
def test_declared_runtime_supplies_cocotb_without_host_tools(tmp_path, outcome, status):
    if not (os.environ.get("EDA_CONTAINER") or os.environ.get("VIBEIC_EDA_CONTAINER")) or not shutil.which("docker"):
        pytest.skip("An existing declared tool container with this source and temporary directory mounted is required")
    if shutil.which("cocotb-config"):
        pytest.skip("This regression exercises a host without cocotb")
    rtl = tmp_path / "unit.v"
    rtl.write_text("`timescale 1ns/1ps\nmodule unit(input wire a, output wire z); assign z=~a; endmodule\n")
    tb = tmp_path / "tb_unit.py"
    tb.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
                  f"@cocotb.test(skip={outcome == 'skip'})\n"
                  "async def check(dut):\n    dut.a.value=0\n    await Timer(1, unit='ns')\n"
                  f"    assert int(dut.z.value)=={0 if outcome == 'fail' else 1}\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(rtl)], "top": "unit", "testbenches": [str(tb)]}, {})
    functional = next(row for row in result["native_steps"] if row["name"] == "Icarus.Functional")
    assert functional["ran"]
    assert functional["status"] == status
    assert all(Path(path).is_file() for path in result["reports"])
    logs = "\n".join(Path(path).read_text(errors="replace") for path in result["reports"]
                     if str(path).endswith(".log"))
    assert "cocotb" in logs
    if outcome == "skip":
        assert "assertion_failures" not in result["metrics"]
    else:
        assert result["metrics"]["assertion_failures"] == (1 if outcome == "fail" else 0)
        assert bool(result["exit_code"]) == (outcome == "fail")


@pytest.mark.parametrize("four_state,failures", [(True, 0), (False, 1)])
def test_icarus_result_judges_functional_checks_when_exit_is_zero(tmp_path, four_state, failures):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    rtl = tmp_path / "unit.v"
    rtl.write_text("module unit(input wire a, output wire z); assign z = ~a; endmodule\n")
    tb = tmp_path / "tb_unit.v"
    condition = "a === 1'bx" if four_state else "z === 1'b1"
    tb.write_text("module tb_unit; reg a; wire z; unit dut(a,z); initial begin "
                  "a=0; #1; a=1; #1; a=1'bx; #1; "
                  f"if ({condition}) $display(\"ORACLE_TB_DONE pass=1/1\"); "
                  "else $display(\"ORACLE_TB_DONE pass=0/1\"); $finish; end endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(rtl)], "top": "unit", "testbenches": [str(tb)]}, {})
    assert result["metrics"]["assertion_failures"] == failures
    logs = [Path(path).read_text(errors="replace") for path in result["reports"] if path.endswith(".log")]
    assert any("ORACLE_TB_DONE pass=0/1" in text for text in logs)
    assert result["native_steps"][0]["name"] == "Icarus.Functional"
    measured = [{"status": "PASS" if failures == 0 else "FAIL"}]
    assert flow_engine.evaluate(flow_engine.ToolResult(**result), measured) == ("PASS" if failures == 0 else "FAIL")


@pytest.mark.parametrize("different", [False, True])
def test_declared_scenarios_run_beside_existing_sample_bench(tmp_path, different):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    import arith_oracle_tb_gen as arithmetic

    project = tmp_path / "design"
    cases = _declared_scenario_project(project, mode="wrong_product" if different else "good")
    cases[1].update(name="random_pairs", stimulus="At least 10000 random operand pairs",
                    coverage_scope="At least 10000 random operand pairs")
    docs = project / "phase1/generated_docs/L10_TEST_CASES.json"
    docs.write_text(json.dumps({"test_cases": cases}))
    sample, code = arithmetic.generate(project, "digital_arithmetic_primitive")
    assert code == 0 and sample["vector_count"] == 28
    tool = {"adapter": "simulation"}
    if not different:
        tool["testbenches"] = [sample["tb"]]
    result = execute(project, project / "output", tool, {})
    logs = "\n".join(Path(path).read_text(errors="replace") for path in result["reports"]
                     if str(path).endswith(".log"))
    assert "ARITH_SCENARIO_DONE transactions=10000 comparisons=80000" in logs
    assert "ARITH_SCENARIO_DONE transactions=9 comparisons=72" in logs
    assert "ARITH_SCENARIO_DONE transactions=180 comparisons=1440" in logs
    statuses = [row["status"] for row in result["native_steps"] if row["name"] == "Icarus.Functional"]
    assert len(statuses) == 4
    assert set(statuses) == ({"FAIL"} if different else {"PASS"})
    if different:
        assert result["exit_code"] != 0
    else:
        assert result["metrics"]["assertion_failures"] == 0
        assert result["exit_code"] == 0


def test_unresolved_declared_scenario_does_not_use_sample_success(tmp_path):
    from test_serial_parallel_declared_function_oracle import _public_scenario_input
    import arith_oracle_tb_gen as arithmetic

    project, _ = _public_scenario_input(tmp_path, "Consecutive transactions", choices=False)
    _, code = arithmetic.generate(project, "digital_arithmetic_primitive")
    assert code == 0
    result = execute(project, project / "output", {"adapter": "simulation"}, {})
    assert result["metrics"] == {}
    assert not result["ran"]
    assert "transaction_rearm" in result["detail"]


def test_adding_an_idle_bench_does_not_reduce_design_coverage(tmp_path):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    rtl = tmp_path / "unit.v"
    rtl.write_text("module unit(input wire [1:0] a, output reg [1:0] z); "
                   "always @* if (a[0]) z = ~a; else z = a; endmodule\n")
    active = tmp_path / "tb_active.v"
    active.write_text("module tb_active; reg [1:0] a; wire [1:0] z; unit dut(a,z); "
                      "initial begin a=0; #1; a=1; #1; a=2; #1; a=3; #1; a=0; #1; "
                      "$display(\"ORACLE_TB_DONE pass=1/1\"); $finish; end endmodule\n")
    idle = tmp_path / "tb_idle.v"
    idle.write_text("module tb_idle; reg [1:0] a=0; wire [1:0] z; unit dut(a,z); "
                    "initial begin #5; $display(\"ORACLE_TB_DONE pass=1/1\"); "
                    "$finish; end endmodule\n")
    tool = {"adapter": "simulation", "rtl": [str(rtl)], "top": "unit"}
    single = execute(tmp_path, tmp_path / "single", {**tool, "testbenches": [str(active)]}, {})
    suite = execute(tmp_path, tmp_path / "suite", {
        **tool, "testbenches": [str(active), str(idle)]}, {})
    assert single["metrics"]["assertion_failures"] == suite["metrics"]["assertion_failures"] == 0
    for category in ("line", "toggle", "branch"):
        metric = f"coverage_{category}_pct"
        assert single["metrics"][metric] > 0
        assert suite["metrics"][metric] >= single["metrics"][metric]


def debug_counter(project, *, different=False):
    rtl = project / "phase2/stage1/rtl/counter_unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module counter_unit(input clk, reset_n, output reg [3:0] count);\n"
                   "always @(posedge clk) if(!reset_n) count<=0; "
                   f"else count<=count+{2 if different else 1}; endmodule\n")
    return rtl


@pytest.mark.parametrize("clocked", [False, True])
def test_debug_interface_without_documents_issues_the_normal_model_handoff(tmp_path, clocked):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    if clocked:
        rtl = debug_counter(tmp_path)
    else:
        rtl = tmp_path / "phase2/stage1/rtl/counter_unit.v"
        rtl.parent.mkdir(parents=True)
        rtl.write_text("module counter_unit(output [3:0] count); assign count=4'd7; endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(rtl)], "top": "counter_unit"}, {})
    assert "requires its reference model" in result["detail"], result
    assert result["metrics"] == {} and not result["ran"]
    report_path = tmp_path / "reports/phase2/gates/professional_tb.json"
    report = json.loads(report_path.read_text())
    assert report["status"] == "INCOMPLETE"
    assert report["reference_model_tier"] == "hook_unfilled"
    handoff = report["reference_model_handoff"]
    assert handoff["status"] == "REQUIRED" and handoff["fallback_skill"] == "testbench-gen"
    assert Path(handoff["artifact_path"]).parent.is_dir()
    assert (Path(handoff["artifact_path"]).parent / "tb_counter_unit.py").is_file()
    assert str(report_path) in result["reports"]


def test_incomplete_arithmetic_producer_keeps_its_normal_handoff(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "logic_unit", "ic_class": "digital_arithmetic_primitive", "top_ports": [
            {"name": name, "direction": direction, "width": 4}
            for name, direction in (("a", "input"), ("b", "input"), ("y", "output"))]}))
    rtl = tmp_path / "phase2/stage1/rtl/logic_unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module logic_unit(input [3:0] a,b, output [3:0] y); assign y=a&b; endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(rtl)], "top": "logic_unit"}, {})
    assert "requires its reference model" in result["detail"], result
    assert result["metrics"] == {} and not result["ran"]
    report = json.loads((tmp_path / "reports/phase2/gates/professional_tb.json").read_text())
    assert report["reference_model_tier"] == "hook_unfilled"
    assert report["reference_model_handoff"]["status"] == "REQUIRED"
    assert Path(report["reference_model_handoff"]["artifact_path"]).parent.is_dir()


@pytest.mark.parametrize("different", [False, True])
def test_debug_reference_model_is_consumed_without_changing_the_rtl(tmp_path, different):
    if not all(shutil.which(name) for name in ("yosys", "iverilog", "vvp", "cocotb-config", "verilator")):
        pytest.skip("Native Yosys, Icarus, cocotb and Verilator are required")
    rtl = debug_counter(tmp_path, different=different)
    tool = {"adapter": "simulation", "rtl": [str(rtl)], "top": "counter_unit"}
    first = execute(tmp_path, tmp_path / "first", tool, {})
    assert "requires its reference model" in first["detail"], first
    report_path = tmp_path / "reports/phase2/gates/professional_tb.json"
    handoff = json.loads(report_path.read_text())["reference_model_handoff"]
    expert = Path(handoff["artifact_path"])
    expert.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
        "@cocotb.test()\nasync def counter_behavior(dut):\n"
        "    dut.clk.value=0\n    dut.reset_n.value=0\n    await Timer(1,unit='ns')\n"
        "    dut.clk.value=1\n    await Timer(1,unit='ns')\n    assert int(dut.count.value)==0\n"
        "    dut.clk.value=0\n    dut.reset_n.value=1\n    await Timer(1,unit='ns')\n"
        "    for expected in range(1,4):\n        dut.clk.value=1\n        await Timer(1,unit='ns')\n"
        "        assert int(dut.count.value)==expected\n        dut.clk.value=0\n        await Timer(1,unit='ns')\n"
        "    print('PROFESSIONAL_TB PASS')\n")
    original = rtl.read_bytes()
    result = execute(tmp_path, tmp_path / "second", tool, {})
    assert rtl.read_bytes() == original
    functional = [row for row in result["native_steps"] if row["name"] == "Icarus.Functional"]
    assert [row["status"] for row in functional] == ["FAIL" if different else "PASS"], result
    assert (result["metrics"]["assertion_failures"] > 0) is different
    assert "reference_model_handoff" not in json.loads(report_path.read_text())


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("source_layout", ["input_only", "mirrored", "header_directory"])
def test_testbench_helper_closure_does_not_change_silicon_sources(tmp_path, different, source_layout):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    from flow_config import resolve_rtl_inputs

    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    dut = rtl / "silicon_unit.v"
    dut.write_text("module silicon_unit(input a, output z); assign z=~a; endmodule\n")
    vendor = tmp_path / "input/vendor_rtl"
    vendor.mkdir(parents=True)
    helper = vendor / "stimulus_helper.v"
    helper.write_text("module stimulus_helper(input a, output expected); "
                      f"assign expected={'a' if different else '~a'}; endmodule\n")
    if source_layout == "mirrored":
        (rtl / helper.name).write_text(helper.read_text())
        helper.write_text("module stimulus_helper(input a, output expected); "
                          f"assign expected={'~a' if different else 'a'}; endmodule\n")
    elif source_layout == "header_directory":
        headers = vendor / "include"
        headers.mkdir()
        (headers / "helper_defs.vh").write_text(f"`define EXPECTED_VALUE {'a' if different else '~a'}\n")
        helper.write_text('`include "helper_defs.vh"\n'
                          "module stimulus_helper(input a, output expected); "
                          "assign expected=`EXPECTED_VALUE; endmodule\n")
    mirror = vendor / "unrelated/nested"
    mirror.mkdir(parents=True)
    (mirror / "unused_stimulus.v").write_text("Unrelated source that must not be compiled.\n")
    (mirror / dut.name).write_text("module silicon_unit(input a, output z); assign z=a; endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "silicon_unit"}))
    benches = tmp_path / "phase2/stage1/sim/tb"
    benches.mkdir(parents=True)
    tb = benches / "tb_unit.v"
    tb.write_text("module tb_unit; reg a; wire z, expected; integer passed=0; "
                  "silicon_unit dut(a,z); stimulus_helper helper(a,expected); "
                  "initial begin a=0; #1; if(z===expected) passed=passed+1; "
                  "a=1; #1; if(z===expected) passed=passed+1; "
                  "$display(\"ORACLE_TB_DONE pass=%0d/2\",passed); $finish; end endmodule\n")
    original, top = resolve_rtl_inputs(tmp_path)
    assert original == [dut]
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "testbenches": [str(tb)]}, {})
    assert resolve_rtl_inputs(tmp_path) == (original, top)
    functional = [row for row in result["native_steps"] if row["name"] == "Icarus.Functional"]
    assert [row["status"] for row in functional] == ["FAIL" if different else "PASS"], result
    assert result["metrics"]["assertion_failures"] == (2 if different else 0)
    assert result["native_steps"][1]["name"] == "Verilator.Coverage"
    assert result["native_steps"][1]["status"] == "PASS", result


@pytest.mark.parametrize("different", [False, True])
def test_cocotb_closure_carries_supplied_header_directories(tmp_path, different):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "cocotb-config", "verilator")):
        pytest.skip("Native Icarus, cocotb and Verilator are required")
    rtl = tmp_path / "phase2/stage1/rtl/silicon_unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text('`include "signal_defs.vh"\n'
                   "module silicon_unit(input a, output z); assign z=`OUTPUT_VALUE; endmodule\n")
    headers = tmp_path / "input/vendor_rtl/include"
    headers.mkdir(parents=True)
    (headers / "signal_defs.vh").write_text(f"`define OUTPUT_VALUE {'a' if different else '~a'}\n")
    bench = tmp_path / "tb_signal.py"
    bench.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
                     "@cocotb.test()\nasync def signal_behavior(dut):\n"
                     "    for value in (0,1):\n        dut.a.value=value\n"
                     "        await Timer(1,unit='ns')\n        assert int(dut.z.value)==1-value\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(rtl)], "top": "silicon_unit",
        "testbenches": [str(bench)]}, {})
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    assert result["metrics"]["assertion_failures"] == (1 if different else 0)
    if not different:
        assert result["native_steps"][1]["status"] == "PASS", result


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("header_layout", ["unique", "mirrored", "selected_parent"])
@pytest.mark.parametrize("suffix", [".vh", pytest.param(".sv", id="source_suffix")])
def test_macro_closure_uses_only_selected_provider(tmp_path, different, header_layout, suffix):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    staged = tmp_path / "phase2/stage1/rtl"
    vendor = tmp_path / "input/vendor_rtl"
    staged.mkdir(parents=True)
    vendor.mkdir(parents=True)
    rtl, shadow = (vendor, staged) if header_layout == "selected_parent" else (staged, vendor)
    dut = rtl / "silicon_unit.v"
    dut.write_text(f'`include "helper_defs{suffix}"\n'
                   "module silicon_unit(input a, output z); `DRIVE_HELPER endmodule\n")
    (rtl / f"helper_defs{suffix}").write_text("`define DRIVE_HELPER selected_helper u(a,z);\n")
    helper = rtl / "selected_helper.v"
    helper.write_text("module selected_helper(input a, output z); "
                      f"assign z={'a' if different else '~a'}; endmodule\n")
    (shadow / (f"shadow_defs{suffix}" if header_layout == "unique" else f"helper_defs{suffix}")).write_text(
        "`define DRIVE_HELPER unrelated_helper u(a,z);\n")
    (shadow / "unrelated_helper.v").write_text(
        "module unrelated_helper(input a, output z); assign z = ; endmodule\n")
    tb = tmp_path / "tb_unit.v"
    tb.write_text("module tb_unit; reg a; wire z; integer passed=0; silicon_unit dut(a,z); "
                  "initial begin a=0; #1; if(z===1'b1) passed=passed+1; "
                  "a=1; #1; if(z===1'b0) passed=passed+1; "
                  "$display(\"ORACLE_TB_DONE pass=%0d/2\",passed); $finish; end endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(dut), str(helper)], "top": "silicon_unit",
        "testbenches": [str(tb)]}, {})
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    assert result["metrics"]["assertion_failures"] == (2 if different else 0)
    assert result["native_steps"][1]["status"] == "PASS", result


@pytest.mark.parametrize("different", [False, True])
def test_macro_closure_keeps_distinct_relative_headers(tmp_path, different):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "verilator", "verilator_coverage")):
        pytest.skip("Native Icarus and Verilator tools are required")
    rtl = tmp_path / "phase2/stage1/rtl"
    for name in ("left", "right"):
        (rtl / name).mkdir(parents=True)
    (rtl / "left/signal_defs.vh").write_text("`define LEFT_VALUE a\n")
    (rtl / "right/signal_defs.vh").write_text(f"`define RIGHT_VALUE 1'b{0 if different else 1}\n")
    dut = rtl / "silicon_unit.v"
    dut.write_text('`include "left/signal_defs.vh"\n`include "right/signal_defs.vh"\n'
                   "module silicon_unit(input a, output z); assign z=`LEFT_VALUE^`RIGHT_VALUE; endmodule\n")
    tb = tmp_path / "tb_unit.v"
    tb.write_text("module tb_unit; reg a; wire z; integer passed=0; silicon_unit dut(a,z); "
                  "initial begin a=0; #1; if(z===1'b1) passed=passed+1; "
                  "a=1; #1; if(z===1'b0) passed=passed+1; "
                  "$display(\"ORACLE_TB_DONE pass=%0d/2\",passed); $finish; end endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "simulation", "rtl": [str(dut)], "top": "silicon_unit",
        "testbenches": [str(tb)]}, {})
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    assert result["metrics"]["assertion_failures"] == (2 if different else 0)
    assert result["native_steps"][1]["status"] == "PASS", result
