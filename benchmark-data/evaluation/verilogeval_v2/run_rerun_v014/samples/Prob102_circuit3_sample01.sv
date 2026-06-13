module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output q
);

    // From the waveform: q = (a | b) & (c | d)
    assign q = (a | b) & (c | d);

endmodule
