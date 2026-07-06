module TopModule (
    input  clk,
    input  x,
    output z
);

    reg flop_xor, flop_and, flop_or;

    initial begin
        flop_xor = 1'b0;
        flop_and = 1'b0;
        flop_or  = 1'b0;
    end

    always @(posedge clk) begin
        flop_xor <= x ^ flop_xor;
        flop_and <= x & ~flop_and;
        flop_or  <= x | ~flop_or;
    end

    assign z = ~(flop_xor | flop_and | flop_or);

endmodule
