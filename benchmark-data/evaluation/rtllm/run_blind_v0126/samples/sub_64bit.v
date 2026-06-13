module sub_64bit (
    input  wire [63:0] A,
    input  wire [63:0] B,
    output wire [63:0] result,
    output wire        overflow
);

    assign result = A - B;

    // Signed overflow on subtraction (A - B):
    // - A positive, B negative, result negative  -> positive overflow
    // - A negative, B positive, result positive  -> negative overflow
    assign overflow = (~A[63] &  B[63] &  result[63]) |
                      ( A[63] & ~B[63] & ~result[63]);

endmodule
