module TopModule (
    input  x,
    input  y,
    output z
);
    // Waveform truth table: (x,y)->z : 00->1, 10->0, 01->0, 11->1  => XNOR
    assign z = ~(x ^ y);
endmodule
