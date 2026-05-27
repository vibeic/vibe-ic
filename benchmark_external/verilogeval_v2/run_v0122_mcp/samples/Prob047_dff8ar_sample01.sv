module TopModule (
    input        clk,
    input        areset,
    input  [7:0] d,
    output reg [7:0] q
);

    // Active-high asynchronous reset to 0, posedge clk.
    always @(posedge clk or posedge areset) begin
        if (areset)
            q <= 8'h00;
        else
            q <= d;
    end

endmodule
