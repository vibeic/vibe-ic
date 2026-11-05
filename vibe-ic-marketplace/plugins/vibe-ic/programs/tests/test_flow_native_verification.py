from __future__ import annotations

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from flow_native_adapters import Commands
from flow_native_verification import eqy, eqy_partitions, xor


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
    result = xor(tmp_path, tmp_path, {"metric": "unexplained_stream_xor"}, commands,
                 state=state, config={})
    assert result["ran"] and result["metrics"]["unexplained_stream_xor"] == 3
    assert not commands.records and result["tool_seconds"] == 0


def test_absent_xor_views_are_not_a_zero_count(tmp_path):
    class EmptyState(dict):
        metrics = {}
    result = xor(tmp_path, tmp_path, {}, Commands(tmp_path), state=EmptyState(), config={})
    assert not result["ran"] and not result["metrics"]


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
