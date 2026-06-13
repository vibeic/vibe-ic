module TopModule (
    input  clk,
    input  in,
    output reg out = 1'b0
);
    always @(posedge clk) begin
        out <= in ^ out;
    end
endmodule
