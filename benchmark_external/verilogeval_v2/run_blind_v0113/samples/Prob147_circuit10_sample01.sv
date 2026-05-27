module TopModule(
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg state_r;

    // next_state = state ? (a|b) : (a&b)
    always @(posedge clk) begin
        state_r <= state_r ? (a | b) : (a & b);
    end

    assign state = state_r;
    // combinational output
    assign q = a ^ b ^ state_r;
endmodule
