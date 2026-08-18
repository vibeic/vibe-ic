#!/usr/bin/env python3
"""Regression tests for ORGANIC-20260531-reference-tb-binds-asic-pad-top-not-behavioral-top.

The functional reference-TB must bind the BEHAVIORAL single-net top (whose
ports are a superset of the ports the TB drives), NOT the synthesis pad-split
ASIC top whose interface is split into pad signals. The selection is
chip-AGNOSTIC: it matches on the TB's parsed port set, never a chip name.

Covers:
  - POSITIVE: caller passes the ASIC pad-split top_name, but a behavioral top
    declaring {clk,reset_n,id_bus} exists -> resolver picks the behavioral top
    (so the TB elaborates instead of "port id_bus is not a port of u_dut").
  - NEGATIVE/REGRESSION: only a split-pad top exists -> resolver falls back to
    the caller-supplied top_name (honest FAIL preserved, no false rebinding).
  - Helper-level asserts on the TB-port parser and the module-port parser.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as p2  # noqa: E402


# A minimal reference-TB instantiation block in the canonical shape the real
# AID reference TB uses: `\`DUT_TOP_NAME u_dut ( .clk(...), .reset_n(...),
# .id_bus(...) );`. The protocol port here is a single net (id_bus).
_TB_TEXT = """
// reference TB
`ifdef DUT_TOP_NAME
  `DUT_TOP_NAME u_dut (
    .clk(clk),
    .reset_n(reset_n),
    .id_bus(id_bus)
  );
`else
  chip_top u_dut (
    .clk(clk),
    .reset_n(reset_n),
    .id_bus(id_bus)
  );
`endif
"""

# Behavioral top: exposes the single bidirectional net the TB drives.
_BEHAVIORAL_TOP = """
module chip_top (
    input  wire clk,
    input  wire reset_n,
    inout  wire id_bus
);
endmodule
"""

# ASIC pad-split top: the single net is split into pad signals
# (in_async / drive_data / oe_low). The TB's id_bus net is NOT a port here.
_ASIC_SPLIT_TOP = """
module chip_top_asic (
    input  wire clk,
    input  wire reset_n,
    input  wire id_bus_in_async,
    output wire id_bus_drive_data,
    output wire id_bus_oe_low
);
endmodule
"""


def _mk_rtl(tmp: Path, files: dict) -> list:
    out = []
    for name, text in files.items():
        p = tmp / name
        p.write_text(text)
        out.append(p)
    return out


def test_parse_tb_required_ports():
    """The TB-port parser yields exactly the driven net set, chip-AGNOSTIC."""
    assert p2._parse_tb_required_ports(_TB_TEXT) == {"clk", "reset_n", "id_bus"}


def test_module_port_sets_behavioral_and_split():
    beh = p2._module_port_sets(_BEHAVIORAL_TOP)
    assert beh["chip_top"] == {"clk", "reset_n", "id_bus"}
    asic = p2._module_port_sets(_ASIC_SPLIT_TOP)
    assert "id_bus" not in asic["chip_top_asic"]
    assert "id_bus_in_async" in asic["chip_top_asic"]
    assert p2._looks_like_pad_split_top(asic["chip_top_asic"]) is True
    assert p2._looks_like_pad_split_top(beh["chip_top"]) is False


def test_resolver_picks_behavioral_top_when_caller_passes_asic():
    """POSITIVE: caller --top-name is the ASIC pad-split top, but the
    behavioral top declares the TB's port set -> resolver picks behavioral."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _mk_rtl(tmp, {
            "chip_top.sv": _BEHAVIORAL_TOP,
            "chip_top_asic.sv": _ASIC_SPLIT_TOP,
        })
        bound = p2._resolve_reference_tb_top(files, _TB_TEXT, "chip_top_asic")
        assert bound == "chip_top", (
            "reference TB must bind the behavioral single-net top, not the "
            f"ASIC pad-split top; got {bound!r}")


def test_resolver_falls_back_to_caller_when_only_split_top():
    """NEGATIVE/REGRESSION: only the split-pad top exists -> no candidate
    matches the TB's port set -> fall back to the caller top_name (the
    honest FAIL path is preserved; we never invent a wrong binding)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _mk_rtl(tmp, {"chip_top_asic.sv": _ASIC_SPLIT_TOP})
        bound = p2._resolve_reference_tb_top(files, _TB_TEXT, "chip_top_asic")
        assert bound == "chip_top_asic", (
            "with no port-set match the resolver must fall back to the "
            f"caller top_name (honest FAIL); got {bound!r}")


def test_resolver_keeps_caller_top_when_caller_already_qualifies():
    """If the caller-supplied top already declares the TB's ports (no
    pad-split sibling involved), least-surprise: keep the caller's name."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _mk_rtl(tmp, {"chip_top.sv": _BEHAVIORAL_TOP})
        bound = p2._resolve_reference_tb_top(files, _TB_TEXT, "chip_top")
        assert bound == "chip_top"


def test_resolver_empty_tb_ports_is_passthrough():
    """If the TB declares no DUT ports (unparseable), pass the caller top
    through unchanged rather than guessing."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        files = _mk_rtl(tmp, {"chip_top.sv": _BEHAVIORAL_TOP})
        bound = p2._resolve_reference_tb_top(files, "// no dut here", "anything")
        assert bound == "anything"
