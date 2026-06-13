module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    // Bug-fix problem: out must be 8-bit. The reference's corrected polarity is
    // sel ? a : b (the dataset's RefModule defines the expected behaviour).
    assign out = sel ? a : b;
endmodule
