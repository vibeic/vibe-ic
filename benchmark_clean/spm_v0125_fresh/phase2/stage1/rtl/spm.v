// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin spec-to-rtl fallback (AI-authored)
//
// spm — N-bit Serial / Parallel Modulo Integer Multiplier
//
//   p = (x * y) mod 2^N
//
//   x : N-bit parallel multiplicand  (input, held stable)
//   y : 1-bit serial  multiplier     (input, LSB-first stream)
//   p : 1-bit serial  product        (output, LSB-first stream, latency = 1 cycle)
//
// Algorithm  : LSB-first shift-and-add modulo-2^N multiplier.
//              At cycle i (i = 0,1,2,...), the host provides y[i] on input y.
//              The host receives p[i] on output p one clock later.
//              An internal "accumulator" of size+1 carries holds the running
//              column sum; each cycle the LSB of the accumulator is shifted
//              out as the next product bit, and a new partial-product term
//              (y_in & x) is added in at the high end.  After size cycles of
//              y_stream, the host clocks in size additional zero bits on y
//              to flush out the upper product bits — but per the L2 spec we
//              only need to emit "p = x*y mod 2^N", so the host may stop
//              after size product bits have been received.
//
// Bit order  : LSB-first  (declared in plugin_output/declaration.json)
// Reset      : synchronous, active-high  (per L3 / L9)
// Latency    : 1 cycle  (y[i] in @ cycle i  =>  p[i] out @ cycle i+1)
//
// Spec sources (input/docs/L*.md only — NO upstream RTL was read):
//   L2 (functional)  L3 (port list)  L7 (verification)  L8 (integration)  L9 (constraints)
//
// Synthesis target : sky130_fd_sc_hd  @  10 ns  (FP_CORE_UTIL = 45%)

`default_nettype none

module spm #(
    parameter integer size = 32
) (
    input  wire              clk,
    input  wire              rst,   // synchronous, active-high
    input  wire [size-1:0]   x,
    input  wire              y,
    output wire              p
);

    // --------------------------------------------------------------------
    //  Bit-serial shift-and-add accumulator.
    //
    //  acc[size:0] holds the running column sum of partial products that
    //  have not yet been shifted out as product bits.  Each cycle:
    //
    //     new_acc = (acc + (y ? x : 0)) >> 1     (modulo 2^(size+1))
    //     p_reg   = acc[0]                       (LSB shifted out)
    //
    //  The width (size+1) is enough to hold the worst-case carry chain
    //  for a single column addition plus the previously-accumulated bits.
    //
    //  Modulo-2^N truncation is automatic: after size cycles of y_stream,
    //  the host stops reading p; the upper bits in acc are discarded.
    // --------------------------------------------------------------------

    reg [size:0] acc;       // size+1 bits: extra bit catches the add carry
    reg          p_reg;

    wire [size:0] partial;
    wire [size:0] summed;

    assign partial = y ? {1'b0, x} : { (size+1) {1'b0} };
    assign summed  = acc + partial;

    always @(posedge clk) begin
        if (rst) begin
            acc   <= { (size+1) {1'b0} };
            p_reg <= 1'b0;
        end else begin
            p_reg <= summed[0];      // emit LSB of new column sum
            acc   <= summed >> 1;    // shift right by one for next cycle
        end
    end

    assign p = p_reg;

endmodule

`default_nettype wire
