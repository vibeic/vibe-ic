module sub_64bit (
    input      [63:0] A,
    input      [63:0] B,
    output     [63:0] result,
    output            overflow
);

    assign result = A - B;

    // Positive overflow: A positive, B negative, result negative.
    // Negative overflow: A negative, B positive, result positive.
    assign overflow = (~A[63] & B[63] & result[63]) |
                       (A[63] & ~B[63] & ~result[63]);

endmodule
