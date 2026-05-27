module TopModule (
    input in,
    input [3:0] state,
    output reg [3:0] next_state,
    output out
);
    // one-hot: A=state[0], B=state[1], C=state[2], D=state[3]
    always @(*) begin
        next_state[0] = (state[0] & ~in) | (state[2] & ~in);          // ->A
        next_state[1] = (state[0] & in) | (state[1] & in) | (state[3] & in); // ->B
        next_state[2] = (state[1] & ~in) | (state[3] & ~in);          // ->C
        next_state[3] = (state[2] & in);                              // ->D
    end
    assign out = state[3];   // Moore output: 1 only in state D
endmodule
