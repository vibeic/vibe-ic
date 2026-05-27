module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);

    // Karnaugh map reduces to 4-input XOR (full checkerboard):
    //   out = 1 exactly when an odd number of {a,b,c,d} are 1.
    assign out = a ^ b ^ c ^ d;

endmodule
