module TopModule (
    input  [99:0] in,
    output [99:0] out_both,
    output [99:0] out_any,
    output [99:0] out_different
);

    // out_both[i]: in[i] AND its neighbour to the LEFT (higher index, in[i+1]).
    //   out_both[98] = in[98] & in[99]. in[99] has no left neighbour => out_both[99]=0.
    assign out_both[98:0] = in[98:0] & in[99:1];
    assign out_both[99]   = 1'b0;

    // out_any[i]: in[i] OR its neighbour to the RIGHT (lower index, in[i-1]).
    //   out_any[2] = in[2] | in[1]. in[0] has no right neighbour => out_any[0]=0.
    assign out_any[99:1] = in[99:1] | in[98:0];
    assign out_any[0]    = 1'b0;

    // out_different[i]: in[i] XOR neighbour to the LEFT (higher index, in[i+1]),
    //   wrapping so in[99]'s left neighbour is in[0]. out_different[99]=in[99]^in[0].
    assign out_different[98:0] = in[98:0] ^ in[99:1];
    assign out_different[99]   = in[99] ^ in[0];

endmodule
