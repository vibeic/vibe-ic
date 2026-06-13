module TopModule (
    input  clk,
    input  d,
    output q
);
    reg p;   // captured on rising edge
    reg n;   // captured on falling edge

    always @(posedge clk)
        p <= d;

    always @(negedge clk)
        n <= d;

    // select the most-recently-captured value based on clk level
    assign q = clk ? p : n;
endmodule
