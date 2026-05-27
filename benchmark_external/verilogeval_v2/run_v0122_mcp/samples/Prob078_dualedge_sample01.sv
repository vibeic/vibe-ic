module TopModule (
    input  clk,
    input  d,
    output q
);

    reg qp;   // captured on rising edge
    reg qn;   // captured on falling edge

    always @(posedge clk) qp <= d;
    always @(negedge clk) qn <= d;

    assign q = clk ? qp : qn;

endmodule
