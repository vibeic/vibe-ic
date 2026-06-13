module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output q
);

    // From the waveform: q is high when an even number of inputs are high
    assign q = ~(a ^ b ^ c ^ d);

endmodule
