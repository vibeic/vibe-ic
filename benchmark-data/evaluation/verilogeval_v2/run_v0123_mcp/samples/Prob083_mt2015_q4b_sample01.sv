module TopModule (
    input  x,
    input  y,
    output z
);
    // Waveform steady states: (0,0)->1 (1,0)->0 (0,1)->0 (1,1)->1  => XNOR
    assign z = ~(x ^ y);
endmodule
