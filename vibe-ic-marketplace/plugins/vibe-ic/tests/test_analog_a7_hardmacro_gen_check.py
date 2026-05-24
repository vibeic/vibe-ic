"""tests/test_analog_a7_hardmacro_gen_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "analog_a7_hardmacro_gen_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _hardmacro(project: Path, block: str,
               lef_extra: str = "",
               lib_extra: str = "",
               v_extra: str = "") -> None:
    h = project / "phase3" / "analog" / "hardmacro" / block
    h.mkdir(parents=True, exist_ok=True)
    (h / f"{block}.lef").write_text(
        "VERSION 5.7 ;\nBUSBITCHARS \"[]\" ;\nDIVIDERCHAR \"/\" ;\n"
        f"MACRO {block}\n  CLASS BLOCK ;\n  SIZE 80 BY 60 ;\n"
        + "  PIN VDD DIRECTION INOUT ; USE POWER ; END VDD\n"
        + "  PIN GND DIRECTION INOUT ; USE GROUND ; END GND\n"
        + "  PIN OUT DIRECTION OUTPUT ; END OUT\n"
        + "  PIN EN DIRECTION INPUT ; END EN\n"
        + "  PIN VREF DIRECTION INPUT ; END VREF\n"
        + f"END {block}\nEND LIBRARY\n" + lef_extra
    )
    (h / f"{block}.lib").write_text(
        f"library({block}_lib) {{\n  technology(cmos);\n"
        + "  delay_model : table_lookup;\n"
        + "  time_unit : 1ns;\n  voltage_unit : 1V;\n"
        + "  current_unit : 1mA;\n  capacitive_load_unit (1, pf);\n"
        + f"  cell({block}) {{\n"
        + "    pin(OUT) {direction:output; capacitance:0.05;}\n"
        + "    pin(EN)  {direction:input;  capacitance:0.02;}\n"
        + "  }\n}\n" + lib_extra
    )
    (h / f"{block}.v").write_text(
        f"// {block} behavioural model\n"
        + f"module {block}(input wire EN, output wire OUT,\n"
        + "                  inout wire VDD, inout wire GND);\n"
        + "  assign OUT = EN ? 1'b1 : 1'bz;\n"
        + "endmodule\n" + v_extra
    )


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-hardmacro-gen"


def test_lef_missing_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "hardmacro" / "ldo" / "ldo.lef").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_HARDMACRO_LEF_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_stub_marker_in_v_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo",
               v_extra="// attestation_kind: ai_authored_methodology_stub\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_HARDMACRO_STUB_MARKER" in f["rule"]
               for f in rpt["findings"])


def test_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    h = tmp_path / "phase3" / "analog" / "hardmacro" / "ldo"
    h.mkdir(parents=True, exist_ok=True)
    (h / "ldo.lef").write_text("VERSION 5.7 ;\n")  # < 250B
    (h / "ldo.lib").write_text(
        "library(ldo_lib) {\n  technology(cmos);\n  delay_model : table_lookup;\n"
        + "  cell(ldo) { pin(OUT) {direction:output; capacitance:0.05;} }\n}\n")
    (h / "ldo.v").write_text(
        "module ldo(input wire EN, output wire OUT);\n  assign OUT = EN;\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A7_HARDMACRO_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
