module TopModule (
    input  clk,
    input  x,
    output z
);

    reg q1, q2, q3; // outputs of XOR-DFF, AND-DFF, OR-DFF

    always @(posedge clk) begin
        q1 <= x ^ q1;   // XOR with own output
        q2 <= x & ~q2;  // AND with complemented own output
        q3 <= x | ~q3;  // OR with complemented own output
    end

    assign z = ~(q1 | q2 | q3); // 3-input NOR

endmodule
