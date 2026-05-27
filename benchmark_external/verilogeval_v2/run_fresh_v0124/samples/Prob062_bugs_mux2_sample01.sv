module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    // Bug fix: out must be an 8-bit mux. Original treated out as 1-bit
    // and bitwise-ANDed a scalar sel with 8-bit vectors.
    assign out = sel ? b : a;
endmodule
