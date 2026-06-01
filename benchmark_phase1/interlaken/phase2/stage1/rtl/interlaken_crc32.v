// =============================================================================
// interlaken_crc32.v  -- combinational CRC-32 update block
//
// Per-lane diagnostic CRC carried in the Diagnostic Word of each metaframe.
// Polynomial 0x04C11DB7 (the standard IEEE-802.3 / Interlaken CRC-32).
//
// Processes 64 payload bits per clock (one Interlaken word), MSB-first,
// purely combinationally: crc_out = f(crc_in, data[63:0]).
// Synthesizable, no state of its own (the register lives in the framer).
// =============================================================================
`default_nettype none

module interlaken_crc32 #(
    parameter integer DW   = 64,
    parameter [31:0]  POLY = 32'h04C11DB7
) (
    input  wire [31:0]    crc_in,
    input  wire [DW-1:0]  data,
    output wire [31:0]    crc_out
);

    integer i;
    reg [31:0] c;
    reg        fb;

    always @* begin
        c = crc_in;
        for (i = DW-1; i >= 0; i = i - 1) begin
            fb = c[31] ^ data[i];
            c  = {c[30:0], 1'b0};
            if (fb)
                c = c ^ POLY;
        end
    end

    assign crc_out = c;

endmodule

`default_nettype wire
