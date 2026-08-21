#!/usr/bin/env python3
"""Tests for chip_top_gate_wrapper_gen.py — FPGA chip_top wrapper gen.

Pins the silicon bug this generator prevents: the open-drain tri-state
polarity is INFERRED from the ASIC RTL `assign <bus>_oe_low = <expr>;`
semantic, NOT from the misleading signal name. A `*_drive_low` RHS means
the bus drives when oe == 1 (active_high); anything else is active_low.

logic-pinned:
  * detect_polarity()/parse_ports() unit branches.
  * CLI PASS: generated wrapper carries the correct tri-state polarity.
  * CLI FAIL: missing `inout <bus>` port / missing `module chip_top` ->
    exit 1; missing input file -> exit 2.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# programs/ is already on sys.path via programs/tests/conftest.py.
# Import directly (rather than importlib.util.exec_module) so the
# module is registered in sys.modules — required by the @dataclass in
# the program (dataclasses resolves cls.__module__ in sys.modules).
import chip_top_gate_wrapper_gen as mod

_PROG = Path(mod.__file__).resolve()


_CHIP_TOP = (
    "module chip_top (\n"
    "  input clk,\n"
    "  input rst,\n"
    "  inout id_bus,\n"
    "  output done\n"
    ");\nendmodule\n"
)


# ── parse_ports ──────────────────────────────────────────────────────
def test_parse_ports_records_direction_and_name():
    ports = mod.parse_ports(_CHIP_TOP, "chip_top")
    triples = [(p.direction, p.name) for p in ports]
    assert ("inout", "id_bus") in triples
    assert ("input", "clk") in triples
    assert ("output", "done") in triples


def test_parse_ports_missing_module_raises():
    import pytest
    with pytest.raises(SystemExit):
        mod.parse_ports("module other (input clk);\nendmodule\n", "chip_top")


# ── detect_polarity — the inference that prevents the bus-stuck bug ──
def test_polarity_drive_low_rhs_is_active_high():
    # `assign id_bus_oe_low = id_bus_drive_low` -> drive when oe==1.
    oe, pol = mod.detect_polarity(
        "assign id_bus_oe_low = id_bus_drive_low;", "id_bus")
    assert oe == "id_bus_oe_low"
    assert pol == "active_high"


def test_polarity_plain_enable_is_active_low():
    oe, pol = mod.detect_polarity(
        "assign id_bus_oe_low = some_enable;", "id_bus")
    assert pol == "active_low"


def test_polarity_no_assign_defaults_active_low():
    oe, pol = mod.detect_polarity("// nothing here", "id_bus")
    assert oe == "id_bus_oe_low"
    assert pol == "active_low"


# ── CLI: PASS end-to-end -> wrapper has correct polarity ─────────────
def _run_cli(args):
    return subprocess.run([sys.executable, str(_PROG)] + args,
                          capture_output=True, text=True)


def test_cli_generates_active_high_tristate(tmp_path):
    top = tmp_path / "chip_top.sv"
    top.write_text(_CHIP_TOP)
    asic = tmp_path / "chip_top_asic.sv"
    asic.write_text("module chip_top_asic (...);\n"
                    "assign id_bus_oe_low = id_bus_drive_low;\n"
                    "endmodule\n")
    out = tmp_path / "fpga_chip_top.v"
    r = _run_cli(["--rtl-chip-top", str(top),
                  "--rtl-chip-top-asic", str(asic),
                  "--output", str(out)])
    assert r.returncode == 0, r.stderr
    wrapper = out.read_text()
    # The polarity-correct tri-state: drive when oe == 1'b1 (active_high).
    assert "id_bus_oe_low_w == 1'b1" in wrapper
    assert "? id_bus_drive_data_w : 1'bz" in wrapper
    assert "active_high" in wrapper


def test_cli_active_low_when_plain_enable(tmp_path):
    top = tmp_path / "chip_top.sv"
    top.write_text(_CHIP_TOP)
    asic = tmp_path / "chip_top_asic.sv"
    asic.write_text("module chip_top_asic (...);\n"
                    "assign id_bus_oe_low = bus_enable;\n"
                    "endmodule\n")
    out = tmp_path / "w.v"
    r = _run_cli(["--rtl-chip-top", str(top),
                  "--rtl-chip-top-asic", str(asic),
                  "--output", str(out)])
    assert r.returncode == 0
    assert "id_bus_oe_low_w == 1'b0" in out.read_text()


# ── CLI: FAIL paths the generator guards ─────────────────────────────
def test_cli_missing_inout_bus_exit_1(tmp_path):
    top = tmp_path / "chip_top.sv"
    top.write_text("module chip_top (\n  input clk,\n  output done\n);\n"
                   "endmodule\n")
    asic = tmp_path / "asic.sv"
    asic.write_text("module chip_top_asic (...);\n"
                    "assign id_bus_oe_low = id_bus_drive_low;\nendmodule\n")
    r = _run_cli(["--rtl-chip-top", str(top),
                  "--rtl-chip-top-asic", str(asic),
                  "--output", str(tmp_path / "o.v")])
    assert r.returncode == 1
    assert "no `inout id_bus`" in (r.stdout + r.stderr)


def test_cli_missing_module_exit_1(tmp_path):
    top = tmp_path / "chip_top.sv"
    top.write_text("module other_mod (input clk);\nendmodule\n")
    asic = tmp_path / "asic.sv"
    asic.write_text("assign id_bus_oe_low = id_bus_drive_low;\n")
    r = _run_cli(["--rtl-chip-top", str(top),
                  "--rtl-chip-top-asic", str(asic),
                  "--output", str(tmp_path / "o.v")])
    assert r.returncode == 1
    assert "module chip_top" in (r.stdout + r.stderr)


def test_cli_missing_input_file_exit_2(tmp_path):
    asic = tmp_path / "asic.sv"
    asic.write_text("assign id_bus_oe_low = id_bus_drive_low;\n")
    r = _run_cli(["--rtl-chip-top", str(tmp_path / "nope.sv"),
                  "--rtl-chip-top-asic", str(asic),
                  "--output", str(tmp_path / "o.v")])
    assert r.returncode == 2
    assert "not found" in r.stderr
