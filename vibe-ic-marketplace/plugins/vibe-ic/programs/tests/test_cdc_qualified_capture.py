"""Qualified payload capture follows native synchronisers and register enables."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import _cdc_netlist as native
from flow_native_adapters import execute


def capture_source(case):
    close_event = case in {"closing_edge", "wrong_hold", "unheld_event"}
    payload_guard = "if (!close_window) " if close_event else "if (update) "
    if case == "wrong_hold":
        payload_guard = "if (close_window) "
    elif case == "unheld_event":
        payload_guard = ""
    toggle_clock = "close_window" if close_event else "other_clk" if case == "wrong_source" else "source_clk"
    toggle_guard = "" if close_event or case == "wrong_source" else "if (update) "
    sample = "meta" if case == "one_stage" else "synchronised"
    enable = f"({sample} != seen)"
    if case == "extra_guard":
        enable += " && allow"
    elif case == "parallel_enable":
        enable += " || allow"
    if case == "unqualified":
        enable = "1'b1"
    edge = "negedge" if case == "opposite_edge" else "posedge"
    return (
        "module unit(input source_clk,destination_clk,other_clk,reset_n,close_window,update,allow,\n"
        "input [7:0] data,output reg [7:0] captured,output observed);\n"
        "reg [7:0] payload; reg completion,meta,synchronised,seen;\n"
        "assign observed=synchronised;\n"
        "always @(posedge source_clk or negedge reset_n)\n"
        f"if(!reset_n) payload<=0; else {payload_guard}payload<=data;\n"
        f"always @(posedge {toggle_clock} or negedge reset_n)\n"
        f"if(!reset_n) completion<=0; else {toggle_guard}completion<=~completion;\n"
        "always @(posedge destination_clk or negedge reset_n)\n"
        "if(!reset_n) meta<=0; else meta<=completion;\n"
        f"always @({edge} destination_clk or negedge reset_n)\n"
        "if(!reset_n) synchronised<=0; else synchronised<=meta;\n"
        "always @(posedge destination_clk or negedge reset_n)\n"
        "if(!reset_n) begin captured<=0; seen<=0; end\n"
        f"else if({enable}) begin captured<=payload; seen<={sample}; end\nendmodule\n")


@pytest.mark.parametrize("frontend", ["v", "sv"])
@pytest.mark.parametrize("enabled_cells", [False, True])
@pytest.mark.parametrize("case,qualified", [
    ("same_domain", True), ("closing_edge", True), ("extra_guard", True),
    ("unqualified", False), ("one_stage", False), ("opposite_edge", False),
    ("parallel_enable", False), ("wrong_source", False),
    ("wrong_hold", False), ("unheld_event", False),
])
def test_native_qualified_capture_requires_a_synchronised_load_condition(
        tmp_path, frontend, enabled_cells, case, qualified):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    source = tmp_path / ("unit." + frontend)
    source.write_text(capture_source(case))
    graph = native.build(tmp_path, [source], "unit")
    if enabled_cells:
        enabled = tmp_path / "enabled.json"
        subprocess.run(["yosys", "-Q", "-T", "-p",
            f"read_json {graph}; opt_dff; write_json {enabled}"],
            capture_output=True, text=True, check=True)
        graph = enabled
    model = native.load(graph)
    metadata = {}
    findings = native.reg_crossing_findings(model, metadata=metadata, calibrate=False)
    payload = next(f for f in model.flops if f.label == "payload")
    rows = [row for row in metadata["crossings"] if row["source_cell"] == payload.name]
    assert metadata["traversal_complete"] and rows
    assert all(bool(row.get("qualification")) == qualified for row in rows)
    if qualified:
        assert findings == []
        assert all(row["synchronised"] for row in rows)
        assert all("stable" in row["qualification"]["stable_data_condition"] for row in rows)
        if case == "closing_edge":
            assert all(row["qualification"]["source_hold_level"] == 1 for row in rows)
            assert metadata["clock_domains"] == ["close_window", "destination_clk", "source_clk"]
    else:
        assert any(row["rule"] == "CDC_REG_NO_SYNC"
                   and row["evidence"]["cell"] == payload.name for row in findings)


@pytest.mark.parametrize("adapter", ["cdc", "implemented_cdc"])
@pytest.mark.parametrize("case,unresolved", [("same_domain", 0), ("closing_edge", 0), ("parallel_enable", 1)])
def test_native_adapter_counts_qualified_payload_as_synchronised(tmp_path, adapter, case, unresolved):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    source = tmp_path / "unit.v"
    source.write_text(capture_source(case))
    library = tmp_path / "cells.lib"
    library.write_text("library(neutral) {}\n")
    result = execute(tmp_path, tmp_path / "native",
        {"adapter": adapter, "rtl": [str(source)], "top": "unit"}, {},
        state={"nl": str(source)}, config={"DESIGN_NAME": "unit", "DEFAULT_CORNER": "nominal",
            "LIB": {"nominal": [str(library)]}})
    assert result["metrics"]["unresolved_crossings"] == unresolved, result
    if adapter == "implemented_cdc":
        assert result["metrics"]["new_unexplained_crossings"] == unresolved, result
    report = json.loads(next(Path(path) for path in result["reports"] if path.endswith("/cdc.json")).read_text())
    qualified = [row for row in report["crossings"]["crossings"] if row.get("qualification")]
    assert bool(qualified) == (unresolved == 0)


@pytest.mark.parametrize("enabled_flop", [False, True])
@pytest.mark.parametrize("case,unresolved", [
    ("closing_edge", 0), ("one_stage", 1), ("parallel_enable", 1), ("wrong_hold", 1)])
def test_implemented_capture_uses_native_liberty_load_functions(tmp_path, enabled_flop, case, unresolved):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    source = capture_source(case).replace("output reg [7:0] captured", "output [7:0] captured")
    source = source.replace("captured<=0; ", "").replace("captured<=payload; ", "")
    sample = "meta" if case == "one_stage" else "synchronised"
    enable = f"({sample} != seen)" + (" || allow" if case == "parallel_enable" else "")
    instances = f"wire capture_enable={enable};\n"
    for bit in range(8):
        if enabled_flop:
            instances += (f"HOLDFF capture{bit}(.C(destination_clk),.R(reset_n),.E(capture_enable),"
                          f".D(payload[{bit}]),.Q(captured[{bit}]));\n")
        else:
            instances += (f"wire next{bit};\n"
                f"SELECT hold{bit}(.A(captured[{bit}]),.B(payload[{bit}]),.S(capture_enable),.Y(next{bit}));\n"
                f"SAMPLE capture{bit}(.C(destination_clk),.R(reset_n),.D(next{bit}),.Q(captured[{bit}]));\n")
    source = source.replace("endmodule", instances + "endmodule")
    rtl = tmp_path / "mapped.v"
    rtl.write_text(source)
    library = tmp_path / "cells.lib"
    cells = []
    for name, state in [("HOLDFF", "(D & E) | (IQ & !E)"), ("SAMPLE", "D")]:
        cells.append(f'cell({name}) {{ ff(IQ,IQN) {{ clocked_on:"C"; clear:"!R"; next_state:"{state}"; }} '
            + ' '.join(f'pin({pin}){{direction:input;}}' for pin in ("C", "D", "R", "E")
                       if pin != "E" or name == "HOLDFF")
            + 'pin(Q){direction:output;function:"IQ";} }')
    cells.append('cell(SELECT) { pin(A){direction:input;} pin(B){direction:input;} '
        'pin(S){direction:input;} pin(Y){direction:output;function:"(A & !S) | (B & S)";} }')
    library.write_text('library(neutral) { ' + ' '.join(cells) + ' }\n')
    result = execute(tmp_path, tmp_path / "native", {"adapter": "implemented_cdc"}, {},
        state={"nl": str(rtl)}, config={"DESIGN_NAME": "unit", "DEFAULT_CORNER": "nominal",
                                       "LIB": {"nominal": [str(library)]}})
    assert result["metrics"]["new_unexplained_crossings"] == unresolved, result
