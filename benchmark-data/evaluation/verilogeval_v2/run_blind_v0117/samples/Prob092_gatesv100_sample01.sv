module TopModule(
    input  [99:0] in,
    output [99:0] out_both,
    output [99:0] out_any,
    output [99:0] out_different
);
    // out_both[i] = in[i] & in[i+1]; out_both[99] = 0 (no left neighbour).
    assign out_both = {1'b0, in[99:1] & in[98:0]};
    // out_any[i] = in[i] | in[i-1]; out_any[0] = 0 (no right neighbour).
    assign out_any = {in[99:1] | in[98:0], 1'b0};
    // out_different[i] = in[i] ^ left-neighbour, wrapping: left of in[99] is in[0].
    assign out_different = in ^ {in[0], in[99:1]};
endmodule
