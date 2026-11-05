from __future__ import annotations

from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from flow_native_adapters import Commands
from flow_native_verification import eqy, eqy_partitions, gls, reset_boundary, xor


def partition(tmp_path, name, word, flags=""):
    listing = tmp_path / "partition.list"
    with listing.open("a") as stream:
        stream.write(f"unit {name} {flags} : y\n")
    status = tmp_path / "strategies" / name / "sat/status"
    status.parent.mkdir(parents=True)
    status.write_text(word + "\n")


@pytest.mark.parametrize("word,flags,expected,count", [
    ("PASS", "", "PASS", 0),
    ("FAIL", "", "FAIL", 1),
    ("UNKNOWN", "", "NOT_MEASURED", None),
    ("TIMEOUT", "", "NOT_MEASURED", None),
    ("PASS", "xbits", "NOT_MEASURED", None),
])
def test_native_partition_verdicts(tmp_path, word, flags, expected, count):
    partition(tmp_path, "output", word, flags)
    status, value, _, reports = eqy_partitions(tmp_path)
    assert (status, value) == (expected, count)
    assert all(path.is_file() for path in reports)


def test_missing_partition_status_never_becomes_zero(tmp_path):
    partition(tmp_path, "first", "PASS")
    with (tmp_path / "partition.list").open("a") as stream:
        stream.write("unit second : q\n")
    assert eqy_partitions(tmp_path)[:2] == ("NOT_MEASURED", None)
    assert eqy_partitions(tmp_path / "absent")[:2] == ("NOT_MEASURED", None)


def test_missing_proof_inputs_do_not_launch(tmp_path):
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={}, config={})
    assert result["ran"] is False
    assert result["metrics"] == {}


def reset_docs(project):
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_and_reset_waveform": {
        "clocks": [{"name": "clk", "edge": "posedge"}],
        "resets": [{"name": "rst_n", "polarity": "active_low", "sync": "synchronous"}]}}))


def test_ambiguous_reset_declarations_do_not_invent_a_boundary(tmp_path):
    reset_docs(tmp_path)
    assert reset_boundary(tmp_path) == (("clk", "posedge"), ("rst_n", "active_low"))
    (tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "resets": [{"name": "rst_n", "polarity": "active_high"}]}))
    assert reset_boundary(tmp_path) is None


@pytest.mark.parametrize("different", [False, True])
def test_actual_eqy_uses_documented_reset_state(tmp_path, different):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    reset_docs(tmp_path)
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input clk, rst_n, a, output reg q);\n"
                   "always @(posedge clk) if(!rst_n) q<=1; else q<=a; endmodule\n")
    value = "~a" if different else "a"
    gate.write_text("module unit(input clk, rst_n, a, output wire q);\n"
                   "reg inverted; assign q=~inverted;\n"
                   f"always @(posedge clk) if(!rst_n) inverted<=0; else inverted<=~({value}); endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["metrics"].get("unproved_equivalence") == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


@pytest.mark.parametrize("different", [False, True])
def test_actual_eqy_detects_unequal_logic(tmp_path, different):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input a, b, output y); assign y = a ^ b; endmodule\n")
    operation = "&" if different else "^"
    gate.write_text(f"module unit(input a, b, output y); assign y = a {operation} b; endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    result = eqy(tmp_path, tmp_path, {"metric": "final_lec_unproved"}, Commands(tmp_path),
                 state={"nl": str(gate)}, config=config)
    assert result["ran"], result
    assert result["metrics"]["unproved_equivalence"] == int(different), result
    assert result["metrics"]["final_lec_unproved"] == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    assert not (tmp_path / "result.json").exists()


def test_xor_reuses_native_state_number(tmp_path):
    state = SimpleNamespace(metrics={"design__xor_difference__count": 3})
    commands = Commands(tmp_path)
    result = xor(tmp_path, tmp_path, {}, commands,
                 state=state, config={})
    assert result["ran"] and result["metrics"]["design__xor_difference__count"] == 3
    assert not commands.records and result["tool_seconds"] == 0


def test_absent_xor_views_are_not_a_zero_count(tmp_path):
    class EmptyState(dict):
        metrics = {}
    result = xor(tmp_path, tmp_path, {}, Commands(tmp_path), state=EmptyState(), config={})
    assert not result["ran"] and not result["metrics"]


def test_stream_xor_does_not_satisfy_finished_geometry(tmp_path):
    class FinishedState(dict):
        metrics = {"design__xor_difference__count": 0}
    state = FinishedState({"gds": "finished.gds", "mag_gds": "before.gds"})
    result = xor(tmp_path, tmp_path, {"metric": "unexplained_stream_xor"}, Commands(tmp_path),
                 state=state, config={"PRIMARY_GDSII_STREAMOUT_TOOL": "magic"})
    assert not result["ran"] and not result["metrics"]
    assert "core rectangle" in result["detail"]


@pytest.mark.parametrize("different", [False, True])
def test_finished_geometry_uses_current_gds(tmp_path, different):
    pytest.importorskip("librelane")
    pya = pytest.importorskip("klayout.db")
    from librelane.common import Path as NativePath
    from librelane.config import Config
    from librelane.state import State
    from librelane_plugins.librelane_plugin_vibeic.signoff import FinishingXOR
    paths = []
    for side, edge in (("before", 100), ("finished", 99 if different else 100)):
        layout = pya.Layout()
        cell = layout.create_cell("unit")
        cell.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, edge, 100))
        path = tmp_path / f"{side}.gds"
        layout.write(str(path))
        paths.append(NativePath(str(path)))
    state = State({"mag_gds": paths[0], "gds": paths[1]}, metrics={
        "design__xor_difference__count": 0, "design__core__bbox": "0 0 1 1"})
    config, _ = Config.load({"DESIGN_NAME": "unit", "PDK": "sky130A",
        "VIBEIC_FINISHING_PRE_GDS": str(paths[0])},
        FinishingXOR.get_all_config_variables(), design_dir=str(tmp_path))
    config = config.copy(PRIMARY_GDSII_STREAMOUT_TOOL="magic")
    result = xor(tmp_path, tmp_path / "native", {"metric": "unexplained_stream_xor"}, Commands(tmp_path),
                 state=state, config=config)
    assert result["metrics"].get("unexplained_stream_xor") == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


@pytest.mark.parametrize("different", [False, True])
def test_original_klayout_xor_invocation(tmp_path, different):
    pytest.importorskip("librelane")
    pya = pytest.importorskip("klayout.db")
    from librelane.config import Config
    from librelane.common import Path as NativePath
    from librelane.state import State
    from librelane.steps.klayout import XOR
    if not shutil.which("klayout"):
        pytest.skip("Native KLayout is required")
    paths = []
    for side, edge in (("a", 100), ("b", 101 if different else 100)):
        layout = pya.Layout()
        cell = layout.create_cell("unit")
        cell.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, edge, 100))
        path = tmp_path / f"{side}.gds"
        layout.write(str(path))
        paths.append(NativePath(str(path)))
    config, _ = Config.load({"DESIGN_NAME": "unit", "PDK": "sky130A"},
                            XOR.get_all_config_variables(), design_dir=str(tmp_path))
    state = State({"mag_gds": paths[0], "klayout_gds": paths[1]})
    result = xor(tmp_path, tmp_path / "native", {}, Commands(tmp_path),
                 state=state, config=config)
    assert result["ran"], result
    assert result["metrics"]["design__xor_difference__count"] == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


def gls_fixture(project, *, different=False, annotated=True, cocotb=False):
    project.mkdir(parents=True, exist_ok=True)
    netlist, model, sdf = [project / name for name in ("netlist.v", "model.v", "timing.sdf")]
    operation = "~a" if different else "a"
    model.write_text("`timescale 1ns/1ps\nmodule delay_cell(input a, output y);\n"
                     f"assign y={operation}; specify (a=>y)=(1,1); endspecify endmodule\n")
    netlist.write_text("module unit(input a, output y);\ndelay_cell gate(.a(a),.y(y));\nendmodule\n")
    delays = "(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1))))" if annotated else ""
    connection = ('(CELL (CELLTYPE "unit") (INSTANCE) (DELAY (ABSOLUTE '
                  '(INTERCONNECT a gate/a (0.5:0.5:0.5)))))\n') if annotated else ""
    sdf.write_text('(DELAYFILE (SDFVERSION "3.0") (DESIGN "unit") (DIVIDER /) (TIMESCALE 1ns)\n'
                   + connection + f'(CELL (CELLTYPE "delay_cell") (INSTANCE gate) {delays}))\n')
    benches = project / "phase2/stage1/sim"
    benches.mkdir(parents=True)
    if cocotb:
        tb = benches / "tb_unit.py"
        tb.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
            "@cocotb.test()\nasync def function(dut):\n"
            "    dut.a.value=0\n    await Timer(3,unit='ns')\n"
            "    dut.a.value=1\n    await Timer(3,unit='ns')\n    assert int(dut.y.value)==1\n")
    else:
        tb = benches / "tb_unit.v"
        tb.write_text("`timescale 1ns/1ps\nmodule tb_unit;\nreg a=0; wire y;\nunit dut(a,y);\n"
            "initial begin #5; a=1; #5;\n"
            "if(y!==1) begin $display(\"ORACLE_TB_DONE pass=0/1\"); $fatal(1,\"functional mismatch\"); end\n"
            "$display(\"ORACLE_TB_DONE pass=1/1\"); $finish; end\nendmodule\n")
    class NativeState(dict):
        metrics = {}
    state = NativeState(nl=str(netlist), sdf={"typical": str(sdf)})
    config = {"DESIGN_NAME": "unit", "CELL_VERILOG_MODELS": [str(model)]}
    return state, config


@pytest.mark.parametrize("different,annotated,expected", [
    (False, True, "PASS"), (True, True, "FAIL"), (False, False, "NOT_MEASURED"),
])
@pytest.mark.parametrize("cocotb", [False, True])
def test_native_gls_annotations_and_function(tmp_path, different, annotated, expected, cocotb):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    if cocotb and not shutil.which("cocotb-config"):
        pytest.skip("Native cocotb is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, different=different, annotated=annotated, cocotb=cocotb)
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == expected, result
    if expected == "NOT_MEASURED":
        assert "gls_failures" not in result["metrics"]
    else:
        assert result["metrics"]["gls_failures"] == int(different), result
        assert result["metrics"]["final_gls_function_timing_errors"] == int(different), result
        assert result["metrics"]["sdf_delays_applied"] > 0, result
    assert not (directory / "result.json").exists()


def test_gls_names_missing_native_inputs(tmp_path):
    result = gls(tmp_path, tmp_path, {}, Commands(tmp_path), state={}, config={})
    assert not result["ran"] and "State netlist" in result["detail"]


def test_gls_replays_every_state_corner(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    state["sdf"]["second_corner"] = state["sdf"]["typical"]
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert [row["corner"] for row in result["native_steps"]] == ["typical", "second_corner"]
    assert all(row["status"] == "PASS" and row["tests"] == 1 for row in result["native_steps"])
    assert result["metrics"]["gls_failures"] == 0


def test_gls_requires_functional_evidence_even_with_annotation(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    bench = project / "phase2/stage1/sim/tb_unit.v"
    bench.write_text(bench.read_text().replace('$display("ORACLE_TB_DONE pass=1/1");', ""))
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["metrics"]["sdf_delays_applied"] > 0
    assert "gls_failures" not in result["metrics"]
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("connected", [False, True])
def test_gls_accepts_native_physical_cell_models(tmp_path, connected):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    model = Path(config["CELL_VERILOG_MODELS"][0])
    port, connection = ("inout node", ".node(a)") if connected else ("", "")
    model.write_text(model.read_text() + f"module physical_cell({port}); endmodule\n")
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("endmodule", f"physical_cell fill({connection});\nendmodule"))
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == "PASS", result
