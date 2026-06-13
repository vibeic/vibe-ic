module TopModule(
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // ON={2,7,15}, dc={3,8,11,12}.  (a is MSB, d is LSB)
    // Minimum SOP (don't-cares absorbed):  c&d  +  ~a&~b&c
    assign out_sop = (c & d) | (~a & ~b & c);
    // Minimum POS (don't-cares absorbed):  c & (~b+d) & (~a+d)
    assign out_pos = c & (~b | d) & (~a | d);
endmodule
