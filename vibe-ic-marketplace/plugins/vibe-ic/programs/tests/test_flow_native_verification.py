from __future__ import annotations

from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from flow_native_adapters import Commands
from flow_native_verification import eqy, eqy_partitions, reset_boundary, xor


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


@pytest.mark.parametrize("different", [False, True])
def test_actual_eqy_reads_corner_pad_models_with_vector_controls(tmp_path, different):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    gold, gate, liberty, pad = [tmp_path / name for name in
                                ("gold.v", "gate.v", "cells.lib", "pads.lib")]
    source = ("module unit(input a, b, input [1:0] mode, output y);\n"
              "wire received; neutral_pad u_pad(.PAD(a), .MODE(mode), .Y(received));\n"
              "assign y=received ^ b; endmodule\n")
    gold.write_text(source)
    gate.write_text(source.replace("received ^ b", "received & b") if different else source)
    liberty.write_text("library(neutral) {}\n")
    pad.write_text("""library (neutral_pads) {
 type (control_pair) {
  base_type : array;
  data_type : bit;
  bit_width : 2;
  bit_from : 1;
  bit_to : 0;
  downto : true;
 }
 cell (neutral_pad) {
  pin (PAD) { direction : input; }
  bus (MODE) { bus_type : control_pair; direction : input; }
  pin (Y) { direction : output; function : "PAD"; }
 }
}
""")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]},
              "PAD_LIBS": {"typ*": [str(pad)], "slow": [str(tmp_path / "unused.lib")]}}
    class ReadInputs(Commands):
        def run(self, argv, cwd=None):
            sections = Path(argv[-1]).read_text().split("[script]", 1)[0]
            self.source_codes = {}
            for arm in ("gold", "gate"):
                source = sections.split(f"[{arm}]\n", 1)[1].split("\n[", 1)[0]
                script = "; ".join(source.strip().splitlines()) + "; hierarchy -check -top unit"
                completed = super().run(["yosys", "-Q", "-T", "-p", script], cwd=cwd)
                self.source_codes[arm] = completed.returncode
            return completed

    commands = ReadInputs(tmp_path)
    result = eqy(tmp_path, tmp_path, {}, commands, state={"nl": str(gate)}, config=config)
    assert commands.source_codes == {"gold": 0, "gate": 0}, result
    assert result["metrics"] == {}


def test_missing_selected_pad_model_does_not_launch_eqy(tmp_path):
    source, liberty = tmp_path / "design.v", tmp_path / "cells.lib"
    source.write_text("module unit; endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(source)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]},
              "PAD_LIBS": {"typical": [str(tmp_path / "missing.lib")]}}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(source)}, config=config)
    assert result["ran"] is False
    assert result["metrics"] == {}


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
