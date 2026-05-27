module TopModule (
    input        clk,
    input        j,
    input        k,
    output reg   Q
);
    initial Q = 1'b0;
    // JK FF: 00 hold, 01 clear, 10 set, 11 toggle.
    always @(posedge clk)
        Q <= (j & ~Q) | (~k & Q);
endmodule
