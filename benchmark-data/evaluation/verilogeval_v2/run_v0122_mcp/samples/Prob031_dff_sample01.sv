module TopModule(
    input  clk,
    input  d,
    output reg q
);
    initial q = 1'b0;
    always @(posedge clk) begin
        q <= d;
    end
endmodule
