"""D75 binds the existing bare-die package/test consumers without approving tapeout."""
from __future__ import annotations

import json
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import _submission_template as ST  # noqa: E402
import flow109_package_electrical as D67  # noqa: E402
import flow109_package_ready as D75  # noqa: E402
import submission_template_ingest as ING  # noqa: E402
import test_flow109_package_electrical as D67T  # noqa: E402
from programs.tests._hostpaths import require_repo  # noqa: E402


def test_d75_adapter_loads_by_path_with_existing_consumers(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "flow109_package_ready_path_control", PROGRAMS / "flow109_package_ready.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.STEP == "D75"
    project = _project(tmp_path)
    result = module.execute(project, def_path=project / module.PAD_DEF,
        tech_lef=project / "input/pdk/tech.tlef", io_lefs=[project / "input/pdk/io.lef"])
    assert result["component_status"] == "PASS"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value,
                    encoding="utf-8")




def _declaration():
    doc = TD.blank_declaration()
    doc["answers"]["deliverable"] = TD.DELIVERABLE_DIE
    doc[TD.PROVENANCE_KEY] = {"deliverable": {
        "answered_by": TD.ANSWERED_BY_OWNER_VALUE,
        "citation": "D75 neutral fixture authority: deliver a bare die.",
    }}
    return doc


def _gds(path: Path) -> None:
    import klayout.db as k
    layout = k.Layout()
    layout.dbu = 0.001
    pad = layout.create_cell("PADX")
    pad.shapes(layout.layer(167, 5)).insert(k.Box(7500, 290000, 67500, 350000))
    top = layout.create_cell("chip_top")
    top.insert(k.CellInstArray(pad.cell_index(), k.Trans(850000, 0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(path))


def _project(root: Path) -> Path:
    project = root / "project"
    decl = _declaration()
    _write(project / TD.DECLARATION_REL, decl)
    own = _declaration()
    own["operator_template"] = {
        "path": None, "slot": None,
        "absent_reason": "Owner selected independent bare-die tapeout.",
    }
    _write(project / "input/submission_template/operator_answers.json", own)
    _write(project / ST.DESIGN_ANSWERS_REL, own)
    _write(project / TD.SELF_TAPEOUT_REL,
           TD.SELF_TAPEOUT_MARKER + "\nowner-selected independent tapeout\n")
    _write(project / "input/docs/L3_interfaces.md", """\
## Physical Pad Placement

| side | signals |
|------|---------|
| East (E) | `clk` |
""")
    _write(project / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json", {
        "layer": "L20", "applicability": "NOT_APPLICABLE", "fields": {},
    })
    _write(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "layer": "L19", "fields": {"die_area_budget_um": "1000x1000"},
    })
    _write(project / "reports/phase3/io_pad_chip_top.json", {
        "program": "io_pad_chip_top_gen", "verdict": "WROTE",
        "chip_top_module": "chip_top",
        "io_library_lefs": ["input/pdk/io.lef"],
    })
    _write(project / "input/pdk/tech.tlef", """\
UNITS
  DATABASE MICRONS 2000 ;
END UNITS
LAYER Metal5
  TYPE ROUTING ;
  WIDTH 0.44 ;
END Metal5
""")
    _write(project / "input/pdk/io.lef", """\
VERSION 5.8 ;
MACRO PADX
  CLASS PAD ;
  ORIGIN 0 0 ;
  SIZE 75 BY 350 ;
  PIN PAD
    DIRECTION INOUT ;
    USE SIGNAL ;
    PORT
      LAYER Metal5 ;
      RECT 7.5 290 67.5 350 ;
    END
  END PAD
END PADX
END LIBRARY
""")
    _write(project / "input/pdk/layers.lyp", """\
<layer-properties><properties><name>OPEN</name><source>OPEN 167/5@1</source></properties></layer-properties>
""")
    _write(project / "input/submission_template/provider_target.json", {
        "provider": "neutral",
        "technical_target": {"dimensions_um": [1000, 1000],
                             "origin_um": [0, 0], "packaging": "bare_die"},
        "bond_pad_edge_distance": {
            "max_distance_um": 900,
            "opening_layer": {"name": "OPEN",
                              "layer_properties": "input/pdk/layers.lyp"},
            "io_lefs": ["input/pdk/io.lef"],
        },
    })
    _write(project / "phase3/stage3/pnr/padring.def", """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 2000 ;
DIEAREA ( 0 0 ) ( 2000000 2000000 ) ;
COMPONENTS 1 ;
- u_pad_clk PADX + PLACED ( 1700000 0 ) N ;
END COMPONENTS
PINS 1 ;
- clk + NET clk + DIRECTION INPUT + USE SIGNAL
  + PORT
    + LAYER Metal5 ( -60000 -60000 ) ( 60000 60000 )
    + PLACED ( 1820000 640000 ) N ;
END PINS
NETS 1 ;
- clk ( PIN clk ) ( u_pad_clk PAD ) ;
END NETS
END DESIGN
""")
    _gds(project / "phase3/stage4/gds/chip_top.gds")
    phase3 = project / "reports/phase3"
    _write(phase3 / "perc_equivalent.json", {
        "verdict": "PASS", "categories": [
            {"category": "ESD", "status": "AUTOMATED", "result": "PASS"}],
    })
    _write(phase3 / "perc_equivalent.rpt", "OVERALL VERDICT: PASS\nESD\n")
    _write(phase3 / "PERC_SIGNOFF_MEMO.md", "**Overall verdict:** `PASS`\nESD\n")
    return project




def _by_name(result, name):
    return next(check for check in result["checks"] if check["check"] == name)


def _produced_d67(project: Path):
    """Run the supplied D67 producer on its neutral checked-in RLC model."""
    context, requirements, reference = D67T._case(project)
    fixture = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                           "programs", "tests", "fixtures", "flow109_d67",
                           "package.sp")
    assert Path(requirements["cases"][0]["model"]["path"]).resolve() == fixture.resolve()
    report = D67T._native(project, context)
    assert report["component_status"] == "PASS", report
    return context, requirements, reference, report














def _retained_catalogue(project: Path, tmp_path: Path) -> Path:
    catalogue = project / ST.STAGED_TEMPLATE_REL
    catalogue.mkdir(parents=True, exist_ok=True)
    source = catalogue / "neutral.json"
    source.write_text(json.dumps({
        "DIE_AREA": [0, 0, 1000, 1000], "SEAL_RING_WIDTH": 10}))
    reason = json.loads((project / ST.DESIGN_ANSWERS_REL).read_text())[
        "operator_template"]["absent_reason"]
    assert ING.main([str(project), "--template", str(catalogue),
                     "--no-template-reason", reason]) == 0
    return source
