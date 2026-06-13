module TopModule(
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    assign out_sop = (~a & ~b & c) | (b & c & d);
    assign out_pos = c & (d | ~a) & (d | ~b);
endmodule
