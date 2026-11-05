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


@pytest.mark.parametrize("kind,unresolved", [
    ("alias", 0), ("latched", 0), ("opposite_phase", 1),
    ("other_latch_clock", 1), ("raw_gate", 1), ("independent", 1),
])
@pytest.mark.parametrize("suffix", [".v", ".sv"])
def test_rtl_cdc_clock_ancestry_uses_native_latch_phase(tmp_path, kind, unresolved, suffix):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    import _cdc_netlist as native
    gate = {
        "alias": "assign clocked=clk_i;",
        "latched": "reg held; always @* if(!clk_i) held=enable_i; assign clocked=clk_i & held;",
        "opposite_phase": "reg held; always @* if(clk_i) held=enable_i; assign clocked=clk_i & held;",
        "other_latch_clock": "reg held; always @* if(!other_i) held=enable_i; assign clocked=clk_i & held;",
        "raw_gate": "assign clocked=clk_i & enable_i;",
        "independent": "assign clocked=other_i;",
    }[kind]
    rtl = tmp_path / ("unit" + suffix)
    if suffix == ".sv":
        gate = gate.replace(" & ", " && ")
    rtl.write_text("module leaf(input clk,d,output reg q); always @(posedge clk) q<=d; endmodule\n"
                   "module unit(input clk_i,other_i,enable_i,d,output q,r); wire clocked; "
                   + gate + " leaf launch(.clk(clocked),.d(d),.q(q)); "
                   "leaf receive(.clk(clk_i),.d(q),.q(r)); endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {
        "adapter": "cdc", "rtl": [str(rtl)], "top": "unit"}, {})
    assert result["exit_code"] == 0, result
    assert result["metrics"]["unresolved_crossings"] == unresolved, result
    graph = next(Path(path) for path in result["reports"] if path.endswith("graph.json"))
    model = native.load(graph, "unit")
    assert len(model.flops) == 2
    if kind == "latched":
        assert native.reg_crossing_findings(model, calibrate=False)
        native._load_latched_clock_gates(model)
        bit = next(f.clk for f in model.flops if f.clk != model.ports["clk_i"][1][0])
        assert model.root(bit) == bit
        assert model.root(bit, clock=True) == model.ports["clk_i"][1][0]
        assert native.reg_crossing_findings(model, calibrate=False) == []


@pytest.mark.parametrize("kind,unresolved", [
    ("integrated", 0), ("opposite_phase", 1), ("other_latch_clock", 1),
    ("raw_gate", 1), ("independent", 1), ("inverted_gate", 1),
])
@pytest.mark.parametrize("suffix", [".v", ".sv"])
def test_implemented_cdc_clock_ancestry_uses_native_library_latch(tmp_path, kind, unresolved, suffix):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    import _cdc_netlist as native
    liberty = tmp_path / "cells.lib"
    liberty.write_text('library(neutral) { '
        'cell(pulse_gate) { clock_gating_integrated_cell: "latch_posedge"; '
        'pin(CK) { direction: input; clock: true; clock_gate_clock_pin: true; } '
        'pin(E) { direction: input; clock_gate_enable_pin: true; } '
        'pin(GCK) { direction: output; clock_gate_out_pin: true; state_function: "CK*held"; } '
        'pin(held) { direction: internal; internal_node: "held"; } } '
        'cell(hold_high) { latch(IQ,IQN) { enable: "CK"; data_in: "D"; } '
        'pin(CK) { direction: input; } pin(D) { direction: input; } '
        'pin(Q) { direction: output; function: "IQ"; } } '
        'cell(hold_low) { latch(IQ,IQN) { enable: "!CK"; data_in: "D"; } '
        'pin(CK) { direction: input; } pin(D) { direction: input; } '
        'pin(Q) { direction: output; function: "IQ"; } } '
        'cell(merge) { pin(A) { direction: input; } pin(B) { direction: input; } '
        'pin(Y) { direction: output; function: "A*B"; } } '
        'cell(invert) { pin(A) { direction: input; } '
        'pin(Y) { direction: output; function: "!A"; } } '
        'cell(storage) { ff(IQ,IQN) { clocked_on: "CK"; next_state: "D"; } '
        'pin(CK) { direction: input; clock: true; } pin(D) { direction: input; } '
        'pin(Q) { direction: output; function: "IQ"; } } }\n')
    gate = {
        "integrated": "pulse_gate gate(.CK(clk_i),.E(enable_i),.GCK(clocked));",
        "opposite_phase": "wire held; hold_high latch(.CK(clk_i),.D(enable_i),.Q(held)); "
                          "merge gate(.A(clk_i),.B(held),.Y(clocked));",
        "other_latch_clock": "wire held; hold_low latch(.CK(other_i),.D(enable_i),.Q(held)); "
                             "merge gate(.A(clk_i),.B(held),.Y(clocked));",
        "raw_gate": "merge gate(.A(clk_i),.B(enable_i),.Y(clocked));",
        "independent": "assign clocked=other_i;",
        "inverted_gate": "wire held,inverted; hold_low latch(.CK(clk_i),.D(enable_i),.Q(held)); "
                         "invert polarity(.A(clk_i),.Y(inverted)); "
                         "merge gate(.A(inverted),.B(held),.Y(clocked));",
    }[kind]
    netlist = tmp_path / ("unit" + suffix)
    netlist.write_text("module unit(input clk_i,other_i,enable_i,d,output q,r); wire clocked; "
        + gate + " storage launch(.CK(clocked),.D(d),.Q(q)); "
        "storage receive(.CK(clk_i),.D(q),.Q(r)); endmodule\n")
    result = execute(tmp_path, tmp_path / "output", {"adapter": "implemented_cdc"}, {},
        state={"nl": str(netlist)}, config={"DESIGN_NAME": "unit", "DEFAULT_CORNER": "typical",
                                           "LIB": {"typical": [str(liberty)]}})
    assert result["exit_code"] == 0, result
    assert result["metrics"]["new_unexplained_crossings"] == unresolved, result
    graph = next(Path(path) for path in result["reports"] if path.endswith("graph.json"))
    model = native.load(graph, "unit")
    assert len(model.flops) == 2
    if kind == "integrated":
        assert {"$_AND_", "$_DLATCH_N_"}.issubset({cell["type"] for cell in model.cells.values()})
        assert native.reg_crossing_findings(model, calibrate=False)
        native._load_latched_clock_gates(model)
        bit = next(f.clk for f in model.flops if f.clk != model.ports["clk_i"][1][0])
        assert model.root(bit) == bit
        assert model.root(bit, clock=True) == model.ports["clk_i"][1][0]
        assert native.reg_crossing_findings(model, calibrate=False) == []
