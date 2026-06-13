module TopModule (
    input            clk,
    input            a,
    output reg [2:0] q = 3'b0
);
    // a=1 -> load 4; a=0 -> count up mod 7 (6 wraps to 0)
    always @(posedge clk) begin
        if (a)
            q <= 3'd4;
        else
            q <= (q == 3'd6) ? 3'd0 : (q + 3'd1);
    end
endmodule
