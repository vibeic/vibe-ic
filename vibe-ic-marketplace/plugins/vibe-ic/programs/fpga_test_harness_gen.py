#!/usr/bin/env python3
"""fpga_test_harness_gen.py — emit FPGA test harness wrapper.

Replaces skill `fpga-test-harness` (archived). Generates DE10-Lite test
harness wrapper around chip_top + LED diagnostic + KEY trigger.

SCOPE, STATED SO A CALLER DOES NOT ASSUME MORE
----------------------------------------------
This emits a FIXED template. It reads nothing from the project — not the RTL,
not chip_top, not L9 — so the generated wrapper only elaborates for a design
whose top is a module literally named `chip_top` exposing exactly
`clk`, `reset_n`, `id_bus` and `state_reg_dbg`, on a DE10-Lite pinout
(CLOCK_50 / KEY / GPIO_0 / LEDR). Adapting it to another top or board is a
manual edit.

It writes ONE file, ``<rtl_dir>/fpga_test_harness.sv``.

WIRING: none. No runner, gate or MCP tool invokes this program; Step 6 of
flow/phase1_phase2_phase3.yaml registers it for discoverability only (see the
comment on that entry). It is invoked by an agent during board bring-up.
"""
import argparse, sys
from pathlib import Path
import _path_layout as _pl

_TEMPLATE = """// Auto-generated FPGA test harness for chip_top
module fpga_test_harness (
  input  wire CLOCK_50,
  input  wire [1:0] KEY,
  inout  wire [35:0] GPIO_0,
  output wire [9:0] LEDR
);
  // Reset = active-LOW KEY[0]
  // Trigger = active-LOW KEY[1]
  // id_bus = GPIO_0[0] = PIN_V10
  // LEDs: state_reg[7:0] = LEDR[7:0]; id_bus = LEDR[8]; heartbeat = LEDR[9]
  wire [7:0] state_reg_dbg;
  reg [25:0] heartbeat = 0;
  always @(posedge CLOCK_50) heartbeat <= heartbeat + 1;
  chip_top u_chip (
    .clk(CLOCK_50), .reset_n(KEY[0]),
    .id_bus(GPIO_0[0]),
    .state_reg_dbg(state_reg_dbg)
  );
  assign LEDR[7:0] = state_reg_dbg;
  assign LEDR[8]   = GPIO_0[0];
  assign LEDR[9]   = heartbeat[25];
endmodule
"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    args = p.parse_args()
    rtl = _pl.rtl_dir(args.project)
    rtl.mkdir(parents=True, exist_ok=True)
    out = rtl / "fpga_test_harness.sv"
    out.write_text(_TEMPLATE)
    print(f"[PASS] fpga_test_harness_gen: emitted {out.name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
