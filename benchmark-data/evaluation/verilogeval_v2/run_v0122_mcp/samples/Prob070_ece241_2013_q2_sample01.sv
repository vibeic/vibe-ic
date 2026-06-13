module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);

    // minimal sum-of-products (don't-cares 3,8,11,12 absorbed)
    assign out_sop = (~a & ~b & c) | (b & c & d);

    // minimal product-of-sums (don't-cares absorbed)
    assign out_pos = c & (b | ~d) & (~a | b) & (~b | ~c | d);

endmodule
