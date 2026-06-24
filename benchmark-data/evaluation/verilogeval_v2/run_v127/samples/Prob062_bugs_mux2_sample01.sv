module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // The buggy original declared `out` as 1 bit and ANDed a 1-bit sel
    // against 8-bit operands. The fix is a width/declaration correction:
    // make `out` 8 bits and select the whole vector with sel.
    assign out = sel ? b : a;

endmodule
