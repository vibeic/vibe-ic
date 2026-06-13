module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // Full checkerboard alternating pattern => XOR parity of all four inputs.
    assign out = a ^ b ^ c ^ d;
endmodule
