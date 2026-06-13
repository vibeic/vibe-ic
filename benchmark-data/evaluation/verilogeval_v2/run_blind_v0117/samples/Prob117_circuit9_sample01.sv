module TopModule (
    input            clk,
    input            a,
    output reg [2:0] q
);
    initial q = 3'd0;  // reset-less registered output: deterministic init

    always @(posedge clk) begin
        if (a)
            q <= 3'd4;                 // load 4 when a is high
        else if (q == 3'd6)
            q <= 3'd0;                 // wrap 6 -> 0 (mod-7)
        else
            q <= q + 3'd1;
    end
endmodule
