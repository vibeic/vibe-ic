"""D45 adopted-netlist CDC/RDC row-local dispatch controls."""
from __future__ import annotations

import json
import shutil

import pytest

import _cdc_netlist as native


pytestmark = pytest.mark.skipif(shutil.which("yosys") is None, reason="native yosys absent")


































def test_yosys_internal_async_dff_is_not_mislabeled_as_zero_flops(tmp_path):
    model = {"modules": {"neutral": {"attributes": {"top": 1},
        "ports": {"clk": {"direction": "input", "bits": [2]},
                  "rst": {"direction": "input", "bits": [3]},
                  "d": {"direction": "input", "bits": [4]},
                  "q": {"direction": "output", "bits": [5]}},
        "netnames": {}, "cells": {"ff": {"type": "$_DFF_PP0_",
            "port_directions": {"C": "input", "D": "input", "Q": "output", "R": "input"},
            "connections": {"C": [2], "D": [4], "Q": [5], "R": [3]},
            "parameters": {}, "attributes": {}}}}}}
    path = tmp_path / "mapped.json"
    path.write_text(json.dumps(model))
    netlist = native.load(path, "neutral")
    observed_types = (netlist.cells["ff"]["type"], tuple(f.type for f in netlist.flops))
    assert observed_types == ("$_DFF_PP0_", ("$_DFF_PP0_",))
    assert native.clock_domains(netlist) == ["clk"]
    assert netlist.flops[0].arst == 3 and netlist.flops[0].arst_value == ["0"]


def test_yosys_internal_simple_dff_is_decoded_with_clock_and_reset_mux(tmp_path):
    model = {"modules": {"neutral": {"attributes": {"top": 1},
        "ports": {"clk": {"direction": "input", "bits": [2]},
                  "rst": {"direction": "input", "bits": [3]},
                  "d": {"direction": "input", "bits": [4]},
                  "q": {"direction": "output", "bits": [5]}},
        "netnames": {"reset_mux": {"bits": [6]}},
        "cells": {
            "mux": {"type": "$mux", "port_directions": {"A": "input", "B": "input", "S": "input", "Y": "output"},
                "connections": {"A": [4], "B": ["0"], "S": [3], "Y": [6]}, "parameters": {}, "attributes": {}},
            "ff": {"type": "$_DFF_P_", "port_directions": {"C": "input", "D": "input", "Q": "output"},
                "connections": {"C": [2], "D": [6], "Q": [5]}, "parameters": {}, "attributes": {}}}}}}
    path = tmp_path / "mapped.json"
    path.write_text(json.dumps(model))
    netlist = native.load(path, "neutral")
    assert native.clock_domains(netlist) == ["clk"]
    assert len(netlist.flops) == 1
    assert netlist.flops[0].type == "$_DFF_P_"
    assert netlist.flops[0].srst == 3
