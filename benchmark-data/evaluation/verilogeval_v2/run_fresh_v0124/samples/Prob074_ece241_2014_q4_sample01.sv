module TopModule (
    input  clk,
    input  x,
    output z
);
    reg q_xor, q_and, q_or;

    // DFFs power up to 0 before the machine begins.
    initial begin
        q_xor = 1'b0;
        q_and = 1'b0;
        q_or  = 1'b0;
    end

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;        // XOR second input = its own FF output
        q_and <= x & ~q_and;       // AND second input = complemented FF output
        q_or  <= x | ~q_or;        // OR  second input = complemented FF output
    end

    assign z = ~(q_xor | q_and | q_or);
endmodule
