module TopModule (
    input  clk,
    input  in,
    output reg out = 1'b0
);

    // DFF takes XOR of 'in' and current 'out'; positive edge, no reset.
    always @(posedge clk) begin
        out <= in ^ out;
    end

endmodule
