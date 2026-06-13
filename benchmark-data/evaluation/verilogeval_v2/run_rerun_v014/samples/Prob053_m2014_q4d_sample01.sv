module TopModule (
    input  clk,
    input  in,
    output reg out
);

    // D flip-flop fed by XOR(in, out); positive-edge triggered, no reset
    always @(posedge clk) begin
        out <= in ^ out;
    end

endmodule
