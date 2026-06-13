module TopModule(
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);
    // minterms 2,7,15 = 1; 0,1,4,5,6,9,10,13,14 = 0; 3,8,11,12 = don't-care
    assign out_sop = (~a & ~b & c & ~d) | (b & c & d);
    assign out_pos = c & (~b | ~c | d) & (~a | b | ~c | d);
endmodule
