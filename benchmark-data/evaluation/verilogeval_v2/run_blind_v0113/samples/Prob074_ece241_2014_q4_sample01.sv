module TopModule (
    input  clk,
    input  x,
    output z
);
    reg q_xor = 1'b0;
    reg q_and = 1'b0;
    reg q_or  = 1'b0;

    always @(posedge clk) begin
        q_xor <= x ^ q_xor;
        q_and <= x & ~q_and;
        q_or  <= x | ~q_or;
    end

    assign z = ~(q_xor | q_and | q_or);
endmodule
