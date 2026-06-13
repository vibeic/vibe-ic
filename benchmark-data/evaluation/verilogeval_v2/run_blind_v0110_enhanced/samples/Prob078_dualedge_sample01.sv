module TopModule(
    input  clk,
    input  d,
    output q
);
    reg p, n;
    always @(posedge clk) p <= d;
    always @(negedge clk) n <= d;
    // When clk is high, the most recent capture was on the posedge (p);
    // when clk is low, the most recent capture was on the negedge (n).
    assign q = clk ? p : n;
endmodule
