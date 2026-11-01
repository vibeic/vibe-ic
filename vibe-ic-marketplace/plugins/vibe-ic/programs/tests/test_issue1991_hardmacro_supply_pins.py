#!/usr/bin/env python3
"""Issue #1991 — a digital hardmacro kit must expose real supply pins.

The top-level routed DEF normally carries the std-cell rails in SPECIALNETS,
not in PINS.  Step 37.5ip used only PINS, so it could publish a LEF and Liberty
with zero supplies even though the PDK and routed power grid both named them.

These tests exercise the producer, not a second checker: the PDK std-cell LEF
supplies the rail names/types, the routed DEF supplies physical rail geometry,
and the resulting LEF/Liberty/documents must all report the same rails.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


PROGRAMS = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve()
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import digital_hardmacro_gen as gen  # noqa: E402

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
from _hostpaths import require_repo  # noqa: E402
from _release_kit import (  # noqa: E402
    SUBJECT, build_gds, build_project, docs_dir,
)


DEF_NO_TOP_PG = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN macro_a ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 50000 ) ;
PINS 1 ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER metal2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 200 10000 ) N ;
END PINS
SPECIALNETS 2 ;
    - rail_hi ( * rail_hi ) + USE POWER
      + ROUTED metal4 2000 + SHAPE STRIPE
        ( 10000 45000 ) ( 90000 45000 ) ;
    - rail_lo ( * rail_lo ) + USE GROUND
      + ROUTED metal4 2000 + SHAPE STRIPE
        ( 10000 5000 ) ( 90000 5000 ) ;
END SPECIALNETS
END DESIGN
"""


CELL_LEF = """VERSION 5.8 ;
MACRO cell_x
  CLASS CORE ;
  SIZE 2 BY 4 ;
  PIN rail_hi
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER metal1 ;
      RECT 0 3.6 2 4 ;
    END
  END rail_hi
  PIN well_hi
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER nwell ;
      RECT 0 0 2 4 ;
    END
  END well_hi
  PIN rail_lo
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER metal1 ;
      RECT 0 0 2 0.4 ;
    END
  END rail_lo
  PIN well_lo
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER pwell ;
      RECT 0 0 2 4 ;
    END
  END well_lo
END cell_x
END LIBRARY
"""


class _FakeSite:
    in_container = False
    where = "synthetic host PDK"

    def magic_version(self) -> str:
        return "test-double"


def _pdk(root: Path, cell_lef: str = CELL_LEF) -> Path:
    # The strict producer compares the caller's exact directory identity with
    # the project's current PDK declaration.  Keep the synthetic root named
    # like the existing typed release fixture (gf180mcuD), rather than making
    # the producer infer or forgive an identity mismatch.
    if root.name != "gf180mcuD":
        root = root / "gf180mcuD"
    magic = root / "libs.tech" / "magic"
    magic.mkdir(parents=True)
    (magic / "generic.magicrc").write_text("# test technology\n")
    if cell_lef:
        lef = root / "libs.ref" / "cells" / "lef"
        lef.mkdir(parents=True)
        (lef / "cells.lef").write_text(cell_lef)
    return root


def _project(root: Path, def_text: str = DEF_NO_TOP_PG,
             design: str = "macro_a", gds: bytes | None = None) -> Path:
    # Start from the existing release fixture builder so the owner-attested
    # HARDMACRO route, current PDK declaration, and typed source layout are
    # present.  The producer-specific routed DEF/GDS below remain the sole
    # subject of these tests; no stale hardmacro view is used as evidence.
    build_project(root, packages=(design,))
    shutil = __import__("shutil")
    shutil.rmtree(root / "phase3" / "stage4" / "hardmacro")
    pnr = root / "phase3" / "stage3" / "pnr"
    out = root / "phase3" / "stage4" / "gds"
    pnr.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text(def_text)
    (out / f"{design}.gds").write_bytes(gds or build_gds(design, 100, 50))
    return root


def _fixture_magic_sidecars(out_lef: Path) -> None:
    """Write the producer's ordinary sidecars for a mocked Magic result."""
    hm = Path(out_lef).parent
    (hm / "digital_lef.tcl").write_text(
        "# Fixture-bound Magic recipe; no native tool was run.\n")
    (hm / "digital_lef.log").write_text(
        "SYNTHETIC FIXTURE ONLY\nDIGITAL_LEF_WRITE_DONE\n")


def _fixture_timing(project: Path, design: str, _container: str,
                    out_dir: Path, extra_liberties=(), *, native_attempts=None):
    """Return a typed, hash-bound interface timing result for these tests."""
    import _physical_current as current

    pnr = project / "phase3" / "stage3" / "pnr"
    spef_dir = project / "phase3" / "stage3" / "extracted" / "spef_corners"
    report = project / "reports" / "phase3" / "sta_mcorner_ocv.rpt"
    netlist = pnr / f"{design}_pnr.v"
    sdc = pnr / "constraint.sdc"
    spef = spef_dir / f"{design}.max.spef"
    pdk_lib = project / "input" / "pdk" / "fixture.lib"
    recipe = out_dir / f".{design}_fixture_etm.tcl"
    for path in (pnr, spef_dir, report.parent, pdk_lib.parent, out_dir):
        path.mkdir(parents=True, exist_ok=True)
    netlist.write_text(f"module {design} (input clk); endmodule\n")
    sdc.write_text("create_clock -name clk -period 20 [get_ports clk]\n")
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    report.write_text("fixture-bound STA; no native measurement.\n")
    pdk_lib.write_text("library (fixture) { cell (fixture) { } }\n")
    recipe.write_text("# fixture-bound timing recipe\n")
    (out_dir / "timing_native.log").write_text(
        "SYNTHETIC FIXTURE ONLY\nTIMING_MODEL_DONE\n")
    inputs = {
        "netlist": current.entry(project, netlist),
        "sdc": current.entry(project, sdc),
        "spef": current.entry(project, spef),
        "sta_report": current.entry(project, report),
        "pdk_liberty": current.entry(project, pdk_lib, external=True),
        "recipe": current.entry(project, recipe),
    }
    text = (
        f"library ({design}_lib) {{\n"
        f"  cell ({design}) {{\n"
        "    timing () { related_pin : \"clk\"; }\n"
        "  }\n"
        "}\n"
    )
    return text, {
        "method": "fixture-bound timing model",
        "netlist": str(netlist),
        "current_inputs": inputs,
        "execution": {"rc": 0, "argv": ["synthetic-fixture", "timing"]},
        "characterised": True,
        "reason_class": None,
        "why": "fixture-bound; no native measurement",
    }


def _lef_from_def(def_text: str, design: str) -> str:
    """Small Magic double: reflect the DEF PINS it was actually handed."""
    lines = [f"MACRO {design}", "  SIZE 100 BY 50 ;"]
    for pin in gen.read_interface(def_text):
        lines += [
            f"  PIN {pin.name}",
            "    DIRECTION INOUT ;" if pin.is_pg else
            f"    DIRECTION {pin.direction} ;",
            f"    USE {pin.use or 'SIGNAL'} ;",
            "    PORT",
            "      LAYER metal4 ;",
            "      RECT 1 1 2 2 ;",
            "    END",
            f"  END {pin.name}",
        ]
    lines += [f"END {design}", "END LIBRARY", ""]
    return "\n".join(lines)


def _fake_magic(monkeypatch, captured: dict, *, timing: bool = False) -> None:
    monkeypatch.setattr(gen, "find_magic_site", lambda _container="": _FakeSite())

    def fake_write(top, _gds, def_file, out_lef, _pdk_root, _full, _pinonly,
                   **_kwargs):
        text = Path(def_file).read_text()
        captured["def"] = text
        Path(out_lef).write_text(_lef_from_def(text, top))
        _fixture_magic_sidecars(Path(out_lef))
        return True, ""

    monkeypatch.setattr(gen, "write_lef_with_magic", fake_write)
    if timing:
        monkeypatch.setattr(gen, "characterise_liberty", _fixture_timing)


def test_generator_adds_pdk_rails_to_lef_and_liberty(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    captured = {}
    _fake_magic(monkeypatch, captured, timing=True)

    rc, record = gen.run(project, str(pdk), False, False)

    lef = (project / "phase3/stage4/hardmacro/macro_a.lef").read_text()
    lib = (project / "phase3/stage4/hardmacro/macro_a.lib").read_text()
    assert rc == 0, record
    assert record.interface["power_ground"] == ["rail_hi", "rail_lo"]
    assert "PIN rail_hi" in lef and "USE POWER" in lef
    assert "PIN rail_lo" in lef and "USE GROUND" in lef
    assert "pg_pin (rail_hi) { pg_type : primary_power ; }" in lib
    assert "pg_pin (rail_lo) { pg_type : primary_ground ; }" in lib
    assert "PINS 3 ;" in captured["def"]


def test_an_unrelated_power_pin_does_not_stand_in_for_the_pdk_power_rail():
    text = DEF_NO_TOP_PG.replace(
        "PINS 1 ;", "PINS 2 ;").replace(
        "END PINS", "    - aux_hi + NET aux_hi + DIRECTION INOUT + USE POWER\n"
        "      + PORT\n"
        "        + LAYER metal2 ( -200 -200 ) ( 200 200 )\n"
        "        + PLACED ( 400 10000 ) N ;\n"
        "END PINS")
    rails = gen.discover_stdcell_rails(CELL_LEF, "metal")

    augmented, pins, reason = gen.add_supply_pins_to_def(text, rails)

    assert augmented is not None, reason
    assert {(p.name, p.use) for p in pins if p.is_pg} == {
        ("aux_hi", "POWER"), ("rail_hi", "POWER"),
        ("rail_lo", "GROUND")}


def test_no_pdk_rail_authority_is_labeled_not_integrable(tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk", cell_lef="")
    captured = {}
    _fake_magic(monkeypatch, captured)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc != 0
    assert record.status == "REFUSED_NOT_INTEGRABLE"
    assert "supply" in record.reason.lower()
    assert not (project / "phase3/stage4/hardmacro").exists()


def test_magic_success_that_drops_one_supply_is_not_integrable(
        tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    monkeypatch.setattr(gen, "find_magic_site",
                        lambda _container="": _FakeSite())

    def drop_power(top, _gds, def_file, out_lef, *_args, **_kwargs):
        text = _lef_from_def(Path(def_file).read_text(), top)
        head = text.index("  PIN rail_hi")
        tail = text.index("  END rail_hi") + len("  END rail_hi\n")
        Path(out_lef).write_text(text[:head] + text[tail:])
        _fixture_magic_sidecars(Path(out_lef))
        return True, ""

    monkeypatch.setattr(gen, "write_lef_with_magic", drop_power)
    monkeypatch.setattr(gen, "characterise_liberty", _fixture_timing)
    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == 1
    assert record.status == "REFUSED_NOT_INTEGRABLE"
    assert record.interface["integrable"] is False
    assert record.interface["staged_lef_power_ground"] == {
        "rail_lo": "GROUND"}


def test_real_routed_def_without_top_pg_is_recovered(tmp_path, monkeypatch):
    """Real-artefact backing: the published run has rails only in SPECIALNETS."""
    cell = require_repo(
        "benchmark-data", "ic", "spm", "v1.5.58_ihp-sg13g2")
    source_def = cell / "phase3/stage3/pnr/routed.def"
    source_gds = cell / "phase3/stage4/gds/spm.gds"
    text = source_def.read_text(errors="replace")
    assert not [p for p in gen.read_interface(text) if p.is_pg]

    project = _project(tmp_path / "project", text, "spm",
                       source_gds.read_bytes())
    real_names = CELL_LEF.replace("rail_hi", "VDD").replace("rail_lo", "VSS")
    pdk = _pdk(tmp_path / "pdk", real_names)
    captured = {}
    _fake_magic(monkeypatch, captured)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == 0, record
    assert record.interface["power_ground"] == ["VDD", "VSS"]
    assert {"VDD", "VSS"} <= {
        p.name for p in gen.read_interface(captured["def"]) if p.is_pg}


def test_datasheet_row_names_the_rails_instead_of_only_counting_them(tmp_path):
    project = build_project(tmp_path / "project", packages=(SUBJECT,))
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "ip_release_docs_gen.py"), str(project)],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    text = (docs_dir(project) / "IP_DATASHEET.md").read_text()
    row = next(line for line in text.splitlines()
               if line.startswith("| Declared supply rails |"))
    assert "VPWR (primary_power)" in row
    assert "VGND (primary_ground)" in row
    assert "| 2 |" not in row


def test_runner_passes_the_selected_cell_lef_and_metal_prefix(
        tmp_path, monkeypatch):
    import phase3_one_shot_runner as runner

    seen = {"cmds": []}

    def fake_run(cmd, **_kwargs):
        seen["cmds"].append([str(c) for c in cmd])
        return subprocess.CompletedProcess(cmd, 0, "produced\n", "")

    pdk = SimpleNamespace(
        name="sky130A",
        cell_lef="/pdk/stdcell.lef",
        metal_prefix="metal",
    )
    named_root = "/foss/pdks/sky130A"
    monkeypatch.setattr(runner, "_hardmacro_pdk_dir",
                        lambda _pdk, _container: named_root)
    # CZT-11 — the DISPATCHER moved, the assertions did not. This step
    # dispatches its producer through `_progress_run` (no wall clock)
    # instead of `subprocess.run(timeout=N)`, so a stub bound to
    # `subprocess.run` no longer intercepts anything and the real
    # producer runs. Retargeting the double is what keeps this test
    # measuring what it was written to measure.
    monkeypatch.setattr(runner._pr, "run", fake_run)

    result = runner.step_digital_hardmacro_gen(tmp_path, pdk, "eda")

    assert result.status == "PASS"
    producer = [cmd for cmd in seen["cmds"]
                if any(str(part).endswith("digital_hardmacro_gen.py")
                       for part in cmd)]
    assert len(producer) == 1, seen["cmds"]
    cmd = producer[0]
    assert "--pdk-root" in cmd
    assert cmd[cmd.index("--pdk-root") + 1] == named_root
    assert "--pdk-name" in cmd
    assert cmd[cmd.index("--pdk-name") + 1] == pdk.name
    assert "--cell-lef" in cmd
    assert cmd[cmd.index("--cell-lef") + 1] == pdk.cell_lef
    assert "--metal-prefix" in cmd
    assert cmd[cmd.index("--metal-prefix") + 1] == "metal"


def test_capture_routes_digital_hardmacro_to_the_owning_generator():
    plugin = PROGRAMS.parent
    routing = json.loads((plugin / "benchmark/CAPTURE_ROUTING.json").read_text())
    route = routing["steps"]["phase3.digital_hardmacro"]
    assert route["bucket_A_program"] == "programs/digital_hardmacro_gen.py"
    assert "programs/digital_hardmacro_check.py" in route["bucket_A_related"]
