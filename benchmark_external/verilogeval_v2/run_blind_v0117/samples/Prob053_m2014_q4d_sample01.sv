module TopModule (
    input  clk,
    input  in,
    output reg out = 0
);
    always @(posedge clk) begin
        out <= in ^ out;
    end
endmodule
