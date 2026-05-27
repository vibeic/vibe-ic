module TopModule (
    input        clk,
    input        a,
    output reg [2:0] q = 0
);
    // From waveform: a=1 -> load 4; a=0 -> count 0..6 (mod 7)
    always @(posedge clk) begin
        if (a)
            q <= 3'd4;
        else if (q == 3'd6)
            q <= 3'd0;
        else
            q <= q + 3'd1;
    end
endmodule
