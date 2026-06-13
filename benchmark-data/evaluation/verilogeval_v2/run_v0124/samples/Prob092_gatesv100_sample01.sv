module TopModule (
    input  [99:0] in,
    output [99:0] out_both,
    output [99:0] out_any,
    output [99:0] out_different
);
    // out_both[i] = in[i] & in[i+1] (neighbour to the LEFT = higher index);
    // out_both[99] forced 0 by placement at the MSB.
    assign out_both = { 1'b0, (in[99:1] & in[98:0]) };

    // out_any[i] = in[i] | in[i-1] (neighbour to the RIGHT = lower index);
    // out_any[0] forced 0 by placement at the LSB.
    assign out_any  = { (in[99:1] | in[98:0]), 1'b0 };

    // out_different[i] = in[i] ^ in[(i+1) mod 100]; wraps around.
    assign out_different = in ^ {in[0], in[99:1]};
endmodule
