module TopModule(
    input  clk,
    input  d,
    output q
);
    reg p;   // captures d on rising edge
    reg n;   // captures d on falling edge

    always @(posedge clk) p <= d;
    always @(negedge clk) n <= d;

    // When clk is high the most recent edge was the rising one (p);
    // when clk is low the most recent edge was the falling one (n).
    assign q = clk ? p : n;
endmodule
