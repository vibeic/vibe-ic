module TopModule (
    input        clk,
    input        a,
    output reg [2:0] q = 3'b0
);
    always @(posedge clk) begin
        if (a)
            q <= 3'd4;
        else if (q == 3'd6)
            q <= 3'd0;
        else
            q <= q + 3'd1;
    end
endmodule
