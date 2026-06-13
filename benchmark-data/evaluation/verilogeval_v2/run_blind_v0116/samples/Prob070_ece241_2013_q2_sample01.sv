module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // minimum sum-of-products
    assign out_sop = (b & c & d) | (~a & ~b & c);
    // minimum product-of-sums
    assign out_pos = c & (d | ~a) & (d | ~b);
endmodule
