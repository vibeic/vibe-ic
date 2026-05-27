module TopModule (
    input        clk,
    input        ar,
    input        d,
    output reg   q = 1'b0
);
    // Positive-edge triggered DFF with active-high ASYNCHRONOUS reset (power-up initializer matches reset value).
    always @(posedge clk or posedge ar) begin
        if (ar)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule
