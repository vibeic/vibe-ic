module TopModule(
    input  x,
    input  y,
    output z
);
    // Waveform: z=1 exactly when x==y -> XNOR
    assign z = ~(x ^ y);
endmodule
