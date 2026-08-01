"""tests/test_analog_a8_hardmacro_gen_check.py — A8 (renumbered from A7)"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a8_hardmacro_gen_check.py")


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


#: What the packaged circuit contains. Nothing writes `design_content` into a
#: LEF, a Liberty, a GDS or a behavioural Verilog, so the whole answer is the
#: corner artefact's — the A4 gate of record's own subject. The HAPPY-PATH
#: fixture carries it because this gate stopped signing off a macro digital
#: PnR will instantiate when nothing on the tree names the circuit it models;
#: a fixture that omitted it would be asserting that silence still signs off.
#: The FAILING fixtures are left exactly as they were: each already fails for
#: its own deliverable reason, and the gate asks the content question LAST.
DESIGN_BOUND = "structure_and_geometry"


def _baseline(project: Path, block: str, design_content=DESIGN_BOUND) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    doc = {"block": block, "_provenance": "real_ngspice",
           "corners": [{"name": "tt_27c_1v8", "simulator_run": True}]}
    if design_content is not None:
        doc["design_content"] = design_content
    (d / "corner_results.json").write_text(json.dumps(doc))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    _baseline(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"
    assert rpt["blocks_design_bound_pass"] == 1


def test_a_package_that_names_no_circuit_does_not_certify(
        tmp_path: Path) -> None:
    """The rule the happy path above now states. Every deliverable is present
    and substantive, so the only thing this can fail on is the certification.

    Measured before the fix: this gate and `analog_hardmacro_check` both
    answered PASS on a design-bound tree, a disclosed-library-default tree and
    a silent one, over the same complete package on which
    `analog_liberty_nonzero_delay_check` answered PASS /
    PASS_STRUCTURE_ONLY / FAIL.
    """
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    _baseline(tmp_path, "ldo", design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A8_DESIGN_CONTENT_UNDECLARED" in f["rule"]
               for f in rpt["findings"])


def test_a_disclosed_library_default_certifies_in_its_own_tier(
        tmp_path: Path) -> None:
    """Only silence costs. A package whose corner artefact records a library
    default still certifies — in the structure-only tier, never as a
    design-bound pass."""
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    _baseline(tmp_path, "ldo", design_content="structure_only")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS_STRUCTURE_ONLY"
    assert rpt["blocks_design_bound_pass"] == 0
    assert "STRUCTURE_ONLY:" in r.stdout, r.stdout


def test_a_missing_deliverable_is_still_a_missing_deliverable(
        tmp_path: Path) -> None:
    """ORDERING CONTROL. A package with no behavioural view is diagnosed as
    that, even on a tree that also says nothing about its subject — that
    finding names a deeper cause and answers this one as a side effect."""
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "hardmacro" / "ldo" / "ldo.v").unlink()
    _baseline(tmp_path, "ldo", design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in
             json.loads((tmp_path / "report.json").read_text())["findings"]}
    assert "A8_HARDMACRO_V_MISSING" in rules, rules
    assert "A8_DESIGN_CONTENT_UNDECLARED" not in rules, rules


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
    assert any("A8_HARDMACRO_LEF_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_stub_marker_in_v_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _hardmacro(tmp_path, "ldo",
               v_extra="// attestation_kind: ai_authored_methodology_stub\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A8_HARDMACRO_STUB_MARKER" in f["rule"]
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
    assert any("A8_HARDMACRO_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
