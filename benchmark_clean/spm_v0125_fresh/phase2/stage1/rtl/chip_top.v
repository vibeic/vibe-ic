// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl fallback (AI-authored from L3/L9)
//
// chip_top — L9-contract top-level wrapper for the spm IC.
//
// Purpose: phase2/stage2 synth invokes yosys with `-top chip_top` per
// L9.top_module="chip_top". This thin wrapper exposes the L3 port list
// with parameter pinned to the L3-default size=32 and instantiates the
// authored inner `spm` data-transform module.
//
// Spec sources (input/docs/L*.md only — NO upstream RTL was read):
//   L3 (port list: clk, rst, x[size-1:0], y, p ; size=32 default)
//   L9 (top_module=chip_top ; SKY130 sky130_fd_sc_hd @10 ns ; util 45%)

`default_nettype none

module chip_top (
    input  wire        clk,
    input  wire        rst,    // synchronous, active-high  (per L3)
    input  wire [31:0] x,      // size = 32  (L3 default)
    input  wire        y,
    output wire        p
);

    spm #(.size(32)) u_spm (
        .clk (clk),
        .rst (rst),
        .x   (x),
        .y   (y),
        .p   (p)
    );

endmodule

`default_nettype wire
