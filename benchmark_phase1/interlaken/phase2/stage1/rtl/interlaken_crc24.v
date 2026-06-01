// =============================================================================
// interlaken_crc24.v  -- combinational CRC-24 update block
//
// Per-burst integrity CRC for the Interlaken Burst/Idle Control Word.
// Polynomial 0x328B63  (x^24 + x^23 + x^21 + x^20 + x^19 + x^17 + x^16 + x^15
//                       + x^13 + x^9 + x^8 + x^6 + x^5 + x^1 + x^0)
//   0x328B63 = 0011 0010 1000 1011 0110 0011
//
// Processes 64 payload bits per clock (one Interlaken word), MSB-first,
// purely combinationally: crc_out = f(crc_in, data[63:0]).
// Synthesizable, no state of its own (the register lives in the framer).
// =============================================================================
`default_nettype none

module interlaken_crc24 #(
    parameter integer DW   = 64,
    parameter [23:0]  POLY = 24'h328B63
) (
    input  wire [23:0]    crc_in,
    input  wire [DW-1:0]  data,
    output wire [23:0]    crc_out
);

    integer i;
    reg [23:0] c;
    reg        fb;

    always @* begin
        c = crc_in;
        for (i = DW-1; i >= 0; i = i - 1) begin
            fb = c[23] ^ data[i];
            c  = {c[22:0], 1'b0};
            if (fb)
                c = c ^ POLY;
        end
    end

    assign crc_out = c;

endmodule

`default_nettype wire
