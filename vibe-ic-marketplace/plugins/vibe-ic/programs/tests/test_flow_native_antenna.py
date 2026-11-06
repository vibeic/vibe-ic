from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

pytest.importorskip("librelane")
db = pytest.importorskip("klayout.db")
odb = pytest.importorskip("odb")

from librelane.common import Toolbox
from librelane.config import Config
from librelane.flows import Flow
from librelane.state import State
from librelane.steps import Step

import flow_engine as engine
import flow_native_analog_die as die


@pytest.fixture
def native_inputs(tmp_path):
    for source in (Path(__file__).parent / "fixtures/native_antenna").iterdir():
        shutil.copyfile(source, tmp_path / source.name)
    empty = tmp_path / "empty"
    empty.touch()
    sdc = tmp_path / "unit.sdc"
    sdc.touch()
    pdk = tmp_path / "pdks/neutral/libs.tech/librelane"
    (pdk / "cells").mkdir(parents=True)
    (pdk / "cells/config.tcl").touch()
    values = {
        "STD_CELL_LIBRARY": "cells", "VDD_PIN": "VDD", "GND_PIN": "VSS",
        "TECH_LEFS": f"nom {tmp_path / 'tech.lef'}",
        "PRIMARY_GDSII_STREAMOUT_TOOL": "klayout", "DEFAULT_CORNER": "nom",
        "STA_CORNERS": "nom", "RT_MIN_LAYER": "metal1", "RT_MAX_LAYER": "metal2",
        "SCL_GROUND_PINS": "VSS", "SCL_POWER_PINS": "VDD", "FILL_CELLS": "",
        "DECAP_CELLS": "", "LIB": f"nom {tmp_path / 'cells.lib'}",
        "CELL_LEFS": "", "CELL_GDS": "", "SYNTH_EXCLUDED_CELL_FILE": empty,
        "PNR_EXCLUDED_CELL_FILE": empty, "OUTPUT_CAP_LOAD": 0,
        "MAX_FANOUT_CONSTRAINT": 10, "CLOCK_UNCERTAINTY_CONSTRAINT": 0,
        "CLOCK_TRANSITION_CONSTRAINT": 0, "TIME_DERATING_CONSTRAINT": 0,
        "IO_DELAY_CONSTRAINT": 0, "SYNTH_DRIVING_CELL": "buf/Y",
        "SYNTH_TIEHI_CELL": "buf/Y", "SYNTH_TIELO_CELL": "buf/Y",
        "SYNTH_BUFFER_CELL": "buf/A/Y", "PLACE_SITE": "unit", "CELL_PAD_EXCLUDE": "",
        "KLAYOUT_TECH": empty, "KLAYOUT_PROPERTIES": empty,
        "KLAYOUT_DEF_LAYER_MAP": empty, "KLAYOUT_ANTENNA_RUNSET": tmp_path / "antenna.drc",
    }
    (pdk / "config.tcl").write_text("\n".join(
        f"set ::env({key}) {{{value}}}" for key, value in values.items()) + "\n")
    config, _ = Config.load({"DESIGN_NAME": "unit", "PNR_SDC_FILE": str(sdc)},
        Step.factory.get("OpenROAD.CheckAntennas").get_all_config_variables(),
        pdk="neutral", pdk_root=str(tmp_path / "pdks"), design_dir=str(tmp_path))
    assert "KLAYOUT_ANTENNA_RUNSET" not in config

    database = odb.dbDatabase.create()
    odb.read_lef(database, str(tmp_path / "tech.lef"))
    tech = database.getTech()
    chip = odb.dbChip.create(database, tech)
    block = odb.dbBlock.create(chip, "unit", "/")
    block.setDieArea(odb.Rect(0, 0, 200000, 200000))
    block.setMinRoutingLayer(1)
    block.setMaxRoutingLayer(2)
    for name in ("metal1", "metal2"):
        grid = odb.dbTrackGrid.create(block, tech.findLayer(name))
        grid.addGridPatternX(0, 200, 1000)
        grid.addGridPatternY(0, 200, 1000)
    gate = odb.dbInst.create(block, database.findMaster("buf"), "gate")
    gate.setLocation(0, 0)
    gate.setPlacementStatus("PLACED")
    net = odb.dbNet.create(block, "signal")
    pin = gate.findITerm("A")
    pin.connect(net)
    encoder = odb.dbWireEncoder()
    encoder.begin(odb.dbWire.create(net))
    encoder.newPath(tech.findLayer("metal1"), "ROUTED")
    encoder.addPoint(500, 500)
    encoder.addITerm(pin)
    encoder.addPoint(100000, 500)
    encoder.end()
    odb.write_db(database, str(tmp_path / "unit.odb"))
    return config


def input_state(project, metal_length):
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("unit")
    top.shapes(layout.layer(1, 0)).insert(db.Box(0, 0, 1000, 1000))
    top.shapes(layout.layer(2, 0)).insert(db.Box(0, 0, metal_length, 1000))
    gds = project / "unit.gds"
    layout.write(str(gds))
    return State.load({"odb": str(project / "unit.odb"), "gds": str(gds), "metrics": {}})


@pytest.mark.parametrize("target", ["ip_hardmacro", "shippable_gds"])
@pytest.mark.parametrize("case,expected", [("clear", "PASS"), ("violation", "FAIL"),
                                           ("no_deck", "NOT_MEASURED")])
def test_public_row_keeps_native_gds_result(tmp_path, monkeypatch, native_inputs, target, case, expected):
    config = native_inputs
    state = input_state(tmp_path, 100000 if case == "violation" else 1000)
    if case == "no_deck":
        config = config.copy(KLAYOUT_ANTENNA_RUNSET=None)

    def initialize(chain):
        if chain.owner is None:
            chain.owner = SimpleNamespace(config=config,
                gating_config_vars=Flow.factory.get("Classic").gating_config_vars)
            chain.config, chain.state = config.to_raw_dict(), state
            chain.toolbox = Toolbox(str(tmp_path / "tool_tmp"))

    monkeypatch.setattr(engine.NativeChain, "initialize", initialize)
    route = {"entry_step": "antenna_checks", "verify_through": "antenna_checks",
             "delivery_target": target, "input_contract": "structured"}
    row = engine.run(tmp_path, route=route)["steps"][0]
    assert row["status"] == expected, row
    steps = {step["name"]: step for step in row["native_steps"]}
    assert steps["OpenROAD.CheckAntennas"]["status"] == "PASS"
    assert row["native_metrics"]["antenna__violating__nets"] == 0
    assert row["native_metrics"]["antenna__violating__pins"] == 0
    assert row["native_metrics"]["route__antenna_violation__count"] == 0
    assert steps["Checker.KLayoutAntenna"]["status"] == expected
    if case == "no_deck":
        assert "klayout__antenna_error__count" not in row["native_metrics"]
        assert "NOT_MEASURED" in steps["Checker.KLayoutAntenna"]["detail"]
    else:
        assert row["native_metrics"]["klayout__antenna_error__count"] == int(case == "violation")
        report = tmp_path / "steps/antenna_checks/klayout_antenna/reports/antenna.klayout.lyrdb"
        assert str(report) in row["reports"] and report.is_file()
        checked = next(item for item in row["metrics"] if item["metric"] == "klayout__antenna_error__count")
        assert (checked["limit"], checked["status"]) == (0, expected)
    assert (tmp_path / "steps/antenna_checks/checker_klayoutantenna/state_in.json").is_file()
    assert (tmp_path / "steps/antenna_checks/state_out.json").is_file()


def test_analog_adapter_keeps_native_checker_failure(tmp_path, native_inputs):
    result = die.execute("antenna_checks", tmp_path, tmp_path / "output", None,
        state=input_state(tmp_path, 100000), config=native_inputs.to_raw_dict(),
        route={"delivery_target": "shippable_gds"})
    assert result["status"] == "FAIL", result
    assert result["metrics"]["antenna__violating__nets"] == 0
    assert result["metrics"]["klayout__antenna_error__count"] == 1
    assert result["native_steps"][-1]["name"] == "Checker.KLayoutAntenna"
    assert result["native_steps"][-1]["status"] == "FAIL"
