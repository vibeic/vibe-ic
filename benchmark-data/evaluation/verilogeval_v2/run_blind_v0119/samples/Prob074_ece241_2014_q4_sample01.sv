module TopModule(
    input  clk,
    input  x,
    output z
);
    // Three D flip-flops, each initially reset to zero.
    reg ff_xor = 1'b0;   // D = x XOR ff_xor
    reg ff_and = 1'b0;   // D = x AND ~ff_and
    reg ff_or  = 1'b0;   // D = x OR  ~ff_or

    always @(posedge clk) begin
        ff_xor <= x ^ ff_xor;
        ff_and <= x & ~ff_and;
        ff_or  <= x | ~ff_or;
    end

    // Three-input NOR of the flip-flop outputs.
    assign z = ~(ff_xor | ff_and | ff_or);
endmodule
