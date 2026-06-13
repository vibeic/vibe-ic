module TopModule(
    input      clk,
    input      a,
    output reg q = 0
);
    // Waveform: q registers ~a each positive clock edge (no reset).
    always @(posedge clk) begin
        q <= ~a;
    end
endmodule
