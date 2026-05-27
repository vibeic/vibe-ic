module TopModule (
    input clk,
    input x,
    output z
);
    // Three DFFs, initially reset to zero.
    reg q_xor = 1'b0;   // driven by XOR gate
    reg q_and = 1'b0;   // driven by AND gate
    reg q_or  = 1'b0;   // driven by OR gate

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;        // XOR: 2nd input = its own output
        q_and <= x & ~q_and;       // AND: 2nd input = complemented output
        q_or  <= x | ~q_or;        // OR : 2nd input = complemented output
    end

    assign z = ~(q_xor | q_and | q_or);  // 3-input NOR
endmodule
