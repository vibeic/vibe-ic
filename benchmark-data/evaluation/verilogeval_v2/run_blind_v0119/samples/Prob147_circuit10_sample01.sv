module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    // One flip-flop holding the carry of a serial full-adder.
    reg state_r;

    always @(posedge clk) begin
        // next carry = majority(state, a, b)
        state_r <= (state_r & a) | (state_r & b) | (a & b);
    end

    assign state = state_r;
    assign q     = state_r ^ a ^ b;  // combinational sum
endmodule
