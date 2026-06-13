module TopModule(
    input  clk,
    input  x,
    output z
);
    reg q0 = 1'b0;
    reg q1 = 1'b0;
    reg q2 = 1'b0;

    always @(posedge clk) begin
        q0 <= x ^ q0;
        q1 <= x & ~q1;
        q2 <= x | ~q2;
    end

    assign z = ~(q0 | q1 | q2);
endmodule
