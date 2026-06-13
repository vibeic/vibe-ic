module TopModule (
    input  clk,
    input  x,
    output z
);
    reg q_xor = 1'b0;   // XOR flip-flop output
    reg q_and = 1'b0;   // AND flip-flop output
    reg q_or  = 1'b0;   // OR  flip-flop output

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;     // XOR with its own output
        q_and <= x & ~q_and;    // AND with its complemented output
        q_or  <= x | ~q_or;     // OR  with its complemented output
    end

    // 3-input NOR of the three flip-flop outputs (Moore output)
    assign z = ~(q_xor | q_and | q_or);
endmodule
