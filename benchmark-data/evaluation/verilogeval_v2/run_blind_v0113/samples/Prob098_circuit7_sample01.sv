module TopModule(
    input  clk,
    input  a,
    output q
);
    // Waveform: q takes the value of ~a, registered on the positive edge.
    reg q_reg = 1'b0;
    always @(posedge clk)
        q_reg <= ~a;
    assign q = q_reg;
endmodule
