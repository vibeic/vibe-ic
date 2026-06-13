module TopModule (
    input  clk,
    input  a,
    output reg [2:0] q
);

    // From the waveform: when a=1, q is loaded to 4 each clock.
    // When a=0, q counts 0..6 (modulo 7).
    always @(posedge clk) begin
        if (a)
            q <= 3'd4;
        else if (q == 3'd6)
            q <= 3'd0;
        else
            q <= q + 3'd1;
    end

endmodule
