module TopModule (
    input  clk,
    input  areset,
    input  x,
    output z
);
    // state 'seen' = a '1' has occurred in a previous cycle.
    // Copy bits up to & including first 1, invert thereafter.
    reg seen;

    always @(posedge clk or posedge areset) begin
        if (areset)
            seen <= 1'b0;
        else
            seen <= seen | x;
    end

    assign z = seen ? ~x : x;
endmodule
