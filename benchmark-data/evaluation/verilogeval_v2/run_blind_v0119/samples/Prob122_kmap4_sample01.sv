module TopModule(
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // K-map is a perfect checkerboard => out = a XOR b XOR c XOR d
    assign out = a ^ b ^ c ^ d;
endmodule
