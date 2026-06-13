module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // LUT indexed by {a,b,c,d}; bit n = map value at minterm n.
    // out=1 minterms: 0,1,2,4,6,7,8,9,11,15
    wire [15:0] lut = 16'b1000_1011_1101_0111;
    assign out = lut[{a, b, c, d}];
endmodule
