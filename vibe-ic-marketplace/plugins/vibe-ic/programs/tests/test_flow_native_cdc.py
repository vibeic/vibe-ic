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


@pytest.mark.parametrize("source,physical,pad_role", [
    ("core_rtl", False, None), ("netlist_only", False, None),
    ("explicit", True, None), ("core_rtl", True, "PAD_LIBS"),
    ("core_rtl", True, "EXTRA_LIBS"), ("explicit", False, "UNUSED_PAD_LIBS"),
])
def test_implemented_cdc_uses_native_top_and_empty_physical_cells(tmp_path, source, physical, pad_role):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    if source == "core_rtl":
        rtl = tmp_path / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "core.v").write_text("module core(input clk,d,output reg q); always @(posedge clk) q<=d; endmodule\n")
        docs = tmp_path / "phase1/generated_docs"
        docs.mkdir(parents=True)
        (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "core"}))
    netlist, liberty = tmp_path / "native.v", tmp_path / "cells.lib"
    extra = "physical_only tap();\n" if physical else ""
    used_pad = pad_role in {"PAD_LIBS", "EXTRA_LIBS"}
    clock = "core_clock" if used_pad else "clk"
    pad = "wire core_clock;\npad_input clock_pad(.PAD(clk),.Y(core_clock));\n" if used_pad else ""
    netlist.write_text("module chip_unit(input clk,d,output q);\n" + pad
                      + f"storage first(.CLK({clock}),.D(d),.Q(q));\n" + extra + "endmodule\n")
    liberty.write_text('library(neutral) { cell(storage) { '
                       'ff(IQ,IQN) { clocked_on: "CLK"; next_state: "D"; } '
                       'pin(CLK) { direction: input; clock: true; } '
                       'pin(D) { direction: input; } '
                       'pin(Q) { direction: output; function: "IQ"; } } }\n')
    config = {"DESIGN_NAME": "chip_unit", "DEFAULT_CORNER": "typical",
              "LIB": {"typical": [str(liberty)]}}
    if pad_role:
        pad_liberty = tmp_path / "pads.lib"
        pad_liberty.write_text('library(pads) { cell(pad_input) { '
                               'pin(PAD) { direction: input; } '
                               'pin(Y) { direction: output; function: "PAD"; } } }\n')
        if not used_pad:
            pad_liberty.write_text('library(pads) { type(bus2) { base_type: array; '
                'data_type: bit; bit_width: 2; bit_from: 1; bit_to: 0; downto: true; } '
                'cell(unused_pad) { bus(PAD) { bus_type: bus2; direction: input; } '
                'pin(Y) { direction: output; function: "PAD[0]"; } } }\n')
        config["EXTRA_LIBS" if pad_role == "EXTRA_LIBS" else "PAD_LIBS"] = (
            {"typical": [str(pad_liberty)]} if pad_role != "EXTRA_LIBS"
                            else [str(pad_liberty)])
    tool = {"adapter": "implemented_cdc"}
    if source == "explicit":
        tool.update(rtl=[str(netlist)], top="chip_unit")
    result = execute(tmp_path, tmp_path / "output", tool, {},
                     state={"nl": str(netlist)}, config=config)
    assert result["exit_code"] == 0, result
    assert result["metrics"]["new_unexplained_crossings"] == 0, result
    report = next(Path(p) for p in result["reports"] if p.endswith("cdc.json"))
    assert json.loads(report.read_text())["crossings"]["decoded_flops"] == 1


def test_implemented_cdc_does_not_stub_connected_unknown_storage(tmp_path):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    netlist, liberty = tmp_path / "native.v", tmp_path / "cells.lib"
    netlist.write_text("module chip_unit(input clk,d,output q);\n"
                      "unknown_storage first(.CLK(clk),.D(d),.Q(q));\nendmodule\n")
    liberty.write_text("library(neutral) {}\n")
    result = execute(tmp_path, tmp_path / "output",
        {"adapter": "implemented_cdc", "rtl": [str(netlist)], "top": "chip_unit"}, {},
        state={"nl": str(netlist)}, config={"DESIGN_NAME": "chip_unit", "DEFAULT_CORNER": "typical",
                                           "LIB": {"typical": [str(liberty)]}})
    assert result["exit_code"] != 0, result
    assert result["metrics"] == {}, result
    logs = "\n".join(Path(p).read_text() for p in result["reports"] if p.endswith(".log"))
    assert "unknown_storage" in logs and "not part of the design" in logs
