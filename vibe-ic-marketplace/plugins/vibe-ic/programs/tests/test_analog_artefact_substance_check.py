"""tests/test_analog_artefact_substance_check.py — v1.6.28

Six cases covering the analog stub-detector gate:
  1. happy path — real-size files, no stub markers       PASS
  2. 64-byte GDS stub (real-world v10627 reproduction)   FAIL
  3. .v contains ai_authored_methodology_stub marker     FAIL
  4. one block has tiny .lef                             FAIL
  5. --allow-stub-marker bypasses content check          PASS
  6. no analog_block_list.json                           VACUOUS_PASS
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.analog_artefact_substance_check import (
    audit, _MIN_BYTES_BY_EXT, _STUB_MARKER, _STUB_MARKERS_DEFAULT,
)


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


def _real_block(project: Path, block: str) -> None:
    """Materialise a 'real-size' set of analog deliverables for `block`
    (each comfortably above per-ext min thresholds, no stub marker)."""
    bdir = project / "phase3" / "analog" / block
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    bdir.mkdir(parents=True, exist_ok=True)
    hdir.mkdir(parents=True, exist_ok=True)
    # GDS ~512 bytes binary (above 200 threshold)
    (bdir / f"{block}.gds").write_bytes(b"\x00\x06\x00\x02" + b"\x00" * 508)
    (hdir / f"{block}.gds").write_bytes(b"\x00\x06\x00\x02" + b"\x00" * 508)
    # SPICE netlist ~300 bytes
    (bdir / f"{block}.sp").write_text(
        "* " + block + " netlist (real-size)\n"
        + ".subckt " + block + " VDD GND OUT EN\n"
        + "* devices...\n" * 10
        + ".ends\n.end\n"
    )
    # LEF ~400 bytes with MACRO + PIN content
    (hdir / f"{block}.lef").write_text(
        "VERSION 5.7 ;\nBUSBITCHARS \"[]\" ;\nDIVIDERCHAR \"/\" ;\n"
        f"MACRO {block}\n  CLASS BLOCK ;\n  SIZE 80 BY 60 ;\n"
        + "  PIN VDD DIRECTION INOUT ; USE POWER ; END VDD\n"
        + "  PIN GND DIRECTION INOUT ; USE GROUND ; END GND\n"
        + "  PIN OUT DIRECTION OUTPUT ; END OUT\n"
        + "  PIN EN DIRECTION INPUT ; END EN\n"
        + f"END {block}\nEND LIBRARY\n"
    )
    # LIB ~300+ bytes (real Liberty headers add up fast)
    (hdir / f"{block}.lib").write_text(
        f"library({block}_lib) {{\n"
        + "  technology(cmos);\n  delay_model : table_lookup;\n"
        + "  time_unit : 1ns;\n  voltage_unit : 1V;\n"
        + "  current_unit : 1mA;\n  capacitive_load_unit (1, pf);\n"
        + f"  cell({block}) {{\n"
        + "    pin(OUT) { direction : output; capacitance : 0.05; }\n"
        + "    pin(EN)  { direction : input;  capacitance : 0.02; }\n"
        + "  }\n}\n"
    )
    # Verilog ~250 bytes
    (hdir / f"{block}.v").write_text(
        f"// {block} behavioural\n"
        + f"module {block}(input wire EN, output wire OUT,\n"
        + "                  inout wire VDD, inout wire GND);\n"
        + "  // simple model\n"
        + "  assign OUT = EN ? 1'b1 : 1'bz;\n"
        + "endmodule\n"
    )


def _stub_block(project: Path, block: str, what_kind: str = "gds") -> None:
    """Materialise a stub deliverable per the requested kind."""
    bdir = project / "phase3" / "analog" / block
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    _real_block(project, block)
    if what_kind == "gds":
        # Replace GDS with the v10627 64-byte stub (HEADER + ENDLIB only)
        stub = (b"\x00\x06\x00\x02\x00\x00\x00\x1c\x01\x02"
                + b"\x00" * 22
                + b"\x00\x07\x02\x06" + b"ld\x00\x14"
                + b"\x03\x05" + b"\x00" * 16
                + b"\x00\x04\x04\x00")
        (hdir / f"{block}.gds").write_bytes(stub)
    elif what_kind == "v_marker":
        (hdir / f"{block}.v").write_text(
            f"// {block} behavioural\n"
            f"// attestation_kind: {_STUB_MARKER}\n"
            f"module {block}(input wire EN, output wire OUT, "
            f"inout wire VDD, inout wire GND);\nendmodule\n"
        )
    elif what_kind == "tiny_lef":
        (hdir / f"{block}.lef").write_text("VERSION 5.7 ;\n")  # < 250 bytes


# ------ tests ------

def test_happy_path_all_real(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["bandgap", "ldo_1v8"])
    _real_block(p, "bandgap")
    _real_block(p, "ldo_1v8")
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.rel_path, f.detail) for f in findings]


def test_64byte_gds_stub_fails(tmp_path: Path) -> None:
    """Real-world v10627 reproduction: 64-byte HEADER+ENDLIB stub."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _stub_block(p, "ldo_1v8", what_kind="gds")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "STUB_FILE_TOO_SMALL"
               and f.rel_path.endswith("ldo_1v8.gds")
               for f in findings), findings


def test_self_declared_stub_marker_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _stub_block(p, "ldo_1v8", what_kind="v_marker")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "AI_STUB_SELF_DECLARED"
               and f.rel_path.endswith("ldo_1v8.v")
               for f in findings), findings


def test_tiny_lef_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _stub_block(p, "ldo_1v8", what_kind="tiny_lef")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "STUB_FILE_TOO_SMALL"
               and f.rel_path.endswith("ldo_1v8.lef")
               for f in findings)


def test_allow_stub_marker_flag_bypasses_content_check(tmp_path: Path) -> None:
    """When --allow-stub-marker is set, the marker substring no longer
    fails the gate. Size check still applies."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _stub_block(p, "ldo_1v8", what_kind="v_marker")  # only marker, sizes are real
    verdict, findings = audit(p, allow_stub_marker=True)
    assert verdict == "PASS"


def test_no_block_list_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS" and findings == []


# ------ v1.6.30 marker-panel tests ------

@pytest.mark.parametrize("marker_phrase", [
    "TODO implement",                # title-case variant
    "Behavioral Stub",               # title-case
    "Placeholder Hardmacro",         # title-case
    "Do Not Tape Out",               # title-case
    "__STUB__",                      # uppercase symbolic
])
def test_alternative_markers_caught(tmp_path: Path, marker_phrase: str) -> None:
    """v1.6.30 panel catches non-v10627 marker phrasings, case-insensitive."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _real_block(p, "ldo_1v8")
    # Inject the marker into the .v file (real-size baseline keeps size OK)
    vfile = p / "phase3" / "analog" / "hardmacro" / "ldo_1v8" / "ldo_1v8.v"
    vfile.write_text(vfile.read_text() + f"\n// {marker_phrase}\n")
    verdict, findings = audit(p)
    assert verdict == "FAIL", f"expected FAIL for marker '{marker_phrase}'"
    assert any(f.rule == "AI_STUB_SELF_DECLARED" for f in findings)


def test_stub_markers_panel_includes_legacy(tmp_path: Path) -> None:
    """The legacy v10627 marker is still in the default panel (back-compat)."""
    assert _STUB_MARKER in _STUB_MARKERS_DEFAULT


def test_custom_stub_markers_replace_panel(tmp_path: Path) -> None:
    """A caller can REPLACE the panel via --stub-markers / API."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _real_block(p, "ldo_1v8")
    # Inject default-panel marker; should NOT trigger when panel is custom.
    vfile = p / "phase3" / "analog" / "hardmacro" / "ldo_1v8" / "ldo_1v8.v"
    vfile.write_text(vfile.read_text() + "\n// behavioral stub\n")
    verdict, _ = audit(p, stub_markers=("totally_different_marker",))
    assert verdict == "PASS"


def test_extra_marker_via_api(tmp_path: Path) -> None:
    """Caller can EXTEND the panel by passing markers including extras."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _real_block(p, "ldo_1v8")
    # Inject a custom marker the default panel doesn't know.
    vfile = p / "phase3" / "analog" / "hardmacro" / "ldo_1v8" / "ldo_1v8.v"
    vfile.write_text(vfile.read_text() + "\n// project_specific_stub\n")
    # Default panel: PASS
    verdict_default, _ = audit(p)
    assert verdict_default == "PASS"
    # Extended panel: FAIL
    verdict_ext, findings = audit(
        p, stub_markers=_STUB_MARKERS_DEFAULT + ("project_specific_stub",))
    assert verdict_ext == "FAIL"
    assert any("project_specific_stub" in f.detail for f in findings)
