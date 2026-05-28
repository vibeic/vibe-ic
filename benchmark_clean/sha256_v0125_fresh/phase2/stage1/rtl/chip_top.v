// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl (AI-authored from input/docs/L*.md)
//
// chip_top — pad-level wrapper around the sha256 core, conforming to the
// runner-canonical top module name (`chip_top`) while preserving the L3
// external port contract verbatim (clk, reset_n, cs, we, address, write_data,
// read_data, error). No logic added; this is a 1:1 port-passthrough.

`default_nettype none
module chip_top (
    input  wire         clk,
    input  wire         reset_n,
    input  wire         cs,
    input  wire         we,
    input  wire [7:0]   address,
    input  wire [31:0]  write_data,
    output wire [31:0]  read_data,
    output wire         error
);
    sha256 u_sha256 (
        .clk        (clk),
        .reset_n    (reset_n),
        .cs         (cs),
        .we         (we),
        .address    (address),
        .write_data (write_data),
        .read_data  (read_data),
        .error      (error)
    );
endmodule
`default_nettype wire
