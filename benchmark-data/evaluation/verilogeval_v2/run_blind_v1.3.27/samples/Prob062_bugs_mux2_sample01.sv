module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // Bug fix (two defects in the original):
    //  1) 'out' was declared scalar (1-bit); widened to [7:0] to carry the
    //     full 8-bit mux result.
    //  2) The original expression (~sel & a) | (sel & b) has sel as a 1-bit
    //     operand ANDed against an 8-bit vector: Verilog zero-extends the
    //     narrower operand, so only bit 0 of each AND term is ever non-zero
    //     and out[7:1] would always read 0 regardless of a/b. The ternary
    //     form lets sel select the whole 8-bit vector correctly.
    assign out = sel ? b : a;

endmodule
