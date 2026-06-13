module TopModule(
    input      clk,
    input      a,
    output reg q = 1'b0
);
    // q registers ~a with one clock of delay (per waveform).
    always @(posedge clk)
        q <= ~a;
endmodule
