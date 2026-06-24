// sub_64bit: 64-bit signed subtractor with overflow detection.
// result = A - B. Overflow when the operands have different signs and the
// result's sign differs from A's sign:
//   - positive overflow: A>=0, B<0, result<0
//   - negative overflow: A<0,  B>=0, result>=0
module sub_64bit (
    input  [63:0] A,
    input  [63:0] B,
    output [63:0] result,
    output        overflow
);

    assign result = A - B;

    assign overflow = (~A[63] &  B[63] &  result[63]) |
                      ( A[63] & ~B[63] & ~result[63]);

endmodule
