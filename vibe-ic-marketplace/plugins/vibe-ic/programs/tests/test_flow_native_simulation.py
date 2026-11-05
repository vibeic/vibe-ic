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
