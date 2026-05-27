module TopModule (
    input      clk,
    input      w,
    input      R,
    input      E,
    input      L,
    output reg Q
);
    initial Q = 1'b0;
    always @(posedge clk) begin
        if (L)
            Q <= R;       // load has priority
        else if (E)
            Q <= w;       // shift in from previous stage
        // else hold
    end
endmodule
