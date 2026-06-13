"""tests/test_aid_class_rtl_gen_chip_top_port_canonicalisation.py — v1.6.85

Closes #17 Bug A1 — chip_top SHOUTING port-name canonicalisation.

Field-agent traced an iverilog `port id_bus is not a port of u_dut`
fail across 4 ECO iterations: aid_class_rtl_gen emitted SHOUTING
all-caps port names (ID_BUS / V_IN / OVP / WAKE) into chip_top.sv
but the reference_tb + de10lite_top wrapper bind to lowercase
canonical names. Canonicalisation is chip-AGNOSTIC: lowercase +
collapse whitespace + collapse multi-underscores. Reject-tests
cover SHOUTING input, whitespace input, multi-underscore input,
and the positive control (already-canonical names).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from programs import aid_class_rtl_gen  # noqa: E402


def _seed(project: Path, l9_top_ports):
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "TEST"}))
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "schema_version": 2,
        "command_set": [{"name": "READ", "opcode_hex": "01"}],
        "crc_parameters": {"polynomial_hex": "0x31"},
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": 2,
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": l9_top_ports,
    }))
    return project


def _read_chip_top(project: Path) -> str:
    """Locate the emitted chip_top.sv regardless of layout-version."""
    for cand in (
        project / "phase2" / "stage1" / "rtl" / "chip_top.sv",
        project / "rtl" / "chip_top.sv",
        project / "phase2" / "rtl" / "chip_top.sv",
    ):
        if cand.is_file():
            return cand.read_text()
    # Fallback: any chip_top.sv under the project tree.
    hits = list(project.rglob("chip_top.sv"))
    assert hits, f"chip_top.sv not emitted under {project}"
    return hits[0].read_text()


def test_canon_port_name_helper_lowercases_and_collapses():
    """Direct unit test of _canon_port_name — the canonicaliser."""
    fn = aid_class_rtl_gen._canon_port_name
    assert fn("ID_BUS") == "id_bus"
    assert fn("OVP") == "ovp"
    assert fn("V_IN") == "v_in"
    assert fn("V  IN") == "v_in"
    assert fn("V__OUT") == "v_out"
    assert fn("V__IN__BUS") == "v_in_bus"
    assert fn("clk") == "clk"  # already canonical, unchanged
    # Falsy / non-str passthrough — caller's None-handling stays intact.
    assert fn("") == ""
    assert fn(None) is None


def test_chip_top_emits_lowercase_canonical_ports(tmp_path):
    """SHOUTING L9 port names must canonicalise to lowercase in
    chip_top.sv. Closes #17 Bug A1."""
    project = _seed(tmp_path / "shouting_proj", [
        {"name": "ID_BUS", "direction": "inout", "width": 1},
        {"name": "OVP", "direction": "input", "width": 1},
        {"name": "WAKE", "direction": "output", "width": 1},
    ])
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    assert "id_bus" in chip_top
    assert "ovp" in chip_top
    assert "wake" in chip_top
    # SHOUTING forms must be gone from the port-list region.
    # (We allow comments / generator-provenance to mention them in
    # docstrings, but the actual port DECLARATIONS must be lowercase.)
    # A targeted assertion: the port direction-line for ID_BUS is gone.
    assert " ID_BUS\n" not in chip_top
    assert " OVP\n" not in chip_top
    assert " WAKE\n" not in chip_top


def test_chip_top_underscore_collapse(tmp_path):
    """Whitespace + multi-underscore L9 port names must collapse."""
    project = _seed(tmp_path / "ws_proj", [
        {"name": "V  IN", "direction": "input", "width": 1},
        {"name": "V__OUT", "direction": "input", "width": 1},
    ])
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    assert "v_in" in chip_top
    assert "v_out" in chip_top
    # Exact sentinel of the rejected forms must NOT appear as a port id.
    # (Comments/log lines are filtered by requiring the leading
    # `wire ` or `inout `/`input `/`output ` token.)
    for bad in ("V__OUT", "V  IN"):
        assert bad not in chip_top, (
            f"un-canonicalised form '{bad}' leaked into chip_top.sv")


def test_chip_top_positive_control_already_canonical(tmp_path):
    """Already-canonical names must be preserved (no double-rewrite)."""
    project = _seed(tmp_path / "ok_proj", [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "reset_n", "direction": "input", "width": 1},
        {"name": "id_bus", "direction": "inout", "width": 1},
    ])
    aid_class_rtl_gen.gen(project)
    chip_top = _read_chip_top(project)
    assert "clk" in chip_top
    assert "reset_n" in chip_top
    assert "id_bus" in chip_top
