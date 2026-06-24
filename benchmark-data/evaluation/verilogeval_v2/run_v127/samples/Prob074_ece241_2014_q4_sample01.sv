module TopModule (
    input  clk,
    input  x,
    output z
);

    // Three D flops, each fed by a gate of x and its own (possibly inverted)
    // output. All flops power up at 0.
    reg q_xor = 1'b0;  // XOR: 2nd input is this flop's output
    reg q_and = 1'b0;  // AND: 2nd input is this flop's complemented output
    reg q_or  = 1'b0;  // OR : 2nd input is this flop's complemented output

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;
        q_and <= x & ~q_and;
        q_or  <= x | ~q_or;
    end

    // z is the 3-input NOR of the three flop outputs.
    assign z = ~(q_xor | q_and | q_or);

endmodule
