module TopModule (
    input  clk,
    input  a,
    output reg q
);
    // Waveform: q registers the inverse of a on each posedge clk.
    always @(posedge clk)
        q <= ~a;
endmodule
