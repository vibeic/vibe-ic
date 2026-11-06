#!/usr/bin/env python3
"""The core inset keeps the PDN ring far enough from the pads for pdngen to
strap the supply pads to it.

MEASURED (subservient x gf180mcuD, OpenROAD 26Q3-3002): pdngen connects a
supply pad with one strap per core-facing pin of the net it supplies, from
the pin across the pad edge to that net's ring, as wide as the pin. It keeps
a strap only when it is LONGER THAN IT IS WIDE (it reads the direction from
the aspect ratio; vibeic/OpenROAD #33). The ground pad's pins are 1.0 um deep
and 9.5-10.25 um wide; with the PDK's 0.46 um pad clearance its straps were
8.82 um (west) and 8.9 um (north, 2412 um die) long, all were cut, and the
core's ground grid had no source: Checker.PowerGridViolations, PSM-0069 on
VSS. With the ring 8 um further out the same pad connected on every edge.

So the producer records, per supplied net, how far beyond the pad edge the
ring's far edge must lie (pin width - pin depth), and the runner's core inset
reserves it. The synthetic library below has shallow pins (3 um wide, 1 um
deep: reach 2 um) and names nothing real.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

DOC = """# External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| South (S) | `a[1:0]` |
| East (E) | `b[1:0]` |
| North (N) | `c[2:0]` |
| West (W) | `q` |
"""

SPEC = {"top_module": "core", "top_ports": [
    {"name": "a", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
    {"name": "b", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
    {"name": "c", "direction": "input", "width": 3, "msb": 2, "lsb": 0},
    {"name": "q", "direction": "output", "width": 1},
]}

#: A pad-connected PDN ring shaped like a real one: 1.6 / 2.0 um rails 1.7 um
#: apart, 6 um off the core, a 0.46 um pad clearance, pads connected on `lv`.
PDN_RING = {"layers": ["lv", "lh"], "widths": [1.6, 2.0],
            "spacings": [1.7, 1.7], "core_offset_um": 6.0,
            "connect_to_pad_layers": ["lv"],
            "connects": [["lv", "lh"]], "min_clearance_um": 0.46}


def _pin(name: str, use: str, rects) -> list[str]:
    lines = [f"  PIN {name}", "    DIRECTION INOUT ;", f"    USE {use} ;",
             "    PORT"]
    for layer, rect in rects:
        lines += [f"      LAYER {layer} ;",
                  "        RECT " + " ".join(f"{v:.3f}" for v in rect) + " ;"]
    return lines + ["    END", f"  END {name}"]


def _macro(name: str, cls: str, pins=(), width=10) -> str:
    lines = [f"MACRO {name}", f"  CLASS {cls} ;",
             f"  SIZE {width}.000 BY 100.000 ;"]
    for pin, use, rects in pins:
        lines += _pin(pin, use, rects)
    return "\n".join(lines + [f"END {name}", ""])


#: The external rail's core-facing pins: 3 um wide, 1 um deep, on `lv`.
SHALLOW = [("lv", (1.0, 99.0, 4.0, 100.0)), ("lv", (6.0, 99.0, 9.0, 100.0))]


def _supply_cell(name: str, external: str, use: str, facing=SHALLOW,
                 opposite_facing=()) -> str:
    """A supply bridge whose EXTERNAL rail alone reaches the core-facing edge
    (y = 100 in the master frame). Its other rails run the width of the cell
    as abutment rails, unless `opposite_facing` gives the opposite-polarity
    rail core-facing metal too (an ESD return that reaches the edge)."""
    ring = {"IOVDD": ("POWER", (0.0, 80.0, 10.0, 84.0)),
            "IOVSS": ("GROUND", (0.0, 86.0, 10.0, 90.0))}
    core = ("VDD", "POWER") if use == "GROUND" else ("VSS", "GROUND")
    pins = []
    for pin, (pin_use, rect) in ring.items():
        if pin == external:
            pins.append((pin, pin_use, list(facing)))
        else:
            pins.append((pin, pin_use, [("lh", rect)] + list(opposite_facing)))
    pins.append((core[0], core[1], [("lh", (0.0, 70.0, 10.0, 74.0))]))
    return _macro(name, "PAD POWER", pins)


def _tree(tmp_path: Path, ground_facing=SHALLOW, ground_opposite=()
          ) -> tuple[Path, Path]:
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
        "SITE test_io_site\n  CLASS PAD ;\n  SIZE 1 BY 100 ;\nEND test_io_site\n"
        "SITE test_io_corner_site\n  CLASS PAD ;\n  SIZE 40 BY 40 ;\nEND test_io_corner_site\n"
        + _macro("test_io__in", "PAD INPUT", [("PAD", "SIGNAL", [])])
        + _macro("test_io__bi", "PAD INOUT", [("PAD", "SIGNAL", [])])
        + _macro("test_io__fill", "PAD SPACER", width=1)
        + _macro("test_io__cor", "ENDCAP BOTTOMLEFT", width=40)
        + _supply_cell("test_io__pbridge", "IOVDD", "POWER")
        + _supply_cell("test_io__gbridge", "IOVSS", "GROUND",
                       facing=ground_facing, opposite_facing=ground_opposite)
    )
    (lefdir / "test_io.lef").write_text(text)
    cfgdir = root / "testpdk/libs.tech/someflow/test_io"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config.tcl").write_text(
        'set ::env(PAD_SITE_NAME) "test_io_site"\n'
        'set ::env(PAD_CORNER_SITE_NAME) "test_io_corner_site"\n'
        'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"\n'
        'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"\n'
        'set ::env(PAD_EDGE_SPACING) "5"\n'
        'set ::env(PAD_PLACE_IO_TERMINALS) '
        '"test_io__in/PAD test_io__bi/PAD"\n')
    return project, root


def _pdk(root: Path) -> SimpleNamespace:
    return SimpleNamespace(name="testpdk", pdn_ring=dict(PDN_RING),
                           tech_lef=str(root / "unused.tlef"),
                           liberty=str(root / "unused.lib"))


def _produce(project: Path, root: Path, monkeypatch, pdk=None):
    """Step 15.5ic's producer with the original host invocation inputs."""
    import _progress_run as _pr
    cfg = pdk or _pdk(root)
    result = _pr.run([
        sys.executable, str(PROGRAMS / "io_pad_chip_top_gen.py"), str(project),
        "--pdk-root", str(root), "--pdk", "testpdk",
        "--power-net", "VDD", "--ground-net", "VSS",
        "--pad-connect-layers", json.dumps(cfg.pdn_ring["connect_to_pad_layers"]),
        "--tie-high-cell", "", "--tie-high-pin", "",
        "--tie-low-cell", "", "--tie-low-pin", "",
        "--tie-liberty", cfg.liberty,
    ], capture_output=True, text=True, errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(
        (project / "reports/phase3/io_pad_chip_top.json").read_text())




def test_the_producer_records_how_far_the_ring_must_stay_from_the_pads(
        tmp_path, monkeypatch):
    project, root = _tree(tmp_path)
    rec = _produce(project, root, monkeypatch)
    reach = rec["power_pad_plan"]["pad_strap_reach"]
    assert reach["verdict"] == "MEASURED"
    assert reach["reach_um"] == pytest.approx(2.0)
    assert rec["die_required_um"]["pad_strap_reach_um"] == pytest.approx(2.0)
    ground = reach["cells"]["test_io__gbridge"]
    assert ground["net"] == "VSS"
    # the same 3 x 1 um pins on every edge, measured across the edge
    for side in "SENW":
        straps = ground["sides"][side]["straps"]
        assert [(s["pin"], s["width_um"], s["depth_um"]) for s in straps] == [
            ("IOVSS", 3.0, 1.0), ("IOVSS", 3.0, 1.0)]
    # the edge is not chosen by reach: the shortest signal edge keeps the pair
    assert rec["power_pad_plan"]["placement_side"] == "W"








def test_only_the_supplied_nets_pins_are_measured(tmp_path, monkeypatch):
    """pdngen straps each ITerm on its own net. The ground cell's IOVDD ESD
    return also reaches the core-facing edge here, 8 um wide and 0.5 um deep
    (reach 7.5); it never sources VSS, so the ground cell's reach stays its
    IOVSS pins' 2 um."""
    project, root = _tree(tmp_path, ground_opposite=[
        ("lv", (1.0, 99.5, 9.0, 100.0))])
    rec = _produce(project, root, monkeypatch)
    ground = rec["power_pad_plan"]["pad_strap_reach"]["cells"]["test_io__gbridge"]
    assert ground["reach_um"] == pytest.approx(2.0)
    assert {s["pin"] for s in ground["sides"]["W"]["straps"]} == {"IOVSS"}


def test_only_the_pad_connect_layers_are_measured(tmp_path, monkeypatch):
    """A core-facing pin on a layer the PDN does not connect pads on is not a
    strap pdngen draws (`-connect_to_pad_layers`)."""
    project, root = _tree(tmp_path, ground_facing=SHALLOW + [
        ("lh", (1.0, 99.8, 9.0, 100.0))])
    rec = _produce(project, root, monkeypatch)
    ground = rec["power_pad_plan"]["pad_strap_reach"]["cells"]["test_io__gbridge"]
    assert ground["reach_um"] == pytest.approx(2.0)
    assert {s["layer"] for s in ground["sides"]["S"]["straps"]} == {"lv"}


def test_a_supply_net_with_no_core_facing_pin_is_not_measured(
        tmp_path, monkeypatch):
    project, root = _tree(tmp_path, ground_facing=[
        ("lv", (1.0, 50.0, 4.0, 60.0))])
    rec = _produce(project, root, monkeypatch)
    reach = rec["power_pad_plan"]["pad_strap_reach"]
    assert reach["verdict"] == "NOT_DETERMINED"
    assert reach["reach_um"] is None
    assert reach["cells"]["test_io__gbridge"]["verdict"] == "NOT_DETERMINED"
    assert rec["die_required_um"]["pad_strap_reach_um"] is None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))


def test_rotated_native_pads_measure_the_actual_core_facing_pins(tmp_path, monkeypatch):
    project, root = _tree(tmp_path)
    lef = root / "testpdk/libs.ref/test_io/lef/test_io.lef"
    text = lef.read_text()
    # Swap the shallow pin rectangles to the master bottom edge, without
    # changing the cell outline. The native R180 rows face them into the core.
    text = text.replace("1.000 99.000 4.000 100.000", "1.000 0.000 4.000 1.000")
    text = text.replace("6.000 99.000 9.000 100.000", "6.000 0.000 9.000 1.000")
    lef.write_text(text)
    cfg = root / "testpdk/libs.tech/someflow/test_io/config.tcl"
    with cfg.open("a") as f:
        for axis in ("HORIZONTAL", "VERTICAL", "CORNER"):
            f.write(f'set ::env(PAD_ROTATION_{axis}) "R180"\n')
    rec = _produce(project, root, monkeypatch)
    reach = rec["power_pad_plan"]["pad_strap_reach"]
    assert reach["verdict"] == "MEASURED"
    assert reach["reach_um"] == pytest.approx(2.0)
    assert rec["derived_answers"]["pad_rotations"]["vertical"] == "R180"
    for cell in reach["cells"].values():
        assert all(side["straps"] for side in cell["sides"].values())
