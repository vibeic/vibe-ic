module TopModule (
    input  clk,
    input  x,
    output z
);

    reg q_xor;   // XOR-gate flip-flop
    reg q_and;   // AND-gate flip-flop
    reg q_or;    // OR-gate flip-flop

    initial begin    // flops reset to 0 before the machine begins
        q_xor = 1'b0;
        q_and = 1'b0;
        q_or  = 1'b0;
    end

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;     // second XOR input = own output
        q_and <= x & ~q_and;    // second AND input = own complemented output
        q_or  <= x | ~q_or;     // second OR input = own complemented output
    end

    assign z = ~(q_xor | q_and | q_or);  // three-input NOR

endmodule
