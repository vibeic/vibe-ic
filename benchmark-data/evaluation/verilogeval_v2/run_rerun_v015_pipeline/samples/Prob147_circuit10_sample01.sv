module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg r_state;

    // next-state (one flip-flop):
    //   from state 0: go to 1 only when a&b
    //   from state 1: go to 0 only when a==0 && b==0
    always @(posedge clk)
        r_state <= r_state ? (a | b) : (a & b);

    assign state = r_state;
    // combinational output: q = a XOR b in state 0, a XNOR b in state 1
    assign q = a ^ b ^ r_state;
endmodule
