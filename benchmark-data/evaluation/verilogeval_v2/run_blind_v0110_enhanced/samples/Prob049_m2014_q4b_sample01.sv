module TopModule (
    input  clk,
    input  ar,
    input  d,
    output reg q = 1'b0
);
    // D flip-flop, posedge clk, asynchronous reset ar -> 0.
    always @(posedge clk or posedge ar) begin
        if (ar)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule
