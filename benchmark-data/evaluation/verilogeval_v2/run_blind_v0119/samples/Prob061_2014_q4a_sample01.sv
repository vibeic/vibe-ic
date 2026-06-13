module TopModule (
    input        clk,
    input        w,
    input        R,
    input        E,
    input        L,
    output reg   Q
);
    initial Q = 1'b0;
    // L (load) has priority over E (shift enable); otherwise hold.
    always @(posedge clk)
        Q <= L ? R : (E ? w : Q);
endmodule
