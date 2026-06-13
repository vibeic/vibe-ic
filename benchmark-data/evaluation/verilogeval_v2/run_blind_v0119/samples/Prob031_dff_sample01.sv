module TopModule (
    input      clk,
    input      d,
    output reg q = 0
);
    always @(posedge clk)
        q <= d;
endmodule
