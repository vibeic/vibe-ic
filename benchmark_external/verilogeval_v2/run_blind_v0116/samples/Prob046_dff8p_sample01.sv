module TopModule (
    input        clk,
    input        reset,
    input  [7:0] d,
    output reg [7:0] q
);

    // Active-high synchronous reset to 0x34, negative-edge triggered.
    always @(negedge clk) begin
        if (reset)
            q <= 8'h34;
        else
            q <= d;
    end

endmodule
