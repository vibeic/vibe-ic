module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // Bug in the original: 'out' was 1-bit and used bitwise AND/OR over 8-bit
    // operands, truncating the result. Correct 8-bit mux:
    assign out = sel ? b : a;

endmodule
