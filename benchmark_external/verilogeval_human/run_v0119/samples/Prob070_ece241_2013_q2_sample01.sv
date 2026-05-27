module TopModule (
    input a,
    input b,
    input c,
    input d,
    output out_sop,
    output out_pos
);
    // ON={2,7,15}, OFF={0,1,4,5,6,9,10,13,14}, dc={3,8,11,12}; value=8a+4b+2c+d
    // Minimum SOP (don't-cares absorbed via Quine-McCluskey):
    assign out_sop = (c & d) | (~a & ~b & c);
    // Minimum POS (complement minimized then inverted):
    assign out_pos = c & (~a | b) & (~b | d);
endmodule
