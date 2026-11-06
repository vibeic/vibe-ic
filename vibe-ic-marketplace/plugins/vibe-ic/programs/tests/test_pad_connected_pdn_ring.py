"""Pad-connected PDN rings are config-owned, geometry-fitted, and fail closed."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))
R = importlib.import_module("phase3_one_shot_runner")


CELL_LEF = """\
MACRO cellA
  CLASS CORE ;
  SIZE 2 BY 10 ;
  PIN PWR
    USE POWER ;
    PORT
      LAYER lower1 ;
        RECT 0 9.7 2 10.3 ;
    END
  END PWR
  PIN GND
    USE GROUND ;
    PORT
      LAYER lower1 ;
        RECT 0 -0.3 2 0.3 ;
    END
  END GND
END cellA
"""


TECH_LEF = """\
LAYER lower1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.5 ;
  WIDTH 0.2 ;
END lower1
LAYER upperV
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 1.0 ;
  WIDTH 0.4 ;
END upperV
LAYER upperH
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 1.0 ;
  WIDTH 0.4 ;
END upperH
"""


RING = {
    "layers": ["upperV", "upperH"],
    "widths": [0.8, 0.9],
    "spacings": [0.6, 0.7],
    "core_offset_um": 4.0,
    "connect_to_pad_layers": ["padFacing"],
    "connects": [["padFacing", "upperH"]],
    "min_clearance_um": 0.3,
}


def _pdk(tmp_path: Path, ring=RING):
    cell = tmp_path / "cells.lef"
    tech = tmp_path / "tech.lef"
    cell.write_text(CELL_LEF)
    tech.write_text(TECH_LEF)
    return R.PdkConfig(
        name="unit", liberty="/not/read.lib", tech_lef=str(tech),
        cell_lef=str(cell), cell_gds=None, site="site", drc_deck=None,
        metal_prefix="lower", tapcell_master=None,
        pdn_straps={
            "stripes": [
                {"layer": "upperV", "width": 0.8,
                 "pitch": 24.0, "offset": 3.0},
                {"layer": "upperH", "width": 0.9,
                 "pitch": 25.0, "offset": 3.2},
            ],
            "connects": [["lower1", "upperV"],
                         ["upperV", "upperH"]],
        },
        pdn_ring=ring,
    )


def test_registry_ring_is_bound_to_the_real_pdk_entry():
    registry = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    entries = [entry for entry in registry["pdks"]
               if entry.get("name") == "gf180mcuD"]
    assert len(entries) == 1
    ring = entries[0]["pdn_ring"]
    assert ring == {
        "layers": ["Metal4", "Metal5"],
        "widths": [1.6, 1.6],
        "spacings": [1.7, 1.7],
        "core_offset_um": 6.0,
        "connect_to_pad_layers": ["Metal2"],
        "connects": [["Metal2", "Metal5"], ["Metal2", "Metal4"]],
        "min_clearance_um": 0.46,
    }


def _self_tapeout(project: Path) -> None:
    """The delivery decides whether a ring pins the die (98109186b): a record
    an earlier run left on disk must not re-pin a floorplan to a ring THIS
    delivery does not build. These projects are self-tape-outs, which build
    their ring, so the record they write is the ring's own measurement."""
    st = project / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    (st / "SELF_TAPEOUT.txt").write_text("self tape-out\n", encoding="utf-8")
