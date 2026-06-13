module TopModule (
    input  clk,
    input  ar,
    input  d,
    output reg q
);

    // Positive-edge triggered D flip-flop with asynchronous reset
    always @(posedge clk or posedge ar) begin
        if (ar)
            q <= 1'b0;
        else
            q <= d;
    end

endmodule
