module TopModule (
    input  clk,
    input  in,
    output out
);
    reg q;
    always @(posedge clk)
        q <= in ^ q;
    assign out = q;
endmodule
