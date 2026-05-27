module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // a is MSB, d is LSB.  on-set {2,7,15}, dc {3,8,11,12}.
    // minimum SOP:  (c & d) | (~a & ~b & c)
    assign out_sop = (c & d) | (~a & ~b & c);
    // minimum POS:  c & (d | (~a & ~b))  == ~( ~c | (~d & (a | b)) )
    assign out_pos = c & (d | (~a & ~b));
endmodule
