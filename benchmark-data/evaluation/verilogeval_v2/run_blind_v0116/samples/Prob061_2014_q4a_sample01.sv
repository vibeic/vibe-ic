module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output reg Q = 1'b0
);

    // L (load) has priority over E (shift-enable); otherwise hold.
    always @(posedge clk) begin
        if (L)
            Q <= R;
        else if (E)
            Q <= w;
        else
            Q <= Q;
    end

endmodule
