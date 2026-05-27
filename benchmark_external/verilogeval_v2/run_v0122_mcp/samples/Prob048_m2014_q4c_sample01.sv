module TopModule (
    input  clk,
    input  d,
    input  r,
    output reg q
);

    // Active-high synchronous reset to 0.
    always @(posedge clk) begin
        if (r)
            q <= 1'b0;
        else
            q <= d;
    end

endmodule
