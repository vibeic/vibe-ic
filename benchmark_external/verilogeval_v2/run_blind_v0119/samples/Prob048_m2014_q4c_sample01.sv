module TopModule (
    input        clk,
    input        d,
    input        r,
    output reg   q = 1'b0
);
    // Active-high SYNCHRONOUS reset to 0 (power-up initializer matches reset value).
    always @(posedge clk) begin
        if (r)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule
