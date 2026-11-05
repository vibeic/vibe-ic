"""Fixed simulator entrypoints: real CLI refusals and neutral native output.

Native cases exercise only the component producer. The neutral bundle omits a
professional verification plan, so the canonical coverage consumer must refuse
qualification despite successful native execution and measured coverage bytes.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

import execution_step4_icarus
import execution_step4_verilator


ENTRYPOINTS = [
    pytest.param(execution_step4_icarus, "icarus", id="icarus"),
    pytest.param(execution_step4_verilator, "verilator", id="verilator"),
]


def _invoke(module, tmp_path, *args):
    cp = subprocess.run([sys.executable, module.__file__, *map(str, args)],
                        cwd=tmp_path, capture_output=True, text=True, timeout=180)
    (tmp_path / "entrypoint_stdout.log").write_text(cp.stdout)
    (tmp_path / "entrypoint_stderr.log").write_text(cp.stderr)
    return cp


@pytest.mark.parametrize("module,simulator", ENTRYPOINTS)
def test_entrypoint_requires_both_input_and_output_roots(tmp_path, module, simulator):
    cp = _invoke(module, tmp_path, "--inputs", tmp_path / "input")
    assert cp.returncode == 2
    assert "--inputs and --outputs are required" in cp.stderr
    assert not (tmp_path / "step4_execution.json").exists()


@pytest.mark.parametrize("module,simulator", ENTRYPOINTS)
def test_entrypoint_refuses_an_undeclared_gate(tmp_path, module, simulator):
    cp = _invoke(module, tmp_path, "--gate", "unregistered_gate")
    assert cp.returncode != 0
    assert "unsupported Step 4 gate bridge" in cp.stderr


@pytest.mark.parametrize("module,simulator", ENTRYPOINTS)
def test_entrypoint_preserves_typed_not_applicable_gate_report(tmp_path, module, simulator):
    report = tmp_path / "vacuous.json"
    cp = _invoke(module, tmp_path, "--gate", "vacuous_testbench_check", ".",
                 "--json", report)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert json.loads(report.read_text())["verdict"] == "NOT_APPLICABLE"


def _native_input(tmp_path):
    project = tmp_path / "input_project"
    rtl = project / "phase2/stage1/rtl/neutral_logic.v"
    bundle = project / "phase2/stage1/sim_professional/neutral_logic"
    rtl.parent.mkdir(parents=True)
    bundle.mkdir(parents=True)
    rtl.write_text("module neutral_logic(input [3:0] a, b, input select, output reg [3:0] q);\n"
                   "always @* begin\n"
                   "  if (select) q = a ^ b;\n"
                   "  else q = ~(a ^ b);\n"
                   "end\nendmodule\n")
    makefile = bundle / "Makefile"
    makefile.write_text("TOPLEVEL_LANG = verilog\n"
                        "COCOTB_TOPLEVEL = neutral_logic\n"
                        "COCOTB_TEST_MODULES = tb_neutral_logic\n"
                        "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
    testbench = bundle / "tb_neutral_logic.py"
    testbench.write_text("import cocotb\nfrom cocotb.triggers import Timer\n\n"
                         "@cocotb.test()\nasync def checks_logic(dut):\n"
                         "    for select in (0, 1):\n"
                         "        for a in range(16):\n"
                         "            for b in range(16):\n"
                         "                dut.a.value = a\n"
                         "                dut.b.value = b\n"
                         "                dut.select.value = select\n"
                         "                await Timer(1, unit='ns')\n"
                         "                expected = (a ^ b) if select else (~(a ^ b) & 15)\n"
                         "                assert int(dut.q.value) == expected\n"
                         "    dut._log.info('PROFESSIONAL_TB PASS')\n")
    files = {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in (rtl, makefile, testbench)}
    manifest = project / "input/issued_manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"step_id": "4", "parameters": {"top": "neutral_logic"},
                                    "files": files}))
    return project, rtl


@pytest.mark.parametrize("module,simulator", ENTRYPOINTS)
def test_entrypoint_refuses_changed_source_before_native_execution(tmp_path, module, simulator):
    project, rtl = _native_input(tmp_path)
    rtl.write_text("module neutral_logic; endmodule\n")
    output = tmp_path / "output_project"
    cp = _invoke(module, tmp_path, "--inputs", project, "--outputs", output)
    assert cp.returncode != 0
    assert "issued input mutation: phase2/stage1/rtl/neutral_logic.v" in cp.stderr
    assert not output.exists()


@pytest.mark.skipif(any(shutil.which(tool) is None for tool in
                       ("iverilog", "vvp", "verilator", "make", "cocotb-config")),
                    reason="native simulator/cocotb toolchain is unavailable")
@pytest.mark.parametrize("module,simulator", ENTRYPOINTS)
def test_entrypoint_runs_its_fixed_simulator_on_bound_neutral_sources(tmp_path, module, simulator):
    project, original_rtl = _native_input(tmp_path)
    original_files = {str(path.relative_to(project)): path.read_bytes()
                      for path in project.rglob("*") if path.is_file()}
    output = tmp_path / "output_project"
    cp = _invoke(module, tmp_path, "--inputs", project, "--outputs", output)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    document = json.loads((output / "step4_execution.json").read_text())
    assert document["schema"] == "execution_step4/1"
    assert document["simulator"] == simulator
    functional = document["functional"]
    assert "SIM=" + simulator in functional["argv"]
    assert functional["rc"] == 0
    assert functional["verdict"] == "PASS"
    assert functional["summary"] == {"suite_names": ["tb_neutral_logic"],
                                      "tests": 1, "failures": 0, "errors": 0,
                                      "skipped": 0, "passed": 1}
    junit = Path(functional["junit"])
    assert ET.parse(junit).find(".//testcase").get("name") == "checks_logic"
    assert (output / "phase2/stage1/sim/results.xml").read_bytes() == junit.read_bytes()
    assert "PROFESSIONAL_TB PASS" in Path(functional["log"]).read_text()
    assert document["qualification"] == "CANONICAL_CONSUMER_REQUIRED"
    code_coverage = document["coverage"]
    assert "SIM=verilator" in code_coverage["run"]["argv"]
    assert code_coverage["run"]["verdict"] == "PASS"
    assert (code_coverage["verdict"], code_coverage["reason"]) == (
        "FAIL", "STEP4_CANONICAL_COVERAGE_CHECK")
    assert "PROFESSIONAL_COVERAGE_PLAN_INVALID" in cp.stdout
    measurement = json.loads((output / "reports/phase2/coverage/coverage_verilator.json").read_text())
    dat = Path(measurement["coverage_dat"])
    assert dat.stat().st_size > 0
    assert measurement["coverage_dat_sha256"] == hashlib.sha256(dat.read_bytes()).hexdigest()
    staged_rtl = str(output / "phase2/stage1/rtl/neutral_logic.v")
    assert measurement["rtl_sources"] == [staged_rtl]
    assert measurement["scope_files"]
    assert measurement["totals"]["line"]["covered"] > 0
    gate = json.loads((output / "reports/phase2/gates/professional_tb.json").read_text())
    assert (gate["status"], gate["simulator"], gate["functional_mismatch"]) == ("PASS", simulator, False)
    actual = json.loads((output / "reports/phase2/coverage/coverage_actual.json").read_text())
    assert actual["evidence_sha256"] == hashlib.sha256(junit.read_bytes()).hexdigest()
    assert (actual["verdict"], actual["tests"], actual["simulator"]) == ("PASS", 1, simulator)
    assert original_rtl.read_bytes() == original_files[str(original_rtl.relative_to(project))]
    assert {str(path.relative_to(project)): path.read_bytes()
            for path in project.rglob("*") if path.is_file()} == original_files
