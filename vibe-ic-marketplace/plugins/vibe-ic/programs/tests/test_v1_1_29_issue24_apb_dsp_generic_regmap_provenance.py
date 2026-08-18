#!/usr/bin/env python3
"""ORGANIC issue #24 — iface_conformance generic-`Name`-header register-map FP,
fixed with a STRUCTURAL PROVENANCE guard (NOT the prose port-detection that
leaked across PR #23's 6 Step-2.7 rounds and was dropped).

THE FP (apb_dsp_unit, CVDP): a register-map table with a GENERIC `Name` header
(`| Addr | Name | Function | Reset |`) + internal-CSR prose listed 4 APB CSRs
that were false-flagged MISSING-PORT because the old regmap_csr_names required a
STRICT `Register Name` header.

THE §4.05-SAFE FIX: recognise the generic-`Name` header (regmap_generic_csr_names)
but mask such a name ONLY under a structural provenance guard —
  (1) it is DIRECTION-LESS (a genuine port carries a PORT-DIRECTION provenance),
  (2) its SOLE interface evidence is a table (`sources == {'table'}`), and
  (3) it does NOT appear under a `## Ports`/Interface section heading
      (`_names_under_ports_section`).
This removes the apb_dsp FP while never absorbing a genuine top-level port — the
two PR #23 Step-2.7 leak shapes (a direction-ful `irq`; a direction-less `status`
also declared under `## Ports` with prose direction the extractor misses) both
fail the guard and still hard-block. No prose port-detection. chip-AGNOSTIC.
"""
import os
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(os.environ.get(
    "VIBE_PROGRAMS", str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as F  # noqa: E402

_GATE = PROGRAMS / "iface_conformance_v2.py"


def _run(tmp_path, spec, rtl, top, rid):
    sp = tmp_path / "spec.md"
    sp.write_text(spec)
    rd = tmp_path / "rtl"
    rd.mkdir(exist_ok=True)
    rf = rd / f"{top}.sv"
    rf.write_text(rtl)
    p = subprocess.run(
        [sys.executable, str(_GATE), "--strict", "--prompt", str(sp),
         "--rtl", str(rf), "--id", rid],
        capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ── the motivating FP — must now PASS (rc=0) ────────────────────────────────
_APB_SPEC = """\
# apb_dsp_unit — Specification

## Ports
- `pclk`   : input — APB clock.
- `presetn`: input — active-low reset.
- `paddr`  : input  [9:0] — address bus.
- `pwdata` : input  [7:0] — write data bus.
- `prdata` : output [7:0] — read data bus.

## Register Map (CSR)
These are internal CSR registers accessed via the bus (not top-level ports).
| Addr | Name              | Function                         | Reset |
|------|-------------------|----------------------------------|-------|
| 0x0  | `r_operand_1`     | memory address of first operand  | 0     |
| 0x1  | `r_operand_2`     | memory address of second operand | 0     |
| 0x3  | `r_write_address` | memory write address             | 0     |
| 0x4  | `r_write_data`    | memory write data                | 0     |
"""
_APB_RTL = """\
module apb_dsp_unit (
    input  wire        pclk,
    input  wire        presetn,
    input  wire [9:0]  paddr,
    input  wire [7:0]  pwdata,
    output reg  [7:0]  prdata
);
    reg [7:0] r_operand_1;
    reg [7:0] r_operand_2;
    reg [7:0] r_write_address;
    reg [7:0] r_write_data;
endmodule
"""


def test_apb_dsp_generic_name_header_csrs_no_longer_false_missing_port(tmp_path):
    rc, out = _run(tmp_path, _APB_SPEC, _APB_RTL,
                   "apb_dsp_unit", "cvdp_copilot_apb_dsp_unit_0001")
    assert rc == 0, (
        "the 4 generic-`Name`-header internal CSRs must no longer false-flag "
        f"MISSING-PORT\n{out}")
    for nm in ("r_operand_1", "r_operand_2", "r_write_address", "r_write_data"):
        assert nm not in out, f"{nm} wrongly reported\n{out}"


# ── §4.05 leak shape 1 (PR #23 round-2): a DIRECTION-FUL irq under a generic
# regmap table must STILL hard-block (a memory-mapped top-level output port). ──
_IRQ_SPEC = """\
# sensor_ctrl
## Overview
The block exposes a top-level `irq` output that is also memory-mapped. `irq` is
an output interrupt line.
## Register Map
These are internal CSRs accessed through the bus, not top-level ports.
| Addr | Name | Function | Reset |
|------|------|----------|-------|
| 0x0 | `ctrl` | control | 0 |
| 0x2 | `irq` | interrupt output | 0 |
"""
_IRQ_RTL = """\
module sensor_ctrl(input wire pclk, input wire presetn, input wire [7:0] pwdata);
  reg [7:0] ctrl; reg [7:0] status;
endmodule
"""


def test_directionful_port_under_generic_regmap_still_blocks(tmp_path):
    rc, out = _run(tmp_path, _IRQ_SPEC, _IRQ_RTL,
                   "sensor_ctrl", "cvdp_copilot_sensor_ctrl_0001")
    assert rc == 1 and "irq" in out, (
        f"a direction-ful memory-mapped port must hard-block\n{out}")


# ── §4.05 leak shape 2 (PR #23 round-4): a DIRECTION-LESS status declared under
# `## Ports` (prose direction the extractor misses) ALSO listed in a generic
# regmap table must STILL hard-block — the ports-section guard catches it. ──
_STATUS_SPEC = """\
# sensor
## Ports
- `pclk` : input — clock.
- `status` : the live status word, continuously driven out of the block.
## Register Map
These are internal CSRs accessed through the bus, not top-level ports.
| Addr | Name | Function | Reset |
|------|------|----------|-------|
| 0x0 | `ctrl` | control | 0 |
| 0x4 | `status` | status word | 0 |
"""
_STATUS_RTL = "module sensor(input wire pclk);\n  reg [7:0] ctrl;\nendmodule\n"


def test_directionless_port_in_ports_section_still_blocks(tmp_path):
    rc, out = _run(tmp_path, _STATUS_SPEC, _STATUS_RTL,
                   "sensor", "cvdp_copilot_sensor_0001")
    assert rc == 1 and "status" in out, (
        "a name declared under `## Ports` (even with unrecognised direction "
        f"prose) must never be masked by the generic-regmap relaxation\n{out}")


# ── regression: strict-header regmap CSRs still masked; genuine port still blocks
_N738_SPEC = """\
APB DSP peripheral.
Top-level interface ports:
| Signal | Direction | Width |
|--------|-----------|-------|
| `pclk` | input | 1 |
| `prdata` | output | 32 |
The internal register map (these are CSRs accessed through the bus, they are
NOT top-level ports of the module):
| Register Name | Access | Offset |
|---------------|--------|--------|
| `op_a_reg` | input | 0x0 |
| `result_reg` | output | 0x14 |
"""
_N738_RTL = "module apb_dsp(input pclk, output reg [31:0] prdata);\nendmodule\n"


def test_strict_header_regmap_still_masked(tmp_path):
    rc, out = _run(tmp_path, _N738_SPEC, _N738_RTL,
                   "apb_dsp", "cvdp_copilot_apb_dsp_0001")
    assert rc == 0, f"strict-header regmap CSRs must stay masked\n{out}"


_WIDGET_SPEC = """\
# widget
## Ports
| Port | Direction | Width |
|------|-----------|-------|
| `clk` | input | 1 |
| `valid_o` | output | 1 |
"""
_WIDGET_RTL = "module widget(input clk);\nendmodule\n"


def test_genuine_missing_port_still_blocks(tmp_path):
    rc, out = _run(tmp_path, _WIDGET_SPEC, _WIDGET_RTL,
                   "widget", "cvdp_copilot_widget_0001")
    assert rc == 1 and "valid_o" in out, (
        f"a genuine missing port (Direction col, no offset) must block\n{out}")


# ── unit-level provenance assertions ────────────────────────────────────────
def test_generic_csr_names_recognised():
    assert F.regmap_generic_csr_names(_APB_SPEC) == {
        "r_operand_1", "r_operand_2", "r_write_address", "r_write_data"}


def test_strict_table_not_double_counted_as_generic():
    # a strict `Register Name` header is in regmap_csr_names, NOT the generic set.
    assert F.regmap_generic_csr_names(_N738_SPEC) == set()


def test_ports_section_names_extracted():
    assert F._names_under_ports_section(_APB_SPEC) == {
        "pclk", "presetn", "paddr", "pwdata", "prdata"}
    assert "status" in F._names_under_ports_section(_STATUS_SPEC)



# ── Step-2.7 round-2: an offset-bearing port table NOT under a register-MAP
# heading must NEVER be absorbed (the mask requires a strict register-map/CSR
# section heading; `## Pin Description` / `## Register Layout` are not). ──
_PINDESC_SPEC = """\
# dma_block

## Pin Description

The block exposes these top-level handshake ports. The hidden testbench drives
and samples each one by exact name at the module boundary.

| Offset | Name   | Role     |
|--------|--------|----------|
| 0x0    | `req`  | request  |
| 0x4    | `gnt`  | grant    |

This block also instantiates internal CSR registers for its control logic.
"""
_LAYOUT_SPEC = """\
# dma_block

## Ports

This module has top-level ports clk, req and gnt, bound by the hidden testbench.

## Register Layout

| Offset | Name   | Role     |
|--------|--------|----------|
| 0x0    | `req`  | request  |
| 0x4    | `gnt`  | grant    |

This block also instantiates internal CSR registers for its control logic.
"""
_DMA_RTL = "module dma_block(input wire clk);\nendmodule\n"


def test_pin_description_offset_table_not_absorbed(tmp_path):
    rc, out = _run(tmp_path, _PINDESC_SPEC, _DMA_RTL,
                   "dma_block", "cvdp_copilot_dma_block_0001")
    assert rc == 1 and "req" in out and "gnt" in out, (
        "an offset table under `## Pin Description` (not a register-MAP heading) "
        f"must not be masked — req/gnt are genuine ports\n{out}")


def test_register_layout_offset_table_not_absorbed(tmp_path):
    rc, out = _run(tmp_path, _LAYOUT_SPEC, _DMA_RTL,
                   "dma_block", "cvdp_copilot_dma_block_0001")
    assert rc == 1 and "req" in out and "gnt" in out, (
        "`## Register Layout` is not a register-MAP heading; its offset table "
        f"must not be masked\n{out}")


def test_strict_heading_required_unit():
    import iface_conformance_v2 as _F
    # apb_dsp `## Register Map (CSR)` heading enables the generic mask
    assert _F.regmap_generic_csr_names(_APB_SPEC)
    # but the same table under a non-register-map heading does NOT
    assert _F.regmap_generic_csr_names(_PINDESC_SPEC) == set()
    assert _F.regmap_generic_csr_names(_LAYOUT_SPEC) == set()


# ── Step-2.7 round-3: `Control and Status Registers` / `Register File` /
# `Memory-Mapped Registers` headings hold genuine exposed ports just as often as
# CSRs, so the mask is restricted to UNAMBIGUOUS `register map`/`csr map`/`csr`
# headings only. A generic offset table under `## Control and Status Registers`
# listing direction-less output ports must NOT be absorbed. ──
_CSR_REGS_SPEC = """\
# fifo_ctrl
This FIFO controller also contains an internal CSR for debug, accessed via the bus.

## Top-Level Control and Status Registers
The following are the module's top-level output ports. The hidden testbench
samples `wr_full`, `rd_empty` and `ovf_flag` at the module boundary by name.
| Offset | Name | Function |
|--------|------|----------|
| 0x0 | `wr_full` | write full |
| 0x4 | `rd_empty` | read empty |
| 0x8 | `ovf_flag` | overflow |
"""
_FIFO_RTL = "module fifo_ctrl(input wire clk, input wire rst_n);\n  reg [3:0] count;\nendmodule\n"


def test_control_and_status_registers_heading_not_absorbed(tmp_path):
    rc, out = _run(tmp_path, _CSR_REGS_SPEC, _FIFO_RTL,
                   "fifo_ctrl", "cvdp_copilot_fifo_ctrl_0001")
    assert rc == 1, (
        "`## ... Control and Status Registers` is NOT an unambiguous register-MAP "
        "heading; its offset table may hold genuine exposed ports → must not be "
        f"masked\n{out}")
    for nm in ("wr_full", "rd_empty", "ovf_flag"):
        assert nm in out, f"{nm} must be flagged MISSING-PORT\n{out}"


def test_strict_heading_unambiguous_only_unit():
    import iface_conformance_v2 as _F
    assert _F.regmap_generic_csr_names(_APB_SPEC)               # register map → yes
    assert _F.regmap_generic_csr_names(_CSR_REGS_SPEC) == set()  # C&S registers → no

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
