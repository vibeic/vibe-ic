module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output q
);

    // From the waveform, q = b | c (a and d are don't-cares)
    assign q = b | c;

endmodule
