import json
from pathlib import Path
import shutil

import pytest

from flow_native_adapters import execute


@pytest.mark.parametrize("declared", [True, False])
def test_declared_synchronous_reset_needs_no_intermediate_intent_file(tmp_path, declared):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    rtl = tmp_path / "unit.v"
    rtl.write_text("module unit(input clk,reset_n,d,output reg q); "
                   "always @(posedge clk) if(!reset_n) q<=0; else q<=d; endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8.json").write_text(json.dumps({"reset_domains": [
        {"name": "reset_n", "polarity": "active_low", **({"sync": "synchronous"} if declared else {})}]}))
    result = execute(tmp_path, tmp_path / "output", {"adapter": "cdc", "rtl": [str(rtl)], "top": "unit"}, {})
    report = next(Path(p) for p in result["reports"] if p.endswith("cdc.json"))
    actual = json.loads(report.read_text())
    assert result["metrics"]["unresolved_crossings"] == 0
    assert actual["resets"]["unresolved_role_candidates"] == 0


def test_native_asynchronous_reset_cycle_still_fails(tmp_path):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    rtl = tmp_path / "cycle.v"
    rtl.write_text("module cycle(input clk,d,output reg q,r); "
                  "always @(posedge clk or posedge r) if(r) q<=0; else q<=d; "
                  "always @(posedge clk or posedge q) if(q) r<=0; else r<=d; endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {"adapter": "cdc", "rtl": [str(rtl)], "top": "cycle"}, {})
    assert result["metrics"]["unresolved_crossings"] > 0


@pytest.mark.parametrize("fault", [None, "crossing", "reset_cycle"])
def test_implemented_cdc_uses_liberty_functions_with_udp_models(tmp_path, fault):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    netlist, liberty, model = [tmp_path / name for name in ("unit.v", "cells.lib", "cells.v")]
    clock = "other_clk" if fault == "crossing" else "clk"
    reset_q, reset_r = ("r", "q") if fault == "reset_cycle" else ("reset_n", "reset_n")
    netlist.write_text("module unit(input clk,other_clk,reset_n,d,output q,r); "
                      f"storage first(.CLK(clk),.RSTN({reset_q}),.D(d),.Q(q)); "
                      f"storage second(.CLK({clock}),.RSTN({reset_r}),.D(q),.Q(r)); endmodule\n")
    liberty.write_text('library(neutral) { cell(storage) { '
                       'ff(IQ,IQN) { clocked_on: "CLK"; next_state: "D"; clear: "!RSTN"; } '
                       'pin(CLK) { direction: input; clock: true; } '
                       'pin(RSTN) { direction: input; } pin(D) { direction: input; } '
                       'pin(Q) { direction: output; function: "IQ"; } } }\n')
    model.write_text("primitive storage_udp(q,clk,d); output q; reg q; input clk,d; "
                     "table (01) 0 : ? : 0; (01) 1 : ? : 1; endtable endprimitive\n"
                     "module storage(input CLK,RSTN,D,output Q); storage_udp ff(Q,CLK,D); endmodule\n")
    config = {"DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]},
              "CELL_VERILOG_MODELS": [str(model)]}
    result = execute(tmp_path, tmp_path / "output",
                     {"adapter": "implemented_cdc", "rtl": [str(netlist)], "top": "unit"},
                     {}, state={"nl": str(netlist)}, config=config)
    assert result["exit_code"] == 0, result
    report = next(Path(p) for p in result["reports"] if p.endswith("cdc.json"))
    actual = json.loads(report.read_text())
    assert actual["crossings"]["decoded_flops"] == 2
    expected = {None: set(), "crossing": {"CDC_REG_NO_SYNC"},
                "reset_cycle": {"CIRCULAR_RESET_DEPENDENCY"}}
    assert {finding["rule"] for finding in actual["findings"]} == expected[fault]
    assert (result["metrics"]["new_unexplained_crossings"] > 0) == bool(fault)
    assert result["metrics"]["new_unexplained_crossings"] == result["metrics"]["unresolved_crossings"]
