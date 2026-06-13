module TopModule (
    input  clk,
    input  d,
    output q
);

    reg qp, qn;

    always @(posedge clk)
        qp <= d;

    always @(negedge clk)
        qn <= d;

    assign q = clk ? qp : qn;

endmodule
