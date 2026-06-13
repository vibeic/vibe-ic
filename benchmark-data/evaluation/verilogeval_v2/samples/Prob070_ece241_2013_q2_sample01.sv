module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out_sop,
    output out_pos
);

    // Inputs treated as number {a,b,c,d} with a as MSB.
    // Minterms (=1): 2, 7, 15.  Don't-cares: 3, 8, 11, 12.
    // Minimum SOP: cd + abd? Derive directly.
    // m2  = 0010, m7 = 0111, m15 = 1111, dc = 0011,1000,1011,1100
    //
    // SOP groupings:
    //   c&d  covers 3(dc),7,11(dc),15  -> c&d
    //   b&c&~d covers 2(0010? b=0)... let's just build from terms.
    // 2 = a=0,b=0,c=1,d=0
    // Use: (c & d) | (~a & ~b & c & ~d)
    assign out_sop = (c & d) | (~a & ~b & c & ~d);

    // POS: complement minterms (=0): 0,1,4,5,6,9,10,13,14 with dc 3,8,11,12
    // Minimum POS form equivalent to above SOP.
    assign out_pos = c & (d | (~a & ~b & ~d));

endmodule
