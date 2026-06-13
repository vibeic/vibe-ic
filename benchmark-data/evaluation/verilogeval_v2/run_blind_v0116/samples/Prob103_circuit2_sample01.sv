module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output q
);
    // From waveform: q = XNOR of all four inputs (even parity)
    assign q = ~(a ^ b ^ c ^ d);
endmodule
