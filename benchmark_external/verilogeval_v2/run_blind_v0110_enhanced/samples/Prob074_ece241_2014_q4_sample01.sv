module TopModule(
    input  clk,
    input  x,
    output z
);
    // Three D flip-flops, initially reset to 0
    reg qx = 1'b0;  // XOR-fed FF
    reg qa = 1'b0;  // AND-fed FF
    reg qo = 1'b0;  // OR-fed FF

    always @(posedge clk) begin
        qx <= x ^ qx;    // XOR, 2nd input = its own output
        qa <= x & ~qa;   // AND, 2nd input = complemented output
        qo <= x | ~qo;   // OR,  2nd input = complementary output
    end

    assign z = ~(qx | qa | qo); // three-input NOR
endmodule
