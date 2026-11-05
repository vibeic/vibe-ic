import shutil
from pathlib import Path

import pytest

import flow_engine
from flow_native_adapters import execute


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
