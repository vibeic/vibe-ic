module TopModule (
    input  clk,
    input  a,
    output q
);
    // Waveform: at each posedge clk, q takes the inverse of a sampled at the edge.
    reg q_reg;
    always @(posedge clk)
        q_reg <= ~a;
    assign q = q_reg;
endmodule
