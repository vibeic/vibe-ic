// =============================================================================
// interlaken_scrambler.v  -- self-synchronous scrambler  x^58 + x^39 + 1
//
// Per-lane payload scrambler used by the Interlaken Framing Layer to ensure
// transition density / DC balance. Self-synchronous form: each output bit is
// fed back into the LFSR state, so a descrambler locks without explicit seed
// exchange (the Scrambler State Word merely accelerates lock).
//
// state holds the most-recent 58 scrambled-output bits.  For each input bit:
//     s_out = d_in ^ state[57] ^ state[38]      // taps at x^58 and x^39
//     state = {state[56:0], s_out}
//
// Processes a full 64-bit word per clock combinationally given a starting
// state, returning the scrambled word and the next 58-bit state. The state
// register itself lives in the framer (reset-initialised there).
// =============================================================================
`default_nettype none

module interlaken_scrambler #(
    parameter integer DW = 64
) (
    input  wire [57:0]    state_in,
    input  wire [DW-1:0]  data_in,      // MSB-first on the wire (data_in[DW-1] first)
    output wire [DW-1:0]  data_out,
    output wire [57:0]    state_out
);

    integer i;
    reg [57:0]   s;
    reg [DW-1:0] o;
    reg          b;

    always @* begin
        s = state_in;
        o = {DW{1'b0}};
        for (i = DW-1; i >= 0; i = i - 1) begin
            // self-synchronous: feedback taps at bit 58 (s[57]) and bit 39 (s[38])
            b    = data_in[i] ^ s[57] ^ s[38];
            o[i] = b;
            s    = {s[56:0], b};
        end
    end

    assign data_out  = o;
    assign state_out = s;

endmodule

`default_nettype wire
