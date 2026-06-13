module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);

    // Minimum sum-of-products (don't-cares 3,8,11,12 absorbed)
    assign out_sop = (c & d) | (~a & ~b & c);

    // Minimum product-of-sums (same function)
    assign out_pos = c & (~b | d) & (~a | d);

endmodule
