module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // minimal sum-of-products
    assign out_sop = (c & d) | (~a & ~b & c);
    // minimal product-of-sums
    assign out_pos = c & (~a | d) & (~b | d);
endmodule
