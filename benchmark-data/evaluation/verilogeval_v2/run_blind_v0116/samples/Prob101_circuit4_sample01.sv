module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output q
);
    // From waveform: q = b | c
    assign q = b | c;
endmodule
