module TopModule (
    input      clk,
    input      L,
    input      q_in,
    input      r_in,
    output reg Q = 1'b0
);
    always @(posedge clk)
        Q <= L ? r_in : q_in;
endmodule
