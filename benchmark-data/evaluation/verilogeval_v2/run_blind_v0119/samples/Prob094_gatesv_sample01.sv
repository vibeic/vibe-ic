module TopModule (
    input  [3:0] in,
    output [3:0] out_both,
    output [3:0] out_any,
    output [3:0] out_different
);
    // out_both[i] = in[i] & in[i+1] (left = higher index). out_both[3] don't-care -> 0.
    assign out_both = {1'b0, in[3:1]} & in;

    // out_any[i] = in[i] | in[i-1] (right = lower index). out_any[0] don't-care -> 0.
    assign out_any = {(in[3:1] | in[2:0]), 1'b0};

    // out_different[i] = in[i] ^ in[i+1], wrapping (in[3] left-neighbour = in[0]).
    assign out_different = in ^ {in[0], in[3:1]};
endmodule
