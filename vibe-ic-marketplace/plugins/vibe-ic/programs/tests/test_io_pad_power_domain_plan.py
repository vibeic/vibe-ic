#!/usr/bin/env python3
"""Project-owned supply pads are derived from LEF electrical roles."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
GEN = PROGRAMS / "io_pad_chip_top_gen.py"

DOC = """# External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| South (S) | `rst` |
| East (E) | `clk` |
| North (N) | `d[1:0]` |
| West (W) | `q` |
"""

SPEC = {"top_module": "core", "top_ports": [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "rst", "direction": "input", "width": 1},
    {"name": "d", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
    {"name": "q", "direction": "output", "width": 1},
]}


def _macro(name: str, cls: str, pins=(), width=10) -> str:
    lines = [f"MACRO {name}", f"  CLASS {cls} ;",
             f"  SIZE {width}.000 BY 100.000 ;"]
    for pin, use in pins:
        lines += [f"  PIN {pin}", "    DIRECTION INOUT ;",
                  f"    USE {use} ;", f"  END {pin}"]
    return "\n".join(lines + [f"END {name}", ""])


def _tree(tmp_path: Path, *, with_ground=True) -> tuple[Path, Path]:
    project = tmp_path / "project"
    (project / "input/docs").mkdir(parents=True)
    (project / "input/docs/L3.md").write_text(DOC)
    (project / "phase1/generated_docs").mkdir(parents=True)
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(SPEC))

    root = tmp_path / "pdk"
    lefdir = root / "testpdk/libs.ref/test_io/lef"
    lefdir.mkdir(parents=True)
    text = (
        _macro("test_io__in", "PAD INPUT", [("PAD", "SIGNAL")])
        + _macro("test_io__bi", "PAD INOUT", [("PAD", "SIGNAL")])
        + _macro("test_io__fill", "PAD SPACER", width=1)
        + _macro("test_io__cor", "ENDCAP BOTTOMLEFT", width=40)
        # External POWER bridge: IOVDD is the external terminal; the macro
        # omits the core VDD pin and returns through IOVSS/VSS.
        + _macro("test_io__pbridge", "PAD POWER", [
            ("IOVDD", "POWER"), ("IOVSS", "GROUND"), ("VSS", "GROUND")])
    )
    if with_ground:
        # Symmetric external GROUND bridge: IOVSS external, core VSS omitted.
        text += _macro("test_io__gbridge", "PAD POWER", [
            ("IOVDD", "POWER"), ("IOVSS", "GROUND"), ("VDD", "POWER")])
    (lefdir / "test_io.lef").write_text(text)
    cfgdir = root / "testpdk/libs.tech/someflow/test_io"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.tcl").write_text(
        'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"\n'
        'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"\n'
        'set ::env(PAD_EDGE_SPACING) "5"\n'
        'set ::env(PAD_PLACE_IO_TERMINALS) '
        '"test_io__in/PAD test_io__bi/PAD"\n')
    (root / "testpdk/SOURCES").write_text("open-pdk test-revision\n")
    return project, root


def _run(project: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GEN), str(project), "--pdk-root", str(root),
         "--pdk", "testpdk", "--power-net", "VDD", "--ground-net", "VSS"],
        capture_output=True, text=True)


def test_minimum_same_domain_pair_is_wired_and_recorded(tmp_path):
    project, root = _tree(tmp_path)
    result = _run(project, root)
    assert result.returncode == 0, result.stdout + result.stderr
    rec = json.loads(
        (project / "reports/phase3/io_pad_chip_top.json").read_text())
    plan = rec["power_pad_plan"]
    assert plan["domain_topology"] == "single_domain"
    assert plan["placement_side"] == "S"
    assert plan["capacity_from_lef"] == "NOT_DETERMINED"
    assert plan["pdk_sources"]["text"] == "open-pdk test-revision"
    assert plan["instances"] == ["u_pad_supply_power", "u_pad_supply_ground"]
    assert rec["derived_answers"]["pad_order_by_side"]["south"][:2] == plan["instances"]
    assert len(rec["pad_instances"]) == 7

    verilog = (project / rec["chip_top_verilog"]).read_text()
    assert "inout VDD" in verilog and "inout VSS" in verilog
    assert ("test_io__pbridge u_pad_supply_power "
            "(.IOVDD(VDD), .IOVSS(VSS), .VSS(VSS));") in verilog
    assert ("test_io__gbridge u_pad_supply_ground "
            "(.IOVDD(VDD), .IOVSS(VSS), .VDD(VDD));") in verilog


def test_missing_ground_bridge_refuses_instead_of_emitting_an_open_ring(tmp_path):
    project, root = _tree(tmp_path, with_ground=False)
    result = _run(project, root)
    assert result.returncode == 1
    assert "SUPPLY_PAD_PAIR_UNRESOLVED" in result.stdout
    rec = json.loads(
        (project / "reports/phase3/io_pad_chip_top.json").read_text())
    assert rec["verdict"] == "REFUSE"
    assert rec["rule"] == "SUPPLY_PAD_PAIR_UNRESOLVED"
