module TopModule (
    input  clk,
    input  w,
    input  R,
    input  E,
    input  L,
    output reg Q
);

    // One stage of an n-bit shift register.
    // L (load) has priority: load R. Otherwise if E (enable) shift in w,
    // else hold.
    always @(posedge clk) begin
        if (L)
            Q <= R;
        else if (E)
            Q <= w;
        else
            Q <= Q;
    end

endmodule
