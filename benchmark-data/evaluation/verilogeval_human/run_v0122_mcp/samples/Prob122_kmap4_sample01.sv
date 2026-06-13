module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);

    // K-map reduces to four-input parity.
    always @(*)
        out = a ^ b ^ c ^ d;

endmodule
